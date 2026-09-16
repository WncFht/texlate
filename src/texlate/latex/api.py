r"""入口装配：``parse_tex`` / ``parse_file``（docs/07 §1）。

默认走 v2 token 流（``Gullet``+``Segmenter``）；``TEXLATE_NO_EXPAND=1``
回退 v1 字节 scanner（并存期基准对照，segmenter-integration §7）。
``*_v1`` 显式入口供 bench 双跑/对照使用。

v1 preamble 判定：``\documentclass`` 与 ``\begin{document}`` 同时在才切
preamble；preamble 整段 LITERAL + 只登记宏。两枚正则都跑在
``mask_tex`` 视图上（注释/逐字内假命中豁免——arXiv 常见注释掉的
备用 preamble；``\begin {document}`` 空格变体亦收）。
"""

from __future__ import annotations

import errno
import os
import re
from pathlib import Path

from texlate.latex.flatten import flatten_inputs
from texlate.latex.gullet import Gullet
from texlate.latex.macro_table import MacroTable
from texlate.latex.model import ScanResult, ScanState, ScanWarning
from texlate.latex.placeholder import PH_RX, PlaceholderIssuer
from texlate.latex.scanner import Scanner
from texlate.latex.segmenter import parse_tex_v2, scan_v2
from texlate.textutil import decode_tex, mask_tex

_PREAMBLE_RX = re.compile(r"\\(documentclass|documentstyle)(?![a-zA-Z])")
_DOC_BEGIN_RX = re.compile(r"\\begin\s*\{document\}")
_NO_EXPAND = "TEXLATE_NO_EXPAND"


def new_state() -> ScanState:
    """装配共享可变状态容器（v1 scanner 用）。"""
    return ScanState(
        issuer=PlaceholderIssuer(),
        ph_map={},
        chunks=[],
        macros=MacroTable(),
        inputs=[],
        warnings=[],
    )


def parse_tex_v1(tex: str) -> ScanResult:
    """v1 字节 scanner 入口（并存期基准对照）。"""
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


def parse_file_v1(
    path: str | os.PathLike[str],
    *,
    flatten: bool = True,
    top_dir: str | os.PathLike[str] | None = None,
) -> ScanResult:
    r"""v1 文件入口：读盘 → ``flatten_inputs`` → ``parse_tex_v1``。

    ``top_dir`` 透传 ``flatten_inputs`` 的同名兜底查找目录（与 v2
    ``parse_file`` 参面一致——``TEXLATE_NO_EXPAND`` 回退不丢语义）。
    """
    main = Path(path).resolve()
    if not main.is_file():  # fifo/设备/检查时点消失——read_bytes 会悬挂或裸 OSError
        raise OSError(errno.ENXIO, "not a regular file", str(main))
    tex = decode_tex(main.read_bytes())
    flat_warnings: list[ScanWarning] = []
    if flatten:
        d = str(main.parent)
        # 主文件预入祖先栈：``\input{self}`` 在 TeX 里是死循环，展平侧直接断
        tex = flatten_inputs(
            tex,
            d,
            d,
            _seen={str(main)},
            warnings=flat_warnings,
            top_dir=str(top_dir) if top_dir is not None else None,
        )
    res = parse_tex_v1(tex)
    res.warnings[:0] = flat_warnings
    return res


def parse_tex(tex: str) -> ScanResult:
    """主入口：单文件文本 → ``ScanResult``（v2 token 流为默认）。"""
    if os.environ.get(_NO_EXPAND):
        return parse_tex_v1(tex)
    return parse_tex_v2(tex)


def parse_file(
    path: str | os.PathLike[str],
    *,
    flatten: bool = True,
    top_dir: str | os.PathLike[str] | None = None,
) -> ScanResult:
    r"""文件入口：读盘 → v2 ``Gullet`` 路径。

    ``flatten=True``：``\\input`` 族由 gullet 按 文件目录→root_dir→top_dir
    解析内联进 vtex（``res.inputs`` 记 (vpos, 绝对路径)）——``top_dir`` 给
    e-print 顶层目录（缺省回落文件所在目录，与 v1 ``flatten_inputs(d,d)``
    同序）。``flatten=False``：无路径无 root 的内存源——``\\input`` 恒不解析
    → 漏网 literal + ``inputs[]`` 记原始名（standalone 单文件语义）。
    """
    if os.environ.get(_NO_EXPAND):
        return parse_file_v1(path, flatten=flatten, top_dir=top_dir)
    main = Path(path).resolve()
    if not main.is_file():  # fifo/设备/检查时点消失——read_bytes 会悬挂或裸 OSError
        raise OSError(errno.ENXIO, "not a regular file", str(main))
    tex = decode_tex(main.read_bytes())
    if flatten:
        g = Gullet(
            root_dir=str(main.parent),
            top_dir=str(top_dir) if top_dir is not None else "",
        )
        # 路径入 _seen 祖先栈：\input{self} 死循环直接断（v1 _seen 同语义）
        g.push_source(tex, str(main))
    else:
        g = Gullet()
        g.push_source(tex)
    return scan_v2(g)
