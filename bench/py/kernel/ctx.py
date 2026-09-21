"""ctx — the object handed to stage functions (design §4).

    def do_xlat(ctx):
        src = ctx.src_path()                    # read-only lake projection
        ws = ctx.workspace()                    # scratch dir, wiped per call
        rec = ctx.upstream_rec("parse")         # last DONE records row
        zh = ctx.paper_dir() / "zh.mock"        # mutating tree, writable-probed
        ctx.emit({"metrics": {"seg": 42}})      # folded into the terminal row
        ctx.emit_note("recovered 2 spans", level="warn")
        return "ok"                             # or {"status":..., ...}

Hard guarantees:

- ``gateway()`` is the ONLY path to the paid client — its construction IS
  the paid assertion (no factory → RuntimeError, no exceptions).
- ``paper_dir``/``workspace``/``asset_dir`` are probe-write checked before
  handoff — a vault-fused (0444) tree can never silently pass for a
  writable workspace (§3.10.2 mutating-tree gate).
- ``emit`` buffers author rows; the kernel flushes them in ONE emit_batch
  with the terminal cell event — a torn row can never exist (§3.2).
- ``upstream_rec`` only ever returns DONE-status records rows in the needs
  domain — kernel masks (dedup/claimed/…) never leak to instruments.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from kernel import claims, events, fsutil, idnorm, lake, locks, paid as paidmod

__all__ = ["Ctx"]


class Ctx:
    """Per-cell author context.

    Positionals: ``run`` (run name str or RunDir), ``cell`` (plan dict),
    ``index`` (a kernel Index created in THIS thread — sqlite conns are
    thread-bound), ``spec`` (the Spec).

    Everything else the kernel injects by keyword: ``rundir`` (RunDir —
    required for work paths when ``run`` is a plain string), ``factory``
    (GatewayFactory | None), ``outbox`` (list collecting emit() rows —
    flushed with the terminal batch), ``emit_note_fn`` (callable
    (text, level) -> None, defaults to buffering note dicts in outbox).
    """

    def __init__(self, run, cell: dict, index, spec, *, rundir=None,
                 factory=None, outbox=None, emit_note_fn=None):
        self.spec = spec
        self.cell = cell
        self.index = index
        self.rundir = rundir if rundir is not None else (
            run if hasattr(run, "work") else None)
        self.run = getattr(run, "run", run)
        self.factory = factory
        self._outbox = outbox if outbox is not None else []
        self._emit_note_fn = emit_note_fn
        # -- cell fields, promoted ---------------------------------------------------
        self.id = str(cell.get("id"))
        self.idc = str(cell.get("idc"))
        self.arm = str(cell.get("arm", "-"))
        self.up = str(cell.get("up", "-"))
        self.variant = str(cell.get("variant", "-"))
        self.stage = str(cell.get("stage"))
        self.safe = idnorm.safe_id(self.idc)
        # merged params: resolved run params ← cell-level overrides
        self.params = dict(cell.get("run_params") or {})
        self.params.update(cell.get("params") or {})
        # paid-session scratch (PaidSession stashes claim fate / last usage)
        self.claim_fate = None
        self.claim_lease = None
        self.last_cost_usd = 0.0
        self.last_usage = None
        self._session = None
        self.stage_obj = spec.stage(self.stage) if spec is not None else None

    # --- upstream records ------------------------------------------------------------

    def upstream_rec(self, stage: str, *, statuses=None):
        """Last records row for this cell key at ``stage``.

        Default: last DONE-status row (the '末条胜行' — dedup/claimed masks
        and retriable rows are looked through). Domain = this run ∪
        spec.foreign_runs. metrics/errors are returned json-decoded.
        Returns None when no such row exists.
        """
        if self.index is None:
            return None
        domain = {self.run}
        if self.spec is not None:
            domain.update(self.spec.foreign_runs or [])
        if statuses is None:
            statuses = tuple(sorted(events.STATUS_DONE))
        elif isinstance(statuses, str):
            statuses = (statuses,)
        sql = ("SELECT run,seq,id,idc,arm,up,variant,stage,status,cat,sig,"
               "code,fp,dur_s,metrics,errors,ts FROM records "
               "WHERE idc=? AND arm=? AND up=? AND variant=? AND stage=?")
        args: list = [self.idc, self.arm, self.up, self.variant, stage]
        sql += f" AND run IN ({','.join('?' * len(domain))})"
        args += sorted(domain)
        sql += f" AND status IN ({','.join('?' * len(statuses))})"
        args += list(statuses)
        sql += " ORDER BY rowid DESC LIMIT 1"
        cur = self.index.conn.execute(sql, args)
        row = cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        for col in ("metrics", "errors"):
            v = d.get(col)
            if isinstance(v, str):
                try:
                    import json
                    d[col] = json.loads(v)
                except ValueError:
                    pass
        return d

    # --- paths ------------------------------------------------------------------------

    def paper_dir(self) -> Path:
        """work/{safe_id} — this id's per-run work dir (probe-write gated)."""
        if self.rundir is None:
            raise RuntimeError("ctx has no rundir — work paths unavailable")
        d = self.rundir.work(self.safe)
        d.mkdir(parents=True, exist_ok=True)
        self._assert_writable(d)
        return d

    def workspace(self, scratch: bool = True) -> Path:
        """paper_dir()/workspace — the paper's shared writable surface.

        SHARED across the paper's stages and arms: this is where
        inter-stage handoff lives (ingest writes ``src/``, transform reads
        it and writes ``zh/`` — the smoke spec's dataflow). Per-stage
        isolation is the instrument's own subdir choice.

        ``scratch=True`` gives a clean dir once per RUN, not per call —
        a ``.wsrun`` marker stamps the owning run name and a foreign or
        absent marker wipes the tree before handoff. Within a run the dir
        persists: wiping per call would destroy upstream stage output.
        ``scratch=False`` never wipes (even across runs).
        """
        d = self.paper_dir() / "workspace"
        if scratch:
            marker = d / ".wsrun"
            owner = None
            try:
                owner = marker.read_text(encoding="utf-8").strip()
            except OSError:
                pass
            if owner != self.run:
                if d.exists():
                    shutil.rmtree(d)
                d.mkdir(parents=True, exist_ok=True)
                marker.write_text(self.run, encoding="utf-8")
        d.mkdir(parents=True, exist_ok=True)
        self._assert_writable(d)
        return d

    def asset_dir(self, kind: str) -> Path:
        """paper_dir()/{kind}.{arm}[@{variant}] — the harvestable tree for
        one mutates kind (vault._work_dirname layout)."""
        from kernel import vault
        d = self.paper_dir() / vault._work_dirname(kind, self.arm, self.variant)
        return d

    def asset_dirs(self, kinds=None) -> dict:
        """{kind: dir} for every mutates-kind dir that exists with content
        — the harvest set (§3.5)."""
        if kinds is None and self.spec is not None:
            kinds = self.spec.mutating_kinds()
        out = {}
        base = self.paper_dir()
        for k in kinds or []:
            from kernel import vault
            d = base / vault._work_dirname(k, self.arm, self.variant)
            if d.is_dir() and any(p.is_file() for p in d.rglob("*")):
                out[k] = d
        return out

    def src_path(self) -> Path | None:
        """Read-only projection of the lake cell's extracted tree into
        paper_dir()/src (hardlink farm). None when the lake can't provide
        the id."""
        cell_dir = lake.hydrate(self.idc)
        if cell_dir is None:
            return None
        extracted = Path(cell_dir) / "extracted"
        if not extracted.is_dir():
            extracted = Path(cell_dir)
        dest = self.paper_dir() / "src"
        if dest.exists():
            shutil.rmtree(dest)
        fsutil.hardlink_farm(extracted, dest)
        return dest

    def lake_path(self, idc: str | None = None) -> Path | None:
        """Path to the lake cell dir for ``idc`` (default: this cell).
        Hydrates on demand; None when unfetchable."""
        return lake.hydrate(idc or self.idc)

    # --- paid surface -------------------------------------------------------------------

    def claim(self):
        """The (idc,arm,variant) ClaimLease — the paid mutex. Caller picks
        acquire/release or the context-manager form."""
        return claims.ClaimLease(self.idc, arm=self.arm, variant=self.variant)

    def paid_slot(self, nslots: int = 4, blocking: bool = True, **kw):
        """One global paid slot — the ≤4 concurrent-request ceiling."""
        return locks.paid_slot(nslots=nslots, blocking=blocking, **kw)

    def gateway(self):
        """The paid channel — LAZY: first call mints a PaidSession off the
        run's GatewayFactory. No factory → RuntimeError (the paid
        assertion)."""
        if self._session is not None:
            return self._session
        if self.factory is None:
            raise RuntimeError(
                "paid gateway requested but no gateway_factory was wired "
                "(construction IS the paid assertion)")
        self._session = self.factory.session(self)
        return self._session

    # --- emit ---------------------------------------------------------------------------

    def emit(self, row):
        """Buffer one author row — merged into the terminal cell event by
        the kernel. Whitelisted keys fold directly (metrics update,
        errors extend, sig/code/dur_s/cat last-wins); cell-identity and
        'status'/'fp' keys drop (they're framework-owned); every other
        key folds into ``metrics`` so rows like {metric, chars, lines}
        land whole. A dict carrying 'type' is validated + buffered as a
        verbatim event instead."""
        if isinstance(row, dict) and "type" in row:
            ev = events.make_event(row["type"], **{k: v for k, v in row.items()
                                                  if k != "type"})
            events.validate(ev)
            self._outbox.append(ev)
            return ev
        self._outbox.append(dict(row or {}))
        return row

    def emit_note(self, text: str, level: str = "info"):
        """Author → note event. Buffered with the cell batch when no
        emit_note_fn is wired."""
        if level not in events.NOTE_LEVELS:
            raise ValueError(f"bad note level {level!r}")
        if self._emit_note_fn is not None:
            return self._emit_note_fn(text, level)
        ev = events.make_event(events.T_NOTE, run=self.run, seq=None,
                               text=str(text), level=level)
        self._outbox.append(ev)
        return ev

    # --- internals ------------------------------------------------------------------------

    @staticmethod
    def _assert_writable(d: Path):
        bad = fsutil.has_nonwritable(d)
        if bad:
            raise PermissionError(
                f"{d}: {len(bad)} non-writable entries — a vault-fused tree "
                f"leaked into the mutating workspace (first: {bad[0]})")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"Ctx(run={self.run!r}, cell={self.idc}/{self.arm}/"
                f"{self.up}/{self.variant}/{self.stage})")
