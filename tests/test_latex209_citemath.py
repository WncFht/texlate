"""latex209 数学域 cite 族 ``\\mbox`` 包裹的单测。

revtex4-2+natbib 链路下数学域裸 ``\\cite`` 的未定义引用标记
``{\\reset@font\\bfseries ?}`` 无盒直排 → ``\\bfseries`` 触发
``\\not@math@alphabet`` 硬报 ``Command \\bfseries invalid in math mode``
（gr-qc/9901082 ``$\\phi^i_{\\pm}=0 \\cite{HawMos}.$`` 实证，
tmp/lane-citemath/EVIDENCE.md）；fixloop halt_on_error 让编译死在
thebibliography 之前、``\\bibcite`` 永不写回 aux → 同错自续。
``\\mbox{\\cite{..}}`` 把标记放回文本域（min6 实证首遍净过）。
"""

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


def test_cite_wrap_basic() -> None:
    r"""9901082 实证签名：``$`` 内裸 ``\cite{..}`` → ``\mbox{\cite{..}}``。"""
    out, info = _convert("$\\phi^i_{\\pm}=0 \\cite{HawMos}.$")
    assert info["math_cite_wrapped"] == 1
    assert "\\mbox{\\cite{HawMos}}" in out
    assert "=0 \\cite" not in out


def test_cite_wrap_all_commands() -> None:
    r"""natbib 全引用面逐命令命中——``\citep/\citet/\citealt/\citealp/\citeauthor
    /\citeyear/\citenum`` 及 ``\citeyearpar/\citefullauthor/\citetalias/
    \citepalias``/大写句首形。"""
    out, info = _convert(
        "$\\cite{k1} \\citep{k2} \\citet{k3} \\citealt{k4} \\citealp{k5}"
        " \\citeauthor{k6} \\citeyear{k7} \\citenum{k8} \\citeyearpar{k9}"
        " \\citefullauthor{k10} \\citetalias{k11} \\citepalias{k12}"
        " \\Citet{k13} \\Citep{k14} \\Citealt{k15} \\Citealp{k16}"
        " \\Citeauthor{k17}$"
    )
    assert info["math_cite_wrapped"] == 17  # noqa: PLR2004
    assert out.count("\\mbox{\\cite") + out.count("\\mbox{\\Cite") == 17  # noqa: PLR2004


def test_cite_wrap_star_and_opts() -> None:
    r"""``*`` + ``[pre][post]`` 可选参整段搬进盒内。"""
    out, info = _convert("$\\citet*[see][\\S5]{key}$")
    assert info["math_cite_wrapped"] == 1
    assert "\\mbox{\\citet*[see][\\S5]{key}}" in out


def test_cite_wrap_single_opt() -> None:
    out, info = _convert("$x \\citep[e.g.][]{k}$")
    assert info["math_cite_wrapped"] == 1
    assert "\\mbox{\\citep[e.g.][]{k}}" in out


def test_cite_wrap_whitespace_args() -> None:
    r"""``\@ifstar``/``\@ifnextchar`` 跳空格口径——cs 与参间空白可跨。"""
    out, info = _convert("$x \\citep [a] {k}$")
    assert info["math_cite_wrapped"] == 1
    assert "\\mbox{\\citep [a] {k}}" in out


def test_cite_wrap_multi_spans() -> None:
    r"""同一文档多个数学域各裹各的。"""
    out, info = _convert("$\\cite{a}$ text $\\citep{b}$")
    assert info["math_cite_wrapped"] == 2  # noqa: PLR2004
    assert "\\mbox{\\cite{a}}" in out
    assert "\\mbox{\\citep{b}}" in out


def test_cite_wrap_delimiters() -> None:
    r"""``$$``/``\\(..\\)``/``\\[..\\]`` 各定界都覆盖。"""
    out, info = _convert("$$\\cite{a}$$\n\\(\\cite{b}\\)\n\\[\\cite{c}\\]")
    assert info["math_cite_wrapped"] == 3  # noqa: PLR2004
    assert out.count("\\mbox{\\cite") == 3  # noqa: PLR2004


def test_cite_wrap_equation_env() -> None:
    r"""数学环境体整段按数学域。"""
    _out, info = _convert(
        "\\begin{equation}\nx = \\cite{a}\n\\end{equation}\n"
        "\\begin{eqnarray*}\ny &=& \\citep{b}\n\\end{eqnarray*}"
    )
    assert info["math_cite_wrapped"] == 2  # noqa: PLR2004


def test_cite_text_mode_untouched() -> None:
    r"""文本域 ``\cite`` 本就合法——不动。"""
    out, info = _convert("see \\cite{a} and \\citep[pre]{b} end")
    assert info["math_cite_wrapped"] == 0
    assert "\\mbox{" not in out


def test_cite_in_mbox_untouched() -> None:
    r"""已裹 ``\mbox``/``\text`` 的不再二裹——文本域实参豁免。"""
    out, info = _convert("$x + \\mbox{\\cite{a}} + \\text{\\citep{b}}$")
    assert info["math_cite_wrapped"] == 0
    assert out.count("\\mbox{\\cite{a}}") == 1


def test_cite_comment_shielded() -> None:
    r"""注释内的同形不命中（遮盖视图定位）。"""
    out, info = _convert("$a % \\cite{x}\n + b$\n% $\\cite{y}$\n$\\cite{z}$")
    assert info["math_cite_wrapped"] == 1
    assert "\\mbox{\\cite{z}}" in out


def test_cite_ref_eqref_untouched() -> None:
    r"""``\ref``/``\eqref`` 走 ``\nfss@text`` 本就安全——不收。"""
    out, info = _convert("$x \\ref{a} \\eqref{b} \\cite{c}$")
    assert info["math_cite_wrapped"] == 1
    assert "\\mbox{\\cite{c}}" in out
    assert "\\mbox{\\ref" not in out


def test_cite_citetext_untouched() -> None:
    r"""``\citetext`` 是字面文本实参、无引用标记路径——不收。"""
    out, info = _convert("$x \\citetext{literal}$")
    assert info["math_cite_wrapped"] == 0
    assert "\\mbox{" not in out


def test_cite_no_brace_arg_untouched() -> None:
    r"""缺 ``{key}`` 实参的裸 ``\cite`` 不裹——``\@citex`` 会把 ``}`` 读成 key。"""
    out, info = _convert("$x + \\cite + y$")
    assert info["math_cite_wrapped"] == 0
    assert "\\mbox{\\cite" not in out


def test_cite_opt_without_key_untouched() -> None:
    r"""有 ``[..]`` 无 ``{key}`` 同样残缺——不动。"""
    _out, info = _convert("$x + \\cite[pre] + y$")
    assert info["math_cite_wrapped"] == 0


def test_cite_inside_group_in_math() -> None:
    r"""数学域内花括号组里的 ``\cite`` 同模态——``{\it $..$}`` 实证形态。"""
    out, info = _convert("{\\it text $\\phi^i_{\\pm}=0 \\cite{HawMos}.)$}")
    assert info["math_cite_wrapped"] == 1
    assert "\\mbox{\\cite{HawMos}}" in out


def test_cite_inner_math_in_textarg() -> None:
    r"""``\mbox{$\cite{}$}`` 嵌套最内层是数学域——仍裹。"""
    out, info = _convert("\\mbox{$x \\cite{a}$}")
    assert info["math_cite_wrapped"] == 1
    assert "\\mbox{$x \\mbox{\\cite{a}}$}" in out


def test_cite_crossing_math_boundary_untouched() -> None:
    r"""调用整体越出数学域（``{key}`` 内含 ``$`` 闭定界）——残缺形态不动。"""
    _out, info = _convert("$\\cite{a$b}$")
    assert info["math_cite_wrapped"] == 0


def test_cite_with_switch_coexist() -> None:
    r"""同域内 switch 组与 cite 包裹两族编辑互不覆盖。"""
    out, info = _convert("$\\cite{a} + {\\em x}$")
    assert info["math_cite_wrapped"] == 1
    assert info["math_switch_fixed"] == 1
    assert "\\mbox{\\cite{a}}" in out
    assert "\\mathit{ x}" in out


def test_cite_inside_switch_group() -> None:
    r"""``{\em \cite{}}`` 组头改 ``\mathit`` 与 cite 包裹并存。"""
    out, info = _convert("${\\em \\cite{a}}$")
    assert info["math_cite_wrapped"] == 1
    assert info["math_switch_fixed"] == 1
    assert "\\mathit{ \\mbox{\\cite{a}}}" in out


def test_cite_adjacent_no_space() -> None:
    r"""相邻调用 ``\cite{a}\cite{b}``——同位闭/开插入保序成 ``}\mbox{``。"""
    out, info = _convert("$\\cite{a}\\cite{b}$")
    assert info["math_cite_wrapped"] == 2  # noqa: PLR2004
    assert "\\mbox{\\cite{a}}\\mbox{\\cite{b}}" in out


def test_cite_nested_in_cite_arg() -> None:
    r"""``\cite`` 实参内的 ``\cite`` 同模态各裹——嵌套零宽插入保序。"""
    out, info = _convert("$\\cite{a\\cite{b}}$")
    assert info["math_cite_wrapped"] == 2  # noqa: PLR2004
    assert "\\mbox{\\cite{a\\mbox{\\cite{b}}}}" in out


def test_cite_no_math_fastpath() -> None:
    r"""无数学域文档短路——文本 ``\cite`` 不扫。"""
    _out, info = _convert("plain \\cite{a} only")
    assert info["math_cite_wrapped"] == 0


def test_cite_preamble_math() -> None:
    r"""preamble/宏体里的数学域同口径——``\title{$\cite{}$}`` 也裹。"""
    out, info = _convert("\\title{T $\\cite{a}$}\nx")
    assert info["math_cite_wrapped"] == 1
    assert "\\mbox{\\cite{a}}" in out


def test_cite_revtex_shape_9901082() -> None:
    r"""gr-qc/9901082 整形态回放——revtex→revtex4-2 升级后包裹。"""
    tex = (
        "\\documentstyle[aps,prl]{revtex}\n\\begin{document}\n"
        "{\\it \n$($An exceptional case is the Hawking Moss instanton \n"
        "corresponding to $\\phi^i_{\\pm}=0 \\cite{HawMos}.)$}\n"
        "\\end{document}\n"
    )
    out, info = upgrade_209(tex)
    assert info["math_cite_wrapped"] == 1
    assert "$\\phi^i_{\\pm}=0 \\mbox{\\cite{HawMos}}.)$" in out
