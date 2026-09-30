"""审查修复钉板两轮合订（server store/settings/events 层契约）。

wave 1：``list_tasks_page``/``delete_task_guard`` 契约、``load`` 磁盘缓存、
``resolve_auth`` 跨槽闸、``recover_startup`` 终态清理、cache 命中聚合、
stale done 重放、``ERROR_CODES`` 名录。
wave 2：``task_ids``/``queued_rows``/``delete_chunks`` 裸 conn 收口、
``chunks_page`` 窄列分页 + limit 钳位、``append_event`` 对已删任务行静默
丢弃、retention 两段 GC、``EventBus.stream`` resync 缺口提示帧、
``SettingsStore.save`` 标量类型闸、``load()`` 深拷贝防污染、retention
设置字段、snapshot options 回显。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from conftest import mk_chunk_row, mk_task_row

from texlate.server.events import EventBus
from texlate.server.settings import (
    _CONNECTION_SLOTS,
    _FIELD_SPECS,
    _MODEL_PROBE_FIELDS,
    BYOK_FIELDS,
    SettingsStore,
    resolve_auth,
)
from texlate.server.store import (
    ACTIVE_STATUSES,
    ERROR_CODES,
    Store,
    new_task_id,
    row_json,
    slim_task_dir,
)
from texlate.server.store._common import _dir_size, _retention_drop_order
from texlate.server.worker import Secrets

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    s = Store(tmp_path / "t.db")
    s.open()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _no_model_probe(clean_env: pytest.MonkeyPatch) -> None:
    """save 内 /v1/models 探活关掉——测试不打网络。"""
    clean_env.setenv("TEXLATE_MODEL_PROBE", "0")


def _collect_stream(
    bus: EventBus, tid: str, n: int | None = None, last_event_id: int = 0
) -> list[dict[str, Any]]:
    """同步收 ``bus.stream`` 前 ``n`` 帧（``None`` = 排干到流终），5s 护栏。"""

    async def run() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        async for ev in bus.stream(tid, last_event_id=last_event_id):
            out.append(ev)
            if n is not None and len(out) >= n:
                break
        return out

    return asyncio.run(asyncio.wait_for(run(), 5))


def _seed_cache_row(conn: sqlite3.Connection, key: str = "k") -> None:
    """``translation_cache`` 单行种子——INSERT 字面量单源（命中计数测试前置）。"""
    conn.execute(
        "INSERT INTO translation_cache (key, translation, model,"
        " target_lang, created_at, last_hit_at) VALUES (?, 'v', 'm', 'l', 0, 0)",
        (key,),
    )
    conn.commit()


# ------------------------------------------------------------------ wave 1

#: tasks_list 序列化实际消费的列——list_tasks_page 必须全覆盖
_LIST_COLS = (
    "id",
    "kind",
    "status",
    "stage",
    "progress",
    "message",
    "title",
    "arxiv_id",
    "source_name",
    "target_lang",
    "model",
    "created_at",
    "updated_at",
    "total_chunks",
    "done_chunks",
    "cached_chunks",
    "failed_chunks",
    "tokens",
    "error_json",
    "last_seq",
)


class TestListTasksPage:
    def test_page_and_total(self, store: Store) -> None:
        tids = [mk_task_row(store)["id"] for _ in range(5)]
        # 显式钉 created_at 消除时钟分辨率并列（同 test_queued_rows_filters_and_orders
        # 手法）——并列下排序对账依赖 tiebreak 口径一致，钉死即与口径无关
        for i, tid in enumerate(tids):
            store.conn.execute(
                "UPDATE tasks SET created_at = ? WHERE id = ?", (100.0 + i, tid)
            )
        store.conn.commit()
        rows, total = store.list_tasks_page("local", limit=2, offset=0)
        assert total == 5  # noqa: PLR2004 -- 样本量
        assert len(rows) == 2  # noqa: PLR2004 -- page size
        ids = [r["id"] for r in rows]
        rows2, total2 = store.list_tasks_page("local", limit=2, offset=2)
        assert total2 == total
        assert not set(ids) & {r["id"] for r in rows2}
        # created_at 倒序与 _list_tasks_all（测试专用全量版）同口径
        all_rows, _ = store.list_tasks_page("local", limit=100)
        assert [r["id"] for r in all_rows] == [
            r["id"]
            for r in store._list_tasks_all("local")  # noqa: SLF001 -- 私有测试专用方法正是本测试对账对象
        ]

    def test_columns_cover_serializer(self, store: Store) -> None:
        """序列化消费的每个键都可从 Row 取到（缺列即 KeyError）。"""
        mk_task_row(store)
        rows, _ = store.list_tasks_page("local")
        (r,) = rows
        for col in _LIST_COLS:
            r[col]

    def test_tenant_isolation(self, store: Store) -> None:
        ta = mk_task_row(store, tenant="a")["id"]
        mk_task_row(store, tenant="b")
        rows, total = store.list_tasks_page("a")
        assert total == 1
        assert rows[0]["id"] == ta

    def test_last_seq_column(self, store: Store) -> None:
        """last_seq = 任务已落事件 seq 上限（无事件 0）——前端 refresh 守卫数据源。"""
        tid = mk_task_row(store)["id"]
        (r,) = store.list_tasks_page("local")[0]
        assert r["last_seq"] == 0
        store.append_event(tid, "stage", {"stage": "translating"})
        store.append_event(tid, "chunk", {"done": 1})
        (r,) = store.list_tasks_page("local")[0]
        assert r["last_seq"] == 2  # noqa: PLR2004 -- 两条事件后水位


class TestDeleteTaskGuard:
    def test_active_blocked(self, store: Store) -> None:
        row = mk_task_row(store)
        assert not store.delete_task_guard(row["id"], blocked=ACTIVE_STATUSES)
        assert store.get(row["id"]) is not None

    def test_terminal_deleted_cascade(self, store: Store) -> None:
        row = mk_task_row(store)
        store.transition(row["id"], "done", force=True)
        store.append_event(row["id"], "stage", {"stage": "parsing"})
        store.put_file(row["id"], "en_pdf", "en.pdf", size=3, sha256="x")
        assert store.delete_task_guard(row["id"], blocked=ACTIVE_STATUSES)
        assert store.get(row["id"]) is None
        assert store.events_since(row["id"], 0) == []
        assert store.files(row["id"]) == {}

    def test_missing_returns_false(self, store: Store) -> None:
        assert not store.delete_task_guard(new_task_id(), blocked=ACTIVE_STATUSES)

    def test_empty_blocked_unconditional(self, store: Store) -> None:
        row = mk_task_row(store)
        assert store.delete_task_guard(row["id"], blocked=frozenset())
        assert store.get(row["id"]) is None


_SETTINGS: dict[str, Any] = {
    "base_url": "http://localhost:3003",
    "model": "m-settings",
    "api_key": "sk-settings-1",
}


class TestCrossSlotAuth:
    """header 指了别的端点却不带 key → 部署方/本机凭证一律不外借。"""

    def test_foreign_base_url_anonymized(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("TEXLATE_API_KEY", "sk-env-7")
        ctx = resolve_auth(
            _SETTINGS,
            header_base_url="http://localhost:4000",
            salt="s",
        )
        assert ctx.api_key == ""
        assert ctx.source == "none"
        assert ctx.base_url == "http://localhost:4000"

    def test_same_slot_settings_key_flows(self, clean_env: pytest.MonkeyPatch) -> None:
        del clean_env
        # header 复指 settings 槽位（含尾斜杠形态）→ settings key 照走
        ctx = resolve_auth(
            _SETTINGS,
            header_base_url="http://localhost:3003/",
            salt="s",
        )
        assert (ctx.api_key, ctx.source) == ("sk-settings-1", "settings")

    def test_header_key_overrides_any_slot(self, clean_env: pytest.MonkeyPatch) -> None:
        del clean_env
        ctx = resolve_auth(
            _SETTINGS,
            header_key="sk-h",
            header_base_url="http://localhost:4000",
            salt="s",
        )
        assert (ctx.api_key, ctx.source) == ("sk-h", "header")

    def test_env_slot_flows_when_repeated(self, clean_env: pytest.MonkeyPatch) -> None:
        """header 复指 env 配置端点 → env key 是它自己槽位的凭证，放行。"""
        clean_env.setenv("TEXLATE_API_KEY", "sk-env-7")
        clean_env.setenv("TEXLATE_BASE_URL", "http://localhost:4000")
        bare = {"base_url": "http://localhost:3003", "model": "m", "api_key": ""}
        ctx = resolve_auth(bare, header_base_url="http://localhost:4000", salt="s")
        assert (ctx.api_key, ctx.source) == ("sk-env-7", "env")

    def test_settings_key_not_leaked_to_env_slot(
        self, clean_env: pytest.MonkeyPatch
    ) -> None:
        """settings key 属于 settings.base_url 槽——header 指 env 端点也不外借。"""
        clean_env.setenv("TEXLATE_API_KEY", "sk-env-7")
        clean_env.setenv("TEXLATE_BASE_URL", "http://localhost:4000")
        ctx = resolve_auth(_SETTINGS, header_base_url="http://localhost:4000", salt="s")
        assert (ctx.api_key, ctx.source) == ("sk-env-7", "env")

    def test_no_header_unchanged(self, clean_env: pytest.MonkeyPatch) -> None:
        """纯 settings / 纯 env 形态不受闸影响。"""
        clean_env.setenv("TEXLATE_API_KEY", "sk-env-7")
        assert resolve_auth(_SETTINGS, salt="s").api_key == "sk-settings-1"
        bare = {"base_url": "", "model": "", "api_key": ""}
        assert resolve_auth(bare, salt="s").api_key == "sk-env-7"


class TestByokFieldSpec:
    """``BYOK_FIELDS`` 单源钉板：请求头面/settings 槽键/探活字段集同由表派生。"""

    def test_wire_headers_and_attrs(self) -> None:
        assert [s.attr for s in BYOK_FIELDS] == [
            "api_key",
            "base_url",
            "model",
            "dialect",
        ]
        assert [s.header for s in BYOK_FIELDS] == [
            "x-texlate-key",
            "x-texlate-base-url",
            "x-texlate-model",
            "x-texlate-dialect",
        ]
        assert [s.settings_key for s in BYOK_FIELDS] == [
            "api_key",
            "base_url",
            "model",
            "dialect",
        ]

    def test_derived_field_sets(self) -> None:
        assert (
            frozenset({"api_key", "base_url", "model", "dialect", "clear_api_key"})
            == _MODEL_PROBE_FIELDS
        )
        assert _CONNECTION_SLOTS == ("api_key", "model", "dialect")

    def test_headers_map_drives_resolution(self, clean_env: pytest.MonkeyPatch) -> None:
        """``headers`` 头面按 spec 查名且覆盖 ``header_*`` kwarg。"""
        del clean_env
        ctx = resolve_auth(
            _SETTINGS,
            header_key="sk-kwarg",
            headers={"x-texlate-key": "sk-h", "x-texlate-model": "m-h"},
            salt="s",
        )
        assert (ctx.api_key, ctx.source) == ("sk-h", "header")
        assert ctx.model == "m-h"

    def test_secrets_from_auth(self) -> None:
        """``Secrets.from_auth``：model 由调用面覆盖，其余随 AuthContext。"""
        ctx = resolve_auth(_SETTINGS, header_key="sk-h", salt="s")
        sec = Secrets.from_auth(ctx, model="m-row")
        assert (
            sec.api_key,
            sec.base_url,
            sec.model,
            sec.dialect,
            sec.source,
        ) == ("sk-h", ctx.base_url, "m-row", ctx.dialect, "header")


class TestRowJson:
    """``store.row_json``——``*_json`` 列容错反序列化钉板。"""

    def test_fault_tolerance(self) -> None:
        assert row_json({}, "options_json") == {}
        assert row_json({"options_json": "{bad"}, "options_json") == {}
        assert row_json({"options_json": "[1, 2]"}, "options_json") == {}
        assert row_json({"options_json": '"lit"'}, "options_json") == {}
        assert row_json({"options_json": '{"a": 1}'}, "options_json") == {"a": 1}
        assert row_json({"config_json": '{"glossary": "g.yaml"}'}, "config_json") == {
            "glossary": "g.yaml"
        }


class TestSettingsLoadCache:
    def test_cache_hit_skips_parse(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = _mk_settings(tmp_path)
        s.load()
        calls = 0
        orig = SettingsStore._normalize  # noqa: SLF001 -- 探 parse 次数

        def _spy(data: dict[str, Any]) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            return orig(data)

        monkeypatch.setattr(SettingsStore, "_normalize", staticmethod(_spy))
        s.load()
        s.load()
        assert calls == 0

    def test_file_change_reloads(self, tmp_path: Path) -> None:
        s = _mk_settings(tmp_path)
        s.save({"model": "m1"})
        assert s.load()["model"] == "m1"
        # 外部直写（手改文件）→ 签名变 → 重读
        s.path.write_text(
            json.dumps({"model": "m2", "api_key": "sk-x"}), encoding="utf-8"
        )
        got = s.load()
        assert got["model"] == "m2"
        assert got["api_key"] == "sk-x"

    def test_save_invalidates(self, tmp_path: Path) -> None:
        s = _mk_settings(tmp_path)
        s.load()  # 暖缓存（文件缺席签名）
        s.save({"model": "m9"})
        assert s.load()["model"] == "m9"

    def test_public_does_not_poison_cache(self, tmp_path: Path) -> None:
        """public() pop api_key 只动浅拷贝——后续 load 仍带 key。"""
        s = _mk_settings(tmp_path)
        s.save({"api_key": "sk-1"})
        s.load()  # 暖缓存
        pub = s.public()
        assert pub["has_api_key"] is True
        assert "api_key" not in pub
        assert s.load()["api_key"] == "sk-1"


class TestRecoverStartupTerminalFields:
    def test_interrupted_clears_stage_sets_finished(self, store: Store) -> None:
        row = mk_task_row(store)
        store.transition(row["id"], "translating", force=True)
        store.recover_startup()
        got = store.get(row["id"])
        assert got["status"] == "interrupted"
        assert got["stage"] is None
        assert got["finished_at"] is not None

    def test_needs_auth_queued_clears_stage_sets_finished(self, store: Store) -> None:
        row = mk_task_row(store, auth_source="header")
        store.recover_startup()
        got = store.get(row["id"])
        assert got["status"] == "needs_auth"
        assert got["stage"] is None
        assert got["finished_at"] is not None

    def test_queued_settings_untouched(self, store: Store) -> None:
        row = mk_task_row(store)
        store.recover_startup()
        got = store.get(row["id"])
        assert got["status"] == "queued"
        assert got["finished_at"] is None


class TestCacheHitBatching:
    def test_hits_flush_with_batch(self, store: Store) -> None:
        tid = mk_task_row(store)["id"]
        _seed_cache_row(store.conn)
        assert store.cache_get("k") == "v"
        assert store.cache_get("k") == "v"
        store.flush_chunk_batch(tid, [], [], {})
        hit = store.conn.execute(
            "SELECT hit_count FROM translation_cache WHERE key = 'k'"
        ).fetchone()["hit_count"]
        assert hit == 2  # noqa: PLR2004 -- 两次命中聚合

    def test_hits_flush_on_close(self, tmp_path: Path) -> None:
        s = Store(tmp_path / "t.db")
        s.open()
        _seed_cache_row(s.conn)
        assert s.cache_get("k") == "v"
        s.close()
        s2 = Store(tmp_path / "t.db")
        s2.open()
        try:
            hit = s2.conn.execute(
                "SELECT hit_count FROM translation_cache WHERE key = 'k'"
            ).fetchone()["hit_count"]
            assert hit == 1
        finally:
            s2.close()


class TestStaleDoneReplay:
    def test_stale_done_skipped_on_retry(self, store: Store) -> None:
        """fault→retry 复活的任务：重放跳过旧 done，续放新事件进 live。"""
        tid = mk_task_row(store)["id"]
        bus = EventBus(store)
        bus.publish(tid, "stage", {"stage": "translating"})  # seq1
        store.transition(tid, "fault", force=True)
        bus.publish(tid, "done", {"status": "fault"})  # seq2 — 旧轮终帧
        store.transition(tid, "queued")  # retry 复活
        bus.publish(tid, "stage", {"stage": "fetching"})  # seq3 — 新一轮

        seen = _collect_stream(bus, tid, 2)  # 只收重放段两帧即撤
        assert [(e["type"], e["seq"]) for e in seen] == [("stage", 1), ("stage", 3)]

    def test_done_last_and_terminal_ends(self, store: Store) -> None:
        """真终态 + done 在重放段末尾 → 照发并终流。"""
        tid = mk_task_row(store)["id"]
        bus = EventBus(store)
        bus.publish(tid, "stage", {"stage": "compiling"})
        store.transition(tid, "done", force=True)
        bus.publish(tid, "done", {"status": "done"})

        seen = _collect_stream(bus, tid)
        assert [e["type"] for e in seen] == ["stage", "done"]

    def test_stale_done_skipped_when_refinished(self, store: Store) -> None:
        """fault→retry→done：旧 done 非重放末尾 → 跳过，收最新 done。"""
        tid = mk_task_row(store)["id"]
        bus = EventBus(store)
        store.transition(tid, "fault", force=True)
        bus.publish(tid, "done", {"status": "fault"})  # seq1 旧轮终帧
        store.transition(tid, "queued")
        bus.publish(tid, "stage", {"stage": "compiling"})  # seq2
        store.transition(tid, "done", force=True)
        bus.publish(tid, "done", {"status": "done"})  # seq3 本轮终帧

        seen = _collect_stream(bus, tid)
        assert [(e["type"], e["seq"]) for e in seen] == [("stage", 2), ("done", 3)]
        assert seen[-1]["data"]["status"] == "done"


class TestErrorCodesNew:
    def test_worker_new_codes_listed(self) -> None:
        assert {"no_html_source", "translate"} <= ERROR_CODES


# ------------------------------------------------------------------ wave 2

_N_CHUNKS = 10
_CLAMP_N = 505
_CLAMP_MAX = 500


def _mk_chunks(n: int) -> list[dict[str, Any]]:
    return [mk_chunk_row(i, src_text=f"src {i}") for i in range(n)]


def _mk_settings(tmp_path: Path) -> SettingsStore:
    root = tmp_path / "d"
    root.mkdir()
    return SettingsStore(root)


class TestConnDisciplineMethods:
    """裸 ``store.conn`` 逃逸点（app.py:605/1640、runner.py:81）的收口方法。"""

    def test_task_ids(self, store: Store) -> None:
        a = mk_task_row(store)["id"]
        b = mk_task_row(store)["id"]
        assert set(store.task_ids()) == {a, b}

    def test_queued_rows_filters_and_orders(self, store: Store) -> None:
        first = mk_task_row(store)["id"]
        second = mk_task_row(store)["id"]
        mk_task_row(store, auth_source="header")  # header 源不进补放面
        active = mk_task_row(store)["id"]
        store.transition(active, "translating", force=True)  # 非 queued 出局
        # 显式钉 created_at 消除时钟分辨率依赖——FIFO 序才可断言
        store.conn.execute(
            "UPDATE tasks SET created_at = ? WHERE id = ?", (100.0, first)
        )
        store.conn.execute(
            "UPDATE tasks SET created_at = ? WHERE id = ?", (200.0, second)
        )
        store.conn.commit()
        rows = store.queued_rows()
        assert [r["id"] for r in rows] == [first, second]
        assert set(rows[0]) == {"id", "model"}  # 窄列钉住
        assert rows[0]["model"] == "m"

    def test_delete_chunks_count_and_idempotent(self, store: Store) -> None:
        tid = mk_task_row(store)["id"]
        store.insert_chunks(tid, _mk_chunks(3))
        assert store.delete_chunks(tid) == 3  # noqa: PLR2004 -- 行数回执
        assert store.all_chunks(tid) == []
        assert store.delete_chunks(tid) == 0


class TestChunksPage:
    _COLS: ClassVar[set[str]] = {
        "seq",
        "chunk_id",
        "kind",
        "status",
        "src_text",
        "translation",
    }

    def test_narrow_columns_order_and_total(self, store: Store) -> None:
        tid = mk_task_row(store)["id"]
        store.insert_chunks(tid, _mk_chunks(_N_CHUNKS))
        store.flush_chunk_batch(
            tid, [("c2", {"status": "ok", "translation": "译2"})], [], {}
        )
        rows, total = store.chunks_page(tid, offset=2, limit=3)
        assert total == _N_CHUNKS
        assert [r["seq"] for r in rows] == [2, 3, 4]
        assert set(rows[0]) == self._COLS
        assert rows[0]["status"] == "ok"
        assert rows[0]["translation"] == "译2"
        assert rows[0]["src_text"] == "src 2"

    def test_limit_clamped(self, store: Store) -> None:
        tid = mk_task_row(store)["id"]
        store.insert_chunks(tid, _mk_chunks(_CLAMP_N))
        rows, total = store.chunks_page(tid, limit=99999)
        assert len(rows) == _CLAMP_MAX
        assert total == _CLAMP_N

    def test_clamp_edges(self, store: Store) -> None:
        tid = mk_task_row(store)["id"]
        store.insert_chunks(tid, _mk_chunks(2))
        rows, total = store.chunks_page(tid, offset=-9, limit=10)
        assert [r["seq"] for r in rows] == [0, 1]
        assert total == 2  # noqa: PLR2004 -- 样本量
        rows, total = store.chunks_page(tid, limit=0)
        assert rows == []
        assert total == 2  # noqa: PLR2004 -- 同上
        rows, _ = store.chunks_page(tid, limit=-5)
        assert rows == []
        rows, _ = store.chunks_page(tid, offset=99)
        assert rows == []

    def test_by_seqs_picks_orders_and_keeps_total(self, store: Store) -> None:
        """定点取块（增量轮询供）：乱序/重复 seq 归一去重升序，total 仍是全集。"""
        tid = mk_task_row(store)["id"]
        store.insert_chunks(tid, _mk_chunks(_N_CHUNKS))
        store.flush_chunk_batch(
            tid, [("c7", {"status": "ok", "translation": "译7"})], [], {}
        )
        rows, total = store.chunks_by_seqs(tid, [9, 0, 7, 7])
        assert total == _N_CHUNKS
        assert [r["seq"] for r in rows] == [0, 7, 9]
        assert rows[1]["translation"] == "译7"
        rows, total = store.chunks_by_seqs(tid, [])
        assert rows == []
        assert total == _N_CHUNKS
        rows, _ = store.chunks_by_seqs(tid, [98, 99])
        assert rows == []


class TestAppendEventDropped:
    """be#8：已 DELETE 任务行的迟到 publish 静默丢弃，FK 不炸 worker。"""

    def test_deleted_task_returns_zero(self, store: Store) -> None:
        tid = mk_task_row(store)["id"]
        store.append_event(tid, "a", {})  # seq1 落盘
        store.delete_task(tid)  # CASCADE 带走事件
        assert store.append_event(tid, "late", {}) == 0
        assert store.events_since(tid, 0) == []
        assert store.last_seq(tid) == 0

    def test_publish_no_fanout_on_drop(self, store: Store) -> None:
        tid = mk_task_row(store)["id"]
        bus = EventBus(store)
        q = bus.subscribe(tid)
        store.delete_task(tid)
        assert bus.publish(tid, "progress", {}) == 0
        assert q.empty()

    def test_live_task_seq_unchanged(self, store: Store) -> None:
        tid = mk_task_row(store)["id"]
        bus = EventBus(store)
        assert bus.publish(tid, "a", {}) == 1
        assert bus.publish(tid, "b", {}) == 2  # noqa: PLR2004 -- seq 步进


def _sweep_retention(
    store: Store, tasks_dir: Path, *, max_age_s: float, max_total_bytes: int
) -> dict[str, Any]:
    """retention 两段 GC 测试面——生产路径是 ``app._sweep_delete``（async），
    本件同步直调同一底层机械：``retention_candidates``/``terminal_oldest_first``
    + ``delete_task_guard`` 条件删 + ``_retention_drop_order`` 剪停单源。
    """
    removed: list[str] = []
    freed = 0

    def _drop(tid: str) -> int:
        if not store.delete_task_guard(tid, blocked=ACTIVE_STATUSES):
            return 0
        sz = _dir_size(tasks_dir / tid)
        shutil.rmtree(tasks_dir / tid, ignore_errors=True)
        removed.append(tid)
        return sz

    if max_age_s > 0:
        for tid in store.retention_candidates(time.time() - max_age_s):
            freed += _drop(tid)
    if max_total_bytes > 0:
        total = _dir_size(tasks_dir)
        if total > max_total_bytes:
            order = _retention_drop_order(
                store.terminal_oldest_first(),
                total_bytes=total,
                cap_bytes=max_total_bytes,
            )
            try:
                tid = next(order)
                while True:
                    sz = _drop(tid)
                    freed += sz
                    tid = order.send(sz)
            except StopIteration:
                pass
    return {"removed": removed, "freed_bytes": freed}


class TestSweepRetention:
    def _mk_terminal(self, store: Store, *, age_s: float = 0.0) -> str:
        """done 任务；``age_s>0`` 把 finished_at/updated_at 回拨构造超龄。"""
        tid = mk_task_row(store)["id"]
        store.transition(tid, "done", force=True)
        if age_s > 0:
            old = time.time() - age_s
            store.conn.execute(
                "UPDATE tasks SET finished_at = ?, updated_at = ? WHERE id = ?",
                (old, old, tid),
            )
            store.conn.commit()
        return str(tid)

    @staticmethod
    def _dir(root: Path, tid: str, size: int) -> None:
        d = root / tid
        d.mkdir(parents=True, exist_ok=True)
        (d / "f.bin").write_bytes(b"x" * size)

    def test_age_phase_terminal_only(self, store: Store, tmp_path: Path) -> None:
        tdir = tmp_path / "tasks"
        tdir.mkdir()
        old_done = self._mk_terminal(store, age_s=3600.0)
        new_done = self._mk_terminal(store)
        queued = mk_task_row(store)["id"]
        stale_active = mk_task_row(store)["id"]
        store.transition(stale_active, "translating", force=True)
        store.conn.execute(
            "UPDATE tasks SET updated_at = ? WHERE id = ?",
            (time.time() - 99999.0, stale_active),
        )
        store.conn.commit()
        for t in (old_done, new_done, queued, stale_active):
            self._dir(tdir, t, 10)
        out = _sweep_retention(store, tdir, max_age_s=60.0, max_total_bytes=0)
        assert out == {"removed": [old_done], "freed_bytes": 10}
        assert store.get(old_done) is None
        assert not (tdir / old_done).exists()
        for t in (new_done, queued, stale_active):
            assert store.get(t) is not None
            assert (tdir / t).is_dir()

    def test_size_phase_oldest_first(self, store: Store, tmp_path: Path) -> None:
        tdir = tmp_path / "tasks"
        tdir.mkdir()
        ids = [self._mk_terminal(store, age_s=a) for a in (300.0, 200.0, 100.0)]
        for t in ids:
            self._dir(tdir, t, 100)
        # 300B > 250 → 删最老一个落到 200B 达标即停
        out = _sweep_retention(store, tdir, max_age_s=0.0, max_total_bytes=250)
        assert out == {"removed": [ids[0]], "freed_bytes": 100}
        assert store.get(ids[0]) is None
        assert store.get(ids[1]) is not None
        assert not (tdir / ids[0]).exists()
        assert (tdir / ids[1]).is_dir()

    def test_size_phase_exhausts_candidates(self, store: Store, tmp_path: Path) -> None:
        """预算压到底 → 终态候选穷尽即停（不炸）；ACTIVE 永不进候选。"""
        tdir = tmp_path / "tasks"
        tdir.mkdir()
        done = self._mk_terminal(store, age_s=100.0)
        active = mk_task_row(store)["id"]
        store.transition(active, "translating", force=True)
        self._dir(tdir, done, 100)
        self._dir(tdir, active, 500)  # ACTIVE 目录再占也不删
        out = _sweep_retention(store, tdir, max_age_s=0.0, max_total_bytes=1)
        assert out["removed"] == [done]
        assert out["freed_bytes"] == 100  # noqa: PLR2004 -- 单任务目录字节
        assert store.get(active) is not None
        assert (tdir / active).is_dir()

    def test_disabled_noop_and_missing_dir(self, store: Store, tmp_path: Path) -> None:
        tid = self._mk_terminal(store, age_s=99999.0)
        out = _sweep_retention(
            store, tmp_path / "nonexistent", max_age_s=0.0, max_total_bytes=0
        )
        assert out == {"removed": [], "freed_bytes": 0}
        assert store.get(tid) is not None

    def test_row_without_dir(self, store: Store, tmp_path: Path) -> None:
        """终态超龄但无任务目录 → 删行 freed=0，不炸。"""
        tdir = tmp_path / "tasks"
        tdir.mkdir()
        tid = self._mk_terminal(store, age_s=99999.0)
        out = _sweep_retention(store, tdir, max_age_s=60.0, max_total_bytes=0)
        assert out == {"removed": [tid], "freed_bytes": 0}
        assert store.get(tid) is None


class TestSlimTaskDir:
    """``slim_task_dir``：白名单=登记路径，其余字节+空目录全清（幂等纯 FS）。"""

    def test_keep_registered_and_prune(self, tmp_path: Path) -> None:
        root = tmp_path / "t1"
        (root / "build-zh" / "aux").mkdir(parents=True)
        (root / "zh").mkdir()
        (root / "zh.pdf").write_bytes(b"x" * 100)
        (root / "build-zh" / "a.aux").write_bytes(b"x" * 50)
        (root / "build-zh" / "aux" / "deep.log").write_bytes(b"x" * 30)
        (root / "zh" / "main.tex").write_bytes(b"x" * 40)
        (root / "orphan.txt").write_bytes(b"x" * 10)
        freed = slim_task_dir(root, {"zh.pdf"}, ("zh",))
        assert freed == 90  # noqa: PLR2004 -- 50+30+10：zh.pdf 与 zh/ 全树保留
        assert (root / "zh.pdf").is_file()
        assert (root / "zh" / "main.tex").is_file()
        assert not (root / "build-zh").exists()
        assert not (root / "orphan.txt").exists()
        assert root.is_dir()  # 根目录本身保留

    def test_idempotent_and_missing_dir(self, tmp_path: Path) -> None:
        assert slim_task_dir(tmp_path / "nope", {"a"}, ()) == 0
        root = tmp_path / "t2"
        root.mkdir()
        (root / "f.bin").write_bytes(b"x" * 7)
        assert slim_task_dir(root, set(), ()) == 7  # noqa: PLR2004 -- 单文件字节
        assert slim_task_dir(root, set(), ()) == 0
        assert root.is_dir()

    def test_keep_entry_traversal_rejected(self, tmp_path: Path) -> None:
        """keep 项含 ``..``/绝对路径不生效——与 file_get confine 闸同口径。"""
        root = tmp_path / "t3"
        root.mkdir()
        (root / "f.bin").write_bytes(b"x" * 9)
        freed = slim_task_dir(root, {"../f.bin", "/abs/f.bin"}, ())
        assert freed == 9  # noqa: PLR2004 -- 单文件字节
        assert not (root / "f.bin").exists()

    def test_symlink_unlinked_not_followed(self, tmp_path: Path) -> None:
        root = tmp_path / "t4"
        outside = tmp_path / "outside"
        (root / "d").mkdir(parents=True)
        outside.mkdir()
        (outside / "real.bin").write_bytes(b"x" * 11)
        (root / "d" / "link").symlink_to(outside / "real.bin")
        freed = slim_task_dir(root, set(), ())
        assert freed == 0  # symlink 不计字节（lstat 非 REG）
        assert not (root / "d").exists()  # 摘链后 d 空被摘
        assert (outside / "real.bin").is_file()  # 目标不动


class TestTerminalTaskIds:
    def test_terminal_only_and_tenant_filter(self, store: Store) -> None:
        done = mk_task_row(store)["id"]
        store.transition(done, "done", force=True)
        fault = mk_task_row(store, tenant="other")["id"]
        store.transition(fault, "fault", force=True)
        active = mk_task_row(store)["id"]  # queued 原样
        assert set(store.terminal_task_ids()) == {done, fault}
        assert store.terminal_task_ids("local") == [done]
        assert store.terminal_task_ids("other") == [fault]
        assert active not in store.terminal_task_ids()


class TestResyncGapFrame:
    """be#18：last_event_id 落已淘汰区段 → 重放前先给 resync 提示帧。"""

    @staticmethod
    def _seed(store: Store, bus: EventBus, tid: str) -> None:
        """发 5 帧再删 seq≤3（模拟 EVENT_CAP 淘汰窗口）。"""
        for i in range(5):
            bus.publish(tid, "progress", {"i": i})
        store.conn.execute(
            "DELETE FROM task_events WHERE task_id = ? AND seq <= 3", (tid,)
        )
        store.conn.commit()

    def test_gap_yields_resync_then_replay(self, store: Store) -> None:
        tid = mk_task_row(store)["id"]
        bus = EventBus(store)
        self._seed(store, bus, tid)

        # last_event_id=2：客户端只见 seq≤2，seq3 已淘汰 → 缺口 3..3
        seen = _collect_stream(bus, tid, 3, last_event_id=2)  # resync+2 重放帧
        assert seen[0] == {
            "seq": 3,
            "type": "resync",
            "data": {"gap_after": 2, "resume_from": 4},
        }
        assert [e["seq"] for e in seen[1:]] == [4, 5]

    def test_contiguous_replay_no_resync(self, store: Store) -> None:
        tid = mk_task_row(store)["id"]
        bus = EventBus(store)
        self._seed(store, bus, tid)

        # last_event_id=3：下一可重放即 seq4——数值连续无缺口
        seen = _collect_stream(bus, tid, 2, last_event_id=3)  # 两帧即撤
        assert [e["type"] for e in seen] == ["progress", "progress"]

    def test_fresh_connect_no_resync(self, store: Store) -> None:
        """last_event_id=0（新连）→ 全量重放语义，无 resync 帧。"""
        tid = mk_task_row(store)["id"]
        bus = EventBus(store)
        self._seed(store, bus, tid)

        seen = _collect_stream(bus, tid, 2)  # 两帧即撤
        assert [e["type"] for e in seen] == ["progress", "progress"]


class TestSettingsScalarGate:
    """be#12：标量字段拒非 str/容器值；context_guidance 限 bool。"""

    def test_str_fields_reject_containers(self, tmp_path: Path) -> None:
        s = _mk_settings(tmp_path)
        # 字段集由 _FIELD_SPECS 派生（同 BYOK_FIELDS/_CONNECTION_SLOTS 钉板手法）——
        # 新增 str 标量字段（如 dialect）自动进闸，不再靠手抄名单
        for f in [spec.name for spec in _FIELD_SPECS if spec.scalar is str]:
            with pytest.raises(ValueError, match="必须是字符串"):
                s.save({f: {"x": 1}})
            with pytest.raises(ValueError, match="必须是字符串"):
                s.save({f: ["a"]})

    def test_engine_dict_was_typeerror(self, tmp_path: Path) -> None:
        """dict 撞 frozenset 枚举校验曾是 TypeError→500；现在统一 ValueError→400。"""
        s = _mk_settings(tmp_path)
        with pytest.raises(ValueError, match="必须是字符串"):
            s.save({"engine": {"x": 1}})

    def test_context_guidance_requires_bool(self, tmp_path: Path) -> None:
        s = _mk_settings(tmp_path)
        for bad in ("yes", 1, ["x"], {"a": 1}):
            with pytest.raises(ValueError, match="布尔"):
                s.save({"context_guidance": bad})
        assert s.save({"context_guidance": False})["context_guidance"] is False
        assert s.load()["context_guidance"] is False

    def test_retention_fields(self, tmp_path: Path) -> None:
        s = _mk_settings(tmp_path)
        assert s.load()["retention_days"] == 0
        assert s.load()["retention_max_gb"] == 0
        out = s.save({"retention_days": 30, "retention_max_gb": 10})
        assert out["retention_days"] == 30  # noqa: PLR2004 -- 样本值
        assert out["retention_max_gb"] == 10  # noqa: PLR2004 -- 同上
        assert s.load()["retention_days"] == 30  # noqa: PLR2004 -- 持久化回读
        with pytest.raises(ValueError, match="非负整数"):
            s.save({"retention_days": -1})
        with pytest.raises(ValueError, match="非负整数"):
            s.save({"retention_max_gb": {"x": 1}})


class TestLoadDeepCopy:
    """be#14：load() 深拷贝——改返回值的嵌套容器不污染磁盘缓存。"""

    def test_cors_origins_mutation_no_poison(self, tmp_path: Path) -> None:
        s = _mk_settings(tmp_path)
        s.save({"cors_origins": ["http://a.example"]})
        got = s.load()
        got["cors_origins"].append("http://evil.example")
        got["cors_origins"].clear()
        again = s.load()  # 签名命中缓存路径
        assert again["cors_origins"] == ["http://a.example"]
        assert s.public()["cors_origins"] == ["http://a.example"]


class TestSnapshotUserOptions:
    """snapshot 回显用户入参 options + config 的 glossary——M10 try-html 透传源。"""

    def test_options_echoed_minus_internal_keys(self, store: Store) -> None:
        tid = mk_task_row(
            store,
            options={
                "concurrency": 4,
                "prefer": "fresh",
                "idempotency_key": "once",
                "share": {"share_key": "x"},
                "reuse_hit": "share:abc",
                "engine_resolved": "xelatex",
            },
            config={"glossary": "g.yaml"},
        )["id"]
        snap = store.snapshot(tid, artifacts={})
        assert snap["options"] == {"concurrency": 4, "prefer": "fresh"}
        assert snap["glossary"] == "g.yaml"

    def test_absent_options_no_key(self, store: Store) -> None:
        tid = mk_task_row(store)["id"]
        snap = store.snapshot(tid, artifacts={})
        assert "options" not in snap
        assert "glossary" not in snap

    def test_bad_json_no_crash(self, store: Store) -> None:
        """腐化 options_json/config_json → 跳过回显不炸 snapshot。"""
        tid = mk_task_row(store)["id"]
        store.update_fields(tid, options_json="{bad", config_json="[1]")
        snap = store.snapshot(tid, artifacts={})
        assert "options" not in snap
        assert "glossary" not in snap
