r"""builtins._slotrev_engine — src/zh 配对 revert 引擎 (slotrev 拆分)。

per-kind 序号对齐: ``_slot_spans`` 定位 → ``_by_kind`` 归桶 → 计数分歧
走 ``_broadcast_value`` unique-src 广播否则整跳 → ``_revert_file``/
``_revert_tree`` 逐文件写回 → ``slot_arg_revert`` precheck 挂点入口。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins._slotrev_holder import _holder_rxs
from texlate.compile.fixloop.builtins._slotrev_ident import (
    _BROADCAST_KINDS,
    _NOTE_CAP,
    _is_ident,
)
from texlate.compile.fixloop.builtins._slotrev_table import _SLOTREV_EXTRA_RXS
from texlate.textutil import CITE_FAMILY_RE, CJK_RX, live_tex

if TYPE_CHECKING:
    import re

    from texlate.compile.fixloop.engine import Engine, LoopCtx

__all__ = [
    "CITE_FAMILY_RE",
    "CJK_RX",
    "Any",
    "Path",
    "_broadcast_value",
    "_by_kind",
    "_full_rxs",
    "_revert_file",
    "_revert_tree",
    "_slot_spans",
    "slot_arg_revert",
]


def _slot_spans(
    src: str, rxs: tuple[tuple[str, re.Pattern[str]], ...]
) -> list[tuple[str, int, int]]:
    r"""单文件源文机位命中 → ``(kind, start, end)`` 序对 (原文 offset)。

    ``judge._slot_args`` 同口径的 ``mask_tex`` 视图 + 死尾截断, 每 match
    全部非 None 捕获组各自入列, 但保留位置供回写 —— arg 切片区间为
    ``src[start:end]``。
    """
    view = live_tex(src)
    hits: list[tuple[str, int, int]] = []
    for kind, rx in rxs:
        for m in rx.finditer(view):
            hits.extend(
                (kind, m.start(i), m.end(i))
                for i, g in enumerate(m.groups(), start=1)
                if g is not None
            )
    return hits


def _by_kind(hits: list[tuple[str, int, int]]) -> dict[str, list[tuple[int, int]]]:
    """命中按 kind 归桶，桶内保文档序 (表行序→finditer 序)。"""
    d: dict[str, list[tuple[int, int]]] = {}
    for kind, s, e in hits:
        d.setdefault(kind, []).append((s, e))
    return d


def _broadcast_value(kind: str, ss: list[tuple[int, int]], src: str) -> str | None:
    """unique-src 广播值 → 唯一 gap 值 或 None。

    ``_BROADCAST_KINDS`` 内 kind 计数分歧时调用：src 侧全部命中值唯一
    ∧ 过 ``_is_ident`` → 返回该值供 zh 侧 CJK gap 广播; 多值/空集/非
    机料 → None (维持整跳，错位 revert 比不复原更糟)。
    """
    if kind not in _BROADCAST_KINDS or not ss:
        return None
    vals = {src[s:e] for s, e in ss}
    if len(vals) != 1:
        return None
    (val,) = vals
    return val if _is_ident(val, kind) else None


def _revert_file(
    src: str, zh: str, rxs: tuple[tuple[str, re.Pattern[str]], ...]
) -> tuple[str, int, list[str], list[str]]:
    r"""单文件 src/zh 配对 revert → ``(新 zh 文本, 改写数, 分歧项, 广播项)``。

    per-kind 序号对齐: k-th zh 命中 ↔ k-th src 命中; 三条件全中才改 —
    双侧相异 ∧ zh 参含 CJK ∧ src 参纯 ident (ASCII 白名单)。改集按
    起始位降序右→左应用, 同位/重叠第二刀跳 (envarg↔restatable 等同位
    多行扫重)。kind 双侧命中数分歧 → 该 kind 整跳记入 ``分歧项``;
    ``_BROADCAST_KINDS`` 内 kind (primgap) 先经 ``_broadcast_value``
    判 unique-src 广播 —— src gap 值唯一则写进 zh 全部 CJK gap 站
    (记 ``广播项`` 而非分歧), 多值/空集才回退整跳。spec-holder 动态
    行由 ``src`` def 体逐文件现查 (``_holder_rxs``)。
    """
    rxs = (*rxs, *_holder_rxs(src))
    src_by = _by_kind(_slot_spans(src, rxs))
    zh_by = _by_kind(_slot_spans(zh, rxs))
    if not zh_by:
        return zh, 0, [], []
    edits: list[tuple[int, int, str]] = []
    skipped: list[str] = []
    broadcast: list[str] = []
    kinds = list(zh_by) + [k for k in src_by if k not in zh_by]
    for kind in kinds:
        ss, zs = src_by.get(kind, []), zh_by.get(kind, [])
        if len(ss) != len(zs):
            val = _broadcast_value(kind, ss, src)
            if val is None:
                skipped.append(f"{kind}({len(ss)}!={len(zs)})")
                continue
            edits.extend((z0, z1, val) for z0, z1 in zs if CJK_RX.search(zh[z0:z1]))
            broadcast.append(f"{kind}({len(ss)}→{len(zs)})")
            continue
        for (s0, s1), (z0, z1) in zip(ss, zs, strict=True):
            sarg, zarg = src[s0:s1], zh[z0:z1]
            if sarg == zarg or not CJK_RX.search(zarg) or not _is_ident(sarg, kind):
                continue
            edits.append((z0, z1, sarg))
    n = 0
    floor = len(zh) + 1
    for z0, z1, sarg in sorted(edits, key=lambda t: (-t[0], -t[1])):
        if z1 > floor:
            continue
        zh = zh[:z0] + sarg + zh[z1:]
        floor = z0
        n += 1
    return zh, n, skipped, broadcast


def _full_rxs() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """机位全表：judge ``_MACHINE_SLOT_RXS`` + cite 族 + 本叶扩展行。"""
    from texlate.compile.judge import (  # noqa: PLC0415  # 延迟：fixloop 链重
        _MACHINE_SLOT_RXS,
    )

    return (*_MACHINE_SLOT_RXS, ("cite", CITE_FAMILY_RE), *_SLOTREV_EXTRA_RXS)


def _revert_tree(
    ctx: LoopCtx, base_root: Path, rxs: tuple[tuple[str, re.Pattern[str]], ...]
) -> tuple[list[str], list[str], list[str], int]:
    """逐 ``*.tex`` 与 baseline 同名件配对 revert → (件条目，分歧项，广播项，改数)。"""
    reverted: list[str] = []
    skipped: list[str] = []
    broadcast: list[str] = []
    n_args = 0
    for f in ctx.tex_files((".tex",)):
        rel = f.relative_to(ctx.wdir).as_posix()
        zh = ctx.read(f)
        if zh is None:
            continue
        try:
            src = (base_root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if src == zh:
            continue
        new_text, n, sk, bc = _revert_file(src, zh, rxs)
        skipped.extend(f"{rel}:{s}" for s in sk)
        broadcast.extend(f"{rel}:{s}" for s in bc)
        if n:
            ctx.write(f, new_text)
            reverted.append(f"{rel}×{n}")
            n_args += n
    return reverted, skipped, broadcast, n_args


def slot_arg_revert(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""把 zh 化机位实参按 ``params.baseline_dir`` pristine 树配对还原。

    precheck 位一次性跑 (L2 resplice 之后的首个耐写入点): 逐 ``*.tex``
    与 baseline 同名件做 per-kind 序号对齐配对, ``src`` 参为纯 ASCII
    标识符而 ``zh`` 参含 CJK → zh 参位换回 src 字节 (``ctx.write``
    记账写)。空转判据自证幂等 —— 机位参无 CJK 即不重扫写。
    """
    del eng, payload
    base_dir = params.get("baseline_dir")
    if not base_dir:
        return False, "no baseline_dir param"
    base_root = Path(str(base_dir))
    if not base_root.is_dir():
        return False, f"baseline_dir not a directory: {base_root}"
    reverted, skipped, broadcast, n_args = _revert_tree(ctx, base_root, _full_rxs())
    if not reverted:
        note = "no zh machine-slot args to revert"
        if broadcast:
            note += f"; broadcast: {', '.join(broadcast[:_NOTE_CAP])}"
        if skipped:
            note += f"; divergent: {', '.join(skipped[:_NOTE_CAP])}"
        return False, note
    note = f"reverted {n_args} args in {len(reverted)} files: "
    note += ", ".join(reverted[:_NOTE_CAP])
    if len(reverted) > _NOTE_CAP:
        note += f" +{len(reverted) - _NOTE_CAP} files"
    if broadcast:
        note += f"; broadcast: {', '.join(broadcast[:_NOTE_CAP])}"
    if skipped:
        note += f"; divergent: {', '.join(skipped[:_NOTE_CAP])}"
    return True, note
