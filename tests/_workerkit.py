"""worker 测试公共骨架——``mk_ctx`` 五件套 + ``scan_base`` 解析直通。

``PipelineWorker`` 段级直调面（``run_stage`` 前门）的配套 harness：
Store+EventBus+PipelineWorker+真实任务行+TaskCtx 一次装配。原
``test_worker_audit_fixes``/``test_fuzz_worker``/``test_worker_term_dict``
三处同构 ``_mk``/``_scan`` 归此一处；异形 ctx（raw row dict、_NullBus、
api_key Secrets 等 per-test 定制）仍留各文件本地。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conftest import mk_task_row

from texlate.server.events import EventBus
from texlate.server.store import Store
from texlate.server.worker import PipelineWorker, Secrets, TaskCtx

if TYPE_CHECKING:
    from pathlib import Path


def mk_ctx(
    tmp_path: Path,
    *,
    options: dict[str, object] | None = None,
    worker_kw: dict[str, object] | None = None,
    task_kw: dict[str, object] | None = None,
) -> tuple[TaskCtx, PipelineWorker, Store]:
    """真实任务行 + TaskCtx + worker（段级直调面；conn 在主线程）。"""
    store = Store(tmp_path / "t.db")
    store.open()
    bus = EventBus(store)
    worker = PipelineWorker(store, bus, tmp_path, **(worker_kw or {}))  # type: ignore[arg-type]
    row = mk_task_row(
        store, arxiv_id="2401.00001", options=options or {}, **(task_kw or {})
    )
    ctx = TaskCtx(
        store=store,
        bus=bus,
        task_id=str(row["id"]),
        row=row,
        secrets=Secrets(),
        root=tmp_path / "tasks" / str(row["id"]),
    )
    return ctx, worker, store


def scan_base(ctx: TaskCtx, worker: PipelineWorker, store: Store, tex: str) -> None:
    """main.tex 落 ``base/`` + ``run_stage parse_all`` 真解析 + chunks 入库。"""
    ctx.base_dir.mkdir(parents=True, exist_ok=True)
    (ctx.base_dir / "main.tex").write_text(tex, encoding="utf-8")
    rows, ctx.scans = worker.run_stage(ctx, "parse_all")
    store.insert_chunks(ctx.task_id, rows)
