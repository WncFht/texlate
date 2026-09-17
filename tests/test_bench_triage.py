"""triage/stagerun records 协议回归：sig 归桶、末条胜去重、上游门豁免、run_meta 墙钟。

实证锚点 bench/results/stagerun-loop1-2026-09-16（audit-bench 发现）。
bench/py 是纯 stdlib 脚本目——triage/benchlib 直接可 import；stagerun
重 import 链（texlate.* + bench 兄弟模块）放测试内延迟加载。
"""

from __future__ import annotations

import json
import shutil
from argparse import Namespace
from typing import TYPE_CHECKING

import benchlib
import pytest
import triage

from texlate.compile.engine import CompRes, parse_log

if TYPE_CHECKING:
    import types
    from pathlib import Path


def _rec(pid: str, stage: str, status: str, **over: object) -> dict:
    rec = {
        "id": pid,
        "stage": stage,
        "arm": "-",
        "upstream": "",
        "status": status,
        "dur_s": 1.0,
        "metrics": {},
        "errors": [],
        "sig": "",
    }
    rec.update(over)
    return rec


# ---------------------------------------------------------------- sig 归桶
def test_bucket_sig_leftover_ph_to_core() -> None:
    """xlat 侧 cat='xlat' + code='leftover_ph' → 归桶 leftover_ph → classify core。"""
    rec = _rec(
        "p1",
        "xlat",
        "fail",
        arm="mock",
        sig="xlat:3",
        errors=[{"code": "leftover_ph", "cat": "xlat", "payload": "3"}],
    )
    assert triage.record_sig(rec) == "leftover_ph"
    assert triage.classify("leftover_ph", rec)[0] == "core"


def test_bucket_sig_count_payload_merges() -> None:
    r"""fault=N 计数 payload 不再按数字碎裂（实证 17 个 fault=\d+ sig 同一缺陷类）。"""
    recs = [
        _rec(
            f"p{i}",
            "xlat",
            "partial",
            arm="mock",
            sig=f"xlat:fault={n} skipped=0",
            errors=[
                {
                    "code": "chunks_bad",
                    "cat": "xlat",
                    "payload": f"fault={n} skipped=0",
                }
            ],
        )
        for i, n in enumerate((1, 7, 104))
    ]
    sigs = {triage.record_sig(r) for r in recs}
    assert sigs == {"chunks_bad:fault=N skipped=N"}


def test_bucket_sig_member_name_dropped() -> None:
    """stub_format:member.gz → stub_format（13 stub 不再碎成 13 票）。"""
    rec = _rec(
        "p1",
        "ingest",
        "reject",
        sig="stub_format:0707/0707.0145.gz",
        errors=[
            {
                "code": "stub_format",
                "cat": "stub_format",
                "payload": "0707/0707.0145.gz",
            }
        ],
    )
    assert triage.record_sig(rec) == "stub_format"


def test_bucket_sig_harness_repr_dropped() -> None:
    rec = _rec(
        "p1",
        "parse",
        "error",
        sig="harness:BrokenProcessPool('boom 123')",
        errors=[
            {
                "code": "harness:BrokenProcessPool",
                "cat": "harness",
                "payload": "BrokenProcessPool('boom 123')",
            }
        ],
    )
    assert triage.record_sig(rec) == "harness:BrokenProcessPool"


def test_bucket_sig_stable_cases() -> None:
    """缺陷类 cat 不动：missing_file 保 payload；unfixable 前缀保留；digit pay
    无 code 换名时保留（auth:401 是 HTTP 状态非计数）。"""
    rec = _rec("p1", "compile", "fail", arm="zh", sig="missing_file:aastex.cls")
    assert triage.record_sig(rec) == "missing_file:aastex.cls"
    rec = _rec(
        "p2",
        "fixloop",
        "fail",
        arm="fix",
        sig="unfixable:missing_file:pst-node",
        errors=[
            {
                "code": "unfixable:missing_file",
                "cat": "missing_file",
                "payload": "pst-node",
            }
        ],
    )
    assert triage.record_sig(rec) == "unfixable:missing_file:pst-node"
    rec = _rec(
        "p3",
        "xlat",
        "fail",
        arm="mock",
        errors=[{"code": "auth", "cat": "auth", "payload": "401"}],
    )
    assert triage.record_sig(rec) == "auth:401"


def test_classify_latex209_payload_wontfix() -> None:
    rec = _rec(
        "p1",
        "compile",
        "reject",
        arm="zh",
        sig="inject:latex209",
        errors=[{"code": "inject_reject", "cat": "inject", "payload": "latex209"}],
    )
    sig = triage.record_sig(rec)
    assert sig == "inject_reject:latex209"
    assert triage.classify(sig, rec)[0] == "wontfix"


# ---------------------------------------------------------------- 去重
def test_load_records_last_wins(tmp_path: Path) -> None:
    rdir = tmp_path / "records"
    rdir.mkdir()
    rows = [
        _rec("a", "compile", "skip", arm="zh", sig="upstream:x"),
        _rec("b", "compile", "clean", arm="zh"),
        _rec("a", "compile", "clean", arm="zh"),  # resume 重记同键 → 末条胜
        {"note": "no-id row kept"},  # 非 stagerun 形状原样保留
    ]
    with (rdir / "compile.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    recs = triage.load_records(tmp_path)
    keyed = [r["status"] for r in recs if r.get("id") == "a"]
    assert keyed == ["clean"]
    assert any(r.get("note") == "no-id row kept" for r in recs)
    # 跨文件同键不去重（键不含 stage）
    with (rdir / "xlat.jsonl").open("w") as f:
        f.write(json.dumps(_rec("a", "xlat", "ok", arm="mock")) + "\n")
    recs = triage.load_records(tmp_path)
    stages = sorted(r["stage"] for r in recs if r.get("id") == "a")
    assert stages == ["compile", "xlat"]


# ---------------------------------------------------------------- 上游门豁免
def test_upstream_gate_skip_no_ticket(tmp_path: Path) -> None:
    (tmp_path / "work").mkdir()
    recs = [
        _rec(
            "g1",
            "xlat",
            "skip",
            arm="mock",
            sig="upstream:parse=reject",
            errors=[
                {
                    "code": "upstream_gate",
                    "cat": "upstream",
                    "payload": "parse=reject",
                }
            ],
        ),
        _rec(
            "g2",
            "xlat",
            "skip",
            arm="mock",
            sig="upstream:parse=error",
            errors=[
                {
                    "code": "upstream_gate",
                    "cat": "upstream",
                    "payload": "parse=error",
                }
            ],
        ),
        # 真失败型 reject（stub 格式永不可解）仍出票——但归桶成一张
        _rec(
            "s1",
            "ingest",
            "reject",
            sig="stub_format:a.gz",
            errors=[{"code": "stub_format", "cat": "stub_format", "payload": "a.gz"}],
        ),
        _rec(
            "s2",
            "ingest",
            "reject",
            sig="stub_format:b.gz",
            errors=[{"code": "stub_format", "cat": "stub_format", "payload": "b.gz"}],
        ),
    ]
    tickets = triage.build_tickets(recs, tmp_path)
    assert [(t["signature"], t["count"]) for t in tickets] == [("stub_format", 2)]


# ---------------------------------------------------------------- verdict_sig 单源
def test_verdict_sig_category_payload_pair() -> None:
    v = {"status": "fail", "category": "missing_file", "payload": "aa.cls"}
    assert benchlib.verdict_sig(v) == "missing_file:aa.cls"


def test_verdict_sig_derived_cat_no_mispair() -> None:
    """cat 由 reasons 派生时不拼 verdict.payload（payload 配的是原 cat）。"""
    v = {
        "status": "fail",
        "category": "other",
        "payload": "mismatched.sty",
        "reasons": ["first_error=syntax: brace"],
    }
    assert benchlib.verdict_sig(v, "syntax error") == "syntax"
    v2 = {
        "status": "fail",
        "category": None,
        "reasons": ["missing_character×3"],
    }
    assert benchlib.verdict_sig(v2) == "missing_character:x3"
    v3 = {
        "status": "fail",
        "category": None,
        "payload": None,
        "reasons": ["first_error=missing_file: x"],
    }
    first_error = "File `uft8.def' not found"
    assert benchlib.verdict_sig(v3, first_error) == "missing_file:uft8.def"
    assert benchlib.verdict_sig({"status": "clean"}) == ""
    assert benchlib.verdict_sig({"status": "fail"}) == "verdict:fail"


def test_judge_dict_has_payload() -> None:
    """benchlib.judge_dict verdict 带 payload 字段（stagerun sig 合成依赖）。"""
    res = CompRes(engine="xelatex")
    res.log = parse_log("! Undefined control sequence.\nl.1 \\x\n")
    tail = benchlib.judge_dict(res, expect_cjk=False)
    assert "payload" in tail["verdict"]


# ---------------------------------------------------------------- run_meta 墙钟
def test_run_meta_started_finished(tmp_path: Path) -> None:
    stagerun: types.ModuleType = pytest.importorskip("stagerun")
    args = Namespace(stage="parse", seed=42, layers="core")
    stagerun.touch_run_meta(tmp_path, args)
    meta = json.loads((tmp_path / "run_meta.json").read_text())
    assert meta["started_at"]
    assert meta["created_at"]
    stagerun.mark_run_finished(tmp_path)
    meta = json.loads((tmp_path / "run_meta.json").read_text())
    assert meta["finished_at"] >= meta["started_at"]
    # 二次 touch：started_at 不漂移，invocations 追加
    first_invocations = len(meta["invocations"])
    stagerun.touch_run_meta(tmp_path, args)
    meta2 = json.loads((tmp_path / "run_meta.json").read_text())
    assert meta2["started_at"] == meta["started_at"]
    assert len(meta2["invocations"]) == first_invocations + 1
    # triage 侧直读：wall_s 用真实起止而非 sum(dur_s)
    line = triage.compute_metrics(tmp_path, [], None)
    assert line["wall_s"] is not None


def test_fixloop_degraded_regression(tmp_path: Path) -> None:
    """跨段退化探测: fixloop 终态 < metrics.compile_status_before 入口态。

    loop1 实证 17 格 partial→fail 旧探测器全漏（只比同段同臂）。
    """
    recs = [
        _rec("p1", "fixloop", "fail", metrics={"compile_status_before": "partial"}),
        _rec("p2", "fixloop", "clean", metrics={"compile_status_before": "fail"}),
        _rec("p3", "fixloop", "partial", metrics={"compile_status_before": "partial"}),
    ]
    line = triage.compute_metrics(tmp_path, recs, None)
    degs = [r for r in line["regressions"] if r["kind"] == "fixloop_degraded"]
    assert [r["id"] for r in degs] == ["p1"]
    assert degs[0]["before"] == "partial"
    assert degs[0]["after"] == "fail"


# ---------------------------------------------------------------- fixloop --rerun 重建
def _stub_fixloop_io(
    stage_fx: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> list[bool]:
    """_fixloop_one 的外部面全部替身——只留 workdir 编排逻辑可观测。"""
    injected: list[bool] = []

    class _Eng:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def compile(self, *_a: object, **_k: object) -> object:
            return object()

    monkeypatch.setattr(
        stage_fx,
        "prepare_chinese",
        lambda *_a, **_k: injected.append(True) or {},
    )
    monkeypatch.setattr(stage_fx, "XelatexEngine", _Eng)
    monkeypatch.setattr(stage_fx.flb, "_index", lambda: None)
    monkeypatch.setattr(stage_fx.flb, "_init_usertree", lambda _p: None)
    monkeypatch.setattr(stage_fx.flb, "_NoSandbox", lambda e: e)
    monkeypatch.setattr(stage_fx.flb, "_texmf_runner", lambda _t: None)
    monkeypatch.setattr(
        stage_fx,
        "fixloop",
        lambda *_a, **_k: {"verdict": "clean", "rounds": [], "actions": []},
    )
    monkeypatch.setattr(
        stage_fx.benchlib,
        "judge_dict",
        lambda *_a, **_k: {"verdict": {"status": "clean", "reasons": []}},
    )
    return injected


def _seed_workdir(wid: Path, *, arm: str = "mock") -> Path:
    """zh/ + 脏 splice/ + parse.json 的最小 workdir。"""
    zh = wid / "zh"
    zh.mkdir(parents=True)
    (zh / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    (zh / ".xlat-arm.json").write_text(json.dumps({"arm": arm}), encoding="utf-8")
    splice = wid / "splice"
    splice.mkdir()
    (splice / "main.tex").write_text("DIRTY MUTATION", encoding="utf-8")
    (splice / "shim.sty").write_text("% shim", encoding="utf-8")
    (wid / "parse.json").write_text(json.dumps({"main_rel": "main.tex"}))
    return splice


def test_fixloop_rerun_rebuilds_splice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fixloop --rerun 重建 splice 自 zh/——上波就地变异不得带入新轮。

    2211.04482 实证脏 splice 泄漏：二轮规则在假树上复跑。重建与
    _compile_one 同式（copytree zh→splice + prepare_chinese 重做）。
    """
    stage_fx: types.ModuleType = pytest.importorskip("stage_fixloop")
    injected = _stub_fixloop_io(stage_fx, monkeypatch)
    splice = _seed_workdir(tmp_path / "work" / "p1")
    args = Namespace(rerun=True, on="all", timeout=1, llm=False, recode=False)
    rec = stage_fx._fixloop_one(  # noqa: SLF001 - 私有编排函数直测
        "p1", tmp_path, args, {"upstream": "mock", "metrics": {}}, None
    )
    assert rec["status"] == "clean"
    assert rec["metrics"]["splice_rebuilt"] is True
    assert injected == [True]
    assert not (splice / "shim.sty").exists()
    assert "DIRTY" not in (splice / "main.tex").read_text()


def test_fixloop_no_rerun_keeps_splice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非 --rerun 契约不变：splice/ 就地复用（resume 语义），不重建不重注。"""
    stage_fx: types.ModuleType = pytest.importorskip("stage_fixloop")
    injected = _stub_fixloop_io(stage_fx, monkeypatch)
    splice = _seed_workdir(tmp_path / "work" / "p1")
    args = Namespace(rerun=False, on="all", timeout=1, llm=False, recode=False)
    rec = stage_fx._fixloop_one(  # noqa: SLF001 - 私有编排函数直测
        "p1", tmp_path, args, {"upstream": "mock", "metrics": {}}, None
    )
    assert rec["status"] == "clean"
    assert "splice_rebuilt" not in rec["metrics"]
    assert injected == []
    assert (splice / "shim.sty").exists()


def test_fixloop_rerun_arm_mismatch_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """zh/ 臂已换代 → arm_mismatch skip（同 _compile_one 门），脏 splice 不动。"""
    stage_fx: types.ModuleType = pytest.importorskip("stage_fixloop")
    injected = _stub_fixloop_io(stage_fx, monkeypatch)
    splice = _seed_workdir(tmp_path / "work" / "p1", arm="real")
    args = Namespace(rerun=True, on="all", timeout=1, llm=False, recode=False)
    rec = stage_fx._fixloop_one(  # noqa: SLF001 - 私有编排函数直测
        "p1", tmp_path, args, {"upstream": "mock", "metrics": {}}, None
    )
    assert rec["status"] == "skip"
    assert rec["errors"][0]["code"] == "arm_mismatch"
    assert injected == []
    assert "DIRTY" in (splice / "main.tex").read_text()


def test_fixloop_rerun_no_zh_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """compile 记录在而 zh/ 缺席是异常 → error（不在脏树上误修）。"""
    stage_fx: types.ModuleType = pytest.importorskip("stage_fixloop")
    injected = _stub_fixloop_io(stage_fx, monkeypatch)
    wid = tmp_path / "work" / "p1"
    splice = _seed_workdir(wid)
    shutil.rmtree(wid / "zh")
    args = Namespace(rerun=True, on="all", timeout=1, llm=False, recode=False)
    rec = stage_fx._fixloop_one(  # noqa: SLF001 - 私有编排函数直测
        "p1", tmp_path, args, {"upstream": "mock", "metrics": {}}, None
    )
    assert rec["status"] == "error"
    assert rec["errors"][0]["code"] == "rerun_no_zh"
    assert injected == []
    assert "DIRTY" in (splice / "main.tex").read_text()
