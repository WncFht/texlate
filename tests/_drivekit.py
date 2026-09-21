"""``worker._loop``/``_loop_tid`` 钉住再 ``asyncio.run`` 的统一直驱面。

``PipelineWorker.run`` 在真回路里钉这两件（core.py）——``_on_loop`` 凭
``_loop`` 把 worker 线程的 store 写弹回 loop 线程。测试直驱 ``run_stage``
段体或 ``asyncio.to_thread`` 包重段时必须复刻这层钉法，否则弹回流静默
失能（写直接落 loop 外线程，断言面失真）。读 loop 侧 tid 用返回后的
``worker._loop_tid``。
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from texlate.server.worker import PipelineWorker


def drive[T](worker: PipelineWorker, awaitable: Awaitable[T]) -> T:
    """钉 ``worker._loop``/``_loop_tid`` 后 ``asyncio.run`` 跑 ``awaitable``。"""

    async def _pinned() -> T:
        worker._loop = asyncio.get_running_loop()  # noqa: SLF001
        worker._loop_tid = threading.get_ident()  # noqa: SLF001
        return await awaitable

    return asyncio.run(_pinned())
