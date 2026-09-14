#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pylatexenc benchmark per bench/PROTOCOL.md.

Usage:
    python bench_pylatexenc.py parse      # corpus robustness, subprocess+30s timeout
    python bench_pylatexenc.py fixtures   # T-assertions on tricky*.tex
    python bench_pylatexenc.py roundtrip  # pos/len reconstruction on corpus .tex
    python bench_pylatexenc.py extract    # translatable-block extraction + leak rate
    python bench_pylatexenc.py newcmd     # \newcommand "half-expansion" feasibility
    python bench_pylatexenc.py all        # everything -> results/pylatexenc-parse.json
"""

import os
import re
import sys
import json
import time
import signal
import traceback
import multiprocessing as mp

BENCH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(BENCH, "corpus")
FIXTURES = os.path.join(BENCH, "fixtures")
RESULTS = os.path.join(BENCH, "results")

import pylatexenc
from pylatexenc.latexwalker import (
    LatexWalker,
    LatexCharsNode,
    LatexGroupNode,
    LatexCommentNode,
    LatexMacroNode,
    LatexEnvironmentNode,
    LatexSpecialsNode,
    LatexMathNode,
    LatexWalkerError,
    LatexWalkerParseError,
    LatexWalkerEndOfStream,
    get_default_latex_context_db,
)
from pylatexenc import macrospec

PYLATEXENC_VERSION = pylatexenc.__version__

MATH_ENVS = {
    "equation",
    "equation*",
    "eqnarray",
    "eqnarray*",
    "align",
    "align*",
    "gather",
    "gather*",
    "flalign",
    "flalign*",
    "multline",
    "multline*",
    "alignat",
    "alignat*",
    "split",
    "math",
    "displaymath",
    "dmath",
    "subequations",
    "cases",
    "dcases",
    "bmatrix",
    "pmatrix",
    "vmatrix",
    "Bmatrix",
    "smallmatrix",
    "matrix",
    "IEEEeqnarray",
    "IEEEeqnarray*",
}
VERBATIM_ENVS = {"verbatim", "verbatim*", "lstlisting", "minted", "lstinputlisting"}
STRUCT_ENVS = {
    "figure",
    "figure*",
    "table",
    "table*",
    "tabular",
    "tabular*",
    "tabularx",
    "array",
    "tikzpicture",
    "algorithm",
    "algorithm2e",
    "algorithmic",
    "thebibliography",
}
TEXT_ENVS = {
    "document",
    "abstract",
    "itemize",
    "enumerate",
    "description",
    "theorem",
    "proposition",
    "lemma",
    "corollary",
    "definition",
    "conjecture",
    "remark",
    "proof",
    "thm",
    "prop",
    "lem",
    "cor",
    "conj",
    "rem",
    "defn",
    "center",
    "quote",
    "quotation",
    "minipage",
    "titlepage",
}

PROTECTED_MACROS = {
    "cite",
    "citet",
    "citep",
    "citealt",
    "citealp",
    "citeauthor",
    "citefullauthor",
    "citeyear",
    "citeyearpar",
    "Citet",
    "Citep",
    "Citealt",
    "Citealp",
    "Citeauthor",
    "citetext",
    "citenum",
    "defcitealias",
    "citetalias",
    "citepalias",
    "ref",
    "eqref",
    "autoref",
    "cref",
    "Cref",
    "pageref",
    "nameref",
    "label",
    "url",
    "includegraphics",
    "input",
    "include",
    "bibliography",
    "bibliographystyle",
    "documentclass",
    "usepackage",
    "RequirePackage",
    "newcommand",
    "renewcommand",
    "providecommand",
    "newenvironment",
    "renewenvironment",
    "def",
    "gdef",
    "edef",
    "xdef",
    "let",
    "newif",
    "setlength",
    "setcounter",
    "hspace",
    "vspace",
    "centering",
    "maketitle",
    "tableofcontents",
    "hypersetup",
    "definecolor",
    "colorlet",
    "usetikzlibrary",
    "lstset",
    "graphicspath",
}
# macro -> which arg positions hold translatable text (0-based in argnlist,
# -1 = last). Values are indices into nodeargd.argnlist.
TEXT_ARG_MACROS = {
    "section": -1,
    "subsection": -1,
    "subsubsection": -1,
    "paragraph": -1,
    "subparagraph": -1,
    "chapter": -1,
    "part": -1,
    "title": -1,
    "author": -1,
    "date": -1,
    "footnote": -1,
    "caption": -1,
    "emph": -1,
    "textbf": -1,
    "textit": -1,
    "textrm": -1,
    "textsc": -1,
    "textsf": -1,
    "textsl": -1,
    "texttt": -1,
    "textup": -1,
    "underline": -1,
    "thanks": -1,
    "item": -1,
    "keywords": -1,
}


def node_end(node):
    if getattr(node, "pos_end", None) is not None:
        return node.pos_end
    return node.pos + node.len


def node_verbatim(node, s):
    if node is None or getattr(node, "pos", None) is None:
        return ""
    return s[node.pos : node_end(node)]


def arg_nodes(node):
    if node.nodeargd is None or node.nodeargd.argnlist is None:
        return []
    return node.nodeargd.argnlist


def walk(nodelist, parent=None, container="top"):
    """yield (node, parent, container). container in
    {'top','group','env','math','marg'}"""
    for node in nodelist or []:
        if node is None:
            continue
        yield node, parent, container
        if isinstance(node, (LatexGroupNode, LatexEnvironmentNode, LatexMathNode)):
            c = {
                "LatexGroupNode": "group",
                "LatexEnvironmentNode": "env",
                "LatexMathNode": "math",
            }[node.__class__.__name__]
            for sub in walk(node.nodelist, node, c):
                yield sub
        if isinstance(node, (LatexMacroNode, LatexEnvironmentNode, LatexSpecialsNode)):
            for a in arg_nodes(node):
                if isinstance(a, LatexGroupNode):
                    yield a, node, "marg"
                    for sub in walk(a.nodelist, a, "marg"):
                        yield sub
                elif a is not None:
                    yield a, node, "marg"


def parse_string(s, tolerant_parsing=True, strict_braces=False, latex_context=None):
    w = LatexWalker(
        s,
        latex_context=latex_context,
        tolerant_parsing=tolerant_parsing,
        strict_braces=strict_braces,
    )
    return w.get_latex_nodes()


# ---------------------------------------------------------------------------
# 1. corpus parse robustness (subprocess per file for hard timeout)
# ---------------------------------------------------------------------------


def _parse_worker(path, q):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            s = f.read()
    except Exception as e:
        q.put({"ok": False, "error": "READ:" + repr(e)})
        return
    res = {"size": len(s)}
    for mode, kw in (
        ("tol", dict(tolerant_parsing=True)),
        ("strict", dict(tolerant_parsing=False, strict_braces=True)),
    ):
        t0 = time.perf_counter()
        try:
            nodelist, pos, nlen = parse_string(s, **kw)
            res[mode + "_ok"] = True
            res[mode + "_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            res[mode + "_nodes"] = len(nodelist)
            res[mode + "_nlen"] = nlen
        except Exception as e:
            res[mode + "_ok"] = False
            res[mode + "_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            res[mode + "_error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    q.put(res)


def run_parse(files, timeout=30):
    out = []
    ctx = mp.get_context("fork")
    for i, path in enumerate(files):
        q = ctx.Queue()
        p = ctx.Process(target=_parse_worker, args=(path, q))
        t0 = time.time()
        p.start()
        p.join(timeout)
        if p.is_alive():
            p.terminate()
            p.join()
            rec = {"ok": False, "error": "TIMEOUT>%ds" % timeout}
        else:
            try:
                rec = q.get(timeout=2)
            except Exception:
                rec = {"ok": False, "error": "CRASH exitcode=%s" % p.exitcode}
        rec["file"] = os.path.relpath(path, BENCH)
        rec["wall_ms"] = round((time.time() - t0) * 1000, 1)
        out.append(rec)
        print(
            "[%2d/%d] %-70s tol=%s strict=%s %sms"
            % (
                i + 1,
                len(files),
                rec["file"][-70:],
                rec.get("tol_ok"),
                rec.get("strict_ok"),
                rec.get("tol_ms"),
            )
        )
    return out


# ---------------------------------------------------------------------------
# 2. fixture assertions
# ---------------------------------------------------------------------------


def marker_spans(s):
    """Return list of (tag, start_pos) for each % @Tnn marker + EOF."""
    marks = [(m.group(1), m.end()) for m in re.finditer(r"% @(T\d+\w*)", s)]
    return marks


def nodes_in_span(nodelist, a, b):
    """top-level nodes overlapping [a,b)"""
    return [n for n in nodelist if n.pos is not None and node_end(n) > a and n.pos < b]


def span_of_construct(s, marks, tag, occurrence=None):
    """span from marker tag to next marker (or +1200 chars cap).
    occurrence=None -> last occurrence; int -> that occurrence."""
    hits = [i for i, (t, p) in enumerate(marks) if t == tag]
    if not hits:
        return None
    i = hits[occurrence if occurrence is not None else -1]
    end = marks[i + 1][1] if i + 1 < len(marks) else len(s)
    return marks[i][1], min(end, marks[i][1] + 1200)


def find_macros(nodelist, s, a, b, names=None):
    """all MacroNodes inside span (deep walk)"""
    found = []
    for n, parent, cont in walk(nodes_in_span(nodelist, a, b)):
        if isinstance(n, LatexMacroNode) and (names is None or n.macroname in names):
            found.append((n, cont, parent))
    return found


def check_fixtures():
    s = open(os.path.join(FIXTURES, "tricky.tex"), encoding="utf-8").read()
    nodelist, _, _ = parse_string(s)
    marks = marker_spans(s)
    checks = {}

    def span(tag):
        return span_of_construct(s, marks, tag)

    # T01: \be..\ee — macro-expanded math env. Expect: parser does NOT
    # expand; check what the usage line produces.
    a, b = span("T01")
    ns = nodes_in_span(nodelist, a, b)
    be_nodes = [
        n for n in ns if isinstance(n, LatexMacroNode) and n.macroname in ("be", "ee")
    ]
    math_nodes = [n for n in ns if isinstance(n, LatexMathNode)]
    leaked_chars = [
        n.chars
        for n in ns
        if isinstance(n, LatexCharsNode) and re.search(r"[A-Za-z}=^]", n.chars)
    ]
    checks["T01"] = {
        "desc": r"\be..\ee (macro expanding to math env)",
        "be_ee_parsed_as": ["MacroNode(%s)" % n.macroname for n in be_nodes],
        "math_node_found": bool(math_nodes),
        "math_content_leaks_as_chars": bool(leaked_chars),
        "leak_sample": [c.strip()[:40] for c in leaked_chars],
        "verdict": "FAIL-protect" if leaked_chars and not math_nodes else "ok",
        "note": "no expansion -> \\be is a bare MacroNode; body parses as text",
    }

    # T02: \dR — math macro used inside $..$ and in text
    a, b = span("T02")
    dR = find_macros(nodelist, s, a, b, {"dR"})
    checks["T02"] = {
        "desc": r"\dR = \mathbb{R} newcommand",
        "occurrences": [
            {
                "container": c,
                "in_math": (
                    p.parsing_state.in_math_mode
                    if getattr(p, "parsing_state", None)
                    else None
                ),
            }
            for n, c, p in dR
        ],
        "parsed_as": "MacroNode, no args (unknown-macro spec)",
        "verdict": "info",
    }

    # T03: \def\wt{\widetilde}
    a, b = span("T03")
    ns = nodes_in_span(nodelist, a, b)
    seq = []
    for n in ns[:8]:
        nm = n.__class__.__name__.replace("Latex", "").replace("Node", "")
        extra = getattr(n, "macroname", getattr(n, "chars", ""))
        seq.append("%s(%r)" % (nm, (extra or "")[:22]))
    checks["T03"] = {
        "desc": r"\def\wt{\widetilde} TeX primitive def",
        "node_sequence": seq,
        "def_has_args": None,
        "verdict": "info",
    }
    dfnodes = [n for n in ns if isinstance(n, LatexMacroNode) and n.macroname == "def"]
    if dfnodes:
        checks["T03"]["def_has_args"] = bool(arg_nodes(dfnodes[0]))

    # T04: natbib + ref family — keys must be inside macro args, never chars
    a, b = span("T04")
    cite_names = {
        "citep",
        "citet",
        "citealp",
        "citeauthor",
        "citeyear",
        "cite",
        "Citep",
        "Citet",
    }
    ref_names = {"ref", "eqref", "autoref", "cref", "pageref", "nameref", "label"}
    key_in_args = {}
    key_leaks = []
    for n, cont, parent in find_macros(nodelist, s, a, b, cite_names | ref_names):
        args = arg_nodes(n)
        last = args[-1] if args else None
        key = (
            last.nodelist[0].chars
            if last is not None
            and isinstance(last, LatexGroupNode)
            and last.nodelist
            and isinstance(last.nodelist[0], LatexCharsNode)
            else None
        )
        key_in_args[n.macroname] = {
            "argspec": getattr(n.nodeargd, "argspec", None),
            "n_args": len(args),
            "key": key,
            "opt_args": sum(1 for x in args[:-1] if x is not None),
        }
    # leaks: cite/ref keys appearing as CharsNode text or inside bare groups
    # (i.e., NOT inside a macro-arg subtree, where they are protected)
    keyre = re.compile(
        r"(vaswani2017|kingma2015|he2016|devlin2019|fig:x|eq:main|sec:a|thm:main)"
    )
    for n, parent, cont in walk(nodes_in_span(nodelist, a, b)):
        if cont == "marg":
            continue  # inside a macro argument -> protected
        if isinstance(n, LatexCharsNode) and n.chars and keyre.search(n.chars):
            key_leaks.append({"chars": n.chars.strip()[:50], "container": cont})
        if isinstance(n, LatexGroupNode):
            txt = "".join(getattr(x, "chars", "") for x in n.nodelist)
            if keyre.search(txt):
                key_leaks.append(
                    {"bare_group_chars": txt.strip()[:50], "container": cont}
                )
    checks["T04"] = {
        "desc": "natbib family + ref family",
        "macros": key_in_args,
        "key_leaks": key_leaks,
        "verdict": "ok" if not key_leaks else "FAIL-leak",
    }

    # T05: \section[Short]{Long}
    a, b = span("T05")
    secs = find_macros(nodelist, s, a, b, {"section"})
    info = []
    for n, cont, p in secs:
        args = arg_nodes(n)
        info.append(
            {
                "argspec": getattr(n.nodeargd, "argspec", None),
                "opt": (
                    args[1].nodelist[0].chars
                    if len(args) > 1
                    and isinstance(args[1], LatexGroupNode)
                    and args[1].nodelist
                    else None
                ),
                "mand": (
                    "".join(getattr(x, "chars", "") for x in args[-1].nodelist)
                    if args and isinstance(args[-1], LatexGroupNode)
                    else None
                ),
            }
        )
    checks["T05"] = {
        "desc": r"\section[Short]{Long}",
        "sections": info,
        "verdict": "ok"
        if info and info[0]["mand"] and "Long" in info[0]["mand"]
        else "FAIL",
    }

    # T06: verbatim / lstlisting with %
    a, b = span("T06")
    envs = [
        (n, c)
        for n, parent, c in walk(nodes_in_span(nodelist, a, b))
        if isinstance(n, LatexEnvironmentNode)
    ]
    einfo = []
    for n, c in envs:
        va = getattr(n.nodeargd, "verbatim_text", None)
        einfo.append(
            {
                "env": n.environmentname,
                "container": c,
                "verbatim_text": (va or "")[:60],
                "inner_types": [
                    x.__class__.__name__.replace("Latex", "")
                    for x in (n.nodelist or [])
                ][:10],
            }
        )
    checks["T06"] = {
        "desc": "verbatim & lstlisting containing %",
        "envs": einfo,
        "verdict": "info",
    }

    # T07: \url{..%..}  \verb|a%b|
    a, b = span("T07")
    urls = find_macros(nodelist, s, a, b, {"url"})
    verbs = find_macros(nodelist, s, a, b, {"verb"})
    uinfo = []
    for n, cont, p in urls:
        args = arg_nodes(n)
        g = args[-1] if args else None
        uinfo.append(
            {
                "node_len": node_end(n) - n.pos,
                "n_args": len(args),
                "group_chars": (
                    "".join(getattr(x, "chars", "")[:40] for x in g.nodelist[:3])
                    if isinstance(g, LatexGroupNode)
                    else None
                ),
                "group_end_minus_node_end": (node_end(g) - node_end(n))
                if g is not None
                else None,
            }
        )
    vinfo = [getattr(n.nodeargd, "verbatim_text", None) for n, c, p in verbs]
    checks["T07"] = {
        "desc": r"\url{..%20..} and \verb|a%b|",
        "url": uinfo,
        "verb_text": vinfo,
        "verdict": "info",
    }

    # T08: comment edge cases
    a, b = span("T08")
    comments = [
        (n.comment or "")[:60]
        for n, parent, c in walk(nodes_in_span(nodelist, a, b))
        if isinstance(n, LatexCommentNode)
    ]
    pct = find_macros(nodelist, s, a, b, {"%"})
    checks["T08"] = {
        "desc": "comment w/ unbalanced brace+math; \\% and \\\\%",
        "comments": comments,
        "escaped_pct_macros": len(pct),
        "verdict": "ok",
    }

    # T09: \author[1]{...\and...}
    a, b = span("T09")
    auth = find_macros(nodelist, s, a, b, {"author", "thanks", "and"})
    ainfo = []
    for n, cont, p in auth:
        args = arg_nodes(n)
        ainfo.append(
            {
                "macro": n.macroname,
                "arg_verbatims": [node_verbatim(x, s)[:40] for x in args],
                "container": cont,
            }
        )
    checks["T09"] = {
        "desc": r"\author[1]{..\thanks..\and..}",
        "macros": ainfo,
        "verdict": "info",
    }

    # T10: subequations/align/flalign
    a, b = span("T10")
    envs = [
        (n.environmentname, c, bool(n.parsing_state.in_math_mode))
        for n, parent, c in walk(nodes_in_span(nodelist, a, b))
        if isinstance(n, LatexEnvironmentNode)
    ]
    checks["T10"] = {
        "desc": "subequations/align/flalign",
        "envs": envs,
        "verdict": "info",
    }

    # T11: theorem[Main Result]
    a, b = span("T11")
    thm = [
        (
            n.environmentname,
            [node_verbatim(x, s)[:40] for x in arg_nodes(n)],
            [x.__class__.__name__.replace("Latex", "") for x in (n.nodelist or [])],
        )
        for n, parent, c in walk(nodes_in_span(nodelist, a, b))
        if isinstance(n, LatexEnvironmentNode)
    ]
    checks["T11"] = {"desc": "theorem[Main Result]", "envs": thm, "verdict": "info"}

    # T12: caption + footnote
    a, b = span("T12")
    caps = find_macros(nodelist, s, a, b, {"caption", "footnote"})
    cinfo = [
        {
            "macro": n.macroname,
            "args": [node_verbatim(x, s)[:50] for x in arg_nodes(n)],
            "container": c,
        }
        for n, c, p in caps
    ]
    checks["T12"] = {
        "desc": "caption containing footnote",
        "macros": cinfo,
        "verdict": "info",
    }

    # T13: \ifdraft...\else...\fi
    a, b = span("T13")
    ns = nodes_in_span(nodelist, a, b)
    ifs = [n.macroname for n in ns if isinstance(n, LatexMacroNode)]
    chars = [
        n.chars.strip()[:45]
        for n in ns
        if isinstance(n, LatexCharsNode) and n.chars.strip()
    ]
    checks["T13"] = {
        "desc": "conditional",
        "macros": ifs,
        "top_level_text": chars,
        "verdict": "info",
    }

    # T16: \NewDocumentCommand
    a, b = span("T16")
    ns = nodes_in_span(nodelist, a, b)
    checks["T16"] = {
        "desc": "xparse NewDocumentCommand",
        "seq": [
            n.__class__.__name__.replace("Latex", "")
            + "(%s)" % (getattr(n, "macroname", "") or getattr(n, "chars", "")[:20])
            for n in ns[:8]
        ],
        "verdict": "info",
    }

    # T17: \text inside math
    a, b = span("T17")
    maths = [n for n in nodes_in_span(nodelist, a, b) if isinstance(n, LatexMathNode)]
    textm = find_macros(nodelist, s, a, b, {"text"})
    checks["T17"] = {
        "desc": r"\text{} inside math",
        "math_nodes": len(maths),
        "text_macro": [
            {"container": c, "arg": [node_verbatim(x, s) for x in arg_nodes(n)]}
            for n, c, p in textm
        ],
        "verdict": "info",
    }

    # T18: figure+caption
    a, b = span("T18")
    caps = find_macros(nodelist, s, a, b, {"caption"})
    checks["T18"] = {
        "desc": "caption inside figure",
        "captions": [
            {"args": [node_verbatim(x, s)[:60] for x in arg_nodes(n)], "container": c}
            for n, c, p in caps
        ],
        "verdict": "info",
    }

    # T20: lists
    a, b = span("T20")
    items = find_macros(nodelist, s, a, b, {"item"})
    checks["T20"] = {
        "desc": "itemize/enumerate/description",
        "items": [
            {"opt": [node_verbatim(x, s) for x in arg_nodes(n)]} for n, c, p in items
        ],
        "verdict": "info",
    }

    # T23: emph/textbf/textit
    a, b = span("T23")
    fmt = find_macros(nodelist, s, a, b, {"emph", "textbf", "textit"})
    checks["T23"] = {
        "desc": "inline formatting",
        "macros": [
            {"name": n.macroname, "arg": [node_verbatim(x, s) for x in arg_nodes(n)]}
            for n, c, p in fmt
        ],
        "verdict": "ok" if all(arg_nodes(n) for n, c, p in fmt) else "FAIL",
    }

    # T22: \href{url}{text}
    a, b = span("T22")
    href = find_macros(nodelist, s, a, b, {"href"})
    hinfo = []
    for n, c, p in href:
        hinfo.append(
            {
                "n_args": len(arg_nodes(n)),
                "args": [node_verbatim(x, s)[:60] for x in arg_nodes(n)],
            }
        )
    # also check trailing groups after a 0-arg href
    checks["T22"] = {"desc": "href", "href": hinfo, "verdict": "info"}

    # T24: bibliography
    a, b = span("T24")
    bib = find_macros(nodelist, s, a, b, {"bibliography", "bibliographystyle"})
    checks["T24"] = {
        "desc": "bibliography",
        "macros": [
            {"name": n.macroname, "args": [node_verbatim(x, s) for x in arg_nodes(n)]}
            for n, c, p in bib
        ],
        "verdict": "info",
    }

    # T25: makeatletter
    a, b = span("T25")
    ns = nodes_in_span(nodelist, a, b)
    checks["T25"] = {
        "desc": "makeatletter block",
        "seq": [
            n.__class__.__name__.replace("Latex", "")
            + "(%s)" % (getattr(n, "macroname", "") or getattr(n, "chars", "")[:24])
            for n in ns[:10]
        ],
        "verdict": "info",
    }

    # T27: accents
    a, b = span("T27")
    acc = find_macros(nodelist, s, a, b, {"'", '"', "~", "c", "u", "v"})
    checks["T27"] = {
        "desc": "accent commands",
        "macros": [
            {"name": n.macroname, "args": [node_verbatim(x, s) for x in arg_nodes(n)]}
            for n, c, p in acc
        ],
        "verdict": "info",
    }

    # T19 abstract, T21 includegraphics, T26 \[ \(, T29 footnote
    for tag, names in (
        ("T19", None),
        ("T21", {"includegraphics"}),
        ("T26", None),
        ("T29", {"footnote"}),
    ):
        sp = span(tag)
        if not sp:
            continue
        a, b = sp
        ns = nodes_in_span(nodelist, a, b)
        checks[tag] = {
            "desc": tag,
            "top_seq": [
                n.__class__.__name__.replace("Latex", "")
                + "(%s)"
                % (
                    getattr(n, "macroname", getattr(n, "environmentname", ""))
                    or (getattr(n, "chars", "") or "")[:24]
                )
                for n in ns[:8]
            ],
            "verdict": "info",
        }

    # --- tricky-209 ---
    s2 = open(os.path.join(FIXTURES, "tricky-209.tex"), encoding="utf-8").read()
    try:
        nl2, _, _ = parse_string(s2)
        seq = [
            n.__class__.__name__.replace("Latex", "")
            + "(%s)"
            % (
                getattr(n, "macroname", "")
                or getattr(n, "environmentname", "")
                or (getattr(n, "chars", "") or "")[:20]
            )
            for n in nl2[:20]
        ]
        checks["T209"] = {
            "desc": "LaTeX2.09 \\documentstyle + \\def",
            "ok": True,
            "top_seq": seq,
            "verdict": "info",
        }
    except Exception as e:
        checks["T209"] = {"ok": False, "error": repr(e)[:200], "verdict": "FAIL"}

    # --- tricky-multi ---
    s3 = open(
        os.path.join(FIXTURES, "tricky-multi", "main.tex"), encoding="utf-8"
    ).read()
    nl3, _, _ = parse_string(s3)
    inputs = [
        (n.macroname, [node_verbatim(x, s3) for x in arg_nodes(n)])
        for n, p, c in walk(nl3)
        if isinstance(n, LatexMacroNode) and n.macroname in ("input", "include")
    ]
    commented = [n.comment for n, p, c in walk(nl3) if isinstance(n, LatexCommentNode)]
    checks["T14"] = {
        "desc": r"\input/\include recursion + commented \input",
        "input_macros_found": inputs,
        "expands_files": False,
        "commented_input_is_comment": any(
            "input{sub/commented-out}" in (c or "") for c in commented
        ),
        "verdict": "info",
    }

    return checks


# ---------------------------------------------------------------------------
# 3. round-trip via pos/len
# ---------------------------------------------------------------------------


def check_roundtrip(path):
    s = open(path, encoding="utf-8", errors="replace").read()
    rec = {"file": os.path.relpath(path, BENCH), "size": len(s)}
    try:
        nodelist, pos, nlen = parse_string(s)
    except Exception as e:
        rec["status"] = "parse_error"
        rec["error"] = repr(e)[:200]
        return rec
    rebuilt = "".join(node_verbatim(n, s) for n in nodelist)
    covered = sum(node_end(n) - n.pos for n in nodelist)
    rec["top_node_bytes"] = covered
    # contiguity check
    gaps = []
    cur = nodelist[0].pos if nodelist else 0
    for n in nodelist:
        if n.pos > cur:
            gaps.append((cur, s[cur : n.pos][:30]))
        cur = max(cur, node_end(n))
    if cur < len(s):
        gaps.append((cur, s[cur : cur + 30]))
    rec["gaps"] = gaps[:5]
    if rebuilt == s:
        rec["status"] = "identical"
    elif rebuilt.strip() == s.strip():
        rec["status"] = "normalized"
    else:
        # first divergence
        i = next(
            (k for k in range(min(len(rebuilt), len(s))) if rebuilt[k] != s[k]),
            min(len(rebuilt), len(s)),
        )
        rec["status"] = "diverged"
        rec["first_diff_pos"] = i
        rec["context"] = {
            "orig": s[max(0, i - 30) : i + 30],
            "rebuilt": rebuilt[max(0, i - 30) : i + 30],
        }
    return rec


# ---------------------------------------------------------------------------
# 4. translatable-block extraction + leak rate
# ---------------------------------------------------------------------------


class Extractor(object):
    r"""paragraph-level translatable block extraction on top of pylatexenc AST.

    Produces blocks: list of {'text': str-with-placeholders, 'protected': {...},
    'pos': (a,b)}. Leak check = literal $, \cite, \ref, \begin{ inside text.
    """

    def __init__(self, s):
        self.s = s
        self.blocks = []
        self.cur = []
        self.protected = {}
        self.counter = 0

    def protect(self, node):
        self.counter += 1
        ph = "[[P%d]]" % self.counter
        self.protected[ph] = node_verbatim(node, self.s)
        self.cur.append(ph)

    def flush(self):
        text = "".join(self.cur)
        if text.strip():
            self.blocks.append(text)
        self.cur = []

    def emit_text(self, txt):
        parts = re.split(r"(\n\s*\n)", txt)
        for i, part in enumerate(parts):
            if i % 2 == 1:
                self.flush()
            elif part:
                self.cur.append(part)

    def process(self, nodelist, container="top"):
        for n in nodelist or []:
            if n is None:
                continue
            if isinstance(n, LatexCharsNode):
                self.emit_text(n.chars)
            elif isinstance(n, LatexCommentNode):
                # comments are not translated; they stay in the source
                # (reconstruction works on pos intervals anyway)
                pass
            elif isinstance(n, LatexMathNode):
                self.protect(n)
            elif isinstance(n, LatexGroupNode):
                self.cur.append(n.delimiters[0])
                self.process(n.nodelist, "group")
                self.cur.append(n.delimiters[1])
            elif isinstance(n, LatexEnvironmentNode):
                self.handle_env(n)
            elif isinstance(n, LatexMacroNode):
                self.handle_macro(n)
            elif isinstance(n, LatexSpecialsNode):
                self.cur.append(node_verbatim(n, self.s))
            else:
                self.cur.append(node_verbatim(n, self.s))

    def handle_env(self, n):
        name = n.environmentname
        if name in MATH_ENVS or name in VERBATIM_ENVS or name in STRUCT_ENVS:
            if name in ("figure", "figure*", "table", "table*"):
                self.flush()
                self.protect(n)  # protect whole float incl. caption?
                # alternative implemented below: scan captions only
                return
            self.flush()
            self.protect(n)
            return
        if name in TEXT_ENVS or True:
            # translatable env: keep \begin..\end markers out, process body
            self.flush()
            self.process(n.nodelist, "env")
            self.flush()

    def handle_macro(self, n):
        name = n.macroname
        if name in PROTECTED_MACROS:
            self.protect(n)
            return
        if name in TEXT_ARG_MACROS:
            args = arg_nodes(n)
            if args:
                # protect macro head up to last arg start; translate last arg
                last = args[-1]
                head = (
                    self.s[n.pos : last.pos]
                    if last is not None
                    else node_verbatim(n, self.s)
                )
                self.protect_raw(head)
                for a in args[:-1]:
                    if a is not None:
                        self.protect_raw(node_verbatim(a, self.s))
                if last is not None:
                    if isinstance(last, LatexGroupNode):
                        self.cur.append(last.delimiters[0])
                        self.process(last.nodelist, "marg")
                        self.cur.append(last.delimiters[1])
                    else:
                        self.cur.append(node_verbatim(last, self.s))
                return
            self.protect(n)
            return
        if name == "href":
            args = arg_nodes(n)
            if len(args) >= 2:
                self.protect_raw(node_verbatim(args[0], self.s))
                last = args[-1]
                if isinstance(last, LatexGroupNode):
                    self.process(last.nodelist, "marg")
                return
            self.protect(n)
            return
        if name == "item":
            self.flush()
            self.cur.append(node_verbatim(n, self.s))
            return
        # unknown macro: protect whole node (verbatim) — conservative
        self.protect(n)

    def protect_raw(self, text):
        self.counter += 1
        ph = "[[P%d]]" % self.counter
        self.protected[ph] = text
        self.cur.append(ph)


LEAK_RE = re.compile(r"(\$|\\cite\w*\{|\\ref\{|\\eqref\{|\\begin\{)")


def run_extract(files):
    out = []
    for path in files:
        s = open(path, encoding="utf-8", errors="replace").read()
        rec = {"file": os.path.relpath(path, BENCH)}
        try:
            nodelist, _, _ = parse_string(s)
        except Exception as e:
            rec["error"] = repr(e)[:150]
            out.append(rec)
            continue
        ex = Extractor(s)
        ex.process(nodelist)
        ex.flush()
        leaks = [b[:80] for b in ex.blocks if LEAK_RE.search(b)]
        rec["n_blocks"] = len(ex.blocks)
        rec["n_leak"] = len(leaks)
        rec["leak_rate"] = round(len(leaks) / max(1, len(ex.blocks)), 3)
        rec["leak_samples"] = leaks[:3]
        rec["n_protected"] = len(ex.protected)
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# 5. \newcommand "half-expansion" feasibility
# ---------------------------------------------------------------------------


def check_newcommand():
    res = {}
    s = (
        r"\newcommand{\vect}[1]{\mathbf{#1}}" + "\n"
        r"\newcommand{\dR}{\mathbb{R}}" + "\n"
        r"After defs: \vect{v} and \dR{} used in text." + "\n"
    )
    nodelist, _, _ = parse_string(s)
    w = LatexWalker(s)
    ctx = w.default_parsing_state.latex_context

    def _is_registered(name):
        spec = ctx.get_macro_spec(name)
        # v3 returns a placeholder unknown-macro spec (macroname='')
        return bool(spec is not None and getattr(spec, "macroname", "") == name)

    res["vect_registered_after_parse"] = _is_registered("vect")
    res["dR_registered_after_parse"] = _is_registered("dR")
    vect = [
        n for n in nodelist if isinstance(n, LatexMacroNode) and n.macroname == "vect"
    ]
    res["vect_node"] = {
        "n_args": len(arg_nodes(vect[0])) if vect else None,
        "verbatim": node_verbatim(vect[0], s) if vect else None,
    }
    # what follows the 0-arg \vect: a bare group
    nl_list = list(nodelist)
    i = nl_list.index(vect[0]) if vect else -1
    res["node_after_vect"] = (
        nl_list[i + 1].__class__.__name__ if i >= 0 and i + 1 < len(nl_list) else None
    )

    # --- can we wire it ourselves? custom args parser returning
    # new_parsing_state (v2.x hook, present but unused by defaults)
    class NewCommandArgsParser(macrospec.MacroStandardArgsParser):
        def parse_args(self, w, pos, parsing_state=None):
            (argd, apos, alen) = super().parse_args(w, pos, parsing_state=parsing_state)
            try:
                name_node = argd.argnlist[1]
                if isinstance(name_node, LatexGroupNode):
                    inner = name_node.nodelist[0] if name_node.nodelist else None
                else:
                    inner = name_node
                macname = getattr(inner, "macroname", None) or getattr(
                    inner, "chars", ""
                ).strip("\\")
                nargs = 0
                if argd.argnlist[2] is not None:
                    opttxt = "".join(
                        getattr(x, "chars", "") for x in argd.argnlist[2].nodelist
                    )
                    m = re.match(r"\s*(\d)", opttxt)
                    nargs = int(m.group(1)) if m else 0
                spec = macrospec.MacroSpec(
                    macname, args_parser=macrospec.MacroStandardArgsParser("{" * nargs)
                )
                newctx = parsing_state.latex_context.filter_context()
                newctx.add_context_category(
                    "user:" + macname, macros=[spec], prepend=True
                )
                newps = parsing_state.sub_context(latex_context=newctx)
                return (argd, apos, alen, {"new_parsing_state": newps})
            except Exception as e:
                import sys as _s

                print("hook exc", e, file=_s.stderr)
                return (argd, apos, alen, {})

    ctx = get_default_latex_context_db()
    ctx.add_context_category(
        "newcmd-hook",
        prepend=True,
        macros=[
            macrospec.MacroSpec("newcommand", args_parser=NewCommandArgsParser("*{[[{"))
        ],
    )
    nodelist2, _, _ = parse_string(s, latex_context=ctx)
    vect2 = [
        n for n in nodelist2 if isinstance(n, LatexMacroNode) and n.macroname == "vect"
    ]
    res["custom_hook"] = {
        "vect_n_args": len(arg_nodes(vect2[0])) if vect2 else None,
        "works": bool(vect2 and len(arg_nodes(vect2[0])) == 1),
        "note": "custom args parser returns new_parsing_state that extends "
        "latex_context; \\vect{v} then parses v as its argument",
    }
    return res


# ---------------------------------------------------------------------------
# damage scan: catastrophic swallow signatures
# ---------------------------------------------------------------------------


def run_damage(files):
    """Per-file anomaly scan:
    - envs inside macro-arg/group subtrees spanning >2000B or to EOF
      (fake env from \\begin inside \\newcommand/\\def bodies)
    - group nodes ending at EOF without their closing brace
      (comment-eats-delimiter, e.g. % inside \\href{}/\\url{})
    """
    out = []
    for path in files:
        s = open(path, encoding="utf-8", errors="replace").read()
        rec = {"file": os.path.relpath(path, BENCH), "size": len(s)}
        try:
            nl, _, _ = parse_string(s)
        except Exception as e:
            rec["error"] = repr(e)[:150]
            out.append(rec)
            continue
        dmg = []
        for n, p, c in walk(nl):
            end = node_end(n)
            if isinstance(n, LatexEnvironmentNode) and c in ("marg", "group"):
                if n.len > 2000 or end >= len(s) - 2:
                    dmg.append(
                        {
                            "kind": "env_in_arg",
                            "env": n.environmentname,
                            "pos": n.pos,
                            "len": end - n.pos,
                            "pct": round(100 * (end - n.pos) / len(s), 1),
                        }
                    )
            if (
                isinstance(n, LatexGroupNode)
                and end >= len(s) - 1
                and not s.rstrip().endswith("}")
            ):
                if end - n.pos > 200:
                    dmg.append(
                        {
                            "kind": "group_to_eof",
                            "pos": n.pos,
                            "len": end - n.pos,
                            "pct": round(100 * (end - n.pos) / len(s), 1),
                            "head": s[n.pos : n.pos + 50],
                        }
                    )
        if dmg:
            rec["damage"] = dmg
        out.append(rec)
    return out


# ---------------------------------------------------------------------------


def corpus_files():
    fs = []
    for root, dirs, names in os.walk(CORPUS):
        dirs.sort()
        for nm in sorted(names):
            if nm.endswith(".tex"):
                fs.append(os.path.join(root, nm))
    return fs


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    files = corpus_files()
    result = {
        "library": "pylatexenc",
        "version": PYLATEXENC_VERSION,
        "python": sys.version.split()[0],
    }
    outname = os.environ.get("BENCH_OUT", "pylatexenc-parse.json")
    outpath = os.path.join(RESULTS, outname)

    if mode in ("parse", "all"):
        result["parse"] = run_parse(files)
        with open(outpath, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        ok = sum(1 for r in result["parse"] if r.get("tol_ok"))
        print("tolerant: %d/%d ok" % (ok, len(files)))

    if mode in ("fixtures", "all"):
        result["fixtures"] = check_fixtures()
        for k, v in result["fixtures"].items():
            print(k, "=>", v.get("verdict"), "|", v.get("desc"))

    if mode in ("roundtrip", "all"):
        rt = []
        for f in files:
            r = check_roundtrip(f)
            rt.append(r)
            if r["status"] != "identical":
                print(
                    "RT %-60s %s gaps=%s"
                    % (r["file"][-60:], r["status"], r.get("gaps"))
                )
        result["roundtrip"] = rt
        from collections import Counter

        print(Counter(r["status"] for r in rt))

    if mode in ("extract", "all"):
        result["extract"] = run_extract(files)
        tot = sum(r.get("n_blocks", 0) for r in result["extract"])
        lk = sum(r.get("n_leak", 0) for r in result["extract"])
        print("blocks=%d leaks=%d rate=%.3f" % (tot, lk, lk / max(1, tot)))

    if mode in ("damage", "all"):
        result["damage"] = run_damage(files)
        for r in result["damage"]:
            if "damage" in r:
                print("DAMAGE", r["file"], r["damage"][:2])

    if mode in ("newcmd", "all"):
        result["newcommand"] = check_newcommand()
        print(json.dumps(result["newcommand"], indent=1))

    if mode == "all":
        with open(outpath, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        print("wrote", outpath)


if __name__ == "__main__":
    main()
