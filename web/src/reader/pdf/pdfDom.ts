// PdfPane DOM 纯工具——拆自 PdfPane.tsx，零 Solid 依赖可单测。
// bandEls* 族经 pageDiv 访问器断开 viewer() 耦合（页号 → 已渲染页 div）。

import { colOf, COL_X_SPLIT, type Pos } from "../logic/alignment";

/** 页号(1 基) → 已渲染页 div（viewer._pages 桥；未渲染/未就位 undefined） */
export type PdfPageDivOf = (page: number) => HTMLElement | undefined;

// 容器 → 有形叶子：display:contents 元素自身无盒不可染，递归取
// 无元素子级的后代；裸文本容器（无子级）按叶子计——染了看不见但
// 不挡同组其余叶子
export const leafEls = (el: HTMLElement): HTMLElement[] => {
    const kids = el.children;
    if (!kids.length) return [el];
    const out: HTMLElement[] = [];
    for (const k of kids) out.push(...leafEls(k as HTMLElement));
    return out;
};

/** linkAnnotation a[href="#<dest>"] → decode 后的 named dest。
    pdf.js getDestinationHash 用 escape() 编码——非 ASCII bibkey 出
    %uXXXX/%FC 形式，decodeURIComponent 抛 → 退 unescape 对齐回原串 */
export const destOf = (a: Element): string | null => {
    const href = a.getAttribute("href") ?? "";
    if (!href.startsWith("#")) return null;
    const h = href.slice(1);
    try {
        return decodeURIComponent(h);
    } catch {
        try {
            return unescape(h);
        } catch {
            return h;
        }
    }
};

export const citeAnchorOf = (t: EventTarget | null): Element | null =>
    (t as Element | null)?.closest?.("section.linkAnnotation a[href^='#']") ??
    null;

/** 批注锚矩形覆盖的印刷文本——<a> 是无文本空元素、caretRangeFromPoint
    不穿透批注层；取同页 .textLayer 相交 span 内逐字 Range 矩形扫描，
    只留真被锚矩形覆盖的字符（行级 span 也能精确切出 "Fig. 3B"）。 */
export const anchorTextOf = (a: Element | null): string => {
    if (!a?.isConnected) return "";
    const r = a.getBoundingClientRect();
    if (!r.width || !r.height) return "";
    const page = a.closest("[data-page-number]");
    if (!page) return "";
    const rng = a.ownerDocument.createRange();
    const out: string[] = [];
    for (const span of page.querySelectorAll(".textLayer span")) {
        const s = span.getBoundingClientRect();
        const overlap =
            s.bottom > r.top + 1 &&
            s.top < r.bottom - 1 &&
            s.right > r.left &&
            s.left < r.right;
        if (!overlap) continue;
        const tn = span.firstChild;
        if (!tn || tn.nodeType !== 3) continue;
        const text = tn.textContent ?? "";
        let lo = -1;
        let hi = -1;
        for (let i = 0; i < text.length; i++) {
            rng.setStart(tn, i);
            rng.setEnd(tn, i + 1);
            const cr = rng.getBoundingClientRect();
            const hit =
                cr.right > r.left &&
                cr.left < r.right &&
                cr.bottom > r.top &&
                cr.top < r.bottom;
            if (hit) {
                if (lo < 0) lo = i;
                hi = i;
            } else if (lo >= 0 && cr.left > r.right) break;
        }
        if (lo >= 0) {
            let s = text.slice(lo, hi + 1);
            // 锚面只罩编号（Fig.~\ref 链面="6C"）——紧前方的
            // 标签词捞回来，卡片标题才读得出「图 6C」
            const before = text.slice(Math.max(0, lo - 16), lo);
            const m =
                /(?:Fig(?:ure)?s?|Tab(?:le)?|Eq(?:n|uation)?s?|Theorems?|Thm|Lemmas?|图|表|式|定理|命题|引理|推论)\.?\s*$/.exec(
                    before,
                );
            if (m) s = m[0] + s;
            out.push(s);
        }
    }
    return out.join(" ").replace(/\s+/g, " ").trim();
};

// Pos → 分位行带元素集（flashAtPos/hoverSeq 共用取带面）：命中页
// textLayer 按 offsetTop 分位取行；pos.x 在场收窄到同栏半区（右栏
// 落点不染同 y 左栏行），收窄空集（缝带点击）落回整带兜底
export const bandElsAt = (pageDiv: PdfPageDivOf, pos: Pos): HTMLElement[] => {
    const div = pageDiv(pos.page);
    if (!div) return [];
    const y = pos.fraction * div.offsetHeight;
    const band = [
        ...div.querySelectorAll<HTMLElement>(".textLayer span"),
    ].filter((sp) => sp.offsetTop <= y && y < sp.offsetTop + sp.offsetHeight);
    const wantCol = colOf(pos) === 1;
    const els =
        pos.x == null
            ? band
            : band.filter(
                  (sp) =>
                      (sp.offsetLeft + sp.offsetWidth / 2) / div.offsetWidth >=
                          COL_X_SPLIT ===
                      wantCol,
              );
    if (els.length) return els;
    if (pos.x != null && band.length) return band;
    return [];
};

/** 落点行带微探：锚分位取自批注矩形顶缘，常悬在行带上沿白缝——
    ±8/16px 步移取首个非空行带（destHotAt 揭示面/destLineText 共用） */
export const bandElsNear = (
    pageDiv: PdfPageDivOf,
    page: number,
    frac: number,
    fx?: number,
): HTMLElement[] => {
    for (const d of [0, 0.008, -0.008, 0.016, -0.016]) {
        const els = bandElsAt(pageDiv, {
            page,
            fraction: Math.min(Math.max(frac + d, 0), 1),
            x: fx,
        });
        if (els.length) return els;
    }
    return [];
};

/** dest 落点行文本——卡标题/站语境的原料（bandElsNear 同栏收窄同法） */
export const destLineText = (
    pageDiv: PdfPageDivOf,
    page: number,
    frac: number,
    fx?: number,
) =>
    bandElsNear(pageDiv, page, frac, fx)
        .map((e) => e.textContent ?? "")
        .join("")
        .replace(/\s+/g, " ")
        .trim();

// rail/侧栏/浮层等窗格 chrome 区的滚轮转给文档滚动口——滚轮语义
// 是「滚动本窗格文档」，不该死在 34px 窄条上。命中的侧件自身可滚
// （thumbs/outline/docinfo）时让给它，滚到头再链回文档；
// ctrl/meta+wheel 是缩放语义不抢。转发写 scrollTop 会触发容器
// scroll 事件——持久化/漂移/同步引擎走同一条路径，语义一致。
// 返回卸载函数（宿主 onCleanup 收）。
export const attachWheelForward = (
    paneEl: HTMLElement,
    containerOf: () => HTMLElement | undefined,
): (() => void) => {
    const onWheel = (e: WheelEvent) => {
        if (e.ctrlKey || e.metaKey) return;
        const container = containerOf();
        if (!container) return;
        let node = e.target as Element | null;
        if (!node || container.contains(node)) return;
        while (node && node !== paneEl) {
            if (node instanceof HTMLElement) {
                const oy = getComputedStyle(node).overflowY;
                if (
                    (oy === "auto" || oy === "scroll") &&
                    node.scrollHeight > node.clientHeight + 1
                ) {
                    const room = node.scrollHeight - node.clientHeight;
                    if (
                        (e.deltaY > 0 && node.scrollTop < room - 1) ||
                        (e.deltaY < 0 && node.scrollTop > 1)
                    )
                        return;
                }
            }
            node = node.parentElement;
        }
        const k = e.deltaMode === 1 ? 16 : 1; // Firefox 行单位滚轮
        container.scrollTop += e.deltaY * k;
        container.scrollLeft += e.deltaX * k;
    };
    paneEl.addEventListener("wheel", onWheel, { passive: true });
    return () => paneEl.removeEventListener("wheel", onWheel);
};
