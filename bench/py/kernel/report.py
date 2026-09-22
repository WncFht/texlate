"""derive — the native run-report projection (§2.1; arch: index 投影 → run 报告).

``build_run_report(index, rundir_or_name, out_dir)`` regenerates one run's
report artifacts without re-executing a single cell:

    cells.jsonl   terminal cell events verbatim — the kernel's own event
                  schema, never a legacy records spelling — with $blob
                  offload markers resolved against the run's derived/blobs/
    cases.jsonl   the run's own file is authoritative (CaseSink); rebuilt
                  from the index cases table when the shard is absent
    report.md     human/agent summary: run identity, finished-event
                  wall_s/cost/counts, per-stage status tally, accounting
                  verdict

Everything written here is a rebuildable derived artifact: output lands in
the run's derived/ tree by default and never touches authored keep-tier
files (report.md at run root is agent/spec prose — R27).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from kernel import events, fsutil, paths

__all__ = ["build_run_report"]


def _iso(ts) -> str | None:
    """epoch ts -> ISO-8601 UTC; anything else -> None."""
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(ts, UTC).isoformat()
    except (OverflowError, ValueError, OSError):
        return None


def _unblob(val, blob_dir: Path | None):
    """Resolve a {"$blob": sha, "$bytes": n} offload marker back to the
    payload under run derived/blobs/. Marker is kept verbatim when the blob
    file is unreadable — a projection must not invent data. Only the strict
    marker shape resolves."""
    if not (events.is_blob_marker(val) and blob_dir is not None):
        return val
    p = blob_dir / f"{val['$blob']}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return val


# --- event sources -------------------------------------------------------------


def _iter_index_events(index, etype: str, run: str | None = None):
    """Yield event dicts of one type from the index events mirror, in
    authoritative append order (line_no)."""
    cur = index.conn.execute(
        "SELECT payload FROM events WHERE type=? ORDER BY line_no", (etype,)
    )
    for (payload,) in cur:
        try:
            ev = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if not isinstance(ev, dict):
            continue
        if run is not None and ev.get("run") != run:
            continue
        yield ev


def _iter_shard_events(rundir: Path | None, etype: str):
    """Yield event dicts of one type from a run dir's events.jsonl shard.

    Shard lines are re-validated on read — the shard is dual-written data,
    not a validated view, so a torn or hand-edited line must not reach the
    projections."""
    if rundir is None:
        return
    p = rundir / "events.jsonl"
    if not p.is_file():
        return
    for _ln, ev, _raw in events.iter_jsonl(p):
        if not isinstance(ev, dict) or ev.get("type") != etype:
            continue
        try:
            events.validate(ev)
        except events.EventError:
            continue
        yield ev


def _cell_events(index, info: dict) -> list[dict]:
    """Terminal-cell source: prefer the run shard (§3.3 dual-write makes it
    authoritative even without an index run row); fall back to the index
    events mirror filtered by run name."""
    rdir = info["rundir"]
    if rdir is not None and (rdir / "events.jsonl").is_file():
        return list(_iter_shard_events(rdir, events.T_CELL))
    return list(_iter_index_events(index, events.T_CELL, run=info["run"]))


def _last_typed(index, info: dict, etype: str) -> dict | None:
    """Last event of a type for this run (finished, ...)."""
    rdir = info["rundir"]
    if rdir is not None and (rdir / "events.jsonl").is_file():
        it = _iter_shard_events(rdir, etype)
    else:
        it = _iter_index_events(index, etype, run=info["run"])
    last = None
    for ev in it:
        last = ev
    return last


# --- run resolution -------------------------------------------------------------


def _run_row(index, run: str) -> dict | None:
    r = index.conn.execute(
        "SELECT run,run_seq,kind,date,slug,spec_hash,ts_start"
        " FROM runs WHERE run=?",
        (run,),
    ).fetchone()
    return dict(r) if r else None


def _run_row_by_dir(index, kind: str, date: str, slug: str) -> dict | None:
    r = index.conn.execute(
        "SELECT run,run_seq,kind,date,slug,spec_hash,ts_start"
        " FROM runs WHERE kind=? AND date=? AND slug=?",
        (kind, date, slug),
    ).fetchone()
    return dict(r) if r else None


def _resolve(index, rundir_or_name) -> dict:
    """Normalize a run reference to {run, kind, date, slug, rundir, row}.

    A directory inside runs/{kind}/{date}/{slug} resolves by identity
    triple; any other existing dir is taken as-is with its basename as the
    run name; a bare name resolves via the index runs table (rundir is then
    the canonical runs/ path when it exists).
    """
    p = Path(rundir_or_name)
    if p.is_dir():
        try:
            parts = p.resolve().relative_to(paths.runs_dir()).parts
        except ValueError:
            parts = ()
        if len(parts) >= 3:
            kind, date, slug = parts[:3]
            row = _run_row_by_dir(index, kind, date, slug)
            rundir = paths.run_dir(kind, date, slug)
            name = row["run"] if row else f"{kind}-{date}-{slug}"
            return {
                "run": name, "kind": kind, "date": date, "slug": slug,
                "rundir": rundir if rundir.is_dir() else p, "row": row,
            }
        name = p.name
        row = _run_row(index, name)
        return {
            "run": row["run"] if row else name,
            "kind": row["kind"] if row else None,
            "date": row["date"] if row else None,
            "slug": row["slug"] if row else None,
            "rundir": p, "row": row,
        }
    name = str(rundir_or_name)
    row = _run_row(index, name)
    if row is not None:
        rd = paths.run_dir(row["kind"], row["date"], row["slug"])
        return {
            "run": row["run"], "kind": row["kind"], "date": row["date"],
            "slug": row["slug"],
            "rundir": rd if rd.is_dir() else None, "row": row,
        }
    return {"run": name, "kind": None, "date": None, "slug": None,
            "rundir": None, "row": None}


# --- file writers -----------------------------------------------------------------


def _write_bytes(path: Path, data: bytes, files: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fsutil.atomic_write(path, data)
    files.append(path)


def _write_jsonl(path: Path, rows: list, files: list) -> None:
    data = "".join(
        json.dumps(r, ensure_ascii=False) + "\n" for r in rows
    ).encode("utf-8")
    _write_bytes(path, data, files)


def _write_text(path: Path, text: str, files: list) -> None:
    _write_bytes(path, text.encode("utf-8"), files)


# --- report -------------------------------------------------------------------


def _write_cases(index, info: dict, out: Path, files: list) -> None:
    """cases.jsonl: the run dir's own file is authoritative; fall back to
    the index cases table (cell_queued payloads)."""
    dst = out / "cases.jsonl"
    rdir = info["rundir"]
    if rdir is not None and (rdir / "cases.jsonl").is_file():
        _write_bytes(dst, (rdir / "cases.jsonl").read_bytes(), files)
        return
    rows = [
        json.loads(r["payload"])
        for r in index.conn.execute(
            "SELECT payload FROM cases WHERE run=? ORDER BY seq",
            (info["run"],),
        )
    ]
    _write_jsonl(dst, rows, files)


def _tally_lines(rows: list[dict]) -> list[str]:
    """Per-stage × status tally for report.md."""
    tally: dict[tuple[str, str], int] = {}
    for ev in rows:
        key = (str(ev.get("stage") or "?"), str(ev.get("status") or "?"))
        tally[key] = tally.get(key, 0) + 1
    lines = ["| stage | status | n |", "| --- | --- | --- |"]
    for (stage, status), n in sorted(tally.items()):
        lines.append(f"| {stage} | {status} | {n} |")
    return lines


def _report_md(info: dict, rows: list[dict], fin: dict | None,
               accounting: dict | None) -> str:
    row = info["row"] or {}
    lines = [
        f"# {info['run']} — derived report",
        "",
        (
            f"- identity: kind={info['kind']} date={info['date']}"
            f" slug={info['slug']} run_seq={row.get('run_seq')}"
            f" spec_hash={row.get('spec_hash')}"
        ),
        f"- cells: {len(rows)} terminal event(s)",
    ]
    if fin is not None:
        lines.append(
            f"- finished: {_iso(fin.get('ts'))} wall_s={fin.get('wall_s')}"
            f" cost_usd={fin.get('cost_usd')}"
        )
        if fin.get("counts") is not None:
            lines.append(
                "- counts: "
                + json.dumps(fin["counts"], ensure_ascii=False,
                             sort_keys=True)
            )
    if accounting is not None:
        lines.append(
            f"- accounting: {'ok' if accounting.get('ok') else 'BROKEN'}"
            f" (plan={accounting.get('plan')}"
            f" queued={accounting.get('queued')}"
            f" terminal={accounting.get('terminal')})"
        )
    lines += ["", "## status tally", ""]
    lines += _tally_lines(rows)
    cats: dict[str, int] = {}
    for ev in rows:
        if ev.get("cat"):
            cats[str(ev["cat"])] = cats.get(str(ev["cat"]), 0) + 1
    if cats:
        lines += ["", "## gate cats", ""]
        for cat, n in sorted(cats.items()):
            lines.append(f"- {cat}: {n}")
    return "\n".join(lines) + "\n"


def build_run_report(index, rundir_or_name, out_dir, *,
                     accounting: dict | None = None) -> dict:
    """Regenerate one run's report artifacts into out_dir.

    rundir_or_name: a run dir path (any dir inside runs/{kind}/{date}/{slug})
    or a run name resolvable via the index runs table. Writes cells.jsonl +
    cases.jsonl + report.md directly into out_dir (created if missing).
    Returns {files: [str...], rows: n, run: name}.
    """
    info = _resolve(index, rundir_or_name)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []

    rdir = info["rundir"]
    blob_dir = (
        rdir / "derived" / "blobs"
        if rdir is not None and (rdir / "derived" / "blobs").is_dir()
        else None
    )
    rows = []
    for ev in _cell_events(index, info):
        row = dict(ev)
        if row.get("metrics"):
            row["metrics"] = _unblob(row["metrics"], blob_dir)
        if row.get("errors"):
            row["errors"] = _unblob(row["errors"], blob_dir)
        rows.append(row)
    _write_jsonl(out / "cells.jsonl", rows, files)
    _write_cases(index, info, out, files)
    fin = _last_typed(index, info, events.T_FINISHED)
    _write_text(out / "report.md", _report_md(info, rows, fin, accounting),
                files)
    return {
        "files": [str(f) for f in files],
        "rows": len(rows),
        "run": info["run"],
    }
