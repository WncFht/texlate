r"""``latex.reconstruct.validate`` — 译文契约校验 + ScanResult 结构校验（``reconstruct`` god-file 机械拆分叶）。

``validate_translation``：``chunk.placeholders`` 多重集必须逐枚出现
在译文 text 里（缺失/幻觉双侧报，``Counter`` 差集口径）。``
validate_result``：pieces 平铺不变式 / 可达性闭包（``protected_tex``
→ ph/chunk → 递归展开）/ 孤儿 chunk / dead ph / 悬空引用四类警告。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from texlate.latex.model import ScanWarning
from texlate.latex.placeholder import CHUNK_RX, PH_RX

if TYPE_CHECKING:
    from texlate.latex.model import Chunk, ScanResult


@dataclass(slots=True)
class TranslationVerdict:
    """``validate_translation`` 结果。"""

    ok: bool
    missing: list[str] = field(default_factory=list)  # 译文丢失的占位符
    extra: list[str] = field(default_factory=list)  # 译文幻觉出的占位符


def validate_translation(chunk: Chunk, text: str) -> TranslationVerdict:
    """译文侧契约校验：``chunk.placeholders`` 多重集必须逐枚出现在 text 里。

    multiset 语义——``[[MATH_1]]``×2 被译文吃掉一个也算 missing
    （list-membership 版会漏，与 rules ``Counter`` 口径对齐）。
    """
    want = Counter(chunk.placeholders or PH_RX.findall(chunk.content))
    got = Counter(PH_RX.findall(text))
    missing = sorted((want - got).elements())
    extra = sorted((got - want).elements())
    return TranslationVerdict(
        ok=not missing and not extra, missing=missing, extra=extra
    )


def validate_result(res: ScanResult) -> list[ScanWarning]:  # noqa: C901, PLR0912 — 四类校验各一段，平铺即清单
    """结构校验：孤儿 chunk、死 ph、pieces 非平铺、悬空占位符引用。"""
    warns: list[ScanWarning] = []

    # pieces 平铺不变式：首 start==0 且无缝
    pos = 0
    for k, p in enumerate(res.pieces):
        if p.span.start != pos:
            warns.append(
                ScanWarning(
                    "pieces_gap",
                    p.span.start,
                    f"piece#{k} start={p.span.start} expect={pos}",
                )
            )
            break
        pos = p.span.end
    if res.pieces and res.pieces[0].span.start != 0:
        warns.append(
            ScanWarning("pieces_gap", 0, f"pieces[0].start={res.pieces[0].span.start}")
        )

    # 可达性：protected_tex → ph/chunk → 递归展开
    reachable: set[str] = set()
    stack = list(PH_RX.findall(res.protected_tex))
    while stack:
        tok = stack.pop()
        if tok in reachable:
            continue
        reachable.add(tok)
        m = CHUNK_RX.fullmatch(tok)
        if m:
            idx = int(m.group(1))
            if idx < len(res.chunks):
                stack.extend(PH_RX.findall(res.chunks[idx].content))
            elif tok not in res.ph_reserved:
                warns.append(ScanWarning("dangling_chunk_ref", 0, tok))
            # ``ph_map[CHUNK]`` fallback 体同走 ``expand`` 优先级——内含
            # ``[[EXPAND_n]]`` 引用属可达面，不计 dead_ph
            if tok in res.ph_map:
                stack.extend(PH_RX.findall(res.ph_map[tok]))
        elif tok in res.ph_map:
            stack.extend(PH_RX.findall(res.ph_map[tok]))
        elif tok not in res.ph_reserved:
            warns.append(ScanWarning("dangling_ph", 0, tok))
        # 落到此 = ph_reserved 字面：源文自带 [[X_n]] 是声明保留的过路
        # 文本而非悬空引用，不告警（S2——dangling_chunk_ref 同规豁免）

    for k, c in enumerate(res.chunks):
        if f"[[CHUNK_{c.id}]]" not in reachable:
            warns.append(ScanWarning("orphan_chunk", c.span.start, f"chunk#{k}"))
    warns.extend(
        ScanWarning("dead_ph", 0, ph) for ph in res.ph_map if ph not in reachable
    )
    return warns
