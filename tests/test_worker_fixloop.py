"""worker fixloop 道钉样：``reject:*`` → partial+reject_at、跨引擎臂、
``_run_fixloop`` 接线（compile_timeout 透传 / halt_on_error 旋钮 / ResProxy 包装）。

自 test_worker_audit_fixes.py 切出（TestFixloopFix + TestRunFixloopWiring）。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from _drivekit import drive
from _workerkit import mk_ctx
from conftest import MINI_TEX, RecordingEngine

import texlate.repair as repair_mod
import texlate.server.worker as worker_mod
from texlate.compile.engine import CompRes, LogInfo
from texlate.server.store import ERROR_CODES

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from texlate.server.store import Store
    from texlate.server.worker import PipelineWorker, TaskCtx


def _prime_terminal_compile(
    ctx: TaskCtx, store: Store, cell: dict[str, object]
) -> None:
    """终态分派哨兵旁路：splice/compile 产物预置 + 登记，直抵 ``stage_compile`` 终判。"""
    ctx.main_rel = "main.tex"
    ctx.engine_name = "tectonic"
    ctx.base_dir.mkdir(parents=True, exist_ok=True)
    ctx.zh_dir.mkdir(parents=True, exist_ok=True)
    (ctx.zh_dir / ".splice-done").write_text("", encoding="utf-8")
    (ctx.zh_dir / ".compile-done").write_text("", encoding="utf-8")
    (ctx.root / "zh.pdf").write_bytes(b"%PDF-1.4 fake")
    (ctx.root / "en.pdf").write_bytes(b"%PDF-1.4 fake")
    store.put_file(ctx.task_id, "zh_pdf", "zh.pdf", data_dir=ctx.root)
    store.put_file(ctx.task_id, "en_pdf", "en.pdf", data_dir=ctx.root)
    ctx.fixloop = cell


def _engine_pair() -> tuple[RecordingEngine, RecordingEngine, dict[str, object]]:
    """xelatex/tectonic 双 RecordingEngine + 路由 ``engine_factory`` 的 worker_kw。"""
    xeng = RecordingEngine("xelatex")
    teng = RecordingEngine("tectonic")

    def factory(name: str, **_kw: object) -> RecordingEngine:
        return {"xelatex": xeng, "tectonic": teng}[name]

    return xeng, teng, {"engine_factory": factory}


def _cross_engine_ctx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cell: dict[str, object],
    *,
    worker_kw: dict[str, object] | None = None,
) -> tuple[TaskCtx, PipelineWorker, Path, CompRes]:
    """跨引擎臂公共布景：tectonic→xelatex 路由 options + 双 main.tex + cell 钉。"""
    ctx, worker, _store = mk_ctx(
        tmp_path,
        options={
            "engine_resolved": "tectonic",
            "route_engines": ["tectonic", "xelatex"],
        },
        worker_kw=worker_kw,
    )
    ctx.main_rel = "main.tex"
    ctx.engine_name = "tectonic"
    work = ctx.root / "build-zh"
    work.mkdir(parents=True)
    ctx.zh_dir.mkdir(parents=True)
    (work / "main.tex").write_text(MINI_TEX, encoding="utf-8")
    (ctx.zh_dir / "main.tex").write_text(MINI_TEX, encoding="utf-8")
    monkeypatch.setattr("texlate.repair.fixloop", lambda *_a, **_kw: cell)
    first = CompRes(engine="tectonic", ok=True, pdf=None, log=LogInfo(n_errors=2))
    return ctx, worker, work, first


class TestFixloopFix:
    """Fix5：``reject:*`` verdict → partial+reject_at；engine_flags 跨引擎臂。"""

    def test_fixloop_reject_maps_partial(self, tmp_path: Path) -> None:
        assert "fixloop_reject" in ERROR_CODES
        ctx, worker, store = mk_ctx(tmp_path)
        _prime_terminal_compile(ctx, store, {"verdict": "reject:r42", "trace": []})
        drive(worker, worker.run_stage(ctx, "stage_compile"))
        row = store.get(ctx.task_id)
        assert row["status"] == "partial"
        err = json.loads(str(row["error_json"]))
        assert err["code"] == "fixloop_reject"
        assert err["reject_at"] == "fixloop"
        assert err["fixloop"]["verdict"] == "reject:r42"

    def test_fixloop_cross_engine_arm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """dropped flags + tectonic + xelatex 候选 + verdict<clean → xelatex 重编取优。"""
        xeng, teng, worker_kw = _engine_pair()
        ctx, worker, work, first = _cross_engine_ctx(
            tmp_path,
            monkeypatch,
            {
                "verdict": "fail",
                "engine_flags": ["-shell-escape"],
                "engine_flags_dropped": ["-shell-escape"],
                "rounds": [],
                "actions": [],
            },
            worker_kw=worker_kw,
        )
        res = worker.run_stage(ctx, "run_fixloop", work, teng, first)
        assert xeng.calls, "xelatex 跨引擎臂应被触发"
        assert xeng.calls[0]["flags"] == ["-shell-escape"]
        assert res.engine == "xelatex"  # clean/partial > fail → 取优换臂
        assert ctx.fixloop is not None
        assert ctx.fixloop["engine_flags_dropped"] == ["-shell-escape"]
        assert ctx.fixloop["cross_engine"]["engine"] == "xelatex"

    def test_fixloop_cross_engine_halt_on_error_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cross_engine_retry 臂 xelatex 构造 ``halt_on_error=False``（2026-09-17 裁决口径）。

        retry 是 fixloop 结束后的交付路径终末重编——与主编译/salvage
        同属 best-effort 族，nonstopmode 续跑才能把 incumbent=fail 的树
        救成 partial；``-halt-on-error`` 首错即停会让唯一 rescue 窗失效
        （b8-e2e 裁决）。无 ``engine_factory``
        时经 ``engine_for`` 真路径构造，钉住旋钮方向。
        """
        built: list[dict[str, object]] = []

        def fake_engine_for(name: str, **kw: object) -> RecordingEngine:
            built.append({"name": name, **kw})
            return RecordingEngine(name)

        ctx, worker, work, first = _cross_engine_ctx(
            tmp_path,
            monkeypatch,
            {
                "verdict": "fail",
                "engine_flags": ["-shell-escape"],
                "engine_flags_dropped": ["-shell-escape"],
                "rounds": [],
                "actions": [],
            },
        )
        monkeypatch.setattr("texlate.server.worker.seams.engine_for", fake_engine_for)
        res = worker.run_stage(
            ctx, "run_fixloop", work, RecordingEngine("tectonic"), first
        )
        assert {"name": "xelatex", "halt_on_error": False} in built
        assert res.engine == "xelatex"  # 救回 partial/clean > fail → adopted

    def test_fixloop_reject_route_cross_engine_arm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``reject_route=xelatex`` cell 令牌 → 无 dropped flag 也换臂。

        t_c9249919e8d7a13f 实证面：biber/biblatex bcf 错配是 tectonic
        bundle 内无解的工具链硬墙——``verdict reject:*`` rank 0，xelatex
        任何 ≥fail 判定即 adopted，死路标签变真路由。
        """
        xeng, teng, worker_kw = _engine_pair()
        ctx, worker, work, first = _cross_engine_ctx(
            tmp_path,
            monkeypatch,
            {
                "verdict": "reject:biber_biblatex_skew_route",
                "reject_route": "xelatex",
                "engine_flags": [],
                "engine_flags_dropped": [],
                "rounds": [],
                "actions": [],
            },
            worker_kw=worker_kw,
        )
        res = worker.run_stage(ctx, "run_fixloop", work, teng, first)
        assert xeng.calls, "xelatex 跨引擎臂应被触发"
        assert res.engine == "xelatex"  # reject rank 0 → 任何 ≥fail 判定即 adopted
        assert ctx.fixloop is not None
        assert ctx.fixloop["reject_route"] == "xelatex"
        assert ctx.fixloop["cross_engine"]["adopted"] is True

    def test_fixloop_reject_adopted_skips_policy_reject(self, tmp_path: Path) -> None:
        """``cross_engine.adopted`` 时 reject verdict 让位实际产物判定 → done。

        _stage_compile 的 reject 短路只挡「未换臂」的死路拒绝；换编被采用
        代表终态已按 xelatex 复判取优，策略标签不应盖掉真实产物。
        """
        ctx, worker, store = mk_ctx(tmp_path)
        _prime_terminal_compile(
            ctx,
            store,
            {
                "verdict": "reject:biber_biblatex_skew_route",
                "reject_route": "xelatex",
                "cross_engine": {"engine": "xelatex", "adopted": True},
                "trace": [],
            },
        )
        drive(worker, worker.run_stage(ctx, "stage_compile"))
        row = store.get(ctx.task_id)
        assert row["status"] == "done"


class TestRunFixloopWiring:
    """``_run_fixloop`` 把 ``compile_timeout`` 带给 fixloop（e2e parity）。"""

    def test_compile_timeout_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        timeout = 7.5
        ctx, worker, _store = mk_ctx(tmp_path, worker_kw={"compile_timeout": timeout})
        captured: dict[str, object] = {}

        def fake_fixloop(*_a: object, **kw: object) -> dict:
            captured.update(kw)
            return {"verdict": "clean", "rounds": [], "actions": []}

        monkeypatch.setattr("texlate.repair.fixloop", fake_fixloop)
        work = tmp_path / "build-zh"
        work.mkdir()
        first = object()
        out = worker.run_stage(  # run_stage 直驱
            ctx,
            "run_fixloop",
            work,
            RecordingEngine("tectonic"),
            first,  # type: ignore[arg-type]
        )
        assert captured["compile_timeout"] == timeout
        assert out is first

    def test_summary_carries_log_excerpt(self) -> None:
        cell = {
            "verdict": "dirty_pdf",
            "main": "main.tex",
            "rounds": [
                {
                    "round": 1,
                    "category": "font",
                    "payload": "x",
                    "pdf": True,
                    "n_errors": 2,
                }
            ],
            "actions": [{"round": 1, "rule": "r1", "detail": "patched"}],
            "log_excerpt": "! error context tail",
        }
        s = worker_mod._fixloop_summary(cell)  # noqa: SLF001
        assert s["log_excerpt"] == "! error context tail"
        assert s["trace"][0]["rule"] == "r1"

    def test_xelatex_fixloop_halt_on_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """fixloop 轮内 xelatex 独立构造 ``halt_on_error=True``（e2e 权威口径）。

        主编译引擎是 best-effort nonstopmode（False）——续跑日志会让
        post-fix 复判混入下游错误、分类签名漂移，故不复用传入引擎。
        """
        ctx, worker, _store = mk_ctx(tmp_path)
        ctx.engine_name = "xelatex"
        built: list[dict[str, object]] = []

        def fake_engine_for(name: str, **kw: object) -> RecordingEngine:
            built.append({"name": name, **kw})
            return RecordingEngine(name)

        captured: dict[str, object] = {}

        def fake_fixloop(_w: object, eng: object, **_kw: object) -> dict:
            captured["eng"] = eng
            return {"verdict": "clean", "rounds": [], "actions": []}

        monkeypatch.setattr(worker_mod.seams, "engine_for", fake_engine_for)
        monkeypatch.setattr("texlate.repair.fixloop", fake_fixloop)
        work = tmp_path / "build-zh"
        work.mkdir()
        main_eng = RecordingEngine("xelatex")
        worker.run_stage(ctx, "run_fixloop", work, main_eng, object())
        assert built == [{"name": "xelatex", "halt_on_error": True}]
        rec = captured["eng"]
        assert isinstance(rec, repair_mod.ResProxy)
        assert rec._inner is not main_eng  # noqa: SLF001

    def test_tectonic_fixloop_reuses_passed_engine(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """tectonic 无 halt_on_error 旋钮——fixloop 仍用传入引擎，不重建。"""
        ctx, worker, _store = mk_ctx(tmp_path)
        captured: dict[str, object] = {}

        def fake_fixloop(_w: object, eng: object, **_kw: object) -> dict:
            captured["eng"] = eng
            return {"verdict": "clean", "rounds": [], "actions": []}

        def forbidden(*_a: object, **_kw: object) -> None:
            raise AssertionError

        monkeypatch.setattr("texlate.repair.fixloop", fake_fixloop)
        monkeypatch.setattr(worker_mod.seams, "engine_for", forbidden)
        work = tmp_path / "build-zh"
        work.mkdir()
        main_eng = RecordingEngine("tectonic")
        worker.run_stage(ctx, "run_fixloop", work, main_eng, object())
        rec = captured["eng"]
        assert rec._inner is main_eng  # noqa: SLF001

    def test_xelatex_fixloop_respects_engine_factory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``engine_factory`` 在场时 fixloop xelatex 引擎也走注入面（不经 engine_for）。"""
        made: list[str] = []
        ctx, worker, _store = mk_ctx(
            tmp_path,
            worker_kw={
                "engine_factory": lambda name: (
                    made.append(name) or RecordingEngine(name)
                )
            },
        )
        ctx.engine_name = "xelatex"
        captured: dict[str, object] = {}

        def fake_fixloop(_w: object, eng: object, **_kw: object) -> dict:
            captured["eng"] = eng
            return {"verdict": "clean", "rounds": [], "actions": []}

        def forbidden(*_a: object, **_kw: object) -> None:
            raise AssertionError

        monkeypatch.setattr("texlate.repair.fixloop", fake_fixloop)
        monkeypatch.setattr(worker_mod.seams, "engine_for", forbidden)
        work = tmp_path / "build-zh"
        work.mkdir()
        worker.run_stage(ctx, "run_fixloop", work, RecordingEngine("xelatex"), object())
        assert made == ["xelatex"]
        rec = captured["eng"]
        assert isinstance(rec, repair_mod.ResProxy)
