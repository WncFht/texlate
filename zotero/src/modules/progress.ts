/**
 * progress.ts — one shared ProgressWindow per batch, one ItemProgress row
 * per item (the Zotero translator-save convention: headline = addon name,
 * each row = item title + arc progress + terminal icon). A single-item
 * translate is just a batch of one.
 *
 * Every call is best-effort: a UI failure must never kill a flow, so all
 * helpers swallow toolkit exceptions and return null/void. `title` stays in
 * the row text across phase rewrites so a row never loses item identity.
 */
import { phaseKey } from "./poller";
import { t } from "../utils/locale";
import type { FlowResult, TaskSnapshot } from "../contracts";
import type { ProgressWindowHelper } from "zotero-plugin-toolkit";

export interface Batch {
  pw: ProgressWindowHelper | null;
  count: number;
}

/** One item's row inside the shared window. */
export interface ItemLine {
  batch: Batch;
  idx: number;
  title: string;
}

const TITLE_MAX = 60;

export function shortTitle(raw: string): string {
  const flat = raw.replace(/\s+/g, " ").trim();
  return flat.length > TITLE_MAX ? `${flat.slice(0, TITLE_MAX - 1)}…` : flat;
}

export function createBatch(): Batch {
  try {
    const pw = new ztoolkit.ProgressWindow("TeXlate");
    pw.show(-1); // persistent — closed by closeBatch once all items end
    return { pw, count: 0 };
  } catch {
    return { pw: null, count: 0 };
  }
}

export function openLine(batch: Batch, title: string): ItemLine {
  try {
    batch.pw?.createLine({ text: title, progress: 0 });
  } catch {
    /* best-effort UI */
  }
  const idx = batch.count++;
  return { batch, idx, title };
}

/** Render a task snapshot as "{title} — {phase} {progress}%" on this item's row. */
export function setPhase(line: ItemLine, snap: TaskSnapshot): void {
  try {
    line.batch.pw?.changeLine({
      idx: line.idx,
      text: `${line.title} — ${t(`phase-${phaseKey(snap)}`)} ${Math.round(
        snap.progress,
      )}%`,
      progress: snap.progress,
    });
  } catch {
    /* best-effort UI */
  }
}

/** Terminal write for one item's row — icon flips to tick/cross. */
export function endLine(
  line: ItemLine,
  type: "success" | "fail",
  text: string,
): void {
  try {
    line.batch.pw?.changeLine({
      idx: line.idx,
      type,
      text: `${line.title} — ${text}`,
      progress: type === "success" ? 100 : undefined,
    });
  } catch {
    /* best-effort UI */
  }
}

/**
 * All items ended — append a summary row for multi-item batches, then arm
 * the close timer (longer when something failed so the user can read it).
 */
export function closeBatch(batch: Batch, results: FlowResult[]): void {
  try {
    if (!batch.pw) return;
    const ok = results.filter((r) => r.ok).length;
    if (results.length > 1) {
      batch.pw.createLine({
        type: ok === results.length ? "success" : "fail",
        text: t("flow-batch-summary", {
          ok,
          failed: results.length - ok,
          total: results.length,
        }),
      });
    }
    batch.pw.startCloseTimer(ok === results.length ? 8000 : 15000);
  } catch {
    /* best-effort UI */
  }
}
