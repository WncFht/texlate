"""SSE 事件总线：``task_events`` 落盘 + 内存订阅扇出（web-layer §2.2/§3.4.3）。

写路径只在 loop 线程：``publish`` → store.append_event（seq 单调）→
扇出到该任务的订阅队列。断线重放走 ``store.events_since(last_id)``；
``snapshot`` 事件不落盘——连接建立时由任务行现场合成（seq=0）。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from texlate.server.store import TERMINAL_STATUSES

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from texlate.server.store import Store

#: 订阅队列上限——停滞消费者（慢网络/挂起连接）不无限吃内存：
#: 溢出即摘除订阅并压 ``_RESYNC`` 哨兵断流，客户端按 SSE 协议带
#: ``Last-Event-ID`` 重连走 ``events_since`` 重放补齐（task_events 是
#: 重放凭据，丢内存队列不丢事件）。量级参照 ``EVENT_CAP``。
_SUB_QUEUE_MAX = 512

#: 断流哨兵（队列专用类型，永不落盘/上电线）——stream 读到即 return。
_RESYNC: dict[str, Any] = {"seq": -1, "type": "_resync", "data": {}}


def _cut(q: asyncio.Queue[dict[str, Any]]) -> None:
    """清空积压压入断流哨兵（有界队列故两步必终止）。"""
    while not q.empty():
        q.get_nowait()
    q.put_nowait(_RESYNC)


def _gap_frame(
    replay: list[dict[str, Any]], last_event_id: int
) -> dict[str, Any] | None:
    """重放缺口检测 → ``resync`` 提示帧（无缺口 / 新连 ``last_event_id=0`` → ``None``）。

    缺口 = 首个可重放 seq 跳号（``last_event_id+1 .. first_seq-1`` 已被
    EVENT_CAP 滚动淘汰）。帧 ``seq`` 取 ``first_seq-1``：大于客户端
    水位线故前端 dedup 不吞；又小于后续真实帧，客户端 Last-Event-ID
    推进到它后断线重连仍从 ``first_seq`` 续放，零漏帧。
    ``data = {gap_after, resume_from}``——前端据它拉新 snapshot 重置
    水位线（旧版客户端无 ``resync`` 监听器，静默忽略不坏事）。
    """
    if not replay or last_event_id <= 0:
        return None
    first_seq = int(replay[0]["seq"])
    if first_seq <= last_event_id + 1:
        return None
    return {
        "seq": first_seq - 1,
        "type": "resync",
        "data": {"gap_after": last_event_id, "resume_from": first_seq},
    }


class EventBus:
    """每任务一组 ``asyncio.Queue`` 订阅者；发布 = 落盘 + 扇出。"""

    def __init__(self, store: Store) -> None:
        """绑定 store（事件持久化走它）。"""
        self._store = store
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    def publish(self, task_id: str, etype: str, data: dict[str, Any]) -> int:
        """事件落盘并扇出；返回分配的 seq。

        ``append_event`` 返 ``0`` = 任务行已删、事件未落盘——不扇出
        （订阅侧靠 delete 前的 done 帧已收场，幽灵帧只会污染水位线）。
        """
        seq = self._store.append_event(task_id, etype, data)
        if seq == 0:
            return 0
        subs = self._subs.get(task_id)
        if subs:
            item = {"seq": seq, "type": etype, "data": data}
            stalled: list[asyncio.Queue[dict[str, Any]]] = []
            for q in subs:
                try:
                    q.put_nowait(item)
                except asyncio.QueueFull:
                    stalled.append(q)
            for q in stalled:
                subs.discard(q)
                _cut(q)
            if not subs:
                self._subs.pop(task_id, None)
        return seq

    def subscribe(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        """注册订阅队列（``_SUB_QUEUE_MAX`` 有界——溢出判停滞断流）。"""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_SUB_QUEUE_MAX)
        self._subs.setdefault(task_id, set()).add(q)
        return q

    def unsubscribe(self, task_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        """摘除订阅；空集顺手清键。"""
        subs = self._subs.get(task_id)
        if subs is None:
            return
        subs.discard(q)
        if not subs:
            self._subs.pop(task_id, None)

    async def stream(
        self, task_id: str, *, last_event_id: int = 0
    ) -> AsyncIterator[dict[str, Any]]:
        """重放 + 实时混合流：先补 seq>last_event_id 的落盘事件，再转发订阅流。

        订阅先于重放注册，消灭间隙；实时侧按 seq 去重。任务终态（done
        事件落地）且队列排空后流自然结束。retry 复活过的任务重放段含
        上一轮 ``done`` 帧——只有落在重放段末尾且当前 status 仍终态的
        ``done`` 才终流；其余（旧轮残留 / 任务已复活）跳过防假死。
        ``last_event_id`` 落在已淘汰区段（首个重放 seq 跳号）时先 yield
        ``resync`` 提示帧再续放（契约见 :func:`_gap_frame`）。
        """
        q = self.subscribe(task_id)
        delivered = last_event_id
        try:
            replay = self._store.events_since(task_id, delivered)
            gap = _gap_frame(replay, last_event_id)
            if gap is not None:
                yield gap
            for i, ev in enumerate(replay):
                delivered = int(ev["seq"])
                if ev["type"] == "done":
                    row = self._store.get(task_id)
                    terminal = row is None or row["status"] in TERMINAL_STATUSES
                    if terminal and i == len(replay) - 1:
                        yield ev
                        return  # 终态已落盘：重放即终，不进实时等待
                    continue  # 旧轮 done 帧（retry 复活/后又有新终态）——跳过
                yield ev
            row = self._store.get(task_id)
            if row is None or row["status"] in TERMINAL_STATUSES:
                # 终态但 done 事件缺席（recover_startup 直改库等）或行已删
                # （delete 端点先发 done 再删行——本订阅晚注册即错过）——不空等
                return
            while True:
                ev = await q.get()
                if ev["type"] == "_resync":
                    return  # 积压溢出被摘除——客户端重连重放补齐
                seq = int(ev["seq"])
                if seq <= delivered:
                    continue
                delivered = seq
                yield ev
                if ev["type"] == "done":
                    return
        finally:
            self.unsubscribe(task_id, q)

    def close_all(self) -> None:
        """关停：全员压断流哨兵（唤醒 ``q.get()`` 上 parked 的生成器）再清表。"""
        for subs in self._subs.values():
            for q in subs:
                _cut(q)
        self._subs.clear()


def sse_frame(ev: dict[str, Any]) -> dict[str, Any]:
    """内部事件 dict → sse-starlette ServerSentEvent 字段。"""
    return {
        "id": str(ev["seq"]),
        "event": str(ev["type"]),
        "data": json.dumps(ev["data"], ensure_ascii=False),
    }
