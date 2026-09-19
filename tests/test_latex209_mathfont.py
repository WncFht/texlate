"""latex209 数学域字体开关组转写 + ``_uses_ds_at`` tar 闸的单测。

209 时代 ``{\\em X}``/``{\\it X}``/``{\\bf X}`` 是 switch 组——2e 下 ``\\em``
在数学域经 ``\\itshape`` 硬报 ``Command \\itshape invalid in math mode``
（astro-ph/9910310 ``\\sum_{{\\em fields}\\,i}`` 实证 1 错），``\\it``/``\\bf``
虽经 ``\\@fontswitch`` 不报错仍归一为 ``\\mathit``/``\\mathbf`` 参数形消歧。
"""

from pathlib import Path

import pytest

from texlate.compile import latex209
from texlate.compile.latex209 import upgrade_209


@pytest.fixture(autouse=True)
def _target_always_resolvable(monkeypatch: pytest.MonkeyPatch) -> None:
    """改名目标类默认放行——与 test_latex209.py 同款打桩。"""
    monkeypatch.setattr(latex209, "_target_resolvable", lambda *_a: True)


def _convert(body: str) -> tuple[str, dict]:
    tex = "\\documentstyle{article}\n\\begin{document}\n" + body + "\n\\end{document}\n"
    return upgrade_209(tex)


def test_math_switch_em_in_ddollar() -> None:
    """9910310 实证签名：``$$`` 内 ``{\\em X}`` → ``\\mathit{X}``。"""
    out, info = _convert(
        "$$\\langle N\\rangle = \\sum_{{\\em fields}\\,i} d\\Omega,\\eqno{(3)}$$"
    )
    assert info["math_switch_fixed"] == 1
    assert "\\mathit{ fields}" in out
    assert "{\\em fields}" not in out


def test_math_switch_it_bf() -> None:
    """``\\it``/``\\bf`` 同形态归一——参数形消歧。"""
    out, info = _convert("$a + {\\it x} + {\\bf y}$")
    assert info["math_switch_fixed"] == 2  # noqa: PLR2004
    assert "\\mathit{ x}" in out
    assert "\\mathbf{ y}" in out


def test_math_switch_2e_decl_forms() -> None:
    r"""过渡期稿 2e 声明形同踩 ``\not@math@alphabet``——gr-qc/9901082 实证。"""
    out, info = _convert(
        "$a + {\\bfseries x} + {\\itshape y} + {\\rmfamily z}"
        " + {\\sffamily w} + {\\ttfamily v}$"
    )
    assert info["math_switch_fixed"] == 5  # noqa: PLR2004
    assert "\\mathbf{ x}" in out
    assert "\\mathit{ y}" in out
    assert "\\mathrm{ z}" in out
    assert "\\mathsf{ w}" in out
    assert "\\mathtt{ v}" in out


def test_math_switch_2e_decl_exclusions() -> None:
    r"""``\slshape/\scshape/\upshape/\mdseries/\normalfont`` 无单义数学字母——保守不动。"""
    _out, info = _convert(
        "${\\slshape a}$ ${\\scshape b}$ ${\\upshape c}$"
        " ${\\mdseries d}$ ${\\normalfont e}$"
    )
    assert info["math_switch_fixed"] == 0


def test_math_switch_bf_not_prefix_of_bfseries() -> None:
    r"""``{\bfseries X}`` 不吃 ``bf`` 前缀截——长名整词命中。"""
    out, info = _convert("${\\bfseries X}$")
    assert info["math_switch_fixed"] == 1
    assert "\\mathbf{ X}" in out
    assert "{\\bfseries X}" not in out


def test_math_switch_delimiters() -> None:
    """``$..$``/``\\(..\\)``/``\\[..\\]`` 各定界都覆盖。"""
    out, info = _convert("$a {\\em x}$\n\\(b {\\em y}\\)\n\\[c {\\em z}\\]")
    assert info["math_switch_fixed"] == 3  # noqa: PLR2004
    assert out.count("\\mathit{") == 3  # noqa: PLR2004


def test_math_switch_equation_env() -> None:
    """数学环境体（无定界符）整段按数学域——``equation``/``eqnarray``。"""
    out, info = _convert(
        "\\begin{equation}\na + {\\em x}\n\\end{equation}\n"
        "\\begin{eqnarray*}\nb &=& {\\it y}\n\\end{eqnarray*}"
    )
    assert info["math_switch_fixed"] == 2  # noqa: PLR2004
    assert "\\mathit{ x}" in out
    assert "\\mathit{ y}" in out


def test_math_switch_text_mode_untouched() -> None:
    """文本域 ``{\\em X}`` 合法——不动。"""
    out, info = _convert("text {\\em x} text\n{\\it y}\n{\\bf z}")
    assert info["math_switch_fixed"] == 0
    assert "{\\em x}" in out
    assert "{\\it y}" in out


def test_math_switch_textarg_in_math_untouched() -> None:
    r"""数学域内文本域实参豁免——``\mbox``/``\text``/``\textit`` 内 ``{\em}`` 合法。"""
    out, info = _convert(
        "$a + \\mbox{{\\em x}} + \\text{{\\it y}} + \\textit{{\\bf z}}$"
    )
    assert info["math_switch_fixed"] == 0
    assert "{\\em x}" in out


def test_math_switch_inner_math_in_textarg() -> None:
    r"""``\mbox{${\em}$}`` 嵌套最内层是数学域——仍修。"""
    out, info = _convert("\\mbox{${\\em x}$}")
    assert info["math_switch_fixed"] == 1
    assert "\\mathit{ x}" in out


def test_math_switch_hbox_spec_untouched() -> None:
    r"""``\hbox to <dim>{...}`` 盒规格后实参仍文本域——``{\em}`` 豁免。"""
    _out, info = _convert("$a + \\hbox to 3em{{\\em x}}$")
    assert info["math_switch_fixed"] == 0


def test_math_switch_multiarg_not_swallowed() -> None:
    r"""``\textbf{A} {\em B}$``——``{\em B}`` 非 ``\textbf`` 实参，数学域照常修。"""
    out, info = _convert("$\\textbf{A} {\\em B}$")
    assert info["math_switch_fixed"] == 1
    assert "\\mathit{ B}" in out


def test_math_switch_comment_shielded() -> None:
    """注释内的同形不命中（遮盖视图定位）。"""
    _out, info = _convert("$a % {\\em x}\n + b$")
    assert info["math_switch_fixed"] == 0


def test_math_switch_comment_before_cs_blocked() -> None:
    r"""``{%c\n\em X}``——行间注释形态不吞（横向空白口径）。"""
    _out, info = _convert("$a {%note\n\\em x}$")
    assert info["math_switch_fixed"] == 0


def test_math_switch_escaped_brace_not_opener() -> None:
    r"""``\{`` 转义花括号不是组开——``\em`` 裸露形态不在 ``{cs X}`` 口径内。"""
    _out, info = _convert("$\\{ \\em x\\}$")
    assert info["math_switch_fixed"] == 0


def test_math_switch_cs_not_group_head() -> None:
    r"""``{\xyz\em X}``——``\em`` 非组首 token，前段不在开关域，保守不动。"""
    _out, info = _convert("$a {\\x\\em x}$")
    assert info["math_switch_fixed"] == 0


def test_math_switch_unclosed_env_untouched() -> None:
    """未闭合 begin 不成域——残缺档保守不动。"""
    _out, info = _convert("\\begin{equation}\na + {\\em x}")
    assert info["math_switch_fixed"] == 0


def test_math_switch_other_switches_untouched() -> None:
    r"""``\cal/\sl/\rm`` 不在映射表——``\@fontswitch`` 机制本就正确/无对应字母。"""
    _out, info = _convert("${\\cal X}$ ${\\sl Y}$ ${\\rm Z}$")
    assert info["math_switch_fixed"] == 0


def test_math_switch_no_math_fastpath() -> None:
    """无数学域文档短路——``{\\em}`` 纯文本用法不扫。"""
    _out, info = _convert("plain text {\\em x} only")
    assert info["math_switch_fixed"] == 0


def test_math_switch_def_body_untouched() -> None:
    r"""``\newcommand`` 体顶层非数学域——调用点模态不可静态知，保守不动。"""
    _out, info = _convert("\\newcommand{\\f}{{\\em x}}\n$\\f$")
    assert info["math_switch_fixed"] == 0


def _fake_tar(payload: bytes) -> bytes:
    """造 tar 伪装件头：``ustar``@257 + 合法 chksum 字段 + 非空 name。"""
    head = bytearray(512)
    head[0:4] = b"file"
    head[148:156] = b"000644 \x00"
    head[257:262] = b"ustar"
    return bytes(head) + payload.ljust(512, b"\x00")


def test_uses_ds_at_tar_disguised_skipped(tmp_path: Path) -> None:
    """随源 ``<cls>.sty`` 实为 tar 伪装件——成员文本的 ``ds@`` 字样不计。"""
    (tmp_path / "myj.sty").write_bytes(_fake_tar(b"\\@namedef{ds@opta}{\\relax}\n"))
    out, info = upgrade_209("\\documentstyle[opta]{myj}\nx\n", root=tmp_path)
    assert info["status"] == "converted"  # 无闸则 ds@ 命中误拒
    assert "\\documentclass[opta]{myj}" in out


def test_uses_ds_at_real_sty_still_rejects(tmp_path: Path) -> None:
    """真文本 ``<cls>.sty`` 内 ``ds@`` 分发照样拒——闸不吃真签名。"""
    (tmp_path / "myj.sty").write_bytes(b"\\@namedef{ds@opta}{\\relax}\n")
    _out, info = upgrade_209("\\documentstyle[opta]{myj}\nx\n", root=tmp_path)
    assert info["status"] == "reject"
    assert info["reason"] == "latex209_ds_at"
