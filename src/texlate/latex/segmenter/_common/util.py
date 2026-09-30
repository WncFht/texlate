r"""``latex.segmenter._common.util`` — 杂项常量/小 helper（``_common`` god-file 机械拆分叶）。

清洗/注释/保护类型小表 + ``CHUNK_ARG_SPEC`` 解析缓存 + 组内再生保护常量 +
``_pick_cut`` 切点优先级链（``_split_bounds``/``_split_rendered`` 共用）。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from texlate.latex.macro_table import parse_argspec
from texlate.latex.model import PhType
from texlate.latex.placeholder import PH_RX
from texlate.latex.tables import CHUNK_MAX

if TYPE_CHECKING:
    from texlate.latex.model import ArgSpec

# ---------------------------------------------------------------- 表常量
# 原 ``segmenter/tables.py``（scanner v1/segmenter v2 双臂单源）——v1 退役后
# 收回本模块直接定义；args/core/env/group/mainloop/pending 仍经本模块取。

_CLEAN_CMD_RX = re.compile(r"\\[a-zA-Z@]+\*?|\\[^a-zA-Z]")
_CLEAN_NONALPHA_RX = re.compile(r"[^a-zA-Z]")
_LEAD_WS_RX = re.compile(r"\s*")
_TRAIL_WS_RX = re.compile(r"\s*$")

_PROTECT_TYP = {
    "includegraphics": PhType.GRAPHICS,
    "url": PhType.URL,
    "path": PhType.URL,
    "label": PhType.LABEL,
    "bibliography": PhType.BIB,
    "bibliographystyle": PhType.BIB,
    "bibitem": PhType.BIB,
}

_CHUNK_SPEC_CACHE: dict[str, list[ArgSpec]] = {}


def _chunk_spec_cached(spec_str: str) -> list[ArgSpec]:
    """``CHUNK_ARG_SPEC`` 签名串 → ``list[ArgSpec]``（解析一次缓存）。"""
    if spec_str not in _CHUNK_SPEC_CACHE:
        _CHUNK_SPEC_CACHE[spec_str] = parse_argspec(spec_str)
    return _CHUNK_SPEC_CACHE[spec_str]


_COMMENT_GAP_RX = re.compile(r"%[^\n]*")
# 参数体内裸 ``%`` 注释（``\%`` 转义由 ``\\.`` 分支先吃掉）——in_arg 渲染串
# 的 ``%`` 必为真注释（token 层已证非 \verb/url 体内）
_ARG_COMMENT_RX = re.compile(r"\\.|%[^\n]*")


# 组内再生保护段的配对前瞻上限（env/math/delim 扫描步数）
_GRP_SCAN_CAP = 4000
#: 组内 consumed marker 的非副作用白名单（input 换源 / if 选支回放）；
#: 其余 tag（def 族/let/catcode/newif/ifundefined…）都在展开时改过宏表，
#: surface 无法再生其副作用——命中即整组回 literal（_close_group）。
_GRP_FLOW_TAGS = ("input:", "input_tag:", "endinput", "if:", "fi:")


def _pick_cut(s: str, i: int, hard: int) -> int:  # noqa: C901 — 切点优先级链，平铺即 §3.8 规则序
    r"""切点优先级链（§3.8）：``[[X_n]]`` 尾 > 段界 ``\n\n`` > 句读空白 > 硬切。

    返回相对 ``i`` 的切长。硬切兜底：找横跨 ``hard`` 的占位符切到它尾后
    （scanner-audit F7——ph 不腰斩）。``_split_bounds``/``_split_rendered``
    共用（v1 ``_split_core`` 是同源字节版）。
    """
    window = s[i:hard]
    cut = -1
    for m in PH_RX.finditer(window):  # 占位符尾是最安全切点
        cut = m.end()
    if cut <= 0:
        ws = window.rfind("\n\n")
        if ws > 0:
            cut = ws + 2
    if cut <= 0:
        for ch in (". ", "} ", " "):
            ws = window.rfind(ch)
            if ws > CHUNK_MAX // 2:
                cut = ws + len(ch)
                break
    if cut <= 0:
        # 硬切：找横跨 hard 的 token 切到它尾后（scanner-audit F7）
        cut = hard - i
        for m in PH_RX.finditer(s, i):
            if m.start() >= hard:
                break
            if m.end() > hard:
                cut = m.end() - i
                break
    return cut
