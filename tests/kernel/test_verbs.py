"""tests/kernel/test_verbs.py — verbs 层最小端到端覆盖。

gate / triage / rundiff / dossier 四动词的函数面：index 投影进账 →
读侧聚合 → 产物渲染。CLI main() 只测 triage 一条（_cli._open_index 换
broot index——其余 verb main 是同形薄壳，函数面即本体）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from kernel import events
from kernel.index import Index
from verbs import dossier, gate, rundiff, triage


def _cell(run, seq, idc="2101.12345", stage="compile", status="ok", **kw):
    return events.make_event(
        events.T_CELL,
        run=run,
        seq=seq,
        id=kw.pop("id", idc),
        idc=idc,
        arm=kw.pop("arm", "zh"),
        up=kw.pop("up", "-"),
        variant=kw.pop("variant", "-"),
        stage=stage,
        status=status,
        **kw,
    )


def _reg_run(idx, run, run_seq, kind="e2e_real", date="2026-01-01", slug="s"):
    idx.apply_event(
        events.make_event(
            events.T_RUN_REGISTERED,
            run=run,
            run_seq=run_seq,
            kind=kind,
            date=date,
            slug=slug,
            spec_hash="h",
            ts_start=1.0,
        )
    )


# -- triage --------------------------------------------------------------------


def test_triage_load_records_last_wins(broot):
    idx = Index()
    _reg_run(idx, "r1", 1)
    idx.apply_event(_cell("r1", 1, status="fail", sig="missing_file:x.sty"))
    idx.apply_event(_cell("r1", 2, status="clean"))
    recs = triage.load_records(idx, "r1")
    assert len(recs) == 1
    assert recs[0]["status"] == "clean"  # seq 末条胜
    assert recs[0]["src"] == "records"


def test_triage_build_tickets_clusters(broot):
    recs = [
        # 同 (stage,sig-bucket) 两格并一票
        {
            "id": "a",
            "stage": "compile",
            "status": "fail",
            "sig": "missing_file:x.sty",
            "errors": [{"cat": "missing_file", "payload": "x.sty"}],
        },
        {"id": "b", "stage": "compile", "status": "fail", "sig": "missing_file:x.sty"},
        # upstream-gated skip 不出票
        {
            "id": "c",
            "stage": "fixloop",
            "status": "skip",
            "errors": [{"cat": "upstream", "code": "no_splice"}],
        },
        # ok 但带 sig → warning 级票；sig cat 是 stage 桶时换 code 归桶
        {
            "id": "d",
            "stage": "xlat",
            "status": "ok",
            "sig": "xlat:leftover_ph",
            "errors": [{"cat": "xlat", "code": "leftover_ph", "payload": "2"}],
        },
        # 干净 ok 不出票
        {"id": "e", "stage": "compile", "status": "clean"},
    ]
    tickets = triage.build_tickets(recs, None)
    sigs = {t["signature"]: t for t in tickets}
    assert len(tickets) == 2  # skip-upstream 与裸 ok 豁免
    miss = sigs["missing_file:x.sty"]
    assert miss["count"] == 2
    assert miss["example_ids"] == ["a", "b"]
    assert miss["repro_path"] is None  # rundir=None → 恒 None
    assert miss["sig_id"].startswith("compile-")
    ph = sigs["leftover_ph"]  # cat 换 code 归桶
    assert ph["fix_class"] == "core"
    assert "warning" in ph["notes"]


def test_triage_compute_metrics_pipeline_regression():
    recs = [
        {
            "id": "p1",
            "stage": "compile",
            "arm": "zh",
            "status": "fail",
            "sig": "missing_file:x.sty",
        },
        {"id": "p1", "stage": "compile", "arm": "base", "status": "clean"},
        {
            "id": "p2",
            "stage": "fixloop",
            "arm": "zh",
            "status": "clean",
            "metrics": {"compile_status_before": "fail"},
        },
        {
            "id": "p2",
            "stage": "fixloop",
            "arm": "zh",
            "status": "stuck",
            "sig": "unfixable:stuck",
            "metrics": {"compile_status_before": "partial"},
        },
    ]
    line = triage.compute_metrics(recs, "r1", "2026-01-01", 12.0, None)
    regs = line["regressions"]
    pipe = [r for r in regs if r["kind"] == "pipeline_introduced"]
    assert [r["id"] for r in pipe] == ["p1"]  # zh fail ∧ base clean
    deg = [r for r in regs if r["kind"] == "fixloop_degraded"]
    assert deg == [
        {"kind": "fixloop_degraded", "id": "p2", "before": "partial", "after": "stuck"}
    ]
    fl = line["fixloop"]
    assert fl["attempted"] == 2 and fl["rescued"] == 1
    md = triage.render_report(line, [], "test")
    assert "p1" not in md or "pipeline_introduced" in md  # 回归行进汇总行
    assert "| compile |" in md and "| fixloop |" in md


def test_triage_main_writes_derived(broot, tmp_path, monkeypatch):
    idx = Index()
    _reg_run(idx, "r1", 1, kind="k", date="2026-01-02", slug="s1")
    idx.apply_event(
        _cell(
            "r1",
            1,
            status="fail",
            sig="missing_file:x.sty",
            errors=[{"cat": "missing_file", "payload": "x.sty"}],
        )
    )
    idx.apply_event(_cell("r1", 2, idc="2101.00002", status="clean"))
    monkeypatch.setattr("kernel.cli._open_index", lambda: idx)
    out = tmp_path / "derived"
    rc = triage.main(
        SimpleNamespace(run="r1", table="both", trend=False, as_json=False, out_dir=out)
    )
    assert rc == 0
    tickets = [
        json.loads(l) for l in (out / "tickets.jsonl").read_text().splitlines() if l
    ]
    assert len(tickets) == 1 and tickets[0]["count"] == 1
    assert "# triage report — r1" in (out / "report.md").read_text()


# -- rundiff --------------------------------------------------------------------


def test_rundiff_stage_cells_and_diff(broot):
    idx = Index()
    _reg_run(idx, "ra", 1)
    _reg_run(idx, "rb", 2)
    idx.apply_event(_cell("ra", 1, idc="p1", status="fail", sig="missing_file:x.sty"))
    idx.apply_event(_cell("ra", 2, idc="p2", status="clean"))
    idx.apply_event(_cell("ra", 3, idc="p3", status="ok"))
    idx.apply_event(_cell("rb", 1, idc="p1", status="clean"))
    idx.apply_event(_cell("rb", 2, idc="p2", status="fail", sig="undefined_cs:\\foo"))
    idx.apply_event(_cell("rb", 3, idc="p4", status="partial"))

    ca = rundiff.stage_cells(idx, "ra")["compile"]
    cb = rundiff.stage_cells(idx, "rb")["compile"]
    d = rundiff.diff_stage(ca, cb)
    assert len(d["improved"]) == 1 and d["improved"][0]["id"] == "p1"
    assert len(d["degraded"]) == 1 and d["degraded"][0]["id"] == "p2"
    assert d["degraded"][0]["sig_b"] == "undefined_cs:\\foo"
    assert [e["id"] for e in d["added"]] == ["p4"]
    assert [e["id"] for e in d["removed"]] == ["p3"]
    assert d["matrix"][("fail", "clean")] == 1
    assert d["matrix"][("(absent)", "partial")] == 1
    md = rundiff.render_md("ra", "rb", {"compile": d})
    assert "## compile" in md and "### degraded (1)" in md


def test_rundiff_deep_churn():
    ra = {
        ("p", "a", "-", "-"): {
            "id": "p",
            "status": "fail",
            "sig": "s1",
            "metrics": {"n_errors": 5},
            "dur_s": 10.0,
        }
    }
    rb = {
        ("p", "a", "-", "-"): {
            "id": "p",
            "status": "fail",
            "sig": "s2",
            "metrics": {"n_errors": 50},
            "dur_s": 120.0,
        }
    }
    d = rundiff.diff_stage(ra, rb, deep=True)
    assert len(d["same"]) == 1 and len(d["churn"]) == 1
    c = d["churn"][0]["churn"]
    assert c["sig"] == ("s1", "s2")
    assert c["n_errors"] == (5, 50)
    assert c["dur_s"] == (10.0, 120.0)


# -- gate ----------------------------------------------------------------------


def _comp(status="clean", **m):
    return {
        "status": status,
        "arm": "zh",
        "up": "-",
        "idc": "p",
        "metrics": m or {},
        "ts": 100.0,
    }


def test_gate_pick_final_paths():
    c = _comp("clean")
    stage, r, drop = gate.pick_final(c, None)
    assert (stage, r, drop) == ("compile", c, None)
    # 非真编译终态的 fix 覆盖不入账
    _, _, drop = gate.pick_final(_comp("reject"), {"status": "clean"})
    assert drop == "over_noncompiled"
    # post.status 与顶 status 相悖 → 拼账丢弃
    f_bad = {
        "status": "clean",
        "metrics": {
            "post": {"status": "fail"},
            "compile_fp": gate.compile_fp(c),
            "compile_status_before": "clean",
        },
    }
    _, _, drop = gate.pick_final(c, f_bad)
    assert drop == "post_inconsistent"
    # fp 匹配 + csb 等值 → fixloop 接管
    f_ok = {
        "status": "clean",
        "metrics": {"compile_fp": gate.compile_fp(c), "compile_status_before": "clean"},
    }
    stage, r, drop = gate.pick_final(c, f_ok)
    assert stage == "fixloop" and r is f_ok and drop is None
    # fp 不匹配 → 陈旧作废
    f_stale = {
        "status": "clean",
        "metrics": {"compile_fp": "0" * 16, "compile_status_before": "clean"},
    }
    _, _, drop = gate.pick_final(c, f_stale)
    assert drop == "fp_mismatch"
    # legacy 档：无 fp 只看 csb；窗内 suspect → window_stale
    f_leg = {"status": "clean", "metrics": {"compile_status_before": "clean"}}
    _, _, drop = gate.pick_final(c, f_leg, window_suspect=True)
    assert drop == "window_stale"
    _, _, drop = gate.pick_final(
        c, {"status": "clean", "metrics": {"compile_status_before": "fail"}}
    )
    assert drop == "stale"
    _, _, drop = gate.pick_final(c, {"status": "clean", "metrics": {}})
    assert drop == "no_csb"


def test_gate_scan_rows_and_tally():
    rows = [
        {
            "stage": "compile",
            "idc": "p1",
            "id": "p1",
            "arm": "zh",
            "up": "-",
            "status": "clean",
            "ts": 10.0,
            "code": "cA",
        },
        {
            "stage": "compile",
            "idc": "p1",
            "id": "p1",
            "arm": "zh",
            "up": "-",
            "status": "fail",
            "ts": 20.0,
            "code": "cA",
        },  # 末条胜
        {
            "stage": "compile",
            "idc": "p2",
            "id": "p2",
            "arm": "base",
            "up": "-",
            "status": "clean",
            "ts": 30.0,
        },
        {
            "stage": "compile",
            "idc": "p3",
            "id": "p3",
            "arm": "zh",
            "up": "mock",
            "status": "clean",
            "ts": 40.0,
        },
        {
            "stage": "compile",
            "idc": "p4",
            "id": "p4",
            "arm": "zh",
            "up": "-",
            "status": "fail",
            "ts": 50.0,
            "errors": [{"code": "arm_mismatch"}],
        },
        {
            "stage": "fixloop",
            "idc": "p1",
            "id": "p1",
            "arm": "zh",
            "up": "-",
            "status": "clean",
            "ts": 25.0,
            "code": "cB",
            "metrics": {"compile_status_before": "fail"},
        },
    ]
    comp, st, si = gate.scan_rows(rows, "compile", arm="zh", upstream="-")
    assert st["rows"] == 5 and st["accepted"] == 2
    assert st["unique"] == 1 and st["superseded"] == 1
    assert st["arm_filtered"] == 1 and st["upstream_filtered"] == 1
    assert st["arm_mismatch"] == 1
    assert comp["p1"]["status"] == "fail"  # append 序末条胜
    assert si["ts_max"] == 20.0
    fix, fst, _ = gate.scan_rows(rows, "fixloop", arm=None, upstream="-")
    assert fst["accepted"] == 1
    suspects = gate.window_suspects(comp, fix)  # fixloop ts=25 > compile p1 ts=20
    assert suspects == set()  # compile 更晚才算 suspect
    t = gate._tally(comp, fix, suspects)
    # p1: fixloop csb='fail' 等值接管（无 fp → legacy_status 档）
    assert t["end"]["fixloop:clean"] == 1 and t["total"] == 1
    assert t["end_pdf"] == 1 and t["uni_pdf"] == 1
    assert t["csb_check"]["legacy_status"] == 1
    g = gate._gate(t["end_pdf"], t["total"])  # 1/1 → 过 90% 门
    assert g["pass"] is True and g["need"] == 0
    g2 = gate._gate(8, 10)  # 80% → 缺 1 格
    assert g2["pass"] is False and g2["need"] == 1


def test_gate_check_freeze_signals():
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    fz = gate.check_freeze(
        ["r1"],
        {"r1": {"exists": True, "torn": True, "tail_truncated": True, "age_s": 5.0}},
        {"compile": {"ts_max": now.timestamp() - 10}},
        [{"run": "r1", "heartbeat_age": 3.0}],
        now,
    )
    assert fz["status"] == "partial"
    assert {
        "in_flight_run",
        "torn_read:r1",
        "tail_truncated:r1",
        "recent_write:compile",
        "recent_write:r1",
    } <= set(fz["reasons"])
    fz2 = gate.check_freeze(["r1"], {}, {"compile": {"ts_max": None}}, [], now)
    assert fz2["status"] == "frozen" and fz2["reasons"] == []


def test_gate_stem_of():
    assert gate._stem_of("runx_compile") == "runx"
    assert gate._stem_of("runx_records_fixloop") == "runx_records"
    assert gate._stem_of("plain") == "plain"


# -- dossier -------------------------------------------------------------------


def test_dossier_fetch_and_latest(broot):
    idx = Index()
    _reg_run(idx, "r1", 1)
    idx.apply_event(_cell("r1", 1, stage="compile", status="fail", arm="base"))
    idx.apply_event(_cell("r1", 2, stage="compile", status="skip"))
    idx.apply_event(
        _cell(
            "r1",
            3,
            stage="compile",
            status="fail",
            sig="missing_file:x.sty",
            metrics={"main_rel": "main.tex"},
        )
    )
    idx.apply_event(
        events.make_event(
            events.T_CASE,
            run="r1",
            seq=4,
            id="2101.12345",
            idc="2101.12345",
            payload={"corpus": "2101.12345", "cond": "fixloop", "verdict": "clean"},
        )
    )
    rows = dossier._fetch_records(idx, ["2101.12345"])
    assert len(rows) == 3
    assert rows[0]["upstream"] == "-"  # up→upstream 映射
    recs = dossier._group_stages(rows)
    latest = dossier._latest(recs)["compile"]
    assert len(latest) == 2  # (id,arm,up) 键两格
    # 主 compile：zh 臂末条 attempted（skip 格不算）
    comp = dossier._primary_compile(recs)
    assert comp["sig"] == "missing_file:x.sty"
    cases = dossier._fetch_cases(idx, ["2101.12345"])
    assert cases == [{"corpus": "2101.12345", "cond": "fixloop", "verdict": "clean"}]


def test_dossier_work_inventory(broot, tmp_path):
    w = tmp_path / "w"
    (w / "src").mkdir(parents=True)
    (w / "src" / "main.tex").write_text("x")
    (w / "zh").mkdir()
    (w / "zh" / ".xlat-arm.json").write_text(json.dumps({"arm": "real", "model": "m"}))
    (w / "splice").mkdir()
    (w / "splice" / "m.pdf").write_bytes(b"%PDF")
    (w / "splice" / "m.log").write_text("! Undefined control sequence.")
    (w / "parse.json").write_text(
        json.dumps({"status": "ok", "main_rel": "main.tex", "totals": {"files": 1}})
    )
    (w / "xlat-zh.jsonl").write_text(
        '{"status":"ok","chunk_id":1}\n{"status":"fail","chunk_id":2,'
        '"error_kind":"timeout"}\n'
    )
    (w / "_texmf" / "home" / "tex/latex").mkdir(parents=True)
    (w / "_texmf" / "home" / "tex/latex" / "x.sty").write_text("s")
    inv = dossier.work_inventory(w)
    assert inv["present"] and inv["src"]["files"] == 1
    assert inv["xlat_arm"]["arm"] == "real"
    assert inv["xlat_arms"]["xlat-zh.jsonl"]["counts"] == {"ok": 1, "fail": 1}
    assert inv["splice_compile"]["pdf"] == ["m.pdf"]
    assert inv["splice_compile"]["log_name"] == "m.log"
    assert inv["parse"]["main_rel"] == "main.tex"
    assert inv["texmf_installed"] == ["tex/latex/x.sty"]


def test_dossier_load_tickets(broot, tmp_path):
    rd = tmp_path / "rd"
    (rd / "derived").mkdir(parents=True)
    (rd / "derived" / "tickets.jsonl").write_text(
        json.dumps({"sig_id": "compile-001", "example_ids": ["2101.12345", "x"]})
        + "\n"
        + json.dumps({"sig_id": "xlat-002", "example_ids": ["other"]})
        + "\n"
    )
    got = dossier.load_tickets({"2101.12345"}, [rd])
    assert got == ["compile-001"]
