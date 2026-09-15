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

from texlate.server.events import EventBus, sse_frame
from texlate.server.store import Store, new_task_id

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from starlette.testclient import TestClient

ARXIV = "2401.00002"
_FEED_DELAY = 0.3


def _mk_task(client: TestClient) -> str:
    r = client.post(f"/api/arxiv/{ARXIV}/translate", json={})
    assert r.status_code == HTTPStatus.ACCEPTED
    return r.json()["task_id"]


class TestBusStream:
    """直连 EventBus（不走路由层）——重放/实时/done 语义。"""

    @pytest.fixture
    def bus(self, tmp_path: Path) -> Iterator[tuple[Store, EventBus]]:
        store = Store(tmp_path / "t.db")
        store.open()
        b = EventBus(store)
        yield store, b
        store.close()

    def _mk(self, store: Store) -> str:
        return store.create_task(
            task_id=new_task_id(), kind="arxiv", target_lang="zh-CN", model="m"
        )["id"]

    def test_replay_then_live(self, bus: tuple[Store, EventBus]) -> None:
        store, b = bus
        tid = self._mk(store)

        async def run() -> list[dict]:
            async def sub() -> list[dict]:
                return [ev async for ev in b.stream(tid)]

            task = asyncio.create_task(sub())
            await asyncio.sleep(0.05)
            b.publish(tid, "stage", {"stage": "parsing"})
            b.publish(tid, "done", {"status": "done"})
            return await asyncio.wait_for(task, 5)

        seen = asyncio.run(run())
        assert [e["type"] for e in seen] == ["stage", "done"]
        assert seen[0]["seq"] == 1

    def test_last_event_id_skips(self, bus: tuple[Store, EventBus]) -> None:
        store, b = bus
        tid = self._mk(store)
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
        tid = self._mk(store)
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


class TestHttpSse:
    """starlette 1.x TestClient 把整个响应缓冲完才返回——流必须先终结再读。

    实时扇出由另起线程 ``portal.call(bus.publish)`` 驱动（本线程堵在
    ``portal.call(app)`` 里无法再发调用）。
    """

    def test_snapshot_frame_first(self, client: TestClient) -> None:
        """首帧 = 合成 snapshot(id:0)；落盘事件随重放流出，done 终流。"""
        tid = _mk_task(client)
        bus = client.app.state.bus
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
        tid = _mk_task(client)
        bus = client.app.state.bus

        def feed() -> None:
            time.sleep(_FEED_DELAY)  # 等 gen 进到 bus.stream 的订阅段
            client.portal.call(partial(bus.publish, tid, "stage", {"stage": "parsing"}))
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
        tid = _mk_task(client)
        bus = client.app.state.bus
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
