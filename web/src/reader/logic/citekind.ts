// citekind —— 目标分类词表叶（w4 自 cmd/hitctx.ts 提出，解 usages→cmd
// 反向边；pdf/pdfCards/pdfInspect 的 classifyDestName 同源同走）。
//   CiteKind          bib/figure/table/equation/theorem/section/other
//   classifyLtxEl     元素 → kind：自身 class 词表优先，不识爬最近
//                     ltx_* 祖先（ltx_caption/ltx_tbody 兜底宿主块）
//   classifyDestName  dest 名/元素 id 前缀分类（pdf named dest +
//                     latexml id 词表双吃）

export type CiteKind =
    | "bib"
    | "figure"
    | "table"
    | "equation"
    | "theorem"
    | "section"
    | "other"
    | null;

/** ltx_* class → kind（宿主元素自身 class 词表，按优先级首个命中） */
const LTX_KIND: [RegExp, Exclude<CiteKind, null>][] = [
    [/^ltx_bibitem$|^ltx_bibblock$/, "bib"],
    [/^ltx_equation$|^ltx_eqn/, "equation"],
    [/^ltx_figure$|^ltx_flex_figure$|^ltx_subfloat$/, "figure"],
    [/^ltx_table$/, "table"],
    [/^ltx_theorem/, "theorem"],
    [
        /^ltx_(chapter|section|subsection|subsubsection|paragraph|subparagraph|abstract)/,
        "section",
    ],
];

/**
 * 元素 → kind：自身 class 词表优先；不识则爬到最近的 ltx_* 祖先重判
 * （嵌套内层如 ltx_caption/ltx_tbody 兜底到宿主 figure/table）。
 */
export function classifyLtxEl(el: Element | null): Exclude<CiteKind, null> {
    for (let cur = el; cur; cur = cur.parentElement) {
        const cls = cur.getAttribute("class") ?? "";
        if (!cls.includes("ltx_")) continue;
        const toks = cls.split(/\s+/);
        for (const [rx, kind] of LTX_KIND)
            if (toks.some((t) => rx.test(t))) return kind;
        if (cur !== el) return "other"; // 最近 ltx_ 祖先不识别 → 不再上爬
    }
    return "other";
}

/** dest 名/元素 id 前缀分类（pdf named dest + latexml id 词表双吃） */
export function classifyDestName(name: string): Exclude<CiteKind, null> {
    const n = name.toLowerCase();
    if (/^(cite|bib)\./.test(n) || /^bib$/.test(n)) return "bib";
    if (/^(equation|eq|eqn)[._-]/.test(n) || /(?:^|\.)e\d+$/.test(n))
        return "equation";
    if (
        /^(figure|fig|subfigure|subfig)[._-]/.test(n) ||
        /(?:^|\.)f\d+(?:\.\w+)?$/.test(n)
    )
        return "figure";
    if (/^(table|tab)[._-]/.test(n) || /(?:^|\.)t\d+(?:\.\d+)?$/.test(n))
        return "table";
    if (
        /^(theorem|thm|lemma|lem|prop|proposition|cor|corollary|def|definition|remark|rem)[._-]/.test(
            n,
        )
    )
        return "theorem";
    if (
        /^(chapter|part|section\*?|subsection|subsubsection|paragraph|appendix|abstract)[._-]/.test(
            n,
        ) ||
        /^s(?:x?\d+)(?:\.s{1,3}\d+)*$/.test(n)
    )
        return "section";
    return "other";
}
