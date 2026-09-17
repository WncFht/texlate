"""server 链 term_dict 落盘钉：``DBStateBridge.save_maps`` → ``export-state/term_dict.json``。

bench ``stage_xlat`` 的 save_maps 观测件在 server 路的等价物——translating
段收工后，文档级术语表（``pipe._doc_glossary``）须物化到任务目录供审计。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("fastapi", reason="server extra 未装")

from texlate.server.events import EventBus
from texlate.server.store import Store, new_task_id
from texlate.server.worker import (
    DBStateBridge,
    PipelineWorker,
    Secrets,
    TaskCtx,
)
from texlate.xlat.pipeline import MockTranslator

_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "A paragraph that has inline math $x+y$ and a command \\alpha that "
    "sits inside the prose.\n"
    "\n"
    "Second paragraph that pads the document body and fills it with the "
    "text that was written for this purpose.\n"
    "\\end{document}\n"
)


def _mk(
    tmp_path: Path, *, worker_kw: dict[str, object] | None = None
) -> tuple[TaskCtx, PipelineWorker, Store]:
    """真实任务行 + TaskCtx + worker（stage 级直调面；conn 在主线程）。"""
    store = Store(tmp_path / "t.db")
    store.open()
    bus = EventBus(store)
    worker = PipelineWorker(store, bus, tmp_path, **(worker_kw or {}))  # type: ignore[arg-type]
    task_id = new_task_id()
    row = store.create_task(
        task_id=task_id,
        kind="arxiv",
        target_lang="zh-CN",
        model="m",
        arxiv_id="2401.00001",
        options={},
    )
    ctx = TaskCtx(
        store=store,
        bus=bus,
        task_id=task_id,
        row=row,
        secrets=Secrets(),
        root=tmp_path / "tasks" / task_id,
    )
    return ctx, worker, store


def _scan(ctx: TaskCtx, worker: PipelineWorker, store: Store, tex: str) -> None:
    """main.tex 落 ``base/`` + 真解析 + chunks 入库。"""
    ctx.base_dir.mkdir(parents=True, exist_ok=True)
    (ctx.base_dir / "main.tex").write_text(tex, encoding="utf-8")
    rows, ctx.scans = worker._parse_all(ctx)  # noqa: SLF001 -- 单测直驱
    store.insert_chunks(ctx.task_id, rows)


class TestSaveMapsBridge:
    """``DBStateBridge.save_maps`` 单元面：三表写 ``state_dir``，未接线空操作。"""

    def test_term_dict_lands(self, tmp_path: Path) -> None:
        store = Store(tmp_path / "t.db")
        store.open()
        out = tmp_path / "tasks" / "t1" / "export-state"
        state = DBStateBridge(store, "t1", state_dir=out)
        state.save_maps(term_dict={"alpha": "阿尔法"})
        doc = json.loads((out / "term_dict.json").read_text(encoding="utf-8"))
        assert doc == {"alpha": "阿尔法"}

    def test_no_state_dir_is_noop(self, tmp_path: Path) -> None:
        store = Store(tmp_path / "t.db")
        store.open()
        state = DBStateBridge(store, "t1")  # 旧构造形态——无落盘面
        state.save_maps(term_dict={"a": "b"})  # 不抛即约
        assert not (tmp_path / "tasks").exists()


class TestStageTranslateTermDict:
    """``_stage_translate`` 收工点：pipe._doc_glossary → export-state/term_dict.json。"""

    def test_term_dict_persisted(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        ctx, worker, store = _mk(
            tmp_path, worker_kw={"translator_factory": lambda _c: MockTranslator()}
        )
        _scan(ctx, worker, store, _TEX)
        asyncio.run(worker._stage_translate(ctx))  # noqa: SLF001
        out = ctx.root / "export-state" / "term_dict.json"
        assert out.is_file()
        term_dict = json.loads(out.read_text(encoding="utf-8"))
        # 占位符恒等注入无条件进 doc_filter 尾部——$x+y$ 的 [[MATH_*]] 必在
        assert any(k.startswith("[[MATH_") and term_dict[k] == k for k in term_dict)

    def test_no_glossary_still_no_crash(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """glossary=None 臂不落盘也不毁段（bench 的 ``if glossary is not None`` 守卫同式）。"""
        ctx, worker, store = _mk(
            tmp_path, worker_kw={"translator_factory": lambda _c: MockTranslator()}
        )
        _scan(ctx, worker, store, _TEX)
        monkeypatch.setattr(
            PipelineWorker, "_make_glossary", lambda _self, _ctx, **_kw: None
        )
        asyncio.run(worker._stage_translate(ctx))  # noqa: SLF001
        assert not (ctx.root / "export-state" / "term_dict.json").exists()
        # 段照常收工——chunks 全 ok
        counts = store.chunk_counts(ctx.task_id)
        assert counts["total"] > 0
        assert counts["done"] == counts["total"]
