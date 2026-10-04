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
 *   phase-<status|stage> for the 11 statuses (queued,
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
  closeBatch,
  createBatch,
  endLine,
  openLine,
  setPhase,
  shortTitle,
  type Batch,
  type ItemLine,
} from "./progress";
import { t } from "../utils/locale";
import { errText, fieldText, sleep } from "../utils/misc";

/** Post-terminal retry window for /api/files visibility (design §二 竞态宽限). */
export const FILES_GRACE_MS = 20000;
export const FILES_GRACE_INTERVAL_MS = 2000;

const inflight = new Set<number>();

function fail(
  line: ItemLine,
  itemID: number,
  error: string,
  ftlKey: string,
  opts: {
    args?: Record<string, unknown>;
    taskId?: string;
    status?: TerminalStatus;
  } = {},
): FlowResult {
  endLine(line, "fail", t(ftlKey, opts.args));
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
  line: ItemLine,
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
          line,
          itemID,
          `attach-failed: ${reasons}`,
          "flow-attach-failed",
          { args: { detail: reasons }, ...at },
        );
      }
      // attachArtifacts owns the mark when it runs; when it was skipped
      // (empty artifacts) or nothing was requested, write it here so
      // "Open in Reader" still works.
      if (getTexlateMark(item) !== taskId) await setTexlateMark(item, taskId);
      endLine(
        line,
        "success",
        status === "partial" ? t("flow-partial-warn") : t("flow-done"),
      );
      return { itemID, ok: true, status, taskId, attach };
    }
    case "fault": {
      const detail = snap.error?.message ?? snap.message;
      return fail(
        line,
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
      return fail(line, itemID, "needs-auth", "flow-needs-auth", {
        args: { serverUrl: prefs.serverUrl },
        ...at,
      });
    }
    default:
      return fail(
        line,
        itemID,
        `task-${status}`,
        `flow-error-task-${status}`,
        at,
      );
  }
}

async function run(item: Zotero.Item, batch: Batch): Promise<FlowResult> {
  const itemID = item.id;
  const prefs = loadPrefs();
  const client = createClient(prefs);
  // Row opens before any check so early exits (untranslatable, already
  // translated, no arXiv id) still leave a visible row in the batch window.
  const title =
    shortTitle(fieldText(item, "title")) ||
    extractArxivId(item) ||
    `#${itemID}`;
  const line = openLine(batch, title);

  try {
    if (!item.isRegularItem()) {
      return fail(line, itemID, "not-regular-item", "flow-error-not-regular");
    }
  } catch {
    /* fall through — odd item still gets an arXiv-id shot */
  }
  const mark = getTexlateMark(item);
  if (mark) {
    endLine(line, "success", t("flow-already-translated"));
    return { itemID, ok: true, taskId: mark };
  }
  const arxivId = extractArxivId(item);
  if (!arxivId) {
    return fail(line, itemID, "no-arxiv-id", "flow-error-no-arxiv-id");
  }

  let taskId: string | undefined;
  try {
    const health = await client.health();
    if (!health.ok)
      return fail(
        line,
        itemID,
        "server-unhealthy",
        "flow-error-server-unhealthy",
      );
    const accepted = await client.createTask(arxivId);
    taskId = accepted.task_id;
    const snap = await pollTask(client, accepted.task_id, {
      intervalMs: prefs.pollIntervalMs,
      timeoutMs: prefs.pollTimeoutMs,
      onProgress: (s) => setPhase(line, s),
    });
    return await finish(line, item, client, accepted.task_id, snap, prefs);
  } catch (e) {
    const x = { taskId };
    if (e instanceof NetworkError)
      return fail(
        line,
        itemID,
        "server-unreachable",
        "flow-error-server-down",
        {
          args: { serverUrl: prefs.serverUrl },
          ...x,
        },
      );
    if (e instanceof TimeoutError)
      return fail(line, itemID, "poll-timeout", "flow-error-poll-timeout", x);
    if (e instanceof ApiError && e.status === 400 && taskId === undefined)
      return fail(
        line,
        itemID,
        `invalid-arxiv-id: ${e.detail}`,
        "flow-error-invalid-arxiv-id",
        { args: { detail: e.detail }, ...x },
      );
    if (e instanceof ApiError)
      return fail(
        line,
        itemID,
        `api-error-${e.status}: ${e.detail}`,
        "flow-error-api",
        { args: { status: e.status, detail: e.detail }, ...x },
      );
    return fail(
      line,
      itemID,
      `unexpected: ${errText(e)}`,
      "flow-error-unexpected",
      { args: { message: errText(e) }, ...x },
    );
  }
}

// ---------------------------------------------------------------- exports

/**
 * Translate one item, writing its row into `batch` (an ad-hoc single-item
 * batch is created and closed when omitted — keeps the API self-contained).
 */
export async function translateItem(
  item: Zotero.Item,
  batch?: Batch,
): Promise<FlowResult> {
  const itemID = item.id;
  const own = batch ?? createBatch();
  let result: FlowResult;
  if (inflight.has(itemID)) {
    const line = openLine(
      own,
      shortTitle(fieldText(item, "title")) ||
        extractArxivId(item) ||
        `#${itemID}`,
    );
    endLine(line, "fail", t("flow-error-inflight"));
    result = { itemID, ok: false, error: "already-inflight" };
  } else {
    inflight.add(itemID);
    try {
      result = await run(item, own);
    } catch (e) {
      const m = errText(e);
      // run() already wrote a row for every reachable failure; this catch is
      // for throws before the row existed (pref/field plumbing) — add one.
      const line = openLine(own, `#${itemID}`);
      endLine(line, "fail", t("flow-error-unexpected", { message: m }));
      result = { itemID, ok: false, error: `unexpected: ${m}` };
    } finally {
      inflight.delete(itemID);
    }
  }
  if (!batch) closeBatch(own, [result]);
  return result;
}

/** Sequential batch: one shared window, batchDelayMs between items. */
export async function translateItems(
  items: Zotero.Item[],
): Promise<FlowResult[]> {
  const { batchDelayMs } = loadPrefs();
  const batch = createBatch();
  const results: FlowResult[] = [];
  for (let i = 0; i < items.length; i++) {
    results.push(await translateItem(items[i], batch));
    if (i < items.length - 1) await sleep(batchDelayMs);
  }
  closeBatch(batch, results);
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
