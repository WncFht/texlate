"""二轮审查修复钉板（store/settings/events 层）：

- ``Store.task_ids``/``queued_rows``/``delete_chunks``——裸 ``store.conn``
  逃逸点（app.py 孤儿清扫 / task_retry / runner._replay_queued）的收口方法；
- ``chunks_page`` 窄列分页 + limit 钳位（U1 流式预览端点供）；
- ``append_event`` 对已 DELETE 任务行静默丢弃（``INSERT…SELECT…WHERE
  EXISTS``，返 ``0``），``publish`` 不扇出幽灵帧；
- ``sweep_retention`` 两段 GC：终态+超龄先删，总量兜底 oldest-first，
  ACTIVE 永不删；
- ``EventBus.stream`` 重放缺口 → ``resync`` 提示帧（seq=首个重放 seq-1）；
- ``SettingsStore.save`` 标量字段类型闸（dict/list 不再被 ``str()``
  字面量持久化，``engine`` 撞非 hashable 值不再 TypeError→500）；
- ``load()`` 深拷贝防嵌套容器别名污染缓存；
- ``retention_days``/``retention_max_gb`` 设置字段（0=关闭）。
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, ClassVar

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")

from conftest import mk_task_row

from texlate.server.events import EventBus
from texlate.server.settings import SettingsStore
from texlate.server.store import Store

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_N_CHUNKS = 10
_CLAMP_N = 505
_CLAMP_MAX = 500


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    s = Store(tmp_path / "t.db")
    s.open()
    yield s
    s.close()


def _mk_chunks(n: int) -> list[dict[str, Any]]:
    return [
        {
            "seq": i,
            "chunk_id": f"c{i}",
            "src_file": "main.tex",
            "byte_start": i * 10,
            "byte_end": i * 10 + 9,
            "kind": "text",
            "src_text": f"src {i}",
        }
        for i in range(n)
    ]


def _mk_settings(tmp_path: Path) -> SettingsStore:
    root = tmp_path / "d"
    root.mkdir()
    return SettingsStore(root)


@pytest.fixture(autouse=True)
def _no_model_probe(clean_env: pytest.MonkeyPatch) -> None:
    """save 内 /v1/models 探活关掉——测试不打网络。"""
    clean_env.setenv("TEXLATE_MODEL_PROBE", "0")


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
        out = store.sweep_retention(tdir, max_age_s=60.0, max_total_bytes=0)
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
        out = store.sweep_retention(tdir, max_age_s=0.0, max_total_bytes=250)
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
        out = store.sweep_retention(tdir, max_age_s=0.0, max_total_bytes=1)
        assert out["removed"] == [done]
        assert out["freed_bytes"] == 100  # noqa: PLR2004 -- 单任务目录字节
        assert store.get(active) is not None
        assert (tdir / active).is_dir()

    def test_disabled_noop_and_missing_dir(self, store: Store, tmp_path: Path) -> None:
        tid = self._mk_terminal(store, age_s=99999.0)
        out = store.sweep_retention(
            tmp_path / "nonexistent", max_age_s=0.0, max_total_bytes=0
        )
        assert out == {"removed": [], "freed_bytes": 0}
        assert store.get(tid) is not None

    def test_row_without_dir(self, store: Store, tmp_path: Path) -> None:
        """终态超龄但无任务目录 → 删行 freed=0，不炸。"""
        tdir = tmp_path / "tasks"
        tdir.mkdir()
        tid = self._mk_terminal(store, age_s=99999.0)
        out = store.sweep_retention(tdir, max_age_s=60.0, max_total_bytes=0)
        assert out == {"removed": [tid], "freed_bytes": 0}
        assert store.get(tid) is None


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
        async def run() -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            async for ev in bus.stream(tid, last_event_id=2):
                out.append(ev)
                if len(out) == 3:  # noqa: PLR2004 -- resync+2 重放帧
                    break
            return out

        seen = asyncio.run(asyncio.wait_for(run(), 5))
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
        async def run() -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            async for ev in bus.stream(tid, last_event_id=3):
                out.append(ev)
                if len(out) == 2:  # noqa: PLR2004 -- 两帧即撤
                    break
            return out

        seen = asyncio.run(asyncio.wait_for(run(), 5))
        assert [e["type"] for e in seen] == ["progress", "progress"]

    def test_fresh_connect_no_resync(self, store: Store) -> None:
        """last_event_id=0（新连）→ 全量重放语义，无 resync 帧。"""
        tid = mk_task_row(store)["id"]
        bus = EventBus(store)
        self._seed(store, bus, tid)

        async def run() -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            async for ev in bus.stream(tid):
                out.append(ev)
                if len(out) == 2:  # noqa: PLR2004 -- 两帧即撤
                    break
            return out

        seen = asyncio.run(asyncio.wait_for(run(), 5))
        assert [e["type"] for e in seen] == ["progress", "progress"]


class TestSettingsScalarGate:
    """be#12：标量字段拒非 str/容器值；context_guidance 限 bool。"""

    def test_str_fields_reject_containers(self, tmp_path: Path) -> None:
        s = _mk_settings(tmp_path)
        for f in (
            "base_url",
            "model",
            "api_key",
            "glossary",
            "glossary_dir",
            "engine",
            "target_lang",
        ):
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
