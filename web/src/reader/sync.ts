// 双栏滚动同步引擎 —— docs/research/product/web-layer.md §5.3 伪码落地。
// 纯 TS、框架无关：PdfPane / HtmlPane 都实现 PaneLike 即可接入。
// 要点（texglot 先例）：20% 焦点线、viewport 字段保持锚点屏幕高度、
// ignoreTop 吞程序跳转回声、rAF+epoch 合帧丢弃过期滚动。

import type { DocId, Pos, PosMap, Side } from "./alignment";

export type { Pos, PosMap, Side };

export interface PageGeom {
    page: number;
    top: number;
    height: number;
}

/** 一个可同步窗格：滚动容器 + 按页/块的几何表 */
export interface PaneLike {
    readonly el: HTMLElement;
    readonly side: Side;
    pages(): PageGeom[];
}

const FOCUS_LINE = 0.2;

/** rAF 单发调度（无 rAF 环境退 16ms setTimeout——jsdom/SSR 兜底） */
export const raf: (cb: FrameRequestCallback) => void =
    typeof requestAnimationFrame === "function"
        ? (cb) => requestAnimationFrame(cb)
        : (cb) => void setTimeout(() => cb(performance.now()), 16);

/** 焦点行 = scrollTop + 20% 视口高；返回所在页 + 页内 fraction + 视口位置 */
export function capturePos(pane: PaneLike): Pos {
    const el = pane.el;
    const t = el.scrollTop;
    const h = el.clientHeight;
    const focus = t + h * FOCUS_LINE;
    const pages = pane.pages();
    // pages 按 top 升序——二分最后一个 top<=focus；滚动每帧走到这，
    // 线性扫在几千块文档上是 O(N)/帧。纯索引访问：pages 无迭代义务
    let lo = 0;
    let hi = pages.length;
    while (lo < hi) {
        const mid = (lo + hi) >>> 1;
        if (pages[mid].top <= focus) lo = mid + 1;
        else hi = mid;
    }
    const p = pages[lo - 1] ?? pages[0];
    if (!p) return { page: 1, fraction: 0 };
    const y = Math.min(Math.max(focus, p.top), p.top + p.height);
    return {
        page: p.page,
        fraction: p.height > 0 ? (y - p.top) / p.height : 0,
        viewport: h > 0 ? (y - t) / h : 0,
    };
}

/** jump() 会写出的 scrollTop（不落地，用于漂移检测/测试） */
export function scrollTopFor(pane: PaneLike, pos: Pos): number | null {
    const p = pane.pages().find((pg) => pg.page === pos.page);
    if (!p) return null;
    return (
        p.top +
        pos.fraction * p.height -
        (pos.viewport ?? 0) * pane.el.clientHeight
    );
}

export function jumpTo(pane: PaneLike, pos: Pos): void {
    const top = scrollTopFor(pane, pos);
    if (top === null) return;
    pane.el.scrollTop = top;
}

/** [data-chunk] 窗格的几何缓存：滚动路径每事件 3 处调 pages()，
 *  querySelectorAll+逐元素 offsetTop 在大文档上是 O(N) 读写——缓存到
 *  尺寸/内容变化。RO 只盯 scroller+body：块高变化必传导 body 高，
 *  content-visibility 块进视口撑回真实高度时逐块回调是首轮滚动
 *  风暴源（N 块 N 回调）；一次 body 回调已够失效缓存——罕见增减
 *  相抵不传导的场景留待下一次变化/重绑自愈。失效是惰性的
 *  （cache=null），重算只发生在下个读方帧，不在 RO 回调里同步算。
 *  MO 盯 body 直接子节点（innerHTML 整段替换 → 重绑锚集合）。
 *  无 RO 的环境退回手动 rebind 失效。 */
export interface ChunkGeom {
    pages(): PageGeom[];
    /** 内容写入/替换后调用：重绑观察目标并清缓存 */
    rebind(): void;
    /**
     * 局部内容改写（单段替换等）后调用：缓存即刻失效；锚集合刷新交给
     *  MO——childList 变化本就触发整绑，无需调用方再同步重绑一遍。
     *  无 MO 的环境退回整绑兜底（与 rebind 等价）。
     */
    invalidate(): void;
    dispose(): void;
}

export function bindChunkGeom(
    scroller: () => HTMLElement,
    body: () => HTMLElement,
): ChunkGeom {
    let els: HTMLElement[] = [];
    let cache: PageGeom[] | null = null;
    const invalidate = () => {
        cache = null;
    };
    const ro =
        typeof ResizeObserver === "function"
            ? new ResizeObserver(invalidate)
            : null;
    const mo =
        typeof MutationObserver === "function"
            ? new MutationObserver(() => rebind())
            : null;

    function rebind() {
        const b = body();
        els = [...b.querySelectorAll<HTMLElement>("[data-chunk]")];
        cache = null;
        ro?.disconnect();
        ro?.observe(scroller());
        ro?.observe(b);
        mo?.disconnect();
        mo?.observe(b, { childList: true });
    }

    return {
        pages() {
            return (cache ??= els.map((el, i) => ({
                page: i + 1,
                top: el.offsetTop,
                height: el.offsetHeight,
            })));
        },
        rebind,
        invalidate() {
            cache = null;
            if (!mo) rebind();
        },
        dispose() {
            ro?.disconnect();
            mo?.disconnect();
        },
    };
}

/**
 * chunk 窗格共享句柄：PaneLike + capture/jump/scrollTopFor/gotoPage/
 * setFontSize。HtmlPane/DomPane 同构——页码即 [data-chunk] 序（seq 1:1）。
 */
export interface ChunkPaneHandle extends PaneLike {
    gotoPage?(n: number): void;
    capture(): Pos;
    jump(pos: Pos): void;
    scrollTopFor(pos: Pos): number | null;
    /** html/dom 缩放落点：正文字号（px） */
    setFontSize?(px: number): void;
}

/** PaneLike + capture/jump/scrollTopFor/gotoPage/setFontSize 的共享构造 */
export function makeChunkPaneHandle(opts: {
    side: DocId;
    scroller: () => HTMLElement;
    body: () => HTMLElement;
    geom: { pages(): PageGeom[] };
}): ChunkPaneHandle {
    return {
        side: opts.side,
        get el() {
            return opts.scroller();
        },
        pages(): PageGeom[] {
            return opts.geom.pages();
        },
        capture() {
            return capturePos(this);
        },
        // 页码 = chunk 序：跳到第 n 段顶
        gotoPage(n) {
            jumpTo(this, { page: n, fraction: 0, viewport: 0 });
        },
        jump(pos) {
            jumpTo(this, pos);
        },
        scrollTopFor(pos) {
            return scrollTopFor(this, pos);
        },
        setFontSize(px) {
            opts.body().style.fontSize = `${px}px`;
        },
    };
}

export class SyncEngine {
    syncing = true;
    private dead = false;
    private scheduled = false;
    private pendingSrc: PaneLike | null = null;
    private ignoreTop = new WeakMap<HTMLElement, number>();
    private disposers: (() => void)[] = [];

    constructor(
        private A: PaneLike,
        private B: PaneLike,
        private map: PosMap,
    ) {
        for (const p of [A, B]) {
            const listener = () => this.onScroll(p);
            p.el.addEventListener("scroll", listener, { passive: true });
            this.disposers.push(() =>
                p.el.removeEventListener("scroll", listener),
            );
        }
    }

    dispose() {
        this.dead = true;
        for (const d of this.disposers) d();
        this.disposers = [];
    }

    /** 立即把 dst 对齐到 src 当前位置（开同步、模式切换、初次挂载后用） */
    alignNow(src: PaneLike) {
        const dst = src === this.A ? this.B : this.A;
        const target = this.map(capturePos(src), src.side);
        jumpTo(dst, target);
        this.ignoreTop.set(dst.el, dst.el.scrollTop);
    }

    private onScroll(src: PaneLike) {
        if (!this.syncing) return;
        const it = this.ignoreTop.get(src.el);
        if (it !== undefined && Math.abs(src.el.scrollTop - it) < 1) return; // 自己程序跳转的回声
        this.ignoreTop.delete(src.el);
        this.pendingSrc = src; // 同帧后到的事件覆盖——合帧后只同步最后一次
        if (this.scheduled) return;
        this.scheduled = true;
        raf(() => {
            this.scheduled = false;
            const s = this.pendingSrc;
            this.pendingSrc = null;
            if (!s || this.dead || !this.syncing) return;
            const pos = capturePos(s); // 帧时刻读最新位置——滚动突发合并为一次几何采样
            const dst = s === this.A ? this.B : this.A;
            const target = this.map(pos, s.side);
            const wanted = scrollTopFor(dst, target);
            if (wanted === null) return;
            if (Math.abs(dst.el.scrollTop - wanted) < 1) return; // 已就位，不制造回声
            dst.el.scrollTop = wanted;
            this.ignoreTop.set(dst.el, dst.el.scrollTop);
        });
    }
}
