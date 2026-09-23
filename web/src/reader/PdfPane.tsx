// PdfPane —— usePDFSlick 封装，向 SyncEngine 暴露 PaneLike 几何接口。
// 规格须知（§5.1）：usePDFSlick 不做实例清理，url 变化会叠第二个实例——
// 因此本组件由调用方按 doc.version 整体重挂（keyed），绝不原位换 url。
//
// 侧件布局：左 rail（缩略图/大纲/附件/查找/信息）+ 侧栏 + 主视区。
// thumbs 容器常驻 DOM 是硬约束——usePDFSlick 构造期 untrack 读 thumbs 元素，
// 晚挂载则 thumbnailViewer 永不创建（pdfslick#136，见 PaneSidebar 头注）。

import {
    createEffect,
    createSignal,
    onCleanup,
    onMount,
    Show,
    untrack,
} from "solid-js";
import { usePDFSlick } from "@pdfslick/solid";
import type { PDFSlick } from "@pdfslick/core";
import "@pdfslick/solid/dist/pdf_viewer.css";

import type { DocId, Pos } from "./alignment";
import {
    capturePos,
    jumpTo,
    onPaneScroll,
    scrollTopFor,
    type PageGeom,
    type PaneLike,
} from "./sync";
import {
    extractBibAtDest,
    extractRefIds,
    type BibEntry,
    type CiteIndex,
    type PdfDocLike,
    type PdfPageLike,
    type RefMeta,
} from "./citations";
import CiteCard, { CiteCardBody } from "./CiteCard";
import UsagesCard from "./UsagesCard";
import { MARKED_SEL, seqOfMarkedSpan, seqOfTextItem } from "./pdfmarks";
import { pdfCiteDests, type UsageEntry } from "./usages";
import type { KeptRef, TaskSnapshot } from "../api/client";
import { ensurePdfjsWorker } from "../pdfjs";
import {
    applyPdfTheme,
    currentPdfTheme,
    patchPdfDocument,
    patchPdfPage,
} from "./pdfTheme";
import PaneSidebar from "./PaneSidebar";
import FindBar from "./FindBar";
import DocInfo from "./DocInfo";
import { t } from "../i18n";

export interface PaneHandle extends PaneLike {
    readonly slick: PDFSlick | null;
    numPages(): number;
    pageNumber(): number;
    gotoPage(n: number): void;
    setScaleValue(v: string): void;
    setScale(v: number): void;
    capture(): Pos;
    jump(pos: Pos): void;
    scrollTopFor(pos: Pos): number | null;
    /** 打开本窗格查找条（Ctrl+F 由上层路由到活动窗格）；
        query 注入输入框并发起查找（sel.find/pane.find 命令面） */
    openFind(query?: string): void;
    /** 镜像 named dest：走未包装的原始 goToDestination（不压本侧栈、
        不回传 nav 事件——ReaderView 拿到 pre/post 自记 dst 栈）；
        FitH/FitR 型 dest 临时免缩放重置。null=dst 无同名锚/未就绪 */
    mirrorDest?(dest: unknown): Promise<{ pre: Pos; post: Pos } | null>;
    /** Pos → 显式 dest 数组（sent-align DOM→PDF 路）：页0基 + XYZ
        锚点，y 为 bottom-up 点制 = (1-fraction)*页高；null=文档未就绪 */
    posDest?(pos: Pos): Promise<unknown[] | null>;
    /** 全页 Link annots 的 dest 名预扫产物（idle 切片渐进充填——返回
        当前已收子集，未扫完≠不存在）。M4 镜像/整合层的「本侧有无此
        dest」预检面 */
    dests?(): ReadonlySet<string>;
    /** sel-system Esc 栈查询/收面：'cite'=悬浮卡 'find'=查找条
        'info'=文档信息 */
    escOpen?(layer: string): boolean;
    escClose?(layer: string): void;
    /** pdf.js 批注编辑器态（keymap 占有判定）：armed=编辑模式开
        （高亮笔等 annotationEditorMode!=NONE）；selected=有选中批注
        （editingstateschanged.details.hasSelectedEditor 快照） */
    pdfjsState?(): { armed: boolean; selected: boolean };
    /** seq → 本窗格已渲染 span.markedContent 元素（跨页续段多枚；
        未渲染页缺席——调用方先 gotoPage/seqPage 定位） */
    seqEls?(seq: number): HTMLElement[];
    /** seq → 页码（idle seqmap 渐进充填——未扫到/无锚 null） */
    seqPage?(seq: number): number | null;
    /** 点击坐标 → Pos（sent-align PDF 源侧臂）：elementFromPoint 命中页 →
        {page, 页内 top-down 分位}；容器外/页间缝 null */
    posAtPoint?(x: number, y: number): Pos | null;
    /** Pos 落点闪示（sent-align PDF→PDF 臂）：命中页 textLayer 分位行带
        加 .sa-flash——单轨，新闪清旧闪 */
    flashAtPos?(pos: Pos): void;
    /** find-usages pdf 臂：cite.<key> dest 反查 link annot 站集开卡 */
    openUsagesFor?(
        target: Element | string | null,
        anchor: Element | null,
    ): boolean;
}

interface LinkServiceLike {
    goToDestination(dest: unknown): Promise<void>;
    _ignoreDestinationZoom?: boolean;
}

interface Props {
    url: string;
    side: DocId;
    /** 「下载带批注副本」文件名（Reader 按 taskId+side 拼好传入） */
    annotName?: string;
    active?: boolean;
    /** 引用索引（dual.json ph→bibMap）——缺位时卡片走 dest 懒抽取兜底 */
    citeIndex?: CiteIndex;
    /** L2 远端元数据回调——缺位卡片只出本地条目 */
    citeMeta?(key: string): RefMeta | undefined;
    /** kept_refs 收藏（M4）：卡 key = entry?.key ?? dest.slice(5) */
    citeKept?(key: string): boolean;
    onToggleKeep?(key: string, payload: KeptRef): void;
    /** 「翻译此文」提交（cite-translate lane）——宿主 ct.submit 包装；
        entry 恒非空（缺条目时合成 {key} 壳——懒抽取回包前也可点） */
    onTranslateRef?(entry: BibEntry): void | Promise<unknown>;
    /** 文献任务行覆写查询（缺省 RefTaskChip 内走 taskByArxiv） */
    refStatusOf?(arxivId: string): TaskSnapshot | undefined;
    onReady?(h: PaneHandle): void;
    onDispose?(h: PaneHandle): void;
    onPageChange?(page: number, numPages: number): void;
    onActivate?(): void;
    onScroll?(): void;
    /** 程序导航窗口开始（ReaderView 静音同步引擎+抑漂移） */
    onNavBegin?(): void;
    /** named-dest 跳转落定（pre/post 供跳回栈+镜像） */
    onDestJump?(dest: unknown, pre: Pos, post: Pos): void;
    /** PDF metadata Title 上报——Reader 层作顶栏/document.title 兜底 */
    onDocTitle?(title: string): void;
    /** 加载失败 veil 的重试——调用方换 key 整体重挂（url 不可在位换，§5.1） */
    onReload?(): void;
}

interface PdfPageViewLike {
    div?: HTMLElement;
}

export default function PdfPane(props: Props) {
    ensurePdfjsWorker();
    const {
        pdfSlick,
        pdfSlickStore,
        viewerRef,
        thumbsRef,
        PDFSlickViewer,
        PDFSlickThumbnails,
        isDocumentLoaded,
        error,
    } =
        // url 刻意非追踪：组件按 doc.version keyed 重挂，绝不在位换 url（§5.1）
        usePDFSlick(
            untrack(() => props.url),
            {
                scaleValue: "page-width",
                getDocumentParams: {
                    cMapUrl: "/pdfjs/cmaps/",
                    cMapPacked: true,
                    standardFontDataUrl: "/pdfjs/standard_fonts/",
                    wasmUrl: "/pdfjs/wasm/",
                },
            },
        );

    const viewer = () => pdfSlick()?.viewer;

    const [findOpen, setFindOpen] = createSignal(false);
    const [infoOpen, setInfoOpen] = createSignal(false);
    let paneEl!: HTMLDivElement;
    let findInput: HTMLInputElement | undefined;
    // findbar 关闭焦点回触发源（rail ⌕ 钮；Ctrl+F 开时同样是它承接，一致可预期）
    let findBtn: HTMLButtonElement | undefined;

    // ---------- 引用悬浮卡 + 跳回栈（同锚双语义：hover=卡 / click=跳+压栈） ----------
    interface CardState {
        rect: DOMRect;
        dest: string;
        entry?: BibEntry;
        loading: boolean;
        notFound: boolean;
        seq: number;
    }
    const [card, setCard] = createSignal<CardState | null>(null);
    // usages 卡（find-usages pdf 臂）——dest 反查 annot 站集开卡；
    // 跳转坐标（页+锚顶 y）与 entry.sites 序对齐存侧车
    const [ucard, setUcard] = createSignal<{
        rect: Pick<DOMRect, "left" | "right" | "top" | "bottom">;
        entry: UsageEntry;
    } | null>(null);
    let usageJumps: { page: number; y: number }[] = [];
    // sent-align 落点闪（单轨——连点两落点旧带当场清算，cite-flash 同款）
    let saFlashEls: HTMLElement[] = [];
    let saFlashTimer = 0;
    const saFlash = (els: HTMLElement[]) => {
        for (const el of saFlashEls) el.classList.remove("sa-flash");
        window.clearTimeout(saFlashTimer);
        saFlashEls = els;
        for (const el of els) el.classList.add("sa-flash");
        saFlashTimer = window.setTimeout(() => {
            for (const el of els) el.classList.remove("sa-flash");
            saFlashEls = [];
        }, 1400);
    };
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

    /** linkAnnotation a[href="#<dest>"] → decode 后的 named dest。
        pdf.js getDestinationHash 用 escape() 编码——非 ASCII bibkey 出
        %uXXXX/%FC 形式，decodeURIComponent 抛 → 退 unescape 对齐回原串 */
    const destOf = (a: Element): string | null => {
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
    const citeAnchorOf = (t: EventTarget | null): Element | null =>
        (t as Element | null)?.closest?.(
            "section.linkAnnotation a[href^='#']",
        ) ?? null;

    const openCard = (a: Element) => {
        // dwell 期间 annotationLayer 可能被逐出/重建（主题 reset、LRU）——
        // 死锚 getBoundingClientRect 全零会让卡落在视口左上
        if (!a.isConnected) return;
        const dest = destOf(a);
        // v1 只出 cite.* 卡——figure./section. 等其它 dest 只跳不卡
        if (!dest || !dest.startsWith("cite.")) return;
        closeUcard(); // 卡族互斥（dom 臂同约）
        const entry = props.citeIndex?.lookup(dest);
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
        const doc = pdfDoc();
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
    /** find-usages pdf 臂：cite.<key> dest 反查全页 link annot 站集 →
        UsagesCard。target=hit.cite.targetId（"cite.key"）或元素；站点
        text 用页码占位（pdf 侧无句级语境——句层靠 seq 锚/C 路另补） */
    const openUsagesFor = (
        target: Element | string | null,
        anchor: Element | null,
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
            cands.find((d) => destSites.get(d)?.length) ??
            (cands.find((d) => destNames.has(d)) ?? cands[0]!);
        const sites = destSites.get(destName) ?? [];
        usageJumps = sites;
        const entry: UsageEntry = {
            target: {
                kind: "bib",
                el: null as unknown as HTMLElement,
                // id=解析后 dest 名（onJumpTarget 直用作 goToDestination
                // 参数）；label=bibkey 展示
                id: destName,
                label: key,
            },
            sites: sites.map((s, i) => ({
                text: `p.${s.page}`,
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
        const rect = a?.isConnected
            ? (a.getClientRects()[0] ?? a.getBoundingClientRect())
            : (viewer()?.container?.getBoundingClientRect() ?? null);
        if (!rect) return false;
        closeCard();
        scrollGraceUntil = performance.now() + 600;
        setUcard({ rect, entry });
        return true;
    };

    const bumpCard = (seq: number, patch: Partial<CardState>) =>
        setCard((c) => (c && c.seq === seq ? { ...c, ...patch } : c));

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
            meta: props.citeMeta?.(citeKey(c)),
        };
    };

    // named-dest 预扫（镜像「本侧有无此 dest」预检面）+ seqmap/usage 站集：
    // 文档就绪后 idle 逐页收 Link annots 的 dest 名/位置 + textContent
    // marked-content item。三表边扫边长——dests()/seqPage() 恒返回已收
    // 子集；卸载置 abort 旗即止（迟到回包 add 进闭包集合无害，组件随
    // 闭包 GC）。
    const destNames = new Set<string>();
    /** dest 名 → 指向它的 link annot 站（usages pdf 臂数据源） */
    const destSites = new Map<string, { page: number; y: number }[]>();
    /** seq → {page, 内容流 item 区间}（item 层 id 尾解码——DOM id
        撞名风险旁路主径；begin/end 供 seq→页内分位跳转） */
    const seqPageMap = new Map<
        number,
        { page: number; begin: number; end: number }
    >();
    let destScanAbort = false;
    const scanDests = (doc: PdfDocLike, numPages: number) => {
        const idle =
            window.requestIdleCallback ??
            ((f: () => void) => window.setTimeout(f, 20));
        let page = 0;
        const step = async () => {
            if (destScanAbort || page >= numPages) return;
            page += 1;
            try {
                const pg = await doc.getPage(page);
                const annots = await (
                    pg as PdfPageLike & {
                        getAnnotations?(o: { intent: string }): Promise<
                            { dest?: unknown; rect?: number[] }[]
                        >;
                    }
                ).getAnnotations?.({ intent: "display" });
                // 只收字符串 named-dest（数组形 explicit dest 无键可查）
                for (const a of annots ?? [])
                    if (typeof a?.dest === "string") {
                        destNames.add(a.dest);
                        const arr =
                            destSites.get(a.dest) ??
                            destSites.set(a.dest, []).get(a.dest)!;
                        // annot.rect=[x1,y1,x2,y2] bottom-up——y2=锚顶
                        arr.push({
                            page,
                            y: Array.isArray(a.rect) ? (a.rect[3] ?? 0) : 0,
                        });
                    }
                const tc = await (
                    pg as PdfPageLike & {
                        getTextContent?(o: {
                            includeMarkedContent: boolean;
                        }): Promise<{ items?: unknown[] }>;
                    }
                ).getTextContent?.({ includeMarkedContent: true });
                // MC 区域栈：文档自有 BMC/BDC 可与 TLXC 互嵌——begin 记
                // 区间起点，end 在配对 endMarkedContent 落定（未配平
                // 留 begin 值，页内分位仍是诚实下界）
                const mcStack: (number | null)[] = [];
                (tc?.items ?? []).forEach((it, i) => {
                    const ty = (it as { type?: unknown }).type;
                    if (
                        ty === "beginMarkedContent" ||
                        ty === "beginMarkedContentProps"
                    ) {
                        const s = seqOfTextItem(it);
                        if (s != null && !seqPageMap.has(s))
                            seqPageMap.set(s, { page, begin: i, end: i });
                        mcStack.push(s);
                    } else if (ty === "endMarkedContent") {
                        const s = mcStack.pop();
                        const rec = s != null ? seqPageMap.get(s) : undefined;
                        if (rec && rec.page === page) rec.end = i;
                    }
                });
            } catch {
                /* 单页注记/文本拉取失败不挡后续页 */
            }
            if (!destScanAbort && page < numPages) idle(() => void step());
        };
        void step();
    };

    // goToDestination 包装持有的原始引用——mirrorDest 走它绕开压栈/回传
    let origGoTo: ((dest: unknown) => Promise<void>) | null = null;
    let wrappedLs: LinkServiceLike | null = null;
    // 导航串行队列：wrapped 跳转与镜像都经它——pdf.js 内部多个 worker
    // 往返乱序落定会把窗格拽回旧意图；排队执行保证落定序=点击序，
    // 且 pre 在任务体里现捕（排队期位置可能已被上一跳改写）
    let navChain: Promise<void> = Promise.resolve();
    let navSeq = 0;
    let mirrorSeq = 0;
    const enqueueNav = (task: () => Promise<void>) => {
        navChain = navChain.then(task, task);
        return navChain;
    };
    const pdfDoc = () =>
        (pdfSlick()?.document ?? null) as unknown as PdfDocLike | null;

    // 页面几何缓存：滚动路径高频调 pages()，_pages[].div 的 offsetTop/Height
    // 只在缩放/旋转/换文档时变化——eventBus 事件 + 容器 RO 失效
    let geomCache: PageGeom[] | null = null;
    const invalidateGeom = () => {
        geomCache = null;
    };

    const openFind = (query?: string) => {
        setFindOpen(true);
        props.onActivate?.();
        queueMicrotask(() => {
            // query 注入：FindBar 的 query 是内部 signal，不改文件的前提
            // 下经「DOM value + 原生 input 事件」喂——Solid 委托 onInput
            // 走 document 监听，bubbles 事件即触发 setQuery→emitDebounced
            if (query != null && findInput) {
                findInput.value = query;
                findInput.dispatchEvent(
                    new Event("input", { bubbles: true }),
                );
            }
            findInput?.focus();
            if (query != null) findInput?.select();
        });
    };

    const closeFind = () => {
        setFindOpen(false);
        findBtn?.focus();
    };

    /** pdf.js 批注选中态快照——editingstateschanged.details
        .hasSelectedEditor 边扫边存（keymap 占有判定的实时面） */
    let edSelected = false;

    const handle: PaneHandle = {
        side: untrack(() => props.side),
        get el() {
            const v = viewer();
            if (!v) throw new Error("PdfPane: viewer not mounted");
            return v.container;
        },
        get slick() {
            return pdfSlick();
        },
        pages(): PageGeom[] {
            if (geomCache) return geomCache;
            const views =
                (viewer() as unknown as { _pages?: PdfPageViewLike[] })
                    ?._pages ?? [];
            const out: PageGeom[] = [];
            views.forEach((v, i) => {
                if (v?.div)
                    out.push({
                        page: i + 1,
                        top: v.div.offsetTop,
                        height: v.div.offsetHeight,
                    });
            });
            geomCache = out;
            return out;
        },
        numPages: () => pdfSlickStore.numPages ?? 0,
        pageNumber: () => pdfSlickStore.pageNumber ?? 1,
        gotoPage: (n) => pdfSlick()?.gotoPage(n),
        setScaleValue: (v) => {
            const s = pdfSlick();
            if (s) s.currentScaleValue = v;
        },
        setScale: (v) => {
            const s = pdfSlick();
            if (s) s.currentScale = v;
        },
        capture() {
            return capturePos(this);
        },
        jump(pos) {
            jumpTo(this, pos);
        },
        scrollTopFor(pos) {
            return scrollTopFor(this, pos);
        },
        openFind,
        escOpen: (l) =>
            l === "cite"
                ? card() != null || ucard() != null
                : l === "find"
                  ? findOpen()
                  : l === "info"
                    ? infoOpen()
                    : false,
        escClose: (l) => {
            if (l === "cite") {
                closeCard();
                closeUcard();
            } else if (l === "find") {
                // 与 FindBar 内部 close 同协议——findbarclose 清命中高亮，
                // 仅 setFindOpen(false) 会把高亮留在 textLayer 上
                pdfSlick()?.eventBus.dispatch("findbarclose", {});
                closeFind();
            } else if (l === "info") setInfoOpen(false);
        },
        pdfjsState: () => ({
            armed: (pdfSlickStore.annotationEditorMode ?? 0) !== 0,
            selected: edSelected,
        }),
        seqEls: (seq) => {
            const c = viewer()?.container;
            if (!c) return [];
            return [
                ...c.querySelectorAll<HTMLElement>(MARKED_SEL),
            ].filter((el) => seqOfMarkedSpan(el) === seq);
        },
        seqPage: (seq) => seqPageMap.get(seq)?.page ?? null,
        posAtPoint: (x, y) => {
            const c = viewer()?.container;
            if (!c) return null;
            const pg = c.ownerDocument
                .elementFromPoint(x, y)
                ?.closest<HTMLElement>("[data-page-number]");
            if (!pg || !c.contains(pg)) return null;
            const page = Number(pg.getAttribute("data-page-number"));
            if (!Number.isFinite(page) || page < 1) return null;
            const r = pg.getBoundingClientRect();
            return {
                page,
                fraction:
                    r.height > 0
                        ? Math.min(Math.max((y - r.top) / r.height, 0), 1)
                        : 0,
            };
        },
        flashAtPos: (pos) => {
            const views = (
                viewer() as unknown as { _pages?: PdfPageViewLike[] }
            )?._pages;
            const div = views?.[pos.page - 1]?.div;
            if (!div) return;
            const y = pos.fraction * div.offsetHeight;
            const els = [
                ...div.querySelectorAll<HTMLElement>(".textLayer span"),
            ].filter(
                (sp) =>
                    sp.offsetTop <= y && y < sp.offsetTop + sp.offsetHeight,
            );
            if (els.length) saFlash(els);
        },
        openUsagesFor,
        async mirrorDest(dest) {
            const s = pdfSlick();
            const orig = origGoTo;
            if (!s || !orig) return null;
            // find-usages 镜像载荷 {u:1,id,ord,chunkOrd}——机会型
            // named-dest 翻译：cite.<key> 在本侧 dest 集内才接（无
            // dest 族文档诚实 null 由对侧降级）；dom 臂 id 带 bib.
            // 前缀时剥一层重试
            if (
                dest != null &&
                typeof dest === "object" &&
                (dest as { u?: unknown }).u === 1
            ) {
                const raw = String((dest as { id?: unknown }).id ?? "");
                const cand =
                    pdfCiteDests(destNames, raw)[0] ??
                    (raw.startsWith("bib.")
                        ? pdfCiteDests(destNames, raw.slice(4))[0]
                        : undefined);
                if (!cand) return null;
                dest = cand;
            }
            // dst 无同名锚即放弃——不显式验会让 pdf.js 内部抛/跳错页
            if (typeof dest === "string") {
                try {
                    const d = await pdfDoc()?.getDestination(dest);
                    if (!d) return null;
                } catch {
                    return null;
                }
            }
            // 与用户导航同队串行——镜像落定序=意图序；有更新的镜像
            // 排队时旧的作废（src 连点两 cite，dst 不该先落 A 再落 B）
            const my = ++mirrorSeq;
            let r: { pre: Pos; post: Pos } | null = null;
            await enqueueNav(async () => {
                if (my !== mirrorSeq) return;
                const pre = capturePos(this);
                try {
                    await orig(dest);
                } catch {
                    return;
                }
                r = { pre, post: capturePos(this) };
            });
            return r;
        },
        dests: () => destNames,
        async posDest(pos) {
            const doc = pdfDoc();
            if (!doc) return null;
            try {
                const page = await doc.getPage(pos.page);
                // view=[x1,y1,x2,y2] 用户空间盒（bottom-up 点制）；
                // getViewport({scale:1}).height 同值——view 直读优先
                const view = (page as unknown as { view?: number[] }).view;
                const h =
                    view && view.length >= 4
                        ? view[3] - view[1]
                        : page.getViewport({ scale: 1 }).height;
                if (!(h > 0)) return null;
                // XYZ dest：[页0基, {name:'XYZ'}, x, y, zoom]——x/zoom
                // null 保持现状；fraction 是 top-down 分位 → bottom-up y
                return [
                    pos.page - 1,
                    { name: "XYZ" },
                    null,
                    (1 - pos.fraction) * h,
                    null,
                ];
            } catch {
                return null;
            }
        },
    };

    // 文档加载完成 → 等 pages 就位（_pages[].div 齐全）后上报 handle
    let readyNotified = false;
    let rafId = 0;
    createEffect(() => {
        if (!isDocumentLoaded() || readyNotified) return;
        const waitPages = () => {
            const s = pdfSlick();
            const views = (
                s?.viewer as unknown as {
                    _pages?: (PdfPageViewLike & {
                        pdfPage?: Parameters<typeof patchPdfPage>[0];
                    })[];
                }
            )?._pages;
            if (s && views?.length && views.every((v) => v?.div)) {
                // 文档级 getPage 补丁根治懒赋值时序洞;view 级补扫
                // 覆盖补丁落地前已取出的页;主题 effect 重渲兜底
                patchPdfDocument(
                    s.document as Parameters<typeof patchPdfDocument>[0],
                );
                for (const v of views) if (v?.pdfPage) patchPdfPage(v.pdfPage);
                readyNotified = true;
                props.onReady?.(handle);
                // dest 预扫走 idle——不占就绪路径
                const d = pdfDoc();
                if (d)
                    scanDests(
                        d,
                        (d as unknown as { numPages?: number }).numPages ??
                            pdfSlickStore.numPages ??
                            0,
                    );
                return;
            }
            rafId = requestAnimationFrame(waitPages);
        };
        waitPages();
    });
    onCleanup(() => cancelAnimationFrame(rafId));
    onCleanup(() => window.clearTimeout(saFlashTimer));
    onCleanup(() => {
        destScanAbort = true;
    });
    onCleanup(() => props.onDispose?.(handle));

    // 纸面色板 ↔ PDF 页渲染:色板身份(bg|fg|invert)变化 → applyPdfTheme
    // 全页 reset + 原位重渲;osDark 与 paperTheme 两路信号经
    // currentPdfTheme 收敛为单一身份键,选板与 auto/none 系统翻转同路。
    // 首挂载恰为 null(原样透传)时不动——默认渲出的就是对的
    let prevPaletteKey = "";
    createEffect(() => {
        const s = pdfSlick();
        if (!s || !isDocumentLoaded()) return;
        const th = currentPdfTheme();
        const key = th
            ? `${th.background}|${th.foreground}|${!!th.invertImages}`
            : "";
        if (key === prevPaletteKey) return;
        prevPaletteKey = key;
        applyPdfTheme(s);
    });

    // 几何缓存失效线：pdf.js 布局变化走 eventBus，容器尺寸走 RO；
    // 同轨订 editingstateschanged——keymap 的 pdfjs().selected 数据源
    createEffect(() => {
        const s = pdfSlick();
        if (!s) return;
        const bus = s.eventBus;
        for (const ev of [
            "scalechanging",
            "rotationchanging",
            "pagesinit",
            "pagesdestroy",
        ]) {
            bus.on(ev, invalidateGeom);
        }
        // details={isEditing,isEmpty,hasSomethingToUndo/Redo,hasSelectedEditor,
        // hasSelectedText}（pdfjs-dist 实证）；防御两形——details 缺失时直读
        const onEdState = (e: object) => {
            const d = e as {
                details?: { hasSelectedEditor?: boolean };
                hasSelectedEditor?: boolean;
            };
            edSelected = !!(d.details?.hasSelectedEditor ?? d.hasSelectedEditor);
        };
        bus.on("editingstateschanged", onEdState);
        const ro =
            typeof ResizeObserver === "function"
                ? new ResizeObserver(invalidateGeom)
                : null;
        ro?.observe(s.viewer.container);
        onCleanup(() => {
            for (const ev of [
                "scalechanging",
                "rotationchanging",
                "pagesinit",
                "pagesdestroy",
            ]) {
                bus.off(ev, invalidateGeom);
            }
            bus.off("editingstateschanged", onEdState);
            ro?.disconnect();
        });
    });

    // usePDFSlick 无实例清理（§5.1）——卸载时亲手拆：unbindEvents 停
    // window/eventBus 监听，loadingTask.destroy() 杀 worker 解析态。
    // document 未落地（在途加载）时订 store 首个 setState 补刀——订阅
    // 不设上限：slick 不暴露 loadingTask 句柄，这是捕获迟到文档的唯一
    // 钩子；加载失败整条引用环（worker promise→store→listener→s）随
    // promise 释放即可被 GC，超时退订反而留出「到得比超时晚」的泄漏窗
    onCleanup(() => {
        const s = pdfSlick();
        if (!s) return;
        try {
            s.unbindEvents();
        } catch {
            /* 半初始化实例上解绑可能抛——不挡销毁 */
        }
        const destroyDoc = () => {
            const d = s.document;
            if (d) void d.loadingTask.destroy().catch(() => undefined);
        };
        if (s.document) {
            destroyDoc();
            return;
        }
        const unsub = s.store.subscribe(() => {
            if (!s.document) return;
            unsub();
            destroyDoc();
        });
    });

    // 文档标题上报：store.title 由 _parseDocumentInfo 落定（metadata.info.Title）——
    // 空串不上报，调用方留 arxiv_id 兜底
    createEffect(() => {
        const title = pdfSlickStore.title;
        if (title) props.onDocTitle?.(title);
    });

    // 页码上报（pdfjs pagechanging → store.pageNumber）
    createEffect(() => {
        const n = pdfSlickStore.pageNumber;
        if (typeof n === "number")
            props.onPageChange?.(n, pdfSlickStore.numPages ?? 0);
    });

    // 用户滚动 → 上层做位置持久化/漂移检测（同步引擎自己在容器上挂监听）
    createEffect(() => {
        const s = pdfSlick();
        if (!s) return;
        onPaneScroll(s.viewer.container, () => props.onScroll?.());
    });

    // linkService.goToDestination 单点劫持——所有内链（cite 锚/大纲/named
    // dest）唯一漏斗；preventDefault/stopPropagation 拦不住 onclick 属性
    // 处理器，包装是唯一能「跳前压栈」的拦截点。navChain 串行化执行：
    // orig 内含多个 worker 往返，裸并发会乱序落定+栈失真；末次入队者
    // 胜出（旧任务轮到执行时 navSeq 已变→直接作废），pre 在执行时现捕。
    // _ignoreDestinationZoom 常置——缩放是双侧统一信号，dest 自带缩放
    // （FitH/FitR）会让两窗格发散且 store 无回写。
    createEffect(() => {
        const s = pdfSlick();
        if (!s || !isDocumentLoaded()) return;
        const ls = s.linkService as unknown as LinkServiceLike;
        if (wrappedLs === ls) return;
        wrappedLs = ls;
        ls._ignoreDestinationZoom = true;
        const orig = ls.goToDestination.bind(ls);
        origGoTo = orig;
        ls.goToDestination = (dest: unknown) => {
            const my = ++navSeq;
            // eslint-disable-next-line solid/reactivity -- 排队回调执行期读 props/信号是有意的
            return enqueueNav(async () => {
                if (my !== navSeq) return; // 更新的导航已排队——作废本跳
                props.onNavBegin?.();
                closeAll();
                // 死链预检：pdf.js 对缺失 dest 只 console.error 不抛——
                // 不预检会记 post≈pre 幻影栈项并截断前进栈
                if (typeof dest === "string") {
                    try {
                        if (!(await pdfDoc()?.getDestination(dest))) return;
                    } catch {
                        return;
                    }
                }
                const pre = capturePos(handle);
                try {
                    await orig(dest);
                } catch {
                    return;
                }
                props.onDestJump?.(dest, pre, capturePos(handle));
            });
        };
    });

    // 悬浮卡委托：pointerover/out 在容器上冒泡统收（enter/leave 不冒泡）；
    // focusin/out 挂 paneEl（卡在 viewer 容器外，焦点锚→卡→卡外三段路都要
    // 看得见）；触屏 tap 走 click capture 拦截出卡。
    // aria-label 由 MO 渐进注入——.linkAnnotation>a 是无文本空元素。
    createEffect(() => {
        const s = pdfSlick();
        if (!s || !isDocumentLoaded()) return;
        const container = s.viewer.container;

        const armOpen = (a: Element) => {
            window.clearTimeout(openTimer);
            openTimer = window.setTimeout(() => {
                openTimer = 0; // 发后即清零——同锚复悬才能再武装
                openCard(a);
            }, OPEN_DELAY);
        };
        const armClose = () => {
            window.clearTimeout(closeTimer); // 重入必须撤旧定时器
            closeTimer = window.setTimeout(closeAll, CLOSE_DELAY);
        };

        const onOver = (e: PointerEvent) => {
            if (e.pointerType === "touch") return; // tap=卡走 click 路
            const a = citeAnchorOf(e.target);
            if (!a) return;
            // 非 cite 锚不进门——否则 curAnchor 被非卡锚占住，cite 卡武装受阻
            const dest = destOf(a);
            if (!dest?.startsWith("cite.")) return;
            if (a === curAnchor) {
                // 同锚复悬/跨行 rect 间走——只续不关（isUserDwelling 同款）；
                // 卡未开且定时器已逝（openCard 早退路径）要补武装
                window.clearTimeout(closeTimer);
                if (!card() && !openTimer) armOpen(a);
                return;
            }
            clearCardTimers();
            curAnchor = a;
            armOpen(a);
        };
        const onOut = (e: PointerEvent) => {
            const rel = e.relatedTarget as Element | null;
            if (rel?.closest?.(".cite-card, .usage-card")) return; // 指针进卡不关
            if (rel === curAnchor) return;
            const a = citeAnchorOf(e.target);
            if (a || card() || ucard()) {
                window.clearTimeout(openTimer);
                armClose();
            }
        };
        const onFocusIn = (e: FocusEvent) => {
            const a = citeAnchorOf(e.target);
            if (!a) return;
            // 指针点击引发的 focus 不出卡（:focus-visible 只对键盘 focus 成立）
            if (!(a instanceof HTMLElement) || !a.matches(":focus-visible"))
                return;
            const dest = destOf(a);
            if (!dest?.startsWith("cite.")) return;
            clearCardTimers();
            curAnchor = a;
            openCard(a); // 键盘 focus 等效 hover——dwell 从略
        };
        const onFocusOut = (e: FocusEvent) => {
            const rel = e.relatedTarget as Element | null;
            if (rel?.closest?.(".cite-card, .usage-card")) return;
            if (!citeAnchorOf(e.target) && !card() && !ucard()) return;
            armClose();
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
            if (lastTouch && e.detail !== 0 && dest?.startsWith("cite.")) {
                // 触屏 tap=出卡：capture 期 stopPropagation——事件到不了
                // target，onclick 属性处理器（goToDestination）根本不触发
                e.stopPropagation();
                e.preventDefault();
                clearCardTimers();
                curAnchor = a;
                openCard(a);
                return;
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
        container.addEventListener("pointerover", onOver);
        container.addEventListener("pointerout", onOut);
        container.addEventListener("pointerdown", onPointerDown, true);
        container.addEventListener("click", onClickCapture, true);
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
            if (dest) destNames.add(dest);
            if (a.hasAttribute("aria-label")) return;
            if (!dest?.startsWith("cite.")) return;
            const entry = props.citeIndex?.lookup(dest);
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
                    if (node instanceof HTMLAnchorElement && node.matches(ANCHOR_SEL))
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

    // rail/侧栏/浮层等窗格 chrome 区的滚轮转给文档滚动口——滚轮语义
    // 是「滚动本窗格文档」，不该死在 34px 窄条上。命中的侧件自身可滚
    // （thumbs/outline/docinfo）时让给它，滚到头再链回文档；
    // ctrl/meta+wheel 是缩放语义不抢。转发写 scrollTop 会触发容器
    // scroll 事件——持久化/漂移/同步引擎走同一条路径，语义一致。
    onMount(() => {
        const onWheel = (e: WheelEvent) => {
            if (e.ctrlKey || e.metaKey) return;
            const container = viewer()?.container;
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
        onCleanup(() => paneEl.removeEventListener("wheel", onWheel));
    });

    return (
        <div
            ref={(el) => (paneEl = el)}
            class="pane pane-pdf"
            classList={{ active: !!props.active }}
            data-side={props.side}
            onPointerDown={() => props.onActivate?.()}
        >
            <PaneSidebar
                slick={pdfSlick}
                store={pdfSlickStore}
                thumbsRef={thumbsRef}
                Thumbs={PDFSlickThumbnails}
                onOpenFind={openFind}
                findBtnRef={(el) => (findBtn = el)}
                onToggleInfo={() => setInfoOpen((v) => !v)}
                annotName={props.annotName}
            />
            <div class="pane-body">
                <PDFSlickViewer viewerRef={viewerRef} store={pdfSlickStore} />
                <Show when={card()}>
                    {(c) => (
                        <CiteCard
                            rect={c().rect}
                            onClose={closeCard}
                            onCardEnter={() => window.clearTimeout(closeTimer)}
                            onCardLeave={() => {
                                window.clearTimeout(closeTimer);
                                closeTimer = window.setTimeout(
                                    closeCard,
                                    CLOSE_DELAY,
                                );
                            }}
                        >
                            <CiteCardBody
                                entry={c().entry}
                                // meta 走活访问器——L2 回包晚于开卡时
                                // props.citeMeta 才填好，快照会永久缺字段
                                meta={() => {
                                    const en = c().entry;
                                    return en
                                        ? props.citeMeta?.(en.key)
                                        : undefined;
                                }}
                                loading={c().loading}
                                notFound={c().notFound}
                                kept={props.citeKept?.(citeKey(c()))}
                                onShowUsages={
                                    destNames.has(c().dest) ||
                                    destSites.get(c().dest)?.length
                                        ? () =>
                                              openUsagesFor(
                                                  c().dest,
                                                  curAnchor,
                                              )
                                        : undefined
                                }
                                usagesCount={destSites.get(c().dest)?.length}
                                onToggleKeep={
                                    props.onToggleKeep
                                        ? () =>
                                              props.onToggleKeep?.(
                                                  citeKey(c()),
                                                  keepPayload(c()),
                                              )
                                        : undefined
                                }
                                onTranslate={
                                    props.onTranslateRef
                                        ? () =>
                                              props.onTranslateRef?.(
                                                  c().entry ?? {
                                                      key: citeKey(c()),
                                                      order: 0,
                                                      label: "",
                                                      text: "",
                                                  },
                                              )
                                        : undefined
                                }
                                refTask={props.refStatusOf}
                                onJump={() => {
                                    const ls = pdfSlick()?.linkService;
                                    if (ls) void ls.goToDestination(c().dest);
                                    closeCard();
                                }}
                            />
                        </CiteCard>
                    )}
                </Show>
                <Show when={ucard()}>
                    {(u) => (
                        <UsagesCard
                            rect={u().rect}
                            entry={u().entry}
                            onClose={closeUcard}
                            onCardEnter={() => window.clearTimeout(closeTimer)}
                            onCardLeave={() => {
                                window.clearTimeout(closeTimer);
                                closeTimer = window.setTimeout(
                                    closeAll,
                                    CLOSE_DELAY,
                                );
                            }}
                            onJump={(s) => {
                                const j = usageJumps[s.order];
                                const ls = pdfSlick()?.linkService;
                                // XYZ dest：y=annot 顶（bottom-up 用户空间），
                                // 落定后引用行贴视口顶
                                if (j && ls)
                                    void ls.goToDestination([
                                        j.page - 1,
                                        { name: "XYZ" },
                                        null,
                                        j.y,
                                        null,
                                    ]);
                                closeUcard();
                            }}
                            onJumpTarget={() => {
                                const ls = pdfSlick()?.linkService;
                                if (ls)
                                    void ls.goToDestination(
                                        u().entry.target.id,
                                    );
                                closeUcard();
                            }}
                        />
                    )}
                </Show>
                <FindBar
                    slick={pdfSlick}
                    open={findOpen()}
                    inputRef={(el) => (findInput = el)}
                    onClose={closeFind}
                />
                <Show when={infoOpen()}>
                    <DocInfo
                        store={pdfSlickStore}
                        onClose={() => setInfoOpen(false)}
                    />
                </Show>
                <Show when={!isDocumentLoaded() && !error()}>
                    <div class="pane-veil">
                        <div
                            class="spinner"
                            role="status"
                            aria-label={t.pane.pdfLoading}
                        />
                    </div>
                </Show>
                <Show when={error()}>
                    {(e) => (
                        <div
                            class="pane-veil pane-error"
                            style={{ "flex-direction": "column", gap: "8px" }}
                        >
                            <span>
                                {t.pane.pdfError}
                                {String(e())}
                            </span>
                            <Show when={props.onReload}>
                                <button
                                    type="button"
                                    class="btn-ghost"
                                    onClick={() => props.onReload?.()}
                                >
                                    {t.reader.retry}
                                </button>
                            </Show>
                        </div>
                    )}
                </Show>
            </div>
        </div>
    );
}
