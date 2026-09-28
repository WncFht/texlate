// features/inspect —— ⌘-Inspect 修饰键检视层（editor-grade inspect lane）：
// VS Code「修饰键=能力揭示开关」范式的最小移植——按住 accel（mac=⌘ /
// win+linux=Ctrl）即揭示可检视元素，⌘+click=原地 peek 卡，⌘+Alt+click=
// 对侧镜像跳（VS Code alternativeCommand 同构）。
//
//   手势矩阵（「吞」=capture 阶 preventDefault+stopPropagation 后无操作）：
//     cite 锚    ⌘+click→目标卡（bib→CiteCard / 他→UsagesCard）
//                ⌘+Alt→镜像跳目标侧同标
//     本体宿主   ⌘+click→UsagesCard（eq/sec/thm 元素由此获第一入口）
//                ⌘+Alt→镜像同 id 载体
//     阅读面空白 ⌘+click→吞（表 inspect 意图——截停 sentalign 兜底跳、
//                pdf.js 内链 onclick、dom 锚跳转默认）；落 math 放行
//                （copylatex 的 document 冒泡委托要收——吞=死点击）
//   揭示（armed）：.insp-armed 挂 .panes 根——纯 CSS（锚下划线/pdf 链锚
//     底线/.insp-t 宿主描边），零 JS 重排；松开/切窗即撤。armed 期
//     pointermove 60ms 节流 hover 强化（dom/html .insp-hot 单轨移标 /
//     pdf 容器 cursor:pointer）。
//
//   单闸拦截序（document capture click——先跑在 pdf.js onclick 属性处理
//   器与全部冒泡/捕获委托之前）：无 accel/e.detail=0/shift/卡内/控件/编辑
//   面/外链/活选区 → return；pane 定位失败/本侧 pdfjs armed → return；
//   alt 臂 inspectDestAt 有 dest → 吞+mirror；inspectAt handled → 吞；
//   math → return；阅读面内 → 吞；余 → return。
//   ⚠ 吞必 preventDefault：pdf.js 内链「不弹新标签」靠 onclick return
//   false——被截停后平台默认（⌘+click 新开标签复制 SPA）会复活。
import type { DocId } from "../alignment";

export interface InspectHandle {
    el: HTMLElement;
    bodyEl?(): HTMLElement | undefined;
    /** dom/html 臂 usages 索引——forEl 宿主命中探测（armed hover 强化用） */
    usageIndex?():
        | {
              forEl(
                  el: Element | null,
              ): { target: { el: HTMLElement; kind: string } } | undefined;
          }
        | undefined;
    /** pdf 臂 dest 命中探测（armed hover 强化用）——tol 走 inspect 紧容差 */
    destAtPoint?(x: number, y: number, tol?: number): string | null;
    /** pdf 臂非锚命中 → dest + 落点行带元素（armed hover 揭示染色面；
        分面容差在 pane 内消化——文字行级紧收/空白浮动体中窗+栏距闸） */
    destHotAt?(
        x: number,
        y: number,
    ): { dest: string; els: HTMLElement[] } | null;
    /** ⌘+click：坐标点 → 原地开检视卡；handled=false 由调用方按兜底语义走 */
    inspectAt?(x: number, y: number): boolean;
    /** ⌘+Alt+click：坐标点 → 对侧镜像载荷；null=该点无可镜像物 */
    inspectDestAt?(x: number, y: number): { dest: unknown } | null;
}

export interface InspectDeps {
    /** .panes 根——.insp-armed 揭示态的挂载点 */
    rootEl(): HTMLElement;
    handleOf(side: DocId): InspectHandle | undefined;
    /** 本侧 pdf.js 批注编辑 armed——armed 侧手势让行编辑多选（逐 pane 判） */
    pdfjsArmed?(side: DocId): boolean;
    /** 任意一侧 pdfjs armed 时压掉揭示态（编辑优先于 reveal） */
    anyPdfjsArmed?(): boolean;
    /** 有 live 选区时放行——选词/复制流不被检视吞 */
    hasLiveSelection?(): boolean;
    /** 对侧镜像跳（ReaderView.mirrorTo 包装：dst 侧 dest 落定 + 压栈） */
    mirror(dst: DocId, dest: unknown): void;
    enabled?(): boolean;
}

const ACCEL_IS_MAC = (() => {
    const nav = navigator as Navigator & {
        userAgentData?: { platform?: string };
    };
    const plat = nav.userAgentData?.platform ?? nav.platform ?? "";
    return /mac/i.test(plat);
})();

const isAccel = (e: MouseEvent | KeyboardEvent) =>
    ACCEL_IS_MAC ? e.metaKey : e.ctrlKey;

const otherSide = (s: DocId): DocId =>
    s === "original" ? "translated" : "original";

const normSide = (v: string | null | undefined): DocId | null =>
    v === "original" || v === "translated" ? v : null;

/** inspect 目的的命中容差——右击语境 0.4 是为「故意找锚」设计的，
    悬停/左击揭示用它会凭空生出假 affordance，收到 0.1。
    ⚠ 现仅作 dom/html 臂参考常量——pdf 臂命中已走 pane 内分面容差
    （PdfPane.inspectDestName：文字行级紧收/空白浮动体中窗+栏距闸） */
export const INSPECT_TOL = 0.1;

// 可检视锚的统一样式族：dom ltx 锚 / html cite 替身 / bib 条目键面 /
// pdf 注释覆盖层——armed 揭示 CSS 与 hover 强化共用这一族选择器
const ANCHOR_SEL =
    "a[href^='#'], .cite-ref, [data-bib-key], section.linkAnnotation a";
const CARD_CHROME_SEL =
    ".cite-card, .usage-card, .latex-card, button, input, textarea, select, [contenteditable='true']";
const EXT_LINK_SEL = "a[href^='http']";
const MATH_SEL = "math, .katex, mjx-container";
const TITLE_SEL = ".ltx_title, h1, h2, h3, h4, h5, h6";

const isTitleHit = (host: Element, el: Element | null) => {
    const t = el?.closest?.(TITLE_SEL);
    return t != null && host.contains(t);
};

export function attachInspect(deps: InspectDeps): { dispose(): void } {
    const doc = document;
    const win = doc.defaultView ?? window;
    let armed = false;
    let lastX = 0;
    let lastY = 0;
    let hotEls: Element[] = [];
    let curEl: HTMLElement | null = null;
    let moveTimer = 0;
    let pend: { x: number; y: number } | null = null;

    const clearFx = () => {
        for (const e of hotEls) e.classList.remove("insp-hot");
        hotEls = [];
        if (curEl) {
            curEl.style.cursor = "";
            curEl = null;
        }
    };

    /** armed 期 hover 强化：锚→锚标热；本体→宿主标热（section 限标题）；
        pdf 页内 dest 命中→落点行带标热 + 容器 cursor:pointer */
    const hoverEval = (x: number, y: number) => {
        let hots: Element[] = [];
        let cur: HTMLElement | null = null;
        const el = doc.elementFromPoint?.(x, y) ?? null;
        const side = normSide(
            el?.closest?.(".pane")?.getAttribute("data-side"),
        );
        const h = side ? deps.handleOf(side) : undefined;
        if (h && side && !deps.pdfjsArmed?.(side)) {
            const body = h.bodyEl?.();
            if (body) {
                if (el && body.contains(el)) {
                    const a = el.closest(ANCHOR_SEL);
                    if (a && body.contains(a)) {
                        hots = [a];
                    } else {
                        const entry = h.usageIndex?.()?.forEl(el);
                        const host = entry?.target.el;
                        if (
                            entry &&
                            host &&
                            (entry.target.kind !== "section" ||
                                isTitleHit(host, el))
                        ) {
                            hots = [host];
                        }
                    }
                }
            } else {
                const a = el?.closest?.("section.linkAnnotation a");
                if (a) {
                    hots = [a];
                } else if (el?.closest?.("[data-page-number]")) {
                    const hit = h.destHotAt?.(x, y);
                    if (hit) {
                        cur = h.el;
                        hots = hit.els;
                    }
                }
            }
        }
        if (hots.length !== hotEls.length || hots[0] !== hotEls[0]) {
            for (const e of hotEls) e.classList.remove("insp-hot");
            for (const e of hots) e.classList.add("insp-hot");
            hotEls = hots;
        }
        if (cur !== curEl) {
            if (curEl) curEl.style.cursor = "";
            if (cur) cur.style.cursor = "pointer";
            curEl = cur;
        }
    };

    const setArmed = (v: boolean) => {
        if (v === armed) return;
        armed = v;
        const reveal = v && !(deps.anyPdfjsArmed?.() ?? false);
        deps.rootEl().classList.toggle("insp-armed", reveal);
        if (v) {
            // 双路径等价：指针已停再按修饰键也要立即揭示热区
            hoverEval(lastX, lastY);
        } else {
            clearFx();
        }
    };

    const onKey = (e: KeyboardEvent) => {
        const a = isAccel(e);
        if (a !== armed) setArmed(a);
    };

    const onMove = (e: PointerEvent) => {
        lastX = e.clientX;
        lastY = e.clientY;
        if (!armed) return;
        if (moveTimer) {
            pend = { x: e.clientX, y: e.clientY };
            return;
        }
        hoverEval(e.clientX, e.clientY);
        moveTimer = win.setTimeout(() => {
            moveTimer = 0;
            const p = pend;
            pend = null;
            if (p) hoverEval(p.x, p.y);
        }, 60);
    };

    const onBlur = () => setArmed(false);
    const onVis = () => {
        if (doc.visibilityState !== "visible") setArmed(false);
    };

    /** 阅读面内判定：dom/html→bodyEl.contains；pdf→viewer 内且命中页壳 */
    const inSurface = (h: InspectHandle, t: Element) => {
        const body = h.bodyEl?.();
        if (body) return body.contains(t);
        return h.el.contains(t) && t.closest("[data-page-number]") != null;
    };

    const onClick = (e: MouseEvent) => {
        if (deps.enabled && !deps.enabled()) return;
        if (!isAccel(e)) return;
        if (e.detail === 0) return;
        // ⌘+Shift+click=浏览器前台新标签——原生语义让行
        if (e.shiftKey) return;
        const t = e.target as Element | null;
        if (!t?.closest) return;
        if (t.closest(CARD_CHROME_SEL)) return;
        if (t.closest(EXT_LINK_SEL)) return;
        if (deps.hasLiveSelection?.()) return;
        const side = normSide(t.closest(".pane")?.getAttribute("data-side"));
        if (!side) return;
        const h = deps.handleOf(side);
        if (!h) return;
        if (deps.pdfjsArmed?.(side)) return;
        const swallow = () => {
            e.preventDefault();
            e.stopPropagation();
        };
        const onMath = t.closest(MATH_SEL) != null;
        if (e.altKey) {
            const r = h.inspectDestAt?.(e.clientX, e.clientY) ?? null;
            if (r != null && r.dest != null) {
                swallow();
                deps.mirror(otherSide(side), r.dest);
                return;
            }
            if (onMath) return;
            if (inSurface(h, t)) swallow();
            return;
        }
        if (h.inspectAt?.(e.clientX, e.clientY)) {
            swallow();
            return;
        }
        if (onMath) return;
        if (inSurface(h, t)) swallow();
    };

    doc.addEventListener("keydown", onKey, true);
    doc.addEventListener("keyup", onKey, true);
    doc.addEventListener("pointermove", onMove, true);
    doc.addEventListener("click", onClick, true);
    win.addEventListener("blur", onBlur);
    doc.addEventListener("visibilitychange", onVis);

    return {
        dispose() {
            doc.removeEventListener("keydown", onKey, true);
            doc.removeEventListener("keyup", onKey, true);
            doc.removeEventListener("pointermove", onMove, true);
            doc.removeEventListener("click", onClick, true);
            win.removeEventListener("blur", onBlur);
            doc.removeEventListener("visibilitychange", onVis);
            if (moveTimer) {
                win.clearTimeout(moveTimer);
                moveTimer = 0;
            }
            setArmed(false);
            deps.rootEl().classList.remove("insp-armed");
            clearFx();
        },
    };
}
