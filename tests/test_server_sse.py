"""§2.2 SSE：snapshot seq=0 合成帧、Last-Event-ID 重放、done 终流。"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from conftest import mk_api_task, mk_task_row

from texlate.server.events import EventBus, sse_frame
from texlate.server.store import Store

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from starlette.testclient import TestClient

ARXIV = "2401.00002"


def _has_sub(bus: EventBus, tid: str) -> bool:
    """bus 是否已有 tid 的订阅者（无公开计数面——读私有表）。"""
    return bool(bus._subs.get(tid))  # noqa: SLF001


def _wait_sub(bus: EventBus, tid: str, timeout: float = 5.0) -> None:
    """自旋到订阅注册：publish 先于订阅会落重放段，live 扇出路径钉不死。"""
    deadline = time.monotonic() + timeout
    while not _has_sub(bus, tid):
        assert time.monotonic() < deadline, f"task {tid} 订阅未注册"
        time.sleep(0.01)


class TestBusStream:
    """直连 EventBus（不走路由层）——重放/实时/done 语义。"""

    @pytest.fixture
    def bus(self, tmp_path: Path) -> Iterator[tuple[Store, EventBus]]:
        store = Store(tmp_path / "t.db")
        store.open()
        b = EventBus(store)
        yield store, b
        store.close()

    def test_replay_then_live(self, bus: tuple[Store, EventBus]) -> None:
        store, b = bus
        tid = mk_task_row(store)["id"]

        async def run() -> list[dict]:
            async def sub() -> list[dict]:
                return [ev async for ev in b.stream(tid)]

            task = asyncio.create_task(sub())
            for _ in range(100):  # sub 首步即挂 _subs——订阅确定再发，走 live 段
                if _has_sub(b, tid):
                    break
                await asyncio.sleep(0)
            assert _has_sub(b, tid)
            b.publish(tid, "stage", {"stage": "parsing"})
            b.publish(tid, "done", {"status": "done"})
            return await asyncio.wait_for(task, 5)

        seen = asyncio.run(run())
        assert [e["type"] for e in seen] == ["stage", "done"]
        assert seen[0]["seq"] == 1

    def test_last_event_id_skips(self, bus: tuple[Store, EventBus]) -> None:
        store, b = bus
        tid = mk_task_row(store)["id"]
        b.publish(tid, "a", {"n": 1})
        b.publish(tid, "b", {"n": 2})

        async def run() -> list[dict]:
            out = []
            async for ev in b.stream(tid, last_event_id=1):
                out.append(ev)
                if len(out) == 1:  # 只读到 seq=2 就撤，避免挂实时等待
                    break
            return out

        seen = asyncio.run(run())
        assert seen[0]["type"] == "b"
        assert seen[0]["seq"] == 2  # noqa: PLR2004 - seq 单调步进

    def test_replayed_done_terminates(self, bus: tuple[Store, EventBus]) -> None:
        store, b = bus
        tid = mk_task_row(store)["id"]
        store.transition(tid, "done", force=True)
        b.publish(tid, "done", {"status": "done"})

        async def run() -> list[dict]:
            return [ev async for ev in b.stream(tid)]

        seen = asyncio.run(asyncio.wait_for(run(), 5))
        assert [e["type"] for e in seen] == ["done"]

    def test_sse_frame_shape(self) -> None:
        frame = sse_frame({"seq": 3, "type": "chunk", "data": {"done": 2}})
        assert frame["id"] == "3"
        assert frame["event"] == "chunk"
        assert json.loads(frame["data"]) == {"done": 2}

    def test_overflow_cuts_stalled_sub(
        self, bus: tuple[Store, EventBus], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """订阅队列溢出 → 摘除 + 哨兵断流；重连按 events_since 全量重放。"""
        monkeypatch.setattr("texlate.server.events._SUB_QUEUE_MAX", 2)
        store, b = bus
        tid = mk_task_row(store)["id"]

        async def run() -> list[dict]:
            out: list[dict] = []

            async def sub() -> None:
                out.extend([ev async for ev in b.stream(tid)])

            task = asyncio.create_task(sub())
            for _ in range(100):
                if _has_sub(b, tid):
                    break
                await asyncio.sleep(0)
            # cap=2：第 3 发触发 QueueFull——积压被清、订阅摘除、哨兵断流
            for i in range(3):
                b.publish(tid, "stage", {"i": i})
            await asyncio.wait_for(task, 5)
            return out

        seen = asyncio.run(run())
        assert seen == []  # 积压被 _cut 清掉——内存队列丢了但落盘未丢
        assert not _has_sub(b, tid)
        store.transition(tid, "done", force=True)
        b.publish(tid, "done", {"status": "done"})

        async def replay() -> list[dict]:
            return [ev async for ev in b.stream(tid)]

        seen2 = asyncio.run(asyncio.wait_for(replay(), 5))
        assert [e["type"] for e in seen2] == ["stage", "stage", "stage", "done"]

    def test_close_all_wakes_parked(self, bus: tuple[Store, EventBus]) -> None:
        """close_all 压哨兵唤醒 q.get() 等待者——关停不依赖传输层取消。"""
        store, b = bus
        tid = mk_task_row(store)["id"]

        async def run() -> list[dict]:
            out: list[dict] = []

            async def sub() -> None:
                out.extend([ev async for ev in b.stream(tid)])

            task = asyncio.create_task(sub())
            for _ in range(100):
                if _has_sub(b, tid):
                    break
                await asyncio.sleep(0)
            assert _has_sub(b, tid)
            b.close_all()
            await asyncio.wait_for(task, 5)
            return out

        seen = asyncio.run(run())
        assert seen == []
        assert not _has_sub(b, tid)


class TestHttpSse:
    """starlette 1.x TestClient 把整个响应缓冲完才返回——流必须先终结再读。

    实时扇出由另起线程 ``portal.call(bus.publish)`` 驱动（本线程堵在
    ``portal.call(app)`` 里无法再发调用）。
    """

    def test_snapshot_frame_first(self, client: TestClient) -> None:
        """首帧 = 合成 snapshot(id:0)；落盘事件随重放流出，done 终流。"""
        tid = mk_api_task(client, ARXIV)
        bus = client.app.state.bus
        client.portal.call(
            partial(client.app.state.store.transition, tid, "done", force=True)
        )
        client.portal.call(partial(bus.publish, tid, "stage", {"stage": "parsing"}))
        client.portal.call(partial(bus.publish, tid, "done", {"status": "done"}))
        with client.stream(
            "GET", f"/api/task/{tid}", headers={"Accept": "text/event-stream"}
        ) as r:
            assert r.status_code == HTTPStatus.OK
            assert r.headers["content-type"].startswith("text/event-stream")
            lines = [ln for ln in r.iter_lines() if ln]
        assert lines[0] == "id: 0"
        assert lines[1] == "event: snapshot"
        snap = json.loads(lines[2].removeprefix("data: "))
        assert snap["task_id"] == tid
        events = [ln[7:] for ln in lines if ln.startswith("event:")]
        assert events == ["snapshot", "stage", "done"]
        ids = [ln[4:] for ln in lines if ln.startswith("id: ")]
        assert ids == ["0", "1", "2"]

    def test_live_publish_then_done(self, client: TestClient) -> None:
        """订阅建立后的 publish 走实时队列扇出。"""
        tid = mk_api_task(client, ARXIV)
        bus = client.app.state.bus

        def feed() -> None:
            # 等 gen 进到 bus.stream 订阅段再发——钉死 live 扇出路径；
            # 订阅若永不注册则只发 done（少 stage → 断言显败，且不挂 iter_lines）
            subscribed = True
            try:
                _wait_sub(bus, tid)
            except AssertionError:
                subscribed = False
            if subscribed:
                client.portal.call(
                    partial(bus.publish, tid, "stage", {"stage": "parsing"})
                )
            client.portal.call(partial(bus.publish, tid, "done", {"status": "done"}))

        t = threading.Thread(target=feed)
        t.start()
        with client.stream(
            "GET", f"/api/task/{tid}", headers={"Accept": "text/event-stream"}
        ) as r:
            events = [ln[7:] for ln in r.iter_lines() if ln.startswith("event:")]
        t.join(timeout=5)
        assert events == ["snapshot", "stage", "done"]

    def test_last_event_id_replay(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        bus = client.app.state.bus
        client.portal.call(
            partial(client.app.state.store.transition, tid, "done", force=True)
        )
        client.portal.call(partial(bus.publish, tid, "stage", {"stage": "a"}))
        client.portal.call(partial(bus.publish, tid, "done", {"status": "done"}))
        # Last-Event-ID=1 → 只重放 done；done 即终流
        with client.stream(
            "GET",
            f"/api/task/{tid}",
            headers={"Accept": "text/event-stream", "Last-Event-ID": "1"},
        ) as r:
            events = [ln[7:] for ln in r.iter_lines() if ln.startswith("event:")]
        assert events == ["snapshot", "done"]
