"""Paid gateway factory + auth breaker + cost meter (design §3.6, §3.10.6).

The paid four-piece, enforced structurally:

1. ``GatewayFactory`` — the SOLE client construction point. A paid cell can
   only reach the gateway through a PaidSession minted here; construction
   of the factory registers the token accountant and (lazily) the client.
   No factory → no gateway → no paid burn, ever.
2. Claim mutex — ``PaidSession.request`` acquires the (idc,arm,variant)
   ClaimLease before touching the wire; the kernel releases it after
   harvest/meta verification (fate=verified|failed|suspended|auth_trip).
3. Per-request slots — every single request runs inside
   ``locks.paid_slot`` (≤4 flock files, global across processes).
4. Cost fuse — ``CostMeter.check(max_cost)`` before every request;
   ``--max-cost`` refusal for paid runs lives in kernel.run.

Auth breaker (§3.10.6):
- per-paper ≥3×401 → release claim with fate 'auth_trip' + PaidAbortCell
- run-wide ≥2 all_failed papers → trip the AUTH_DEAD sentinel + PaidAbortRun
- ``AUTH_DEAD`` is checked before EVERY request and before probe_model.

PAUSE is checked before every request too — a paused run holds cells, it
never half-burns a request.
"""
from __future__ import annotations

import contextlib
import math
import threading

from kernel import claims, events, ledger, locks

__all__ = [
    "AuthError",
    "BudgetExceeded",
    "CostMeter",
    "GatewayFactory",
    "PaidAbortCell",
    "PaidAbortRun",
    "PaidPause",
    "PaidSession",
    "is_auth_error",
]


# --- exceptions ---------------------------------------------------------------------


class PaidPause(Exception):
    """PAUSE sentinel engaged — retriable hold, no request was sent."""


class PaidAbortCell(Exception):
    """Per-paper auth breaker tripped (≥3×401 on this idc) — abort the cell."""


class PaidAbortRun(Exception):
    """Run-wide auth breaker / AUTH_DEAD sentinel — abort the whole run."""


class BudgetExceeded(Exception):
    """spent + estimate_next would cross max_cost — refuse before burning."""


class AuthError(Exception):
    """A counted 401 below the per-paper fuse — the cell may retry later."""

    def __init__(self, msg, status: int = 401):
        super().__init__(msg)
        self.status = status


def is_auth_error(exc: BaseException) -> bool:
    """Detect a 401-shaped client exception without importing its class."""
    for attr in ("status", "status_code", "code", "errno"):
        if getattr(exc, attr, None) == 401:
            return True
    resp = getattr(exc, "response", None)
    return resp is not None and getattr(resp, "status_code", None) == 401


# --- usage / pricing -----------------------------------------------------------------


def _usage_of(res):
    """Pull a {in,out,total}_tok usage dict out of a client response.

    Accepts dicts ({"usage": {...}} or flat), objects with .usage, and
    stage_xlat-style usage payloads ({prompt_tokens, completion_tokens}).
    Returns None when the response carries no accounting data — the
    request is still metered as a zero-cost sample.
    """
    u = None
    if isinstance(res, dict):
        u = res.get("usage") or (res if any(
            k in res for k in (
                "in_tok", "out_tok", "input_tokens", "output_tokens",
                "prompt_tokens", "completion_tokens")) else None)
    if u is None:
        u = getattr(res, "usage", None)
    if u is None:
        return None
    get = (u.get if isinstance(u, dict)
           else lambda k, d=None: getattr(u, k, d))

    def pick(*names):
        for n in names:
            v = get(n)
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    continue
        return 0

    return {
        "in_tok": pick("in_tok", "input_tokens", "prompt_tokens",
                       "promptTokens"),
        "out_tok": pick("out_tok", "output_tokens", "completion_tokens",
                        "completionTokens"),
        "total": pick("total_tokens", "total", "totalTokens"),
        "model": get("model"),
    }


class CostMeter:
    """Token accountant (§3.6③). Construction registers the accountant —
    every PaidSession feeds usage here.

    ``prices`` shapes accepted:
      flat: {"in": usd_per_tok, "out": usd_per_tok}
      per-mtok: {"in_per_mtok": x, "out_per_mtok": y}
      per-model: {"model-a": {<either of the above>}, "*": {fallback}}
    """

    def __init__(self, prices=None):
        self.prices = dict(prices or {})
        self._lock = threading.Lock()
        self._spent = 0.0
        self._samples: list[float] = []
        self._requests = 0

    # -- pricing --------------------------------------------------------------------
    def _price_row(self, model) -> dict:
        p = self.prices
        if model is not None and isinstance(p.get(model), dict):
            return p[model]
        if isinstance(p.get("*"), dict):
            return p["*"]
        return p

    def usd_for(self, usage, model=None) -> float:
        if usage is None:
            return 0.0
        if isinstance(usage, (int, float)):
            return float(usage)  # pre-priced cost hook output
        row = self._price_row(model or usage.get("model"))
        in_tok = int(usage.get("in_tok") or 0)
        out_tok = int(usage.get("out_tok") or 0)
        if "in_per_mtok" in row or "out_per_mtok" in row:
            return (in_tok * float(row.get("in_per_mtok", 0.0))
                    + out_tok * float(row.get("out_per_mtok", 0.0))) / 1e6
        return (in_tok * float(row.get("in", 0.0))
                + out_tok * float(row.get("out", 0.0)))

    def record(self, usage=None, usd=None, model=None) -> float:
        """Register one request's spend; returns the usd charged."""
        if usd is None:
            usd = self.usd_for(usage, model=model)
        usd = float(usd)
        with self._lock:
            self._spent += usd
            self._samples.append(usd)
            self._requests += 1
        return usd

    def count(self) -> None:
        """Register a non-priced wire call (probe) — requests++ only.
        Recording a fake $0 sample would drag estimate_next down."""
        with self._lock:
            self._requests += 1

    # -- fuse ------------------------------------------------------------------------
    def spent(self) -> float:
        with self._lock:
            return self._spent

    def requests(self) -> int:
        with self._lock:
            return self._requests

    def estimate_next(self) -> float:
        """mu + 2*sigma over observed per-request costs (0 when cold)."""
        with self._lock:
            if not self._samples:
                return 0.0
            mu = sum(self._samples) / len(self._samples)
            if len(self._samples) < 2:
                return mu * 2  # cold-start: pessimistic double
            var = sum((s - mu) ** 2 for s in self._samples) / (
                len(self._samples) - 1)
            return mu + 2.0 * math.sqrt(var)

    def check(self, max_cost):
        """Raise BudgetExceeded when spent + estimate_next() crosses max_cost."""
        if max_cost is None:
            return
        if self.spent() >= float(max_cost):
            msg = (
                f"cost fuse: spent {self.spent():.4f} >= max_cost "
                f"{max_cost}"
            )
            raise BudgetExceeded(msg)
        if self.spent() + self.estimate_next() > float(max_cost):
            msg = (
                f"cost fuse: spent {self.spent():.4f} + estimate_next "
                f"{self.estimate_next():.4f} > max_cost {max_cost}"
            )
            raise BudgetExceeded(msg)


# --- factory / session -----------------------------------------------------------------


class GatewayFactory:
    """The sole paid-client construction point (§3.6③).

    ``factory_fn()`` builds the raw client (lazy — first session/request
    constructs it; construction IS the paid assertion). ``ctx`` carries the
    run/cell context the accountant binds to; ``prices`` feeds the meter.

    ``shared`` holds run-wide breaker state so every session minted off
    this factory sees the same per-paper 401 counts.
    """

    def __init__(self, factory_fn, ctx=None, *, prices=None, meter=None,
                 nslots: int = 4, max_cost=None):
        if not callable(factory_fn):
            msg = "GatewayFactory needs a callable factory_fn"
            raise TypeError(msg)
        self.factory_fn = factory_fn
        self.ctx = ctx
        self.meter = meter if meter is not None else CostMeter(prices)
        self.nslots = int(nslots)
        self.max_cost = max_cost
        self._client_obj = None
        self._client_lock = threading.Lock()
        self.shared = {"paper_auth": {}, "all_failed": 0, "aborted": False}
        self._shared_lock = threading.Lock()

    def _client(self):
        """Lazy client construction — AUTH_DEAD gates even construction.
        Private: the raw client must never be reachable from stage code —
        session.request() is the only wire path."""
        if locks.auth_dead():
            msg = "AUTH_DEAD sentinel engaged"
            raise PaidAbortRun(msg)
        with self._client_lock:
            if self._client_obj is None:
                self._client_obj = (
                    self.factory_fn(self.ctx) if self._wants_ctx()
                    else self.factory_fn())
        return self._client_obj

    def _wants_ctx(self) -> bool:
        try:
            import inspect
            sig = inspect.signature(self.factory_fn)
            return len([
                p for p in sig.parameters.values()
                if p.default is p.empty
                and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
            ]) >= 1
        except (TypeError, ValueError):
            return False

    def session(self, ctx) -> PaidSession:
        """Mint a per-cell session bound to this cell's claim key."""
        return PaidSession(self, ctx)

    def bump_auth(self, idc: str) -> tuple[int, int]:
        """Count one 401 for idc; returns (paper_count, all_failed)."""
        with self._shared_lock:
            n = self.shared["paper_auth"].get(idc, 0) + 1
            self.shared["paper_auth"][idc] = n
            return n, self.shared["all_failed"]

    def fail_paper(self, idc: str) -> int:
        """Mark a paper all-failed; returns the DISTINCT failed-paper
        count — a paper re-hitting its 401 limit must not re-increment
        (the run fuse counts failed papers, not 401 bursts)."""
        with self._shared_lock:
            failed = self.shared.setdefault("failed_papers", set())
            if idc not in failed:
                failed.add(idc)
                self.shared["all_failed"] += 1
            return self.shared["all_failed"]

    def abort(self):
        with self._shared_lock:
            self.shared["aborted"] = True

    def aborted(self) -> bool:
        with self._shared_lock:
            return self.shared["aborted"]


class PaidSession:
    """Per-cell paid channel. request() is the ONLY wire path:

    PAUSE → AUTH_DEAD → abort flag → budget fuse → claim acquire →
    paid_slot → client call → usage accounting → 401 breaker.
    """

    # per-paper and run-wide fuses (§3.10.6)
    PAPER_401_LIMIT = 3
    RUN_ALL_FAILED_LIMIT = 2

    def __init__(self, factory: GatewayFactory, ctx):
        self.factory = factory
        self.ctx = ctx
        self._lease = None
        self._client_obj = None

    # -- internals --------------------------------------------------------------------
    def _key(self) -> tuple:
        return (str(getattr(self.ctx, "idc", "-")),
                str(getattr(self.ctx, "arm", "-")),
                str(getattr(self.ctx, "variant", "-")))

    def claim(self):
        """Acquire (idempotently) the claim mutex for this cell key.

        Blocking — §3.10.6 takes the lease just before the first request
        and holds it until harvest/meta verification. When the kernel
        already holds a lease for this cell it is REUSED (a second flock
        on the same file would deadlock the cell); the session publishes
        its own lease back onto the ctx so the release-audit event sees
        one lease either way. Returns the lease.
        """
        existing = getattr(self.ctx, "claim_lease", None)
        if existing is not None and existing.held:
            # the kernel's lease or our own re-read back off the ctx —
            # either way it releases at cell end, not via this session
            self._lease = existing
            return existing
        if self._lease is None or not self._lease.held:
            idc, arm, variant = self._key()
            self._lease = claims.ClaimLease(idc, arm=arm, variant=variant)
            self._lease.acquire(blocking=True)
            with contextlib.suppress(AttributeError):
                self.ctx.claim_lease = self._lease
        return self._lease

    def release_claim(self, fate: str | None = None):
        """Drop the claim mutex (idempotent). ``fate`` is recorded on the
        ctx for the kernel's claim-release audit event."""
        self._mark_fate(fate)
        if self._lease is not None:
            self._lease.release()

    def _mark_fate(self, fate: str | None):
        if fate:
            with contextlib.suppress(AttributeError):
                self.ctx.claim_fate = fate

    def _trip_claim(self):
        """Auth-trip bookkeeping: mark the release-audit fate. The lease
        is NEVER dropped here — releasing mid-cell opens an
        'absent'-verdict re-burn window (a rival oracle sees free claim +
        no durable evidence until the terminal row lands). The kernel
        releases ctx.claim_lease after the terminal emit; a bare-session
        caller drops it via release_claim() at their own cell boundary."""
        self._mark_fate("auth_trip")

    def _client(self):
        """Raw client — session-internal. The ONLY wire path stage code
        may touch is request(); a public accessor would bypass the
        claim/slot/PAUSE/meter gates."""
        if self._client_obj is None:
            self._client_obj = self.factory._client()
        return self._client_obj

    def probe_model(self):
        """Cheap liveness probe — AUTH_DEAD is checked FIRST (a dead-auth
        probe would hang the gateway bridge; §3.10.6). Still a wire call:
        it rides the global paid_slot and counts on the meter — an
        uncounted probe would let a probing fleet exceed the concurrency
        ceiling and hide traffic from the cost ledger."""
        if locks.auth_dead():
            msg = "AUTH_DEAD sentinel engaged"
            raise PaidAbortRun(msg)
        if self.factory.aborted():
            msg = "run aborted by auth breaker"
            raise PaidAbortRun(msg)
        cli = self._client()
        probe = getattr(cli, "probe_model", None)
        if not callable(probe):
            return True
        with locks.paid_slot(nslots=self.factory.nslots) as _slot:
            self._slot_ev("acquire", _slot)
            try:
                res = probe()
            finally:
                self._slot_ev("release", _slot)
        self.factory.meter.count()
        return res

    def _slot_ev(self, op: str, slot: int) -> None:
        """Mirror one paid-slot take/drop into the ledger (§3.10 Q3 —
        the index paid_slots table is the OBSERVATIONAL mirror sweep
        reconciles; the flock is the lock, the row is the audit).
        Emitted in real time — not via the terminal outbox — so a crash
        leaves a dangling row the reaper cleans rather than nothing.
        Observational only: every failure is swallowed; the wire path
        never dies for a mirror row."""
        try:
            ctx = self.ctx
            alloc = getattr(ctx, "_alloc", None)
            if callable(alloc):
                seq = alloc()
            else:
                rd = getattr(ctx, "rundir", None)
                seq = None
                if rd is not None:
                    from kernel import runs as _runs
                    seq = _runs._kernel_seq(rd)
            idc, arm, variant = self._key()
            ev = events.make_event(
                events.T_CLAIM,
                run=getattr(ctx, "run", None),
                seq=seq, id=getattr(ctx, "id", None),
                idc=idc, arm=arm, variant=variant, op=op, slot=slot)
            rd = getattr(ctx, "rundir", None)
            sink = getattr(getattr(ctx, "index", None), "apply_event", None)
            ledger.emit(ev,
                        run_dir=rd.path if rd is not None else None,
                        sink=sink)
        except Exception:  # noqa: S110 -- docstring 声明观测镜像失败全吞咽
            pass

    # -- the wire ----------------------------------------------------------------------
    def request(self, method, *a, **kw):
        """One paid request. ``method`` is a client attribute name or a
        callable taking (*a, **kw)."""
        # gates that cost nothing — checked on EVERY request
        if locks.pause_engaged():
            msg = "PAUSE sentinel engaged"
            raise PaidPause(msg)
        if locks.auth_dead():
            self.factory.abort()
            msg = "AUTH_DEAD sentinel engaged"
            raise PaidAbortRun(msg)
        if self.factory.aborted():
            msg = "run aborted by auth breaker"
            raise PaidAbortRun(msg)
        self.factory.meter.check(self.factory.max_cost)

        idc, _arm, _var = self._key()
        self.claim()
        try:
            with locks.paid_slot(nslots=self.factory.nslots) as _slot:
                self._slot_ev("acquire", _slot)
                try:
                    # re-check the free gates AFTER the blocking waits —
                    # a PAUSE/AUTH_DEAD/abort/budget trip engaged while
                    # queued must still stop the wire call (the pre-wait
                    # checks are stale by the time the slot lands)
                    if locks.pause_engaged():
                        msg = "PAUSE sentinel engaged"
                        raise PaidPause(msg)
                    if locks.auth_dead():
                        self.factory.abort()
                        msg = "AUTH_DEAD sentinel engaged"
                        raise PaidAbortRun(msg)
                    if self.factory.aborted():
                        msg = "run aborted by auth breaker"
                        raise PaidAbortRun(msg)
                    self.factory.meter.check(self.factory.max_cost)
                    res = self._call(method, *a, **kw)
                finally:
                    self._slot_ev("release", _slot)
        except PaidAbortRun:
            self._trip_claim()
            raise
        except Exception as exc:
            if is_auth_error(exc):
                n, _af = self.factory.bump_auth(idc)
                if n >= self.PAPER_401_LIMIT:
                    all_failed = self.factory.fail_paper(idc)
                    self._trip_claim()
                    if all_failed >= self.RUN_ALL_FAILED_LIMIT:
                        locks.trip_auth_dead(
                            f"{all_failed} papers all_failed on 401 "
                            f"(last: {idc})")
                        self.factory.abort()
                        msg = (
                            f"auth breaker: {all_failed} papers all_failed; "
                            "AUTH_DEAD tripped"
                        )
                        raise PaidAbortRun(msg) from exc
                    msg = (
                        f"auth breaker: {idc} saw {n}x401 — cell aborted, "
                        "claim released auth_trip"
                    )
                    raise PaidAbortCell(msg) from exc
                msg = (
                    f"401 from gateway (paper {idc}, {n}/"
                    f"{self.PAPER_401_LIMIT})"
                )
                raise AuthError(msg, status=401) from exc
            raise
        # usage accounting — post-request, inside the claim
        usage = _usage_of(res)
        usd = self.factory.meter.record(
            usage, usd=self._cost_hook(usage, res))
        try:
            self.ctx.last_cost_usd = usd
            self.ctx.last_usage = usage
        except AttributeError:
            pass
        return res

    def _call(self, method, *a, **kw):
        cli = self._client()
        if callable(method):
            return method(cli, *a, **kw)
        fn = getattr(cli, method)
        return fn(*a, **kw)

    def _cost_hook(self, usage, res):
        hook = getattr(getattr(self.ctx, "stage_obj", None),
                       "cost_hook", None)
        if not callable(hook):
            return None
        try:
            return hook(usage)
        except TypeError:
            return hook(usage, res)

    # convenience — most paid verbs are POST-shaped
    def post(self, *a, **kw):
        return self.request("post", *a, **kw)
