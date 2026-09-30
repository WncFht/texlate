"""diagrams.tex vendored serving (envdiag fix 1, task #140):

``\\input{diagrams}`` → ``diagrams.tex`` 缺件：repo ``vendor/stubs/diagrams.tex``
真 stub (与 ``vendor/stubs/diagrams.sty`` 同源宏面剥包壳) 经
static_precheck ``_scan_vendored`` round-0 平铺，``missing_file`` 不再
发火 → ``legacy_pkg_shim`` 空 stub 与 ``undefined_env_polyfill``
noop-env 链整段失效 (math/0104250 / math/0408052 实证链)。
"""

import shutil
from pathlib import Path

import pytest
from _fixloopkit import EngStub, mk_ctx, n_err, requires_xelatex, rule, run_xelatex

import texlate.compile.fixloop as _fixloop_mod
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import _apply_scan_install

VENDOR = Path(_fixloop_mod.__file__).parent / "vendor"


def _scan_params(**kw: object) -> dict:
    """30-route.yaml ``static_precheck`` 的活 params (随 yaml 漂移) + kw 覆写。"""
    p = dict(rule("static_precheck").action.get("params") or {})
    p.update(kw)
    return p


def test_diagrams_tex_is_vendored() -> None:
    """basename ``diagrams.tex`` 在 vendor stubs/ 层收得到件。"""
    assert (VENDOR / "stubs" / "diagrams.tex").is_file()
    assert not (VENDOR / "files" / "diagrams.tex").exists()


def test_scan_install_drops_real_diagrams_tex(tmp_path: Path) -> None:
    """``\\input{diagrams}`` + 裸名 ``\\input diagrams`` 扫描 → 真 stub 落 wdir。

    缺省 ``dir`` → 包内真 vendor 根; 落盘件是富 stub 非 yaml 空 shim。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\input{diagrams}\n\\input diagrams\n",
        encoding="utf-8",
    )
    ctx, eng = mk_ctx(tmp_path), EngStub()
    ok, note = _apply_scan_install(ctx, eng, _scan_params())
    assert ok
    landed = tmp_path / "diagrams.tex"
    assert landed.is_file()
    assert "diagrams.tex" in ctx.installed
    assert "vendored" in note
    assert "diagrams.tex" in note
    body = landed.read_text(encoding="utf-8")
    # 真环境定义在场 (空 shim 仅 % 注释 + \endinput)
    assert "\\def\\diagram" in body
    assert "\\def\\enddiagram" in body
    assert "\\providecommand{\\rTo}" in body
    assert "\\def\\newarrow" in body
    # \input 装入件 @ 非字母 → makeatletter 包裹必须在场
    assert "\\makeatletter" in body
    # 包壳全剥：无 \usepackage 期专属命令
    assert "\\ProvidesPackage" not in body
    assert "\\NeedsTeXFormat" not in body
    assert "\\ProcessOptions" not in body


def test_vendored_fetch_diagrams_tex(tmp_path: Path) -> None:
    """missing_file|diagrams.tex payload → vendored_fetch 同款落件。"""
    ctx = mk_ctx(tmp_path)
    ok, note = TRANSFORM_FNS["vendored_fetch"](ctx, None, "diagrams.tex", {})
    assert ok, note
    assert "vendored[stubs]" in note
    body = (tmp_path / "diagrams.tex").read_text(encoding="utf-8")
    assert "\\def\\diagram" in body


@pytest.mark.integration
@requires_xelatex
def test_diagrams_tex_input_compiles(tmp_path: Path) -> None:
    """``\\input{diagrams}`` preamble 装入真编译钉：{diagram} env /
    plain 式 / \\newarrow 自定义族全零 ``!`` 错 (math/0104250 形)。
    """
    shutil.copy(VENDOR / "stubs" / "diagrams.tex", tmp_path / "diagrams.tex")
    log = run_xelatex(
        tmp_path,
        r"""% !TeX program = xelatex
\documentclass{article}
\usepackage{amsmath}
\input{diagrams}
\newarrow{Equalto}{=}{=}{=}{=}{=}
\begin{document}
text
\begin{diagram}
A &\rTo^{f}& B \cr
\dTo_{g} && \dEqualto \cr
C &\rEqualto& D \cr
\end{diagram}
\begin{equation}\begin{diagram}
X &\rTo& Y \\ \dTo && \dTo \\ Z &\rTo& W
\end{diagram}\end{equation}
\diagram E &\rTo& F \cr G &\dTo& H \enddiagram
\end{document}
""",
    )
    assert n_err(log) == 0, f"vendored diagrams.tex 装入后仍 {n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()
