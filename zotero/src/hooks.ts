import { initLocale } from "./utils/locale";
import { createZToolkit } from "./utils/ztoolkit";
import { registerMenus } from "./modules/menu";
import { registerPrefsPane } from "./modules/prefs";
import { installSelftest } from "./modules/selftest";
import { installBootstrap } from "./modules/bootstrap";

async function onStartup() {
  await Promise.all([
    Zotero.initializationPromise,
    Zotero.unlockPromise,
    Zotero.uiReadyPromise,
  ]);

  initLocale();

  installSelftest();
  installBootstrap();
  registerPrefsPane();

  await Promise.all(
    Zotero.getMainWindows().map((win) => onMainWindowLoad(win)),
  );

  // Mark initialized as true to confirm plugin loading status
  // outside of the plugin (e.g. scaffold testing process)
  addon.data.initialized = true;
}

async function onMainWindowLoad(win: _ZoteroTypes.MainWindow): Promise<void> {
  // Create ztoolkit for every window
  addon.data.ztoolkit = createZToolkit();

  win.MozXULElement.insertFTLIfNeeded(
    `${addon.data.config.addonRef}-mainWindow.ftl`,
  );

  registerMenus(win);
}

async function onMainWindowUnload(win: Window): Promise<void> {
  ztoolkit.unregisterAll();
  addon.data.dialog?.window?.close();
}

function onShutdown(): void {
  ztoolkit.unregisterAll();
  addon.data.dialog?.window?.close();
  // Remove addon object
  addon.data.alive = false;
  // @ts-expect-error - Plugin instance is not typed
  delete Zotero[addon.data.config.addonInstance];
}

/**
 * Dispatcher for Preference UI events — called from preferences.xhtml's
 * groupbox onload. Window binding for the declarative prefs dialog is owned
 * by modules/prefs.ts, so the "load" case is intentionally a no-op.
 * @param type event type
 * @param data event data
 */
async function onPrefsEvent(type: string, data: { [key: string]: any }) {
  switch (type) {
    case "load":
      break;
    default:
      return;
  }
}

// Keep in mind hooks only do dispatch. Don't add code that does real jobs in hooks.
// Otherwise the code would be hard to read and maintain.

export default {
  onStartup,
  onShutdown,
  onMainWindowLoad,
  onMainWindowUnload,
  onPrefsEvent,
};
