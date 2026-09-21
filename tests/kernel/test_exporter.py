"""Tests for kernel/exporter.py — legacy run-layout projection (design §5).

Every test runs against an isolated $TEXLATE_BENCH_ROOT via the `broot`
fixture (see conftest.py). Files stay KB-scale — /tmp is quota-sensitive.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from kernel import events, exporter, ledger, paths
from kernel import index as index_mod

KIND = "soak"
DATE = "2026-09-21"
SLUG = "t1"
RUN = f"{KIND}-{DATE}-{SLUG}"

RAW_ID = "cond-mat--9601002"  # writer's safe-form spelling — NOT canon
IDC = "cond-mat/9601002"
SID = "cond-mat--9601002"

LEGACY_KEYS = {
    "id", "stage", "arm", "upstream", "code", "status",
    "dur_s", "metrics", "errors", "sig",
}


def _mint(run=RUN, kind=KIND, date=DATE, slug=SLUG):
    n = ledger.mint_run_seq(run, kind, date, slug, "spechash0")
    return paths.run_dir(kind, date, slug), n


def _queued(run, seq, stage):
    return events.make_event(
        events.T_CELL_QUEUED, run=run, seq=seq, id=RAW_ID, idc=IDC,
        arm="zh", up="-", variant="-", stage=stage,
        needs=[], fp_input="fp0",
    )


def _started(run, seq, stage):
    return events.make_event(
        events.T_CELL_STARTED, run=run, seq=seq, id=RAW_ID, idc=IDC,
        arm="zh", up="-", variant="-", stage=stage,
        claim_id="c1", attempt=1,
    )


def _cell(run, seq, stage, status="ok", **kw):
    return events.make_event(
        events.T_CELL, run=run, seq=seq,
        id=kw.pop("id", RAW_ID), idc=kw.pop("idc", IDC),
        arm=kw.pop("arm", "zh"), up=kw.pop("up", "-"),
        variant=kw.pop("variant", "-"), stage=stage, status=status,
        dur_s=kw.pop("dur_s", 0.5), metrics=kw.pop("metrics", {}),
        errors=kw.pop("errors", []), sig=kw.pop("sig", ""),
        code=kw.pop("code", "abc123"), **kw,
    )


def _soak_events(run=RUN):
    """queued+started+terminal across 3 stages, then finished."""
    evs, seq = [], 0
    for stage in ("parse", "xlat", "compile"):
        evs.append(_queued(run, seq + 1, stage))
        evs.append(_started(run, seq + 2, stage))
        kw = {}
        if stage != "parse":
            kw["up"] = "mock"
        if stage == "xlat":
            kw["queue_wait_s"] = 1.25
        evs.append(_cell(run, seq + 3, stage, **kw))
        seq += 3
    evs.append(
        events.make_event(
            events.T_FINISHED, run=run, seq=seq + 1,
            wall_s=12.5, counts={"ok": 3}, cost_usd=0.0,
        )
    )
    return evs


def _emit_all(evs, rdir):
    for ev in evs:
        ledger.emit(ev, run_dir=rdir)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


# --- project_records ----------------------------------------------------------


def test_project_records_filters_and_raw_id(broot, tmp_path):
    idx = index_mod.Index()
    rdir, _n = _mint()
    _emit_all(_soak_events(), rdir)
    # a second run whose cells must not leak into run-filtered projections
    r2 = "soak-2026-09-21-t2"
    rdir2, _ = _mint(r2, KIND, DATE, "t2")
    _emit_all([_cell(r2, 1, "xlat", id="2101.00001", idc="2101.00001")], rdir2)
    idx.tail_ingest()

    rows = exporter.project_records(idx, run=RUN)
    assert len(rows) == 3  # one terminal cell per stage
    assert {r["stage"] for r in rows} == {"parse", "xlat", "compile"}
    for r in rows:
        assert set(r) >= LEGACY_KEYS
        # original spelling preserved — the deliberate §3.7 asymmetry
        assert r["id"] == RAW_ID
        assert r["id"] != IDC
    by_stage = {r["stage"]: r for r in rows}
    assert by_stage["parse"]["upstream"] == ""       # "-" sentinel -> ""
    assert by_stage["xlat"]["upstream"] == "mock"    # upstream arm verbatim
    assert by_stage["xlat"]["queue_wait_s"] == 1.25  # optional whitelist key
    assert "queue_wait_s" not in by_stage["parse"]
    assert by_stage["compile"]["code"] == "abc123"

    # stage filter
    xrows = exporter.project_records(idx, run=RUN, stage="xlat")
    assert len(xrows) == 1 and xrows[0]["stage"] == "xlat"

    # no filter -> both runs' cells
    allrows = exporter.project_records(idx)
    assert len(allrows) == 4
    idx.close()


def test_project_eval_records_lane(broot):
    idx = index_mod.Index(eval_stages={"judge"})
    rdir, _n = _mint()
    evs = _soak_events() + [
        _cell(RUN, 11, "judge", status="ok", metrics={"score": 95})
    ]
    _emit_all(evs, rdir)
    idx.tail_ingest()
    eval_rows = exporter.project_eval_records(idx, run=RUN)
    assert len(eval_rows) == 1
    assert eval_rows[0]["stage"] == "judge"
    assert eval_rows[0]["metrics"] == {"score": 95}
    idx.close()


def test_kernel_cat_surfaces_in_errors(broot):
    idx = index_mod.Index()
    rdir, _n = _mint()
    evs = [_cell(RUN, 1, "xlat", status="reject", cat="regen_gate")]
    _emit_all(evs, rdir)
    idx.tail_ingest()
    rows = exporter.project_records(idx, run=RUN)
    assert rows[0]["errors"] == [
        {"code": "regen_gate", "cat": "regen_gate", "payload": None}
    ]
    idx.close()


# --- export_run: soak family ----------------------------------------------------


def _mk_run_artifacts(rdir: Path):
    (rdir / "cases.jsonl").write_text(
        json.dumps({"corpus": IDC, "cond": "fixloop", "verdict": "clean"})
        + "\n"
    )
    (rdir / "invocations.jsonl").write_text(
        json.dumps({"flags": {"resume": True}, "spec_hash": "spechash0"})
        + "\n"
    )
    wdir = rdir / "work" / SID
    (wdir / "src").mkdir(parents=True)
    (wdir / "src" / "main.tex").write_text("\\documentclass{article}")
    (wdir / "zh.mock").mkdir()
    (wdir / "zh.mock" / "zh.tex").write_text("译文正文")
    (wdir / "splice.mock").mkdir()
    (wdir / "splice.mock" / "main.tex").write_text("spliced main")
    # not part of the legacy {src,zh,splice} projection — must be skipped
    (wdir / "xlat-state.zh").mkdir()
    (wdir / "xlat-state.zh" / "s.json").write_text("{}")
    (wdir / "state").mkdir()
    (wdir / "state" / "st.json").write_text("{}")
    return wdir


def test_export_run_soak_layout(broot, tmp_path):
    idx = index_mod.Index()
    rdir, run_seq = _mint()
    _emit_all(_soak_events(), rdir)
    wdir = _mk_run_artifacts(rdir)
    idx.tail_ingest()

    out_dir = tmp_path / "out"
    res = exporter.export_run(idx, rdir, out_dir)
    out = out_dir / RUN
    assert res["run"] == RUN
    assert res["family"] == "soak"
    assert res["rows"] == 3
    assert out.is_dir()

    # records/{stage}.jsonl — legacy schema + raw id spelling
    rec_dir = out / "records"
    assert {p.name for p in rec_dir.iterdir()} == {
        "parse.jsonl", "xlat.jsonl", "compile.jsonl",
    }
    xrows = _jsonl(rec_dir / "xlat.jsonl")
    assert len(xrows) == 1
    assert xrows[0]["id"] == RAW_ID
    assert xrows[0]["upstream"] == "mock"
    assert xrows[0]["queue_wait_s"] == 1.25

    # cases.jsonl — hardlink-farmed verbatim from the run dir
    assert (out / "cases.jsonl").is_file()
    assert _jsonl(out / "cases.jsonl") == [
        {"corpus": IDC, "cond": "fixloop", "verdict": "clean"}
    ]
    assert (
        os.stat(out / "cases.jsonl").st_ino
        == os.stat(rdir / "cases.jsonl").st_ino
    )

    # run_meta.json — union of runs row + finished event + invocations
    meta = json.loads((out / "run_meta.json").read_text())
    assert meta["name"] == RUN
    assert meta["kind"] == KIND
    assert meta["run_seq"] == run_seq
    assert meta["spec_hash"] == "spechash0"
    assert meta["counts"] == {"ok": 3}
    assert meta["wall_s"] == 12.5
    assert meta["finished_at"]
    assert len(meta["invocations"]) == 1
    assert meta["invocations"][0]["spec_hash"] == "spechash0"

    # work farm — single zh.mock/splice.mock project to legacy bare names,
    # sharing the source inode (same tmp volume -> real hardlinks)
    wout = out / "work" / SID
    assert (wout / "src" / "main.tex").is_file()
    assert (wout / "zh" / "zh.tex").is_file()
    assert (wout / "splice" / "main.tex").is_file()
    assert (
        os.stat(wout / "src" / "main.tex").st_ino
        == os.stat(wdir / "src" / "main.tex").st_ino
    )
    assert (
        os.stat(wout / "zh" / "zh.tex").st_ino
        == os.stat(wdir / "zh.mock" / "zh.tex").st_ino
    )
    # non-asset subtrees are not projected
    assert not (wout / "xlat-state.zh").exists()
    assert not (wout / "state").exists()
    idx.close()


def test_export_run_multi_arm_keeps_qualified_names(broot, tmp_path):
    idx = index_mod.Index()
    rdir, _n = _mint()
    _emit_all(_soak_events(), rdir)
    wdir = rdir / "work" / SID
    for arm in ("mock", "real"):
        (wdir / f"zh.{arm}").mkdir(parents=True)
        (wdir / f"zh.{arm}" / "zh.tex").write_text(f"zh {arm}")
    idx.tail_ingest()

    exporter.export_run(idx, rdir, tmp_path / "out")
    wout = tmp_path / "out" / RUN / "work" / SID
    # two zh.* dirs: neither may silently overwrite the other
    assert (wout / "zh.mock" / "zh.tex").read_text() == "zh mock"
    assert (wout / "zh.real" / "zh.tex").read_text() == "zh real"
    assert not (wout / "zh").exists()
    idx.close()


def test_export_run_by_name_and_fallback_cases(broot, tmp_path):
    idx = index_mod.Index()
    rdir, _n = _mint()
    _emit_all(_soak_events(), rdir)  # no cases.jsonl in rundir
    idx.tail_ingest()

    res = exporter.export_run(idx, RUN, tmp_path / "out")
    out = tmp_path / "out" / RUN
    assert res["family"] == "soak"
    # cases fall back to the index cases table (cell_queued payloads)
    crows = _jsonl(out / "cases.jsonl")
    assert len(crows) == 3
    assert all(c["type"] == "cell_queued" for c in crows)
    assert crows[0]["id"] == RAW_ID
    idx.close()


# --- export_run: e2e family -----------------------------------------------------


def test_export_run_e2e_flat_five_piece(broot, tmp_path):
    idx = index_mod.Index()
    run2 = "e2e-2026-09-21-m1"
    rdir2, _n = _mint(run2, "e2e", "2026-09-21", "m1")
    evs = [
        _cell(
            run2, 1, "e2e", id="2101.12345", idc="2101.12345",
            arm="-", variant="pipe-xel", status="clean",
            metrics={
                "verdict": {"status": "clean"},
                "translate": {"chunks": 3},
                "main": "a.tex",
            },
        ),
        _cell(
            run2, 2, "e2e", id="2101.12345", idc="2101.12345",
            arm="-", variant="base-xel", status="clean",
            metrics={"verdict": {"status": "clean"}},
        ),
        _cell(
            run2, 3, "e2e", id="2101.99999", idc="2101.99999",
            arm="-", variant="pipe-xel", status="fail",
            metrics={"verdict": {"status": "fail"}},
        ),
        events.make_event(
            events.T_FINISHED, run=run2, seq=4,
            wall_s=1.0, counts={"clean": 2, "fail": 1},
        ),
    ]
    _emit_all(evs, rdir2)
    idx.tail_ingest()

    res = exporter.export_run(idx, run2, tmp_path / "out")
    out = tmp_path / "out" / run2
    assert res["family"] == "e2e"
    names = {p.name for p in out.iterdir()}
    assert {
        "records.jsonl", "results.json", "matrix.md",
        "summary.md", "run_meta.json",
    } <= names
    assert not (out / "records").exists()
    assert not (out / "work").exists()

    # records.jsonl — one row per id, conds keyed by variant
    recs = _jsonl(out / "records.jsonl")
    assert [r["id"] for r in recs] == ["2101.12345", "2101.99999"]
    r0 = recs[0]
    assert r0["pipe-xel"]["translate"]["chunks"] == 3
    assert r0["base-xel"]["verdict"]["status"] == "clean"
    assert r0["main"] == "a.tex"          # case-level key lifted
    assert r0["status"] == "clean"        # last-write-wins
    assert recs[1]["status"] == "fail"

    # results.json — same rows keyed by id
    results = json.loads((out / "results.json").read_text())
    assert set(results) == {"2101.12345", "2101.99999"}
    assert results["2101.99999"]["pipe-xel"]["verdict"]["status"] == "fail"

    mtxt = (out / "matrix.md").read_text()
    assert "| 工程 | main |" in mtxt
    assert "pipe-xel" in mtxt and "base-xel" in mtxt
    stxt = (out / "summary.md").read_text()
    assert "pipe-xel" in stxt and "fail" in stxt

    meta = json.loads((out / "run_meta.json").read_text())
    assert meta["name"] == run2
    assert meta["kind"] == "e2e"
    assert meta["counts"] == {"clean": 2, "fail": 1}
    assert res["rows"] == 2
    idx.close()


def test_export_mode_forced(broot, tmp_path):
    """A non-e2e kind forced to e2e still produces the flat five-piece."""
    idx = index_mod.Index()
    rdir, _n = _mint()
    _emit_all(_soak_events(), rdir)
    idx.tail_ingest()
    res = exporter.export_run(idx, rdir, tmp_path / "out", mode="e2e")
    out = tmp_path / "out" / RUN
    assert res["family"] == "e2e"
    assert (out / "records.jsonl").is_file()
    assert not (out / "records").exists()
    with pytest.raises(ValueError):
        exporter.export_run(idx, rdir, tmp_path / "o2", mode="bogus")
    idx.close()


# --- export_all -----------------------------------------------------------------


def test_export_all(broot, tmp_path):
    idx = index_mod.Index()
    rdir, _n = _mint()
    _emit_all(_soak_events(), rdir)
    r2 = "e2e-2026-09-21-m1"
    rdir2, _ = _mint(r2, "e2e", DATE, "m1")
    _emit_all(
        [
            _cell(r2, 1, "e2e", id="2101.00001", idc="2101.00001",
                  arm="-", variant="pipe-xel", status="clean"),
        ],
        rdir2,
    )
    idx.tail_ingest()

    res = exporter.export_all(idx, tmp_path / "out")
    assert (tmp_path / "out" / RUN / "records" / "xlat.jsonl").is_file()
    assert (tmp_path / "out" / r2 / "records.jsonl").is_file()
    assert res["rows"] == 4  # 3 soak cells + 1 e2e case row
    assert set(res["runs"]) == {RUN, r2}
    idx.close()


# --- events.jsonl shard as source ------------------------------------------------


def test_export_uses_run_shard_without_index_rows(broot, tmp_path):
    """With an empty index the rundir shard still yields the full export."""
    idx = index_mod.Index()  # never ingested — index knows nothing
    rdir, _n = _mint()
    _emit_all(_soak_events(), rdir)
    res = exporter.export_run(idx, rdir, tmp_path / "out")
    out = tmp_path / "out" / RUN
    assert res["rows"] == 3
    xrows = _jsonl(out / "records" / "xlat.jsonl")
    assert xrows[0]["id"] == RAW_ID
    meta = json.loads((out / "run_meta.json").read_text())
    assert meta["counts"] == {"ok": 3}   # finished event read from the shard
    idx.close()
