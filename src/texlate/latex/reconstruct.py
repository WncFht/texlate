r"""splice 重建 + DAG 递归展开 + validate（docs/07 §9）。

- **identity**：``translations=None`` → 平铺 pieces + ph 体逐字 → 逐字节 = 原文。
- O(总规模)+memo；相对 spike ``str.replace`` 不动点语义等价
  （同一替换表迭代至不动点 ≡ DAG 递归展开；构造上无环，assert 兜底）。
- **译文侧契约**：译文必须保留 ``chunk.placeholders`` 全列；
  :func:`validate_translation` 校验缺失/幻觉占位符（由 translate 层消费）。
- ``cjk_glue_fix``（``\\cmd这是`` → 插空格）是 post-reconstruct 全局修正一步，
  只在有译文时启用（identity 路径保持逐字节）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from texlate.latex.model import Chunk, ScanResult, ScanWarning
from texlate.latex.placeholder import CHUNK_RX, PH_RX

_CJK_RX = re.compile(r"(\\[a-zA-Z@]+\*?)(?=[㐀-鿿豈-﫿])")


def cjk_glue_fix(s: str) -> str:
    r"""``\cmd这是`` → ``\cmd 这是``：控制字后直接贴 CJK 时插空格。

    控制字后随空格在 TeX 里被吸收 → 源码语义不变，渲染更稳。
    """
    return _CJK_RX.sub(r"\1 ", s)


def reconstruct(res: ScanResult, translations: dict[int, str] | None = None) -> str:
    """按 pieces splice + 占位符 DAG 递归展开（docs/07 §9 伪码原样）。

    ``translations``：``{chunk_id: 译文}``；None → identity 重建。
    """
    trans = (
        {}
        if translations is None
        else {f"[[CHUNK_{k}]]": v for k, v in translations.items()}
    )
    memo: dict[str, str] = {}
    chunks = res.chunks
    active: set[str] = set()

    def expand(token: str) -> str:  # token 形如 [[X_n]]
        if token in memo:
            return memo[token]
        if token in active:
            return token  # 译文侧自指/互指环（ph_map 构造上无环）→ 留字面
        active.add(token)
        body = trans.get(token)
        if body is None:
            body = res.ph_map.get(token)
        if body is None:
            m = CHUNK_RX.fullmatch(token)
            idx = int(m.group(1)) if m else -1
            body = chunks[idx].content if 0 <= idx < len(chunks) else token
        memo[token] = PH_RX.sub(lambda mm: expand(mm.group(0)), body)
        active.discard(token)
        return memo[token]

    # LITERAL 段也可能内嵌 ph（短 run / MINED_ONLY run 发渲染文本）——全段展开。
    out = [PH_RX.sub(lambda m: expand(m.group(0)), p.text) for p in res.pieces]
    result = "".join(out)
    if translations:
        result = cjk_glue_fix(result)
    return result


# ---------------------------------------------------------------- validate


@dataclass(slots=True)
class TranslationVerdict:
    """``validate_translation`` 结果。"""

    ok: bool
    missing: list[str] = field(default_factory=list)  # 译文丢失的占位符
    extra: list[str] = field(default_factory=list)  # 译文幻觉出的占位符


def validate_translation(chunk: Chunk, text: str) -> TranslationVerdict:
    """译文侧契约校验：``chunk.placeholders`` 全列必须在 text 里，无幻觉。"""
    want = chunk.placeholders or PH_RX.findall(chunk.content)
    got = PH_RX.findall(text)
    missing = [ph for ph in want if ph not in got]
    extra = [ph for ph in got if ph not in want]
    return TranslationVerdict(
        ok=not missing and not extra, missing=missing, extra=extra
    )


def validate_result(res: ScanResult) -> list[ScanWarning]:  # noqa: C901 — 四类校验各一段，平铺即清单
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
            else:
                warns.append(ScanWarning("dangling_chunk_ref", 0, tok))
        elif tok in res.ph_map:
            stack.extend(PH_RX.findall(res.ph_map[tok]))
        else:
            warns.append(ScanWarning("dangling_ph", 0, tok))

    for k, c in enumerate(res.chunks):
        if f"[[CHUNK_{c.id}]]" not in reachable:
            warns.append(ScanWarning("orphan_chunk", c.span.start, f"chunk#{k}"))
    warns.extend(
        ScanWarning("dead_ph", 0, ph) for ph in res.ph_map if ph not in reachable
    )
    return warns
