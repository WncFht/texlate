r"""builtins.gfx_missing.caselink — 缺图 ci 改名域 (gfx_missing 拆分)。

``graphic_case_link``: 引用在盘但引擎喊缺 —— 大小写不敏感找真身
(``_find_graphic_ci``) → ``\includegraphics``/``\includepdf`` 参数
改写真名; ``dir/{stem}.ext`` braced 名去括全量扫
(``_debrace_sweep``)。``_GRAPHIC_EXTS``/``_INCLUDE_GFX_RE``/
``_INCLUDE_PDF_RE``/``_graphic_ref_hit`` 是本族共享判定件,
``_gfxm_*`` 兄弟叶全经本叶直引。
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from texlate.compile.fixloop.builtins.graphics import (
    _NUMERIC_EXT_RE,
    _iter_project_files,
    _norm_graphic_name,
)
from texlate.textutil import safe_is_file

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from texlate.compile.fixloop.engine.ctx import LoopCtx
    from texlate.compile.fixloop.engine.proto import Engine


__all__ = [
    "_GRAPHIC_EXTS",
    "_INCLUDE_GFX_RE",
    "_INCLUDE_PDF_RE",
    "_NUMERIC_EXT_RE",
    "_debrace_sweep",
    "_find_graphic_ci",
    "_graphic_ref_hit",
    "_iter_project_files",
    "_norm_graphic_name",
    "_rewrite_case_refs",
    "graphic_case_link",
    "safe_is_file",
]


# ════════════════════════════════════════════════════════════════
# missing_graphic: 缺图 ci 改名 + 坏图分级修复
# (signature-mining 2026-09-16 top5#2: 2403.15102/2211.04457 大小写不符，
#  1502.06541/1012.5273 在盘拒载)
# ════════════════════════════════════════════════════════════════


#: graphicx 可装载图形扩展名面 —— 无扩展名 ``\includegraphics{x}`` 的
#: ci 补全候选域 (与 _EPS_EXTS 分工：那边管 PS 族转换，这边管全图形族匹配)。
_GRAPHIC_EXTS = (
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".eps",
    ".epsf",
    ".epsi",
    ".ps",
    ".mps",
)


#: ``\includegraphics`` 引用点：g1=可选 opts, g2=图像参数 (星号变体同收)。
#: arg 捕获面收一层内层花括 (``dir/{stem}.ext``/``{file.png}`` 两形) ——
#: ``[^}]*`` 在内层 ``}`` 处截断会漏 braced 实参 (1710.09412 micro2 实证)。
_INCLUDE_GFX_RE = re.compile(
    r"\\includegraphics\*?\s*(?:\[([^\]\n]*)\])?\s*\{((?:[^{}]|\{[^{}]*\})*)\}"
)


#: ``\includepdf[opts]{file}`` (pdfpages) 引用点 —— W66 孤儿裁决面：
#: 与 ``_INCLUDE_GFX_RE`` 分正则而非并表 —— graphic_repair 的 ``\fbox``
#: stub 语义只适用图像件，includepdf 缺件占位是 ``\clearpage\null``。
_INCLUDE_PDF_RE = re.compile(
    r"\\includepdf(?![a-zA-Z])\s*(?:\[([^\]\n]*)\])?\s*\{((?:[^{}]|\{[^{}]*\})*)\}"
)


def _find_graphic_ci(
    ctx: LoopCtx, want: str, files: list[Path] | None = None
) -> Path | None:
    r"""工程目录内大小写不敏感找图真身。

    命中序: 相对路径整串 ci 相等 / 文件名 ci 相等 (rank0) → want 无扩展名时
    stem ci 相等且扩展名在图形族面 (rank1, ``.\d+`` 数字扩展同收);
    多命中取 rank 低 + 相对路径短者 (确定性排序)。
    ``files`` 传 ``_ProjectScan.files`` 快照免逐 want 重扫 —— 候选面同走
    ``_iter_project_files`` 排除 (引擎封装树/隐藏面不做 ci 真身)。
    """
    want = _norm_graphic_name(want)
    if not want:
        return None
    wl = want.lower()
    base = PurePosixPath(wl).name
    stemless = "." not in base
    cands: list[tuple[int, int, str, Path]] = []
    for p in files if files is not None else _iter_project_files(ctx):
        rel = p.relative_to(ctx.wdir).as_posix().lower()
        if rel == wl or p.name.lower() == base:
            rank = 0
        elif (
            stemless
            and p.stem.lower() == base
            and (p.suffix.lower() in _GRAPHIC_EXTS or _NUMERIC_EXT_RE.match(p.suffix))
        ):
            rank = 1
        else:
            continue
        cands.append((rank, len(rel), str(p), p))
    if not cands:
        return None
    return min(cands, key=lambda t: t[:3])[3]


def _graphic_ref_hit(arg: str, want: str) -> bool:
    r"""``\includegraphics`` 参数 arg 是否指向 payload want (全 ci)。

    相等判定: 全路径 / basename / 无扩展名侧对侧 stem (``{fig}`` ↔
    ``fig.pdf`` 双向) —— 覆盖 ``{sf_08_VX}`` vs ``img/sf_08_VX.pdf`` 各形。
    """
    a = _norm_graphic_name(arg).lower()
    w = _norm_graphic_name(want).lower()
    if not a or not w:
        return False
    if a == w:
        return True
    ap, wp = PurePosixPath(a), PurePosixPath(w)
    if ap.name == wp.name:
        return True
    if "." not in ap.name and ap.name == wp.stem:
        return True
    return "." not in wp.name and ap.stem == wp.name


def _rewrite_case_refs(ctx: LoopCtx, exts: tuple[str, ...], want: str, rel: str) -> int:
    r"""逐 tex 文件: 指 want 且本不可解析的 ``\includegraphics``/``\includepdf`` 参数改写 rel。

    ``(wdir|filedir)/arg`` 已命中文件的引用是别人的好引用 —— 不动;
    该守卫同时保证二次触火幂等 (改写后 arg 恰可解析 → 不再命中改写条件)。
    W66 扩面: ``\includepdf`` 与 ``\includegraphics`` 共享 ci-glob 命中面。
    """
    changed = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None or ("\\includegraphics" not in t and "\\includepdf" not in t):
            continue

        def _sub(m: re.Match[str], _f: Path = f) -> str:
            arg = m.group(2)
            if not _graphic_ref_hit(arg, want):
                return m.group(0)
            a = _norm_graphic_name(arg)
            if safe_is_file(ctx.wdir / a) or safe_is_file(_f.parent / a):
                return m.group(0)
            return (
                m.group(0)[: m.start(2) - m.start()]
                + rel
                + m.group(0)[m.end(2) - m.start() :]
            )

        nt = _INCLUDE_GFX_RE.sub(_sub, t)
        nt = _INCLUDE_PDF_RE.sub(_sub, nt)
        if nt != t:
            ctx.write(f, nt)
            changed += 1
    return changed


def _debrace_sweep(ctx: LoopCtx, exts: tuple[str, ...], base: Path) -> int:
    r"""全工程 ``\includegraphics``/``\includepdf`` braced 参数去括改写。

    ``dir/{stem}.ext``/``{file.png}`` 内层分组符 xetex 不剥按字面名寻档
    (1710.09412 micro2 实证): 去括路径在解析位 (main_dir|filedir) 命中
    即改写。braced 字面名在盘 (病态但合法) → 不动; 去括名也不在 → 不动
    (真缺件留占位域)。一次点火全量扫 —— 逐 payload 版多 braced 名格
    (1710.09412 ~16 名) 同样烧穿轮次上限。返回改写文件数。
    """
    changed = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None or ("\\includegraphics" not in t and "\\includepdf" not in t):
            continue

        def _sub(m: re.Match[str], _f: Path = f) -> str:
            arg = m.group(2)
            if "{" not in arg and "}" not in arg:
                return m.group(0)
            a = _norm_graphic_name(arg)
            if safe_is_file(base / a) or safe_is_file(_f.parent / a):
                return m.group(0)
            d = _norm_graphic_name(a.replace("{", "").replace("}", ""))
            if not d or not (safe_is_file(base / d) or safe_is_file(_f.parent / d)):
                return m.group(0)
            return (
                m.group(0)[: m.start(2) - m.start()]
                + d
                + m.group(0)[m.end(2) - m.start() :]
            )

        nt = _INCLUDE_GFX_RE.sub(_sub, t)
        nt = _INCLUDE_PDF_RE.sub(_sub, nt)
        if nt != t:
            ctx.write(f, nt)
            changed += 1
    return changed


def graphic_case_link(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""大小写不符型 missing_graphic: ci 找真身 → ``\includegraphics`` 参数改写真名。

    实证: e-print 跨平台搬运后 ``{img/sf_08_VX.pdf}`` vs 盘上
    ``img/SF_08_VX.pdf`` 在 Linux 敏感 FS 挂 (2403.15102/2211.04457)。
    改写参数而非建 symlink —— 改写随工程走可移植, 不依赖 FS/平台语义。
    """
    del eng
    want = _norm_graphic_name(payload or "")
    if not want:
        return False, "no graphic payload"
    if safe_is_file(ctx.wdir / want):
        return False, f"{want} resolves verbatim — not a case mismatch"
    # 1710.09412 (micro2 普查): ``dir/{stem}.ext`` 部分花括名 —— xetex 不剥
    # 内层分组符按字面名寻档 (micro2 车道实证), 盘上真身是去括名。
    # braced payload 即文档惯用法证据 → 全量扫; 去括名不在盘的不动，让位
    # ci-glob/占位域。先于 ci-glob —— 精确路径级命中不该轮到占位件遮真图。
    if "{" in want or "}" in want:
        mp = ctx.main_path()
        base = mp.parent if mp is not None else ctx.wdir
        exts = tuple(params.get("exts") or (".tex", ".sty"))
        changed = _debrace_sweep(ctx, exts, base)
        if changed:
            return True, f"de-brace {want}: swept refs in {changed} file(s)"
    real = _find_graphic_ci(ctx, want)
    if real is None:
        return False, f"no case-variant of {want} in project"
    rel = real.relative_to(ctx.wdir).as_posix()
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    changed = _rewrite_case_refs(ctx, exts, want, rel)
    if not changed:
        return False, f"{want} -> {rel} resolved but no ref rewrote"
    return True, f"case-link {want} -> {rel}: rewrote refs in {changed} file(s)"
