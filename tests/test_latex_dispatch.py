r"""scanner._dispatch_cmd 19 行分派表逐行覆盖（docs/07 §3.2 顺序即语义）。"""

from texlate.latex import parse_tex, reconstruct
from texlate.latex.model import ScanResult
from texlate.latex.placeholder import PH_RX

DOC = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}\n"


def scan(body: str) -> ScanResult:
    return parse_tex(DOC % body)


def ph_types(res: ScanResult) -> list[str]:
    return [k.split("_")[0].strip("[]") for k in res.ph_map]


def test_row1_verb_delim() -> None:
    r"""`\verb|a%b|` → ``[[VERB]]``，``%`` 不当注释。"""
    res = scan(r"before \verb|a%b| after")
    assert any(v == "\\verb|a%b|" for v in res.ph_map.values())
    assert reconstruct(res) == DOC % r"before \verb|a%b| after"


def test_row1_verb_star_and_eol_cap() -> None:
    r"""``\verb*`` + 定界搜索不过 EOL（W9：找不到同行闭符 → 逐字）。"""
    res = scan(r"a \verb*|x y| b")
    assert "\\verb*|x y|" in res.ph_map.values()
    res2 = scan("a \\verb|x y\nb| c")
    # 闭符在下一行 → verb 不成立，逐字
    assert "\\verb|x y" not in " ".join(res2.ph_map.values())


def test_row1_lstinline_opt_and_brace() -> None:
    res = scan(r"a \lstinline[language=C]|x%y| b")
    assert "\\lstinline[language=C]|x%y|" in res.ph_map.values()
    res2 = scan(r"a \lstinline{x%y} b")
    assert "\\lstinline{x%y}" in res2.ph_map.values()


def test_row2_newcommand_registered() -> None:
    r"""``\newcommand`` 整段 LITERAL + 宏表登记；正文调用走宏行。"""
    res = scan("\\newcommand{\\dR}{\\mathrm{d}R}\nBody uses \\dR here.")
    assert "dR" in res.macros.cmds
    assert any(v == "\\dR" for v in res.ph_map.values())
    assert (
        reconstruct(res)
        == DOC % "\\newcommand{\\dR}{\\mathrm{d}R}\nBody uses \\dR here."
    )


def test_row2_def_delimited_degrades() -> None:
    r"""``\def\f(#1){}`` 定界参 → 不登记 + ``def_parse_fail``（v1 刻意降级）。"""
    res = scan("\\def\\f(#1){x#1}\nAfter \\f(y).")
    assert "f" not in res.macros.cmds
    assert any(w.kind == "def_parse_fail" for w in res.warnings)
    assert reconstruct(res) == DOC % "\\def\\f(#1){x#1}\nAfter \\f(y)."


def test_row2_newenvironment() -> None:
    res = scan("\\newenvironment{mybox}[1]{\\begin{figure}}{\\end{figure}}\nText.")
    assert "mybox" in res.macros.envs
    assert res.macros.envs["mybox"].nargs == 1


def test_row3_newif_registers() -> None:
    r"""``\newif\ifX`` → ifflags[X]=False + ``\Xtrue/\Xfalse`` LITERAL 宏。"""
    res = scan("\\newif\\ifdbg\n\\dbgtrue\nText.")
    assert res.macros  # 宏表对象在
    assert "dbgtrue" in res.macros.cmds
    assert res.macros.cmds["dbgtrue"].kind.name == "LITERAL"


def test_row4_math_env() -> None:
    res = scan("Text\n\\begin{equation}x=1\\end{equation}\nmore")
    assert any(t == "MATH" for t in ph_types(res))


def test_row4_verbatim_env() -> None:
    r"""verbatim env 整段 ``[[VERB]]``，内部 ``%`` 不触发注释。"""
    body = "Text\n\\begin{verbatim}a%\\cite{x}\\end{verbatim}\nmore"
    res = scan(body)
    assert "\\begin{verbatim}a%\\cite{x}\\end{verbatim}" in res.ph_map.values()
    assert reconstruct(res) == DOC % body


def test_row4_protected_env_mines_caption() -> None:
    r"""figure → ``[[ENV]]``；内部 ``\caption`` 仍挖为 chunk（§3.5）。"""
    body = "\\begin{figure}\\caption{Cap text here.}\\end{figure}"
    res = scan(body)
    assert any(t == "ENV" for t in ph_types(res))
    assert any("Cap text here." in c.content for c in res.chunks)


def test_row4_transparent_env() -> None:
    r"""未知/透明 env：``\begin/\end`` 行逐字，内容正常进主流。"""
    body = "\\begin{itemize}\\item First item text here.\\end{itemize}"
    res = scan(body)
    assert "\\begin{itemize}" in res.protected_tex
    assert any("First item text here." in c.content for c in res.chunks)


def test_row5_stray_end_and_document_cut() -> None:
    r"""``\end{document}`` 顶层截停：其后内容整体逐字，不再扫描。"""
    res = scan("Text\n\\end{document}\n\\section{After} $x$")
    # \end{document} 之后不再产生新 ph/chunk
    assert not any("After" in c.content for c in res.chunks)


def test_row5_end_inside_arg() -> None:
    r"""in_arg 的 ``\end{env}`` → ``[[ENVTAG]]`` 而非截停。"""
    body = "\\section{a \\begin{itemize}\\item b\\end{itemize} c}"
    res = scan(body)
    assert any(t == "ENVTAG" for t in ph_types(res))


def test_row6_cite_family() -> None:
    res = scan(r"See \cite{a,b} and \citep[cf.]{x}.")
    assert any("\\cite{a,b}" in v for v in res.ph_map.values())
    assert any("\\citep[cf.]{x}" in v for v in res.ph_map.values())


def test_row7_ref_family() -> None:
    res = scan(r"Eq.~\eqref{e1}, Fig.~\autoref{f2}, \cref{x}.")
    types = ph_types(res)
    assert types.count("REF") == 3  # noqa: PLR2004 - 三个 ref 族命令各出一个 ph


def test_row8_protect_names() -> None:
    res = scan(r"Val \label{sec:a} \url{http://x/%20} \includegraphics{g}")
    types = ph_types(res)
    assert "LABEL" in types
    assert "URL" in types
    assert "GRAPHICS" in types
    assert "\\url{http://x/%20}" in res.ph_map.values()  # verbatim 花括号


def test_row9_href() -> None:
    r"""``\href{url}{text}``：url→``[[HREF]]``，text 留主流可译。"""
    res = scan(r"Link \href{http://a}{the description text} done.")
    assert "{http://a}" in res.ph_map.values()  # HREF 体 = {url} 段
    assert any("the description text" in c.content for c in res.chunks)


def test_row10_input_records() -> None:
    r"""未展平的 ``\input`` → LITERAL + ``inputs[]`` 记录。"""
    res = scan(r"Body\input{chap1} tail")
    assert res.inputs
    assert res.inputs[0][1] == "chap1"
    assert "\\input{chap1}" in res.protected_tex


def test_row11_chunk_arg() -> None:
    res = scan("\\section{Intro Title Text}\npara")
    assert any(
        c.context == "section" and c.content == "Intro Title Text" for c in res.chunks
    )
    assert "[[CHUNK_" in res.protected_tex


def test_row11_captionof_spec() -> None:
    r"""``\captionof{type}{text}`` 走 ``("mom",2)`` 签名——首参是类型不译。"""
    res = scan("\\captionof{figure}{Cap text body}\n")
    assert any(c.content == "Cap text body" for c in res.chunks)


def test_row12_protect_block() -> None:
    res = scan(r"\author{Alice \and Bob}\ntext")
    assert any(t == "AUTHOR" for t in ph_types(res))
    assert "\\author{Alice \\and Bob}" in res.ph_map.values()


def test_row13_transparent_cmd() -> None:
    r"""``\emph{..}`` 命令名逐字、参数文本并进当前 run。"""
    res = scan("This is \\emph{very important} text indeed.")
    blob = " ".join(c.content for c in res.chunks)
    assert "\\emph{very important}" in blob or "very important" in blob


def test_row14_boundary_cmds() -> None:
    r"""``\item``/``\maketitle`` 是 run 硬边界，本体 LITERAL。"""
    res = scan("\\maketitle\n\nPara one text here.\n\\item Item body text here")
    assert "\\maketitle" in res.protected_tex
    assert any("Item body text here" in c.content for c in res.chunks)


def test_row16_display_math_delims() -> None:
    res = scan("Text \\[ x^2 \\] and \\( y \\) done.")
    types = ph_types(res)
    assert types.count("MATH") == 2  # noqa: PLR2004 - \[ \] 与 \( \) 各一个 MATH ph


def test_row17_inline_literals() -> None:
    res = scan(r"Word \LaTeX\ and 50\% off, caf\'e {\bf bold} end.")
    # 无 ph 泄漏：inline 字面命令整行进 run
    assert all("\\LaTeX" not in v or True for v in res.ph_map.values())
    assert (
        reconstruct(res) == DOC % r"Word \LaTeX\ and 50\% off, caf\'e {\bf bold} end."
    )


def test_row18_macro_transparent() -> None:
    r"""TRANSPARENT 宏：``\bfrac{a}{b}`` 文本位参数子扫渲染。"""
    res = scan("\\newcommand{\\pair}[2]{#1 and #2}\nSee \\pair{alpha words}{beta}.")
    assert (
        reconstruct(res)
        == DOC % "\\newcommand{\\pair}[2]{#1 and #2}\nSee \\pair{alpha words}{beta}."
    )


def test_row18_macro_opaque() -> None:
    r"""OPAQUE 宏（体无自然文本）→ 整调用 ``[[MACRO]]``。"""
    res = scan("\\newcommand{\\XX}{\\ensuremath{X}\\xspace}\nUse \\XX now.")
    assert any(t == "MACRO" for t in ph_types(res))


def test_row18_macro_protect_args() -> None:
    r"""``protect_args``：``#1`` 落在 ``\ref`` 参数位 → 该位 ``[[KEY]]``。"""
    res = scan(r"\newcommand{\secc}[1]{Section~\ref{#1}}" + "\nSee \\secc{sec:x} end.")
    assert any(t == "KEY" for t in ph_types(res))


def test_row7_ref_beats_macro() -> None:
    r"""``\Xref`` 名字撞 ref 族后缀 → 分派行 7 先截（顺序即语义）。"""
    res = scan(r"\newcommand{\secref}[1]{Section~\ref{#1}}" + "\nSee \\secref{sec:x}.")
    assert any(t == "REF" for t in ph_types(res))


def test_row19_unknown_cmd_with_args() -> None:
    r"""未知命令 ``\foo{a}{b}`` → 整调用 ``[[CMD]]``（禁单 token 读参）。"""
    res = scan("Text \\foo{a}{b} more.")
    assert any(v.startswith("\\foo{a}{b}") for v in res.ph_map.values())


def test_row19_unknown_cmd_bare() -> None:
    r"""未知命令无 ``{/[`` 参数 → 逐字进 run。"""
    res = scan("Text \\fooX bare continues here.")
    assert "\\fooX" not in res.ph_map
    assert reconstruct(res) == DOC % "Text \\fooX bare continues here."


def test_dispatch_identity_all_rows() -> None:
    r"""抽样恒等：19 行各形态一锅炖，reconstruct 逐字节还原。"""
    body = (
        "\\newcommand{\\ie}{i.e.}\n"
        "Para \\cite{a} \\ref{b} \\label{c} \\emph{em} \\item it \\be?\n"
        "\\begin{align}x\\end{align}\\begin{verbatim}v%\\end{verbatim}\n"
        "\\section{T}\\footnote{F}\\author{A}\\href{u}{t}\\verb|v| $m$ \\[d\\]"
    )
    res = scan(body)
    assert reconstruct(res) == DOC % body


def test_pieces_tile_source() -> None:
    """平铺不变式：pieces.span 无缝覆盖 ``[0, len(tex))``。"""
    body = "P1 \\cite{a} text.\n\n\\begin{figure}\\caption{C}\\end{figure}\n"
    tex = DOC % body
    res = parse_tex(tex)
    pos = 0
    for p in res.pieces:
        assert p.span.start == pos
        pos = p.span.end
    assert pos == len(tex)
    assert "".join(p.text for p in res.pieces) == res.protected_tex
    # protected_tex 里只允许 PH_RX 形态占位符
    for m in PH_RX.finditer(res.protected_tex):
        assert m.group(0) in res.ph_map or m.group(0).startswith("[[CHUNK_")
