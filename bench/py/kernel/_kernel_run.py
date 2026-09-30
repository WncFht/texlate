"""kernel._kernel_run — run/plan 编排叶 (kernel.kernel 拆分叶，§2.1 管线本体).

- ``run``/``plan``       — 管线入口与 dry-run 报价
- ``RunError``           — run 级拒绝/崩溃 (管线前或出管线)
- ``_first_fire_gate``   — §6 Phase-3 首火闸 (dedup 覆盖 + 封缄 index +
                           新鲜 vault verify 三腿; coverage.json 存证)
- ``_SeqAlloc``          — per-run 单调 seq mint (cell_queued 占低段)
- ``_max_shard_seq``/``_shard_terminal_keys`` — resume 的 shard 扫面
- ``_RunEnv``            — run() 内部执行环境 dataclass (dict bag 打字化)
- ``_wrap_factory``      — gateway_factory 归一到 GatewayFactory
- ``_tally``/``_reconcile_pending``/``_verdict_for`` — 收尾对账与
                           run 末 pending vault meta 裁决 (§3.5)

执行件 (``_run_cell``/needs/emit/lookahead/规划面) 各归其叶，本叶只
编排。门面回引名单见 ``kernel.kernel._LEAF_EXPORTS``; monkeypatch 锚
点归本叶。
"""

from __future__ import annotations

import contextlib
import itertools
import json
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from kernel import (
    dedup as dedupmod,
)
from kernel import events, executors, fsutil, idnorm, locks, paths, runs, vault
from kernel import (
    index as indexmod,
)
from kernel import (
    paid as paidmod,
)
from kernel import (
    spec as specmod,
)
from kernel._kernel_cell import _run_cell
from kernel._kernel_emit import _emit, _emit_batch, _note, _terminal_ev
from kernel._kernel_frame import (
    _coerce_params,
    _enumerate_cells,
    _resolve_spec,
    _sel_hit,
    _spec_env,
)
from kernel._kernel_lookahead import _Lookahead

if TYPE_CHECKING:
    from collections.abc import Callable

    from kernel.spec import Spec

__all__ = ["RunError", "plan", "run"]


class RunError(RuntimeError):
    """A run-level refusal/crash — raised before or out of the pipeline."""


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
    with contextlib.suppress(OSError, ValueError):
        stamp = json.loads(paths.vault_verify_stamp_path().read_text(encoding="utf-8"))
    verify_age = (
        time.time() - stamp["ts"]
        if isinstance(stamp, dict) and isinstance(stamp.get("ts"), (int, float))
        else None
    )
    verify_fresh = verify_age is not None and verify_age < _VERIFY_FRESH_S
    coverage = {
        "ts": round(time.time(), 3),
        "paid_keys": len(paid_keys),
        "quote": {
            k: quote[k]
            for k in (
                "new",
                "reuse",
                "missing",
                "claimed",
                "attempted",
                "unsealed",
                "total",
            )
        },
        "sealed": bool(quote["sealed"]),
        "verify_age_s": (round(verify_age, 1) if verify_age is not None else None),
        "verify_fresh": verify_fresh,
    }
    try:
        d = rd.derived()
        d.mkdir(parents=True, exist_ok=True)
        fsutil.atomic_write(
            d / "coverage.json",
            (
                json.dumps(coverage, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n"
            ).encode("utf-8"),
        )
    except OSError:
        pass  # evidence write is best-effort; the gate still binds
    fails = []
    if not coverage["sealed"] or coverage["quote"]["unsealed"]:
        fails.append(
            f"index unsealed (sealed={coverage['sealed']} "
            f"unsealed={coverage['quote']['unsealed']})"
        )
    if not verify_fresh:
        fails.append(
            "vault verify stale/missing "
            f"(age_s={coverage['verify_age_s']}, need <{_VERIFY_FRESH_S}s — "
            "run `bench vault verify`)"
        )
    if fails:
        raise RunError(
            "first-fire gate refused paid run: "
            + "; ".join(fails)
            + f" (coverage: {coverage['quote']})"
        )
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


# --- shard scan (resume 终态面) ----------------------------------------------------


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


# --- run pipeline ------------------------------------------------------------------------


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
        return paidmod.GatewayFactory(gateway_factory, None, max_cost=max_cost)
    msg = (
        f"gateway_factory must be a GatewayFactory or callable, got "
        f"{type(gateway_factory).__name__}"
    )
    raise TypeError(msg)


@dataclass
class _RunEnv:
    """run() 管线内部执行环境包——_emit/_note/_Lookahead/_run_cell 等
    kernel 内部件共享的料单（不跨模块、不入 wire）。

    原 dict bag ~15 个 stringly 键打字化：dict 形态下 typo 键名静默成
    新键、缺键读回 None 流过，dataclass 形态即 AttributeError 当场爆。
    三段补齐：构造即锁前 10 字段；锁内段填 alloc/oracle/terminal_keys；
    执行段填 lookahead/results。``_spec_env`` 的 probe dict 是另一物件
    （记名进 run metadata）——勿混淆。
    """

    rd: runs.RunDir
    spec: Spec
    factory: paidmod.GatewayFactory | None
    max_cost: float | None
    sel: str | None
    allow_regen: bool
    yes: bool
    abort: threading.Event
    emit: Callable[[str], None]
    thread_local: threading.local
    alloc: _SeqAlloc | None = None
    oracle: dedupmod.DedupOracle | None = None
    terminal_keys: set[tuple] = field(default_factory=set)
    lookahead: _Lookahead | None = None
    results: list = field(default_factory=list)


def run(
    spec_or_path,
    params=None,
    *,
    date=None,
    slug=None,
    resume=False,
    replan=False,
    max_cost=None,
    regen=False,
    sel=None,
    yes=False,
    allow_regen=False,
    gateway_factory=None,
    jobs=4,
    emit=print,
) -> dict:
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
            msg = (
                "paid spec refuses to run without --max-cost (§3.6 cost "
                "fuse is mandatory, not advisory)"
            )
            raise RunError(msg)
        if gateway_factory is None:
            msg = (
                "paid spec refuses to run without a gateway_factory "
                "(client construction IS the paid assertion)"
            )
            raise RunError(msg)
    factory = _wrap_factory(gateway_factory, max_cost)
    if (
        spec.has_paid()
        and factory is not None
        and not factory.meter.prices
        and not any(getattr(s, "cost_hook", None) for s in spec.stages if s.paid)
    ):
        msg = (
            "paid spec has no pricing surface: meter.prices is empty and "
            "no paid stage declares cost_hook — every request would "
            "account $0 and the mandatory --max-cost fuse could never "
            "bind (§3.6)"
        )
        raise RunError(msg)
    # executor='process' is declared in the vocabulary but not wired: the
    # submitted callable must cross a pickle boundary (env holds
    # thread-local Index/Oracle/factory — none picklable) and the cost
    # meter/abort flag are process-local. Refuse loudly rather than dying
    # on a pickle error mid-pipeline. Free CPU-bound stages can still run
    # per-stage executor='thread' (parse shells out — the GIL is not its
    # bottleneck).
    for _st in spec.stages:
        if (_st.executor or spec.executor) == "process":
            msg = (
                "executor='process' is not wired yet (env/alloc/meter "
                "cannot cross the pickle boundary) — use 'thread' or "
                "'async-owned' for now"
            )
            raise RunError(msg)

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
            msg = (
                "resume needs explicit date+slug (the run "
                "identity is the triple, never inferred)"
            )
            raise RunError(msg)
        rd = runs.load_run(spec.kind, date, slug)
    else:
        rd = runs.create_run(
            spec.kind,
            slug=slug,
            date=date,
            spec_dict=spec_dict,
            spec_hash=shash,
            spec_env=_spec_env(spec),
        )

    # 4-8 under kernel-active + run.lock
    env = _RunEnv(
        rd=rd,
        spec=spec,
        factory=factory,
        max_cost=max_cost,
        sel=sel,
        allow_regen=allow_regen or regen,
        yes=yes,
        abort=threading.Event(),
        emit=emit,
        thread_local=threading.local(),
    )
    stop_hb = threading.Event()
    hb = None
    main_idx = None
    try:
        with locks.kernel_active_hold(), rd.lock(blocking=False):
            hb = threading.Thread(
                target=runs.heartbeat_loop, args=(rd, 15.0, stop_hb), daemon=True
            )
            hb.start()

            # invocation rows record runs that ACTUALLY executed — the
            # lock-loser of a concurrent same-slug resume must leave no row
            runs.add_invocation(
                rd,
                {
                    "resume": resume,
                    "replan": replan,
                    "max_cost": max_cost,
                    "regen": regen,
                    "sel": sel,
                    "yes": yes,
                    "allow_regen": allow_regen,
                    "jobs": jobs,
                },
                spec_hash=shash,
                code_stamp=specmod.code_sha(spec),
            )

            # 5. seq mint + index + oracle snapshot
            alloc = _SeqAlloc(_max_shard_seq(rd) + 1)
            env.alloc = alloc
            main_idx = indexmod.Index()
            main_idx.tail_ingest()
            oracle = dedupmod.DedupOracle.snapshot(
                main_idx, paid_stages={s.name for s in spec.stages if s.paid}
            )
            env.oracle = oracle
            env.terminal_keys = _shard_terminal_keys(rd)

            # 4. frozen plan (verbatim on resume unless --replan)
            cells = runs.freeze_plan(rd, cells, replan=replan)

            # 4.5 first-fire gate (§6 Phase-3 首火闸): paid specs show
            #     dedup coverage + sealed index + fresh vault verify, or
            #     the paid ``arm`` refuses — evidence lands in coverage.json
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
                k = (
                    str(c["idc"]),
                    str(c.get("arm", "-")),
                    str(c.get("up", "-")),
                    str(c.get("variant", "-")),
                    str(c["stage"]),
                )
                if k in env.terminal_keys:
                    continue
                queued.append(
                    events.make_event(
                        events.T_CELL_QUEUED,
                        run=rd.run,
                        seq=alloc(),
                        id=c["id"],
                        idc=c["idc"],
                        arm=c.get("arm", "-"),
                        up=c.get("up", "-"),
                        variant=c.get("variant", "-"),
                        stage=c["stage"],
                        needs=c.get("needs", []),
                        fp_input=c.get("fp_input"),
                    )
                )
            _emit_batch(env, main_idx, queued)
            emit(
                f"run {rd.run}: {len(queued)} cells queued "
                f"({len(cells) - len(queued)} already terminal)"
            )

            # 6.5 lake lookahead prefetcher (§3.10.3): plan-order walk,
            #     bounded window ahead of the execution frontier; the
            #     initial burst IS the plan-time batch warm-up
            lookahead = None
            if spec.lake and spec.prefetch:
                lookahead = _Lookahead(env, spec)
                env.lookahead = lookahead
                lookahead.start(cells, env.terminal_keys)

            # 7. executor pass — cells partitioned by effective executor
            by_exec: dict[str, list] = {}
            for c in cells:
                st = spec.stage(c["stage"])
                ex = st.executor if st and st.executor else spec.executor
                by_exec.setdefault(ex, []).append(c)
            results = []
            try:
                for ex, group in by_exec.items():
                    if env.abort.is_set():
                        results.extend(
                            (c, {"cell": None, "status": "aborted"}) for c in group
                        )
                        continue
                    results.extend(
                        executors.execute_cells(
                            group,
                            lambda c: _run_cell(env, c),
                            executor=ex,
                            jobs=jobs,
                            same_id_serial=spec.same_id_serial,
                        )
                    )
            finally:
                if lookahead is not None:
                    lookahead.stop()
            env.results = results

            # aborted-run drain: cells the executor never reached still owe
            # the ledger a row — emit it from here (the abort flag makes
            # _run_cell short-circuit, but cells skipped at the group level
            # were never called at all)
            if env.abort.is_set():
                done_keys = set()
                for _c, r in results:
                    if isinstance(r, dict) and isinstance(r.get("cell"), tuple):
                        done_keys.add(r["cell"])
                for c in cells:
                    k = (
                        str(c["idc"]),
                        str(c.get("arm", "-")),
                        str(c.get("up", "-")),
                        str(c.get("variant", "-")),
                        str(c["stage"]),
                    )
                    if k in done_keys or k in env.terminal_keys:
                        continue
                    _emit(
                        env,
                        main_idx,
                        _terminal_ev(env, c, "error", seq=alloc(), cat="auth_dead"),
                    )

            # 8. reconcile — this run's pending vault metas -> verdicts
            _reconcile_pending(env, main_idx)

            acct = runs.accounting_check(rd)
            counts = _tally(env)
            finished = events.make_event(
                events.T_FINISHED,
                run=rd.run,
                seq=alloc(),
                wall_s=round(time.time() - t_start, 3),
                counts=counts,
                cost_usd=round(factory.meter.spent(), 6)
                if factory is not None
                else 0.0,
                accounting_ok=acct["ok"],
            )
            _emit(env, main_idx, finished)
            if not acct["ok"]:
                _note(
                    env,
                    f"accounting equation failed: "
                    f"missing={len(acct['missing_terminal'])} "
                    f"extra_queued={len(acct['extra_queued'])} "
                    f"dup={len(acct['dup_terminal'])} "
                    f"extra_term={len(acct['extra_terminal'])}",
                    level="warn",
                )
            emit(
                f"run {rd.run} finished: {counts} "
                f"accounting={'ok' if acct['ok'] else 'BROKEN'}"
            )
            return {
                "ok": bool(acct["ok"]) and not env.abort.is_set(),
                "run": rd.run,
                "run_seq": rd.run_seq,
                "kind": spec.kind,
                "date": rd.date,
                "slug": rd.slug,
                "spec_hash": shash,
                "counts": counts,
                "accounting": acct,
                "cost_usd": factory.meter.spent() if factory else 0.0,
                "cells": len(cells),
            }
    except locks.WouldBlock as exc:
        msg = f"run dir {rd.path} is locked by another runner ({exc})"
        raise RunError(msg) from exc
    finally:
        stop_hb.set()
        if hb is not None:
            hb.join(timeout=5)
        if main_idx is not None:
            main_idx.close()


def _tally(env) -> dict:
    counts: dict[str, int] = {}
    for _cell, r in env.results:
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
    rd = env.rd
    spec = env.spec
    for meta in vault.pending_metas():
        if meta.get("source_run") != rd.run:
            continue
        idc, arm, variant = meta["idc"], meta["arm"], meta["variant"]
        altseq = meta.get("altseq", "0")
        try:
            zone, verdict = _verdict_for(idx, spec, idc, arm, variant, meta=meta)
            if verdict == "pending_abort":
                for k in spec.mutating_kinds() or ("zh",):
                    vault.tombstone(
                        idc,
                        arm,
                        variant,
                        k,
                        "pending_abort",
                        lost_run=rd.run,
                        sink=idx.apply_event,
                        run_dir=rd.path,
                    )
            else:
                vault.promote(
                    idc,
                    arm,
                    variant,
                    altseq,
                    zone,
                    verdict,
                    source_run=rd.run,
                    sink=idx.apply_event,
                    run_dir=rd.path,
                )
        except Exception as exc:
            _note(
                env,
                f"reconcile failed for {idc}/{arm}/{variant}@"
                f"{altseq}: {type(exc).__name__}: {exc}",
                level="warn",
            )


def _verdict_for(idx, spec, idc, arm, variant, meta=None):
    """pending meta verdict from this run's cell rows (§3.5 reconcile):
    any clean-class -> (primary, primary); fail-class only -> (quar, quar);
    nothing parseable -> pending_abort; else (primary, alt). A clean
    verdict is capped at alt when the copy's declared splice lacks a
    product pdf (fig-only/pdf-less shells must not certify a cell)."""
    statuses = set()
    for r in idx.conn.execute(
        "SELECT status FROM cells WHERE idc=? AND arm=? AND variant=?",
        (idc, arm, variant),
    ):
        statuses.add(r["status"])
    if statuses & events.STATUS_CLEAN:
        zone, verdict = "primary", "primary"
    elif statuses and statuses <= events.STATUS_FAIL:
        zone, verdict = "quar", "quar"
    elif not statuses:
        return ("pending", "pending_abort")
    else:
        zone, verdict = "primary", "alt"
    if (
        verdict == "primary"
        and isinstance(meta, dict)
        and "splice" in (meta.get("files") or {})
        and not vault._copy_product_ok(meta, "splice")[0]
    ):
        verdict = "alt"  # 无产物 pdf 的 splice 副本不得晋 primary
    return (zone, verdict)


# --- plan (dry run) -----------------------------------------------------------------------


def plan(
    spec_or_path,
    params=None,
    *,
    date=None,
    slug=None,
    replan=False,
    max_cost=None,
    regen=False,
    sel=None,
    yes=False,
    allow_regen=False,
    emit=print,
    **kw,
) -> dict:
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
            idx, paid_stages={s.name for s in spec.stages if s.paid}
        )
        # quote over unique paid-cell keys — the oracle's unit of account
        # is (idc,arm,variant), not the full cell tuple. need_kinds is the
        # spec-level union of paid mutates: the key IS the paid domain, so
        # every key carries the full paid-product requirement.
        paid_kinds = frozenset(
            k for s in spec.stages if s.paid for k in (s.mutates or ())
        )
        seen = set()
        qcells = []
        for c in cells:
            st = spec.stage(c["stage"])
            # The oracle's unit of account is the cell's CLAIM key —
            # dedup_key_of, not the raw cell triple (eval specs claim on
            # a remapped keyspace; quoting cell keys would misquote them).
            k = (
                spec.dedup_key_of(st, c)
                if st is not None
                else (c["idc"], c.get("arm", "-"), c.get("variant", "-"))
            )
            if k in seen:
                continue
            seen.add(k)
            qcells.append(
                {
                    "idc": k[0],
                    "arm": k[1],
                    "variant": k[2],
                    "stage_paid": bool(st and st.paid),
                    "need_kinds": paid_kinds,
                }
            )
        quote = oracle.quote(qcells)
    finally:
        idx.close()

    would_run = quote["new"]
    regen_hits = [
        k
        for k in quote["regen_decisions"]
        if _sel_hit(sel, {"idc": k[0], "arm": k[1], "variant": k[2]})
    ]
    emit(
        f"plan {spec.kind}: {len(cells)} cells "
        f"new={quote['new']} reuse={quote['reuse']} "
        f"missing={quote['missing']} claimed={quote['claimed']} "
        f"attempted={quote['attempted']} unsealed={quote['unsealed']}"
    )
    return {
        "ok": True,
        "kind": spec.kind,
        "spec_hash": specmod.spec_hash(spec),
        "cells": cells,
        "would_run": would_run,
        "quote": quote,
        "sealed": quote["sealed"],
        "regen_decisions": quote["regen_decisions"],
        "regen_sel_hits": regen_hits,
        "canon_dropped": problems,
    }
