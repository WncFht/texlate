r"""builtins.layoutfix.core — env 跨度/overfull 幅度/编辑回放的通用件 (layoutfix 拆分)。

``_env_spans`` ``\begin``/``\end`` 栈配对跨度 / ``_span_marks``+``_in_spans``
合并区间命中判定 (bisect 前缀和) / ``_max_overfull_pt`` log 出血幅度 —
``_lfx_*`` 兄弟叶全经本叶直引。
"""

from __future__ import annotations

import re
from bisect import bisect_right

__all__ = [
    "_ENV_TOKEN_RX",
    "_OVF_PT_RX",
    "_env_spans",
    "_in_spans",
    "_max_overfull_pt",
    "_span_marks",
    "bisect_right",
    "re",
]

#: ``\begin{E}``/``\end{E}`` token 面——遮盖视图上扫 (注释/verbatim 内死命中
#: 天然不现)。星号名/连名 (``tableorg`` 等) 由各族名单放行。
_ENV_TOKEN_RX = re.compile(r"\\(begin|end)\s*\{([^}\s]+)\}")

#: ``Overfull \hbox (12.34pt too wide) ...`` 幅度数字组——_fixloop_log 上
#: 取 max 决定收缩档 (内联/对齐/段落三形态同收 ``\hbox``+``\vbox``)。
_OVF_PT_RX = re.compile(r"Overfull \\[hv]box \((\d+(?:\.\d+)?)pt too wide\)")


def _max_overfull_pt(log: str) -> float:
    """Log 里 Overfull box 最大出血点; 无 → 0.0。"""
    mx = 0.0
    for m in _OVF_PT_RX.finditer(log):
        mx = max(mx, float(m.group(1)))
    return mx


def _env_spans(vis: str, names: frozenset[str]) -> list[tuple[int, int]]:
    r"""遮盖视图内 ``names`` 族 env 的 ``(begin_start, end_end)`` 跨度表。

    ``\begin``/``\end`` token 序走查, 同名嵌套计深, 非配对 ``\end`` 容错
    出栈到匹配层 (残稿容忍, layout._demote_wrapfloats_text 同款骨架)。
    """
    spans: list[tuple[int, int]] = []
    stack: list[tuple[str, int]] = []
    for m in _ENV_TOKEN_RX.finditer(vis):
        tag, name = m.group(1), m.group(2)
        if tag == "begin":
            stack.append((name, m.start()))
            continue
        for i in range(len(stack) - 1, -1, -1):
            if stack[i][0] == name:
                if name in names:
                    spans.append((stack[i][1], m.end()))
                del stack[i:]
                break
    return spans


def _span_marks(spans: list[tuple[int, int]]) -> list[int]:
    """跨度表 → 合并区间的命中判定用边界列 (bisect 前缀和)。"""
    if not spans:
        return []
    spans = sorted(spans)
    merged: list[list[int]] = [[*spans[0]]]
    for lo, hi in spans[1:]:
        if lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    marks: list[int] = []
    for lo, hi in merged:
        marks.extend((lo, hi))
    return marks


def _in_spans(marks: list[int], pos: int) -> bool:
    """``pos`` 是否落在合并区间列内 (marks = 交错 lo/hi 边界列)。"""
    i = bisect_right(marks, pos)
    return i % 2 == 1
