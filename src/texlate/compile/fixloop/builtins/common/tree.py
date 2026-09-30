r"""builtins.common.tree — 工作树指纹 + 工程件遍历 (common 拆分)。

``_wdir_fingerprint``/``_fp_diff`` —— engine ``_landing_sync`` 外部落件
基线与 ``builtins.misc._invalidate_changed``/docstrip 全量失效两侧消费
的通用树扫件; ``_wdir_project_files``/``_in_wdir`` —— 工程件遍历
(dot 段与 ``_texmf``/``_tect_out`` 引擎封装树排除, assetfix
``_conv_sibling`` 同口径共用, 自 builtins.shim 归位)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.textutil import safe_is_file

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

    from texlate.compile.fixloop.engine import LoopCtx

__all__ = [
    "_PDF_SANITIZE_SKIP_DIRS",
    "_fp_diff",
    "_in_wdir",
    "_wdir_fingerprint",
    "_wdir_project_files",
    "safe_is_file",
]


def _wdir_fingerprint(wdir: Path) -> dict[Path, tuple[int, int]]:
    """工作树文件 ``(mtime_ns, size)`` 指纹——``run_tool`` 改盘面快照 diff 用。

    通用树扫件而非规则实现——engine ``_landing_sync`` 的外部落件基线与
    ``builtins.misc._invalidate_changed``/docstrip 全量失效两侧消费。
    """
    fp: dict[Path, tuple[int, int]] = {}
    for p in wdir.rglob("*"):
        try:
            st = p.stat()
        except OSError:
            continue
        if p.is_file():
            fp[p] = (st.st_mtime_ns, st.st_size)
    return fp


def _fp_diff(
    before: dict[Path, tuple[int, int]],
    after: dict[Path, tuple[int, int]],
    *,
    exclude: Iterable[Path] = (),
) -> list[Path]:
    """指纹 diff 核：基线间变值路径集 (``exclude`` 自产写件除外)。

    ``_landing_sync`` 的外部落件判据与 ``builtins.misc._invalidate_changed``
    的通用补同核——后者免 exclude (全量失效)。
    """
    excl = set(exclude)
    return [
        p
        for p in set(before) | set(after)
        if before.get(p) != after.get(p) and p not in excl
    ]


#: 工程件遍历的排除目录 —— ``_texmf`` (wired vendored texmfhome) 与
#: ``_tect_out`` (tectonic 产物树) 是引擎/注入侧封装件，非稿自带件。
#: (canonical 自 builtins.graphics 归位 —— 彼侧副本删后回引本件。)
_PDF_SANITIZE_SKIP_DIRS = frozenset({"_texmf", "_tect_out"})


def _in_wdir(ctx: LoopCtx, p: Path) -> bool:
    """``p`` resolve 后是否仍落 ``ctx.wdir`` 内 —— resolve 失败按逃逸论。"""
    try:
        p.resolve().relative_to(ctx.wdir.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _wdir_project_files(ctx: LoopCtx) -> Iterator[tuple[Path, tuple[str, ...]]]:
    """``wdir`` 工程件遍历 → ``(path, wdir 相对 parts)``, dot 段与引擎树排除。

    dot 段路径 (``.git``/``.fixloop-*`` 类) 与任一段命中
    ``_PDF_SANITIZE_SKIP_DIRS`` (``_texmf`` wired texmfhome / ``_tect_out``
    tectonic 产物树) 的件都不算工程档——引擎封装件非稿自带，归位/hoist
    不得把它们当搬运源 (``parts[0]`` 判会漏嵌套位，须 any-part)。
    """
    for p in ctx.wdir.rglob("*"):
        if not safe_is_file(p):
            continue
        parts = p.relative_to(ctx.wdir).parts
        if any(part.startswith(".") for part in parts) or any(
            part in _PDF_SANITIZE_SKIP_DIRS for part in parts
        ):
            continue
        yield p, parts
