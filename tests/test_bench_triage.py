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

from texlate.compile.engine import CompRes
from texlate.compile.loginfo import parse_log

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


# ---------------------------------------------------------------- fixloop 归因签名
def test_fixloop_attr_last_regular_round() -> None:
    """归因 = 末个正规轮 (cat, pay)：salvage 哨兵不占槽、pay 空不回填旧轮。

    2609.19664 实证：r2 babel_opt|latin 已装，r3-r5 ``other:None`` streak
    触 stuck——旧回填走成 ``stuck:latin`` 误桶。
    """
    rounds = [
        {"round": 1, "cat": "missing_file", "pay": "fairmeta.cls"},
        {"round": 2, "cat": "babel_opt", "pay": "latin"},
        {"round": 3, "cat": "other", "pay": None},
        {"round": 4, "cat": "other", "pay": None},
        {"round": 5, "cat": "other", "pay": None},
        {"round": 6, "cat": None, "pay": None},  # 旧 schema salvage 哨兵无标
    ]
    assert benchlib.fixloop_attr(rounds, "stuck") == ("other", "")
    # 新 schema "salvage": true 同回退
    rounds[-1]["salvage"] = True
    assert benchlib.fixloop_attr(rounds, "stuck") == ("other", "")
    # 非 salvage 末轮真实签名照取（streak 有 payload 时保留）
    assert benchlib.fixloop_attr(rounds[:2], "stuck") == ("babel_opt", "latin")
    # clean 系 verdict 的 cat=None 末轮是正规轮——不回退
    assert benchlib.fixloop_attr(
        [{"cat": "other"}, {"cat": None}], "no_errors_no_pdf"
    ) == (None, "")
    assert benchlib.fixloop_attr([], "stuck") == (None, "")


def test_fixloop_sig_terminal_cat() -> None:
    """终态词 sig 拼归因 cat：stuck streak 签 {cat}:{pay} 的头半进桶键。"""
    assert benchlib.fixloop_sig("stuck", "other", "") == "stuck:other"
    assert (
        benchlib.fixloop_sig("stuck", "babel_opt", "latin") == "stuck:babel_opt:latin"
    )
    assert benchlib.fixloop_sig("max_rounds", "syntax", "x") == "max_rounds:syntax:x"
    assert benchlib.fixloop_sig("stuck", None, "") == "stuck"
    assert (
        benchlib.fixloop_sig("unfixable:missing_file", "missing_file", "a.cls")
        == "unfixable:missing_file:a.cls"
    )
    # cat 化终态 sig 仍归 core（引擎/taxonomy 缺口），不落 rule 人工归因
    assert triage.classify("stuck:other", {})[0] == "core"


def test_legacy_records_stuck_attr(tmp_path: Path) -> None:
    """legacy_records 同口径：salvage 尾 + other streak → ``stuck:other``。"""
    doc = {
        "a": {
            "id": "a",
            "pipe-fix": {
                "fixloop": {
                    "verdict": "stuck",
                    "final_cat": None,
                    "rounds": [
                        {"cat": "missing_file", "pay": "fairmeta.cls"},
                        {"cat": "babel_opt", "pay": "latin"},
                        {"cat": "other", "pay": None},
                        {"cat": "other", "pay": None},
                        {"cat": "other", "pay": None},
                        {"cat": None, "pay": None},
                    ],
                }
            },
        }
    }
    (tmp_path / "results.json").write_text(json.dumps(doc))
    recs = triage.legacy_records(tmp_path)
    sigs = {r["sig"] for r in recs}
    assert "stuck:other" in sigs
    assert "stuck:latin" not in sigs


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


# ---------------------------------------------------------------- safe_id 撞名归一
def test_canon_id_unflattens() -> None:
    """``canon_id`` = safe_id 逆：``--``→``/``；幂等，新式/规范形不动。"""
    sl = pytest.importorskip("stagerun_lib")
    assert sl.canon_id("math--0408287") == "math/0408287"
    assert sl.canon_id("cond-mat--0605673") == "cond-mat/0605673"
    assert sl.canon_id("0707.0005") == "0707.0005"
    assert sl.canon_id("math/0408287") == "math/0408287"
    assert sl.canon_id(sl.canon_id("math--0408287")) == "math/0408287"


def test_workdir_collision_invariant(tmp_path: Path) -> None:
    """双拼写同 wid 是既有事实（存量 workdir 不迁）——归一在 id 层不在 wid 层。"""
    sl = pytest.importorskip("stagerun_lib")
    assert sl.workdir(tmp_path, "math/0408287") == sl.workdir(tmp_path, "math--0408287")


def test_select_ids_dual_spelling_dedups() -> None:
    """--ids 收 flat+slash 双拼写 → 归一坍缩成单任务（loop1 撞名实证形）。"""
    sl = pytest.importorskip("stagerun_lib")
    args = Namespace(
        ids="math--0408287,math/0408287,0707.0005", n=0, seed=42, only=None
    )
    entries = [{"id": "math/0408287"}, {"id": "0707.0005"}]
    ids = sl.select_ids(entries, args, "compile")
    assert ids == ["0707.0005", "math/0408287"]
    # flat 拼写不在 manifest 也照归一（定点 smoke 不受 manifest 成员约束）
    args2 = Namespace(ids="math--0408287", n=0, seed=42, only=None)
    assert sl.select_ids([], args2, "compile") == ["math/0408287"]


def test_dedup_wids_drops_collision(capsys) -> None:  # noqa: ANN001
    """同 wid 只留一个任务（保规范形），撞名者丢弃 + stderr 显式化对偶。"""
    sl = pytest.importorskip("stagerun_lib")
    ids = sl.dedup_wids(["math--0408287", "math/0408287", "0707.0005"])
    assert ids == ["math/0408287", "0707.0005"]
    err = capsys.readouterr().err
    assert "math/0408287≡math--0408287" in err


def test_reclog_canon_resume_cross_spelling(tmp_path: Path) -> None:
    """flat 存量账 → canon pid ``is_done`` 命中——双拼写 resume 连续。

    loop1 records 实证 65 对双拼写并存；不 canon 则规范形续跑全漏判。
    """
    sl = pytest.importorskip("stagerun_lib")
    rp = tmp_path / "records" / "parse.jsonl"
    rp.parent.mkdir(parents=True)
    rp.write_text(
        json.dumps(_rec("math--0408287", "parse", "ok")) + "\n", encoding="utf-8"
    )
    log = sl.RecLog(rp)
    try:
        assert log.is_done("math/0408287", "-")
        assert log.is_done("math--0408287", "-")
        log.append(_rec("hep-th/9901001", "parse", "ok"))
        assert log.is_done("hep-th--9901001", "-")
    finally:
        log.close()


def test_load_latest_canon_cross_spelling(tmp_path: Path) -> None:
    """同篇双拼写并存 → canon 键下 append 序末条胜（跨拼写）。"""
    sl = pytest.importorskip("stagerun_lib")
    rp = tmp_path / "compile.jsonl"
    rows = [
        _rec("math--0408287", "compile", "fail", arm="zh"),
        _rec("math/0408287", "compile", "clean", arm="zh"),
    ]
    rp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    latest = sl.load_latest(rp)
    assert latest[("math/0408287", "zh", "")]["status"] == "clean"
    assert ("math--0408287", "zh", "") not in latest


def test_fixloop_cand_flat_compile_rec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """compile 账 flat 拼写存量 → canon pid 候选命中（不静默落选）。

    调度只到 _fixloop_one 编排面——monkeypatch 替身观测派发的
    (pid, crec.id) 对：pid 须规范形，crec 是盘上原始 flat 记录。
    """
    stage_fx = pytest.importorskip("stage_fixloop")
    sl = pytest.importorskip("stagerun_lib")
    recs_dir = tmp_path / "records"
    recs_dir.mkdir()
    (recs_dir / "compile.jsonl").write_text(
        json.dumps(_rec("math--0408287", "compile", "fail", arm="zh", upstream="mock"))
        + "\n",
        encoding="utf-8",
    )
    seen: list[tuple[str, str]] = []

    def _stub(pid, out_dir, args, crec, sink) -> dict:  # noqa: ANN001,ARG001
        seen.append((pid, crec["id"]))
        return sl.base_rec(pid, "fixloop", "fix")

    monkeypatch.setattr(stage_fx, "_fixloop_one", _stub)
    monkeypatch.setattr(stage_fx.Ruleset, "load", classmethod(lambda _cls: None))
    args = Namespace(
        on="all", xlat_arm=None, recode=False, rerun=False, jobs=2, time_budget=0
    )
    log = sl.RecLog(recs_dir / "fixloop.jsonl")
    try:
        stage_fx.stage_fixloop(args, tmp_path, ["math/0408287"], log)
    finally:
        log.close()
    assert seen == [("math/0408287", "math--0408287")]
