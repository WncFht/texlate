"""kernel._kernel_lookahead — lake 预取双机制叶 (kernel.kernel 拆分叶, §3.10.3).

``_Lookahead`` 守护线程沿 plan 序走 distinct idc, 经 spec.fetch_fn 逐
格 hydrate, 窗口上界 ``LOOKAHEAD_CELLS`` 格或 ``LOOKAHEAD_BYTES`` 字
节; 启动空窗的 ≤32 格即时 burst 即 plan-time 批量预热, 持续运行即
run-internal lookahead——两个具名机制是一条线程。

monkeypatch 锚点: 窗口常量 ``LOOKAHEAD_CELLS``/``LOOKAHEAD_BYTES`` 是
本叶模块全局——测试 patch 须指 ``kernel._kernel_lookahead`` 本叶,
setattr 到 ``kernel.kernel`` 门面无效 (test_kernel 实证)。
门面回引名单见 ``kernel.kernel._LEAF_EXPORTS``。
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from kernel import fsutil, lake
from kernel._kernel_emit import _note

if TYPE_CHECKING:
    from kernel.spec import Spec

# Window bounds: at most this many hydrated-but-unconsumed cells — or this
# many bytes of them — may sit ahead of the execution frontier.
LOOKAHEAD_CELLS = 32
LOOKAHEAD_BYTES = 512 * 1024**2


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
        self._pending: dict[str, int] = {}  # idc -> hydrated bytes
        self._consumed: set[str] = set()  # started before prefetch landed
        self._thread: threading.Thread | None = None

    def _window_open(self) -> bool:
        return (
            len(self._pending) < LOOKAHEAD_CELLS
            and sum(self._pending.values()) < LOOKAHEAD_BYTES
        )

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
        run_seq = getattr(env.rd, "run_seq", 0) or 0
        source = getattr(spec, "lake_source", "arxiv") or "arxiv"
        for idc in idcs:
            if self._stop.is_set() or env.abort.is_set():
                return
            with self._cond:
                while not (
                    self._stop.is_set() or env.abort.is_set() or self._window_open()
                ):
                    self._cond.wait(timeout=2.0)
                if self._stop.is_set() or env.abort.is_set():
                    return
            if not lake.admit(0):
                _note(
                    env,
                    "lake lookahead paused: zone over capacity cap "
                    "or fs floor — consumers still self-hydrate",
                    level="warn",
                )
                return
            try:
                d = lake.hydrate(
                    idc, fetch_fn=spec.fetch_fn, source=source, run_seq=run_seq
                )
            except Exception as exc:
                _note(
                    env,
                    f"lake prefetch {idc} failed: {type(exc).__name__}: {exc}",
                    level="warn",
                )
                continue
            if d is None:
                continue  # lazy-unfetchable — no slot used
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
            k = (
                str(c["idc"]),
                str(c.get("arm", "-")),
                str(c.get("up", "-")),
                str(c.get("variant", "-")),
                str(c["stage"]),
            )
            if k in terminal_keys:
                continue
            idc = str(c["idc"])
            if idc not in seen:
                seen.add(idc)
                idcs.append(idc)
        if not idcs:
            return
        self._thread = threading.Thread(
            target=self._loop, args=(idcs,), daemon=True, name="lake-lookahead"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=10)
