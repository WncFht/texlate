"""worker 取消协议钉样（审计修复批）：

- ``_to_thread``：cancel_flag 预查不发新段 + in_flight 登记/置位生命周期
- ``_drain_threads``：``_DRAIN_S`` 有界预算排空在飞段（孤儿残尾记 warning 放走）
- ``_log``/``_warning``/``_progress``/``_register`` 终态守卫（迟到写不落盘）
- ``_check_cancelled``/``cancel_running``/``stop`` 三点置 ``cancel_flag``
- ``_dispatch_fault``：dispatch 前置段失败 queued → fault + error/done 事件
- ``_opt_int`` ``hi`` 上限钳位 + bad_option warning（concurrency≤16/qps≤50）
- ``SegmentCache.prewarm`` 批查预载 + ``__delitem__`` 三面同清 + ``_written`` 续命
- ``XlatPipeline._drain`` cancel → finally 收尸 worker（不游离）
- ``_AbortingTranslator`` → ``_SectionAbort``（普通 Exception——非
  CancelledError/ChatError，给 export 内嵌管线的 crash-skip 排空语义）
- reuse 命中零物化 → ``reuse_dead`` 熔断回退自跑
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from test_worker_audit_fixes import _mk

import texlate.server.worker.events as worker_events
from texlate.server.events import EventBus
from texlate.server.store import new_task_id
from texlate.server.worker import (
    _FLUSH_N,
    SegmentCache,
    TaskCtx,
    TaskRunner,
    _AbortingTranslator,
    _SectionAbort,
)
from texlate.xlat.client import ChatError
from texlate.xlat.pipeline import (
    ChunkIn,
    ChunkResult,
    MockTranslator,
    PipelineConfig,
    XlatPipeline,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestToThreadProtocol:
    """``_to_thread``：旗标预查 + ``in_flight`` 登记生命周期。"""

    def test_flag_set_skips_new_section(self, tmp_path: Path) -> None:
        ctx, worker, _store = _mk(tmp_path)
        ran = threading.Event()

        def fn(_c: TaskCtx) -> None:
            ran.set()

        async def drive() -> None:
            ctx.cancel_flag.set()
            with pytest.raises(asyncio.CancelledError):
                await worker._to_thread(ctx, fn)  # noqa: SLF001
            assert not ran.is_set(), "旗标已置位不得新造在飞段"
            assert not ctx.in_flight, "预查拦截不得登记 in_flight"

        asyncio.run(drive())

    def test_in_flight_registers_and_sets(self, tmp_path: Path) -> None:
        ctx, worker, _store = _mk(tmp_path)
        started, release = threading.Event(), threading.Event()

        def slow(_c: TaskCtx) -> int:
            started.set()
            release.wait(2)
            return 7

        async def drive() -> None:
            t = asyncio.create_task(worker._to_thread(ctx, slow))  # noqa: SLF001
            assert await asyncio.to_thread(started.wait, 2)
            assert ctx.in_flight, "在飞段必须登记 in_flight"
            assert not all(e.is_set() for e in ctx.in_flight)
            release.set()
            assert await t == 7  # noqa: PLR2004
            assert all(e.is_set() for e in ctx.in_flight)

        asyncio.run(drive())

    def test_drain_threads_bounded_wait(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx, worker, _store = _mk(tmp_path)
        monkeypatch.setattr(worker_events, "_DRAIN_S", 0.2)
        gate = threading.Event()

        def hang(_c: TaskCtx) -> None:
            gate.wait(5)

        async def drive() -> None:
            t = asyncio.create_task(worker._to_thread(ctx, hang))  # noqa: SLF001
            await asyncio.sleep(0.05)
            t.cancel()  # coroutine 先死、线程仍卡 gate——孤儿现场
            with contextlib.suppress(asyncio.CancelledError):
                await t
            t0 = time.monotonic()
            await worker._drain_threads(ctx)  # noqa: SLF001
            elapsed = time.monotonic() - t0
            assert elapsed >= 0.15, "drain 必须真等过预算"  # noqa: PLR2004
            assert elapsed < 2.0, "drain 不得无界等孤儿"  # noqa: PLR2004
            gate.set()  # 放走孤儿线程防测试进程挂尾巴

        asyncio.run(drive())

    def test_abort_if_cancelled_pure_memory(self, tmp_path: Path) -> None:
        ctx, worker, _store = _mk(tmp_path)
        worker._abort_if_cancelled(ctx)  # noqa: SLF001 -- 未置位不抛
        ctx.cancel_flag.set()
        with pytest.raises(asyncio.CancelledError):
            worker._abort_if_cancelled(ctx)  # noqa: SLF001


class TestTerminalGuards:
    """终态后非状态写全体守卫（孤儿线程迟到扇出不落盘/不发声）。"""

    def test_log_warning_progress_register_guarded(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path)
        store.transition(ctx.task_id, "done", progress=100, force=True, message="完成")
        base = len(store.events_since(ctx.task_id, 0))
        worker._log(ctx, "late log")  # noqa: SLF001
        worker._warning(ctx, "x", "late warn")  # noqa: SLF001
        worker._progress(ctx, 42)  # noqa: SLF001
        rec = worker._register(ctx, "zh_pdf", "zh.pdf")  # noqa: SLF001
        assert len(store.events_since(ctx.task_id, 0)) == base, "终态后零新事件"
        assert store.get(ctx.task_id)["progress"] == 100  # noqa: PLR2004
        assert "zh_pdf" not in store.files(ctx.task_id)
        assert rec["kind"] == "zh_pdf"
        assert rec["bytes"] is None  # 同形 dict 返回

    def test_guarded_before_terminal_still_writes(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path)
        worker._progress(ctx, 33)  # noqa: SLF001
        worker._log(ctx, "live log")  # noqa: SLF001
        assert store.get(ctx.task_id)["progress"] == 33  # noqa: PLR2004
        assert any(e["type"] == "log" for e in store.events_since(ctx.task_id, 0))


class TestCancelFlagProducers:
    """``_check_cancelled``/``cancel_running``/``stop`` 三点都置 cancel_flag。"""

    def test_check_cancelled_sets_flag(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path)
        store.update_fields(ctx.task_id, status="cancelled")
        with pytest.raises(asyncio.CancelledError):
            worker._check_cancelled(ctx)  # noqa: SLF001
        assert ctx.cancel_flag.is_set()

    def test_cancel_running_sets_flag(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path)
        runner = TaskRunner(store, EventBus(store), worker)

        async def drive() -> None:
            task = asyncio.create_task(asyncio.sleep(30))
            runner._current = (ctx.task_id, ctx, task)  # noqa: SLF001
            assert not runner.cancel_running("other-task")
            assert runner.cancel_running(ctx.task_id)
            assert ctx.cancel_flag.is_set()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            assert task.cancelled()

        asyncio.run(drive())

    def test_stop_sets_flag(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path)
        runner = TaskRunner(store, EventBus(store), worker)

        async def drive() -> None:
            worker_task = asyncio.create_task(asyncio.sleep(30))
            runner._current = (ctx.task_id, ctx, worker_task)  # noqa: SLF001
            await runner.stop()
            assert ctx.cancel_flag.is_set()
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task

        asyncio.run(drive())


class TestDispatchFault:
    """dispatch 前置段失败：queued → fault + error/done 事件；非 queued 不覆盖。"""

    def test_queued_transitions_fault(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path)
        runner = TaskRunner(store, EventBus(store), worker)
        runner._dispatch_fault(ctx.task_id)  # noqa: SLF001
        row = store.get(ctx.task_id)
        assert row["status"] == "fault"
        err = json.loads(str(row["error_json"]))
        assert err["code"] == "internal"
        assert err["retryable"] is True
        types = [e["type"] for e in store.events_since(ctx.task_id, 0)]
        assert "error" in types
        assert "done" in types

    def test_non_queued_untouched(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path)
        store.transition(ctx.task_id, "done", progress=100, force=True)
        runner = TaskRunner(store, EventBus(store), worker)
        runner._dispatch_fault(ctx.task_id)  # noqa: SLF001
        assert store.get(ctx.task_id)["status"] == "done"
        assert not any(e["type"] == "error" for e in store.events_since(ctx.task_id, 0))


class TestOptIntClamp:
    """``_opt_int`` ``hi`` 上限钳位 + bad_option warning 留痕。"""

    def test_hi_clamp_warns(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path)
        got = worker._opt_int(  # noqa: SLF001
            ctx, {"concurrency": 99}, "concurrency", 3, hi=16
        )
        assert got == 16  # noqa: PLR2004
        got = worker._opt_int(ctx, {"qps": 500}, "qps", 4, hi=50)  # noqa: SLF001
        assert got == 50  # noqa: PLR2004
        assert (
            worker._opt_int(ctx, {"concurrency": 4}, "concurrency", 3, hi=16)  # noqa: SLF001
            == 4  # noqa: PLR2004
        )
        warns = [
            e
            for e in store.events_since(ctx.task_id, 0)
            if e["type"] == "warning" and e["data"]["code"] == "bad_option"
        ]
        msgs = [w["data"]["message"] for w in warns]
        assert any("concurrency" in m for m in msgs)
        assert any("qps" in m for m in msgs)


class TestSegmentCachePrewarm:
    """prewarm 批查预载 + ``__delitem__`` 三面同清 + ``_written`` run 内续命。"""

    def test_prewarm_read_and_delete(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path)
        del ctx, worker
        store.conn.execute(
            "INSERT INTO translation_cache"
            " (key, translation, model, target_lang, hit_count,"
            "  created_at, last_hit_at) VALUES (?,?,?,?,0,0,0)",
            ("pfx:k1", "译文一", "m", "zh-CN"),
        )
        store.conn.commit()
        cache = SegmentCache(store, prefix="pfx", model="m", target_lang="zh-CN")
        cache.prewarm(["k1", "k2"])
        assert "k1" in cache
        assert "k2" not in cache
        assert cache["k1"] == "译文一"
        assert store._cache_hits.get("pfx:k1") == 1  # noqa: SLF001 -- 借道记账可断言
        with pytest.raises(KeyError):
            cache["k2"]
        # pending → drain → _written：run 内 dedup 不回表
        cache["k3"] = "译文三"
        assert "k3" in cache
        drained = cache.drain()
        assert ("pfx:k3", "译文三", "m", "zh-CN") in drained
        assert cache["k3"] == "译文三"
        # __delitem__：内存三面 + 库行同清
        del cache["k1"]
        assert "k1" not in cache
        assert store.cache_get("pfx:k1") is None
        del cache["k3"]
        assert "k3" not in cache
        # 未预载实例回退逐键读穿透（库行已被删 → miss）
        cold = SegmentCache(store, prefix="pfx", model="m", target_lang="zh-CN")
        assert "k2" not in cold


class _HangTranslator:
    """translate 永不返回——记录跑它的 task 供收尸断言。"""

    def __init__(self) -> None:
        self.tasks: list[asyncio.Task[None] | None] = []

    async def translate(self, **_kw: object) -> str:
        self.tasks.append(asyncio.current_task())
        await asyncio.Event().wait()
        return ""  # pragma: no cover -- 永不到达


class TestPipelineDrainCancel:
    """``_drain`` cancel：join 被撕开后 finally 收尸 worker——不揣半开 client 游离。"""

    def test_cancel_collects_workers(self, tmp_path: Path) -> None:
        del tmp_path
        tr = _HangTranslator()

        async def drive() -> list[asyncio.Task[None] | None]:
            pipe = XlatPipeline(tr, config=PipelineConfig(concurrency=2))
            chunks = [
                ChunkIn(chunk_id=f"c{i}", content=f"para {i} " * 8, kind="para")
                for i in range(5)
            ]
            items = [("single", c) for c in chunks]
            t = asyncio.create_task(pipe._drain(items, {}))  # noqa: SLF001
            await asyncio.sleep(0.1)  # warmup 首 item + worker 上工
            t.cancel()
            with pytest.raises(asyncio.CancelledError):
                await t
            return tr.tasks

        tasks = asyncio.run(drive())
        assert tasks, "worker/warmup 必须真上过工"
        assert all(x is not None and x.done() for x in tasks), (
            "cancel 后所有 task 必须被收尸"
        )
        assert any(x.cancelled() for x in tasks if x is not None)


class TestAbortingTranslator:
    """``_AbortingTranslator``：旗标置位 → ``_SectionAbort``（非 CancelledError/ChatError）。"""

    def test_flag_raises_section_abort(self, tmp_path: Path) -> None:
        del tmp_path
        inner = MockTranslator()
        flag = threading.Event()
        tr = _AbortingTranslator(inner, flag)

        async def drive() -> None:
            out = await tr.translate(
                system="s", user="hello world", temperature=0.0, max_tokens=10
            )
            assert out == inner.zh, "未置位时透传 inner"
            flag.set()
            with pytest.raises(_SectionAbort) as ei:
                await tr.translate(system="s", user="x", temperature=0.0, max_tokens=10)
            assert not isinstance(ei.value, asyncio.CancelledError)
            assert not isinstance(ei.value, ChatError)

        asyncio.run(drive())
        assert len(inner.calls) == 1, "置位后的调用不得落到 inner"
        assert tr.calls is inner.calls, "__getattr__ 透传接线面"


class TestReuseZeroMaterialize:
    """#12：命中行产物被并发清空 → 零物化 → ``reuse_dead`` 熔断回退自跑。"""

    def test_materialize_empty_returns_zero(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path)
        donor = store.create_task(
            task_id=new_task_id(),
            kind="arxiv",
            target_lang="zh-CN",
            model="m",
            arxiv_id="2401.00002",
            options={},
        )
        n = worker._materialize_reuse(ctx, dict(donor))  # noqa: SLF001
        assert n == 0

    def test_post_resolve_dead_skips_lookup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx, worker, store = _mk(tmp_path)
        ctx.reuse_dead = True
        store.update_fields(ctx.task_id, cache_key="alias-key")
        ctx.row["cache_key"] = "alias-key"

        def _boom(*_a: object, **_k: object) -> None:
            pytest.fail("reuse_dead 下 find_reusable 不许被调")

        monkeypatch.setattr(store, "find_reusable", _boom)
        hit = worker._post_resolve_reuse(  # noqa: SLF001
            ctx, "2401.00001", 2, source="eprint"
        )
        assert hit is False
        assert store.get(ctx.task_id)["cache_key"] != "alias-key", "re-key 保留"

    def test_zero_materialize_refetches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx, worker, store = _mk(tmp_path)
        donor = store.create_task(
            task_id=new_task_id(),
            kind="arxiv",
            target_lang="zh-CN",
            model="m",
            arxiv_id="2401.00002",
            options={},
        )
        ctx.root.mkdir(parents=True)
        ctx.src_dir.mkdir(parents=True)
        calls = {"n": 0}

        def fake_fetch(c: TaskCtx) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                c.reuse_hit = dict(donor)

        monkeypatch.setattr(worker, "_fetch_arxiv", fake_fetch)

        async def drive() -> None:
            worker._loop = asyncio.get_running_loop()  # noqa: SLF001
            worker._loop_tid = threading.get_ident()  # noqa: SLF001
            await worker._stage_fetch(ctx)  # noqa: SLF001

        asyncio.run(drive())
        assert calls["n"] == 2, "零物化必须回退重跑 fetch"  # noqa: PLR2004
        assert ctx.reuse_dead
        assert ctx.reuse_hit is None
        assert (ctx.src_dir / ".fetch-done").is_file()


class TestDocOnResultBatching:
    """#11：doc 路 ``on_result`` 按 ``_FLUSH_N``/``_FLUSH_MS`` 合批——不打满 EVENT_CAP。"""

    def test_batches_until_threshold_then_flush(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path)
        counters = {"done": 0, "failed": 0}
        on_result, flush = worker._doc_on_result(ctx, counters)  # noqa: SLF001
        r = ChunkResult(chunk_id="c1", source="abcdef", translation="译文", kind="para")
        for _ in range(_FLUSH_N - 1):
            on_result(r)
        assert not [
            e for e in store.events_since(ctx.task_id, 0) if e["type"] == "chunk"
        ], "未满批不得回弹"
        on_result(r)  # 第 _FLUSH_N 条触发合批
        evs = [e for e in store.events_since(ctx.task_id, 0) if e["type"] == "chunk"]
        assert len(evs) == 1
        assert len(evs[0]["data"]["items"]) == _FLUSH_N
        on_result(r)
        flush()  # _run_doc finally 的尾批排空
        evs = [e for e in store.events_since(ctx.task_id, 0) if e["type"] == "chunk"]
        assert len(evs) == 2  # noqa: PLR2004
        assert len(evs[1]["data"]["items"]) == 1
        assert store.get(ctx.task_id)["done_chunks"] == _FLUSH_N + 1
