r"""``\if`` 两档展开的单测（docs/07 §8.6 + plasTeX processIfContent 语义）。

可求值族 → 只推回选中支（未选支+界标全 LITERAL）；
不可求值 → 结构界标 literal，双分支都进分段器（召回优先）。
注：分支文本需明显超过 CHUNK_MIN(20) 清洗阈值才成 chunk，否则 literal。
"""

from texlate.latex import parse_tex, reconstruct
from texlate.latex.model import ScanResult

DOC = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}\n"


def scan(body: str) -> ScanResult:
    return parse_tex(DOC % body)


def blob(res: ScanResult) -> str:
    return "\n".join(c.content for c in res.chunks)


def test_iftrue_selects_first() -> None:
    body = "\\iftrue AAA first selected branch text \\else BBB other \\fi"
    res = scan(body)
    b = blob(res)
    assert "AAA first selected branch text" in b
    assert "BBB other" not in b
    assert reconstruct(res) == DOC % body


def test_iffalse_selects_else() -> None:
    res = scan(
        "\\iffalse AAA hidden branch text \\else BBB shown else branch text \\fi"
    )
    b = blob(res)
    assert "BBB shown else branch text" in b
    assert "AAA hidden branch text" not in b


def test_ifnum_eval() -> None:
    res = scan("\\ifnum 1<2 yes selected branch text here \\else no \\fi")
    assert "yes selected branch text here" in blob(res)
    res2 = scan("\\ifnum 3<2 yes \\else no selected else branch text \\fi")
    assert "no selected else branch text" in blob(res2)


def test_ifnum_unevaluable_is_landmark() -> None:
    r"""``\ifnum`` 读不出数（寄存器）→ 界标：双分支都扫，``\if/\else/\fi`` literal。"""
    body = (
        "\\ifnum \\count0<2 AAA first branch text here "
        "\\else BBB second branch text \\fi"
    )
    res = scan(body)
    b = blob(res)
    assert "AAA first branch text here" in b
    assert "BBB second branch text" in b
    assert "\\else" in res.protected_tex
    assert "\\fi" in res.protected_tex


def test_ifmmode_false() -> None:
    r"""``\ifmmode`` 恒 False（数学区已被 ``[[MATH]]`` 保护）。"""
    res = scan("\\ifmmode in-math \\else not math mode else text here \\fi")
    assert "not math mode else text here" in blob(res)


def test_newif_flag_flow() -> None:
    r"""``\newif\ifx`` + ``\\xtrue`` 副作用 → ``\ifx`` 取真分支。"""
    res = scan(
        "\\newif\\ifx \\xtrue\n"
        "\\ifx AAA flag true branch text \\else BBB flag false text \\fi"
    )
    b = blob(res)
    assert "AAA flag true branch text" in b
    assert "BBB flag false text" not in b


def test_newif_default_false() -> None:
    res = scan("\\newif\\ifx\n\\ifx AAA \\else BBB default else text here \\fi")
    assert "BBB default else text here" in blob(res)


def test_ifcase_selects_nth() -> None:
    res = scan(
        "\\ifcase 2 zero \\or one \\or two third case text here \\else other \\fi"
    )
    b = blob(res)
    assert "two third case text here" in b
    assert "zero" not in b
    assert "other" not in b


def test_ifx_same_literal() -> None:
    res = scan("\\ifx aa same literal text selected \\else diff \\fi")
    assert "same literal text selected" in blob(res)


def test_ifx_macro_unevaluable() -> None:
    r"""``\ifx\a\b`` 宏比较 → 不可求值 → 界标双分支。"""
    res = scan(
        "\\ifx\\foo\\bar AAA first branch words \\else BBB second branch text \\fi"
    )
    b = blob(res)
    assert "AAA first branch words" in b
    assert "BBB second branch text" in b


def test_ifdefined_known() -> None:
    res = scan(
        "\\newcommand{\\ZZ}{z}\n"
        "\\ifdefined\\ZZ defined selected text here \\else undef \\fi"
    )
    assert "defined selected text here" in blob(res)


def test_ifdefined_unknown_landmark() -> None:
    r"""``\ifdefined\unknown`` → 界标（刻意分歧：召回优先不断言 False）。"""
    res = scan(
        "\\ifdefined\\unk AAA first words here \\else BBB second words here \\fi"
    )
    b = blob(res)
    assert "AAA first words here" in b
    assert "BBB second words here" in b


def test_if_char_equal() -> None:
    res = scan("\\if xx equal char branch text \\else ne \\fi")
    assert "equal char branch text" in blob(res)


def test_nested_if() -> None:
    r"""嵌套 ``\if``：``if*`` 计深度，``\fi`` 配对。"""
    body = (
        "\\iftrue outer selected text here \\iftrue inner selected text here \\fi "
        "\\else never selected \\fi"
    )
    res = scan(body)
    b = blob(res)
    assert "outer selected text here" in b or "inner selected text here" in b
    assert "never" not in b


def test_newif_inside_if_kept_together() -> None:
    r"""case 内 ``\newif\ifY`` 整对不拆（plasTeX：newif 追加下一 token）。"""
    body = "\\iftrue text a \\newif\\ifY more selected long text here \\else other \\fi"
    res = scan(body)
    assert reconstruct(res) == DOC % body
    assert "more selected long text here" in blob(res)


def test_cond_landmark_in_run() -> None:
    r"""界标 ``\if..\fi``：命令本身是 LITERAL piece，两侧文本照常成 chunk。"""
    res = scan("Para before text here.\n\\ifdraft AAA draft long words \\fi\nAfter.")
    assert "\\ifdraft" in res.protected_tex


def test_cond_in_arg_is_cond_ph() -> None:
    r"""in_arg 里 ``\else``/``\fi`` 散件 → ``[[COND]]``。"""
    res = scan("\\footnote{a \\else b}")
    assert any(k.startswith("[[COND") for k in res.ph_map)


def test_if_no_fi_unterminated() -> None:
    r"""``\fi`` 缺失 → ``if_unterminated`` warning，剩余文本仍逐字安全。"""
    body = "\\iftrue some text and no fi at all here"
    res = scan(body)
    assert any(w.kind == "if_unterminated" for w in res.warnings)
    assert reconstruct(res) == DOC % body
