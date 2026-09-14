// Shared helpers for unified-latex benchmark.
const {
    printRaw,
} = require("@unified-latex/unified-latex-util-print-raw/index.cjs");

// ---------- AST helpers ----------
function isNode(n, type) {
    return (
        n != null &&
        typeof n === "object" &&
        !Array.isArray(n) &&
        n.type === type
    );
}
function isMacro(n, name) {
    return isNode(n, "macro") && (name === undefined || n.content === name);
}

// Walk every node (depth-first). cb(node, ctx) — ctx carries flags.
function walk(nodes, cb, ctx = {}) {
    if (!Array.isArray(nodes)) nodes = [nodes];
    for (const node of nodes) {
        if (node == null || typeof node !== "object") continue;
        const r = cb(node, ctx);
        if (r === "skip") continue;
        // descend
        if (Array.isArray(node.content) && node.type !== "string") {
            let childCtx = ctx;
            if (["inlinemath", "displaymath", "mathenv"].includes(node.type))
                childCtx = { ...ctx, inMath: true };
            if (node.type === "verbatim" || node.type === "verb")
                childCtx = { ...ctx, inVerbatim: true };
            walk(node.content, cb, childCtx);
        }
        if (Array.isArray(node.args)) {
            for (const a of node.args)
                if (Array.isArray(a.content)) walk(a.content, cb, ctx);
        }
    }
}

// Find all nodes matching predicate anywhere in tree.
// `tree` may be a root node, any node, or an array of nodes.
function findAll(tree, pred) {
    const out = [];
    walk(tree, (n, ctx) => {
        if (pred(n, ctx)) out.push(n);
    });
    return out;
}

// ---------- translatable-block extraction ----------
// Mimics the intended pipeline: extract prose text blocks for translation,
// protecting math/verbatim/comments and "key-like" macro arguments.

// Macros whose arguments should NOT be translated (keys, urls, file paths, defs)
const PROTECT_ARG_MACROS = new Set([
    "cite",
    "citep",
    "citet",
    "citealp",
    "citealt",
    "citeauthor",
    "citeyear",
    "citeyearpar",
    "citeposs",
    "Citep",
    "Citet",
    "citeonline",
    "ref",
    "eqref",
    "autoref",
    "cref",
    "Cref",
    "pageref",
    "nameref",
    "vref",
    "label",
    "url",
    "input",
    "include",
    "includegraphics",
    "bibliography",
    "bibliographystyle",
    "usepackage",
    "documentclass",
    "lstinputlisting",
    "includepdf",
    "newcommand",
    "renewcommand",
    "providecommand",
    "NewDocumentCommand",
    "RenewDocumentCommand",
    "newtheorem",
    "newcounter",
    "setcounter",
    "setlength",
    "addtolength",
    "hypersetup",
    "graphicspath",
    "definecolor",
    "colorlet",
    "bibliography",
    "addbibresource",
    "index",
    "gls",
    "Gls",
    "acrlong",
    "acrshort",
    "makeindex",
    "tableofcontents",
]);
// Macros where ALL attached args are protected
const PROTECT_ALL_ARGS = PROTECT_ARG_MACROS;
// Macros where only SOME args are protected: name -> set of protected arg indices
const PARTIAL_PROTECT = {
    href: new Set([0, 1]), // sig "o m m": opt,url protected; last = text
    hyperref: new Set([0]), // [url]{text}: idx0 = url? signature 'o m' varies; treat arg0 as url
    url: "all",
};
// Macros whose args ARE translatable text (explicit list, else default-descend)
const TEXT_ARG_MACROS = new Set([
    "emph",
    "textbf",
    "textit",
    "textsl",
    "textsc",
    "textrm",
    "texttt",
    "textmd",
    "textup",
    "underline",
    "section",
    "subsection",
    "subsubsection",
    "paragraph",
    "subparagraph",
    "chapter",
    "part",
    "caption",
    "footnote",
    "thanks",
    "title",
    "author",
    "date",
    "item",
    "frametitle",
    "text",
    "mbox",
    "marginpar",
    "authornote",
    "subtitle",
    "subcaption",
    "headline",
]);

// Environments whose whole content is protected (non-prose or math)
const PROTECTED_ENVS = new Set([
    "tabular",
    "tabular*",
    "tabularx",
    "array",
    "tikzpicture",
    "pgfpicture",
    "thebibliography",
    "filecontents",
    "filecontents*",
    "algorithm",
    "algorithmic",
    "lstlisting",
    "minted",
    "comment",
    "verbatim",
    "verbatim*",
    "axis",
    "scope",
    "pspicture",
    "asy",
    "circuitikz",
    "sidewaystable",
    "matrix",
    "pmatrix",
    "bmatrix",
    "Bmatrix",
    "vmatrix",
    "Vmatrix",
    "smallmatrix",
    "cases",
    "split",
    "aligned",
    "alignedat",
    "gathered",
]);
// Math envs by name (in addition to mathenv node type)
const MATH_ENV_NAMES = new Set([
    "equation",
    "equation*",
    "align",
    "align*",
    "alignat",
    "alignat*",
    "gather",
    "gather*",
    "multline",
    "multline*",
    "flalign",
    "flalign*",
    "eqnarray",
    "eqnarray*",
    "displaymath",
    "math",
    "subequations",
    "IEEEeqnarray",
    "IEEEeqnarray*",
    "empheq",
    "dmath",
    "dmath*",
    "dgroup",
]);

function envName(node) {
    // node.env may be string or array of nodes
    if (node.env == null) return "";
    if (typeof node.env === "string") return node.env;
    try {
        return printRaw(node.env).trim();
    } catch {
        return "";
    }
}

// Collect translatable blocks from a parsed root.
// A "block" = maximal run of inline text-ish nodes between block boundaries.
// Returns [{text, nodes}] where text = printRaw of collected nodes.
function extractTranslatableBlocks(root) {
    const blocks = [];
    let cur = [];
    const flush = () => {
        if (cur.length === 0) return;
        const text = cur.map((n) => printRaw(n)).join("");
        if (text.trim().length > 0) blocks.push({ text, nodes: cur });
        cur = [];
    };

    // collect text-ish leaf content inside an arg/group/inline region
    function collectInline(nodes) {
        for (const node of nodes) {
            if (node == null || typeof node !== "object") {
                continue;
            }
            switch (node.type) {
                case "string":
                case "whitespace":
                    cur.push(node);
                    break;
                case "comment":
                case "parbreak":
                    // comments dropped; parbreak is a boundary but inside args rarely
                    if (node.type === "parbreak") flush();
                    break;
                case "inlinemath":
                case "displaymath":
                case "verbatim":
                case "verb":
                    // protected: leak check wants to know if they appear — they don't here
                    break;
                case "macro": {
                    const name = node.content;
                    if (PROTECT_ALL_ARGS.has(name)) {
                        // macro token itself not emitted; args skipped entirely
                        break;
                    }
                    if (PARTIAL_PROTECT[name] instanceof Set) {
                        // emit macro? No — but descend into non-protected args
                        node.args?.forEach((a, i) => {
                            if (
                                !PARTIAL_PROTECT[name].has(i) &&
                                Array.isArray(a.content)
                            )
                                collectInline(a.content);
                        });
                        break;
                    }
                    // Unknown/other macro: if it has attached args, decide per macro list.
                    // For TEXT_ARG macros descend; otherwise still descend into args
                    // (they may hold prose) but do not emit the macro token itself.
                    if (Array.isArray(node.args) && node.args.length > 0) {
                        for (const a of node.args) {
                            if (Array.isArray(a.content))
                                collectInline(a.content);
                        }
                    } else {
                        // bare macro (possibly unknown like \citep): emit token so that
                        // leaked constructs are VISIBLE in the extracted block
                        cur.push(node);
                    }
                    break;
                }
                case "group":
                    collectInline(node.content);
                    break;
                case "argument":
                    collectInline(node.content);
                    break;
                case "environment":
                case "mathenv":
                    flush();
                    descendEnv(node);
                    flush();
                    break;
                default:
                    // hash_number, etc.
                    break;
            }
        }
    }

    function descendEnv(envNode) {
        const name = envName(envNode);
        if (
            envNode.type === "mathenv" ||
            MATH_ENV_NAMES.has(name) ||
            PROTECTED_ENVS.has(name)
        ) {
            return; // fully protected
        }
        if (Array.isArray(envNode.content)) collectInline(envNode.content);
    }

    collectInline(Array.isArray(root.content) ? root.content : [root]);
    flush();
    return blocks;
}

module.exports = {
    walk,
    findAll,
    isNode,
    isMacro,
    extractTranslatableBlocks,
    envName,
    MATH_ENV_NAMES,
    PROTECTED_ENVS,
    printRaw,
};
