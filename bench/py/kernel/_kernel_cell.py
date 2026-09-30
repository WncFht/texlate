"""kernel._kernel_cell — cell 临界段叶 (kernel.kernel 拆分叶, §2.1/§3.6/§3.10.6).

``_run_cell`` 永不抛的单格临界段, cell_lock 内序:

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
NB-only. ``_thread_index`` 造线程本 Index/Oracle (sqlite 线程绑定);
``_harvest_last_mutating`` 是 §3.5 末 mutating 段终态收割 (quick()
拒径与 dedup 终态同样收——终态行是 work 树字节最后的托管点)。

门面回引名单见 ``kernel.kernel._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING

from kernel import (
    cache as cachemod,
)
from kernel import (
    claims,
    events,
    idnorm,
    locks,
    runs,
    vault,
)
from kernel import (
    dedup as dedupmod,
)
from kernel import (
    index as indexmod,
)
from kernel import (
    paid as paidmod,
)
from kernel._kernel_emit import (
    _emit,
    _emit_batch,
    _merge_outbox,
    _note,
    _synth_sig,
    _terminal_ev,
)
from kernel._kernel_frame import _sel_hit
from kernel._kernel_needs import _last_outcome, _needs_eval
from kernel.ctx import Ctx
from kernel.spec import cell_fp

if TYPE_CHECKING:
    from kernel.spec import Spec


def _thread_index(env):
    """Per-worker-thread Index — sqlite conns are thread-bound."""
    tl = env.thread_local
    idx = getattr(tl, "index", None)
    if idx is None:
        spec = env.spec
        eval_stages = {
            s.name for s in getattr(spec, "stages", ()) if getattr(s, "eval", False)
        } or None
        idx = indexmod.Index(eval_stages=eval_stages)
        tl.index = idx
        tl.oracle = dedupmod.DedupOracle(
            idx,
            manifest_tail=env.oracle.manifest_tail,
            paid_pool_snap=env.oracle.paid_pool_snap,
            sealed_gen=env.oracle.sealed_gen,
            min_offset=env.oracle.min_offset,
            kind_evidence=env.oracle.kind_evidence,
        )
    return tl.index, tl.oracle


def _harvest_last_mutating(env, idx, cell, stage_name, status, alloc):
    """§3.5: the LAST mutating stage's done-status terminal seals the
    cell's mutates-kind trees into the vault before the terminal row.

    Runs on every terminal path — quick() refusals included: reject is a
    done status, and a regen/budget-refused paid cell still owns upstream
    mutates products that would otherwise die in the work tree. 'dedup'
    quick-terminals harvest too: an inherited verdict says this stage's
    own work is done, but upstream stages may have run for real THIS run
    and their products sit in the work tree uncommitted — the dedup row
    is the last custody point before they are swept (2609.20519 实证:
    xlat/compile 真跑产出 zh/splice, layoutqc 撞上陈旧 declined-verdict
    dedup, 字节随 remove_cell_tree 清零, v1 键域自此永久饥饿)."""
    spec = env.spec
    if stage_name != spec.last_mutating_stage() or status not in events.STATUS_DONE | {
        "dedup"
    }:
        return
    rd = env.rd
    ctx = Ctx(rd, cell, idx, spec)
    assets = ctx.asset_dirs()
    if not assets:
        return
    idc = str(cell["idc"])
    arm = str(cell.get("arm", "-"))
    variant = str(cell.get("variant", "-"))
    try:
        vault.harvest(
            idc,
            arm,
            variant,
            assets,
            source_run=rd.run,
            id=cell["id"],
            seq=alloc,
            sink=idx.apply_event,
            run_dir=rd.path,
        )
    except Exception as exc:
        _note(
            env,
            f"harvest failed for {idc}/{arm}/{variant}: {type(exc).__name__}: {exc}",
            level="warn",
        )


def _run_cell(env, cell: dict) -> dict:
    """One plan cell through the critical section. NEVER raises — every
    path lands exactly one ledger row (terminal or retriable)."""
    rd: runs.RunDir = env.rd
    spec: Spec = env.spec
    alloc = env.alloc
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
        ev = _terminal_ev(
            env, cell, status, seq=alloc(), cat=cat, errors=errors, extra=extra
        )
        _emit(env, idx, ev)
        return {"cell": key, "status": status, "cat": cat}

    # ExitStack second so claim release unwinds INSIDE cell.lock on every
    # path — an emit failure mid-cell must not strand the lease held.
    with runs.cell_lock(rd, safe), contextlib.ExitStack() as _stack:
        # lookahead frontier bump — inside cell_lock: a cell queued on the
        # lock has not consumed its prefetched bytes yet
        la = env.lookahead
        if la is not None:
            la.cell_started(idc)

        # 0. run-level abort flag (auth breaker tripped mid-run)
        if env.abort.is_set():
            return quick("error", cat="auth_dead")

        # 1. already terminal in THIS run (resume continuation)
        if key in env.terminal_keys:
            return {"cell": key, "status": "already-terminal"}

        # 2. cross-run dedup — the last VERDICT row (records, not the
        #    queued-masked cells table) decides; DONE = work evidence.
        #    'dedup' pointer rows and 'declined:*' gate rejects are
        #    transparent to _last_outcome — a decline is conditional on
        #    the upstream state at emit time and must be re-evaluated,
        #    not inherited. 'lost'/'claimed'/'unpaid_gate' are KERNEL
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
            stage_paid
            and not stage.mutates
            and (spec.eval or getattr(stage, "eval", False))
        )
        if (
            last is not None
            and (not stage_paid or eval_paid_nobytes)
            and last["status"] in events.STATUS_DONE | {"dedup"}
        ):
            # mutates 格的 verdict-dedup 还须字节在押: DONE 行只证跑过,
            # 不证产物入 vault —— dedup 终态历史上不收 harvest, 字节
            # 也可能被 sweep/清理核销。oracle 证 ABSENT/MISSING(无在押
            # 副本, 含登记丢失) → 放行 fn 重跑自愈: 免费格 regen 零成本,
            # regen 闸护的是花费不是免费重算; verified/claimed/unsealed
            # 维持 dedup —— 在押字节、他跑竞态、未封缄不确定态不翻案。
            mut = frozenset(stage.mutates) if stage is not None else ()
            if mut and oracle is not None:
                verdict = oracle.check(
                    idc,
                    arm,
                    variant,
                    stage_paid=False,
                    need_kinds=mut,
                    stage_name=stage_name,
                )
                if verdict in (dedupmod.ABSENT, dedupmod.MISSING):
                    pass
                else:
                    return quick("dedup")
            else:
                return quick("dedup")

        # 3. paid gate — the fail-closed oracle owns every paid cell
        if stage is not None and stage.paid:
            k_idc, k_arm, k_var = spec.dedup_key_of(stage, cell)
            verdict = oracle.check(
                k_idc,
                k_arm,
                k_var,
                stage_paid=True,
                need_kinds=frozenset(stage.mutates or ()),
                stage_name=stage_name,
            )
            if verdict == dedupmod.UNSEALED:
                return quick("error", cat="index_unsealed")
            if verdict == dedupmod.CLAIMED:
                return quick("claimed", cat="claimed")
            if verdict == dedupmod.VERIFIED:
                return quick("dedup")
            if verdict == dedupmod.MISSING:
                sel_hit = _sel_hit(env.sel, cell)
                if not oracle.regen_allowed(
                    k_idc,
                    k_arm,
                    k_var,
                    env.allow_regen,
                    sel_hit,
                    env.max_cost,
                    env.yes,
                ):
                    return quick("reject", cat="regen_gate")
                _note(
                    env,
                    f"regen authorized for {idc}/{arm}/{variant} "
                    f"(tombstoned bytes, sel hit)",
                    level="warn",
                )
            # absent (or regen-authorized missing): budget fuse
            try:
                env.factory.meter.check(env.max_cost)
            except paidmod.BudgetExceeded as exc:
                return quick(
                    "reject", cat="budget", errors=[{"cat": "budget", "msg": str(exc)}]
                )

        # 4. needs evaluation — domain = this run ∪ spec.foreign_runs
        verdict, payload = _needs_eval(rd, spec, idx, cell, safe)
        if verdict == "skip":
            return quick("skip", errors=[{"cat": "needs", "msg": payload}])
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
                f"{cell['stage']}@{upstream_rec['run']}#{upstream_rec['seq']}"
            )
        try:
            fp = cell_fp(spec, cell)
        except Exception:
            fp = None
        n_prior = idx.conn.execute(
            "SELECT COUNT(*) c FROM records WHERE idc=? AND arm=? AND up=?"
            " AND variant=? AND stage=?",
            (idc, arm, up, variant, stage_name),
        ).fetchone()["c"]
        pre = []
        if claim_acquired:
            pre.append(
                events.make_event(
                    events.T_CLAIM,
                    run=rd.run,
                    seq=alloc(),
                    id=cell["id"],
                    idc=k_idc,
                    arm=k_arm,
                    variant=k_var,
                    op="acquire",
                )
            )
        pre.append(
            events.make_event(
                events.T_CELL_STARTED,
                run=rd.run,
                seq=alloc(),
                id=cell["id"],
                idc=idc,
                arm=arm,
                up=up,
                variant=variant,
                stage=stage_name,
                attempt=n_prior + 1,
            )
        )
        _emit_batch(env, idx, pre)

        # 8. the stage fn — outbox rows fold into the terminal batch
        ctx = Ctx(
            rd,
            cell,
            idx,
            spec,
            alloc=alloc,
            factory=(env.factory if stage is not None and stage.paid else None),
        )
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
            env.abort.set()
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
        except Exception as exc:
            status = "error"
            exc_errors = [{"cat": "exception", "msg": f"{type(exc).__name__}: {exc}"}]
        dur_s = round(time.monotonic() - t0, 4)

        # status_class classification (§3.1 mandatory) — unclassified
        # lands 'fault' + a loud note, never a silent retry
        cat = None
        errors = exc_errors
        auth_tripped = False
        sc = (stage.status_class or {}) if stage is not None else {}
        cls = sc.get(status)
        if cls is None:
            errors = (errors or []) + [
                {"cat": "unclassified", "msg": f"status {status!r} not in status_class"}
            ]
            _note(
                env,
                f"{idc}/{stage_name}: unclassified status {status!r} -> fault",
                level="warn",
            )
            status = "fault"
        elif cls == "upstream":
            errors = (errors or []) + [{"cat": "upstream", "msg": f"status {status!r}"}]
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
        ev = _terminal_ev(
            env,
            cell,
            status,
            seq=alloc(),
            cat=cat,
            dur_s=dur_s,
            fp=fp,
            errors=errors or None,
            metrics=result.get("metrics"),
            sig=result.get("sig"),
            code=result.get("code"),
            extra=extra,
        )
        batch = [ev]
        # the fn's own return dict is the FIRST outbox row — its errors /
        # sig / extra keys fold through the same merge path as emit() rows
        # (identity keys drop, scalars last-win, unknown keys -> metrics);
        # metrics/sig/code were already applied above and re-apply as
        # no-ops. Without this a returned {"errors": [...]} silently dies.
        merge_rows = [result, *ctx._outbox]
        if ctx._caches:
            # §3.9 metrics lane — probe/store counters ride the terminal
            merge_rows.append({"metrics": {"cache": cachemod.metrics_of(ctx._caches)}})
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
                "verified"
                if status in events.STATUS_CLEAN
                else "failed"
                if status in events.STATUS_DONE
                else "suspended"
            )
            batch.append(
                events.make_event(
                    events.T_CLAIM,
                    run=rd.run,
                    seq=alloc(),
                    id=cell["id"],
                    idc=k_idc,
                    arm=k_arm,
                    variant=k_var,
                    op="release",
                    fate=fate,
                )
            )
        _emit_batch(env, idx, batch)
        # CaseSink file lane: the batch's case events mirror into
        # cases.jsonl AFTER the ledger commit (ledger is truth; the file
        # is the per-run derived artifact and rebuildable from events).
        for bev in batch:
            if bev.get("type") == events.T_CASE:
                try:
                    runs.add_case(rd, bev)
                except OSError as exc:
                    _note(
                        env,
                        f"cases.jsonl append failed for {idc}/{stage_name}: {exc}",
                        level="warn",
                    )
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
                _note(
                    env,
                    f"seg-cache flush failed for {idc}/{stage_name}: {exc}",
                    level="warn",
                )
        if lease is not None:
            lease.release()
        if ctx.claim_lease is not None:
            # a session-owned lease (stage fn acquired via ctx.gateway()
            # outside the kernel's own claim path) unwinds here too —
            # mid-cell release would open an 'absent'-verdict re-burn
            # window before the terminal row lands; idempotent on the
            # kernel's own lease
            ctx.claim_lease.release()
        env.emit(f"[{status}] {idc} {arm}/{up}/{variant}/{stage_name}")
        return {"cell": key, "status": status, "cat": cat}
