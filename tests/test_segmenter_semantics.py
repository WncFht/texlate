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
from conftest import ART, check_invariants

from texlate.latex import parse_file, parse_tex
from texlate.latex.gullet import Gullet
from texlate.latex.model import PieceKind, ScanResult

BEAMER = "\\documentclass{beamer}\n\\begin{document}\n%s\n\\end{document}\n"


@pytest.fixture(autouse=True)
def _pin_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 v2（Gullet+Segmenter）路径——外部 ``TEXLATE_NO_EXPAND`` 不串扰。"""
    monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)


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
    assert c.content == "Item words here."


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
    r"""``\par`` cs 经 gullet 转 eol_par——与空行同切段效果；cs 吞掉的空格
    剖成字面 piece，不折进后段 chunk（bug-B）。"""
    res = scan("First paragraph text here.\\par Second paragraph text here.")
    assert [c.content for c in res.chunks] == [
        "First paragraph text here.",
        "Second paragraph text here.",
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
    r"""``\def`` 体内 ``\par`` → eol_par 段界在 ``_close_group`` 重拼为同
    run ``\n\n`` 段内分隔（Option D 全或无发射——逐段冲刷会让空 ident
    尾段在 literal 路径丢结构字节）；ident 面 ``\twopara`` 只在
    ``[[EXPAND_1]]`` 出现一次（不重复还原）。"""
    res = scan(
        "Before \\twopara after.",
        "\\def\\twopara{First expanded part.\\par Second expanded part.}\n",
    )
    assert [c.content for c in res.chunks] == [
        " Before First expanded part.\n\nSecond expanded part. after. ",
    ]
    assert res.ph_map["[[EXPAND_1]]"] == "\\twopara"
    assert res.ph_map["[[CHUNK_0]]"] == "\nBefore [[EXPAND_1]] after.\n"


def test_expand_long_def_blank_line_splits() -> None:
    r"""``\long\def`` + 真空行：展开体内空行同走 eol_par→``\n\n`` 合段。"""
    res = scan(
        "Before \\twopara after.",
        "\\long\\def\\twopara{First expanded part.\n\nSecond expanded part.}\n",
    )
    assert len(res.chunks) == 1
    assert "First expanded part." in res.chunks[0].content
    assert "Second expanded part." in res.chunks[0].content


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
    → 命令名/括号字面段成 ``[[CMD]]`` 代位，text 参仍内联进 content
    （M1：lit 段不再进 run surface——``\rotatebox[origin=c]{90}`` 的
    ``[origin=c]`` 同款字面段曾在参内被译）。"""
    res = scan("\\section{Title \\alert{inner words} rest} tail.")
    [c] = res.chunks
    assert c.content == "Title [[CMD_1]]inner words[[CMD_2]] rest"
    assert res.ph_map["[[CMD_1]]"] == "\\alert{"
    assert res.ph_map["[[CMD_2]]"] == "}"


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


def test_hyperref_argspec_chunk_arg_two_forms() -> None:
    r"""``\hyperref``（hyperref ``m m`` key+text）自 ``*ref`` 后缀规则放出
    交 argspec——mand=1 REF 会把 ``[label]{text}`` 的 text 吞进 ``[[REF]]``。
    ``m`` 签名项兼收 ``[`` 组：文档形 ``[label]{text}`` 与民间
    ``{label}{text}`` 皆 key 位留字面、text 位出 chunk ctx=hyperref。"""
    res = scan(
        "Text \\hyperref[sec:x]{Bracket Words Here} end.",
        "\\usepackage{hyperref}\n",
    )
    [c] = [c for c in res.chunks if c.context == "hyperref"]
    assert c.content == "Bracket Words Here"
    assert "\\hyperref[sec:x]{[[CHUNK_0]]}" in res.protected_tex

    res2 = scan(
        "Text \\hyperref{sec:x}{Brace Words Here} end.",
        "\\usepackage{hyperref}\n",
    )
    [c2] = [c for c in res2.chunks if c.context == "hyperref"]
    assert c2.content == "Brace Words Here"
    assert "\\hyperref{sec:x}{[[CHUNK_0]]}" in res2.protected_tex


def test_family_ref_suffix_still_shadows_key_only_refs() -> None:
    r"""对照：``*ref`` 后缀规则对 key-only 宏不变——``\autoref{sec:x}``
    （argspec 有同名 hyperref ``s m`` key 条目）仍整调用 ``[[REF]]``，
    不走路19 argspec。"""
    res = scan(
        "Text \\autoref{sec:x} more words here.",
        "\\usepackage{hyperref}\n",
    )
    [c] = res.chunks
    assert c.content == "Text [[REF_1]] more words here."
    assert res.ph_map["[[REF_1]]"] == "\\autoref{sec:x}"
    assert all(c.context != "autoref" for c in res.chunks)


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


# ------------------------------------------------------- 弹栈尾盖闸


def test_popped_source_cover_skips_buffered_fid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r"""源弹栈 ≠ fid 枯竭：``\\section{..\\hyperbaseurl{u%20}..}`` 的 ``%``
    吃掉闭括号 → 参读拉穿 EOF → fid-0 源被 ``read()`` 提前弹栈，回放 token
    躺合成回放源 ``tokbuf``——弹栈尾盖若抢跑会把 fid 余下字节一次盖掉，
    回放分派的 ``_cover_to`` 全零宽 → ph 空体 → 整段 LITERAL（#169 flake
    原形，曾以 ~1/20 概率随机现）。

    触发本是 ``id()`` 地址复用概率事件：合成源落在刚释放主源地址上时
    ``id`` 碰撞把弹栈遮蔽成"仍在栈"。``unread`` 前垫一批短生命周期对象
    抢占 freelist——回放源落他址、遮蔽失效，无闸代码路径下确定性全灭。
    """
    real_unread = Gullet.unread

    def unread_pad(self: Gullet, toks: list) -> None:
        _pad = [bytearray(64) for _ in range(96)]
        real_unread(self, toks)

    monkeypatch.setattr(Gullet, "unread", unread_pad)
    for _ in range(10):
        res = scan(
            "Text \\section{See \\hyperbaseurl{u%20} rest of title} tail.",
            "\\usepackage{hyperref}\n",
        )
        assert res.ph_map["[[CMD_1]]"] == "\\hyperbaseurl{u%20}"
