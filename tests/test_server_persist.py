"""server-persist-audit 批：files 登记行生命周期一致性钉样。

- ``Store.delete_file``：删行 + 返回 path（磁盘件清理由调用方负责）。
- ``insert_chunks`` 显式事务：executemany 中途失败 rollback——不留
  半成品 chunks 给下一个无关 ``commit()`` 静默落库。
- ``worker._invalidate_splice``：译文变更摘哨兵时派生产物行 + 磁盘件
  并删（``_SPLICE_STALE_KINDS``），en_pdf/src_tar 保留。
- ``app.task_retry`` 换 main：body.main 与 options.main 同口径触发
  清理——chunks + base/zh/build-* + 全部非 src_tar 产物行/磁盘件。
- ``reader_get`` 以 ``dual_json`` 登记行为准（磁盘孤儿件不服务）。
- ``EventBus.stream``：任务行已删 → 不空等（delete 的 done 事件先于
  删行发出，晚注册订阅者靠行缺席兜底）。
- ``worker._opt_int`` ≤0/非数值钳位 + ``bad_option`` 告警事件（下游旋钮
  无 ``__post_init__`` 兜底）。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from _workerkit import mk_ctx
from conftest import mk_chunk_row, mk_task_row

from texlate.server.events import EventBus
from texlate.server.store import Store, new_task_id
from texlate.server.worker import (
    DBStateBridge,
    PipelineWorker,
    Secrets,
    SegmentCache,
    TaskCtx,
)

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.testclient import TestClient

# 产物 kind→磁盘文件名全表：两处 seed 与 purge 断言同源派生——
# 新增产物 kind 不会静默漏掉清理面覆盖。
ARTIFACT_FILES = (
    ("src_tar", "src.tar"),
    ("en_pdf", "en.pdf"),
    ("zh_pdf", "zh.pdf"),
    ("zh_src_zip", "zh-src.zip"),
    ("dual_json", "dual.json"),
    ("compile_log", "compile.log"),
    ("md_zip", "md.zip"),
)
# splice 摘哨兵只清依赖 chunks 的派生产物——en_pdf（base/ 编译）与
# src_tar（源件）不依赖 chunks，属保留侧。
_SPLICE_KEPT = ("en_pdf", "src_tar")


def _mk_store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "t.db")
    s.open()
    return s


def _chunk(seq: int, cid: str | None = None) -> dict:
    return mk_chunk_row(seq, chunk_id=cid or f"c{seq}")


class TestDeleteFile:
    """``delete_file``：行删除 + path 回执 + 配额字节回落。"""

    def test_delete_returns_path_and_frees_quota(self, tmp_path: Path) -> None:
        store = _mk_store(tmp_path)
        try:
            row = mk_task_row(store)
            tdir = tmp_path / "tasks" / row["id"]
            tdir.mkdir(parents=True)
            (tdir / "zh.pdf").write_bytes(b"%PDF fake")
            (tdir / "en.pdf").write_bytes(b"%PDF en")
            store.put_file(row["id"], "zh_pdf", "zh.pdf", data_dir=tdir)
            store.put_file(row["id"], "en_pdf", "en.pdf", data_dir=tdir)
            before = store.tenant_usage("local")["bytes"]
            assert before > 0

            got = store.delete_file(row["id"], "zh_pdf")
            assert got == "zh.pdf"
            assert store.file_record(row["id"], "zh_pdf") is None
            assert store.file_record(row["id"], "en_pdf") is not None
            assert store.tenant_usage("local")["bytes"] < before

            assert store.delete_file(row["id"], "zh_pdf") is None
            assert store.delete_file(row["id"], "nope") is None
        finally:
            store.close()

    def test_cascade_still_covers_remaining(self, tmp_path: Path) -> None:
        """delete_file 摘单行不碍 delete_task 级联清剩余行。"""
        store = _mk_store(tmp_path)
        try:
            row = mk_task_row(store)
            store.put_file(row["id"], "zh_pdf", "zh.pdf", size=1, sha256="x")
            store.put_file(row["id"], "en_pdf", "en.pdf", size=1, sha256="y")
            store.delete_file(row["id"], "zh_pdf")
            store.delete_task(row["id"])
            left = store.conn.execute(
                "SELECT COUNT(*) AS c FROM files WHERE task_id = ?", (row["id"],)
            ).fetchone()
            assert left["c"] == 0
        finally:
            store.close()


class TestInsertChunksTxn:
    """executemany 中途 IntegrityError → rollback：半成品批次不落库。"""

    def test_failed_batch_leaves_no_partial(self, tmp_path: Path) -> None:
        store = _mk_store(tmp_path)
        try:
            row = mk_task_row(store)
            store.insert_chunks(row["id"], [_chunk(0)])
            # 第二批 c0 撞 (task_id, chunk_id) PK——executemany 中途炸
            with pytest.raises(sqlite3.IntegrityError):
                store.insert_chunks(
                    row["id"], [_chunk(1, "c1"), _chunk(2, "c0"), _chunk(3)]
                )
            assert not store.conn.in_transaction, "失败后事务必须已回滚"
            ids = [c["chunk_id"] for c in store.all_chunks(row["id"])]
            assert ids == ["c0"], "半成品批次不得落库（c1 是批次头一行）"
        finally:
            store.close()


class TestSpliceInvalidationArtifacts:
    """``_invalidate_splice`` 摘哨兵 → 派生产物行 + 磁盘件并清。"""

    def _ctx(self, tmp_path: Path) -> tuple[TaskCtx, PipelineWorker, Store]:
        return mk_ctx(tmp_path)

    def _seed_artifacts(self, ctx: TaskCtx, store: Store) -> None:
        """上一轮产物现场：哨兵 + files 行 + 磁盘件。"""
        ctx.zh_dir.mkdir(parents=True)
        (ctx.zh_dir / ".splice-done").write_text("", encoding="utf-8")
        for kind, name in ARTIFACT_FILES:
            (ctx.root / name).write_bytes(b"old")
            store.put_file(ctx.task_id, kind, name, data_dir=ctx.root)

    def _pre_rows(self, store: Store, task_id: str) -> dict[str, tuple[str, str]]:
        return {
            r["chunk_id"]: (str(r["status"]), str(r["translation"] or ""))
            for r in store.all_chunks(task_id)
        }

    def _teardown(
        self,
        worker: PipelineWorker,
        ctx: TaskCtx,
        store: Store,
        pre_rows: dict[str, tuple[str, str]],
    ) -> None:
        asyncio.run(
            worker.run_stage(
                ctx,
                "teardown_translate",
                run_task=None,
                state=DBStateBridge(store, ctx.task_id),
                cache=SegmentCache(store, prefix="t", model="m", target_lang="zh-CN"),
                status_map={},
                sse_items=[],
                usage={"calls": 0},
                clients=[],
                pre_rows=pre_rows,
            )
        )

    def test_changed_rows_purge_stale_artifacts(self, tmp_path: Path) -> None:
        ctx, worker, store = self._ctx(tmp_path)
        try:
            store.insert_chunks(ctx.task_id, [_chunk(0)])
            self._seed_artifacts(ctx, store)
            pre = self._pre_rows(store, ctx.task_id)
            # 本段翻译落盘：c0 pending→ok+译文
            store.update_chunk(
                ctx.task_id,
                "c0",
                {"status": "ok", "translation": "译文", "attempts": 1},
            )
            self._teardown(worker, ctx, store, pre)
            assert not (ctx.zh_dir / ".splice-done").exists()
            stale = [(k, n) for k, n in ARTIFACT_FILES if k not in _SPLICE_KEPT]
            for kind, _name in stale:
                assert store.file_record(ctx.task_id, kind) is None, kind
            for _kind, name in stale:
                assert not (ctx.root / name).exists(), name
            # en_pdf（base/ 编译）与 src_tar 不依赖 chunks——保留
            assert store.file_record(ctx.task_id, "en_pdf") is not None
            assert store.file_record(ctx.task_id, "src_tar") is not None
            assert (ctx.root / "en.pdf").is_file()
            assert (ctx.root / "src.tar").is_file()
        finally:
            store.close()

    def test_unchanged_rows_keep_everything(self, tmp_path: Path) -> None:
        ctx, worker, store = self._ctx(tmp_path)
        try:
            store.insert_chunks(ctx.task_id, [_chunk(0)])
            self._seed_artifacts(ctx, store)
            pre = self._pre_rows(store, ctx.task_id)
            self._teardown(worker, ctx, store, pre)
            assert (ctx.zh_dir / ".splice-done").is_file()
            assert store.file_record(ctx.task_id, "zh_pdf") is not None
            assert (ctx.root / "zh.pdf").is_file()
        finally:
            store.close()


class TestRetryMainChangeCleanup:
    """``POST retry`` 换 main：chunks + 目录 + 派生产物行/磁盘件全清。"""

    def _seed(
        self, client: TestClient, store: Store, tmp_path: Path
    ) -> tuple[str, Path]:
        """fault 任务 + main_tex + 全量产物行/磁盘件 + chunks + 哨兵。"""
        tid = new_task_id()

        async def setup() -> None:
            mk_task_row(store, task_id=tid, arxiv_id="2401.00001")
            store.update_fields(tid, main_tex="main.tex")
            store.insert_chunks(tid, [_chunk(0), _chunk(1)])
            store.transition(tid, "fault", force=True, error={"code": "compile"})

        client.portal.call(setup)
        tdir = tmp_path / "data" / "tasks" / tid
        (tdir / "src").mkdir(parents=True)
        (tdir / "src" / ".fetch-done").write_text("", encoding="utf-8")
        (tdir / "base").mkdir()
        (tdir / "zh").mkdir()
        (tdir / "build-en").mkdir()
        (tdir / "build-zh").mkdir()

        async def register() -> None:
            for kind, name in ARTIFACT_FILES:
                (tdir / name).write_bytes(b"old")
                store.put_file(tid, kind, name, data_dir=tdir)

        client.portal.call(register)
        return tid, tdir

    def test_body_main_purges_artifacts(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        store = client.app.state.store
        tid, tdir = self._seed(client, store, tmp_path)
        r = client.post(f"/api/task/{tid}/retry", json={"main": "other.tex"})
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        # retry 清全部非 src_tar 产物行/磁盘件——断言随 ARTIFACT_FILES 派生
        purged = [(k, n) for k, n in ARTIFACT_FILES if k != "src_tar"]

        async def inspect() -> None:
            assert store.all_chunks(tid) == []
            for kind, _name in purged:
                assert store.file_record(tid, kind) is None, kind
            assert store.file_record(tid, "src_tar") is not None
            assert store.get(tid)["status"] == "queued"
            opts = json.loads(str(store.get(tid)["options_json"]))
            assert opts["main"] == "other.tex"

        client.portal.call(inspect)
        for _kind, name in purged:
            assert not (tdir / name).exists(), name
        assert (tdir / "src.tar").is_file()
        assert (tdir / "src" / ".fetch-done").is_file()
        for d in ("base", "zh", "build-en", "build-zh"):
            assert not (tdir / d).exists(), d
        # files API 不再发旧 en.pdf
        assert client.get(f"/api/files/{tid}/en.pdf").status_code == (
            HTTPStatus.NOT_FOUND
        )

    def test_options_main_same_cleanup(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """``options.main`` 与 body.main 同口径——绕不过清理面。"""
        store = client.app.state.store
        tid, tdir = self._seed(client, store, tmp_path)
        r = client.post(
            f"/api/task/{tid}/retry", json={"options": {"main": "other.tex"}}
        )
        assert r.status_code == HTTPStatus.ACCEPTED, r.text

        async def inspect() -> None:
            assert store.all_chunks(tid) == []
            assert store.file_record(tid, "en_pdf") is None
            opts = json.loads(str(store.get(tid)["options_json"]))
            assert opts["main"] == "other.tex"

        client.portal.call(inspect)
        assert not (tdir / "en.pdf").exists()

    def test_same_main_no_cleanup(self, client: TestClient, tmp_path: Path) -> None:
        """main 未变（与 resolved main_tex 同值）→ 一切保留。"""
        store = client.app.state.store
        tid, tdir = self._seed(client, store, tmp_path)
        r = client.post(f"/api/task/{tid}/retry", json={"main": "main.tex"})
        assert r.status_code == HTTPStatus.ACCEPTED, r.text

        async def inspect() -> None:
            assert len(store.all_chunks(tid)) == 2  # noqa: PLR2004 -- 两块种子
            assert store.file_record(tid, "zh_pdf") is not None

        client.portal.call(inspect)
        assert (tdir / "zh.pdf").is_file()
        assert (tdir / "base").is_dir()


class TestReaderDualGate:
    """reader 以 dual_json 登记行为准——磁盘孤儿件不服务。"""

    def test_orphan_dual_json_404(self, client: TestClient, tmp_path: Path) -> None:
        store = client.app.state.store
        tid = new_task_id()

        async def setup() -> None:
            mk_task_row(store, task_id=tid)
            store.transition(tid, "done", force=True)

        client.portal.call(setup)
        tdir = tmp_path / "data" / "tasks" / tid
        tdir.mkdir(parents=True)
        (tdir / "dual.json").write_text('{"documents": {}}', encoding="utf-8")
        r = client.get(f"/api/task/{tid}/reader")
        assert r.status_code == HTTPStatus.NOT_FOUND
        # 登记后同盘件正常服务
        client.portal.call(partial(store.put_file, tid, "dual_json", "dual.json"))
        r = client.get(f"/api/task/{tid}/reader")
        assert r.status_code == HTTPStatus.OK


class TestStreamDeletedTask:
    """任务行已删的 ``stream``——重放空、行缺席 → 不 parked。"""

    def test_stream_returns_for_missing_row(self, tmp_path: Path) -> None:
        store = _mk_store(tmp_path)
        try:
            bus = EventBus(store)

            async def drive() -> list[dict]:
                return [ev async for ev in bus.stream("t_" + "0" * 16)]

            got = asyncio.run(asyncio.wait_for(drive(), timeout=2.0))
            assert got == []
        finally:
            store.close()


class TestOptIntClamp:
    """``_opt_int`` ≤0 钳位——qps 等旋钮下游无 ``__post_init__`` 兜底。"""

    def test_zero_negative_and_junk(self, tmp_path: Path) -> None:
        store = _mk_store(tmp_path)
        try:
            bus = EventBus(store)
            worker = PipelineWorker(store, bus, tmp_path)
            row = mk_task_row(store)
            ctx = TaskCtx(
                store=store,
                bus=bus,
                task_id=row["id"],
                row=row,
                secrets=Secrets(),
                root=tmp_path / "tasks" / row["id"],
            )
            opt_int = worker._opt_int  # noqa: SLF001 -- 单测直驱
            dft, good = 4, 9
            # 0/None/缺席走 falsy→默认；负值与 "0" 串钳 1；正常值透传
            assert opt_int(ctx, {"qps": 0}, "qps", dft) == dft
            assert opt_int(ctx, {}, "qps", dft) == dft
            assert opt_int(ctx, {"qps": -7}, "qps", dft) == 1
            assert opt_int(ctx, {"qps": "0"}, "qps", dft) == 1
            assert opt_int(ctx, {"qps": "abc"}, "qps", dft) == dft
            assert opt_int(ctx, {"qps": good}, "qps", dft) == good
            # 钳位/非数值路径落 bad_option 告警事件（可观测性）
            evs = store.events_since(row["id"], 0)
            warns = [
                e
                for e in evs
                if e["type"] == "warning" and e["data"].get("code") == "bad_option"
            ]
            assert len(warns) == 3  # noqa: PLR2004 -- -7/"0"/"abc" 三条
        finally:
            store.close()
