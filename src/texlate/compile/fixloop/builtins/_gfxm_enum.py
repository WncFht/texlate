r"""builtins._gfxm_enum — 缺件枚举与工程快照域 (gfx_missing 拆分)。

``_LOG_MISS_GFX_RE`` log 全量枚举 + ``_graphicspath_dirs`` 声明目录
并集 + ``_enum_missing_graphics`` 源侧静态枚举 (halt_on_error 盲区
补全) + ``_ProjectScan`` 单轮点火共享快照/宏模板缓存 ——
``_gfxm_stub``/``_gfxm_driver`` 两消费叶共用。
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from texlate.compile.fixloop.builtins._gfxm_caselink import (
    _GRAPHIC_EXTS,
    _INCLUDE_GFX_RE,
)
from texlate.compile.fixloop.builtins._gfxm_refscan import (
    _EPS_KV_RE,
    _KV_FILE_RE,
    _gfx_macro_templates,
)
from texlate.compile.fixloop.builtins.common import _live_matches
from texlate.compile.fixloop.builtins.graphics import (
    _iter_project_files,
    _norm_graphic_name,
)
from texlate.textutil import safe_is_file

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop._engine_proto import Engine


__all__ = [
    "_ENUM_ARG_BAD_RE",
    "_GRAPHICSPATH_RE",
    "_GSPATH_DIR_RE",
    "_LOG_MISS_GFX_RE",
    "_ProjectScan",
    "_disk_hit",
    "_enum_missing_graphics",
    "_graphicspath_dirs",
]


#: 编译 log 全量枚举缺图签名的两形 —— nonstop 编译单趟即列全部缺件
#: (``File `X' not found`` 兼中 pdftex.def ": using draft setting" 前缀与
#: LaTeX Warning/Error 两阶; ``Unable to load picture or PDF file 'X'`` 是
#: xetex 图形域专属)。多缺件格逐轮单补烧穿轮次上限 (v3all
#: 2501.01329/2501.01425 实证：8 轮逐件补，末件占位写于末次编译后 →
#: 差一轮翻 clean) —— 一次点火同签全补。
_LOG_MISS_GFX_RE = re.compile(
    r"Unable to load picture or PDF file '([^']+)'|File `([^']+)' not found"
)


# ═══ 源侧枚举 (haltsweep): halt_on_error 下 log 只曝首件，log 扫不够 ═══


#: ``\graphicspath{{d1/}{d2/}}`` 声明点 (遮盖视图; 多次声明取并集=保守超集)。
_GRAPHICSPATH_RE = re.compile(r"\\graphicspath\s*\{((?:[^{}]|\{[^{}]*\})*)\}")


_GSPATH_DIR_RE = re.compile(r"\{([^{}]*)\}")


#: 枚举只收字面 arg —— 宏拼名/特殊字符形 (``\imgdir/x``) 静态不可判，
#: 留在 log 驱动臂 (``_LOG_MISS_GFX_RE``) 的既有逐件路径。
_ENUM_ARG_BAD_RE = re.compile(r"[\\%#~^&$'\"`\x00-\x1f]")


def _graphicspath_dirs(ctx: LoopCtx) -> list[PurePosixPath]:
    r"""全工程活 ``\graphicspath`` 目录并集 —— 超集只减误判 (不误占位真图)。"""
    dirs: list[PurePosixPath] = []
    for f in ctx.tex_files():
        t = ctx.read(f)
        if t is None or "\\graphicspath" not in t:
            continue
        for m in _live_matches(_GRAPHICSPATH_RE, t):
            for raw in _GSPATH_DIR_RE.findall(m.group(1)):
                d = _norm_graphic_name(raw).rstrip("/")
                pp = PurePosixPath(d)
                if (
                    d
                    and not pp.is_absolute()
                    and ".." not in pp.parts
                    and not _ENUM_ARG_BAD_RE.search(d)
                    and pp not in dirs
                ):
                    dirs.append(pp)
    return dirs


def _disk_hit(ctx: LoopCtx, p: Path, disk: set[str] | None) -> bool:
    """快照成员检 + 实况兜底。

    ``disk`` (wdir 相对 posix 名集) 在册免 stat; 脱册回落 ``safe_is_file``
    —— sweep 内新落盘件与 symlink 径件不受快照盲区。
    """
    if disk is not None:
        try:
            if p.relative_to(ctx.wdir).as_posix() in disk:
                return True
        except ValueError:
            pass
    return safe_is_file(p)


def _enum_missing_graphics(
    ctx: LoopCtx, eng: Engine | None, base: Path, disk: set[str] | None = None
) -> list[str]:
    r"""源侧枚举存活图形引用的全部缺件名 —— halt_on_error 盲区补全。

    fixloop 编译走 ``halt_on_error`` —— 每轮 log 只曝首个缺件
    (``_LOG_MISS_GFX_RE`` 扫不出未达段), 逐 payload 补件在多缺件格
    烧穿轮次上限 (v3all 2501.01425: 8 轮补 8 件, log 从未触及的第 9+
    件仍在)。对每张 tex: 活 ``\includegraphics``/epsfig 族字面 arg →
    解析位 (filedir / main_dir / wdir / ``\graphicspath`` 目录) 全 miss
    即缺件候选; 带后缀 arg 再过 ``eng.probe_file`` (kpathsea texmf 树
    —— 防占位遮蔽 texlive 随发图如 mwe ``example-image.pdf``; 无后缀
    arg 免探: 同名 texmf 图按 ``\Gin@extensions`` 扩展序先中, 落盘
    ``.eps`` 永不遮蔽)。非字面 arg 跳过 —— 静态不可判, 归 log 臂。
    ``disk`` 传 ``_ProjectScan.disk`` 快照: arg×root×ext 成员检免逐件
    stat, 脱册路径仍实况兜底 (与全 stat 口径语义等价)。
    """
    gspath = _graphicspath_dirs(ctx)
    wants: list[str] = []
    for f in ctx.tex_files():
        t = ctx.read(f)
        if t is None or not any(
            k in t for k in ("\\includegraphics", "\\epsf", "\\psfig")
        ):
            continue
        args = [m.group(2) for m in _live_matches(_INCLUDE_GFX_RE, t)]
        for m in _live_matches(_EPS_KV_RE, t):
            kv = _KV_FILE_RE.search(m.group(1))
            args.append(kv.group(1) if kv else m.group(1))
        for arg in args:
            a = _norm_graphic_name(arg)
            if not a or _ENUM_ARG_BAD_RE.search(a):
                continue
            pp = PurePosixPath(a)
            if pp.is_absolute() or ".." in pp.parts:
                continue
            exts = ("",) if pp.suffix else ("", *_GRAPHIC_EXTS)
            roots = [f.parent, base, ctx.wdir]
            roots += [r / g for g in gspath for r in (f.parent, base, ctx.wdir)]
            if any(
                _disk_hit(ctx, root / f"{a}{e}", disk) for root in roots for e in exts
            ):
                continue
            if pp.suffix and eng is not None and eng.probe_file(a, cwd=base):
                continue  # texmf 树可解 (mwe 族) —— 占位会遮蔽真件，跳过
            if a not in wants:
                wants.append(a)
    return wants


class _ProjectScan:
    """单轮点火共享的工程文件快照 + 懒取宏模板缓存 —— 占位 sweep 免逐 want 重扫。

    ``files``/``disk`` 走 ``_iter_project_files`` 排除面 —— ``disk`` 为
    wdir 相对 posix 名集，供 ``_enum_missing_graphics`` 成员检免逐
    arg×root×ext stat。sweep 落盘件经 ``add`` 入册，后续 want 的
    ci/去括救检立见 (与逐件 rglob 读到新件同语义)。``templates()``
    懒取 ``_gfx_macro_templates`` —— 只有无后缀 want 的活引用复核需要。
    """

    def __init__(self, ctx: LoopCtx) -> None:
        self._ctx = ctx
        self.files = _iter_project_files(ctx)
        self.disk = {p.relative_to(ctx.wdir).as_posix() for p in self.files}
        self._templates: dict[str, dict[str, Any]] | None = None

    def templates(self) -> dict[str, dict[str, Any]]:
        """``_gfx_macro_templates`` 结果缓存 —— 首取后全 sweep 复用。"""
        if self._templates is None:
            self._templates = _gfx_macro_templates(self._ctx)
        return self._templates

    def add(self, p: Path) -> None:
        """Sweep 内新落盘件入册。"""
        try:
            rel = p.relative_to(self._ctx.wdir).as_posix()
        except ValueError:
            return
        if rel not in self.disk:
            self.disk.add(rel)
            self.files.append(p)
