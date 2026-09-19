"""diagrams.tex vendored serving (envdiag fix 1, task #140):

``\\input{diagrams}`` → ``diagrams.tex`` 缺件: repo ``vendor/stubs/diagrams.tex``
真 stub (与 ``vendor/stubs/diagrams.sty`` 同源宏面剥包壳) 经
static_precheck ``_scan_vendored`` round-0 平铺, ``missing_file`` 不再
发火 → ``legacy_pkg_shim`` 空 stub 与 ``undefined_env_polyfill``
noop-env 链整段失效 (math/0104250 / math/0408052 实证链)。
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx, _apply_scan_install

VENDOR = Path(__file__).resolve().parent.parent / "src/texlate/compile/fixloop/vendor"


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


class _EngNoInstall:
    """probe 全缺 / install 全败的最小引擎替身 (vendored 兜底才有得走)。"""

    name = "xelatex"

    def __init__(self) -> None:
        self.install_calls: list[str] = []

    def probe_file(self, fname: str, cwd: Path | None = None) -> None:  # noqa: ARG002
        return None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:  # noqa: ARG002
        self.install_calls.append(fname)
        return False


# 30-route.yaml static_precheck 的 \input 扫描 pattern (suffix 补 .tex)。
_INPUT_SCAN = [
    {
        "regex": (
            r"\\(?:input|include|InputIfFileExists)(?=[^a-zA-Z])"
            r"\s*\{?([^\s{}%\\]+)"
        ),
        "suffix": ".tex",
    }
]


def _scan_params(**kw: object) -> dict:
    p = {"vendored": True, "scan_patterns": _INPUT_SCAN}
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
    ctx, eng = _ctx(tmp_path), _EngNoInstall()
    ok, note = _apply_scan_install(ctx, eng, _scan_params())
    assert ok
    landed = tmp_path / "diagrams.tex"
    assert landed.is_file()
    assert "diagrams.tex" in ctx.installed
    assert "vendored ['diagrams.tex']" in note
    body = landed.read_text(encoding="utf-8")
    # 真环境定义在场 (空 shim 仅 % 注释 + \endinput)
    assert "\\def\\diagram" in body
    assert "\\def\\enddiagram" in body
    assert "\\providecommand{\\rTo}" in body
    assert "\\def\\newarrow" in body
    # \input 装入件 @ 非字母 → makeatletter 包裹必须在场
    assert "\\makeatletter" in body
    # 包壳全剥: 无 \usepackage 期专属命令
    assert "\\ProvidesPackage" not in body
    assert "\\NeedsTeXFormat" not in body
    assert "\\ProcessOptions" not in body


def test_vendored_fetch_diagrams_tex(tmp_path: Path) -> None:
    """missing_file|diagrams.tex payload → vendored_fetch 同款落件。"""
    ctx = _ctx(tmp_path)
    ok, note = TRANSFORM_FNS["vendored_fetch"](ctx, None, "diagrams.tex", {})
    assert ok, note
    assert "vendored[stubs]" in note
    body = (tmp_path / "diagrams.tex").read_text(encoding="utf-8")
    assert "\\def\\diagram" in body


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("xelatex") is None, reason="xelatex not installed")
def test_diagrams_tex_input_compiles(tmp_path: Path) -> None:
    """``\\input{diagrams}`` preamble 装入真编译钉: {diagram} env /
    plain 式 / \\newarrow 自定义族全零 ``!`` 错 (math/0104250 形)。
    """
    shutil.copy(VENDOR / "stubs" / "diagrams.tex", tmp_path / "diagrams.tex")
    (tmp_path / "main.tex").write_text(
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
        encoding="utf-8",
    )
    xelatex = shutil.which("xelatex")
    subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
        [xelatex, "-interaction=nonstopmode", "main.tex"],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=False,
    )
    log = (tmp_path / "main.log").read_text(encoding="utf-8", errors="replace")
    n_err = len(re.findall(r"^! ", log, re.MULTILINE))
    assert n_err == 0, f"vendored diagrams.tex 装入后仍 {n_err} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()
