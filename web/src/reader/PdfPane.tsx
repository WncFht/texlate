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

import { colOf, COL_X_SPLIT, type DocId, type Pos } from "./alignment";
import {
    capturePos,
    jumpTo,
    onPaneScroll,
    scrollTopFor,
    type PageGeom,
    type PaneLike,
} from "./sync";
import {
    destPointOf,
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
import { classifyDestName } from "./cmd/hitctx";
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
        {page, 页内 top-down 分位, x 页宽分位}；容器外/页间缝 null */
    posAtPoint?(x: number, y: number): Pos | null;
    /** 点击坐标 → seq（elementFromPoint 命中 markedContent span——
        TLXC 锚文档精确序；无锚命中/未渲染页 null，调用方按兜底语义走） */
    seqAtPoint?(x: number, y: number): number | null;
    /** Pos 落点闪示（sent-align PDF→PDF 臂）：命中页 textLayer 分位行带
        加 .sa-flash——单轨，新闪清旧闪。返回实际着闪元素集（anim 面） */
    flashAtPos?(pos: Pos): HTMLElement[];
    /** seq 锚闪示（sent-align seq 精度臂）：seqEls 命中则整组闪；
        无已渲染锚（懒渲染页/en.pdf 无标）→ pos 在场落回 flashAtPos。
        返回实际着闪元素集（anim 面） */
    flashSeq?(seq: number, pos: Pos | null): HTMLElement[];
    /** seq → markedContent 字形叶集（flashSeq 同源 leafEls 下钻）——
        sent-align 句级落点/闪示的原料面；未渲染页缺席 */
    seqLeaves?(seq: number): HTMLElement[];
    /** 任意字形叶集打闪（sent-align 句级叶集闪面——flashAtPos/flashSeq
        之外的第三闪；saFlash 单轨同口径） */
    flashEls?(els: HTMLElement[]): void;
    /** seq 悬停伴显（sent-align hover 臂）：cls=sa-hot|sa-peer 单轨染色
        ——锚叶集命中染锚；锚缺席（懒渲染页/无标文档）且 pos 在场落回
        行带；seq null 清轨。与 sa-flash 分轨互不清 */
    hoverSeq?(seq: number | null, pos: Pos | null, cls: string): void;
    /** 任意字形叶集染色（sent-align 句级悬停面——hoverSeq 的 els 版） */
    tintEls?(els: HTMLElement[], cls: string): void;
    /** dest（named/显式数组）→ 落点着陆闪：seq 命中闪锚叶，落回行带；
        goToDestination 落定/镜像落定/菜单跳的揭示共用面 */
    flashDest?(dest: unknown): void;
    /** ⌘-Inspect armed hover：非锚命中 → dest + 落点行带元素集（揭示
        染色原料）；锚命中走锚自身 .insp-hot 不入此路 */
    destHotAt?(
        x: number,
        y: number,
    ): { dest: string; els: HTMLElement[] } | null;
    /** 图/表/式/定理等本体坐标 → 落点 dest 名（destPos 反查——右键
        本体反查 usages 的命台面）；无候选/未扫完/other 类 null；
        tol=垂直分位容差（默认 0.4 右击档，⌘-Inspect 臂走紧档） */
    destAtPoint?(x: number, y: number, tol?: number): string | null;
    /** find-usages pdf 臂：cite.<key> dest 反查 link annot 站集开卡；
        at=显式卡锚矩形（右键本体路——锚元素缺席时卡落点击点） */
    openUsagesFor?(
        target: Element | string | null,
        anchor: Element | null,
        at?: Pick<DOMRect, "left" | "right" | "top" | "bottom">,
    ): boolean;
    /** ⌘-Inspect：坐标点 → 原地开检视卡（锚→目标卡/页内→UsagesCard）；
        handled=false 由闸按兜底语义走 */
    inspectAt?(x: number, y: number): boolean;
    /** ⌘-Inspect：坐标点 → 镜像载荷 {dest}；无可镜像物 null */
    inspectDestAt?(x: number, y: number): { dest: unknown } | null;
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
    /** 最近打闪时刻——landingFlash 的新度闸：sentalign 句级闪与
        goToDestination 包装落定闪同轨，新闪在场时迟到的落定闪不补 */
    let saFlashAt = 0;
    // 容器 → 有形叶子：display:contents 元素自身无盒不可染，递归取
    // 无元素子级的后代；裸文本容器（无子级）按叶子计——染了看不见但
    // 不挡同组其余叶子
    const leafEls = (el: HTMLElement): HTMLElement[] => {
        const kids = el.children;
        if (!kids.length) return [el];
        const out: HTMLElement[] = [];
        for (const k of kids) out.push(...leafEls(k as HTMLElement));
        return out;
    };
    const saFlash = (els: HTMLElement[]) => {
        for (const el of saFlashEls) el.classList.remove("sa-flash");
        window.clearTimeout(saFlashTimer);
        saFlashEls = els;
        if (els.length) saFlashAt = performance.now();
        for (const el of els) el.classList.add("sa-flash");
        saFlashTimer = window.setTimeout(() => {
            for (const el of els) el.classList.remove("sa-flash");
            saFlashEls = [];
        }, 1400);
    };
    // sent-align 悬停伴显轨（sa-hot/sa-peer 单轨——同窗格二态互斥，换轨
    // 先摘旧类；与 sa-flash 分轨互不清，闪动画跑着悬停照样染）
    let saTintEls: HTMLElement[] = [];
    let saTintCls = "";
    // 在场悬停请求——textLayer 懒渲染/重渲后按此补染（渲染把锚 span
    // 整棵换掉，不染则 peer 页现形后悬停色依旧缺席）
    let saTintReq: { seq: number; pos: Pos | null; cls: string } | null = null;
    const saTint = (els: HTMLElement[], cls: string) => {
        const old = saTintCls;
        for (const el of saTintEls) {
            if (old) el.classList.remove(old);
        }
        saTintEls = els;
        saTintCls = els.length ? cls : "";
        for (const el of els) el.classList.add(cls);
    };
    const reTint = (req: { seq: number; pos: Pos | null; cls: string }) => {
        const c = viewer()?.container;
        const els = c
            ? [...c.querySelectorAll<HTMLElement>(MARKED_SEL)].filter(
                  (el) => seqOfMarkedSpan(el) === req.seq,
              )
            : [];
        const leaves = els.flatMap(leafEls);
        if (leaves.length) saTint(leaves, req.cls);
        else if (req.pos) saTint(bandElsAt(req.pos), req.cls);
        else saTint([], req.cls);
    };
    // Pos → 分位行带元素集（flashAtPos/hoverSeq 共用取带面）：命中页
    // textLayer 按 offsetTop 分位取行；pos.x 在场收窄到同栏半区（右栏
    // 落点不染同 y 左栏行），收窄空集（缝带点击）落回整带兜底
    const bandElsAt = (pos: Pos): HTMLElement[] => {
        const views = (viewer() as unknown as { _pages?: PdfPageViewLike[] })
            ?._pages;
        const div = views?.[pos.page - 1]?.div;
        if (!div) return [];
        const y = pos.fraction * div.offsetHeight;
        const band = [
            ...div.querySelectorAll<HTMLElement>(".textLayer span"),
        ].filter(
            (sp) => sp.offsetTop <= y && y < sp.offsetTop + sp.offsetHeight,
        );
        const wantCol = colOf(pos) === 1;
        const els =
            pos.x == null
                ? band
                : band.filter(
                      (sp) =>
                          (sp.offsetLeft + sp.offsetWidth / 2) /
                              div.offsetWidth >=
                              COL_X_SPLIT ===
                          wantCol,
                  );
        if (els.length) return els;
        if (pos.x != null && band.length) return band;
        return [];
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

    /** 批注锚矩形覆盖的印刷文本——<a> 是无文本空元素、caretRangeFromPoint
        不穿透批注层；取同页 .textLayer 相交 span 内逐字 Range 矩形扫描，
        只留真被锚矩形覆盖的字符（行级 span 也能精确切出 "Fig. 3B"）。 */
    const anchorTextOf = (a: Element | null): string => {
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
    /** 落点行带微探：锚分位取自批注矩形顶缘，常悬在行带上沿白缝——
        ±8/16px 步移取首个非空行带（destHotAt 揭示面/destLineText 共用） */
    const bandElsNear = (
        page: number,
        frac: number,
        fx?: number,
    ): HTMLElement[] => {
        for (const d of [0, 0.008, -0.008, 0.016, -0.016]) {
            const els = bandElsAt({
                page,
                fraction: Math.min(Math.max(frac + d, 0), 1),
                x: fx,
            });
            if (els.length) return els;
        }
        return [];
    };
    /** dest 落点行文本——卡标题/站语境的原料（bandElsNear 同栏收窄同法） */
    const destLineText = (page: number, frac: number, fx?: number) =>
        bandElsNear(page, frac, fx)
            .map((e) => e.textContent ?? "")
            .join("")
            .replace(/\s+/g, " ")
            .trim();

    /** 卡标题派生：锚印刷文本拿不出像样的词（锚面只罩 "(“等碎片）时，
        用 dest 落点行印刷文本兜底——eq 抓 "(N)"，浮动体抓「图 N/表 N/
        Figure N」类标签词，兜底行首 4 词 */
    const destRowLabel = (dest: string, kind: string): string => {
        const pt = destPoint.get(dest);
        if (!pt) return "";
        const line = destLineText(pt.page, pt.frac, pt.fx ?? undefined);
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
            cands.find((d) => destSites.get(d)?.length) ??
            cands.find((d) => destNames.has(d)) ??
            cands[0]!;
        const sites = destSites.get(destName) ?? [];
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
                        ? `p.${s.page} · ${destLineText(s.page, s.frac, s.fx).slice(0, 60) || "…"}`
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
                : (viewer()?.container?.getBoundingClientRect() ?? null));
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
    /** dest 名 → 指向它的 link annot 站（usages pdf 臂数据源）；
        frac/fx=锚位页内分位（卡站行语境抽取用） */
    const destSites = new Map<
        string,
        { page: number; y: number; frac?: number; fx?: number }[]
    >();
    /** 页 → dest 落点表（{name, 页内 top-down 分位, x 分位}）——图/式
        本体右键反查 usages 的命台面；getDestinations 词表驱动、idle
        渐进充填 */
    const destPos = new Map<
        number,
        { name: string; frac: number; fx: number | null }[]
    >();
    /** dest 名 → 落点（destPos 的反查面——落定闪/行带揭示的点名寻址） */
    const destPoint = new Map<
        string,
        { page: number; frac: number; fx: number | null }
    >();
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
        // 视口页为中心螺旋外扫——annotations/seqmap 的可用性跟着用户
        // 视线走（原序扫时非首页读者的本体反查/句跳要干等全文档扫完）
        const cur = Math.min(
            Math.max(viewer()?.currentPageNumber ?? 1, 1),
            Math.max(numPages, 1),
        );
        const order: number[] = [];
        for (let d = 0; d < numPages; d++) {
            if (cur + d <= numPages) order.push(cur + d);
            if (d > 0 && cur - d >= 1) order.push(cur - d);
        }
        let oi = 0;
        const step = async () => {
            if (destScanAbort || oi >= order.length) return;
            const page = order[oi++]!;
            try {
                const pg = await doc.getPage(page);
                const annots = await (
                    pg as PdfPageLike & {
                        getAnnotations?(o: {
                            intent: string;
                        }): Promise<{ dest?: unknown; rect?: number[] }[]>;
                    }
                ).getAnnotations?.({ intent: "display" });
                const pview = (pg as unknown as { view?: number[] }).view;
                const vw =
                    pview && pview.length >= 4 ? pview[2]! - pview[0]! : 0;
                const vh =
                    pview && pview.length >= 4 ? pview[3]! - pview[1]! : 0;
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
                            frac:
                                vh > 0 && Array.isArray(a.rect)
                                    ? Math.min(
                                          Math.max(
                                              1 -
                                                  (a.rect[3]! - pview![1]!) /
                                                      vh,
                                              0,
                                          ),
                                          1,
                                      )
                                    : undefined,
                            fx:
                                vw > 0 && Array.isArray(a.rect)
                                    ? Math.min(
                                          Math.max(
                                              (a.rect[0]! - pview![0]!) / vw,
                                              0,
                                          ),
                                          1,
                                      )
                                    : undefined,
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
            if (!destScanAbort && oi < order.length) idle(() => void step());
        };
        void step();
        // dest 落点解析与页扫并行——二者独立面，串行时 destAtPoint 要等
        // 全页扫完才活（本体反查/Inspect 命台面死窗 = 整个页扫时长）
        void resolveDestPoints();
    };

    /** 第二程：dest 词表 → 落点页内分位（本体反查命台面）。
        getDestinations 一把梭全词表，getPageIndex/getPage 逐名解——
        页对象按号缓存复用，idle 切片 24 名/帧不堵交互。无 y 的整页锚
        记 0.5（「页中」是最近邻口径下最诚实的落点——顶/底会偏吸页沿）。 */
    const resolveDestPoints = async () => {
        const d = pdfDoc();
        if (!d?.getDestinations) return;
        // pdf.js≥4 返回 Map（词表含 name-tree 锚——LaTeX 引擎的 dest 全在
        // 那）；老版本/测试桩是 Record——两形都收，漏读 Map 是词表全空的
        // 静默塌方（posTotal=0 → destAtPoint 恒 null）
        let all: Map<string, unknown> | Record<string, unknown>;
        try {
            all = (await d.getDestinations()) ?? new Map();
        } catch {
            return;
        }
        const idle =
            window.requestIdleCallback ??
            ((f: () => void) => window.setTimeout(f, 20));
        const pageCache = new Map<number, Promise<PdfPageLike>>();
        const pageOf = (n: number) => {
            let p = pageCache.get(n);
            if (!p) {
                p = d.getPage(n);
                pageCache.set(n, p);
            }
            return p;
        };
        const entries =
            all instanceof Map ? [...all.entries()] : Object.entries(all);
        let i = 0;
        const step = async () => {
            if (destScanAbort || i >= entries.length) return;
            const slice = entries.slice(i, i + 24);
            i += 24;
            for (const [name, raw] of slice) {
                // 词表值应是 dest 数组；{D:…} 包装形防御摊平
                const pt = destPointOf(
                    Array.isArray(raw)
                        ? raw
                        : (raw as { D?: unknown } | null)?.D,
                );
                if (!pt) continue;
                try {
                    const pnum = (await d.getPageIndex(pt.ref)) + 1;
                    const pg = await pageOf(pnum);
                    const view = (pg as unknown as { view?: number[] }).view;
                    const vp = pg.getViewport({ scale: 1 });
                    const h =
                        view && view.length >= 4
                            ? view[3] - view[1]
                            : vp.height;
                    const w =
                        view && view.length >= 4 ? view[2] - view[0] : vp.width;
                    if (!(h > 0)) continue;
                    const x0 = view?.[0] ?? 0;
                    const y0 = view?.[1] ?? 0;
                    const frac =
                        pt.y == null
                            ? 0.5
                            : Math.min(Math.max(1 - (pt.y - y0) / h, 0), 1);
                    const fx =
                        pt.x == null || !(w > 0)
                            ? null
                            : Math.min(Math.max((pt.x - x0) / w, 0), 1);
                    const arr =
                        destPos.get(pnum) ?? destPos.set(pnum, []).get(pnum)!;
                    arr.push({ name, frac, fx });
                    destPoint.set(name, { page: pnum, frac, fx });
                } catch {
                    /* 单 dest 解页失败不挡后续名 */
                }
            }
            if (!destScanAbort && i < entries.length) idle(() => void step());
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
                findInput.dispatchEvent(new Event("input", { bubbles: true }));
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

    /** 本体坐标 → 落点 dest 名：posAtPoint 同法解页+分位（多取 x 分位做
        双栏并列消歧），同页 destPos 候选过「other 类拒收 + |Δfy|≤tol 闸 +
        Δfy+0.25Δfx 最近邻」；有引用站（destSites 非空）的候选优先——同距
        时「真被引过」的才是用户要答的。opts.kinds 收窄类型白名单、
        opts.maxDx 栏距闸（超距拒收——跨栏同高误吸用） */
    const destAtPoint = (
        x: number,
        y: number,
        tol = 0.4,
        opts?: { kinds?: ReadonlySet<string>; maxDx?: number },
    ): string | null => {
        const c = viewer()?.container;
        if (!c) return null;
        const pg = c.ownerDocument
            .elementFromPoint(x, y)
            ?.closest<HTMLElement>("[data-page-number]");
        if (!pg || !c.contains(pg)) return null;
        const page = Number(pg.getAttribute("data-page-number"));
        if (!Number.isFinite(page)) return null;
        const r = pg.getBoundingClientRect();
        if (r.height <= 0 || r.width <= 0) return null;
        const fy = (y - r.top) / r.height;
        const fx = (x - r.left) / r.width;
        let bestAny: { score: number; name: string } | null = null;
        let bestHit: { score: number; name: string } | null = null;
        for (const d of destPos.get(page) ?? []) {
            const kind = classifyDestName(d.name);
            if (kind === "other") continue;
            if (opts?.kinds && !opts.kinds.has(kind)) continue;
            const dy = Math.abs(d.frac - fy);
            if (dy > tol) continue;
            if (
                opts?.maxDx != null &&
                d.fx != null &&
                Math.abs(d.fx - fx) > opts.maxDx
            )
                continue;
            const score =
                dy +
                (d.fx != null ? Math.min(Math.abs(d.fx - fx), 1) * 0.25 : 0);
            if (!bestAny || score < bestAny.score)
                bestAny = { score, name: d.name };
            if (destSites.get(d.name)?.length)
                if (!bestHit || score < bestHit.score)
                    bestHit = { score, name: d.name };
        }
        return (bestHit ?? bestAny)?.name ?? null;
    };

    // ⌘-Inspect 命中分面容差：落在 textLayer 字形上=行级紧收（±~2%页≈一行
    // 高，原 0.1 页分位会把上下五六行正文全吸进最近 dest）；紧窗落空且
    // 目标是浮动体（式号右置锚在左/多行式跨数行）→ 半窗补一刀不挂栏
    // 闸。空白/图形区=浮动体中窗（±9%页）+栏距闸 0.45——图面本体无字
    // 可点，适度窗是「点在图上」语义；0.45≈一栏宽，异栏同高不收而单栏
    // 锚在左、点在图心不冤
    const INSPECT_TEXT_TOL = 0.02;
    const INSPECT_TEXT_FLOAT_TOL = 0.045;
    const INSPECT_FLOAT_TOL = 0.09;
    const INSPECT_FLOAT_KINDS = new Set(["figure", "table", "equation"]);
    const inspectDestName = (
        x: number,
        y: number,
        t: Element | null,
    ): string | null => {
        const onText = t?.closest?.(".textLayer span") != null;
        if (onText)
            return (
                destAtPoint(x, y, INSPECT_TEXT_TOL) ??
                destAtPoint(x, y, INSPECT_TEXT_FLOAT_TOL, {
                    kinds: INSPECT_FLOAT_KINDS,
                })
            );
        return destAtPoint(x, y, INSPECT_FLOAT_TOL, {
            kinds: INSPECT_FLOAT_KINDS,
            maxDx: 0.45,
        });
    };

    /** 落点 Pos → 着陆闪：pos→client 点 seqAtPoint 多 x 采样（dest 落点
        常在块间白/栏缝/图区，单点易落空），有 seq 闪锚叶（句粒度跟着
        marked 叶走）；无 seq 落回行带。懒渲页 textLayer 未起时两路皆
        空——200ms 步最多重试两拍。
        新闪闸：mirrorDest 也过 goToDestination 包装——sentalign 句级闪
        与落定闪同轨互踩，400ms 内已有新闪则整场免打（迟到的整锚闪会
        把句闪回退成段闪） */
    const landingFlash = (pos: Pos | null, attempt = 0): void => {
        if (!pos) return;
        if (performance.now() - saFlashAt < 400) return;
        const views = (viewer() as unknown as { _pages?: PdfPageViewLike[] })
            ?._pages;
        const div = views?.[pos.page - 1]?.div;
        if (!div) return;
        const r = div.getBoundingClientRect();
        if (r.height <= 0 || r.width <= 0) return;
        const c = viewer()?.container;
        const cy = r.top + r.height * pos.fraction + 4;
        let seq: number | null = null;
        if (c)
            for (const xf of [pos.x ?? 0.3, pos.x ?? 0.7, 0.3, 0.7, 0.5]) {
                const sp = c.ownerDocument
                    .elementFromPoint(r.left + r.width * xf, cy)
                    ?.closest<HTMLElement>(MARKED_SEL);
                if (sp && c.contains(sp)) {
                    seq = seqOfMarkedSpan(sp);
                    if (seq != null) break;
                }
            }
        let els: HTMLElement[] = [];
        if (seq != null) els = (handle.seqEls?.(seq) ?? []).flatMap(leafEls);
        if (!els.length) els = bandElsAt(pos);
        if (els.length) {
            saFlash(els);
            return;
        }
        if (attempt < 2)
            window.setTimeout(() => landingFlash(pos, attempt + 1), 200);
    };

    /** named/显式 dest → 落点 Pos → landingFlash（cite 锚/usages 站跳/
        镜像跳的落定揭示共用面）；词表缺席/解页失败静默无闪 */
    const flashDest = async (dest: unknown): Promise<void> => {
        let pos: Pos | null = null;
        if (typeof dest === "string") {
            const pt = destPoint.get(dest);
            if (pt)
                pos = {
                    page: pt.page,
                    fraction: pt.frac,
                    x: pt.fx ?? undefined,
                };
        } else if (Array.isArray(dest)) {
            const pt = destPointOf(dest);
            const d = pdfDoc();
            if (pt && d)
                try {
                    const pnum = (await d.getPageIndex(pt.ref)) + 1;
                    const pg = await d.getPage(pnum);
                    const view = (pg as unknown as { view?: number[] }).view;
                    const h =
                        view && view.length >= 4
                            ? view[3]! - view[1]!
                            : pg.getViewport({ scale: 1 }).height;
                    const w =
                        view && view.length >= 4
                            ? view[2]! - view[0]!
                            : pg.getViewport({ scale: 1 }).width;
                    if (h > 0)
                        pos = {
                            page: pnum,
                            fraction:
                                pt.y == null
                                    ? 0.5
                                    : Math.min(
                                          Math.max(
                                              1 - (pt.y - (view?.[1] ?? 0)) / h,
                                              0,
                                          ),
                                          1,
                                      ),
                            x:
                                pt.x == null || !(w > 0)
                                    ? undefined
                                    : Math.min(
                                          Math.max(
                                              (pt.x - (view?.[0] ?? 0)) / w,
                                              0,
                                          ),
                                          1,
                                      ),
                        };
                } catch {
                    /* 解页失败无闪 */
                }
        }
        // 首拍延 180ms——同轨上 sentalign 句级闪多在此窗内落定，届时
        // 新闪闸自然让行，纯 nav 跳的闪在滚动落定后才出反而更贴
        if (pos) window.setTimeout(() => landingFlash(pos), 180);
    };

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
            return [...c.querySelectorAll<HTMLElement>(MARKED_SEL)].filter(
                (el) => seqOfMarkedSpan(el) === seq,
            );
        },
        seqPage: (seq) => seqPageMap.get(seq)?.page ?? null,
        seqAtPoint: (x, y) => {
            const c = viewer()?.container;
            if (!c) return null;
            // markedContent span 或其内层文本片——closest 上爬取锚宿主
            const sp = c.ownerDocument
                .elementFromPoint(x, y)
                ?.closest<HTMLElement>(MARKED_SEL);
            if (!sp || !c.contains(sp)) return null;
            return seqOfMarkedSpan(sp);
        },
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
                x:
                    r.width > 0
                        ? Math.min(Math.max((x - r.left) / r.width, 0), 1)
                        : 0,
            };
        },
        flashSeq(seq, pos) {
            const els = this.seqEls?.(seq) ?? [];
            // markedContent 容器是 display:contents 无盒——类打上也不
            // 渲染；逐层下钻到无元素子级的叶子（真字形 span）逐个打闪
            const leaves = els.flatMap(leafEls);
            if (leaves.length) {
                saFlash(leaves);
                return leaves;
            }
            if (pos) return this.flashAtPos?.(pos) ?? [];
            return [];
        },
        seqLeaves(seq) {
            const els = this.seqEls?.(seq) ?? [];
            return els.flatMap(leafEls);
        },
        flashEls(els) {
            if (els.length) saFlash(els);
        },
        flashAtPos: (pos) => {
            const els = bandElsAt(pos);
            if (els.length) saFlash(els);
            return els;
        },
        hoverSeq(seq, pos, cls) {
            if (seq == null) {
                // 清轨按类名认账——对侧 clearHot 广播式双发 null，sa-peer
                // 清不踩本轨活着的 sa-hot（自身的 pointerleave 才发得动）
                if (saTintCls === "" || saTintCls === cls) {
                    saTintReq = null;
                    saTint([], cls);
                }
                return;
            }
            saTintReq = { seq, pos, cls };
            const els = this.seqEls?.(seq) ?? [];
            // 同 flashSeq：display:contents 容器染色看不见，染到字形叶
            const leaves = els.flatMap(leafEls);
            if (leaves.length) saTint(leaves, cls);
            else if (pos) saTint(bandElsAt(pos), cls);
            else saTint([], cls);
        },
        openUsagesFor,
        destAtPoint,
        // ⌘-Inspect：锚→bib 开 CiteCard/他开 UsagesCard；页内非锚命中
        // （分面容差 inspectDestName——文字行级紧收/空白浮动体中窗）→
        // 卡落点击矩形；other 类 dest 不出卡
        inspectAt(x, y) {
            const c = viewer()?.container;
            if (!c) return false;
            const t = c.ownerDocument.elementFromPoint(x, y);
            const a = citeAnchorOf(t);
            if (a) {
                const dest = destOf(a);
                if (!dest) return false;
                if (classifyDestName(dest) === "other") return false;
                if (dest.startsWith("cite.")) {
                    openCard(a);
                    return true;
                }
                return openUsagesFor(dest, a);
            }
            const dest = inspectDestName(x, y, t);
            if (!dest) return false;
            const span =
                (t as Element | null)?.closest?.(".textLayer span") ?? null;
            return openUsagesFor(dest, span, {
                left: x - 1,
                right: x + 1,
                top: y - 1,
                bottom: y + 1,
            });
        },
        inspectDestAt(x, y) {
            const c = viewer()?.container;
            if (!c) return null;
            const t = c.ownerDocument.elementFromPoint(x, y);
            const a = citeAnchorOf(t);
            if (a) {
                const dest = destOf(a);
                return dest && classifyDestName(dest) !== "other"
                    ? { dest }
                    : null;
            }
            const dest = inspectDestName(x, y, t);
            return dest ? { dest } : null;
        },
        // ⌘-Inspect armed hover 强化：非锚命中 → dest + 落点行带元素
        // （揭示染色面）；锚命中无需此路——锚自身 .insp-hot 已标
        destHotAt(x, y) {
            const c = viewer()?.container;
            if (!c) return null;
            const t = c.ownerDocument.elementFromPoint(x, y);
            const dest = inspectDestName(x, y, t);
            if (!dest) return null;
            const pt = destPoint.get(dest);
            const els = pt
                ? bandElsNear(pt.page, pt.frac, pt.fx ?? undefined)
                : [];
            return { dest, els };
        },
        tintEls(els, cls) {
            saTint(els, cls);
        },
        flashDest: (dest: unknown) => void flashDest(dest),
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
                // null 保持现状；fraction 是 top-down 分位 → bottom-up y。
                // y 上抬 0.18*可见高——pdf.js 把 dest 点贴到视口顶，
                // 多留这段让目标行停在与 capturePos 一致的 ~20% 焦点线；
                // 可见高是 CSS px，dest y 是 PDF 单位底向上，要除当前
                // 缩放换算
                const scale =
                    (viewer() as unknown as { currentScale?: number })
                        ?.currentScale ?? 1;
                const visH =
                    scale > 0
                        ? (viewer()?.container.clientHeight ?? 0) / scale
                        : 0;
                const y0 = view && view.length >= 4 ? view[1]! : 0;
                const y = Math.min(
                    y0 + (1 - pos.fraction) * h + 0.18 * visH,
                    y0 + h,
                );
                return [pos.page - 1, { name: "XYZ" }, null, y, null];
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
        for (const el of saTintEls)
            if (saTintCls) el.classList.remove(saTintCls);
        saTintEls = [];
    });
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
            edSelected = !!(
                d.details?.hasSelectedEditor ?? d.hasSelectedEditor
            );
        };
        bus.on("editingstateschanged", onEdState);
        // textLayer 懒渲/重渲把锚 span 整棵换掉——存活悬停按 saTintReq
        // 补染（懒渲页现形后 peer 色不该缺席；saTint 内已滤零尺寸壳）
        const reapplyTint = () => {
            if (saTintReq) reTint(saTintReq);
        };
        bus.on("textlayerrendered", reapplyTint);
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
            bus.off("textlayerrendered", reapplyTint);
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
                // 落定揭示：dest→落点 seq/行带闪（cite 锚/usages 站跳
                // 共用；sentalign 跳走 mirrorDest 原路不入此漏斗）
                void flashDest(dest);
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

        const armOpen = (a: Element) => {
            const lane = destLane(a);
            const dest = destOf(a);
            if (!lane || !dest) return;
            window.clearTimeout(openTimer);
            openTimer = window.setTimeout(() => {
                openTimer = 0; // 发后即清零——同锚复悬才能再武装
                if (!a.isConnected) return;
                if (lane === "bib") openCard(a);
                else openUsagesFor(dest, a);
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
            // 非卡面锚不进门——否则 curAnchor 被非卡锚占住，卡武装受阻
            if (!destLane(a)) return;
            if (a === curAnchor) {
                // 同锚复悬/跨行 rect 间走——只续不关（isUserDwelling 同款）；
                // 卡未开且定时器已逝（openCard 早退路径）要补武装
                window.clearTimeout(closeTimer);
                if (!card() && !ucard() && !openTimer) armOpen(a);
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
            if (a) {
                window.clearTimeout(openTimer);
                armClose();
                return;
            }
            // 卡开着时「任意 pointerout→arm」会被 DOM 更迭噪声打死：右键
            // 本体开卡瞬间 pdf.js 的 selectionRendering 重排 textLayer 节点，
            // 指针原地不动也吐 pointerout（rel=非卡元素）——开卡宽限窗内
            // 只认真锚离开，噪声窗后恢复正常宽限关
            if ((card() || ucard()) && performance.now() >= scrollGraceUntil)
                armClose();
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
            const dest = destAtPoint(e.clientX, e.clientY);
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
                                              openUsagesFor(c().dest, curAnchor)
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
