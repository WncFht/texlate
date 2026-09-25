// anim —— 句对位动效层（sent-align v1.6 动效臂）。
// 三件套：press 点击涟漪 / land 连线+行擦入 / cancelLand 清场。
//
// 设计约束：
//   - 全部 position:fixed + transform/opacity —— 不触 textLayer 几何，
//     零重排（sa-* 既有面同款「background/box-shadow 落笔」纪律）。
//   - prefers-reduced-motion 全域降级——涟漪/连线/擦入全不产，静态
//     落点提示本就由 sa-flash 承担（css 面另有 0.6s 降时兜底）。
//   - 单轨——land 在飞时新 land 当场清算旧连线/擦入（sa-flash 单轨同款）。

/** 落点元素 → 行级矩形组：逐行 getClientRects、按 (top,height) 圆整
    归行并集（同 sid 被 em/a 切成同行多片时擦入须盖整段行幅——只留
    首片会把句尾截掉）、滤掉零尺寸壳（markedContent 容器级）。 */
export function lineRects(els: Iterable<Element>): DOMRect[] {
    const rows = new Map<
        string,
        { top: number; left: number; right: number; height: number }
    >();
    for (const el of els) {
        for (const r of el.getClientRects()) {
            if (r.width < 2 || r.height < 2) continue;
            const k = `${Math.round(r.top)}|${Math.round(r.height)}`;
            const g = rows.get(k);
            if (g) {
                g.left = Math.min(g.left, r.left);
                g.right = Math.max(g.right, r.right);
            } else {
                rows.set(k, {
                    top: r.top,
                    left: r.left,
                    right: r.right,
                    height: r.height,
                });
            }
        }
    }
    return [...rows.values()]
        .sort((a, b) => a.top - b.top || a.left - b.left)
        .map(
            (g) => new DOMRect(g.left, g.top, g.right - g.left, g.height),
        );
}

const reduceMotion = (): boolean =>
    typeof matchMedia === "function" &&
    matchMedia("(prefers-reduced-motion: reduce)").matches;

const SVG_NS = "http://www.w3.org/2000/svg";
const WIPE_MAX_LINES = 8;
const WIPE_STAGGER_MS = 40;
const ARC_TOTAL_MS = 1100;

let arcSvg: SVGSVGElement | null = null;
let wipeEls: HTMLElement[] = [];
let rippleEl: HTMLElement | null = null;
let landTimer = 0;

/** 点击 ack——源侧落点扩散环（~380ms scale+fade，纯 transform）。 */
export function press(x: number, y: number): void {
    if (reduceMotion()) return;
    const d = document.createElement("div");
    d.className = "sa-ripple";
    d.style.left = `${x}px`;
    d.style.top = `${y}px`;
    document.body.append(d);
    rippleEl = d;
    window.setTimeout(() => {
        d.remove();
        if (rippleEl === d) rippleEl = null;
    }, 420);
}

const clearWipe = (): void => {
    for (const el of wipeEls) el.remove();
    wipeEls = [];
};

/** 连线/擦入面清场（不动涟漪——按下 ack 生命期自理，且应盖过连线并存）。 */
const clearLandFx = (): void => {
    window.clearTimeout(landTimer);
    landTimer = 0;
    arcSvg?.remove();
    arcSvg = null;
    clearWipe();
};

/** 全摘——连线 svg + 擦入盖层 + 在飞涟漪（视图销毁口径；land 单轨
    只走 clearLandFx——press→land 同帧时杀涟漪会把按下 ack 截没）。 */
export function cancelLand(): void {
    clearLandFx();
    rippleEl?.remove();
    rippleEl = null;
}

/** 落句动效——行擦入（逐行 overlay scaleX 0→1，stagger 依读序）
    + 连线（源点 → 首个视口内行左缘中的三次贝塞尔，stroke-dashoffset
    描入→停→随 svg 渐隐）。els 是落句渲染元素集（pdf marked 叶/
    dom sid span），矩形在此刻取——调用方保证已过滚动落定帧。
    from=null（非点击跳如右键 gotoPeer）→ 只擦不连——无从谈起源点。 */
export function land(
    from: { x: number; y: number } | null,
    els: Element[],
): void {
    clearLandFx();
    if (reduceMotion()) return;
    const rects = lineRects(els);
    if (!rects.length) return;
    for (const [i, r] of rects.slice(0, WIPE_MAX_LINES).entries()) {
        const d = document.createElement("div");
        d.className = "sa-wipe";
        d.style.left = `${r.left}px`;
        d.style.top = `${r.top}px`;
        d.style.width = `${r.width}px`;
        d.style.height = `${r.height}px`;
        d.style.animationDelay = `${i * WIPE_STAGGER_MS}ms`;
        document.body.append(d);
        wipeEls.push(d);
    }
    if (from) {
        // 跨页 seq 首行可能在视口外——连线指到看不见的点不如指首个可见行
        const t =
            rects.find(
                (r) => r.bottom > 0 && r.top < window.innerHeight,
            ) ?? rects[0]!;
        const x0 = from.x;
        const y0 = from.y;
        const x1 = t.left;
        const y1 = t.top + t.height / 2;
        const dx = x1 - x0;
        const svg = document.createElementNS(SVG_NS, "svg");
        svg.setAttribute("class", "sa-arc-svg");
        const path = document.createElementNS(SVG_NS, "path");
        path.setAttribute(
            "d",
            `M ${x0} ${y0} C ${x0 + dx * 0.4} ${y0}, ${x1 - dx * 0.4} ${y1}, ${x1} ${y1}`,
        );
        path.setAttribute("class", "sa-arc-path");
        path.setAttribute("pathLength", "1");
        svg.append(path);
        document.body.append(svg);
        arcSvg = svg;
    }
    landTimer = window.setTimeout(clearLandFx, ARC_TOTAL_MS);
}
