// host/paneRegistry —— pane handle 注册表与宿主查询基板。
// handles() 注册表由 PaneSlot onReady/onDispose 维护（U3：隐藏侧常驻挂载、
// display:none 保活，handle 仍在表内——位置捕获/同步只认 paneVisible 一侧）。
// 各簇共用的基底件：bodyOf/liveBodyEl 文本宿主查询、sideOfHit 命中侧归一、
// paneVisible 可见侧判、restoredSides 恢复闸。零下游依赖——最早实例化。

import { createSignal } from "solid-js";
import type { DocId } from "../logic/alignment";
import type { Mode } from "../chrome/Toolbar";
import type { AnyHandle } from "../panes/PaneSlot";
import type { HitCtx } from "../cmd/hitctx";

export function createPaneRegistry(deps: { mode(): Mode; active(): DocId }) {
    const { mode, active } = deps;
    const [handles, setHandles] = createSignal<
        Partial<Record<DocId, AnyHandle>>
    >({});
    const restoredSides = new Set<DocId>();

    /** hit.paneSide → DocId；panes 内非 pane 目标落活动侧 */
    const sideOfHit = (hit: HitCtx): DocId =>
        hit.paneSide === "en"
            ? "original"
            : hit.paneSide === "zh"
              ? "translated"
              : active();

    /** 本侧文本宿主（dom/html 的 bodyEl 挂点）；pdf/缺席 → null */
    const bodyOf = (side: DocId): HTMLElement | null => {
        const h = handles()[side];
        return h && "bodyEl" in h && typeof h.bodyEl === "function"
            ? h.bodyEl()
            : null;
    };

    /** live-pane 文本宿主——LivePane 挂在 TaskProgress（.panes 外、非
        handles() 体系），partial 共屏/同页时经 DOM 现查（copy-latex
        zh 盲区兜底与 sent-align 的 live 侧登记共用此源） */
    const liveBodyEl = (): HTMLElement | null =>
        document.querySelector<HTMLElement>(".live-pane .pane-html-body");

    const paneVisible = (side: DocId) => mode() === "split" || mode() === side;

    return {
        handles,
        setHandles,
        restoredSides,
        sideOfHit,
        bodyOf,
        liveBodyEl,
        paneVisible,
    };
}
