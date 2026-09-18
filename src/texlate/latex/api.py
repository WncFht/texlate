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
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    import os
    from collections.abc import Callable

from texlate.latex.flatten import flatten_inputs
from texlate.latex.gullet import Gullet
from texlate.latex.macro_table import MacroTable
from texlate.latex.model import ScanResult, ScanState, ScanWarning
from texlate.latex.placeholder import PH_RX, PlaceholderIssuer
from texlate.latex.prose import file_has_prose
from texlate.latex.scanner import Scanner
from texlate.latex.segmenter import parse_tex_v2, scan_v2
from texlate.textutil import (
    BEGIN_DOC_RX,
    DOCCLASS_RX,
    _tar_disguised,
    decode_tex,
    env_flag,
    mask_tex,
)

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
    mdoc = BEGIN_DOC_RX.search(masked)
    mpream = DOCCLASS_RX.search(masked)
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
    blob = main.read_bytes()
    if _tar_disguised(blob):
        # tar 伪装 .tex——decode_tex 永不抛会把成员字节当散文喂
        # parse→reconstruct 写回即腐蚀 blob；直读入口按 OSError 拒
        raise OSError(errno.EINVAL, "tar archive disguised as .tex", str(main))
    tex = decode_tex(blob)
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
    if env_flag(_NO_EXPAND, default=False):
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
    if env_flag(_NO_EXPAND, default=False):
        return parse_file_v1(path, flatten=flatten, top_dir=top_dir)
    main = Path(path).resolve()
    if not main.is_file():  # fifo/设备/检查时点消失——read_bytes 会悬挂或裸 OSError
        raise OSError(errno.ENXIO, "not a regular file", str(main))
    blob = main.read_bytes()
    if _tar_disguised(blob):
        # tar 伪装 .tex——成员字节不是 tex 面（同 parse_file_v1 闸）
        raise OSError(errno.EINVAL, "tar archive disguised as .tex", str(main))
    tex = decode_tex(blob)
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


# ------------------------------------------------------------------ 树扫描段
#: ``.rtx.tex``（REVTeX 运行时转储，regress4-1003.1717）——静默跳过不进任何
#: 名单。
RTX_TEX_SUFFIX: Final = ".rtx.tex"
#: ``.code.tex``（tikzlibrary 机制件）——散文门前置记 support，按原文保留。
CODE_TEX_SUFFIX: Final = ".code.tex"
#: 名闸并集——凭文件名即知非翻译内容件；fixloop ``_SUPPORT_SUFFIXES``
#: （builtins.py）同表，待换指本常量。
NAME_GATED_TEX_SUFFIXES: Final = (RTX_TEX_SUFFIX, CODE_TEX_SUFFIX)


@dataclass(slots=True)
class TexTreeScan:
    """``scan_tex_tree`` 产物：四级分流后三桶。"""

    #: ``(abspath, root 相对 posix, ScanResult)``——过散文门的内容件，序稳定。
    parsed: list[tuple[Path, str, ScanResult]] = field(default_factory=list)
    #: 有意不进翻译集（``.code.tex`` 机制件/无散文宏件转储）——按原文保留。
    support: list[str] = field(default_factory=list)
    #: 解析崩记名 ``(rel, exc)``——该文件按原文保留；异常随行供记 log。
    fault: list[tuple[str, Exception]] = field(default_factory=list)


def scan_tex_tree(
    root: Path, *, on_file: Callable[[Path], None] | None = None
) -> TexTreeScan:
    r"""枚举树内 ``.tex`` → 四级分流（e2e/worker 两臂共享的扫描段单源）。

    门序：dotfile 跳过 → ``.rtx.tex`` 跳过 → ``.code.tex`` 记 support →
    解析崩记 fault（不拖垮整树）→ 无散文记 support → 余者入 ``parsed``。
    ``on_file`` 逐文件回调——worker 取消轮询挂点，CLI/bench 臂缺省。
    """
    out = TexTreeScan()
    for f in sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".tex"
    ):
        if on_file is not None:
            on_file(f)
        if f.name.startswith("."):
            continue  # 隐文件不进翻译集
        lowered = f.name.lower()
        if lowered.endswith(RTX_TEX_SUFFIX):
            continue  # REVTeX 运行时转储不进翻译集
        rel = f.relative_to(root).as_posix()
        if lowered.endswith(CODE_TEX_SUFFIX):
            out.support.append(rel)
            continue
        try:
            blob = f.read_bytes()
        except OSError:
            blob = b""  # 读不动交给下方 parse_file 的 fault 分流记名
        if _tar_disguised(blob):
            # tar 伪装 .tex——成员字节不是翻译面（decode_tex 永不抛会把成员
            # 文本当散文送译、写回腐蚀 blob）；不入任何名单，逐字节原样保留
            continue
        try:
            res = parse_file(f, flatten=False)
        except Exception as exc:  # noqa: BLE001 -- 单文件解析崩不拖垮整树
            out.fault.append((rel, exc))  # 记名可审计，该文件按原文保留
            continue
        if not file_has_prose(res.chunks):
            # 无散文（pstricks/epsf/宏件/gnuplot 转储）——送译即腐蚀，
            # 按原文保留；与 fault 分流：这里是有意跳过而非失败
            out.support.append(rel)
            continue
        out.parsed.append((f, rel, res))
    return out
