// tree-sitter-latex (@pfoerster/tree-sitter-latex 0.6.0, native binding via tree-sitter 0.25) benchmark:
//  1) corpus parse: ms + ERROR node count + MISSING node count + error coverage per file
//     (node offsets are UTF-16 char indices — bytes/errorBytes/corruptedAt are all char units)
//  2) tricky.tex trap regions: which traps fall inside ERROR nodes
//  3) post-translation validator evaluation: corrupted inputs -> can ERROR/MISSING localize damage?
//  4) incremental re-parse demo (tree.edit + parse with old tree)
// Writes: ../results/tree-sitter-latex-parse.json, ../results/tree-sitter-latex-traps.json,
//         ../results/tree-sitter-latex-validator.json
"use strict";
const fs = require("fs");
const path = require("path");
const Parser = require("tree-sitter");
const Latex = require("@pfoerster/tree-sitter-latex");
const {
    CORPUS,
    FIXTURES,
    RESULTS,
    listTexFiles,
    trapRegions,
    ensureResults,
} = require("./common");

const parser = new Parser();
parser.setLanguage(Latex);
const PARSE_TIMEOUT_US = 30_000_000; // 30s——语料文件超大时不让单篇拖死整批

function errorStats(root) {
    let errorNodes = 0,
        missingNodes = 0,
        errorBytes = 0;
    const errorSpans = [];
    const stack = [root]; // 迭代遍历——深树递归会爆栈
    while (stack.length) {
        const n = stack.pop();
        if (n.type === "ERROR") {
            errorNodes++;
            errorBytes += n.endIndex - n.startIndex;
            errorSpans.push([n.startIndex, n.endIndex]);
        }
        if (n.isMissing) missingNodes++;
        for (let i = n.childCount - 1; i >= 0; i--) stack.push(n.child(i));
    }
    return { errorNodes, missingNodes, errorBytes, errorSpans };
}

function collectErrorNodes(root, includeMissing) {
    const errs = [];
    const stack = [root];
    while (stack.length) {
        const n = stack.pop();
        if (n.type === "ERROR" || (includeMissing && n.isMissing)) errs.push(n);
        for (let i = n.childCount - 1; i >= 0; i--) stack.push(n.child(i));
    }
    return errs;
}

// ---------- 1. corpus ----------
function benchCorpus() {
    const rows = [];
    for (const f of listTexFiles(CORPUS)) {
        const src = fs.readFileSync(f, "utf8");
        const t0 = process.hrtime.bigint();
        const tree = parser.parse(src, null, {
            timeoutMicros: PARSE_TIMEOUT_US,
        });
        const ms = Number(process.hrtime.bigint() - t0) / 1e6;
        if (!tree) {
            // 超时返回 null（binding 不抛）——诚实记一行而不是崩掉整批
            rows.push({
                file: path.relative(CORPUS, f),
                bytes: src.length,
                ok: false,
                timeout: true,
                hasError: false,
                errorNodes: 0,
                missingNodes: 0,
                errorBytes: 0,
                errorPct: 0,
                ms: Math.round(ms * 100) / 100,
            });
            continue;
        }
        const s = errorStats(tree.rootNode);
        rows.push({
            file: path.relative(CORPUS, f),
            bytes: src.length,
            ok: true, // tree-sitter never throws
            hasError: tree.rootNode.hasError,
            errorNodes: s.errorNodes,
            missingNodes: s.missingNodes,
            errorBytes: s.errorBytes,
            errorPct: +((100 * s.errorBytes) / src.length).toFixed(2),
            ms: Math.round(ms * 100) / 100,
            firstErrorSpan: s.errorSpans[0] || null,
        });
    }
    return rows;
}

// ---------- 2. traps: does each @Tnn region contain / sit inside ERROR? ----------
function benchTraps() {
    const src = fs.readFileSync(path.join(FIXTURES, "tricky.tex"), "utf8");
    const tree = parser.parse(src);
    const regions = trapRegions(src);
    // collect all ERROR nodes with ranges
    const errs = collectErrorNodes(tree.rootNode, false).map((n) => [
        n.startIndex,
        n.endIndex,
    ]);
    const rows = regions.map((r) => {
        const inside = errs.filter(([a, b]) => a < r.end && b > r.start);
        const coveredPct = inside.length
            ? Math.min(
                  100,
                  Math.round(
                      (100 *
                          inside.reduce(
                              (x, [a, b]) =>
                                  x +
                                  (Math.min(b, r.end) - Math.max(a, r.start)),
                              0,
                          )) /
                          (r.end - r.start),
                  ),
              )
            : 0;
        return {
            id: r.id,
            lines: `${r.startLine + 1}-${r.endLine}`,
            errorNodesInRegion: inside.length,
            regionCoveredByErrorPct: coveredPct,
        };
    });
    // also: parse a variant with the two \begin/\end-in-macro lines neutralized, to see residual errors
    const sanitized = src
        .replace(/\\begin\{equation\}/g, "BEGIN_EQ")
        .replace(/\\end\{equation\}/g, "END_EQ");
    const t2 = parser.parse(sanitized);
    const s2 = errorStats(t2.rootNode);
    return {
        perTrap: rows,
        totalErrorNodes: errs.length,
        errorSpans: errs,
        sanitized: {
            errorNodes: s2.errorNodes,
            missingNodes: s2.missingNodes,
            errorBytes: s2.errorBytes,
        },
    };
}

// ---------- 3. validator evaluation ----------
// For each corrupted sample: record ERROR/MISSING positions vs the actual corruption offset.
function benchValidator() {
    const base = fs.readFileSync(path.join(FIXTURES, "tricky.tex"), "utf8");
    const good = [
        "\\documentclass{article}\n\\begin{document}\nHello \\textbf{world}, see \\eqref{eq:x}.\n\\begin{equation}\n a=b\n\\end{equation}\n\\end{document}\n",
        "Para one.\n\nPara two with $x^2$ math and \\emph{emphasis}.\n",
    ];
    const cases = [];
    // a) delete one closing brace mid-document
    {
        const src = good[0];
        const at = src.indexOf("{world}") + "{world".length; // position of the }
        const bad = src.slice(0, at) + src.slice(at + 1);
        cases.push({ name: "delete-}", corruptedAt: at, src: bad });
    }
    // b) \begin/\end name mismatch
    {
        const src = good[0].replace("\\end{equation}", "\\end{eqnarray}");
        cases.push({
            name: "env-name-mismatch",
            corruptedAt: src.indexOf("eqnarray"),
            src,
        });
    }
    // c) unclosed inline math
    {
        const src = good[1].replace("$x^2$", "$x^2"); // drop closing $
        cases.push({
            name: "unclosed-$",
            corruptedAt: src.indexOf("$x^2"),
            src,
        });
    }
    // d) dangling \end
    {
        const src = good[1] + "\\end{table}\n";
        cases.push({ name: "dangling-end", corruptedAt: src.length, src });
    }
    // e) \begin without \end
    {
        const src = good[0].replace("\\end{equation}\n", "");
        cases.push({
            name: "missing-end",
            corruptedAt: good[0].indexOf("\\end{equation}"),
            src,
        });
    }
    // f) brace opened never closed (\section{TITLE)
    {
        const src = "Text before.\n\\section{Broken title\nMore text after.\n";
        cases.push({
            name: "unclosed-group",
            corruptedAt: src.indexOf("{Broken"),
            src,
        });
    }
    // g) realistic translation damage: placeholder + mangled command
    {
        const src =
            "Translated text \\citep{key2020} end.\n\nSecond para $\\alpha + \\beta$ done.\n";
        const bad = src.replace("\\citep{key2020}", "\\citep{key2020"); // dropped }
        cases.push({
            name: "cite-unclosed",
            corruptedAt: src.indexOf("key2020") + 7,
            src: bad,
        });
    }
    // h) big real file: cut one } from tricky.tex and see localization
    {
        const at = base.indexOf("for details.") - 2;
        const bad = base.slice(0, at) + base.slice(at + 1); // remove the } of \href{..}{the documentation}
        cases.push({ name: "tricky-minus-brace", corruptedAt: at, src: bad });
    }

    const out = [];
    for (const c of cases) {
        const t = parser.parse(c.src);
        const errs = collectErrorNodes(t.rootNode, true).map((n) => ({
            type: n.isMissing ? "MISSING" : "ERROR",
            start: n.startIndex,
            end: n.endIndex,
            row: n.startPosition.row,
        }));
        const near = errs.filter(
            (e) =>
                Math.abs(e.start - c.corruptedAt) < 200 ||
                (e.start <= c.corruptedAt && e.end >= c.corruptedAt),
        );
        out.push({
            case: c.name,
            corruptedAt: c.corruptedAt,
            hasError: t.rootNode.hasError,
            errorCount: errs.length,
            errors: errs.slice(0, 6),
            localizedNearCorruption: near.length > 0,
        });
    }
    return out;
}

// ---------- 4. incremental reparse ----------
function benchIncremental() {
    const src = fs.readFileSync(path.join(FIXTURES, "tricky.tex"), "utf8");
    const t1 = parser.parse(src);
    // simulate an edit: replace a word mid-file
    const at = src.indexOf("very important");
    const edited =
        src.slice(0, at) +
        "EXTREMELY important" +
        src.slice(at + "very important".length);
    // row/col 由 src/edited 现算——fixture 一改硬编码 Point 就静默失效
    const rowOf = (s, i) => s.slice(0, i).split("\n").length - 1;
    const colOf = (s, i) => i - (s.lastIndexOf("\n", i - 1) + 1);
    t1.edit({
        startIndex: at,
        oldEndIndex: at + 14,
        newEndIndex: at + 19,
        startPosition: { row: rowOf(src, at), column: colOf(src, at) },
        oldEndPosition: {
            row: rowOf(src, at + 14),
            column: colOf(src, at + 14),
        },
        newEndPosition: {
            row: rowOf(edited, at + 19),
            column: colOf(edited, at + 19),
        },
    });
    const t0 = process.hrtime.bigint();
    const t2 = parser.parse(edited, t1);
    const ms = Number(process.hrtime.bigint() - t0) / 1e6;
    return {
        incrementalMs: Math.round(ms * 1000) / 1000,
        hasError: t2.rootNode.hasError,
        changedRanges: t1.getChangedRanges(t2).length,
    };
}

// ---------- run ----------
ensureResults();
const corpus = benchCorpus();
fs.writeFileSync(
    path.join(RESULTS, "tree-sitter-latex-parse.json"),
    JSON.stringify(corpus, null, 1),
);
const traps = benchTraps();
fs.writeFileSync(
    path.join(RESULTS, "tree-sitter-latex-traps.json"),
    JSON.stringify(traps, null, 1),
);
const validator = benchValidator();
fs.writeFileSync(
    path.join(RESULTS, "tree-sitter-latex-validator.json"),
    JSON.stringify(validator, null, 1),
);
const incr = benchIncremental();

console.log("== corpus ==");
console.log(
    `files=${corpus.length} clean=${corpus.filter((r) => r.ok && !r.hasError).length} withErrors=${corpus.filter((r) => r.hasError).length} timeout=${corpus.filter((r) => r.timeout).length}`,
);
console.log(
    "files where >10% of bytes are inside ERROR:",
    corpus
        .filter((r) => r.errorPct > 10)
        .map((r) => `${r.file}(${r.errorPct}%,${r.errorNodes}err)`)
        .join(" ") || "none",
);
console.log(
    "files with small errors (<=10%):",
    corpus
        .filter((r) => r.errorPct > 0 && r.errorPct <= 10)
        .map(
            (r) =>
                `${r.file}(${r.errorPct}%,${r.errorNodes}e+${r.missingNodes}m)`,
        )
        .join(" ") || "none",
);
const slow = corpus.filter((r) => r.ms > 50);
console.log(
    "slow(>50ms):",
    slow.map((r) => `${r.file}:${r.ms}ms`).join(" ") || "none",
);
console.log(
    "total chars in ERROR:",
    corpus.reduce((a, r) => a + r.errorBytes, 0),
    "/",
    corpus.reduce((a, r) => a + r.bytes, 0),
);
console.log("== traps ==");
traps.perTrap.forEach((t) =>
    console.log(
        ` ${t.id} lines ${t.lines}: errNodes=${t.errorNodesInRegion} cover=${t.regionCoveredByErrorPct}%`,
    ),
);
console.log("sanitized (BEGIN_EQ/END_EQ):", JSON.stringify(traps.sanitized));
console.log("== validator ==");
validator.forEach((v) =>
    console.log(
        ` ${v.localizedNearCorruption ? "HIT " : "MISS"} ${v.case.padEnd(20)} errs=${v.errorCount} near=${v.localizedNearCorruption} ${JSON.stringify(v.errors.slice(0, 3))}`,
    ),
);
console.log("== incremental ==", JSON.stringify(incr));
