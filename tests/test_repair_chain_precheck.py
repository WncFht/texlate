"""修复链第 0 招：fixloop precheck 相在 L2 前的独立预跑（e2e/pipecore 面）。

``t_f74894ebc691aaf4`` 实证链：missing_file 类基建失败进 L2 归因面只会
把块拖去重译/回退——precheck 把装缺件（scan_install）提前到归因前，
装上即重编、clean 直接收工（L2/fixloop 两臂全省）；``reject:<rid>``
不重编不跑 L2，交 fixloop 复现 + ``fixloop_flags_tail`` 跨引擎消费。

附带钉 ``_texmf_wire``：编译尾段/跨引擎重试每发新造的引擎必须看见
``work/_texmf`` 装件树（fixloop ``_wire_engine`` 只盖它手里那台）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conftest import RecordingEngine

from texlate import e2e
from texlate.pipecore import PipeJob, precheck_job

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

#: 最小可解析工程（与 test_e2e._MAIN 同型——两段散文保证出 chunk）。
_MAIN = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "\\section{Intro}\n"
    "This is a longer paragraph of English text that should definitely be\n"
    "segmented into at least one chunk for translation purposes.\n"
    "\n"
    "And a second paragraph here.\n"
    "\\end{document}\n"
)

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


def _project(root: Path, main: str = _MAIN) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "main.tex").write_text(main, encoding="utf-8")
    return root


def test_precheck_install_short_circuits_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_engine: dict[str, RecordingEngine],  # noqa: ARG001 -- judge/env 钉住副作用
) -> None:
    """首编 fail → precheck 装上缺件 → 重编 clean → L2/fixloop 两臂全省。

    走 xelatex——``static_precheck`` 在 tectonic 是 ``degrade: skip``
    （bundle 按需自拉，预检空转），装件臂只有 xelatex 真跑。
    """
    work = _project(tmp_path / "p")
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
    # clean 早退在 L2/fixloop 键写入前——与首编即 clean 的报告同形
    assert "l2" not in report
    assert "fixloop" not in report


def test_precheck_noop_falls_through_to_l2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_engine: dict[str, RecordingEngine],  # noqa: ARG001
) -> None:
    """装不上件（全 False 桩）+ 无 flag → 不重编 → L2/fixloop 照常跑。"""
    work = _project(tmp_path / "p")

    def factory(name: str, **kw: object) -> RecordingEngine:
        eng = RecordingEngine(name, **kw)
        eng.produce_pdf = False
        return eng

    monkeypatch.setattr(e2e, "engine_for", factory)
    report = e2e.pipeline_run(work, "auto", timeout=10.0)

    assert report["status"] == "fail"
    pre = report["precheck"]
    assert pre["enabled"] is True
    assert pre["installed"] == []
    assert report["l2"]["enabled"] is True
    assert report["fixloop"]["enabled"] is True


def test_precheck_reject_skips_l2_routes_fixloop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_engine: dict[str, RecordingEngine],  # noqa: ARG001
) -> None:
    """precheck ``reject:<rid>`` → 不重编不跑 L2 → fixloop 复现拒绝 → partial。

    ``route_engines=[tectonic]`` 掐掉跨引擎消费——拒绝原样落盘可断。
    """
    work = _project(tmp_path / "p", main=_PSTRICKS)

    def factory(name: str, **kw: object) -> RecordingEngine:
        eng = RecordingEngine(name, **kw)
        eng.produce_pdf = False
        return eng

    monkeypatch.setattr(e2e, "engine_for", factory)
    rec = e2e.pipe_condition(
        work, "tectonic", "main.tex", 10.0, route_engines=["tectonic"]
    )

    assert rec["precheck"]["verdict"] == "reject:pstricks_route"
    assert rec["precheck"]["reject_route"] == "xelatex"
    assert rec["l2"] == {"enabled": False, "reason": "precheck_reject"}
    assert rec["fixloop"]["verdict"] == "reject:pstricks_route"
    assert rec["status"] == "partial"
    assert rec["reject_at"] == "fixloop"


def test_compile_judge_engine_texmf_wired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_engine: dict[str, RecordingEngine],  # noqa: ARG001
) -> None:
    """编译尾段新造引擎接 ``work/_texmf``——precheck/fixloop 装件可见。"""
    work = _project(tmp_path / "p")
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
    work = _project(tmp_path / "p")
    job = PipeJob(work, "main.tex", "tectonic", 10.0)

    def boom(name: str, **kw: object) -> RecordingEngine:  # noqa: ARG001
        msg = "engine factory boom"
        raise RuntimeError(msg)

    rep = precheck_job(job, engine_fn=boom)
    assert rep["enabled"] is True
    assert "RuntimeError" in rep["error"]
