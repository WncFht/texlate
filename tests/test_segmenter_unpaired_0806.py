r"""0806.3472 回归：展开组 surface 三缺陷。

- **detokenize 空格**：``{\bf X}`` 经宏展开后控制词与字母之间无 gap 字节
  可恢复（token pos 指调用点），须按 TeX 词法补空格——否则 ``\bfKostant``
  融合成一个未定义控制词（identity 重建照常，surface 已坏，mock 还把融合
  词当 ``\cs`` 整保留 → 词不被翻译）。
- **BOUNDARY_TAIL 组内缺失**：顶层 ``_handle_boundary`` 用 ``BOUNDARY_TAIL``
  argspec 把 ``\vspace{2mm}`` 结构参消费进 LITERAL；``_group_surface`` 无
  对应分支 → ``{2mm}`` 逐字符落 chunk surface → 翻译 ``mm`` →
  ``\vspace{2这是译文}`` → ``Illegal unit of measure``。
- **未配对 ``$$``**：``_on_math`` unpaired 分支丢 ``nxt``（``$$`` 第二枚
  ``$``）→ surface 留单 ``$``；且 ``$$`` 扫描 raw-read 耗尽 Mouth 弹栈后
  ``unread`` 建合成源，主循环尾扫把余下字节整盖 → 回放 token 零宽 vspan
  → ``$\omega$`` 等 ph 体空串被静默丢弃。

#77 残留收口：

- **``\text`` 族参数边界**：``_on_math`` 体扫遇 ``\text/\mbox/\intertext``
  族须按 ``*→[o]→{m}`` 整参跳扫——参内 ``$`` 属组内配对，否则
  ``\text{...$x$...}`` 在内层 ``$`` 截断外层数学（``missing_character``
  残留面）。
- **C2 EOF 门守卫**：unpaired 中止的 EOF 判据须 ``x is None and
  isinstance(src, Gullet)``——``_ListSource`` 子扫（env 体/参数）耗尽
  同样 ``x is None`` 但 unread 同队回插安全，误走 LITERAL 尾盖会把
  ``[cons,文件尾)`` 从主扫字节里抢走。
"""

import re

from texlate.latex import parse_tex, reconstruct
from texlate.latex.model import ScanResult

_PHANTOM = (
    "\\documentclass{amsart}\n"
    "\\def\\phantomsubsection#1{\\vspace{2mm}\\noindent{\\bf #1.}}\n"
    "\\begin{document}\n"
    "\\phantomsubsection{Kostant modules}\n"
    "We classify modules over the algebras.\n"
    "\\end{document}\n"
)

_PICTURE_DD = (
    "\\documentclass{amsart}\n"
    "\\begin{document}\n"
    "Creates one extra internal circle:\n"
    "$$\n"
    "\\begin{picture}(10,10)\n"
    "\\put(0,0){$x$}\n"
    "\n"
    "\\put(1,1){$y$}\n"
    "\\end{picture}\n"
    "$$\n"
    "Since $\\omega$ sends circles to zero, done.\n"
    "\\end{document}\n"
)


def _raw_surface(res: ScanResult) -> str:
    """chunk content 原样拼接（ph 不展开——surface 轨原貌）。"""
    return "\n".join(c.content for c in res.chunks)


def _expanded_surface(res: ScanResult) -> str:
    """chunk content 内 ``[[X_n]]`` 按 ph_map 展开一层——surface 可见文本。"""
    parts = []
    for c in res.chunks:
        s = c.content
        for ph, body in res.ph_map.items():
            s = s.replace(ph, body)
        parts.append(s)
    return "\n".join(parts)


# ------------------------------------------------------------- detokenize


def test_expand_group_cs_letter_no_fusion() -> None:
    r"""``{\bf #1.}`` 展开：``\bf``+``Kostant`` 不得融合成 ``\bfKostant``。"""
    res = parse_tex(_PHANTOM)
    assert reconstruct(res) == _PHANTOM
    surf = _expanded_surface(res)
    assert "\\bfKostant" not in surf
    assert "Kostant" in surf  # 词不被融合控制词吞掉（可译性）


def test_expand_group_cs_before_nonletter_no_space() -> None:
    r"""反例护栏：``{\bf{x}}``/``\bf\em`` 式邻接不得误插空格。"""
    tex = (
        "\\documentclass{amsart}\n"
        "\\def\\x{{\\bf\\em two words here}}\n"
        "\\begin{document}\n"
        "\\x and more text to make a chunk.\n"
        "\\end{document}\n"
    )
    res = parse_tex(tex)
    assert reconstruct(res) == tex
    surf = _expanded_surface(res)
    assert "\\bf \\em" not in surf  # cs+cs 邻接无空格
    assert "\\bfem" not in surf


# ------------------------------------------------------------- BOUNDARY_TAIL


def test_expand_group_boundary_tail_arg_protected() -> None:
    r"""``\vspace{2mm}`` 在展开组内：整调用进 ``[[CMD_n]]``，``{2mm}`` 不落 surface。"""
    res = parse_tex(_PHANTOM)
    assert reconstruct(res) == _PHANTOM
    raw = _raw_surface(res)
    assert "{2mm}" not in raw
    assert re.search(r"\[\[CMD_\d+\]\]", raw)
    ph = re.search(r"\[\[CMD_\d+\]\]", raw)
    assert ph is not None
    assert res.ph_map[ph.group(0)] == "\\vspace{2mm}"


def test_expand_group_boundary_star_variant() -> None:
    r"""``\vspace*{1em}`` 星号变体同样整调用保护（``ArgSpec("s")`` 支）。"""
    tex = (
        "\\documentclass{amsart}\n"
        "\\def\\x{\\vspace*{1em}Gap marked here}\n"
        "\\begin{document}\n"
        "\\x followed by more running text.\n"
        "\\end{document}\n"
    )
    res = parse_tex(tex)
    assert reconstruct(res) == tex
    raw = _raw_surface(res)
    assert "{1em}" not in raw


# ------------------------------------------------------------- 未配对 $$


def test_unpaired_dd_display_math_surface_keeps_both_dollars() -> None:
    r"""``$$`` opener 因 picture 内 eol_par 中止：surface 须保 ``$$`` 非单 ``$``。"""
    res = parse_tex(_PICTURE_DD)
    assert reconstruct(res) == _PICTURE_DD
    surf = _expanded_surface(res)
    # 两个 $$ 各丢一枚 $ → 单 $ 残留；修复后 $$ 成对或整体 literal
    assert "$$" in surf or "$$" in res.protected_tex


def test_unpaired_dd_eof_tail_math_not_dropped() -> None:
    r"""``$$`` 扫描耗尽源（EOF 中止）：回放区 ``$\omega$`` 不得静默消失。"""
    res = parse_tex(_PICTURE_DD)
    surf = _expanded_surface(res)
    assert "\\omega" in surf or "\\omega" in res.protected_tex


def test_unpaired_dd_before_paragraph_break() -> None:
    r"""``$$\n\n\begin{Lemma}`` 型：``$$`` 后紧跟段界 → 不得丢第二枚 ``$``。"""
    tex = (
        "\\documentclass{amsart}\n"
        "\\begin{document}\n"
        "First paragraph of running text here.\n"
        "$$\n"
        "\n"
        "Second paragraph follows the stray display marker.\n"
        "\\end{document}\n"
    )
    res = parse_tex(tex)
    assert reconstruct(res) == tex
    surf = _expanded_surface(res)
    assert "$$" in surf or "$$" in res.protected_tex


# ------------------------------------------- \text 族参数边界 / C2 守卫（#77）


def test_math_text_arg_inner_dollar_no_split() -> None:
    r"""``$..\text{..$c \mu$}..$``：``\text`` 内层 ``$`` 不截断外层数学。"""
    tex = (
        "\\documentclass{amsart}\n"
        "\\begin{document}\n"
        "Basis is $\\left\\{(c \\mu| \\:\\big|\\:\n"
        "\\text{for all oriented cup diagrams $c \\mu$}\\right\\}$ here.\n"
        "\\end{document}\n"
    )
    res = parse_tex(tex)
    assert reconstruct(res) == tex
    m = re.search(r"\[\[MATH_\d+\]\]", res.protected_tex)
    assert m is not None
    body = res.ph_map[m.group(0)]
    assert "\\text{for all oriented cup diagrams $c \\mu$}" in body
    assert body.endswith("\\right\\}$")


def test_math_textarg_box_prefix_variants() -> None:
    r"""``\mbox{..$x$..}``/``\makebox[..]{..$x$..}`` 同款跳扫。"""
    tex = (
        "\\documentclass{amsart}\n"
        "\\begin{document}\n"
        "Formula $a+\\mbox{for $x$}+b$ and $c+\\makebox[2cm]{see $y$}+d$ end.\n"
        "\\end{document}\n"
    )
    res = parse_tex(tex)
    assert reconstruct(res) == tex
    bodies = [
        res.ph_map[m.group(0)]
        for m in re.finditer(r"\[\[MATH_\d+\]\]", res.protected_tex)
    ]
    assert "\\mbox{for $x$}" in bodies[0]
    assert "\\makebox[2cm]{see $y$}" in bodies[1]


def test_arg_subscan_unpaired_math_no_tail_steal() -> None:
    r"""``\section{..$x}`` 参数 ``_ListSource`` 子扫耗尽 → unread 回放，
    不得把 ``[cons,EOF)`` 整段 LITERAL 抢走主扫字节（C2 守卫面）。"""
    tex = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\section{Title with $unpaired}\n"
        "After body text here.\n"
        "\\end{document}\n"
    )
    res = parse_tex(tex)
    assert reconstruct(res) == tex
    contents = [c.content for c in res.chunks]
    assert any("After body text here." in c for c in contents)
    assert any(w.kind == "unpaired_dollar" for w in res.warnings)
