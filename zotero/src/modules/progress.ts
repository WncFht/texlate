/**
 * progress.ts — per-item progress plumbing between flow.ts and the UI.
 *
 * Live progress renders into the item-pane task list (taskpane.ts) — the
 * floating ProgressWindow is `dependent=yes` and buries under the main
 * window on macOS, so it only survives as a completion toast: `pw` is
 * created lazily on the first terminal line, collect one row per item,
 * and closeBatch shows it with an auto-close timer.
 *
 * Every call is best-effort: a UI failure must never kill a flow, so all
 * helpers swallow toolkit exceptions and return null/void.
 */
import { phaseKey } from "./poller";
import { endTask, openTask, updateTask } from "./taskpane";
import { t } from "../utils/locale";
import type { FlowResult, TaskSnapshot } from "../contracts";
import type { ProgressWindowHelper } from "zotero-plugin-toolkit";

export interface Batch {
  /** Lazily created on the first endLine — null until a toast is needed. */
  pw: ProgressWindowHelper | null;
}

/** One item's row: the pane row keyed by itemID + this batch's toast. */
export interface ItemLine {
  batch: Batch;
  itemID: number;
  title: string;
}

const TITLE_MAX = 60;

export function shortTitle(raw: string): string {
  const flat = raw.replace(/\s+/g, " ").trim();
  return flat.length > TITLE_MAX ? `${flat.slice(0, TITLE_MAX - 1)}…` : flat;
}

export function createBatch(): Batch {
  return { pw: null };
}

export function openLine(batch: Batch, itemID: number, title: string): ItemLine {
  try {
    openTask(itemID, title);
  } catch {
    /* best-effort UI */
  }
  return { batch, itemID, title };
}

/** "{phase} {progress}%" on the item's pane row + determinate bar. */
export function setPhase(line: ItemLine, snap: TaskSnapshot): void {
  try {
    const pct = Math.max(0, Math.min(100, Math.round(snap.progress)));
    updateTask(line.itemID, `${t(`phase-${phaseKey(snap)}`)} ${pct}%`, pct);
  } catch {
    /* best-effort UI */
  }
}

/** Free-text status on the pane row — bootstrap phases (indeterminate). */
export function setLineStatus(line: ItemLine, text: string): void {
  try {
    updateTask(line.itemID, text, null);
  } catch {
    /* best-effort UI */
  }
}

/**
 * Terminal write: pane row flips to ✓/✗, and the batch toast collects a
 * line (creating the ProgressWindow on first use — shown by closeBatch).
 */
export function endLine(
  line: ItemLine,
  type: "success" | "fail",
  text: string,
): void {
  try {
    endTask(line.itemID, type === "success", text);
  } catch {
    /* best-effort UI */
  }
  try {
    const pw = (line.batch.pw ??= new ztoolkit.ProgressWindow("TeXlate"));
    pw.createLine({
      type,
      text: `${line.title} — ${text}`,
      progress: type === "success" ? 100 : undefined,
    });
  } catch {
    /* best-effort UI */
  }
}

/**
 * All items ended — append a summary row for multi-item batches, then show
 * the toast with an auto-close timer (longer when something failed).
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
    batch.pw.show(ok === results.length ? 8000 : 15000);
  } catch {
    /* best-effort UI */
  }
}
