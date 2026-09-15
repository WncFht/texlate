r"""入口装配：``parse_tex`` / ``parse_file``（docs/07 §1）。

preamble 判定（spike 原样，W11 留档：``\begin {document}`` 带空格或注释内
的 ``\begin{document}`` 会被正则误判——低频，不修）：``\documentclass`` 与
``\begin{document}`` 同时在才切 preamble；preamble 整段 LITERAL + 只登记宏。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import os

from texlate.latex.flatten import flatten_inputs
from texlate.latex.macro_table import MacroTable
from texlate.latex.model import ScanResult, ScanState, ScanWarning
from texlate.latex.placeholder import PlaceholderIssuer
from texlate.latex.scanner import Scanner

_PREAMBLE_RX = re.compile(r"\\(documentclass|documentstyle)(?![a-zA-Z])")
_DOC_BEGIN_RX = re.compile(r"\\begin\{document\}")


def new_state() -> ScanState:
    """装配共享可变状态容器。"""
    return ScanState(
        issuer=PlaceholderIssuer(),
        ph_map={},
        chunks=[],
        macros=MacroTable(),
        inputs=[],
        warnings=[],
    )


def parse_tex(tex: str) -> ScanResult:
    """主入口：单文件文本 → ``ScanResult``。"""
    state = new_state()
    sc = Scanner(state)
    mdoc = _DOC_BEGIN_RX.search(tex)
    mpream = _PREAMBLE_RX.search(tex)
    preamble_end = mdoc.end() if (mpream and mdoc) else 0
    return sc.scan(tex, preamble_end=preamble_end)


def parse_file(path: str | os.PathLike[str], *, flatten: bool = True) -> ScanResult:
    r"""文件入口：读盘 → ``flatten_inputs`` → ``parse_tex``。"""
    tex = Path(path).read_text(encoding="utf-8", errors="replace")
    flat_warnings: list[ScanWarning] = []
    if flatten:
        d = str(Path(path).resolve().parent)
        tex = flatten_inputs(tex, d, d, warnings=flat_warnings)
    res = parse_tex(tex)
    res.warnings[:0] = flat_warnings
    return res
