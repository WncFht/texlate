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
    index as indexmod,
    kernel,
    lake,
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


def _collector_spec(fn, items):
    """Needs-free collector stage (the e2e_real fixloop/layoutqc shape):
    no needs edges, upstream gates live inside the fn."""
    st = _stage("coll", fn, status_class=dict(SC, reject="terminal"))
    return Spec(stages=[st], items=items, kind="tbench", eval=True)


def _seed_verdict(idc, status, seq, sig=None, stage="coll"):
    """Stamp a historical cross-run cell row straight into the index."""
    idx = indexmod.Index()
    ev = events.make_event(
        events.T_CELL,
        run="seed",
        run_seq=900,
        seq=seq,
        id=idc,
        idc=idc,
        arm="-",
        up="-",
        variant="-",
        stage=stage,
        status=status,
        dur_s=0.1,
    )
    if sig is not None:
        ev["sig"] = sig
    assert idx.apply_event(ev) == "applied"
    idx.close()


def test_declined_gate_reject_never_dedups(broot: Path):
    """declined:* rejects are conditional gate verdicts over the upstream
    state at emit time — upstream revival must re-run the fn, not inherit
    the stale decline."""
    calls = []

    def coll(ctx):
        calls.append("coll")
        if len(calls) == 1:
            return {"status": "reject", "sig": "declined:qc_no_input"}
        return "ok"

    spec = _collector_spec(coll, [{"id": "2401.00001"}])
    r1 = kernel.run(spec, **_quiet())
    rd1 = runs.load_run(spec.kind, r1["date"], r1["slug"])
    row = _cell_rows(rd1)[0]
    assert row["status"] == "reject" and row["sig"] == "declined:qc_no_input"

    # upstream "revived" — the decline must not dedup; the fn re-evaluates
    r2 = kernel.run(spec, **_quiet())
    rd2 = runs.load_run(spec.kind, r2["date"], r2["slug"])
    assert _cell_rows(rd2)[0]["status"] == "ok"
    assert calls == ["coll", "coll"]

    # and the real verdict dedups normally from here on
    r3 = kernel.run(spec, **_quiet())
    rd3 = runs.load_run(spec.kind, r3["date"], r3["slug"])
    assert _cell_rows(rd3)[0]["status"] == "dedup"
    assert calls == ["coll", "coll"]


def test_dedup_pile_over_declined_reads_through(broot: Path):
    """Dedup rows stacked on a declined row are pointers to it — the scan
    reads through the whole pile, so a poisoned cell unbricks on the next
    run without ledger surgery."""
    spec = _collector_spec(lambda ctx: "ok", [{"id": "2401.00001"}])
    _seed_verdict("2401.00001", "reject", 1, sig="declined:qc_no_input")
    _seed_verdict("2401.00001", "dedup", 2)
    _seed_verdict("2401.00001", "dedup", 3)
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    assert _cell_rows(rd)[0]["status"] == "ok"


def test_dedup_pile_over_verdict_still_dedups(broot: Path):
    """Guard against over-masking: dedup rows on a real verdict keep
    deduping — the mask only removes pointer rows, not work evidence."""
    calls = []
    spec = _collector_spec(lambda ctx: calls.append("c") or "ok",
                           [{"id": "2401.00001"}])
    _seed_verdict("2401.00001", "ok", 1)
    _seed_verdict("2401.00001", "dedup", 2)
    _seed_verdict("2401.00001", "dedup", 3)
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    assert _cell_rows(rd)[0]["status"] == "dedup"
    assert calls == []


def test_last_mutating_dedup_harvests_upstream_products(broot: Path):
    """last_mutating 撞 dedup 终态也收字节 —— 2609.20519 实证缺口:

    上游格本 run 真跑产出的 mutates 树, 在末段 dedup 行下以前直接随
    remove_cell_tree 清零, verdict 留账而字节永远不入 vault。末段自身
    kind 在押时 dedup 合法——此时要收的恰是上游新产出的 zh。"""
    # 末段自身 kind 已押 → coll dedup 合法成立 (字节闸放行 dedup)
    lqc_src = broot / "lqc-src"
    lqc_src.mkdir()
    (lqc_src / "qc.json").write_text("{}")
    vault.harvest("2401.00001", "-", "-", {"layoutqc": lqc_src},
                  source_run="seed", verdict="verified", zone="primary")

    def produce(ctx):
        d = ctx.asset_dir("zh")
        (d / "payload.txt").write_text("fresh bytes")
        return "ok"

    spec = _free_spec({"a": produce, "coll": lambda ctx: "ok"},
                      [{"id": "2401.00001"}])
    spec.stages[0].mutates = ["zh"]
    spec.stages[1].mutates = ["layoutqc"]
    _seed_verdict("2401.00001", "ok", 1, stage="coll")
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    rows = {e["stage"]: e["status"] for e in _cell_rows(rd)}
    assert rows["a"] == "ok"
    assert rows["coll"] == "dedup"
    # dedup 终态仍触发 harvest —— zh 字节入 vault 而非随 workdir 清零
    assert vault.bytes_ok("2401.00001", "-", "-")


def test_mutates_dedup_requires_intact_bytes(broot: Path):
    """免费 mutates 格 dedup 要字节在押: verdict-done + vault 缺席 →
    放行重跑 (免费 regen); 字节补齐后回到 dedup。"""
    calls = []

    def produce(ctx):
        calls.append("a")
        d = ctx.asset_dir("zh")
        (d / "payload.txt").write_text("fresh bytes")
        return "ok"

    spec = _free_spec({"a": produce, "coll": lambda ctx: "ok"},
                      [{"id": "2401.00001"}])
    spec.stages[0].mutates = ["zh"]
    spec.stages[1].mutates = ["layoutqc"]
    # a 有历史 ok verdict 但 vault 无字节 → 必须真跑不能 dedup
    _seed_verdict("2401.00001", "ok", 1, stage="a")
    _seed_verdict("2401.00001", "ok", 2, stage="coll")
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    rows = {e["stage"]: e["status"] for e in _cell_rows(rd)}
    assert calls == ["a"]                        # 字节缺席 → 重跑
    assert rows["a"] == "ok"
    assert vault.bytes_ok("2401.00001", "-", "-")

    calls.clear()
    res2 = kernel.run(spec, **_quiet())
    rd2 = runs.load_run(spec.kind, res2["date"], res2["slug"])
    rows2 = {e["stage"]: e["status"] for e in _cell_rows(rd2)}
    assert calls == []                           # 字节在押 → dedup
    assert rows2["a"] == "dedup"


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


# --- Wave-A0 kernel gaps ------------------------------------------------------------


def test_select_filters_plan_by_params(broot: Path):
    """G1: spec.select(item, resolved) narrows the frame per-run — run and
    plan share the filter, rejected items never pay a canon lookup."""
    spec = _free_spec(
        {"a": lambda c: "ok"},
        [{"id": "x"}, {"id": "y"}, {"id": "z"}],
        params={"keep": Param(str, default="x")},
        select=lambda it, p: it["id"] == p["keep"])
    res = kernel.run(spec, {"keep": "y"}, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    assert [r["idc"] for r in _cell_rows(rd)] == ["y"]
    q = kernel.plan(spec, {"keep": "z"}, **_quiet())
    assert [c["idc"] for c in q["cells"]] == ["z"]


def test_extra_item_fields_reach_cell(broot: Path):
    """G2 passthrough: item fields beyond the framework keys land on the
    cell dict verbatim — eval dedup_key callables read them."""
    seen = []

    def fn(ctx):
        seen.append((ctx.cell.get("model"), ctx.cell.get("rep")))
        return "ok"

    spec = _free_spec({"a": fn}, [{"id": "x", "model": "mA", "rep": 2}])
    kernel.run(spec, **_quiet())
    assert seen == [("mA", 2)]
    # and the frozen plan carries the extras (resume fidelity)
    res = kernel.run(_free_spec({"a": fn},
                                [{"id": "x", "model": "mA", "rep": 2}]),
                     **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    plan_cell = json.loads(rd.plan_path().read_text())["cells"][0]
    assert plan_cell["model"] == "mA" and plan_cell["rep"] == 2


def test_sig_synthesized_from_first_error(broot: Path):
    """G12: errors[0] -> 'cat:pay' when the fn doesn't return a sig."""

    def fn(ctx):
        return {"status": "fail",
                "errors": [{"cat": "compile", "code": "runaway",
                            "payload": "tcb"}]}

    spec = _free_spec({"a": fn}, [{"id": "x"}])
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    assert _cell_rows(rd)[0]["sig"] == "compile:tcb"


def test_sig_explicit_wins_over_synthesis(broot: Path):
    spec = _free_spec(
        {"a": lambda ctx: {"status": "fail", "sig": "custom:sig",
                           "errors": [{"cat": "x"}]}},
        [{"id": "x"}])
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    assert _cell_rows(rd)[0]["sig"] == "custom:sig"


def test_sig_synthesized_for_emit_errors(broot: Path):
    """Errors folded in via ctx.emit AFTER _terminal_ev ran still get a
    synthesized sig (the post-merge re-check)."""

    def fn(ctx):
        ctx.emit({"errors": [{"cat": "late", "msg": "m"}]})
        return "fail"

    spec = _free_spec({"a": fn}, [{"id": "x"}])
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    assert _cell_rows(rd)[0]["sig"] == "late"


def test_emit_case_lands_ledger_file_and_index(broot: Path):
    """G9: emit_case rows ride the terminal batch -> case events ->
    cases.jsonl + index.cases, all atomically with the cell verdict."""

    def fn(ctx):
        ctx.emit_case({"chunk": 0, "verdict": "pass"})
        ctx.emit_case({"chunk": 1, "verdict": "fail", "esa": 0.4})
        return "ok"

    spec = _free_spec({"a": fn}, [{"id": "x"}])
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    cases = [e for e in _shard(rd) if e["type"] == "case"]
    assert [c["payload"]["chunk"] for c in cases] == [0, 1]
    assert all(c["stage"] == "a" and c["idc"] == "x" for c in cases)
    cl = rd.cases_path()
    rows = [json.loads(l) for l in cl.read_text().splitlines()]
    assert len(rows) == 2 and rows[0]["payload"]["verdict"] == "pass"
    idx = indexmod.Index()
    try:
        idx.tail_ingest()
        got = idx.conn.execute(
            "SELECT stage, payload FROM cases WHERE idc='x'").fetchall()
    finally:
        idx.close()
    author_rows = [r for r in got
                   if "chunk" in json.loads(r["payload"])]
    assert len(author_rows) == 2
    assert all(r["stage"] == "a" for r in author_rows)


def test_emit_case_dies_with_failed_cell(broot: Path):
    """A crashed cell emits no case rows — the buffer only flushes inside
    the terminal batch."""
    def fn(ctx):
        ctx.emit_case({"chunk": 0})
        raise RuntimeError("boom")

    spec = _free_spec({"a": fn}, [{"id": "x"}])
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    # the error terminal still flushes the batch — the case row lands too
    # (partial eval evidence is deliberately preserved for fail cells)
    assert _cell_rows(rd)[0]["status"] == "error"
    cases = [e for e in _shard(rd) if e["type"] == "case"]
    assert len(cases) == 1  # buffered pre-crash rows DO land — doc'd choice


def test_eval_paid_remapped_dedup_key_runs_and_dedups(broot: Path):
    """G2: an eval paid stage may claim on a remapped keyspace; the cell's
    own DONE row dedups the re-run (no mutates => no bytes to lose). Cell
    uniqueness still rides arm/variant — the remap moves the CLAIM space."""
    calls = []
    spec = Spec(
        kind="tevpaid", eval=True,
        dedup_key=lambda c: (c["idc"], c.get("model", "-"),
                             str(c.get("rep", "-"))),
        items=[{"id": "s1", "variant": "v0", "model": "mA", "rep": 0},
               {"id": "s1", "variant": "v1", "model": "mA", "rep": 1}],
        stages=[_stage("judge",
                       lambda ctx: calls.append(ctx.cell["rep"]) or "ok",
                       paid=True)])
    assert specmod.compile_checks(spec) == []
    factory = _factory(object())
    res = kernel.run(spec, max_cost=1.0, gateway_factory=factory, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    assert [r["status"] for r in _cell_rows(rd)] == ["ok", "ok"]
    assert calls == [0, 1]
    claim_evs = [e for e in _shard(rd)
                 if e["type"] == "claim" and e.get("op") == "acquire"]
    keys = {(e["idc"], e["arm"], e["variant"]) for e in claim_evs}
    assert keys == {("s1", "mA", "0"), ("s1", "mA", "1")}
    calls.clear()
    res2 = kernel.run(spec, max_cost=1.0, gateway_factory=factory,
                      **_quiet())
    rd2 = runs.load_run(spec.kind, res2["date"], res2["slug"])
    assert [r["status"] for r in _cell_rows(rd2)] == ["dedup", "dedup"]
    assert calls == []


def test_process_executor_refused_loudly(broot: Path):
    """G8 deferred: executor='process' fails fast at run entry, not on a
    pickle error deep in the executor pass."""
    spec = _free_spec({"a": lambda c: "ok"}, [{"id": "x"}],
                      executor="process")
    with pytest.raises(kernel.RunError, match="process"):
        kernel.run(spec, **_quiet())
    # stage-level override refuses identically
    spec2 = _free_spec({"a": lambda c: "ok"}, [{"id": "x"}])
    spec2.stages[0].executor = "process"
    with pytest.raises(kernel.RunError, match="process"):
        kernel.run(spec2, **_quiet())


# --- lake wiring (G4): fetch_fn + lake_ensure + lookahead -----------------------------


def _lake_fetch(calls, files=None):
    """A spec.fetch_fn: populate {stage}/extracted/, record the idc."""
    def fetch(idc, stage):
        calls.append(idc)
        ex = Path(stage) / "extracted"
        ex.mkdir(parents=True)
        for name, body in (files or {"a.tex": "tex"}).items():
            p = ex / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
    return fetch


def test_lake_ensure_fetches_via_spec_fetch_fn(broot: Path, monkeypatch):
    """G4: a stage fn hydrates through ctx.lake_ensure — the spec's
    fetch_fn supplies the bytes; one-fetch-one-wait makes the prefetcher
    and the consumer agree on a single fetch."""
    monkeypatch.setenv("TEXLATE_LAKE_FLOOR_GB", "0")
    calls = []

    def fn(ctx):
        d = ctx.lake_ensure()
        return "ok" if d is not None and (d / "extracted" / "a.tex") \
            .is_file() else "error"

    spec = _free_spec({"a": fn}, [{"id": "9901.00010"}],
                      lake=True, fetch_fn=_lake_fetch(calls))
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    assert [r["status"] for r in _cell_rows(rd)] == ["ok"]
    assert calls == ["9901.00010"]           # exactly one fetch (lock-dedup)
    assert lake.is_complete("9901.00010")
    meta = json.loads(
        (lake.cell_dir("9901.00010") / "meta.json").read_text())
    assert meta["run_seq"] == rd.run_seq


def test_src_path_projects_hydrated_tree(broot: Path, monkeypatch):
    """src_path rides lake_ensure: spec fetch_fn -> hardlink projection
    into work/{id}/src."""
    monkeypatch.setenv("TEXLATE_LAKE_FLOOR_GB", "0")
    calls = []

    def fn(ctx):
        src = ctx.src_path()
        if src is None:
            return "error"
        return "ok" if (src / "a.tex").read_text() == "tex" else "error"

    spec = _free_spec({"a": fn}, [{"id": "9901.00011"}],
                      lake=True, fetch_fn=_lake_fetch(calls))
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    assert [r["status"] for r in _cell_rows(rd)] == ["ok"]
    assert calls == ["9901.00011"]


def test_prefetch_disabled_leaves_lake_lazy(broot: Path):
    """prefetch=False: no lookahead thread, and a stage fn that never
    asks leaves the cell unfetched."""
    calls = []
    spec = _free_spec({"a": lambda ctx: "ok"}, [{"id": "9901.00012"}],
                      lake=True, prefetch=False,
                      fetch_fn=_lake_fetch(calls))
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    assert [r["status"] for r in _cell_rows(rd)] == ["ok"]
    assert calls == []
    assert not lake.is_complete("9901.00012")


def test_lookahead_burst_hydrates_all(broot: Path, monkeypatch):
    """The t=0 burst IS the plan-time batch warm-up: driven directly, the
    prefetcher hydrates every non-terminal planned idc; cells already
    terminal are skipped; early cell_started races are absorbed by the
    consumed-set instead of leaking a window slot."""
    monkeypatch.setenv("TEXLATE_LAKE_FLOOR_GB", "0")
    from types import SimpleNamespace
    calls = []
    spec = Spec(kind="tlake", stages=[], items=[], lake=True,
                fetch_fn=_lake_fetch(calls))
    env = {"abort": threading.Event(),
           "rd": SimpleNamespace(run_seq=1, run="tlake/2026-01-01/x")}
    la = kernel._Lookahead(env, spec)
    cells = [{"id": i, "idc": i, "arm": "-", "up": "-", "variant": "-",
              "stage": "a"}
             for i in (f"9901.0002{i}" for i in range(4))]
    # the last cell is already terminal this run — filtered out
    terminal = {("9901.00023", "-", "-", "-", "a")}
    la.start(cells, terminal)
    # consume two while the loop may still be walking — the consumed-set
    # drops their (possibly not-yet-recorded) pending entries
    la.cell_started("9901.00020")
    la.cell_started("9901.00021")
    la._thread.join(timeout=10)
    assert not la._thread.is_alive()
    assert sorted(calls) == ["9901.00020", "9901.00021", "9901.00022"]
    for i in calls:
        assert lake.is_complete(i)
    # never-consumed hydrations sit in the window; consumed ones don't
    assert set(la._pending) == {"9901.00022"}


def test_lookahead_window_bounded(broot: Path, monkeypatch):
    """Window bound: with LOOKAHEAD_CELLS=2 the prefetcher never runs
    more than 2 hydrations ahead of the execution frontier."""
    monkeypatch.setenv("TEXLATE_LAKE_FLOOR_GB", "0")
    monkeypatch.setattr(kernel, "LOOKAHEAD_CELLS", 2)
    monkeypatch.setattr(kernel, "LOOKAHEAD_BYTES", 10 ** 12)
    state = {"fetched": 0, "started": 0, "viol": 0}
    lock = threading.Lock()

    def fetch(idc, stage):
        with lock:
            if state["fetched"] - state["started"] > 2:
                state["viol"] += 1
            state["fetched"] += 1
        ex = Path(stage) / "extracted"
        ex.mkdir(parents=True)
        (ex / "a.tex").write_text("x")

    def fn(ctx):
        with lock:
            state["started"] += 1
        time.sleep(0.01)                   # let the prefetcher run ahead
        return "ok"

    spec = _free_spec(
        {"a": fn},
        [{"id": f"9901.0004{i}"} for i in range(6)],
        lake=True, fetch_fn=fetch)
    kernel.run(spec, **_quiet())
    assert state["viol"] == 0
