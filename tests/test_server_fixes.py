"""审查修复钉板：list_tasks_page/delete_task_guard 契约、load 磁盘缓存、
resolve_auth 跨槽闸、recover_startup 终态清理、cache 命中聚合、stale done 重放。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")

from conftest import mk_task_row

from texlate.server.events import EventBus
from texlate.server.settings import SettingsStore, resolve_auth
from texlate.server.store import (
    ACTIVE_STATUSES,
    ERROR_CODES,
    Store,
    new_task_id,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    s = Store(tmp_path / "t.db")
    s.open()
    yield s
    s.close()


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
)


class TestListTasksPage:
    def test_page_and_total(self, store: Store) -> None:
        for _ in range(5):
            mk_task_row(store)
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


class TestSettingsLoadCache:
    @pytest.fixture(autouse=True)
    def _no_probe(self, clean_env: pytest.MonkeyPatch) -> None:
        """save 内 /v1/models 探活关掉——测试不打网络。"""
        clean_env.setenv("TEXLATE_MODEL_PROBE", "0")

    def _store(self, tmp_path: Path) -> SettingsStore:
        root = tmp_path / "d"
        root.mkdir()
        return SettingsStore(root)

    def test_cache_hit_skips_parse(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = self._store(tmp_path)
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
        s = self._store(tmp_path)
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
        s = self._store(tmp_path)
        s.load()  # 暖缓存（文件缺席签名）
        s.save({"model": "m9"})
        assert s.load()["model"] == "m9"

    def test_public_does_not_poison_cache(self, tmp_path: Path) -> None:
        """public() pop api_key 只动浅拷贝——后续 load 仍带 key。"""
        s = self._store(tmp_path)
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
        store.conn.execute(
            "INSERT INTO translation_cache (key, translation, model,"
            " target_lang, created_at, last_hit_at) VALUES ('k','v','m','l',0,0)"
        )
        store.conn.commit()
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
        s.conn.execute(
            "INSERT INTO translation_cache (key, translation, model,"
            " target_lang, created_at, last_hit_at) VALUES ('k','v','m','l',0,0)"
        )
        s.conn.commit()
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

        async def run() -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            async for ev in bus.stream(tid):
                out.append(ev)
                if len(out) == 2:  # noqa: PLR2004 -- 只收重放段两帧即撤
                    break
            return out

        seen = asyncio.run(asyncio.wait_for(run(), 5))
        assert [(e["type"], e["seq"]) for e in seen] == [("stage", 1), ("stage", 3)]

    def test_done_last_and_terminal_ends(self, store: Store) -> None:
        """真终态 + done 在重放段末尾 → 照发并终流。"""
        tid = mk_task_row(store)["id"]
        bus = EventBus(store)
        bus.publish(tid, "stage", {"stage": "compiling"})
        store.transition(tid, "done", force=True)
        bus.publish(tid, "done", {"status": "done"})

        async def run() -> list[dict[str, Any]]:
            return [ev async for ev in bus.stream(tid)]

        seen = asyncio.run(asyncio.wait_for(run(), 5))
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

        async def run() -> list[dict[str, Any]]:
            return [ev async for ev in bus.stream(tid)]

        seen = asyncio.run(asyncio.wait_for(run(), 5))
        assert [(e["type"], e["seq"]) for e in seen] == [("stage", 2), ("done", 3)]
        assert seen[-1]["data"]["status"] == "done"


class TestErrorCodesNew:
    def test_worker_new_codes_listed(self) -> None:
        assert {"no_html_source", "translate"} <= ERROR_CODES
