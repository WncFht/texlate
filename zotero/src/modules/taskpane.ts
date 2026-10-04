/**
 * taskpane.ts — "TeXlate" collapsible section in the right item pane: the
 * live task list with real progress bars.
 *
 * This is the primary progress surface. The floating ProgressWindow is a
 * `dependent=yes` child window that macOS z-orders under the main window —
 * clicking Zotero buries it — so live progress lives here instead and the
 * window degrades to a completion toast (progress.ts).
 *
 * The section is process-global, not per-item: it shows every in-flight
 * and recently-finished task regardless of which item is selected, so
 * onItemChange only re-asserts enabled. Registration happens once at
 * startup (hooks.ts); pluginID makes Zotero drop the section on
 * disable/remove, and each mounted section body is tracked so updates
 * repaint every open window's pane.
 */

import { config } from "../../package.json";
import { t } from "../utils/locale";

const HTML_NS = "http://www.w3.org/1999/xhtml";
const ICON = `chrome://${config.addonRef}/content/icons/menu-icon.svg`;
/** Oldest terminal rows beyond this cap are dropped — the list stays short. */
const MAX_TERMINAL = 15;

interface PaneTask {
  itemID: number;
  title: string;
  text: string;
  /** 0..100 determinate; null = indeterminate (bootstrap/status phases). */
  progress: number | null;
  state: "running" | "success" | "fail";
}

interface MountedPane {
  doc: Document;
  body: HTMLDivElement;
  setSummary: (summary: string) => void;
}

const tasks = new Map<number, PaneTask>(); // insertion order = display order
const mounted = new Set<MountedPane>();

// createElementNS resolves to plain Element in this dom lib — assert the
// concrete HTMLElement types the XHTML names imply.
function renderTask(doc: Document, task: PaneTask): HTMLElement {
  const row = doc.createElementNS(HTML_NS, "div") as HTMLDivElement;
  row.style.cssText =
    "display:flex;flex-direction:column;gap:2px;padding:5px 2px;" +
    "border-bottom:1px solid var(--fill-quinary, rgba(0,0,0,.08));";

  const title = doc.createElementNS(HTML_NS, "div") as HTMLDivElement;
  title.textContent = task.title;
  title.style.cssText =
    "font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";

  const status = doc.createElementNS(HTML_NS, "div") as HTMLDivElement;
  const mark =
    task.state === "success" ? "✓ " : task.state === "fail" ? "✗ " : "";
  status.textContent = mark + task.text;
  status.style.cssText =
    "font-size:.93em;color:" +
    (task.state === "fail"
      ? "var(--accent-red, #c62828)"
      : "var(--fill-secondary)");

  row.append(title, status);
  if (task.state === "running") {
    const bar = doc.createElementNS(HTML_NS, "progress") as HTMLProgressElement;
    bar.max = 100;
    bar.style.width = "100%";
    if (task.progress !== null) bar.value = task.progress;
    row.appendChild(bar);
  }
  return row;
}

function renderPane(pane: MountedPane): void {
  const { doc, body } = pane;
  body.replaceChildren();
  if (tasks.size === 0) {
    const empty = doc.createElementNS(HTML_NS, "div") as HTMLDivElement;
    empty.textContent = t("taskpane-empty");
    empty.style.cssText = "padding:4px 2px;color:var(--fill-secondary);";
    body.appendChild(empty);
  } else {
    for (const task of tasks.values()) body.appendChild(renderTask(doc, task));
  }
  let running = 0;
  for (const task of tasks.values()) if (task.state === "running") running++;
  pane.setSummary(
    running > 0 ? t("taskpane-running-count", { count: running }) : "",
  );
}

function renderAll(): void {
  for (const pane of mounted) renderPane(pane);
}

/** Open (or reopen, on retry) the task's row. */
export function openTask(itemID: number, title: string): void {
  tasks.delete(itemID); // re-set moves a retried row to the end
  tasks.set(itemID, {
    itemID,
    title,
    text: "",
    progress: null,
    state: "running",
  });
  renderAll();
}

/** Update the row's status text; null progress = indeterminate bar. */
export function updateTask(
  itemID: number,
  text: string,
  progress: number | null,
): void {
  const task = tasks.get(itemID);
  if (!task) return;
  task.text = text;
  task.progress = progress;
  renderAll();
}

/** Flip the row to a terminal state and enforce the terminal-row cap. */
export function endTask(itemID: number, ok: boolean, text: string): void {
  const task = tasks.get(itemID);
  if (!task) return;
  task.text = text;
  task.state = ok ? "success" : "fail";
  let terminal = 0;
  for (const t2 of tasks.values()) if (t2.state !== "running") terminal++;
  if (terminal > MAX_TERMINAL) {
    const overflow = terminal - MAX_TERMINAL;
    let dropped = 0;
    for (const t2 of tasks.values()) {
      if (dropped >= overflow) break;
      if (t2.state !== "running") {
        tasks.delete(t2.itemID);
        dropped++;
      }
    }
  }
  renderAll();
}

/**
 * Register the section once for the whole plugin (not per window).
 * l10n convention: header label needs a `.label` attribute message, the
 * sidenav rail button needs `.tooltiptext` — bare values land in
 * textContent, which XUL toolbarbutton/collapsible-section don't render.
 */
export function registerTaskPane(): void {
  try {
    Zotero.ItemPaneManager.registerSection({
      paneID: "texlate-tasks",
      pluginID: config.addonID,
      sidenav: {
        l10nID: `${config.addonRef}-taskpane-sidenav`,
        icon: ICON,
      },
      header: {
        l10nID: `${config.addonRef}-taskpane`,
        icon: ICON,
      },
      onInit: ({ doc, body, setEnabled, setSectionSummary }) => {
        setEnabled(true);
        const pane: MountedPane = {
          doc,
          body,
          setSummary: (s) => void setSectionSummary(s),
        };
        mounted.add(pane);
        renderPane(pane);
      },
      onDestroy: ({ body }) => {
        for (const pane of mounted) {
          if (pane.body === body) mounted.delete(pane);
        }
      },
      // Required by runtime optionTypeDefinition in both Zotero 7 and 10
      // (the zotero-types d.ts wrongly marks it optional — omitting it
      // throws "Option must have onRender" and registration silently
      // fails, which is exactly how this pane went missing on first ship).
      // The body element persists across renders; repaint current state.
      onRender: ({ body }) => {
        for (const pane of mounted) {
          if (pane.body === body) renderPane(pane);
        }
      },
      // Task list is global, not item-scoped — always stay enabled.
      onItemChange: ({ setEnabled }) => {
        setEnabled(true);
      },
    });
  } catch (e) {
    ztoolkit.log("taskpane: registerSection failed", e);
  }
}
