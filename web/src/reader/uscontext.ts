// uscontext —— 引用语境句抽取（find-usages lane 的句库内核）。
// 三条供给路，输出同型 {text,start,end}：
//   DOM 路  sentenceAround(block, anchor)——dom 视图 pane DOM 干净文本句切
//           （fu-popover-spike figIndex.ts 逐字移植）；
//   掩码路  maskedSentenceAt(text, ph, s, e)——dual.json 源文路
//           （texlate.xlat.batch.sentence_ends 忠实移植：{}depth 跟踪 +
//           \\ 转义双跳 + depth==0 的 .!? 后随空白/[[SL]]/[[PL]] 才切 +
//           abbrev_cut 缩写位豁免；[[PL]] 与空行是硬界）；
//   zh 路   zhTokenSentence(zhText, ph, tokName)——同名 [[CITE_n]] token
//           在 zh 文本存活（fu-bib-reverse 777/777）→ 同法扩 zh 句界
//           （CJK 。！？无空白亦界）。
// 可读化 = markdown.ts 的 phText + RESIDUE_RULES 纯字符串复用。

import { PH_TOKEN_RX, phText, RESIDUE_RULES } from "./markdown";

// ================================================================ DOM 路

/** 干净文本剥离集——annotation(TeX alttext)/script/style 不进句文本 */
const SKIP_RX = "annotation,script,style,noscript,template";

/** 引用句块容器——LaTeXML 正文句都在 p/li/caption/note 内 */
export const BLOCK_RX = "p, li, td, th, figcaption, .ltx_p, .ltx_note";

/** 句界扫描：西文 . ! ? 需跟空白（"3.5"/"Fig.2" 不切）；
    CJK 。！？后无空白也是边界（"句。下句" 形态） */
const PUNCT_RX = /[.!?。！？]+/g;
const CLOSERS = ")]}'\"”’»";

/** 缩写护栏：扫描到 "." 边界时回看前文，命中则跳过。
    覆盖 LaTeXML 语料高频：Fig/Figs/Eq/Eqs/Sec/Table/No/Vol/pp/cf/vs/
    e.g/i.e/et al/resp/approx/ca/Dr/Mr/Ms/St/Jr + 单字母缩写（A. Smith） */
const ABBREV_TAIL_RX =
    /(?:^|[\s([{"'""'‘])(?:Fig|Figs|fig|figs|Eq|Eqs|eq|eqs|Sec|Secs|sec|Sect|Table|Tab|No|Nos|Vol|vol|pp|p|cf|Cf|vs|viz|resp|approx|ca|Dr|Mr|Ms|Mrs|St|Jr|Sr|Prof|Rep|Sen|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|al|[A-Z])$/;

interface CleanMap {
    text: string;
    /** 锚在干净文本中的字符区间 [start,end) */
    anchorStart: number;
    anchorEnd: number;
}

/** block → 干净文本 + 锚偏移。递归走子树：SKIP_RX 子树整体剥离；
    锚自身文本计入干净文本（"Figure [1]" 的 1 是句的一部分）。 */
function cleanTextWithAnchor(
    block: HTMLElement,
    anchor: Element,
): CleanMap | null {
    let text = "";
    let anchorStart = -1;
    let anchorEnd = -1;
    const visit = (node: Node, inAnchor: boolean) => {
        if (node.nodeType === 3 /* TEXT_NODE */) {
            const v = node.nodeValue ?? "";
            if (inAnchor && anchorStart < 0) anchorStart = text.length;
            text += v;
            if (inAnchor) anchorEnd = text.length;
            return;
        }
        if (node.nodeType !== 1) return;
        const el = node as Element;
        if (el.matches(SKIP_RX)) return;
        const nowAnchor = inAnchor || el === anchor;
        if (el === anchor && anchorStart < 0) anchorStart = text.length;
        for (const ch of el.childNodes) visit(ch, nowAnchor);
        if (el === anchor && anchorEnd < 0) anchorEnd = text.length;
    };
    for (const ch of block.childNodes) visit(ch, false);
    if (anchorStart < 0) return null;
    if (anchorEnd < 0) anchorEnd = text.length;
    return { text, anchorStart, anchorEnd };
}

/** 干净文本上的句界集合（返回升序起点数组）。 */
export function sentenceStarts(text: string): number[] {
    const starts = [0];
    PUNCT_RX.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = PUNCT_RX.exec(text))) {
        const p0 = m.index;
        let i = p0 + m[0].length;
        // 吃标点后的连续闭括号/引号（"(Figure 2)." 的 ")." 形态）
        while (i < text.length && CLOSERS.includes(text[i])) i++;
        const ch = text[p0];
        if (ch === "。" || ch === "！" || ch === "？") {
            // CJK 句界无需空白；文末不算新起点
            if (i < text.length) starts.push(i);
            continue;
        }
        if (i >= text.length) continue; // 文末标点不算新起点
        const ws = /^\s+/.exec(text.slice(i));
        if (!ws) continue; // 西文句界必须跟空白（挡掉 "3.5"、"d_k.x"）
        // "." 边界回看缩写——"Fig. 3" / "et al. (2020)" 不切
        if (ch === ".") {
            const before = text.slice(Math.max(0, p0 - 24), p0);
            if (ABBREV_TAIL_RX.test(before)) continue;
            // "e.g." / "i.e." 双点形态：前一个字符也是 "."
            if (text[p0 - 1] === ".") continue;
        }
        starts.push(i + ws[0].length);
    }
    return starts;
}

/** block+anchor → 含锚句的 [start,end) 与文本；anchorStart = 锚在块干净
    文本中的字符偏移（UsageAnchor.charOff 源）。锚不在块内返回 null */
export function sentenceAround(
    block: HTMLElement,
    anchor: Element,
): { text: string; start: number; end: number; anchorStart: number } | null {
    const cm = cleanTextWithAnchor(block, anchor);
    if (!cm) return null;
    const starts = sentenceStarts(cm.text);
    // 含锚句 = 最后一个 start <= anchorStart 的段，终点=下一段起点或文末
    let i = 0;
    while (i + 1 < starts.length && starts[i + 1] <= cm.anchorStart) i++;
    const start = starts[i];
    const end = starts[i + 1] ?? cm.text.length;
    const text = cm.text.slice(start, end).replace(/\s+/g, " ").trim();
    return text ? { text, start, end, anchorStart: cm.anchorStart } : null;
}

// ================================================================ 可读化

/** 剥 body 顶层 `{...}` 组内容（组内花括号保留）——cite 键表兜底解析用 */
function braceGroups(body: string): string[] {
    const out: string[] = [];
    let depth = 0;
    let cur = "";
    for (const ch of body) {
        if (ch === "{") {
            depth++;
            if (depth > 1) cur += ch;
        } else if (ch === "}") {
            depth--;
            if (depth === 0) {
                out.push(cur);
                cur = "";
            } else {
                cur += ch;
            }
        } else if (depth > 0) {
            cur += ch;
        }
    }
    return out;
}

/** 文本级掩码解析 + 排版残件清理（unmaskLatex 的纯字符串对应物） */
export function unmaskText(raw: string, ph: Record<string, string>): string {
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

// ================================================================ 掩码路

/** `\cite` 族命令（\cite/\citet/\citep/\nocite/\citeauthor…）可选参后键表组
    ——textutil/cite.py CITE_FAMILY_RE 镜像 */
const CITE_FAMILY_RX =
    /\\[a-zA-Z@]*cite[a-zA-Z@]*\*?\s*(?:\[[^\]\n]*\]\s*)*\{([^}]*)\}/;

/** ph 体 → bibkey 列表：正常 `\cite{a,b}` 逗号拆；畸形 mega-key
    （`\citealp{a}; \citealp[opt]\n{b}`）回退最后一个 brace 组 */
export function citeKeys(body: string): string[] {
    const m = CITE_FAMILY_RX.exec(body);
    const keystr = m ? m[1] : (braceGroups(body).pop() ?? "");
    return keystr
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
}

/** 切点前尾词——``Fig.``/``e.g.``/``et al.``/``Sec.`` 缩写位识别用 */
const ABBREV_WORD_RX = /([A-Za-z][A-Za-z.]*)$/;
/** 无点尾词的缩写长度上界（Fig/Sec/Eq/Dr 系） */
const ABBREV_MAX_WORD = 3;

/** ``text[i]``（``.!?`` 位）是缩写尾点则不切——batch.abbrev_cut 逐字移植：
    尾词含 ``.``（``e.g.``/``al.``）或 ≤3 字母（``Fig``/``Sec``/``Dr``）→
    缩写位。保守向偏欠切——``is.``/``wow!`` 这类真句尾小词也被放过，
    欠切只让块偏大，过切才毁句。 */
function abbrevCut(text: string, i: number): boolean {
    const m = ABBREV_WORD_RX.exec(text.slice(0, i));
    if (!m) return false;
    const w = m[1];
    return w.includes(".") || w.length <= ABBREV_MAX_WORD;
}

/** 掩码态文本的句界切点集——batch.sentence_ends 移植：
    depth==0 的 ``.!?`` 后随 `` ``/``\n``/``[[SL]]``/``[[PL]]`` 才切；
    ``\\`` 转义双跳 + ``{}`` 深度跟踪 + abbrevCut 豁免。
    附加 CJK 。！？无空白切点（zh 文本句界；en 源文几乎不含 CJK 字，
    恒开无副作用）。返回「句段起点」升序数组（切点在标点后随符之后）。 */
export function maskedSentenceStarts(text: string): number[] {
    const starts = [0];
    const n = text.length;
    let depth = 0;
    let i = 0;
    while (i < n) {
        const c = text[i];
        if (c === "\\") {
            i += 2;
            continue;
        }
        if (c === "{") {
            depth++;
            i++;
            continue;
        }
        if (c === "}") {
            depth = Math.max(0, depth - 1);
            i++;
            continue;
        }
        if (c === "。" || c === "！" || c === "？") {
            // CJK 句界：吃尾随闭括号/引号后，无需空白即新起点
            let j = i + 1;
            while (j < n && CLOSERS.includes(text[j])) j++;
            if (j < n) starts.push(j);
            i++;
            continue;
        }
        if ((c === "." || c === "!" || c === "?") && depth === 0) {
            let j = i + 1;
            // 吃标点后的连续闭括号/引号——与 DOM 路同口径
            while (j < n && CLOSERS.includes(text[j])) j++;
            const after = text.slice(j);
            if (/^\[\[\s*(?:SL|PL)\s*\]\]/.test(after) || /^\s/.test(after)) {
                if (!abbrevCut(text, i)) {
                    // 吞掉后随空白与换行 token——句段起点落在可见文本处
                    const wm = /^(?:\[\[\s*(?:SL|PL)\s*\]\]|\s)+/.exec(after);
                    const next = j + (wm ? wm[0].length : 0);
                    if (next < n) starts.push(next);
                }
            }
        }
        i++;
    }
    return starts;
}

/** 掩码态硬界：``[[PL]]`` 与空行——边界两侧位置都算切点 */
const HARD_BREAK_RX = /\[\[\s*PL\s*\]\]|\n\s*\n/g;

/** 掩码态 chunk 内 [start,end) 所在句 span：左右扩至最近句界或硬界，
    unmask 后给可读文本。 */
export function maskedSentenceAt(
    text: string,
    ph: Record<string, string> | undefined,
    start: number,
    end: number,
): { text: string; start: number; end: number } | null {
    const bounds = new Set<number>([0, text.length]);
    for (const s of maskedSentenceStarts(text)) bounds.add(s);
    HARD_BREAK_RX.lastIndex = 0;
    let hm: RegExpExecArray | null;
    while ((hm = HARD_BREAK_RX.exec(text))) {
        bounds.add(hm.index);
        bounds.add(hm.index + hm[0].length);
    }
    let left = 0;
    let right = text.length;
    for (const b of bounds) {
        if (b <= start && b > left) left = b;
        if (b >= end && b < right) right = b;
    }
    const raw = text.slice(left, right);
    const readable = unmaskText(raw, ph ?? {});
    return readable ? { text: readable, start: left, end: right } : null;
}

// ================================================================ zh 路

/** zh 文本中同名 ``[[CITE_n]]`` token 位 → zh 语境句（token 存活即句界
    对称——fu-bib-reverse 777/777；token 缺失返回 null，卡面隐 zh 行）。 */
export function zhTokenSentence(
    zhText: string | undefined,
    ph: Record<string, string> | undefined,
    tokName: string,
): string | null {
    if (!zhText) return null;
    const km = /^\[\[\s*([A-Z]+)\s*_?(\d+)\s*\]\]$/.exec(tokName);
    if (!km) return null;
    const want = `${km[1]}_${km[2]}`;
    // matchAll 克隆迭代——maskedSentenceAt→unmaskText 内部复用共享
    // PH_TOKEN_RX（replace 会重置 lastIndex），裸 exec 循环可能死循环
    for (const m of zhText.matchAll(PH_TOKEN_RX)) {
        if (`${m[1]}_${m[2]}` !== want) continue;
        const s = maskedSentenceAt(
            zhText,
            ph ?? {},
            m.index,
            m.index + m[0].length,
        );
        return s?.text ?? null;
    }
    return null;
}
