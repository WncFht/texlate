"""flock locks, heartbeats, sentinels and the paid-slot gate.

Design: docs/spec/bench-trizone.md — §3.3 (write contract, lock
ordering), §3.10.6 (claim lease = flock files, paid slots, AUTH_DEAD),
risk rows R21 (lock-inode footgun) and R22 (detach losing the lock).

LOCK ORDERING — the only legal direction (§3.3 / §3.10.6):

    run.lock -> cell.lock -> claim.lock -> leaf locks {slot, ledger, index, vault}

While holding a leaf lock a caller may only *probe* (LOCK_NB) other locks —
never blocking-acquire them. Code that must inspect many locks at once
(reaper, doctor) is therefore built from nonblocking probes only; code that
must serialize (emit, run registration) sits at its own level in the chain.

Invariants:
    - Lock files are created once and NEVER unlinked or renamed by anything
      in this module (R21: flock pins the inode — unlink+recreate swaps it
      and silently resurrects a second writer under the same name).
    - Locks live on the open file description, not the process: process
      death releases every lock it held, so a successful LOCK_NB probe is
      an authoritative life proof (§3.10.6).
    - Linux-only: fcntl.flock semantics.
"""

from __future__ import annotations

import fcntl
import os
import select
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager, suppress
from pathlib import Path

from kernel import paths

__all__ = [
    "WouldBlock",
    "auth_dead",
    "clear_auth_dead",
    "detach_with_lock",
    "flock",
    "heartbeat_age",
    "kernel_active_hold",
    "kernel_idle",
    "lock_free",
    "paid_slot",
    "pause_engaged",
    "touch",
    "trip_auth_dead",
]


class WouldBlock(Exception):
    """A nonblocking flock attempt found the lock already held."""


def _open_lock(path) -> int:
    """Open (creating if needed) a lock file and return the fd.

    O_CREAT mode applies only on first creation — an existing file keeps
    its mode. Parents are created so ad-hoc lock paths work; the file
    itself is never unlinked afterwards (R21).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return os.open(p, os.O_RDWR | os.O_CREAT, 0o644)


@contextmanager
def flock(path, exclusive: bool = True, blocking: bool = True):
    """Hold an flock on `path` for the duration of the block; yields the fd.

    exclusive=True -> LOCK_EX, False -> LOCK_SH. blocking=False raises
    WouldBlock immediately if the lock is held. The lock file is never
    unlinked by this module.
    """
    fd = _open_lock(path)
    op = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    if not blocking:
        op |= fcntl.LOCK_NB
    try:
        fcntl.flock(fd, op)
    except BlockingIOError as e:
        os.close(fd)
        msg = f"{path} is held"
        raise WouldBlock(msg) from e
    except BaseException:
        os.close(fd)
        raise
    try:
        yield fd
    finally:
        with suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def lock_free(path) -> bool:
    """NB probe: True iff nobody holds the lock — authoritative life proof.

    Acquires LOCK_EX|LOCK_NB on a throwaway fd and releases it. Works for
    both EX- and SH-held locks (any hold blocks an EX probe). Read-only
    and non-creating: an absent lock file means no holder ever existed —
    a probe must not materialize files on the paths it reads (an orphaned
    probe inside a deleted tree would resurrect it).
    """
    try:
        fd = os.open(path, os.O_RDWR)  # no O_CREAT — probe must not create
    except FileNotFoundError:
        return True
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    finally:
        os.close(fd)


def touch(path) -> Path:
    """Heartbeat: update mtime, creating the file (and parents) if absent."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    return p


def heartbeat_age(path) -> float | None:
    """Seconds since `path`'s mtime; None if the file is missing.

    May return a small negative on clock skew — callers compare against a
    staleness threshold, so a negative honestly reads as "alive".
    """
    try:
        return time.time() - Path(path).stat().st_mtime
    except FileNotFoundError:
        return None


# --- kernel-wide sentinels ----------------------------------------------------


@contextmanager
def kernel_active_hold():
    """Hold LOCK_SH on the .kernel-active file for the run's lifetime.

    Every active runner holds SH; kernel_idle()'s EX probe therefore fails
    while any runner is alive — that's the "is the kernel busy" signal the
    census/drain gate checks (§3.10.9 drain protocol).
    """
    with flock(paths.kernel_active_path(), exclusive=False, blocking=True) as fd:
        yield fd


def kernel_idle() -> bool:
    """True iff LOCK_EX NB probe succeeds on .kernel-active — no active runner."""
    return lock_free(paths.kernel_active_path())


def pause_engaged() -> bool:
    """True while the $ROOT/PAUSE file exists (Phase-0 stop-the-world flag)."""
    return paths.pause_path().exists()


def auth_dead() -> bool:
    """True while the locks/AUTH_DEAD sentinel exists (§3.10.6 breaker)."""
    return paths.auth_dead_path().exists()


def trip_auth_dead(reason: str = "") -> Path:
    """Create the AUTH_DEAD sentinel; concurrent runs must drain on first 401.

    Content is diagnostic only (ts + reason) — existence is the signal.
    """
    p = paths.auth_dead_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{time.time():.3f}\t{reason}\n", encoding="utf-8")
    return p


def clear_auth_dead() -> None:
    """Remove the AUTH_DEAD sentinel (manual reset after the auth fix)."""
    paths.auth_dead_path().unlink(missing_ok=True)


# --- paid slots ---------------------------------------------------------------


@contextmanager
def paid_slot(
    nslots: int = 4,
    blocking: bool = True,
    poll_s: float = 0.05,
    timeout: float | None = None,
):
    """Hold one of nslots global paid-slot lock files; yields the slot index.

    NB-scans locks/slots/slot{0..nslots-1}.lock and holds the first free one.
    blocking=True retries with `poll_s` sleeps until a slot frees (or
    `timeout` seconds elapse -> TimeoutError); blocking=False raises
    WouldBlock when every slot is held. Slots are flock files, so a dead
    holder's slot frees itself — the reaper only has to fix the audit side.
    """
    if nslots < 1:
        msg = f"paid_slot needs nslots>=1, got {nslots}"
        raise ValueError(msg)
    slot_paths = [paths.slots_dir() / f"slot{i}.lock" for i in range(nslots)]
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        for i, sp in enumerate(slot_paths):
            fd = _open_lock(sp)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                continue
            except BaseException:
                os.close(fd)
                raise
            try:
                yield i
            finally:
                with suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            return
        if not blocking:
            msg = f"all {nslots} paid slots held"
            raise WouldBlock(msg)
        if deadline is not None and time.monotonic() >= deadline:
            msg = f"paid_slot: no slot freed within {timeout}s"
            raise TimeoutError(msg)
        time.sleep(poll_s)


# --- detach protocol (R22) -----------------------------------------------------

# The detached child must hold the lock itself: a flock inherited via
# pass_fds would die with the parent's fd, and close_fds drops it entirely —
# the original R22 bug. So the child is a tiny stub that opens the lock file,
# flocks it (blocking per contract), marks the fd inheritable so the lock
# survives exec, acks over the pipe, then execs argv. Parent returns only
# after the ack: "spawned" == "lock held".
_DETACH_STUB = r"""
import fcntl, os, signal, sys
lock_path, wfd = sys.argv[1], int(sys.argv[2])
argv = sys.argv[3:]
os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
fcntl.flock(fd, fcntl.LOCK_EX)
os.set_inheritable(fd, True)            # lock lives on this fd; keep it over exec
os.write(wfd, b"ok")
os.close(wfd)
if argv:
    os.execvp(argv[0], argv)
while True:                             # no argv: pure lock-holder, still useful
    signal.pause()
"""


def _read_ack(rfd: int, timeout: float | None) -> bytes:
    """Read up to 2 ack bytes; b''/short on stub death, TimeoutError on timeout."""
    buf = b""
    deadline = None if timeout is None else time.monotonic() + timeout
    while len(buf) < 2:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                msg = "detach ack timeout"
                raise TimeoutError(msg)
            ready, _, _ = select.select([rfd], [], [], remaining)
            if not ready:
                msg = "detach ack timeout"
                raise TimeoutError(msg)
        chunk = os.read(rfd, 2 - len(buf))
        if not chunk:
            break  # EOF: stub died before ack
        buf += chunk
    return buf


def detach_with_lock(
    argv, lock_path, *, ack_timeout: float | None = None, **popen_kw
) -> subprocess.Popen:
    """Spawn a child that holds `lock_path` (LOCK_EX) while running `argv`.

    Protocol (R22): child opens the lock file, flocks it BLOCKING, marks the
    fd inheritable, writes 'ok' to a pipe, then execs argv. Parent returns
    only after the ack — so a live returned Popen implies the lock is held.

    Fail-fast: a NB pre-probe raises WouldBlock immediately when the lock is
    already held (e.g. a second detach while the first child lives — the
    contract test). A racer that grabs the lock between probe and spawn just
    delays the ack (blocking semantics); bound the wait with ack_timeout,
    which raises TimeoutError and kills the stub on expiry.

    argv may be empty: the stub then becomes a pure lock-holder (useful for
    tests and drain tooling). close_fds is forced True — the whole point is
    that no parent lock fd leaks into the child; the pipe fd is passed
    explicitly via pass_fds.
    """
    argv = [str(a) for a in (argv or ())]
    lock_path = str(lock_path)
    if argv and shutil.which(argv[0]) is None:
        msg = f"detach target not on PATH: {argv[0]}"
        raise FileNotFoundError(msg)

    # Fast-path pre-probe (also materializes the immortal lock file).
    pfd = _open_lock(lock_path)
    try:
        try:
            fcntl.flock(pfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            msg = f"{lock_path} already held"
            raise WouldBlock(msg) from e
        fcntl.flock(pfd, fcntl.LOCK_UN)
    finally:
        os.close(pfd)

    rfd, wfd = os.pipe()
    try:
        kw = dict(popen_kw)
        kw["close_fds"] = True  # R22: never inherit parent lock fds
        kw["pass_fds"] = (*kw.get("pass_fds", ()), wfd)
        kw.setdefault("stdin", subprocess.DEVNULL)
        cmd = [sys.executable, "-c", _DETACH_STUB, lock_path, str(wfd), *argv]
        proc = subprocess.Popen(cmd, **kw)
    except Exception:
        os.close(rfd)
        os.close(wfd)
        raise

    os.close(wfd)  # child owns its copy; EOF works now
    try:
        ack = _read_ack(rfd, ack_timeout)
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        os.close(rfd)
    if ack != b"ok":
        proc.kill()
        proc.wait()
        msg = f"detach stub failed before ack ({ack!r})"
        raise RuntimeError(msg)
    return proc
