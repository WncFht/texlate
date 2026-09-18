/**
 * prefs.ts — TexlatePrefs loading + declarative settings dialog.
 * Path (a): zotero-plugin-toolkit SettingsDialogHelper (pdf-translate
 * AllowedSettingsMethods pattern) — zero custom xhtml for the dialog.
 * apiKey is a plaintext Zotero pref (README-documented).
 *
 * ftl keys needed in addon.ftl (locale agent fills; getString prefixes
 * `texlate-` — `t()` casts until i10n.d.ts regenerates):
 *   prefs-dialog-title  = TeXlate Settings
 *   prefs-server-url    = Server URL
 *   prefs-api-key       = API key (optional)
 *   prefs-attach-zh     = Attach Chinese PDF (zh.pdf)
 *   prefs-attach-en     = Attach English PDF (en.pdf)
 *   prefs-attach-dual   = Attach bilingual PDF (dual.pdf)
 *   prefs-batch-delay   = Delay between batch items (ms)
 *   prefs-poll-interval = Poll interval (ms)
 *   prefs-poll-timeout  = Poll timeout (ms)
 *   prefs-status        = Connection
 *   prefs-check         = Check connection
 *   prefs-checking      = Checking…
 *   prefs-health-ok     = Connected — server version { $version }
 *   prefs-health-bad    = Unexpected response — is a texlate server at this URL?
 *   prefs-health-down   = Cannot reach server — is `uvx texlate web` running?
 *   prefs-save          = Save
 *   prefs-cancel        = Cancel
 * plus in preferences.ftl (xhtml pane): prefs-open-settings = Open TeXlate Settings
 */
import { config, homepage } from "../../package.json";
import { SettingsDialogHelper } from "zotero-plugin-toolkit";
import type { FluentMessageId } from "../../typings/i10n";
import type { TexlatePrefs } from "../contracts";
import { NetworkError } from "../contracts";
import { createClient } from "./client";
import { getString } from "../utils/locale";
import { getPref, setPref } from "../utils/prefs";

type PrefKey = keyof _ZoteroTypes.Prefs["PluginPrefsMap"];

const STATUS_ID = "texlate-health-status";
const INPUT_STYLE = { minWidth: "28em" } as const;

function t(id: string, args?: Record<string, unknown>): string {
  const key = id as FluentMessageId;
  return args === undefined ? getString(key) : getString(key, { args });
}

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
  return s || "http://127.0.0.1:8765";
}

/** Build TexlatePrefs from a raw pref map (Zotero.Prefs or dialog values). */
function prefsFrom(raw: Record<string, unknown>): TexlatePrefs {
  const attachKinds: string[] = [];
  if (bool(raw.attachZhPdf, true)) attachKinds.push("zh.pdf");
  if (bool(raw.attachEnPdf, false)) attachKinds.push("en.pdf");
  if (bool(raw.attachDualPdf, false)) attachKinds.push("dual.pdf");
  return {
    serverUrl: normalizeServerUrl(raw.serverUrl),
    apiKey: typeof raw.apiKey === "string" ? raw.apiKey.trim() : "",
    attachKinds,
    batchDelayMs: num(raw.batchDelayMs, 1000),
    pollIntervalMs: num(raw.pollIntervalMs, 2000, 1),
    pollTimeoutMs: num(raw.pollTimeoutMs, 10800000, 1),
  };
}

export function loadPrefs(): TexlatePrefs {
  return prefsFrom({
    serverUrl: getPref("serverUrl"),
    apiKey: getPref("apiKey"),
    attachZhPdf: getPref("attachZhPdf"),
    attachEnPdf: getPref("attachEnPdf"),
    attachDualPdf: getPref("attachDualPdf"),
    batchDelayMs: getPref("batchDelayMs"),
    pollIntervalMs: getPref("pollIntervalMs"),
    pollTimeoutMs: getPref("pollTimeoutMs"),
  });
}

async function checkConnection(dialog: SettingsDialogHelper): Promise<void> {
  const el = dialog.window?.document.getElementById(STATUS_ID);
  const say = (msg: string) => {
    if (el) el.textContent = msg;
  };
  say(t("prefs-checking"));
  const prefs = prefsFrom(dialog.getAllSettingsData());
  try {
    const res = await createClient(prefs).health();
    say(
      res.ok
        ? t("prefs-health-ok", { version: res.version ?? "unknown" })
        : t("prefs-health-bad"),
    );
  } catch (e) {
    say(
      e instanceof NetworkError
        ? t("prefs-health-down")
        : t("prefs-health-bad"),
    );
  }
}

export function openPrefsDialog(): void {
  addon.data.dialog?.window?.close();
  const dialog = new SettingsDialogHelper()
    .setSettingHandlers(
      (key: string) => getPref(key as PrefKey),
      (key: string, value: unknown) => {
        setPref(key as PrefKey, value as never);
      },
    )
    .addSetting(t("prefs-server-url"), "serverUrl", {
      tag: "input",
      attributes: { type: "text" },
      styles: INPUT_STYLE,
    })
    .addSetting(t("prefs-api-key"), "apiKey", {
      tag: "input",
      attributes: { type: "password" },
      styles: INPUT_STYLE,
    })
    .addSetting(
      t("prefs-attach-zh"),
      "attachZhPdf",
      { tag: "input", attributes: { type: "checkbox" } },
      { valueType: "boolean" },
    )
    .addSetting(
      t("prefs-attach-en"),
      "attachEnPdf",
      { tag: "input", attributes: { type: "checkbox" } },
      { valueType: "boolean" },
    )
    .addSetting(
      t("prefs-attach-dual"),
      "attachDualPdf",
      { tag: "input", attributes: { type: "checkbox" } },
      { valueType: "boolean" },
    )
    .addSetting(
      t("prefs-batch-delay"),
      "batchDelayMs",
      { tag: "input", attributes: { type: "number", min: 0, step: 100 } },
      { valueType: "number" },
    )
    .addSetting(
      t("prefs-poll-interval"),
      "pollIntervalMs",
      { tag: "input", attributes: { type: "number", min: 1, step: 100 } },
      { valueType: "number" },
    )
    .addSetting(
      t("prefs-poll-timeout"),
      "pollTimeoutMs",
      { tag: "input", attributes: { type: "number", min: 1, step: 60000 } },
      { valueType: "number" },
    )
    .addStaticRow(t("prefs-status"), {
      tag: "span",
      namespace: "html",
      id: STATUS_ID,
      styles: { whiteSpace: "pre-wrap" },
    })
    .addButton(t("prefs-check"), "check", {
      noClose: true,
      callback: () => void checkConnection(dialog),
    })
    .addAutoSaveButton(t("prefs-save"), "save")
    .addButton(t("prefs-cancel"), "cancel")
    .open(t("prefs-dialog-title"));
  addon.data.dialog = dialog;
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
  // preferences.xhtml's button calls Zotero.<instance>.api.openPrefsDialog().
  Object.assign(addon.api, { openPrefsDialog });
}
