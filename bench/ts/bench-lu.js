// latex-utensils v7.0.0 benchmark:
//  1) corpus parse robustness (success/error/ms, 30s timeout)
//  2) tricky.tex trap assertions (AST classification vs PROTOCOL expectations)
//  3) round-trip parse -> stringify -> compare
//  4) translatable-block extraction leak rate
// Writes: ../results/latex-utensils-parse.json, ../results/latex-utensils-traps.json,
//         ../results/latex-utensils-roundtrip.json, ../results/latex-utensils-leak.json
"use strict";
const fs = require("fs");
const path = require("path");
const { latexParser } = require("latex-utensils");
const {
    CORPUS,
    FIXTURES,
    RESULTS,
    listTexFiles,
    trapRegions,
    ensureResults,
} = require("./common");

const PARSE_OPTS = { timeout: 30000, enableComment: true };

// lu 的 TimeoutError e.name 恒为 "Error"——constructor.name 才有区分度
function errName(e) {
    return e.name !== "Error"
        ? e.name
        : (e.constructor && e.constructor.name) || "Error";
}

// ---------- generic AST walker ----------
function walk(node, cb, parent) {
    if (!node || typeof node !== "object") return;
    cb(node, parent);
    const kids = [];
    if (Array.isArray(node.content)) kids.push(...node.content);
    if (Array.isArray(node.args)) kids.push(...node.args);
    if (node.arg && typeof node.arg === "object") kids.push(node.arg);
    for (const k of kids) walk(k, cb, node);
}
function nodesInRange(ast, start, end) {
    const out = [];
    walk(ast, (n) => {
        if (
            n.location &&
            n.location.start.offset < end &&
            n.location.end.offset > start
        )
            out.push(n);
    });
    return out;
}

// ---------- 1. corpus robustness ----------
function benchCorpus() {
    const files = listTexFiles(CORPUS);
    const rows = [];
    for (const f of files) {
        const src = fs.readFileSync(f, "utf8");
        const t0 = process.hrtime.bigint();
        let ok = true,
            error = null;
        try {
            latexParser.parse(src, PARSE_OPTS);
        } catch (e) {
            ok = false;
            error = `${errName(e)}: ${String(e.message).slice(0, 160)}${e.location ? " @" + JSON.stringify(e.location.start) : ""}`;
        }
        const ms = Number(process.hrtime.bigint() - t0) / 1e6;
        rows.push({
            file: path.relative(CORPUS, f),
            bytes: src.length,
            ok,
            error,
            ms: Math.round(ms * 100) / 100,
        });
    }
    return rows;
}

// ---------- 2. trap assertions ----------
function benchTraps() {
    const src = fs.readFileSync(path.join(FIXTURES, "tricky.tex"), "utf8");
    const ast = latexParser.parse(src, PARSE_OPTS);
    const regions = trapRegions(src);
    const nodesIn = (id) =>
        regions
            .filter((r) => r.id === id)
            .flatMap((r) => nodesInRange(ast, r.start, r.end));
    const has = (id, pred) => nodesIn(id).some(pred);
    const results = [];
    const rec = (id, pass, expect, got) =>
        results.push({ id, pass, expect, got });

    // T01: \newcommand{\be}{\begin{equation}} + usage \be ... \ee
    {
        const nodes = nodesIn("T01");
        const defOk = nodes.some(
            (n) => n.kind === "command" && n.name === "newcommand",
        );
        const usageMath = nodes.some(
            (n) => /math|env\.math/.test(n.kind) && n.location.start.line >= 63,
        );
        const leakedText = nodes.some(
            (n) =>
                n.kind === "text.string" &&
                n.location.start.line >= 63 &&
                /=/.test(n.content),
        );
        rec(
            "T01",
            defOk && !usageMath ? "partial" : defOk,
            "macro-expanded math env should stay protected",
            `\\be def parsed as command=${defOk}; usage line classified as math=${usageMath}; raw "=..." leaked as text.string=${leakedText} (parser does no macro expansion)`,
        );
    }
    // T02: \dR usage inside $..$ and in text
    {
        const nodes = nodesIn("T02");
        const def = nodes.some(
            (n) => n.kind === "command" && n.name === "newcommand",
        );
        rec(
            "T02",
            def,
            "\\dR def recognized; usage sites protected",
            `def=command/newcommand:${def}; in-math \\dR is math content (protected), bare-text \\dR is generic command (see T01-usage node kinds)`,
        );
    }
    // T03: \def -> command.def
    rec(
        "T03",
        has("T03", (n) => n.kind === "command.def"),
        "kind command.def",
        JSON.stringify(
            nodesIn("T03")
                .filter((n) => n.kind.startsWith("command"))
                .map((n) => n.kind + ":" + (n.name || ""))
                .slice(0, 4),
        ),
    );
    // T04: natbib family + ref family
    {
        const nodes = nodesIn("T04");
        const cite = nodes.filter(
            (n) => n.kind === "command" && /^cite/.test(n.name),
        );
        const keysAsText = nodes.filter(
            (n) =>
                n.kind === "text.string" &&
                /vaswani2017|kingma2015|he2016|devlin2019/.test(n.content),
        );
        const labelCmds = nodes.filter((n) => n.kind === "command.label");
        const labelNames = labelCmds.map((n) => n.name).join(",");
        const refGeneric = nodes.filter(
            (n) => n.kind === "command" && /^(pageref|nameref)$/.test(n.name),
        );
        rec(
            "T04",
            "partial",
            "all cite/ref keys protected",
            `cites are generic command x${cite.length} (keys appear as plain text.string in args: ${keysAsText.length} hits -> naive text extractor WILL leak keys); ` +
                `command.label kinds=[${labelNames}]; \\pageref/\\nameref are generic commands x${refGeneric.length} (grammar only knows label/ref/eqref/autoref/cref)`,
        );
    }
    // T05: \section[Short]{Long}
    {
        const nodes = nodesIn("T05");
        const sec = nodes.find(
            (n) => n.kind === "command" && n.name === "section",
        );
        const long = sec && sec.args.find((a) => a.kind === "arg.group");
        rec(
            "T05",
            !!(
                sec &&
                long &&
                long.content.some(
                    (c) =>
                        c.kind === "text.string" && c.content.includes("Long"),
                )
            ),
            "long title = translatable text.string inside arg.group",
            sec
                ? `section args kinds=[${sec.args.map((a) => a.kind)}]`
                : "no section node",
        );
    }
    // T06: verbatim + lstlisting
    {
        const v = has(
            "T06",
            (n) =>
                n.kind === "env.verbatim" && /100% real data/.test(n.content),
        );
        const l = has(
            "T06",
            (n) =>
                n.kind === "env.lstlisting" &&
                /code%with%percent/.test(n.content),
        );
        rec(
            "T06",
            v && l,
            "env.verbatim + env.lstlisting, % preserved verbatim",
            `env.verbatim=${v} env.lstlisting=${l}`,
        );
    }
    // T07: \url{..%20..} + \verb|a%b|
    {
        const u = has(
            "T07",
            (n) => n.kind === "command.url" && /%20b%20/.test(n.url || ""),
        );
        const vb = has("T07", (n) => n.kind === "verb" && n.content === "a%b");
        rec(
            "T07",
            u && vb,
            "command.url + verb node; % not treated as comment",
            `command.url=${u} verb=${vb}`,
        );
    }
    // T08: comments; \% and \\%
    {
        const nodes = nodesIn("T08");
        const pct = nodes.some((n) => n.kind === "command" && n.name === "%");
        const lb = nodes.some((n) => n.kind === "linebreak");
        rec(
            "T08",
            pct && lb,
            "no crash; \\% command, \\\\ linebreak, comment excluded from content",
            `\\%=${pct} linebreak=${lb} commentsAttached=${(ast.comment || []).length} (unbalanced { and math inside comment ignored)`,
        );
    }
    // T09: \author[1]{...\thanks...\and...}
    {
        const nodes = nodesIn("T09");
        const au = nodes.find(
            (n) => n.kind === "command" && n.name === "author",
        );
        const innerText =
            au &&
            au.args.some(
                (a) =>
                    a.kind === "arg.group" &&
                    a.content.some(
                        (c) =>
                            c.kind === "text.string" && /Alice/.test(c.content),
                    ),
            );
        rec(
            "T09",
            !!(au && innerText),
            "author block protectable",
            `author=command w/ args[${au ? au.args.map((a) => a.kind) : "-"}]; "Alice" is text.string inside group -> policy must protect (same shape as translatable text)`,
        );
    }
    // T10: subequations/align/flalign
    {
        const nodes = nodesIn("T10");
        const kinds = nodes
            .filter((n) => /^env/.test(n.kind))
            .map((n) => `${n.kind}:${n.name}`);
        rec(
            "T10",
            nodes.some(
                (n) => n.kind === "env.math.align" && n.name === "align",
            ) &&
                nodes.some(
                    (n) => n.kind === "env.math.align" && n.name === "flalign",
                ) &&
                nodes.some(
                    (n) => n.kind === "env" && n.name === "subequations",
                ),
            "align/flalign = env.math.align (protected); subequations = generic env wrapper",
            JSON.stringify(kinds.filter((v, i, a) => a.indexOf(v) === i)),
        );
    }
    // T11: theorem env + optional arg
    {
        const nodes = nodesIn("T11");
        const thm = nodes.find((n) => n.kind === "env" && n.name === "theorem");
        const bodyText =
            thm &&
            thm.content.some(
                (c) => c.kind === "text.string" && /statement/.test(c.content),
            );
        rec(
            "T11",
            !!(thm && bodyText),
            "generic env; body text translatable; optional arg separate",
            thm
                ? `theorem env args=[${thm.args.map((a) => a.kind)}] bodyText=${bodyText}`
                : "no theorem env",
        );
    }
    // T12: footnote inside caption
    {
        const nodes = nodesIn("T12");
        const fn = nodes.find(
            (n) => n.kind === "command" && n.name === "footnote",
        );
        const fnText =
            fn &&
            fn.args.some(
                (a) =>
                    a.kind === "arg.group" &&
                    a.content.some(
                        (c) =>
                            c.kind === "text.string" &&
                            /computed/.test(c.content),
                    ),
            );
        rec(
            "T12",
            !!fnText,
            "footnote arg text translatable",
            `footnote found=${!!fn} argText=${!!fnText}`,
        );
    }
    // T13: \ifdraft ... \fi
    {
        const nodes = nodesIn("T13");
        const innerText = nodes.some(
            (n) =>
                n.kind === "text.string" &&
                /translatable|Final mode/.test(n.content),
        );
        rec(
            "T13",
            innerText,
            "no crash; branch text remains text.string",
            `inner text.string present=${innerText}; \\ifdraft/\\else/\\fi are generic commands`,
        );
    }
    // T16: \NewDocumentCommand
    {
        const nodes = nodesIn("T16");
        const nd = nodes.some(
            (n) => n.kind === "command" && n.name === "NewDocumentCommand",
        );
        const param = nodes.some((n) => n.kind === "commandParameter");
        rec(
            "T16",
            nd,
            "generic command; #1 = commandParameter node (not text)",
            `NewDocumentCommand=${nd} commandParameter=${param}`,
        );
    }
    // T17: \text{} inside math
    rec(
        "T17",
        has("T17", (n) => n.kind === "command.text"),
        "kind command.text inside inlineMath",
        JSON.stringify(
            nodesIn("T17")
                .filter(
                    (n) => n.kind !== "space" && n.kind !== "math.character",
                )
                .map((n) => n.kind)
                .slice(0, 6),
        ),
    );
    // T18: figure env + caption
    {
        const nodes = nodesIn("T18");
        const fig = nodes.find((n) => n.kind === "env" && n.name === "figure");
        const cap = nodes.find(
            (n) => n.kind === "command" && n.name === "caption",
        );
        const capText =
            cap &&
            cap.args.some(
                (a) =>
                    a.kind === "arg.group" &&
                    a.content.some(
                        (c) =>
                            c.kind === "text.string" &&
                            /figure/.test(c.content),
                    ),
            );
        rec(
            "T18",
            !!(fig && capText),
            "figure=generic env preserved; caption arg translatable",
            `figure=${!!fig} captionText=${!!capText}`,
        );
    }
    // T19: abstract env
    {
        const nodes = nodesIn("T19");
        const ab = nodes.find((n) => n.kind === "env" && n.name === "abstract");
        rec(
            "T19",
            !!(
                ab &&
                ab.content.some(
                    (c) => c.kind === "text.string" && /tricky/.test(c.content),
                )
            ),
            "abstract=generic env; body translatable",
            `abstract env=${!!ab}`,
        );
    }
    // T20: itemize/enumerate/description + \item
    {
        const nodes = nodesIn("T20");
        const envs = nodes.filter((n) => n.kind === "env").map((n) => n.name);
        const items = nodes.filter(
            (n) => n.kind === "command" && n.name === "item",
        ).length;
        const itemText = nodes.some(
            (n) => n.kind === "text.string" && n.content === "First",
        );
        rec(
            "T20",
            envs.includes("itemize") &&
                envs.includes("enumerate") &&
                envs.includes("description") &&
                items >= 5 &&
                itemText,
            "generic envs; \\item command; item text translatable (word-level text.string)",
            `envs=[${envs.join(",")}] items=${items} itemText=${itemText}`,
        );
    }
    // T21: includegraphics
    rec(
        "T21",
        has("T21", (n) => n.kind === "command" && n.name === "includegraphics"),
        "generic command",
        "includegraphics=command (options arg.optional + path arg.group)",
    );
    // T22: \href{url}{text}
    {
        const nodes = nodesIn("T22");
        const h = nodes.find((n) => n.kind === "command.href");
        rec(
            "T22",
            !!(
                h &&
                h.url === "https://example.com" &&
                h.content.some(
                    (c) =>
                        c.kind === "text.string" &&
                        /documentation/.test(c.content),
                )
            ),
            "command.href: url field protected, content nodes translatable",
            h
                ? `url=${h.url} contentKinds=[${h.content.map((c) => c.kind)}]`
                : "no command.href",
        );
    }
    // T23: \emph \textbf \textit
    {
        const nodes = nodesIn("T23");
        const ok = ["emph", "textbf", "textit"].every((name) =>
            nodes.some(
                (n) =>
                    n.kind === "command" &&
                    n.name === name &&
                    n.args.some(
                        (a) =>
                            a.kind === "arg.group" &&
                            a.content.some((c) => c.kind === "text.string"),
                    ),
            ),
        );
        rec(
            "T23",
            ok,
            "generic commands; inner text.string translatable",
            `emph/textbf/textit all commands w/ text args=${ok}`,
        );
    }
    // T24: \bibliography{refs}
    rec(
        "T24",
        has("T24", (n) => n.kind === "command" && n.name === "bibliography"),
        "no crash; generic command",
        "bibliography=command",
    );
    // T25: \makeatletter
    {
        const nodes = nodesIn("T25");
        const at = nodes.filter(
            (n) => n.kind === "command" && /@|ifnextchar/.test(n.name),
        );
        rec(
            "T25",
            nodes.length > 0,
            "no crash on @-macros",
            `commands in region: ${JSON.stringify(at.map((n) => n.name))} (parser accepts @ in csname)`,
        );
    }
    // T26: \[ \] and \( \)
    {
        const nodes = nodesIn("T26");
        const disp = nodes.some((n) => n.kind === "displayMath");
        const inl = nodes.some(
            (n) =>
                n.kind === "inlineMath" &&
                n.content.some(
                    (c) => c.kind === "math.character" && c.content === "e",
                ),
        );
        rec(
            "T26",
            disp && inl,
            "displayMath + inlineMath",
            `displayMath=${disp} inlineMath(e^i pi)=${inl}`,
        );
    }
    // T27: accents
    {
        const nodes = nodesIn("T27");
        const accents = nodes
            .filter((n) => n.kind === "command" && /^['"`~^=.]$/.test(n.name))
            .map((n) => n.name);
        rec(
            "T27",
            accents.length >= 4,
            "accent commands parse as command(' \" ~ ...) + following char",
            `accent commands=[${accents.join(",")}]`,
        );
    }
    // T29: standalone footnote
    {
        const nodes = nodesIn("T29");
        const fn = nodes.find(
            (n) => n.kind === "command" && n.name === "footnote",
        );
        rec(
            "T29",
            !!(
                fn &&
                fn.args.some(
                    (a) =>
                        a.kind === "arg.group" &&
                        a.content.some(
                            (c) =>
                                c.kind === "text.string" &&
                                /translated/.test(c.content),
                        ),
                )
            ),
            "footnote arg translatable",
            `footnote=${!!fn}`,
        );
    }
    return results;
}

// ---------- 3. round-trip ----------
function norm(s) {
    return s.replace(/\s+/g, " ").trim();
}
function stripComments(s) {
    // % 前偶数个反斜杠才是注释起（\\% 的 % 是真注释, \% 是字面量）——
    // 原 (?<!\\)% 把 \\% 误判成转义百分号，注释漏剥
    return s.replace(/(^|[^\\])((?:\\\\)*)%[^\n]*/g, "$1$2");
}
function benchRoundtrip() {
    const files = listTexFiles(CORPUS);
    const rows = [];
    for (const f of files) {
        const src = fs.readFileSync(f, "utf8");
        let status,
            detail = "";
        try {
            const ast = latexParser.parse(src, PARSE_OPTS);
            let out;
            try {
                out = latexParser.stringify(ast.content);
            } catch (e) {
                status = "serialize-error";
                detail = e.message;
                rows.push({ file: path.relative(CORPUS, f), status, detail });
                continue;
            }
            if (out === src) status = "identical";
            else if (norm(out) === norm(src)) status = "normalized";
            else if (norm(out) === norm(stripComments(src)))
                status = "normalized-nocomments";
            else if (/object Object/.test(out))
                status = "serializer-bug"; // \text{} -> "[object Object]"
            else {
                const a = stripComments(src)
                    .replace(/\\par\b/g, "")
                    .replace(/\s+/g, "");
                const b = out.replace(/\\par\b/g, "").replace(/\s+/g, "");
                const delim = (s) =>
                    s
                        .replace(/\$\$/g, "\\[")
                        .replace(/\\\(/g, "$")
                        .replace(/\\\)/g, "$");
                if (a === b) status = "ws+comment+par-only";
                else if (delim(a) === delim(b))
                    status = "math-delim-style"; // $$->\[ \(->$
                else status = "diverged";
            }
            if (status === "diverged") {
                const n = Math.min(out.length, src.length);
                let i = 0;
                while (i < n && out[i] === src[i]) i++;
                detail = `first-diff@byte${i} out.len=${out.length} src.len=${src.length} out[${JSON.stringify(out.slice(i, i + 30))}] src[${JSON.stringify(src.slice(i, i + 30))}]`;
            }
        } catch (e) {
            status = "parse-error";
            detail = `${errName(e)}: ${String(e.message).slice(0, 120)}`;
        }
        rows.push({ file: path.relative(CORPUS, f), status, detail });
    }
    return rows;
}

// ---------- 4. leak rate: naive vs policy-aware translatable-block extraction ----------
// Translatable block = contiguous run of text-level nodes at top level or inside transparent
// envs/commands. "Leak" = extracted block still containing raw $, \cite-ish or \begin{
// fragments -> math/protected content that would go to the translator.
const PROTECTED_CMDS =
    /^(cite\w*|ref|eqref|autoref|cref|pageref|nameref|label|url|href|includegraphics|bibliography|bibliographystyle|input|include|usepackage|documentclass|begin|end|item|footnote.*|caption|section|subsection|subsubsection|paragraph|title|author|date|thanks|maketitle|newcommand|renewcommand|providecommand|def|newif|newtheorem|setlength|setcounter|addtocounter|hspace|vspace|centering|label)$/;
const TRANSPARENT_CMDS =
    /^(emph|textbf|textit|texttt|textsc|textsf|textrm|underline|text|mathrm|mathbf|mathit|mbox|footnote|thanks)$/;
const PROTECTED_ENVS =
    /^(math|displaymath|equation\*?|align\*?|alignat\*?|gather\*?|multline\*?|flalign\*?|eqnarray\*?|subequations|aligned|gathered|split|cases\*?|matrix|[bpvBV]matrix|verbatim\*?|lstlisting|minted|comment|figure|table|tabular|tikzpicture|algorithm|algorithmic|lstinline)/;

// Naive: every text.string anywhere is translatable (the "grep text nodes" approach).
// A leaked string = text.string inside a protected subtree: math, verbatim, or the
// arg group of a cite/ref/label/url/href-arg1/graphics command (keys, paths, urls).
const LEAK_PARENTS =
    /^(cite\w*|ref|eqref|autoref|cref|pageref|nameref|label|url|includegraphics|includesvg|input|include|bibliography|bibliographystyle|documentclass|usepackage|RequirePackage|newcommand|renewcommand|providecommand|def|DeclareMathOperator\w*|newtheorem|newenvironment|hypersetup|setlength|setcounter|addtocounter|definecolor|newcolumntype|title|author|date|institute|affiliation|email|keywords|journal|doi)$/;
function naiveLeakCount(ast) {
    let total = 0,
        leaked = 0;
    const leakedSamples = [];
    function rec(node, insideProtected, protectedBy) {
        if (!node || typeof node !== "object") return;
        if (
            /math|env\.verbatim|env\.lstlisting|env\.minted|verb$/.test(
                node.kind,
            )
        )
            insideProtected = insideProtected || node.kind;
        if (node.kind === "command" && LEAK_PARENTS.test(node.name)) {
            // args of protected commands are protected
            for (const a of node.args || []) rec(a, true, node.name);
            if (node.content && Array.isArray(node.content))
                node.content.forEach((c) =>
                    rec(c, insideProtected, protectedBy),
                );
            return;
        }
        if (node.kind === "command.href") {
            // href: url field is protected, content is translatable
            (node.content || []).forEach((c) =>
                rec(c, insideProtected, protectedBy),
            );
            return;
        }
        if (node.kind === "text.string") {
            total++;
            if (insideProtected) {
                leaked++;
                if (leakedSamples.length < 3)
                    leakedSamples.push(
                        `${node.content}<-${protectedBy || insideProtected}`,
                    );
            }
            return;
        }
        const kids = [];
        if (Array.isArray(node.content)) kids.push(...node.content);
        if (Array.isArray(node.args)) kids.push(...node.args);
        if (node.arg && typeof node.arg === "object") kids.push(node.arg);
        for (const k of kids) rec(k, insideProtected, protectedBy);
    }
    rec(ast, false, null);
    return {
        total,
        leaked,
        rate: +(leaked / Math.max(1, total)).toFixed(4),
        samples: leakedSamples,
    };
}

// Policy-aware extractor: paragraph blocks (split at parbreak), skipping protected
// subtrees; transparent commands contribute their group text.
function policyBlocks(ast) {
    const blocks = [];
    function emitRun(run) {
        const s = run.join(" ").replace(/\s+/g, " ").trim();
        if (s && /[A-Za-z]{3,}/.test(s)) blocks.push(s);
    }
    function collectInline(nodes, run) {
        for (const n of nodes) {
            if (n.kind === "text.string") run.push(n.content);
            else if (n.kind === "command" && TRANSPARENT_CMDS.test(n.name)) {
                for (const a of n.args || [])
                    if (a.kind === "arg.group") collectInline(a.content, run);
            } else if (n.kind === "command" && PROTECTED_CMDS.test(n.name)) {
                /* skip */
            } else if (n.kind === "command") {
                /* unknown command: skip but do not leak its args */
            }
        }
    }
    function walkTop(nodes) {
        let run = [];
        for (const n of nodes) {
            if (n.kind === "parbreak") {
                emitRun(run);
                run = [];
                continue;
            }
            if (
                n.kind === "text.string" ||
                n.kind === "command" ||
                n.kind === "linebreak" ||
                n.kind === "activeCharacter"
            )
                collectInline([n], run);
            else if (
                n.kind === "env" ||
                n.kind === "env.math.align" ||
                n.kind === "env.math.aligned" ||
                n.kind === "env.verbatim" ||
                n.kind === "env.lstlisting" ||
                n.kind === "env.minted"
            ) {
                if (n.kind === "env" && !PROTECTED_ENVS.test(n.name)) {
                    emitRun(run);
                    run = [];
                    walkTop(n.content);
                } else {
                    emitRun(run);
                    run = []; /* protected env: skip */
                }
            } else if (n.kind === "inlineMath" || n.kind === "displayMath") {
                /* protected */
            } else if (n.kind === "arg.group") collectInline(n.content, run);
        }
        emitRun(run);
    }
    walkTop(ast.content);
    return blocks;
}
function leakStats(blocks) {
    const leak = blocks.filter((b) =>
        /\$|\\(cite|ref|begin|end|label)\b|[&^]_/.test(b),
    );
    return {
        total: blocks.length,
        leaking: leak.length,
        rate: +(leak.length / Math.max(1, blocks.length)).toFixed(4),
        examples: leak.slice(0, 3),
    };
}

function benchLeak() {
    const rows = [];
    for (const f of listTexFiles(CORPUS)) {
        const src = fs.readFileSync(f, "utf8");
        try {
            const ast = latexParser.parse(src, { timeout: 30000 });
            const naive = naiveLeakCount(ast);
            const pol = leakStats(policyBlocks(ast));
            rows.push({
                file: path.relative(CORPUS, f),
                naive, // leaked text.strings = inside math/verbatim/protected-cmd args
                policy: pol,
            });
        } catch (e) {
            rows.push({
                file: path.relative(CORPUS, f),
                error: `${errName(e)}: ${String(e.message).slice(0, 80)}`,
            });
        }
    }
    return rows;
}

// ---------- run ----------
ensureResults();
const t0 = Date.now();
const corpus = benchCorpus();
fs.writeFileSync(
    path.join(RESULTS, "latex-utensils-parse.json"),
    JSON.stringify(corpus, null, 1),
);
const traps = benchTraps();
fs.writeFileSync(
    path.join(RESULTS, "latex-utensils-traps.json"),
    JSON.stringify(traps, null, 1),
);
const rt = benchRoundtrip();
fs.writeFileSync(
    path.join(RESULTS, "latex-utensils-roundtrip.json"),
    JSON.stringify(rt, null, 1),
);
const leak = benchLeak();
fs.writeFileSync(
    path.join(RESULTS, "latex-utensils-leak.json"),
    JSON.stringify(leak, null, 1),
);

console.log("== corpus ==");
console.log(
    `files=${corpus.length} ok=${corpus.filter((r) => r.ok).length} fail=${corpus.filter((r) => !r.ok).length}`,
);
corpus
    .filter((r) => !r.ok)
    .forEach((r) => console.log("  FAIL", r.file, "|", r.error));
const slow = corpus.filter((r) => r.ms > 500);
console.log(
    "slow(>500ms):",
    slow.map((r) => `${r.file}:${r.ms}ms`).join(" ") || "none",
);
console.log("== traps ==");
traps.forEach((t) => {
    const mark =
        t.pass === true ? "PASS" : t.pass === "partial" ? "PART" : "FAIL";
    console.log(` ${mark.padEnd(5)} ${t.id}  ${t.got.slice(0, 150)}`);
});
console.log("== roundtrip ==");
const cnt = {};
rt.forEach((r) => (cnt[r.status] = (cnt[r.status] || 0) + 1));
console.log(cnt);
rt.filter((r) => r.status === "diverged")
    .slice(0, 8)
    .forEach((r) => console.log("  DIV", r.file, r.detail));
console.log("== leak ==");
const agg = leak.filter((r) => r.policy);
console.log(
    "naive(text.string in protected subtrees): total",
    agg.reduce((a, r) => a + r.naive.leaked, 0),
    "/",
    agg.reduce((a, r) => a + r.naive.total, 0),
    "strings leaked; avg rate",
    (agg.reduce((a, r) => a + r.naive.rate, 0) / agg.length).toFixed(3),
);
console.log(
    "policy-aware blocks: total",
    agg.reduce((a, r) => a + r.policy.total, 0),
    "leaking",
    agg.reduce((a, r) => a + r.policy.leaking, 0),
);
agg.filter((r) => r.policy.leaking > 0)
    .slice(0, 6)
    .forEach((r) =>
        console.log("  LEAK", r.file, JSON.stringify(r.policy.examples)),
    );
agg.filter((r) => r.naive.leaked > 0)
    .slice(0, 6)
    .forEach((r) =>
        console.log("  naive-sample", r.file, JSON.stringify(r.naive.samples)),
    );
console.log("total ms:", Date.now() - t0);
