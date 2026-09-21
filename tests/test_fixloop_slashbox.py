"""slashbox stub 保真钉 (slashlane, 2026-09-19):

- ``vendor/stubs/slashbox.sty``: 原件 (K. Yasuoka 1993) 无许可 TL2020 除名,
  stub 按公开界面同义重写 —— ``\\slashbox``/``\\backslashbox``
  ``[w][s]{A}{B}`` 双可选参 (w 默认 0pt 自然宽, s∈{l,r,lr} 抑制该侧
  ``\\tabcolsep`` 外探), picture-mode ``\\line`` 对角线 + 双标签。
- 参内 ``\\\\`` 经 ``\\shortstack`` 消化 —— 1109.5364
  ``\\backslashbox{\\\\climate\\\\ variable}{zone}`` 实证; 退化
  ``\\makebox`` 形在 tabular 受限横态炸 Missing/Extra } (95-targeted
  ``slashbox_arg_newline`` 规则仍作 syntax 相兜底)。
- ``\\ProvidesPackage`` 版本串必须 YYYY/MM/DD 日期开头 —— 裸文字版串经
  ``\\@parse@version@`` 漏进排版流 → Missing\\begin{document} (本 lane
  探针实证)。

实证面 (fixloop records 6 格): 1109.5364 / 1206.5785 / 1404.0561 /
1608.06845 / 2203.12985 / 2410.00118 —— 全部 ``\\usepackage{slashbox}`` +
``\\backslashbox{A}{B}`` 双参形。
"""

import re
import shutil
from pathlib import Path

from _fixloopkit import STUBS, n_err, requires_xelatex, run_xelatex

from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx

STUB = STUBS / "slashbox.sty"


def _code(body: str) -> str:
    """滤 % 注释行 —— pin 断言不被注释文本夹带。"""
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("%"))


# ------------------------------------------------------- 源码级 pin (免编译)


def test_both_public_macros_provided() -> None:
    """\\slashbox 与 \\backslashbox 双宏面齐 (providecommand 不覆盖稿自带)。"""
    code = _code(STUB.read_text(encoding="utf-8"))
    assert "\\providecommand{\\slashbox}" in code
    assert "\\providecommand{\\backslashbox}" in code


def test_picture_mode_diagonal_present() -> None:
    """双对角线: \\slashbox=/ (1 向), \\backslashbox=\\ (-1 向)。"""
    code = _code(STUB.read_text(encoding="utf-8"))
    assert "\\line(##1,1)" in code
    assert "\\line(##1,-1)" in code


def test_args_digested_by_shortstack() -> None:
    r"""参内 \\ 由 \shortstack 消化 —— 不得回潮 \makebox 退化形
    (tabular 受限横态 \\ 变行尾炸 Missing/Extra }, 1109.5364 实证)。"""
    code = _code(STUB.read_text(encoding="utf-8"))
    assert "\\shortstack[l]{#3}" in code
    assert "\\shortstack[r]{#4}" in code
    assert "\\makebox{#3" not in code


def test_optional_arg_chain_present() -> None:
    """真件签名 [w][s]{A}{B}: w 默认 0pt 自然宽, s 默认 c (双侧 tabcolsep)。"""
    code = _code(STUB.read_text(encoding="utf-8"))
    assert "[0pt]" in code
    assert "[c]" in code
    assert "\\@tfor" in code  # s ∈ {l,r,lr} 逐字符抑制


def test_providespackage_dated() -> None:
    """版本串日期开头 —— 裸文字版串漏进排版流 (Missing\\begin{document})。"""
    body = STUB.read_text(encoding="utf-8")
    m = re.search(r"\\ProvidesPackage\{slashbox\}\[([^\]]*)\]", body)
    assert m is not None
    assert re.match(r"\d{4}/\d{2}/\d{2}", m.group(1))


# ------------------------------------------------------- 交付通路


def test_vendored_fetch_drops_stub_default_root(tmp_path: Path) -> None:
    """missing_file payload slashbox.sty → 缺省 vendor 根命中 stubs 层落 wdir。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = TRANSFORM_FNS["vendored_fetch"](ctx, None, "slashbox.sty", {})
    assert ok, note
    assert "vendored[stubs]" in note
    dropped = ctx.wdir / "slashbox.sty"
    text = dropped.read_text(encoding="utf-8")
    assert text.startswith("% texlate-fixloop-injected:")
    assert "\\providecommand{\\backslashbox}" in text


# ------------------------------------------------------- 真编译钉


@requires_xelatex
def test_both_macros_render_in_tabular(tmp_path: Path) -> None:
    r"""tabular 单元格内双宏 + 可选宽 + 参内 \\ (1109.5364 形) 全零 '!' 错。"""
    shutil.copy(STUB, tmp_path / "slashbox.sty")
    log = run_xelatex(
        tmp_path,
        r"""\documentclass{article}
\usepackage{slashbox}
\begin{document}
\begin{tabular}{|l|c|}
\hline
\backslashbox{Method}{Omission\%} & $0\%$ \\ \hline
\slashbox{lower}{upper} & x \\ \hline
\backslashbox{\\climate\\ variable}{zone} & Temp \\ \hline
\backslashbox[30mm]{wide}{args} & y \\ \hline
\backslashbox[40mm][l]{suppressed}{sep} & z \\ \hline
\end{tabular}
\end{document}
""",
    )
    assert n_err(log) == 0, f"仍 {n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()


@requires_xelatex
def test_backslashbox_inside_multirow(tmp_path: Path) -> None:
    r"""1109.5364 实录形: \multirow{2}{*} \protect{\backslashbox{..}{..}}。"""
    shutil.copy(STUB, tmp_path / "slashbox.sty")
    log = run_xelatex(
        tmp_path,
        r"""\documentclass{article}
\usepackage{slashbox}
\usepackage{multirow}
\begin{document}
\begin{tabular}{|l|c|}
\hline
\multirow{2}{*} \protect{\backslashbox{\\climate\\ variable}{zone}} & Temp \\ \hline
& Precip \\ \hline
\end{tabular}
\end{document}
""",
    )
    assert n_err(log) == 0, f"仍 {n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()


@requires_xelatex
def test_usepackage_comma_list_form(tmp_path: Path) -> None:
    r"""1404.0561 形: \usepackage{...,slashbox,...} 逗号装载列表。"""
    shutil.copy(STUB, tmp_path / "slashbox.sty")
    log = run_xelatex(
        tmp_path,
        r"""\documentclass{article}
\usepackage{amsmath,array,graphicx,slashbox,multirow}
\begin{document}
\begin{tabular}{ll}
\backslashbox{$\gamma$}{$\gamma$'} & $a_{1g}$ \\
\end{tabular}
\end{document}
""",
    )
    assert n_err(log) == 0, f"仍 {n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()
