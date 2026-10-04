r"""builtins.layoutfix.secskip — ``\@startsection`` 小正 afterskip 垫底 (layoutfix 拆分)。

``section_skip_floor`` (qc-impl): cls/sty ``\@startsection`` 六参形第
5 参 (afterskip) 纯字面量 0 < x < ~1.4ex → ``1.5ex`` —— fandol CJK
extents 下标题贴正文 (``geo_text_overlap``) 的兜底垫高。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import _map_tex_files, _splice
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx

__all__ = [
    "_AFTERSKIP_FLOOR_PT",
    "_AFTERSKIP_TARGET",
    "_DIMEN_PT",
    "_STARTSEC_RX",
    "_section_skip_floor_text",
    "section_skip_floor",
]

#: ``\\@startsection{name}{lvl}{indent}{beforeskip}{afterskip}{style}``
#: 六参形 —— afterskip (第 5 参) 纯字面量捕获 (组 1 = 含花括整参，
#: 组 2 = 数值，组 3 = 单位)。glue 形 (``1.5ex plus .2ex``) 与 cs 形
#: (``\\smallskipamount``) 不匹配本式，天然不收。
_STARTSEC_RX = re.compile(
    r"\\@startsection\s*"
    r"\{[^{}]*\}\s*"  # name
    r"\{[^{}]*\}\s*"  # level
    r"\{[^{}]*\}\s*"  # indent
    r"\{[^{}]*\}\s*"  # beforeskip
    r"(\{\s*([0-9]*\.?[0-9]+)\s*([a-zA-Z]{2})\s*\})"  # afterskip 字面量
)

#: 单位 → pt 折算 (「小正」门近似值即可——ex/em 按 10pt 标准体估，
#: 误判域仅限 1.0–1.4 档 afterskip, 垫到 1.5ex 仍是无害小垫高)。
_DIMEN_PT: dict[str, float] = {
    "pt": 1.0,
    "bp": 1.00375,
    "pc": 12.0,
    "in": 72.27,
    "cm": 28.4528,
    "mm": 2.84528,
    "dd": 1.07,
    "cc": 12.84,
    "sp": 1.0 / 65536,
    "ex": 4.3,
    "em": 10.0,
}

#: afterskip 地板 (~1.4ex @10pt ≈ 6pt) 与目标值 —— sig-alternate.cls
#: 4pt 实证在闸内 (1503.00038: fandol CJK extents 下标题贴正文)。
_AFTERSKIP_FLOOR_PT = 6.0
_AFTERSKIP_TARGET = "{1.5ex}"


def _section_skip_floor_text(t: str) -> tuple[str, int]:
    vis = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    for m in _STARTSEC_RX.finditer(vis):
        num, unit = m.group(2), m.group(3).lower()
        factor = _DIMEN_PT.get(unit)
        if factor is None:
            continue  # mu/陌生单位不动
        pt = float(num) * factor
        if not 0 < pt < _AFTERSKIP_FLOOR_PT:
            continue  # 负值本不匹配 (regex 无 - 位); 零/已足高跳过
        edits.append((m.start(1), m.end(1), _AFTERSKIP_TARGET))
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def section_skip_floor(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""cls/sty ``\\@startsection`` 小正 afterskip (0 < x < ~1.4ex) → ``1.5ex``。

    实证 (qc-impl 2026-09-28, 1503.00038): ``sig-alternate.cls:1009``
    ``\\@startsection{section}...{4pt}`` —— afterskip 4pt 在 fandol CJK
    extents 下标题贴正文 (``geo_text_overlap``, 600dpi seam 0 白行)。
    编译 clean 无 log 标记, 唯 precheck ``always`` 面可达。负值
    (run-in 标题有意设计) 与 glue/cs 形不收——只动纯字面量。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".cls", ".sty", ".tex"))
    n = _map_tex_files(ctx, exts, _section_skip_floor_text)
    if not n:
        return False, r"no small positive \@startsection afterskip"
    return True, f"afterskip floored to 1.5ex in {n} file(s)"
