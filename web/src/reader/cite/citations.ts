// citations —— 引用锚面索引与文献条目抽取。
// 两条本地供给路（缺一即降级为「只有跳转没有卡」）：
//   ①buildCiteIndex(dual)：eprint 链主路——chunks[].ph 里 [[BIB_n]]→\bibitem
//     反查 bibkey→条目；条目正文=同 chunk en 中该 token 至下一 BIB token
//     的子串（掩码经 phText 解出可读文本）。`\bibliography{x}` 也产 BIB
//     token 但值非 \bibitem——按 ph 值前缀过滤。
//   ②extractBibAtDest(doc,dest)：pdf.js named dest → 目标页 textContent
//     兜底——.bbl/无 ph 链条目不进 chunks 但 cite.<key> 锚仍在，按 dest
//     落点行起向下收条目（悬挂缩进/段距/[n] 标签三类边界启发式）。
// 远端元数据（L2）不进本模块——服务端 refs 代理回包由 ReaderView 持有、
// 以 citeMeta 回调注入卡片。

import type { DualJson } from "../../api/client";
import type { RefMeta } from "../../api/types";
import { canonArxivKey } from "../../arxidcanon";
import { PH_TOKEN_RX, phText, RESIDUE_RULES } from "../logic/markdown";

export type { RefMeta };

export interface BibEntry {
    /** bibkey（\bibitem{key} / cite.<key> 锚名后缀） */
    key: string;
    /** 文献表序号（BIB 文档序 1-based；lazy dest 路未知为 0） */
    order: number;
    /** 显示标签：\bibitem[label] 优先，否则 [order] */
    label: string;
    /** 条目正文（掩码已解、排版残件已清的可读文本） */
    text: string;
    arxivId?: string;
    doi?: string;
}

export interface CiteIndex {
    /** bibkey 或 cite.<key> dest → 条目 */
    lookup(keyOrDest: string): BibEntry | undefined;
    entries(): BibEntry[];
    size: number;
}

const BIBITEM_VAL_RX = /^\\bibitem\b/;
const BIBITEM_KEY_RX = /\\bibitem\s*(?:\[([^\]]*)\]\s*)?\{([^}]*)\}/;

/** 新式 arXiv ID：YYMM.NNNNN——yymm 硬约束（year∈91..今年 | month∈01..12）
    防 `\d{4}.\d{4}` 式误报（research §3.1） */
function validNewArxivId(yymm: string): boolean {
    const yy = Number(yymm.slice(0, 2));
    const mm = Number(yymm.slice(2, 4));
    const curYY = new Date().getFullYear() % 100;
    const okYY = (yy >= 91 && yy <= 99) || (yy >= 0 && yy <= curYY);
    return okYY && mm >= 1 && mm <= 12;
}

/** 条目文本 → arXiv ID / DOI（L1 行动链接 + L2 远端解析的键） */
export function extractRefIds(text: string): {
    arxivId?: string;
    doi?: string;
} {
    let arxivId: string | undefined;
    const m1 =
        /(?:arxiv\.org\/(?:abs|pdf)\/|arXiv[:\s])([a-z-]+\/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?/i.exec(
            text,
        ) ?? /\b(\d{4}\.\d{4,5})(?:v\d+)?\b/.exec(text);
    if (m1) {
        const id = m1[1];
        if (id.includes("/") || validNewArxivId(id.slice(0, 4))) arxivId = id;
    }
    // 裸 DOI 臂（cite-translate §数据底盘：36.3%→43.3%）：\doi{}/\mn@doi{}/
    // doi={} 等不带 doi.org/doi: 前缀的形——5,325 条（7.1%）此前全漏。
    // 与带前缀臂同一捕获面：\b10\. 起、\S+ 收，条界残尾在出口统一剥。
    const m2 =
        /(?:doi\.org\/|doi[:\s]+)(10\.\d{4,9}\/\S+)/i.exec(text) ??
        /\b(10\.\d{4,9}\/\S+)/.exec(text);
    const doi = m2?.[1]?.replace(/[.,;\])}]+$/, "");
    return { arxivId, doi };
}

/**
 * arXiv/DOI id 匹配键（cite-translate 双侧 canon——条目侧与 task 行
 * arxiv_id 两侧都过本函数才比）：canonArxivKey（arxidcanon.ts 单源）的
 * 本域惯名别名。校验非职责——坏输入只是匹配不上（strict canon 是
 * parseArxivId/服务端 normalize_arxiv_id 的事）。
 */
export const canonRefId = canonArxivKey;

/** 文本级掩码解析 + 排版残件清理（unmaskLatex 的纯字符串对应物） */
function cleanBibText(raw: string, ph: Record<string, string>): string {
    let s = raw.replace(PH_TOKEN_RX, (_m, kind: string, n: string) => {
        const body = ph[`[[${kind}_${n}]]`];
        return body != null ? (phText(kind, body) ?? "") : "";
    });
    for (let i = 0; i < 3; i++) {
        const prev = s;
        for (const [rx, rep] of RESIDUE_RULES) s = s.replace(rx, rep);
        if (s === prev) break;
    }
    return s.replace(/\s{2,}/g, " ").trim();
}

/** dual.json chunks → bibkey 索引；无 \bibitem 时 size=0（走兜底路） */
export function buildCiteIndex(dual: DualJson | null | undefined): CiteIndex {
    const map = new Map<string, BibEntry>();
    let order = 0;
    for (const c of dual?.chunks ?? []) {
        const ph = c.ph;
        if (!ph) continue;
        const en = c.en ?? "";
        // chunk 内全部掩码 token 的出现序——BIB token 的条目正文终点是
        // 下一个 BIB token 起点（跨 chunk 的尾条在 chunk 尾截断）
        const toks: { idx: number; end: number; kind: string; n: string }[] =
            [];
        PH_TOKEN_RX.lastIndex = 0;
        let m: RegExpExecArray | null;
        while ((m = PH_TOKEN_RX.exec(en)))
            toks.push({
                idx: m.index,
                end: m.index + m[0].length,
                kind: m[1],
                n: m[2],
            });
        for (let i = 0; i < toks.length; i++) {
            const tk = toks[i];
            if (tk.kind !== "BIB") continue;
            const body = ph[`[[BIB_${tk.n}]]`];
            if (!body || !BIBITEM_VAL_RX.test(body.trim())) continue;
            const km = BIBITEM_KEY_RX.exec(body.trim());
            if (!km) continue;
            const key = km[2].trim();
            const nextBib = toks.slice(i + 1).find((t) => {
                const b = ph[`[[${t.kind}_${t.n}]]`];
                return (
                    t.kind === "BIB" &&
                    b != null &&
                    BIBITEM_VAL_RX.test(b.trim())
                );
            });
            const rawText = en.slice(tk.end, nextBib?.idx ?? en.length);
            const text = cleanBibText(rawText, ph);
            order += 1;
            const label = km[1]?.trim() || `[${order}]`;
            map.set(key, {
                key,
                order,
                label,
                text,
                ...extractRefIds(text),
            });
        }
    }
    return {
        size: map.size,
        lookup(keyOrDest) {
            const key = keyOrDest.startsWith("cite.")
                ? keyOrDest.slice(5)
                : keyOrDest;
            return map.get(key);
        },
        entries() {
            return [...map.values()];
        },
    };
}

// ---------------------------------------------------------------- PDF dest 兜底

export interface PdfDocLike {
    getDestination(name: string): Promise<unknown[] | null>;
    /** pdf.js≥4 返回 Map（含 name-tree 锚）；老版本为 Record——消费方须两形兼容 */
    getDestinations?(): Promise<
        Map<string, unknown> | Record<string, unknown> | null
    >;
    getPageIndex(ref: unknown): Promise<number>;
    getPage(n: number): Promise<PdfPageLike>;
}
export interface PdfPageLike {
    getViewport(o: { scale: number }): { height: number; width: number };
    getTextContent(): Promise<{
        items: { str: string; transform: number[] }[];
    }>;
}

interface TextLine {
    y: number; // pdf 用户空间（自底向上）
    minX: number;
    str: string;
}

export interface DestPoint {
    /** 页引用（getPageIndex 直喂） */
    ref: unknown;
    /** pdf 用户空间 y（bottom-up）；Fit/FitV/XYZ-null 等整页锚为 null */
    y: number | null;
    /** pdf 用户空间 x（仅 XYZ 携带）；缺席 null */
    x: number | null;
}

/** named/explicit dest 数组 → 落点。y 槽位随 fit 型而变：
    XYZ=[ref,XYZ,left,top,zoom]、FitH/FitBH=[ref,FitH,top]、
    FitR=[ref,FitR,left,bottom,right,top]；Fit/FitB/FitV/FitBV 与
    XYZ null-top 无 y。extractBibAtDest 与 PdfPane destPos 的单一解析点。 */
export function destPointOf(dest: unknown): DestPoint | null {
    if (!Array.isArray(dest) || dest.length < 2) return null;
    const kind = (dest[1] as { name?: string } | undefined)?.name ?? "";
    let x: number | null = null;
    let y: number | null = null;
    if (kind === "XYZ") {
        x = dest[2] == null ? null : Number(dest[2]);
        y = dest[3] == null ? null : Number(dest[3]);
    } else if (kind === "FitH" || kind === "FitBH") {
        y = Number(dest[2]);
    } else if (kind === "FitR") {
        y = Number(dest[5]);
    }
    if (x !== null && !Number.isFinite(x)) x = null;
    if (y !== null && !Number.isFinite(y)) y = null;
    return { ref: dest[0], x, y };
}

/** 新条目边界启发式：行首 `[n]`/`[Author …]` 标签（首行自身不算） */
const BIB_LABEL_RX = /^\s*\[[A-Za-z0-9][^\]]{0,60}\]/;

/**
 * cite.<key> named dest → 落点页 textContent 里收文献条目文本。
 * 行分组按 pdf 用户空间 y（自底向上——条目后续行 y 递减）；边界：
 * 大段距（>1.7×行高）、左缩进回退（悬挂缩进的下一条）、行首标签。
 */
export async function extractBibAtDest(
    doc: PdfDocLike,
    destName: string,
): Promise<{ text: string } | null> {
    let dest: unknown[] | null;
    try {
        dest = await doc.getDestination(destName);
    } catch {
        return null;
    }
    const pt = destPointOf(dest);
    if (!pt) return null;
    const ref = pt.ref;
    // ICLR/ICML/CoRL 模板 pdfview=FitH 的 cite.* 锚正是 len-3 FitH，
    // 老代码 len<4 直接 null 是实测踩中的坑——y=null 走首标签兜底
    const targetY = pt.y;
    let page: PdfPageLike;
    try {
        const idx = await doc.getPageIndex(ref);
        page = await doc.getPage(idx + 1);
    } catch {
        return null;
    }
    // pane 拆解（keyed 重挂）会 destroy loadingTask——在途 worker 调用
    // reject/orphan，调用方无 catch 时既是 unhandled rejection 又让卡永转
    let tc: { items: { str: string; transform: number[] }[] };
    let vpH: number;
    try {
        tc = await page.getTextContent();
        vpH = page.getViewport({ scale: 1 }).height;
    } catch {
        return null;
    }

    // item.transform = [a,b,c,d,e,f]——f 是 viewport 系 top-origin y，
    // 换回 pdf 用户空间：y_pdf = vp.height - f；x_pdf = e
    const lines: TextLine[] = [];
    for (const it of tc.items) {
        if (!it.str.trim()) continue;
        const y = vpH - it.transform[5];
        const x = it.transform[4];
        const last = lines[lines.length - 1];
        if (last && Math.abs(last.y - y) < 2.5) {
            last.str += it.str;
            if (x < last.minX) last.minX = x;
        } else {
            lines.push({ y, minX: x, str: it.str });
        }
    }
    if (!lines.length) return null;
    // y 降序（页面自上向下）
    lines.sort((a, b) => b.y - a.y);

    let start = -1;
    if (targetY !== null) {
        // dest 落点行：|lineY - targetY| 最近且在半行距内
        let best = Infinity;
        for (let i = 0; i < lines.length; i++) {
            const d = Math.abs(lines[i].y - targetY);
            if (d < best) {
                best = d;
                start = i;
            }
        }
        if (best > 9) return null;
    } else {
        // dest 无 y（Fit/FitV/XYZ-null）——退页内首个条目标签行；
        // 锚无坐标时 pdf.js 自己也只跳整页，取首标签是最佳可用近似
        start = lines.findIndex((l) => BIB_LABEL_RX.test(l.str));
    }
    if (start < 0) return null;

    const destLine = lines[start];
    const picked = [destLine.str];
    let prevY = destLine.y;
    let lineH = 0;
    for (let i = start + 1; i < lines.length && picked.length < 10; i++) {
        const ln = lines[i];
        const gap = prevY - ln.y; // 自上向下 y 递减 → 正 gap
        if (lineH === 0) lineH = gap;
        if (lineH > 0 && gap > lineH * 1.7) break; // 段距跳变 → 新块
        if (BIB_LABEL_RX.test(ln.str)) break; // 行首标签 → 下一条目
        if (ln.minX < destLine.minX - 3) break; // 左缩进回退 → 悬挂缩进的下一条
        picked.push(ln.str);
        prevY = ln.y;
    }
    const text = picked
        .join(" ")
        .replace(/\s{2,}/g, " ")
        .trim();
    return text ? { text } : null;
}
