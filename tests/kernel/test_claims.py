"""Tests for kernel.claims — lease mutex, escaping, reaper probe.

ClaimLease objects each own a distinct fd, so in-process double-claim tests
exercise real flock exclusion; detach_with_lock supplies a true
cross-process claimant.
"""
from __future__ import annotations

import threading
import time

from kernel import claims, locks, paths

# --- encoding / path shape ------------------------------------------------------

def test_escape_roundtrip():
    for s in ("zh", "real", "v1", "a.b@c%d-e", "-", "x y", "%"):
        assert claims.unescape_component(claims.escape_component(s)) == s
    assert claims.escape_component("a.b@c%d") == "a%2Eb%40c%25d"


def test_safe_id_convention():
    assert claims.safe_id("cond-mat/9601001") == "cond-mat--9601001"
    assert claims.safe_id("2301.12345") == "2301.12345"


def test_claim_lock_path_shape(broot):
    p = claims.claim_lock_path("cond-mat/9601001", "zh")
    assert p.parent == paths.claims_locks_dir()
    assert p.name == "cond-mat--9601001.zh.lock"

    pv = claims.claim_lock_path("cond-mat/9601001", "zh", "rep2")
    assert pv.name == "cond-mat--9601001.zh.rep2.lock"

    # dotted canon id: dot escaped inside the safe_id component
    pn = claims.claim_lock_path("math.QA/9701001", "real")
    assert pn.name == "math%2EQA--9701001.real.lock"

    # new-style bare id keeps no literal dot either
    pb = claims.claim_lock_path("2301.12345", "zh")
    assert pb.name == "2301%2E12345.zh.lock"


def test_claim_lock_name_roundtrip(broot):
    cases = [
        ("cond-mat/9601001", "zh", "-"),
        ("math.QA/9701001", "real", "rep2"),
        ("2301.12345", "-", "-"),
        ("hep-th/9601001", "mock", "weird.variant@x"),
    ]
    for idc, arm, variant in cases:
        p = claims.claim_lock_path(idc, arm, variant)
        got_idc, got_arm, got_variant = claims.parse_claim_lock_name(p)
        assert (got_idc, got_arm, got_variant) == (
            idc, arm or "-", variant or "-")


def test_claim_path_injectivity(broot):
    """No two distinct (idc, arm, variant) tuples map to the same filename.

    Domain note: idc must be canon — canon ids never contain '--' (design
    §3.10.7), which is what makes safe_id injective.
    """
    seen = {}
    idcs = ["a/b", "a.b", "math.QA/1", "hep-th/9601001",
            "2301.12345", "cond-mat/9601001"]
    arms = ["zh", "a.b", "-"]
    variants = ["-", "v1", "a.b"]
    for idc in idcs:
        for arm in arms:
            for variant in variants:
                name = claims.claim_lock_path(idc, arm, variant).name
                assert name not in seen, (name, seen[name], (idc, arm, variant))
                seen[name] = (idc, arm, variant)


# --- ClaimLease basics ------------------------------------------------------------

def test_lease_acquire_release(broot):
    lease = claims.ClaimLease("cond-mat/9601001", "zh")
    assert lease.acquire()
    assert lease.held
    assert not locks.lock_free(lease.path)
    lease.release()
    assert not lease.held
    assert locks.lock_free(lease.path)
    lease.release()                              # idempotent


def test_lease_acquire_idempotent(broot):
    lease = claims.ClaimLease("cond-mat/9601001")
    assert lease.acquire()
    assert lease.acquire()                       # already ours
    lease.release()


def test_double_claim_only_one_wins(broot):
    """Two ClaimLease objects (distinct fds) — exactly one acquires."""
    l1 = claims.ClaimLease("cond-mat/9601001", "zh")
    l2 = claims.ClaimLease("cond-mat/9601001", "zh")
    assert l1.acquire()
    assert not l2.acquire()
    l1.release()
    assert l2.acquire()
    l2.release()


def test_different_cells_do_not_contend(broot):
    l1 = claims.ClaimLease("cond-mat/9601001", "zh")
    l2 = claims.ClaimLease("cond-mat/9601001", "splice")
    l3 = claims.ClaimLease("cond-mat/9601001", "zh", "rep2")
    l4 = claims.ClaimLease("hep-th/9601001", "zh")
    for lease in (l1, l2, l3, l4):
        assert lease.acquire()
        lease.release()


def test_held_by_other(broot):
    l1 = claims.ClaimLease("cond-mat/9601001", "zh")
    l2 = claims.ClaimLease("cond-mat/9601001", "zh")
    assert not l1.held_by_other()                # free -> no other holder
    assert l1.acquire()
    assert not l1.held_by_other()                # held by us -> False
    assert l2.held_by_other()                    # other fd sees the hold
    l1.release()
    assert not l2.held_by_other()


def test_blocking_acquire_waits_for_release(broot):
    l1 = claims.ClaimLease("cond-mat/9601001", "zh")
    l2 = claims.ClaimLease("cond-mat/9601001", "zh")
    assert l1.acquire()

    def drop():
        time.sleep(0.15)
        l1.release()

    th = threading.Thread(target=drop)
    th.start()
    t0 = time.monotonic()
    assert l2.acquire(blocking=True)
    assert time.monotonic() - t0 >= 0.1
    l2.release()
    th.join()


def test_concurrent_double_claim_never_two(broot):
    """N racing leases: flock atomicity — never more than one holder at once."""
    n = 8
    barrier = threading.Barrier(n)
    state = {"holding": 0, "max_held": 0}
    guard = threading.Lock()

    def race():
        lease = claims.ClaimLease("cond-mat/9601001", "zh")
        barrier.wait(timeout=10)
        if lease.acquire():                      # one-shot NB attempt
            with guard:
                state["holding"] += 1
                state["max_held"] = max(state["max_held"], state["holding"])
            time.sleep(0.05)                     # overlap window if buggy
            with guard:
                state["holding"] -= 1
            lease.release()

    threads = [threading.Thread(target=race) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
        assert not t.is_alive()
    assert state["max_held"] == 1                # exactly one NB winner


def test_lease_context_manager(broot):
    with claims.ClaimLease("cond-mat/9601001", "zh") as lease:
        assert lease.held
        assert not locks.lock_free(lease.path)
    assert not lease.held
    assert locks.lock_free(lease.path)


# --- cross-process exclusion --------------------------------------------------------

def test_foreign_process_holder_blocks_claim(broot):
    lp = claims.claim_lock_path("cond-mat/9601001", "zh")
    proc = locks.detach_with_lock([], lp)        # child holds the claim lock
    try:
        lease = claims.ClaimLease("cond-mat/9601001", "zh")
        assert not lease.acquire()               # cross-process exclusion
        assert lease.held_by_other()
        assert not locks.lock_free(lp)
    finally:
        proc.kill()
        proc.wait()
    lease = claims.ClaimLease("cond-mat/9601001", "zh")
    assert lease.acquire()                       # death released it
    lease.release()


# --- reaper ---------------------------------------------------------------------

def test_reaper_collect_free_claims(broot):
    held = claims.ClaimLease("cond-mat/9601001", "zh")
    dead = claims.ClaimLease("hep-th/9601001", "zh")
    dead.acquire()
    dead.release()
    held.acquire()
    try:
        free = claims.reaper_collect()
        assert dead.path in free
        assert held.path not in free
    finally:
        held.release()
    assert held.path in claims.reaper_collect()


def test_reaper_collect_foreign_death(broot):
    lp = claims.claim_lock_path("cond-mat/9601001", "zh")
    proc = locks.detach_with_lock([], lp)
    assert lp not in claims.reaper_collect()     # live holder
    proc.kill()
    proc.wait()
    assert lp in claims.reaper_collect()         # dead holder -> reap candidate
