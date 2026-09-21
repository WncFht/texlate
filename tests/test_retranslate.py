"""单块重译 job：``enqueue_retranslate`` → chunks.zh 更新 + dual.json 重写 + 失败不 fault。"""

from __future__ import annotations

import json
import time
from functools import partial
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from conftest import (
    FakeEngine,
    make_app,
    mk_task_row,
    upload_tex,
    wait_terminal,
)
from starlette.testclient import TestClient

from texlate.server.store import Store
from texlate.xlat.client import ChatError
from texlate.xlat.pipeline import MockTranslator

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

#: 重译标记串——MockTranslator(zh=…) 散文段替换桩，与初译「这是译文」可区分
_MARK = "重译标记"


class _MarkedTranslator:
    """``[compile_error]`` 语境切标记桩——主链初译与重译产出可区分。"""

    def __init__(self) -> None:
        self.plain = MockTranslator()
        self.marked = MockTranslator(zh=_MARK)

    async def translate(self, *, user: str, **kw: object) -> str:
        arm = self.marked if "[compile_error]" in user else self.plain
        return await arm.translate(user=user, **kw)


class _BoomTranslator:
    """``[compile_error]`` 语境抛传输错——``retranslate_chunk`` 归 ``None`` 臂。"""

    def __init__(self) -> None:
        self.plain = MockTranslator()

    async def translate(self, *, user: str, **kw: object) -> str:
        if "[compile_error]" in user:
            msg = "simulated transport failure"
            raise ChatError(msg)
        return await self.plain.translate(user=user, **kw)


def _store(db: Path) -> Store:
    """worker loop 线程外的只读观测口（conn 线程亲和，本线程另开实例）。"""
    s2 = Store(db)
    s2.open()
    return s2


def _wait_event(db: Path, tid: str, needle: str, timeout: float = 20.0) -> dict:
    """轮询 task_events 直到含 ``needle`` 的 log 行出现（job 终态观测面）。"""
    deadline = time.monotonic() + timeout
    evs: list[dict] = []
    while time.monotonic() < deadline:
        s2 = _store(db)
        try:
            evs = s2.events_since(tid, 0)
        finally:
            s2.close()
        hit = next(
            (e for e in evs if e["type"] == "log" and needle in str(e["data"])),
            None,
        )
        if hit is not None:
            return hit
        time.sleep(0.05)
    pytest.fail(f"no log event containing {needle!r}: {evs[-3:]}")


def _chunk(db: Path, tid: str, seq: int) -> dict:
    s2 = _store(db)
    try:
        return next(r for r in s2.all_chunks(tid) if int(r["seq"]) == seq)
    finally:
        s2.close()


def _retranslate_keeps_chunk(
    tmp_path: Path,
    *,
    needle: str,
    factory: Callable[[object], object] | None = None,
) -> tuple[FakeEngine, Path, str, dict, dict]:
    """失败臂公共流：upload→done→enqueue→等 ``needle`` 事件→原译保留/引擎零触碰。

    ``factory=None`` 即不注入 ``translator_factory``（无 BYOK 臂）；
    返回 ``(engine, db, tid, before, after)`` 供各钉补断言。
    """
    engine = FakeEngine()
    overrides: dict[str, object] = {
        "start_worker": True,
        "engine_factory": lambda _name: engine,
    }
    if factory is not None:
        overrides["translator_factory"] = factory
    app = make_app(tmp_path, **overrides)
    with TestClient(app) as c:
        tid = upload_tex(c)["task_id"]
        assert wait_terminal(c, tid)["status"] == "done"
        db = tmp_path / "data" / "texlate.db"
        before = _chunk(db, tid, 0)
        calls0 = len(engine.calls)
        c.portal.call(partial(c.app.state.runner.enqueue_retranslate, tid, 0))
        _wait_event(db, tid, needle)
        after = _chunk(db, tid, 0)
    assert after["translation"] == before["translation"]
    # 重译失败不重编——zh.pdf/产物面零触碰
    assert len(engine.calls) == calls0
    return engine, db, tid, before, after


class TestRetranslateJob:
    """``runner.enqueue_retranslate`` 串行域 job 的端到端口径。"""

    @pytest.fixture
    def retr_client(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> Iterator[tuple[TestClient, FakeEngine, Path]]:
        """MarkedTranslator + FakeEngine 的活 worker app；产出 (client, engine, db)。"""
        engine = FakeEngine()
        app = make_app(
            tmp_path,
            start_worker=True,
            translator_factory=lambda _ctx: _MarkedTranslator(),
            engine_factory=lambda _name: engine,
        )
        with TestClient(app) as c:
            yield c, engine, tmp_path / "data" / "texlate.db"

    def test_retranslate_updates_zh_dual_and_pdf(
        self,
        retr_client: tuple[TestClient, FakeEngine, Path],
    ) -> None:
        """重译落地：chunks.zh 换标记译 + zh/ 源树 + dual.json + zh.pdf 重编。"""
        c, engine, db = retr_client
        tid = upload_tex(c)["task_id"]
        snap = wait_terminal(c, tid)
        assert snap["status"] == "done"
        before = _chunk(db, tid, 0)
        assert _MARK not in str(before["translation"])
        calls0 = len(engine.calls)
        c.portal.call(partial(c.app.state.runner.enqueue_retranslate, tid, 0))
        _wait_event(db, tid, "chunk #0 已重译")
        after = _chunk(db, tid, 0)
        assert _MARK in str(after["translation"])
        assert after["status"] == "ok"
        assert after["error_code"] in (None, "")
        # 任务本体不迁终态——重译是终态后的旁路 job
        s2 = _store(db)
        try:
            row = s2.get(tid)
            assert row is not None
            assert row["status"] == "done"
            files = s2.files(tid)
        finally:
            s2.close()
        assert "zh_pdf" in files
        assert "dual_json" in files
        # zh.pdf 重编走过（FakeEngine 一记）+ zh 源树 resplice 出标记译
        assert len(engine.calls) > calls0
        root = c.app.state.data_dir / "tasks" / tid
        zh_blobs = "\n".join(
            f.read_text(encoding="utf-8", errors="replace")
            for f in (root / "zh").rglob("*.tex")
        )
        assert _MARK in zh_blobs
        dual = json.loads((root / "dual.json").read_text(encoding="utf-8"))
        zh0 = next(ch for ch in dual["chunks"] if int(ch["seq"]) == 0)
        assert _MARK in str(zh0["zh"])

    def test_transport_failure_keeps_translation_and_status(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """传输崩 → error_code=provider_error 记名，原译/终态原样保留。"""
        _eng, db, tid, before, after = _retranslate_keeps_chunk(
            tmp_path,
            needle="传输层失败",
            factory=lambda _ctx: _BoomTranslator(),
        )
        assert after["status"] == before["status"]
        assert after["error_code"] == "provider_error"
        # 任务本体不迁终态——重译失败是终态后的旁路 job
        s2 = _store(db)
        try:
            row = s2.get(tid)
        finally:
            s2.close()
        assert row is not None
        assert row["status"] == "done"

    def test_no_key_skips_mock_overwrite(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """无 BYOK key + 无注入厂 → 拒绝落 MockTranslator 占位译文（闸守真译）。"""
        _retranslate_keeps_chunk(tmp_path, needle="无 BYOK")


class TestEnqueueGates:
    """``enqueue_retranslate`` 闸与路由同口径：KeyError/ValueError 分流。"""

    def test_gates(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        engine = FakeEngine()
        app = make_app(
            tmp_path,
            start_worker=True,
            translator_factory=lambda _ctx: MockTranslator(),
            engine_factory=lambda _name: engine,
        )
        with TestClient(app) as c:
            runner = c.app.state.runner
            store = c.app.state.store
            with pytest.raises(KeyError):
                c.portal.call(partial(runner.enqueue_retranslate, "nope", 0))
            # ACTIVE 任务（queued）→ ValueError
            tid = c.portal.call(partial(mk_task_row, store))["id"]
            with pytest.raises(ValueError, match="not retranslatable"):
                c.portal.call(partial(runner.enqueue_retranslate, tid, 0))
            # done 但无 zh splice 树 → ValueError
            c.portal.call(partial(store.transition, tid, "done", force=True))
            with pytest.raises(ValueError, match="spliced zh"):
                c.portal.call(partial(runner.enqueue_retranslate, tid, 0))
            # done + splice + 无该 seq → ValueError
            zh = c.app.state.data_dir / "tasks" / tid / "zh"
            zh.mkdir(parents=True)
            (zh / ".splice-done").touch()
            with pytest.raises(ValueError, match="no chunk"):
                c.portal.call(partial(runner.enqueue_retranslate, tid, 9))
