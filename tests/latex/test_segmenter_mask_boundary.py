r"""xlat-mask 桶回归（wontfix-scout 裁决 §2，2026-09-18）。

- **aipproc keyval 第二参泄露**（0905.0330/0905.2183/1012.1143/
  astro-ph/0408494/astro-ph/0605512）：``\author{name}{key=val,..}`` 的
  PROTECT_BLOCK 保护只盖首个 mandatory 组，后续 keyval 组裸进 chunk——
  ``address=`` 键位被译成 ``这是译文=``，splice 后 ``\setkeys`` 炸
  ``Package keyval Error``。修复：首个 ``{arg}`` 之后续吃 keyval 形
  ``{..}`` 组（``key=``/``flag,key=`` 起头）并入 ``[[AUTHOR]]``。
- **``\)/\]`` 混排闭符提前关 math**（1306.6030）：``\def\({\left(}``
  重定义后 ``\)/\]`` 是普通定界符宏，``_on_math`` 原先把 ``\)`` 当
  ``$`` 闭符 → ``[[MATH]]`` 提前关闭、余段裸露被译 + ``$`` 奇偶翻转
  串行吞噬。修复：闭符扫描加内层配对深度——``\(/\[`` +1，``\)/\]``
  仅在无 pending 内层开符时作 outer 闭符。
"""

from _segkit import scan_art
from conftest import chunk_text


def _phs(res: object, prefix: str) -> list[str]:
    """ph_map 中指定前缀的占位体列表（签发序）。"""
    return [
        v
        for k, v in res.ph_map.items()  # type: ignore[attr-defined]
        if k.startswith(prefix)
    ]


# ------------------------------------------------------------------ aipproc keyval


def test_author_keyval_second_arg_protected() -> None:
    r"""``\author{N}{key=val,..}``：keyval 第二参整组并入 ``[[AUTHOR]]``。"""
    res = scan_art(
        "\\author{P.~G.~Hofmeister}{\n"
        '  address={TU Braunschweig, Institut f\\"ur Geophysik},\n'
        "  email={p@example.com}\n"
        "}\n"
        "Body text here long enough to be its own chunk for sure yes."
    )
    assert _phs(res, "[[AUTHOR") == [
        (
            "\\author{P.~G.~Hofmeister}{\n"
            '  address={TU Braunschweig, Institut f\\"ur Geophysik},\n'
            "  email={p@example.com}\n"
            "}"
        )
    ]
    ct = chunk_text(res)
    assert "address" not in ct
    assert "email" not in ct
    assert "Body text" in ct


def test_author_opt_then_keyval_protected() -> None:
    r"""``\author[opt]{N}{key=val}``：``[opt]``+双组一并保护。"""
    res = scan_art(
        "\\author[P. Hofmeister]{P.~G.~Hofmeister}{address={TU}}"
        "Body text here long enough to be its own chunk for sure."
    )
    assert _phs(res, "[[AUTHOR") == [
        "\\author[P. Hofmeister]{P.~G.~Hofmeister}{address={TU}}"
    ]
    assert "address" not in chunk_text(res)


def test_author_prose_group_not_swallowed() -> None:
    r"""反例：``\author{N}{散文组}`` 非 keyval 形——第二组照常进 chunk。"""
    res = scan_art(
        "\\author{Some One}{A prose group long enough to be its own chunk text.}"
    )
    assert _phs(res, "[[AUTHOR") == ["\\author{Some One}"]
    assert "A prose group" in chunk_text(res)


def test_author_keyval_after_blank_line_not_swallowed() -> None:
    r"""``\author{N}`` 后空行再 ``{key=val}``：段界分隔即非参数——不收。"""
    res = scan_art("\\author{Some One}\n\n{flag,address={TU}}Body text for chunk yes.")
    assert _phs(res, "[[AUTHOR") == ["\\author{Some One}"]
    assert "address" in chunk_text(res)


def test_author_flag_prefixed_keyval_protected() -> None:
    r"""``{flag,address={..}}`` 裸键位前缀的 keyval 组同样收。"""
    res = scan_art("\\author{Some One}{flag,address={TU}}Body text for chunk yes.")
    assert _phs(res, "[[AUTHOR") == ["\\author{Some One}{flag,address={TU}}"]
    assert "address" not in chunk_text(res)


# ------------------------------------------------------------------ \) 混排闭符深度


def test_math_inner_paren_depth_redefined_close() -> None:
    r"""1306.6030：``\def\({\left(}`` 面 ``$H\((..\dots)\)=..$`` 整段单 MATH。"""
    res = scan_art(
        "\\begin{enumerate}\n"
        "\\item $H\\((\\infty,\\infty,0,0,\\dots)\\)=\\mathbb Z[\\frac16]$.\n"
        "\\item $H\\((0,1,1,1,1,\\dots)\\)$ is the subgroup of rationals.\n"
        "\\end{enumerate}",
        defs="\\def\\({\\left(}\\def\\){\\right)}\n",
    )
    assert _phs(res, "[[MATH") == [
        "$H\\((\\infty,\\infty,0,0,\\dots)\\)=\\mathbb Z[\\frac16]$",
        "$H\\((0,1,1,1,1,\\dots)\\)$",
    ]
    assert not any(w.kind == "unpaired_dollar" for w in res.warnings)
    assert "subgroup of rationals" in chunk_text(res)


def test_math_mixed_closer_no_inner_open_still_closes() -> None:
    r"""0806.1984 不回退：无内层 ``\(`` 时 ``\)`` 仍当 ``$`` 闭符。"""
    res = scan_art("We have $\\alpha(x)\\), for all $p \\in S$ the claim holds.")
    assert _phs(res, "[[MATH") == ["$\\alpha(x)\\)", "$p \\in S$"]
    assert ", for all " in chunk_text(res)


def test_math_inner_bracket_depth_display() -> None:
    r"""``$$a \[b\] c$$``：``\[``/``\]`` 内层配对——``\]`` 不提前关 display。"""
    res = scan_art("Display $$a \\[b\\] c$$ then trailing words for the chunk.")
    assert _phs(res, "[[MATH") == ["$$a \\[b\\] c$$"]


def test_math_inner_open_unclosed_dollar_still_closes() -> None:
    r"""``$a \( b$``：内层 ``\(`` 未配对——``$`` 照常闭（``\left(`` 不悬 ``$`` 界）。"""
    res = scan_art("Math $a \\( b$ here and trailing words fill out the chunk.")
    assert _phs(res, "[[MATH") == ["$a \\( b$"]
