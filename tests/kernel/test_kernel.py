"""Tests for kernel/kernel.py — the run pipeline + cell critical section.

Every test runs against an isolated $TEXLATE_BENCH_ROOT via `broot`.
Specs are built in-memory (eval=True skips the corpus registry — ids stay
verbatim canon spellings like '2401.00001').
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from kernel import (
    claims,
    dedup,
    events,
    kernel,
    ledger,
    locks,
    paid,
    paths,
    runs,
    spec as specmod,
    vault,
)
from kernel.spec import Param, Spec, Stage

SC = {"ok": "terminal", "error": "retriable", "skip": "retriable",
      "fail": "terminal", "fault": "terminal"}


def _stage(name, fn, **kw):
    kw.setdefault("status_class", dict(SC))
    return Stage(name, fn=fn, **kw)


def _free_spec(fns, items, **kw):
    """fns: {stage_name: callable}; stages wired linearly a->b->c."""
    names = list(fns)
    stages = []
    for i, n in enumerate(names):
        needs = [(names[i - 1], {"ok"})] if i else []
        stages.append(_stage(n, fns[n], needs=needs))
    kw.setdefault("kind", "tbench")
    kw.setdefault("eval", True)          # verbatim ids, no registry scan
    return Spec(stages=stages, items=items, **kw)


def _paid_spec(fn, items, **kw):
    kw.setdefault("kind", "tpaid")
    kw.setdefault("eval", True)
    kw.setdefault("dedup_key", ("idc", "arm", "variant"))
    return Spec(stages=[_stage("pay", fn, paid=True)], items=items, **kw)


def _shard(rd: runs.RunDir) -> list[dict]:
    return [e for _ln, e, _raw in events.iter_jsonl(rd.events_path())
            if isinstance(e, dict)]


def _cell_rows(rd, status=None):
    return [e for e in _shard(rd)
            if e["type"] == "cell" and (status is None or e["status"] == status)]


def _quiet(**kw):
    kw.setdefault("emit", lambda *_a, **_k: None)
    return kw


# --- end-to-end ----------------------------------------------------------------------


def test_two_stage_free_spec_end_to_end(broot: Path):
    calls = []
    spec = _free_spec(
        {"ingest": lambda ctx: calls.append(("ingest", ctx.idc)) or "ok",
         "xlat": lambda ctx: calls.append(("xlat", ctx.idc)) or
             {"status": "ok", "metrics": {"segs": 7}}},
        [{"id": "2401.00001"}])
    res = kernel.run(spec, **_quiet())
    assert res["ok"] is True
    assert res["counts"].get("ok") == 2
    assert calls == [("ingest", "2401.00001"), ("xlat", "2401.00001")]

    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    shard = _shard(rd)
    types = [e["type"] for e in shard]
    assert types.count("cell_queued") == 2
    assert types.count("cell_started") == 2
    assert types.count("cell") == 2
    assert "finished" in types
    # plan.json frozen with both cells
    plan = json.loads(rd.plan_path().read_text())
    assert [c["stage"] for c in plan["cells"]] == ["ingest", "xlat"]
    # xlat's ok row carries the merged metrics
    xrow = [e for e in shard if e["type"] == "cell"
            and e["stage"] == "xlat"][0]
    assert xrow["metrics"] == {"segs": 7}
    assert xrow["fp"]                                # fp stamped
    # accounting equation balanced
    acct = runs.accounting_check(rd)
    assert acct["ok"] is True and acct["terminal"] == 2


def test_empty_plan_warns_not_crashes(broot: Path):
    spec = _free_spec({"a": lambda c: "ok"}, [])
    res = kernel.run(spec, **_quiet())
    assert res["cells"] == 0 and res["counts"] == {}


def test_dedup_skip_on_second_run(broot: Path):
    calls = []
    spec = _free_spec(
        {"ingest": lambda ctx: calls.append("ingest") or "ok",
         "xlat": lambda ctx: calls.append("xlat") or "ok"},
        [{"id": "2401.00001"}])
    r1 = kernel.run(spec, **_quiet())
    assert r1["counts"]["ok"] == 2 and len(calls) == 2

    calls.clear()
    r2 = kernel.run(spec, **_quiet())
    rd2 = runs.load_run(spec.kind, r2["date"], r2["slug"])
    rows = _cell_rows(rd2)
    assert [e["status"] for e in rows] == ["dedup", "dedup"]
    assert calls == []                                # nothing re-executed
    assert r2["ok"] is True


def test_fp_changes_do_not_affect_done_set(broot: Path):
    spec = _free_spec({"a": lambda ctx: "ok"}, [{"id": "2401.00001"}],
                      params={"temp": Param(float, default=0.1)})
    r1 = kernel.run(spec, {"temp": 0.1}, **_quiet())
    rd1 = runs.load_run(spec.kind, r1["date"], r1["slug"])
    fp1 = _cell_rows(rd1)[0]["fp"]

    # a different fp-effective param would mint a different fp…
    fp2 = specmod.cell_fp(spec, {
        "id": "2401.00001", "idc": "2401.00001", "arm": "-", "up": "-",
        "variant": "-", "stage": "a", "fp_input": None,
        "run_params": {"temp": 0.9}, "params": {}})
    assert fp1 != fp2
    # …but the done-set is fp-blind: run 2 still dedups (§3.4)
    r2 = kernel.run(spec, {"temp": 0.9}, **_quiet())
    rd2 = runs.load_run(spec.kind, r2["date"], r2["slug"])
    assert _cell_rows(rd2)[0]["status"] == "dedup"


def test_needs_missing_skips(broot: Path):
    spec = _free_spec(
        {"ingest": lambda ctx: "ok", "xlat": lambda ctx: "ok"},
        [{"id": "2401.00001", "stage": "xlat"}])      # upstream never runs
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    rows = _cell_rows(rd)
    assert len(rows) == 1 and rows[0]["status"] == "skip"
    assert rows[0]["errors"][0]["cat"] == "needs"


def test_upstream_lost_is_hard_fault(broot: Path):
    def ingest(ctx):
        return "ok"          # declares mutates zh but produces no bytes

    spec = _free_spec(
        {"ingest": ingest, "xlat": lambda ctx: "ok"},
        [{"id": "2401.00001"}])
    spec.stages[0].mutates = ["zh"]
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    rows = {e["stage"]: e for e in _cell_rows(rd)}
    assert rows["ingest"]["status"] == "ok"
    assert rows["xlat"]["status"] == "fault"
    assert rows["xlat"]["cat"] == "upstream-lost"


def test_unclassified_status_lands_fault_plus_note(broot: Path):
    spec = _free_spec({"a": lambda ctx: "weird"}, [{"id": "x"}])
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    row = _cell_rows(rd)[0]
    assert row["status"] == "fault"
    assert row["errors"][0]["cat"] == "unclassified"
    notes = [e for e in _shard(rd) if e["type"] == "note"]
    assert any("unclassified" in n["text"] for n in notes)


def test_cell_exception_is_error_not_crash(broot: Path):
    def boom(ctx):
        raise RuntimeError("kapow")

    spec = _free_spec({"a": boom}, [{"id": "x"}])
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    row = _cell_rows(rd)[0]
    assert row["status"] == "error"
    assert "kapow" in row["errors"][0]["msg"]
    # a retriable ending still emitted its terminal — the queue drained,
    # so the accounting equation (which detects LOST cells) balances
    assert res["accounting"]["ok"] is True
    assert res["ok"] is True


def test_pause_holds_paid_cells_without_calling_fn(broot: Path):
    """PAUSE is a paid-spend fence (§6 Phase-3 rescope): a paid cell held
    at the per-cell gate lands error/pause without ever calling its fn;
    free cells proceed under the fence (covered by cli/integration)."""
    calls = []
    spec = _paid_spec(lambda ctx: calls.append(1) or "ok",
                      [{"id": "x"}])
    paths.pause_path().touch()
    res = kernel.run(spec, max_cost=5.0,
                     gateway_factory=_factory(object()), **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    row = _cell_rows(rd)[0]
    assert row["status"] == "error" and row["cat"] == "pause"
    assert calls == []                                # fn never ran


def test_emit_batch_integrity(broot: Path, monkeypatch):
    batches = []
    orig = ledger.emit_batch

    def spy(evs, **kw):
        batches.append([e["type"] for e in evs])
        return orig(evs, **kw)

    monkeypatch.setattr(ledger, "emit_batch", spy)

    def fn(ctx):
        ctx.emit({"metrics": {"n": 3}})
        ctx.emit_note("hello", level="warn")
        return {"status": "ok"}

    spec = _free_spec({"a": fn}, [{"id": "x"}])
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    # terminal + author note + started land in exactly two batches:
    # [cell_started] then [cell, note] — never a torn row
    assert ["cell_started"] in batches
    assert ["cell", "note"] in batches
    row = _cell_rows(rd)[0]
    assert row["metrics"] == {"n": 3}
    note = [e for e in _shard(rd) if e["type"] == "note"
            and e["text"] == "hello"][0]
    assert note["level"] == "warn"


def test_resume_reruns_retriable_cells(broot: Path):
    def fn(ctx):
        marker = ctx.paper_dir() / "done.marker"
        if not marker.exists():
            marker.touch()
            raise RuntimeError("first attempt fails")
        return "ok"

    spec = _free_spec({"a": fn}, [{"id": "x"}])
    r1 = kernel.run(spec, date="2026-09-21", slug="r1", **_quiet())
    assert r1["ok"] is True  # error cell emitted its terminal — balanced
    r2 = kernel.run(spec, resume=True, date="2026-09-21", slug="r1",
                    **_quiet())
    rd = runs.load_run(spec.kind, "2026-09-21", "r1")
    rows = _cell_rows(rd)
    assert [r["status"] for r in rows] == ["error", "ok"]
    # queued twice, terminal twice -> pairwise balanced
    assert r2["accounting"]["ok"] is True
    assert r2["ok"] is True


def test_frozen_plan_verbatim_on_resume(broot: Path):
    spec = _free_spec({"a": lambda ctx: "ok"}, [{"id": "x"}])
    r1 = kernel.run(spec, date="2026-09-21", slug="fr", **_quiet())
    rd = runs.load_run(spec.kind, "2026-09-21", "fr")
    frozen = json.loads(rd.plan_path().read_text())["cells"]
    # a resumed run with a DIFFERENT enumeration still uses the frozen plan
    spec2 = _free_spec({"a": lambda ctx: "ok"}, [{"id": "y"}])
    kernel.run(spec2, resume=True, date="2026-09-21", slug="fr", **_quiet())
    assert json.loads(rd.plan_path().read_text())["cells"] == frozen


def test_run_lock_failfast(broot: Path):
    spec = _free_spec({"a": lambda c: "ok"}, [{"id": "x"}])
    r1 = kernel.run(spec, date="2026-09-21", slug="lk", **_quiet())
    rd = runs.load_run(spec.kind, "2026-09-21", "lk")
    with rd.lock():
        with pytest.raises(kernel.RunError):
            kernel.run(spec, resume=True, date="2026-09-21", slug="lk",
                       **_quiet())


def test_paid_spec_refuses_without_max_cost_and_factory(broot: Path):
    spec = _paid_spec(lambda ctx: "ok", [{"id": "2401.00001"}])
    with pytest.raises(kernel.RunError):
        kernel.run(spec, **_quiet())                        # no max_cost
    with pytest.raises(kernel.RunError):
        kernel.run(spec, max_cost=1.0, **_quiet())          # no factory


def test_same_id_serial_groups(broot: Path):
    """cells sharing idc never overlap — even across arms."""
    active: dict[str, int] = {}
    overlap = []
    guard = threading.Lock()

    def fn(ctx):
        with guard:
            active[ctx.idc] = active.get(ctx.idc, 0) + 1
            if active[ctx.idc] > 1:
                overlap.append(ctx.idc)          # same-idc overlap = violation
        time.sleep(0.03)
        with guard:
            active[ctx.idc] -= 1
        return "ok"

    items = [{"id": "2401.00001", "arm": "a"},
             {"id": "2401.00001", "arm": "b"},
             {"id": "2401.00002", "arm": "a"}]
    spec = _free_spec({"a": fn}, items)
    kernel.run(spec, jobs=2, **_quiet())
    assert overlap == []


def test_plan_quote_shape(broot: Path):
    spec = _free_spec({"a": lambda c: "ok"}, [{"id": "2401.00001"}])
    res = kernel.plan(spec, **_quiet())
    assert res["ok"] is True and res["kind"] == "tbench"
    q = res["quote"]
    assert q["total"] == 1 and q["new"] == 1 and q["sealed"] is True
    assert res["would_run"] == 1


# --- paid gate paths (oracle consulted inside the critical section) -----------------


def _factory(client, **kw):
    kw.setdefault("prices", {"in": 1e-6, "out": 2e-6})
    return paid.GatewayFactory(lambda _ctx=None: client, **kw)


def test_paid_full_path_claim_slot_meter(broot: Path, monkeypatch):
    class Client:
        def __init__(self):
            self.calls = 0

        def chat(self, payload=None):
            self.calls += 1
            return {"usage": {"in_tok": 100, "out_tok": 50}, "text": "ok"}

    client = Client()
    factory = _factory(client)
    slot_entries = []
    orig_slot = locks.paid_slot

    def slot_spy(**kw):
        slot_entries.append(kw)
        return orig_slot(**kw)

    monkeypatch.setattr(locks, "paid_slot", slot_spy)

    def fn(ctx):
        res = ctx.gateway().request("chat", payload={"q": 1})
        assert res["text"] == "ok"
        return "ok"

    spec = _paid_spec(fn, [{"id": "2401.00001"}])
    res = kernel.run(spec, max_cost=5.0, gateway_factory=factory, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    rows = _cell_rows(rd)
    assert [r["status"] for r in rows] == ["ok"]
    assert client.calls == 1
    # usage metered through the token accountant: 100*1e-6 + 50*2e-6
    assert abs(factory.meter.spent() - 0.0002) < 1e-9
    assert factory.meter.requests() == 1
    # slot bound: every request inside locks.paid_slot
    assert slot_entries and slot_entries[0]["nslots"] == 4
    # claim audit: acquire + release fate=verified (lifecycle stream —
    # slot-carrying events are the per-request paid_slots mirror)
    claims_ev = [e for e in _shard(rd)
                 if e["type"] == "claim" and e.get("slot") is None]
    assert [e["op"] for e in claims_ev] == ["acquire", "release"]
    assert claims_ev[1]["fate"] == "verified"
    # claim file was really held then released
    lease = claims.ClaimLease("2401.00001", arm="-", variant="-")
    assert not lease.held_by_other()


def test_claimed_skip_via_held_lease(broot: Path):
    lease = claims.ClaimLease("2401.00001", arm="-", variant="-")
    assert lease.acquire()
    try:
        spec = _paid_spec(lambda ctx: "ok", [{"id": "2401.00001"}])
        res = kernel.run(spec, max_cost=1.0,
                         gateway_factory=_factory(object()), **_quiet())
        rd = runs.load_run(spec.kind, res["date"], res["slug"])
        row = _cell_rows(rd)[0]
        assert row["status"] == "claimed" and row["cat"] == "claimed"
    finally:
        lease.release()


def test_unsealed_index_first_fire_refusal(broot: Path):
    """A poisoned seal refuses the paid RUN at the first-fire gate
    (§6 Phase-3): RunError + coverage.json evidence; the per-cell
    index_unsealed path remains for seal loss mid-run."""
    paths.index_dirty_path().touch()                 # poison the seal
    spec = _paid_spec(lambda ctx: "ok", [{"id": "2401.00001"}])
    with pytest.raises(kernel.RunError):
        kernel.run(spec, max_cost=1.0, date="2026-09-22", slug="uu",
                   gateway_factory=_factory(object()), **_quiet())
    rd = runs.load_run(spec.kind, "2026-09-22", "uu")
    assert _cell_rows(rd) == []
    cov = json.loads(
        (rd.derived() / "coverage.json").read_text(encoding="utf-8"))
    assert cov["sealed"] is False


def test_regen_gate_rejects_tombstoned_cell(broot: Path):
    vault.tombstone("2401.00001", "-", "-", "zh", "test-lost")
    spec = _paid_spec(lambda ctx: "ok", [{"id": "2401.00001"}])
    res = kernel.run(spec, max_cost=1.0,
                     gateway_factory=_factory(object()), **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    row = _cell_rows(rd)[0]
    assert row["status"] == "reject" and row["cat"] == "regen_gate"


def test_verified_vault_copy_dedups_paid_cell(broot: Path, tmp_path):
    # harvest real bytes so the oracle's verified leg fires
    src = tmp_path / "zhsrc"
    (src / "zh").mkdir(parents=True)
    (src / "zh" / "out.pdf").write_bytes(b"paid bytes")
    vault.harvest("2401.00001", "-", "-", {"zh": src / "zh"},
                  source_run="adhoc")
    spec = _paid_spec(lambda ctx: "ok", [{"id": "2401.00001"}])
    res = kernel.run(spec, max_cost=1.0,
                     gateway_factory=_factory(object()), **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    assert _cell_rows(rd)[0]["status"] == "dedup"


def test_cost_fuse_rejects_at_max_cost(broot: Path):
    class Client:
        def chat(self):
            return {"usage": {"in_tok": 100, "out_tok": 50}}

    factory = _factory(Client())
    calls = []

    def fn(ctx):
        calls.append(ctx.idc)
        ctx.gateway().request("chat")
        return "ok"

    spec = _paid_spec(fn, [{"id": "2401.00001"}, {"id": "2401.00002"}])
    res = kernel.run(spec, max_cost=0.0001, gateway_factory=factory,
                     jobs=1, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    rows = sorted(_cell_rows(rd), key=lambda e: e["idc"])
    # cell 1 spends 0.0002 > fuse armed for cell 2 (spent+est > max)
    assert rows[0]["status"] == "ok"
    assert rows[1]["status"] == "reject" and rows[1]["cat"] == "budget"
    assert calls == ["2401.00001"]                   # second cell never ran


def test_auth_breaker_three_401s_abort_cell(broot: Path):
    class Client:
        def chat(self):
            exc = Exception("unauthorized")
            exc.status_code = 401
            raise exc

    factory = _factory(Client())

    def fn(ctx):
        s = ctx.gateway()
        for _ in range(2):
            try:
                s.request("chat")
            except Exception:
                pass
        s.request("chat")                            # third 401 -> abort
        return "ok"

    spec = _paid_spec(fn, [{"id": "2401.00001"}])
    res = kernel.run(spec, max_cost=1.0, gateway_factory=factory,
                     jobs=1, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    row = _cell_rows(rd)[0]
    assert row["status"] == "fail" and row["cat"] == "auth_dead"
    assert row["auth_tripped"] is True
    assert factory.shared["paper_auth"]["2401.00001"] == 3
    assert factory.shared["all_failed"] == 1
    release = [e for e in _shard(rd)
               if e["type"] == "claim" and e["op"] == "release"
               and e.get("slot") is None][0]
    assert release["fate"] == "auth_trip"


def test_auth_breaker_two_papers_trips_auth_dead(broot: Path):
    class Client:
        def chat(self):
            exc = Exception("unauthorized")
            exc.status_code = 401
            raise exc

    factory = _factory(Client())

    def fn(ctx):
        s = ctx.gateway()
        for _ in range(2):
            try:
                s.request("chat")
            except Exception:
                pass
        s.request("chat")
        return "ok"

    spec = _paid_spec(fn, [{"id": "2401.00001"}, {"id": "2401.00002"}])
    res = kernel.run(spec, max_cost=1.0, gateway_factory=factory,
                     jobs=1, **_quiet())
    assert paths.auth_dead_path().exists()           # sentinel tripped
    assert factory.shared["all_failed"] == 2
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    cats = sorted(e["cat"] for e in _cell_rows(rd))
    assert cats == ["auth_dead", "auth_dead"]
    assert res["ok"] is False


def test_auth_dead_sentinel_refuses_paid_cell(broot: Path):
    locks.trip_auth_dead("test")
    spec = _paid_spec(lambda ctx: "ok", [{"id": "2401.00001"}])
    res = kernel.run(spec, max_cost=1.0,
                     gateway_factory=_factory(object()), **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    row = _cell_rows(rd)[0]
    assert row["status"] == "error" and row["cat"] == "auth_dead"
