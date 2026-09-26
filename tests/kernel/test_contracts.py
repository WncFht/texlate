"""Red-team contract tests — executable versions of the design's attack
scenarios (docs/spec/bench-trizone.md risk table R1-R28 + §3.x).

Every test cites the risk row or section it exercises. Where the design
contract cannot currently be expressed against the landed API the test
asserts the *designed* behavior — a failure here is a kernel finding, not
a bad test.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from kernel import (
    claims,
    events,
    fsutil,
    idnorm,
    importer,
    index as indexmod,
    kernel,
    ledger,
    locks,
    paid,
    paths,
    report,
    runs,
    sweep,
    vault,
)
from kernel.ctx import Ctx
from kernel.spec import Spec, Stage

SC = {"ok": "terminal", "error": "retriable", "skip": "retriable",
      "fail": "terminal", "fault": "terminal"}


def _stage(name, fn, **kw):
    kw.setdefault("status_class", dict(SC))
    return Stage(name, fn=fn, **kw)


def _free_spec(fns, items, **kw):
    names = list(fns)
    stages = []
    for i, n in enumerate(names):
        needs = [(names[i - 1], {"ok"})] if i else []
        stages.append(_stage(n, fns[n], needs=needs))
    kw.setdefault("kind", "tbench")
    kw.setdefault("eval", True)
    return Spec(stages=stages, items=items, **kw)


def _paid_spec(fn, items, **kw):
    kw.setdefault("kind", "tpaid")
    kw.setdefault("eval", True)
    kw.setdefault("dedup_key", ("idc", "arm", "variant"))
    return Spec(stages=[_stage("pay", fn, paid=True)], items=items, **kw)


def _quiet(**kw):
    kw.setdefault("emit", lambda *_a, **_k: None)
    return kw


def _factory(client=None):
    return paid.GatewayFactory(lambda *_a, **_k: client,
                               prices={"in": 1e-6, "out": 2e-6})


def _note(seq, text="n", run="t/x/y"):
    return events.make_event(events.T_NOTE, run=run, seq=seq,
                             text=text, level="info")


def _hot_events():
    return [e for _l, e, _r in events.iter_jsonl(paths.events_path())
            if isinstance(e, dict)]


# ---------------------------------------------------------------------------
# R21 — lock inode footgun (locks are immortal; lifecycle ops inside the lock)
# ---------------------------------------------------------------------------

def test_r21_delete_recreate_parent_dir_swaps_lock_inode(broot, tmp_path):
    """R21 primitive: delete+recreate of a lock's parent dir swaps the inode —
    the same path then flocks successfully for a second owner while the first
    holder still lives. This is WHY nothing may ever unlink a lock file."""
    d = tmp_path / "cell"
    d.mkdir()
    lp = d / ".lock"
    lp.touch()
    with locks.flock(lp, exclusive=True, blocking=False):
        assert not locks.lock_free(lp)          # held — NB probe sees it
        shutil.rmtree(d)                        # hostile/lifecycle delete
        d.mkdir()
        lp2 = d / ".lock"
        lp2.touch()                             # fresh inode, same path
        assert locks.lock_free(lp2), (
            "recreated lock path must report free — the footgun itself: "
            "a live holder on the dead inode is now invisible")
        with locks.flock(lp2, exclusive=True, blocking=False):
            pass                                 # second owner of 'the same' lock


def test_r21_kernel_source_never_unlinks_lock_files(broot):
    """R21 static audit: no kernel code path may unlink/remove a .lock file
    directly. (Parent-dir deletion is exercised behaviorally below.)"""
    src = Path(kernel.__file__).resolve().parent
    offenders = []
    for f in sorted(src.glob("*.py")):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if (".unlink(" in line or "os.remove(" in line
                    or "os.unlink(" in line) and ".lock" in line:
                offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert offenders == [], f"kernel unlinks lock files: {offenders}"


def test_r21_remove_cell_tree_must_not_kill_live_cell_lock(broot):
    """R21/R10: work/{sid}/.lock is the cell's liveness proof. The single
    delete verb MUST serialize on it — refuse or block while held. A delete
    that succeeds kills the lock inode; a new lock on a fresh inode then has
    two owners -> silent double-burn."""
    rd = runs.create_run("tc", slug="s")
    sid = idnorm.safe_id("2401.00001")
    cell = rd.work(sid)
    cell.mkdir(parents=True)
    (cell / ".lock").touch()
    (cell / "payload.bin").write_bytes(b"x")
    with locks.flock(rd.cell_lock_path(sid), exclusive=True, blocking=False):
        try:
            runs.remove_cell_tree(rd, sid, vault_check=lambda: True)
        except (runs.BlockedDelete, locks.WouldBlock, OSError):
            pass                                     # contract: loud refusal
        else:
            pytest.fail(
                "remove_cell_tree rmtree'd a LIVE-LOCKED cell — its .lock "
                "inode is gone and a fresh lock now has two owners (R21)")
        assert cell.exists(), "live-locked cell tree must survive the delete"


def test_r21_remove_cell_tree_probe_rmtree_toctou(broot):
    """R21 residual: the NB probe and the rmtree are not atomic — a racer
    acquiring the cell lock DURING vault_check still loses its lock inode
    to the rmtree. 'Lifecycle ops inside the lock' means the lock must be
    HELD through the delete, not merely probed once beforehand."""
    rd = runs.create_run("tc2", slug="s")
    sid = idnorm.safe_id("2401.00001")
    cell = rd.work(sid)
    cell.mkdir(parents=True)
    (cell / ".lock").touch()
    (cell / "payload.bin").write_bytes(b"x")

    racer = locks.flock(rd.cell_lock_path(sid), exclusive=True,
                        blocking=False)

    def vault_check():
        racer.__enter__()        # claim lands between probe and rmtree
        return True

    try:
        runs.remove_cell_tree(rd, sid, vault_check=vault_check)
    except (runs.BlockedDelete, locks.WouldBlock, OSError):
        pass                                       # contract: loud refusal
    else:
        pytest.fail(
            "remove_cell_tree rmtree'd a cell whose lock was acquired "
            "during the vault_check window — probe-only NB check leaves a "
            "kill-the-inode race (R21 requires delete-under-lock)")
    finally:
        with contextlib.suppress(Exception):
            racer.__exit__(None, None, None)


def test_r21_prune_must_serialize_on_run_lock(broot):
    """R21/R10 at run level: prune is a lifecycle op — with run.lock held by
    a live runner it must refuse wholesale, not delete the run's
    shard/plan/derived out from under it. (Cell-level probe only covers
    work/; the run archive has no protection.)"""
    import types
    from kernel import cli
    rd = runs.create_run("tpr", slug="s")
    ledger.emit(_note(1, "seed"), run_dir=rd.path)   # shard material exists
    rd.plan_path().write_text('{"cells": []}', encoding="utf-8")
    assert rd.events_path().exists()
    assert rd.plan_path().exists()
    with rd.lock(blocking=False):
        rc = cli._cmd_prune(types.SimpleNamespace(
            run=str(rd.path), keep=""))
        missing = [p.name for p in
                   (rd.events_path(), rd.plan_path(), rd.spec_path())
                   if not p.exists()]
        assert not missing, (
            f"prune deleted {missing} of a live run (rc={rc}) — run.lock "
            f"held throughout and nothing serialized the lifecycle op (R21)")


# ---------------------------------------------------------------------------
# R22 — detach double-fire (child holds the lock, parent returns after ack)
# ---------------------------------------------------------------------------

def test_r22_detach_double_fire_second_refused(broot, tmp_path):
    """R22: two concurrent detaches of the same lock — the second MUST be
    refused; a live returned Popen implies the lock is actually held."""
    lp = tmp_path / "detach.lock"
    p1 = locks.detach_with_lock([], lp, ack_timeout=15)
    try:
        assert not locks.lock_free(lp)           # ack returned => lock held
        with pytest.raises(locks.WouldBlock):
            locks.detach_with_lock([], lp, ack_timeout=15)
    finally:
        p1.kill()
        p1.wait()
    assert locks.lock_free(lp)                   # holder death frees it
    p2 = locks.detach_with_lock([], lp, ack_timeout=15)
    try:
        assert not locks.lock_free(lp)
    finally:
        p2.kill()
        p2.wait()


# ---------------------------------------------------------------------------
# R16 / §3.2 — torn tail
# ---------------------------------------------------------------------------

def test_r16_torn_tail_partial_line_healed(broot):
    """R16: a crash-torn final line (no trailing \\n) is truncated at the
    next emit — the new event lands at the healed offset and the partial
    bytes die with it."""
    ledger.emit(_note(1, "a"))
    ep = paths.events_path()
    with open(ep, "ab") as f:
        f.write(b'{"type":"note","tex')          # torn JSON, no newline
    torn_size = ep.stat().st_size
    off = ledger.emit(_note(2, "b"))
    assert off < torn_size, "emit must heal to just past the last newline"
    body = ep.read_bytes()
    assert b'{"type":"note","tex' not in body    # partial bytes gone
    evs = [e for e in _hot_events() if e["type"] == "note"]
    assert [e["seq"] for e in evs] == [1, 2]


def test_r16_lockless_whole_line_injection_no_byte_tearing(broot):
    """R16 hostile: a lock-free writer appending a WHOLE line (with \\n) is
    tolerated — the injected line survives as a skippable row and the next
    emit lands intact after it; byte-level tearing never happens."""
    ledger.emit(_note(1, "a"))
    ep = paths.events_path()
    with open(ep, "ab") as f:                     # no ledger lock — hostile
        f.write(b'NOT-JSON HOSTILE LINE\n')
        f.write(b'{"hostile": true, "type": "note"}\n')
    ledger.emit(_note(2, "b"))
    rows = list(events.iter_jsonl(ep))
    payloads = [r[1] for r in rows]
    assert payloads[0]["seq"] == 1
    assert payloads[1] is None                    # garbage line: skip-and-warn
    assert payloads[2] == {"hostile": True, "type": "note"}
    assert payloads[3]["seq"] == 2                # new event byte-intact
    # the read-side/ingest side also tolerates the injection: tail_ingest
    # consumes the good lines and does not crash on the hostile ones
    idx = indexmod.Index()
    try:
        idx.tail_ingest()
        idx.tail_ingest()                         # idempotent second pass
    finally:
        idx.close()


# ---------------------------------------------------------------------------
# §3.2 — emit_batch atomicity
# ---------------------------------------------------------------------------

def test_emit_batch_one_invalid_event_lands_nothing(broot):
    """§3.2: emit_batch validates ALL events BEFORE the ledger lock — one
    invalid row fails the whole batch and nothing partial is written."""
    good = _note(1, "good")
    bad = {"type": "cell", "v": 1, "ts": 1.0, "run": "t/x/y", "seq": 2,
           "id": "x", "idc": "x", "arm": "-", "up": "-", "variant": "-",
           "stage": "s", "status": "bogus-status"}
    ep = paths.events_path()
    size0 = ep.stat().st_size if ep.exists() else 0
    with pytest.raises(events.EventError):
        ledger.emit_batch([good, bad])
    size1 = ep.stat().st_size if ep.exists() else 0
    assert size1 == size0, "invalid batch must write zero bytes"
    with pytest.raises(events.EventError):
        ledger.emit_batch([bad, good])            # order-independent
    size2 = ep.stat().st_size if ep.exists() else 0
    assert size2 == size0
    # sanity: an all-valid batch lands every line
    offs = ledger.emit_batch([_note(3, "x"), _note(4, "y")])
    assert len(offs) == 2


# ---------------------------------------------------------------------------
# R6 / §3.10.6 — double-run claim: serial skip, one acquire in the ledger
# ---------------------------------------------------------------------------

def test_r6_second_run_same_paid_cell_degrades_to_claimed(broot):
    """R6: two runs racing the same paid cell — the loser degrades to a
    serial 'claimed' skip, never a double burn. The ledger must show
    exactly ONE claim op=acquire for the cell."""
    gate = threading.Event()
    ran = []

    def slow(ctx):
        ran.append(ctx.run)
        gate.wait(timeout=30)
        return "ok"

    spec_a = _paid_spec(slow, [{"id": "2401.00001"}])
    res_a = {}
    err_a = []

    def run_a():
        try:
            res_a.update(kernel.run(spec_a, max_cost=1.0,
                                    gateway_factory=_factory(), jobs=1,
                                    **_quiet()))
        except Exception as exc:  # noqa: BLE001 - surface in main thread
            err_a.append(exc)

    t = threading.Thread(target=run_a, daemon=True)
    t.start()
    # Wait until A's claim-acquire is durable in the ledger — that implies
    # the lease is held AND the hot tail is quiet until gate.set(), so B's
    # oracle snapshot sees a sealed index (min_offset == watermark).
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if any(e["type"] == "claim" and e.get("op") == "acquire"
               and e.get("idc") == "2401.00001" for e in _hot_events()):
            break
        time.sleep(0.02)
    else:
        gate.set()
        t.join(timeout=30)
        pytest.fail("run A never emitted its claim acquire")
    try:
        res_b = kernel.run(
            _paid_spec(lambda ctx: "ok", [{"id": "2401.00001"}]),
            max_cost=1.0, gateway_factory=_factory(), jobs=1, **_quiet())
    finally:
        gate.set()
        t.join(timeout=35)
    assert not err_a, f"run A failed: {err_a}"
    evs = _hot_events()
    acquires = [e for e in evs
                if e["type"] == "claim" and e.get("op") == "acquire"
                and e.get("idc") == "2401.00001"]
    assert len(acquires) == 1, (
        f"expected exactly ONE claim acquire, got {len(acquires)}")
    assert acquires[0]["run"] == res_a["run"]
    b_cells = [e for e in evs if e["type"] == "cell"
               and e.get("run") == res_b["run"]]
    assert b_cells and all(e["status"] == "claimed" for e in b_cells), (
        f"loser must land 'claimed', got {[e['status'] for e in b_cells]}")
    a_cells = [e for e in evs if e["type"] == "cell"
               and e.get("run") == res_a["run"]]
    assert any(e["status"] == "ok" for e in a_cells)


# ---------------------------------------------------------------------------
# §3.10.2 — 0444 fuse (mutating trees refuse non-writable entries)
# ---------------------------------------------------------------------------

def test_0444_fuse_mutating_tree_refused_and_projections(broot, tmp_path):
    """§3.10.2: a mutating tree carrying 0444 bytes must refuse writes
    (has_nonwritable gate + ctx.workspace/asset_dir probe); the hardlink
    projection preserves the fuse (never chmods dst); copy_mutating is the
    only writable-projection verb."""
    rd = runs.create_run("t0444", slug="s")
    spec = _free_spec({"s1": lambda c: "ok"}, [{"id": "2401.00001"}])
    ctx = Ctx(rd, {"id": "2401.00001", "idc": "2401.00001", "stage": "s1"},
              None, spec)
    d = ctx.workspace()
    victim = d / "sealed.bin"
    victim.write_bytes(b"paid")
    victim.chmod(0o444)
    assert victim in fsutil.has_nonwritable(d)
    with pytest.raises(PermissionError):
        ctx.workspace()                            # fuse: refuse to mutate
    # hardlink farm: dst keeps the fuse — shared inode, no write bit
    src = tmp_path / "src"
    src.mkdir()
    (src / "b.bin").write_bytes(b"data")
    (src / "b.bin").chmod(0o444)
    dst = tmp_path / "farm"
    fsutil.hardlink_farm(src, dst)
    assert not (dst / "b.bin").stat().st_mode & 0o222, (
        "hardlink projection must stay read-only")
    # copy_mutating is the writable verb — 0444 src still yields u+w dst
    dst2 = tmp_path / "mut"
    fsutil.copy_mutating(src, dst2)
    assert (dst2 / "b.bin").stat().st_mode & 0o200


# ---------------------------------------------------------------------------
# R12 / §3.10.7 — canon ambiguity (bare 7-digit tails are never guessed)
# ---------------------------------------------------------------------------

def test_r12_bare_tail_registry_gated(broot):
    """§3.10.7: bare \\d{7} tails resolve ONLY via the registry —
    no registry -> Invalid; |cats|=0 -> Invalid; |cats|>=2 -> Ambig;
    |cats|=1 untracked -> Ambig (local single cat != global uniqueness);
    tracked source or explicit override -> Ok."""
    tail = "9601002"
    assert idnorm.canon_id(tail, None).state == idnorm.INVALID
    reg = idnorm.PapersRegistry()
    assert idnorm.canon_id(tail, reg).state == idnorm.INVALID   # |cats|=0
    reg.add("hep-th/9601002", src="manual")                     # untracked
    r1 = idnorm.canon_id(tail, reg)
    assert r1.state == idnorm.AMBIG                             # untracked 1-cat
    reg.add("cond-mat/9601002", src="manifest")                 # now 2 cats
    r2 = idnorm.canon_id(tail, reg)
    assert r2.state == idnorm.AMBIG and len(r2.candidates) == 2
    reg2 = idnorm.PapersRegistry()
    reg2.add("hep-th/9601002", src="manifest")                  # tracked 1-cat
    r3 = idnorm.canon_id(tail, reg2)
    assert r3.state == idnorm.OK and r3.idc == "hep-th/9601002"
    reg3 = idnorm.PapersRegistry()
    reg3.resolve_tail(tail, "cond-mat/9601002", src="override")
    r4 = idnorm.canon_id(tail, reg3)
    assert r4.state == idnorm.OK and r4.idc == "cond-mat/9601002"


def test_canon_drift_frozen_idc_lands_verbatim(broot):
    """§3.10.7 frozen-wins leg: emit must NOT recompute canon. A cell event
    whose `id` would re-resolve differently still lands with the plan-frozen
    `idc` — never rewritten, never dropped."""
    ev = events.make_event(
        events.T_CELL, run="t/x/y", seq=1,
        id="math.QA/9703043",            # re-resolves to math.QA/9703043
        idc="q-alg/9703043",             # plan-frozen canon (registry flipped)
        arm="-", up="-", variant="-", stage="x", status="ok")
    ledger.emit(ev)
    landed = json.loads(paths.events_path().read_bytes().splitlines()[-1])
    assert landed["idc"] == "q-alg/9703043", "frozen idc must win"
    assert landed["id"] == "math.QA/9703043", "raw spelling must be kept"


def test_canon_drift_emits_fail_loud_signal(broot, tmp_path):
    """§3.10.7 audit leg: '发现重算≠冻结值按冻结值落账+note canon_drift' —
    when a source carries BOTH the raw spelling and a divergent frozen
    adjudication (bench.db records.id + records.id_canon), the frozen value
    must land AND a canon_drift signal must reach the ledger (fail-loud,
    not silent)."""
    db = tmp_path / "bench.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE runs(run_id INTEGER PRIMARY KEY, name TEXT,"
                 " source TEXT, kind TEXT, path TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE records(rec_id INTEGER PRIMARY KEY,"
                 " run_id INTEGER, id TEXT, id_canon TEXT, arm TEXT,"
                 " upstream TEXT, stage TEXT, status TEXT, dur_s REAL,"
                 " metrics TEXT, errors TEXT, sig TEXT, code TEXT,"
                 " queue_wait_s REAL)")
    conn.execute("INSERT INTO runs VALUES (1,'r1','live','xlat','/x',"
                 " '2026-01-01T00:00:00')")
    conn.execute("INSERT INTO records(run_id,id,id_canon,stage,status)"
                 " VALUES (1,'math.QA/9703043','q-alg/9703043','x','ok')")
    conn.commit()
    conn.close()
    idx = indexmod.Index()
    try:
        importer.import_benchdb(db, idx)
    finally:
        idx.close()
    evs = [e for _n, _o, e in ledger.iter_all_events() if isinstance(e, dict)]
    cells = [e for e in evs if e["type"] == "cell"]
    assert cells and all(e["idc"] == "q-alg/9703043" for e in cells), (
        "frozen canon must land")
    signals = [e for e in evs
               if e.get("cat") == "canon_drift"
               or e.get("canon_drift_of") is not None
               or (e["type"] == "note"
                   and "canon_drift" in str(e.get("text", "")))]
    assert signals, (
        "id/id_canon drift landed with ZERO audit signal — §3.10.7 "
        "requires a canon_drift note/cat on the divergent event")


# ---------------------------------------------------------------------------
# §3.3 — import idempotence
# ---------------------------------------------------------------------------

def test_import_reimport_emits_zero_new_events(broot, tmp_path):
    """§3.3 importer contract: re-importing the same records file must emit
    ZERO new ledger lines (payload-sha dedup at the emit filter), apply zero
    index rows, and write zero new quarantine rows."""
    idx = indexmod.Index()
    f = tmp_path / "records.jsonl"
    rows = [
        {"id": "2401.00001", "stage": "xlat", "status": "ok",
         "upstream": "-", "arm": "-", "dur_s": 1.5,
         "metrics": {"segs": 3}, "errors": [], "sig": "s1", "code": "c1"},
        {"id": "2401.00002", "stage": "xlat", "status": "fail",
         "upstream": "-", "arm": "-", "dur_s": 0.5,
         "metrics": {}, "errors": [{"code": "x"}], "sig": "s2", "code": "c2"},
    ]
    f.write_text("".join(json.dumps(r) + "\n" for r in rows))
    try:
        s1 = importer.import_jsonl_file(f, "imp-test", index=idx)
        assert s1["emitted"] >= 2
        n_lines = sum(1 for _l, _e, _r
                      in events.iter_jsonl(paths.events_path()))
        s2 = importer.import_jsonl_file(f, "imp-test", index=idx)
    finally:
        idx.close()
    assert s2["emitted"] == 0, f"re-import emitted {s2['emitted']} new lines"
    assert s2["applied"] == 0
    assert s2["dup_skipped"] >= 2
    n_lines2 = sum(1 for _l, _e, _r
                   in events.iter_jsonl(paths.events_path()))
    assert n_lines2 == n_lines, "re-import must not grow the ledger"
    assert s2["quar_written"] == 0, "re-import must not spam quarantine"


# ---------------------------------------------------------------------------
# §3.10.5 — seqfile loss recovery (scanback minting)
# ---------------------------------------------------------------------------

def test_seqfile_loss_scanback_recovers_without_collision(broot):
    """§3.10.5: a deleted ledger/.seq must recover via scanback — the next
    minted run_seq is max(registered)+1, never a collision."""
    rd1 = runs.create_run("tsq", slug="a")
    rd2 = runs.create_run("tsq", slug="b")
    assert {rd1.run_seq, rd2.run_seq} == {1, 2}
    paths.seqfile_path().unlink()                   # the loss event
    rd3 = runs.create_run("tsq", slug="c")
    assert rd3.run_seq > max(rd1.run_seq, rd2.run_seq), (
        "scanback must recover the high-water mark")
    seqs = sorted(e["run_seq"] for e in _hot_events()
                  if e["type"] == "run_registered")
    assert seqs == [1, 2, 3], f"seq collision after seqfile loss: {seqs}"


# ---------------------------------------------------------------------------
# §3.2 — index rebuild equivalence
# ---------------------------------------------------------------------------

def test_index_rebuild_equivalent_to_tail_ingest(broot):
    """§3.2: the index is a pure projection — a full rebuild() over the
    ledger must answer every query identically to the incremental
    tail_ingest state."""
    spec = _free_spec(
        {"a": lambda c: "ok",
         "b": lambda c: {"status": "ok", "metrics": {"m": 1}}},
        [{"id": "2401.00001"}, {"id": "2401.00002"}])
    kernel.run(spec, jobs=1, **_quiet())

    def answers(idx):
        return {
            "done_a1": idx.done("2401.00001", "-", "-", "-", "a"),
            "done_b1": idx.done("2401.00001", "-", "-", "-", "b"),
            "done_a2": idx.done("2401.00002", "-", "-", "-", "a"),
            "pool": idx.paid_pool(),
            "claims": idx.active_claims(),
            "cell_b1": idx.last_cell("2401.00001", "-", "-", "-", "b"),
            "records": idx.conn.execute("SELECT COUNT(*) c FROM records")
            .fetchone()["c"],
            "cells": idx.conn.execute("SELECT COUNT(*) c FROM cells")
            .fetchone()["c"],
            "watermark": idx.sealed_state()[1],
        }

    idx = indexmod.Index()
    try:
        idx.tail_ingest()
        before = answers(idx)
        idx.rebuild()
        after = answers(idx)
    finally:
        idx.close()
    assert after == before, (
        f"rebuild diverged from tail_ingest: {before} vs {after}")


# ---------------------------------------------------------------------------
# §3.10.5 — seal chain (prev_seal_sha links + iter order across boundary)
# ---------------------------------------------------------------------------

def test_seal_chain_links_and_event_order_across_boundary(broot):
    """§3.10.5: every seals.jsonl row hash-chains to the previous segment
    (genesis '0'*64 for the first); iter_all_events replays sealed zsts then
    the hot tail in authoritative append order."""
    for i in range(20):
        ledger.emit(_note(i))
    # distinct now_ts: same-second segment names would collide into a '.N'
    # suffix that sorts BEFORE the base name, scrambling replay order —
    # pinned ts keeps the name sort chronological (the contract under test).
    z1 = ledger.seal_if_needed(now_ts=1_700_000_000, max_bytes=1)
    assert z1 is not None, "first seal did not fire"
    for i in range(20, 40):
        ledger.emit(_note(i))
    z2 = ledger.seal_if_needed(now_ts=1_800_000_000, max_bytes=1)
    assert z2 is not None, "second seal did not fire"
    for i in range(40, 50):
        ledger.emit(_note(i))

    rows = [e for e in (row for _l, row, _r
                        in events.iter_jsonl(paths.seals_path()))
            if isinstance(e, dict)]
    assert len(rows) == 2, f"expected 2 seal rows, got {len(rows)}"
    assert rows[0]["prev_seal_sha"] == "0" * 64
    assert rows[1]["prev_seal_sha"] == rows[0]["zst_sha"], (
        "seal hash chain broken")
    seen = [e["seq"] for _n, _o, e in ledger.iter_all_events()
            if isinstance(e, dict) and e.get("type") == "note"]
    assert seen == list(range(50)), (
        "iter_all_events must replay sealed+hot in append order")


# ---------------------------------------------------------------------------
# R4 / §3.5 — vault commit order (meta-last; meta-less bytes never count)
# ---------------------------------------------------------------------------

def test_vault_metaless_bytes_never_count_and_still_block_slot(broot, tmp_path):
    """R4: meta.json is the commit marker — bytes renamed into place without
    a meta (the mid-harvest crash window) must read bytes_ok=False, produce
    no query row, surface in find_meta_less_dirs, AND keep the credential
    slot occupied so a retry cannot nest into the squatter."""
    idc = "2401.00001"
    squatter = vault.leaf_dir("primary", "zh", idc, "-", "-", "0")
    squatter.mkdir(parents=True)
    (squatter / "paper.pdf").write_bytes(b"paid bytes")
    assert vault.bytes_ok(idc, "-", "-") is False
    assert vault.query(idc) == []
    assert squatter in vault.find_meta_less_dirs()
    assert vault._slot_taken(idc, "-", "-", "0") is True
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.bin").write_bytes(b"x")
    with pytest.raises(vault.DestOccupied):
        vault.harvest(idc, "-", "-", {"zh": src}, altseq="0")


def test_vault_dest_occupied_explicit_altseq_refused(broot, tmp_path):
    """§3.10.4: an explicit altseq commit into an occupied slot refuses —
    never silently nest into an existing destination."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.bin").write_bytes(b"x")
    vault.harvest("2401.00001", "-", "-", {"zh": src}, altseq="0")
    with pytest.raises(vault.DestOccupied):
        vault.harvest("2401.00001", "-", "-", {"zh": src}, altseq="0")
    # a DIFFERENT slot is still free — the refusal is per-slot
    vault.harvest("2401.00001", "-", "-", {"zh": src}, altseq="1")


# ---------------------------------------------------------------------------
# §3.6 — paid-slot cap
# ---------------------------------------------------------------------------

def test_paid_slot_cap_fifth_nb_fails_release_wins(broot):
    """§3.6: at most nslots paid requests may hold a slot; the (n+1)th NB
    attempt fails, and releasing a slot lets the next contender win it."""
    cms = [locks.paid_slot(4, blocking=False) for _ in range(4)]
    held = [cm.__enter__() for cm in cms]
    assert sorted(held) == [0, 1, 2, 3]
    try:
        with pytest.raises(locks.WouldBlock):
            with locks.paid_slot(4, blocking=False):
                pass
        cms[0].__exit__(None, None, None)
        with locks.paid_slot(4, blocking=False) as s:
            assert s == held[0], "freed slot must be re-winnable"
    finally:
        for cm in cms[1:]:
            cm.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# §3.10.1 / R7 — sweep zombie (stale heartbeat + free run.lock)
# ---------------------------------------------------------------------------

def test_sweep_zombie_lost_and_claim_reap_locked_cell_survives(broot):
    """§3.10.1: heartbeat stale >600s ∧ run.lock NB-free → per-cell cell.lock
    NB recheck; free cells land 'lost', claim leases are reaped, but a HELD
    cell.lock means a live worker — never reaped."""
    rd = runs.create_run("tz", slug="z")
    idc_dead, idc_live = "2401.00001", "2401.00002"
    sid_live = idnorm.safe_id(idc_live)
    for i, idc in enumerate((idc_dead, idc_live)):
        ledger.emit(events.make_event(
            events.T_CELL_QUEUED, run=rd.run, seq=i * 2 + 1, id=idc, idc=idc,
            arm="-", up="-", variant="-", stage="pay"), run_dir=rd.path)
        ledger.emit(events.make_event(
            events.T_CELL_STARTED, run=rd.run, seq=i * 2 + 2, id=idc, idc=idc,
            arm="-", up="-", variant="-", stage="pay"), run_dir=rd.path)
    ledger.emit(events.make_event(
        events.T_CLAIM, run=rd.run, seq=9, id=idc_dead, idc=idc_dead,
        arm="-", variant="-", op="acquire"), run_dir=rd.path)
    # stale the heartbeat; run.lock stays free (nobody holds it)
    stale = time.time() - (sweep.ZOMBIE_AGE_S + 60)
    os.utime(rd.heartbeat_path(), (stale, stale))
    with runs.cell_lock(rd, sid_live, blocking=False):
        rep = sweep.sweep(light=True)
    zombies = [z for z in rep["zombies"] if z["run"] == rd.run]
    assert zombies, f"zombie run not reaped: {rep}"
    assert zombies[0]["lost_cells"] == 1 and zombies[0]["live_cells"] == 1
    evs = _hot_events()
    lost = [e for e in evs if e["type"] == "cell"
            and e.get("status") == "lost" and e.get("run") == rd.run]
    assert [e["idc"] for e in lost] == [idc_dead], (
        "only the lock-free cell may be reaped")
    assert not any(e.get("idc") == idc_live and e.get("status") == "lost"
                   for e in evs), "LOCKED cell.lock cell must survive"
    reaps = [e for e in evs if e["type"] == "claim"
             and e.get("op") == "reap" and e.get("idc") == idc_dead]
    assert reaps, "dead claimant's lease was not reaped"


# ---------------------------------------------------------------------------
# §3.10.1 / R10 — remove_cell_tree blocked (paid tree without vault meta)
# ---------------------------------------------------------------------------

def test_remove_cell_tree_blocked_without_vault_meta(broot):
    """R10/§3.10.1: a paid-shaped cell tree with no vault copy must refuse
    delete (BlockedDelete + warn note); the tree survives untouched."""
    rd = runs.create_run("tblk", slug="s")
    sid = idnorm.safe_id("2401.00001")
    cell = rd.work(sid)
    paid_tree = cell / "zh.-"
    paid_tree.mkdir(parents=True)
    (paid_tree / "paper.pdf").write_bytes(b"paid")
    with pytest.raises(runs.BlockedDelete):
        runs.remove_cell_tree(rd, sid, vault_check=lambda: False)
    assert (paid_tree / "paper.pdf").exists(), "blocked delete removed bytes"
    notes = [e for e in _hot_events() if e["type"] == "note"
             and "BLOCKED" in str(e.get("text", ""))]
    assert notes, "blocked delete must emit a warn note (fail-loud)"


# ---------------------------------------------------------------------------
# R15 — plan-freeze verbatim on rerun
# ---------------------------------------------------------------------------

def test_plan_freeze_verbatim_on_rerun(broot):
    """R15/§3.1: a frozen plan.json is authoritative — a resume with a
    differently-shaped spec must reuse the frozen cell list verbatim, never
    re-enumerate."""
    spec1 = _free_spec({"a": lambda c: "ok"}, [{"id": "2401.00001"}],
                       kind="tfz")
    r1 = kernel.run(spec1, date="2026-01-01", slug="fz",
                    jobs=1, **_quiet())
    rd = runs.load_run("tfz", r1["date"], r1["slug"])
    plan0 = rd.plan_path().read_bytes()
    spec2 = _free_spec({"a": lambda c: "ok"},
                       [{"id": "2401.00001"}, {"id": "2401.00002"}],
                       kind="tfz")
    r2 = kernel.run(spec2, resume=True, date=r1["date"], slug=r1["slug"],
                    jobs=1, **_quiet())
    assert rd.plan_path().read_bytes() == plan0, (
        "frozen plan.json mutated on rerun")
    evs = _hot_events()
    assert not any(e.get("id") == "2401.00002" or e.get("idc") == "2401.00002"
                   for e in evs), "new spec's extra item leaked into a frozen plan"


# ---------------------------------------------------------------------------
# §3.7 — report projection keeps the original id spelling
# ---------------------------------------------------------------------------

def test_report_keeps_original_id_spelling(broot, tmp_path):
    """§3.7 read-side asymmetry: projection must keep the writer's raw `id`
    spelling — canon normalization is a write-boundary act, never a
    read-time rewrite."""
    ev = events.make_event(
        events.T_CELL, run="t/x/y", seq=1,
        id="Cond-Mat/9601002",                  # non-canon raw spelling
        idc="cond-mat/9601002",
        arm="-", up="-", variant="-", stage="x", status="ok")
    ledger.emit(ev)
    idx = indexmod.Index()
    try:
        idx.tail_ingest()
        out = tmp_path / "rep"
        report.build_run_report(idx, "t/x/y", str(out))
        rows = [
            json.loads(ln)
            for ln in (out / "cells.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if ln.strip()
        ]
    finally:
        idx.close()
    assert len(rows) == 1
    assert rows[0]["id"] == "Cond-Mat/9601002", (
        "projected row lost the original id spelling")
