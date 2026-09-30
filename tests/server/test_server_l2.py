"""worker 编译段加固验收：L2 回灌编排（先于 fixloop）/ env_judge /
.compile-done 哨兵 resume / interrupted done 事件 / .splice-done 序。

e2e 侧语义对齐 ``pipe_condition``：非 clean → L2（归因重译+resplice+重编）
→ 仍非 clean → fixloop。worker 侧多担一层：resplice 改的是 ``build-zh``，
成品树 ``zh/`` 与 chunks 表由 worker 自己回写。
"""

from __future__ import annotations

import asyncio
import time
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from _serverkit import L2FlakyEngine
from conftest import (
    MINI_TEX,
    FakeEngine,
    live_app,
    mk_task_row,
    store_call,
    task_events,
    upload_tex,
    wait_terminal,
)
from starlette.testclient import TestClient

from texlate.server.events import EventBus
from texlate.server.store import Store, new_task_id
from texlate.server.worker import PipelineWorker, Secrets, TaskCtx, TaskRunner
from texlate.server.worker._common import (
    _compile_done_verdict,
    _write_compile_done,
)
from texlate.xlat.pipeline import MockTranslator

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

    from texlate.compile.engine import CompRes


#: 含未知 env 的工程——env_judge 判定面（``mybox`` 不在静态表内）
ENV_TEX = (
    "\\documentclass{article}\n"
    "\\newenvironment{mybox}{}{}\n"
    "\\begin{document}\n"
    "\\section{Intro}\n"
    "\\begin{mybox}\n"
    "This paragraph sits inside a custom environment and is long enough to\n"
    "become a translation chunk for the pipeline to process.\n"
    "\\end{mybox}\n"
    "\\end{document}\n"
)


class EnvJudgeNoTranslator(MockTranslator):
    """env_judge 调用（``should be translated`` 判定 prompt）一律答 False。"""

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """judge prompt → ``False``（判不可译）；其余走 mock。"""
        if "should be translated" in system:
            self.calls.append(
                {
                    "system": system,
                    "user": user,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
            )
            return "False"
        return await super().translate(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )


class _HangTranslator:
    """translate 永挂——cancel/interrupted 路径用。"""

    async def translate(
        self,
        *,
        system: str,  # noqa: ARG002
        user: str,  # noqa: ARG002
        temperature: float,  # noqa: ARG002
        max_tokens: int,  # noqa: ARG002
        response_format: dict[str, str] | None = None,  # noqa: ARG002
    ) -> str:
        """睡到被 cancel。"""
        await asyncio.sleep(3600)
        return ""  # pragma: no cover -- 永远到不了


class _BangEngine:
    """compile 直接抛——``_fail`` 取 fresh stage 的观测面。"""

    name = "bang"

    def compile(self, wdir: Path, main: str, **kw: object) -> CompRes:  # noqa: ARG002
        """必炸。"""
        msg = "engine exploded"
        raise RuntimeError(msg)


def _live_app(
    tmp_path: Path,
    *,
    translator: object | None = None,
    engine: object | None = None,
    **kw: object,
) -> FastAPI:
    """start_worker app：可注入 translator/engine（缺省 Mock+Fake）。"""
    t = translator if translator is not None else MockTranslator()
    e = engine if engine is not None else FakeEngine()
    return live_app(tmp_path, lambda _ctx: t, engine_factory=lambda _name: e, **kw)


def _chunks(client: TestClient, tid: str) -> list[dict]:
    """chunks 表全量（portal 回 loop 线程）。"""
    return store_call(client, client.app.state.store.all_chunks, tid)


class TestL2Repair:
    """L2 回灌编排：非 clean → L2（重译+resplice+重编）→ fixloop。"""

    def test_l2_repair_skips_fixloop(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """首编可归因失败 → L2 重译+重编转绿 → fixloop 不跑 → done。"""
        eng = L2FlakyEngine(n_fail=1)
        translator = MockTranslator()
        with TestClient(_live_app(tmp_path, translator=translator, engine=eng)) as c:
            tid = upload_tex(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "done", snap
            evs = task_events(c, tid)
            l2_evs = [e for e in evs if e["type"] == "l2"]
            l2_done = [e["data"] for e in l2_evs if e["data"].get("phase") == "done"]
            assert len(l2_done) == 1
            assert l2_done[0]["retranslated"]
            assert l2_done[0]["report"]["recompiled"] == "clean"
            # L2 修好后 zh 侧 fixloop 不跑——en 臂帧（cond="en"）合法在流中
            assert all(
                e["data"].get("cond") == "en" for e in evs if e["type"] == "fixloop"
            )
            # 重译真被调过（[compile_error] 反馈）
            assert any("[compile_error]" in call["user"] for call in translator.calls)

    def test_l2_runs_before_fixloop(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """L2 重编仍败 → 回落原文 → 回落态裸编仍败 → fixloop 兜底：事件序 l2 < fixloop。"""
        eng = L2FlakyEngine(n_fail=3)
        with TestClient(_live_app(tmp_path, engine=eng)) as c:
            tid = upload_tex(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "partial", snap
            evs = task_events(c, tid)
            seqs = {
                e["type"]: int(e["seq"]) for e in evs if e["type"] in ("l2", "fixloop")
            }
            assert "l2" in seqs
            assert "fixloop" in seqs
            assert seqs["l2"] < seqs["fixloop"]
            l2_data = next(
                e["data"]
                for e in evs
                if e["type"] == "l2" and e["data"].get("phase") == "done"
            )
            assert l2_data["retranslated"]
            # 重译后仍被点名 → 回落原文落库
            rows = _chunks(c, tid)
            assert any(
                r["status"] == "fallback_orig" and r["error_code"] == "l2_reverted"
                for r in rows
            )

    def test_l2_fallback_verified_fixloop_off(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """fixloop 关闭条件路径：回落态仍补一次裸编验证（zh-src.zip 不装未验证树）。

        洞案（fallback_unverified 侦察）：``fixloop=false`` 时旧码回落后无任何
        验证即交付——pdf=重译态、zip=回落态三方分歧。新码回落后恒裸编。
        """
        monkeypatch.setenv("TEXLATE_NO_FIXLOOP", "1")
        eng = L2FlakyEngine(n_fail=2)
        with TestClient(_live_app(tmp_path, engine=eng)) as c:
            tid = upload_tex(c)["task_id"]
            snap = wait_terminal(c, tid)
            # fallback_orig 块存在 → 终态 partial（降级交付语义，非 done）
            assert snap["status"] == "partial", snap
            evs = task_events(c, tid)
            l2_data = next(
                e["data"]
                for e in evs
                if e["type"] == "l2" and e["data"].get("phase") == "done"
            )
            # 回落确实发生（done 帧 fallback 计数）+ 回落态裸编判定入账（report 全量键）
            assert l2_data["fallback"]
            assert l2_data["report"]["fallback_verdict"] == "clean"
            assert "fallback_unverified" not in l2_data["report"]
            # 首编 + 重译态重编 + 回落态裸编 = build-zh 同 wdir 共 3 次
            n_work = sum(1 for call in eng.calls if "build-zh" in call["wdir"])
            assert n_work == 3  # noqa: PLR2004 -- 首编+重译重编+回落裸编
            rows = _chunks(c, tid)
            assert any(
                r["status"] == "fallback_orig" and r["error_code"] == "l2_reverted"
                for r in rows
            )

    def test_l2_disabled_by_env(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``TEXLATE_NO_L2=1`` → 无 l2 事件，fixloop 直接兜底。"""
        monkeypatch.setenv("TEXLATE_NO_L2", "1")
        eng = L2FlakyEngine(n_fail=2)
        with TestClient(_live_app(tmp_path, engine=eng)) as c:
            tid = upload_tex(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "done", snap
            evs = task_events(c, tid)
            assert not [e for e in evs if e["type"] == "l2"]
            assert [e for e in evs if e["type"] == "fixloop"]
            done = next(e for e in evs if e["type"] == "done")
            assert done["data"]["stats"]["l2"]["enabled"] is False


class TestEnvJudge:
    """``TEXLATE_ENV_JUDGE``：静态表外 env 块 LLM 可译性判定。"""

    def test_env_judge_reverts_unknown_env(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """判 False → 块出 splice 保原文 + chunks 落 fallback_orig/env_judge。"""
        monkeypatch.setenv("TEXLATE_ENV_JUDGE", "1")
        translator = EnvJudgeNoTranslator()
        with TestClient(_live_app(tmp_path, translator=translator)) as c:
            tid = upload_tex(c, ENV_TEX)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "partial", snap
            rows = _chunks(c, tid)
            assert any(
                r["status"] == "fallback_orig" and r["error_code"] == "env_judge"
                for r in rows
            )
            assert any(
                "should be translated" in call["system"] for call in translator.calls
            )
            # zh/main.tex 里该块保留英文原文
            zh = tmp_path / "data" / "tasks" / tid / "zh" / "main.tex"
            assert "inside a custom environment" in zh.read_text(encoding="utf-8")

    def test_env_judge_off_by_default(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """缺省关：未知 env 块照常进 splice，不问 judge。"""
        translator = MockTranslator()
        with TestClient(_live_app(tmp_path, translator=translator)) as c:
            tid = upload_tex(c, ENV_TEX)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "done", snap
            assert not any(
                "should be translated" in call["system"] for call in translator.calls
            )
            assert not [r for r in _chunks(c, tid) if r["error_code"] == "env_judge"]


class TestCompileHoles:
    """T6 编译段洞：哨兵 resume / splice-done 序 / interrupted done / fresh stage。"""

    def test_compile_done_sentinel_resume(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """interrupted resume：``.compile-done`` + zh_pdf 在 → 不重编。"""
        eng = FakeEngine()
        with TestClient(_live_app(tmp_path, engine=eng)) as c:
            tid = upload_tex(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "done"
            n_calls = len(eng.calls)
            assert n_calls >= 1
            zh = tmp_path / "data" / "tasks" / tid / "zh"
            # 哨兵载荷=终态 verdict——FakeEngine 净 log 即 clean
            assert (zh / ".compile-done").read_text(encoding="utf-8") == "clean"

            # 模拟崩溃恢复留下的 interrupted（recover_startup 形态）
            def _flip(store: Store) -> None:
                store.conn.execute(
                    "UPDATE tasks SET status='interrupted' WHERE id=?", (tid,)
                )
                store.conn.commit()

            store_call(c, _flip, c.app.state.store)
            r = c.post(f"/api/task/{tid}/retry", json={})
            assert r.status_code == HTTPStatus.ACCEPTED, r.text
            snap = wait_terminal(c, tid)
            assert snap["status"] == "done"
            # en/zh 两侧都没重编（en 走 _has_pdf，zh 走 .compile-done）
            assert len(eng.calls) == n_calls

    def test_compile_done_sentinel_fail_resume(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """c32920 实证：verdict=fail 的死层 pdf 曾被空哨兵 resume 计 ok→done。

        哨兵载荷=终态 verdict——fail 件 resume 落 partial（残件照交付但
        不洗绿），且哨兵臂短路不触发重编。
        """
        eng = FakeEngine()
        with TestClient(_live_app(tmp_path, engine=eng)) as c:
            tid = upload_tex(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "done"
            n_calls = len(eng.calls)
            sentinel = tmp_path / "data" / "tasks" / tid / "zh" / ".compile-done"
            sentinel.write_text("fail", encoding="utf-8")

            def _flip(store: Store) -> None:
                store.conn.execute(
                    "UPDATE tasks SET status='interrupted' WHERE id=?", (tid,)
                )
                store.conn.commit()

            store_call(c, _flip, c.app.state.store)
            r = c.post(f"/api/task/{tid}/retry", json={})
            assert r.status_code == HTTPStatus.ACCEPTED, r.text
            snap = wait_terminal(c, tid)
            assert snap["status"] == "partial"
            assert len(eng.calls) == n_calls

    def test_compile_done_verdict_roundtrip(self, tmp_path: Path) -> None:
        """哨兵载荷口径：verdict 三词回读；缺席/旧版空件/脏值 → None 走复测臂。"""
        zh = tmp_path / "zh"
        zh.mkdir()
        assert _compile_done_verdict(zh) is None
        _write_compile_done(zh, "partial")
        assert _compile_done_verdict(zh) == "partial"
        _write_compile_done(zh, "clean")
        assert _compile_done_verdict(zh) == "clean"
        (zh / ".compile-done").write_text("", encoding="utf-8")
        assert _compile_done_verdict(zh) is None
        (zh / ".compile-done").write_text("bogus", encoding="utf-8")
        assert _compile_done_verdict(zh) is None

    def test_splice_done_written_after_zip(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``_zip_zh`` 抛错时 ``.splice-done`` 不得已写——否则 resume 永缺 zip。"""
        calls = {"n": 0}
        orig = PipelineWorker._zip_zh  # noqa: SLF001 -- 装配面即被测对象

        def boom(self: PipelineWorker, ctx: object) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                msg = "zip boom"
                raise RuntimeError(msg)
            orig(self, ctx)  # type: ignore[arg-type]

        monkeypatch.setattr(PipelineWorker, "_zip_zh", boom)
        with TestClient(_live_app(tmp_path)) as c:
            tid = upload_tex(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "fault"
            zh = tmp_path / "data" / "tasks" / tid / "zh"
            assert not (zh / ".splice-done").exists()
            r = c.post(f"/api/task/{tid}/retry", json={})
            assert r.status_code == HTTPStatus.ACCEPTED, r.text
            snap = wait_terminal(c, tid)
            assert snap["status"] == "done"
            assert (zh / ".splice-done").exists()
            rec = store_call(c, c.app.state.store.file_record, tid, "zh_src_zip")
            assert rec is not None
            assert rec["bytes"]

    def test_interrupted_emits_done(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002,
    ) -> None:
        """worker 任务被 cancel → interrupted 终态必须补 done 事件。

        直驱 ``worker.run``（不走 TaskRunner）：cancel 落在 translating
        段内，``run()`` 的 CancelledError 臂把任务推入 interrupted 并
        发 done——终态一致性给 SSE reader/等待者收尾。
        """
        store = Store(tmp_path / "x.db")
        store.open()
        bus = EventBus(store)
        worker = PipelineWorker(
            store,
            bus,
            tmp_path / "data",
            translator_factory=lambda _ctx: _HangTranslator(),
            engine_factory=lambda _n: FakeEngine(),
        )
        tid = new_task_id()
        row = mk_task_row(store, task_id=tid, kind="upload_tex")
        root = tmp_path / "data" / "tasks" / tid
        (root / "upload").mkdir(parents=True)
        (root / "upload" / "main.tex").write_text(MINI_TEX, encoding="utf-8")
        ctx = TaskCtx(
            store=store,
            bus=bus,
            task_id=tid,
            row=row,
            secrets=Secrets(),
            root=root,
        )

        async def _drive() -> None:
            task = asyncio.create_task(worker.run(ctx))
            deadline = time.time() + 10
            while time.time() < deadline:
                await asyncio.sleep(0.05)
                if store.get(tid)["status"] == "translating":
                    break
            assert store.get(tid)["status"] == "translating"
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(_drive())
        row2 = store.get(tid)
        assert row2 is not None
        assert row2["status"] == "interrupted"
        done = [e for e in store.events_since(tid, 0) if e["type"] == "done"]
        assert done
        assert done[0]["data"]["status"] == "interrupted"

    def test_stream_returns_on_orphan_terminal(self, tmp_path: Path) -> None:
        """终态但无 done 事件（recover_startup 直改库）→ stream 不空挂。"""
        store = Store(tmp_path / "x.db")
        store.open()
        bus = EventBus(store)
        tid = new_task_id()
        mk_task_row(store, task_id=tid, kind="upload_tex")
        store.conn.execute("UPDATE tasks SET status='interrupted' WHERE id=?", (tid,))
        store.conn.commit()

        async def _drain() -> list[dict]:
            async with asyncio.timeout(5):
                return [ev async for ev in bus.stream(tid)]

        out = asyncio.run(_drain())
        assert out == []

    def test_fail_error_event_fresh_stage(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """``_fail`` 的 error 事件 stage 取库内现值（非入队快照的 None）。"""
        with TestClient(_live_app(tmp_path, engine=_BangEngine())) as c:
            tid = upload_tex(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "fault"
            assert snap["error"]["code"] == "internal"
            err_evs = [e for e in task_events(c, tid) if e["type"] == "error"]
            assert err_evs
            assert err_evs[0]["data"]["stage"] == "compiling"

    def test_dispatch_stop_no_deadlock(self, tmp_path: Path) -> None:
        """stop() cancel dispatcher 时,``await task`` 的 CancelledError 不得吞——
        否则循环回 ``queue.get()`` 死等,``await dispatcher`` 永久挂起。"""

        class _HangWorker:
            """run() 永久挂起——dispatcher ``await task`` 处吃双 cancel。"""

            def __init__(self, data_dir: Path) -> None:
                self.data_dir = data_dir

            async def run(self, ctx: TaskCtx) -> None:  # noqa: ARG002
                await asyncio.sleep(3600)

        async def _go() -> None:
            store = Store(tmp_path / "t.db")
            store.open()
            bus = EventBus(store)
            runner = TaskRunner(store, bus, _HangWorker(tmp_path))  # type: ignore[arg-type]
            runner.start()
            tid = new_task_id()
            mk_task_row(store, task_id=tid, kind="upload_tex")
            runner.enqueue(tid)
            deadline = time.time() + 5
            while runner._current is None and time.time() < deadline:  # noqa: SLF001, ASYNC110 -- 轮询 pickup,无事件可挂
                await asyncio.sleep(0.02)
            assert runner._current is not None, "dispatcher 未接单"  # noqa: SLF001
            await asyncio.wait_for(runner.stop(), timeout=5)
            assert runner._dispatcher is not None  # noqa: SLF001
            assert runner._dispatcher.done()  # noqa: SLF001

        asyncio.run(_go())
