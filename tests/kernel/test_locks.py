"""Tests for kernel.locks — flock semantics, sentinels, paid slots, detach.

flock lives on the open file description: two os.open()s of the same file
are independent lock contexts even inside one process, so most contention
tests run in-process on separate fds. detach_with_lock gives real
cross-process coverage.
"""

from __future__ import annotations

import fcntl
import os
import sys
import threading
import time
from contextlib import ExitStack
from typing import TYPE_CHECKING

import pytest
from kernel import locks, paths

if TYPE_CHECKING:
    from pathlib import Path

_FRESH_HB_AGE_S = 5  # 刚 touch 的 heartbeat 读龄须在此秒内
_OLD_HB_AGE_S = 3600  # utime 回拨一小时后的读龄基准
_FAIL_FAST_S = 5  # detach 抢锁失败须在此秒内返回

# --- flock -----------------------------------------------------------------


def test_flock_exclusive_blocks_second_fd(broot: Path) -> None:
    p = broot / "locks" / "a.lock"
    with locks.flock(p) as fd1:
        assert isinstance(fd1, int)
        fd2 = os.open(p, os.O_RDWR)  # separate fd: real contention
        try:
            with pytest.raises(BlockingIOError):  # raw fcntl, separate fd
                fcntl.flock(fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd2)


def test_flock_nonblocking_raises_wouldblock(broot: Path) -> None:
    p = broot / "locks" / "b.lock"
    with (
        locks.flock(p),
        pytest.raises(locks.WouldBlock),
        locks.flock(p, blocking=False),
    ):
        pass


def test_flock_shared_coexist_exclusive_fails(broot: Path) -> None:
    p = broot / "locks" / "c.lock"
    with locks.flock(p, exclusive=False):
        with locks.flock(p, exclusive=False):  # second SH on another fd: fine
            pass
        assert not locks.lock_free(p)  # EX probe fails under SH hold


def test_flock_released_on_ctx_exit(broot: Path) -> None:
    p = broot / "locks" / "d.lock"
    with locks.flock(p):
        pass
    assert locks.lock_free(p)


def test_lock_file_never_unlinked(broot: Path) -> None:
    p = broot / "locks" / "immortal.lock"
    inode0 = None
    with locks.flock(p) as fd:
        inode0 = os.fstat(fd).st_ino
    assert p.exists()  # still there after release
    assert p.stat().st_ino == inode0  # same inode — R21
    with locks.flock(p):
        pass
    assert p.stat().st_ino == inode0


def test_lock_free_fresh_path(broot: Path) -> None:
    assert locks.lock_free(broot / "locks" / "fresh.lock")


# --- heartbeat ---------------------------------------------------------------


def test_heartbeat_age_missing(broot: Path) -> None:
    assert locks.heartbeat_age(broot / "nope") is None


def test_touch_and_heartbeat_age(broot: Path) -> None:
    hb = broot / "hb"
    locks.touch(hb)
    assert hb.exists()
    age = locks.heartbeat_age(hb)
    assert age is not None
    assert 0 <= age < _FRESH_HB_AGE_S
    old = time.time() - _OLD_HB_AGE_S
    os.utime(hb, (old, old))
    assert locks.heartbeat_age(hb) > _OLD_HB_AGE_S - 1


# --- kernel-active / pause / auth_dead ---------------------------------------


def test_kernel_active_hold_and_idle(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    assert locks.kernel_idle()
    with locks.kernel_active_hold():
        assert not locks.kernel_idle()
    assert locks.kernel_idle()


def test_kernel_active_two_runners(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    with locks.kernel_active_hold():
        with locks.kernel_active_hold():  # second SH hold coexists
            assert not locks.kernel_idle()
        assert not locks.kernel_idle()
    assert locks.kernel_idle()


def test_pause_engaged(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    assert not locks.pause_engaged()
    paths.pause_path().touch()
    assert locks.pause_engaged()


def test_auth_dead_sentinel_cycle(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    assert not locks.auth_dead()
    p = locks.trip_auth_dead("first 401")
    assert locks.auth_dead()
    assert "first 401" in p.read_text()
    locks.clear_auth_dead()
    assert not locks.auth_dead()
    locks.clear_auth_dead()  # idempotent


# --- paid_slot -----------------------------------------------------------------


def test_paid_slot_yields_index_and_releases(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    with locks.paid_slot() as i:
        assert i == 0
        assert not locks.lock_free(paths.slots_dir() / "slot0.lock")
    assert locks.lock_free(paths.slots_dir() / "slot0.lock")


def test_paid_slot_first_free(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    with locks.paid_slot() as a:
        with locks.paid_slot() as b:
            assert (a, b) == (0, 1)
            with locks.paid_slot() as c:
                assert c == 2  # noqa: PLR2004 -- 断言字面量(第三个槽序号)
        with locks.paid_slot() as d:
            assert d == 1  # freed slot reused


def test_paid_slot_cap_nonblocking(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    with ExitStack() as st:
        got = [st.enter_context(locks.paid_slot(nslots=4)) for _ in range(4)]
        assert sorted(got) == [0, 1, 2, 3]
        with pytest.raises(locks.WouldBlock), locks.paid_slot(
            nslots=4, blocking=False
        ):
            pass


def test_paid_slot_blocking_timeout(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    with ExitStack() as st:
        for _ in range(2):
            st.enter_context(locks.paid_slot(nslots=2))
        with pytest.raises(TimeoutError), locks.paid_slot(
            nslots=2, timeout=0.2, poll_s=0.02
        ):
            pass


def test_paid_slot_blocking_waits_for_release(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用(隔离 bench root)
    holder = locks.flock(paths.slots_dir() / "slot0.lock")
    holder.__enter__()
    released = threading.Event()

    def drop() -> None:
        time.sleep(0.15)
        holder.__exit__(None, None, None)
        released.set()

    th = threading.Thread(target=drop)
    th.start()
    with locks.paid_slot(nslots=1, timeout=5, poll_s=0.02) as i:
        assert i == 0
        assert released.is_set()
    th.join()


# --- detach_with_lock (R22) -----------------------------------------------------


def test_detach_pure_holder_and_fail_fast(broot: Path) -> None:
    lp = broot / "locks" / "det.lock"
    proc = locks.detach_with_lock([], lp)  # argv empty -> pure holder
    try:
        assert proc.poll() is None  # alive, holding the lock
        assert not locks.lock_free(lp)
        t0 = time.monotonic()
        with pytest.raises(locks.WouldBlock):
            locks.detach_with_lock([], lp)  # second fire: fail fast
        assert time.monotonic() - t0 < _FAIL_FAST_S
    finally:
        proc.kill()
        proc.wait()
    assert locks.lock_free(lp)  # death released the lock


def test_detach_exec_keeps_lock(broot: Path) -> None:
    lp = broot / "locks" / "det2.lock"
    proc = locks.detach_with_lock(
        [sys.executable, "-c", "import time; time.sleep(60)"], lp
    )
    try:
        assert proc.poll() is None
        # lock survived exec (fd marked inheritable in the stub)
        assert not locks.lock_free(lp)
    finally:
        proc.terminate()
        proc.wait()
    assert locks.lock_free(lp)


def test_detach_bad_argv_fails_fast(broot: Path) -> None:
    with pytest.raises(FileNotFoundError):
        locks.detach_with_lock(
            ["definitely-not-a-real-binary-xyz"], broot / "locks" / "det3.lock"
        )


def test_detach_ack_eof_gives_runtime_error(
    broot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # stub that dies before ack -> parent must raise, not hang
    monkeypatch.setattr(locks, "_DETACH_STUB", "import sys; sys.exit(3)")
    with pytest.raises(RuntimeError):
        locks.detach_with_lock([], broot / "locks" / "det4.lock", ack_timeout=5)
