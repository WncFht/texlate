"""SSE 事件总线：``task_events`` 落盘 + 内存订阅扇出（web-layer §2.2/§3.4.3）。

写路径只在 loop 线程：``publish`` → store.append_event（seq 单调）→
扇出到该任务的订阅队列。断线重放走 ``store.events_since(last_id)``；
``snapshot`` 事件不落盘——连接建立时由任务行现场合成（seq=0）。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from texlate.server.store import Store


class EventBus:
    """每任务一组 ``asyncio.Queue`` 订阅者；发布 = 落盘 + 扇出。"""

    def __init__(self, store: Store) -> None:
        """绑定 store（事件持久化走它）。"""
        self._store = store
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    def publish(self, task_id: str, etype: str, data: dict[str, Any]) -> int:
        """事件落盘并扇出；返回分配的 seq。"""
        seq = self._store.append_event(task_id, etype, data)
        subs = self._subs.get(task_id)
        if subs:
            item = {"seq": seq, "type": etype, "data": data}
            for q in subs:
                q.put_nowait(item)
        return seq

    def subscribe(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        """注册订阅队列（无界——内部缓冲，消费者是 SSE 生成器）。"""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
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
        事件落地）且队列排空后流自然结束。
        """
        q = self.subscribe(task_id)
        delivered = last_event_id
        try:
            for ev in self._store.events_since(task_id, delivered):
                delivered = int(ev["seq"])
                yield ev
                if ev["type"] == "done":
                    return  # 终态已落盘：重放即终，不进实时等待
            while True:
                ev = await q.get()
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
        """关停：清订阅表（生成器侧 finally 自行收尾）。"""
        self._subs.clear()


def sse_frame(ev: dict[str, Any]) -> dict[str, Any]:
    """内部事件 dict → sse-starlette ServerSentEvent 字段。"""
    return {
        "id": str(ev["seq"]),
        "event": str(ev["type"]),
        "data": json.dumps(ev["data"], ensure_ascii=False),
    }
