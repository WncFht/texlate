"""Claim leases — the REAL paid-dedup mutex (design §3.10.6).

A claim is an flock file:

    locks/claims/{safe_id}.{arm}[.{variant}].lock    — never unlinked (R21)

The index `claims` table and the claim events are AUDIT only. The kernel
trusts the flock: it is acquired just before the first gateway request and
released after harvest meta is verified (fate: verified | failed |
suspended). Holder death releases the lock automatically, so a LOCK_NB
probe is an authoritative life proof — two concurrent runs claiming the
same cell degrade to a serial skip, never a double burn.

Lock ordering (locks.py docstring): run.lock -> cell.lock -> claim.lock ->
leaf locks {slot, ledger, index, vault}. A claim holder may take leaf locks;
a leaf-lock holder may only NB-probe a claim, never blocking-acquire it.

Filename encoding (§3.10.4 "组件级转义恢复单射"): every component is
percent-escaped so the dot-separated name round-trips injectively —
'%'->'%25' first, then '.'->'%2E', '@'->'%40'. safe_id itself is escaped as
one component: canon ids like `math.QA/9601001` or `2301.12345` carry dots
that would otherwise be indistinguishable from component separators.
Escaping/safe_id are re-exported from kernel.idnorm — single implementation.
"""

from __future__ import annotations

import fcntl
import os
from contextlib import suppress
from pathlib import Path
from typing import Self

from kernel import locks, paths
from kernel.idnorm import (
    escape_component,
    idc_from_safe,
    safe_id,
    unescape_component,
)

__all__ = [
    "ClaimLease",
    "claim_lock_path",
    "escape_component",
    "parse_claim_lock_name",
    "reaper_collect",
    "safe_id",
    "stale_open",
    "unescape_component",
]


def _norm_comp(v, default: str = "-") -> str:
    return default if v is None or v == "" else str(v)


def claim_lock_path(idc, arm="-", variant="-") -> Path:
    """locks/claims/{safe_id}.{arm}[.{variant}].lock

    The variant component is omitted when variant is the null spelling '-',
    matching the `arm[@variant]` convention used everywhere else. All three
    components are escaped so the name parses back injectively.
    """
    arm = _norm_comp(arm)
    variant = _norm_comp(variant)
    name = escape_component(safe_id(idc)) + "." + escape_component(arm)
    if variant != "-":
        name += "." + escape_component(variant)
    return paths.claims_locks_dir() / (name + ".lock")


def parse_claim_lock_name(path) -> tuple[str, str, str]:
    """Inverse of claim_lock_path: filename -> (idc, arm, variant)."""
    stem = Path(path).name
    stem = stem.removesuffix(".lock")
    parts = stem.split(".")
    sid = unescape_component(parts[0]) if parts and parts[0] else ""
    idc = idc_from_safe(sid)
    arm = unescape_component(parts[1]) if len(parts) > 1 else "-"
    variant = unescape_component(parts[2]) if len(parts) > 2 else "-"
    return idc, arm, variant


# --- the lease ------------------------------------------------------------------


class ClaimLease:
    """flock lease on one (idc, arm, variant) cell — the paid-dedup mutex.

    Holds its own fd on the claim lock file while acquired. acquire() is
    idempotent; release() is a no-op when not held. Not thread-shared by
    design — one lease object per claiming context (flock state lives on
    the fd, and each lease owns a distinct fd).
    """

    def __init__(self, idc, arm: str = "-", variant: str = "-"):
        self.idc = str(idc)
        self.arm = _norm_comp(arm)
        self.variant = _norm_comp(variant)
        self.path = claim_lock_path(self.idc, self.arm, self.variant)
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self, blocking: bool = False) -> bool:
        """Take the claim. NB mode returns False when another holder lives.

        blocking=True waits on flock until the current holder releases (or
        dies — death frees the lock). Idempotent: returns True immediately
        if this lease already holds the claim.
        """
        if self._fd is not None:
            return True
        fd = locks._open_lock(self.path)
        op = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(fd, op)
        except BlockingIOError:
            os.close(fd)
            return False
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        return True

    def release(self) -> None:
        """Drop the claim; no-op when not held. Process death also releases."""
        fd, self._fd = self._fd, None
        if fd is None:
            return
        with suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    def held_by_other(self) -> bool:
        """NB probe: True iff some OTHER holder keeps this claim alive.

        False while this lease itself holds the claim. Authoritative life
        proof — a dead claimant's lock is already gone.
        """
        if self._fd is not None:
            return False
        return not locks.lock_free(self.path)

    def __enter__(self) -> Self:
        self.acquire(blocking=True)
        return self

    def __exit__(self, *exc) -> bool:
        self.release()
        return False

    def __del__(self):  # hygiene only; explicit release wins
        with suppress(Exception):
            self.release()


def reaper_collect() -> list[Path]:
    """Claim-lock files with no live holder — reap candidates for the sweep.

    The flock itself is already free (holder died or released cleanly); the
    sweep cross-references these paths against live claim rows in the index
    to decide which leases need an op='reap' audit event. Sorted for
    determinism.
    """
    d = paths.claims_locks_dir()
    if not d.is_dir():
        return []
    return [p for p in sorted(d.glob("*.lock")) if locks.lock_free(p)]


def stale_open(idx) -> list[tuple[str, str, str]]:
    """(idc, arm, variant) the index shows acquire-open while the flock is
    free — held-by-dead leases. Detection core shared by the sweep reaper
    (adds a shard-release veto before mutating) and the doctor audit
    (report-only, no veto). ``idx=None`` → []."""
    if idx is None:
        return []
    return [
        (idc, arm, variant)
        for idc, arm, variant in sorted(idx.active_claims())
        if locks.lock_free(claim_lock_path(idc, arm, variant))
    ]
