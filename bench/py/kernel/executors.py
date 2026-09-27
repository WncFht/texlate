"""Cell executors — thread / process / async-owned (design §4 executor
contract).

    execute_cells(cells, run_cell_fn, executor="thread", jobs=4,
                  same_id_serial=True, registry=None)
        -> list[(cell, result|BaseException)] in input order

Contract:

- ``run_cell_fn(cell)`` is called exactly once per cell and is expected to
  handle its own exceptions (a raised exception is collected, never
  propagated — one dying cell must not kill the pool).
- ``same_id_serial=True`` (default): cells sharing an idc are STRICTLY
  serial — grouped per idc, each group runs on one worker in order.
  Groups run in parallel across workers. This is the scheduler-side half
  of same-id serialization; the cell.lock inside the critical section is
  the correctness half.
- executor='thread' → ThreadPoolExecutor (default; sqlite/index objects
  are thread-bound — workers build their own).
- executor='process' → ProcessPoolExecutor; the pickle boundary means
  ``run_cell_fn`` must be an importable module-level callable and cells
  must be pickle-able (plain dicts are). Results come back as (cell,
  result); a dead worker surfaces as the executor's exception on that
  group.
- executor='async-owned' → thread executor, but each cell invocation runs
  inside ``contextvars.copy_context().run`` so contextvars set around the
  submission propagate into the cell (the instrument owns its own event
  loop inside the cell fn — the kernel never touches asyncio itself).
"""

from __future__ import annotations

import contextvars
import functools
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

__all__ = ["execute_cells"]

_EXECUTORS = ("thread", "process", "async-owned")


def _group_key(cell: dict) -> str:
    return str(cell.get("idc", cell.get("id", "-")))


def _groups(cells: list, same_id_serial: bool) -> list[list[dict]]:
    """Partition cells into serial groups preserving input order.

    same_id_serial: one group per idc (insertion-ordered). Otherwise each
    cell is its own group (flat parallelism).
    """
    if not same_id_serial:
        return [[c] for c in cells]
    by: dict[str, list[dict]] = {}
    order: list[str] = []
    for c in cells:
        k = _group_key(c)
        if k not in by:
            by[k] = []
            order.append(k)
        by[k].append(c)
    return [by[k] for k in order]


def _run_group(cells: list, run_cell_fn) -> list:
    """Serial runner for one same-idc group on one worker."""
    out = []
    for cell in cells:
        try:
            out.append((cell, run_cell_fn(cell)))
        except BaseException as exc:
            out.append((cell, exc))
    return out


def _run_group_ctx(cells: list, run_cell_fn) -> list:
    """Same, with contextvars propagation per cell (async-owned)."""
    out = []
    for cell in cells:
        try:
            ctx = contextvars.copy_context()
            out.append((cell, ctx.run(run_cell_fn, cell)))
        except BaseException as exc:
            out.append((cell, exc))
    return out


def execute_cells(
    cells,
    run_cell_fn,
    executor: str = "thread",
    jobs: int = 4,
    same_id_serial: bool = True,
    registry=None,
) -> list:
    """Run ``run_cell_fn`` over ``cells``.

    Returns [(cell, result)] in the ORIGINAL input order; a cell that
    raised carries its exception object as the result. ``registry`` is
    accepted for caller symmetry (canon data is plan-time, not executor
    business) and ignored.
    """
    if executor not in _EXECUTORS:
        msg = f"executor {executor!r} not in {_EXECUTORS}"
        raise ValueError(msg)
    cells = list(cells)
    if not cells:
        return []
    jobs = max(1, int(jobs or 1))
    groups = _groups(cells, same_id_serial)
    runner = _run_group_ctx if executor == "async-owned" else _run_group

    results: list = []
    if executor == "process":
        # pickle boundary: run_cell_fn and cells must pickle; cells are
        # plain dicts by construction (§4). The bound callable ships with
        # each group — an unpicklable (closure) run_cell_fn fails loudly
        # at submission, not mid-map.
        bound = functools.partial(runner, run_cell_fn=run_cell_fn)
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for group_res in pool.map(bound, groups):
                results.extend(group_res)
    else:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futs = [(g, pool.submit(runner, g, run_cell_fn)) for g in groups]
            for g, f in futs:
                try:
                    results.extend(f.result())
                except BaseException as exc:  # group runner itself died
                    # every cell in THAT group surfaces the failure;
                    # later groups still collect their real results
                    results.extend((c, exc) for c in g)
    # restore input order — results arrive grouped
    pos = {id(c): i for i, c in enumerate(cells)}
    results.sort(key=lambda cr: pos.get(id(cr[0]), 0))
    return results
