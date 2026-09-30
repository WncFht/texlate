r"""入口装配：``parse_tex`` / ``parse_file``（docs/spec/latex-pipeline.md）。

v2 token 流（``Gullet``+``Segmenter``）是唯一解析路径。
"""

from __future__ import annotations

import errno
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
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
#: 单源——fixloop ``_SUPPORT_SUFFIXES``（``builtins.misc``）已并指本常量。
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
    #: ``main`` 闭包外剔出的 parsed 候选（⊆ support，单列供审计记 log）。
    unreachable: list[str] = field(default_factory=list)


def scan_tex_tree(
    root: Path,
    *,
    main: Path | None = None,
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
    ``main`` 非空时按 ``\\input`` 闭包裁剪 ``parsed``（``_drop_unreachable``）。
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
    if main is not None:
        _drop_unreachable(out, root, main)
    return out


def _drop_unreachable(  # noqa: C901, PLR0912 -- fail-open 闸序平铺即安全语义本体
    scan: TexTreeScan, root: Path, main: Path
) -> None:
    r"""以 ``main`` 的 ``\input`` 闭包裁剪 ``parsed``——闭包外件剔入 support。

    t_6648 教训：e-print tarball 嵌整份复件论文（``A Baseline…/main.tex``），
    主文件链永不引用——其 chunk 全为幽灵：译文照翻（token 双倍烧）、DOM 双份
    渲染、zh 注锚永不落 PDF（seqpos 缺 ``t`` 侧全来自幽灵区）。

    闭包 = ``parse_file(main, flatten=True, top_dir=root)`` 的 ``res.inputs``
    绝对路径集——gullet 展平内联即引擎真相：``\input``/``\include``/
    ``\subfile``/``\import`` 双参/in-arg 全覆盖且含传递（MAX_INPUTS=8 深度
    拒绝项落 ``missing_input`` warning，经漏网名面保命）。

    fail-open 四闸——闭包不可证即保留（误剔方向 = 真内容不译，绝对禁）：
    ① flatten 解析崩 ② 动态文件名（``res.input_dyn>0``：``\input{\cs}``/
    计算式名，gullet ArgMismatch 静默区）③ 漏网字面名与候选件
    basename+.tex 配对成功（深度拒/seen 断环/真缺失不可分——过保方向）
    ④ main 自身不可相对定位。
    """
    try:
        res = parse_file(main, flatten=True, top_dir=root)
    except Exception:  # noqa: BLE001 -- 闭包不可证 → 全量保留
        return
    if res.input_dyn:
        return  # 动态文件名输入在——闭包不完备，fail-open
    try:
        root_r = root.resolve()
        keep = {main.resolve().relative_to(root_r).as_posix()}
    except (OSError, RuntimeError, ValueError):
        return
    raw: list[str] = []
    for _pos, name in res.inputs:
        if Path(name).is_absolute():
            try:
                keep.add(Path(name).resolve().relative_to(root_r).as_posix())
            except (OSError, RuntimeError, ValueError):
                continue  # 越界输入（texmf/绝对路径外件）与树内分流无关
        else:
            raw.append(name)
    for w in res.warnings:
        if w.kind != "missing_input":
            continue
        # detail 形：``cmd:fname``/``f{n} cmd:fname``/``depth>N:fname``/
        # ``tag:t@fname``——末段 ``:``/``@`` 分界取文件名（含 ``:`` 的病理
        # 名不撑，e-print 无此物）
        fname = w.detail.split("@")[-1].split(":")[-1].strip()
        if fname:
            raw.append(fname)
    cand: set[str] = set()
    for n in raw:
        base = PurePosixPath(n.replace("\\", "/")).name
        if not base:
            continue
        # 无后缀门——``Path.suffix`` 把词干点号误当扩展名（``2.1_x`` →
        # ``.1_x``）会漏掉 arXiv ``N.N_name`` 全族；候选本就是过保方向
        # （parsed 只有 .tex 件，``foo.sty`` 类候选永不误配）。
        cand.add(base)
        if not base.lower().endswith(".tex"):
            cand.add(base + ".tex")
    parsed: list[tuple[Path, str, ScanResult]] = []
    for f, rel, res_f in scan.parsed:
        if rel in keep or PurePosixPath(rel).name in cand:
            parsed.append((f, rel, res_f))
            continue
        scan.unreachable.append(rel)
        scan.support.append(rel)  # 原文保留——zh 树镜像不丢件
    scan.parsed = parsed
