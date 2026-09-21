r"""B5a nested-docclass 注入缝钉（0812.0615 lang10.tex 实证）。

``\documentclass`` 藏进 ``\IfFileExists{cls}{..}{..}`` 可执行组/条件实参内
（depth>0）时，旧 depth-0-only 口径零缝 → ``inject_cjk`` 记 no-docline、
``_inject_after_docclass`` 走头注使 prologue 落 ``\documentclass`` 之前
（``\usepackage`` 头注 = Missing ``\begin{document}`` 级联烧轮次）。

新口径：可执行组/条件实参内的 depth>0 命中产出缝——缝位 = **整个构造的
depth-0 收尾**：``_nested_construct_end`` 扫到最外包容组闭 ``}`` 后，再吞
同构造紧随的 ``{..}``/``[..]`` 实参（``\IfFileExists`` arg3），prologue
落构造全闭之后、任臂皆在真声明后；停在 arg2 闭 ``}`` 会被当 arg3 扫走。
宏体（``\newcommand``/``\def`` 体内）命中仍非真声明点——跳过归 proxy 缝。
depth-0 命中行为字节级不变。
"""

from pathlib import Path

from _fixloopkit import mk_ctx

from texlate.compile._seams import find_docclass_ends
from texlate.compile.fixloop._builtins_common import _inject_after_docclass
from texlate.compile.inject import inject_cjk

_DOC = "\\begin{document}\nx\n\\end{document}\n"

#: 0812.0615 lang10.tex 同构单行形——docclass 藏 ``\IfFileExists`` 两臂。
_HIDDEN_1LINE = (
    "\\IfFileExists{mycls.cls}{\\documentclass{mycls}}{\\documentclass{article}}\n"
    + _DOC
)

#: lang10.tex 多行形——arg2 内含嵌套 ``\IfFileExists``/``\usepackage``，
#: arg3 跨行 ``\message`` + docclass + ``\let`` 尾码。
_HIDDEN_MULTILINE = (
    "\\NeedsTeXFormat{LaTeX2e}\n"
    "\\newif\\ifsmfart\n"
    "\\IfFileExists{smfart.cls}\n"
    "  {\\documentclass[12pt,english]{smfart}\n"
    "   \\IfFileExists{smfenum.sty}{\\usepackage{smfenum}}{}\n"
    "    \\usepackage{bull}\n"
    "    \\smfarttrue}\n"
    "{\\message{^^J*** warn ***^^J}\n"
    "\n"
    "\n"
    "\\documentclass[12pt]{amsart}\\let\\Subsection\\subsection}\n"
    "\\setcounter{tocdepth}{1}\n" + _DOC
)


def test_iffileexists_both_branches_single_seam() -> None:
    r"""两臂各藏 docclass → 去重单缝，落 ``\IfFileExists{..}{..}{..}`` 全闭后行尾。"""
    hits = find_docclass_ends(_HIDDEN_1LINE)
    assert len(hits) == 1
    pos, lineno, cmd = hits[0]
    assert cmd == "documentclass"
    assert lineno == 1
    # 缝 pos = arg3 闭 ``}`` 后的 ``\n``——构造文本逐字节完好。
    assert _HIDDEN_1LINE[:pos].endswith("{article}}")
    assert _HIDDEN_1LINE[pos] == "\n"


def test_iffileexists_multiline_seam_after_arg3() -> None:
    """多行形 docclass 分藏 arg2/arg3 → 单缝落 arg3 闭 ``}`` 行尾（非 arg2 后）。

    停在 arg2 闭 ``}`` 会把注入物当 ``\\IfFileExists`` 的 arg3 扫走——
    本钉锁死「吞完同构造尾随实参」语义。
    """
    hits = find_docclass_ends(_HIDDEN_MULTILINE)
    assert len(hits) == 1
    pos, lineno, _cmd = hits[0]
    # 缝落在 arg3 闭 ``}``（``\subsection}`` 行）的行尾——其前是 arg3 全文。
    assert _HIDDEN_MULTILINE[:pos].endswith("\\subsection}")
    assert _HIDDEN_MULTILINE[pos] == "\n"
    assert lineno == _HIDDEN_MULTILINE[:pos].count("\n") + 1


def test_depth0_docclass_byte_identical() -> None:
    """depth-0 路径字节级不变——简单声明、``\\ifpdf`` 双臂、裸声明三形态。"""
    assert find_docclass_ends("\\documentclass{article}\nx\n") == [
        (23, 1, "documentclass")
    ]
    two = "\\ifpdf\n\\documentclass{a}\n\\else\n\\documentclass{b}\n\fi\nx\n"
    hits = find_docclass_ends(two)
    assert [c for _, _, c in hits] == ["documentclass", "documentclass"]
    assert all(two[p] == "\n" for p, _, _ in hits)
    assert find_docclass_ends("\\documentclass\nrest\n") == [(14, 1, "documentclass")]


def test_nested_bare_group() -> None:
    """裸组 ``{\\doclass}`` —— 可执行组内命中产缝，落组闭 ``}`` 行尾。"""
    tex = "{\\documentclass{a}}\n" + _DOC
    hits = find_docclass_ends(tex)
    assert len(hits) == 1
    pos = hits[0][0]
    assert tex[:pos].endswith("{a}}")
    assert tex[pos] == "\n"


def test_nested_executable_arg() -> None:
    r"""``\ifmain{\doclass}{}`` 条件实参内命中 → 缝落全部尾随实参之后。"""
    tex = "\\ifmain{\\documentclass{a}}{}\n" + _DOC
    hits = find_docclass_ends(tex)
    assert len(hits) == 1
    pos = hits[0][0]
    assert tex[:pos].endswith("{}")
    assert tex[pos] == "\n"


def test_nested_deeper_group() -> None:
    r"""更深嵌套 ``{\ifx\a\b{\doclass}\fi}`` —— 缝落**最外**包容组闭 ``}`` 后。"""
    tex = "{\\ifx\\a\\b{\\documentclass{a}}\\fi}\n" + _DOC
    hits = find_docclass_ends(tex)
    assert len(hits) == 1
    pos = hits[0][0]
    assert tex[:pos].endswith("\\fi}")
    assert tex[pos] == "\n"


def test_nested_conditional_arm_braces() -> None:
    r"""``\ifpdf{\doclass}\else{\doclass}\fi`` —— 组臂内命中各产臂内缝。

    ``\else``/``\fi`` 是 cs token 不是实参组——尾随实参吞并在其前停止，
    每臂缝落自臂 ``}`` 后（行内有活代码 → ``}`` 后即插，不越臂）。
    """
    tex = "\\ifpdf{\\documentclass{a}}\\else{\\documentclass{b}}\\fi\n" + _DOC
    hits = find_docclass_ends(tex)
    assert len(hits) == 2  # noqa: PLR2004
    pos_a, pos_b = hits[0][0], hits[1][0]
    assert tex[pos_a - 1] == "}"
    assert tex[pos_a : pos_a + 5] == "\\else"
    assert tex[pos_b - 1] == "}"
    assert tex[pos_b : pos_b + 3] == "\\fi"


def test_def_body_docclass_still_proxy() -> None:
    r"""宏体 ``\newcommand{\x}{\doclass}`` 内命中仍跳过——零缝归 proxy 调用点。"""
    alone = "\\newcommand{\\x}{\\documentclass{a}}\n" + _DOC
    assert find_docclass_ends(alone) == []
    called = "\\newcommand{\\x}{\\documentclass{a}}\n\\x\n" + _DOC
    hits = find_docclass_ends(called)
    assert len(hits) == 1
    assert called[hits[0][0]] == "\n"
    assert hits[0][0] > called.index("\\x\n")


def test_inject_cjk_nested_prologue_placement() -> None:
    """端到端：ctex prologue 落构造全闭之后、``\\begin{document}`` 之前。"""
    out, info = inject_cjk(_HIDDEN_1LINE, mode="ctex")
    assert info["status"] == "injected"
    # 构造文本逐字节完好——未插进任何两个实参之间。
    construct = (
        "\\IfFileExists{mycls.cls}{\\documentclass{mycls}}{\\documentclass{article}}"
    )
    assert construct in out
    ctex_at = out.index("\\usepackage[fontset=fandol")
    assert out.index(construct) + len(construct) < ctex_at
    assert ctex_at < out.index("\\begin{document}")


def test_inject_after_docclass_nested_seam(tmp_path: Path) -> None:
    """fixloop 消费侧：``_inject_after_docclass`` 走缝位而非头注（B5a 正解）。"""
    (tmp_path / "main.tex").write_text(_HIDDEN_1LINE, encoding="utf-8")
    ctx = mk_ctx(tmp_path)
    assert _inject_after_docclass(ctx, "SNIP")
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert not t.startswith("SNIP")
    assert "}\nSNIP\n\\begin{document}" in t


def test_seam_pos_invariants_nested() -> None:
    """nested 缝位同守全局不变式：pos 落 ``\\n``/``}`` 后，lineno 与 pos 自洽。"""
    for tex in (
        _HIDDEN_1LINE,
        _HIDDEN_MULTILINE,
        "{\\documentclass{a}}\n" + _DOC,
        "\\ifmain{\\documentclass{a}}{}\n" + _DOC,
        "{\\ifx\\a\\b{\\documentclass{a}}\\fi}\n" + _DOC,
    ):
        for pos, lineno, _cmd in find_docclass_ends(tex):
            assert pos == len(tex) or tex[pos] == "\n" or tex[pos - 1] == "}"
            assert lineno == tex[:pos].count("\n") + 1
