"""§3.2/§3.3/§3.4 store 层：状态机守卫、启动恢复、cache_key 索引、事件重放。"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest
from conftest import mk_task_row

from texlate.server.store import (
    ERROR_CODES,
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
        row = mk_task_row(store)
        assert row["status"] == "queued"
        assert row["auth_source"] == "none"
        assert row["tenant"] == "local"

    def test_cancel_active_ok(self, store: Store) -> None:
        row = mk_task_row(store)
        out = store.transition(row["id"], "cancelled")
        assert out["status"] == "cancelled"

    @pytest.mark.parametrize(
        "src", ["fault", "partial", "cancelled", "interrupted", "needs_auth"]
    )
    def test_retry_from_terminal(self, store: Store, src: str) -> None:
        row = mk_task_row(store)
        store.transition(row["id"], src, force=True)
        out = store.transition(row["id"], "queued")
        assert out["status"] == "queued"

    def test_retry_from_done_rejected(self, store: Store) -> None:
        row = mk_task_row(store)
        store.transition(row["id"], "done", force=True)
        with pytest.raises(TransitionError):
            store.transition(row["id"], "queued")

    def test_cancel_terminal_rejected(self, store: Store) -> None:
        row = mk_task_row(store)
        store.transition(row["id"], "done", force=True)
        with pytest.raises(TransitionError):
            store.transition(row["id"], "cancelled")

    def test_forward_needs_force(self, store: Store) -> None:
        row = mk_task_row(store)
        with pytest.raises(TransitionError):
            store.transition(row["id"], "translating")
        out = store.transition(row["id"], "translating", force=True)
        assert out["status"] == "translating"

    def test_missing_task(self, store: Store) -> None:
        with pytest.raises(StoreError):
            store.transition("t_" + "0" * 16, "cancelled")

    def test_queued_clears_error(self, store: Store) -> None:
        row = mk_task_row(store)
        store.transition(row["id"], "fault", force=True, error={"code": "parse"})
        out = store.transition(row["id"], "queued")
        assert out["error_json"] is None
        assert out["finished_at"] is None


class TestRecoverStartup:
    def test_active_to_interrupted(self, store: Store) -> None:
        row = mk_task_row(store)
        store.transition(row["id"], "translating", force=True)
        out = store.recover_startup()
        assert out == {"interrupted": 1, "needs_auth": 0}
        assert store.get(row["id"])["status"] == "interrupted"

    def test_header_source_to_needs_auth(self, store: Store) -> None:
        row = mk_task_row(store, auth_source="header")
        store.transition(row["id"], "compiling", force=True)
        out = store.recover_startup()
        assert out == {"interrupted": 0, "needs_auth": 1}
        assert store.get(row["id"])["status"] == "needs_auth"

    def test_queued_untouched(self, store: Store) -> None:
        row = mk_task_row(store)
        store.recover_startup()
        assert store.get(row["id"])["status"] == "queued"


class TestCacheKey:
    def test_unique_while_active(self, store: Store) -> None:
        mk_task_row(store, cache_key="ck1")
        with pytest.raises(sqlite3.IntegrityError):
            mk_task_row(store, cache_key="ck1")

    def test_done_frees_key(self, store: Store) -> None:
        row = mk_task_row(store, cache_key="ck2")
        store.transition(row["id"], "done", force=True)
        mk_task_row(store, cache_key="ck2")  # 不撞

    def test_find_active_and_reusable(self, store: Store) -> None:
        row = mk_task_row(store, cache_key="ck3")
        assert store.find_active_by_cache_key("ck3")["id"] == row["id"]
        assert store.find_reusable("ck3") is None
        store.transition(row["id"], "done", force=True)
        assert store.find_active_by_cache_key("ck3") is None
        assert store.find_reusable("ck3")["id"] == row["id"]

    def test_find_reusable_excludes_partial(self, store: Store) -> None:
        """partial 是降级交付不克隆——毒传播先例 t_f74894ebc691aaf4。"""
        row = mk_task_row(store, cache_key="ckp")
        store.transition(row["id"], "partial", force=True)
        assert store.find_reusable("ckp") is None
        store.transition(row["id"], "done", force=True)
        assert store.find_reusable("ckp")["id"] == row["id"]


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


def _legacy_store(tmp_path: Path, ddl: str) -> Store:
    """老 schema 库造件：``old.db`` 铺旧 DDL → ``Store.open()`` 迁移臂接管。"""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(ddl)
    conn.commit()
    conn.close()
    s = Store(db)
    s.open()
    return s


class TestChunks:
    def test_insert_and_counts(self, store: Store) -> None:
        row = mk_task_row(store)
        store.insert_chunks(row["id"], [_chunk(0), _chunk(1)])
        assert store.has_chunks(row["id"])
        counts = store.chunk_counts(row["id"])
        assert counts == {"total": 2, "done": 0, "failed": 0}

    def test_flush_batch_counters(self, store: Store) -> None:
        row = mk_task_row(store)
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
        assert counts == {"total": 3, "done": 3, "failed": 2}
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

    def test_warnings_persisted(self, store: Store) -> None:
        """T3：chunk warnings 落 chunks.warnings（JSON 列）。"""
        row = mk_task_row(store)
        store.insert_chunks(row["id"], [_chunk(0)])
        store.flush_chunk_batch(
            row["id"],
            [
                (
                    "c0",
                    {
                        "status": "fallback_orig",
                        "warnings": json.dumps(
                            ["slots unanswered"], ensure_ascii=False
                        ),
                        "attempts": 3,
                    },
                )
            ],
            [],
            {"total": 1, "done": 1, "failed": 1},
        )
        chunk = store.all_chunks(row["id"])[0]
        assert json.loads(chunk["warnings"]) == ["slots unanswered"]

    def test_warnings_column_migration(self, tmp_path: Path) -> None:
        """老库（chunks 无 warnings 列）→ open() 探测补列（幂等）。"""
        s = _legacy_store(
            tmp_path,
            "CREATE TABLE chunks ("
            " task_id TEXT NOT NULL, seq INTEGER NOT NULL,"
            " chunk_id TEXT NOT NULL, status TEXT DEFAULT 'pending',"
            " PRIMARY KEY (task_id, chunk_id));",
        )
        try:
            cols = {str(r["name"]) for r in s.conn.execute("PRAGMA table_info(chunks)")}
            assert "warnings" in cols
            s.conn.execute(
                "INSERT INTO chunks (task_id, seq, chunk_id, warnings)"
                " VALUES ('t_x', 0, 'c0', ?)",
                (json.dumps(["w"]),),
            )
            got = s.conn.execute(
                "SELECT warnings FROM chunks WHERE chunk_id = 'c0'"
            ).fetchone()
            assert json.loads(got["warnings"]) == ["w"]
        finally:
            s.close()


class TestErrorCodes:
    def test_inject_reject_listed(self) -> None:
        """T7b：inject_reject 是合法错误码（inject 拒翻 → fault 落它）。"""
        assert "inject_reject" in ERROR_CODES


class TestIdempotencyKey:
    def test_create_extracts_column(self, store: Store) -> None:
        """options.idempotency_key 建行时提升为一等列（find_by_idempotency 走列查）。"""
        row = mk_task_row(store, options={"idempotency_key": "k-new"})
        assert row["idempotency_key"] == "k-new"
        assert store.find_by_idempotency("local", "k-new")["id"] == row["id"]
        assert store.find_by_idempotency("local", "nope") is None
        assert store.find_by_idempotency("other", "k-new") is None  # 租户隔离
        assert mk_task_row(store)["idempotency_key"] is None

    def test_column_migration_backfill(self, tmp_path: Path) -> None:
        """老库（tasks 无 idempotency_key 列）→ open() 补列 + options_json 回填。"""
        s = _legacy_store(
            tmp_path,
            "CREATE TABLE tasks ("
            " id TEXT PRIMARY KEY, kind TEXT NOT NULL,"
            " status TEXT NOT NULL DEFAULT 'queued',"
            " stage TEXT, progress INTEGER NOT NULL DEFAULT 0,"
            " message TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',"
            " arxiv_id TEXT, source_name TEXT NOT NULL DEFAULT '',"
            " main_tex TEXT NOT NULL DEFAULT '', target_lang TEXT NOT NULL,"
            " model TEXT NOT NULL, config_json TEXT NOT NULL DEFAULT '{}',"
            " options_json TEXT NOT NULL DEFAULT '{}',"
            " auth_source TEXT NOT NULL DEFAULT 'settings',"
            " tenant TEXT NOT NULL DEFAULT 'local', cache_key TEXT,"
            " total_chunks INTEGER NOT NULL DEFAULT 0,"
            " done_chunks INTEGER NOT NULL DEFAULT 0,"
            " cached_chunks INTEGER NOT NULL DEFAULT 0,"
            " failed_chunks INTEGER NOT NULL DEFAULT 0,"
            " tokens INTEGER NOT NULL DEFAULT 0, error_json TEXT,"
            " worker_id TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,"
            " started_at REAL, finished_at REAL);"
            "INSERT INTO tasks (id, kind, target_lang, model, options_json,"
            " created_at, updated_at) VALUES ('t_old', 'arxiv', 'zh-CN', 'm',"
            ' \'{"idempotency_key":"k-old"}\', 1, 1);',
        )
        try:
            cols = {str(r["name"]) for r in s.conn.execute("PRAGMA table_info(tasks)")}
            assert "idempotency_key" in cols
            hit = s.find_by_idempotency("local", "k-old")
            assert hit is not None
            assert hit["id"] == "t_old"
        finally:
            s.close()


class TestHotQueryPlans:
    """钉查询计划——热查询退成全表扫时索引形同虚设。"""

    def _plan(self, store: Store, sql: str, params: tuple) -> list[str]:
        return [
            str(r[3]) for r in store.conn.execute(f"EXPLAIN QUERY PLAN {sql}", params)
        ]

    def test_idem_uses_composite(self, store: Store) -> None:
        plan = self._plan(
            store,
            "SELECT * FROM tasks WHERE tenant = ? AND idempotency_key = ?"
            " ORDER BY created_at DESC LIMIT 1",
            ("local", "k"),
        )
        assert any("idx_tasks_idem" in p for p in plan), plan

    def test_cachekey_uses_partial(self, store: Store) -> None:
        plan = self._plan(
            store,
            "SELECT * FROM tasks WHERE cache_key = ?"
            " AND status IN ('done','partial') ORDER BY created_at DESC LIMIT 1",
            ("ck",),
        )
        assert any("idx_tasks_cachekey" in p for p in plan), plan


class TestUsage:
    def test_record_and_snapshot(self, store: Store) -> None:
        """T4：record_usage upsert 累加 + snapshot 带 usage。"""
        row = mk_task_row(store)
        assert store.usage_for(row["id"]) is None
        snap = store.snapshot(row["id"], artifacts={})
        assert "usage" not in snap
        store.record_usage(
            row["id"],
            model="m1",
            calls=2,
            prompt_tokens=100,
            completion_tokens=50,
            latency_s=1.5,
        )
        store.record_usage(
            row["id"],
            model="m1",
            calls=1,
            prompt_tokens=10,
            completion_tokens=5,
            latency_s=0.5,
        )
        u = store.usage_for(row["id"])
        assert u is not None
        assert u["calls"] == 3  # noqa: PLR2004 -- 2+1 upsert 累加
        assert u["prompt_tokens"] == 110  # noqa: PLR2004
        assert u["completion_tokens"] == 55  # noqa: PLR2004
        assert u["latency_s"] == pytest.approx(2.0)
        snap = store.snapshot(row["id"], artifacts={})
        assert snap["usage"]["calls"] == 3  # noqa: PLR2004


class TestEvents:
    def test_seq_monotonic(self, store: Store) -> None:
        row = mk_task_row(store)
        s1 = store.append_event(row["id"], "stage", {"stage": "parsing"})
        s2 = store.append_event(row["id"], "chunk", {"done": 1})
        assert s1 == 1
        assert s2 == s1 + 1
        assert store.last_seq(row["id"]) == s2

    def test_events_since(self, store: Store) -> None:
        row = mk_task_row(store)
        store.append_event(row["id"], "a", {})
        store.append_event(row["id"], "b", {"x": 1})
        evs = store.events_since(row["id"], 1)
        assert [e["type"] for e in evs] == ["b"]
        assert evs[0]["data"] == {"x": 1}


class TestSnapshot:
    def test_schema(self, store: Store) -> None:
        row = mk_task_row(store, title="T", arxiv_id="2401.00001")
        snap = store.snapshot(row["id"], artifacts={"zh_pdf": "/x"})
        assert snap["task_id"] == row["id"]
        assert snap["status"] == "queued"
        assert snap["artifacts"] == {"zh_pdf": "/x"}
        assert snap["counters"]["total"] == 0
        assert snap["error"] is None
        assert snap["last_seq"] == 0

    def test_warnings_replayed(self, store: Store) -> None:
        """snapshot.warnings 重放 task_events 的 warning 事件（非恒空）。"""
        row = mk_task_row(store)
        assert store.snapshot(row["id"], artifacts={})["warnings"] == []
        store.append_event(row["id"], "stage", {"stage": "translating"})
        store.append_event(
            row["id"], "warning", {"code": "chunks_failed", "message": "2 块回退原文"}
        )
        store.append_event(
            row["id"], "warning", {"code": "mock_translator", "message": "占位"}
        )
        snap = store.snapshot(row["id"], artifacts={})
        assert snap["warnings"] == [
            "[chunks_failed] 2 块回退原文",
            "[mock_translator] 占位",
        ]
        assert snap["last_seq"] == 3  # noqa: PLR2004 -- stage+warning×2
