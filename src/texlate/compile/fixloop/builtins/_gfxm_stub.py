r"""builtins._gfxm_stub — 真缺件占位落盘域 (gfx_missing 拆分)。

``graphic_missing_placeholder``/``_stub_sweep``/``_stub_graphic_at``:
解析位 (main_dir) 落最小合法格式占位 —— 扩展名分发
``_gfxm_assets`` 四件; 双层守卫 ``..`` 拒 + wdir 逃逸拒 + 已在盘
decline; rescue_check 下 ci/去括变体在盘让位 case_link。
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from texlate.compile.fixloop.builtins._gfxm_assets import (
    _EPS_PLACEHOLDER,
    _JPEG_PLACEHOLDER,
    _PDF_PLACEHOLDER,
    _PNG_PLACEHOLDER,
)
from texlate.compile.fixloop.builtins._gfxm_caselink import (
    _GRAPHIC_EXTS,
    _find_graphic_ci,
)
from texlate.compile.fixloop.builtins._gfxm_enum import (
    _LOG_MISS_GFX_RE,
    _enum_missing_graphics,
    _ProjectScan,
)
from texlate.compile.fixloop.builtins._gfxm_refscan import (
    _has_live_graphic_ref,
)
from texlate.compile.fixloop.builtins.common import _fixloop_log
from texlate.compile.fixloop.builtins.graphics import (
    _EPS_EXTS,
    _norm_graphic_name,
)
from texlate.textutil import safe_is_file

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop._engine_proto import Engine


__all__ = [
    "_EPS_EXTS",
    "_fixloop_log",
    "_stub_graphic_at",
    "_stub_sweep",
    "graphic_missing_placeholder",
]


def _stub_graphic_at(  # noqa: C901, PLR0911, PLR0912 - 逐门 decline note 即归因
    ctx: LoopCtx, base: Path, want: str, *, rescue_check: bool, scan: _ProjectScan
) -> tuple[bool, str]:
    r"""单件缺图占位落盘 —— ``graphic_missing_placeholder`` 逐 payload 核。

    ``rescue_check=True`` (log 扫描补件): 去括名/ci-变体在盘 → decline
    让路 case_link 下轮按真名修复 —— 占位是缺件兜底不该遮可救真图。
    首错 payload 不做此检: case_link@17 本轮已先评 (含 kv 形引用
    ``_INCLUDE_GFX_RE`` 够不着时占位落名仍是唯一编译救法)。
    ``scan`` 携带本轮共享文件快照/宏模板缓存 —— 逐 want 不重扫全树。
    """
    suffix = PurePosixPath(want).suffix.lower()
    if suffix and suffix not in _GRAPHIC_EXTS:
        return False, f"{want}: not a known graphic ext"
    if not suffix:
        if not _has_live_graphic_ref(ctx, want, scan.templates()):
            return False, f"{want}: no live graphic ref — not graphic domain"
        want += ".eps"
        suffix = ".eps"
    if ".." in PurePosixPath(want).parts:
        return False, f"{want}: path traversal rejected"
    f = base / want
    try:
        f.resolve().relative_to(ctx.wdir.resolve())
    except (OSError, RuntimeError, ValueError):
        return False, f"{want}: escapes wdir"
    if safe_is_file(f):
        return False, f"{want}: resolved meanwhile"
    if rescue_check:
        d = want.replace("{", "").replace("}", "")
        if d != want and safe_is_file(base / d):
            return False, f"{want}: de-braced file on disk — case_link domain"
        if _find_graphic_ci(ctx, want, scan.files) is not None:
            return False, f"{want}: ci-variant on disk — case_link domain"
    blob: str | bytes
    if suffix in _EPS_EXTS:
        blob = _EPS_PLACEHOLDER
    elif suffix == ".pdf":
        blob = _PDF_PLACEHOLDER
    elif suffix == ".png":
        blob = _PNG_PLACEHOLDER
    elif suffix in (".jpg", ".jpeg"):
        blob = _JPEG_PLACEHOLDER
    else:
        # _GRAPHIC_EXTS 日后扩面时的保守缺省 —— 格式不符的占位即废件
        return False, f"{want}: no placeholder asset for {suffix}"
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(blob, str):
            ctx.write(f, blob)
        else:
            f.write_bytes(blob)
            ctx.invalidate(f)
    except OSError as e:
        return False, f"{want}: write failed ({e})"
    scan.add(f)  # 落盘件入册 —— 后续 want 的 ci/去括救检可见
    return True, f"placeholder {suffix.lstrip('.').upper()} at {want}"


def _stub_sweep(
    ctx: LoopCtx,
    base: Path,
    wants: list[str],
    *,
    rescue_skip_first: bool = False,
    scan: _ProjectScan | None = None,
) -> tuple[bool, str]:
    r"""Wants 全量逐件过 ``_stub_graphic_at`` 落占位 → (有落盘, 汇总 note)。

    ``rescue_skip_first=True``: 首件 (本轮首错 payload) 免 rescue_check
    —— case_link 本轮已先评; 其余 sweep 件带检, 去括/ci 变体在盘时让位。
    ``scan`` 缺省自建 —— 调用点已建 (``_enum_missing_graphics`` 同快照)
    时传入复用, 一轮点火只付一次全树扫。note 组装: 首件落盘 note +
    ``(+N swept)`` + ``| declined: ...``。
    """
    if scan is None:
        scan = _ProjectScan(ctx)
    wrote: list[str] = []
    declined: list[str] = []
    for i, w in enumerate(wants):
        ok, note = _stub_graphic_at(
            ctx, base, w, rescue_check=i > 0 or not rescue_skip_first, scan=scan
        )
        (wrote if ok else declined).append(note)
    if not wrote:
        return False, declined[0] if declined else "no stub written"
    head = wrote[0]
    if len(wrote) > 1:
        head += f" (+{len(wrote) - 1} swept)"
    if declined:
        head += f" | declined: {'; '.join(declined)}"
    return True, head


def graphic_missing_placeholder(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""图档真缺件 → ``<main_dir>/<payload>`` 落最小合法格式占位。

    graphic_ext_relax 残家 (failmine3 8 格) + xetex "Unable to load
    picture or PDF file" 残家 (failmine4-covgap 6 格): sibling 不存在时
    剥扩展名也救不了 —— 修复不是改源而是补档 (xbb_pregen 旁件同形)。
    站点改写形盖不全调用面: ``\epsfig{file=X.eps}`` kv 形与宏体
    ``#1.eps`` 间接名 (payload 是展开后真名, 源码字面不可锚) 只能由
    「真名落盘」治; 子目录路径 (``FIGS/``/``images/``) mkdir 随行。

    占位格式按 payload 扩展名分发 (xetex image-sniff 认格式字节):
    ``.eps/.epsf/.epsi/.ps/.mps`` → 文本 EPS; ``.png/.jpg/.jpeg/.pdf``
    → 同构图二进制占位; 无扩展名 (ext-relax 残家 vanilla 解析序) 须
    先过 ``_has_live_graphic_ref`` 复核才补 ``.eps`` —— ``\input`` 系
    裸缺件不落图占位。落盘基址 = ``main_path().parent`` (TeX 的
    cwd 解析位; main 未知退回 wdir) —— main 住子目录时 wdir 根位
    对 TeX 不可见。payload 是 log 派生路径 —— 双层守卫: ``..`` 段拒
    + resolve 后仍须在 wdir 内 (防穿越写); 解析位已有档 (大小写
    变体/前轮已补) → False 让路。

    micro2 扩面 (v3all 2501.01329/2501.01425): 本轮 log 全量枚举同签
    缺图一次补齐 —— nonstop 编译单趟已列全部, 逐轮单补在多缺件格
    烧穿轮次上限。log 缺席/单件时行为与旧逐件版等价。

    haltsweep 扩面 (v3all 8 格普查): fixloop 编译走 halt_on_error —
    每轮 log 只曝首个缺件, log 扫臂实际仍逐轮单补 (2501.01425 烧
    8 轮, 余 3 件 log 从未触及)。补 ``_enum_missing_graphics`` 源侧
    枚举 —— 全工程活引用静态解析, 一轮尽列已知缺件。
    """
    del params
    want = _norm_graphic_name(payload or "")
    if not want:
        return False, "no graphic payload"
    mp = ctx.main_path()
    base = mp.parent if mp is not None else ctx.wdir
    wants = [want]
    for m in _LOG_MISS_GFX_RE.finditer(_fixloop_log(ctx)):
        w = _norm_graphic_name(m.group(1) or m.group(2))
        if w and w not in wants:
            wants.append(w)
    scan = _ProjectScan(ctx)
    for w in _enum_missing_graphics(ctx, eng, base, scan.disk):
        if w not in wants:
            wants.append(w)
    return _stub_sweep(ctx, base, wants, rescue_skip_first=True, scan=scan)
