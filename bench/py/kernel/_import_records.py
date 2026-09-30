"""kernel._import_records — bench.db / worktree jsonl 源导入 (kernel.importer 拆分叶).

records 面两源驱动：

- ``import_benchdb`` — bench.db 五表 (records/eval_records/cases/cells)
  按 (table,run) 切 import run, run_seq 依 §3.3 (created_at -> path mtime
  -> name) 序铸造;
- ``import_jsonl_file`` — 工作树散账 records*.jsonl / cases.jsonl, 一文件
  一 ledger run, run_meta.json 的 started_at 锚定 shard 日期。

行级规整/转换/落账全在 ``_import_core``; 本叶只含源驱动与 run 序/日期解析。
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from kernel._import_core import (
    _commit,
    _ensure_import_run,
    _flush_quar,
    _load_quar_shas,
    _norm_db_raw,
    _norm_db_record,
    _norm_jsonl_row,
    _parse_ts,
    _prepare_run,
    _sha,
    _slugify,
    _stats,
    redact,
)
from kernel.events import iter_jsonl

# ---------------------------------------------------------------------------
# bench.db
# ---------------------------------------------------------------------------

_DB_TABLES = ("records", "eval_records", "cases", "cells")

_DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


def _run_sort_key(run: dict):
    """(started_at -> dir mtime -> run name) per §3.3. Timestamps sort
    NUMERICALLY — a lexical repr() inverts across digit-width boundaries
    and mixed ISO spellings (' ' vs 'T' separator) misorder."""
    ca = _parse_ts(run.get("created_at"))
    name = str(run.get("name") or "")
    if ca is not None:
        return (0, ca, name)
    p = run.get("path")
    if p:
        try:
            return (1, float(Path(p).stat().st_mtime), name)
        except OSError:
            pass
    return (2, 0.0, name)


def _run_date(run: dict) -> str:
    ca = run.get("created_at")
    if isinstance(ca, str) and len(ca) >= 10:
        return ca[:10]
    m = _DATE_RE.search(str(run.get("name") or ""))
    if m:
        return m.group(1)
    p = run.get("path")
    if p:
        try:
            mt = Path(p).stat().st_mtime
            return datetime.fromtimestamp(mt, tz=UTC).strftime("%Y-%m-%d")
        except OSError:
            pass
    return "undated"


def import_benchdb(db_path, index, registry=None, dry: bool = False) -> dict:
    """Import all five bench.db tables as per-(table,run) ledger runs.

    Run identity: 'import-<table>-r<run_id>-<slugified name>' — run_id is
    in the name because the db reuses names across source='live'/'archive'
    (e.g. two distinct 'soak-2026-09-18' runs). Runs are minted in
    (created_at -> path mtime -> name) order so run_seq approximates
    chronology.
    """
    stats = _stats()
    db_path = str(db_path)
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        existing = {
            r[0]
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        runs = {}
        if "runs" in existing:
            runs = {
                r["run_id"]: dict(r)
                for r in db.execute(
                    "SELECT run_id,name,source,kind,path,created_at FROM runs"
                )
            }
        groups = []
        for table in _DB_TABLES:
            if table not in existing:
                continue
            for (rid,) in db.execute(f"SELECT DISTINCT run_id FROM {table}"):  # noqa: S608 -- table 来自 _DB_TABLES 白名单迭代
                run = runs.get(rid) or {
                    "run_id": rid,
                    "name": f"run-{rid}",
                    "created_at": None,
                    "path": None,
                    "kind": "?",
                    "source": "?",
                }
                groups.append((_run_sort_key(run), table, rid))
        groups.sort(key=lambda g: (g[0], g[1], g[2]))

        quar_seen = _load_quar_shas()
        for _sk, table, rid in groups:
            run = runs.get(rid) or {"name": f"run-{rid}"}
            base = str(run.get("name") or f"run-{rid}")
            run_name = f"import-{table}-r{rid}-{_slugify(base)}"
            date = _run_date(run)
            slug = _slugify(f"{table}-r{rid}-{base}")
            run_ts = _parse_ts(run.get("created_at")) or 0.0
            run_seq, rdir, minted, rr = _ensure_import_run(
                index,
                run_name,
                date=date,
                slug=slug,
                spec_hash=f"benchdb:{table}:{rid}",
                dry=dry,
            )
            stats["runs"] += 1
            stats["runs_minted"] += int(minted)
            quar: list = []
            if rr is not None and index is not None and not dry:
                index.apply_events([rr])

            if table == "records":
                norm_fn = lambda row, _ts=run_ts: _norm_db_record(row, _ts)  # noqa: E731
            else:
                norm_fn = lambda row, _t=table, _ts=run_ts: _norm_db_raw(  # noqa: E731
                    _t, row, _ts
                )

            def rows(_table=table, _rid=rid):
                for r in db.execute(
                    f"SELECT * FROM {_table} WHERE run_id=?"  # noqa: S608 -- _table 来自 _DB_TABLES 白名单
                    " ORDER BY rec_id",
                    (_rid,),
                ):
                    stats["rows"] += 1
                    yield dict(r)

            evs = _prepare_run(
                rows(),
                run_name=run_name,
                run_seq=run_seq,
                registry=registry,
                src="benchdb",
                stats=stats,
                quar=quar,
                norm_fn=norm_fn,
            )
            _commit(evs, rdir=rdir, index=index, stats=stats, dry=dry)
            _flush_quar(quar, quar_seen, stats, dry)
    finally:
        db.close()
    return stats


# ---------------------------------------------------------------------------
# worktree jsonl files
# ---------------------------------------------------------------------------


def _run_meta_ts(rdir: Path) -> float | None:
    """started_at analog from a worktree run_meta.json (best effort)."""
    p = Path(rdir) / "run_meta.json"
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(meta, dict):
        for k in ("started_at", "ts_start", "start", "ts", "created_at"):
            ts = _parse_ts(meta.get(k))
            if ts is not None:
                return ts
    return None


def import_jsonl_file(
    path, run, stage_map=None, index=None, registry=None, dry: bool = False
) -> dict:
    """Import one worktree records*.jsonl / cases.jsonl file.

    `run` is the ledger run name (str) or a Path to the source run dir
    (name derived as import-<dirname>, started_at from run_meta.json).
    File order is preserved; identical lines pre-deduped.
    """
    stats = _stats()
    path = Path(path)
    if isinstance(run, Path):
        src_dir = run
        run_name = f"import-{_slugify(src_dir.name)}"
    else:
        src_dir = path.parent
        run_name = (
            str(run)
            if run
            else f"import-{_slugify(path.parent.name)}-{_slugify(path.stem)}"
        )
    file_ts = path.stat().st_mtime
    ts_start = _run_meta_ts(src_dir) or file_ts
    date = datetime.fromtimestamp(ts_start, tz=UTC).strftime("%Y-%m-%d")
    slug = _slugify(run_name.removeprefix("import-"))
    run_seq, rdir, minted, rr = _ensure_import_run(
        index, run_name, date=date, slug=slug, spec_hash=f"jsonl:{path.name}", dry=dry
    )
    stats["runs"] += 1
    stats["runs_minted"] += int(minted)

    quar: list = []
    quar_seen = _load_quar_shas()
    if rr is not None and index is not None and not dry:
        index.apply_events([rr])

    def norm_fn(row):
        return _norm_jsonl_row(
            row, fname=path.name, file_ts=file_ts, stage_map=stage_map
        )

    def rows():
        for _ln, ev, raw in iter_jsonl(path):
            stats["rows"] += 1
            if ev is None or not isinstance(ev, dict):
                reason = "bad_line" if ev is None else "non_object"
                payload, n_red = redact(raw if ev is None else ev)
                stats["redacted"] += n_red
                quar.append(
                    {
                        "type": "import_quarantine",
                        "src": "jsonl",
                        "run": run_name,
                        "reason": reason,
                        "payload": payload,
                        "dedup_sha": _sha(raw),
                        "ts": file_ts,
                    }
                )
                stats["quarantined"] += 1
                stats["bad_lines"] += 1
                continue
            yield ev

    evs = _prepare_run(
        rows(),
        run_name=run_name,
        run_seq=run_seq,
        registry=registry,
        src="jsonl",
        stats=stats,
        quar=quar,
        norm_fn=norm_fn,
    )
    _commit(evs, rdir=rdir, index=index, stats=stats, dry=dry)
    _flush_quar(quar, quar_seen, stats, dry)
    return stats
