/**
 * flow.ts — production translate flow for one item (menu-triggered).
 *
 * translateItem NEVER throws: expected failures and unexpected exceptions are
 * both encoded in FlowResult.error as a STABLE MACHINE CODE (kebab-case,
 * optional ": detail" suffix — e.g. "server-unreachable", "task-fault: …").
 * Localized text goes to the ProgressWindow; selftest/dev-verify match on
 * the code prefix.
 *
 * ftl keys used (locale agent — all under the addonRef prefix):
 *   flow-start {id} · phase-<status|stage> for the 11 statuses (queued,
 *   fetching, parsing, translating, compiling, done, partial, fault,
 *   cancelled, interrupted, needs_auth) · flow-error-not-regular ·
 *   flow-error-no-arxiv-id · flow-error-inflight · flow-already-translated ·
 *   flow-error-server-down {serverUrl} (hint "uvx texlate web") ·
 *   flow-error-server-unhealthy · flow-error-invalid-arxiv-id {detail} ·
 *   flow-error-api {status, detail} · flow-error-poll-timeout ·
 *   flow-error-task-fault {detail} · flow-error-task-cancelled ·
 *   flow-error-task-interrupted · flow-error-unexpected {message} ·
 *   flow-needs-auth {serverUrl} · flow-done · flow-partial-warn ·
 *   flow-attach-failed {detail} · flow-batch-summary {ok, failed, total}
 */

import {
  ApiError,
  NetworkError,
  TimeoutError,
  type AttachResult,
  type FileInfo,
  type FlowResult,
  type TaskSnapshot,
  type TerminalStatus,
  type TexlateClient,
  type TexlatePrefs,
} from "../contracts";
import { extractArxivId } from "./arxivId";
import { createClient } from "./client";
import { pollTask } from "./poller";
import { attachArtifacts, getTexlateMark, setTexlateMark } from "./attach";
import { loadPrefs } from "./prefs";
import {
  appendLine,
  createProgress,
  endProgress,
  flashProgress,
  setPhase,
  type Progress,
} from "./progress";
import { t } from "../utils/locale";
import { errText, fieldText, sleep } from "../utils/misc";

/** Post-terminal retry window for /api/files visibility (design §二 竞态宽限). */
export const FILES_GRACE_MS = 20000;
export const FILES_GRACE_INTERVAL_MS = 2000;

const inflight = new Set<number>();

function fail(
  pw: Progress,
  itemID: number,
  error: string,
  ftlKey: string,
  opts: {
    args?: Record<string, unknown>;
    taskId?: string;
    status?: TerminalStatus;
  } = {},
): FlowResult {
  endProgress(pw, "fail", t(ftlKey, opts.args));
  const { args: _a, ...rest } = opts;
  return { itemID, ok: false, error, ...rest };
}

/**
 * Terminal ≠ artifacts visible (server "done" races /api/files — pdf2zh
 * COMPLETED_FILE_GRACE_MS). Retry while the map is empty, or while zh_pdf is
 * absent despite zh.pdf being requested. Returns the last-seen map.
 */
export async function awaitFiles(
  client: TexlateClient,
  taskId: string,
  kinds: string[],
): Promise<Record<string, FileInfo>> {
  const needZh = kinds.includes("zh.pdf");
  const deadline = Date.now() + FILES_GRACE_MS;
  let artifacts: Record<string, FileInfo>;
  for (;;) {
    try {
      artifacts = await client.listFiles(taskId);
    } catch {
      artifacts = {};
    }
    // Match the FileInfo.url tail like attach.ts rather than spelling the
    // zh.pdf ↔ zh_pdf db-kind map a second way (server builds the url as
    // /api/files/{id}/{urlKind}).
    const hasZh = Object.values(artifacts).some((f) =>
      f.url.endsWith("/zh.pdf"),
    );
    const ok = Object.keys(artifacts).length > 0 && (!needZh || hasZh);
    if (ok || Date.now() >= deadline) return artifacts;
    await sleep(FILES_GRACE_INTERVAL_MS);
  }
}

/** Terminal dispatch (design §二 状态映射). `snap.status` is terminal per pollTask. */
async function finish(
  pw: Progress,
  item: Zotero.Item,
  client: TexlateClient,
  taskId: string,
  snap: TaskSnapshot,
  prefs: TexlatePrefs,
): Promise<FlowResult> {
  const itemID = item.id;
  const status = snap.status as TerminalStatus;
  const at = { taskId, status };
  switch (status) {
    case "done":
    case "partial": {
      const artifacts = await awaitFiles(client, taskId, prefs.attachKinds);
      const attach: AttachResult =
        Object.keys(artifacts).length === 0
          ? { attached: [], missing: [...prefs.attachKinds], failed: [] }
          : await attachArtifacts(item, client, taskId, {
              kinds: prefs.attachKinds,
              titleHint: fieldText(item, "title") || undefined,
            });
      // attached=0 is a failure only when something was actually wanted:
      // missing kinds or failed downloads. All-empty means every kind was
      // dedup-skipped (PDF already on the item) or nothing was requested.
      if (
        attach.attached.length === 0 &&
        (attach.missing.length > 0 || attach.failed.length > 0)
      ) {
        const reasons = [
          ...attach.missing.map((k) => `missing ${k}`),
          ...attach.failed.map((f) => `${f.kind}: ${f.reason}`),
        ].join("; ");
        return fail(
          pw,
          itemID,
          `attach-failed: ${reasons}`,
          "flow-attach-failed",
          { args: { detail: reasons }, ...at },
        );
      }
      if (status === "partial") appendLine(pw, t("flow-partial-warn"));
      // attachArtifacts owns the mark when it runs; when it was skipped
      // (empty artifacts) or nothing was requested, write it here so
      // "Open in Reader" still works.
      if (getTexlateMark(item) !== taskId) await setTexlateMark(item, taskId);
      endProgress(pw, "success", t("flow-done"));
      return { itemID, ok: true, status, taskId, attach };
    }
    case "fault": {
      const detail = snap.error?.detail ?? snap.error?.message ?? snap.message;
      return fail(
        pw,
        itemID,
        `task-fault: ${detail}`,
        "flow-error-task-fault",
        { args: { detail }, ...at },
      );
    }
    case "needs_auth": {
      try {
        Zotero.launchURL(`${prefs.serverUrl}/#/settings`);
      } catch {
        /* launch is best-effort */
      }
      return fail(pw, itemID, "needs-auth", "flow-needs-auth", {
        args: { serverUrl: prefs.serverUrl },
        ...at,
      });
    }
    default:
      return fail(
        pw,
        itemID,
        `task-${status}`,
        `flow-error-task-${status}`,
        at,
      );
  }
}

async function run(item: Zotero.Item): Promise<FlowResult> {
  const itemID = item.id;
  const prefs = loadPrefs();
  const client = createClient(prefs);

  try {
    if (!item.isRegularItem()) {
      flashProgress("fail", t("flow-error-not-regular"));
      return { itemID, ok: false, error: "not-regular-item" };
    }
  } catch {
    /* fall through — odd item still gets an arXiv-id shot */
  }
  const mark = getTexlateMark(item);
  if (mark) {
    flashProgress("success", t("flow-already-translated"));
    return { itemID, ok: true, taskId: mark };
  }
  const arxivId = extractArxivId(item);
  if (!arxivId) {
    flashProgress("fail", t("flow-error-no-arxiv-id"));
    return { itemID, ok: false, error: "no-arxiv-id" };
  }

  const pw = createProgress(t("flow-start", { id: arxivId }));
  let taskId: string | undefined;
  try {
    const health = await client.health();
    if (!health.ok)
      return fail(
        pw,
        itemID,
        "server-unhealthy",
        "flow-error-server-unhealthy",
      );
    const accepted = await client.createTask(arxivId);
    taskId = accepted.task_id;
    const snap = await pollTask(client, accepted.task_id, {
      intervalMs: prefs.pollIntervalMs,
      timeoutMs: prefs.pollTimeoutMs,
      onProgress: (s) => setPhase(pw, s),
    });
    return await finish(pw, item, client, accepted.task_id, snap, prefs);
  } catch (e) {
    const x = { taskId };
    if (e instanceof NetworkError)
      return fail(pw, itemID, "server-unreachable", "flow-error-server-down", {
        args: { serverUrl: prefs.serverUrl },
        ...x,
      });
    if (e instanceof TimeoutError)
      return fail(pw, itemID, "poll-timeout", "flow-error-poll-timeout", x);
    if (e instanceof ApiError && e.status === 400 && taskId === undefined)
      return fail(
        pw,
        itemID,
        `invalid-arxiv-id: ${e.detail}`,
        "flow-error-invalid-arxiv-id",
        { args: { detail: e.detail }, ...x },
      );
    if (e instanceof ApiError)
      return fail(
        pw,
        itemID,
        `api-error-${e.status}: ${e.detail}`,
        "flow-error-api",
        { args: { status: e.status, detail: e.detail }, ...x },
      );
    return fail(
      pw,
      itemID,
      `unexpected: ${errText(e)}`,
      "flow-error-unexpected",
      { args: { message: errText(e) }, ...x },
    );
  }
}

// ---------------------------------------------------------------- exports

export async function translateItem(item: Zotero.Item): Promise<FlowResult> {
  const itemID = item.id;
  if (inflight.has(itemID)) {
    flashProgress("fail", t("flow-error-inflight"));
    return { itemID, ok: false, error: "already-inflight" };
  }
  inflight.add(itemID);
  try {
    return await run(item);
  } catch (e) {
    const m = errText(e);
    flashProgress("fail", t("flow-error-unexpected", { message: m }));
    return { itemID, ok: false, error: `unexpected: ${m}` };
  } finally {
    inflight.delete(itemID);
  }
}

/** Sequential batch: batchDelayMs between items, never after the last. */
export async function translateItems(
  items: Zotero.Item[],
): Promise<FlowResult[]> {
  const { batchDelayMs } = loadPrefs();
  const results: FlowResult[] = [];
  for (let i = 0; i < items.length; i++) {
    results.push(await translateItem(items[i]));
    if (i < items.length - 1) await sleep(batchDelayMs);
  }
  const ok = results.filter((r) => r.ok).length;
  flashProgress(
    ok === results.length ? "success" : "fail",
    t("flow-batch-summary", {
      ok,
      failed: results.length - ok,
      total: results.length,
    }),
  );
  return results;
}

/** Launch the SPA reader for an already-translated item; false when unmarked. */
export function openInReader(item: Zotero.Item): boolean {
  const taskId = getTexlateMark(item);
  if (!taskId) return false;
  try {
    Zotero.launchURL(createClient(loadPrefs()).readerUrl(taskId));
    return true;
  } catch (e) {
    ztoolkit.log("openInReader launchURL failed:", e);
    return false;
  }
}
