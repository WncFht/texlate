// copylatex —— 「复制 LaTeX 源」纯逻辑层（copy-latex lane，可 vitest）。
// 规格锚点 = docs/dev/ux-impl-2026-09-22/copy-latex 实现文档：
//   mathTexFrom(el)   三级提取：math[alttext]（dom 链，与 annotation 逐字节
//                     相同 8907/8907）→ .katex annotation[x-tex]（html/live，
//                     phText 剥界符形）→ 皆无懒载 mathml-to-latex（外源
//                     MathML/MathJax assistive-mml，标 approx）。
//   selChunks(b,r)    Range.intersectsNode 扫 [data-chunk] → seq 闭区间 +
//                     首/尾边界段 anchor 文本各 ≤400（含选区边缘上下文）。
//   pdfSeqsForText    pdf 无 DOM 锚：选区文本归一化后对 dual.chunks[].en/zh
//                     做 token 级 difflib 最长块锚定——只段级不做偏移级。
//   copyText(s)       navigator.clipboard.writeText + textarea execCommand
//                     兜底（iframe/失焦/非 secure context 降级链）。
//
// 安全约定：本文件只产纯串——alttext/annotation/选区文本绝不 innerHTML。

import { t } from "../i18n";

// ---------------------------------------------------------------- i18n 兜底

/**
 * t-path 解析 + 回退串——i18n 键在整合期才进 zh.ts/en.ts（i18n.test.ts
 * parity 守护），此间以 fb 双语句兜底；键落地后自动走 t.*。
 * 用法：clText("reader.copyLatex.copy", "复制")。
 */
export function clText(path: string, fb: string): string {
    let cur: unknown = t;
    for (const k of path.split(".")) {
        if (cur == null || typeof cur !== "object") return fb;
        cur = (cur as Record<string, unknown>)[k];
    }
    return typeof cur === "string" ? cur : fb;
}

// ---------------------------------------------------------------- 公式提取

export interface MathTex {
    tex: string;
    /** true = mathml-to-latex 重构（缺注释/语义等价非逐字节——卡/toast 须标） */
    approx: boolean;
}

const ANN_SEL = "annotation[encoding='application/x-tex']";

/** alttext → annotation[x-tex] 两路同步提取（无懒载）。 */
export function mathTexSync(el: Element | null): MathTex | null {
    if (!el) return null;
    const alt = el.getAttribute("alttext");
    if (alt && alt.trim()) return { tex: alt, approx: false };
    const ann = el.matches(ANN_SEL)
        ? el
        : el.querySelector(ANN_SEL);
    const t = ann?.textContent?.trim();
    return t ? { tex: t, approx: false } : null;
}

/** el 自身/后代首个 <math> 的 outerHTML（MathML 兜底臂的喂入体）。 */
function mathmlOf(el: Element): string | null {
    const tag = el.tagName;
    if (tag === "math" || tag === "MATH") return el.outerHTML;
    return el.querySelector("math")?.outerHTML ?? null;
}

type Mml2Tex = (mathml: string) => string | Promise<string>;

/** 懒载单例——165KB 包只在真兜底路径上付一次代价。 */
let m2lPromise: Promise<Mml2Tex> | null = null;
const loadM2L = (): Promise<Mml2Tex> => {
    m2lPromise ??= import("mathml-to-latex").then(
        (m) => (s: string) => m.MathMLToLaTeX.convert(s),
    );
    return m2lPromise;
};

/**
 * 三级提取入口。opts.convert 可注入假实现（vitest 不拉真包）；
 * 缺省走懒载 mathml-to-latex。全路败北 → null。
 */
export async function mathTexFrom(
    el: Element | null,
    opts: { convert?: Mml2Tex } = {},
): Promise<MathTex | null> {
    const sync = mathTexSync(el);
    if (sync) return sync;
    if (!el) return null;
    const mml = mathmlOf(el);
    if (!mml) return null;
    try {
        const conv = opts.convert ?? (await loadM2L());
        const tex = (await conv(mml)).trim();
        return tex ? { tex, approx: true } : null;
    } catch {
        return null; // 转换失败与无源同归——调用面按「无源」提示
    }
}

/** 行内/展示式判定：math[display=block]/.katex-display/ltx 展示容器 → false。 */
export function mathIsInline(el: Element): boolean {
    const disp = el.getAttribute("display");
    if (disp === "block") return false;
    return (
        el.closest(
            ".katex-display, .ltx_equation, .ltx_eqn_table, .ltx_display_math, mjx-container[jax='CHTML'][display='true']",
        ) == null
    );
}

// ---------------------------------------------------------------- 选区→chunk

export interface SelChunks {
    /** 命中的 data-chunk 键（文档序） */
    keys: string[];
    /** int seq 闭区间 [min..max] 展开——跨段选区必须把中间段一并切出 */
    seqs: number[];
    /** 首边界段内选区文本（≤cap，保首缘）；无命中/无锚 undefined */
    head?: string;
    /** 尾边界段内选区文本（≤cap，保尾缘） */
    tail?: string;
}

const DEFAULT_ANCHOR_CAP = 400;

/** data-chunk 键 → int seq；缺省只认纯数字键（html/live 链 seq 直书）。 */
const defaultSeqOf = (key: string): number | null =>
    /^\d+$/.test(key) ? Number(key) : null;

/**
 * bodyEl 下与 range 相交的 [data-chunk] → seq 闭区间 + 边界 anchor。
 * 文档序首个命中块 = head 侧、末个 = tail 侧；anchor 是选区在该块内的
 * 交集文本（服务端在边界切片内 difflib 定位后外扩句界——cl-arb-sel
 * anchor 臂 med 误差 0）。嵌套锚（figure 内子块）按文档序取最外首/
 * 最内尾，seq 闭区间天然含中间块。
 */
export function selChunks(
    bodyEl: Element,
    range: Range,
    opts: {
        seqOf?: (key: string) => number | null;
        anchorCap?: number;
    } = {},
): SelChunks {
    const cap = opts.anchorCap ?? DEFAULT_ANCHOR_CAP;
    const seqOf = opts.seqOf ?? defaultSeqOf;
    const doc = bodyEl.ownerDocument!;
    const hits: { el: Element; key: string; seq: number | null }[] = [];
    for (const el of bodyEl.querySelectorAll("[data-chunk]")) {
        let inRange = false;
        try {
            inRange = range.intersectsNode(el);
        } catch {
            /* 游离节点（jsdom/重绘中）按未命中 */
        }
        if (!inRange) continue;
        const key = el.getAttribute("data-chunk") ?? "";
        hits.push({ el, key, seq: seqOf(key) });
    }
    const nums = hits
        .map((h) => h.seq)
        .filter((n): n is number => n != null);
    const seqs: number[] = [];
    if (nums.length) {
        const lo = Math.min(...nums);
        const hi = Math.max(...nums);
        for (let s = lo; s <= hi; s++) seqs.push(s);
    }

    /** 选区 ∩ 元素文本——clamp 双侧端点到元素界 */
    const intersectText = (el: Element): string => {
        const er = doc.createRange();
        er.selectNodeContents(el);
        const sub = range.cloneRange();
        try {
            if (sub.compareBoundaryPoints(Range.START_TO_START, er) < 0)
                sub.setStart(er.startContainer, er.startOffset);
            if (sub.compareBoundaryPoints(Range.END_TO_END, er) > 0)
                sub.setEnd(er.endContainer, er.endOffset);
            return sub.toString();
        } catch {
            return "";
        } finally {
            sub.detach?.();
            er.detach?.();
        }
    };

    const out: SelChunks = { keys: hits.map((h) => h.key), seqs };
    if (!hits.length) return out;
    const headTxt = intersectText(hits[0].el).trim();
    const tailTxt = intersectText(hits[hits.length - 1].el).trim();
    if (headTxt) out.head = headTxt.slice(0, cap); // 首缘 = 切点侧
    if (tailTxt) out.tail = tailTxt.slice(-cap); // 尾缘 = 切点侧
    return out;
}

// ---------------------------------------------------------------- pdf 模糊锚定

export interface PdfDualLike {
    chunks?: { seq: number; en?: string; zh?: string }[] | null;
}

/**
 * 归一化：NFKD（连字 U+FB00 系/全角/兼容形折叠）+ 去组合附加符 + 小写 +
 * 智能引号/破折号折叠 + 空白塌缩为单空格（词界是 token 的切分依据——
 * 全剥会把相邻词焊死）+ 断行连字符接词（"architec- ture" →
 * "architecture"；"state-of-the-art" 无随空格不受影响）。
 */
function normSel(s: string): string {
    return s
        .normalize("NFKD")
        .replace(/\p{M}/gu, "")
        .toLowerCase()
        .replace(/[‘’‚‛]/g, "'")
        .replace(/[“”„‟]/g, '"')
        .replace(/[‐‑‒–—−]/g, "-")
        .replace(/\s+/g, " ")
        .replace(/([a-z])- /g, "$1")
        .trim();
}

/** token 化：拉丁词/数字串成 token，CJK/标点逐字成 token（部分覆盖可配）。 */
const TOK_RX = /[a-z0-9]+|[^\sa-z0-9]/giu;
const toksOf = (s: string): string[] => normSel(s).match(TOK_RX) ?? [];

/**
 * LaTeX 源 → 渲染态近似（expPdfAnchor 验证形）：占位符 [[X_n]]/数学
 * $..$|\(...\)|\[..\]/命令 \cmd*[opt]/花括号/~/转义符 \%&#_ 全抹——
 * 对齐 pdf 字形层再进 token 面。
 */
const texStrip = (s: string): string =>
    s.replace(/\[\[[A-Z]+_\d+\]\]/g, " ")
        .replace(/\$[^$]*\$|\\\([^)]*\\\)|\\\[[^\]]*\\\]/g, " ")
        .replace(/\\[a-zA-Z]+\*?(\[[^\]]*\])?/g, " ")
        .replace(/[{}]/g, " ")
        .replace(/~/g, " ")
        .replace(/\\([%&#_])/g, "$1")
        .replace(/\\+/g, " ");

/** chunk 行 token 缓存——per-(dual,side) memoize（WeakMap 随快照 GC） */
interface PdfRow {
    seq: number;
    toks: string[];
}
const pdfRowsCache = new WeakMap<
    PdfDualLike,
    Partial<Record<"en" | "zh", PdfRow[]>>
>();
const pdfRows = (dual: PdfDualLike, side: "en" | "zh"): PdfRow[] => {
    let rec = pdfRowsCache.get(dual);
    if (!rec) {
        rec = {};
        pdfRowsCache.set(dual, rec);
    }
    let rows = rec[side];
    if (!rows) {
        rows = (dual.chunks ?? [])
            .map((c) => ({
                seq: c.seq,
                toks: toksOf(
                    texStrip(
                        (side === "zh" ? c.zh : c.en) ?? c.en ?? c.zh ?? "",
                    ),
                ),
            }))
            .filter((r) => r.toks.length);
        rec[side] = rows;
    }
    return rows;
};

interface AnchorScore {
    /** 最长单块（token 数）——聚簇权重证据 */
    best: number;
    /** gap 合并后最大 a 侧覆盖（同组 b-gap ≤GAP_MERGE 的块 len 加和） */
    cov: number;
    /** gap 合并后最大 b 侧跨度（含组内 gap——选区被页眉/公式切碎时用） */
    selCov: number;
    /** 选区头落在块尾：sel 前缀 == chunk 后缀 的匹配长（head 边界块） */
    edgeHead: number;
    /** 块头落在选区尾：chunk 前缀 == sel 后缀 的匹配长（tail 边界块） */
    edgeTail: number;
}

interface MBlock {
    ai: number;
    bj: number;
    len: number;
}

/**
 * difflib get_matching_blocks 同构：递归最长匹配 + 左右切分，产全量
 * 不重叠匹配块（双维单调增序）。token 数 <1k 量级递归代价可忽略。
 */
function matchingBlocks(a: string[], b: string[]): MBlock[] {
    const out: MBlock[] = [];
    const rec = (alo: number, ahi: number, blo: number, bhi: number) => {
        const b2j = new Map<string, number[]>();
        for (let j = blo; j < bhi; j++) {
            const l = b2j.get(b[j]);
            if (l) l.push(j);
            else b2j.set(b[j], [j]);
        }
        let best = 0,
            bi = -1,
            bj = -1;
        let prev = new Map<number, number>();
        for (let i = alo; i < ahi; i++) {
            const next = new Map<number, number>();
            for (const j of b2j.get(a[i]) ?? []) {
                const l = (prev.get(j - 1) ?? 0) + 1;
                next.set(j, l);
                if (l > best) {
                    best = l;
                    bi = i - l + 1;
                    bj = j - l + 1;
                }
            }
            prev = next;
        }
        if (!best) return;
        out.push({ ai: bi, bj, len: best });
        rec(alo, bi, blo, bj);
        rec(bi + best, ahi, bj + best, bhi);
    };
    rec(0, a.length, 0, b.length);
    return out.sort((x, y) => x.ai - y.ai || x.bj - y.bj);
}

/** 同组 b 间距上限——页眉页脚/行间公式/引用占位切碎 pdf 流的经验口 */
const GAP_MERGE = 30;

/**
 * 段级锚定评分：全量匹配块 + gap 合并覆盖 + 两侧边界证据。
 *   cov    ：b 间距 ≤GAP_MERGE 的连续块成组，组内 a-len 加和取最大
 *            （chunk 被 pdf 侧噪声切碎时碎块覆盖合并计数）；
 *   selCov ：同组 b 跨度（含 gap）取最大——小选区整段落入大块内部、
 *            或选区被页眉/公式切碎时用；
 *   edgeHead：选区起点落在本块中段 → sel 开头 == 本块尾部连续串；
 *   edgeTail：选区终点落在本块中段 → 本块开头 == sel 尾部连续串。
 */
function anchorScore(a: string[], b: string[]): AnchorScore {
    const blocks = matchingBlocks(a, b);
    const sc: AnchorScore = {
        best: 0,
        cov: 0,
        selCov: 0,
        edgeHead: 0,
        edgeTail: 0,
    };
    let gA = 0,
        gStart = 0,
        gEnd = 0;
    const flush = () => {
        if (gA > sc.cov) sc.cov = gA;
        const span = gEnd - gStart;
        if (span > sc.selCov) sc.selCov = span;
    };
    for (const bl of blocks) {
        if (bl.len > sc.best) sc.best = bl.len;
        if (bl.bj === 0 && bl.ai + bl.len === a.length && bl.len > sc.edgeHead)
            sc.edgeHead = bl.len;
        if (bl.ai === 0 && bl.bj + bl.len === b.length && bl.len > sc.edgeTail)
            sc.edgeTail = bl.len;
        if (!gA || bl.bj - gEnd > GAP_MERGE) {
            // !gA 兜住组起点初始化——否则首块 bj≤GAP 时 gStart 残留 0，
            // selCov 虚胖成 0..末块 的幻影跨度
            if (gA) flush();
            gA = 0;
            gStart = bl.bj;
        }
        gA += bl.len;
        gEnd = bl.bj + bl.len;
    }
    if (gA) flush();
    return sc;
}

/**
 * pdf 侧选区 → seq 区间：归一化 token 面做段级锚定（不做偏移级——pdf 文本层
 * 是字形汤，偏移无义）。chunk 先经 texStrip 对齐渲染态。段命中三判据任立：
 *   内部块：合并覆盖 ≥ min(len, max(3, 35%·len))——整段含入选区恒命中，
 *           切碎段（数学/引用占位）靠 gap 合并救回；
 *   边界块：edgeHead/edgeTail ≥ 4——选区边缘连续 4+ token 缀上即算
 *           （边界覆盖本就短，用位置证据而非占比）；
 *   内含块：合并跨度 ≥ min(selLen, max(3, 80%·selLen))——小选区整段落入
 *           大块内部、或选区被页眉噪声切碎。
 * 命中集按 seq 序 gap≤2 连通聚簇（单洞未命中段=图/表/无文本块），胜者
 * = Σ(best+edge) 最大簇，返簇的 seq 闭区间——标题页等重复文本散落命中
 * 不再膨胀成跨页大区间（旧闭区间最坏 span=75 实证）。
 */
export function pdfSeqsForText(
    dual: PdfDualLike | null | undefined,
    selText: string,
    side: "en" | "zh" | null | undefined,
): number[] {
    const selToks = toksOf(selText);
    if (!selToks.length || !dual) return [];
    const matched: { seq: number; w: number }[] = [];
    const needSel = Math.min(
        selToks.length,
        Math.max(3, Math.ceil(selToks.length * 0.8)),
    );
    for (const r of pdfRows(dual, side === "zh" ? "zh" : "en")) {
        const needChunk = Math.min(
            r.toks.length,
            Math.max(3, Math.ceil(r.toks.length * 0.35)),
        );
        const sc = anchorScore(r.toks, selToks);
        if (
            sc.cov >= needChunk ||
            sc.selCov >= needSel ||
            sc.edgeHead >= 4 ||
            sc.edgeTail >= 4
        )
            matched.push({
                seq: r.seq,
                w: sc.best + sc.edgeHead + sc.edgeTail,
            });
    }
    if (!matched.length) return [];
    matched.sort((x, y) => x.seq - y.seq);
    // 连通聚簇：seq 间距 ≤2（恰一个未命中段）同簇
    const clusters: (typeof matched)[] = [];
    for (const m of matched) {
        const last = clusters[clusters.length - 1];
        if (last && m.seq - last[last.length - 1]!.seq <= 2) last.push(m);
        else clusters.push([m]);
    }
    let win = clusters[0]!,
        winW = -1;
    for (const c of clusters) {
        const w = c.reduce((s, m) => s + m.w, 0);
        if (w > winW) {
            winW = w;
            win = c;
        }
    }
    const lo = win[0]!.seq,
        hi = win[win.length - 1]!.seq;
    const out: number[] = [];
    for (let s = lo; s <= hi; s++) out.push(s);
    return out;
}

// ---------------------------------------------------------------- 剪贴板

/**
 * clipboard.writeText（secure context+focus 才有）→ textarea+execCommand
 * 兜底。返回是否复制成功——失败面由调用方决定（卡内 pre 可选文本即
 * 「手动复制」退路，不静默）。
 */
export async function copyText(
    s: string,
    doc: Document | null = typeof document !== "undefined"
        ? document
        : null,
): Promise<boolean> {
    try {
        const clip = doc?.defaultView?.navigator?.clipboard;
        if (clip) {
            await clip.writeText(s);
            return true;
        }
    } catch {
        /* 权限/失焦/非安全上下文 → 走兜底 */
    }
    if (!doc) return false;
    const ta = doc.createElement("textarea");
    ta.value = s;
    // 不可见但可聚焦——display:none 会让 select() 失效
    ta.style.position = "fixed";
    ta.style.top = "0";
    ta.style.left = "0";
    ta.style.opacity = "0";
    ta.style.pointerEvents = "none";
    doc.body.appendChild(ta);
    try {
        ta.focus();
        ta.select();
        return doc.execCommand("copy");
    } catch {
        return false;
    } finally {
        ta.remove();
    }
}

// ---------------------------------------------------------------- 档位存取

export type CopyLatexMode = "sent" | "whole";

const MODE_KEY = "texlate-copylatex-mode";

/** 选区复制档位（localStorage 记档，不进服务端 Settings 白名单）。 */
export function copyLatexMode(
    storage?: Pick<Storage, "getItem"> | null,
): CopyLatexMode {
    try {
        const s =
            storage === undefined
                ? typeof localStorage !== "undefined"
                  ? localStorage
                  : null
                : storage;
        return s?.getItem(MODE_KEY) === "whole" ? "whole" : "sent";
    } catch {
        return "sent";
    }
}

export function setCopyLatexMode(
    m: CopyLatexMode,
    storage?: Pick<Storage, "setItem"> | null,
): void {
    try {
        const s =
            storage === undefined
                ? typeof localStorage !== "undefined"
                  ? localStorage
                  : null
                : storage;
        s?.setItem(MODE_KEY, m);
    } catch {
        /* 隐私模式/满额——档位退回默认不影响功能 */
    }
}
