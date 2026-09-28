"""Tests for kernel/runs.py — the runs zone (identity triple materialization,
frozen plans, heartbeats, the accounting equation, the single delete verb).

Every test runs against an isolated $TEXLATE_BENCH_ROOT via `broot`.
"""

from __future__ import annotations

import json
import os
import threading
import time

import pytest
from kernel import events, ledger, locks, paths, runs

# 每个测试都要隔离 BENCH_ROOT——broot 只要副作用，全模块钉版不再逐个形参声明
pytestmark = pytest.mark.usefixtures("broot")

# 刚 touch 过的心跳 age 上界：远小于内核新鲜阈 _HEARTBEAT_FRESH_S(600s) 的宽限
_RECENT_HEARTBEAT_S = 5


def _cell(id_: str, arm: str = "zh", stage: str = "xlat") -> dict:
    return {
        "id": id_,
        "idc": id_,
        "arm": arm,
        "up": "-",
        "variant": "-",
        "stage": stage,
        "needs": [],
        "fp_input": None,
    }


def _queued(rd: runs.RunDir, seq: int, id_: str, stage: str = "xlat") -> dict:
    ev = events.make_event(
        events.T_CELL_QUEUED,
        run=rd.run,
        seq=seq,
        id=id_,
        idc=id_,
        arm="zh",
        up="-",
        variant="-",
        stage=stage,
    )
    ledger.emit(ev, run_dir=rd.path)
    return ev


def _terminal(
    rd: runs.RunDir, seq: int, id_: str, status: str = "ok", stage: str = "xlat"
) -> dict:
    ev = events.make_event(
        events.T_CELL,
        run=rd.run,
        seq=seq,
        id=id_,
        idc=id_,
        arm="zh",
        up="-",
        variant="-",
        stage=stage,
        status=status,
    )
    ledger.emit(ev, run_dir=rd.path)
    return ev


def _shard(rd: runs.RunDir) -> list[dict]:
    return [
        ev for _ln, ev, _raw in events.iter_jsonl(rd.events_path()) if ev is not None
    ]


# --- create_run layout (§1 tree) -------------------------------------------------


def test_create_run_layout_matches_spec_tree() -> None:
    rd = runs.create_run(
        "soak",
        spec_dict={"kind": "soak", "params": {"n": 3}},
        spec_env={"python": "3.14"},
    )
    rdir = rd.path
    assert rdir == paths.run_dir("soak", rd.date, "soak")
    # the §1 run-dir tree
    for rel in (
        "spec.json",
        "spec_env.json",
        "invocations.jsonl",
        "events.jsonl",
        ".lock",
        "heartbeat",
    ):
        assert (rdir / rel).exists(), rel
    assert (rdir / "work" / "_texmf").is_dir()
    assert (rdir / "derived").is_dir()
    assert json.loads((rdir / "spec.json").read_text()) == {
        "kind": "soak",
        "params": {"n": 3},
    }
    assert json.loads((rdir / "spec_env.json").read_text()) == {"python": "3.14"}
    assert (rdir / "invocations.jsonl").read_bytes() == b""
    # run_registered dual-written into the shard by mint
    shard = _shard(rd)
    regs = [e for e in shard if e["type"] == "run_registered"]
    assert len(regs) == 1
    assert regs[0]["run_seq"] == rd.run_seq == 1
    assert regs[0]["run"] == f"soak/{rd.date}/soak"
    # runs.jsonl report row
    rows = [
        r
        for _ln, r, _raw in events.iter_jsonl(paths.runs_jsonl_path())
        if r is not None
    ]
    assert rows == [
        {
            "run": f"soak/{rd.date}/soak",
            "run_seq": 1,
            "kind": "soak",
            "date": rd.date,
            "slug": "soak",
            "spec_hash": regs[0]["spec_hash"],
            "ts_start": rows[0]["ts_start"],
        }
    ]


def test_create_run_default_date_is_utc() -> None:
    rd = runs.create_run("adhoc")
    assert rd.date == time.strftime("%Y-%m-%d", time.gmtime())


def test_create_run_slug_unique_suffix() -> None:
    rd1 = runs.create_run("soak", date="2026-09-21")
    rd2 = runs.create_run("soak", date="2026-09-21")
    rd3 = runs.create_run("soak", date="2026-09-21")
    assert (rd1.slug, rd2.slug, rd3.slug) == ("soak", "soak-2", "soak-3")
    assert (rd1.run_seq, rd2.run_seq, rd3.run_seq) == (1, 2, 3)


def test_create_run_explicit_slug_collision_raises() -> None:
    runs.create_run("soak", slug="w1", date="2026-09-21")
    with pytest.raises(FileExistsError):
        runs.create_run("soak", slug="w1", date="2026-09-21")


def test_create_run_bad_components_rejected() -> None:
    with pytest.raises(ValueError, match=r"kind.*not a safe path component"):
        runs.create_run("bad/kind")
    with pytest.raises(ValueError, match=r"slug.*not a safe path component"):
        runs.create_run("soak", slug="../x")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        runs.create_run("soak", date="09/21")


def test_load_run_reattaches() -> None:
    rd = runs.create_run("fixloop", slug="f1", date="2026-09-21")
    rd2 = runs.load_run("fixloop", "2026-09-21", "f1")
    assert rd2.path == rd.path
    assert rd2.run_seq == rd.run_seq
    with pytest.raises(FileNotFoundError):
        runs.load_run("fixloop", "2026-09-21", "nope")


# --- freeze_plan --------------------------------------------------------------------


def test_freeze_plan_writes_then_reuses_verbatim() -> None:
    rd = runs.create_run("soak", date="2026-09-21")
    cells = [_cell("2401.00001"), _cell("2401.00002")]
    got = runs.freeze_plan(rd, cells)
    assert rd.plan_path().exists()
    on_disk = json.loads(rd.plan_path().read_text())
    assert on_disk == {"cells": got}
    assert got[0]["idc"] == "2401.00001"

    # frozen: a different enumeration is ignored — the file wins verbatim
    other = [_cell("9999.99999")]
    again = runs.freeze_plan(rd, other)
    assert again == got
    assert json.loads(rd.plan_path().read_text()) == {"cells": got}

    # replan=True re-enumerates and rewrites
    replanned = runs.freeze_plan(rd, other, replan=True)
    assert replanned[0]["idc"] == "9999.99999"
    assert json.loads(rd.plan_path().read_text()) == {"cells": replanned}


# --- invocations / cases ----------------------------------------------------------------


def test_add_invocation_and_case() -> None:
    rd = runs.create_run("xlat", date="2026-09-21")
    runs.add_invocation(
        rd, {"resume": True, "max_cost": 5}, spec_hash="abc", code_stamp="def"
    )
    runs.add_invocation(rd, {"resume": True}, spec_hash="abc")
    rows = [
        r for _ln, r, _raw in events.iter_jsonl(rd.invocations_path()) if r is not None
    ]
    assert [r["flags"] for r in rows] == [
        {"resume": True, "max_cost": 5},
        {"resume": True},
    ]
    assert rows[0]["spec_hash"] == "abc"
    assert rows[0]["code_stamp"] == "def"

    runs.add_case(rd, {"id": "2401.00001", "verdict": "primary"})
    cases = [r for _ln, r, _raw in events.iter_jsonl(rd.cases_path()) if r is not None]
    assert cases == [{"id": "2401.00001", "verdict": "primary"}]


# --- cell_lock -----------------------------------------------------------------------------


def test_cell_lock_serializes_same_id() -> None:
    rd = runs.create_run("soak", date="2026-09-21")
    order: list[tuple[str, str]] = []

    def worker(tag: str) -> None:
        with runs.cell_lock(rd, "2401--00001"):
            order.append(("enter", tag))
            time.sleep(0.05)
            order.append(("exit", tag))

    t = threading.Thread(target=worker, args=("B",))
    with runs.cell_lock(rd, "2401--00001"):
        order.append(("enter", "A"))
        t.start()
        time.sleep(0.05)
        order.append(("exit", "A"))
    t.join(timeout=5)
    # serialized: A fully exits before B enters
    assert order == [("enter", "A"), ("exit", "A"), ("enter", "B"), ("exit", "B")]


def test_cell_lock_nb_raises_while_held() -> None:
    rd = runs.create_run("soak", date="2026-09-21")
    with runs.cell_lock(rd, "s1"):
        assert not locks.lock_free(rd.cell_lock_path("s1"))
    assert locks.lock_free(rd.cell_lock_path("s1"))


def test_run_lock_nb_failfast() -> None:
    rd = runs.create_run("soak", date="2026-09-21")
    with rd.lock(), pytest.raises(locks.WouldBlock), rd.lock():
        pass
    # released
    with rd.lock():
        pass


# --- heartbeat / active_runs -----------------------------------------------------------------


def test_heartbeat_loop_touches_until_stopped() -> None:
    rd = runs.create_run("soak", date="2026-09-21")
    hb = rd.heartbeat_path()
    old = time.time() - 3600
    os.utime(hb, (old, old))
    stop = threading.Event()
    t = threading.Thread(
        target=runs.heartbeat_loop,
        args=(rd,),
        kwargs={"interval_s": 0.02, "stop_event": stop},
        daemon=True,
    )
    t.start()
    time.sleep(0.08)
    stop.set()
    t.join(timeout=5)
    assert locks.heartbeat_age(hb) < 1.0


def test_active_runs_fresh_locked_only() -> None:
    rd = runs.create_run("soak", date="2026-09-21")
    # fresh heartbeat but NO lock held -> not active
    rd.heartbeat_touch()
    assert runs.active_runs() == []
    # fresh heartbeat + lock held -> active
    with rd.lock():
        got = runs.active_runs()
        assert [g["run"] for g in got] == [rd.run]
        assert got[0]["kind"] == "soak"
        assert got[0]["slug"] == "soak"
        assert got[0]["heartbeat_age"] < _RECENT_HEARTBEAT_S
        # stale heartbeat + lock held -> zombie, not active
        old = time.time() - 3600
        os.utime(rd.heartbeat_path(), (old, old))
        assert runs.active_runs() == []


def test_active_runs_ignores_non_run_dirs() -> None:
    stray = paths.runs_dir() / "soak" / "2026-09-21"
    stray.mkdir(parents=True)
    (stray / "not-a-run").write_text("x")  # file, not dir
    assert runs.active_runs() == []


# --- accounting_check ---------------------------------------------------------------------------


def test_accounting_check_balanced_run_is_ok() -> None:
    rd = runs.create_run("soak", date="2026-09-21")
    cells = [_cell("2401.00001"), _cell("2401.00002")]
    runs.freeze_plan(rd, cells)
    _queued(rd, 1, "2401.00001")
    _queued(rd, 2, "2401.00002")
    _terminal(rd, 3, "2401.00001")
    _terminal(rd, 4, "2401.00002", status="fail")
    res = runs.accounting_check(rd)
    assert res["ok"] is True
    assert res["plan"] == len(cells)
    assert res["queued"] == len(cells)
    assert res["terminal"] == len(cells)
    assert res["missing_terminal"] == []
    assert res["extra_queued"] == []


def test_accounting_check_missing_terminal_and_extra_queued() -> None:
    rd = runs.create_run("soak", date="2026-09-21")
    runs.freeze_plan(rd, [_cell("2401.00001"), _cell("2401.00002")])
    _queued(rd, 1, "2401.00001")
    _queued(rd, 2, "2401.00002")
    _queued(rd, 3, "2401.00003")  # queued but NOT in plan
    _terminal(rd, 4, "2401.00001")  # 2401.00002, 2401.00003 hang
    res = runs.accounting_check(rd)
    assert res["ok"] is False
    missing = [k[0] for k in res["missing_terminal"]]
    assert sorted(missing) == ["2401.00002", "2401.00003"]
    assert [k[0] for k in res["extra_queued"]] == ["2401.00003"]


def test_accounting_check_dup_terminal_is_violation() -> None:
    rd = runs.create_run("soak", date="2026-09-21")
    runs.freeze_plan(rd, [_cell("2401.00001")])
    _queued(rd, 1, "2401.00001")
    _terminal(rd, 2, "2401.00001")
    _terminal(rd, 3, "2401.00001", status="fail")  # second terminal: not 恰一个
    res = runs.accounting_check(rd)
    assert res["ok"] is False
    assert [k[0] for k in res["dup_terminal"]] == ["2401.00001"]


def test_accounting_check_no_plan_flags_all_queued() -> None:
    rd = runs.create_run("soak", date="2026-09-21")
    _queued(rd, 1, "2401.00001")
    _terminal(rd, 2, "2401.00001")
    res = runs.accounting_check(rd)
    assert res["ok"] is False
    assert [k[0] for k in res["extra_queued"]] == ["2401.00001"]


# --- remove_cell_tree ------------------------------------------------------------------------------


def test_remove_cell_tree_deletes_and_notes() -> None:
    rd = runs.create_run("soak", date="2026-09-21")
    cell = rd.work("2401--00001")
    (cell / "zh.mock").mkdir(parents=True)
    (cell / "zh.mock" / "out.pdf").write_bytes(b"pdf")
    removed = runs.remove_cell_tree(rd, "2401--00001")
    assert removed == cell
    assert not cell.exists()
    # note emitted to BOTH ledger and the run shard (dual-write)
    notes = [e for e in _shard(rd) if e["type"] == "note"]
    assert len(notes) == 1
    assert "2401--00001" in notes[0]["text"]
    ledger_notes = [
        e
        for _ln, e, _raw in events.iter_jsonl(paths.events_path())
        if e is not None and e["type"] == "note"
    ]
    assert len(ledger_notes) == 1
    assert ledger_notes[0]["run"] == rd.run
    # kernel rows carry negative seqs — no collision with executor mints
    assert notes[0]["seq"] < 0


def test_remove_cell_tree_missing_dir_still_notes() -> None:
    rd = runs.create_run("soak", date="2026-09-21")
    runs.remove_cell_tree(rd, "ghost--00000")  # no-op delete, note still lands
    notes = [e for e in _shard(rd) if e["type"] == "note"]
    assert len(notes) == 1


def test_remove_cell_tree_blocks_unpaid_unharvested() -> None:
    rd = runs.create_run("soak", date="2026-09-21")
    cell = rd.work("2401--00002")
    (cell / "zh.mock").mkdir(parents=True)
    (cell / "zh.mock" / "out.pdf").write_bytes(b"paid bytes")
    with pytest.raises(runs.BlockedDelete):
        runs.remove_cell_tree(rd, "2401--00002", vault_check=lambda: False)
    assert (cell / "zh.mock" / "out.pdf").exists()  # nothing was deleted
    # the block is on the books — a warn note, not silent
    notes = [e for e in _shard(rd) if e["type"] == "note"]
    assert len(notes) == 1
    assert notes[0]["level"] == "warn"
    assert "BLOCKED" in notes[0]["text"]


def test_remove_cell_tree_vault_secured_deletes() -> None:
    rd = runs.create_run("soak", date="2026-09-21")
    cell = rd.work("2401--00003")
    (cell / "zh.mock").mkdir(parents=True)
    (cell / "zh.mock" / "out.pdf").write_bytes(b"harvested")
    runs.remove_cell_tree(rd, "2401--00003", vault_check=lambda: True)
    assert not cell.exists()
