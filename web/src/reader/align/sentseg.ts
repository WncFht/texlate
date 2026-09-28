// sentseg —— 句级切分叶（w4 自 sentalign.ts 拆出；全 lane 规格注释见
// sentalign.ts 头）。三段：
//   splitZh   zhseg.py 的正则臂移植（「。！？!?…+闭引号」run、ASCII '.'
//             过 _abbrev_dot 闸、_GUARD_RX 保护区、{} 深度>0 抑制、\\
//             双跳、句尾吸收随行空白）——Intl.Segmenter zh 对 Latin
//             缩写系统性过切，禁用（实施文档 §风险 15）。
//   splitEn   Intl.Segmenter("en",sentence)，输入先扁平化（\n 等长
//             换空格——RAW 变体在 \n 处乱切 4571 vs 4025，禁直切原文）。
//   sentLen   去掩码可见长——splitEn 的占位片判与 inject 的 len/对位
//             cost 共口径（随切句走：en 臂 carry 判调用它，留在对位叶
//             会造 sentseg→sentbeads 反向边）。
// 模块级 g-flag 正则（ZH_*_RX）靠函数内 lastIndex=0 复位、enSeg 是
// Intl.Segmenter 单例——必须与所属函数同文件，拆半留跨文件可变共享态。

// ------------------------------------------------------------------ 类型

export type SaSide = "en" | "zh";
/** 句区间（半开 [start,end)，拼接文本坐标） */
export type SentSpan = readonly [number, number];

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
        while (
            e < n &&
            (text[e] === " " || text[e] === "\t" || text[e] === "\n")
        )
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
            const pseg = flat
                .slice(prev[0], prev[1])
                .replace(EN_CLOSERS_RX, "");
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

/** 掩码 token——对位长度只计可见文本（en_len/zh_len 同口径） */
const PH_RX =
    /\[\[[A-Z][A-Z_]*(?:_?\d+)?\]\]|\[\[__TEXLATE_[A-Z_]+_LIT\d+__\]\]|⟪[A-Z]\d+⟫/g;

/** 对位长度：去掩码、去全部空白。 */
export const sentLen = (s: string): number =>
    s.replace(PH_RX, " ").replace(/\s+/g, "").length;
