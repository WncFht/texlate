r"""排序不相交区间的 bisect 判定件 + CJK 码点面单源。

``_merge_ranges``/``_in_ranges``：区间列 → 排序不相交面 + ``bisect_right``
单候选命中——``encoding`` 的字符粗分类与 CJK 码点面共用的低层件（叶间单向
引用，不回引 facade）。

``CJK_RANGES``/``CJK_RX``/``is_cjk_cp``：CJK 统一表意码点面——judge/l0/l2
三处计数曾各自漂移（judge 缺 〇、l0 只有三区、l2 扩F 截断在 2EBEF），
单源化后口径唯一。
"""

from __future__ import annotations

import re
from bisect import bisect_right
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable


def _merge_ranges(
    ranges: Iterable[tuple[int, int]],
) -> tuple[tuple[int, int], ...]:
    """区间列 → 排序不相交面（相邻并入）——bisect 单候选判定前提。"""
    out: list[list[int]] = []
    for lo, hi in sorted(ranges):
        if out and lo <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return tuple((p[0], p[1]) for p in out)


def _in_ranges(
    cp: int, los: tuple[int, ...], merged: tuple[tuple[int, int], ...]
) -> bool:
    """``any(lo <= cp <= hi)`` 的 bisect 版——``merged`` 须排序不相交。"""
    i = bisect_right(los, cp) - 1
    return i >= 0 and cp <= merged[i][1]


# ---------------------------------------------------------------- CJK 码点面

#: CJK 统一表意码点面：扩A + 基本区 + 兼容区 + 〇（U+3007，日期用字）
#: + 扩B~F（U+20000–2FA1F）。judge/l0/l2 三处计数曾各自漂移（judge 缺
#: 〇、l0 只有三区、l2 扩F 截断在 2EBEF）——单源化后口径唯一。
CJK_RANGES: Final = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x3007, 0x3007),
    (0x20000, 0x2FA1F),
)

#: ``CJK_RANGES`` 的字符类形态（``findall`` 计数用）。
CJK_RX: Final = re.compile(
    "["
    + "".join(f"{chr(lo)}-{chr(hi)}" if lo != hi else chr(lo) for lo, hi in CJK_RANGES)
    + "]"
)


#: ``CJK_RANGES`` 的排序不相交面 + lo 列——``_char_class``/l2 逐字调用
#: （breview ``_score_text`` 全文体 ~5.9M 次），线性 any() 改 bisect。
_CJK_MERGED: Final = _merge_ranges(CJK_RANGES)
_CJK_LOS: Final = tuple(lo for lo, _ in _CJK_MERGED)


def is_cjk_cp(cp: int) -> bool:
    """码点是否落在 ``CJK_RANGES``（``Missing character:`` 码点判定用）。"""
    return _in_ranges(cp, _CJK_LOS, _CJK_MERGED)
