"""Runs zone — materialization of the (kind, date, slug) identity triple.

Layout per design §1 (docs/dev/bench-redesign-v2-trizone.md):

    runs/{kind}/{date}/{slug}/
        spec.json         frozen bench definition (verbatim dict)
        spec_env.json     env-probe snapshot (names, never secret values)
        invocations.jsonl one row per resume/retry
        events.jsonl      this run's event shard (dual-written by ledger.emit)
        plan.json         frozen cell enumeration (freeze_plan)
        cases.jsonl       evaluation-case sink
        .lock             run-level flock — NEVER unlinked (R21)
        heartbeat         mtime liveness; zombie harvest evidence
        report.md         keep-tier human/agent summary
        work/             per-run private work tree (not shared across runs)
            _texmf/       run-shared texmf
            {safe_id}/    per-cell tree + .lock (same_id_serial)
        derived/          rebuildable derivatives

Rules baked here:

- ``.lock`` files are created once and NEVER unlinked: flock pins the inode,
  unlink+recreate silently resurrects a second writer under the same name.
- ``run.lock`` is LOCK_NB fail-fast by default — the pgrep-argv social
  contract dies here (§2.1 step 4, R21's LOCK_NB precedent).
- ``cell.lock`` is LOCK_EX blocking — same-id serialization inside a run.
- Active-run test (§3.10.1): heartbeat mtime fresh (<10min) AND run.lock held
  (NB probe fails). Stale heartbeat + free lock = zombie, sweep material.
- Kernel-emitted ledger rows take NEGATIVE seqs so they can never collide
  with executor-minted cell seqs inside the same run shard.
- ``remove_cell_tree`` is THE single delete verb (§3.10.1): prune, evict,
  sweep and zombie harvest all funnel through it, and a paid tree whose
  bytes are not yet in vault raises ``BlockedDelete`` instead of
  evaporating (the ``vault_check`` callable is the byte-security oracle;
  falsy = paid bytes unharvested = block).
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import shutil
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from kernel import events, fsutil, ledger, locks, paths
from kernel.events import iter_jsonl
from kernel.idnorm import idc_from_safe

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

__all__ = [
    "BlockedDelete",
    "RunDir",
    "accounting_check",
    "active_runs",
    "add_case",
    "add_invocation",
    "cell_lock",
    "create_run",
    "freeze_plan",
    "heartbeat_loop",
    "load_run",
    "remove_cell_tree",
]

_HEAL_CHUNK = 64 * 1024
_HEARTBEAT_FRESH_S = 600.0  # <10min fresh per §3.10.1 zombie rule

_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class BlockedDelete(Exception):
    """remove_cell_tree refused: the tree holds paid bytes that no vault
    meta vouches for — harvest (or stage) before deleting."""


# --- small append helper ---------------------------------------------------------

def _append_line(path: Path, payload: bytes) -> None:
    """Heal a torn tail, append payload in ONE os.write, fsync.

    Same append contract as the ledger path minus the lock: run-local jsonl
    files have exactly one writer (the owning run), so flock is unnecessary —
    but the torn-tail heal still applies after a crash mid-append. payload
    must already include the trailing newline.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        size = os.fstat(fd).st_size
        offset = size
        pos = size
        while pos > 0:
            n = min(_HEAL_CHUNK, pos)
            pos -= n
            buf = os.pread(fd, n, pos)
            idx = buf.rfind(b"\n")
            if idx != -1:
                offset = pos + idx + 1
                break
        else:
            offset = 0
        if offset != size:
            os.ftruncate(fd, offset)
        if payload:
            n = os.write(fd, payload)
            if n != len(payload):
                msg = f"short write {n}/{len(payload)} on {path}"
                raise OSError(msg)
        os.fsync(fd)
    finally:
        os.close(fd)
    if not existed:
        fsutil.fsync_dir(path.parent)


def _append_row(path: Path, row: dict) -> None:
    line = json.dumps(
        row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    _append_line(path, line)


def _kernel_seq(rundir: RunDir) -> int:
    """Next negative seq for kernel-emitted shard rows.

    Executor-minted cell seqs are >=0; kernel rows (notes) take -1, -2, …
    so (run_seq, seq) dedup keys can never collide across the two writers.
    """
    lo = 0
    shard = rundir.events_path()
    if shard.exists():
        for _ln, ev, _raw in iter_jsonl(shard):
            if not isinstance(ev, dict):
                continue
            seq = ev.get("seq")
            if isinstance(seq, int) and not isinstance(seq, bool) and seq < lo:
                lo = seq
    return lo - 1


def _emit_note(rundir: RunDir, text: str, level: str = "info",
               safe_id: str | None = None) -> None:
    """Emit a note event (ledger + this run's shard, same critical section)."""
    kw = {}
    if safe_id is not None:
        kw = {"id": safe_id, "idc": idc_from_safe(safe_id)}
    ev = events.make_event(
        events.T_NOTE, run=rundir.run, seq=_kernel_seq(rundir),
        text=text, level=level, **kw,
    )
    ledger.emit(ev, run_dir=rundir.path)


# --- RunDir ------------------------------------------------------------------------


@dataclass
class RunDir:
    """A materialized run directory — the identity triple on disk.

    ``path`` is ``runs/{kind}/{date}/{slug}``; ``run_seq`` is the globally
    monotonic number minted under the ledger lock at registration (used for
    cross-run ordering, never for identity).
    """

    path: Path
    kind: str
    date: str
    slug: str
    run_seq: int = 0

    @property
    def run(self) -> str:
        """The run id string carried on every event: ``kind/date/slug``."""
        return f"{self.kind}/{self.date}/{self.slug}"

    # -- path accessors (pure path math, no side effects) ------------------------

    def lock_path(self) -> Path:
        return self.path / ".lock"

    def heartbeat_path(self) -> Path:
        return self.path / "heartbeat"

    def events_path(self) -> Path:
        return self.path / "events.jsonl"

    def plan_path(self) -> Path:
        return self.path / "plan.json"

    def report_path(self) -> Path:
        return self.path / "report.md"

    def spec_path(self) -> Path:
        return self.path / "spec.json"

    def spec_env_path(self) -> Path:
        return self.path / "spec_env.json"

    def invocations_path(self) -> Path:
        return self.path / "invocations.jsonl"

    def cases_path(self) -> Path:
        return self.path / "cases.jsonl"

    def work(self, safe_id: str = "") -> Path:
        """``work/{safe_id}`` cell tree (or the work/ root when empty)."""
        w = self.path / "work"
        return w / safe_id if safe_id else w

    def derived(self) -> Path:
        return self.path / "derived"

    def cell_lock_path(self, safe_id: str) -> Path:
        # outside work/{safe}/ — the stage fn may rmtree its own paper_dir
        # mid-cell; a lock inode inside it would be orphaned while the
        # kernel still flocks it (and a recreated .lock would let a second
        # holder in). Lock files are immortal (R21), so they live under
        # the run's own locks/ dir.
        return self.path / "locks" / f"{safe_id}.lock"

    # -- locks / liveness ------------------------------------------------------------

    def lock(self, blocking: bool = False) -> AbstractContextManager[int]:
        """Context manager holding the run-level flock.

        Default LOCK_NB fail-fast (§2.1 step 4: a second concurrent writer
        for the same run identity is rejected immediately). Pass
        ``blocking=True`` to queue instead.
        """
        return locks.flock(self.lock_path(), exclusive=True, blocking=blocking)

    def heartbeat_touch(self) -> Path:
        """Heartbeat is pure mtime — touch the file, never write content."""
        return locks.touch(self.heartbeat_path())


# --- creation -------------------------------------------------------------------------


def _check_name(what: str, value: str) -> None:
    if not _NAME_RE.fullmatch(value):
        msg = f"{what} {value!r} is not a safe path component"
        raise ValueError(msg)


def create_run(kind: str, slug: str | None = None, date: str | None = None,
               spec_dict: dict | None = None, spec_hash: str = "",
               spec_env: dict | None = None) -> RunDir:
    """Materialize a run: mkdir the §1 tree, write spec/env/empty jsonls,
    mint run_seq under the ledger lock, register in runs.jsonl.

    - ``date`` defaults to UTC today (YYYY-MM-DD — timezone pinned, §7).
    - ``slug`` defaults to ``kind`` made unique with ``-2``, ``-3`` …
      suffixes. An explicit slug that already exists raises FileExistsError
      (resume goes through ``load_run``, never create).
    - ``spec_hash`` is auto-computed from spec_dict when not supplied; it
      feeds run_registered/invocations, never the run identity (R15).
    """
    _check_name("kind", kind)
    date = date or time.strftime("%Y-%m-%d", time.gmtime())
    if not _DATE_RE.fullmatch(date):
        msg = f"date {date!r} must be YYYY-MM-DD (UTC)"
        raise ValueError(msg)

    if slug is not None:
        _check_name("slug", slug)
        rdir = paths.run_dir(kind, date, slug)
        rdir.mkdir(parents=True)  # FileExistsError = identity collision
    else:
        for i in itertools.count(1):
            cand = kind if i == 1 else f"{kind}-{i}"
            rdir = paths.run_dir(kind, date, cand)
            try:
                rdir.mkdir(parents=True)
            except FileExistsError:
                continue
            slug = cand
            break

    # Static files first — a crash before mint leaves an unregistered dir
    # (sweep/doctor material), never a registered run without its archive.
    fsutil.atomic_write(
        rdir / "spec.json",
        json.dumps(spec_dict or {}, ensure_ascii=False, sort_keys=True,
                   indent=2).encode("utf-8"),
    )
    fsutil.atomic_write(
        rdir / "spec_env.json",
        json.dumps(spec_env or {}, ensure_ascii=False, sort_keys=True,
                   indent=2).encode("utf-8"),
    )
    (rdir / "invocations.jsonl").touch()
    (rdir / "events.jsonl").touch()
    (rdir / ".lock").touch()  # immortal lock file — created once, never unlinked
    (rdir / "work" / "_texmf").mkdir(parents=True, exist_ok=True)
    (rdir / "derived").mkdir(exist_ok=True)
    locks.touch(rdir / "heartbeat")

    if not spec_hash and spec_dict is not None:
        blob = json.dumps(spec_dict, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
        spec_hash = hashlib.sha256(blob).hexdigest()

    run_id = f"{kind}/{date}/{slug}"
    # mint_run_seq appends the runs.jsonl report row in the mint lock
    # window — no separate append here (import mints take the same path).
    run_seq = ledger.mint_run_seq(run_id, kind, date, slug, spec_hash)
    return RunDir(path=rdir, kind=kind, date=date, slug=slug, run_seq=run_seq)


def load_run(kind: str, date: str, slug: str) -> RunDir:
    """Reattach to an existing run dir (resume) — reads run_seq back from the
    shard's run_registered event. FileNotFoundError when the dir is absent."""
    rdir = paths.run_dir(kind, date, slug)
    if not rdir.is_dir():
        msg = f"run dir not found: {rdir}"
        raise FileNotFoundError(msg)
    run_seq = 0
    shard = rdir / "events.jsonl"
    if shard.exists():
        for _ln, ev, _raw in iter_jsonl(shard):
            if (
                isinstance(ev, dict)
                and ev.get("type") == events.T_RUN_REGISTERED
                and isinstance(ev.get("run_seq"), int)
            ):
                run_seq = ev["run_seq"]
    return RunDir(path=rdir, kind=kind, date=date, slug=slug, run_seq=run_seq)


# --- plan / invocations / cases ---------------------------------------------------------


def freeze_plan(rundir: RunDir, cells: list[dict],
                replan: bool = False) -> list[dict]:
    """Frozen-plan semantics (spec.freeze_plan / §3.1 invariant).

    ``plan.json`` exists and ``replan`` is False → return its cell list
    VERBATIM (the plan is frozen — re-enumeration never silently mutates it).
    Otherwise normalize each cell to the schema
    ``{id,idc,arm,up,variant,stage,needs,fp_input}`` (extra caller keys are
    preserved), write ``{"cells": [...]}`` via atomic_write, return the list.
    """
    pp = rundir.plan_path()
    if pp.exists() and not replan:
        plan = json.loads(pp.read_text(encoding="utf-8"))
        return plan["cells"]
    norm = []
    for c in cells:
        cell = {
            "id": None, "idc": None, "arm": "-", "up": "-",
            "variant": "-", "stage": None, "needs": [], "fp_input": None,
        }
        cell.update(c)
        if cell["idc"] is None:
            cell["idc"] = cell["id"]
        norm.append(cell)
    payload = json.dumps(
        {"cells": norm}, ensure_ascii=False, sort_keys=True, indent=2
    ).encode("utf-8")
    fsutil.atomic_write(pp, payload)
    return norm


def add_invocation(rundir: RunDir, flags: dict, spec_hash: str = "",
                   code_stamp: str = "") -> None:
    """Append one invocations.jsonl row: {flags, spec_hash, code_stamp, ts}.

    Spec tweaks change the invocation record, never the run identity (R15).
    """
    _append_row(rundir.invocations_path(), {
        "flags": dict(flags), "spec_hash": spec_hash,
        "code_stamp": code_stamp, "ts": round(time.time(), 3),
    })


def add_case(rundir: RunDir, row: dict) -> None:
    """Append one cases.jsonl row verbatim (fsync'd) — the CaseSink lane."""
    _append_row(rundir.cases_path(), row)


# --- locks / liveness ---------------------------------------------------------------------


def cell_lock(rundir: RunDir, safe_id: str,
              blocking: bool = True) -> AbstractContextManager[int]:
    """Context manager holding ``work/{safe_id}/.lock`` (LOCK_EX, blocking).

    The same-id serializer inside a run (§2.1 cell critical section). The
    lock file is created once and never unlinked (R21).
    """
    return locks.flock(
        rundir.cell_lock_path(safe_id), exclusive=True, blocking=blocking
    )


def heartbeat_loop(rundir: RunDir, interval_s: float = 15.0,
                   stop_event=None) -> None:
    """Touch the heartbeat every ``interval_s`` — run in a daemon thread.

    ``stop_event`` is a threading.Event; when absent the loop is infinite
    (rely on the daemon thread dying with the process — the mtime then goes
    stale, which is exactly what the zombie rule wants).
    """
    while True:
        rundir.heartbeat_touch()
        if stop_event is not None:
            if stop_event.wait(interval_s):
                return
        else:
            time.sleep(interval_s)


def active_runs(max_age_s: float = _HEARTBEAT_FRESH_S) -> list[dict]:
    """Scan runs/*/*/* for live runs.

    Active = heartbeat mtime younger than ``max_age_s`` AND the run .lock is
    held (NB probe fails). Stale heartbeat or free lock means the run is
    dead/zombie — not listed. Returns dicts sorted by path:
    ``{kind, date, slug, run, path, heartbeat_age}``.
    """
    out: list[dict] = []
    base = paths.runs_dir()
    if not base.is_dir():
        return out
    for rdir in sorted(base.glob("*/*/*")):
        if not rdir.is_dir():
            continue
        age = locks.heartbeat_age(rdir / "heartbeat")
        if age is None or age >= max_age_s:
            continue
        if locks.lock_free(rdir / ".lock"):
            continue
        kind, date, slug = rdir.relative_to(base).parts
        out.append({
            "kind": kind, "date": date, "slug": slug,
            "run": f"{kind}/{date}/{slug}", "path": rdir,
            "heartbeat_age": age,
        })
    return out


# --- accounting ------------------------------------------------------------------------------


def _cell_key(d: dict) -> tuple:
    """The §3.1 cell key: (idc, arm, up, variant, stage)."""
    return (
        str(d.get("idc") or d.get("id")),
        str(d.get("arm")),
        str(d.get("up")),
        str(d.get("variant")),
        str(d.get("stage")),
    )


def accounting_check(rundir: RunDir) -> dict:
    """The §3.1 accounting equation for one run.

    ``plan.json`` cells ⊇ cell_queued cells, and every queued cell has
    exactly one terminal cell event — finished-time validation. Returns::

        {plan, queued, terminal,            # counts
         missing_terminal,                  # queued keys with 0 terminals
         extra_queued,                      # queued keys absent from plan
         dup_terminal,                      # queued keys with >1 terminal
         extra_terminal,                    # terminal events on unqueued keys
         ok}
    """
    plan_keys: set[tuple] = set()
    pp = rundir.plan_path()
    if pp.exists():
        plan = json.loads(pp.read_text(encoding="utf-8"))
        for c in plan.get("cells", []):
            plan_keys.add(_cell_key(c))

    queued: dict[tuple, int] = {}
    terminal: dict[tuple, int] = {}
    shard = rundir.events_path()
    if shard.exists():
        for _ln, ev, _raw in iter_jsonl(shard):
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == events.T_CELL_QUEUED:
                k = _cell_key(ev)
                queued[k] = queued.get(k, 0) + 1
            elif events.is_terminal_cell(ev):
                k = _cell_key(ev)
                terminal[k] = terminal.get(k, 0) + 1

    extra_queued = sorted(queued.keys() - plan_keys, key=repr)
    missing_terminal = sorted(
        (k for k in queued if terminal.get(k, 0) == 0), key=repr
    )
    dup_terminal = sorted(
        (k for k, n in terminal.items() if n > 1 and k in queued), key=repr
    )
    extra_terminal = sorted(
        (k for k in terminal if k not in queued), key=repr
    )
    ok = not (extra_queued or missing_terminal or dup_terminal
              or extra_terminal)
    return {
        "plan": len(plan_keys),
        "queued": len(queued),
        "terminal": sum(terminal.values()),
        "missing_terminal": missing_terminal,
        "extra_queued": extra_queued,
        "dup_terminal": dup_terminal,
        "extra_terminal": extra_terminal,
        "ok": ok,
    }


# --- the single delete verb --------------------------------------------------------------------


def remove_cell_tree(rundir: RunDir, safe_id: str, vault_check=None) -> Path:
    """Delete ``work/{safe_id}`` — THE single delete verb (§3.10.1).

    prune, evict, sweep and zombie harvest all funnel through here.

    ``vault_check``: zero-arg callable returning truthy when the cell's paid
    bytes are secured in vault (harvest meta verified / staged). A falsy
    return means paid bytes are unharvested → the delete is refused with
    ``BlockedDelete`` and a warn note lands in the ledger (the §3.10.1
    "paid tree ∧ no vault meta → block + note" hard gate). ``None`` means the
    caller asserts the tree carries no paid bytes — use with care.

    Always emits a note event; returns the (former) cell path.
    """
    cell = rundir.work(safe_id)
    try:
        with locks.flock(rundir.cell_lock_path(safe_id),
                         exclusive=True, blocking=False):
            # Delete-under-lock (R21): a probe-only check leaves a TOCTOU —
            # a racer acquiring between probe and rmtree loses its lock
            # inode and a fresh lock double-owns the cell. The lock is
            # HELD through vault_check + rmtree; a live cell's hold makes
            # the NB acquire raise WouldBlock — the loud refusal.
            if vault_check is not None and not vault_check():
                _emit_note(
                    rundir,
                    f"remove_cell_tree BLOCKED for {safe_id}: paid tree "
                    f"without vault meta — harvest before delete",
                    level="warn", safe_id=safe_id,
                )
                msg = (
                    f"{safe_id}: paid cell tree with no vault meta — "
                    f"refusing delete (harvest first)"
                )
                raise BlockedDelete(msg)
            if cell.exists():
                shutil.rmtree(cell)
                with suppress(OSError):
                    fsutil.fsync_dir(cell.parent)
    except locks.WouldBlock:
        _emit_note(
            rundir,
            f"remove_cell_tree BLOCKED for {safe_id}: cell lock held — "
            f"live cell, refusing delete (R21)",
            level="warn", safe_id=safe_id,
        )
        raise BlockedDelete(
            f"{safe_id}: cell lock held — refusing delete (R21: rmtree "
            f"kills the lock inode and a fresh lock double-owns the cell)")
    _emit_note(rundir, f"remove_cell_tree: {safe_id}", safe_id=safe_id)
    return cell
