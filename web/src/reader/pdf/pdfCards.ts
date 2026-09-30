// PdfPane 悬浮卡族——cite CiteCard + find-usages UsagesCard 的
// 生命周期（dwell 定时器簇/双卡互斥/跳回栈侧车）与 DOM 委托整片。
// use* 前缀即契约：必须在组件 owner 顶层同步调用（createSignal/
// createEffect/onCleanup 都要 owner——事件回调里懒调会静默泄漏监听）。
// 定时器簇与 panes/DomPane.tsx:146-155 同构——共享化抽取留后续工单，
// 本文件先保逐字搬；destAtPoint/viewer 等外部面一律 getter 注入。

import { createEffect, createSignal, onCleanup } from "solid-js";
import type { PDFSlick } from "@pdfslick/core";
import {
    anchorTextOf,
    citeAnchorOf,
    destLineText,
    destOf,
    type PdfPageDivOf,
} from "./pdfDom";
import { classifyDestName } from "../logic/citekind";
import {
    extractBibAtDest,
    extractRefIds,
    type BibEntry,
    type CiteIndex,
    type PdfDocLike,
    type RefMeta,
} from "../cite/citations";
import type { UsageEntry } from "../cite/usages";
import type { DestPointRow, DestSite } from "./pdfDestScan";
import type { KeptRef } from "../../api/client";
import { t } from "../../i18n";

export interface CardState {
    rect: DOMRect;
    dest: string;
    entry?: BibEntry;
    loading: boolean;
    notFound: boolean;
    seq: number;
}

export interface UcardState {
    rect: Pick<DOMRect, "left" | "right" | "top" | "bottom">;
    entry: UsageEntry;
}

export interface PdfCardsDeps {
    viewer(): PDFSlick["viewer"] | undefined;
    paneEl(): HTMLElement;
    pdfSlick(): PDFSlick | null;
    isDocumentLoaded(): boolean;
    pdfDoc(): PdfDocLike | null;
    /** idle 扫描表同一实例——labelAnchor 渲染播种的写入面也在这份上 */
    destNames: Set<string>;
    destSites: Map<string, DestSite[]>;
    destPoint: Map<string, DestPointRow>;
    pageDiv: PdfPageDivOf;
    citeIndex(): CiteIndex | undefined;
    /** L2 远端元数据回调（活访问器——回包晚于开卡时 props 才填好） */
    citeMeta(key: string): RefMeta | undefined;
    /** 本体右键反查 dest（inspect 工厂实现——getter 断开环依赖） */
    destAtPoint(x: number, y: number, tol?: number): string | null;
}

export interface PdfCards {
    card(): CardState | null;
    ucard(): UcardState | null;
    /** usages 卡跳转坐标侧车（页+锚顶 y）——开卡时重写的活数组 */
    usageJumps(): { page: number; y: number }[];
    /** 当前武装锚（hover/focus 去重 + Tab 送焦判定） */
    curAnchor(): Element | null;
    openCard(a: Element): void;
    openUsagesFor(
        target: Element | string | null,
        anchor: Element | null,
        at?: Pick<DOMRect, "left" | "right" | "top" | "bottom">,
    ): boolean;
    bumpCard(seq: number, patch: Partial<CardState>): void;
    citeKey(c: CardState): string;
    keepPayload(c: CardState): KeptRef;
    closeCard(): void;
    closeUcard(): void;
    /** 双卡互斥总收——导航/滚动/缩放/空白点击等灭卡点统一走这 */
    closeAll(): void;
    onCardEnter(): void;
    onCiteCardLeave(): void;
    onUsageCardLeave(): void;
}

export const usePdfCards = (deps: PdfCardsDeps): PdfCards => {
    // ---------- 引用悬浮卡 + 跳回栈（同锚双语义：hover=卡 / click=跳+压栈） ----------
    const [card, setCard] = createSignal<CardState | null>(null);
    // usages 卡（find-usages pdf 臂）——dest 反查 annot 站集开卡；
    // 跳转坐标（页+锚顶 y）与 entry.sites 序对齐存侧车
    const [ucard, setUcard] = createSignal<UcardState | null>(null);
    let usageJumps: { page: number; y: number }[] = [];
    let openTimer = 0;
    let closeTimer = 0;
    let cardSeq = 0;
    let curAnchor: Element | null = null;
    let lastTouch = false;
    // 开卡后短暂滚动宽限——tap/键盘 focus 半可见锚时浏览器 focus-scroll
    // 会把锚挪进视口（程序滚非用户滚），不宽限则开卡即被 scroll→close 杀
    let scrollGraceUntil = 0;
    const OPEN_DELAY = 150; // Wikipedia dwell——防扫过误开
    const CLOSE_DELAY = 350; // 宽限关——指针过卡缝/跨行锚 rect 间走不闪关

    const clearCardTimers = () => {
        window.clearTimeout(openTimer);
        window.clearTimeout(closeTimer);
        openTimer = closeTimer = 0;
    };
    const closeCard = () => {
        clearCardTimers();
        curAnchor = null;
        setCard(null);
    };
    const closeUcard = () => {
        setUcard(null);
    };
    // 双卡互斥（开一方收另一方）——导航/滚动/缩放/空白点击等灭卡点统一收
    const closeAll = () => {
        closeCard();
        closeUcard();
    };

    const bumpCard = (seq: number, patch: Partial<CardState>) =>
        setCard((c) => (c && c.seq === seq ? { ...c, ...patch } : c));

    const openCard = (a: Element) => {
        // dwell 期间 annotationLayer 可能被逐出/重建（主题 reset、LRU）——
        // 死锚 getBoundingClientRect 全零会让卡落在视口左上
        if (!a.isConnected) return;
        const dest = destOf(a);
        // v1 只出 cite.* 卡——figure./section. 等其它 dest 只跳不卡
        if (!dest || !dest.startsWith("cite.")) return;
        closeUcard(); // 卡族互斥（dom 臂同约）
        const entry = deps.citeIndex()?.lookup(dest);
        const seq = ++cardSeq;
        curAnchor = a;
        scrollGraceUntil = performance.now() + 600;
        setCard({
            rect: a.getClientRects()[0] ?? a.getBoundingClientRect(),
            dest,
            entry,
            loading: !entry,
            notFound: false,
            seq,
        });
        if (entry) return;
        // ph 索引未命中 → dest 懒抽取（.bbl/无 ph 链：cite.* 锚仍在）
        const doc = deps.pdfDoc();
        if (!doc) {
            bumpCard(seq, { loading: false, notFound: true });
            return;
        }
        void extractBibAtDest(doc, dest)
            .then((hit) => {
                if (!hit) {
                    bumpCard(seq, { loading: false, notFound: true });
                    return;
                }
                const ids = extractRefIds(hit.text);
                bumpCard(seq, {
                    loading: false,
                    entry: {
                        key: dest.slice(5),
                        order: 0,
                        label: "",
                        text: hit.text,
                        ...ids,
                    },
                });
            })
            .catch(() => bumpCard(seq, { loading: false, notFound: true }));
    };

    /** 卡标题派生：锚印刷文本拿不出像样的词（锚面只罩 "(“等碎片）时，
        用 dest 落点行印刷文本兜底——eq 抓 "(N)"，浮动体抓「图 N/表 N/
        Figure N」类标签词，兜底行首 4 词 */
    const destRowLabel = (dest: string, kind: string): string => {
        const pt = deps.destPoint.get(dest);
        if (!pt) return "";
        const line = destLineText(
            deps.pageDiv,
            pt.page,
            pt.frac,
            pt.fx ?? undefined,
        );
        if (!line) return "";
        if (kind === "equation") {
            const m = /\(\s*\d{1,3}[a-zA-Z]?\s*\)/.exec(line);
            if (m) return m[0].replace(/\s+/g, "");
        }
        const m =
            /(Fig(?:ure)?s?\.?|Tab(?:le)?s?\.?|Sec(?:tion)?s?\.?|Eq(?:uation)?s?\.?|Theorem|Lemma|Proposition|Corollary|Algorithm|Appendix|图|表|式|节|章|定理|引理|命题|推论|算法|附录)\s*[\w.:-]{0,10}/.exec(
                line,
            );
        if (m) return m[0].trim();
        return line.split(/\s+/).slice(0, 4).join(" ");
    };

    /** find-usages pdf 臂：任意 named dest 反查全页 link annot 站集 →
        UsagesCard。target=hit.cite.targetId（"cite.key"/"figure.caption.3"
        皆收）或元素；站点 text=页码+引用行语境（懒渲页无行回退 p.N）。
        非 cite 族 kind/label 按 dest 分类+锚/落点行印刷文本 */
    const openUsagesFor = (
        target: Element | string | null,
        anchor: Element | null,
        at?: Pick<DOMRect, "left" | "right" | "top" | "bottom">,
    ): boolean => {
        const raw =
            typeof target === "string"
                ? target
                : ((target as Element | null)?.id ?? "");
        const key = raw.startsWith("cite.") ? raw.slice(5) : raw;
        if (!key) return false;
        // dest 词表三族候选：cite.<key> 主流 / 裸 <key> / bib.<key>——
        // 命中族同时决定「跳到目标本身」的 dest
        const cands = raw.includes(".")
            ? [raw]
            : [`cite.${key}`, `bib.${key}`, key];
        const destName =
            cands.find((d) => deps.destSites.get(d)?.length) ??
            cands.find((d) => deps.destNames.has(d)) ??
            cands[0]!;
        const sites = deps.destSites.get(destName) ?? [];
        usageJumps = sites;
        // 图/表/式锚的 dest 尾号≠印刷编号（figure.caption.11 可能是「图 1」）
        // ——label 取锚矩形下 textLayer 的印刷文本（"Fig. 3"/"表 1"/"(4)"；
        // 批注层 <a> 是无文本空元素）；锚面只有标点碎片时落点行兜底
        // （"(" 实证：eq 号 span 按字切块，锚面只罩住开括号）；bib 照旧 key
        const kind = classifyDestName(destName);
        let label = kind === "bib" ? key : anchorTextOf(anchor);
        if (
            kind !== "bib" &&
            (!label || label.length < 2 || !/[\p{L}\p{N}]/u.test(label))
        )
            label = destRowLabel(destName, kind) || label || key;
        const entry: UsageEntry = {
            target: {
                kind,
                el: null as unknown as HTMLElement,
                // id=解析后 dest 名（onJumpTarget 直用作 goToDestination
                // 参数）
                id: destName,
                label,
            },
            sites: sites.map((s, i) => ({
                text:
                    s.frac != null
                        ? `p.${s.page} · ${destLineText(deps.pageDiv, s.page, s.frac, s.fx).slice(0, 60) || "…"}`
                        : `p.${s.page}`,
                zhText: null,
                anchors: [
                    {
                        id: destName,
                        ord: i,
                        chunkOrd: -1,
                        charOff: -1,
                        seq: null,
                    },
                ],
                block: null,
                order: i,
                seq: null,
            })),
        };
        const a = anchor as HTMLElement | null;
        // at（右键落点矩形）优先——本体右键无锚元素，卡要落在点击点上
        // 而不是锚 span/容器角
        const rect =
            at ??
            (a?.isConnected
                ? (a.getClientRects()[0] ?? a.getBoundingClientRect())
                : (deps.viewer()?.container?.getBoundingClientRect() ?? null));
        if (!rect) return false;
        closeCard();
        scrollGraceUntil = performance.now() + 600;
        setUcard({ rect, entry });
        return true;
    };

    /** kept payload（M4）：卡 key = entry.key（ph 索引/懒抽取路都填
        dest 尾）；meta 收此刻 L2 快照——迟到的回包不追灌 */
    const citeKey = (c: CardState) => c.entry?.key ?? c.dest.slice(5);
    const keepPayload = (c: CardState): KeptRef => {
        const e = c.entry;
        return {
            label: e?.label || undefined,
            text: e?.text || undefined,
            arxivId: e?.arxivId,
            doi: e?.doi,
            meta: deps.citeMeta(citeKey(c)),
        };
    };

    // 卡沿开收——原 JSX 内联 handler 提升（closeTimer 私态不出域，
    // 语义与原内联体逐字同）
    const onCardEnter = () => {
        window.clearTimeout(closeTimer);
    };
    const onCiteCardLeave = () => {
        window.clearTimeout(closeTimer);
        closeTimer = window.setTimeout(closeCard, CLOSE_DELAY);
    };
    const onUsageCardLeave = () => {
        window.clearTimeout(closeTimer);
        closeTimer = window.setTimeout(closeAll, CLOSE_DELAY);
    };

    // 悬浮卡委托：pointerover/out 在容器上冒泡统收（enter/leave 不冒泡）；
    // focusin/out 挂 paneEl（卡在 viewer 容器外，焦点锚→卡→卡外三段路都要
    // 看得见）；触屏 tap 走 click capture 拦截出卡。
    // aria-label 由 MO 渐进注入——.linkAnnotation>a 是无文本空元素。
    createEffect(() => {
        const s = deps.pdfSlick();
        if (!s || !deps.isDocumentLoaded()) return;
        const container = s.viewer.container;
        const paneEl = deps.paneEl();

        // 悬停/触屏/键盘强入口的 dest 类分派：bib→CiteCard；浮动体+式+定理
        // →UsagesCard（"被引用在哪"正是用户要的面）；section/other 不进门
        // ——sec 引用密、悬停即弹太吵，走右键 cite.usages
        const USAGE_HOVER = new Set(["figure", "table", "equation", "theorem"]);
        const destLane = (a: Element): "bib" | "usage" | null => {
            const dest = destOf(a);
            if (!dest) return null;
            const kind = classifyDestName(dest);
            if (kind === "bib") return "bib";
            return USAGE_HOVER.has(kind) ? "usage" : null;
        };

        const scheduleOpen = (a: Element) => {
            const lane = destLane(a);
            const dest = destOf(a);
            if (!lane || !dest) return;
            window.clearTimeout(openTimer);
            openTimer = window.setTimeout(() => {
                openTimer = 0; // 发后即清零——同锚复悬才能再排程
                if (!a.isConnected) return;
                if (lane === "bib") openCard(a);
                else openUsagesFor(dest, a);
            }, OPEN_DELAY);
        };
        const scheduleClose = () => {
            window.clearTimeout(closeTimer); // 重入必须撤旧定时器
            closeTimer = window.setTimeout(closeAll, CLOSE_DELAY);
        };

        const onOver = (e: PointerEvent) => {
            if (e.pointerType === "touch") return; // tap=卡走 click 路
            const a = citeAnchorOf(e.target);
            if (!a) return;
            // 非卡面锚不进门——否则 curAnchor 被非卡锚占住，卡开排程受阻
            if (!destLane(a)) return;
            if (a === curAnchor) {
                // 同锚复悬/跨行 rect 间走——只续不关（isUserDwelling 同款）；
                // 卡未开且定时器已逝（openCard 早退路径）要补排程
                window.clearTimeout(closeTimer);
                if (!card() && !ucard() && !openTimer) scheduleOpen(a);
                return;
            }
            clearCardTimers();
            curAnchor = a;
            scheduleOpen(a);
        };
        const onOut = (e: PointerEvent) => {
            const rel = e.relatedTarget as Element | null;
            if (rel?.closest?.(".cite-card, .usage-card")) return; // 指针进卡不关
            if (rel === curAnchor) return;
            const a = citeAnchorOf(e.target);
            if (a) {
                window.clearTimeout(openTimer);
                scheduleClose();
                return;
            }
            // 卡开着时「任意 pointerout→scheduleClose」会被 DOM 更迭噪声打死：右键
            // 本体开卡瞬间 pdf.js 的 selectionRendering 重排 textLayer 节点，
            // 指针原地不动也吐 pointerout（rel=非卡元素）——开卡宽限窗内
            // 只认真锚离开，噪声窗后恢复正常宽限关
            if ((card() || ucard()) && performance.now() >= scrollGraceUntil)
                scheduleClose();
        };
        const onFocusIn = (e: FocusEvent) => {
            const a = citeAnchorOf(e.target);
            if (!a) return;
            // 指针点击引发的 focus 不出卡（:focus-visible 只对键盘 focus 成立）
            if (!(a instanceof HTMLElement) || !a.matches(":focus-visible"))
                return;
            const lane = destLane(a);
            const dest = destOf(a);
            if (!lane || !dest) return;
            clearCardTimers();
            curAnchor = a;
            // 键盘 focus 等效 hover——dwell 从略
            if (lane === "bib") openCard(a);
            else openUsagesFor(dest, a);
        };
        const onFocusOut = (e: FocusEvent) => {
            const rel = e.relatedTarget as Element | null;
            if (rel?.closest?.(".cite-card, .usage-card")) return;
            if (!citeAnchorOf(e.target) && !card() && !ucard()) return;
            // 开卡宽限窗内焦点迁移多半是平台噪声（右键/菜单焦点让渡），
            // 与 onOut 同闸
            if (performance.now() < scrollGraceUntil) return;
            scheduleClose();
        };
        const onPointerDown = (e: PointerEvent) => {
            lastTouch = e.pointerType === "touch";
        };
        const onClickCapture = (e: MouseEvent) => {
            const t0 = e.target as Element | null;
            if (t0?.closest?.(".cite-card, .usage-card")) return; // 卡内点击归卡自己
            const a = citeAnchorOf(t0);
            if (!a) {
                if (card() || ucard()) closeAll(); // 点窗格空白处即收卡
                return;
            }
            const dest = destOf(a);
            // detail=0 是键盘/AT 合成的 click——保持跳转语义不截卡
            if (lastTouch && e.detail !== 0 && dest) {
                const lane = destLane(a);
                if (lane) {
                    // 触屏 tap=出卡：capture 期 stopPropagation——事件到不了
                    // target，onclick 属性处理器（goToDestination）根本不触发
                    e.stopPropagation();
                    e.preventDefault();
                    clearCardTimers();
                    curAnchor = a;
                    if (lane === "bib") openCard(a);
                    else openUsagesFor(dest, a);
                    return;
                }
            }
            closeAll(); // 鼠标 click=跳——卡随跳收
        };
        // 卡在 paneEl 内但 DOM 序远离锚——Tab 默认会先遍历后续所有链接才到
        // 卡。锚上按 Tab 直接把焦点送进卡内首个可焦点件
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key !== "Tab" || e.shiftKey) return;
            if (!card() || document.activeElement !== curAnchor) return;
            const el = paneEl.querySelector<HTMLElement>(
                ".cite-card button, .cite-card a[href]",
            );
            if (!el) return;
            e.preventDefault();
            el.focus();
        };

        const onScrollClose = () => {
            if (performance.now() < scrollGraceUntil) return;
            closeAll();
        };
        // 图/表/式/定理等本体右键 → 直开 usages 卡（dom 臂
        // attachUsages.onContextMenu 同语义、contextmenu 全类规格）。
        // 让行：shift=原生菜单；链锚=ctxm 菜单（cite.usages 项）；无
        // dest 命中=ctxm 常规菜单。命中才 preventDefault+stopPropagation
        // ——.panes 上的 ctxm 委托收不到，浏览器原生菜单也不弹
        const onCtxMenu = (e: MouseEvent) => {
            if (e.shiftKey) return;
            if (citeAnchorOf(e.target)) return;
            const dest = deps.destAtPoint(e.clientX, e.clientY);
            if (!dest) return;
            e.preventDefault();
            e.stopPropagation();
            // 卡锚=点击点小矩形；文本片命中时 span 兼作 label 语境源
            // （anchorTextOf 捞印刷体「Fig. 3」）
            const span =
                (e.target as Element | null)?.closest?.(".textLayer span") ??
                null;
            openUsagesFor(dest, span, {
                left: e.clientX - 1,
                right: e.clientX + 1,
                top: e.clientY - 1,
                bottom: e.clientY + 1,
            });
        };
        container.addEventListener("pointerover", onOver);
        container.addEventListener("pointerout", onOut);
        container.addEventListener("pointerdown", onPointerDown, true);
        container.addEventListener("click", onClickCapture, true);
        container.addEventListener("contextmenu", onCtxMenu);
        container.addEventListener("scroll", onScrollClose, { passive: true });
        paneEl.addEventListener("focusin", onFocusIn);
        paneEl.addEventListener("focusout", onFocusOut);
        paneEl.addEventListener("keydown", onKeyDown);
        const bus = s.eventBus;
        bus.on("scalechanging", closeAll);
        bus.on("pagesdestroy", closeAll);
        // 只扫增量 addedNodes——全容器 qSA 在滚动翻页期是每批 mutation
        // O(全锚) 的热路径浪费
        const labelAnchor = (a: HTMLAnchorElement) => {
            const dest = destOf(a);
            // 渲染即播种 destNames——cite.targetExists 不等 idle 全扫
            if (dest) deps.destNames.add(dest);
            if (a.hasAttribute("aria-label")) return;
            if (!dest?.startsWith("cite.")) return;
            const entry = deps.citeIndex()?.lookup(dest);
            a.setAttribute(
                "aria-label",
                t.cite.linkAria.replace("{n}", entry?.label ?? dest.slice(5)),
            );
        };
        const ANCHOR_SEL = "section.linkAnnotation a[href^='#']";
        const mo = new MutationObserver((records) => {
            for (const rec of records) {
                for (const node of rec.addedNodes) {
                    if (!(node instanceof Element)) continue;
                    if (
                        node instanceof HTMLAnchorElement &&
                        node.matches(ANCHOR_SEL)
                    )
                        labelAnchor(node);
                    for (const a of node.querySelectorAll<HTMLAnchorElement>(
                        ANCHOR_SEL,
                    ))
                        labelAnchor(a);
                }
            }
        });
        mo.observe(container, { childList: true, subtree: true });
        onCleanup(() => {
            container.removeEventListener("pointerover", onOver);
            container.removeEventListener("pointerout", onOut);
            container.removeEventListener("pointerdown", onPointerDown, true);
            container.removeEventListener("click", onClickCapture, true);
            container.removeEventListener("contextmenu", onCtxMenu);
            container.removeEventListener("scroll", onScrollClose);
            paneEl.removeEventListener("focusin", onFocusIn);
            paneEl.removeEventListener("focusout", onFocusOut);
            paneEl.removeEventListener("keydown", onKeyDown);
            bus.off("scalechanging", closeAll);
            bus.off("pagesdestroy", closeAll);
            mo.disconnect();
            clearCardTimers();
        });
    });

    return {
        card,
        ucard,
        usageJumps: () => usageJumps,
        curAnchor: () => curAnchor,
        openCard,
        openUsagesFor,
        bumpCard,
        citeKey,
        keepPayload,
        closeCard,
        closeUcard,
        closeAll,
        onCardEnter,
        onCiteCardLeave,
        onUsageCardLeave,
    };
};
