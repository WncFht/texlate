/**
 * menu.ts — "TeXlate" submenu on the library-item context menu.
 *
 * Mechanism (b): Zotero.MenuManager.registerMenu, the native Zotero 7 API —
 * ztoolkit.Menu is deprecated upstream, and MenuManager re-runs `onShowing`
 * with the live selection (`context.items`) on every popup, which is exactly
 * the per-popup visibility recompute this UX needs. `main/library/item` is a
 * GROUPED_TARGET: Zotero prepends one separator shared by all plugins (and
 * rejects plugin-supplied top-level separators), so both actions sit under a
 * single submenu — one group chrome, hidden as a whole when neither applies.
 */
import { config } from "../../package.json";
import type { MenuState } from "../contracts";
import { hasArxivId } from "./arxivId";
import { getTexlateMark } from "./attach";
import { openInReader, translateItems } from "./flow";

type ItemContext = _ZoteroTypes.MenuManager.LibraryMenuContext;

let registered = false;

const isTranslatable = (item: Zotero.Item): boolean =>
  hasArxivId(item) && getTexlateMark(item) === null;
const isMarked = (item: Zotero.Item): boolean => getTexlateMark(item) !== null;

/** Pure visibility decision — dev-verify asserts this without a real popup. */
export function computeMenuState(items: Zotero.Item[]): MenuState {
  const regular = items.filter((item) => item.isRegularItem());
  return {
    translate: regular.some(isTranslatable),
    reader: regular.some(isMarked),
  };
}

/** Raw selection — MenuManager supplies it; ZoteroPane is the fallback. */
function selectedItems(
  context: ItemContext,
  win: _ZoteroTypes.MainWindow,
): Zotero.Item[] {
  if (context.items) return context.items;
  try {
    // `win` is the first window menus were registered on — possibly closed.
    return win.ZoteroPane.getSelectedItems();
  } catch {
    return [];
  }
}

export function registerMenus(win: _ZoteroTypes.MainWindow): void {
  // addon.api.computeMenuState is wired once by installSelftest (onStartup).
  if (registered) return; // MenuManager is global; covers every main window.
  const ok = Zotero.MenuManager.registerMenu({
    menuID: `${config.addonRef}-itemmenu`,
    pluginID: config.addonID,
    target: "main/library/item",
    menus: [
      {
        menuType: "submenu",
        l10nID: `${config.addonRef}-menu`,
        // 16px SVG + context-fill——随菜单文字色自动适配 hover/暗色，
        // 位图 favicon 缩到 16px 发糊且暗色不变色（MenuManager 官方约定）。
        icon: `chrome://${config.addonRef}/content/icons/menu-icon.svg`,
        onShowing: (_event, context) => {
          const state = computeMenuState(selectedItems(context, win));
          context.setVisible(state.translate || state.reader);
        },
        onShown: (_event, context) => {
          // Zotero's group separator is shared chrome with no visibility
          // logic; with every plugin item hidden it would dangle at the menu
          // bottom — hide it too. Runs on popupshown so all plugins'
          // onShowing hooks have already settled their `hidden` state.
          const popup = context.menuElem?.parentElement;
          if (!popup) return;
          const customItems = Array.from(
            popup.querySelectorAll(":scope > .zotero-custom-menu-item"),
          ) as Element[];
          const anyVisible = customItems.some(
            (el) =>
              el.localName !== "menuseparator" &&
              el.getAttribute("hidden") !== "true",
          );
          (
            Array.from(
              popup.querySelectorAll(
                ":scope > menuseparator.zotero-custom-menu-group-separator",
              ),
            ) as Element[]
          ).forEach((sep) => {
            if (anyVisible) sep.removeAttribute("hidden");
            else sep.setAttribute("hidden", "true");
          });
        },
        menus: [
          {
            menuType: "menuitem",
            l10nID: `${config.addonRef}-translate`,
            onShowing: (_event, context) => {
              context.setVisible(
                computeMenuState(selectedItems(context, win)).translate,
              );
            },
            onCommand: (_event, context) => {
              const items = selectedItems(context, win).filter(
                (item) => item.isRegularItem() && isTranslatable(item),
              );
              if (!items.length) return;
              // Fire-and-forget — flow reports progress/failures itself.
              void translateItems(items).catch((e: unknown) => ztoolkit.log(e));
            },
          },
          {
            menuType: "menuitem",
            l10nID: `${config.addonRef}-open-reader`,
            onShowing: (_event, context) => {
              context.setVisible(
                computeMenuState(selectedItems(context, win)).reader,
              );
            },
            onCommand: (_event, context) => {
              const item = selectedItems(context, win).find(
                (it) => it.isRegularItem() && isMarked(it),
              );
              if (item) openInReader(item);
            },
          },
        ],
      },
    ],
  });
  if (ok) registered = true;
}
