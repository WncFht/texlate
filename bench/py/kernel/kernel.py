"""kernel — the 8-step run pipeline + the cell critical section (§2.1).

    run(spec_or_path, params=None, *, date=None, slug=None, resume=False,
        replan=False, max_cost=None, regen=False, sel=None, yes=False,
        allow_regen=False, gateway_factory=None, jobs=4, emit=print)
        -> dict
    plan(spec_or_path, params=None, **kw) -> dict        # dry-run quote

Pipeline (design §2.1):

    1. spec load + compile_checks + param coercion (stringly params die
       here — unknown/uncoercible params are refused before side effects)
    2. item enumeration + canon resolution (registry-gated unless
       spec.eval; ambig/invalid ids drop with a note, never silently)
    3. run materialization — create_run (auto-slug) or load_run (resume);
       spec.json/spec_env/invocations frozen beside the events shard
    4. frozen plan — freeze_plan writes {cells} once; resume reads it
       verbatim unless --replan
    5. seq allocator (per-run monotonic mint seeded above existing shard
       seqs) + Index + tail_ingest + DedupOracle snapshot
    6. cell_queued batch — one emit_batch for every plan cell lacking a
       terminal in THIS run (accounting's queued set, §3.1)
    7. executor pass — cells grouped by stage executor, same-idc serial
    8. reconcile — this run's pending vault metas promoted by cell
       verdicts; accounting_check; finished event; report dict

Cell critical section (§2.1, §3.6, §3.10.6), inside cell_lock:

    this-run terminal recheck -> cross-run done -> paid oracle
    (unsealed->error/index_unsealed | claimed->claimed | verified->dedup
     | missing->regen gate | absent->proceed) -> meter pre-check ->
    needs eval (no domain DONE row -> skip; done but product lost ->
    fault/upstream-lost) -> PAUSE (paid cells only) -> AUTH_DEAD ->
    claim NB-acquire ->
    claim acquire event + cell_started -> fn(ctx) -> status_class
    classify (unclassified -> fault + note) -> last-mutating harvest
    BEFORE terminal emit (§3.5) -> ONE emit_batch {terminal + outbox +
    claim-release fate} -> lease.release()

Lock order honored: run.lock -> cell.lock -> claim.lock -> leaf {slot,
ledger, index, vault}. Everything under cell.lock that isn't a leaf is
NB-only.
"""
from __future__ import annotations

import contextlib
import itertools
import json
import shutil
import sys
import threading
import time
from pathlib import Path

from kernel import (
    cache as cachemod,
    claims,
    dedup as dedupmod,
    events,
    executors,
    fsutil,
    idnorm,
    index as indexmod,
    lake,
    ledger,
    locks,
    paid as paidmod,
    paths,
    runs,
    spec as specmod,
    vault,
)
from kernel.ctx import Ctx
from kernel.spec import Spec, SpecError, cell_fp, compile_checks, load_spec

__all__ = ["run", "plan", "RunError"]


class RunError(RuntimeError):
    """A run-level refusal/crash — raised before or out of the pipeline."""


# --- small utilities -----------------------------------------------------------------


def _sel_hit(sel, cell: dict) -> bool:
    """Selector match: comma-separated k=v predicates over
    {id,idc,arm,up,variant,stage}; bare tokens match id|idc. All must
    match; '*' matches everything. sel=None -> False (no hit claimed)."""
    if sel is None:
        return False
    s = str(sel).strip()
    if not s or s == "*":
        return True
    for pred in s.split(","):
        pred = pred.strip()
        if not pred:
            continue
        if "=" in pred:
            k, v = pred.split("=", 1)
            if str(cell.get(k.strip(), "")) != v.strip():
                return False
        else:
            if pred not in (str(cell.get("id")), str(cell.get("idc"))):
                return False
    return True


def _coerce_params(spec: Spec, params) -> dict:
    """Run params: defaults <- supplied, coerced through Param types.
    Unknown keys and missing requireds are refused (§4 — no stringly)."""
    params = dict(params or {})
    unknown = sorted(set(params) - set(spec.params))
    if unknown:
        raise SpecError([f"unknown run params {unknown} — spec declares "
                         f"{sorted(spec.params)}"])
    out = {}
    for name, p in spec.params.items():
        raw = params.get(name, p.default)
        if raw is None:
            if p.required:
                raise SpecError([f"required param {name!r} missing"])
            out[name] = None
            continue
        out[name] = p.coerce(name, raw)
    return out


def _spec_env(spec: Spec) -> dict:
    """Probe-name -> resolution. 记名不记值: only tool identities/paths,
    never secrets."""
    env = {"python": sys.version.split()[0]}
    for probe in spec.env_probes:
        if probe == "python":
            continue
        env[str(probe)] = shutil.which(str(probe)) or None
    return env


def _max_shard_seq(rd: runs.RunDir) -> int:
    hi = -1
    shard = rd.events_path()
    if shard.exists():
        for _ln, ev, _raw in events.iter_jsonl(shard):
            if isinstance(ev, dict) and isinstance(ev.get("seq"), int):
                hi = max(hi, ev["seq"])
    return hi


def _shard_terminal_keys(rd: runs.RunDir) -> set:
    """Cell keys already terminal in THIS run's shard (resume's done set)."""
    out = set()
    shard = rd.events_path()
    if not shard.exists():
        return out
    for _ln, ev, _raw in events.iter_jsonl(shard):
        if isinstance(ev, dict) and events.is_terminal_cell(ev):
            out.add(runs._cell_key(ev))
    return out


# --- first-fire gate (§6 Phase-3 首火闸) -----------------------------------------


_VERIFY_FRESH_S = 24 * 3600


def _first_fire_gate(spec: Spec, oracle, cells: list, rd) -> dict:
    """The no-attendance paid-spend machine gate.

    Three legs, ALL must hold or the paid spec refuses to run:

    1. dedup coverage — ``oracle.quote`` over the unique paid cell keys;
    2. sealed index — ``quote['sealed']`` AND zero 'unsealed' buckets
       (a stale index errs toward re-pay; fail-closed);
    3. vault verify freshness — ``vault/.verify-stamp.json`` written by a
       clean `bench vault verify` within 24h.

    coverage.json lands in the run's derived/ either way — the refused
    attempt leaves its evidence behind.
    """
    paid_keys = set()
    for c in cells:
        st = spec.stage(c["stage"])
        if st is not None and st.paid:
            paid_keys.add(spec.dedup_key_of(st, c))
    quote = oracle.quote(sorted(paid_keys))
    stamp = None
    try:
        stamp = json.loads(
            paths.vault_verify_stamp_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    verify_age = (time.time() - stamp["ts"]
                  if isinstance(stamp, dict)
                  and isinstance(stamp.get("ts"), (int, float))
                  else None)
    verify_fresh = verify_age is not None and verify_age < _VERIFY_FRESH_S
    coverage = {
        "ts": round(time.time(), 3),
        "paid_keys": len(paid_keys),
        "quote": {k: quote[k] for k in
                  ("new", "reuse", "missing", "claimed", "attempted",
                   "unsealed", "total")},
        "sealed": bool(quote["sealed"]),
        "verify_age_s": (round(verify_age, 1)
                         if verify_age is not None else None),
        "verify_fresh": verify_fresh,
    }
    try:
        d = rd.derived()
        d.mkdir(parents=True, exist_ok=True)
        fsutil.atomic_write(
            d / "coverage.json",
            (json.dumps(coverage, ensure_ascii=False, sort_keys=True,
                        indent=2) + "\n").encode("utf-8"))
    except OSError:
        pass  # evidence write is best-effort; the gate still binds
    fails = []
    if not coverage["sealed"] or coverage["quote"]["unsealed"]:
        fails.append(
            f"index unsealed (sealed={coverage['sealed']} "
            f"unsealed={coverage['quote']['unsealed']})")
    if not verify_fresh:
        fails.append(
            "vault verify stale/missing "
            f"(age_s={coverage['verify_age_s']}, need <{_VERIFY_FRESH_S}s — "
            "run `bench vault verify`)")
    if fails:
        raise RunError(
            "first-fire gate refused paid run: " + "; ".join(fails)
            + f" (coverage: {coverage['quote']})")
    return coverage


class _SeqAlloc:
    """Per-run monotonic seq mint — one counter under one lock, shared by
    every worker thread. cell_queued consumes the low range; execution
    events mint upward. (run_seq,seq) uniqueness is the index dedup key —
    no two events ever share a seq."""

    def __init__(self, start: int):
        self._it = itertools.count(start)
        self._lock = threading.Lock()

    def __call__(self) -> int:
        with self._lock:
            return next(self._it)


# --- item enumeration + canon ---------------------------------------------------------


def _enumerate_cells(spec: Spec, registry, resolved: dict):
    """Items x stages -> plan cell dicts. Returns (cells, problems) —
    problems are ids that failed canon (dropped, noted later)."""
    stage_order = specmod.topo_stages(spec) or list(spec.stages)
    cells: list[dict] = []
    problems: list[str] = []
    for item in spec.iter_items():
        # G1 plan-filter: spec.select(item, resolved_params) narrows the
        # frame per-run BEFORE canon — rejected items never pay a registry
        # lookup, and raw-id selectors (--ids) match the author's spelling.
        if spec.select is not None and not spec.select(item, resolved):
            continue
        raw = item.get("id")
        if spec.eval:
            idc = str(raw)
        else:
            res = idnorm.canon_id(str(raw), registry)
            if not res.ok or not res.idc:
                problems.append(
                    f"item {raw!r}: canon {res.state} ({res.reason})")
                continue
            idc = res.idc
        wanted = item.get("stage")
        for st in stage_order:
            if wanted and st.name != wanted:
                continue
            cell = {
                "id": str(raw), "idc": idc,
                "arm": str(item.get("arm", "-")),
                "up": str(item.get("up", "-")),
                "variant": str(item.get("variant", "-")),
                "stage": st.name,
                "needs": [{"stage": s, "accept": sorted(a)}
                          for s, a in st.needs],
                "fp_input": item.get("fp_input"),
                "params": dict(item.get("params") or {}),
                "run_params": dict(resolved),
                "layer": item.get("layer"),
            }
            # Extra item fields ride the cell verbatim (eval dedup_key
            # callables read them — e.g. cell["model"]/["rep"]). Framework
            # keys are already set above and never overwritten; "id"/"idc"/
            # "stage" are the canonical spellings, also already set.
            for k, v in item.items():
                if k not in cell:
                    cell[k] = v
            cells.append(cell)
    return cells, problems


# --- needs evaluation ------------------------------------------------------------------


def _last_outcome(idx, idc, arm, up, variant, stage) -> dict | None:
    """Last T_CELL records row for the key across ALL runs.

    The `cells` table is a latest-state projection — this run's own
    cell_queued/cell_started events mask prior terminal outcomes to
    'queued'/'started'. `records` holds T_CELL rows only, so it is the
    honest outcome history the self-dedup check must read (§3.1).
    """
    row = idx.conn.execute(
        "SELECT run,seq,id,idc,arm,up,variant,stage,status,cat,sig,code,"
        "fp,dur_s,metrics,errors,ts FROM records "
        "WHERE idc=? AND arm=? AND up=? AND variant=? AND stage=? "
        "ORDER BY rowid DESC LIMIT 1",
        (idc, arm, up, variant, stage)).fetchone()
    return dict(row) if row is not None else None


def _last_rec(idx, idc, arm, up, variant, stage, domain=None,
              statuses=None) -> dict | None:
    """Last records row for the key — newest ledger row wins (rowid)."""
    sql = ("SELECT run,seq,id,idc,arm,up,variant,stage,status,cat,sig,code,"
           "fp,dur_s,metrics,errors,ts FROM records "
           "WHERE idc=? AND arm=? AND up=? AND variant=? AND stage=?")
    args: list = [idc, arm, up, variant, stage]
    if domain is not None:
        dom = sorted(domain)
        sql += f" AND run IN ({','.join('?' * len(dom))})"
        args += dom
    if statuses is not None:
        sts = sorted(statuses)
        sql += f" AND status IN ({','.join('?' * len(sts))})"
        args += sts
    sql += " ORDER BY rowid DESC LIMIT 1"
    row = idx.conn.execute(sql, args).fetchone()
    return dict(row) if row is not None else None


def _dir_has_files(d: Path) -> bool:
    try:
        return d.is_dir() and any(p.is_file() for p in d.rglob("*"))
    except OSError:
        return False


def _product_ok(rd: runs.RunDir, cell: dict, up_stage: str,
                up_spec, rec: dict, idc: str, arm: str, variant: str,
                safe: str) -> bool:
    """'产物可解析' for a mutating upstream — PER-KIND, never cell-level.

    A kind counts through evidence the stage fn can actually REACH: an
    intact vault copy declaring it (ctx restores via vault.restore), or
    this run's own work tree. The upstream run's work tree is NOT
    evidence — ctx.upstream_asset_dir can only read this run's
    paper_dir, so bytes stranded in a foreign run dir greenlight a cell
    that then crash-loops on FileNotFoundError. A manifest-dead kind
    (tombstone/loss row with no later revive) vetoes the whole product
    UNLESS fresh work-tree bytes exist for it — vault-intact bytes do
    NOT revive a tombstoned kind, because tombstone is a verdict-layer
    loss record that deliberately leaves bytes on disk. The old
    cell-level bytes_ok leg let a live 'state' copy mask a tombstoned
    'zh' — downstream then burned paid requests against a product the
    ledger had already declared lost."""
    if not up_spec or not up_spec.mutates:
        return True
    try:
        ev = dedupmod.manifest_kind_evidence().get((idc, arm, variant))
    except Exception:
        ev = None
    dead = ev["dead"] if ev else set()
    try:
        vrows = vault.query(idc, arm, variant)
    except Exception:
        vrows = []
    base = rd.work(safe)
    lost = present = False
    for k in up_spec.mutates:
        work = _dir_has_files(base / vault._work_dirname(k, arm, variant))
        intact = any(
            isinstance(r.get("files"), dict) and k in r["files"]
            and r.get("bytes_ok")
            for r in vrows)
        if k in dead and not work:
            lost = True
        elif intact or work:
            present = True
    return present and not lost


def _needs_eval(rd: runs.RunDir, spec: Spec, idx, cell: dict,
                safe: str):
    """Evaluate the cell's needs edges (§3.6 needs domain).

    Returns ("proceed", primary_upstream_rec|None)
         | ("skip", reason)
         | ("fault", "upstream-lost").

    Domain = this run ∪ spec.foreign_runs. The LAST domain row governs:
    'dedup' resolves through the mask to the last DONE row anywhere (a
    dedup terminal in this run IS the declaration that the work is done);
    every other non-DONE row falls back to the last DONE row in domain —
    a retriable retry after an ok still counts the ok.
    """
    stage = spec.stage(cell["stage"])
    if stage is None:
        return ("skip", f"stage {cell['stage']} not in spec")
    domain = {rd.run} | set(spec.foreign_runs or [])
    primary = None
    for up_stage, _accept in stage.needs:
        latest = _last_rec(idx, cell["idc"], cell["arm"], cell["up"],
                           cell["variant"], up_stage, domain=domain)
        if latest is None:
            return ("skip", f"needs {up_stage}: no record in domain")
        if latest["status"] == "dedup":
            rec = _last_rec(idx, cell["idc"], cell["arm"], cell["up"],
                            cell["variant"], up_stage,
                            statuses=events.STATUS_DONE)
        else:
            rec = _last_rec(idx, cell["idc"], cell["arm"], cell["up"],
                            cell["variant"], up_stage, domain=domain,
                            statuses=events.STATUS_DONE)
        if rec is None:
            return ("skip", f"needs {up_stage}: no done row "
                            f"(latest domain: {latest['status']})")
        accept = stage.accept_for(up_stage)
        if rec["status"] not in accept:
            return ("skip", f"needs {up_stage}: status {rec['status']!r} "
                            f"not in accept {sorted(accept)}")
        up_spec = spec.stage(up_stage)
        if not _product_ok(rd, cell, up_stage, up_spec, rec,
                           cell["idc"], cell["arm"], cell["variant"], safe):
            return ("fault", "upstream-lost")
        if primary is None:
            primary = rec
    return ("proceed", primary)


# --- outbox / terminal plumbing --------------------------------------------------------


_CELL_MERGE_KEYS = {"metrics", "errors", "sig", "code", "dur_s"}
# Framework-owned cell fields — emit() can never rewrite identity/status
# (status comes from the fn return alone; fp is kernel-stamped).
_CELL_RESERVED = {"id", "idc", "arm", "up", "variant", "stage", "run",
                  "seq", "ts", "type", "status", "fp"}


def _merge_outbox(terminal_ev: dict, outbox: list) -> list:
    """Fold author emit() rows into the terminal event + verbatim events.

    Rows without 'type' merge into the terminal cell event: whitelisted
    merge keys fold directly (metrics update, errors extend, scalars
    last-wins); cell-identity/framework keys drop; every other payload
    key folds into ``metrics`` — that keeps the T_CELL whitelist closed
    while still landing author rows like {metric, chars, lines} on the
    ledger (§3.1). Rows with 'type' (make_event'd verbatim events incl.
    buffered notes) pass through as their own ledger rows.
    """
    extra: list[dict] = []

    def _metrics() -> dict:
        m = terminal_ev.get("metrics")
        if not isinstance(m, dict):
            m = {}
            terminal_ev["metrics"] = m
        return m

    for row in outbox:
        if not isinstance(row, dict):
            continue
        if "type" in row:
            extra.append(row)
            continue
        for k, v in row.items():
            if k in _CELL_RESERVED:
                continue
            if k == "metrics" and isinstance(v, dict):
                _metrics().update(v)
            elif k == "errors":
                e = terminal_ev.get("errors")
                if not isinstance(e, list):
                    e = []
                    terminal_ev["errors"] = e
                e.extend(v if isinstance(v, list) else [v])
            elif k in _CELL_MERGE_KEYS:
                terminal_ev[k] = v
            else:
                _metrics()[k] = v
    return extra


def _synth_sig(errors) -> str | None:
    """errors[0] -> ``cat:pay`` default sig (the benchlib.errors_sig triage
    contract as a kernel-side default — a fn returning its own sig always
    wins; this only fires when the row would otherwise carry none)."""
    if not isinstance(errors, list) or not errors:
        return None
    e0 = errors[0]
    if not isinstance(e0, dict):
        return None
    cat = str(e0.get("cat") or e0.get("code") or "error")
    pay = str(e0.get("payload") or "")
    return f"{cat}:{pay}".rstrip(":")


def _terminal_ev(env, cell, status: str, *, seq: int, cat=None, dur_s=None,
                 fp=None, metrics=None, errors=None, sig=None, code=None,
                 extra=None) -> dict:
    ev = events.make_event(
        events.T_CELL, run=env["rd"].run, seq=seq, id=cell["id"],
        idc=cell["idc"], arm=cell["arm"], up=cell["up"],
        variant=cell["variant"], stage=cell["stage"], status=status)
    spec = env.get("spec")
    stage_obj = spec.stage(cell["stage"]) if spec is not None else None
    if (spec is not None and spec.eval) or (
            stage_obj is not None and getattr(stage_obj, "eval", False)):
        ev["eval"] = True
    if cat is not None:
        ev["cat"] = cat
    if dur_s is not None:
        ev["dur_s"] = dur_s
    if fp is not None:
        ev["fp"] = fp
    if metrics is not None:
        ev["metrics"] = metrics
    if errors is not None:
        ev["errors"] = errors
    if sig is None:
        sig = _synth_sig(errors)
    if sig is not None:
        ev["sig"] = sig
    if code is not None:
        ev["code"] = code
    for k, v in (extra or {}).items():
        if k in events.OPTIONAL_WHITELIST:
            ev[k] = v
    return ev


def _note(env, text: str, level: str = "info"):
    """Kernel note row — negative seqs (kernel writer namespace)."""
    try:
        runs._emit_note(env["rd"], text, level=level)
    except Exception:
        pass


# --- lake lookahead prefetcher (§3.10.3 预取双机制) ------------------------------------

# Window bounds: at most this many hydrated-but-unconsumed cells — or this
# many bytes of them — may sit ahead of the execution frontier.
LOOKAHEAD_CELLS = 32
LOOKAHEAD_BYTES = 512 * 1024 ** 2


class _Lookahead:
    """Run-internal lake prefetcher. One daemon thread walks the plan's
    distinct idcs in order, hydrating each through the spec's fetch_fn,
    holding at most LOOKAHEAD_CELLS cells (or LOOKAHEAD_BYTES of payload)
    not yet consumed by a started cell. At run start the window is empty
    so the first ≤32 cells hydrate immediately — that burst IS the
    plan-time batch warm-up; sustained operation IS the run-internal
    lookahead. The two named mechanisms are one thread.

    Prefetch is advisory: a hydrate failure is a note, never fatal — the
    consumer's own ctx.lake_ensure retries under the same per-cell lease
    (one-fetch-one-wait). Window bookkeeping tolerates races: a cell that
    starts before its prefetch record lands is remembered ``consumed``
    so the late record is dropped instead of leaking a slot."""

    def __init__(self, env, spec: Spec) -> None:
        self._env = env
        self._spec = spec
        self._stop = threading.Event()
        self._cond = threading.Condition()
        self._pending: dict[str, int] = {}   # idc -> hydrated bytes
        self._consumed: set[str] = set()     # started before prefetch landed
        self._thread: threading.Thread | None = None

    def _window_open(self) -> bool:
        return (len(self._pending) < LOOKAHEAD_CELLS
                and sum(self._pending.values()) < LOOKAHEAD_BYTES)

    def cell_started(self, idc: str) -> None:
        """Frontier bump — a started cell claims its prefetched bytes."""
        with self._cond:
            if idc in self._pending:
                del self._pending[idc]
            else:
                self._consumed.add(idc)
            self._cond.notify_all()

    def _loop(self, idcs: list) -> None:
        spec = self._spec
        env = self._env
        run_seq = getattr(env["rd"], "run_seq", 0) or 0
        source = getattr(spec, "lake_source", "arxiv") or "arxiv"
        for idc in idcs:
            if self._stop.is_set() or env["abort"].is_set():
                return
            with self._cond:
                while not (self._stop.is_set() or env["abort"].is_set()
                           or self._window_open()):
                    self._cond.wait(timeout=2.0)
                if self._stop.is_set() or env["abort"].is_set():
                    return
            if not lake.admit(0):
                _note(env, "lake lookahead paused: zone over capacity cap "
                           "or fs floor — consumers still self-hydrate",
                      level="warn")
                return
            try:
                d = lake.hydrate(idc, fetch_fn=spec.fetch_fn,
                                 source=source, run_seq=run_seq)
            except Exception as exc:  # noqa: BLE001 - advisory lane
                _note(env, f"lake prefetch {idc} failed: "
                           f"{type(exc).__name__}: {exc}", level="warn")
                continue
            if d is None:
                continue                  # lazy-unfetchable — no slot used
            try:
                size = fsutil.dir_size(d)
            except OSError:
                size = 0
            with self._cond:
                if idc not in self._consumed:
                    self._pending[idc] = size

    def start(self, cells: list, terminal_keys: set) -> None:
        """Spawn the prefetcher over plan-order distinct idcs whose cells
        still owe this run a terminal (already-terminal cells need no
        warm bytes — and never claim a window slot)."""
        idcs, seen = [], set()
        for c in cells:
            k = (str(c["idc"]), str(c.get("arm", "-")), str(c.get("up", "-")),
                 str(c.get("variant", "-")), str(c["stage"]))
            if k in terminal_keys:
                continue
            idc = str(c["idc"])
            if idc not in seen:
                seen.add(idc)
                idcs.append(idc)
        if not idcs:
            return
        self._thread = threading.Thread(
            target=self._loop, args=(idcs,), daemon=True,
            name="lake-lookahead")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=10)


# --- the cell critical section ----------------------------------------------------------


def _thread_index(env):
    """Per-worker-thread Index — sqlite conns are thread-bound."""
    tl = env["thread_local"]
    idx = getattr(tl, "index", None)
    if idx is None:
        spec = env.get("spec")
        eval_stages = {s.name for s in getattr(spec, "stages", ())
                       if getattr(s, "eval", False)} or None
        idx = indexmod.Index(eval_stages=eval_stages)
        tl.index = idx
        tl.oracle = dedupmod.DedupOracle(
            idx,
            manifest_tail=env["oracle"].manifest_tail,
            paid_pool_snap=env["oracle"].paid_pool_snap,
            sealed_gen=env["oracle"].sealed_gen,
            min_offset=env["oracle"].min_offset,
            kind_evidence=env["oracle"].kind_evidence,
        )
    return tl.index, tl.oracle


def _emit(env, idx, ev):
    return ledger.emit(ev, run_dir=env["rd"].path, sink=idx.apply_event)


def _emit_batch(env, idx, evs):
    return ledger.emit_batch(evs, run_dir=env["rd"].path,
                             sink=idx.apply_event)


def _harvest_last_mutating(env, idx, cell, stage_name, status, alloc):
    """§3.5: the LAST mutating stage's done-status terminal seals the
    cell's mutates-kind trees into the vault before the terminal row.

    Runs on every terminal path — quick() refusals included: reject is a
    done status, and a regen/budget-refused paid cell still owns upstream
    mutates products that would otherwise die in the work tree."""
    spec = env["spec"]
    if (stage_name != spec.last_mutating_stage()
            or status not in events.STATUS_DONE):
        return
    rd = env["rd"]
    ctx = Ctx(rd, cell, idx, spec)
    assets = ctx.asset_dirs()
    if not assets:
        return
    idc = str(cell["idc"])
    arm = str(cell.get("arm", "-"))
    variant = str(cell.get("variant", "-"))
    try:
        vault.harvest(
            idc, arm, variant, assets, source_run=rd.run,
            id=cell["id"], seq=alloc, sink=idx.apply_event,
            run_dir=rd.path)
    except Exception as exc:  # noqa: BLE001 - loud, not fatal
        _note(env, f"harvest failed for {idc}/{arm}/{variant}: "
                   f"{type(exc).__name__}: {exc}", level="warn")


def _run_cell(env, cell: dict) -> dict:
    """One plan cell through the critical section. NEVER raises — every
    path lands exactly one ledger row (terminal or retriable)."""
    rd: runs.RunDir = env["rd"]
    spec: Spec = env["spec"]
    alloc = env["alloc"]
    idx, oracle = _thread_index(env)
    idc = str(cell["idc"])
    arm = str(cell.get("arm", "-"))
    up = str(cell.get("up", "-"))
    variant = str(cell.get("variant", "-"))
    stage_name = str(cell["stage"])
    safe = idnorm.safe_id(idc)
    stage = spec.stage(stage_name)
    key = (idc, arm, up, variant, stage_name)

    def quick(status, cat=None, errors=None, extra=None):
        """Terminal-ish one-shot row (gates that fire before fn runs)."""
        _harvest_last_mutating(env, idx, cell, stage_name, status, alloc)
        ev = _terminal_ev(env, cell, status, seq=alloc(), cat=cat,
                          errors=errors, extra=extra)
        _emit(env, idx, ev)
        return {"cell": key, "status": status, "cat": cat}

    # ExitStack second so claim release unwinds INSIDE cell.lock on every
    # path — an emit failure mid-cell must not strand the lease held.
    with runs.cell_lock(rd, safe), contextlib.ExitStack() as _stack:
        # lookahead frontier bump — inside cell_lock: a cell queued on the
        # lock has not consumed its prefetched bytes yet
        la = env.get("lookahead")
        if la is not None:
            la.cell_started(idc)

        # 0. run-level abort flag (auth breaker tripped mid-run)
        if env["abort"].is_set():
            return quick("error", cat="auth_dead")

        # 1. already terminal in THIS run (resume continuation)
        if key in env["terminal_keys"]:
            return {"cell": key, "status": "already-terminal"}

        # 2. cross-run dedup — the last OUTCOME row (records, not the
        #    queued-masked cells table) decides; DONE ∪ {dedup} = work
        #    evidence. 'lost'/'claimed'/'unpaid_gate' are KERNEL
        #    adjudication states (swept zombie, live-lock mask, gate
        #    refusal) — deduping them bricks a never-completed cell
        #    forever. ASSET-PAID STAGES SKIP THIS ENTIRELY: the step-3
        #    oracle owns them (verified -> dedup, missing -> regen gate,
        #    absent -> budget fuse) because a DONE row without verified
        #    bytes is poison. EVAL-PAID stages with no mutates have no
        #    bytes to lose — their own DONE row IS the paid evidence and
        #    dedups here (§4 eval keyspace).
        last = _last_outcome(idx, idc, arm, up, variant, stage_name)
        stage_paid = stage is not None and stage.paid
        eval_paid_nobytes = bool(
            stage_paid and not stage.mutates
            and (spec.eval or getattr(stage, "eval", False)))
        if (last is not None and (not stage_paid or eval_paid_nobytes)
                and last["status"] in events.STATUS_DONE | {"dedup"}):
            return quick("dedup")

        # 3. paid gate — the fail-closed oracle owns every paid cell
        if stage is not None and stage.paid:
            k_idc, k_arm, k_var = spec.dedup_key_of(stage, cell)
            verdict = oracle.check(
                k_idc, k_arm, k_var, stage_paid=True,
                need_kinds=frozenset(stage.mutates or ()))
            if verdict == dedupmod.UNSEALED:
                return quick("error", cat="index_unsealed")
            if verdict == dedupmod.CLAIMED:
                return quick("claimed", cat="claimed")
            if verdict == dedupmod.VERIFIED:
                return quick("dedup")
            if verdict == dedupmod.MISSING:
                sel_hit = _sel_hit(env["sel"], cell)
                if not oracle.regen_allowed(
                        k_idc, k_arm, k_var, env["allow_regen"], sel_hit,
                        env["max_cost"], env["yes"]):
                    return quick("reject", cat="regen_gate")
                _note(env, f"regen authorized for {idc}/{arm}/{variant} "
                           f"(tombstoned bytes, sel hit)", level="warn")
            # absent (or regen-authorized missing): budget fuse
            try:
                env["factory"].meter.check(env["max_cost"])
            except paidmod.BudgetExceeded as exc:
                return quick("reject", cat="budget",
                             errors=[{"cat": "budget", "msg": str(exc)}])

        # 4. needs evaluation — domain = this run ∪ spec.foreign_runs
        verdict, payload = _needs_eval(rd, spec, idx, cell, safe)
        if verdict == "skip":
            return quick("skip",
                         errors=[{"cat": "needs", "msg": payload}])
        if verdict == "fault":
            return quick("fault", cat="upstream-lost")
        upstream_rec = payload

        # 5. PAUSE — retriable hold, PAID cells only (Phase 3 rescope: the
        #    fence stops spend, not free work — the migration runs under it)
        if stage is not None and stage.paid and locks.pause_engaged():
            return quick("error", cat="pause")

        # 6. paid: AUTH_DEAD + claim mutex (NB — the oracle just probed
        #    'absent'; a live racer wins the claim, we degrade to claimed)
        lease = None
        claim_acquired = False
        if stage is not None and stage.paid:
            if locks.auth_dead():
                return quick("error", cat="auth_dead")
            k_idc, k_arm, k_var = spec.dedup_key_of(stage, cell)
            lease = claims.ClaimLease(k_idc, arm=k_arm, variant=k_var)
            if not lease.acquire(blocking=False):
                return quick("claimed", cat="claimed")
            claim_acquired = True
            _stack.callback(lease.release)

        # 7. fp_input chain + attempt count + claim-acquire + cell_started
        if upstream_rec is not None and not cell.get("fp_input"):
            cell = dict(cell)
            cell["fp_input"] = upstream_rec.get("fp") or (
                f"{cell['stage']}@{upstream_rec['run']}#"
                f"{upstream_rec['seq']}")
        try:
            fp = cell_fp(spec, cell)
        except Exception:
            fp = None
        n_prior = idx.conn.execute(
            "SELECT COUNT(*) c FROM records WHERE idc=? AND arm=? AND up=?"
            " AND variant=? AND stage=?",
            (idc, arm, up, variant, stage_name)).fetchone()["c"]
        pre = []
        if claim_acquired:
            pre.append(events.make_event(
                events.T_CLAIM, run=rd.run, seq=alloc(), id=cell["id"],
                idc=k_idc, arm=k_arm, variant=k_var, op="acquire"))
        pre.append(events.make_event(
            events.T_CELL_STARTED, run=rd.run, seq=alloc(), id=cell["id"],
            idc=idc, arm=arm, up=up, variant=variant, stage=stage_name,
            attempt=n_prior + 1))
        _emit_batch(env, idx, pre)

        # 8. the stage fn — outbox rows fold into the terminal batch
        ctx = Ctx(rd, cell, idx, spec, alloc=alloc, factory=(
            env["factory"] if stage is not None and stage.paid else None))
        if lease is not None:
            ctx.claim_lease = lease
        t0 = time.monotonic()
        status, result, exc_errors = None, {}, []
        try:
            out = stage.fn(ctx) if stage is not None else None
            if isinstance(out, dict):
                result = dict(out)
                status = result.pop("status", "ok")
            elif out is None:
                status = "ok"
            else:
                status = str(out)
        except paidmod.PaidAbortCell as exc:
            status = "fail"
            exc_errors = [{"cat": "auth_dead", "msg": str(exc)}]
        except paidmod.PaidAbortRun as exc:
            env["abort"].set()
            status = "error"
            exc_errors = [{"cat": "auth_dead", "msg": str(exc)}]
        except paidmod.PaidPause as exc:
            status = "error"
            exc_errors = [{"cat": "pause", "msg": str(exc)}]
        except paidmod.BudgetExceeded as exc:
            status = "reject"
            exc_errors = [{"cat": "budget", "msg": str(exc)}]
        except paidmod.AuthError as exc:
            status = "error"
            exc_errors = [{"cat": "auth_dead", "msg": str(exc)}]
        except Exception as exc:  # noqa: BLE001 - cell isolation
            status = "error"
            exc_errors = [{"cat": "exception",
                           "msg": f"{type(exc).__name__}: {exc}"}]
        dur_s = round(time.monotonic() - t0, 4)

        # status_class classification (§3.1 mandatory) — unclassified
        # lands 'fault' + a loud note, never a silent retry
        cat = None
        errors = exc_errors
        auth_tripped = False
        sc = (stage.status_class or {}) if stage is not None else {}
        cls = sc.get(status)
        if cls is None:
            errors = (errors or []) + [{
                "cat": "unclassified",
                "msg": f"status {status!r} not in status_class"}]
            _note(env, f"{idc}/{stage_name}: unclassified status "
                       f"{status!r} -> fault", level="warn")
            status = "fault"
        elif cls == "upstream":
            errors = (errors or []) + [{"cat": "upstream",
                                        "msg": f"status {status!r}"}]
        for e in exc_errors:
            if e.get("cat") in events.CATS:
                cat = e["cat"]
                if cat == "auth_dead":
                    auth_tripped = True
                break

        # 9. harvest — the LAST mutating stage's done-status terminal
        #    secures bytes into the vault BEFORE the terminal emit (§3.5)
        _harvest_last_mutating(env, idx, cell, stage_name, status, alloc)

        # 10. ONE emit_batch: terminal + outbox + claim-release (§3.2 —
        #     a torn row can never exist)
        extra = {}
        if auth_tripped:
            extra["auth_tripped"] = True
        ev = _terminal_ev(env, cell, status, seq=alloc(), cat=cat,
                          dur_s=dur_s, fp=fp, errors=errors or None,
                          metrics=result.get("metrics"),
                          sig=result.get("sig"), code=result.get("code"),
                          extra=extra)
        batch = [ev]
        # the fn's own return dict is the FIRST outbox row — its errors /
        # sig / extra keys fold through the same merge path as emit() rows
        # (identity keys drop, scalars last-win, unknown keys -> metrics);
        # metrics/sig/code were already applied above and re-apply as
        # no-ops. Without this a returned {"errors": [...]} silently dies.
        merge_rows = [result, *ctx._outbox]
        if ctx._caches:
            # §3.9 metrics lane — probe/store counters ride the terminal
            merge_rows.append(
                {"metrics": {"cache": cachemod.metrics_of(ctx._caches)}})
        for ob in _merge_outbox(ev, merge_rows):
            if "seq" not in ob or ob.get("seq") is None:
                ob["seq"] = alloc()
            ob.setdefault("run", rd.run)
            batch.append(ob)
        # outbox errors fold into the terminal AFTER _terminal_ev ran —
        # re-synthesize sig when the merge introduced the first error row
        if ev.get("sig") is None and ev.get("errors"):
            ev["sig"] = _synth_sig(ev["errors"])
        if claim_acquired:
            fate = ctx.claim_fate or (
                "verified" if status in ("ok", "partial", "clean")
                else "failed" if status in events.STATUS_DONE
                else "suspended")
            batch.append(events.make_event(
                events.T_CLAIM, run=rd.run, seq=alloc(), id=cell["id"],
                idc=k_idc, arm=k_arm, variant=k_var, op="release",
                fate=fate))
        _emit_batch(env, idx, batch)
        # CaseSink file lane: the batch's case events mirror into
        # cases.jsonl AFTER the ledger commit (ledger is truth; the file
        # is the per-run derived artifact and rebuildable from events).
        for bev in batch:
            if bev.get("type") == events.T_CASE:
                try:
                    runs.add_case(rd, bev)
                except OSError as exc:
                    _note(env, f"cases.jsonl append failed for "
                               f"{idc}/{stage_name}: {exc}", level="warn")
        # Segment-cache flush (§3.9): buffered stores land ONLY on a
        # flush-worthy terminal — failed/crashed cells' segments never
        # reach the shared buckets. Ledger-first ordering: the verdict
        # row already committed; a flush failure is a note, not an error.
        for _sc in ctx._caches:
            try:
                if status in cachemod.FLUSH_STATUSES:
                    _sc.flush()
                else:
                    _sc.discard()
            except OSError as exc:
                _note(env, f"seg-cache flush failed for "
                           f"{idc}/{stage_name}: {exc}", level="warn")
        if lease is not None:
            lease.release()
        if ctx.claim_lease is not None:
            # a session-owned lease (stage fn acquired via ctx.gateway()
            # outside the kernel's own claim path) unwinds here too —
            # mid-cell release would open an 'absent'-verdict re-burn
            # window before the terminal row lands; idempotent on the
            # kernel's own lease
            ctx.claim_lease.release()
        env["emit"](f"[{status}] {idc} {arm}/{up}/{variant}/{stage_name}")
        return {"cell": key, "status": status, "cat": cat}


# --- run pipeline ------------------------------------------------------------------------


def _resolve_spec(spec_or_path):
    if isinstance(spec_or_path, Spec):
        spec = spec_or_path
    elif isinstance(spec_or_path, dict):
        raise SpecError(["dict is not a Spec — author Spec(...) objects"])
    else:
        spec = load_spec(spec_or_path)
    problems = compile_checks(spec)
    if problems:
        raise SpecError(problems)
    return spec


def _wrap_factory(gateway_factory, max_cost):
    """Normalize the gateway_factory param -> GatewayFactory.

    Accepts a GatewayFactory (meter/max_cost honored, max_cost filled when
    unset) or a bare callable (wrapped). None stays None — the caller
    refuses when the spec needs paid."""
    if gateway_factory is None:
        return None
    if isinstance(gateway_factory, paidmod.GatewayFactory):
        if max_cost is not None:
            # the run flag is the documented fuse — it wins over a
            # pre-built factory value rather than silently diverging
            gateway_factory.max_cost = max_cost
        return gateway_factory
    if callable(gateway_factory):
        return paidmod.GatewayFactory(gateway_factory, None,
                                      max_cost=max_cost)
    raise TypeError(
        f"gateway_factory must be a GatewayFactory or callable, got "
        f"{type(gateway_factory).__name__}")


def run(spec_or_path, params=None, *, date=None, slug=None, resume=False,
        replan=False, max_cost=None, regen=False, sel=None, yes=False,
        allow_regen=False, gateway_factory=None, jobs=4, emit=print) -> dict:
    """The run pipeline (§2.1). Returns a report dict."""
    paths.ensure_layout()
    t_start = time.time()

    # 1. spec + params — refused before ANY side effect
    spec = _resolve_spec(spec_or_path)
    resolved = _coerce_params(spec, params)
    if gateway_factory is None:
        # the spec may carry its own gateway (the only way a paid spec is
        # runnable from `bench run` — cli never injects one)
        gateway_factory = getattr(spec, "gateway_factory", None)
    if jobs is None:
        jobs = 4
    if spec.has_paid():
        if max_cost is None:
            raise RunError(
                "paid spec refuses to run without --max-cost (§3.6 cost "
                "fuse is mandatory, not advisory)")
        if gateway_factory is None:
            raise RunError(
                "paid spec refuses to run without a gateway_factory "
                "(client construction IS the paid assertion)")
    factory = _wrap_factory(gateway_factory, max_cost)
    if spec.has_paid() and factory is not None and not factory.meter.prices \
            and not any(getattr(s, "cost_hook", None)
                        for s in spec.stages if s.paid):
        raise RunError(
            "paid spec has no pricing surface: meter.prices is empty and "
            "no paid stage declares cost_hook — every request would "
            "account $0 and the mandatory --max-cost fuse could never "
            "bind (§3.6)")
    # executor='process' is declared in the vocabulary but not wired: the
    # submitted callable must cross a pickle boundary (env holds
    # thread-local Index/Oracle/factory — none picklable) and the cost
    # meter/abort flag are process-local. Refuse loudly rather than dying
    # on a pickle error mid-pipeline. Free CPU-bound stages can still run
    # per-stage executor='thread' (parse shells out — the GIL is not its
    # bottleneck).
    for _st in spec.stages:
        if (_st.executor or spec.executor) == "process":
            raise RunError(
                "executor='process' is not wired yet (env/alloc/meter "
                "cannot cross the pickle boundary) — use 'thread' or "
                "'async-owned' for now")

    # 2. items + canon (eval specs run verbatim — no registry gate)
    registry = None if spec.eval else idnorm.PapersRegistry.load()
    cells, problems = _enumerate_cells(spec, registry, resolved)
    if not cells:
        # R28: an empty plan is a loud warn, not a crash
        emit("plan is empty — nothing to run")

    # 3. run materialization
    spec_dict = spec.to_dict()
    spec_dict["resolved_params"] = resolved
    shash = specmod.spec_hash(spec)
    if resume:
        if date is None or slug is None:
            raise RunError("resume needs explicit date+slug (the run "
                           "identity is the triple, never inferred)")
        rd = runs.load_run(spec.kind, date, slug)
    else:
        rd = runs.create_run(spec.kind, slug=slug, date=date,
                             spec_dict=spec_dict, spec_hash=shash,
                             spec_env=_spec_env(spec))

    # 4-8 under kernel-active + run.lock
    env = {
        "rd": rd, "spec": spec, "factory": factory, "max_cost": max_cost,
        "sel": sel, "allow_regen": allow_regen or regen, "yes": yes,
        "abort": threading.Event(), "emit": emit,
        "thread_local": threading.local(),
    }
    stop_hb = threading.Event()
    hb = None
    main_idx = None
    try:
        with locks.kernel_active_hold(), rd.lock(blocking=False):
            hb = threading.Thread(
                target=runs.heartbeat_loop,
                args=(rd, 15.0, stop_hb), daemon=True)
            hb.start()

            # invocation rows record runs that ACTUALLY executed — the
            # lock-loser of a concurrent same-slug resume must leave no row
            runs.add_invocation(
                rd, {"resume": resume, "replan": replan,
                     "max_cost": max_cost, "regen": regen, "sel": sel,
                     "yes": yes, "allow_regen": allow_regen, "jobs": jobs},
                spec_hash=shash, code_stamp=specmod.code_sha(spec))

            # 5. seq mint + index + oracle snapshot
            alloc = _SeqAlloc(_max_shard_seq(rd) + 1)
            env["alloc"] = alloc
            main_idx = indexmod.Index()
            main_idx.tail_ingest()
            oracle = dedupmod.DedupOracle.snapshot(
                main_idx,
                paid_stages={s.name for s in spec.stages if s.paid})
            env["oracle"] = oracle
            env["terminal_keys"] = _shard_terminal_keys(rd)

            # 4. frozen plan (verbatim on resume unless --replan)
            cells = runs.freeze_plan(rd, cells, replan=replan)

            # 4.5 first-fire gate (§6 Phase-3 首火闸): paid specs show
            #     dedup coverage + sealed index + fresh vault verify, or
            #     the paid arm refuses — evidence lands in coverage.json
            if spec.has_paid():
                try:
                    _first_fire_gate(spec, oracle, cells, rd)
                except RunError as exc:
                    _note(env, str(exc), level="warn")
                    raise

            for p in problems:
                _note(env, f"canon drop: {p}", level="warn")

            # 6. queue — one batch for cells lacking this-run terminals
            queued = []
            for c in cells:
                k = (str(c["idc"]), str(c.get("arm", "-")),
                     str(c.get("up", "-")), str(c.get("variant", "-")),
                     str(c["stage"]))
                if k in env["terminal_keys"]:
                    continue
                queued.append(events.make_event(
                    events.T_CELL_QUEUED, run=rd.run, seq=alloc(),
                    id=c["id"], idc=c["idc"], arm=c.get("arm", "-"),
                    up=c.get("up", "-"), variant=c.get("variant", "-"),
                    stage=c["stage"], needs=c.get("needs", []),
                    fp_input=c.get("fp_input")))
            _emit_batch(env, main_idx, queued)
            emit(f"run {rd.run}: {len(queued)} cells queued "
                 f"({len(cells) - len(queued)} already terminal)")

            # 6.5 lake lookahead prefetcher (§3.10.3): plan-order walk,
            #     bounded window ahead of the execution frontier; the
            #     initial burst IS the plan-time batch warm-up
            lookahead = None
            if spec.lake and spec.prefetch:
                lookahead = _Lookahead(env, spec)
                env["lookahead"] = lookahead
                lookahead.start(cells, env["terminal_keys"])

            # 7. executor pass — cells partitioned by effective executor
            by_exec: dict[str, list] = {}
            for c in cells:
                st = spec.stage(c["stage"])
                ex = (st.executor if st and st.executor else spec.executor)
                by_exec.setdefault(ex, []).append(c)
            results = []
            try:
                for ex, group in by_exec.items():
                    if env["abort"].is_set():
                        results.extend(
                            (c, {"cell": None, "status": "aborted"})
                            for c in group)
                        continue
                    results.extend(executors.execute_cells(
                        group,
                        lambda c: _run_cell(env, c),
                        executor=ex, jobs=jobs,
                        same_id_serial=spec.same_id_serial))
            finally:
                if lookahead is not None:
                    lookahead.stop()
            env["results"] = results

            # aborted-run drain: cells the executor never reached still owe
            # the ledger a row — emit it from here (the abort flag makes
            # _run_cell short-circuit, but cells skipped at the group level
            # were never called at all)
            if env["abort"].is_set():
                done_keys = set()
                for _c, r in results:
                    if isinstance(r, dict) and isinstance(
                            r.get("cell"), tuple):
                        done_keys.add(r["cell"])
                for c in cells:
                    k = (str(c["idc"]), str(c.get("arm", "-")),
                         str(c.get("up", "-")), str(c.get("variant", "-")),
                         str(c["stage"]))
                    if k in done_keys or k in env["terminal_keys"]:
                        continue
                    _emit(env, main_idx, _terminal_ev(
                        env, c, "error", seq=alloc(), cat="auth_dead"))

            # 8. reconcile — this run's pending vault metas -> verdicts
            _reconcile_pending(env, main_idx)

            acct = runs.accounting_check(rd)
            counts = _tally(env)
            finished = events.make_event(
                events.T_FINISHED, run=rd.run, seq=alloc(),
                wall_s=round(time.time() - t_start, 3), counts=counts,
                cost_usd=round(factory.meter.spent(), 6)
                if factory is not None else 0.0,
                accounting_ok=acct["ok"])
            _emit(env, main_idx, finished)
            if not acct["ok"]:
                _note(env, f"accounting equation failed: "
                           f"missing={len(acct['missing_terminal'])} "
                           f"extra_queued={len(acct['extra_queued'])} "
                           f"dup={len(acct['dup_terminal'])} "
                           f"extra_term={len(acct['extra_terminal'])}",
                      level="warn")
            emit(f"run {rd.run} finished: {counts} "
                 f"accounting={'ok' if acct['ok'] else 'BROKEN'}")
            return {
                "ok": bool(acct["ok"]) and not env["abort"].is_set(),
                "run": rd.run, "run_seq": rd.run_seq, "kind": spec.kind,
                "date": rd.date, "slug": rd.slug, "spec_hash": shash,
                "counts": counts, "accounting": acct,
                "cost_usd": factory.meter.spent() if factory else 0.0,
                "cells": len(cells),
            }
    except locks.WouldBlock as exc:
        raise RunError(f"run dir {rd.path} is locked by another runner "
                       f"({exc})") from exc
    finally:
        stop_hb.set()
        if hb is not None:
            hb.join(timeout=5)
        if main_idx is not None:
            main_idx.close()


def _tally(env) -> dict:
    counts: dict[str, int] = {}
    for _cell, r in env.get("results", []):
        if isinstance(r, dict):
            s = str(r.get("status", "?"))
        elif isinstance(r, BaseException):
            s = "executor-error"
        else:
            s = "?"
        counts[s] = counts.get(s, 0) + 1
    return counts


def _reconcile_pending(env, idx):
    """Run-end vault reconcile (§3.5): this run's pending metas promote by
    the cell's verdict — clean statuses -> primary, fail-only -> quar,
    else alt. Missing bytes -> tombstone pending_abort. All verdict
    evidence comes from the index (this run's terminal rows)."""
    rd = env["rd"]
    spec = env["spec"]
    for meta in vault.pending_metas():
        if meta.get("source_run") != rd.run:
            continue
        idc, arm, variant = meta["idc"], meta["arm"], meta["variant"]
        altseq = meta.get("altseq", "0")
        try:
            zone, verdict = _verdict_for(idx, spec, idc, arm, variant)
            if verdict == "pending_abort":
                for k in spec.mutating_kinds() or ("zh",):
                    vault.tombstone(idc, arm, variant, k,
                                    "pending_abort", lost_run=rd.run,
                                    sink=idx.apply_event, run_dir=rd.path)
            else:
                vault.promote(idc, arm, variant, altseq, zone, verdict,
                              source_run=rd.run, sink=idx.apply_event,
                              run_dir=rd.path)
        except Exception as exc:  # noqa: BLE001 - reconcile must not crash
            _note(env, f"reconcile failed for {idc}/{arm}/{variant}@"
                       f"{altseq}: {type(exc).__name__}: {exc}",
                  level="warn")


def _verdict_for(idx, spec, idc, arm, variant):
    """pending meta verdict from this run's cell rows (§3.5 reconcile):
    any clean-class -> (primary, primary); fail-class only -> (quar, quar);
    nothing parseable -> pending_abort; else (primary, alt)."""
    statuses = set()
    for r in idx.conn.execute(
            "SELECT status FROM cells WHERE idc=? AND arm=? AND variant=?",
            (idc, arm, variant)):
        statuses.add(r["status"])
    if statuses & {"ok", "partial", "clean"}:
        return ("primary", "primary")
    if statuses and statuses <= {"fail", "fault", "dirty_pdf", "reject"}:
        return ("quar", "quar")
    if not statuses:
        return ("pending", "pending_abort")
    return ("primary", "alt")


# --- plan (dry run) -----------------------------------------------------------------------


def plan(spec_or_path, params=None, *, date=None, slug=None, replan=False,
         max_cost=None, regen=False, sel=None, yes=False, allow_regen=False,
         emit=print, **kw) -> dict:
    """Dry run — pipeline steps 1-4 minus the run dir: spec checks, param
    coercion, item enumeration + canon, then the five-bucket paid quote.

    Returns {kind, spec_hash, cells, would_run, quote, sealed,
    regen_decisions, canon_dropped, ok}. cli.py prints the quote buckets.
    """
    paths.ensure_layout()
    spec = _resolve_spec(spec_or_path)
    resolved = _coerce_params(spec, params)
    registry = None if spec.eval else idnorm.PapersRegistry.load()
    cells, problems = _enumerate_cells(spec, registry, resolved)

    idx = indexmod.Index()
    try:
        idx.tail_ingest()
        oracle = dedupmod.DedupOracle.snapshot(
            idx, paid_stages={s.name for s in spec.stages if s.paid})
        # quote over unique paid-cell keys — the oracle's unit of account
        # is (idc,arm,variant), not the full cell tuple. need_kinds is the
        # spec-level union of paid mutates: the key IS the paid domain, so
        # every key carries the full paid-product requirement.
        paid_kinds = frozenset(
            k for s in spec.stages if s.paid for k in (s.mutates or ()))
        seen = set()
        qcells = []
        for c in cells:
            st = spec.stage(c["stage"])
            # The oracle's unit of account is the cell's CLAIM key —
            # dedup_key_of, not the raw cell triple (eval specs claim on
            # a remapped keyspace; quoting cell keys would misquote them).
            k = (spec.dedup_key_of(st, c) if st is not None
                 else (c["idc"], c.get("arm", "-"), c.get("variant", "-")))
            if k in seen:
                continue
            seen.add(k)
            qcells.append({"idc": k[0], "arm": k[1], "variant": k[2],
                           "stage_paid": bool(st and st.paid),
                           "need_kinds": paid_kinds})
        quote = oracle.quote(qcells)
    finally:
        idx.close()

    would_run = quote["new"]
    regen_hits = [k for k in quote["regen_decisions"]
                  if _sel_hit(sel, {"idc": k[0], "arm": k[1],
                                    "variant": k[2]})]
    emit(f"plan {spec.kind}: {len(cells)} cells "
         f"new={quote['new']} reuse={quote['reuse']} "
         f"missing={quote['missing']} claimed={quote['claimed']} "
         f"attempted={quote['attempted']} unsealed={quote['unsealed']}")
    return {
        "ok": True,
        "kind": spec.kind, "spec_hash": specmod.spec_hash(spec),
        "cells": cells, "would_run": would_run,
        "quote": quote, "sealed": quote["sealed"],
        "regen_decisions": quote["regen_decisions"],
        "regen_sel_hits": regen_hits,
        "canon_dropped": problems,
    }
