"""修复链第 0 招：fixloop precheck 相在 logfix 前的独立预跑（e2e/pipecore 面）。

``t_f74894ebc691aaf4`` 实证链：missing_file 类基建失败进 logfix 归因面只会
把块拖去重译/回退——precheck 把装缺件（scan_install）提前到归因前，
装上即重编、clean 直接收工（logfix/fixloop 两臂全省）；``reject:<rid>``
不重编不跑 logfix，交 fixloop 复现 + ``fixloop_flags_tail`` 跨引擎消费。

附带钉 ``_texmf_wire``：编译尾段/跨引擎重试每发新造的引擎必须看见
``work/_texmf`` 装件树（fixloop ``_wire_engine`` 只盖它手里那台）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conftest import RecordingEngine, failing_engine, make_project

from texlate import e2e
from texlate.pipecore import PipeJob, precheck_job

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

#: tectonic 上 pstricks 是硬墙——precheck ``pstricks_route`` 预检拒。
_PSTRICKS = (
    "\\documentclass{article}\n"
    "\\usepackage{pstricks}\n"
    "\\begin{document}\n"
    "A paragraph of English text long enough to be segmented into chunks.\n"
    "\n"
    "And a second paragraph here so the chunker stays honest.\n"
    "\\end{document}\n"
)


def test_precheck_install_short_circuits_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_engine: dict[str, RecordingEngine],  # noqa: ARG001 -- judge/env 钉住副作用
) -> None:
    """首编 fail → precheck 装上缺件 → 重编 clean → logfix/fixloop 两臂全省。

    走 xelatex——``static_precheck`` 在 tectonic 是 ``degrade: skip``
    （bundle 按需自拉，预检空转），装件臂只有 xelatex 真跑。
    """
    work = make_project(tmp_path / "p")
    n = [0]

    def factory(name: str, **kw: object) -> RecordingEngine:
        eng = RecordingEngine(name, **kw)
        eng.texmfhome = None  # 真引擎实例 attr——_texmf_wire 的接线面
        eng.produce_pdf = n[0] > 0  # 首台不产 pdf，其后全产
        eng.install_file = lambda _f, *, font_related=False: True  # noqa: ARG005
        n[0] += 1
        return eng

    monkeypatch.setattr(e2e, "engine_for", factory)
    report = e2e.pipeline_run(work, "xelatex", timeout=10.0)

    assert report["status"] == "clean"
    pre = report["precheck"]
    assert pre["enabled"] is True
    assert pre["installed"], "static_precheck 应装上扫描到的缺件"
    # clean 早退在 logfix/fixloop 键写入前——与首编即 clean 的报告同形
    assert "logfix" not in report
    assert "fixloop" not in report


def test_precheck_noop_falls_through_to_logfix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_engine: dict[str, RecordingEngine],  # noqa: ARG001
) -> None:
    """装不上件（全 False 桩）+ 无 flag → 不重编 → logfix/fixloop 照常跑。"""
    work = make_project(tmp_path / "p")
    monkeypatch.setattr(e2e, "engine_for", failing_engine)
    report = e2e.pipeline_run(work, "auto", timeout=10.0)

    assert report["status"] == "fail"
    pre = report["precheck"]
    assert pre["enabled"] is True
    assert pre["installed"] == []
    assert report["logfix"]["enabled"] is True
    assert report["fixloop"]["enabled"] is True


def test_precheck_reject_skips_logfix_routes_fixloop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_engine: dict[str, RecordingEngine],  # noqa: ARG001
) -> None:
    """precheck ``reject:<rid>`` → 不重编不跑 logfix → fixloop 复现拒绝 → partial。

    ``route_engines=[tectonic]`` 掐掉跨引擎消费——拒绝原样落盘可断。
    """
    work = make_project(tmp_path / "p", main=_PSTRICKS)
    monkeypatch.setattr(e2e, "engine_for", failing_engine)
    rec = e2e.pipe_condition(
        work, "tectonic", "main.tex", 10.0, route_engines=["tectonic"]
    )

    assert rec["precheck"]["verdict"] == "reject:pstricks_route"
    assert rec["precheck"]["reject_route"] == "xelatex"
    assert rec["logfix"] == {"enabled": False, "reason": "precheck_reject"}
    assert rec["fixloop"]["verdict"] == "reject:pstricks_route"
    assert rec["status"] == "partial"
    assert rec["reject_at"] == "fixloop"


def test_compile_judge_engine_texmf_wired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_engine: dict[str, RecordingEngine],  # noqa: ARG001
) -> None:
    """编译尾段新造引擎接 ``work/_texmf``——precheck/fixloop 装件可见。"""
    work = make_project(tmp_path / "p")
    seen: list[RecordingEngine] = []

    def factory(name: str, **kw: object) -> RecordingEngine:
        eng = RecordingEngine(name, **kw)
        eng.texmfhome = None
        seen.append(eng)
        return eng

    monkeypatch.setattr(e2e, "engine_for", factory)
    e2e.pipeline_run(work, "auto", timeout=10.0)

    assert seen
    assert all(eng.texmfhome == work / "_texmf" for eng in seen)


def test_precheck_job_crash_returns_error_dict(tmp_path: Path) -> None:
    """precheck 崩 → ``{"enabled": True, "error": ...}``——不毁主报告。"""
    work = make_project(tmp_path / "p")

    def boom(name: str, **kw: object) -> RecordingEngine:  # noqa: ARG001
        msg = "engine factory boom"
        raise RuntimeError(msg)

    job = PipeJob(work, "main.tex", "tectonic", 10.0, engine_fn=boom)
    rep = precheck_job(job)
    assert rep["enabled"] is True
    assert "RuntimeError" in rep["error"]
