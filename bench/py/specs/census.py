"""census — the lake audit spec: every manifested cell, zero paid work.

The first real spec over the trizone lake (Phase 3): proves the full
kernel pipeline — items from the live catalog, canon gate, freeze_plan,
cell locks, needs domain, executor, claims — without touching the paid
surface.

    bench run census            # all catalog cells
    bench plan census           # dedup coverage quote, no run

Stages per cell:

- ``probe``   — lake.is_complete(idc) (the §3.10.3 read predicate) plus a
  non-blocking ClaimLease acquire/release on the cell's own (idc,arm,
  variant) key: the paid mutex mechanics exercised on a free path —
  contested claims are a metric, never an error. Statuses: ok (complete),
  partial (raw tier only — no extracted layer to verify), skip (no cell
  dir, or the empty anchor dir register seeds for skeletons — a seed is
  not damage), error (payload present but torn).
- ``verify``  — needs probe.ok; deterministic spread-sample of mtree.txt
  file rows rehashed against extracted/ bytes (``sample`` param, default
  4). Missing mtree -> clean; any mismatch/missing member -> fail.
"""
from __future__ import annotations

import contextlib
import hashlib
import json

from kernel import claims, lake
from kernel.spec import Param, Spec, Stage


def _items():
    """The census frame = the live lake catalog. Called once per spec
    load (compile_checks materializes it) — `bench run`/`bench plan`
    always see the catalog as of invocation."""
    cat = lake.LakeCatalog.load()
    return [
        {"id": idc}
        for idc, _row in sorted(cat.rows().items())
    ]


def _claim_probe(ctx):
    """NB acquire/release on the cell's own claim key; returns True/False
    or None when disabled by param."""
    if not ctx.params.get("claim", True):
        return None
    lease = claims.ClaimLease(ctx.idc, arm=ctx.arm, variant=ctx.variant)
    got = bool(lease.acquire(blocking=False))
    if got:
        lease.release()
    return got


def _probe(ctx):
    cell = lake.cell_dir(ctx.idc)
    if not cell.is_dir():
        ctx.emit({"stage": "probe", "metric": "lake_cell",
                  "present": 0, "complete": 0})
        return "skip"
    meta_path = cell / "meta.json"
    has_raw = (cell / "raw").exists()
    has_ext = (cell / "extracted").exists()
    if not meta_path.exists() and not has_raw and not has_ext:
        # Empty anchor dir — register seeds one per skeleton. A seed is
        # not a torn cell: nothing to verify, nothing broken.
        ctx.emit({"stage": "probe", "metric": "lake_cell",
                  "present": 1, "complete": 0, "reason": "skeleton",
                  "claim": _claim_probe(ctx)})
        return "skip"
    if has_raw and not has_ext:
        # raw tier only — real payload, nothing at the extracted layer.
        # A legitimate partial tier (catalog: raw_only), not damage;
        # terminal so resumes don't churn it.
        ctx.emit({"stage": "probe", "metric": "lake_cell",
                  "present": 1, "complete": 0, "reason": "raw_only",
                  "has_raw": 1, "claim": _claim_probe(ctx)})
        return "partial"
    complete = lake.is_complete(ctx.idc)
    meta = {}
    with contextlib.suppress(OSError, ValueError):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    ctx.emit({
        "stage": "probe", "metric": "lake_cell",
        "present": 1, "complete": int(complete),
        "n_files": meta.get("n_files"),
        "has_raw": int(has_raw),
        "claim": _claim_probe(ctx),
    })
    return "ok" if complete else "error"


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify(ctx):
    cell = lake.cell_dir(ctx.idc)
    mtree = cell / "mtree.txt"
    if not mtree.is_file():
        ctx.emit({"stage": "verify", "metric": "lake_verify",
                  "checked": 0, "reason": "no_mtree"})
        return "clean"
    files = []
    try:
        for line in mtree.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 4 and parts[3] == "file" and parts[2]:
                files.append((parts[0], parts[1], parts[2]))
    except OSError:
        return "error"
    if not files:
        ctx.emit({"stage": "verify", "metric": "lake_verify",
                  "checked": 0, "reason": "empty_mtree"})
        return "clean"
    n = max(1, int(ctx.params.get("sample", 4)))
    step = max(1, len(files) // n)
    pick = files[::step][:n]
    bad = []
    for rel, size, sha in pick:
        f = cell / "extracted" / rel
        try:
            if not f.is_file():
                bad.append({"rel": rel, "why": "missing"})
            elif f.stat().st_size != int(size):
                bad.append({"rel": rel, "why": "size"})
            elif _sha256(f) != sha:
                bad.append({"rel": rel, "why": "sha256"})
        except (OSError, ValueError) as exc:
            bad.append({"rel": rel, "why": f"{type(exc).__name__}"})
    ctx.emit({
        "stage": "verify", "metric": "lake_verify",
        "checked": len(pick), "files": len(files),
        "mismatch": len(bad),
        **({"bad": bad[:8]} if bad else {}),
    })
    return "fail" if bad else "ok"


spec = Spec(
    kind="census",
    params={
        "sample": Param(type=int, default=4),
        "claim": Param(type=bool, default=True),
    },
    items=_items,
    stages=[
        Stage("probe", _probe, status_class={
            "ok": "terminal", "partial": "terminal", "skip": "retriable",
            "error": "retriable"}),
        Stage("verify", _verify, needs=[("probe", {"ok"})],
              status_class={
                  "ok": "terminal", "fail": "terminal",
                  "clean": "terminal", "error": "retriable"}),
    ],
    lake=True,
)
