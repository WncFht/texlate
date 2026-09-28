// sentinject —— DOM 注入叶（w4 自 sentalign.ts 拆出；全 lane 规格注释见
// sentalign.ts 头）：align-inject 的 piecewise 包裹——TreeWalker 收文本→
// 切句→倒序 splitText 逐片包 span.ens/zhs[data-sid="{chunk}.{k}"]。
//   元素从不搬家（只分文本节点）——<a>/<em> 跨界句产多片同 sid span
//   （49% sid 多片段实证）；RESTRICTED_SPAN_PARENTS 内留裸片防
//   foster-parenting；嵌套 [data-chunk] 经 closest 闸防 footnote 幽灵句。
//
// sid 协议："{data-chunk}.{k}"（k=块内非空句序位，0 起）。
// 契约：sid → 元素集合——任何消费方一律 querySelectorAll，禁单元素假设。

import { sentLen, splitEn, splitZh, type SaSide } from "./sentseg";

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
    for (const sp of [...block.querySelectorAll<HTMLElement>("[data-sid]")]) {
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
                RESTRICTED_SPAN_PARENTS.has((parent as Element).localName);
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
