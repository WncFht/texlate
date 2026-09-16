r"""分段器 S3 语义黑盒测试 —— ``parse_tex``/``parse_file`` 端到端。

规格来源：``docs/research/latex/segmenter-integration.md`` + docs/07 §3。
覆盖（与 test_latex_argspec.py 的表/门控冒烟互补，不重复）：

- 组边界：``{...}`` 不泄 chunk、``\def`` 作用域不出组、eol_par 跨括号切段
- 保护段：math/verb/env → ``[[TYPE_n]]`` 占位 + ph_map 本体，净字零泄漏
- run 双轨：surface→``chunk.content``、ident→``[[CHUNK_k]]``/``[[EXPAND_n]]``
  ph_map 回退（reconstruct 优先级 trans→ph_map→content）
- ``\usepackage`` 位置门控 + 族表压 argspec 优先级
- ``parse_file`` ``\input`` flatten / flatten=False

公共不变式（每条用例都过）：pieces 无缝平铺 ``[0, len(vtex))`` +
``reconstruct(res) == tex`` + ``validate_result`` 零告警。
"""

from pathlib import Path

import pytest

from texlate.latex import parse_file, parse_tex, reconstruct
from texlate.latex.model import PieceKind, ScanResult
from texlate.latex.reconstruct import validate_result

ART = "\\documentclass{article}\n%s\\begin{document}\n%s\n\\end{document}\n"
BEAMER = "\\documentclass{beamer}\n\\begin{document}\n%s\n\\end{document}\n"


@pytest.fixture(autouse=True)
def _pin_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 v2（Gullet+Segmenter）路径——外部 ``TEXLATE_NO_EXPAND`` 不串扰。"""
    monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)


def check_invariants(res: ScanResult, tex: str) -> None:
    """公共断言：恒等重建 + 校验零告警 + pieces 无缝平铺 vtex。"""
    assert reconstruct(res) == tex
    assert validate_result(res) == []
    pos = 0
    for p in res.pieces:
        assert p.span.start == pos
        pos = p.span.end
    assert pos == len(res.vtex)


def scan(body: str, preamble: str = "", doc: str = ART) -> ScanResult:
    tex = doc % (preamble, body) if doc is ART else doc % body
    res = parse_tex(tex)
    check_invariants(res, tex)
    return res


# ------------------------------------------------------------- 组边界


def test_group_nested_braces_in_chunk_arg() -> None:
    r"""``\section{A {nested} title}``：match_brace 配对——内组不截断参数。"""
    res = scan("Text \\section{A {nested} title} tail here.")
    [c] = [c for c in res.chunks if c.context == "section"]
    assert c.content == "A {nested} title"


def test_group_inline_braces_stay_in_run() -> None:
    r"""裸 ``{...}`` 组不开边界：花括号字面进 chunk，前后文本同段。"""
    res = scan("Before {inside group words} after text here.")
    [c] = res.chunks
    assert c.content == "Before {inside group words} after text here."


def test_group_def_scope_does_not_escape() -> None:
    r"""``{\def\zz{..} A \zz B} then \zz``：组内 ``\zz`` 展开出 ``[[EXPAND]]``；
    组外 ``\zz`` 宏已弹栈 → 字面进 chunk——宏作用域不出组。"""
    res = scan("{\\def\\zz{ZZ ZZ ZZ} A \\zz B} then \\zz tail text.")
    assert res.ph_map["[[EXPAND_1]]"] == "\\zz"
    [c] = res.chunks
    assert "ZZ ZZ ZZ" in c.content  # 组内展开文
    assert "\\zz" in c.content  # 组外 \zz 字面（未展开）
    assert res.ph_map["[[CHUNK_0]]"] == " A [[EXPAND_1]] B} then \\zz tail text.\n"


def test_group_eol_par_splits_across_braces() -> None:
    r"""``{a\n\nb}``：eol_par 不敬括号——run 在组内一分为二。"""
    res = scan("Text {first words here\n\nsecond words here} tail.")
    assert [c.content for c in res.chunks] == [
        "Text {first words here",
        "second words here} tail.",
    ]


def test_chunk_arg_par_inside_braces_stays_content() -> None:
    r"""``\section{A\n\nB}``：参数按配对括号读取——par 留在 chunk content。"""
    res = scan("Text \\section{Title one\n\nTitle two} tail here.")
    [c] = [c for c in res.chunks if c.context == "section"]
    assert c.content == "Title one\n\nTitle two"


def test_chunk_arg_boundary_footnote() -> None:
    r"""``\footnote{..}`` 恰罩参数区间——后句另起 chunk，不混段。"""
    res = scan("A sentence.\\footnote{Note text words} Next sentence here.")
    [note] = [c for c in res.chunks if c.context == "footnote"]
    assert note.content == "Note text words"
    assert all("Next sentence" not in c.content for c in res.chunks if c is note)


def test_env_inside_braces_still_dispatches() -> None:
    r"""``{\begin{itemize}..\end{itemize}}``：括号组不阻断 env 追踪——
    begin/end 行字面、``\item`` 出 chunk env=itemize。"""
    res = scan("Text {\\begin{itemize}\\item Item words here.\\end{itemize}} tail.")
    [c] = res.chunks
    assert c.context == "item"
    assert c.env == "itemize"
    assert c.content == " Item words here."


# ------------------------------------------------------------- 保护段


def test_protect_inline_math() -> None:
    r"""``$..$`` → ``[[MATH_1]]`` 占位进 run；ph_map 本体含定界符。"""
    res = scan("Text $x^2 + y$ more words here.")
    [c] = res.chunks
    assert c.content == "Text [[MATH_1]] more words here."
    assert c.placeholders == ["[[MATH_1]]"]
    assert res.ph_map["[[MATH_1]]"] == "$x^2 + y$"


def test_protect_math_env_and_delim() -> None:
    r"""``equation`` env 与 ``\[..\]`` 同出 ``[[MATH]]``——本体罩整段。"""
    res = scan("Text\n\\begin{equation}x = 1\\end{equation}\nmore words here.")
    assert res.ph_map["[[MATH_1]]"] == "\\begin{equation}x = 1\\end{equation}"
    res2 = scan("Text \\[x = 1\\] more words here.")
    assert res2.ph_map["[[MATH_1]]"] == "\\[x = 1\\]"


def test_protect_verb_inline() -> None:
    r"""``\verb|..|`` → ``[[VERB]]``——``%`` 在定界体内不视作注释。"""
    res = scan("Text \\verb|a%b| more words here.")
    assert res.ph_map["[[VERB_1]]"] == "\\verb|a%b|"


def test_protect_verbatim_env_standalone_piece() -> None:
    r"""``verbatim`` env → 独立 PROTECTED piece；体内伪 ``\end{document}``
    不截断、``%`` 不成注释；本区零 chunk。"""
    res = scan(
        "Text\n\\begin{verbatim}a % not comment \\end{document}\n\\end{verbatim}\nmore."
    )
    body = res.ph_map["[[VERB_1]]"]
    assert body.startswith("\\begin{verbatim}")
    assert "\\end{document}" in body  # 伪 end 被 verbatim 体吞掉
    assert body.endswith("\\end{verbatim}")
    assert PieceKind.PROTECTED in [p.kind for p in res.pieces]


def test_protect_figure_env_caption_mined() -> None:
    r"""``figure``（PROTECTED_ENVS）→ ``[[ENV]]`` 整段；``\caption`` 参数
    被挖掘出独立 chunk（ctx=caption env=figure），env 本体内嵌
    ``[[CHUNK_k]]`` 引用。"""
    res = scan(
        "Text\n\\begin{figure}\\caption{A caption here}\\end{figure}\nmore words."
    )
    assert (
        res.ph_map["[[ENV_1]]"] == "\\begin{figure}\\caption{[[CHUNK_0]]}\\end{figure}"
    )
    [cap] = [c for c in res.chunks if c.context == "caption"]
    assert cap.content == "A caption here"
    assert cap.env == "figure"


def test_itemize_item_context() -> None:
    r"""``\item`` 切段：ctx=item、env=itemize；短项 force_chunk 仍出。"""
    res = scan(
        "\\begin{itemize}\n\\item First item words here.\n"
        "\\item Second item words.\n\\end{itemize}"
    )
    items = [c for c in res.chunks if c.context == "item"]
    assert len(items) == 2  # noqa: PLR2004
    assert all(c.env == "itemize" for c in items)
    assert "First item words here." in items[0].content


def test_unknown_env_top_level_transparent() -> None:
    r"""未知 env 顶层透明：begin/end 行字面、体出 chunk env=fooenv。"""
    res = scan("Text\n\\begin{fooenv}Body words inside here.\\end{fooenv}\nmore text.")
    assert "\\begin{fooenv}" in res.protected_tex
    assert "\\end{fooenv}" in res.protected_tex
    [c] = [c for c in res.chunks if "Body words inside here." in c.content]
    assert c.env == "fooenv"


def test_unknown_env_in_arg_becomes_env_ph() -> None:
    r"""未知 env 落在 ``\section{..}`` 参数内 → 整 env ``[[ENV_n]]`` 嵌进
    chunk content——环境不穿透参数边界（in_arg 泄漏修复口径）。"""
    res = scan("\\section{Title \\begin{fooenv}body words\\end{fooenv} end} tail.")
    [c] = res.chunks
    assert c.context == "section"
    env_ph = next(k for k in res.ph_map if k.startswith("[[ENV"))
    assert res.ph_map[env_ph] == "\\begin{fooenv}body words\\end{fooenv}"
    assert env_ph in c.content


def test_comment_in_arg_ph() -> None:
    r"""参数内 ``%`` 注释 → ``[[COMMENT_n]]`` 占位留 content（泄漏 B 修复）。"""
    res = scan("\\section{Title % cut this\nrest words} tail text.")
    [c] = res.chunks
    assert c.placeholders == ["[[COMMENT_1]]"]
    assert res.ph_map["[[COMMENT_1]]"] == "% cut this"
    assert c.content == "Title [[COMMENT_1]]\nrest words"


def test_macro_call_in_arg_not_expanded() -> None:
    r"""参数收集走原始 ``read()`` 流：``\section{..\sw{x}..}`` 内 ``\sw``
    不经 gullet 展开——探针档 ``[[CMD]]`` 罩 ``\sw{x}`` 整调用。"""
    res = scan("\\section{Title \\sw{x} rest words} tail.", "\\def\\sw#1{SWAP#1}\n")
    [c] = res.chunks
    assert c.content == "Title [[CMD_1]] rest words"
    assert res.ph_map["[[CMD_1]]"] == "\\sw{x}"


# --------------------------------------------------- run 双轨 / eol_par


def test_eol_par_blank_line_splits() -> None:
    r"""空行 → eol_par：一段 run 劈两个 ``para`` chunk。"""
    res = scan("First paragraph text here.\n\nSecond paragraph text here.")
    assert [c.content for c in res.chunks] == [
        "First paragraph text here.",
        "Second paragraph text here.",
    ]
    assert all(c.context == "para" for c in res.chunks)


def test_eol_par_cs_splits() -> None:
    r"""``\par`` cs 经 gullet 转 eol_par——与空行同切段效果（后段留前导空）。"""
    res = scan("First paragraph text here.\\par Second paragraph text here.")
    assert [c.content for c in res.chunks] == [
        "First paragraph text here.",
        " Second paragraph text here.",
    ]


def test_expand_surface_and_phmap_fallback() -> None:
    r"""展开组双轨：``chunk.content`` = surface（展开文），``ph_map[[CHUNK_k]]``
    = ident（``[[EXPAND_1]]`` 回溯 ``\frag`` 调用点 vtex 切片）。"""
    res = scan("Text \\frag end of line.", "\\def\\frag{expanded words here}\n")
    [c] = res.chunks
    assert c.content == " Text expanded words here end of line. "
    assert res.ph_map["[[EXPAND_1]]"] == "\\frag"
    assert res.ph_map["[[CHUNK_0]]"] == "\nText [[EXPAND_1]] end of line.\n"


def test_expand_par_inside_def_splits_run() -> None:
    r"""``\def`` 体内 ``\par`` → eol_par 作虚拟段分隔：一次调用产两段 chunk；
    ident 面 ``\twopara`` 只在 ``[[EXPAND_1]]`` 出现一次（不重复还原）。"""
    res = scan(
        "Before \\twopara after.",
        "\\def\\twopara{First expanded part.\\par Second expanded part.}\n",
    )
    assert [c.content for c in res.chunks] == [
        " Before First expanded part.",
        "Second expanded part. after. ",
    ]
    assert res.ph_map["[[EXPAND_1]]"] == "\\twopara"
    assert res.ph_map["[[CHUNK_0]]"] == "\nBefore [[EXPAND_1]]"
    assert res.ph_map["[[CHUNK_1]]"] == " after.\n"


def test_expand_long_def_blank_line_splits() -> None:
    r"""``\long\def`` + 真空行：展开体内空行同样转 eol_par 切段。"""
    res = scan(
        "Before \\twopara after.",
        "\\long\\def\\twopara{First expanded part.\n\nSecond expanded part.}\n",
    )
    assert len(res.chunks) == 2  # noqa: PLR2004
    assert "First expanded part." in res.chunks[0].content
    assert "Second expanded part." in res.chunks[1].content


def test_expand_regenerated_protection() -> None:
    r"""展开面再生保护：``\frag`` 体内的 ``\cite``/``$math$`` 在 surface
    侧重新出 ``[[CITE]]``/``[[MATH]]`` 占位（全局计数器连号）。"""
    res = scan(
        "Text \\frag end of line.",
        "\\def\\frag{see \\cite{key1} math $x$}\n",
    )
    [c] = res.chunks
    assert c.content == " Text see [[CITE_1]] math [[MATH_2]] end of line. "
    assert res.ph_map["[[CITE_1]]"] == "\\cite{key1}"
    assert res.ph_map["[[MATH_2]]"] == "$x$"
    assert res.ph_map["[[EXPAND_3]]"] == "\\frag"


def test_expand_nested_single_expand() -> None:
    r"""嵌套展开只出最外 ``[[EXPAND_1]]``→``\outer``——inner 调用点在组内、
    零宽不外发占位；cs 后空白按 TeX 规则吸收（``INNER TEXT``+`` DONE``）。"""
    res = scan(
        "Text \\outer end.",
        "\\def\\inner{INNER TEXT}\\def\\outer{OUTER \\inner DONE}\n",
    )
    [c] = res.chunks
    assert c.content == " Text OUTER INNER TEXTDONE end. "
    assert res.ph_map["[[EXPAND_1]]"] == "\\outer"
    assert "[[EXPAND_2]]" not in res.ph_map


def test_expand_short_run_stays_literal_with_expand_ph() -> None:
    r"""短 run 落 LITERAL piece 仍持 ``[[EXPAND]]``——ident 面经 ph_map
    重建（LITERAL text 是渲染形，可内嵌占位符）。"""
    res = scan("Ok \\frag.", "\\def\\frag{zz}\n")
    assert not res.chunks
    assert any(
        "[[EXPAND_1]]" in p.text for p in res.pieces if p.kind is PieceKind.LITERAL
    )
    assert res.ph_map["[[EXPAND_1]]"] == "\\frag"


# ------------------------------------------- ph_map 回退（argspec chunk-arg）


def test_argspec_chunk_arg_phmap_fallback() -> None:
    r"""argspec chunk-arg：``\frametitle`` 参数子扫再生 ``[[CITE]]``/``[[MATH]]``；
    in_arg chunk 的 ident 面即 ``vtex[span]`` 原始参数切片——无需
    ``ph_map[[CHUNK_k]]`` 回退（回退只对展开组内 chunk 生效）。"""
    res = scan("Text \\frametitle{Title with \\cite{kk} and $x$} end.", doc=BEAMER)
    [c] = res.chunks
    assert c.context == "frametitle"
    assert c.content == "Title with [[CITE_1]] and [[MATH_2]]"
    assert res.ph_map["[[CITE_1]]"] == "\\cite{kk}"
    assert res.ph_map["[[MATH_2]]"] == "$x$"
    assert res.vtex[c.span.start : c.span.end] == "Title with \\cite{kk} and $x$"
    assert "[[CHUNK_0]]" not in res.ph_map


def test_chunk_arg_key_role_stays_literal() -> None:
    r"""``key`` 位不出 chunk：``\hyperlink{sec:k}{text}``——key 位留
    protected_tex 字面，仅 text 位独立成段。"""
    res = scan(
        "Text \\hyperlink{sec:intro}{Jump to section} end.",
        "\\usepackage{hyperref}\n",
    )
    [c] = [c for c in res.chunks if c.context == "hyperlink"]
    assert c.content == "Jump to section"
    assert "\\hyperlink{sec:intro}{" in res.protected_tex


def test_chunk_arg_nested_in_arg_inlines() -> None:
    r"""in_arg 侧 chunk-arg 不另开段：``\section{T \alert{inner} rest}``
    → ``\alert{..}`` 整体内联进 content（括号保留，不挖洞）。"""
    res = scan("\\section{Title \\alert{inner words} rest} tail.")
    [c] = res.chunks
    assert c.content == "Title \\alert{inner words} rest"


# ------------------------------------------------------- \usepackage 门控


def test_usepackage_positional_gating() -> None:
    r"""``\usepackage`` 位置语义：加载点前 ``\frametitle`` 未知 → 探针
    ``[[CMD]]``；加载点后 → argspec chunk-arg（pkgs 集按分派时刻读取）。"""
    tex = (
        "Text \\frametitle{Early Title} mid.\n"
        "\\usepackage{beamer}\n"
        "Text \\frametitle{Late Title} end."
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert res.ph_map["[[CMD_1]]"] == "\\frametitle{Early Title}"
    assert any(
        c.context == "frametitle" and c.content == "Late Title" for c in res.chunks
    )


def test_usepackage_in_document_body() -> None:
    r"""``\usepackage`` 在 document 体内同样登记（boundary 路径补记 pkgs）。"""
    res = scan(
        "First para text goes here.\n\\usepackage{mathtools}\n"
        "Text \\ArrowBetweenLines more words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\ArrowBetweenLines"


def test_usepackage_comma_list_registers_all() -> None:
    r"""逗号名单逐包登记：``{amsmath,mathtools}`` → mathtools 宏命中。"""
    res = scan(
        "Text \\ArrowBetweenLines more words here.",
        "\\usepackage{amsmath,mathtools}\n",
    )
    assert res.ph_map["[[CMD_1]]"] == "\\ArrowBetweenLines"


# --------------------------------------------------------- 族表优先级


def test_family_env_mandatory_arg_beats_argspec_protect() -> None:
    r"""族表优先于 argspec env 路由：``subfigure``（argspec body=protect
    但 ∈ ENV_MANDATORY_ARG）维持透明——``{w}`` 必参吞进 begin 行字面、
    体出 chunk env=subfigure。"""
    res = scan(
        "Before\n\\begin{subfigure}{.5\\linewidth}"
        "Body text with many more words inside.\\end{subfigure}\nafter text here."
    )
    assert "\\begin{subfigure}{.5\\linewidth}" in res.protected_tex
    [c] = [c for c in res.chunks if c.env == "subfigure"]
    assert "Body text with many more words inside." in c.content


def test_family_verbatim_beats_argspec_protect() -> None:
    r"""``filecontents``（argspec protect 但 ∈ VERBATIM_ENVS）→ ``[[VERB]]``；
    ``\end`` 行锚定收尾，体内 ``%`` 不成注释。"""
    res = scan(
        "Before\n\\begin{filecontents}{x.bib}line % pct\n\\end{filecontents}\nafter."
    )
    body = res.ph_map["[[VERB_1]]"]
    assert body.startswith("\\begin{filecontents}{x.bib}")
    assert "line % pct" in body
    assert body.endswith("\\end{filecontents}")


def test_family_ref_suffix_beats_argspec_chunk_arg() -> None:
    r"""名后缀族规则压 argspec：``\hyperref``（hyperref ``o m m`` key+text）
    以 ``*ref`` 后缀命中 REF 族——``[[REF]]`` 只罩 ``{key}`` 位，text 位
    带括号留在 run（argspec 独立 chunk 路径不生效）。"""
    res = scan(
        "Text \\hyperref{sec:x}{Ref Words Here} end.",
        "\\usepackage{hyperref}\n",
    )
    [c] = res.chunks
    assert c.content == "Text [[REF_1]]{Ref Words Here} end."
    assert res.ph_map["[[REF_1]]"] == "\\hyperref{sec:x}"
    assert all(c.context != "hyperref" for c in res.chunks)


# ------------------------------------------------------------- parse_file


def test_parse_file_input_flatten(tmp_path: Path) -> None:
    r"""``\input`` flatten：子文件内容并入 vtex（inputs 记 vpos+绝对路径）；
    文件边 run 跨单个 ``\n`` 合并成同一 chunk。"""
    sub = tmp_path / "sub.tex"
    sub.write_text(
        "Sub file paragraph words here.\n\nSecond sub para words.",
        encoding="utf-8",
    )
    main = tmp_path / "main.tex"
    tex = ART % (
        "",
        (
            "Intro words go here with a longer sentence.\n"
            "\\input{sub}\nOutro words here."
        ),
    )
    main.write_text(tex, encoding="utf-8")
    res = parse_file(main)
    check_invariants(res, res.vtex)
    assert res.inputs[0][1] == str(sub)
    contents = [c.content for c in res.chunks]
    assert any("Intro words go here" in c for c in contents)
    assert any("Sub file paragraph words here." in c for c in contents)
    merged = [c for c in contents if "Second sub para words." in c]
    assert "Outro words here." in merged[0]


def test_parse_file_flatten_false(tmp_path: Path) -> None:
    r"""``flatten=False``：``\input{sub}`` 字面保留 + inputs 记相对名 +
    ``missing_input`` 告警。"""
    (tmp_path / "sub.tex").write_text("sub", encoding="utf-8")
    main = tmp_path / "main.tex"
    main.write_text(
        ART % ("", "Intro words go here.\n\\input{sub}\nOutro words here."),
        encoding="utf-8",
    )
    res = parse_file(main, flatten=False)
    assert "\\input{sub}" in res.protected_tex
    assert res.inputs[0][1] == "sub"
    assert any(w.kind == "missing_input" for w in res.warnings)
