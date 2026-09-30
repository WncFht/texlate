"""客户端接线/适配小件域（自 ``_common`` 出叶）。

``_new_usage_meter`` 是 ``ChatClient.usage_sink`` 真账记账累加器（主链/
旁路臂共用）；``_translator_clients``/``_aclose_clients`` 是 translator
底层 ``ChatClient`` 面的取出与尽力收尾（``_FallbackTranslator`` 主备两路、
单路 ``.client``、``_PerCallTranslator`` 存活 loop 面三形归一）；
``_Sink`` 是 ``pipecore.ReportSink`` 的 worker 适配——修复链实况/日志
出口单口（e2e/bench 臂走 ``NULL_SINK`` 不构造本类）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from texlate.xlat.client import ChatClient

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.xlat.client import UsageRecord

log = logging.getLogger(__name__)


def _new_usage_meter() -> tuple[dict[str, Any], Callable[[UsageRecord], None]]:
    """Usage 累加器 + ``ChatClient.usage_sink`` 回调（T4 真账记账）。

    主链/旁路臂（env_judge、L2、doc export）共用——旁路 client 不挂
    sink 时 token 消耗从 ``task_usage`` 蒸发。
    """
    usage: dict[str, Any] = {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "latency_s": 0.0,
        "model": "",
    }

    def _on_usage(u: UsageRecord) -> None:
        usage["calls"] += 1
        usage["prompt_tokens"] += u["prompt_tokens"]
        usage["completion_tokens"] += u["completion_tokens"]
        usage["latency_s"] += u["latency_s"]
        usage["model"] = u["model"]

    return usage, _on_usage


def _translator_clients(translator: object) -> list[ChatClient]:
    """取 translator 底层 ``ChatClient`` 列表（usage_sink/aclose 接线面）。

    ``_FallbackTranslator`` 主备两路；单路 translator 只有 ``.client``。
    """
    raw = getattr(translator, "clients", None)
    if raw is None:
        raw = [getattr(translator, "client", None)]
    return [c for c in raw if isinstance(c, ChatClient)]


async def _aclose_clients(clients: list[ChatClient]) -> None:
    """逐一关 translator 底层 client（L2/env_judge 旁路自建 translator 的收尾）。

    单个 aclose 抛错（连接已坏/半关状态）不挡其余、不上浮——收尾失败
    不该把任务终态改判 fault，更不该在 ``finally`` 里盖掉真异常。
    """
    for c in clients:
        try:
            await c.aclose()
        except Exception as e:  # noqa: BLE001 -- 收尾尽力而为
            log.debug("client aclose failed: %s: %s", type(e).__name__, e)


class _Sink:
    """``pipecore.ReportSink`` 的 worker 适配——绑 ``_log``/``_repair_event`` 闭包。

    修复链实况/日志出口单口：pipecore 各 ``sink.log``/``sink.event``
    调用经此分发到任务日志行与 ``bus.publish``（scrub 在
    ``_repair_event`` 内）。e2e/bench 臂走 ``NULL_SINK`` 不构造本类。
    """

    __slots__ = ("_event_fn", "_log_fn")

    def __init__(
        self,
        log_fn: Callable[[str], None],
        event_fn: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self._log_fn = log_fn
        self._event_fn = event_fn

    def log(self, msg: str) -> None:
        """一行修复日志 → 任务日志。"""
        self._log_fn(msg)

    def event(self, etype: str, payload: dict[str, Any]) -> None:
        """一帧修复实况 → ``_repair_event``（scrub+发布）。"""
        self._event_fn(etype, payload)
