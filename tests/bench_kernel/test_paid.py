"""Tests for kernel/paid.py — CostMeter, GatewayFactory lazy client,
PaidSession gate ordering, and the 401 auth breaker.

`broot` gives each test an isolated $TEXLATE_BENCH_ROOT so the PAUSE /
AUTH_DEAD sentinels and claim/slot lock files live in tmp space.
"""

from __future__ import annotations

import contextlib
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from kernel import claims, locks, paid, paths

if TYPE_CHECKING:
    from pathlib import Path
    from typing import ClassVar, NoReturn


class _Ctx:
    """Minimal ctx stand-in: the session only reads the claim key."""

    def __init__(
        self, idc: str = "2401.00001", arm: str = "-", variant: str = "-"
    ) -> None:
        self.idc, self.arm, self.variant = idc, arm, variant
        self.claim_lease = None
        self.claim_fate = None


def _session(
    client: object | None = None,
    ctx: _Ctx | None = None,
    **fkw: object,
) -> tuple[paid.GatewayFactory, paid.PaidSession]:
    f = paid.GatewayFactory(
        lambda _c=None: client if client is not None else object(), **fkw
    )
    return f, f.session(ctx or _Ctx())


# --- CostMeter -------------------------------------------------------------------------


def test_meter_price_table_flat_and_per_mtok() -> None:
    m = paid.CostMeter({"in": 1e-6, "out": 2e-6})
    assert m.usd_for({"in_tok": 100, "out_tok": 50}) == pytest.approx(0.0002)
    m2 = paid.CostMeter({"in_per_mtok": 1.0, "out_per_mtok": 2.0})
    assert m2.usd_for({"in_tok": 1e6, "out_tok": 1e6}) == pytest.approx(3.0)
    m3 = paid.CostMeter(
        {"model-a": {"in": 1e-6, "out": 0.0}, "*": {"in": 0.0, "out": 1e-6}}
    )
    assert m3.usd_for(
        {"in_tok": 10, "out_tok": 10, "model": "model-a"}
    ) == pytest.approx(10e-6)
    assert m3.usd_for({"in_tok": 10, "out_tok": 10, "model": "other"}) == pytest.approx(
        10e-6
    )
    assert m.usd_for(None) == 0.0


def test_meter_record_spent_estimate_next() -> None:
    m = paid.CostMeter()
    assert m.estimate_next() == 0.0
    m.record(usd=0.10)
    m.record(usd=0.20)
    assert m.spent() == pytest.approx(0.30)
    # mu=0.15, sigma=0.0707 -> est = mu + 2*sigma
    est = m.estimate_next()
    assert est == pytest.approx(0.15 + 2 * 0.0707106781)
    m.record(usd=0.10)
    assert m.requests() == 3  # noqa: PLR2004 -- 断言字面量(已录三笔请求)


def test_meter_check_fuses_before_crossing() -> None:
    m = paid.CostMeter()
    m.check(1.0)  # cold: no spend yet
    m.record(usd=0.9)
    # 0.9 + estimate(1.8) > 1.0 -> refused
    with pytest.raises(paid.BudgetExceeded):
        m.check(1.0)
    m.check(3.0)  # still affordable


# --- is_auth_error ----------------------------------------------------------------------


def test_is_auth_error_shapes() -> None:
    class StatusError(Exception):
        status = 401

    class PlainError(Exception):
        pass

    e2 = PlainError("x")
    e2.status_code = 401
    e3 = Exception("x")
    e3.code = 401
    e4 = Exception("x")
    assert paid.is_auth_error(StatusError())
    assert paid.is_auth_error(e2)
    assert paid.is_auth_error(e3)
    assert not paid.is_auth_error(e4)
    assert paid.is_auth_error(paid.AuthError("x", status=401))


# --- usage extraction ---------------------------------------------------------------------


def test_usage_of_shapes() -> None:
    assert paid._usage_of(  # noqa: SLF001 -- 钉私有面：usage 抽取无公共等价入口
        {"usage": {"in_tok": 1, "out_tok": 2}}
    ) == {
        "in_tok": 1,
        "out_tok": 2,
        "total": 0,
        "model": None,
    }
    u = paid._usage_of(  # noqa: SLF001 -- 同上
        {"prompt_tokens": 5, "completion_tokens": 7}
    )
    assert u == {"in_tok": 5, "out_tok": 7, "total": 0, "model": None}

    class R:
        usage: ClassVar[dict] = {"input_tokens": 3, "output_tokens": 4}

    assert paid._usage_of(R()) == {  # noqa: SLF001 -- 同上
        "in_tok": 3,
        "out_tok": 4,
        "total": 0,
        "model": None,
    }
    assert paid._usage_of({"no": "usage"}) is None  # noqa: SLF001 -- 同上


# --- GatewayFactory / session gates --------------------------------------------------------


def test_factory_lazy_client_and_meter(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    built = []

    def mk(_ctx: object | None = None) -> object:
        built.append(1)
        return object()

    f = paid.GatewayFactory(mk)
    assert built == []  # lazy: nothing yet
    f._client()  # noqa: SLF001 -- 钉私有面：懒构造仅此入口
    f._client()  # noqa: SLF001 -- 同上
    assert built == [1]  # built exactly once


def test_session_request_full_gate_path(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    calls = []

    class Client:
        def chat(self, x: int) -> dict:
            calls.append(x)
            return {"usage": {"in_tok": 10, "out_tok": 5}}

    f, s = _session(Client(), prices={"in": 1e-6, "out": 1e-6})
    res = s.request("chat", 42)
    assert calls == [42]
    assert res["usage"] == {"in_tok": 10, "out_tok": 5}
    assert f.meter.spent() == pytest.approx(15e-6)
    # the claim stays HELD after the request — the kernel releases it only
    # after harvest/meta verification (§3.10.6); request ≠ claim scope
    assert claims.ClaimLease("2401.00001").held_by_other()
    s.release_claim(fate="verified")
    assert not claims.ClaimLease("2401.00001").held_by_other()


def test_session_reuses_ctx_lease_no_deadlock(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    """The kernel-held claim lease must be REUSED, not double-flocked."""
    held = claims.ClaimLease("2401.00001")
    held.acquire()
    ctx = _Ctx()
    ctx.claim_lease = held

    class Client:
        def chat(self) -> dict:
            return {"usage": {}}

    _f, s = _session(Client(), ctx=ctx)
    res = s.request("chat")  # would deadlock on a 2nd flock
    assert res == {"usage": {}}
    assert s._lease is held  # noqa: SLF001 -- 钉私有面：复用断言须看内部 lease
    held.release()


def test_session_pause_blocks_before_request(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    calls = []
    _f, s = _session(type("C", (), {"chat": lambda _self: calls.append(1)}))
    paths.pause_path().touch()
    with pytest.raises(paid.PaidPause):
        s.request("chat")
    assert calls == []


def test_session_auth_dead_blocks_and_aborts(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    locks.trip_auth_dead("test")
    f, s = _session()
    with pytest.raises(paid.PaidAbortRun):
        s.request("chat")
    assert f.aborted() is True


def test_probe_model_checks_auth_dead_first(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    _f, s = _session()
    locks.trip_auth_dead("x")
    with pytest.raises(paid.PaidAbortRun):
        s.probe_model()


def test_session_budget_fuse_before_request(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    calls = []
    f, s = _session(
        type("C", (), {"chat": lambda _self: calls.append(1)}), max_cost=0.0
    )
    f.meter.record(usd=1.0)
    with pytest.raises(paid.BudgetExceeded):
        s.request("chat")
    assert calls == []


def test_session_401_counting_then_cell_abort(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    class Client:
        def chat(self) -> NoReturn:
            exc = Exception("nope")
            exc.status_code = 401
            raise exc

    f, s = _session(Client())
    # 401 #1 and #2 -> counted AuthError (retriable)
    for n in (1, 2):
        with pytest.raises(paid.AuthError) as ei:
            s.request("chat")
        assert ei.value.status == HTTPStatus.UNAUTHORIZED
        assert f.shared["paper_auth"]["2401.00001"] == n
    # 401 #3 -> per-paper fuse: fate marked auth_trip + abort cell
    with pytest.raises(paid.PaidAbortCell):
        s.request("chat")
    assert f.shared["paper_auth"]["2401.00001"] == paid.PaidSession.PAPER_401_LIMIT
    assert f.shared["all_failed"] == 1
    assert s.ctx.claim_fate == "auth_trip"
    # deferred release: the lease stays held until the cell boundary —
    # a mid-cell drop would open an 'absent'-verdict re-burn window
    # before the terminal row lands. For a bare session the caller's
    # release_claim() IS the cell end.
    assert claims.ClaimLease("2401.00001").held_by_other()
    s.release_claim()
    assert not claims.ClaimLease("2401.00001").held_by_other()


def test_session_second_paper_failure_trips_run(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    class Client:
        def chat(self) -> NoReturn:
            exc = Exception("nope")
            exc.status_code = 401
            raise exc

    f = paid.GatewayFactory(lambda _c=None: Client())
    for idc in ("2401.00001", "2401.00002"):
        s = f.session(_Ctx(idc=idc))
        for _ in range(2):
            with contextlib.suppress(paid.AuthError):
                s.request("chat")
        with contextlib.suppress(paid.PaidAbortCell, paid.PaidAbortRun):
            s.request("chat")
    assert f.shared["all_failed"] == paid.PaidSession.RUN_ALL_FAILED_LIMIT
    assert paths.auth_dead_path().exists()


def test_session_claim_actually_held_during_request(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    seen = {}

    class Client:
        def chat(self) -> dict:
            seen["held"] = not locks.lock_free(
                claims.claim_lock_path("2401.00001", "-", "-")
            )
            return {"usage": {}}

    _f, s = _session(Client())
    s.request("chat")
    assert seen["held"] is True
