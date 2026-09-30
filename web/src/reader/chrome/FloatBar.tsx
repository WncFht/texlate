// FloatBar —— selectionchange→getBoundingClientRect→浮动工具条
// （floatbar 预研版移植落地，TS + Solid 包装）。
//
// 行为锁定项（预研实证面，逐行对应）：
//  * selectionchange → rAF 合帧 → 单次 getBoundingClientRect → fixed 定位；
//  * 拖拽期压制：pointerDown 时 selectionchange 只记 pending，pointerup 才
//    排程（'release' 默认）；非拖拽走 40ms 静默 debounce（键盘选区）；
//  * 滚动跟随：document capture scroll（pane 内滚动容器不冒泡），每帧重算
//    锚 rect 重放 place；锚出视口→藏（curRange 留存），滚回→重现；
//  * 条自身 pointerdown/mousedown preventDefault——点钮不收选区；
//    user-select:none 由 .floatbar 皮肤承担；
//  * 仪器面 stats{events,schedules,positions,rectReads,shows,hides,
//    lastShowMs,lastPlaceMs} + el.dataset.placement/flipped/state。
//
// 落地增量（实现文档三处对抗修复 + 仓内差异）：
//  1) pointercancel 按 pointerup 同语义解卡——拖拽被打断（触摸滚动夺手势）
//     不再永久卡死 pointerDown 压制位；
//  2) opts.allowShow(range) 展示闸——空命令集/菜单开单期不示条；veto 时
//     保锚（keepAnchor）以便 refresh() 在闸松后免 selectionchange 重现；
//  3) 跨 pane 选区锚取 anchor 侧 rect 而非并集——union 会跨双栏缝把条
//     悬到 gutter 上；实现=range.getClientRects() 滤 anchorNode 所在 pane
//     盒内的 rect 再取并集，滤空回退 range.getBoundingClientRect()。
//  ResizeObserver 属组件层（props.observeEls）——非滚动布局漂移
// （pane 拉宽/字体回流）经 api.refresh() 全量重估。

import {
    createEffect,
    createSignal,
    For,
    onCleanup,
    onMount,
    Show,
} from "solid-js";
import { Portal } from "solid-js/web";

export const BAR_GAP = 8; // 条与选区间的纵向缝
export const BAR_MARGIN = 8; // 条贴视口的边距

export interface RectLike {
    left: number;
    top: number;
    right: number;
    bottom: number;
    width: number;
    height: number;
}

export interface BarPlaced {
    left: number;
    top: number;
    placement: "above" | "below";
    flipped: boolean;
}

/**
 * 纯函数落点：anchor=选区锚 rect（视口系），w/h=条实测宽高。
 * prefer='above'（默认）：上放不下→下；都不放下→空大侧贴边。
 * 返回 {left, top, placement, flipped}——flipped=未落在 prefer 侧。
 * 不变式（place_fuzz 验证）：w+2m<=vw 且 h+2m<=vh 时结果必在视口内。
 */
export function placeBar(
    anchor: RectLike,
    w: number,
    h: number,
    vw: number,
    vh: number,
    opts: { gap?: number; margin?: number; prefer?: "above" | "below" } = {},
): BarPlaced {
    const gap = opts.gap ?? BAR_GAP;
    const m = opts.margin ?? BAR_MARGIN;
    const prefer = opts.prefer ?? "above";
    const cx = anchor.left + (anchor.right - anchor.left) / 2;
    let left = cx - w / 2;
    const roomAbove = anchor.top - m;
    const roomBelow = vh - anchor.bottom - m;
    const fitsAbove = roomAbove >= h + gap;
    const fitsBelow = roomBelow >= h + gap;
    let placement: "above" | "below";
    let top: number;
    const aboveTop = () => anchor.top - gap - h;
    const belowTop = () => anchor.bottom + gap;
    if (prefer === "above") {
        if (fitsAbove) {
            placement = "above";
            top = aboveTop();
        } else if (fitsBelow) {
            placement = "below";
            top = belowTop();
        } else if (roomAbove >= roomBelow) {
            placement = "above";
            top = m;
        } else {
            placement = "below";
            top = vh - h - m;
        }
    } else {
        if (fitsBelow) {
            placement = "below";
            top = belowTop();
        } else if (fitsAbove) {
            placement = "above";
            top = aboveTop();
        } else if (roomBelow >= roomAbove) {
            placement = "below";
            top = vh - h - m;
        } else {
            placement = "above";
            top = m;
        }
    }
    left = Math.min(Math.max(m, left), Math.max(m, vw - w - m));
    top = Math.min(Math.max(m, top), Math.max(m, vh - h - m));
    return { left, top, placement, flipped: placement !== prefer };
}

export interface FloatBarStats {
    events: number;
    schedules: number;
    positions: number;
    rectReads: number;
    shows: number;
    hides: number;
    lastShowMs: number;
    lastPlaceMs: number;
}

export interface FloatBarApi {
    el: HTMLElement;
    stats: FloatBarStats;
    visible(): boolean;
    /** 手动触发一次重估（闸松/布局漂移/同步改选区后） */
    refresh(): void;
    /** 立即收条（菜单互斥/动作执行后） */
    hide(): void;
    /** 当前锚 range（滚动重估/动作载荷用） */
    range(): Range | null;
    destroy(): void;
}

export interface CreateFloatBarOpts {
    document?: Document;
    /** 自带条元素（Solid 组件根）；缺省自建空壳 append 到 body */
    bar?: HTMLElement;
    /** 'release'（默认）拖拽松手才出 | 'live' 拖拽逐帧跟 */
    mode?: "release" | "live";
    gap?: number;
    margin?: number;
    prefer?: "above" | "below";
    offscreenHide?: boolean;
    zIndex?: number;
    /** 展示闸：false → 收条但保锚（refresh 可免 selectionchange 重现） */
    allowShow?(range: Range): boolean;
}

/**
 * 控制器（框架无关）。返回 {el, stats, visible(), refresh(), hide(),
 * range(), destroy()}。
 */
export function createFloatBar(opts: CreateFloatBarOpts = {}): FloatBarApi {
    const doc = opts.document ?? document;
    const win = doc.defaultView ?? window;
    const mode = opts.mode ?? "release";
    const gap = opts.gap ?? BAR_GAP;
    const margin = opts.margin ?? BAR_MARGIN;
    const prefer = opts.prefer ?? "above";
    const offscreenHide = opts.offscreenHide ?? true;

    const el =
        opts.bar ??
        (() => {
            const d = doc.createElement("div");
            doc.body.appendChild(d);
            return d;
        })();
    el.classList.add("floatbar");
    el.style.position = "fixed";
    el.style.left = "0";
    el.style.top = "0";
    el.style.visibility = "hidden";
    el.style.pointerEvents = "none"; // 隐藏期不吃事件
    if (opts.zIndex != null) el.style.zIndex = String(opts.zIndex);

    const stats: FloatBarStats = {
        events: 0,
        schedules: 0,
        positions: 0,
        rectReads: 0,
        shows: 0,
        hides: 0,
        lastShowMs: NaN,
        lastPlaceMs: NaN,
    };

    let shown = false;
    let pendingEvtT = NaN;
    let rafId = 0;
    let debounceT = 0;
    let pointerDown = false;
    let pendingAfterUp = false;
    let destroyed = false;
    let curRange: Range | null = null;

    const vw = () => win.innerWidth;
    const vh = () => win.innerHeight;

    function hide(keepAnchor = false) {
        if (!shown) {
            if (!keepAnchor) curRange = null;
            return;
        }
        shown = false;
        if (!keepAnchor) curRange = null;
        stats.hides++;
        el.style.visibility = "hidden";
        el.style.pointerEvents = "none";
        el.dataset.state = "hidden";
    }

    const offscreen = (r: RectLike) =>
        offscreenHide &&
        (r.bottom < 0 || r.top > vh() || r.right < 0 || r.left > vw());

    const liveSel = (): boolean => {
        const sel = win.getSelection();
        return (
            !!sel &&
            sel.rangeCount > 0 &&
            !sel.isCollapsed &&
            String(sel).length > 0
        );
    };

    /** 选区 anchor 端所在 pane（跨 pane 选区的锚侧判定源） */
    const anchorPane = (): Element | null => {
        const sel = win.getSelection?.();
        const n = sel?.anchorNode ?? null;
        if (!n) return null;
        const e = n.nodeType === 3 ? n.parentElement : (n as Element);
        return e?.closest?.(".pane, .live-pane") ?? null;
    };

    function anchorRect(range: Range): RectLike | null {
        stats.rectReads++;
        // 跨 pane 选区：锚取 anchor 侧——并集会悬到栏缝 gutter 上
        const pane = anchorPane();
        if (pane) {
            const pr = pane.getBoundingClientRect();
            const rects = Array.from(range.getClientRects()).filter(
                (r) =>
                    r.width >= 1 &&
                    r.height >= 1 &&
                    r.left >= pr.left - 1 &&
                    r.right <= pr.right + 1 &&
                    r.top >= pr.top - 1 &&
                    r.bottom <= pr.bottom + 1,
            );
            if (rects.length) {
                const left = Math.min(...rects.map((r) => r.left));
                const top = Math.min(...rects.map((r) => r.top));
                const right = Math.max(...rects.map((r) => r.right));
                const bottom = Math.max(...rects.map((r) => r.bottom));
                return {
                    left,
                    top,
                    right,
                    bottom,
                    width: right - left,
                    height: bottom - top,
                };
            }
        }
        const r = range.getBoundingClientRect();
        if (!r || (r.width < 1 && r.height < 1)) return null;
        return r;
    }

    function place(rect: RectLike) {
        const w = el.offsetWidth || 96; // 首帧估宽兜底
        const h = el.offsetHeight || 32;
        const p = placeBar(rect, w, h, vw(), vh(), { gap, margin, prefer });
        el.style.transform = `translate(${p.left}px, ${p.top}px)`;
        el.dataset.placement = p.placement;
        el.dataset.flipped = String(p.flipped);
        stats.positions++;
        return p;
    }

    function show() {
        if (shown) return;
        shown = true;
        stats.shows++;
        if (!Number.isNaN(pendingEvtT))
            stats.lastShowMs = performance.now() - pendingEvtT;
        el.style.visibility = "visible";
        el.style.pointerEvents = "auto";
        el.dataset.state = "visible";
    }

    // selectionchange 驱动的全量评估（显/隐/落位一把抓）
    function evaluate() {
        const t0 = performance.now();
        const sel = win.getSelection();
        if (
            !sel ||
            sel.rangeCount === 0 ||
            sel.isCollapsed ||
            !String(sel).length
        ) {
            pendingEvtT = NaN;
            hide();
            stats.lastPlaceMs = performance.now() - t0;
            return;
        }
        const range = sel.getRangeAt(0);
        const rect = anchorRect(range);
        if (!rect) {
            pendingEvtT = NaN;
            hide();
            stats.lastPlaceMs = performance.now() - t0;
            return;
        }
        if (offscreen(rect)) {
            pendingEvtT = NaN;
            curRange = range; // 出屏也留锚——滚回可重显
            hide(true);
            stats.lastPlaceMs = performance.now() - t0;
            return;
        }
        // 展示闸（空命令集/菜单互斥）：收条但保锚——闸松后 refresh() 重现
        if (opts.allowShow && !opts.allowShow(range)) {
            pendingEvtT = NaN;
            curRange = range;
            hide(true);
            stats.lastPlaceMs = performance.now() - t0;
            return;
        }
        curRange = range;
        place(rect);
        show();
        pendingEvtT = NaN;
        stats.lastPlaceMs = performance.now() - t0;
    }

    function schedule() {
        stats.schedules++;
        if (rafId) return;
        rafId = win.requestAnimationFrame(() => {
            rafId = 0;
            if (destroyed) return;
            evaluate();
        });
    }

    // 拖拽期（pointerDown）只记 pending 不落位；非拖拽 40ms 静默 debounce。
    function onSelChange() {
        stats.events++;
        if (Number.isNaN(pendingEvtT)) pendingEvtT = performance.now();
        if (pointerDown && mode === "release") {
            pendingAfterUp = true;
            return;
        }
        if (mode === "release") {
            clearTimeout(debounceT);
            debounceT = win.setTimeout(schedule, 40);
        } else {
            schedule();
        }
    }

    function onPointerDown(e: Event) {
        pointerDown = true;
        const t = e.target;
        if (
            shown &&
            (e as PointerEvent).button === 0 &&
            t instanceof Node &&
            !el.contains(t)
        )
            hide();
    }
    function onPointerUp() {
        pointerDown = false;
        if (pendingAfterUp) {
            pendingAfterUp = false;
            pendingEvtT = performance.now(); // 计量=松手→出条，不含拖拽时长
            schedule();
        }
    }

    // 滚动跟随：capture 兜 pane 内滚动容器（scroll 不冒泡）。
    // shown 与 offscreen-hidden（curRange 仍在）两态都要重估：
    // 锚回视口即重显，出视口即藏。
    function onScroll() {
        if (!curRange || rafId) return;
        rafId = win.requestAnimationFrame(() => {
            rafId = 0;
            if (destroyed || !curRange) return;
            if (!liveSel()) return hide();
            const rect = anchorRect(curRange);
            if (!rect) return hide();
            if (offscreen(rect)) return hide(true);
            if (opts.allowShow && !opts.allowShow(curRange)) return hide(true);
            place(rect);
            show();
        });
    }

    function onResize() {
        if (!curRange) return;
        if (!liveSel()) return hide();
        const rect = anchorRect(curRange);
        if (!rect) return hide();
        if (offscreen(rect)) return hide(true);
        if (opts.allowShow && !opts.allowShow(curRange)) return hide(true);
        place(rect);
        show();
    }

    // 条上按下不夺焦/不收选区（preventDefault 同时挡掉兼容 mouse 事件
    // 的默认行为；mousedown 再兜一道旧路径）。
    const keepSel = (e: Event) => e.preventDefault();
    el.addEventListener("pointerdown", keepSel);
    el.addEventListener("mousedown", keepSel);

    doc.addEventListener("selectionchange", onSelChange);
    doc.addEventListener("pointerdown", onPointerDown, true);
    doc.addEventListener("pointerup", onPointerUp, true);
    // 对抗修复①：pointercancel 同 pointerup 解卡——拖拽被夺手势
    // （触摸滚动/系统手势）不再永久卡在 pointerDown 压制位
    doc.addEventListener("pointercancel", onPointerUp, true);
    doc.addEventListener("scroll", onScroll, { capture: true, passive: true });
    win.addEventListener("resize", onResize);

    return {
        el,
        stats,
        visible: () => shown,
        refresh: schedule,
        hide: () => hide(),
        range: () => curRange,
        destroy() {
            destroyed = true;
            clearTimeout(debounceT);
            if (rafId) win.cancelAnimationFrame(rafId);
            el.removeEventListener("pointerdown", keepSel);
            el.removeEventListener("mousedown", keepSel);
            doc.removeEventListener("selectionchange", onSelChange);
            doc.removeEventListener("pointerdown", onPointerDown, true);
            doc.removeEventListener("pointerup", onPointerUp, true);
            doc.removeEventListener("pointercancel", onPointerUp, true);
            doc.removeEventListener("scroll", onScroll, { capture: true });
            win.removeEventListener("resize", onResize);
            if (!opts.bar) el.remove();
        },
    };
}

// ---------------------------------------------------------------- Solid 组件

export interface FloatBarItem {
    id: string;
    label: string;
    hint?: string;
}

/**
 * 划词浮条组件——Portal→body（同 CiteCard fixed 脱壳约定），按钮由
 * itemsFor(range) 现算（allowShow 内联调用，展示前 buttons 已入 DOM，
 * place() 量到真宽）。
 *
 * @param itemsFor   选区 range → 条钮集（宿主：cmdreg enabled+bar 前 N 项；
 *                   空集 = 不示条）
 * @param onAction   钮击出口（id + 当前锚 range）；执行后收条
 * @param suppressed 互斥闸（右键菜单开单期 true）
 * @param observeEls ResizeObserver 目标（pane 容器/滚动宿主——非滚动漂移
 *                   经 refresh 全量重估）；信号式取值，createEffect 跟踪
 * @param apiRef     控制器出口（宿主存 api 调 refresh/hide）
 */
export function FloatBar(props: {
    itemsFor(range: Range): FloatBarItem[];
    onAction(id: string, range: Range | null): void;
    suppressed?(): boolean;
    observeEls?(): readonly (Element | null | undefined)[];
    apiRef?(api: FloatBarApi | null): void;
}) {
    let barEl!: HTMLDivElement;
    const [items, setItems] = createSignal<FloatBarItem[]>([]);
    const [api, setApi] = createSignal<FloatBarApi | null>(null);

    onMount(() => {
        const ctl = createFloatBar({
            bar: barEl,
            allowShow: (range) => {
                if (props.suppressed?.()) return false;
                const its = props.itemsFor(range);
                setItems(its); // 同步渲染——show() 前按钮已就位，量到真宽
                return its.length > 0;
            },
        });
        setApi(ctl);
        props.apiRef?.(ctl);
        onCleanup(() => {
            props.apiRef?.(null);
            ctl.destroy();
        });
    });

    // 对抗修复②：非滚动布局漂移（pane 拉宽/字体回流/挂载完成）——
    // RO 观察宿主给的面，变化即全量重估（refresh=schedule→evaluate）
    createEffect(() => {
        const els = (props.observeEls?.() ?? []).filter(
            (e): e is Element => !!e,
        );
        const ctl = api();
        if (!els.length || !ctl || typeof ResizeObserver === "undefined")
            return;
        const ro = new ResizeObserver(() => ctl.refresh());
        for (const e of els) ro.observe(e);
        onCleanup(() => ro.disconnect());
    });

    const click = (id: string) => {
        const ctl = api();
        const range =
            ctl?.range() ??
            (window.getSelection()?.rangeCount
                ? window.getSelection()!.getRangeAt(0)
                : null);
        props.onAction(id, range);
        ctl?.hide(); // 动作执行后收条（选区留存——refresh 可重现）
    };

    return (
        <Portal>
            <div ref={(n) => (barEl = n)} class="floatbar" role="toolbar">
                <For each={items()}>
                    {(it) => (
                        <button type="button" onClick={() => click(it.id)}>
                            {it.label}
                            <Show when={it.hint}>
                                <span class="fb-hint">{it.hint}</span>
                            </Show>
                        </button>
                    )}
                </For>
            </div>
        </Portal>
    );
}
