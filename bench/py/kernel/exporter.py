"""export --legacy — project the ledger/index back into legacy run layouts (§5).

This is a READ-SIDE adapter: it consumes cell events (via the index or a run
dir's events.jsonl shard) and emits the file shapes old consumers expect.

    project_records(index, run=None, stage=None) -> list[dict]
        terminal cell events -> legacy records rows:
        {id, stage, arm, upstream, code, status, dur_s, metrics, errors, sig,
         queue_wait_s?}
        id = ORIGINAL spelling, never canon — the read-side asymmetry is
        deliberate (§3.7): non-canon matches are an audit signal, so the
        projection must not silently rewrite the writer's spelling.
        upstream <- up ("-" sentinel -> ""), code <- code, sig/errors
        verbatim. When the event carries a kernel `cat` but no errors, a
        single {code: cat, cat: cat} error row is synthesized so the
        errors[0] findings channel still carries the gate reason.
        Eval cells (stage in index.eval_stages or ev.eval) project to the
        same row shape — they form the eval-records lane at file level
        (old consumers kept eval-records.jsonl outside records/).

    export_run(index, rundir_or_name, out_dir, mode='auto') -> dict
        soak family: out/{run}/records/{stage}.jsonl + cases.jsonl
                     + run_meta.json + work/{wid}/{src,zh,splice}
        e2e family:  out/{run}/{records.jsonl, results.json, matrix.md,
                     summary.md, run_meta.json}
        mode: 'auto' (run kind starting with 'e2e' -> e2e, else soak),
              'soak'/'stagerun', 'e2e'/'flat'.
        returns {files: [str...], rows: n, run: name, family: ...}

    export_all(index, out_dir) -> dict   # every registered run -> out/{run}/

Work farm: fsutil.hardlink_farm each work cell's src/zh/splice trees
(read-only projection, inode-shared, EXDEV falls back to a-w copies).
A lone `zh.{arm}[@{variant}]` projects to the legacy `zh` name; several
qualified dirs keep their own names — silently letting one arm overwrite
another is worse than a non-legacy dirname. `src@` lake symlinks are
dereferenced by the farm itself (scandir follows the link root).

Event source: the run dir's events.jsonl shard when it exists (dual-written
in the emit critical section, §3.3 — it is authoritative for the run even
when the index lacks the run row), else the index events mirror filtered
by run name.
"""
from __future__ import annotations

import errno
import json
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from kernel import events, fsutil, paths

# "empty" spellings for arm/up/variant dimensions: "-" is the kernel
# sentinel; "" and None cover legacy/imported rows.
_EMPTY = (None, "-", "")

# Case-level keys lifted from an arm's metrics blob to the record top level
# in the e2e projection (observed fields in legacy e2e records.jsonl rows).
_CASE_LIFT = ("main", "route", "layer")

# Work-cell subdirs that join the legacy work/{wid}/ projection.
_WORK_KINDS = ("src", "zh", "splice")


# --- small helpers ------------------------------------------------------------


def _iso(ts) -> str | None:
    """epoch ts -> ISO-8601 UTC; anything else -> None."""
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None
    return datetime.fromtimestamp(ts, UTC).isoformat()


def _upstream(up) -> str:
    """event `up` -> legacy `upstream` ("-" sentinel flattens to "")."""
    return "" if up in _EMPTY else str(up)


def _unblob(val, blob_dir: Path | None):
    """Resolve a {"$blob": sha} metrics/errors offload marker back to the
    payload stored under run derived/blobs/. Marker is kept verbatim when the
    blob file is unreadable — a projection must not invent data."""
    if not (
        isinstance(val, dict)
        and isinstance(val.get("$blob"), str)
        and blob_dir is not None
    ):
        return val
    p = blob_dir / f"{val['$blob']}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return val


def _legacy_row(ev: dict, blob_dir: Path | None = None) -> dict:
    """One terminal cell event -> one legacy records row.

    Append-ledger semantics: every cell event is a row; consumers apply
    last-write-wins on (id, arm, upstream) exactly like the old files.
    """
    errs = _unblob(ev.get("errors") or [], blob_dir)
    if not errs and ev.get("cat"):
        # Kernel-gated cells (dedup/claimed/regen_gate/...) have no
        # instrument errors — surface the gate cat in errors[0] like
        # stagerun's gate_rec did, so triage/fixloop filters still see it.
        errs = [{"code": ev["cat"], "cat": ev["cat"], "payload": None}]
    row = {
        "id": ev.get("id"),  # ORIGINAL spelling — never canon (§3.7)
        "stage": ev.get("stage"),
        "arm": ev.get("arm"),
        "upstream": _upstream(ev.get("up")),
        "code": ev.get("code") or "",
        "status": ev.get("status"),
        "dur_s": ev.get("dur_s") or 0.0,
        "metrics": _unblob(ev.get("metrics") or {}, blob_dir),
        "errors": errs,
        "sig": ev.get("sig") or "",
    }
    if ev.get("queue_wait_s") is not None:
        row["queue_wait_s"] = ev["queue_wait_s"]
    return row


def _is_eval_cell(index, ev: dict) -> bool:
    """Eval lane: stage declared eval by the Index caller, or a row the
    import path tagged eval=1 (imports bypass the cell key whitelist)."""
    if ev.get("eval"):
        return True
    stages = getattr(index, "eval_stages", None) or ()
    return ev.get("stage") in stages


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
    """Yield event dicts of one type from a run dir's events.jsonl shard."""
    if rundir is None:
        return
    p = rundir / "events.jsonl"
    if not p.is_file():
        return
    for _ln, ev, _raw in events.iter_jsonl(p):
        if isinstance(ev, dict) and ev.get("type") == etype:
            yield ev


def _cell_events(index, info: dict) -> list[dict]:
    """Terminal-cell source for export: prefer the run shard (§3.3 dual-write
    makes it authoritative even without an index run row); fall back to the
    index events mirror filtered by run name."""
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


def _family(mode: str, kind: str | None) -> str:
    m = (mode or "auto").lower()
    if m == "auto":
        return (
            "e2e"
            if str(kind or "").lower().replace("_", "-").startswith("e2e")
            else "soak"
        )
    if m in ("e2e", "flat"):
        return "e2e"
    if m in ("soak", "stagerun", "stage"):
        return "soak"
    msg = f"unknown export mode {mode!r}"
    raise ValueError(msg)


def _blob_dir(index, run: str | None) -> Path | None:
    """run's derived/blobs dir (metrics/errors offload target) when known."""
    if not run:
        return None
    row = _run_row(index, run)
    if not row:
        return None
    d = paths.run_dir(row["kind"], row["date"], row["slug"]) / "derived" / "blobs"
    return d if d.is_dir() else None


# --- public projection API -------------------------------------------------------


def _project(index, run, stage, eval_only: bool) -> list[dict]:
    blob_dirs: dict[str, Path | None] = {}
    rows = []
    for ev in _iter_index_events(index, events.T_CELL, run=run):
        if stage is not None and ev.get("stage") != stage:
            continue
        if eval_only and not _is_eval_cell(index, ev):
            continue
        rname = ev.get("run")
        if rname not in blob_dirs:
            blob_dirs[rname] = _blob_dir(index, rname)
        rows.append(_legacy_row(ev, blob_dirs[rname]))
    return rows


def project_records(index, run=None, stage=None) -> list[dict]:
    """events -> legacy records rows.

    Every terminal cell event yields one row in ledger order; filter by
    run name and/or stage name. `id` keeps the writer's original spelling
    (§3.7 read-side asymmetry). Eval cells are included — the caller splits
    the lane by stage/eval_stages if it needs the records/-only view.
    """
    return _project(index, run, stage, eval_only=False)


def project_eval_records(index, run=None) -> list[dict]:
    """events -> eval_records rows (same projected shape; eval lane only)."""
    return _project(index, run, None, eval_only=True)


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


def _write_json(path: Path, obj, files: list) -> None:
    _write_bytes(
        path,
        (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8"),
        files,
    )


def _write_text(path: Path, text: str, files: list) -> None:
    _write_bytes(path, text.encode("utf-8"), files)


def _link_or_copy(src: Path, dst: Path, files: list) -> None:
    """Hardlink src -> dst (same-inode projection); EXDEV falls back to
    copyfile so cross-volume exports still work."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.copyfile(src, dst)
    files.append(dst)


# --- piece exporters --------------------------------------------------------------


def _export_cases(index, info: dict, out: Path, files: list) -> None:
    """cases.jsonl: the run dir's own file is authoritative (CaseSink
    平移); fall back to the index cases table (cell_queued payloads)."""
    dst = out / "cases.jsonl"
    rdir = info["rundir"]
    if rdir is not None and (rdir / "cases.jsonl").is_file():
        _link_or_copy(rdir / "cases.jsonl", dst, files)
        return
    rows = [
        json.loads(r["payload"])
        for r in index.conn.execute(
            "SELECT payload FROM cases WHERE run=? ORDER BY seq",
            (info["run"],),
        )
    ]
    _write_jsonl(dst, rows, files)


def _export_meta(index, info: dict, out: Path, files: list) -> None:
    """run_meta.json: union shape — stagerun fields (created_at/invocations/
    finished_at) + kernel run identity + finished-event tallies."""
    row = info["row"] or {}
    invocations = []
    rdir = info["rundir"]
    if rdir is not None and (rdir / "invocations.jsonl").is_file():
        for _ln, ev, _raw in events.iter_jsonl(rdir / "invocations.jsonl"):
            if isinstance(ev, dict):
                invocations.append(ev)
    meta = {
        "tool": info["run"],
        "name": info["run"],
        "kind": info["kind"],
        "run_seq": row.get("run_seq"),
        "spec_hash": row.get("spec_hash"),
        "date": info["date"],
        "slug": info["slug"],
        "created_at": _iso(row.get("ts_start")),
        "started_at": _iso(row.get("ts_start")),
        "invocations": invocations,
        "exported_at": _iso(time.time()),
        "exported_by": "kernel.exporter",
    }
    fin = _last_typed(index, info, events.T_FINISHED)
    if fin is not None:
        meta["finished_at"] = _iso(fin.get("ts"))
        meta["ended_at"] = meta["finished_at"]  # e2e-shape alias
        meta["wall_s"] = fin.get("wall_s")
        meta["counts"] = fin.get("counts")
        meta["cost_usd"] = fin.get("cost_usd")
    _write_json(out / "run_meta.json", meta, files)


def _kind_dirs(wdir: Path, kind: str) -> list[Path]:
    """Subdirs of a work cell dir for one asset kind.

    `src`/`src@` answer for src (src@ is the lake symlink spelling);
    zh/splice match their qualified `kind.{arm}[@{variant}]` forms too.
    is_dir() follows the src@ link — a dangling link simply isn't a dir.
    """
    out = []
    try:
        entries = sorted(wdir.iterdir())
    except OSError:
        return out
    for e in entries:
        if kind == "src":
            ok = e.name in ("src", "src@")
        else:
            ok = e.name == kind or e.name.startswith(f"{kind}.")
        if ok and e.is_dir():
            out.append(e)
    return out


def _farm_work(rundir: Path, out: Path, files: list) -> None:
    """work/{wid}/{src,zh,splice} hardlink-farmed from the run work/ tree.

    Single candidate -> legacy bare name (zh.mock -> zh). Several candidates
    -> each keeps its qualified name; one arm must never silently overwrite
    another in a disaster-recovery projection. Non-asset subtrees
    (xlat-state.*/state/build.*/_texmf) are not part of the legacy layout.
    """
    work = rundir / "work"
    if not work.is_dir():
        return
    for wdir in sorted(work.iterdir()):
        if not wdir.is_dir() or wdir.name.startswith(("_", ".")):
            continue
        for kind in _WORK_KINDS:
            dirs = _kind_dirs(wdir, kind)
            if not dirs:
                continue
            if len(dirs) == 1:
                targets = ((dirs[0], kind),)
            else:
                targets = tuple((d, d.name) for d in dirs)
            for src_dir, name in targets:
                dst = out / "work" / wdir.name / name
                fsutil.hardlink_farm(src_dir, dst)
                files.append(dst)


def _export_soak(index, info: dict, out: Path) -> dict:
    files: list[Path] = []
    rdir = info["rundir"]
    blobs = (
        rdir / "derived" / "blobs"
        if rdir is not None and (rdir / "derived" / "blobs").is_dir()
        else None
    )
    by_stage: dict[str, list[dict]] = {}
    eval_rows: list[dict] = []
    n = 0
    for ev in _cell_events(index, info):
        row = _legacy_row(ev, blobs)
        if _is_eval_cell(index, ev):
            eval_rows.append(row)
        else:
            by_stage.setdefault(str(ev.get("stage") or "unknown"), []).append(row)
        n += 1
    for stage in sorted(by_stage):
        _write_jsonl(out / "records" / f"{stage}.jsonl", by_stage[stage], files)
    if eval_rows:
        _write_jsonl(out / "eval-records.jsonl", eval_rows, files)
    _export_cases(index, info, out, files)
    _export_meta(index, info, out, files)
    if rdir is not None:
        _farm_work(rdir, out, files)
    return {"files": files, "rows": n}


def _cond_key(ev: dict) -> str:
    """Per-case column key for the e2e projection. variant carries the e2e
    condition dimension (§3.1); both dimensions non-trivial -> arm@variant
    so no (arm,variant) pair can collide into another."""
    arm, var = ev.get("arm"), ev.get("variant")
    arm_ok, var_ok = arm not in _EMPTY, var not in _EMPTY
    if arm_ok and var_ok:
        return f"{arm}@{var}"
    if var_ok:
        return str(var)
    return str(arm) if arm_ok else "-"


def _verdict_mark(metrics, status) -> str:
    """Matrix cell mark: metrics.verdict.status > metrics.status > cell status."""
    if isinstance(metrics, dict):
        v = metrics.get("verdict")
        if isinstance(v, dict) and v.get("status") is not None:
            return str(v["status"])
        if metrics.get("status") is not None:
            return str(metrics["status"])
    return str(status if status is not None else "?")


def _export_e2e(index, info: dict, out: Path) -> dict:
    files: list[Path] = []
    rdir = info["rundir"]
    blobs = (
        rdir / "derived" / "blobs"
        if rdir is not None and (rdir / "derived" / "blobs").is_dir()
        else None
    )
    cases: dict[str, dict] = {}
    statuses: dict[tuple, object] = {}
    order: list[str] = []
    eval_rows: list[dict] = []
    for ev in _cell_events(index, info):
        if _is_eval_cell(index, ev):
            eval_rows.append(_legacy_row(ev, blobs))
            continue
        pid = ev.get("id")
        row = cases.get(pid)
        if row is None:
            row = {"id": pid, "status": None}
            cases[pid] = row
            order.append(pid)
        ck = _cond_key(ev)
        metrics = _unblob(ev.get("metrics") or {}, blobs)
        row[ck] = metrics
        statuses[(pid, ck)] = ev.get("status")
        row["status"] = ev.get("status")  # last-write-wins, like the old append账
        for k in _CASE_LIFT:
            if (
                row.get(k) is None
                and isinstance(metrics, dict)
                and metrics.get(k) is not None
            ):
                row[k] = metrics[k]
    recs = [cases[pid] for pid in order]
    _write_jsonl(out / "records.jsonl", recs, files)
    _write_json(out / "results.json", {pid: cases[pid] for pid in order}, files)

    lift = {"id", "status", *_CASE_LIFT}
    cols = sorted({k for r in cases.values() for k in r} - lift)
    mlines = [
        "| 工程 | main | " + " | ".join(cols) + " |",
        "| --- | --- | " + " | ".join("---" for _ in cols) + " |",
    ]
    for pid in sorted(cases):
        r = cases[pid]
        marks = [
            _verdict_mark(r.get(c), statuses.get((pid, c))) for c in cols
        ]
        mlines.append(
            "| " + " | ".join([str(pid), str(r.get("main") or "?"), *marks]) + " |"
        )
    _write_text(out / "matrix.md", "\n".join(mlines) + "\n", files)

    slines = [
        f"# {info['run']} — e2e legacy projection",
        "",
        f"- 样本：{len(cases)} 篇（run_seq={ (info['row'] or {}).get('run_seq') }）",
        "",
        "## cond 状态统计",
    ]
    for c in cols:
        tally: dict[str, int] = {}
        ran = 0
        for pid, r in cases.items():
            if c not in r:
                continue
            ran += 1
            mark = _verdict_mark(r[c], statuses.get((pid, c)))
            tally[mark] = tally.get(mark, 0) + 1
        slines.append(
            f"- **{c}**: "
            + " ".join(f"{k} {v}" for k, v in sorted(tally.items()))
            + f" /{ran}"
        )
    fin = _last_typed(index, info, events.T_FINISHED)
    if fin is not None and fin.get("counts") is not None:
        slines += [
            "",
            "- counts: "
            + json.dumps(fin["counts"], ensure_ascii=False, sort_keys=True),
        ]
    _write_text(out / "summary.md", "\n".join(slines) + "\n", files)

    if eval_rows:
        _write_jsonl(out / "eval-records.jsonl", eval_rows, files)
    _export_cases(index, info, out, files)
    _export_meta(index, info, out, files)
    return {"files": files, "rows": len(recs)}


# --- public export API -------------------------------------------------------------


def export_run(index, rundir_or_name, out_dir, mode: str = "auto") -> dict:
    """Export one run to out_dir/{run}/ in its legacy family layout.

    rundir_or_name: a run dir path (any dir inside runs/{kind}/{date}/{slug})
    or a run name resolvable via the index runs table. `run` slashes are
    flattened to "--" for the output dir name. Returns
    {files: [str...], rows: n, run, family}.
    """
    info = _resolve(index, rundir_or_name)
    fam = _family(mode, info["kind"])
    out = Path(out_dir) / str(info["run"]).replace("/", "--")
    out.mkdir(parents=True, exist_ok=True)
    res = _export_e2e(index, info, out) if fam == "e2e" else _export_soak(
        index, info, out
    )
    return {
        "files": [str(f) for f in res["files"]],
        "rows": res["rows"],
        "run": info["run"],
        "family": fam,
    }


def export_all(index, out_dir) -> dict:
    """Every run registered in the index -> its own out/{run}/ dir."""
    runs = [
        dict(r)
        for r in index.conn.execute(
            "SELECT run,kind,date,slug FROM runs ORDER BY run_seq"
        )
    ]
    files: list[str] = []
    rows = 0
    per_run = {}
    for r in runs:
        res = export_run(index, r["run"], out_dir)
        per_run[res["run"]] = {"rows": res["rows"], "family": res["family"]}
        files.extend(res["files"])
        rows += res["rows"]
    return {"files": files, "rows": rows, "runs": per_run}


__all__ = [
    "export_all",
    "export_run",
    "project_eval_records",
    "project_records",
]
