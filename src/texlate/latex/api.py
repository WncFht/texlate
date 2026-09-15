r"""入口装配：``parse_tex`` / ``parse_file``（docs/07 §1）。

preamble 判定：``\documentclass`` 与 ``\begin{document}`` 同时在才切
preamble；preamble 整段 LITERAL + 只登记宏。两枚正则都跑在
``mask_tex`` 视图上（注释/逐字内假命中豁免——arXiv 常见注释掉的
备用 preamble；``\begin {document}`` 空格变体亦收）。
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
from texlate.latex.placeholder import PH_RX, PlaceholderIssuer
from texlate.latex.scanner import Scanner
from texlate.textutil import decode_tex, mask_tex

_PREAMBLE_RX = re.compile(r"\\(documentclass|documentstyle)(?![a-zA-Z])")
_DOC_BEGIN_RX = re.compile(r"\\begin\s*\{document\}")


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
    # 源文自带 [[X_n]] 形字面 → 签发避让 + 信号（reconstruct 会把原文当 ph 展开）
    reserved = PH_RX.findall(tex)
    if reserved:
        state.ph_reserved.update(reserved)
        state.warnings.append(
            ScanWarning("ph_collision", 0, f"{len(reserved)} 处 [[X_n]] 形字面")
        )
    sc = Scanner(state)
    # 等长遮盖视图：注释/verbatim 内的假 \begin{document} 不参与判定，
    # 命中的 offset 与原文逐字节对齐（W11 留档弱点修复——曾接受不修）。
    masked = mask_tex(tex)
    mdoc = _DOC_BEGIN_RX.search(masked)
    mpream = _PREAMBLE_RX.search(masked)
    preamble_end = mdoc.end() if (mpream and mdoc) else 0
    return sc.scan(tex, preamble_end=preamble_end)


def parse_file(path: str | os.PathLike[str], *, flatten: bool = True) -> ScanResult:
    r"""文件入口：读盘 → ``flatten_inputs`` → ``parse_tex``。"""
    tex = decode_tex(Path(path).read_bytes())
    flat_warnings: list[ScanWarning] = []
    if flatten:
        d = str(Path(path).resolve().parent)
        tex = flatten_inputs(tex, d, d, warnings=flat_warnings)
    res = parse_tex(tex)
    res.warnings[:0] = flat_warnings
    return res
