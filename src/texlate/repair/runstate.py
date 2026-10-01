"""repair.runstate — ``TreeRun``/``split_cid`` 运行态叶 (repair 拆分叶).

``TreeRun`` = ``_translate_tree`` 的内部运行态（splice 后供 logfix 回灌复用，
携带翻译期 ephemeral loop 令牌）；``split_cid`` 是 ``"fidx:cid"`` 复合键
拆分解的唯一实现（全仓共用，勿就地重写）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from pathlib import Path
    from typing import Any

    from texlate.latex.model import ScanResult
    from texlate.xlat.pipeline import ChunkIn, XlatPipeline

_T = TypeVar("_T")


@dataclass
class TreeRun:
    """``_translate_tree`` 的内部运行态——splice 后供 logfix 回灌复用。

    ``loop`` = 翻译期 ephemeral loop：``pipe`` 的 httpx client 池钉死在
    首个消费 loop 上，拆多次 ``asyncio.run`` 会让 env_judge/logfix 重译臂
    在死 loop 绑定的连接上跑（foreign-loop RuntimeError）。生命周期
    令牌与 ``baseline_snapshot`` td 同款——调用方持有到修复链收敛，
    收尾 ``close_loop()``；手工构造/worker 旁路臂留 ``None``，
    ``drive`` 退回逐次 ``asyncio.run``。
    """

    scans: list[tuple[Path, ScanResult]]
    trans: dict[int, dict[int, str]]  # fidx → {chunk.id: 译文}
    chunk_ins: dict[str, ChunkIn]  # "fidx:cid" → ChunkIn（带 ph_fragments）
    pipe: XlatPipeline
    loop: asyncio.AbstractEventLoop | None = field(default=None, repr=False)

    def drive(self, coro: Coroutine[Any, Any, _T]) -> _T:
        """在翻译期 loop 上跑协程——缺席（手工构造 run）退回 ``asyncio.run``。"""
        if self.loop is None:
            return asyncio.run(coro)
        return self.loop.run_until_complete(coro)

    def close_loop(self) -> None:
        """关翻译期 loop——pipe 条件收尾调用（幂等）。"""
        if self.loop is not None:
            self.loop.close()
            self.loop = None


def split_cid(chunk_id: str) -> tuple[int, int]:
    """``"fidx:cid"`` → (fidx, cid)."""
    a, _, b = chunk_id.partition(":")
    return int(a), int(b)
