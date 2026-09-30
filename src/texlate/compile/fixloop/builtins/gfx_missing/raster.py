r"""builtins.gfx_missing.raster — raster 伪装 ``.pdf`` 改名域 (gfx_missing 拆分)。

``raster_pdf_rename``: e-print 船货 ``X.pdf`` 实为 PNG/JPEG 字节 →
magic 探测改真扩展名 + ``\includegraphics`` arg 后缀换名 —
改名保路径位, 全量扫一次点火盖多伪装件格。
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from texlate.compile.fixloop.builtins.common import (
    _live_matches,
    _map_tex_files,
)
from texlate.compile.fixloop.builtins.gfx_missing.caselink import (
    _INCLUDE_GFX_RE,
    _graphic_ref_hit,
)
from texlate.compile.fixloop.builtins.graphics import (
    _norm_graphic_name,
    _pdf_asset_targets,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from texlate.compile.fixloop.engine.ctx import LoopCtx
    from texlate.compile.fixloop.engine.proto import Engine


__all__ = [
    "_RASTER_MAGICS",
    "_map_tex_files",
    "_mislabeled_pdf_targets",
    "_pdf_asset_targets",
    "_rewrite_mislabeled_refs",
    "_sniff_raster_ext",
    "raster_pdf_rename",
]


# ════════════════════════════════════════════════════════════════
# raster-in-pdf 伪装件 (singlesweep mislabeled-raster-as-pdf 6 格):
# e-print 船货 ``X.pdf`` 实为 PNG/JPEG 字节 —— 引擎按后缀走 pdf
# 链拒载 (xetex "Unable to load picture or PDF file 'X.pdf'")。
# ════════════════════════════════════════════════════════════════


#: 伪装件 magic → 真格式扩展名 (graphicx 原生可读面; ``.jpeg``
#: 同收 ``\Gin@extensions`` 但 ``.jpg`` 是通用落名)。
_RASTER_MAGICS: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
)


def _sniff_raster_ext(p: Path) -> str | None:
    """文件头 magic → raster 扩展名; 非 PNG/JPEG 伪装 (真 pdf/其它) → None。"""
    try:
        with p.open("rb") as fh:
            head = fh.read(16)
    except OSError:
        return None
    for magic, ext in _RASTER_MAGICS:
        if head.startswith(magic):
            return ext
    return None


def _mislabeled_pdf_targets(ctx: LoopCtx) -> list[tuple[Path, str]]:
    r"""``wdir`` 全量 ``*.pdf`` magic 复核 → ``[(path, real_ext)]``。

    排除面与 ``_pdf_asset_targets`` 同口径: dot-部件 (``.fixloop-*``
    底板快照)、``_texmf``/``_tect_out`` 封装树、main 输出 pdf
    (重编译自生非内嵌图件)。真 ``%PDF`` 头件不落表 —— 引擎可读。
    """
    return [
        (p, ext)
        for p in _pdf_asset_targets(ctx)
        if (ext := _sniff_raster_ext(p)) is not None
    ]


def _rewrite_mislabeled_refs(
    ctx: LoopCtx, exts: tuple[str, ...], renamed: dict[str, str]
) -> int:
    r"""逐 tex: 指向已改名件的显式 ``.pdf`` arg → 后缀换真格式名 → 改写文件数。

    arg 只换尾缀不动目录/stem —— 改名保路径位, 原解析机制
    (filedir/main_dir/graphicspath) 对新名同效。无扩展名 arg 不收
    (``{fig5}`` ← ``fig5.pdf``): ``\Gin@extensions`` 序含 .png/.jpg
    改名后自解 (1607.00405 实证)。``\includepdf`` 不扫 —— pdfpages
    只收真 pdf, 改名后其缺件归 includepdf_missing_stub 诚实降级。
    """

    def _fn(t: str) -> tuple[str, int]:
        if "\\includegraphics" not in t:
            return t, 0
        out: list[str] = []
        prev = 0
        n = 0
        for m in _live_matches(_INCLUDE_GFX_RE, t):
            arg = m.group(2)
            if PurePosixPath(_norm_graphic_name(arg)).suffix.lower() != ".pdf":
                continue
            new_rel = next(
                (new for old, new in renamed.items() if _graphic_ref_hit(arg, old)),
                None,
            )
            if new_rel is None:
                continue
            new_arg = re.sub(
                r"(?i)\.pdf(\s*)$", PurePosixPath(new_rel).suffix + r"\1", arg
            )
            out.append(t[prev : m.start(2)])
            out.append(new_arg)
            prev = m.end(2)
            n += 1
        if not n:
            return t, 0
        out.append(t[prev:])
        return "".join(out), n

    return _map_tex_files(ctx, exts, _fn)


def raster_pdf_rename(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``.pdf`` 名实为 PNG/JPEG 字节 → 改名真扩展名 + ``\includegraphics`` arg 后缀改写。

    singlesweep mislabeled-raster-as-pdf 6 格 (1607.00405 fig5.pdf=PNG
    / 2310.01082 mlp_noise.pdf=JPEG / 2504.15280 fig0-all-angles 与
    fig2-question 双 PNG): e-print 船货 ``X.pdf`` 字节非 ``%PDF`` ——
    引擎按后缀走 pdf 链, 格式不符拒载 (``missing_graphic|X.pdf``)。
    ``graphic_repair`` 的 gs 重蒸馏对光栅字节同样失败 → ``\fbox``
    stub 丢真图; 改名+引用改写是全救。全量扫一次点火 ——
    halt_on_error 每轮只曝首件 (2504.15280 双伪装件实证), 逐轮修
    会烧穿轮次上限。目标位撞名 (``X.png`` 已在盘) 逐件 decline
    不覆写; 无一改成则整体 False 让 repair/stub 域接手。
    """
    del eng, payload
    targets = _mislabeled_pdf_targets(ctx)
    if not targets:
        return False, "no raster-bytes .pdf in fileset"
    renamed: dict[str, str] = {}
    skipped: list[str] = []
    for src, ext in targets:
        dst = src.with_suffix(ext)
        if dst.exists():
            skipped.append(f"{dst.name} exists")
            continue
        try:
            src.rename(dst)
        except OSError as e:
            skipped.append(f"{src.name}({e})")
            continue
        ctx.invalidate(src)
        ctx.invalidate(dst)
        renamed[src.relative_to(ctx.wdir).as_posix()] = dst.relative_to(
            ctx.wdir
        ).as_posix()
    if not renamed:
        return False, f"0/{len(targets)} renamed ({'; '.join(skipped)})"
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    changed = _rewrite_mislabeled_refs(ctx, exts, renamed)
    note = (
        f"renamed {len(renamed)}/{len(targets)} raster-as-pdf "
        f"({', '.join(renamed.values())}), refs rewritten in {changed} file(s)"
    )
    if skipped:
        note += f"; skipped: {'; '.join(skipped)}"
    return True, note
