// Default preference values for the texlate addon.
// SYNC: these defaults are duplicated as fallbacks in
// src/modules/prefs.ts (prefsFrom) — Zotero loads this file pre-bundle, so it
// cannot import the shared TS constants. Any default change must be applied
// in both places.
pref("serverUrl", "http://127.0.0.1:8765");
pref("apiKey", "");
pref("attachZhPdf", true);
pref("attachEnPdf", false);
pref("batchDelayMs", 1000);
pref("pollIntervalMs", 2000);
pref("pollTimeoutMs", 10800000);
pref("autoStart", true);
pref("bootstrapDataDir", "");
