r"""builtins._slotrev_holder — doc 自定义 spec-holder 宏探测 (slotrev 拆分)。

def 体以 spec-env ``\begin`` 收尾的 ``\X{spec}`` 等价 ``\begin{ENV}{spec}``
(1502.01845 ``\betb`` 实证) —— ``_holder_rxs`` 逐文件现查 def 名并现编
调用站 rx, 供 revert 引擎拼入 rxs 尾。
"""

from __future__ import annotations

import re

from texlate.compile.fixloop.builtins._slotrev_lex import _ARGB
from texlate.textutil import CMD_BOUNDARY, live_tex

__all__ = [
    "_HOLDER_CAP",
    "_HOLDER_DEF_RX",
    "_HOLDER_TAIL_RX",
    "_holder_rxs",
    "live_tex",
]

#: doc 自定义 spec-holder 宏探测 —— def 体以 spec-env ``\begin`` 收尾
#: 即 ``\X{spec}`` 等价 ``\begin{ENV}{spec}`` (1502.01845 ``\betb``
#: = ``\begin{center}\begin{tabular}`` 实证，参被译 → kernel "Illegal
#: character in array arg.")。[n] 形参表宏不收 (带参宏 {} 实参被 #n
#: 消费不进 token 流); ``\newcommand{\cs}``/``\newcommand\cs`` 双形 +
#: def/edef/gdef/xdef 族同盖。体一层花括号嵌套封顶 (``{center}``/
#: ``{tabular}`` 内层组)。
_HOLDER_DEF_RX = re.compile(
    r"\\(?:newcommand\*?|renewcommand\*?|providecommand\*?|"
    r"DeclareRobustCommand\*?|def|gdef|edef|xdef)"
    r"\s*\{?\\([A-Za-z@]+)\}?\s*"
    r"\{((?:[^{}]|\{[^{}]*\})*)\}"
)
#: def 体尾部 spec-env ``\begin`` 断言 (可带 ``[pos]`` 尾巴); env 表
#: 与 colspec 双臂同步 (2026-09-20 zhleakimpl 补 xtabular/tabu/tblr
#: 系/nicematrix/xltabular —— 双参 env 结尾的 holder 调用站只收首
#: 参，参位仍全机位故收之无害)。
_HOLDER_TAIL_RX = re.compile(
    r"\\begin\s*\{(?:tabular|array|deluxetable|smalldeluxetable|"
    r"sidewaysdeluxetable|sidewaystable|supertabular|mpsupertabular|"
    r"longtable|xtabular|tabu|longtabu|tblr|longtblr|talltblr|"
    r"booktabs|longtabs|talltabs|NiceTabular|NiceArray|"
    r"pNiceArray|bNiceArray|BNiceArray|vNiceArray|VNiceArray|"
    r"tabularx|tabulary|xltabular|NiceTabularX)\*?\}"
    r"\s*(?:\[[^\]\n]*\]\s*)?$"
)
#: 每文件 spec-holder 名发现上限 (防宏农场文 noise kinds 刷屏)。
_HOLDER_CAP = 8


def _holder_rxs(src: str) -> tuple[tuple[str, re.Pattern[str]], ...]:
    r"""``src`` 文内 spec-holder 宏 → per-name ``(colspec_holder:X, rx)`` 表。

    ``mask_tex`` 视图扫描 (注释/逐字内 def 不算); 调用站 rx 吃可选
    ``[opt]`` 后首 ``{}`` 参 —— def 自体因体含花括号天然不匹配
    (``_ARG`` 吃不进 ``{}`` 体)。spec 参 ``_ARGB`` 收 —— holder
    调用站 spec 同带 ``>{...}`` 嵌组 (2026-09-20 zhleakimpl)。
    """
    view = live_tex(src)
    out: list[tuple[str, re.Pattern[str]]] = []
    seen: set[str] = set()
    for m in _HOLDER_DEF_RX.finditer(view):
        name, body = m.group(1), m.group(2)
        if name in seen or not _HOLDER_TAIL_RX.search(body):
            continue
        seen.add(name)
        rx = re.compile(
            r"\\" + re.escape(name) + CMD_BOUNDARY + r"\s*(?:\[[^\]\n]*\]\s*)?" + _ARGB
        )
        out.append((f"colspec_holder:{name}", rx))
        if len(out) >= _HOLDER_CAP:
            break
    return tuple(out)
