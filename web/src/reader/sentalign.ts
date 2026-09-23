// sentalign —— 句级双语对位（sent-align lane，v1 纯前端 B 方案）。
// 实施文档：docs/dev/ux-impl-2026-09-22/sent-align…实施文档.md。
// 四段纯逻辑 + 一段会话，全部 jsdom 可单测：
//   splitZh          zhseg.py 的正则臂移植（「。！？!?…+闭引号」run、ASCII '.'
//                    过 _abbrev_dot 闸、_GUARD_RX 保护区、{} 深度>0 抑制、\\
//                    双跳、句尾吸收随行空白）——Intl.Segmenter zh 对 Latin
//                    缩写系统性过切，禁用（实施文档 §风险 15）。
//   splitEn          Intl.Segmenter("en",sentence)，输入先扁平化（\n 等长
//                    换空格——RAW 变体在 \n 处乱切 4571 vs 4025，禁直切原文）。
//   alignBeads       align-monotonic 贪心对位移植：rho=zh/en 逐 chunk 自适应，
//                    |log(zl/(el·rho))| 严格缩小才扩边，MAXG=4/侧，残句并末 bead。
//   injectSentSpans  align-inject 的 piecewise 包裹：TreeWalker 收文本→切句→
//                    倒序 splitText 逐片包 span.ens/zhs[data-sid="{chunk}.{k}"]。
//                    元素从不搬家（只分文本节点）——<a>/<em> 跨界句产多片同
//                    sid span（49% sid 多片段实证）；RESTRICTED_SPAN_PARENTS
//                    内留裸片防 foster-parenting；嵌套 [data-chunk] 经
//                    closest 闸防 footnote 幽灵句。
//   SentAlignSession 双侧 pane 会话：mountSide 注入+对位+data-bead 标引+
//                    MutationObserver 增量重注（repaint/paint 自动覆盖）+
//                    bodyEl 委托 pointerover/out/click（align-hover-perf
//                    结论：委托 ~0ms 重绑 vs 逐 span 8–40ms）。
//
// sid 协议："{data-chunk}.{k}"（k=块内非空句序位，0 起）。
// bead 协议：data-bead="{chunk}.{b}"（b=块内 bead 序位）——交互单位是 bead
// 不是句（句数不等 7.53% chunk 天然降级组高亮，绝不伪装 1:1）。
// 契约：sid/bead → 元素集合——任何消费方一律 querySelectorAll，禁单元素假设。

import type { Pos } from "./alignment";
import { forEachSliced } from "./sync";

// ------------------------------------------------------------------ 类型

export type SaSide = "en" | "zh";
/** 句区间（半开 [start,end)，拼接文本坐标） */
export type SentSpan = readonly [number, number];
/** bead = m:n 句组（半开句序位区间） */
export interface Bead {
    en0: number;
    en1: number;
    zh0: number;
    zh1: number;
}
/** injectSentSpans 返回的逐句描述（对位/分位插值用） */
export interface SentInfo {
    /** "{chunk}.{k}" */
    sid: string;
    k: number;
    /** 去空白+占位符长度（对位 cost 用——与 align.py en_len/zh_len 同口径） */
    len: number;
    /** 拼接文本起点/终点偏移（DOM→PDF 句内分位用） */
    start: number;
    end: number;
}

const other = (s: SaSide): SaSide => (s === "en" ? "zh" : "en");

// ================================================================== 切句

// ---- zh 正则臂（zhseg.py 逐行移植） ----
const ZH_TERM_RUN_RX = /[。！？!?…]+["'’”』」》）)\]】>]*/g;
const ZH_ASCII_DOT_RX = /\.["'’”』」》）)\]】>]*(?=\s|$)/g;
const ZH_ABBREV_TAIL_RX = /[A-Za-z.]+$/;
const ZH_ABBREV_MAX_WORD = 3;
/** 保护区——[[..]] token / $..$/$$..$$ / \(...\)\[...\] / URL 整段跳过 */
const ZH_GUARD_RX =
    /\[\[[A-Za-z_]+\d*\]\]|\$\$[^$]*\$\$|\$[^$\n]*\$|\\\([^)]*\\\)|\\\[[^\]]*\\\]|https?:\/\/\S+/g;

function zhAbbrevDot(text: string, i: number): boolean {
    /** text[i]=='.' 是缩写尾点则不切——batch.abbrev_cut 的 zh 移植：
        尾词含 '.'（e.g./al.）或 ≤3 字母（Fig/B/Dr）→ 缩写位；
        尾词表取不到字母 → 前字符是数字也按缩写兜（3.14/v2.1）。 */
    const m = ZH_ABBREV_TAIL_RX.exec(text.slice(0, i));
    if (!m) return i > 0 && /\d/.test(text[i - 1]!);
    const w = m[0];
    if (w.includes(".") || w.length <= ZH_ABBREV_MAX_WORD) return true;
    return i > 0 && /\d/.test(text[i - 1]!);
}

/** zh 文本 → 句区间表（含句尾空白吸收）。切点=CJK 终止符 run 尾或合规
    ASCII '.' 尾；{} 深度>0 与 \\ 转义双跳与 sentence_ends 同口径。 */
export function splitZh(text: string): SentSpan[] {
    const n = text.length;
    // 括号深度图——逐字符扫，\\ 双跳（sentence_ends 同则）
    const depthAt = new Array<number>(n + 1).fill(0);
    let depth = 0;
    let i = 0;
    while (i < n) {
        const c = text[i]!;
        if (c === "\\") {
            depthAt[i + 1] = depth;
            if (i + 2 <= n) depthAt[i + 2] = depth;
            i += 2;
            continue;
        }
        if (c === "{") depth++;
        else if (c === "}") depth = Math.max(0, depth - 1);
        depthAt[i + 1] = depth;
        i++;
    }
    // 保护区区间表
    const guards: [number, number][] = [];
    ZH_GUARD_RX.lastIndex = 0;
    for (let m = ZH_GUARD_RX.exec(text); m; m = ZH_GUARD_RX.exec(text))
        guards.push([m.index, m.index + m[0].length]);
    const inGuard = (p: number) => guards.some(([s, e]) => s <= p && p < e);

    const cuts = new Set<number>();
    for (const [rx, isDot] of [
        [ZH_TERM_RUN_RX, false],
        [ZH_ASCII_DOT_RX, true],
    ] as const) {
        rx.lastIndex = 0;
        for (let m = rx.exec(text); m; m = rx.exec(text)) {
            if (inGuard(m.index)) continue;
            if (depthAt[m.index]! > 0) continue;
            if (isDot && zhAbbrevDot(text, m.index)) continue;
            cuts.add(m.index + m[0].length);
        }
    }
    const spans: SentSpan[] = [];
    let prev = 0;
    for (const c of [...cuts].sort((a, b) => a - b)) {
        // 吸收界后空白/换行入前句
        let e = c;
        while (e < n && (text[e] === " " || text[e] === "\t" || text[e] === "\n"))
            e++;
        if (text.slice(prev, c).trim()) spans.push([prev, e]);
        prev = e;
    }
    if (text.slice(prev, n).trim()) spans.push([prev, n]);
    return spans;
}

// ---- en Intl 臂 ----
const enSeg = new Intl.Segmenter("en", { granularity: "sentence" });

/** 扁平化：\n 等长换空格——Intl 在 \n 处乱切（RAW 4571 vs flat 4025），
    等长替换保偏移映射不变。 */
const flatOf = (text: string): string => text.replace(/\n/g, " ");

/** en 文本 → 句区间表（ws-only segment 剔除——只返非空句）。 */
export function splitEn(text: string): SentSpan[] {
    const flat = flatOf(text);
    const out: SentSpan[] = [];
    for (const s of enSeg.segment(flat)) {
        const e = s.index + s.segment.length;
        if (flat.slice(s.index, e).trim()) out.push([s.index, e]);
    }
    return out;
}

// ================================================================== 对位

const MAXG = 4; // bead 单侧最大句数（实测 87.6% 1:1）
/** 掩码 token——对位长度只计可见文本（en_len/zh_len 同口径） */
const PH_RX =
    /\[\[[A-Z][A-Z_]*(?:_?\d+)?\]\]|\[\[__TEXLATE_[A-Z_]+_LIT\d+__\]\]|⟪[A-Z]\d+⟫/g;

/** 对位长度：去掩码、去全部空白。 */
export const sentLen = (s: string): number =>
    s.replace(PH_RX, " ").replace(/\s+/g, "").length;

const cost = (el: number, zl: number, rho: number): number =>
    el <= 0 || zl <= 0 || rho <= 0 ? 1e9 : Math.abs(Math.log(zl / (el * rho)));

/**
 * 贪心单调对位（align.py:align_greedy 移植）：逐 bead 双侧各取一句起，
 * 谁能让 |log(zl/(el·rho))| 严格变小就扩谁（小者先），否则闭合；单侧耗尽
 * 残句并入末 bead。rho 缺省 = Σzh/Σen（逐 chunk 自适应）。
 */
export function alignBeads(
    enLens: readonly number[],
    zhLens: readonly number[],
    rho?: number,
): Bead[] {
    const m = enLens.length;
    const n = zhLens.length;
    const r =
        rho ??
        (() => {
            const et = enLens.reduce((a, b) => a + b, 0);
            const zt = zhLens.reduce((a, b) => a + b, 0);
            return et > 0 ? zt / et : 1;
        })();
    const beads: Bead[] = [];
    let i = 0;
    let j = 0;
    while (i < m && j < n) {
        const en0 = i;
        const zh0 = j;
        i++;
        j++;
        let el = enLens[en0]!;
        let zl = zhLens[zh0]!;
        for (;;) {
            const cur = cost(el, zl, r);
            let best: [number, "en" | "zh"] | null = null;
            if (i < m && i - en0 < MAXG) {
                const c = cost(el + enLens[i]!, zl, r);
                if (c < cur - 1e-9 && (best === null || c < best[0]))
                    best = [c, "en"];
            }
            if (j < n && j - zh0 < MAXG) {
                const c = cost(el, zl + zhLens[j]!, r);
                if (c < cur - 1e-9 && (best === null || c < best[0]))
                    best = [c, "zh"];
            }
            if (best === null) break;
            if (best[1] === "en") {
                el += enLens[i]!;
                i++;
            } else {
                zl += zhLens[j]!;
                j++;
            }
        }
        beads.push({ en0, en1: i, zh0, zh1: j });
    }
    // 残句并入末 bead（双侧皆空才兜底独占）
    if (i < m || j < n) {
        if (beads.length) {
            const last = beads[beads.length - 1]!;
            last.en1 = m;
            last.zh1 = n;
        } else {
            beads.push({ en0: 0, en1: m, zh0: 0, zh1: n });
        }
    }
    return beads;
}

// ================================================================== 注入

/** SKIP_TAGS——整树跳（math/svg/script/style/noscript/template/annotation/
    pre/code/textarea/select + button：chunk-retx 等 pane chrome 不进句流） */
const SKIP_TAGS = new Set([
    "math",
    "svg",
    "script",
    "style",
    "noscript",
    "template",
    "annotation",
    "pre",
    "code",
    "textarea",
    "select",
    "button",
]);
/** SKIP_CLASS_PREFIX——ltx_* 页面 chrome 词表（align-inject 同款） */
const SKIP_CLASS_PREFIX = [
    "ltx_tag",
    "ltx_pagination",
    "ltx_role_newpage",
    "ltx_note_mark",
    "ltx_TOC",
    "ltx_tocentry",
    "ltx_toclist",
    "ltx_verbatim",
];
/** SKIP_CLASSES——渲染管线插桩件（KaTeX 替身/ph 掩码/chunk 徽标/元信息/
    sentseg 哨兵）——这些文本是 chrome 不是句料 */
const SKIP_CLASSES = new Set([
    "katex",
    "ph-tok",
    "chunk-meta",
    "chunk-badge",
    "chunk-retx",
    "sb",
    "cite-card",
]);
/** RESTRICTED_SPAN_PARENTS——span 非法子级容器：其内文本留裸片不包
    （包进去会被 reparse foster-parent 出去 → textContent 重排实证） */
const RESTRICTED_SPAN_PARENTS = new Set([
    "table",
    "tbody",
    "thead",
    "tfoot",
    "tr",
    "colgroup",
    "ul",
    "ol",
    "dl",
    "select",
    "optgroup",
    "datalist",
    "map",
    "frameset",
    "picture",
]);

const sidClass = (lang: SaSide): string => (lang === "en" ? "ens" : "zhs");

/** 元素是「跳过子树」根（块内判 acceptNode 的逐祖先链用） */
function skipEl(el: Element, block: Element): boolean {
    if (SKIP_TAGS.has(el.localName)) return true;
    // 嵌套 [data-chunk] 是独立对位单元——footnote-in-para 幽灵句闸
    if (el !== block && el.hasAttribute("data-chunk")) return true;
    if (el.hasAttribute("data-sid")) return true; // 幂等闸
    if (el.hasAttribute("data-ph")) return true; // 掩码替身文本不进句流
    for (const c of el.classList) {
        if (SKIP_CLASSES.has(c)) return true;
        for (const p of SKIP_CLASS_PREFIX) if (c.startsWith(p)) return true;
    }
    return false;
}

/** block 内接受文本节点（手工递归——jsdom TreeWalker 静默忽略对象形 filter） */
function textNodesOf(block: Element): Text[] {
    const out: Text[] = [];
    const walk = (el: Element) => {
        for (const n of el.childNodes) {
            if (n.nodeType === 3) {
                out.push(n as Text);
            } else if (n.nodeType === 1) {
                const e = n as Element;
                if (!skipEl(e, block)) walk(e);
            }
        }
    };
    walk(block);
    return out;
}

/** 摘除块内全部 sid span（重注入前的归位——文本并回裸节点） */
export function stripSentSpans(block: Element): void {
    for (const sp of [
        ...block.querySelectorAll<HTMLElement>("[data-sid]"),
    ]) {
        const parent = sp.parentNode!;
        while (sp.firstChild) parent.insertBefore(sp.firstChild, sp);
        parent.removeChild(sp);
    }
    // 归并相邻文本节点——splitText 残件回一体（对后续注入/选择都干净）
    block.normalize();
}

/**
 * 块内句级 span 注入。幂等前提：调用方保证块内无残 sid（重注入先
 * stripSentSpans）；含 data-sid 的子树本函数跳过。
 * @returns 逐句 SentInfo[]（sid="{chunk}.{k}"，start/end=拼接偏移）
 */
export function injectSentSpans(
    block: Element,
    lang: SaSide,
): { sents: SentInfo[]; concatLen: number } {
    const key = block.getAttribute("data-chunk") ?? "";
    const nodes = textNodesOf(block);
    let concat = "";
    const ranges = nodes.map((n) => {
        const start = concat.length;
        concat += n.data;
        return { node: n, start, end: concat.length };
    });
    const empty = { sents: [] as SentInfo[], concatLen: concat.length };
    if (!concat.trim()) return empty;
    const spans = lang === "zh" ? splitZh(concat) : splitEn(concat);
    if (!spans.length) return empty;

    const cls = sidClass(lang);
    const doc = block.ownerDocument!;
    const sents: SentInfo[] = [];
    // 逐节点 piece 表（节点局部偏移，文档序）
    const pieceMap = new Map<
        Text,
        { start: number; end: number; k: number; bare: boolean }[]
    >();
    for (let k = 0; k < spans.length; k++) {
        const [s, e] = spans[k]!;
        for (const r of ranges) {
            const a = Math.max(s, r.start);
            const b = Math.min(e, r.end);
            if (a >= b) continue;
            const parent = r.node.parentNode;
            const bare =
                parent != null &&
                parent.nodeType === 1 &&
                RESTRICTED_SPAN_PARENTS.has(
                    (parent as Element).localName,
                );
            const list = pieceMap.get(r.node) ?? [];
            list.push({ start: a - r.start, end: b - r.start, k, bare });
            pieceMap.set(r.node, list);
        }
        sents.push({
            sid: `${key}.${k}`,
            k,
            len: sentLen(concat.slice(s, e)),
            start: s,
            end: e,
        });
    }
    // 倒序 splitText 逐片包 span——每节点自持，跨节点无扰
    for (const [node, pieces] of pieceMap) {
        for (let pi = pieces.length - 1; pi >= 0; pi--) {
            const p = pieces[pi]!;
            if (p.bare) continue; // RESTRICTED 父内裸片
            if (p.end < node.data.length) node.splitText(p.end);
            const mid = p.start > 0 ? node.splitText(p.start) : node;
            const span = doc.createElement("span");
            span.className = cls;
            span.setAttribute("data-sid", sents[p.k]!.sid);
            mid.parentNode!.insertBefore(span, mid);
            span.appendChild(mid);
        }
    }
    return { sents, concatLen: concat.length };
}

// ================================================================== 会话

/** 属性选择器（值内引号转义——data-chunk 键含 .: 等任意字符） */
const attrSel = (name: string, value: string): string =>
    `[${name}="${value.replace(/(["\\])/g, "\\$1")}"]`;

interface ChunkState {
    el: Element;
    sents: SentInfo[];
    concatLen: number;
    beadList: Bead[] | null; // 最近一次对位全列（无对位 → null）
}

interface SideState {
    body: HTMLElement;
    scroller: HTMLElement;
    kind: string;
    capture?: () => Pos;
    chunks: Map<string, ChunkState>;
    mo: MutationObserver | null;
    timer: number;
    dirty: Set<Element>;
    detach: (() => void)[];
}

/** 会话对外依赖——宿主（ReaderView/整合层）注入，全可选。 */
export interface SentAlignDeps {
    /** 程序导航静音窗（ReaderView.onNavBegin——SyncEngine 回声吞没） */
    navBegin?(): void;
    /** 目标侧跳转记账：宿主记 navStacks[dst].recordJump(pre,post,pair)。
        pre/post 为 null 表示源侧无 capture（只跳不记）。 */
    recordJump?(dst: SaSide, pre: Pos | null, post: Pos | null): void;
    /** Pos 映射（ReaderView.mapper() 的 en/zh 适配——DOM→PDF 分位插值） */
    mapPos?(pos: Pos, from: SaSide): Pos;
    /** {page,fraction} → pdf.js 显式 dest 数组（PdfPane 页高换算，v1.5） */
    pdfDest?(dst: SaSide, pos: Pos): unknown[] | Promise<unknown[] | null>;
    /** pdf 侧落跳（未记录路径——PdfPane.handle.mirrorDest 同款，
        回 {pre,post} 供 recordJump；null=目标不可达） */
    pdfJump?(
        dst: SaSide,
        dest: unknown[],
    ): Promise<{ pre: Pos; post: Pos } | null>;
    /** PDF→PDF 落点闪示（PdfPane.flashAtPos 桥——r.post 分位行带） */
    pdfFlash?(dst: SaSide, pos: Pos): void;
    /** seq+侧 → Pos（服务端 seqpos——seq 精度直锚，seq 臂优先于
        mapPos 分位插值）；不可查返回 null */
    seqPos?(seq: number, side: SaSide): Pos | null;
    /** data-chunk key → seq（ReaderView seqOf 桥——DOM 侧 seq 定位） */
    seqOfChunk?(key: string): number | null;
    /** seq 锚闪示（PdfPane.flashSeq 桥——markedContent 整组闪；
        缺省调用方落回 pdfFlash 行带） */
    pdfFlashSeq?(dst: SaSide, seq: number, pos: Pos | null): void;
    /** 增量重注防抖（ms，缺省 60——LivePane rAF 分片一拍内合批） */
    debounceMs?: number;
    /** flash 时长（ms，缺省 1400——cite-flash 同款） */
    flashMs?: number;
}

/**
 * 双侧句级对位会话。mountSide 注一侧 DOM 窗格（dom/html/live 同口径）；
 * mountPdfSide 登记 pdf 跳转目标侧（无 body，只供 DOM→PDF 点击）。
 */
export class SentAlignSession {
    private sides = new Map<SaSide, SideState>();
    private pdfTargets = new Set<SaSide>();
    private pdfClickDetach = new Map<SaSide, () => void>();
    private hotEls: Element[] = [];
    private peerEls: Element[] = [];
    private lastKey = "";
    private flashEls: Element[] = [];
    private flashTimer = 0;

    constructor(private deps: SentAlignDeps = {}) {}

    /** 活侧查询（测试/整合面） */
    sideState(side: SaSide): ReadonlyMap<string, ChunkState> | null {
        return this.sides.get(side)?.chunks ?? null;
    }

    /** 一侧 DOM 窗格就位：委托 + MO 先挂，全量注入走 40ms 分片让帧
        （大文档首注 O(N)——不切帧会卡对侧滚动；MO 回声闸滤自身变异）。 */
    async mountSide(
        side: SaSide,
        body: HTMLElement,
        opts: {
            scroller?: HTMLElement;
            kind?: string;
            capture?: () => Pos;
        } = {},
    ): Promise<void> {
        this.unmountSide(side);
        const st: SideState = {
            body,
            scroller: opts.scroller ?? body,
            kind: opts.kind ?? "dom",
            capture: opts.capture,
            chunks: new Map(),
            mo: null,
            timer: 0,
            dirty: new Set(),
            detach: [],
        };
        this.sides.set(side, st);
        this.attachBody(side, st);
        this.watchBody(side, st);
        const els = [...st.body.querySelectorAll("[data-chunk]")];
        await forEachSliced(
            els,
            (el) => this.injectChunk(side, el),
            () => this.sides.get(side) !== st,
        );
        if (this.sides.get(side) === st) this.prune(side);
    }

    /** 对侧是 pdf 时登记（kind='pdf' 仅作 DOM→PDF 跳转目标） */
    mountPdfSide(side: SaSide): void {
        this.pdfTargets.add(side);
    }

    /** pdf 源侧点击（PDF→PDF/PDF→DOM 补臂）：el 上 delegated click →
        seqAtPoint 命中 seq → jumpSeq（seq 精度快路）；无 seq 兜底
        posAtPoint → jumpPosToPdf。守卫与 attachBody.onClick 同口径——
        链接/按钮/批注层/悬浮卡让位，拖选收尾不跳。幂等重挂。 */
    mountPdfClickSource(
        side: SaSide,
        el: HTMLElement,
        posAtPoint: (x: number, y: number) => Pos | null,
        seqAtPoint?: (x: number, y: number) => number | null,
    ): void {
        this.pdfClickDetach.get(side)?.();
        const onClick = (e: MouseEvent) => {
            const t = e.target as Element | null;
            if (
                t?.closest?.(
                    "a, button, .annotationLayer, .cite-card, .usage-card",
                )
            )
                return;
            const sel = el.ownerDocument?.getSelection?.();
            if (sel && !sel.isCollapsed) return;
            const seq = seqAtPoint?.(e.clientX, e.clientY) ?? null;
            if (seq != null && this.jumpSeq(side, seq)) return;
            const pos = posAtPoint(e.clientX, e.clientY);
            if (!pos) return;
            this.jumpPosToPdf(side, pos);
        };
        el.addEventListener("click", onClick);
        this.pdfClickDetach.set(side, () =>
            el.removeEventListener("click", onClick),
        );
    }

    unmountSide(side: SaSide): void {
        this.pdfClickDetach.get(side)?.();
        this.pdfClickDetach.delete(side);
        const st = this.sides.get(side);
        if (!st) {
            this.pdfTargets.delete(side);
            return;
        }
        for (const d of st.detach) d();
        st.mo?.disconnect();
        window.clearTimeout(st.timer);
        // 清零残留：本侧 hot/对侧 peer + 全部注入 span（开关关闭零残留）
        this.clearHot();
        for (const cs of st.chunks.values()) stripSentSpans(cs.el);
        this.sides.delete(side);
        this.pdfTargets.delete(side);
        // 对侧 bead 标引清不掉源侧概念——本侧没了对位即失效，剥对侧 bead 标
        const os = this.sides.get(other(side));
        if (os)
            for (const cs of os.chunks.values()) this.writeBeads(other(side), cs, null);
    }

    destroy(): void {
        for (const s of ["en", "zh"] as const) this.unmountSide(s);
        window.clearTimeout(this.flashTimer);
        this.clearFlash();
    }

    // ---------------------------------------------------------- 注入/对位

    /** 单块重注入（repaint/paint/新增路径）：剥旧 span→重切→重对位。
        幂等——含 data-sid 子树的块 strip 后重来，双跑不双包。 */
    injectChunk(side: SaSide, el: Element): void {
        const st = this.sides.get(side);
        if (!st || !st.body.contains(el)) return;
        const key = el.getAttribute("data-chunk");
        if (key == null) return;
        stripSentSpans(el);
        const { sents, concatLen } = injectSentSpans(el, side);
        st.chunks.set(key, { el, sents, concatLen, beadList: null });
        this.alignChunk(key);
        // 嵌套 [data-chunk] 的 sid span 被 strip 一并剥走——递归重注复位
        // （外层句流本就不含嵌套块文本，块序与脏集均不受影响）
        for (const inner of el.querySelectorAll("[data-chunk]")) {
            st.dirty.delete(inner);
            this.injectChunk(side, inner);
        }
    }

    /** MO 批处理：脏块重注 + 摘走的块从映射清除 */
    private flushDirty(side: SaSide): void {
        const st = this.sides.get(side);
        if (!st) return;
        const dirty = [...st.dirty];
        st.dirty.clear();
        for (const el of dirty)
            if (st.body.contains(el)) this.injectChunk(side, el);
        this.prune(side);
    }

    /** 已从 DOM 摘走的块出映射；对侧同键 bead 标引重算 */
    private prune(side: SaSide): void {
        const st = this.sides.get(side);
        if (!st) return;
        for (const [key, cs] of st.chunks) {
            if (st.body.contains(cs.el)) continue;
            st.chunks.delete(key);
            this.alignChunk(key); // 对侧 bead 降级为无 bead
        }
    }

    /** 单键对位：两侧皆有该 chunk → alignBeads + 双侧写 data-bead；
        缺一 → 双侧该键 bead 标引全剥（无 bead 只本侧 hot）。 */
    private alignChunk(key: string): void {
        const e = this.sides.get("en")?.chunks.get(key);
        const z = this.sides.get("zh")?.chunks.get(key);
        const beads =
            e && z && e.sents.length && z.sents.length
                ? alignBeads(
                      e.sents.map((s) => s.len),
                      z.sents.map((s) => s.len),
                  )
                : null;
        if (e) {
            e.beadList = beads;
            this.writeBeads("en", e, beads);
        }
        if (z) {
            z.beadList = beads;
            this.writeBeads("zh", z, beads);
        }
    }

    /** data-bead 写回：beads[i] 覆盖句 [s0,s1) 全部同 sid span 打 "{key}.{i}"；
        null = 剥光 */
    private writeBeads(side: SaSide, cs: ChunkState, beads: Bead[] | null): void {
        const spans = [...cs.el.querySelectorAll("[data-sid]")];
        for (const sp of spans) sp.removeAttribute("data-bead");
        if (!beads) return;
        for (let b = 0; b < beads.length; b++) {
            const bd = beads[b]!;
            const k0 = side === "en" ? bd.en0 : bd.zh0;
            const k1 = side === "en" ? bd.en1 : bd.zh1;
            for (let k = k0; k < k1; k++) {
                const sid = cs.sents[k]?.sid;
                if (!sid) continue;
                for (const sp of cs.el.querySelectorAll(attrSel("data-sid", sid)))
                    sp.setAttribute("data-bead", `${keyOf(cs)}.${b}`);
            }
        }
    }

    // ---------------------------------------------------------- 增量观察

    private watchBody(side: SaSide, st: SideState): void {
        if (typeof MutationObserver !== "function") return;
        // 注入/剥 span 的自身变异全是这几形：added=[span.ens|zhs] /
        // added=[Text]（splitText 尾片 + appendChild 移入）/ removed=[Text]
        // （移出原父 + normalize 归并）/ removed=[span.ens|zhs]（strip）。
        // 回声判据 = added+removed 里元素节点全是 .ens/.zhs——其余一律实变。
        // 已知漏判面：对块内「只增删裸文本节点」的真变异会被当回声——该
        // 形态在渲染管线里不出现（内容更新都带元素），漏了也只是句界过期。
        const ownNode = (n: Node): boolean =>
            n.nodeType !== 1 ||
            (n as Element).classList.contains("ens") ||
            (n as Element).classList.contains("zhs");
        const mo = new MutationObserver((records) => {
            for (const r of records) {
                if (r.type !== "childList") continue;
                if (
                    [...r.addedNodes].every(ownNode) &&
                    [...r.removedNodes].every(ownNode)
                )
                    continue;
                const tgt = r.target;
                if (tgt instanceof Element) {
                    const chunk = tgt.closest("[data-chunk]");
                    if (chunk) {
                        st.dirty.add(chunk);
                        continue;
                    }
                }
                for (const n of r.addedNodes) {
                    if (n.nodeType !== 1) continue;
                    const el = n as Element;
                    if (el.hasAttribute("data-chunk")) st.dirty.add(el);
                    for (const c of el.querySelectorAll("[data-chunk]"))
                        st.dirty.add(c);
                }
            }
            if (!st.dirty.size) return;
            window.clearTimeout(st.timer);
            st.timer = window.setTimeout(
                () => this.flushDirty(side),
                this.deps.debounceMs ?? 60,
            );
        });
        mo.observe(st.body, { childList: true, subtree: true });
        st.mo = mo;
    }

    // ---------------------------------------------------------- 悬停/点击

    private attachBody(side: SaSide, st: SideState): void {
        const onOver = (e: Event) => {
            const t = e.target as Element | null;
            const sp = t?.closest?.("[data-sid]") ?? null;
            const key = sp
                ? `${sp.getAttribute("data-sid")}|${sp.getAttribute("data-bead") ?? ""}`
                : "";
            if (key === this.lastKey) return;
            this.clearHot();
            this.lastKey = key;
            if (!sp) return;
            const sid = sp.getAttribute("data-sid")!;
            const bead = sp.getAttribute("data-bead");
            const block = sp.closest("[data-chunk]") ?? st.body;
            this.hotEls = [
                ...block.querySelectorAll(attrSel("data-sid", sid)),
            ];
            for (const el of this.hotEls) el.classList.add("sa-hot");
            if (bead) {
                const os = this.sides.get(other(side));
                if (os) {
                    this.peerEls = [
                        ...os.body.querySelectorAll(attrSel("data-bead", bead)),
                    ];
                    for (const el of this.peerEls)
                        el.classList.add("sa-peer");
                }
            }
        };
        const onOut = (e: Event) => {
            const rel = (e as PointerEvent).relatedTarget as Element | null;
            const to = rel?.closest?.("[data-sid]") ?? null;
            const key = to
                ? `${to.getAttribute("data-sid")}|${to.getAttribute("data-bead") ?? ""}`
                : "";
            if (key === this.lastKey) return; // 同句内片段间移动——不清
            this.clearHot();
        };
        const onClick = (e: Event) => {
            const t = e.target as Element | null;
            // 链接/按钮/掩码件优先——cite 跳/retx 钮不被句跳截胡
            if (t?.closest?.("a, button, [data-ph]")) return;
            // 拖选收尾的 click 不跳（选区非坍缩=用户在选择而非导航）
            const sel = st.body.ownerDocument?.getSelection?.();
            if (sel && !sel.isCollapsed) return;
            const sp = t?.closest?.("[data-sid]") ?? null;
            if (!sp) return;
            const dst = other(side);
            this.deps.navBegin?.();
            if (this.sides.get(dst)?.body) {
                // DOM→DOM：bead 粒度跳（无 bead = 对侧无对位，不跳）
                const bead = sp.getAttribute("data-bead");
                if (bead) this.jumpToBead(dst, bead, side);
                return;
            }
            // DOM→PDF（v1.5）：对侧无 DOM 无从对位——句内分位直跳，
            // 不依赖 bead（分位精度反而更高：m:n bead 内取本句起点）
            this.jumpSidToPdf(side, sp);
        };
        st.body.addEventListener("pointerover", onOver);
        st.body.addEventListener("pointerout", onOut);
        st.body.addEventListener("click", onClick);
        st.detach.push(() => {
            st.body.removeEventListener("pointerover", onOver);
            st.body.removeEventListener("pointerout", onOut);
            st.body.removeEventListener("click", onClick);
        });
    }

    private clearHot(): void {
        for (const el of this.hotEls) el.classList.remove("sa-hot");
        for (const el of this.peerEls) el.classList.remove("sa-peer");
        this.hotEls = [];
        this.peerEls = [];
        this.lastKey = "";
    }

    private clearFlash(): void {
        for (const el of this.flashEls) el.classList.remove("sa-flash");
        this.flashEls = [];
    }

    private flash(els: Element[]): void {
        this.clearFlash();
        window.clearTimeout(this.flashTimer);
        this.flashEls = els;
        for (const el of els) el.classList.add("sa-flash");
        this.flashTimer = window.setTimeout(
            () => this.clearFlash(),
            this.deps.flashMs ?? 1400,
        );
    }

    // ---------------------------------------------------------- 点击跳转

    /** pdfDest→pdfJump→recordJump→闪示公共尾（四调用点同构）：
        seq 在场且 pdfFlashSeq 可用 → 锚闪，否则 pdfFlash 行带兜底；
        dest/jump 任一环落空静默收（deps 闸在调用方）。 */
    private pdfJumpFlash(dst: SaSide, pos: Pos, seq?: number | null): void {
        void Promise.resolve(this.deps.pdfDest!(dst, pos)).then((dest) => {
            if (!dest) return;
            return this.deps.pdfJump!(dst, dest).then((r) => {
                if (!r) return;
                this.deps.recordJump?.(dst, r.pre, r.post);
                if (this.deps.pdfFlashSeq && seq != null)
                    this.deps.pdfFlashSeq(dst, seq, r.post);
                else this.deps.pdfFlash?.(dst, r.post);
            });
        });
    }

    /** 点击 → 对侧 bead 首元素跳转（DOM 侧）：scroller 滚位 + flash +
        recordJump（pre/post 由宿主 capture 供——无 capture 只跳不记）。 */
    private jumpToBead(dst: SaSide, bead: string, _src: SaSide): void {
        const st = this.sides.get(dst);
        if (!st?.body) return;
        const els = [
            ...st.body.querySelectorAll(attrSel("data-bead", bead)),
        ];
        if (!els.length) return;
        const pre = st.capture?.() ?? null;
        const first = els[0] as HTMLElement;
        const sr = st.scroller.getBoundingClientRect();
        st.scroller.scrollTop +=
            first.getBoundingClientRect().top - sr.top - 12;
        this.flash(els);
        const post = st.capture?.() ?? null;
        this.deps.recordJump?.(dst, pre, post);
    }

    /** seq 精度点击分派（v2）：PDF 源侧 seqAtPoint 命中后的快路。
        dst 是 DOM → seqOfChunk 找块元素滚位+sa-flash；dst 是 pdf →
        seqPos 直锚 → pdfDest/pdfJump → pdfFlashSeq（锚闪）/pdfFlash
        （行带兜底）。不可落地 → false（调用方走位置映射兜底）。 */
    private jumpSeq(src: SaSide, seq: number): boolean {
        const dst = other(src);
        const st = this.sides.get(dst);
        if (st?.body && this.deps.seqOfChunk) {
            const els = [
                ...st.body.querySelectorAll("[data-chunk]"),
            ].filter(
                (el) =>
                    this.deps.seqOfChunk!(
                        el.getAttribute("data-chunk") ?? "",
                    ) === seq,
            );
            if (els.length) {
                this.deps.navBegin?.();
                const pre = st.capture?.() ?? null;
                const first = els[0] as HTMLElement;
                const sr = st.scroller.getBoundingClientRect();
                st.scroller.scrollTop +=
                    first.getBoundingClientRect().top - sr.top - 12;
                this.flash(els);
                const post = st.capture?.() ?? null;
                this.deps.recordJump?.(dst, pre, post);
                return true;
            }
        }
        const pos = this.deps.seqPos?.(seq, dst) ?? null;
        if (!pos || !this.deps.pdfDest || !this.deps.pdfJump) return false;
        this.deps.navBegin?.();
        this.pdfJumpFlash(dst, pos, seq);
        return true;
    }

    /** DOM→PDF：seq 快路优先（chunk key→seq→seqPos 直锚，seq 精度+
        锚闪）；seqpos 缺席落回 sid 分位→mapPos→pdfDest 旧臂
        （sidPos 以块序充 page——对齐 kind:"pages" 才成立，pdf 视图
        下是粗近似兜底）。 */
    private jumpSidToPdf(src: SaSide, sp: Element): void {
        const dst = other(src);
        if (!this.pdfTargets.has(dst) && !this.deps.pdfJump) return;
        const key = sp
            .closest("[data-chunk]")
            ?.getAttribute("data-chunk");
        const seq =
            key != null ? (this.deps.seqOfChunk?.(key) ?? null) : null;
        const sPos =
            seq != null ? (this.deps.seqPos?.(seq, dst) ?? null) : null;
        if (sPos && this.deps.pdfDest && this.deps.pdfJump) {
            this.pdfJumpFlash(dst, sPos, seq);
            return;
        }
        if (!this.deps.mapPos || !this.deps.pdfDest || !this.deps.pdfJump)
            return;
        const pos = this.sidPos(src, sp);
        if (!pos) return;
        this.pdfJumpFlash(dst, this.deps.mapPos(pos, src));
    }

    /** PDF→PDF：源侧点击位 Pos → mapPos → pdfDest → pdfJump →
        recordJump + pdfFlash（jumpSidToPdf 同构，免 sidPos 句定位）。
        chunk/行带级精度上限——真句级 quad 高亮属 v2（需后端句锚）。 */
    private jumpPosToPdf(src: SaSide, pos: Pos): void {
        const dst = other(src);
        if (!this.pdfTargets.has(dst) && !this.deps.pdfJump) return;
        if (!this.deps.mapPos || !this.deps.pdfDest || !this.deps.pdfJump)
            return;
        this.deps.navBegin?.();
        this.pdfJumpFlash(dst, this.deps.mapPos(pos, src));
    }

    /** 命令面入口：从 src 侧 bead 跳到对侧（sent.gotoPeer 同款路径）。 */
    jumpToPeer(bead: string, src: SaSide): void {
        this.deps.navBegin?.();
        this.jumpToBead(other(src), bead, src);
    }

    /** sid span → 源侧 Pos：所在 chunk 页序 + 句内分位（句首字符偏移/
        chunk 拼接长——createPositionMapper 的 {page,fraction} 口径） */
    private sidPos(side: SaSide, sp: Element): Pos | null {
        const st = this.sides.get(side);
        if (!st) return null;
        const sid = sp.getAttribute("data-sid");
        const chunk = sp.closest("[data-chunk]");
        const key = chunk?.getAttribute("data-chunk");
        const cs = key == null ? null : st.chunks.get(key);
        if (!sid || !cs) return null;
        const sent = cs.sents.find((s) => s.sid === sid);
        if (!sent) return null;
        const pages = st.body.querySelectorAll("[data-chunk]");
        let idx = 0;
        for (let p = 0; p < pages.length; p++)
            if (pages[p] === cs.el) {
                idx = p + 1;
                break;
            }
        if (!idx) return null;
        return {
            page: idx,
            fraction: cs.concatLen > 0 ? sent.start / cs.concatLen : 0,
        };
    }
}

const keyOf = (cs: ChunkState): string =>
    cs.el.getAttribute("data-chunk") ?? "";
