"""tests/kernel/test_index.py — index.sqlite projection contract.

Covers: rebuild equivalence across all event types, tail_ingest watermark
semantics, (run_seq,seq) replay vs conflict-quarantine, sealed oracle
fail-closed behavior, paid_pool / vault_bytes_ok / active_claims
projections, and rebuild refusal while the kernel is active.
"""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3

import pytest
from kernel import events, paths
from kernel.index import Index, ingest_runless, rebuild_index

IDC = "cs/2401.00001"
IDC2 = "hep-ph/9901223"


# -- helpers ---------------------------------------------------------------------


def _append(evs) -> int:
    """Append events to the hot-tail ledger; returns bytes written."""
    p = paths.events_path()
    n = 0
    with open(p, "a", encoding="utf-8") as f:
        for ev in evs:
            line = events.dumps(ev) + "\n"
            f.write(line)
            n += len(line.encode("utf-8"))
    return n


def _run(run="r1", run_seq=1, **kw):
    return events.make_event(
        events.T_RUN_REGISTERED,
        run=run,
        run_seq=run_seq,
        kind="xlat",
        date="2026-09-21",
        slug=run,
        spec_hash="abc",
        ts_start=1.0,
        **kw,
    )


def _queued(seq, run="r1", idc=IDC, stage="xlat", **kw):
    kw.setdefault("id", idc)
    return events.make_event(
        events.T_CELL_QUEUED,
        run=run,
        seq=seq,
        idc=idc,
        arm="zh",
        up="-",
        variant="-",
        stage=stage,
        needs=[],
        fp_input="fp0",
        **kw,
    )


def _started(seq, run="r1", idc=IDC, stage="xlat", **kw):
    kw.setdefault("id", idc)
    return events.make_event(
        events.T_CELL_STARTED,
        run=run,
        seq=seq,
        idc=idc,
        arm="zh",
        up="-",
        variant="-",
        stage=stage,
        claim_id="c1",
        attempt=1,
        **kw,
    )


def _cell(seq, run="r1", idc=IDC, status="ok", stage="xlat", arm="zh", **kw):
    kw.setdefault("id", idc)
    return events.make_event(
        events.T_CELL,
        run=run,
        seq=seq,
        idc=idc,
        arm=arm,
        up="-",
        variant="-",
        stage=stage,
        status=status,
        dur_s=1.5,
        sig="cat:pay",
        code="deadbeef",
        fp="fp1",
        **kw,
    )


def _claim(seq, op, run="r1", idc=IDC, slot=None, **kw):
    kw.setdefault("id", idc)
    ev = events.make_event(
        events.T_CLAIM, run=run, seq=seq, idc=idc, arm="zh", variant="-", op=op, **kw
    )
    if slot is not None:
        ev["slot"] = slot
    return ev


def _asset(seq, idc=IDC, kind="zh", state="verified", run="r1", **kw):
    kw.setdefault("id", idc)
    return events.make_event(
        events.T_ASSET,
        run=run,
        seq=seq,
        idc=idc,
        arm="zh",
        variant="-",
        kind=kind,
        path=f"vault/{kind}/{idc}",
        sha="sha1",
        bytes=123,
        state=state,
        **kw,
    )


def _tombstone(idc=IDC, kind="zh", **kw):
    kw.setdefault("id", idc)
    return events.make_event(
        events.T_TOMBSTONE,
        idc=idc,
        arm="zh",
        variant="-",
        kind=kind,
        reason="lost bytes",
        lost_run="r0",
        **kw,
    )


def _count(idx, table):
    return idx.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# -- rebuild -----------------------------------------------------------------------


def test_rebuild_equivalence_all_types(broot):
    evs = [
        _run(),
        _queued(1),
        _started(2),
        _cell(3, status="ok"),
        _claim(4, "acquire", slot="s0"),
        _claim(5, "release", slot="s0"),
        _claim(6, "acquire", idc=IDC2),
        _asset(7, state="verified"),
        _tombstone(idc=IDC2),
        events.make_event(events.T_NOTE, run="r1", seq=8, text="hi", level="info"),
        events.make_event(
            events.T_FINISHED,
            run="r1",
            seq=9,
            wall_s=2.0,
            counts={"ok": 1},
            cost_usd=0.01,
        ),
        events.make_event(events.T_LAKE_CELL, id=IDC, idc=IDC, state="hydrated"),
    ]
    size = _append(evs)
    idx = Index()
    applied = idx.rebuild()
    assert applied == len(evs)

    # cells / done
    assert idx.done(IDC, "zh", "-", "-", "xlat")
    cell = idx.last_cell(IDC, "zh", "-", "-", "xlat")
    assert cell["status"] == "ok" and cell["last_run"] == "r1"
    assert cell["last_seq"] == 3

    # records / cases / assets / runs / papers
    assert _count(idx, "records") == 1
    assert _count(idx, "cases") == 1
    assert _count(idx, "assets") == 1
    assert _count(idx, "runs") == 1
    row = idx.conn.execute("SELECT * FROM papers WHERE idc=?", (IDC,)).fetchone()
    assert row is not None and row["id_raw"] == IDC

    # claims: IDC released → only IDC2 lease active
    assert idx.active_claims() == {(IDC2, "zh", "-")}
    # paid_slots: s0 released → empty
    assert _count(idx, "paid_slots") == 0
    # vault: IDC verified (bytes ok); IDC2 tombstoned (not ok)
    assert (IDC, "zh", "-") in idx.vault_bytes_ok()
    assert (IDC2, "zh", "-") not in idx.vault_bytes_ok()
    # paid pool
    assert idx.paid_pool() == {(IDC, "zh", "-")}

    # sealed state: gen bumped, watermark = file tail
    gen, wm = idx.sealed_state()
    assert gen == 1 and wm == size
    assert idx.check_sealed(gen, wm)

    # every row in events mirror
    assert _count(idx, "events") == len(evs)
    idx.close()


def test_rebuild_idempotent_and_gen_bumps(broot):
    _append([_run(), _cell(1)])
    idx = Index()
    idx.rebuild()
    g1, wm1 = idx.sealed_state()
    idx.rebuild()
    g2, wm2 = idx.sealed_state()
    assert g2 == g1 + 1 and wm2 == wm1
    assert _count(idx, "events") == 2
    assert _count(idx, "records") == 1
    idx.close()


def test_rebuild_empty_ledger(broot):
    idx = Index()
    assert idx.rebuild() == 0
    assert idx.sealed_state() == (1, 0)
    assert idx.check_sealed(1, 0)
    idx.close()


def test_rebuild_refused_when_kernel_active(broot):
    """Rebuild must refuse while the kernel holds .kernel-active (§3.2)."""
    idx = Index()
    hold_fd = None
    ctx = None
    try:
        from kernel import locks

        hold = getattr(locks, "kernel_active_hold", None)
    except ImportError:
        hold = None
    if hold is not None:
        ctx = hold()
        ctx.__enter__()
    else:
        # Fallback: the authoritative liveness proof is an flock on the
        # .kernel-active sentinel — hold it like the kernel would.
        hold_fd = os.open(paths.kernel_active_path(), os.O_CREAT | os.O_RDWR)
        fcntl.flock(hold_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(RuntimeError):
            idx.rebuild()
    finally:
        if ctx is not None:
            ctx.__exit__(None, None, None)
        if hold_fd is not None:
            fcntl.flock(hold_fd, fcntl.LOCK_UN)
            os.close(hold_fd)
    # released → rebuild proceeds
    assert idx.rebuild() == 0
    idx.close()


# -- tail_ingest --------------------------------------------------------------------


def test_tail_ingest_incremental_watermark(broot):
    idx = Index()
    e1 = _cell(1, status="ok")
    n1 = _append([e1])
    assert idx.tail_ingest() == 1
    assert idx.sealed_state() == (0, n1)

    n2 = _append([_cell(2, idc=IDC2, status="fail")])
    # torn tail: partial line with no newline must not be consumed
    frag = '{"type":"note","run":"r1","seq":99'
    with open(paths.events_path(), "a", encoding="utf-8") as f:
        f.write(frag)
    assert idx.tail_ingest() == 1
    assert idx.sealed_state() == (0, n1 + n2)

    # finish the torn line — the completed note is consumed next pass
    with open(paths.events_path(), "a", encoding="utf-8") as f:
        rest = ',"text":"done","level":"info","ts":1.0,"v":1}\n'
        f.write(rest)
    n3 = len(frag.encode()) + len(rest.encode())
    assert idx.tail_ingest() == 1  # the completed note line now applies
    gen, wm = idx.sealed_state()
    assert wm == n1 + n2 + n3
    idx.close()


def test_tail_ingest_exact_watermark_math(broot):
    evs = [_run(), _cell(1), _cell(2, idc=IDC2)]
    total = _append(evs)
    idx = Index()
    assert idx.tail_ingest() == 3
    # watermark sits exactly past the last newline → next ingest is a no-op
    assert idx.tail_ingest() == 0
    assert idx.sealed_state()[1] == total == paths.events_path().stat().st_size
    idx.close()


def test_tail_ingest_shrunken_ledger_resets(broot):
    """Locked truncate+rewrite must not strand the watermark."""
    _append([_cell(1), _cell(2)])
    idx = Index()
    assert idx.tail_ingest() == 2
    p = paths.events_path()
    ev = _cell(9, idc=IDC2, status="ok")
    p.write_text(events.dumps(ev) + "\n")  # shorter rewrite
    assert idx.tail_ingest() == 1
    assert idx.sealed_state()[1] == p.stat().st_size
    idx.close()


def test_tail_ingest_missing_file(broot):
    paths.events_path().unlink()
    idx = Index()
    assert idx.tail_ingest() == 0
    idx.close()


# -- dedup / quarantine ---------------------------------------------------------------


def test_same_payload_replay_counts_dedup_skip(broot):
    idx = Index()
    ev = _cell(5, run_seq=1)
    assert idx.apply_event(ev) == "applied"
    assert idx.apply_event(ev) == "replay"
    assert idx.apply_event(dict(ev)) == "replay"
    assert idx.dedup_skip_count() == 2
    assert _count(idx, "events") == 1
    assert _count(idx, "records") == 1
    idx.close()


def test_conflict_different_payload_quarantines(broot):
    idx = Index()
    ev1 = _cell(5, run_seq=1, status="ok")
    ev2 = _cell(5, run_seq=1, status="fail")  # same (run_seq,seq), new payload
    assert idx.apply_event(ev1) == "applied"
    assert idx.apply_event(ev2) == "quarantined"

    qp = paths.quarantine_path()
    lines = qp.read_text().strip().split("\n")
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["reason"] == "seq_conflict"
    assert rec["run_seq"] == 1 and rec["seq"] == 5
    assert rec["payload_sha"] != rec["existing_sha"]

    # loser did not land; original row stands
    assert _count(idx, "events") == 1
    assert idx.last_cell(IDC, "zh", "-", "-", "xlat")["status"] == "ok"

    # replaying the quarantined payload dedups, does not re-quarantine
    assert idx.apply_event(ev2) == "replay"
    assert len(qp.read_text().strip().split("\n")) == 1
    assert idx.dedup_skip_count() == 1
    idx.close()


def test_runless_events_dedup_by_payload(broot):
    idx = Index()
    tomb = _tombstone()
    assert ingest_runless(tomb, idx) == "applied"
    assert ingest_runless(tomb, idx) == "replay"
    row = idx.conn.execute(
        "SELECT run_seq FROM events WHERE payload_sha=?", (events.content_hash(tomb),)
    ).fetchone()
    assert row["run_seq"] == -1
    assert _count(idx, "events") == 1
    idx.close()


def test_run_seq_resolved_via_runs_table(broot):
    """Events lacking run_seq resolve it from the runs projection."""
    idx = Index()
    idx.apply_event(_run(run="r7", run_seq=7))
    ev = _cell(3, run="r7")
    ev.pop("run_seq", None)
    assert idx.apply_event(ev) == "applied"
    row = idx.conn.execute("SELECT run_seq FROM events WHERE seq=3").fetchone()
    assert row["run_seq"] == 7
    idx.close()


# -- sealed oracle ---------------------------------------------------------------------


def test_check_sealed_fail_closed(broot):
    _append([_cell(1)])
    idx = Index()
    idx.rebuild()
    gen, wm = idx.sealed_state()
    assert idx.check_sealed(gen, wm)
    assert not idx.check_sealed(gen, wm + 1)  # stale watermark → refuse
    assert not idx.check_sealed(gen + 1, 0)  # wrong gen → refuse
    assert not idx.check_sealed(gen - 1, 0)
    idx.note_dirty("test")
    assert idx.dirty()
    assert not idx.check_sealed(gen, wm)  # dirty flag → refuse
    idx.rebuild()
    assert not idx.dirty()  # rebuild clears flag
    gen2, _ = idx.sealed_state()
    assert gen2 == gen + 1
    assert not idx.check_sealed(gen, wm)  # old snapshot gen refused
    assert idx.check_sealed(gen2, wm)
    idx.close()


def test_check_sealed_needs_ingest_first(broot):
    """Index built before a ledger append must fail the seal check until
    tail_ingest catches up (watermark < run's fsync offset)."""
    _append([_cell(1)])
    idx = Index()
    idx.rebuild()
    gen, wm = idx.sealed_state()
    n = _append([_cell(2, idc=IDC2)])
    assert not idx.check_sealed(gen, wm + n)  # not yet ingested
    idx.tail_ingest()
    assert idx.check_sealed(gen, wm + n)
    idx.close()


# -- projections -----------------------------------------------------------------------


def test_paid_pool_only_ok_partial(broot):
    _append(
        [
            _cell(1, idc="a/1", status="ok"),
            _cell(2, idc="a/2", status="partial"),
            _cell(3, idc="a/3", status="fail"),
            _cell(4, idc="a/4", status="reject"),
            _cell(5, idc="a/5", status="error"),  # retriable — not terminal
        ]
    )
    idx = Index()
    idx.rebuild()
    assert idx.paid_pool() == {("a/1", "zh", "-"), ("a/2", "zh", "-")}
    assert idx.done("a/3", "zh", "-", "-", "xlat")  # fail is terminal
    assert not idx.done("a/5", "zh", "-", "-", "xlat")  # error is retriable
    idx.close()


def test_done_runs_scope_and_last_cell(broot):
    _append([_cell(1, run="rA", status="ok")])
    idx = Index()
    idx.rebuild()
    assert idx.done(IDC, "zh", "-", "-", "xlat", runs=["rA"])
    assert not idx.done(IDC, "zh", "-", "-", "xlat", runs=["rB"])
    assert idx.done(IDC, "zh", "-", "-", "xlat")  # unscoped
    # a later queued event from another run flips the cell back to non-terminal
    idx.apply_event(_queued(2, run="rB"))
    assert not idx.done(IDC, "zh", "-", "-", "xlat")
    cell = idx.last_cell(IDC, "zh", "-", "-", "xlat")
    assert cell["status"] == "queued" and cell["last_run"] == "rB"
    idx.close()


def test_kernel_statuses_are_terminal(broot):
    """dedup/claimed/lost/unpaid_gate must count as done — never re-burn."""
    for i, st in enumerate(["dedup", "claimed", "lost", "unpaid_gate"], 1):
        _append([_cell(i, idc=f"a/{i}", status=st)])
    idx = Index()
    idx.rebuild()
    for i in range(1, 5):
        assert idx.done(f"a/{i}", "zh", "-", "-", "xlat")
    idx.close()


def test_active_claims_last_op_wins(broot):
    _append(
        [
            _claim(1, "acquire", idc="a/1"),
            _claim(2, "acquire", idc="a/2"),
            _claim(3, "release", idc="a/1"),
            _claim(4, "acquire", idc="a/3"),
            _claim(5, "reap", idc="a/3"),
        ]
    )
    idx = Index()
    idx.rebuild()
    assert idx.active_claims() == {("a/2", "zh", "-")}
    idx.close()


def test_paid_slots_follow_slot_ops(broot):
    _append(
        [
            _claim(1, "acquire", idc="a/1", slot="s0"),
            _claim(2, "acquire", idc="a/2", slot="s1"),
            _claim(3, "release", idc="a/1", slot="s0"),
        ]
    )
    idx = Index()
    idx.rebuild()
    rows = idx.conn.execute("SELECT slot, idc FROM paid_slots").fetchall()
    assert {r["slot"]: r["idc"] for r in rows} == {"s1": "a/2"}
    idx.close()


def test_vault_bytes_ok_lifecycle(broot):
    _append(
        [
            _asset(1, idc="a/1", state="verified"),
            _asset(2, idc="a/2", state="pending"),
            _asset(3, idc="a/3", state="staged"),
            _tombstone(idc="a/1"),  # verified → lost: must leave the ok set
        ]
    )
    idx = Index()
    idx.rebuild()
    ok = idx.vault_bytes_ok()
    assert ("a/1", "zh", "-") not in ok  # tombstoned
    assert ("a/2", "zh", "-") not in ok  # pending = treated as no-bytes
    assert ("a/3", "zh", "-") not in ok  # staged pending likewise
    # an explicit primary verdict lands bytes-ok
    idx.apply_event(_asset(4, idc="a/4", state="verified", verdict="primary"))
    assert ("a/4", "zh", "-") in idx.vault_bytes_ok()
    idx.close()


def test_eval_records_routing(broot):
    idx = Index(eval_stages={"score"})
    idx.apply_event(_cell(1, stage="xlat"))
    idx.apply_event(_cell(2, stage="score", idc=IDC2))
    tagged = _cell(3, stage="other", idc="a/9")
    tagged["eval"] = 1  # caller-tagged row (import paths)
    idx.apply_event(tagged)
    assert _count(idx, "records") == 3
    rows = idx.conn.execute(
        "SELECT stage, idc FROM eval_records ORDER BY seq"
    ).fetchall()
    assert [(r["stage"], r["idc"]) for r in rows] == [("score", IDC2), ("other", "a/9")]
    idx.close()


def test_papers_first_spelling_wins(broot):
    idx = Index()
    idx.apply_event(_cell(1, idc=IDC))
    ev2 = _cell(2, run="r2", idc=IDC)
    ev2["id"] = "cs/2401.00001v2"  # later event, different raw spelling
    idx.apply_event(ev2)
    row = idx.conn.execute("SELECT * FROM papers WHERE idc=?", (IDC,)).fetchone()
    assert row["id_raw"] == IDC  # INSERT OR IGNORE — first-seen stays
    idx.close()


def test_bad_line_counted_not_fatal(broot):
    p = paths.events_path()
    with open(p, "a", encoding="utf-8") as f:
        f.write(events.dumps(_cell(1)) + "\n")
        f.write("{this is not json\n")
        f.write("42\n")  # valid JSON, wrong shape — also a bad line
        f.write("null\n")
        f.write(events.dumps(_cell(2, idc=IDC2)) + "\n")
    idx = Index()
    assert idx.tail_ingest() == 2
    assert int(idx._meta_get("bad_lines")) == 3
    idx.close()


# -- module conveniences -----------------------------------------------------------------


def test_rebuild_index_and_schema_drift(broot):
    _append([_cell(1)])
    idx = rebuild_index()
    assert idx.done(IDC, "zh", "-", "-", "xlat")
    idx.close()
    # simulate schema drift → plain open refuses, rebuild_index tolerates
    conn = sqlite3.connect(str(paths.index_path()))
    conn.execute("UPDATE meta SET value='99' WHERE key='schema_v'")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError):
        Index()
    idx = rebuild_index()
    assert idx.sealed_state()[0] == 1
    idx.close()


def test_ingest_runless_default_index(broot):
    tomb = _tombstone(idc="a/7")
    assert ingest_runless(tomb) == "applied"
    idx = Index()
    row = idx.conn.execute(
        "SELECT run_seq FROM events WHERE payload_sha=?", (events.content_hash(tomb),)
    ).fetchone()
    assert row["run_seq"] == -1
    # and the same tombstone replayed via the ledger dedups on rebuild
    _append([tomb])
    idx.rebuild()
    # tombstone projected into vault_meta on both paths
    vm = idx.conn.execute("SELECT verdict FROM vault_meta WHERE idc='a/7'").fetchone()
    assert vm["verdict"] == "tombstone"
    idx.close()
