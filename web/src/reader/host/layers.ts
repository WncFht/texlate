// host/layers —— Esc 层栈 + 键盘分发 + inspect 挂载。
// 最大扇入点（几乎消费一切子系统）——依赖序最后实例化。
// keymap 缺省栈经 isOpen/close 回调接本面；dispatchAction 的
// mode:N/ui:*/nav:*/sel:*/cite: 路由全靠注入回调。

import { onCleanup, onMount, type Setter } from "solid-js";
import type { DocId } from "../logic/alignment";
import type { PaneHandle } from "../pdf/pdfHandle";
import type { DomPaneHandle } from "../panes/DomPane";
import type { AnyHandle } from "../panes/PaneSlot";
import type { HitCtx } from "../cmd/hitctx";
import type { CopyLatexHandle } from "../features/copylatex";
import { attachReaderKeys } from "../chrome/keymap";
import { attachInspect, type InspectHandle } from "../features/inspect";
import { collapseSelection, hasLiveSelection } from "../sel/selection";
import type { Mode } from "../chrome/Toolbar";

export function createLayers(deps: {
    handles(): Partial<Record<DocId, AnyHandle>>;
    active(): DocId;
    syncing(): boolean;
    helpOpen(): boolean;
    setHelpOpen: Setter<boolean>;
    shareOpen(): boolean;
    setShareOpen(v: boolean): void;
    shareBtnEl(): HTMLButtonElement | undefined;
    ctxm: { isOpen(): boolean; close(): void };
    menuCard(): { rect: DOMRect; hit: HitCtx } | null;
    setMenuCard(v: { rect: DOMRect; hit: HitCtx } | null): void;
    cl: CopyLatexHandle;
    refsOpen(): boolean;
    setRefsOpen(v: boolean): void;
    setSync(on: boolean): void;
    navBack(side: DocId): void;
    navFwd(side: DocId): void;
    stepPage(d: number): void;
    planModeChange(next: Mode): void;
    runKeyCmd(id: string): void;
    openCiteAtFocus(): void;
    panesEl(): HTMLDivElement;
    mirrorTo(dst: DocId, dest: unknown, tries: number, pair: number): void;
    navPairSeq: { n: number };
}) {
    const {
        handles,
        active,
        syncing,
        helpOpen,
        setHelpOpen,
        shareOpen,
        setShareOpen,
        shareBtnEl,
        ctxm,
        menuCard,
        setMenuCard,
        cl,
        refsOpen,
        setRefsOpen,
        setSync,
        navBack,
        navFwd,
        stepPage,
        planModeChange,
        runKeyCmd,
        openCiteAtFocus,
        panesEl,
        mirrorTo,
        navPairSeq,
    } = deps;

    /** pane 级 Esc 面聚合：escOpen 任一为真 / escClose 双侧广播
        （DomPane 'cite' 卡 / PdfPane 'cite'+'find'+'info' 各管各层） */
    const forEachEsc = (m: "escOpen" | "escClose", layer: string): boolean => {
        let any = false;
        for (const s of ["original", "translated"] as const) {
            const h = handles()[s] as PaneHandle | DomPaneHandle | undefined;
            const fn = h?.[m];
            if (typeof fn !== "function") continue;
            const r = (fn as (layer: string) => unknown).call(h, layer);
            if (m === "escOpen") any = !!r || any;
        }
        return any;
    };

    const layerOpen = (l: string): boolean => {
        switch (l) {
            case "help":
                return helpOpen();
            case "menu":
                return ctxm.isOpen() || shareOpen();
            case "cite":
                return (
                    menuCard() != null ||
                    cl.cardOpen() ||
                    refsOpen() ||
                    forEachEsc("escOpen", "cite")
                );
            case "find":
                return forEachEsc("escOpen", "find");
            case "info":
                return forEachEsc("escOpen", "info");
            case "sel":
                return hasLiveSelection(document);
            default:
                return false;
        }
    };

    const closeLayer = (l: string) => {
        switch (l) {
            case "help":
                setHelpOpen(false);
                return;
            case "menu":
                // ctxm 关单自带回焦；share 弹层回焦分享钮（menuNav 同义）
                if (ctxm.isOpen()) ctxm.close();
                else {
                    setShareOpen(false);
                    shareBtnEl()?.focus();
                }
                return;
            case "cite":
                if (menuCard() != null) {
                    setMenuCard(null);
                    return;
                }
                // copy-latex 卡 / 文献面板同层归并（各件自带 Esc capture 先
                // 杀事件——走到这里说明事件漏出或程序化 closeLayer 调用）
                if (cl.cardOpen()) {
                    cl.closeCard();
                    return;
                }
                if (refsOpen()) {
                    setRefsOpen(false);
                    return;
                }
                forEachEsc("escClose", "cite");
                return;
            case "find":
            case "info":
                forEachEsc("escClose", l);
                return;
            case "sel":
                collapseSelection(document);
                return;
        }
    };

    /** pdf.js 批注编辑器态聚合——双侧任一为真即占（keymap 占有判定） */
    const pdfjsAgg = () => {
        let armed = false;
        let selected = false;
        for (const s of ["original", "translated"] as const) {
            const st = (handles()[s] as PaneHandle | undefined)?.pdfjsState?.();
            if (st) {
                armed = armed || st.armed;
                selected = selected || st.selected;
            }
        }
        return { armed, selected };
    };

    const dispatchAction = (action: string) => {
        switch (action) {
            case "ui:find": {
                const h = handles()[active()];
                if (h && "openFind" in h) h.openFind();
                return;
            }
            case "ui:help":
                setHelpOpen((v) => !v);
                return;
            case "ui:sync":
                setSync(!syncing());
                return;
            case "nav:back":
                navBack(active());
                return;
            case "nav:fwd":
                navFwd(active());
                return;
            case "page:-1":
                stepPage(-1);
                return;
            case "page:+1":
                stepPage(1);
                return;
            case "mode:1":
                planModeChange("split");
                return;
            case "mode:2":
                planModeChange("translated");
                return;
            case "mode:3":
                planModeChange("original");
                return;
            case "mode:4":
                planModeChange("guide");
                return;
            case "sel:copy":
                runKeyCmd("sel.copy");
                return;
            case "sel:xlat":
                runKeyCmd("sel.xlat"); // 未注册——sel-translate lane 挂点
                return;
            case "sel:lookup":
                runKeyCmd("sel.find");
                return;
            case "cite:open":
                openCiteAtFocus();
                return;
            default:
                return; // noop:sel / esc:* / pass / pdfjs:own ——栈内已消化
        }
    };

    // 键盘面：attachReaderKeys 单分发器（Esc 层栈/输入区豁免/Alt+←→/
    // pdfjs 占有/键表 11 步管线——替换原手排 switch）。
    onMount(() => {
        const keys = attachReaderKeys({
            act: (kind, detail) => {
                if (kind !== "dispatch") return;
                const a = (detail as { action?: string } | undefined)?.action;
                if (a) dispatchAction(a);
            },
            isOpen: layerOpen,
            close: closeLayer,
            hasSelection: () => hasLiveSelection(document),
            onCite: (tgt) =>
                !!(tgt as Element | null)?.closest?.(
                    "a[href^='#bib.'], a[href^='#cite.'], a.cite-ref, .ltx_cite",
                ),
            pdfjs: pdfjsAgg,
        });
        onCleanup(() => keys.dispose());

        // ⌘-Inspect 修饰键检视层：accel 按住→.insp-armed 揭示，⌘+click→
        // 原地 peek 卡，⌘+Alt+click→mirrorTo 对侧镜像跳。单 document
        // capture 闸吞/放——pane 级 inspectAt/inspectDestAt 缺槽的手势
        // 静默放过（live-pane 等非检视面不被误吞）
        const insp = attachInspect({
            rootEl: () => panesEl(),
            handleOf: (side) => handles()[side] as InspectHandle | undefined,
            pdfjsArmed: (side) =>
                (handles()[side] as PaneHandle | undefined)?.pdfjsState?.()
                    .armed ?? false,
            anyPdfjsArmed: () => pdfjsAgg().armed,
            hasLiveSelection: () => hasLiveSelection(document),
            mirror: (dst, dest) => mirrorTo(dst, dest, 2, ++navPairSeq.n),
        });
        onCleanup(() => insp.dispose());
    });

    return { forEachEsc, layerOpen };
}
