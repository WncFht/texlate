"""worker 测试公共骨架——``mk_ctx`` 五件套 + ``mk_runner`` TaskRunner 装配 +
``scan_base`` 解析直通 + ``_insert_chunk`` 最小行。

``PipelineWorker`` 段级直调面（``run_stage`` 前门）的配套 harness：
Store+EventBus+PipelineWorker+ 真实任务行+TaskCtx 一次装配。原
``test_worker_audit_fixes``/``test_fuzz_worker``/``test_worker_term_dict``
三处同构 ``_mk``/``_scan`` 归此一处；``_insert_chunk`` 最小行件备此供
worker 道复用（``test_fixloop_live_events``/``test_fuzz_worker`` 已收编；
``test_app_endpoints`` 的 ``client`` 形异形件签名不同，仍本地）。
``mk_runner`` 是 ``TaskRunner(store, bus, worker)`` 一次装配件
（``test_worker_cancel_protocol`` 本地件收编，``worker=`` 形参留予
_HangWorker 类覆写站点）。
异形 ctx（raw row dict、_NullBus、api_key Secrets 等 per-test 定制）
仍留各文件本地。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conftest import mk_task_row

from texlate.server.events import EventBus
from texlate.server.store import Store
from texlate.server.worker import PipelineWorker, Secrets, TaskCtx, TaskRunner

if TYPE_CHECKING:
    from pathlib import Path


def mk_ctx(
    tmp_path: Path,
    *,
    options: dict[str, object] | None = None,
    worker_kw: dict[str, object] | None = None,
    task_kw: dict[str, object] | None = None,
) -> tuple[TaskCtx, PipelineWorker, Store]:
    """真实任务行 + TaskCtx + worker（段级直调面；conn 在主线程）。

    ``task_kw`` 透传 ``mk_task_row`` 并可覆盖钉定字段（``arxiv_id``/``options``）。
    """
    store = Store(tmp_path / "t.db")
    store.open()
    bus = EventBus(store)
    worker = PipelineWorker(store, bus, tmp_path, **(worker_kw or {}))  # type: ignore[arg-type]
    row_kw = {"arxiv_id": "2401.00001", "options": options or {}}
    row_kw.update(task_kw or {})
    row = mk_task_row(store, **row_kw)
    ctx = TaskCtx(
        store=store,
        bus=bus,
        task_id=str(row["id"]),
        row=row,
        secrets=Secrets(),
        root=tmp_path / "tasks" / str(row["id"]),
    )
    return ctx, worker, store


def mk_runner(
    store: Store,
    tmp_path: Path,
    *,
    worker: PipelineWorker | None = None,
    bus: EventBus | None = None,
) -> TaskRunner:
    """``TaskRunner(store, bus, worker)`` 一次装配——缺省自造
    EventBus/PipelineWorker；传入既有 worker 时共 bus（生产 app.py 同 wiring）。"""
    bus = bus or EventBus(store)
    worker = worker or PipelineWorker(store, bus, tmp_path)
    return TaskRunner(store, bus, worker)


def scan_base(ctx: TaskCtx, worker: PipelineWorker, store: Store, tex: str) -> None:
    """main.tex 落 ``base/`` + ``run_stage parse_all`` 真解析 + chunks 入库。"""
    ctx.base_dir.mkdir(parents=True, exist_ok=True)
    (ctx.base_dir / "main.tex").write_text(tex, encoding="utf-8")
    rows, ctx.scans = worker.run_stage(ctx, "parse_all")
    store.insert_chunks(ctx.task_id, rows)


def _insert_chunk(  # noqa: PLR0913
    store: Store,
    task_id: str,
    chunk_id: str = "c1",
    *,
    seq: int = 0,
    src: str = "hello world",
    status: str = "pending",
) -> None:
    """最小 chunks 行（``insert_chunks`` 合法面），status 非 pending 走 update。"""
    store.insert_chunks(
        task_id,
        [
            {
                "chunk_id": chunk_id,
                "seq": seq,
                "src_file": "main.tex",
                "src_text": src,
                "kind": "para",
                "byte_start": 0,
                "byte_end": len(src),
            }
        ],
    )
    if status != "pending":
        # update_chunk 契约是 flush 事务内复用不 commit——测试侧补 commit 收尾
        store.update_chunk(task_id, chunk_id, {"status": status})
        store.conn.commit()
