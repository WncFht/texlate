"""终态任务重试时恢复源码树，保留已有译文。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from _drivekit import drive
from _workerkit import mk_ctx
from conftest import MINI_TEX

from texlate.server._common import slim_terminal_tasks
from texlate.server.worker._common import _StageError

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.server.store import Store
    from texlate.server.worker import PipelineWorker, TaskCtx


class NoModelCalls:
    """恢复已完成的块时，任何模型调用都使测试失败。"""

    async def translate(self, **_kwargs: object) -> str:
        pytest.fail("resume must not make another model call")


def prepared_task(tmp_path: Path) -> tuple[TaskCtx, PipelineWorker, Store]:
    ctx, worker, store = mk_ctx(
        tmp_path,
        task_kw={"kind": "upload_tex"},
        options={"auto_glossary": False, "env_judge": False, "logfix": False},
        worker_kw={"translator_factory": lambda _ctx: NoModelCalls()},
    )
    upload = ctx.root / "upload"
    upload.mkdir(parents=True)
    (upload / "main.tex").write_text(MINI_TEX, encoding="utf-8")
    drive(worker, worker.run_stage(ctx, "stage_fetch"))
    drive(worker, worker.run_stage(ctx, "stage_parse"))
    for row in store.all_chunks(ctx.task_id):
        store.update_chunk(
            ctx.task_id,
            row["chunk_id"],
            {
                "status": "ok",
                "translation": "这是已经完成并应当保留的中文译文。",
                "attempts": 1,
            },
        )
    store.conn.commit()
    return ctx, worker, store


@pytest.mark.parametrize("terminal", ["cancelled", "fault"])
def test_retry_after_slim_restores_base_and_keeps_translations(
    tmp_path: Path, terminal: str
) -> None:
    ctx, worker, store = prepared_task(tmp_path)
    saved = store.all_chunks(ctx.task_id)
    store.transition(ctx.task_id, terminal, force=True)
    slimmed, _ = asyncio.run(slim_terminal_tasks(store, ctx.root.parent, skip=set()))
    assert slimmed == 1
    assert not ctx.src_dir.exists()
    assert not ctx.base_dir.exists()
    store.transition(ctx.task_id, "queued")
    resumed = replace(ctx, row=store.get(ctx.task_id), scans={}, chunks_cache=None)

    async def replay() -> None:
        await worker.run_stage(resumed, "stage_fetch")
        await worker.run_stage(resumed, "stage_parse")
        assert (resumed.base_dir / ".base-done").is_file()
        assert resumed.scans
        await worker.run_stage(resumed, "stage_translate")
        await asyncio.to_thread(worker._build_zh, resumed)  # noqa: SLF001 -- 覆盖真实 splice 路径

    drive(worker, replay())
    assert store.all_chunks(ctx.task_id) == saved
    assert (resumed.zh_dir / "main.tex").is_file()
    assert "这是已经完成" in (resumed.zh_dir / "main.tex").read_text(encoding="utf-8")


@pytest.mark.parametrize("mutation", ["text", "span", "missing"])
def test_resume_refuses_mismatched_source_without_replacing_chunks(
    tmp_path: Path, mutation: str
) -> None:
    ctx, worker, store = prepared_task(tmp_path)
    saved = store.all_chunks(ctx.task_id)
    source = ctx.base_dir / "main.tex"
    text = source.read_text(encoding="utf-8")
    if mutation == "text":
        source.write_text(text.replace("longer", "shorty"), encoding="utf-8")
    elif mutation == "span":
        source.write_text("% shifted\n" + text, encoding="utf-8")
    else:
        source.unlink()
    resumed = replace(ctx, scans={}, chunks_cache=None)
    with pytest.raises(_StageError, match="saved chunks"):
        drive(worker, worker.run_stage(resumed, "stage_parse"))
    assert store.all_chunks(ctx.task_id) == saved
    assert not resumed.scans


@pytest.mark.parametrize("mutation", ["text", "span"])
def test_rebuilt_source_mismatch_preserves_paid_chunks(
    tmp_path: Path, mutation: str
) -> None:
    ctx, worker, store = prepared_task(tmp_path)
    saved = store.all_chunks(ctx.task_id)
    store.transition(ctx.task_id, "fault", force=True)
    asyncio.run(slim_terminal_tasks(store, ctx.root.parent, skip=set()))
    upload = ctx.root / "upload" / "main.tex"
    text = upload.read_text(encoding="utf-8")
    changed = (
        text.replace("longer", "shorty") if mutation == "text" else "% shifted\n" + text
    )
    upload.write_text(changed, encoding="utf-8")
    store.transition(ctx.task_id, "queued")
    resumed = replace(ctx, row=store.get(ctx.task_id), scans={}, chunks_cache=None)
    drive(worker, worker.run_stage(resumed, "stage_fetch"))
    with pytest.raises(_StageError, match="saved chunks"):
        drive(worker, worker.run_stage(resumed, "stage_parse"))
    assert store.all_chunks(ctx.task_id) == saved
    assert not resumed.scans
