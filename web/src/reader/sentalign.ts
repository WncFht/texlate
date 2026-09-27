// sentalign —— 句级双语对位（sent-align lane，v1 纯前端 B 方案）。
// 实施文档：docs/dev/projects/ux-impl-2026-09-22/sent-align…实施文档.md。
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
//                    PDF dst 句级落地（v1.7）：marked 叶文本重切句 →
//                    u·concatLen 选句 → 句首叶 {page,fraction} 作落点 +
//                    pdfFlashEls 句域闪（替代整段锚闪）；叶缺席退
//                    interpDst/seqPos+行带，懒渲页 160/550ms 双拍重选。
//
// sid 协议："{data-chunk}.{k}"（k=块内非空句序位，0 起）。
// bead 协议：data-bead="{chunk}.{b}"（b=块内 bead 序位）——交互单位是 bead
// 不是句（句数不等 7.53% chunk 天然降级组高亮，绝不伪装 1:1）。
// 契约：sid/bead → 元素集合——任何消费方一律 querySelectorAll，禁单元素假设。

import type { Pos } from "./alignment";
import { MARKED_SEL } from "./pdfmarks";
import { ROW_DOWN, ROW_EPSX, ROW_UP } from "./pdfseqpos";
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
const clamp = (v: number, lo: number, hi: number) =>
    Math.min(Math.max(v, lo), hi);
const colOf = (p: Pos): number => (p.x != null && p.x >= 0.45 ? 1 : 0);
/** 阅读序位 page+(col+frac)/2——与 alignment.ts share 同构；跨栏
    续块 S=(p,c0,.5)→S'=(p,c1,.1) 下 lin 差仍为正（page+frac 线性位
    在该情形下为负、u 恒夹 0/1——对抗复核 N2 实证） */
const roLin = (p: Pos): number => p.page + (colOf(p) + p.fraction) / 2;

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

const EN_CLOSERS_RX = /["'’”』」》）)\]】>*\s]+$/;
const EN_TAIL_WORD_RX = /[A-Za-z.]+$/;
/** 超 3 字母仍属缩写的尾词表（zhAbbrevDot 词表外延——Fig/al/Dr 等
    ≤3 已被长度闸兜住，这里只收更长者） */
const EN_ABBREV_WORDS = new Set(
    (
        "prof figs secs refs approx ibid resp etal assoc dept univ inc ltd " +
        "jan feb mar apr jun jul aug sep sept oct nov dec"
    ).split(" "),
);

/** 句段尾是缩写/碎片则不切——zhAbbrevDot 同口径增强：点前尾词含 '.'
    （e.g./i.i.d./U.S.）强证据直并；短尾词 ≤3（al/Fig/Dr）、白名单、
    数字尾（3.14/v2.1）是弱证据——要下句以小写/数字起的续句信号才并
    （否则 "One. Two." 式短句会链式全并；[[占位]] 不作续句信号——
    占位符同样可以是新句主语，"Elo. [[CMD]]" 实证误并）。过并比过切
    安全——碎片句级联错 bead（en 领先 zh 一句实证），并多了只是
    bead 略宽。 */
function enFragTail(seg: string, next: string): boolean {
    const core = seg.replace(/[.\s]+$/, "");
    const tail = EN_TAIL_WORD_RX.exec(core)?.[0] ?? "";
    if (tail.includes(".")) return true;
    const weak =
        (tail.length > 0 && tail.length <= 3) ||
        EN_ABBREV_WORDS.has(tail.replace(/\./g, "").toLowerCase()) ||
        (!tail && /\d$/.test(core));
    if (!weak) return false;
    return /^[\p{Ll}\d]/u.test(next);
}

/** en 文本 → 句区间表（ws-only segment 剔除 + 碎片后并）。 */
export function splitEn(text: string): SentSpan[] {
    const flat = flatOf(text);
    const raw: SentSpan[] = [];
    for (const s of enSeg.segment(flat)) {
        const e = s.index + s.segment.length;
        if (flat.slice(s.index, e).trim()) raw.push([s.index, e]);
    }
    const out: SentSpan[] = [];
    let carry: number | null = null; // 纯占位片起点——并下句
    for (const [s, e] of raw) {
        const st: number = carry ?? s;
        carry = null;
        if (sentLen(flat.slice(s, e)) === 0) {
            carry = st; // 整片只含掩码占位符——无独立句格
            continue;
        }
        if (out.length) {
            const prev = out[out.length - 1]!;
            const pseg = flat.slice(prev[0], prev[1]).replace(EN_CLOSERS_RX, "");
            const nxt = flat.slice(s, e).trimStart();
            if (enFragTail(pseg, nxt)) {
                out[out.length - 1] = [prev[0], e];
                continue;
            }
        }
        out.push([st, e]);
    }
    if (carry != null) {
        const lastE = raw[raw.length - 1]![1];
        // 末位残片并回末句（全占位文本防御：无句则自成片）
        if (out.length) out[out.length - 1] = [out[out.length - 1]![0], lastE];
        else out.push([carry, lastE]);
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

/** 悬停轨 dedup：同元素集（首末同+同长）且首元素仍带 cls → 免重标。
    60ms 节流下清再加=两帧态闪；cls 校验挡外部扫轨后的陈旧判同 */
const sameEls = (
    a: readonly Element[] | null,
    b: readonly Element[] | null,
    cls?: string,
): boolean =>
    a != null &&
    b != null &&
    a.length > 0 &&
    a.length === b.length &&
    a[0] === b[0] &&
    a[a.length - 1] === b[b.length - 1] &&
    (cls == null || a[0]!.classList.contains(cls));

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
    /** PDF→PDF 落点闪示（PdfPane.flashAtPos 桥——r.post 分位行带）。
        返实际打闪的元素集（供动效层取行矩形——连线终点/擦入幅面） */
    pdfFlash?(dst: SaSide, pos: Pos): Element[] | undefined;
    /** seq+侧 → Pos（服务端 seqpos——seq 精度直锚，seq 臂优先于
        mapPos 分位插值）；不可查返回 null */
    seqPos?(seq: number, side: SaSide): Pos | null;
    /** 同侧阅读序地标表（pdfseqpos.seqLands）——块内插值 u/S' 的
        发现面：源侧点击位在块内占比 → 对侧同 seq 区间插值落点；
        缺省退块首锚（行为同旧版） */
    seqLands?(side: SaSide): readonly { seq: number; pos: Pos }[];
    /** data-chunk key → seq（ReaderView seqOf 桥——DOM 侧 seq 定位） */
    seqOfChunk?(key: string): number | null;
    /** seq+侧 → 块文本长（ph 剥净——ReaderView seqLenOf 桥）：供
        interpDst 的 dst 幅面夹取（浮动体撑大的 dst 块区间 ≠ 文本幅面，
        u·Δdst 会把落点甩进图区/下页）；缺省不夹（行为同旧版） */
    chunkLen?(seq: number, side: SaSide): number;
    /** seq 锚闪示（PdfPane.flashSeq 桥——markedContent 整组闪；
        缺省调用方落回 pdfFlash 行带）。返实际打闪元素集（anim.land 用） */
    pdfFlashSeq?(dst: SaSide, seq: number, pos: Pos | null): Element[] | undefined;
    /** dst pdf 侧 seq 的 marked 字形叶（PdfPane.seqLeaves 桥）——句级
        落点/闪示的原料；已渲染页才查得到，缺席退插值/直锚+整段闪 */
    pdfSeqLeaves?(dst: SaSide, seq: number): HTMLElement[] | undefined;
    /** 句级叶集打闪（PdfPane.flashEls 桥——pdfSentAt 句域叶集闪面；
        缺省或选句落空退 pdfFlash 行带/pdfFlashSeq 整段） */
    pdfFlashEls?(dst: SaSide, els: HTMLElement[]): void;
    /** pdf 侧悬停对位桥（PdfPane.hoverSeq 桥）：seq=null 清色；pos 供
        无锚 seq 的行带兜底；cls='sa-hot'(源侧)/'sa-peer'(对侧)。
        每 pdf 窗格单轨——新 cls 覆盖旧色。 */
    pdfHover?(
        side: SaSide,
        seq: number | null,
        pos: Pos | null,
        cls: string,
    ): void;
    /** pdf 侧逐元素悬停色（PdfPane.tintEls 桥——句级揭示面：源侧句叶
        sa-hot / 对侧对位句叶 sa-peer）；空数组=清本 cls 轨。与 pdfHover
        共 saTint 单轨——清色任一入口皆生效。 */
    pdfTintEls?(dst: SaSide, els: HTMLElement[], cls: string): void;
    /** 动效层（anim.ts）：press=源侧点击涟漪；land=连线+行擦入，
        els=落句渲染元素集（pdf marked 叶/dom sid span——land 内取
        行矩形，调用方保证已过滚动落定帧）。from=null=非点击跳
        （右键 gotoPeer 等）——只擦入不连线 */
    anim?: {
        press?(x: number, y: number): void;
        land?(from: { x: number; y: number } | null, els: Element[]): void;
    };
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
    private pdfHoverDetach = new Map<SaSide, () => void>();
    /** pdf 悬停臂存活的 seq（侧 → seq|null）——DOM 对侧 peer 遭重注
        后按此补臂（指针静止不重发 pointermove，不补则 sa-peer 永失） */
    private pdfHoverCur = new Map<SaSide, number | null>();
    /** peer 轨代次——clearHot 递增；pdf 悬停臂 sameSeq 早退还要比对
        代次，否则外部扫轨（DOM 悬停切换/DOM 侧滚动）后同 seq 不补臂 */
    private peerGen = 0;
    /** 侧 → 本侧 pdf 臂最近补 peer 时的代次（armPdfPeer 内记） */
    private pdfPeerGenArmed = new Map<SaSide, number>();
    /** pdf 对侧句级 peer 已打色的叶集（dedup——60ms 移动重算同句免重标） */
    private pdfPeerSentEls: HTMLElement[] | null = null;
    /** 侧 → 本侧 pdf 悬停最近 pos（句级 peer 的 u 原料——DOM 对侧重注
        后补臂无新 pointermove，按存位重算同句） */
    private pdfHoverPos = new Map<SaSide, Pos | null>();
    private hotEls: Element[] = [];
    private peerEls: Element[] = [];
    private lastKey = "";
    private flashEls: Element[] = [];
    private flashTimer = 0;
    /** 句级闪示延迟重试的代际闸——pdfJumpFlash 每次进 sent 臂递增；
        180ms 窗内新跳作废旧重试（防陈旧句集闪到最新落点上） */
    private flashGen = 0;

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
            // posAt 惰性化——seq 快路落地时不许碰 posAtPoint（调用序契约）
            const posAt = () => posAtPoint(e.clientX, e.clientY);
            let from: { x: number; y: number } | null = null;
            if (seq != null) {
                from = this.animPress(e.clientX, e.clientY);
                if (this.jumpSeq(side, seq, posAt, from)) return;
            }
            const pos = posAt();
            if (!pos) return;
            if (from == null) from = this.animPress(e.clientX, e.clientY);
            this.jumpPosToPdf(side, pos, from);
        };
        el.addEventListener("click", onClick);
        this.pdfClickDetach.set(side, () =>
            el.removeEventListener("click", onClick),
        );
    }

    /** pdf 源侧悬停对位（动效臂 C）：pointermove ~60ms 节流（带尾沿
        补评——静止位不吃陈旧 seq）→ seqAtPoint → 本侧 sa-hot（锚 run
        着色/行带兜底）+ 对侧 sa-peer（pdf 锚组经 pdfHover 桥；DOM
        对侧走 seq↔data-chunk 1:1 查句 span）。同 seq 时本侧随 pos
        行带跟手、对侧不重算；离开/滚动/无 seq 清零。
        守卫与点击同口径（拖选/链接/卡片不跟手）。幂等重挂。 */
    mountPdfHoverSource(
        side: SaSide,
        el: HTMLElement,
        seqAtPoint: (x: number, y: number) => number | null,
        posAtPoint: (x: number, y: number) => Pos | null,
    ): void {
        this.pdfHoverDetach.get(side)?.();
        let last = 0;
        let pend: { x: number; y: number; t: Element | null } | null = null;
        let pendT = 0;
        let lastHotEls: HTMLElement[] | null = null;
        const setSeq = (
            seq: number | null,
            pos: Pos | null,
            t: Element | null,
        ) => {
            this.pdfHoverCur.set(side, seq);
            this.pdfHoverPos.set(side, pos);
            if (seq == null) {
                lastHotEls = null;
                this.deps.pdfHover?.(side, null, null, "sa-hot");
                this.armPdfPeer(side, null, null);
                return;
            }
            // 句级 hot：指针下叶所在句叶集（pdfSentUnder）→ 逐叶 sa-hot；
            // 缺料（非叶上/切空/dep 缺）退整锚/行带旧路。dedup 防 60ms
            // 节流重标同句闪帧
            const sentEls =
                t != null ? this.pdfSentUnder(side, seq, t) : null;
            if (sentEls?.length && this.deps.pdfTintEls) {
                if (!sameEls(sentEls, lastHotEls, "sa-hot")) {
                    this.deps.pdfTintEls(side, sentEls, "sa-hot");
                    lastHotEls = sentEls;
                }
            } else {
                lastHotEls = null;
                this.deps.pdfHover?.(side, seq, pos, "sa-hot");
            }
            // 句级 peer 随 pos 跟手（u→对侧同句）——同 seq 也重算，
            // DOM 写由 armPdfPeer 内 dedup 兜住
            this.armPdfPeer(side, seq, pos);
        };
        const resolve = (x: number, y: number, t: Element | null) => {
            last = Date.now();
            if (t?.closest?.("a, button, .cite-card, .usage-card")) {
                setSeq(null, null, null);
                return;
            }
            const seq = seqAtPoint(x, y);
            setSeq(seq, seq != null ? posAtPoint(x, y) : null, t);
        };
        const onMove = (e: PointerEvent) => {
            if (e.buttons !== 0) return; // 拖选中不跟手
            const wait = 60 - (Date.now() - last);
            if (wait <= 0) {
                pend = null;
                resolve(e.clientX, e.clientY, e.target as Element | null);
                return;
            }
            // 尾沿：节流窗内的移动存末笔，窗满补评——指针停在句上时
            // 悬停色不许留在旧 seq 上
            pend = { x: e.clientX, y: e.clientY, t: e.target as Element | null };
            if (!pendT)
                pendT = window.setTimeout(() => {
                    pendT = 0;
                    const p = pend;
                    pend = null;
                    if (p) resolve(p.x, p.y, p.t);
                }, wait);
        };
        const onLeave = () => {
            pend = null;
            window.clearTimeout(pendT);
            pendT = 0;
            setSeq(null, null, null);
        };
        el.addEventListener("pointermove", onMove);
        el.addEventListener("pointerleave", onLeave);
        // 静止指针下窗格滚动——句料位移悬停即失效（scroll 不冒泡，
        // capture 抓内层 pdfSlickContainer）
        el.addEventListener("scroll", onLeave, { capture: true, passive: true });
        this.pdfHoverDetach.set(side, () => {
            el.removeEventListener("pointermove", onMove);
            el.removeEventListener("pointerleave", onLeave);
            el.removeEventListener("scroll", onLeave, { capture: true });
            window.clearTimeout(pendT);
            setSeq(null, null, null);
        });
    }

    /** pdf 悬停臂的对侧 peer 对位（句级）：源侧 pos → 块内分位 u →
        dst 同 seq 句。pdf 对侧 → pdfSentAt 句叶 pdfTintEls；DOM 对侧
        → u·concatLen 所在句 sid span 子集（peerEls 承载）。缺料
        （u 不可求/切空/dep 缺）退整锚/整段旧路；dedup 兜 60ms 重算 */
    private armPdfPeer(
        side: SaSide,
        seq: number | null,
        pos: Pos | null,
    ): void {
        this.pdfPeerGenArmed.set(side, this.peerGen);
        const dst = other(side);
        if (seq == null) {
            for (const e of this.peerEls) e.classList.remove("sa-peer");
            this.peerEls = [];
            this.pdfPeerSentEls = null;
            this.deps.pdfHover?.(dst, null, null, "sa-peer");
            return;
        }
        const u =
            this.fracInBlock(side, seq, pos ? () => pos : undefined)?.u ??
            null;
        if (this.pdfTargets.has(dst)) {
            const sent = u != null ? this.pdfSentAt(dst, seq, u) : null;
            if (sent?.els.length && this.deps.pdfTintEls) {
                if (!sameEls(sent.els, this.pdfPeerSentEls, "sa-peer")) {
                    this.deps.pdfTintEls(dst, sent.els, "sa-peer");
                    this.pdfPeerSentEls = sent.els;
                }
            } else {
                this.pdfPeerSentEls = null;
                this.deps.pdfHover?.(
                    dst,
                    seq,
                    this.deps.seqPos?.(seq, dst) ?? null,
                    "sa-peer",
                );
            }
            if (this.peerEls.length) {
                for (const e of this.peerEls) e.classList.remove("sa-peer");
                this.peerEls = [];
            }
            return;
        }
        const st = this.sides.get(dst);
        if (!st?.body || !this.deps.seqOfChunk) return;
        const chunks = [...st.body.querySelectorAll("[data-chunk]")].filter(
            (e) =>
                this.deps.seqOfChunk!(e.getAttribute("data-chunk") ?? "") ===
                seq,
        );
        let peerEls: Element[] = chunks.flatMap((e) => [
            ...e.querySelectorAll("[data-sid]"),
        ]);
        // 句级收束：u·concatLen 所在句的 sid span 子集；句料缺席保全块
        if (u != null && chunks.length) {
            const cs = st.chunks.get(
                chunks[0]!.getAttribute("data-chunk") ?? "",
            );
            const sent = cs?.sents.length
                ? (cs.sents.find((s) => s.end > u * cs.concatLen) ??
                    cs.sents[cs.sents.length - 1])
                : null;
            if (sent) {
                const spans = chunks.flatMap((e) => [
                    ...e.querySelectorAll(attrSel("data-sid", sent.sid)),
                ]);
                if (spans.length) peerEls = spans;
            }
        }
        this.pdfPeerSentEls = null;
        if (sameEls(peerEls, this.peerEls, "sa-peer")) return;
        for (const e of this.peerEls) e.classList.remove("sa-peer");
        this.peerEls = peerEls;
        for (const e of this.peerEls) e.classList.add("sa-peer");
    }

    unmountSide(side: SaSide): void {
        this.pdfClickDetach.get(side)?.();
        this.pdfClickDetach.delete(side);
        this.pdfHoverDetach.get(side)?.();
        this.pdfHoverDetach.delete(side);
        this.pdfHoverCur.delete(side);
        this.pdfHoverPos.delete(side);
        this.pdfPeerGenArmed.delete(side);
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
        this.flashGen++; // 作废在途句级延迟重试
    }

    // ---------------------------------------------------------- 注入/对位

    /** 单块重注入（repaint/paint/新增路径）：剥旧 span→重切→重对位。
        幂等——含 data-sid 子树的块 strip 后重来，双跑不双包。
        悬停轨与将亡块相交时先记悬点再清场、注完按原 sid/seq 补臂——
        静止指针不重发 pointerover，不补则悬停色永久丢失。 */
    injectChunk(side: SaSide, el: Element): void {
        const st = this.sides.get(side);
        if (!st || !st.body.contains(el)) return;
        const key = el.getAttribute("data-chunk");
        if (key == null) return;
        const hotSp = this.hotEls[0] ?? null;
        const hotSid = hotSp?.getAttribute("data-sid") ?? null;
        const hotSide = hotSp
            ? st.body.contains(hotSp)
              ? side
              : other(side)
            : null;
        const hoverHit =
            (hotSp != null && el.contains(hotSp)) ||
            this.peerEls.some((e) => el.contains(e));
        if (hoverHit) this.clearHot();
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
        if (!hoverHit) return;
        if (hotSp != null && hotSid != null && hotSide != null) {
            // DOM 悬停：热 span 活着沿用（对侧 peer 块被注的情形），
            // 亡了按同 sid 找新 span（本块重切后同 sid 仍指同句）
            const hst = this.sides.get(hotSide);
            const nsp =
                hst && hst.body.contains(hotSp)
                    ? hotSp
                    : (hst?.body.querySelector(attrSel("data-sid", hotSid)) ??
                      null);
            if (hst && nsp) this.armHover(hotSide, hst, nsp);
            return;
        }
        // pdf 悬停臂的 DOM peer 被注——按存活 seq 补 peer（pdfHoverCur
        // 记着源侧 cur，sameSeq 早退不会自己来补）
        for (const [s, q] of this.pdfHoverCur)
            if (q != null && other(s) === side)
                this.armPdfPeer(s, q, this.pdfHoverPos.get(s) ?? null);
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

    /** DOM 悬停武装：同 sid 全集 sa-hot + 对侧 bead 全集 sa-peer +
        pdf 对侧 seq 桥 sa-peer。lastKey 由本函数记——dedup 键带侧名
        （en/zh 同 sid 配对撞 key 会互相吞悬停，见 attachBody）。 */
    private armHover(side: SaSide, st: SideState, sp: Element): void {
        const sid = sp.getAttribute("data-sid")!;
        const bead = sp.getAttribute("data-bead");
        this.lastKey = `${side}|${sid}|${bead ?? ""}`;
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
        if (
            this.pdfTargets.has(other(side)) &&
            this.deps.seqOfChunk &&
            this.deps.pdfHover
        ) {
            // DOM→PDF 悬停对位：seq↔chunk 1:1——对侧 pdf 注册即对位存在
            // （bead 是 DOM↔DOM 概念，pdf 对侧无 bead 也有 seq 对位）；
            // 块 key → seq → pdf 对侧 sa-peer（无 seq 传 null 清轨）
            const ck = block.getAttribute("data-chunk");
            const seq = ck ? this.deps.seqOfChunk(ck) : null;
            const dst = other(side);
            this.deps.pdfHover(
                dst,
                seq,
                seq != null ? (this.deps.seqPos?.(seq, dst) ?? null) : null,
                "sa-peer",
            );
        }
    }

    private attachBody(side: SaSide, st: SideState): void {
        const onOver = (e: Event) => {
            const t = e.target as Element | null;
            const sp = t?.closest?.("[data-sid]") ?? null;
            const key = sp
                ? `${side}|${sp.getAttribute("data-sid")}|${sp.getAttribute("data-bead") ?? ""}`
                : "";
            if (key === this.lastKey) return;
            this.clearHot();
            if (!sp) return;
            this.armHover(side, st, sp);
        };
        const onOut = (e: Event) => {
            const rel = (e as PointerEvent).relatedTarget as Element | null;
            const to = rel?.closest?.("[data-sid]") ?? null;
            // dedup 键带目标侧名——1:1 配对双侧 sid/bead 同字（实测 87.6%），
            // en→zh 直移若只比 sid|bead 会撞 key：out 被早退（en sa-hot 残留）、
            // over 被 dedup 吞（zh 永不染色）
            const key = to
                ? `${st.body.contains(to) ? side : other(side)}|${to.getAttribute("data-sid")}|${to.getAttribute("data-bead") ?? ""}`
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
            const from = this.animPress(
                (e as PointerEvent).clientX,
                (e as PointerEvent).clientY,
            );
            const dst = other(side);
            this.deps.navBegin?.();
            if (this.sides.get(dst)?.body) {
                // DOM→DOM：bead 粒度跳（无 bead = 对侧无对位，不跳）
                const bead = sp.getAttribute("data-bead");
                if (bead) this.jumpToBead(dst, bead, side, from);
                return;
            }
            // DOM→PDF（v1.5）：对侧无 DOM 无从对位——句内分位直跳，
            // 不依赖 bead（分位精度反而更高：m:n bead 内取本句起点）
            this.jumpSidToPdf(side, sp, from);
        };
        // 静止指针下滚动容器位移——悬停句挪走色相即失效（同 pdf 臂口径）
        const onScroll = () => this.clearHot();
        st.body.addEventListener("pointerover", onOver);
        st.body.addEventListener("pointerout", onOut);
        st.body.addEventListener("click", onClick);
        st.scroller.addEventListener("scroll", onScroll, {
            capture: true,
            passive: true,
        });
        st.detach.push(() => {
            st.body.removeEventListener("pointerover", onOver);
            st.body.removeEventListener("pointerout", onOut);
            st.body.removeEventListener("click", onClick);
            st.scroller.removeEventListener("scroll", onScroll, {
                capture: true,
            });
        });
    }

    private clearHot(): void {
        for (const el of this.hotEls) el.classList.remove("sa-hot");
        for (const el of this.peerEls) el.classList.remove("sa-peer");
        this.hotEls = [];
        this.peerEls = [];
        this.pdfPeerSentEls = null;
        this.lastKey = "";
        this.peerGen++; // pdf 悬停臂代次失效——同 seq 也要重补 peer
        // DOM→PDF 悬停对位臂的清场——两侧 pdf peer 一并剥（未挂 pdf
        // hover 时 pdfHover 缺省空调，代价=一次空调用；pdf 侧 saTint
        // 按类名认账，活着的 sa-hot 轨不被此清踩掉）
        this.deps.pdfHover?.("en", null, null, "sa-peer");
        this.deps.pdfHover?.("zh", null, null, "sa-peer");
    }

    private clearFlash(): void {
        for (const el of this.flashEls) el.classList.remove("sa-flash");
        this.flashEls = [];
    }

    /** 点击 ack——涟漪 + 返回连线源点（调用方沿跳路透传给 animLand；
        不落字段——半途 bail 的点不会被迟来的非点击跳误当起点，
        异步 pdfJump 各持各的源点不互踩）。 */
    private animPress(x: number, y: number): { x: number; y: number } {
        this.deps.anim?.press?.(x, y);
        return { x, y };
    }

    /** 落句动效——from=press 源点才有连线语义（null=非点击跳只擦入）；
        els 空/reduced-motion 由 anim 内拒。 */
    private animLand(
        from: { x: number; y: number } | null,
        els: Element[] | undefined,
    ): void {
        if (els?.length) this.deps.anim?.land?.(from, els);
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
        dest/jump 任一环落空静默收（deps 闸在调用方）。
        sent 在场（u 有值）→ 句级闪示优先：预选叶集 → 跳后重选
        （跳前页未渲缺席）→ 行带 → 整段逐级退。
        from 在同步点击路上取定后随闭包走——异步落地各持各源点。 */
    private pdfJumpFlash(
        dst: SaSide,
        pos: Pos,
        seq?: number | null,
        from?: { x: number; y: number } | null,
        sent?: { seq: number; u: number; els?: HTMLElement[] },
    ): void {
        // 每次起跳作废旧延迟重试（不止 sent 臂——行带跳也该压掉
        // 前一次跳留下的在途句级重选）
        const gen = ++this.flashGen;
        void Promise.resolve(this.deps.pdfDest!(dst, pos))
            .then((dest) => {
                if (!dest) return;
                return this.deps.pdfJump!(dst, dest).then((r) => {
                    if (!r) return;
                    this.deps.recordJump?.(dst, r.pre, r.post);
                    let els: Element[] | undefined;
                    if (sent) {
                        const trySent = (): Element[] | undefined => {
                            const hits = sent.els?.length
                                ? sent.els
                                : this.pdfSentAt(dst, sent.seq, sent.u)?.els;
                            if (hits?.length && this.deps.pdfFlashEls) {
                                this.deps.pdfFlashEls(dst, hits);
                                return hits;
                            }
                            return undefined;
                        };
                        els = trySent();
                        if (!els?.length) {
                            els = this.deps.pdfFlash?.(dst, r.post);
                            if (!els?.length && seq != null)
                                els = this.deps.pdfFlashSeq?.(
                                    dst,
                                    seq,
                                    r.post,
                                );
                            // 落点页懒渲（resolve 在 scroll 写位后、
                            // textLayer 未起，冷页实测 ~500ms）——
                            // 双拍重试；命中即封代际灭在途同伴；
                            // gen 闸挡窗内连点的陈旧闪示
                            if (!els?.length)
                                for (const ms of [160, 550])
                                    window.setTimeout(() => {
                                        if (gen !== this.flashGen) return;
                                        const late = trySent();
                                        if (late?.length) {
                                            this.flashGen++;
                                            this.animLand(
                                                from ?? null,
                                                late,
                                            );
                                        }
                                    }, ms);
                        }
                    } else {
                        els =
                            this.deps.pdfFlashSeq && seq != null
                                ? this.deps.pdfFlashSeq(dst, seq, r.post)
                                : this.deps.pdfFlash?.(dst, r.post);
                    }
                    // 滚动落定帧已过（pdfJump resolve 在 scroll 写位后）——
                    // els 行矩形此刻取连线终点才准
                    this.animLand(from ?? null, els ?? undefined);
                });
            })
            .catch(() => {}); // deps 拒收同落空口径——静默收
    }

    /** seq 锚页组叶集：marked 多现（TOC 重放+正文真标）按 seqPos 锚页
        择组，无锚页取裹字最多组；叶缺席/全空 → null */
    private seqLeafGroup(side: SaSide, seq: number): HTMLElement[] | null {
        const all = this.deps.pdfSeqLeaves?.(side, seq);
        if (!all?.length) return null;
        const anchorPage = this.deps.seqPos?.(seq, side)?.page ?? null;
        const groups = new Map<Element, HTMLElement[]>();
        for (const el of all) {
            const host = el.closest(MARKED_SEL) ?? el;
            const g = groups.get(host);
            if (g) g.push(el);
            else groups.set(host, [el]);
        }
        let leaves: HTMLElement[] | null = null;
        let bestLen = -1;
        for (const g of groups.values()) {
            const page = Number(
                g[0]!
                    .closest("[data-page-number]")
                    ?.getAttribute("data-page-number"),
            );
            if (anchorPage != null && page === anchorPage) {
                leaves = g;
                break;
            }
            const len = g.reduce(
                (a, el) => a + (el.textContent ?? "").length,
                0,
            );
            if (len > bestLen) {
                bestLen = len;
                leaves = g;
            }
        }
        return leaves;
    }

    /** dst pdf 侧句级落点+闪示集：seq 的 marked 叶文本重切句 →
        u·concatLen 所在句 → 句首叶 {page,fraction,x} 作落点 Pos、
        句域叶集作闪示面（与 DOM 臂 sents.find 同语义）。
        叶缺席/切空 → null（调用方退插值/直锚旧路）。 */
    private pdfSentAt(
        dst: SaSide,
        seq: number,
        u: number,
    ): { pos: Pos; els: HTMLElement[] } | null {
        const leaves = this.seqLeafGroup(dst, seq);
        if (!leaves?.length) return null;
        const offs: number[] = [];
        let concat = "";
        for (const el of leaves) {
            offs.push(concat.length);
            concat += el.textContent ?? "";
        }
        if (!concat.length) return null;
        const sents = (dst === "zh" ? splitZh : splitEn)(concat);
        if (!sents.length) return null;
        const target = clamp(u, 0, 1) * concat.length;
        const [s0, s1] =
            sents.find(([, e]) => e > target) ?? sents[sents.length - 1]!;
        const els = leaves.filter(
            (el, i) =>
                offs[i]! < s1 &&
                s0 < offs[i]! + (el.textContent ?? "").length,
        );
        if (!els.length) return null;
        // 句首叶 → 落点 Pos（posAtPoint 同口径：页号+页内 top-down
        // 分位+x 页宽分位）
        const pg = els[0]!.closest("[data-page-number]");
        const page = Number(pg?.getAttribute("data-page-number"));
        const pr = pg?.getBoundingClientRect();
        if (!pg || !Number.isFinite(page) || !pr?.height) return null;
        const r = els[0]!.getBoundingClientRect();
        const pos: Pos = {
            page,
            fraction: clamp((r.top - pr.top) / pr.height, 0, 1),
        };
        if (pr.width > 0)
            pos.x = clamp((r.left - pr.left) / pr.width, 0, 1);
        return { pos, els };
    }

    /** 指针元素所在句叶集（悬停句级揭示面）：seq 锚叶重切句 → 含 t 的
        叶定句，句域叶集返；t 非叶子孙/切空 → null（调用方退整锚/行带） */
    private pdfSentUnder(
        side: SaSide,
        seq: number,
        t: Element,
    ): HTMLElement[] | null {
        const leaves = this.seqLeafGroup(side, seq);
        if (!leaves?.length) return null;
        const hitIdx = leaves.findIndex((l) => l === t || l.contains(t));
        if (hitIdx < 0) return null;
        const offs: number[] = [];
        let concat = "";
        for (const el of leaves) {
            offs.push(concat.length);
            concat += el.textContent ?? "";
        }
        if (!concat.length) return null;
        const sents = (side === "zh" ? splitZh : splitEn)(concat);
        if (!sents.length) return null;
        const lo = offs[hitIdx]!;
        const hi = lo + (leaves[hitIdx]!.textContent ?? "").length;
        const sent =
            sents.find(([s0, s1]) => s0 <= lo && hi <= s1) ??
            sents.find(([s0, s1]) => lo < s1 && s0 < hi);
        if (!sent) return null;
        const els = leaves.filter(
            (el, i) =>
                offs[i]! < sent[1] &&
                sent[0] < offs[i]! + (el.textContent ?? "").length,
        );
        return els.length ? els : null;
    }

    /** 点击 → 对侧 bead 首元素跳转（DOM 侧）：scroller 滚位 + flash +
        recordJump（pre/post 由宿主 capture 供——无 capture 只跳不记）。
        from 缺省（gotoPeer 命令跳）→ 落句只擦入不连线。 */
    private jumpToBead(
        dst: SaSide,
        bead: string,
        _src: SaSide,
        from?: { x: number; y: number } | null,
    ): void {
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
        this.animLand(from ?? null, els);
        const post = st.capture?.() ?? null;
        this.deps.recordJump?.(dst, pre, post);
    }

    /** seq 精度点击分派（v2）：PDF 源侧 seqAtPoint 命中后的快路。
        srcPosAt 供块内分位 u（seq 锚记块首——点击落点按比例推进块内：
        DOM 臂落到所在句 span，pdf 臂 S→S' 区间线性插值）；无 seqLands
        dep/末块/未取位 → u=null 退块首锚。dst 是 DOM → seqOfChunk 找
        块元素滚位+sa-flash；dst 是 pdf → 插值位/seqPos 直锚 →
        pdfDest/pdfJump → pdfFlashSeq（锚闪）/pdfFlash（行带兜底）。
        不可落地 → false（调用方走位置映射兜底）。 */
    private jumpSeq(
        src: SaSide,
        seq: number,
        srcPosAt?: () => Pos | null,
        from?: { x: number; y: number } | null,
    ): boolean {
        const dst = other(src);
        const fb = this.fracInBlock(src, seq, srcPosAt);
        const u = fb?.u ?? null;
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
                // u 在场 → 目标句 span（块内偏移比块首更贴点）；查不到
                // 句/无 span 退整块锚
                let first = els[0] as HTMLElement;
                let flashSet: Element[] = els;
                if (u != null) {
                    const cs = st.chunks.get(
                        first.getAttribute("data-chunk") ?? "",
                    );
                    const sent = cs?.sents.length
                        ? (cs.sents.find(
                              (s) => s.end > u * cs.concatLen,
                          ) ?? cs.sents[cs.sents.length - 1]!)
                        : null;
                    const spans = sent
                        ? [
                              ...first.querySelectorAll(
                                  attrSel("data-sid", sent.sid),
                              ),
                          ]
                        : [];
                    if (spans.length) {
                        first = spans[0] as HTMLElement;
                        flashSet = spans;
                    }
                }
                const sr = st.scroller.getBoundingClientRect();
                st.scroller.scrollTop +=
                    first.getBoundingClientRect().top - sr.top - 12;
                this.flash(flashSet);
                this.animLand(from ?? null, flashSet);
                const post = st.capture?.() ?? null;
                this.deps.recordJump?.(dst, pre, post);
                return true;
            }
        }
        // dst 已渲染时优先句级落点——u·dst 文本长定句、句首叶定 Pos
        // （叶缺席退锚区间插值/直锚，行为同旧版）
        const sent = u != null ? this.pdfSentAt(dst, seq, u) : null;
        const pos =
            sent?.pos ??
            this.interpDst(dst, seq, u, fb?.span ?? null) ??
            this.deps.seqPos?.(seq, dst) ??
            null;
        if (!pos || !this.deps.pdfDest || !this.deps.pdfJump) return false;
        this.deps.navBegin?.();
        this.pdfJumpFlash(
            dst,
            pos,
            seq,
            from,
            u != null ? { seq, u, els: sent?.els } : undefined,
        );
        return true;
    }

    /** 源侧点击位的块内分位 u = (lin(click)−lin(S_src)) /
        (lin(S'_src)−lin(S_src)) clamp [0,1]——seq 锚是块首，S' 是
        阅读序下一锚（无下一锚=末块无从插值 → null）。srcPosAt 惰性
        取位：seqLands dep 缺席时一步不动（posAtPoint 调用序契约）。 */
    private fracInBlock(
        src: SaSide,
        seq: number,
        srcPosAt?: () => Pos | null,
    ): { u: number; span: number } | null {
        const lands = this.deps.seqLands?.(src);
        if (!lands?.length || !srcPosAt) return null;
        const i = lands.findIndex((l) => l.seq === seq);
        if (i < 0 || i + 1 >= lands.length) return null;
        const p0 = srcPosAt();
        if (!p0) return null;
        // 点击落在锚行幅面 [x,x1] 内且行带命中（宽行跨中缝——raw-x 栏判
        // 会把点击划去对栏，roLin 把 u 冲穿）→ 栏随锚行；否则同
        // containingSeq 栏降级：本页无右栏地标时右半点击退 col0，
        // 否则阅读序位落进空带 u 恒夹 1
        const sp = lands[i]!.pos;
        const onRow =
            p0.x != null &&
            sp.x != null &&
            sp.x1 != null &&
            p0.fraction - sp.fraction >= -ROW_UP &&
            p0.fraction - sp.fraction <= ROW_DOWN &&
            p0.x >= sp.x - ROW_EPSX &&
            p0.x <= sp.x1 + ROW_EPSX;
        const p = onRow
            ? { ...p0, x: sp.x }
            : p0.x != null &&
                p0.x >= 0.45 &&
                !lands.some(
                    (l) => l.pos.page === p0.page && colOf(l.pos) === 1,
                )
              ? { ...p0, x: 0 }
              : p0;
        const a = roLin(lands[i]!.pos);
        const d = roLin(lands[i + 1]!.pos) - a;
        if (d === 0) return null;
        return { u: clamp((roLin(p) - a) / d, 0, 1), span: d };
    }

    /** u 应用侧：dst 同 seq 区间 [S_dst,S'_dst) 线性插回 Pos；
        序列不齐/末块 → null（调用方退 seqPos 块首锚）。
        srcSpan 在场且块长可查时做文本幅面夹取——浮动体/跨页缝把
        dst 块区间撑成数倍文本高，u·Δdst 会把落点甩进图区/邻页；
        est_dst = srcSpan·(len_dst/len_src)·W（W 补字形宽差 zh2/en0.5），
        src 侧对称 rescale（src 块膨胀稀释的 u 除回 min(srcSpan,est_src)）。 */
    private interpDst(
        dst: SaSide,
        seq: number,
        u: number | null,
        srcSpan: number | null = null,
    ): Pos | null {
        if (u == null) return null;
        const lands = this.deps.seqLands?.(dst);
        if (!lands?.length) return null;
        const i = lands.findIndex((l) => l.seq === seq);
        if (i < 0 || i + 1 >= lands.length) return null;
        const pa = lands[i]!.pos;
        const pb = lands[i + 1]!.pos;
        let dDst = roLin(pb) - roLin(pa);
        if (srcSpan != null && srcSpan > 0) {
            const lenSrc = this.deps.chunkLen?.(seq, other(dst)) ?? 0;
            const lenDst = this.deps.chunkLen?.(seq, dst) ?? 0;
            if (lenSrc > 0 && lenDst > 0) {
                const r = (lenDst / lenSrc) * (dst === "zh" ? 2.0 : 0.5);
                const estDst = srcSpan * r;
                const estSrc = r > 0 ? dDst / r : dDst;
                u = clamp(
                    (u * srcSpan) / Math.max(1e-9, Math.min(srcSpan, estSrc)),
                    0,
                    1,
                );
                dDst = Math.min(dDst, estDst);
            }
        }
        const y = roLin(pa) + u * dDst;
        const page = Math.floor(y);
        const s = y - page; // 页内阅读序分位：[0,.5)=左栏 [.5,1)=右栏
        const col = s >= 0.5 ? 1 : 0;
        const out: Pos = {
            page,
            fraction: clamp((s - col * 0.5) * 2, 0, 0.999),
        };
        // x 沿两锚线性插补——单侧缺退单锚值，双缺不带（契约可选）
        const x =
            pa.x != null && pb.x != null
                ? pa.x + u * (pb.x - pa.x)
                : (pa.x ?? pb.x);
        if (x != null) out.x = clamp(x, 0, 1);
        return out;
    }

    /** DOM→PDF：seq 快路优先（chunk key→seq→seqPos 直锚，seq 精度+
        锚闪）；seqpos 缺席落回 sid 分位→mapPos→pdfDest 旧臂
        （sidPos 以块序充 page——对齐 kind:"pages" 才成立，pdf 视图
        下是粗近似兜底）。 */
    private jumpSidToPdf(
        src: SaSide,
        sp: Element,
        from?: { x: number; y: number } | null,
    ): void {
        const dst = other(src);
        if (!this.pdfTargets.has(dst) && !this.deps.pdfJump) return;
        const key = sp
            .closest("[data-chunk]")
            ?.getAttribute("data-chunk");
        const seq =
            key != null ? (this.deps.seqOfChunk?.(key) ?? null) : null;
        // 句内分位充块内插值的 u——seq 锚是块首，u 把落点推进块内
        // （seqLands dep 缺席时 interpDst 直接 null，等价旧版直锚）；
        // dst 叶在场时 pdfSentAt 直接给句级 Pos+闪集
        const sidP = this.sidPos(src, sp);
        const u = sidP?.fraction ?? null;
        const sent =
            seq != null && u != null ? this.pdfSentAt(dst, seq, u) : null;
        const sPos =
            seq != null
                ? (sent?.pos ??
                  this.interpDst(dst, seq, u) ??
                  this.deps.seqPos?.(seq, dst) ??
                  null)
                : null;
        if (sPos && this.deps.pdfDest && this.deps.pdfJump) {
            this.pdfJumpFlash(
                dst,
                sPos,
                seq,
                from,
                seq != null && u != null
                    ? { seq, u, els: sent?.els }
                    : undefined,
            );
            return;
        }
        if (!this.deps.mapPos || !this.deps.pdfDest || !this.deps.pdfJump)
            return;
        if (!sidP) return;
        this.pdfJumpFlash(dst, this.deps.mapPos(sidP, src), null, from);
    }

    /** PDF→PDF：源侧点击位 Pos → mapPos → pdfDest → pdfJump →
        recordJump + pdfFlash（jumpSidToPdf 同构，免 sidPos 句定位）。
        chunk/行带级精度上限——真句级 quad 高亮属 v2（需后端句锚）。 */
    private jumpPosToPdf(
        src: SaSide,
        pos: Pos,
        from?: { x: number; y: number } | null,
    ): void {
        const dst = other(src);
        if (!this.pdfTargets.has(dst) && !this.deps.pdfJump) return;
        if (!this.deps.mapPos || !this.deps.pdfDest || !this.deps.pdfJump)
            return;
        this.deps.navBegin?.();
        this.pdfJumpFlash(dst, this.deps.mapPos(pos, src), null, from);
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
