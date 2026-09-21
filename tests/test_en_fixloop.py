"""``_compile_en`` 的 fixloop 救援臂：原文编译不出 pdf → 同一 fixloop 引擎修基建。

``t_74d635d226e68251``（2609.18207v1）实证：algpseudocodex.sty 未装让
**双侧**编译同挂——zh 侧有 L2 豁免 + fixloop install 救回，en 侧此前
裸编无救援，en.pdf 缺席令 reader 只剩译文栏。``_task_texmf`` 的任务级
共享装件树让 en/zh 装件互见，en 臂 ``cond="en"`` 沉淀 cases；修复只动
``build-en`` 一次性树——``base/`` 是 zh 重建与 baseline 的 pristine 源，
不回灌、不占 ``ctx.fixloop`` 归账位。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")

from conftest import RecordingEngine

from texlate.server.events import EventBus
from texlate.server.store import Store, new_task_id
from texlate.server.worker import PipelineWorker, Secrets, TaskCtx

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_TEX = (
    "\\documentclass{article}\n"
    "\\usepackage{algpseudocodex}\n"
    "\\begin{document}\n"
    "Body paragraph long enough to matter.\n"
    "\\end{document}\n"
)


def _fixloop_spy() -> tuple[list[object], Callable[..., dict[str, object]]]:
    """fixloop 调用探针：``(calls, stub)``——断言臂自熄/首编通过时零调用。"""
    calls: list[object] = []

    def _spy(*_a: object, **_kw: object) -> dict[str, object]:
        calls.append(1)
        return {}

    return calls, _spy


def _mk(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    *,
    options: dict[str, object] | None = None,
    engine: RecordingEngine | None = None,
) -> tuple[TaskCtx, PipelineWorker, Store]:
    """最小 TaskCtx + worker：真 Store/EventBus + RecordingEngine 注入。"""
    store = Store(tmp_path / "t.db")
    store.open()
    request.addfinalizer(store.close)
    bus = EventBus(store)
    eng = engine or RecordingEngine("tectonic")
    worker = PipelineWorker(store, bus, tmp_path, engine_factory=lambda _name: eng)  # type: ignore[arg-type]
    task_id = new_task_id()
    row = store.create_task(
        task_id=task_id,
        kind="arxiv",
        target_lang="zh-CN",
        model="m",
        arxiv_id="2609.18207",
        options=options or {},
    )
    ctx = TaskCtx(
        store=store,
        bus=bus,
        task_id=task_id,
        row=row,
        secrets=Secrets(),
        root=tmp_path / "tasks" / task_id,
    )
    ctx.main_rel = "main.tex"
    ctx.engine_name = "tectonic"
    ctx.base_dir.mkdir(parents=True)
    (ctx.base_dir / "main.tex").write_text(_TEX, encoding="utf-8")
    return ctx, worker, store


class TestEnFixloop:
    """en 侧无 pdf → fixloop 臂触发/救回登记/不回灌/不占归账位。"""

    def test_missing_pkg_rescued_and_registered(
        self,
        tmp_path: Path,
        request: pytest.FixtureRequest,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """缺包挂 → fixloop 救回出 pdf → en_pdf 登记 + ``cond="en"`` 透传。"""
        eng = RecordingEngine("tectonic")
        eng.produce_pdf = False  # 首编挂（未装 algpseudocodex）
        ctx, worker, store = _mk(tmp_path, request, engine=eng)
        conds: list[object] = []

        def _stub(work: Path, proxy: object, **kw: object) -> dict[str, object]:
            conds.append(kw.get("cond"))
            eng.produce_pdf = True  # 装上后复编即出
            proxy.compile(work, "main.tex")  # type: ignore[attr-defined]
            return {
                "verdict": "clean",
                "final_pdf": "main.pdf",
                "installed": ["algpseudocodex"],
                "rounds": [],
                "actions": [],
            }

        monkeypatch.setattr("texlate.repair.fixloop", _stub)
        worker._compile_en(ctx)  # noqa: SLF001
        assert conds == ["en"]
        assert (ctx.root / "en.pdf").is_file()
        assert store.file_record(ctx.task_id, "en_pdf") is not None
        # en 臂不占 zh 归账位——``ctx.fixloop`` 只喂 zh 的判据/error_json
        assert ctx.fixloop is None

    def test_fixloop_edits_not_written_back(
        self,
        tmp_path: Path,
        request: pytest.FixtureRequest,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """fixloop 在 build-en 内的改写/落件不泄进 ``base/`` pristine 树。"""
        eng = RecordingEngine("tectonic")
        eng.produce_pdf = False
        ctx, worker, _store = _mk(tmp_path, request, engine=eng)

        def _stub(work: Path, proxy: object, **_kw: object) -> dict[str, object]:
            (work / "algpseudocodex.sty").write_text("% stub\n", encoding="utf-8")
            (work / "main.tex").write_text("% rewritten\n", encoding="utf-8")
            eng.produce_pdf = True
            proxy.compile(work, "main.tex")  # type: ignore[attr-defined]
            return {"verdict": "clean", "final_pdf": "main.pdf", "rounds": []}

        monkeypatch.setattr("texlate.repair.fixloop", _stub)
        worker._compile_en(ctx)  # noqa: SLF001
        assert (ctx.root / "en.pdf").is_file()
        # base/ 保持 pristine——落件与改写都留在 build-en 一次性树
        assert not (ctx.base_dir / "algpseudocodex.sty").exists()
        assert (ctx.base_dir / "main.tex").read_text(encoding="utf-8") == _TEX

    def test_still_no_pdf_warns_only(
        self,
        tmp_path: Path,
        request: pytest.FixtureRequest,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """fixloop 也救不出 → ``en_compile`` warning、无 en_pdf、流程不炸。"""
        eng = RecordingEngine("tectonic")
        eng.produce_pdf = False
        ctx, worker, store = _mk(tmp_path, request, engine=eng)
        monkeypatch.setattr(
            "texlate.repair.fixloop",
            lambda *_a, **_kw: {"verdict": "fail", "rounds": [], "actions": []},
        )
        worker._compile_en(ctx)  # noqa: SLF001
        assert not (ctx.root / "en.pdf").exists()
        assert store.file_record(ctx.task_id, "en_pdf") is None
        assert any(
            e["type"] == "warning" and e["data"]["code"] == "en_compile"
            for e in store.events_since(ctx.task_id, 0)
        )

    def test_fixloop_disabled_no_attempt(
        self,
        tmp_path: Path,
        request: pytest.FixtureRequest,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """``options.fixloop=False`` → 臂自熄，首挂直走 warning。"""
        eng = RecordingEngine("tectonic")
        eng.produce_pdf = False
        ctx, worker, _store = _mk(
            tmp_path, request, engine=eng, options={"fixloop": False}
        )
        calls, _spy = _fixloop_spy()
        monkeypatch.setattr("texlate.repair.fixloop", _spy)
        worker._compile_en(ctx)  # noqa: SLF001
        assert calls == []
        assert not (ctx.root / "en.pdf").exists()

    def test_clean_first_pass_skips_fixloop(
        self,
        tmp_path: Path,
        request: pytest.FixtureRequest,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """首编即出 pdf → 不触发 fixloop（无无谓救援轮）。"""
        ctx, worker, _store = _mk(tmp_path, request)
        calls, _spy = _fixloop_spy()
        monkeypatch.setattr("texlate.repair.fixloop", _spy)
        worker._compile_en(ctx)  # noqa: SLF001
        assert calls == []
        assert (ctx.root / "en.pdf").is_file()
