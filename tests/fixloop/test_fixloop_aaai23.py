"""eracls 车道 (2026-09-20): ``vendor/stubs/aaai23.sty`` 钉测试。

census era-cls-absent-vendor 唯一真空件: aaai23.sty off-CTAN/TL
(``tlmgr search --file`` 零命中, install 路够不到) —— vendored_fetch
(11.5, missing_file 全payload basename) 是服务径。stub 面照稿自带
aaai2026.sty 实件抄 (``\\affiliations``/``\\equalcontrib``/copyright 族/
``\\pubnote``/``\\keywords`` + submission/draft 选项吞), 版式不强制
(espcrc2 先例)。
"""

from pathlib import Path

import pytest
from _fixloopkit import n_err, requires_xelatex, run_xelatex

import texlate.compile.fixloop as _fixloop_mod
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.builtins.vendored import _vendored_source
from texlate.compile.fixloop.engine import LoopCtx

STUBS = Path(_fixloop_mod.__file__).parent / "vendor" / "stubs"


def test_aaai23_vendored_resolution() -> None:
    """包内 vendor 根 basename 查件: aaai23.sty → stubs 层命中。"""
    src = _vendored_source(STUBS.parent, "aaai23.sty")
    assert src is not None
    assert src.parent.name == "stubs"


def test_aaai23_fetch_drops(tmp_path: Path) -> None:
    """vendored_fetch(真 vendor 根) → stubs 件平铺 wdir, note 标层。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok, note = TRANSFORM_FNS["vendored_fetch"](ctx, None, "aaai23.sty", {})
    assert ok, note
    assert "vendored[stubs]" in note
    assert (tmp_path / "aaai23.sty").is_file()


@pytest.mark.integration
@requires_xelatex
def test_aaai23_stub_surface_compiles(tmp_path: Path) -> None:
    """stub 宏面真编译钉: [submission] 选项吞 + \\affiliations 附 \\@author
    + \\equalcontrib→\\thanks + copyright/keywords/pubnote 族 —— 全零 ``!`` 错。

    实证基线 2303.16206/supp.tex: \\usepackage[submission]{aaai23} +
    \\affiliations{…\\textsuperscript{\\rm 1}…\\\\…} + \\author{…\\equalcontrib…}。
    """
    log = run_xelatex(
        tmp_path,
        r"""% !TeX program = xelatex
\documentclass[letterpaper]{article}
\usepackage[submission]{aaai23}
\title{Some AAAI Paper}
\author{
    First Author\textsuperscript{\rm 1}\thanks{With help.}\\
    Second Author \textsuperscript{\rm 1}\equalcontrib\\
    Third Author \textsuperscript{\rm 2}\equalcontrib
}
\affiliations{
    \textsuperscript{\rm 1}Affiliation One\\
    \textsuperscript{\rm 2}Affiliation Two\\
    name@example.com
}
\nocopyright
\copyrightyear{2023}
\copyrighttext{Copyright text.}
\pubnote{Running head text.}
\keywords{alpha, beta}
\begin{document}
\maketitle
\begin{abstract}
Abstract body.
\end{abstract}
\section{Intro}
Body text.
\end{document}
""",
        extra={"aaai23.sty": (STUBS / "aaai23.sty").read_text(encoding="utf-8")},
    )
    assert n_err(log) == 0, f"aaai23 stub 宏面仍 {n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()
