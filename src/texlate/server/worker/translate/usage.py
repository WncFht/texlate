"""worker.translate.usage — usage 记账 + 旁路臂收尾叶 (worker.translate 域缝叶)。

``_meter_usage`` ``usage_sink`` 装配糖、``_persist_usage`` 真实 usage
落账唯一实现（旁路臂累加/唯一记账臂替换估算）、``_run_ephemeral``
旁路臂 ephemeral-loop 消费壳（coro 与 client 关闭收进同一
``asyncio.run``）、``_teardown_bypass`` 旁路臂统一收尾
（env_judge/L2/llm_hook 同构）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, TypeVar

from texlate.server.worker import seams
from texlate.server.worker._common import _new_usage_meter

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from texlate.server.worker._common import TaskCtx
    from texlate.xlat.client import ChatClient

log = logging.getLogger(__name__)

_T = TypeVar("_T")


class _TranslateUsage:
    """usage 记账/旁路臂收尾 mixin。"""

    def _meter_usage(self, clients: list[ChatClient]) -> dict[str, Any]:
        """给一组 client 挂 usage_sink 并返回累加 dict（``_new_usage_meter`` 的装配糖）。"""
        usage, sink = _new_usage_meter()
        for c in clients:
            c.usage_sink = sink
        return usage

    def _persist_usage(
        self, ctx: TaskCtx, usage: dict[str, Any], *, replace_est: bool = False
    ) -> None:
        """真实 usage 落账唯一实现——旁路臂**累加**、唯一记账臂**替换**。

        旁路 meter 只数本臂调用——``tokens_est`` **累加**而非覆盖
        （覆盖会把主链真账抹成旁路小计）。ExportError/crash 早退也把
        已发调用的真账留下；``_on_loop`` 回弹使 worker 线程内的旁路臂
        （env_judge/L2/llm_hook）也可直调，loop 线程上的
        ``_teardown_translate`` 则直调直写。``replace_est=True`` 给唯一
        记账臂（translating 段/doc 路——est 全程只是字符估算）用真账
        **替换**估算。
        """
        if not usage["calls"]:
            return
        real = usage["prompt_tokens"] + usage["completion_tokens"]
        ctx.tokens_est = real if replace_est else ctx.tokens_est + real
        self._on_loop(self.store.update_fields, ctx.task_id, tokens=ctx.tokens_est)
        self._on_loop(
            self.store.record_usage,
            ctx.task_id,
            model=str(usage["model"]),
            calls=int(usage["calls"]),
            prompt_tokens=int(usage["prompt_tokens"]),
            completion_tokens=int(usage["completion_tokens"]),
            latency_s=float(usage["latency_s"]),
        )

    def _run_ephemeral(
        self,
        clients: list[ChatClient],
        coro_fn: Callable[[], Awaitable[_T]],
    ) -> _T:
        """旁路臂 ephemeral-loop 消费壳：coro 与 client 关闭收进同一 ``asyncio.run``。

        client 的用/关必须收进同一 ephemeral loop——拆两次 ``asyncio.run``
        会在已关 loop 上 aclose（RuntimeError 吞掉 → 连接 FD 泄漏）；关完
        清空清单让外层 ``_teardown_bypass`` 不对已关 client 二次 aclose。
        """

        async def _arm() -> _T:
            try:
                return await coro_fn()
            finally:
                await seams._aclose_clients(clients)  # noqa: SLF001 -- seams 缝
                clients.clear()

        return asyncio.run(_arm())

    def _teardown_bypass(
        self,
        ctx: TaskCtx,
        usage: dict[str, Any] | None,
        clients: list[ChatClient],
        *,
        label: str,
    ) -> None:
        """旁路臂统一收尾（env_judge/L2/llm_hook 同构）：已发调用落账 + 未用 client 兜底关闭。

        旁路烧的是 BYOK token——崩溃/早退也把已发调用落账（``usage`` 为
        None 的臂只关 client）；``clients`` 非空 = 消费臂未跑到
        （``_run_ephemeral`` 跑过的已自清清单）——未用 client 在新 loop
        上关是平凡路径，兜底不敞口。
        """
        if usage is not None:
            try:
                self._persist_usage(ctx, usage)
            except Exception:
                log.debug("%s usage persist failed", label, exc_info=True)
        if clients:
            try:
                asyncio.run(seams._aclose_clients(clients))  # noqa: SLF001 -- seams 缝
            except Exception:
                log.debug("%s client aclose failed", label, exc_info=True)
