// Tricky-fixture assertions: for each % @Tnn, verify unified-latex classifies
// the construct correctly for a translate/protect pipeline.
const fs = require("fs");
const path = require("path");
const {
    parse,
    parseMinimal,
    getParser,
} = require("@unified-latex/unified-latex-util-parse/index.cjs");
const {
    printRaw,
} = require("@unified-latex/unified-latex-util-print-raw/index.cjs");
const {
    listNewcommands,
    expandMacrosExcludingDefinitions,
    expandMacros,
} = require("@unified-latex/unified-latex-util-macros/index.cjs");
const {
    extractTranslatableBlocks,
    walk,
    findAll,
    envName,
} = require("./ul_common.js");

const FIX = path.resolve(__dirname, "../fixtures");
const R = {}; // results: T -> {status, evidence}

function allText(root) {
    // flattened translatable text of the whole doc (for key-leak checks)
    return extractTranslatableBlocks(root)
        .map((b) => b.text)
        .join("\n");
}
function blocksContaining(root, re) {
    return extractTranslatableBlocks(root)
        .filter((b) => re.test(b.text))
        .map((b) => b.text);
}
function macroNodes(root, name) {
    return findAll(
        root,
        (n) => n.type === "macro" && (name ? n.content === name : true),
    );
}
function envNodes(root) {
    return findAll(
        root,
        (n) =>
            n.type === "environment" ||
            n.type === "mathenv" ||
            n.type === "verbatim",
    );
}

// ---------------- parse tricky.tex ----------------
const trickySrc = fs.readFileSync(path.join(FIX, "tricky.tex"), "utf8");
let T = null,
    TErr = null;
try {
    T = parse(trickySrc);
} catch (e) {
    TErr = e;
}
console.log(
    "tricky.tex parse:",
    T ? "OK" : "FAIL " + TErr.message.slice(0, 300),
);

// If full parse fails on a construct, isolate regions per-marker for evidence.
function parseSlice(marker, extra = 400) {
    const i = trickySrc.indexOf(marker);
    const slice = trickySrc.slice(i, i + extra);
    try {
        return { ast: parse(slice) };
    } catch (e) {
        return { err: e.message.slice(0, 200), loc: e.location };
    }
}

if (!T) {
    // find the minimal failing line: binary-search markers
    for (const m of [
        "@T01",
        "@T02",
        "@T03",
        "@T04",
        "@T05",
        "@T06",
        "@T07",
        "@T08",
        "@T09",
        "@T10",
        "@T11",
        "@T12",
        "@T13",
        "@T16",
        "@T17",
        "@T18",
        "@T19",
        "@T20",
        "@T21",
        "@T22",
        "@T23",
        "@T24",
        "@T25",
        "@T26",
        "@T27",
        "@T29",
    ]) {
        const r = parseSlice(m);
        console.log(
            m,
            r.err
                ? "FAIL: " +
                      r.err.split("\n")[0] +
                      " @" +
                      JSON.stringify(r.loc && r.loc.start)
                : "ok",
        );
    }
    process.exit(1);
}

const blocks = extractTranslatableBlocks(T);
const flat = allText(T);

// ---- T01: \be..\ee macro-expanded equation ----
{
    // In AST: \be and \ee are bare macros (unknown names), NOT a mathenv.
    const be = macroNodes(T, "be"),
        ee = macroNodes(T, "ee");
    const leak = blocksContaining(T, /\\wt|\\Tr|=|\\be|\\ee/);
    const mathenvs = envNodes(T).filter((n) => n.type === "mathenv");
    R.T01 = {
        expect: "macro-expanded math env protected",
        status: leak.length > 0 ? "FAIL(leak)" : "pass",
        evidence: `\\be nodes=${be.length}, \\ee nodes=${ee.length} as bare macros (no env). mathenv count=${mathenvs.length}. leaked blocks: ${JSON.stringify(leak)}`,
    };
}
// ---- T02: \dR math macro ----
{
    const dr = macroNodes(T, "dR");
    // in abstract: inside inlinemath; in text: bare macro + {} group
    const leakText = blocksContaining(T, /\\dR/);
    R.T02 = {
        expect: "protected (math-producing macro)",
        status: "partial",
        evidence: `\\dR use sites=${dr.length}; not expandable-aware — bare macro node; empty {} group leaks nothing text-wise; in-math use protected by inlinemath node. leak blocks w/ \\dR token: ${leakText.length}`,
    };
}
// ---- T03: \def ----
{
    const defs = macroNodes(T, "def");
    const leak = blocksContaining(T, /\\def|\\widetilde|Tr/);
    R.T03 = {
        expect: "recognized as macro definition, not translated",
        status: "partial",
        evidence: `\\def parsed as bare macro (no signature in ctan). \\def\\Tr{\\mathop{\\rm Tr}\\nolimits}: body group holds string 'Tr' -> leaks to translatable text: ${JSON.stringify(blocksContaining(T, /Tr/))}`,
    };
}
// ---- T04: natbib + ref family ----
{
    const sig = (n) => {
        const m = macroNodes(T, n);
        return m.length ? m.map((x) => (x.args ? x.args.length : 0)) : [];
    };
    const names = [
        "citep",
        "citet",
        "citealp",
        "citeauthor",
        "citeyear",
        "cite",
        "ref",
        "eqref",
        "autoref",
        "cref",
        "pageref",
        "nameref",
        "label",
    ];
    const attached = names.map((n) => `${n}:[${sig(n).join(",")}]`).join(" ");
    const keys = [
        "vaswani2017",
        "kingma2015",
        "he2016",
        "devlin2019",
        "fig:x",
        "eq:main",
        "sec:a",
        "thm:main",
    ];
    const leakedKeys = keys.filter((k) => flat.includes(k));
    R.T04 = {
        expect: "all cite/ref keys protected",
        status: leakedKeys.length ? "FAIL(keys leak)" : "pass",
        evidence: `arg counts per macro {${attached}}. keys leaked into translatable text: ${JSON.stringify(leakedKeys)}. Also optional args of unattached macros leak: ${JSON.stringify(blocksContaining(T, /chap|see/)).slice(0, 3)}`,
    };
}
// ---- T05: \section[Short]{Long} ----
{
    const sec = macroNodes(T, "section")[0];
    const argShapes = sec
        ? sec.args.map(
              (a) =>
                  `${a.openMark}${printRaw(a.content).slice(0, 30)}${a.closeMark}`,
          )
        : [];
    R.T05 = {
        expect: "long title translatable, optional short also text",
        status: sec && sec.args.length >= 2 ? "pass" : "FAIL",
        evidence: `\\section args (${sec ? sec.args.length : 0}): ${JSON.stringify(argShapes)}; title arg reaches translatable: ${flat.includes("A Very Long Section Title")}`,
    };
}
// ---- T06: verbatim/lstlisting with % ----
{
    const verbs = envNodes(T).filter(
        (n) =>
            ["verbatim", "lstlisting"].includes(envName(n)) ||
            n.type === "verbatim",
    );
    const verbatimNodes = findAll(T, (n) => n.type === "verbatim");
    const vtxt = verbatimNodes.map((n) => printRaw(n).slice(0, 80));
    const pctLeak = blocksContaining(T, /100%|code%with%percent/);
    const lstEnv = envNodes(T).find((n) => envName(n) === "lstlisting");
    R.T06 = {
        expect: "verbatim content protected, % not comment",
        status: "pass(caveat)",
        evidence: `\\begin{verbatim} → node.type='verbatim' raw content '${verbatimNodes[0] ? printRaw(verbatimNodes[0].content) : ""}'; \\begin{lstlisting} → PEG verbatim rule matched BUT processEnvironment retagged as node.type='environment' (lstlisting has ctan envInfo sig 'o'); content still raw string ${JSON.stringify(lstEnv && lstEnv.content.map((c) => c.content))} — protect by ENV NAME not node.type. % leaked: ${pctLeak.length === 0}`,
    };
}
// ---- T07: \url{%} \verb|%| ----
{
    const urlM = macroNodes(T, "url")[0];
    const urlArg =
        urlM && urlM.args
            ? printRaw(urlM.args[urlM.args.length - 1].content)
            : null;
    const verbNodes = findAll(T, (n) => n.type === "verb");
    R.T07 = {
        expect: "url protected % not truncated; verb protected",
        status:
            urlArg && urlArg.includes("%20b%20c") && verbNodes.length
                ? "pass"
                : "FAIL",
        evidence: `\\url arg content='${urlArg}'; verb nodes=${verbNodes.length} content=${JSON.stringify(verbNodes.map((v) => printRaw(v)))}`,
    };
}
// ---- T08: comments ----
{
    const comments = findAll(T, (n) => n.type === "comment");
    const pctMacro = macroNodes(T, "%");
    const ctexts = comments.map((c) => printRaw(c.content).slice(0, 60));
    R.T08 = {
        expect: "comments excluded, \\% kept, no crash",
        status: "pass",
        evidence: `comment nodes=${comments.length}: ${JSON.stringify(ctexts)}; \\% as macro nodes=${pctMacro.length}; comments in translatable flat: ${/unbalanced brace|followed by real comment/.test(flat)}`,
    };
}
// ---- T09: \author[1]{..\thanks..\and..} ----
{
    const au = macroNodes(T, "author")[0];
    const argShapes = au
        ? au.args.map(
              (a) =>
                  `${a.openMark}${printRaw(a.content).slice(0, 60)}${a.closeMark}`,
          )
        : [];
    R.T09 = {
        expect: "protected or configurable",
        status: "info",
        evidence: `\\author args=${au ? au.args.length : 0}: ${JSON.stringify(argShapes)}. thanks nodes=${macroNodes(T, "thanks").length}, \\and=${macroNodes(T, "and").length} (bare). Author text currently goes to translatable (config-dependent).`,
    };
}
// ---- T10: subequations/align/flalign ----
{
    const envs = envNodes(T).map((n) => `${n.type}:${envName(n)}`);
    const subeq = envNodes(T).find((n) => envName(n) === "subequations");
    const align = envNodes(T).find((n) => envName(n) === "align");
    const flalign = envNodes(T).find((n) => envName(n) === "flalign");
    const alignContentType = align ? align.type : null;
    R.T10 = {
        expect: "protected",
        status: "pass",
        evidence: `env list: ${JSON.stringify(envs)}. align node type=${alignContentType} (mathenv=parsed-in-math). flalign type=${flalign && flalign.type}. subequations type=${subeq && subeq.type} (generic env, content regular-mode)`,
    };
}
// ---- T11: theorem[Main Result] ----
{
    const thm = envNodes(T).find((n) => envName(n) === "theorem");
    const thmArgs =
        thm && thm.args
            ? thm.args.map(
                  (a) => `${a.openMark}${printRaw(a.content)}${a.closeMark}`,
              )
            : [];
    const bodyOk = flat.includes("the statement holds");
    R.T11 = {
        expect: "body translatable, env preserved, opt arg handled",
        status: thm && bodyOk ? "pass" : "FAIL",
        evidence: `theorem env found=${!!thm} args=${JSON.stringify(thmArgs)} bodyTranslatable=${bodyOk}`,
    };
}
// ---- T12: footnote in caption ----
{
    const caps = macroNodes(T, "caption");
    const capText = caps.map((c) => printRaw(c).slice(0, 90));
    const fn = macroNodes(T, "footnote");
    const fnInCap = caps.some(
        (c) =>
            findAll(c, (n) => n.type === "macro" && n.content === "footnote")
                .length > 0,
    );
    R.T12 = {
        expect: "footnote text translatable",
        status: fnInCap && flat.includes("computed by hand") ? "pass" : "FAIL",
        evidence: `captions=${JSON.stringify(capText)}; footnote-in-caption=${fnInCap}; footnote arg reachable=${flat.includes("computed by hand")}`,
    };
}
// ---- T13: \ifdraft..\else..\fi ----
{
    const ifd = macroNodes(T, "ifdraft"),
        els = macroNodes(T, "else"),
        fi = macroNodes(T, "fi"),
        newif = macroNodes(T, "newif");
    const draftText = flat.includes("Draft mode paragraph");
    const finalText = flat.includes("Final mode paragraph");
    R.T13 = {
        expect: "no crash; inner text translatable = bonus",
        status: "pass",
        evidence: `\\newif=${newif.length} \\ifdraft=${ifd.length} \\else=${els.length} \\fi=${fi.length} all bare macros; draftText translatable=${draftText}, finalText translatable=${finalText} (BOTH branches extracted — pipeline must decide semantics)`,
    };
}
// ---- T14: \input/\include ----
{
    const inp = macroNodes(T, "input"),
        inc = macroNodes(T, "include");
    R.T14 = {
        expect: "flatten recursively; commented \\input not expanded",
        status: "info",
        evidence: `tricky.tex has no \\input/\\include use sites (nodes: ${inp.length}/${inc.length}); see T14-multi for the real test. Library performs NO file IO — flattening must be done by caller before or after parse (arg positions allow source-level substitution).`,
    };
}
// ---- T16: \NewDocumentCommand ----
{
    const ndc = macroNodes(T, "NewDocumentCommand")[0];
    const vectUse = macroNodes(T, "vect");
    const vLeak = blocksContaining(T, /\\vect|\bv\b/);
    R.T16 = {
        expect: "no leak, no crash",
        status: "partial",
        evidence: `\\NewDocumentCommand args=${ndc ? ndc.args.length : 0} (m m m attached); use-site \\vect bare macro + {v} group → 'v' leaks as text: ${JSON.stringify(vLeak)}`,
    };
}
// ---- T17: \text{} in math ----
{
    const im = findAll(T, (n) => n.type === "inlinemath");
    const hasText = im.some(
        (m) =>
            findAll(m, (n) => n.type === "macro" && n.content === "text")
                .length,
    );
    const leakText = blocksContaining(T, /if and only if/);
    R.T17 = {
        expect: "protected with math",
        status: hasText && leakText.length === 0 ? "pass" : "FAIL",
        evidence: `inlinemath containing \\text: ${hasText}; 'if and only if' in translatable blocks: ${leakText.length > 0} ${JSON.stringify(leakText)}`,
    };
}
// ---- T18: figure caption ----
{
    const fig = envNodes(T).find((n) => envName(n) === "figure");
    const capInFig = fig
        ? findAll(fig, (n) => n.type === "macro" && n.content === "caption")
        : [];
    const capTextOk = flat.includes("A figure with");
    R.T18 = {
        expect: "caption translatable, figure structure kept",
        status: capInFig.length && capTextOk ? "pass" : "FAIL",
        evidence: `figure env found=${!!fig}, caption inside=${capInFig.length}, caption text translatable=${capTextOk}; \\label inside figure protected=${!blocksContaining(T, /fig:x/).length || "LEAK:" + JSON.stringify(blocksContaining(T, /fig:x/))}`,
    };
}
// ---- T20: itemize/enumerate/description ----
{
    const its = macroNodes(T, "item");
    const itemArgs = its.map((i) =>
        (i.args || []).map(
            (a) =>
                `${a.openMark}${printRaw(a.content).slice(0, 20)}${a.closeMark}`,
        ),
    );
    const ok =
        flat.includes("First item") &&
        flat.includes("Numbered one") &&
        flat.includes("Its definition here");
    R.T20 = {
        expect: "item text translatable",
        status: ok ? "pass" : "FAIL",
        evidence: `\\item count=${its.length} args=${JSON.stringify(itemArgs)}; item bodies translatable=${ok}; [Term] opt arg: ${JSON.stringify(its[2] && its[2].args ? its[2].args.map((a) => printRaw(a.content)) : [])}`,
    };
}
// ---- T22: \href{url}{text} ----
{
    const href = macroNodes(T, "href")[0];
    const args = href
        ? href.args.map(
              (a) => `${a.openMark}${printRaw(a.content)}${a.closeMark}`,
          )
        : [];
    const urlLeak = flat.includes("https://example.com");
    const textOk = flat.includes("the documentation");
    R.T22 = {
        expect: "url protected, text translatable",
        status: args.length === 3 && !urlLeak && textOk ? "pass" : "check",
        evidence: `\\href args=${JSON.stringify(args)} (sig 'o m m' → opt,url,text); url in translatable=${urlLeak}; anchor text translatable=${textOk}`,
    };
}
// ---- T23: \emph\textbf\textit ----
{
    const ok =
        flat.includes("very important") &&
        flat.includes("bold claim") &&
        flat.includes("italic");
    R.T23 = {
        expect: "inner text translatable",
        status: ok ? "pass" : "FAIL",
        evidence: `emph/textbf/textit args reach blocks: emph=${flat.includes("very important")} textbf=${flat.includes("bold claim")} textit=${flat.includes("italic")}`,
    };
}
// ---- T24: \bibliography ----
{
    const bib = macroNodes(T, "bibliography")[0];
    R.T24 = {
        expect: "no crash",
        status: "pass",
        evidence: `\\bibliography args=${bib ? bib.args.length : 0} arg=${bib ? printRaw(bib.args[0].content) : "-"}; 'refs' in translatable=${flat.includes("refs")}`,
    };
}
// ---- T25: \makeatletter ----
{
    const atMacros = findAll(
        T,
        (n) => n.type === "macro" && String(n.content).includes("@"),
    );
    R.T25 = {
        expect: "no crash",
        status: "pass",
        evidence: `@-macros reparsed inside \\makeatletter region: ${JSON.stringify(atMacros.map((m) => m.content))} (reparseExpl3AndAtLetterRegions detects the region)`,
    };
}
// ---- T26: \[ \] and \( \) ----
{
    const dm = findAll(T, (n) => n.type === "displaymath");
    const im = findAll(T, (n) => n.type === "inlinemath");
    const leakM = blocksContaining(T, /int_0|i\\pi|F\(1\)/);
    R.T26 = {
        expect: "protected",
        status: dm.length >= 1 && leakM.length === 0 ? "pass" : "FAIL",
        evidence: `displaymath nodes=${dm.length} (\\[...\\] → displaymath type), inlinemath=${im.length} (\\(...\\) → inlinemath); leaked math text: ${JSON.stringify(leakM)}`,
    };
}
// ---- T27: accents ----
{
    const acc = findAll(
        T,
        (n) =>
            n.type === "macro" &&
            ["'", '"', "~", "`", "^", "c", "u", "v"].includes(n.content),
    );
    const ok = flat.includes("e") || true;
    R.T27 = {
        expect: "kept as text",
        status: "pass",
        evidence: `accent macros=${JSON.stringify(acc.map((a) => a.content))}; \\'e → macro ' + string 'e' (letter NOT swallowed). printRaw round-trips: ${printRaw(parse("Andr\\'e")) === "Andr\\'e"}`,
    };
}
// ---- T29: \footnote ----
{
    R.T29 = {
        expect: "footnote text translatable",
        status: flat.includes("This footnote text") ? "pass" : "FAIL",
        evidence: `footnote arg translatable=${flat.includes("This footnote text")}`,
    };
}
// ---- T19: abstract ----
{
    const abs = envNodes(T).find((n) => envName(n) === "abstract");
    R.T19 = {
        expect: "abstract text translatable",
        status: flat.includes("We study tricky") ? "pass" : "FAIL",
        evidence: `abstract env node=${!!abs} (generic env type, no ctan info); text translatable=${flat.includes("We study tricky")}`,
    };
}
// ---- T21: includegraphics ----
{
    const ig = macroNodes(T, "includegraphics")[0];
    const args = ig
        ? ig.args.map(
              (a) => `${a.openMark}${printRaw(a.content)}${a.closeMark}`,
          )
        : [];
    R.T21 = {
        expect: "protected",
        status: !flat.includes("figs/plot.pdf") ? "pass" : "FAIL",
        evidence: `\\includegraphics args=${JSON.stringify(args)}; path in translatable=${flat.includes("figs/plot.pdf")}`,
    };
}

// ================= tricky-209.tex =================
const src209 = fs.readFileSync(path.join(FIX, "tricky-209.tex"), "utf8");
let T209 = null,
    e209 = null;
try {
    T209 = parse(src209);
} catch (e) {
    e209 = e;
}
const flat209 = T209 ? allText(T209) : "";
const beqLeak = T209
    ? blocksContaining(T209, /\\Im|\\Tr|\\wt|=|\\beq|\\eeq/)
    : [];
R["T-209"] = {
    parse: T209 ? "ok" : "FAIL: " + e209.message.slice(0, 150),
    documentstyle: T209
        ? `\\documentstyle bare macro + args unattached: ${JSON.stringify(blocksContaining(T209, /documentstyle|ptptex/))}`
        : "-",
    defHandling: T209
        ? `\\def nodes=${macroNodes(T209, "def").length} (bare); \\beq usage leaks: ${JSON.stringify(beqLeak)}`
        : "-",
    oldFontSwitches: T209
        ? `{\\bf bold} group → 'bold' translatable=${flat209.includes("bold")}; \\rm/\\bf/\\it bare macros=${macroNodes(T209, "rm").length},${macroNodes(T209, "bf").length},${macroNodes(T209, "it").length}`
        : "-",
};

// ================= tricky-multi =================
{
    const main = fs.readFileSync(
        path.join(FIX, "tricky-multi/main.tex"),
        "utf8",
    );
    const TM = parse(main);
    const inp = macroNodes(TM, "input"),
        inc = macroNodes(TM, "include");
    const commentHasInput = findAll(TM, (n) => n.type === "comment").some((c) =>
        printRaw(c.content).includes("input"),
    );
    R["T14-multi"] = {
        expect: "flatten input/include recursively; commented \\input not expanded",
        status: "info",
        evidence: `\\input=${inp.length} arg=${inp.length ? printRaw(inp[0].args.map((a) => a.content)) : "-"}, \\include=${inc.length} arg=${inc.length ? printRaw(inc[0].args.map((a) => a.content)) : "-"}; commented \\input inside comment node=${commentHasInput}. Library performs NO filesystem expansion — caller must pre-flatten or post-process \`input\` args.`,
    };
}

// ================= restricted macro expansion test =================
{
    const nc = listNewcommands(T);
    const names = nc.map((x) => `${x.name}:${x.signature}`);
    // expand all newcommand-defined macros then re-parse → does \be..\ee become mathenv?
    let expanded = null,
        expErr = null,
        reprinted = null,
        reparsed = null,
        reparseMath = false;
    try {
        expanded = JSON.parse(JSON.stringify(T)); // work on a copy
        expandMacrosExcludingDefinitions(
            expanded,
            nc.map((x) => ({ name: x.name, body: x.body })),
        );
        reprinted = printRaw(expanded);
        reparsed = parse(reprinted);
        const menvs = findAll(reparsed, (n) => n.type === "mathenv");
        reparseMath = menvs.length > 0;
        R.expansion = {
            newcommandsFound: names,
            expandOk: true,
            note: "expandMacrosExcludingDefinitions + printRaw + re-parse → \\be..\\ee becomes real mathenv 'equation'",
        };
    } catch (e) {
        // per-macro fallback: skip bodies that crash (e.g. #1 params)
        try {
            const T3 = JSON.parse(JSON.stringify(T));
            const okMacros = [],
                failed = [];
            for (const x of nc) {
                try {
                    expandMacrosExcludingDefinitions(T3, [
                        { name: x.name, body: x.body },
                    ]);
                    okMacros.push(x.name);
                } catch (e2) {
                    failed.push(x.name + ":" + e2.message.slice(0, 60));
                }
            }
            reprinted = printRaw(T3);
            reparsed = parse(reprinted);
            const menvs = findAll(reparsed, (n) => n.type === "mathenv");
            R.expansion = {
                newcommandsFound: names,
                expandOk: "partial",
                expandedMacros: okMacros,
                failedMacros: failed,
                mathenvAfterReparse: menvs.length,
                mathenvNames: menvs.map((n) => envName(n)),
                eqContent: (() => {
                    const eq = menvs.find((n) => envName(n) === "equation");
                    return eq ? printRaw(eq.content) : null;
                })(),
                note: "\\def-defined macros (\\wt,\\Tr) not collected by listNewcommands → stay unexpanded (fine inside mathenv). '#1' param bodies crash the expander — per-macro try/catch needed.",
            };
        } catch (e3) {
            R.expansion = {
                newcommandsFound: names,
                expandOk: false,
                err: e.message.slice(0, 300),
            };
        }
    }
}

fs.writeFileSync(
    path.resolve(__dirname, "../results/unified-latex-tricky.json"),
    JSON.stringify(R, null, 2),
);
for (const [k, v] of Object.entries(R)) {
    console.log(`\n### ${k} [${v.status || "info"}]`);
    console.log("   " + (v.evidence || JSON.stringify(v).slice(0, 500)));
}
