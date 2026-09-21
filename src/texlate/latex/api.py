r"""入口装配：``parse_tex`` / ``parse_file``（docs/spec/latex-pipeline.md）。

v2 token 流（``Gullet``+``Segmenter``）是唯一解析路径。
"""

from __future__ import annotations

import errno
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    import os
    from collections.abc import Callable

    from texlate.latex.model import ScanResult

from texlate.latex.gullet import Gullet
from texlate.latex.prose import file_has_prose
from texlate.latex.segmenter import parse_tex_v2, scan_v2
from texlate.textutil import _tar_disguised, decode_tex


def parse_tex(tex: str, *, front_matter: frozenset[str] = frozenset()) -> ScanResult:
    """主入口：单文件文本 → ``ScanResult``（v2 token 流）。"""
    return parse_tex_v2(tex, front_matter=front_matter)


def parse_file(
    path: str | os.PathLike[str],
    *,
    flatten: bool = True,
    top_dir: str | os.PathLike[str] | None = None,
    front_matter: frozenset[str] = frozenset(),
) -> ScanResult:
    r"""文件入口：读盘 → v2 ``Gullet`` 路径。

    ``flatten=True``：``\\input`` 族由 gullet 按 文件目录→root_dir→top_dir
    解析内联进 vtex（``res.inputs`` 记 (vpos, 绝对路径)）——``top_dir`` 给
    e-print 顶层目录（缺省回落文件所在目录，``flatten_inputs`` 同序兜底）。
    ``flatten=False``：无路径无 root 的内存源——``\\input`` 恒不解析
    → 漏网 literal + ``inputs[]`` 记原始名（standalone 单文件语义）。
    ``front_matter`` = preamble 前置发射白名单（ScanState 同义透传）。
    """
    main = Path(path).resolve()
    if not main.is_file():  # fifo/设备/检查时点消失——read_bytes 会悬挂或裸 OSError
        raise OSError(errno.ENXIO, "not a regular file", str(main))
    blob = main.read_bytes()
    if _tar_disguised(blob):
        # tar 伪装 .tex——成员字节不是 tex 面（decode_tex 永不抛，写回即腐蚀）
        raise OSError(errno.EINVAL, "tar archive disguised as .tex", str(main))
    tex = decode_tex(blob)
    if flatten:
        g = Gullet(
            root_dir=str(main.parent),
            top_dir=str(top_dir) if top_dir is not None else "",
        )
        # 路径入 _seen 祖先栈：\input{self} 死循环直接断（flatten_inputs _seen 同语义）
        g.push_source(tex, str(main))
    else:
        g = Gullet()
        g.push_source(tex)
    return scan_v2(g, front_matter=front_matter)


# ------------------------------------------------------------------ 树扫描段
#: ``.rtx.tex``（REVTeX 运行时转储，regress4-1003.1717）——静默跳过不进任何
#: 名单。
RTX_TEX_SUFFIX: Final = ".rtx.tex"
#: ``.code.tex``（tikzlibrary 机制件）——散文门前置记 support，按原文保留。
CODE_TEX_SUFFIX: Final = ".code.tex"
#: 名闸并集——凭文件名即知非翻译内容件；``.tex`` 名闸知识属 latex 层
#: 单源——fixloop ``_SUPPORT_SUFFIXES``（``_builtins_misc``）已并指本常量。
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
    root: Path,
    *,
    on_file: Callable[[Path], None] | None = None,
    front_matter: frozenset[str] = frozenset(),
) -> TexTreeScan:
    r"""枚举树内 ``.tex`` → 四级分流（e2e/worker 两臂共享的扫描段单源）。

    门序：dotfile 跳过 → ``.rtx.tex`` 跳过 → ``.code.tex`` 记 support →
    解析崩分两叉（解析闸内判定）：``OSError(EINVAL)``（tar 伪装 ``.tex``，
    tar 闸在 ``parse_file`` 内）静默跳过——不进任何名单、逐字节保留；
    其余解析崩记 fault（单文件崩不拖垮整树，原文保留）→
    无散文记 support → 余者入 ``parsed``。
    ``on_file`` 逐文件回调——worker 取消轮询挂点，CLI/bench 臂缺省。
    ``front_matter`` = preamble 前置发射白名单（透传 ``parse_file``）。
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
            res = parse_file(f, flatten=False, front_matter=front_matter)
        except Exception as exc:  # noqa: BLE001 -- 单文件解析崩不拖垮整树
            if isinstance(exc, OSError) and exc.errno == errno.EINVAL:
                # tar 伪装 .tex——成员字节不是翻译面（decode_tex 永不抛会把
                # 成员文本当散文送译、写回腐蚀 blob）；不入任何名单，逐字节
                # 原样保留。tar 闸单源在 parse_file 内，扫树不再预读重复检
                continue
            out.fault.append((rel, exc))  # 记名可审计，该文件按原文保留
            continue
        if not file_has_prose(res.chunks):
            # 无散文（pstricks/epsf/宏件/gnuplot 转储）——送译即腐蚀，
            # 按原文保留；与 fault 分流：这里是有意跳过而非失败
            out.support.append(rel)
            continue
        out.parsed.append((f, rel, res))
    return out
