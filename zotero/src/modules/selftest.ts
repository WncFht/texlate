import {
  ApiError,
  type FileInfo,
  NetworkError,
  type SelftestResult,
  type SelftestStep,
} from "../contracts";
import { config } from "../../package.json";
import { extractArxivId } from "./arxivId";
import { attachArtifacts, getTexlateMark } from "./attach";
import { createClient } from "./client";
import { FILES_GRACE_MS } from "./flow";
import { computeMenuState } from "./menu";
import { loadPrefs } from "./prefs";
import { pollTask } from "./poller";
import { fieldText, sleep } from "../utils/misc";

/**
 * selftest.ts — e2e chain verification for dev-verify (RDP eval). Same modules
 * as production; per-step attributable evidence in SelftestResult. NEVER throws.
 *
 * The module ships in the production xpi by design — dev-verify validates the
 * shipping artifact — but stays inert unless explicitly armed: run() refuses
 * with a dev-gate failure unless the undocumented pref
 * `${config.prefsPrefix}.devSelftest === true` exists on the global branch
 * (dev-verify writes it via RDP in phase_prefs; no prefs.js default, no UI).
 */

/** Assertion failure inside a step — message lands verbatim in detail. */
class StepError extends Error {
  override readonly name = "StepError";
}
/** Sentinel unwinding the pipeline after a recorded step failure. */
class Halt extends Error {}

/**
 * Step-local error formatter — richer than utils/misc.errText: prefixes
 * `unreachable:` for NetworkError and `Name:` for Error subclasses whose
 * name isn't a bare "Error", so step details stay attributable.
 */
function stepErrText(e: unknown): string {
  if (e instanceof StepError || e instanceof ApiError) return e.message;
  if (e instanceof NetworkError) return `unreachable: ${e.message}`;
  if (e instanceof Error) return `${e.name}: ${e.message}`;
  return String(e);
}

/** Attribute an extracted id to doi/url/archiveID/extra (substring probe). */
function idSource(item: Zotero.Item, id: string): string {
  const needle = id.toLowerCase();
  for (const name of ["DOI", "url", "archiveID", "extra"]) {
    if (fieldText(item, name).toLowerCase().includes(needle)) {
      return name === "DOI" ? "doi" : name;
    }
  }
  return "unknown";
}

type Out<T> = [T, string];
async function step<T>(
  steps: SelftestStep[],
  name: string,
  fn: () => Out<T> | Promise<Out<T>>,
): Promise<T> {
  try {
    const [v, d] = await fn();
    steps.push({ name, ok: true, detail: d });
    return v;
  } catch (e) {
    steps.push({ name, ok: false, detail: stepErrText(e) });
    throw new Halt();
  }
}

async function run(itemID: number, negative: boolean): Promise<SelftestResult> {
  const steps: SelftestStep[] = [];
  let taskId: string | undefined;
  if (Zotero.Prefs.get(`${config.prefsPrefix}.devSelftest`, true) !== true) {
    steps.push({
      name: "dev-gate",
      ok: false,
      detail: `${config.prefsPrefix}.devSelftest pref not enabled (global branch)`,
    });
    return { ok: false, itemID, steps, error: "dev-gate" };
  }
  try {
    const item = await step(steps, "resolve-item", () => {
      const it = Zotero.Items.get(itemID);
      if (!it) throw new StepError(`item ${itemID} not found`);
      if (!it.isRegularItem())
        throw new StepError(`item ${itemID} not regular (${it.itemType})`);
      const t = fieldText(it, "title").slice(0, 40);
      return [it, `itemID=${itemID} type=${it.itemType} title=${t}`];
    });
    const prefs = await step(steps, "prefs", () => {
      const p = loadPrefs();
      const d = `serverUrl=${p.serverUrl} apiKey=${p.apiKey ? "set" : "empty"} kinds=[${p.attachKinds}]`;
      return [p, d];
    });
    const client = await step(steps, "health", async () => {
      const c = createClient(prefs);
      const h = await c.health();
      if (!h.ok) throw new StepError("unhealthy");
      return [c, `ok version=${h.version ?? "unknown"}`];
    });
    const arxivId = await step(steps, "extract", (): Out<string> => {
      const id = extractArxivId(item);
      if (negative) {
        if (id !== null) throw new StepError(`expected no arXiv id, got ${id}`);
        return ["", "no arXiv id (expected)"];
      }
      if (id === null) throw new StepError("no arXiv id extractable");
      return [id, `arxivId=${id} source=${idSource(item, id)}`];
    });
    await step(steps, "already-marked", () => {
      const mark = getTexlateMark(item);
      if (negative && mark !== null)
        throw new StepError(`expected mark=none, got ${mark}`);
      return [mark, `mark=${mark ?? "none"}`];
    });
    if (negative) return { ok: true, itemID, steps };
    const created = await step(steps, "create", async () => {
      const a = await client.createTask(arxivId);
      return [a.task_id, `taskId=${a.task_id} status=${a.status}`];
    });
    taskId = created;
    const finalSnap = await step(steps, "poll", async () => {
      const t0 = Date.now();
      let polls = 0;
      const snap = await pollTask(client, created, {
        intervalMs: prefs.pollIntervalMs,
        timeoutMs: prefs.pollTimeoutMs,
        onProgress: () => {
          polls += 1;
        },
      });
      const d = `status=${snap.status} progress=${snap.progress} elapsed=${Date.now() - t0}ms polls=${polls}`;
      return [snap, d];
    });
    await step(steps, "files", async () => {
      // Mirror of flow.awaitFiles (private there — export it and this step
      // can call it directly): terminal status races /api/files visibility,
      // so retry while the map is empty, or while zh_pdf is absent despite
      // zh.pdf being requested, until the grace deadline.
      const fetchArts = async (): Promise<Record<string, FileInfo>> => {
        try {
          return await client.listFiles(created);
        } catch {
          return {};
        }
      };
      const needZh = prefs.attachKinds.includes("zh.pdf");
      const deadline = Date.now() + FILES_GRACE_MS;
      let arts = await fetchArts();
      while (
        (Object.keys(arts).length === 0 || (needZh && !("zh_pdf" in arts))) &&
        Date.now() < deadline
      ) {
        await sleep(2000); // flow.FILES_GRACE_INTERVAL_MS (private there)
        arts = await fetchArts();
      }
      if (Object.keys(arts).length === 0) {
        const e = finalSnap.error?.message ?? "-";
        throw new StepError(
          `empty artifacts (status=${finalSnap.status} ${e})`,
        );
      }
      const per = Object.entries(arts)
        .map(
          ([k, f]) =>
            `${k}=${f.bytes}B sha256=${f.sha256?.slice(0, 12) ?? "-"}`,
        )
        .join(" ");
      return [arts, `kinds=[${Object.keys(arts).join(",")}] ${per}`];
    });
    await step(steps, "download+attach", async () => {
      const r = await attachArtifacts(item, client, created, {
        kinds: prefs.attachKinds,
      });
      const att = r.attached
        .map((a) => `${a.kind}:${a.itemID}/${a.bytes}B`)
        .join(",");
      const fail = r.failed.map((f) => `${f.kind}:${f.reason}`).join(",");
      const d = `attached=[${att}] missing=[${r.missing.join(",")}] failed=[${fail}]`;
      // All-empty = every kind dedup-skipped (PDF already on the item) or
      // none requested — the attachments-verify step confirms presence.
      if (
        r.attached.length === 0 &&
        (r.missing.length > 0 || r.failed.length > 0)
      ) {
        throw new StepError(`none attached ${d}`);
      }
      return [r, d];
    });
    await step(steps, "mark", () => {
      const fresh = Zotero.Items.get(itemID);
      const mark = fresh ? getTexlateMark(fresh) : null;
      if (mark !== created)
        throw new StepError(`mark=${mark ?? "absent"} expected ${created}`);
      return [mark, `extra mark verified: texlate: ${mark}`];
    });
    await step(steps, "attachments-verify", () => {
      const fresh = Zotero.Items.get(itemID);
      if (!fresh) throw new StepError(`item ${itemID} vanished`);
      const titles = fresh
        .getAttachments()
        .map((id) => Zotero.Items.get(id))
        .map((a) => (a ? fieldText(a, "title") || a.getDisplayTitle() : "?"));
      const mine = titles.filter((t) => t.startsWith("TeXlate"));
      if (mine.length === 0)
        throw new StepError(`no texlate attachment (titles=[${titles}])`);
      return [mine, `attachment count=${mine.length} titles=[${mine}]`];
    });
    await step(steps, "reader-url", () => {
      const url = client.readerUrl(created);
      const want = `${prefs.serverUrl}/#/reader/${created}`;
      if (url !== want) throw new StepError(`reader=${url} expected=${want}`);
      return [url, `reader=${url}`];
    });
    return { ok: true, itemID, steps, taskId };
  } catch (e) {
    if (!(e instanceof Halt)) {
      steps.push({ name: "unexpected", ok: false, detail: stepErrText(e) });
    }
    const bad = steps.find((s) => !s.ok);
    return { ok: false, itemID, steps, taskId, error: bad?.name ?? "?" };
  }
}

/** `Zotero.texlate.selftest(itemID)` — full chain against the live server. */
export function selftest(itemID: number): Promise<SelftestResult> {
  return run(itemID, false);
}

/** Negative path: assert extract→null + mark→none (menu-grey precondition). */
export function selftestNonArxiv(itemID: number): Promise<SelftestResult> {
  return run(itemID, true);
}

/** Wire onto the addon instance (Zotero.texlate IS addon) — call in onStartup. */
export function installSelftest(): void {
  Object.assign(addon, { selftest, selftestNonArxiv });
  Object.assign(addon.api, { selftest, selftestNonArxiv, computeMenuState });
}
