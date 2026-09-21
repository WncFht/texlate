"""segmenter/半解析测试公共骨架——``ART`` 模板 scan + ``ph_map`` 体过滤 + 散文负载常量。

``test_segmenter_*``/``test_args_kvdig``/``test_keyval_leak`` 簇逐文件复刻的
同构脚手架归此一处（沿用 ``_workerkit``/``_fixloopkit``/``_fuzzkit`` 抽取先例）：

- ``scan_art``：``art % (defs, body)`` → ``parse_tex`` → ``check_invariants``
  三件套（6 文件逐字节同体；``art`` 形参覆盖 BEAMER 等变体模板）。
- ``ph_bodies``/``cmd_bodies``：``[[KIND_n]]`` ph 体过滤——PlaceholderIssuer
  只产 ``[[TYPE_\\d+]]`` 键形，``fullmatch`` 与 ``startswith("[[KIND_")``
  等效（注意必须带下划线——裸 ``[[ENV`` 前缀会误吃 ``[[ENVTAG_n]]``）。
- ``PROSE``/``KEY``：跨文件逐字相同的散文/cite-key 负载常量。
- ``nested_probe_call``：``gen_overflow`` 回压用例的嵌套 ``\\f{…}`` 调用链
  构造器（cmd_prose/grp_prose 两处逐字同构）。
- ``scan_prose``/``_PROSE_HEAD``/``_PROSE_TAIL``：标准散文三明治——``body``
  夹进前/后散文再 ``scan_art``（operand 扫描须活在散文 run 内；
  operandfix 本地副本与 inputtail 7+ 内联站点同形单源）。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from conftest import ART, check_invariants

if TYPE_CHECKING:
    from texlate.latex.model import ScanResult

#: 公共散文负载——凑足 scout ≥4 连词判据。
PROSE = "We consider a two form antisymmetric tensor field theory in detail"
#: 公共 cite-key 负载（非散文参钉版）。
KEY = "dalianis2020"

#: 标准散文三明治——前/后散文保住段界语境（operand 扫描须活在散文 run 内）。
_PROSE_HEAD = "Prose before keeps the run alive and gives context here.\n"
_PROSE_TAIL = "Trailing prose after the block keeps going here."


def scan_art(body: str, defs: str = "", art: str = ART) -> ScanResult:
    """``art % (defs, body)`` 解析 + 公共不变式（恒等重建/零告警/无缝平铺）。"""
    from texlate.latex import parse_tex  # noqa: PLC0415

    tex = art % (defs, body)
    res = parse_tex(tex)
    check_invariants(res, tex)
    return res


def scan_prose(body: str, defs: str = "") -> ScanResult:
    """``body`` 夹进标准前/后散文三明治再 ``scan_art``——同形 scaffold 单源。"""
    return scan_art(_PROSE_HEAD + body + "\n" + _PROSE_TAIL, defs)


def ph_bodies(res: ScanResult, kind: str = "CMD") -> list[str]:
    """全部 ``[[KIND_n]]`` ph 体（覆盖区间原文）。"""
    return [
        body
        for ph, body in res.ph_map.items()
        if re.fullmatch(rf"\[\[{kind}_\d+\]\]", ph)
    ]


def cmd_bodies(res: ScanResult) -> list[str]:
    """全部 ``[[CMD_n]]`` ph 体（覆盖区间原文）。"""
    return ph_bodies(res, "CMD")


def nested_probe_call(depth: int = 40, *, cs: str = "\\f", inner: str | None = None) -> str:
    """gen 回压嵌套链：``\\f{Outer prose words wrap around … tail.}`` ×depth。"""
    body = f"{cs}{{{inner if inner is not None else PROSE + ' deep.'}}}"
    for _ in range(depth):
        body = f"{cs}{{Outer prose words wrap around {body} tail.}}"
    return body
