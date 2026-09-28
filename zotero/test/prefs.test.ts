import { assert } from "chai";
import { config } from "../package.json";
import type { TexlatePrefs } from "../src/contracts";
import { loadPrefs } from "../src/modules/prefs";

/**
 * addon/prefs.js ⇆ prefs.ts prefsFrom fallback parity.
 * Zotero loads prefs.js pre-bundle so the defaults are duplicated by hand
 * (SYNC comments in both files); this spec is the drift gate.
 * The TS side is exercised for real: stubbing Zotero.Prefs.get to return
 * undefined makes loadPrefs() take every fallback, equivalent to
 * prefsFrom({}) — which is not exported.
 */

// pref("key", <literal>) — literals are string/number/boolean, all valid JSON
const PREF_RX = /pref\("(\w+)",\s*([^;]+?)\s*\);/g;

/** Projection from a pref() key to where its default lands in TexlatePrefs. */
const PREF_TO_FIELD: Record<string, (p: TexlatePrefs) => unknown> = {
  serverUrl: (p) => p.serverUrl,
  apiKey: (p) => p.apiKey,
  attachZhPdf: (p) => p.attachKinds.includes("zh.pdf"),
  attachEnPdf: (p) => p.attachKinds.includes("en.pdf"),
  attachDualPdf: (p) => p.attachKinds.includes("dual.pdf"),
  batchDelayMs: (p) => p.batchDelayMs,
  pollIntervalMs: (p) => p.pollIntervalMs,
  pollTimeoutMs: (p) => p.pollTimeoutMs,
};

async function readPrefsJs(): Promise<Record<string, unknown>> {
  const uri = await Zotero.Plugins.resolveURI(config.addonID, "prefs.js");
  const text = await Zotero.File.getContentsFromURLAsync(uri);
  const out: Record<string, unknown> = {};
  for (const m of text.matchAll(PREF_RX)) out[m[1]] = JSON.parse(m[2]);
  return out;
}

/** loadPrefs() with the pref store blanked → prefsFrom sees only fallbacks. */
function loadPrefsBlank(): TexlatePrefs {
  // Zotero.Prefs.get is a namespace function — direct assignment trips
  // TS2630, so patch through a mutable view of the namespace object.
  const prefs = Zotero.Prefs as unknown as { get: unknown };
  const origGet = prefs.get;
  prefs.get = () => undefined;
  try {
    return loadPrefs();
  } finally {
    prefs.get = origGet;
  }
}

describe("prefs defaults parity (addon/prefs.js vs prefs.ts fallbacks)", function () {
  it("pref() keys match the TS fallback field set", async function () {
    const jsDefaults = await readPrefsJs();
    assert.sameMembers(Object.keys(jsDefaults), Object.keys(PREF_TO_FIELD));
  });

  it("every pref() literal equals its TS fallback", async function () {
    const jsDefaults = await readPrefsJs();
    const tsDefaults = loadPrefsBlank();
    for (const [key, value] of Object.entries(jsDefaults)) {
      const project = PREF_TO_FIELD[key];
      if (!project) assert.fail(`unmapped pref key "${key}"`);
      assert.strictEqual(project(tsDefaults), value, key);
    }
  });
});
