"""§3.2/§3.3/§3.4 store 层：状态机守卫、启动恢复、cache_key 索引、事件重放。"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

import pytest

from texlate.server.store import (
    Store,
    StoreError,
    TransitionError,
    new_task_id,
    valid_task_id,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_TASK_ID_LEN = 18  # "t_" + 16 hex


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    """内存级 tmp 库；非 autouse。"""
    s = Store(tmp_path / "t.db")
    s.open()
    yield s
    s.close()


def _mk(store: Store, **kw: Any) -> dict:  # noqa: ANN401 -- 建行参数透传
    kw.setdefault("task_id", new_task_id())
    kw.setdefault("kind", "arxiv")
    kw.setdefault("target_lang", "zh-CN")
    kw.setdefault("model", "m")
    return store.create_task(**kw)


class TestTaskId:
    def test_shape(self) -> None:
        tid = new_task_id()
        assert tid.startswith("t_")
        assert len(tid) == _TASK_ID_LEN
        assert valid_task_id(tid)

    def test_rejects(self) -> None:
        assert not valid_task_id("")
        assert not valid_task_id("t_")  # 长度不够
        assert not valid_task_id("t_" + "z" * 16)  # 非 hex
        assert not valid_task_id("x_" + "0" * 16)
        assert not valid_task_id("t_../etc/passwd0")


class TestStateMachine:
    def test_create_defaults(self, store: Store) -> None:
        row = _mk(store)
        assert row["status"] == "queued"
        assert row["auth_source"] == "settings"
        assert row["tenant"] == "local"

    def test_cancel_active_ok(self, store: Store) -> None:
        row = _mk(store)
        out = store.transition(row["id"], "cancelled")
        assert out["status"] == "cancelled"

    @pytest.mark.parametrize(
        "src", ["fault", "partial", "cancelled", "interrupted", "needs_auth"]
    )
    def test_retry_from_terminal(self, store: Store, src: str) -> None:
        row = _mk(store)
        store.transition(row["id"], src, force=True)
        out = store.transition(row["id"], "queued")
        assert out["status"] == "queued"

    def test_retry_from_done_rejected(self, store: Store) -> None:
        row = _mk(store)
        store.transition(row["id"], "done", force=True)
        with pytest.raises(TransitionError):
            store.transition(row["id"], "queued")

    def test_cancel_terminal_rejected(self, store: Store) -> None:
        row = _mk(store)
        store.transition(row["id"], "done", force=True)
        with pytest.raises(TransitionError):
            store.transition(row["id"], "cancelled")

    def test_forward_needs_force(self, store: Store) -> None:
        row = _mk(store)
        with pytest.raises(TransitionError):
            store.transition(row["id"], "translating")
        out = store.transition(row["id"], "translating", force=True)
        assert out["status"] == "translating"

    def test_missing_task(self, store: Store) -> None:
        with pytest.raises(StoreError):
            store.transition("t_" + "0" * 16, "cancelled")

    def test_queued_clears_error(self, store: Store) -> None:
        row = _mk(store)
        store.transition(row["id"], "fault", force=True, error={"code": "parse"})
        out = store.transition(row["id"], "queued")
        assert out["error_json"] is None
        assert out["finished_at"] is None


class TestRecoverStartup:
    def test_active_to_interrupted(self, store: Store) -> None:
        row = _mk(store)
        store.transition(row["id"], "translating", force=True)
        out = store.recover_startup()
        assert out == {"interrupted": 1, "needs_auth": 0}
        assert store.get(row["id"])["status"] == "interrupted"

    def test_header_source_to_needs_auth(self, store: Store) -> None:
        row = _mk(store, auth_source="header")
        store.transition(row["id"], "compiling", force=True)
        out = store.recover_startup()
        assert out == {"interrupted": 0, "needs_auth": 1}
        assert store.get(row["id"])["status"] == "needs_auth"

    def test_queued_untouched(self, store: Store) -> None:
        row = _mk(store)
        store.recover_startup()
        assert store.get(row["id"])["status"] == "queued"


class TestCacheKey:
    def test_unique_while_active(self, store: Store) -> None:
        _mk(store, cache_key="ck1")
        with pytest.raises(sqlite3.IntegrityError):
            _mk(store, cache_key="ck1")

    def test_done_frees_key(self, store: Store) -> None:
        row = _mk(store, cache_key="ck2")
        store.transition(row["id"], "done", force=True)
        _mk(store, cache_key="ck2")  # 不撞

    def test_find_active_and_reusable(self, store: Store) -> None:
        row = _mk(store, cache_key="ck3")
        assert store.find_active_by_cache_key("ck3")["id"] == row["id"]
        assert store.find_reusable("ck3") is None
        store.transition(row["id"], "done", force=True)
        assert store.find_active_by_cache_key("ck3") is None
        assert store.find_reusable("ck3")["id"] == row["id"]


def _chunk(seq: int) -> dict:
    return {
        "seq": seq,
        "chunk_id": f"c{seq}",
        "src_file": "a.tex",
        "byte_start": seq,
        "byte_end": seq + 1,
        "kind": "text",
        "src_text": f"t{seq}",
    }


class TestChunks:
    def test_insert_and_counts(self, store: Store) -> None:
        row = _mk(store)
        store.insert_chunks(row["id"], [_chunk(0), _chunk(1)])
        assert store.has_chunks(row["id"])
        counts = store.chunk_counts(row["id"])
        assert counts == {"total": 2, "done": 0, "cached": 0, "failed": 0}

    def test_flush_batch_counters(self, store: Store) -> None:
        row = _mk(store)
        store.insert_chunks(row["id"], [_chunk(i) for i in range(3)])
        store.flush_chunk_batch(
            row["id"],
            [
                ("c0", {"status": "ok", "translation": "译0", "attempts": 1}),
                ("c1", {"status": "fallback_orig", "attempts": 1}),
                ("c2", {"status": "failed", "error_code": "validate"}),
            ],
            [("k1", "译0", "m", "zh-CN")],
            {"total": 3, "done": 3, "cached": 1, "failed": 2, "tokens": 7},
        )
        counts = store.chunk_counts(row["id"])
        # done = 已处理（ok+fallback_orig+failed）；failed = fallback_orig+failed
        assert counts == {"total": 3, "done": 3, "cached": 0, "failed": 2}
        out = store.get(row["id"])
        assert out["done_chunks"] == 3  # noqa: PLR2004 - 三块样本
        assert out["failed_chunks"] == 2  # noqa: PLR2004 - fallback+failed
        assert out["cached_chunks"] == 1
        assert out["tokens"] == 7  # noqa: PLR2004 - flush 写入 token 合计
        chunks = {c["chunk_id"]: c for c in store.all_chunks(row["id"])}
        assert chunks["c0"]["translation"] == "译0"
        assert chunks["c1"]["status"] == "fallback_orig"
        assert chunks["c2"]["error_code"] == "validate"
        assert store.cache_get("k1") == "译0"


class TestEvents:
    def test_seq_monotonic(self, store: Store) -> None:
        row = _mk(store)
        s1 = store.append_event(row["id"], "stage", {"stage": "parsing"})
        s2 = store.append_event(row["id"], "chunk", {"done": 1})
        assert s1 == 1
        assert s2 == s1 + 1
        assert store.last_seq(row["id"]) == s2

    def test_events_since(self, store: Store) -> None:
        row = _mk(store)
        store.append_event(row["id"], "a", {})
        store.append_event(row["id"], "b", {"x": 1})
        evs = store.events_since(row["id"], 1)
        assert [e["type"] for e in evs] == ["b"]
        assert evs[0]["data"] == {"x": 1}


class TestSnapshot:
    def test_schema(self, store: Store) -> None:
        row = _mk(store, title="T", arxiv_id="2401.00001")
        snap = store.snapshot(row["id"], artifacts={"zh_pdf": "/x"})
        assert snap["task_id"] == row["id"]
        assert snap["status"] == "queued"
        assert snap["artifacts"] == {"zh_pdf": "/x"}
        assert snap["counters"]["total"] == 0
        assert snap["error"] is None
        assert snap["last_seq"] == 0
