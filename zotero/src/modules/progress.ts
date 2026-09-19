/**
 * progress.ts — ProgressWindow plumbing for the translate flow.
 *
 * Every call is best-effort: a UI failure must never kill a flow, so all
 * helpers swallow toolkit exceptions and return null/void. Callers resolve
 * ftl text themselves except setPhase, which owns the snapshot→line
 * rendering ("{phase} {progress}%").
 */
import { phaseKey } from "./poller";
import { t } from "../utils/locale";
import type { TaskSnapshot } from "../contracts";
import type { ProgressWindowHelper } from "zotero-plugin-toolkit";

export type Progress = ProgressWindowHelper | null;

export function createProgress(text: string): Progress {
  try {
    const pw = new ztoolkit.ProgressWindow("TeXlate");
    pw.createLine({ text, progress: 0 });
    pw.show(-1);
    return pw;
  } catch {
    return null;
  }
}

/** Render a task snapshot as "{phase} {progress}%" on line 0. */
export function setPhase(pw: Progress, snap: TaskSnapshot): void {
  try {
    pw?.changeLine({
      idx: 0,
      text: `${t(`phase-${phaseKey(snap)}`)} ${Math.round(snap.progress)}%`,
      progress: snap.progress,
    });
  } catch {
    /* best-effort UI */
  }
}

export function appendLine(pw: Progress, text: string): void {
  try {
    pw?.createLine({ type: "default", text });
  } catch {
    /* best-effort UI */
  }
}

export function endProgress(
  pw: Progress,
  type: "success" | "fail",
  text: string,
): void {
  try {
    pw?.changeLine({ idx: 0, type, text, progress: 100 });
    pw?.startCloseTimer(8000);
  } catch {
    /* best-effort UI */
  }
}

/** One-shot popup for results with no persistent progress window. */
export function flashProgress(type: "success" | "fail", text: string): void {
  try {
    const pw = new ztoolkit.ProgressWindow("TeXlate");
    pw.createLine({ type, text });
    pw.show(6000);
  } catch {
    /* best-effort UI */
  }
}
