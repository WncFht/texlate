// 双栏滚动同步引擎 —— docs/research/product/web-layer.md §5.3 伪码落地。
// 纯 TS、框架无关：PdfPane / HtmlPane 都实现 PaneLike 即可接入。
// 要点（texglot 先例）：20% 焦点线、viewport 字段保持锚点屏幕高度、
// ignoreTop 吞程序跳转回声、rAF+epoch 合帧丢弃过期滚动。

import type { Pos, PosMap, Side } from "./alignment";

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

const raf: (cb: FrameRequestCallback) => void =
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
    const p = [...pages].reverse().find((pg) => pg.top <= focus) ?? pages[0];
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
    return p.top + pos.fraction * p.height - (pos.viewport ?? 0) * pane.el.clientHeight;
}

export function jumpTo(pane: PaneLike, pos: Pos): void {
    const top = scrollTopFor(pane, pos);
    if (top === null) return;
    pane.el.scrollTop = top;
}

export class SyncEngine {
    syncing = true;
    private epoch = 0;
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
            this.disposers.push(() => p.el.removeEventListener("scroll", listener));
        }
    }

    dispose() {
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

    /** 当前 src 位置映射出的 dst 期望 scrollTop（>500px 漂移提示用） */
    expectedTop(src: PaneLike): number | null {
        const dst = src === this.A ? this.B : this.A;
        return scrollTopFor(dst, this.map(capturePos(src), src.side));
    }

    counterpart(p: PaneLike): PaneLike {
        return p === this.A ? this.B : this.A;
    }

    private onScroll(src: PaneLike) {
        if (!this.syncing) return;
        const it = this.ignoreTop.get(src.el);
        if (it !== undefined && Math.abs(src.el.scrollTop - it) < 1) return; // 自己程序跳转的回声
        this.ignoreTop.delete(src.el);
        const pos = capturePos(src);
        const e = ++this.epoch;
        const dst = src === this.A ? this.B : this.A;
        raf(() => {
            if (e !== this.epoch || !this.syncing) return; // 合帧 + epoch 丢弃过期
            const target = this.map(pos, src.side);
            const wanted = scrollTopFor(dst, target);
            if (wanted === null) return;
            if (Math.abs(dst.el.scrollTop - wanted) < 1) return; // 已就位，不制造回声
            dst.el.scrollTop = wanted;
            this.ignoreTop.set(dst.el, dst.el.scrollTop);
        });
    }
}
