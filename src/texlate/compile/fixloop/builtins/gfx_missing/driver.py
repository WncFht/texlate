r"""builtins.gfx_missing.driver — xdvipdfmx 驱动期缺图域 (gfx_missing 拆分)。

``driver_missing_image_stub``: ``Image inclusion failed. Could not
find file: X`` fatal 名 (``other``/``driver_fatal`` 双轮名源) →
经 ``gfx_missing.enum`` 源侧枚举一轮尽列 + ``gfx_missing.stub._stub_sweep``
占位落盘。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from texlate.compile.fixloop.builtins.gfx_missing.enum import (
    _enum_missing_graphics,
    _ProjectScan,
)
from texlate.compile.fixloop.builtins.gfx_missing.stub import _stub_sweep
from texlate.compile.fixloop.builtins.graphics import _norm_graphic_name

if TYPE_CHECKING:
    from typing import Any

    from texlate.compile.fixloop.engine.ctx import LoopCtx
    from texlate.compile.fixloop.engine.proto import Engine


__all__ = [
    "_DRV_IMG_MISS_RE",
    "driver_missing_image_stub",
]


# ═══ xdvipdfmx 驱动期缺图域 (failmine4 drvstage 车道 2026-09-20) ═══


#: 驱动 fatal 行的缺图名捕获 —— ``Image inclusion failed. Could not
#: find file: X`` 名字恒占行尾 (xdvipdfmx fatal 单行不折行，probe4
#: 实证 120+col 路径仍整行)。
_DRV_IMG_MISS_RE = re.compile(
    r"Image inclusion failed\.\s*Could not find file:\s*([^\n]+)"
)


def driver_missing_image_stub(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``Image inclusion failed`` 驱动期缺图 fatal → 解析位落占位件。

    failmine4 drvstage 4 格 (2501.01611/2502.00335/2504.06306/
    2505.07205): tex 趟净 (``.xbb`` 旁件供 bbox / ``\special{psfile}``
    裸递串 / nonstop 先错已修后的残轮) 但 xdvipdfmx 嵌入期找不到
    图档 —— ``*: fatal:`` 只走合并 stdout 不进 .log, ``_report_of``
    归一成 ``!`` 行后 taxonomy 无头模 → ``other`` 类目派发; 归一化
    漏形由 ``_round_cat`` driver_fatal 臂兜底 (payload=原始 fatal
    行)。tex 侧 ``!`` 标记臂群 (graphic_missing_placeholder@17.6
    等) 对此面零可见 —— 驱动名只在 stdout_tail/err_head/payload。

    名源双面: ``other`` 轮读 ``ctx.err_head`` (归一 ``!`` 行+ctx),
    ``driver_fatal`` 轮读 ``payload``。名经 ``_norm_graphic_name``
    规整后逐件过 ``_stub_graphic_at`` 全守卫 (ext 白名单/``..`` 拒/
    wdir 逃逸拒/已在盘 decline=幂等); ``rescue_check=True`` —— 去
    括/ci 变体在盘时让位不落假图遮真件 (占位是缺件兜底; 驱动期
    ci 残家属后续专用臂域, 非本臂假件理)。落盘基址同 tex 侧:
    ``main_path().parent`` (xelatex cwd = main 所在目录)。

    补 ``_enum_missing_graphics`` 源侧枚举 (haltsweep 同件): 驱动
    每轮 fatal 只曝首件, 而 ``other`` 轮 ``applied`` dedup 键恒为
    ``{rid}:None`` —— 单补一件即封再派发, 多缺件格 (2501.01611:
    shufflenet+model 双缺) 会卡 stuck。一轮尽列已知缺件。
    """
    del params
    blob = (payload or "") + "\n" + (ctx.err_head or "")
    wants: list[str] = []
    for m in _DRV_IMG_MISS_RE.finditer(blob):
        w = _norm_graphic_name(m.group(1))
        if w and w not in wants:
            wants.append(w)
    if not wants:
        return False, "no driver missing-image name"
    mp = ctx.main_path()
    base = mp.parent if mp is not None else ctx.wdir
    scan = _ProjectScan(ctx)
    for w in _enum_missing_graphics(ctx, eng, base, scan.disk):
        if w not in wants:
            wants.append(w)
    return _stub_sweep(ctx, base, wants, scan=scan)
