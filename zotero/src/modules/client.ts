/**
 * client.ts — HTTP client for the texlate server REST API.
 *
 * Transport: `Zotero.HTTP.request` (XHR). The plugin sandbox has no
 * AbortController or ReadableStream, so fetch-based timeout/cancel isn't
 * viable; Zotero.HTTP is the ecosystem standard (zotero-pdf-translate,
 * pdf2zh) and handles proxy/cookie plumbing for us. `successCodes: false`
 * makes every response resolve so all status mapping lives in one place:
 * non-2xx → ApiError, status 0 (refused/DNS/reset) → NetworkError, and the
 * XHR timeout rejection → TimeoutError.
 */
import {
  ApiError,
  isRetryableStatus,
  NetworkError,
  TimeoutError,
  type AcceptedResponse,
  type ChannelProbeReport,
  type ChannelsView,
  type FileInfo,
  type FilesResponse,
  type HealthResponse,
  type TaskSnapshot,
  type TexlateClient,
  type TexlatePrefs,
} from "../contracts";

const JSON_TIMEOUT_MS = 15_000;
// Generous: remote servers on slow links need >30s for 20MB+ PDFs.
const DOWNLOAD_TIMEOUT_MS = 120_000;

// Rejections from Zotero.HTTP are untyped (TimeoutException,
// BrowserOfflineException, CancelledException, SecurityException, raw XHR
// setup throws). Only TimeoutException maps to our TimeoutError; the rest
// are transport-level → NetworkError.
function toTransportError(e: unknown): Error {
  const TimeoutCtor = (
    Zotero.HTTP as unknown as { TimeoutException?: new (ms?: number) => Error }
  ).TimeoutException;
  const msg = e instanceof Error ? e.message : String(e);
  if ((TimeoutCtor && e instanceof TimeoutCtor) || /\btimed out\b/i.test(msg)) {
    return new TimeoutError(msg);
  }
  return new NetworkError(msg);
}

function decodeBinary(data: unknown): string {
  try {
    return data ? new TextDecoder().decode(data as ArrayBuffer) : "";
  } catch {
    return "";
  }
}

export function createClient(prefs: TexlatePrefs): TexlateClient {
  const base = prefs.serverUrl.replace(/\/+$/, "");

  function headers(): Record<string, string> {
    // Plain JSON Accept — sending text/event-stream on /api/task upgrades
    // the response to a never-terminating SSE stream.
    const h: Record<string, string> = { Accept: "application/json" };
    if (prefs.apiKey) h["X-Texlate-Key"] = prefs.apiKey;
    return h;
  }

  async function request<T>(
    method: string,
    path: string,
    opts: { body?: string; binary?: boolean; timeoutMs?: number } = {},
  ): Promise<T> {
    let xhr: XMLHttpRequest;
    try {
      xhr = await Zotero.HTTP.request(method, `${base}${path}`, {
        headers: {
          ...headers(),
          ...(opts.body ? { "Content-Type": "application/json" } : {}),
        },
        body: opts.body,
        responseType: opts.binary ? "arraybuffer" : "",
        timeout: opts.timeoutMs ?? JSON_TIMEOUT_MS,
        successCodes: false,
        errorDelayMax: 0, // no transport-layer retry; poller owns cadence
      });
    } catch (e) {
      throw toTransportError(e);
    }
    if (xhr.status === 0) {
      throw new NetworkError(`connection failed: ${method} ${path}`);
    }
    // Decode the body only when it's needed: non-2xx error detail or the
    // JSON parse path. A successful binary download skips the (potentially
    // large) ArrayBuffer→string decode entirely.
    if (xhr.status < 200 || xhr.status >= 300) {
      throw new ApiError(
        xhr.status,
        opts.binary ? decodeBinary(xhr.response) : (xhr.responseText ?? ""),
      );
    }
    if (opts.binary) return xhr.response as T;
    const raw = xhr.responseText ?? "";
    try {
      return JSON.parse(raw) as T;
    } catch {
      throw new ApiError(xhr.status, raw);
    }
  }

  // The dedup-active set counts `interrupted` (and other retryable terminals
  // can surface the same way) — adopting one dead-ends polling an
  // empty-artifacts corpse. Resurrect via /retry first.
  async function adoptExisting(taskId: string): Promise<AcceptedResponse> {
    const snap = await request<TaskSnapshot>("GET", `/api/task/${taskId}`);
    if (isRetryableStatus(snap.status)) {
      return await request<AcceptedResponse>(
        "POST",
        `/api/task/${taskId}/retry`,
        { body: "{}" },
      );
    }
    return {
      task_id: taskId,
      status: snap.status,
      events_url: "",
      reused: true,
    };
  }

  return {
    health: () => request<HealthResponse>("GET", "/api/health"),

    createTask: async (arxivId) => {
      try {
        return await request<AcceptedResponse>(
          "POST",
          // raw interpolate — old-format ids carry "/" (hep-th/9901001) and
          // the route is {arxiv_id:path}; server normalizes/validates.
          `/api/arxiv/${arxivId}/translate`,
          { body: "{}" },
        );
      } catch (e) {
        // 409 duplicate_active carries the live task_id — adopt it and poll
        // rather than failing (server-side dedup is the designed path;
        // dev-server's curl check does the same).
        if (
          e instanceof ApiError &&
          e.status === 409 &&
          typeof e.payload?.task_id === "string"
        ) {
          return adoptExisting(e.payload.task_id);
        }
        throw e;
      }
    },

    getTask: (taskId) => request<TaskSnapshot>("GET", `/api/task/${taskId}`),

    listFiles: async (taskId) =>
      // `artifacts` could be absent/null on a contract-bending response —
      // an empty map degrades to "missing" instead of a TypeError.
      (await request<FilesResponse>("GET", `/api/files/${taskId}`)).artifacts ??
      {},

    async downloadFile(taskId, urlKind, destPath, opts) {
      const buf = await request<ArrayBuffer>(
        "GET",
        `/api/files/${taskId}/${urlKind}`,
        { binary: true, timeoutMs: DOWNLOAD_TIMEOUT_MS },
      );
      const bytes = new Uint8Array(buf);
      if (
        opts?.expectPdf &&
        urlKind.endsWith(".pdf") &&
        !(
          bytes[0] === 0x25 &&
          bytes[1] === 0x50 &&
          bytes[2] === 0x44 &&
          bytes[3] === 0x46
        )
      ) {
        throw new ApiError(200, `${urlKind}: expected %PDF magic`);
      }
      await IOUtils.write(destPath, bytes);
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      const sha256 = Array.from(new Uint8Array(digest), (b) =>
        b.toString(16).padStart(2, "0"),
      ).join("");
      return { bytes: bytes.length, sha256 };
    },

    readerUrl: (taskId) => `${base}/#/reader/${taskId}`,

    listChannels: () => request<ChannelsView>("GET", "/api/channels"),

    // Probe runs real model chats server-side (stage2, ≤8 models) — far
    // slower than a plain JSON round-trip; borrow the download budget.
    probeChannel: (id) =>
      request<ChannelProbeReport>("POST", "/api/channels/probe", {
        body: JSON.stringify({ id }),
        timeoutMs: DOWNLOAD_TIMEOUT_MS,
      }),
  };
}
