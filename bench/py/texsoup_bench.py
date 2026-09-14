#!/usr/bin/env python
"""TexSoup benchmark — PROTOCOL.md 4 项评测.

Outputs:
  results/texsoup-parse.json   corpus 逐文件结果
  stdout                       fixtures 断言表 + round-trip + 泄漏率汇总
"""

import json, os, signal, sys, time, traceback
from collections import Counter

import TexSoup
from TexSoup.data import (
    TexExpr,
    TexNode,
    TexNamedEnv,
    TexUnNamedEnv,
    TexCmd,
    TexText,
    TexArgs,
    TexMathModeEnv,
    TexDisplayMathModeEnv,
    TexMathEnv,
    TexDisplayMathEnv,
    BraceGroup,
    BracketGroup,
)
from TexSoup.utils import TC
from TexSoup.tokens import MATH_ENV_NAMES, SKIP_ENV_NAMES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # bench/
CORPUS = os.path.join(ROOT, "corpus")
FIXTURES = os.path.join(ROOT, "fixtures")
RESULTS = os.path.join(ROOT, "results")
TIMEOUT = 30


class TimeoutError_(Exception):
    pass


def _alarm(signum, frame):
    raise TimeoutError_()


signal.signal(signal.SIGALRM, _alarm)


def corpus_files():
    out = []
    for dirpath, _, files in os.walk(CORPUS):
        for f in sorted(files):
            if f.endswith(".tex"):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


def timed_parse(src, tolerance):
    t0 = time.perf_counter()
    signal.alarm(TIMEOUT)
    try:
        soup = TexSoup.TexSoup(src, tolerance=tolerance)
        return soup, time.perf_counter() - t0, None
    except Exception as e:
        return None, time.perf_counter() - t0, e
    finally:
        signal.alarm(0)


# ---------------------------------------------------------------------------
# 遍历辅助
# ---------------------------------------------------------------------------


def iter_exprs(expr):
    """Depth-first yield of every TexExpr (incl. args content)."""
    yield expr
    for a in getattr(expr, "args", []) or []:
        yield from iter_exprs(a)
    for c in getattr(expr, "contents", []) or []:
        if isinstance(c, str):
            continue
        yield from iter_exprs(c)


def node_kind(node):
    e = node.expr if isinstance(node, TexNode) else node
    if isinstance(e, TexNamedEnv):
        return "env:%s" % e.name
    if isinstance(e, (TexMathModeEnv, TexDisplayMathModeEnv)):
        return "math:inline" if isinstance(e, TexMathModeEnv) else "math:display"
    if isinstance(e, (TexMathEnv, TexDisplayMathEnv)):
        return "math:paren" if isinstance(e, TexMathEnv) else "math:bracket"
    if isinstance(e, TexUnNamedEnv):
        return "env:%s" % e.name
    if isinstance(e, TexCmd):
        return "cmd:%s" % e.name
    if isinstance(e, BraceGroup):
        return "group:{}"
    if isinstance(e, BracketGroup):
        return "group:[]"
    if isinstance(e, TexText):
        toks = getattr(e, "_contents", None) or [e]
        cat = getattr(toks[0], "category", None)
        if cat == TC.Comment:
            return "comment"
        return "text"
    return type(e).__name__


def is_math_node(node):
    e = node.expr if isinstance(node, TexNode) else node
    if isinstance(
        e, (TexMathModeEnv, TexDisplayMathModeEnv, TexMathEnv, TexDisplayMathEnv)
    ):
        return True
    return isinstance(e, TexNamedEnv) and e.name in MATH_ENV_NAMES


def text_of_arg(arg):
    if isinstance(arg, (BraceGroup, BracketGroup)):
        return "".join(str(c) for c in arg.contents)
    return str(arg)


# ---------------------------------------------------------------------------
# 可译块提取 (protocol §4)
# ---------------------------------------------------------------------------

# 整族不译命令: 参数与命令本身都不进可译块
PROTECTED_CMDS = set(
    """
    citep citet citealp citeauthor citeyear cite citealt citealp* citep*
    citet* citeyearpar nocite
    ref eqref autoref cref Cref pageref nameref label vref fref
    url path includegraphics input include includeonly
    documentclass documentstyle usepackage RequirePackage LoadClass
    bibliography bibliographystyle addbibresource
    newcommand renewcommand providecommand DeclareRobustCommand
    NewDocumentCommand RenewDocumentCommand DeclareDocumentCommand
    newenvironment renewenvironment newtheorem def edef gdef xdef let
    makeatletter makeatother newif ifdraft fi else drafttrue draftfalse
    begin end item[never] setcounter addtocounter setlength
    hspace vspace vspace* hspace* newline linebreak pagebreak
    noindent indent centering hline cline rule
    usetikzlibrary DeclareMathOperator DeclareMathOperator*
    DeclareUnicodeCharacter pdfoutput jobname
    tableofcontents listoffigures listoftables maketitle title author
    date thanks and footnotemark footnotetext affiliation institute
    hypersetup definecolor colorlet graphicspath
    selectlanguage setmainfont mathversion
    captionof subcaptionbox phantomsubcaption
    printbibliography medskip bigskip smallskip
    columnwidth textwidth textheight linewidth oddsidemargin
    newcounter newlength newsavebox newenvironment
    ensuremath mathds mathbb mathbf mathrm mathit mathsf mathtt mathcal
    mathop operatorname limits nolimits displaylimits
    """.split()
)

# 内部文本可译的 inline 命令 (取最后一个 brace 参数或全部文本)
INLINE_TEXT_CMDS = set(
    """
    emph textbf textit textsl textsc texttt textrm textsf textmd textup
    underline uppercas e lowercase text footnote footnotemark
    caption subcaption paragraph subparagraph
    section subsection subsubsection chapter part
    title author thanks
    """.split()
)

# 结构内文本可译的环境
TRANSLATABLE_ENVS = set(
    """
    document abstract itemize enumerate description theorem proof
    lemma corollary proposition definition remark example figure table
    quote quotation verse center flushleft flushright minipage
    subequations comment
    """.split()
)

VERBATIM_ENVS = set(SKIP_ENV_NAMES) | {"minted", "lstlisting*"}


def extract_blocks(soup, src=""):
    """Return list of translatable blocks.

    TexText 的 token category 在树中已丢失 (TexText.__init__ 做 str() 降级),
    注释只能用 position 回查: src[position] == '%' => 注释.
    """
    blocks = []

    def is_comment_expr(e):
        p = getattr(e, "position", -1)
        return p >= 0 and p < len(src) and src[p] == "%"

    def walk(node, in_math, in_protected, acc):
        e = node.expr if isinstance(node, TexNode) else node
        kind = node_kind(node)

        if kind == "comment" or (kind == "text" and is_comment_expr(e)):
            return
        if is_math_node(node):
            return  # 数学整体保护, 不进可译块
        if isinstance(e, TexNamedEnv):
            if e.name in VERBATIM_ENVS:
                return
            for c in e.contents:
                if isinstance(c, TexExpr):
                    walk(TexNode(c), in_math, in_protected, acc)
                elif isinstance(c, str):
                    acc.append(c)
            return
        if isinstance(e, TexUnNamedEnv):
            # [tex] root or unnamed non-math
            for c in e.contents:
                if isinstance(c, TexExpr):
                    walk(TexNode(c), in_math, in_protected, acc)
                elif isinstance(c, str):
                    acc.append(c)
            return
        if isinstance(e, TexCmd):
            name = e.name
            if name in PROTECTED_CMDS:
                return
            if name in INLINE_TEXT_CMDS:
                # href: arg0 保护 arg1 可译
                if name == "href":
                    pass
                for a in e.args:
                    if isinstance(a, (BraceGroup,)):
                        walk_arg(a, acc)
                return
            if name == "href":
                if len(e.args) >= 2:
                    walk_arg(e.args[-1], acc)
                return
            if name == "includegraphics":
                return
            if name == "item":
                # \item 标记本身不译, 内容可译
                for c in e.contents:
                    if isinstance(c, TexExpr):
                        walk(TexNode(c), in_math, in_protected, acc)
                    elif isinstance(c, str):
                        acc.append(c)
                return
            # 未知命令: 源码并入块文本 (潜在泄漏)
            acc.append(str(e))
            return
        if kind == "text":
            acc.append(str(e))
            return
        if isinstance(e, (BraceGroup, BracketGroup)):
            walk_arg(e, acc)
            return
        # fallback: treat as text
        acc.append(str(e))

    def walk_arg(arg, acc):
        for c in arg.contents:
            if isinstance(c, TexExpr):
                walk(TexNode(c), False, False, acc)
            elif isinstance(c, str):
                acc.append(c)

    # top level: each child of soup's [tex] root that yields text becomes
    # part of the current paragraph block; split on blank lines
    cur = []

    def flush():
        text = "".join(cur)
        if text.strip():
            blocks.append(text)
        cur.clear()

    def flush_on_para(s):
        # split block at paragraph boundaries inside a text run
        parts = s.split("\n\n")
        for i, p in enumerate(parts):
            if i:
                flush()
            cur.append(p)

    root_children = []
    for c in soup.expr.contents:
        root_children.append(c)

    for c in root_children:
        if isinstance(c, TexExpr):
            acc = []
            walk(TexNode(c), False, False, acc)
            text = "".join(acc)
            flush_on_para(text)
        elif isinstance(c, str):
            cur.append(c)

    flush()
    return blocks


LEAK_MARKERS = ("$", r"\cite", r"\ref", r"\begin{")


def leak_stats(blocks):
    n = 0
    n_cmd = 0
    leaks = []
    import re

    for b in blocks:
        if any(m in b for m in LEAK_MARKERS):
            n += 1
            leaks.append(b[:90])
        if re.search(r"\\[a-zA-Z@]+", b):
            n_cmd += 1
    return n, n_cmd, leaks


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def run_fixture_assertions():
    src_full = open(os.path.join(FIXTURES, "tricky.tex")).read()
    results = []

    soup0, _, err0 = timed_parse(src_full, 0)
    soup_full, _, err1 = timed_parse(src_full, 1)
    results.append(("parse t=0", err0 is None, str(err0)[:120] if err0 else ""))
    results.append(("parse t=1", err1 is None, str(err1)[:120] if err1 else ""))

    # T25 单独测: \makeatletter 区中的 \@ifnextchar[ 是 t=0 崩溃点
    mini = (
        r"\documentclass{article}" + "\n"
        r"\makeatletter" + "\n"
        r"\newcommand{\secretmacro}{\@ifnextchar[{\@with}{\@without}}" + "\n"
        r"\makeatother" + "\n"
        r"\begin{document}text\end{document}"
    )
    _, _, err25 = timed_parse(mini, 0)
    results.append(
        (
            "T25",
            err25 is None,
            ("t=0 崩于 \\@ifnextchar[: %s" % str(err25)[:80]) if err25 else "ok",
        )
    )

    # T06 单独测: 单行 verbatim 含 % 使 \end 被注释吞掉 — t=0/t=1 均不可恢复
    for nm, sub in (
        ("T06-verbatim-oneline%", "\\begin{verbatim}100% real\\end{verbatim}"),
        ("T06-verbatim-multiline%", "\\begin{verbatim}\n100% real\n\\end{verbatim}"),
        ("T06-lst-oneline%", "\\begin{lstlisting}x%y\\end{lstlisting}"),
    ):
        ok_any = False
        errs = []
        for tol in (0, 1):
            _, _, e = timed_parse(sub, tol)
            errs.append(e)
            ok_any = ok_any or e is None
        results.append(
            (nm, ok_any, "ok" if ok_any else "t0/t1 均 FAIL: %s" % str(errs[0])[:70])
        )

    # 其余断言在移除 \makeatletter 区+单行 verbatim 的变体上做
    # (t=1 的树结构已被吞arg破坏; 单行 verbatim % 任何 tolerance 都崩)
    src = src_full.replace(
        r"""\makeatletter
\newcommand{\secretmacro}{\@ifnextchar[{\@with}{\@without}}
\makeatother""",
        "",
    ).replace(
        r"\begin{verbatim}100% real data\end{verbatim}",
        "\\begin{verbatim}\n100% real data\n\\end{verbatim}",
    )
    soup, _, err_v = timed_parse(src, 0)
    results.append(
        (
            "parse variant(no T25/T06) t=0",
            err_v is None,
            str(err_v)[:120] if err_v else "",
        )
    )

    if soup is None:
        return None, src, results

    def find_cmd(name):
        return [n for n in soup.find_all(name)]

    def check(tid, ok, note=""):
        results.append((tid, bool(ok), note))

    # T01: \be..\ee — 无宏展开, 内容应为普通文本(泄漏) — 记录 TexSoup 实际行为
    be = find_cmd("be")
    ee = find_cmd("ee")
    eq_envs = [n for n in soup.descendants if is_math_node(n) and "wt" in str(n)]
    leak_region = False
    if be:
        # 检查 \be 与 \ee 之间是否产生了可译文本 (= (M^2) 之类)
        blocks = extract_blocks(soup, src)
        leak_region = any("(M^2)" in b or "\\wt" in b for b in blocks)
    check(
        "T01",
        leak_region,
        "\\be..\\ee 未展开: 内容%s泄漏为可译文本" % ("" if leak_region else "未"),
    )
    # T02: \dR 数学内被保护, 文本中残留为 cmd
    dr_in_math = any("dR" in str(n) for n in soup.descendants if is_math_node(n))
    check(
        "T02", dr_in_math, "$x \\in \\dR$ 内 dR=%s; 文本中 \\dR 为裸命令" % dr_in_math
    )
    # T03: \def 解析为 cmd + args
    defs = find_cmd("def")
    ok_def = bool(defs) and str(defs[0].args[0]) == "\\wt" if defs else False
    check("T03", ok_def, "def args=%s" % (str(defs[0].args)[:60] if defs else "none"))
    # T04: natbib 全族
    fam = {}
    for c in (
        "citep",
        "citet",
        "citealp",
        "citeauthor",
        "citeyear",
        "ref",
        "eqref",
        "autoref",
        "cref",
        "pageref",
        "nameref",
        "label",
    ):
        fam[c] = bool(find_cmd(c))
    missing = [c for c, v in fam.items() if not v]
    check("T04", not missing, "missing=%s" % missing)
    # T05: section[Short]{Long}
    sec = find_cmd("section")
    ok5 = False
    if sec:
        a = sec[0].args
        ok5 = len(a) >= 2 and "Short" in str(a[0]) and "Long Section Title" in str(a[1])
    check("T05", ok5, "args=%s" % (str(sec[0].args)[:70] if sec else "none"))
    # T06: verbatim/lstlisting 单行 % 保护
    verb = [n for n in soup.descendants if node_kind(n) == "env:verbatim"]
    lst = [n for n in soup.descendants if node_kind(n) == "env:lstlisting"]
    ok6 = (
        verb
        and "100% real data" in str(verb[0])
        and lst
        and "code%with%percent" in str(lst[0])
    )
    check("T06", bool(ok6), "verbatim=%d lstlisting=%d" % (len(verb), len(lst)))
    # T07: url 原样 + verb
    url = find_cmd("url")
    verb_cmd = find_cmd("verb")
    ok7 = url and "a%20b%20c" in str(url[0]) and verb_cmd and "a%b" in str(verb_cmd[0])
    check(
        "T07",
        bool(ok7),
        "url=%s verb=%s"
        % (
            str(url[0])[:40] if url else "-",
            str(verb_cmd[0])[:40] if verb_cmd else "-",
        ),
    )
    # T08: 注释在树中 (category 已丢, 用 position 回查 src[pos]=='%'), \% 保留
    comments = [
        n
        for n in soup.descendants
        if node_kind(n) == "text"
        and 0 <= getattr(n, "position", -1) < len(src)
        and src[n.position] == "%"
    ]
    esc = "\\%" in str(soup)
    check(
        "T08",
        len(comments) > 0 and esc,
        "comments(经 position 探测)=%d, \\%% preserved=%s" % (len(comments), esc),
    )
    # T09: author[1]{...}
    auth = find_cmd("author")
    ok9 = auth and len(auth[0].args) >= 2 and "Alice" in str(auth[0].args[-1])
    check("T09", bool(ok9), "author args=%d" % (len(auth[0].args) if auth else 0))
    # T10: subequations/align/flalign
    ok10 = all(
        [n for n in soup.descendants if node_kind(n) == "env:" + e]
        for e in ("subequations", "align", "flalign")
    )
    check("T10", bool(ok10), "math envs present")
    # T11: theorem env
    thm = [n for n in soup.descendants if node_kind(n) == "env:theorem"]
    ok11 = thm and "statement holds" in str(thm[0]) and "Main Result" in str(thm[0])
    check("T11", bool(ok11), "theorem env=%d" % len(thm))
    # T12: caption 内 footnote
    fn = find_cmd("footnote")
    ok12 = fn and any("computed by hand" in str(n) for n in fn)
    check("T12", bool(ok12), "footnote=%d" % len(fn))
    # T13: ifdraft 不崩
    ifd = find_cmd("ifdraft")
    blocks = extract_blocks(soup, src)
    ok13 = (
        bool(ifd)
        and any("Draft mode" in b for b in blocks)
        and any("Final mode" in b for b in blocks)
    )
    check("T13", ok13, "ifdraft=%d both branches extracted=%s" % (len(ifd), ok13))
    # T14: \input 是否展开 — TexSoup 不读文件系统, 预期 FAIL
    inp = find_cmd("input")
    check("T14", False, "TexCmd(input)=%d — 不展开文件 (架构上无 IO)" % len(inp))
    # T16: NewDocumentCommand
    ndc = find_cmd("NewDocumentCommand")
    ok16 = ndc and len(ndc[0].args) >= 3
    check("T16", bool(ok16), "NDC args=%d" % (len(ndc[0].args) if ndc else 0))
    # T17: \text in math
    math_envs = [n for n in soup.descendants if is_math_node(n)]
    ok17 = any("text" in str(n) and "if and only if" in str(n) for n in math_envs)
    check("T17", ok17, "")
    # T18: figure 内 caption
    fig = [n for n in soup.descendants if node_kind(n) == "env:figure"]
    ok18 = fig and "caption" in str(fig[0]) and "A figure with" in str(fig[0])
    check("T18", bool(ok18), "")
    # T20: lists
    ok20 = all(
        [n for n in soup.descendants if node_kind(n) == "env:" + e]
        for e in ("itemize", "enumerate", "description")
    )
    check("T20", bool(ok20), "")
    # T21/22: href
    href = find_cmd("href")
    ok22 = (
        href
        and len(href[0].args) >= 2
        and "example.com" in str(href[0].args[0])
        and "documentation" in str(href[0].args[1])
    )
    check("T22", bool(ok22), "href args=%s" % (str(href[0].args)[:60] if href else "-"))
    # T23: emph/textbf/textit
    ok23 = find_cmd("emph") and find_cmd("textbf") and find_cmd("textit")
    check("T23", bool(ok23), "")
    # T24: bibliography
    check("T24", bool(find_cmd("bibliography")), "")
    # T26: \[ \] \( \) — \[ 映射为 TexDisplayMathEnv(math:bracket)
    dm = [n for n in soup.descendants if node_kind(n) == "math:bracket"]
    im = [n for n in soup.descendants if node_kind(n) == "math:paren"]
    check(
        "T26",
        bool(dm) and bool(im),
        "bracket-math=%d paren-math=%d" % (len(dm), len(im)),
    )
    # T27: accents
    ok27 = "Andr\\'e" in str(soup) and 'M\\"uller' in str(soup)
    check("T27", ok27, "")
    # T29: footnote standalone
    ok29 = any("should be translated" in str(n) for n in fn)
    check("T29", ok29, "")
    # T19: abstract
    ab = [n for n in soup.descendants if node_kind(n) == "env:abstract"]
    check("T19", bool(ab), "")

    return soup, src, results


def position_audit(soup, src):
    """每个节点 position 是否支持区间切片: src[pos:pos+len(str)] == str(node)."""
    total = ok = bare = 0
    bad = []
    for node in soup.descendants:
        p = getattr(node, "position", None)
        if p is None:
            bare += 1  # bare str child — position 不可得
            continue
        total += 1
        s = str(node)
        if p is None or p < 0 or src[p : p + len(s)] != s:
            bad.append((node_kind(node), p, s[:40]))
        else:
            ok += 1
    return total, ok, bare, bad[:8]


def main():
    os.makedirs(RESULTS, exist_ok=True)
    files = corpus_files()
    print("corpus files: %d" % len(files))

    # ---------- 1. corpus parse ----------
    parse_rows = []
    rt = Counter()
    pos_tot = pos_ok = pos_bare = 0
    for f in files:
        src = open(f, encoding="utf-8", errors="replace").read()
        soup, ms, err = timed_parse(src, 0)
        row = {
            "file": os.path.relpath(f, ROOT),
            "ok": err is None,
            "error": None
            if err is None
            else "%s: %s" % (type(err).__name__, str(err)[:160]),
            "ms": round(ms * 1000, 2),
        }
        if err is not None:
            soup, ms1, err1 = timed_parse(src, 1)
            row["ok_t1"] = err1 is None
            row["error_t1"] = (
                None
                if err1 is None
                else "%s: %s" % (type(err1).__name__, str(err1)[:160])
            )
            row["ms_t1"] = round(ms1 * 1000, 2)
        if soup is not None:
            out = str(soup)
            if out == src:
                row["roundtrip"] = "identical"
                rt["identical"] += 1
            elif " ".join(out.split()) == " ".join(src.split()):
                row["roundtrip"] = "normalized"
                rt["normalized"] += 1
            else:
                row["roundtrip"] = "diverged"
                rt["diverged"] += 1
                row["rt_len_delta"] = len(out) - len(src)
            t, o, nb, _bad = position_audit(soup, src)
            pos_tot += t
            pos_ok += o
            pos_bare += nb
        parse_rows.append(row)
        print(
            "  %-52s %s %8.1fms"
            % (
                row["file"],
                "OK" if row["ok"] else "FAIL(%s)" % (row["error"] or "").split(":")[0],
                row["ms"],
            )
        )

    with open(os.path.join(RESULTS, "texsoup-parse.json"), "w") as fh:
        json.dump(parse_rows, fh, ensure_ascii=False, indent=1)

    n_ok = sum(r["ok"] for r in parse_rows)
    n_ok_t1 = sum(r.get("ok_t1") for r in parse_rows if not r["ok"])
    print("\n== parse: %d/%d ok @t0; +%d recovered @t1" % (n_ok, len(files), n_ok_t1))
    print("== roundtrip:", dict(rt))
    print(
        "== position audit: %d/%d nodes slice-exact (bare-str children w/o position: %d)"
        % (pos_ok, pos_tot, pos_bare)
    )

    # ---------- 2. fixtures ----------
    print("\n== fixtures/tricky.tex ==")
    soup_fx, src_fx, fx_rows = run_fixture_assertions()
    for tid, ok, note in fx_rows:
        print("  %-6s %-4s %s" % (tid, "PASS" if ok else "FAIL", note))

    # ---------- 4. leak rate ----------
    print("\n== leak rate (corpus, t1-parsed files) ==")
    tot_blocks = 0
    tot_leak = 0
    tot_cmdleak = 0
    per_file = []
    for row in parse_rows:
        if not row["ok"] and not row.get("ok_t1"):
            continue
        f = os.path.join(ROOT, row["file"])
        src = open(f, encoding="utf-8", errors="replace").read()
        soup, _, err = timed_parse(src, 0)
        if soup is None:
            soup, _, _ = timed_parse(src, 1)
        if soup is None:
            continue
        blocks = extract_blocks(soup, src)
        n, nc, leaks = leak_stats(blocks)
        tot_blocks += len(blocks)
        tot_leak += n
        tot_cmdleak += nc
        per_file.append((row["file"], len(blocks), n, nc, leaks[:2]))
        if n:
            print("  %-50s blocks=%d leak=%d" % (row["file"], len(blocks), n))
            for l in leaks[:2]:
                print("      | %s" % l.replace("\n", " "))
    print(
        "TOTAL: %d blocks, protocol-leak=%d (%.1f%%), cmd-in-text=%d (%.1f%%)"
        % (
            tot_blocks,
            tot_leak,
            100.0 * tot_leak / max(tot_blocks, 1),
            tot_cmdleak,
            100.0 * tot_cmdleak / max(tot_blocks, 1),
        )
    )

    # fixtures leak demo
    if soup_fx is not None:
        blocks = extract_blocks(soup_fx, src_fx)
        print("\n== tricky.tex extracted blocks (%d) ==" % len(blocks))
        for b in blocks:
            mark = " <== LEAK" if any(m in b for m in LEAK_MARKERS) or "\\" in b else ""
            print("   [%s]%s" % (b.replace("\n", " | ")[:110], mark))

    # ---------- tricky-209 + tricky-multi ----------
    for name in ("tricky-209.tex",):
        src = open(os.path.join(FIXTURES, name)).read()
        soup, ms, err = timed_parse(src, 0)
        print(
            "\n== %s: t0 %s"
            % (name, "OK" if err is None else "FAIL %s" % str(err)[:100])
        )
        if soup is None:
            soup, ms, err = timed_parse(src, 1)
            print("   t1 %s" % ("OK" if err is None else "FAIL %s" % str(err)[:100]))
        if soup is not None:
            print("   roundtrip=%s" % ("identical" if str(soup) == src else "DIVERGED"))
            eqs = [n for n in soup.descendants if is_math_node(n)]
            print(
                "   math envs=%d  cmds def=%d newcommand=%d"
                % (
                    len(eqs),
                    len(soup.find_all("def")),
                    len(soup.find_all("newcommand")),
                )
            )

    msrc = open(os.path.join(FIXTURES, "tricky-multi", "main.tex")).read()
    soup, _, err = timed_parse(msrc, 0)
    print("\n== tricky-multi/main.tex: %s" % ("OK" if err is None else "FAIL"))
    if soup is not None:
        s = str(soup)
        print(
            "   \\input cmd count=%d, sub-content present=%s, commented-out absent=%s"
            % (
                len(soup.find_all("input")) + len(soup.find_all("include")),
                "Intro paragraph" in s,
                "MUST NOT APPEAR" not in s,
            )
        )


if __name__ == "__main__":
    main()
