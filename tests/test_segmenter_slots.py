r"""非文本槽位保护回归 —— loop1 stagerun 五类腐蚀形态钉版。

取证现场 ``bench/results/stagerun-loop1-2026-09-16/``：407 格 terminal-partial
中 segmenter 把非文本槽位当 TEXT 段放出，mock 翻译体落进槽位即腐蚀：

1. 维度操作数（``illegal_unit`` ×138）：``\vskip3pt``/``\\[5pt]``/``\vspace{30pt}``
   的单位字母进 chunk → ``3这是译文``；
2. cs+text 黏连（``undefined_cs`` ×104，bug-B）：``\item FSU`` 的后随空格折进
   chunk，``.strip()`` 后重建成 ``\itemFSU``——首字母黏上 cs 名；
3. 名字槽位（``Undefined color`` ×2993/``No counter`` ×292/keyval ~19）：
   ``\textcolor{red}`` 的 ``{red}``、``\arabic{section}`` 的 ``{section}``
   被当可译文本；
4. ``\par``/换行进短参（×62）——xlat 侧归属（译文体内产 ``\par``），
   segmenter 只负责不把 ``\par`` 吞进参数（``ws_skip_arg`` 旧保障），此文件不钉；
5. array preamble（``Illegal pream-token`` ×12）：``\begin{tabu}{cc}`` 的
   格式参裸进 surface。

1e 追补两条同族实证（``bench/results/modec-misschar-2026-09-16/report.md``）：

6. ``_on_math`` 混排闭符（0806.1984 miss×12）：``$\alpha(x)\)`` 的 ``\)``
   不收闭符 → 越过真闭符吞散文、``$`` 奇偶翻转；
7. accent 参保护（0806.3144）：``\c{c}``/``\~n`` 的参字母被译成
   ``\c{这是译文}``——accent+CJK 恒无字槽。

每条用例过公共不变式：``reconstruct(res) == tex`` + ``validate_result`` 零告警
+ pieces 无缝平铺 ``[0, len(vtex))``。
"""

import pytest

from texlate.latex import parse_tex, reconstruct
from texlate.latex.model import PieceKind, ScanResult
from texlate.latex.reconstruct import validate_result

DOC = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}\n"


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


def scan(body: str) -> ScanResult:
    tex = DOC % body
    res = parse_tex(tex)
    check_invariants(res, tex)
    return res


def blob(res: ScanResult) -> str:
    return "\n".join(c.content for c in res.chunks)


# ------------------------------------------------------------- 类1 维度操作数


def test_slot_dimen_bare_operand() -> None:
    r"""``\vskip3pt``：BOUNDARY + dimen 尾扫 → 整体 LITERAL piece，单位不进 chunk。"""
    res = scan("Para text here enough words.\\vskip3pt Tail words here more.")
    assert any(
        p.kind is PieceKind.LITERAL and p.text == "\\vskip3pt" for p in res.pieces
    )
    assert "3pt" not in blob(res)


def test_slot_dimen_glue_plus_minus() -> None:
    r"""glue 形 ``\vskip 3pt plus 1pt``：``plus/minus`` 序一并罩住。"""
    res = scan("Para text here enough words.\\vskip 3pt plus 1pt Tail here.")
    assert any(
        p.kind is PieceKind.LITERAL and p.text == "\\vskip 3pt plus 1pt"
        for p in res.pieces
    )
    assert "plus" not in blob(res)


def test_slot_bsbs_dimen_opt() -> None:
    r"""``\\[5pt]``：单字符 cs 的维度 ``[opt]`` → ``[[CMD]]`` 罩整调用。"""
    res = scan("Line one words here.\\\\[5pt] Line two words here ok.")
    assert res.ph_map["[[CMD_1]]"] == "\\\\[5pt]"
    assert "5pt" not in blob(res)


def test_slot_bsbs_space_dimen_opt() -> None:
    r"""``\\ [5pt]``（星号位空白变体）同罩——``[5pt]`` 不落正文。"""
    res = scan("Line one words here.\\\\ [5pt] Line two words here ok.")
    assert res.ph_map["[[CMD_1]]"] == "\\\\ [5pt]"
    assert "5pt" not in blob(res)


def test_slot_bsbs_nondimen_stays_text() -> None:
    r"""保守面：``\\[x]`` 非维度 ``[opt]`` 不罩——原样留文本面（不扩大打击面）。"""
    res = scan("Line one \\\\[x] line two words here enough.")
    assert "\\\\[x]" in blob(res)
    assert not res.ph_map


def test_slot_vspace_brace_arg() -> None:
    r"""``\vspace{30pt}``：BOUNDARY_TAIL ``s m`` 组参 → 整调用 LITERAL。"""
    res = scan("Para text here enough words.\\vspace{30pt} Tail words here.")
    assert any(
        p.kind is PieceKind.LITERAL and p.text == "\\vspace{30pt}" for p in res.pieces
    )
    assert "30pt" not in blob(res)


def test_slot_dimen_assign_eq() -> None:
    r"""``\hangindent=.5em``：``=<atom>`` 赋值尾 → ``[[CMD]]`` 罩含等号整段。"""
    res = scan("Para text here enough words.\\hangindent=.5em Tail words.")
    assert res.ph_map["[[CMD_1]]"] == "\\hangindent=.5em"
    assert ".5em" not in blob(res)


def test_slot_kern_bare() -> None:
    r"""``\kern2em``：刚性 dimen 名裸操作数 → ``[[CMD]]``。"""
    res = scan("Para text here enough words.\\kern2em Tail words here more.")
    assert res.ph_map["[[CMD_1]]"] == "\\kern2em"
    assert "2em" not in blob(res)


def test_slot_dimen_cs_operand() -> None:
    r"""``\hskip \labelsep``：寄存器 cs 作操作数 → 尾扫覆盖整段 LITERAL。"""
    res = scan("Para text here enough words.\\hskip \\labelsep Tail words.")
    assert any(
        p.kind is PieceKind.LITERAL and p.text == "\\hskip \\labelsep"
        for p in res.pieces
    )
    assert "\\labelsep" not in blob(res)


def test_slot_rule_keywords() -> None:
    r"""``\vrule width 2pt``：``width|height|depth`` 序 → ``[[CMD]]`` 罩关键字+量。"""
    res = scan("Para text here enough words.\\vrule width 2pt Tail words.")
    assert res.ph_map["[[CMD_1]]"] == "\\vrule width 2pt"
    assert "width" not in blob(res)


def test_slot_font_decl() -> None:
    r"""``\font\myfont=cmr10 at 12pt``：字体声明 ``\cs=name at <dimen>`` 整罩。"""
    res = scan("Para text here enough words.\\font\\myfont=cmr10 at 12pt Tail.")
    assert res.ph_map["[[CMD_1]]"] == "\\font\\myfont=cmr10 at 12pt"
    assert "cmr10" not in blob(res)


def test_slot_assign_generic() -> None:
    r"""表外未知名 ``\foo=2pt``：通用 ``=<atom>`` 尾扫兜底 → ``[[CMD]]``。"""
    res = scan("Para text here enough words.\\foo=2pt Tail words here.")
    assert res.ph_map["[[CMD_1]]"] == "\\foo=2pt"
    assert "2pt" not in blob(res)


def test_slot_dimen_in_arg() -> None:
    r"""in_arg 同式：``\section{A \vskip3pt B}`` 内维度尾也罩 ``[[CMD]]``。"""
    res = scan("\\section{A \\vskip3pt B tail words here}")
    [c] = res.chunks
    assert c.content == "A [[CMD_1]] B tail words here"
    assert res.ph_map["[[CMD_1]]"] == "\\vskip3pt"


# ------------------------------------------------------------- 类2 cs+latin 黏连（bug-B）


def test_bugb_item_no_leading_space() -> None:
    r"""``\item FSU``：cs 吞掉的空格剖成字面 piece，chunk 无前导空——
    下游 ``.strip()`` 不再产 ``\itemFSU``。"""
    res = scan("Text \\begin{itemize}\\item FSU words here enough text.\\end{itemize}")
    [c] = res.chunks
    assert c.context == "item"
    assert c.content == "FSU words here enough text."


def test_bugb_par_comment_gap() -> None:
    r"""``\par%note\ni)``：注释+换行的间隙同样剖出——后段 chunk 即 ``i)``。"""
    res = scan("First para words here.\\par%note\ni) second item words here.")
    assert [c.content for c in res.chunks] == [
        "First para words here.",
        "i) second item words here.",
    ]


# ------------------------------------------------------------- 类3 名字槽位


def test_slot_textcolor_head() -> None:
    r"""``\textcolor{red}{text}``：``[o]{m}`` 头参进 ``[[CMD]]``，``{text}`` 留主流。"""
    res = scan("Para \\textcolor{red}{warning words here} tail more words.")
    [c] = res.chunks
    assert c.content == "Para [[CMD_1]]{warning words here} tail more words."
    assert res.ph_map["[[CMD_1]]"] == "\\textcolor{red}"
    assert "red" not in blob(res).replace("warning", "")


def test_slot_colorbox_head() -> None:
    r"""``\colorbox{blue}{text}`` 同式：颜色名保护、文本参数可译。"""
    res = scan("Para \\colorbox{blue}{warning words here} tail more words.")
    [c] = res.chunks
    assert c.content == "Para [[CMD_1]]{warning words here} tail more words."
    assert res.ph_map["[[CMD_1]]"] == "\\colorbox{blue}"


def test_slot_color_probe() -> None:
    r"""``\color{red}``：探针路（无族表登记）``{red}`` 随 ``[[CMD]]`` 罩住。"""
    res = scan("Para \\color{red} warning words here tail more words now.")
    assert res.ph_map["[[CMD_1]]"] == "\\color{red}"
    assert "red" not in blob(res)


def test_slot_counter_probe() -> None:
    r"""``\arabic{section}``：计数器名 ``{section}`` 进 ``[[CMD]]`` 不译。"""
    res = scan("Para \\arabic{section} warning words here tail more words.")
    assert res.ph_map["[[CMD_1]]"] == "\\arabic{section}"
    assert "section}" not in blob(res)


# ------------------------------------------------------------- 类5 env preamble


def test_slot_deluxetable_preamble() -> None:
    r"""``\begin{deluxetable}{lRLc}``：argspec env ``m o`` + ``body_role=protect``
    → 整段 ``[[ENV]]``，列规不进 surface；``\tablecaption`` 内挖照常。"""
    res = scan(
        "\\begin{deluxetable}{lRLc}\\tablecaption{Cap words here}"
        "a&b\\end{deluxetable}\nTail words here enough."
    )
    [env] = [v for k, v in res.ph_map.items() if k.startswith("[[ENV_")]
    assert env.startswith("\\begin{deluxetable}{lRLc}")
    assert env.endswith("\\end{deluxetable}")
    assert "\\tablecaption{[[CHUNK_" in env
    [cap] = [c for c in res.chunks if c.context == "tablecaption"]
    assert cap.content == "Cap words here"
    assert "lRLc" not in blob(res)


def test_slot_supertabular_preamble() -> None:
    r"""``\begin{supertabular}{cc}``：``o m`` 签名 ``{cc}`` 罩进 ``[[ENV]]``。"""
    res = scan("\\begin{supertabular}{cc}a&b\\end{supertabular}\nTail words here ok.")
    assert res.ph_map["[[ENV_1]]"] == (
        "\\begin{supertabular}{cc}a&b\\end{supertabular}"
    )
    assert "cc}" not in blob(res)


# ------------------------------------------------------------- 展开组内镜像
# ``_group_surface`` 对 ``_dispatch`` 的同构复刻：展开体里的同一批形态
# 也必须出占位——组内没有 LITERAL piece，一切走 ph。


def test_grp_dimen_bare_operand() -> None:
    r"""组内 ``\vskip3pt`` → ``[[CMD]]``（主流是 LITERAL piece，组内对应 ph）。"""
    res = scan("\\newcommand{\\vv}{pre \\vskip3pt post words here}\nText \\vv tail.")
    [c] = res.chunks
    assert c.content == " Text pre [[CMD_1]] post words here tail. "
    assert res.ph_map["[[CMD_1]]"] == "\\vskip3pt"


def test_grp_bsbs_dimen_opt() -> None:
    r"""组内 ``\\[5pt]`` → ``[[CMD]]`` 罩维度 ``[opt]``。"""
    res = scan("\\newcommand{\\vv}{pre \\\\[5pt] post words here}\nText \\vv tail.")
    assert res.ph_map["[[CMD_1]]"] == "\\\\[5pt]"


def test_grp_textcolor_head() -> None:
    r"""组内 ``\textcolor{red}{warn}``：头参罩 ``[[CMD]]``，``{warn}`` 留 surface。"""
    res = scan(
        "\\newcommand{\\vv}{pre \\textcolor{red}{warn words} post}\nText \\vv tail."
    )
    [c] = res.chunks
    assert c.content == " Text pre [[CMD_1]]{warn words} post tail. "
    assert res.ph_map["[[CMD_1]]"] == "\\textcolor{red}"


def test_grp_color_probe() -> None:
    r"""组内 ``\color{red}`` 探针 → ``[[CMD]]`` 罩 ``{red}``。"""
    res = scan("\\newcommand{\\vv}{pre \\color{red} post words here}\nText \\vv tail.")
    assert res.ph_map["[[CMD_1]]"] == "\\color{red}"


def test_grp_counter_probe() -> None:
    r"""组内 ``\arabic{section}`` → ``[[CMD]]`` 罩计数器名。"""
    res = scan(
        "\\newcommand{\\vv}{pre \\arabic{section} post words here}\nText \\vv tail."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\arabic{section}"


def test_grp_env_macro_args_eaten() -> None:
    r"""``\bea{c} x \eea``（env-macro 展开）：``{c}`` 列规随 ``[[MATH]]`` 罩住——
    hep-ph--0605151 实形，组内 begin 行参数不泄 surface。"""
    res = scan(
        "\\newcommand{\\bea}{\\begin{array}}\\newcommand{\\eea}{\\end{array}}\n"
        "\\bea{c} x \\eea Tail words here enough."
    )
    assert res.ph_map["[[MATH_1]]"] == "\\bea{c} x \\eea"


def test_grp_env_begin_opt_eaten() -> None:
    r"""组内 ``\begin{itemize}[noitemsep]``：``[opt]`` 版式参随 ``[[ENVTAG]]``
    罩住（``env_opt_is_format`` 门），不裸进 surface。"""
    res = scan(
        "\\newcommand{\\vv}{pre \\begin{itemize}[noitemsep]\\item x post\\end{itemize}}\n"
        "Text \\vv tail words."
    )
    assert res.ph_map["[[ENVTAG_1]]"] == "\\begin{itemize}[noitemsep]"
    assert "noitemsep" not in blob(res)


def test_grp_item_label_flows() -> None:
    r"""组内 ``\item[lab text]``：label 是可译文本，留 surface 不随 ``[[CMD]]``——
    spec=None 的 BOUNDARY 行漂移修复（此前 label 被误吃）。"""
    res = scan(
        "\\newcommand{\\vv}{\\begin{itemize}\\item[lab text] x post\\end{itemize}}\n"
        "Text \\vv tail words here."
    )
    [c] = res.chunks
    assert "[[CMD_2]][lab text] x post" in c.content
    assert res.ph_map["[[CMD_2]]"] == "\\item"


# ------------------------------------------------------------- 类6 混排数学闭符


def test_math_mixed_paren_closer() -> None:
    r"""``$\alpha(x)\), for all $p \in S$``（0806.1984 实形）：``\)`` 收闭
    第一个数学段，``, for all ``/`` and `` 回散文、后两 ``$..$`` 各成 ph——
    不收则 ``for all`` 落数学、``\p`` 裸进散文被译。"""
    res = scan("\\item $\\alpha(x)\\), for all $p \\in S$ and $g_1\\in G$ words.")
    assert res.ph_map["[[MATH_1]]"] == "$\\alpha(x)\\)"
    assert res.ph_map["[[MATH_2]]"] == "$p \\in S$"
    assert res.ph_map["[[MATH_3]]"] == "$g_1\\in G$"
    assert [c.content for c in res.chunks] == [
        "[[MATH_1]], for all [[MATH_2]] and [[MATH_3]] words."
    ]


def test_math_mixed_bracket_closer_display() -> None:
    r"""``$$x\]``：display 体内 ``\]`` 同收闭符（LaTeX 语义 ``\]`` 在数学
    态即 ``$$``），尾部散文不回吞。"""
    res = scan("Para $$x\\] tail words here enough more.")
    assert res.ph_map["[[MATH_1]]"] == "$$x\\]"
    assert "tail words" in blob(res)


def test_math_paren_text_arg_not_closed() -> None:
    r"""``\( .. \text{..)..} .. \)``：``\text`` 正文参体内 ``\)`` 不关外层
    数学——``_find_math_close_tok`` 同走 ``_math_skip_textarg`` 跳扫
    （wave-2 残余洞：不收则内层 ``\)`` 截断、后半落散文被译）。"""
    res = scan("Para \\(a + \\text{ if ) b } + c\\) tail words here.")
    assert res.ph_map["[[MATH_1]]"] == "\\(a + \\text{ if ) b } + c\\)"
    assert "tail words" in blob(res)


# ------------------------------------------------------------- 类7 accent 参


def test_accent_braced_arg() -> None:
    r"""``\c{c}``（0806.3144 实形）：整调用 ``[[CMD]]``——参字母 ``c`` 不进
    chunk 被译（cedilla+CJK 无预组字槽）。"""
    res = scan("Le\\c{c}ons sur la th\\'eorie tail words here.")
    assert res.ph_map["[[CMD_1]]"] == "\\c{c}"
    assert res.ph_map["[[CMD_2]]"] == "\\'e"
    assert "Le[[CMD_1]]ons" in blob(res)


def test_accent_bare_letter_arg() -> None:
    r"""``\~n``/``\c\i`` 单 token 参同罩——花括号缺席不构成逃生口。"""
    res = scan("Espa\\~na and \\c\\i words here enough.")
    assert res.ph_map["[[CMD_1]]"] == "\\~n"
    assert res.ph_map["[[CMD_2]]"] == "\\c\\i"


def test_accent_family_chars() -> None:
    r"""族面抽查：``\v``/``\H``/``\r``/``\d``/``\b``/``\k``/``\t``/``\=``/``\.``
    参均保护（``\r`` 本轮补入 ``ACCENT_CHARS``）。"""
    res = scan("N\\v{e}mec \\H{o} Dvo\\r{r}\\'ak \\d{o} \\k{a} x\\=y \\.z tail.")
    assert res.ph_map["[[CMD_1]]"] == "\\v{e}"
    assert res.ph_map["[[CMD_2]]"] == "\\H{o}"
    assert res.ph_map["[[CMD_3]]"] == "\\r{r}"
    assert res.ph_map["[[CMD_5]]"] == "\\d{o}"
    assert res.ph_map["[[CMD_6]]"] == "\\k{a}"
    assert res.ph_map["[[CMD_7]]"] == "\\=y"
    assert res.ph_map["[[CMD_8]]"] == "\\.z"


def test_accent_no_arg_stays_literal() -> None:
    r"""保守面：``\c`` 后随组闭（无参）→ 裸名内联字面，组结构不扰。"""
    res = scan("Text {\\it a\\c} tail words here enough more.")
    assert "{\\it a\\c}" in blob(res)
    assert not res.ph_map


def test_grp_accent_bare_arg() -> None:
    r"""组内 ``\~n`` 裸参形 → ``[[CMD]]``（``\c{c}`` 花括号形本由探针罩，
    裸参是组内镜像补齐的洞）。"""
    res = scan("\\newcommand{\\vv}{pre \\~n post words here}\nText \\vv tail.")
    assert res.ph_map["[[CMD_1]]"] == "\\~n"
    [c] = res.chunks
    assert "[[CMD_1]]" in c.content
