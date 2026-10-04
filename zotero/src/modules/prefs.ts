/**
 * prefs.ts — TexlatePrefs loading + the inline settings pane.
 *
 * The pane (addon/content/preferences.xhtml, loaded into Zotero's own
 * settings window by PreferencePanes.register) hosts the form directly —
 * no dialog: initPrefsPane hydrates each control from Zotero.Prefs and
 * writes back on `change`, so edits apply immediately. apiKey is a
 * plaintext Zotero pref (README-documented).
 *
 * The check/start buttons act on the CURRENT field values, not saved
 * prefs — a user can type a URL and probe it before blurring the field.
 *
 * ftl: field/button labels live in preferences.ftl (DOM l10n inside the
 * xhtml); runtime status strings live in addon.ftl for t() —
 *   prefs-checking · prefs-health-ok {version} · prefs-health-bad ·
 *   prefs-health-down · flow-error-bootstrap {detail}
 */
import { config, homepage } from "../../package.json";
import type { TexlatePrefs } from "../contracts";
import { NetworkError } from "../contracts";
import { createClient } from "./client";
import { ensureServer } from "./bootstrap";
import { t } from "../utils/locale";
import { getPref, setPref } from "../utils/prefs";

type PrefKey = keyof _ZoteroTypes.Prefs["PluginPrefsMap"];

const STATUS_ID = "texlate-health-status";
const BUTTON_IDS = { check: "texlate-check", start: "texlate-start" } as const;

/**
 * SYNC: these defaults are duplicated as literals in addon/prefs.js —
 * Zotero loads prefs.js pre-bundle so it cannot import TS constants.
 * test/prefs.test.ts is the drift gate.
 */
const DEFAULTS = {
  serverUrl: "http://127.0.0.1:8765",
  apiKey: "",
  attachZhPdf: true,
  attachEnPdf: false,
  batchDelayMs: 1000,
  pollIntervalMs: 2000,
  pollTimeoutMs: 10800000,
  autoStart: true,
  bootstrapDataDir: "",
} as const;

type FieldKind = "text" | "number" | "checkbox";

/** pref key → control kind; element id is `texlate-${key}`. */
const FIELDS: ReadonlyArray<readonly [keyof typeof DEFAULTS, FieldKind]> = [
  ["serverUrl", "text"],
  ["apiKey", "text"],
  ["attachZhPdf", "checkbox"],
  ["attachEnPdf", "checkbox"],
  ["batchDelayMs", "number"],
  ["pollIntervalMs", "number"],
  ["pollTimeoutMs", "number"],
  ["autoStart", "checkbox"],
];

function num(v: unknown, fallback: number, min = 0): number {
  const n = Number(v);
  return Number.isFinite(n) && n >= min ? n : fallback;
}

function bool(v: unknown, fallback: boolean): boolean {
  if (typeof v === "boolean") return v;
  if (v === "true") return true;
  if (v === "false") return false;
  return fallback;
}

/** Trim + strip trailing slashes; empty falls back to local default. */
function normalizeServerUrl(v: unknown): string {
  const s = (typeof v === "string" ? v.trim() : "").replace(/\/+$/, "");
  return s || DEFAULTS.serverUrl;
}

/** Build TexlatePrefs from a raw pref map (Zotero.Prefs or live fields). */
function prefsFrom(raw: Record<string, unknown>): TexlatePrefs {
  const attachKinds: string[] = [];
  if (bool(raw.attachZhPdf, DEFAULTS.attachZhPdf)) attachKinds.push("zh.pdf");
  if (bool(raw.attachEnPdf, DEFAULTS.attachEnPdf)) attachKinds.push("en.pdf");
  return {
    serverUrl: normalizeServerUrl(raw.serverUrl),
    apiKey:
      typeof raw.apiKey === "string" ? raw.apiKey.trim() : DEFAULTS.apiKey,
    attachKinds,
    batchDelayMs: num(raw.batchDelayMs, DEFAULTS.batchDelayMs),
    pollIntervalMs: num(raw.pollIntervalMs, DEFAULTS.pollIntervalMs, 1),
    pollTimeoutMs: num(raw.pollTimeoutMs, DEFAULTS.pollTimeoutMs, 1),
    autoStart: bool(raw.autoStart, DEFAULTS.autoStart),
    bootstrapDataDir:
      typeof raw.bootstrapDataDir === "string"
        ? raw.bootstrapDataDir.trim()
        : DEFAULTS.bootstrapDataDir,
  };
}

export function loadPrefs(): TexlatePrefs {
  return prefsFrom({
    serverUrl: getPref("serverUrl"),
    apiKey: getPref("apiKey"),
    attachZhPdf: getPref("attachZhPdf"),
    attachEnPdf: getPref("attachEnPdf"),
    batchDelayMs: getPref("batchDelayMs"),
    pollIntervalMs: getPref("pollIntervalMs"),
    pollTimeoutMs: getPref("pollTimeoutMs"),
    autoStart: getPref("autoStart"),
    bootstrapDataDir: getPref("bootstrapDataDir"),
  });
}

// ---------------------------------------------------------------- inline pane

function fieldId(key: string): string {
  return `texlate-${key}`;
}

function fieldValue(el: Element, kind: FieldKind): unknown {
  if (kind === "checkbox") return (el as HTMLInputElement).checked;
  const v = (el as HTMLInputElement).value;
  if (kind === "number") {
    const n = Number(v);
    return Number.isFinite(n) && v !== "" ? n : undefined;
  }
  return v;
}

function writeField(
  el: Element,
  key: keyof typeof DEFAULTS,
  kind: FieldKind,
): void {
  const v = getPref(key as PrefKey);
  if (kind === "checkbox") {
    (el as HTMLInputElement).checked = bool(v, DEFAULTS[key] as boolean);
  } else {
    (el as HTMLInputElement).value = String(v ?? DEFAULTS[key]);
  }
}

/** Read live control values (unsaved edits included) into TexlatePrefs. */
function panePrefs(doc: Document): TexlatePrefs {
  const raw: Record<string, unknown> = {};
  for (const [key, kind] of FIELDS) {
    const el = doc.getElementById(fieldId(key));
    if (el) raw[key] = fieldValue(el, kind);
  }
  return prefsFrom(raw);
}

function say(doc: Document, msg: string): void {
  const el = doc.getElementById(STATUS_ID);
  if (el) el.textContent = msg;
}

async function checkConnection(doc: Document): Promise<void> {
  say(doc, t("prefs-checking"));
  try {
    const res = await createClient(panePrefs(doc)).health();
    say(
      doc,
      res.ok
        ? t("prefs-health-ok", { version: res.version ?? "unknown" })
        : t("prefs-health-bad"),
    );
  } catch (e) {
    say(
      doc,
      e instanceof NetworkError
        ? t("prefs-health-down")
        : t("prefs-health-bad"),
    );
  }
}

async function startServer(doc: Document): Promise<void> {
  const prefs = panePrefs(doc);
  try {
    const client = createClient(prefs);
    await ensureServer(prefs, (msg) => say(doc, msg));
    const res = await client.health();
    say(
      doc,
      res.ok
        ? t("prefs-health-ok", { version: res.version ?? "unknown" })
        : t("prefs-health-bad"),
    );
  } catch (e) {
    say(
      doc,
      t("flow-error-bootstrap", {
        detail: e instanceof Error ? e.message : String(e),
      }),
    );
  }
}

/**
 * preferences.xhtml groupbox onload entry: hydrate controls from prefs,
 * write back on `change` (auto-save), wire the two action buttons.
 */
export function initPrefsPane(doc: Document): void {
  for (const [key, kind] of FIELDS) {
    const el = doc.getElementById(fieldId(key));
    if (!el) continue;
    writeField(el, key, kind);
    el.addEventListener("change", () => {
      const v = fieldValue(el, kind);
      if (v !== undefined) setPref(key as PrefKey, v as never);
    });
  }
  doc
    .getElementById(BUTTON_IDS.check)
    ?.addEventListener("click", () => void checkConnection(doc));
  doc
    .getElementById(BUTTON_IDS.start)
    ?.addEventListener("click", () => void startServer(doc));
}

export function registerPrefsPane(): void {
  void Zotero.PreferencePanes.register({
    pluginID: config.addonID,
    src: rootURI + "content/preferences.xhtml",
    label: t("prefs-title"),
    image: `chrome://${config.addonRef}/content/icons/favicon.png`,
    helpURL: homepage,
  }).catch((e: unknown) => {
    ztoolkit.log("PreferencePanes.register failed:", e);
  });
}
