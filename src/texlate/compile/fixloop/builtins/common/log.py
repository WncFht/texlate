r"""builtins.common.log — 编译 log 定位 + missing_char 读侧短路 (common 拆分)。

``_iter_log_candidates`` 候选枚举序 (``{stem}.log`` → ``_tect_out`` →
全树 ``*.log`` 名序) 单源, ``_fixloop_log`` 无门版 / ``_compile_log_text``
``Missing character`` 内容门版同轨; ``_mc_seen`` = 内容门 +
``_mc_parse_log`` 解析码位表 (texlog 单源直引, 无同形双写)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.texlog import _mc_parse_log

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from texlate.compile.fixloop.engine import LoopCtx

__all__ = [
    "_compile_log_text",
    "_fixloop_log",
    "_iter_log_candidates",
    "_mc_parse_log",
    "_mc_seen",
]


def _iter_log_candidates(ctx: LoopCtx) -> Iterable[Path]:
    """本轮编译 log 候选枚举：``{stem}.log`` → ``_tect_out/{stem}.log`` → 全树 ``*.log`` (名序)。

    ``_fixloop_log``/``_compile_log_text`` 共用的定位序 —— 两侧仅内容
    门不同 (无门 vs ``Missing character`` 门), 枚举单源消漂移。
    ``ctx.read`` 吞 OSError → ``None``, 缺件/目录同名天然滤除。
    """
    main = ctx.main_path()
    if main is not None:
        stem = main.stem
        yield ctx.wdir / f"{stem}.log"
        yield ctx.wdir / "_tect_out" / f"{stem}.log"
    yield from sorted(ctx.wdir.rglob("*.log"))


def _fixloop_log(ctx: LoopCtx) -> str:
    """本轮编译 log 定位 (通用版，无内容过滤)。

    首个非空候选即返 —— 候选序见 ``_iter_log_candidates``
    (``{stem}.log`` → ``_tect_out/{stem}.log`` → 兜底 ``*.log``)。
    """
    for p in _iter_log_candidates(ctx):
        if t := ctx.read(p):
            return t
    return ""


def _compile_log_text(ctx: LoopCtx) -> str:
    """定位本轮编译 log (Missing character 内容门)。

    候选序同 ``_iter_log_candidates``; 首个含 Missing character
    的非空 log 命中即返。
    """
    for p in _iter_log_candidates(ctx):
        if (t := ctx.read(p)) and "Missing character" in t:
            return t
    return ""


def _mc_seen(ctx: LoopCtx) -> dict[int, tuple[str, str]] | None:
    """含缺字的编译 log → 解析码位表; 无 log → ``None`` (表可空：全 nullfont 滤除)。

    ``_compile_log_text`` (内容门) + ``_mc_parse_log`` 的读侧短路 ——
    misschar 叶与 shim 叶 log-gate 同用 (后者 ``_fixloop_log`` + 子串门
    无 rglob 兜底，弱于本口径)。
    """
    log = _compile_log_text(ctx)
    return _mc_parse_log(log) if log else None
