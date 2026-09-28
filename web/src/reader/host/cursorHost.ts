// host/cursorHost —— 句游标宿主（v 模态；dom/html 双侧各一，pdf 侧不建）。
// sents 原位换血（cursor.otherSents 持同引用才不失效）+ MutationObserver
// 120ms 防抖重分句 + 浮层让路闸。对外 wireSelPane/unwireSelPane 两口供
// 根部 paneReady/paneDisposed 调。
//
// load-bearing：ctor dispose + CAPTURE 重挂顺序是修过的坑（模态内按键须
// 先于 bubble 阶 keymap 吃掉——'['双发、Esc 错塌 sel 两坑由此免），逐字搬。
// layerOpen 属 layers 簇（最大扇入最后实例化）——deps 里以晚期绑定回跳，
// 本 hook 键位回调只在运行期触达，初始化序无害。

import { onCleanup } from "solid-js";
import { other, type DocId } from "../logic/alignment";
import type { AnyHandle } from "../panes/PaneSlot";
import { segmentDoc, type SegSide, type SentMark } from "../sel/sentseg";
import { makeCursor, type Cursor } from "../sel/cursor";

export function createCursorHost(deps: {
    handles(): Partial<Record<DocId, AnyHandle>>;
    bodyOf(side: DocId): HTMLElement | null;
    liveEl(): HTMLElement | undefined;
    ctxm: { isOpen(): boolean };
    shareOpen(): boolean;
    helpOpen(): boolean;
    layerOpen(l: string): boolean;
}) {
    const { handles, bodyOf, liveEl, ctxm, shareOpen, helpOpen, layerOpen } =
        deps;

    const segSideOf = (side: DocId): SegSide =>
        side === "translated" ? "zh" : "en";

    /** 双侧分句表（原位重灌——cursor.otherSents 持同引用才不失效） +
        句游标/观察器登记 */
    const sents: Record<DocId, SentMark[]> = {
        original: [],
        translated: [],
    };
    const cursors: Partial<Record<DocId, Cursor>> = {};
    const segMOs = new Map<DocId, MutationObserver>();
    const segTimers = new Map<DocId, number>();

    /** 重分句：旧 .sb 全摘再 segmentDoc 重钉，数组原位换血
        （cursor.otherSents 持引用——换新数组会让对侧查找失真） */
    const resegment = (side: DocId) => {
        const body = bodyOf(side);
        if (!body) return;
        for (const el of body.querySelectorAll(".sb")) el.remove();
        const marks = segmentDoc(body, segSideOf(side));
        sents[side].length = 0;
        sents[side].push(...marks);
    };

    /** 游标本体：ctor 自挂的 bubble 监听摘掉换 CAPTURE 重挂——模态内按键
        须先于 bubble 阶的 keymap 吃掉（'['双发、Esc 错塌 sel 两坑由此免）；
        浮层在场时模式内按键让路给层内导航 */
    const ensureCursor = (side: DocId) => {
        if (cursors[side] || !sents[side].length) return;
        const h = handles()[side];
        const body = bodyOf(side);
        if (!h || !body) return;
        const cur = makeCursor({
            pane: h.el, // ChunkPaneHandle.el = .pane 滚动宿主
            body,
            sents: sents[side],
            otherSents: sents[other(side)],
            live: liveEl() ?? null,
            variant: "roving",
        });
        cur.dispose(); // 摘 ctor 自挂的 bubble 监听——换 capture 重挂
        const onKey = (e: KeyboardEvent): string | null => {
            // 浮层在场（菜单/帮助/引用卡/信息/分享/查找条）→ 层内键盘导航优先；
            // find 在 ESC_ORDER 序位高于 sel——findbar 开着时 Esc 先收条而非退模态
            if (
                cur.state.mode !== "idle" &&
                (ctxm.isOpen() ||
                    shareOpen() ||
                    helpOpen() ||
                    layerOpen("cite") ||
                    layerOpen("find") ||
                    layerOpen("info"))
            )
                return null;
            return cur.onKey(e);
        };
        document.addEventListener("keydown", onKey, true);
        cursors[side] = {
            ...cur,
            dispose: () => document.removeEventListener("keydown", onKey, true),
        };
    };

    const dropCursor = (side: DocId) => {
        cursors[side]?.dispose();
        delete cursors[side];
        sents[side].length = 0;
    };

    /** 游标重建：chunkFirst 快照在 ctor 建——sents 换血后必须重造，
        否则 ]/[ 跳块按旧表落错句 */
    const rebuildCursor = (side: DocId) => {
        const cur = cursors[side];
        if (cur) {
            if (cur.state.mode !== "idle") cur.exit(false);
            cur.dispose();
            delete cursors[side];
        }
        ensureCursor(side);
    };

    /** body 观察：childList 直子级变化（HtmlPane retx replaceWith /
        LivePane insertBefore / DomPane 分片 append 全落这层）→ 120ms
        防抖重分句；.sb 钉在块内部不触发本层——自环天然免 */
    const watchBody = (side: DocId, body: HTMLElement) => {
        segMOs.get(side)?.disconnect();
        const mo = new MutationObserver(() => {
            window.clearTimeout(segTimers.get(side));
            segTimers.set(
                side,
                window.setTimeout(() => {
                    resegment(side);
                    rebuildCursor(side); // DOM 换血后 marker 全换，模态内退模态保命
                }, 120),
            );
        });
        mo.observe(body, { childList: true });
        segMOs.set(side, mo);
    };

    /** pane 挂点三件套：bodyEl 在场才分段/观察/建游标（pdf 侧不建） */
    const wireSelPane = (side: DocId) => {
        const body = bodyOf(side);
        if (!body) return;
        resegment(side);
        watchBody(side, body);
        ensureCursor(side);
    };
    const unwireSelPane = (side: DocId) => {
        segMOs.get(side)?.disconnect();
        segMOs.delete(side);
        window.clearTimeout(segTimers.get(side));
        segTimers.delete(side);
        dropCursor(side);
    };

    // sel-system：双侧游标/观察器/分句表卸载（幂等——paneDisposed 可能已清）
    onCleanup(() => {
        for (const s of ["original", "translated"] as const) unwireSelPane(s);
    });

    return { wireSelPane, unwireSelPane };
}
