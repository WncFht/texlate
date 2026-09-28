// host/syncZoom —— 同步引擎建毁 + syncing 标志位 + 缩放落地 + 页码翻页 +
// 分栏 divider 拖拽。
//
// engine.syncing 双 effect 分离是有意的（建毁 effect 不认 syncing——
// 开/关同步不再整台引擎重挂，滚动监听重绑是白烧；第二条 effect 只写
// 运行中引擎的标志位）。zoom effect 留注：paneReady 手工补赶不上
// setInfo→setZoom 窗口期。

import { createEffect, createSignal, onCleanup, untrack } from "solid-js";
import type { Mode } from "../chrome/Toolbar";
import type { DocId, PosMap } from "../logic/alignment";
import { zoomToFontPx } from "../logic/paneUtils";
import { SyncEngine } from "../logic/sync";
import type { PaneHandle } from "../pdf/pdfHandle";
import type { HtmlPaneHandle } from "../panes/HtmlPane";
import type { DomPaneHandle } from "../panes/DomPane";
import type { AnyHandle } from "../panes/PaneSlot";

/** 分栏拖拽比例上下限（15%–85%），dblclick 回 50/50 */
const SPLIT_MIN = 0.15;
const SPLIT_MAX = 0.85;

export function createSyncZoom(deps: {
    handles(): Partial<Record<DocId, AnyHandle>>;
    mode(): Mode;
    syncing(): boolean;
    setSyncing(on: boolean): void;
    zoom(): string;
    setZoom(z: string): void;
    active(): DocId;
    swapped(): boolean;
    mapper(): PosMap;
    pageCounts(): Record<DocId, number>;
    pageNums(): Record<DocId, number>;
    navMuteUntil: { at: number };
    updateDrift(): void;
    persistPosition(): void;
    panesEl(): HTMLDivElement;
}) {
    const {
        handles,
        mode,
        syncing,
        setSyncing,
        zoom,
        setZoom,
        active,
        swapped,
        mapper,
        pageCounts,
        pageNums,
        navMuteUntil,
        updateDrift,
        persistPosition,
        panesEl,
    } = deps;

    let engine: SyncEngine | null = null;
    const [splitPct, setSplitPct] = createSignal(0.5);

    // ---------- 同步引擎 ----------

    /** split + 两侧 handle 就位 → 建引擎；否则销毁（handles() 是响应源）。
     *  syncing 不参与本 effect——开/关同步不再整台引擎重挂（滚动监听重绑是白烧） */
    createEffect(() => {
        engine?.dispose();
        engine = null;
        if (mode() !== "split") return;
        const a = handles().original;
        const b = handles().translated;
        if (!a || !b) return;
        const e = new SyncEngine(a, b, mapper(), () => navMuteUntil.at);
        e.syncing = untrack(syncing);
        engine = e;
        onCleanup(() => e.dispose());
    });

    // syncing 只写运行中引擎的标志位（引擎缺席时由上面建机路径带初值）
    createEffect(() => {
        if (engine) engine.syncing = syncing();
    });

    const setSync = (on: boolean) => {
        setSyncing(on);
        if (engine) {
            engine.syncing = on;
            if (on) {
                const src = handles()[active()] ?? handles().original;
                if (src) engine.alignNow(src);
            }
        }
        if (!on) updateDrift();
        persistPosition();
    };

    onCleanup(() => engine?.dispose());

    // ---------- 缩放 / 页码 ----------

    /** 缩放值落单个窗格：pdf → setScale/setScaleValue；html/dom → setFontSize 档位 */
    const applyZoomTo = (h: AnyHandle | undefined, z: string) => {
        if (!h || !z) return;
        const ph = h as PaneHandle;
        if (ph.setScaleValue) {
            if (z.endsWith("%")) ph.setScale(Number(z.slice(0, -1)) / 100);
            else ph.setScaleValue(z);
            return;
        }
        (h as HtmlPaneHandle | DomPaneHandle).setFontSize?.(zoomToFontPx(z));
    };

    // zoom × handles 响应式落地：usePDFSlick 初值恒 page-width（§5.1 坑），
    // reading.zoom 恢复、窗格 keyed 重挂、用户改缩放三路共用——在 paneReady
    // 里手工补赶不上 setInfo→setZoom 之间的 await 窗口
    createEffect(() => {
        const z = zoom();
        for (const side of ["original", "translated"] as const) {
            applyZoomTo(handles()[side], z);
        }
    });

    const applyZoom = (z: string) => {
        setZoom(z);
        persistPosition();
    };

    const gotoPage = (n: number) => {
        handles()[active()]?.gotoPage?.(n);
    };

    const stepPage = (d: number) => {
        const cur = pageNums()[active()] ?? 1;
        const total = pageCounts()[active()] || 1;
        gotoPage(Math.min(total, Math.max(1, cur + d)));
    };

    // ---------- 分栏拖拽 divider ----------

    const onDividerDown = (e: PointerEvent) => {
        e.preventDefault();
        const bar = e.currentTarget as HTMLElement;
        bar.setPointerCapture(e.pointerId);
        // 拖拽全程 panesEl 几何不变——rect 只读一次，不随 pointermove 反复强制 layout
        const r = panesEl().getBoundingClientRect();
        const move = (ev: PointerEvent) => {
            if (r.width <= 0) return;
            const frac = (ev.clientX - r.left) / r.width;
            // DOM 序恒 original|divider|translated；swapped 仅视觉翻转
            // （row-reverse）——指针越靠右 original 槽越小，取反
            const logical = swapped() ? 1 - frac : frac;
            setSplitPct(Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, logical)));
        };
        const up = () => {
            bar.removeEventListener("pointermove", move);
            bar.removeEventListener("pointerup", up);
            bar.removeEventListener("pointercancel", up);
        };
        bar.addEventListener("pointermove", move);
        bar.addEventListener("pointerup", up);
        bar.addEventListener("pointercancel", up);
    };

    return {
        engine: () => engine,
        setSync,
        applyZoom,
        gotoPage,
        stepPage,
        splitPct,
        setSplitPct,
        onDividerDown,
    };
}
