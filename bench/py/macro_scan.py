#!/usr/bin/env python3
"""
macro_scan.py — 统计 arXiv 语料中 LaTeX 高级构造使用频率.
输出 results/macro-stats.json
"""

import json
import os
import re
from collections import Counter, defaultdict

CORPUS = os.path.expanduser("~/src/texlate/bench/corpus")
OUT = os.path.expanduser("~/src/texlate/bench/results/macro-stats.json")

# ---------- 文本清洗 ----------

LIT_ENVS = {
    "verbatim",
    "verbatim*",
    "Verbatim",
    "lstlisting",
    "minted",
    "comment",
    "filecontents",
    "filecontents*",
    "filecontents+",
}


def blank_literal_bodies(text):
    r"""把 verbatim 类环境的正文行替换为空(保留行数/换行).
    \begin/\end 所在行保留(其中 \begin 行在之后注释剥离中仍有效)."""
    lines = text.split("\n")
    out = []
    lit_env = None
    for line in lines:
        if lit_env is None:
            m = re.search(
                r"\\begin\s*\{(verbatim\*?|Verbatim|lstlisting|minted|comment|filecontents\*?\+?)\}",
                line,
            )
            if m:
                lit_env = m.group(1)
                out.append(line)
                continue
            out.append(line)
        elif re.search(r"\\end\s*\{%s\}" % re.escape(lit_env), line):
            lit_env = None
            out.append(line)
        else:
            out.append("")
    return "\n".join(out)


def strip_comments(text):
    r"""按行剥离注释: 未被奇数个反斜杠转义的 % 起到行尾删除.
    同行内 \verb<d>..</d>, \verb*<d>, \lstinline<d> 的内容跳过."""
    lines = text.split("\n")
    res = []
    for line in lines:
        i, n = 0, len(line)
        buf = []
        while i < n:
            c = line[i]
            if c == "%":
                # 数前面的连续反斜杠
                bs = 0
                j = i - 1
                while j >= 0 and line[j] == "\\":
                    bs += 1
                    j -= 1
                if bs % 2 == 0:
                    break  # 真注释
                buf.append(c)
                i += 1
                continue
            if c == "\\":
                m = re.match(r"\\(verb\*?|lstinline\*?)(.)", line[i:])
                if m and m.group(2) not in ("\\", " ", "\t"):
                    d = m.group(2)
                    end = line.find(d, i + len(m.group(0)))
                    if end == -1:
                        end = n
                    buf.append(line[i : end + 1])
                    i = end + 1
                    continue
            buf.append(c)
            i += 1
        res.append("".join(buf))
    return "\n".join(res)


# ---------- 平衡括号 ----------


def read_balanced(s, i):
    """s[i] == '{' 时返回 (body, next_index); 容忍 \\{ \\}."""
    assert s[i] == "{"
    depth, j, n = 0, i, len(s)
    while j < n:
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1 : j], j + 1
        j += 1
    return s[i + 1 :], n


def skip_ws(s, i):
    while i < len(s) and s[i] in " \t\n":
        i += 1
    return i


def read_bracket(s, i):
    """读 [..] 可选参数, 返回 (content, next). 没有则 (None, i)."""
    i = skip_ws(s, i)
    if i < len(s) and s[i] == "[":
        depth, j = 0, i
        while j < len(s):
            if s[j] == "[":
                depth += 1
            elif s[j] == "]":
                depth -= 1
                if depth == 0:
                    return s[i + 1 : j], j + 1
            j += 1
        return s[i + 1 :], len(s)
    return None, i


def read_group_or_name(s, i):
    """读 {\\foo} 或 \\foo 形式的宏名, 返回 (name, next)."""
    i = skip_ws(s, i)
    if i < len(s) and s[i] == "{":
        body, j = read_balanced(s, i)
        return body.strip().lstrip("\\"), j
    m = re.match(r"\\([a-zA-Z@]+|.)", s[i:])
    if m:
        return m.group(1), i + len(m.group(0))
    return None, i


# ---------- 宏定义提取 ----------


def extract_defs(text):
    """返回 [{kind, name, nargs, body, pos, extra}]"""
    defs = []
    n = len(text)

    # 1) \newcommand/\renewcommand/\providecommand/\DeclareRobustCommand
    for m in re.finditer(
        r"\\(newcommand|renewcommand|providecommand|DeclareRobustCommand)\s*(\*?)", text
    ):
        i = skip_ws(text, m.end())
        name, i = read_group_or_name(text, i)
        nargs, i = read_bracket(text, i)
        _default, i = read_bracket(text, i)
        i2 = skip_ws(text, i)
        body = ""
        if i2 < n and text[i2] == "{":
            body, i = read_balanced(text, i2)
        defs.append(
            {
                "kind": m.group(1),
                "name": name,
                "nargs": nargs,
                "body": body,
                "pos": m.start(),
            }
        )

    # 2) \newenvironment / \renewenvironment
    for m in re.finditer(r"\\(newenvironment|renewenvironment)\s*(\*?)", text):
        i = skip_ws(text, m.end())
        name, i = read_group_or_name(text, i)
        nargs, i = read_bracket(text, i)
        _default, i = read_bracket(text, i)
        i2 = skip_ws(text, i)
        beg = end = ""
        if i2 < n and text[i2] == "{":
            beg, i = read_balanced(text, i2)
            i2 = skip_ws(text, i)
            if i2 < n and text[i2] == "{":
                end, i = read_balanced(text, i2)
        defs.append(
            {
                "kind": m.group(1),
                "name": name,
                "nargs": nargs,
                "body": beg + "\x00" + end,
                "pos": m.start(),
            }
        )

    # 3) xparse \NewDocumentCommand 等
    for m in re.finditer(
        r"\\((?:New|Renew|Provide|Declare|Expandable|NewExpandable)DocumentCommand)\s*",
        text,
    ):
        i = skip_ws(text, m.end())
        name, i = read_group_or_name(text, i)
        spec = ""
        i2 = skip_ws(text, i)
        if i2 < n and text[i2] == "{":
            spec, i = read_balanced(text, i2)
        i2 = skip_ws(text, i)
        body = ""
        if i2 < n and text[i2] == "{":
            body, i = read_balanced(text, i2)
        defs.append(
            {
                "kind": m.group(1),
                "name": name,
                "nargs": spec,
                "body": body,
                "pos": m.start(),
            }
        )

    # 4) \DeclareMathOperator / \DeclareMathOperator*
    for m in re.finditer(r"\\(DeclareMathOperator)\s*\*?", text):
        i = skip_ws(text, m.end())
        name, i = read_group_or_name(text, i)
        i2 = skip_ws(text, i)
        body = ""
        if i2 < n and text[i2] == "{":
            body, i = read_balanced(text, i2)
        defs.append(
            {
                "kind": m.group(1),
                "name": name,
                "nargs": None,
                "body": body,
                "pos": m.start(),
            }
        )

    # 5) \def / \gdef / \edef / \xdef (含 \long\def)
    for m in re.finditer(r"\\(gdef|edef|xdef|def)\s*\\([a-zA-Z@]+|.)", text):
        i = m.end()
        # 参数文本: 到第一个 { 为止
        j = i
        params = []
        while j < n:
            c = text[j]
            if c == "{":
                break
            if c == "\\":
                j += 2
                continue
            if c in " \t\n#[](),":
                params.append(c)
                j += 1
                continue
            if c.isdigit():
                params.append(c)
                j += 1
                continue
            break
        params = "".join(params).strip()
        j = skip_ws(text, j)
        body = ""
        if j < n and text[j] == "{":
            body, _ = read_balanced(text, j)
        defs.append(
            {
                "kind": m.group(1),
                "name": m.group(2),
                "nargs": params,
                "body": body,
                "pos": m.start(),
            }
        )

    # 6) \let / \newif / \newtheorem / \newcount 等 (无体或特殊)
    defs.extend(
        {"kind": "let", "name": m.group(1), "nargs": None, "body": "", "pos": m.start()}
        for m in re.finditer(r"\\let\s*\\([a-zA-Z@]+|.)", text)
    )
    defs.extend(
        {
            "kind": m.group(1),
            "name": m.group(2),
            "nargs": None,
            "body": "",
            "pos": m.start(),
        }
        for m in re.finditer(
            r"\\(newif|newcount|newlength|newtoks|newbox|newdimen|newskip|newcounter|newsavebox|newread|newwrite|newmuskip)\s*\\([a-zA-Z@]+)",
            text,
        )
    )
    for m in re.finditer(r"\\newtheorem\s*\*?", text):
        i = skip_ws(text, m.end())
        name, i = read_group_or_name(text, i)
        _, i = read_bracket(text, i)
        i2 = skip_ws(text, i)
        title = ""
        if i2 < n and text[i2] == "{":
            title, i = read_balanced(text, i2)
        defs.append(
            {
                "kind": "newtheorem",
                "name": name,
                "nargs": None,
                "body": title,
                "pos": m.start(),
            }
        )
    # 7) \newlist / \DeclarePairedDelimiter 等杂项声明
    for m in re.finditer(
        r"\\(DeclarePairedDelimiterX?|DeclareRobustCommand|DeclareTextCommand|DeclareUnicodeCharacter|DeclareMathSymbol|DeclareMathAccent|DeclareSymbolFont|mathchardef)\b",
        text,
    ):
        if m.group(1) == "DeclareRobustCommand":
            continue  # 已在(1)
        defs.append(
            {
                "kind": m.group(1),
                "name": "",
                "nargs": None,
                "body": "",
                "pos": m.start(),
            }
        )

    defs.sort(key=lambda d: d["pos"])
    return defs


# ---------- 定义体特征 ----------

MATH_CMDS = re.compile(
    r"\\(frac|dfrac|tfrac|sqrt|sum|prod|int|iint|iiint|oint|partial|nabla|infty"
    r"|alpha|beta|gamma|delta|epsilon|varepsilon|zeta|eta|theta|vartheta|iota"
    r"|kappa|lambda|mu|nu|xi|pi|varpi|rho|varrho|sigma|varsigma|tau|upsilon"
    r"|phi|varphi|chi|psi|omega|Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Upsilon"
    r"|Phi|Psi|Omega|ell|hbar|imath|jmath|Re|Im|aleph|wp"
    r"|mathbb|mathcal|mathbf|mathit|mathsf|mathtt|mathfrak|mathrm|mathscr|boldsymbol|bm"
    r"|vec|hat|widehat|tilde|widetilde|bar|overline|underline|dot|ddot|overrightarrow|overleftarrow"
    r"|left|right|leftarrow|rightarrow|Leftarrow|Rightarrow|leftrightarrow|Leftrightarrow"
    r"|to|mapsto|implies|impliedby|iff|gets"
    r"|leq|geq|neq|approx|equiv|sim|simeq|propto|cong|prec|succ|ll|gg|subset|subseteq|supset|supseteq"
    r"|in|ni|notin|cup|cap|setminus|emptyset|forall|exists|nexists|pm|mp|times|div|cdot|ast|star"
    r"|circ|bullet|oplus|ominus|otimes|odot|wedge|vee|neg|land|lor|perp|parallel|mid|nmid"
    r"|quad|qquad|displaystyle|textstyle|limits|nolimits|substack|overset|underset"
    r"|operatorname|binom|boxed|sqrt\[|ensuremath|text|mathrm|intertext|mathop"
    r"|begin\{equation|begin\{align|begin\{math|begin\{cases|begin\{array|begin\{pmatrix)\b"
)


def body_flags(body):
    flags = []
    if re.search(r"\\(begin|end)\s*\{", body):
        flags.append("begin_end")
    if re.search(
        r"\\begin\s*\{(equation|align|gather|eqnarray|multline|IEEEeqnarray|math|displaymath|subequations|alignat|flalign|cases|array|pmatrix|bmatrix|split|gathered|aligned)",
        body,
    ):
        flags.append("begin_math_env")
    if re.search(
        r"\\begin\s*\{(figure|table|tabular|itemize|enumerate|description|theorem|proof|center|minipage|quote|verbatim|lstlisting|frame|block|algorithm)",
        body,
    ):
        flags.append("begin_other_env")
    has_dollar = ("$" in body) or ("\\(" in body) or ("\\[" in body)
    if has_dollar:
        flags.append("dollar_math")
    if MATH_CMDS.search(body):
        flags.append("math_cmd")
    if re.search(r"[#][_^]", body) or re.search(r"(?<![\\a-zA-Z])[_^]", body):
        flags.append("sub_sup")
    # 可译文本: 去命令/括号后字母总数
    cleaned = re.sub(r"\\[a-zA-Z@]+\*?", "", body)
    cleaned = re.sub(r"\\.?", "", cleaned)
    letters = re.sub(r"[^a-zA-Z]", "", cleaned)
    if len(letters) > 20:
        flags.append("text_gt20")
    return flags, cleaned.strip()


# ---------- 主扫描 ----------

CMD_PATTERNS = {
    # 引用族
    "cite_tokens": re.compile(
        r"\\(cite[a-zA-Z]*|nocite|parencite[a-zA-Z]*|textcite[a-zA-Z]*|autocite[a-zA-Z]*|footcite|smartcite|supercite|fullcite|volcite|citenum|citetext)\b"
    ),
    # 章节可选参数
    "sec_opt": re.compile(
        r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\s*\*?\s*\["
    ),
    # if 族
    "if_tokens": re.compile(r"\\(if[a-zA-Z@]*|else|fi|or)\b"),
    "makeatletter": re.compile(r"\\makeatletter"),
    # 逐字
    "verb_cmd": re.compile(r"\\verb\*?"),
    "lstinline": re.compile(r"\\lstinline"),
    "mintinline": re.compile(r"\\mint(inline)?\b"),
    # 文件
    "input_inc": re.compile(
        r"\\(input|include|includeonly|subfile|subfileinclude|import|subimport|includefrom|subincludefrom|InputIfFileExists)\b"
    ),
    # 环境
    "begin_env": re.compile(r"\\begin\s*\{([^}]+)\}"),
    # 209 / 引擎
    "documentstyle": re.compile(r"\\documentstyle"),
    "inputenc": re.compile(r"\\usepackage\s*\[?[^\]]*\]?\s*\{inputenc\}"),
    "fontenc": re.compile(r"\\usepackage\s*\[?[^\]]*\]?\s*\{fontenc\}"),
    "fontspec": re.compile(r"\\usepackage\s*\{?fontspec\}?|\\setmainfont"),
    # 奇技
    "expandafter": re.compile(r"\\expandafter"),
    "csname": re.compile(r"\\csname"),
    "catcode": re.compile(r"\\catcode"),
    "bgroup": re.compile(r"\\bgroup\b|\\egroup\b"),
    "atbegin": re.compile(r"\\AtBeginDocument|\\AtEndDocument|\\AtBeginEnvironment"),
    "lowlevel": re.compile(
        r"\\(advance|multiply|divide|loop|repeat|uppercase|lowercase|noexpand|protect\b|meaning|jobname|the\w*\s|toks\d*|immediate|openout|closeout|write18|write\b|read\b|detokenize|scantokens|unexpanded|numexpr|dimexpr|ifcase)\b"
    ),
    "ifx_undef": re.compile(
        r"\\(@ifundefined|IfFileExists|ifthenelse|IfStrEq|ifstrequal|ifdef|ifundef|ifcsdef|ifcsundef|ifdefequal|ifblank|ifstrempty|ifdefstring|ifcsstring|ifboolexpr|ifboolexpe|whileboolexpr|ifdefined|ifcsname)\b"
    ),
    "usepackage": re.compile(r"\\usepackage\s*(?:\[([^\]]*)\])?\s*\{([^}]+)\}"),
    "bibliography": re.compile(
        r"\\(bibliography|bibliographystyle|addbibresource|printbibliography|begin\{thebibliography\}|bibitem)\b"
    ),
    "tikz": re.compile(
        r"\\(usetikzlibrary|tikzset|pgfdeclareimage|addplot|node\b|draw\b|tikz\b)|\\begin\{(tikzpicture|pgfplots|axis|tikzcd)"
    ),
    "algorithm": re.compile(
        r"\\begin\{(algorithm|algorithmic|algorithmicx|algorithm2e|procedure|listing)\}|\\(Require|Ensure|State|Procedure|EndProcedure)\b"
    ),
    "cleveref": re.compile(r"\\(cref|Cref|crefrange|cpageref|autoref|nameref)\b"),
    "siunitx": re.compile(r"\\(SI|si|num|ang|qty)\b"),
    "gloss": re.compile(
        r"\\(gls|Gls|acrshort|acrlong|acrfull|newacronym|newglossaryentry)\b"
    ),
    "url": re.compile(r"\\(url|href|hyperref|doi|email|path)\b"),
    "footnote": re.compile(r"\\footnote\b|\\thanks\b"),
    "includegraphics": re.compile(r"\\includegraphics|\\epsfig|\\psfig|\\psfrag"),
    "twooptarg_cmds": re.compile(r"\\(subcaption|sidecaption)\b"),
    "customflags": re.compile(
        r"\\(ifdraft|iffinal|ifsubmission|ifarxiv|ifpreprint|ifshort|iflong|ifcamready|ifcamera|ifnotes|ifcomments|ifappendix|ifsupp|ifrebuttal|ifanonym|ifanonymous|ifextended|iffull|ifconf|ifjournal|ifacmlarge|ifsoc|\w*@draft|@\w*if)\b",
        re.IGNORECASE,
    ),
}

MATH_ENVS = {
    "equation",
    "equation*",
    "align",
    "align*",
    "gather",
    "gather*",
    "gathered",
    "multline",
    "multline*",
    "multlined",
    "eqnarray",
    "eqnarray*",
    "alignat",
    "alignat*",
    "xalignat",
    "xalignat*",
    "xxalignat",
    "flalign",
    "flalign*",
    "subequations",
    "IEEEeqnarray",
    "IEEEeqnarray*",
    "IEEEeqnarraybox",
    "dmath",
    "dmath*",
    "dgroup",
    "dgroup*",
    "dseries",
    "dseries*",
    "empheq",
    "math",
    "displaymath",
    "split",
    "cases",
    "dcases",
    "array",
    "matrix",
    "pmatrix",
    "bmatrix",
    "vmatrix",
    "Bmatrix",
    "smallmatrix",
    "eqsplit",
    "aligned",
    "alignedat",
    "numcases",
    "subnumcases",
    "IEEEproof",
    "eqn",
    "eq*",
}


def scan_file(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except Exception as e:
        return None, str(e)
    lit = blank_literal_bodies(raw)
    clean = strip_comments(lit)
    defs = extract_defs(clean)
    # 特征
    feats = {}
    for k, pat in CMD_PATTERNS.items():
        if k in {"cite_tokens", "if_tokens"}:
            feats[k] = Counter(m.group(1) for m in pat.finditer(clean))
        elif k == "begin_env":
            feats[k] = Counter(
                m.group(1).rstrip("*") + ("*" if m.group(1).endswith("*") else "")
                if False
                else m.group(1)
                for m in pat.finditer(clean)
            )
        elif k == "usepackage":
            cnt = Counter()
            for m in pat.finditer(clean):
                for p in m.group(2).split(","):
                    cnt[p.strip()] += 1
            feats[k] = cnt
        elif k in {"sec_opt", "input_inc", "bibliography"}:
            feats[k] = Counter(m.group(1) for m in pat.finditer(clean))
        else:
            feats[k] = len(pat.findall(clean))
    # verbatim 环境单独统计(用原文,因正文已被 blank)
    verb_envs = Counter()
    for m in re.finditer(
        r"\\begin\s*\{(verbatim\*?|Verbatim|lstlisting|minted|comment|filecontents\*?|alltt)\}",
        raw,
    ):
        verb_envs[m.group(1)] += 1
    feats["literal_envs"] = verb_envs
    feats["lines"] = raw.count("\n") + 1
    feats["nchars"] = len(raw)
    feats["is_impl"] = bool(
        re.search(
            r"\\(ProvidesClass|ProvidesPackage|ProvidesFile|NeedsTeXFormat|LoadClass|ProvidesExplPackage)",
            raw,
        )
    )
    # \begin{document} 位置 → 定义在正文中的比例
    docpos = clean.find("\\begin{document}")
    return {
        "defs": defs,
        "feats": feats,
        "docpos": docpos,
        "raw": raw,
        "clean": clean,
    }, None


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def main():
    papers = defaultdict(list)  # paper_id -> [relpath]
    for root, _dirs, files in os.walk(CORPUS):
        for fn in files:
            if fn.endswith(".tex"):
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, CORPUS)
                paper = rel.split(os.sep)[0]
                papers[paper].append(rel)

    result = {"n_papers": len(papers), "papers": {}}
    all_def_examples = {
        "begin_end": [],
        "begin_math_env": [],
        "math_cmd": [],
        "dollar_math": [],
        "text_gt20": [],
        "sub_sup": [],
    }

    # per_paper[pp] = {files: {rel: filerecord}, lines, ...}
    per_paper = {}
    for paper in sorted(papers):
        p = {"files": {}, "errors": []}
        for rel in sorted(papers[paper]):
            full = os.path.join(CORPUS, rel)
            data, err = scan_file(full)
            if err:
                p["errors"].append((rel, err))
                continue
            for d in data["defs"]:
                flags, cleaned = body_flags(d.get("body") or "")
                d["flags"] = flags
                d["file"] = rel
                d["line"] = line_of(data["clean"], d["pos"])
                d["in_body"] = data["docpos"] >= 0 and d["pos"] > data["docpos"]
                d["is_impl"] = data["feats"]["is_impl"]
                d["body_snip"] = (d.get("body") or "")[:300]
                d["cleaned_snip"] = cleaned[:200]
                for f in flags:
                    ex = {
                        "paper": paper,
                        "file": rel,
                        "line": d["line"],
                        "kind": d["kind"],
                        "name": d["name"],
                        "body": d["body_snip"],
                        "cleaned": d["cleaned_snip"],
                    }
                    if len(all_def_examples.setdefault(f, [])) < 60:
                        all_def_examples[f].append(ex)
            p["files"][rel] = {"feats": data["feats"], "defs": data["defs"]}
        per_paper[paper] = p

    def aggregate(exclude_impl):
        """对全部文件(可选排除实现文件)聚合出 summary."""
        env_hist = Counter()
        cite_hist = Counter()
        if_hist = Counter()
        pkg_hist = Counter()
        sec_opt_hist = Counter()
        input_hist = Counter()
        bib_hist = Counter()
        lit_hist = Counter()
        Counter()
        kind_tot = Counter()
        kind_papers = defaultdict(set)
        flag_totals = Counter()
        flag_papers = defaultdict(set)
        flag_kind = Counter()  # (flag, kind)
        papers_with_any_def = 0
        total_defs = 0
        defs_in_body = 0
        defs_per_paper = {}
        ntex = 0
        tot_lines = 0
        cite_pp = {}
        natbib = {
            "citep",
            "citet",
            "citealp",
            "citealt",
            "citeauthor",
            "citeyear",
            "citeyearpar",
            "citepalias",
            "citetalias",
            "Citep",
            "Citet",
            "citetext",
            "citeonline",
            "citeyearnp",
            "citepos",
            "citenum",
        }
        biblatex = {
            "parencite",
            "textcite",
            "autocite",
            "footcite",
            "smartcite",
            "supercite",
            "fullcite",
            "volcite",
            "parencites",
            "textcites",
            "footfullcite",
            "citeurl",
            "citename",
            "citestyle",
        }
        papers_natbib = papers_biblatex = papers_basic = 0
        sec_opt_papers = 0
        if_papers = 0
        else_papers = 0
        fi_papers = 0
        mal_papers = 0
        mal_total = 0
        verb_papers = 0
        verb_total = 0
        litenv_papers = 0
        minted_papers = 0
        papers_gt1 = 0
        papers_input = 0
        longtail_names = {
            "subequations",
            "flalign",
            "alignat",
            "alignat*",
            "xalignat",
            "xxalignat",
            "IEEEeqnarray",
            "IEEEeqnarray*",
            "dmath",
            "dmath*",
            "dgroup",
            "empheq",
            "split",
            "aligned",
            "alignedat",
            "cases",
            "dcases",
            "gathered",
            "multlined",
            "numcases",
        }
        papers_longtail = 0
        docstyle_papers = []
        inputenc_papers = []
        fontenc_papers = []
        fontspec_papers = []
        odd = {
            k: [0, 0]
            for k in [
                "expandafter",
                "csname",
                "catcode",
                "bgroup",
                "atbegin",
                "lowlevel",
                "ifx_undef",
                "tikz",
                "algorithm",
                "cleveref",
                "siunitx",
                "gloss",
                "url",
                "footnote",
                "includegraphics",
                "customflags",
                "twooptarg_cmds",
                "documentstyle",
            ]
        }
        impl_files = []
        files_per_paper = {}
        math_env_hist = Counter()
        env_hist_all = Counter()

        for pp, p in per_paper.items():
            nfiles = 0
            for rel, fr in p["files"].items():
                feats = fr["feats"]
                if exclude_impl and feats["is_impl"]:
                    impl_files.append(rel)
                    continue
                nfiles += 1
                ntex += 1
                tot_lines += feats["lines"]
                env_hist.update(feats.get("begin_env", {}))
                env_hist_all.update(feats.get("begin_env", {}))
                cite_hist.update(feats.get("cite_tokens", {}))
                if_hist.update(feats.get("if_tokens", {}))
                pkg_hist.update(feats.get("usepackage", {}))
                sec_opt_hist.update(feats.get("sec_opt", {}))
                input_hist.update(feats.get("input_inc", {}))
                bib_hist.update(feats.get("bibliography", {}))
                lit_hist.update(feats.get("literal_envs", {}))
                for e, c in feats.get("begin_env", {}).items():
                    if e.rstrip("*") in MATH_ENVS or e in MATH_ENVS:
                        math_env_hist[e] += c
            files_per_paper[pp] = nfiles
            # defs
            ndefs = 0
            for fr in p["files"].values():
                feats = fr["feats"]
                if exclude_impl and feats["is_impl"]:
                    continue
                for d in fr["defs"]:
                    ndefs += 1
                    kind_tot[d["kind"]] += 1
                    kind_papers[d["kind"]].add(pp)
                    for f in d["flags"]:
                        flag_totals[f] += 1
                        flag_papers[f].add(pp)
                        flag_kind[(f, d["kind"])] += 1
                    if d["in_body"]:
                        defs_in_body += 1
            defs_per_paper[pp] = ndefs
            total_defs += ndefs
            if ndefs > 0:
                papers_with_any_def += 1
            # cites
            c = Counter()
            for fr in p["files"].values():
                if exclude_impl and fr["feats"]["is_impl"]:
                    continue
                c.update(fr["feats"].get("cite_tokens", {}))
            nb = sum(v for k, v in c.items() if k in natbib)
            bl = sum(v for k, v in c.items() if k in biblatex)
            bs = c.get("cite", 0)
            if nb:
                papers_natbib += 1
            if bl:
                papers_biblatex += 1
            if bs:
                papers_basic += 1
            cite_pp[pp] = {"natbib": nb, "biblatex": bl, "basic": bs, "raw": dict(c)}
            # sec opt
            so = sum(
                fr["feats"].get("sec_opt", {}).get("section", 0)
                + fr["feats"].get("sec_opt", {}).get("subsection", 0)
                + fr["feats"].get("sec_opt", {}).get("chapter", 0)
                for rel, fr in p["files"].items()
                if not (exclude_impl and fr["feats"]["is_impl"])
            )
            if so:
                sec_opt_papers += 1
            # ifs
            iftok = Counter()
            for fr in p["files"].values():
                if exclude_impl and fr["feats"]["is_impl"]:
                    continue
                iftok.update(fr["feats"].get("if_tokens", {}))
            if any(k.startswith("if") and k != "iff" for k in iftok):
                if_papers += 1
            if iftok.get("else"):
                else_papers += 1
            if iftok.get("fi"):
                fi_papers += 1
            # makeatletter / verb
            mal = sum(
                fr["feats"].get("makeatletter", 0)
                for fr in p["files"].values()
                if not (exclude_impl and fr["feats"]["is_impl"])
            )
            if mal:
                mal_papers += 1
            mal_total += mal
            vb = sum(
                fr["feats"].get("verb_cmd", 0)
                for fr in p["files"].values()
                if not (exclude_impl and fr["feats"]["is_impl"])
            )
            if vb:
                verb_papers += 1
            verb_total += vb
            le = sum(
                sum(fr["feats"].get("literal_envs", {}).values())
                for fr in p["files"].values()
                if not (exclude_impl and fr["feats"]["is_impl"])
            )
            if le:
                litenv_papers += 1
            mt = sum(
                fr["feats"].get("literal_envs", {}).get("minted", 0)
                + fr["feats"].get("mintinline", 0)
                for fr in p["files"].values()
                if not (exclude_impl and fr["feats"]["is_impl"])
            )
            if mt:
                minted_papers += 1
            # files/input
            if nfiles > 1:
                papers_gt1 += 1
            ii = Counter()
            for fr in p["files"].values():
                if exclude_impl and fr["feats"]["is_impl"]:
                    continue
                ii.update(fr["feats"].get("input_inc", {}))
            if ii.get("input") or ii.get("include") or ii.get("subfile"):
                papers_input += 1
            # math longtail
            envs = Counter()
            for fr in p["files"].values():
                if exclude_impl and fr["feats"]["is_impl"]:
                    continue
                envs.update(fr["feats"].get("begin_env", {}))
            if any(e in longtail_names for e in envs):
                papers_longtail += 1
            # 209/engine
            ds = sum(
                fr["feats"].get("documentstyle", 0)
                for fr in p["files"].values()
                if not (exclude_impl and fr["feats"]["is_impl"])
            )
            if ds:
                docstyle_papers.append(pp)
            if any(
                fr["feats"].get("inputenc", 0)
                for fr in p["files"].values()
                if not (exclude_impl and fr["feats"]["is_impl"])
            ):
                inputenc_papers.append(pp)
            if any(
                fr["feats"].get("fontenc", 0)
                for fr in p["files"].values()
                if not (exclude_impl and fr["feats"]["is_impl"])
            ):
                fontenc_papers.append(pp)
            if any(
                fr["feats"].get("fontspec", 0)
                for fr in p["files"].values()
                if not (exclude_impl and fr["feats"]["is_impl"])
            ):
                fontspec_papers.append(pp)
            # odd
            for k, ov in odd.items():
                v = sum(
                    fr["feats"].get(k, 0)
                    for fr in p["files"].values()
                    if not (exclude_impl and fr["feats"]["is_impl"])
                )
                ov[1] += v
                if v:
                    ov[0] += 1

        return {
            "n_papers": len(per_paper),
            "n_tex": ntex,
            "tot_lines": tot_lines,
            "impl_files": sorted(set(impl_files)),
            "files_per_paper": files_per_paper,
            "def_kind_tot": dict(kind_tot),
            "def_kind_papers": {k: len(v) for k, v in kind_papers.items()},
            "papers_with_any_def": papers_with_any_def,
            "total_defs": total_defs,
            "defs_in_body": defs_in_body,
            "defs_per_paper": defs_per_paper,
            "flag_totals": dict(flag_totals),
            "flag_papers": {k: len(v) for k, v in flag_papers.items()},
            "flag_kind": {"%s|%s" % k: v for k, v in flag_kind.items()},
            "cite": {
                "natbib_papers": papers_natbib,
                "biblatex_papers": papers_biblatex,
                "basic_papers": papers_basic,
                "hist": dict(cite_hist.most_common(40)),
                "per_paper": cite_pp,
            },
            "sec_opt": {
                "hist": dict(sec_opt_hist),
                "total": sum(sec_opt_hist.values()),
                "papers": sec_opt_papers,
            },
            "if_hist": dict(if_hist.most_common(80)),
            "if_papers": if_papers,
            "else_papers": else_papers,
            "fi_papers": fi_papers,
            "makeatletter_papers": mal_papers,
            "makeatletter_total": mal_total,
            "verb_papers": verb_papers,
            "verb_total": verb_total,
            "literal_envs": dict(lit_hist),
            "literal_env_papers": litenv_papers,
            "minted_papers": minted_papers,
            "papers_gt1file": papers_gt1,
            "papers_input_include": papers_input,
            "input_hist": dict(input_hist),
            "math_env_hist": dict(sorted(math_env_hist.items(), key=lambda x: -x[1])),
            "papers_math_longtail": papers_longtail,
            "env_hist_top": dict(env_hist_all.most_common(60)),
            "documentstyle_papers": docstyle_papers,
            "inputenc_papers": inputenc_papers,
            "fontenc_papers": fontenc_papers,
            "fontspec_papers": fontspec_papers,
            "odd": {k: {"papers": v[0], "total": v[1]} for k, v in odd.items()},
            "bib_hist": dict(bib_hist),
            "pkg_top": dict(pkg_hist.most_common(60)),
        }

    summary_all = aggregate(False)
    summary_clean = aggregate(True)
    summary_all["flag_examples"] = {k: v[:15] for k, v in all_def_examples.items()}
    summary_all["flag_examples_rest"] = {k: len(v) for k, v in all_def_examples.items()}
    result["summary"] = summary_all
    result["summary_clean"] = summary_clean
    # per-paper defs 明细(轻量)
    result["papers"] = {}
    for pp, p in per_paper.items():
        result["papers"][pp] = {
            "files": {
                rel: {"is_impl": fr["feats"]["is_impl"], "lines": fr["feats"]["lines"]}
                for rel, fr in p["files"].items()
            },
            "defs": [
                {
                    k: d[k]
                    for k in (
                        "kind",
                        "name",
                        "nargs",
                        "flags",
                        "file",
                        "line",
                        "in_body",
                        "is_impl",
                        "body_snip",
                        "cleaned_snip",
                    )
                }
                for fr in p["files"].values()
                for d in fr["defs"]
            ],
            "errors": p["errors"],
        }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1, default=dict)
    print("wrote", OUT)
    for name, s in (("ALL", summary_all), ("CLEAN(no impl)", summary_clean)):
        print("========", name)
        print(
            "n_tex",
            s["n_tex"],
            "lines",
            s["tot_lines"],
            "defs",
            s["total_defs"],
            "papers_with_def",
            s["papers_with_any_def"],
            "defs_in_body",
            s["defs_in_body"],
        )
        print("kind_tot", s["def_kind_tot"])
        print("flag_totals", s["flag_totals"], "flag_papers", s["flag_papers"])
        print("cite", {k: v for k, v in s["cite"].items() if k != "per_paper"})
        print("sec_opt", s["sec_opt"])
        print(
            "if/else/fi papers",
            s["if_papers"],
            s["else_papers"],
            s["fi_papers"],
            "makeatletter",
            s["makeatletter_papers"],
            s["makeatletter_total"],
        )
        print(
            "verb",
            s["verb_papers"],
            s["verb_total"],
            "litenv",
            s["literal_envs"],
            s["literal_env_papers"],
            "minted_p",
            s["minted_papers"],
        )
        print(
            "multifile",
            s["papers_gt1file"],
            "input_inc",
            s["papers_input_include"],
            s["input_hist"],
        )
        print(
            "math_lt",
            s["papers_math_longtail"],
            "docstyle",
            s["documentstyle_papers"],
            "inputenc",
            len(s["inputenc_papers"]),
            "fontenc",
            len(s["fontenc_papers"]),
            "fontspec",
            s["fontspec_papers"],
        )
        print("odd", s["odd"])


if __name__ == "__main__":
    main()
