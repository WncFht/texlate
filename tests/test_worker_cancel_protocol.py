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
import sys
import threading
import time
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from _drivekit import drive
from _workerkit import mk_ctx, mk_runner

import texlate.server.worker.emit as worker_emit
from texlate.compile.sandbox import run_process
from texlate.server.store import Store, new_task_id
from texlate.server.worker import (
    _FLUSH_N,
    PipelineWorker,
    Secrets,
    SegmentCache,
    TaskCtx,
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
        ctx, worker, _store = mk_ctx(tmp_path)
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
        ctx, worker, _store = mk_ctx(tmp_path)
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
        ctx, worker, _store = mk_ctx(tmp_path)
        monkeypatch.setattr(worker_emit, "_DRAIN_S", 0.2)
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
        ctx, worker, _store = mk_ctx(tmp_path)
        worker._abort_if_cancelled(ctx)  # noqa: SLF001 -- 未置位不抛
        ctx.cancel_flag.set()
        with pytest.raises(asyncio.CancelledError):
            worker._abort_if_cancelled(ctx)  # noqa: SLF001


class TestTerminalGuards:
    """终态后非状态写全体守卫（孤儿线程迟到扇出不落盘/不发声）。"""

    def test_log_warning_progress_register_guarded(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
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
        ctx, worker, store = mk_ctx(tmp_path)
        worker._progress(ctx, 33)  # noqa: SLF001
        worker._log(ctx, "live log")  # noqa: SLF001
        assert ctx.log_buf == ["live log"], "非终态行先缓冲（合批契约）"
        worker._flush_logs(ctx)  # noqa: SLF001
        assert store.get(ctx.task_id)["progress"] == 33  # noqa: PLR2004
        assert any(e["type"] == "log" for e in store.events_since(ctx.task_id, 0))


class TestCancelFlagProducers:
    """``_check_cancelled``/``cancel_running``/``stop`` 三点都置 cancel_flag。"""

    def test_check_cancelled_sets_flag(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        store.update_fields(ctx.task_id, status="cancelled")
        with pytest.raises(asyncio.CancelledError):
            worker._check_cancelled(ctx)  # noqa: SLF001
        assert ctx.cancel_flag.is_set()

    def test_cancel_running_sets_flag(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        runner = mk_runner(store, tmp_path, worker=worker, bus=ctx.bus)

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
        ctx, worker, store = mk_ctx(tmp_path)
        runner = mk_runner(store, tmp_path, worker=worker, bus=ctx.bus)

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
        ctx, worker, store = mk_ctx(tmp_path)
        runner = mk_runner(store, tmp_path, worker=worker, bus=ctx.bus)
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
        ctx, worker, store = mk_ctx(tmp_path)
        store.transition(ctx.task_id, "done", progress=100, force=True)
        runner = mk_runner(store, tmp_path, worker=worker, bus=ctx.bus)
        runner._dispatch_fault(ctx.task_id)  # noqa: SLF001
        assert store.get(ctx.task_id)["status"] == "done"
        assert not any(e["type"] == "error" for e in store.events_since(ctx.task_id, 0))


class TestOptIntClamp:
    """``_opt_int`` ``hi`` 上限钳位 + bad_option warning 留痕。"""

    def test_hi_clamp_warns(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
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
        ctx, worker, store = mk_ctx(tmp_path)
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
        ctx, worker, store = mk_ctx(tmp_path)
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
        ctx, worker, store = mk_ctx(tmp_path)
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
        ctx, worker, store = mk_ctx(tmp_path)
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
        drive(worker, worker.run_stage(ctx, "stage_fetch"))
        assert calls["n"] == 2, "零物化必须回退重跑 fetch"  # noqa: PLR2004
        assert ctx.reuse_dead
        assert ctx.reuse_hit is None
        assert (ctx.src_dir / ".fetch-done").is_file()


class TestDocOnResultBatching:
    """#11：doc 路 ``on_result`` 按 ``_FLUSH_N``/``_FLUSH_MS`` 合批——不打满 EVENT_CAP。"""

    def test_batches_until_threshold_then_flush(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
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


class TestRunProcessShouldCancel:
    """review2 worker#1：``run_process(should_cancel=)`` 分片轮询中断臂。

    ``communicate`` 在 ``TimeoutExpired`` 后可合法重入续读——按
    ``_CANCEL_POLL_S`` 切片间查旗标，置位抛 ``CancelledError`` 落既有
    ``except BaseException`` → ``_kill_tree`` 收树（孤儿收敛亚秒级）。
    """

    def test_should_cancel_kills_sleeper(self, tmp_path: Path) -> None:
        flag = threading.Event()
        timer = threading.Timer(0.2, flag.set)
        timer.start()
        t0 = time.monotonic()
        try:
            with pytest.raises(asyncio.CancelledError):
                run_process(
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    cwd=tmp_path,
                    env={},
                    timeout=60,
                    should_cancel=flag.is_set,
                )
        finally:
            timer.cancel()
        assert time.monotonic() - t0 < 10, "旗标置位须远早于 timeout 收敛"  # noqa: PLR2004

    def test_should_cancel_pre_set(self, tmp_path: Path) -> None:
        """旗标在 communicate 前已置位——首个轮询点即抛不空转。"""
        with pytest.raises(asyncio.CancelledError):
            run_process(
                [sys.executable, "-c", "print('never')"],
                cwd=tmp_path,
                env={},
                timeout=30,
                should_cancel=lambda: True,
            )

    def test_no_flag_unchanged(self, tmp_path: Path) -> None:
        """``should_cancel=None`` 旧路径：单发 communicate 正常回。"""
        rc, out, _s, timed_out = run_process(
            [sys.executable, "-c", "print('ok-line')"],
            cwd=tmp_path,
            env={},
            timeout=30,
        )
        assert rc == 0
        assert "ok-line" in out
        assert not timed_out


class TestLogBatching:
    """review2 worker#3：``_log`` 行合批——N 行/计时/边界排空合并成单事件。"""

    def _logs(self, store: Store, task_id: str) -> list[dict]:
        return [e for e in store.events_since(task_id, 0) if e["type"] == "log"]

    def test_n_lines_single_event(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        n = worker_emit._LOG_FLUSH_N  # noqa: SLF001
        for i in range(n):
            worker._log(ctx, f"l{i}")  # noqa: SLF001
        evs = self._logs(store, ctx.task_id)
        assert len(evs) == 1, "满批应只发一条合并事件"
        assert evs[0]["data"]["line"].splitlines() == [f"l{i}" for i in range(n)]
        assert ctx.log_buf == []

    def test_time_threshold_flushes(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        worker._log(ctx, "a")  # noqa: SLF001
        assert ctx.log_buf == ["a"], "首行缓冲不立即发"
        ctx.log_last -= worker_emit._LOG_FLUSH_S + 0.01  # noqa: SLF001 -- 推过计时闸
        worker._log(ctx, "b")  # noqa: SLF001
        evs = self._logs(store, ctx.task_id)
        assert len(evs) == 1
        assert evs[0]["data"]["line"].splitlines() == ["a", "b"]

    def test_residual_flushed_at_stage_boundary(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        worker._log(ctx, "l1")  # noqa: SLF001
        worker._log(ctx, "l2")  # noqa: SLF001
        assert not self._logs(store, ctx.task_id), "未满批不得提前扇出"
        worker.run_stage(ctx, "stage", "parsing", "解析", 9)
        evs = self._logs(store, ctx.task_id)
        assert len(evs) == 1
        assert evs[0]["data"]["line"].splitlines() == ["l1", "l2"]
        types = [e["type"] for e in store.events_since(ctx.task_id, 0)]
        assert types.index("log") < types.index("stage"), "log 不得越过 stage"

    def test_mark_terminal_flushes_and_drops(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        worker._mock_warned.add(ctx.task_id)  # noqa: SLF001
        worker._log(ctx, "tail")  # noqa: SLF001
        worker._mark_terminal(ctx, "done")  # noqa: SLF001
        assert [e["data"]["line"] for e in self._logs(store, ctx.task_id)] == [
            "tail"
        ], "终态迁移前残余行须先排空"
        assert ctx.terminal == "done"
        assert ctx.task_id not in worker._mock_warned, "终态摘除 mock 告警登记"  # noqa: SLF001
        worker._log(ctx, "after")  # noqa: SLF001
        assert ctx.log_buf == [], "terminal 置位后 _log 直接丢"

    def test_warning_orders_after_buffer(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        worker._log(ctx, "l1")  # noqa: SLF001
        worker._warning(ctx, "w1", "warn-msg")  # noqa: SLF001
        types = [e["type"] for e in store.events_since(ctx.task_id, 0)]
        assert types.index("log") < types.index("warning")


class TestMaterializeCopyfileToctou:
    """review2 worker#9：``is_file``→``copyfile`` 间并发清空 → OSError 按缺失跳过。"""

    def test_copyfile_oserror_skips(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shutil  # noqa: PLC0415

        ctx, worker, store = mk_ctx(tmp_path)
        donor = store.create_task(
            task_id=new_task_id(),
            kind="arxiv",
            target_lang="zh-CN",
            model="m",
            arxiv_id="2401.00002",
            options={},
        )
        hit_root = tmp_path / "tasks" / donor["id"]
        hit_root.mkdir(parents=True)
        (hit_root / "zh.pdf").write_bytes(b"%PDF-1.4 hit")
        store.put_file(donor["id"], "zh_pdf", "zh.pdf", data_dir=hit_root)
        ctx.root.mkdir(parents=True)

        def boom(*_a: object, **_kw: object) -> None:
            msg = "vanished between is_file and copyfile"
            raise FileNotFoundError(msg)

        monkeypatch.setattr(shutil, "copyfile", boom)
        n = worker._materialize_reuse(ctx, dict(donor))  # noqa: SLF001
        assert n == 0, "拷贝失败按缺失跳过——n=0 落零物化熔断臂"
        assert not (ctx.root / "zh.pdf").exists()
        worker._flush_logs(ctx)  # noqa: SLF001
        evs = [e for e in store.events_since(ctx.task_id, 0) if e["type"] == "log"]
        assert any("拷贝失败" in e["data"]["line"] for e in evs)


class TestBabeldocProgressThrottle:
    """review2 worker#7：on_progress 节流——pct Δ≥1pt 或距上次 ≥0.2s 才回弹。"""

    def test_ticks_throttled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import texlate.server.worker.pdf as pdf_mod  # noqa: PLC0415
        from texlate.server.babeldoc import BabeldocRun  # noqa: PLC0415

        ctx, worker, store = mk_ctx(tmp_path, worker_kw={"babeldoc": "/bin/true"})
        ctx.secrets = Secrets(api_key="k", base_url="http://b", model="m")
        ctx.root.mkdir(parents=True)
        up = ctx.root / "upload"
        up.mkdir()
        (up / "p.pdf").write_bytes(b"%PDF-1.4 fake")

        writes: list[int] = []

        def spy(_c: TaskCtx, v: int) -> None:
            writes.append(v)

        monkeypatch.setattr(worker, "_progress", spy)
        monkeypatch.setattr(worker, "_build_dual", lambda *_a: None)
        ticks = 200

        async def fake_run(_job: object, **kw: object) -> BabeldocRun:
            on_progress = kw["on_progress"]
            for i in range(ticks):
                on_progress(i * 0.4, "stage-a")
            return BabeldocRun(rc=0, seconds=0.1, status="ok", outputs={})

        monkeypatch.setattr(pdf_mod, "run_babeldoc", fake_run)
        drive(worker, worker.run_stage(ctx, "run_pdf"))
        assert 1 <= len(writes) <= ticks // 2, "0.4pt 步进的 tick 大多被节流"
        assert store.get(ctx.task_id)["status"] == "done"


class TestPendingEnqueue:
    """review2 worker#15：``_queue is None`` 窗 enqueue 暂存——secrets 不只登不消。"""

    def test_prestart_enqueue_drains_on_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = Store(tmp_path / "t.db")
        store.open()
        try:
            runner = mk_runner(store, tmp_path)
            row = store.create_task(
                task_id=new_task_id(),
                kind="arxiv",
                target_lang="zh-CN",
                model="m",
                auth_source="header",  # replay 防御性排除——唯 _pending_enqueue 送达
            )
            tid = str(row["id"])
            runner.enqueue(tid, Secrets(api_key="k"))
            assert runner._queue is None  # noqa: SLF001 -- start() 前窗
            assert tid in runner.secrets, "secrets 登记不丢"

            ran: list[str] = []

            async def fake_run(_self: PipelineWorker, c: TaskCtx) -> None:
                ran.append(c.task_id)

            monkeypatch.setattr(PipelineWorker, "run", fake_run)

            async def drive() -> None:
                runner.start()
                await asyncio.sleep(0.2)
                assert ran == [tid], "start() 须把暂存条目灌进队列"
                await runner.stop()

            asyncio.run(drive())
        finally:
            store.close()


class TestStageSeconds:
    """review2 worker#13：``_stage`` 首入点 monotonic → done 载荷 ``stage_seconds``。"""

    def test_stage_marks_first_touch(self, tmp_path: Path) -> None:
        ctx, worker, _store = mk_ctx(tmp_path)
        assert ctx.stage_marks == {}
        worker.run_stage(ctx, "stage", "fetching", "取源", 3)
        worker.run_stage(ctx, "stage", "parsing", "解析", 9)
        assert set(ctx.stage_marks) == {"fetching", "parsing"}
        first = ctx.stage_marks["fetching"]
        worker.run_stage(ctx, "stage", "fetching", "取源完成", 8)
        assert ctx.stage_marks["fetching"] == first, "setdefault 不覆写首入点"

    def test_stage_seconds_diff_and_done_payload(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        now = time.monotonic()
        ctx.stage_marks["fetching"] = now - 10.0
        ctx.stage_marks["parsing"] = now - 4.0
        ctx.stage_marks["translating"] = now - 1.0
        ss = worker._stats(ctx)["stage_seconds"]  # noqa: SLF001
        assert 5.9 <= ss["fetch"] <= 6.1  # noqa: PLR2004
        assert 2.9 <= ss["parse"] <= 3.1  # noqa: PLR2004
        assert ss["translate"] >= 0.9  # noqa: PLR2004 -- 末段计到构建点
        assert "compile" not in ss, "未跑段无 mark 自然缺席"
        worker._fail(ctx, "x", "boom", retryable=False, stage=None)  # noqa: SLF001
        done = [e for e in store.events_since(ctx.task_id, 0) if e["type"] == "done"][
            -1
        ]
        assert done["data"]["stats"]["stage_seconds"]["fetch"] == ss["fetch"]
