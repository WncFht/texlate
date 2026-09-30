"""kernel._import_lake — lake 域导入 (kernel.importer 拆分叶).

lake 面两条 Phase 3 (§3.10) 驱动：

- ``register_lake_manifests`` — corpus manifest 行 → lake catalog 播种
  (全行死路 → ``failed``/``regen_cost='network'``, 否则 ``skeleton``);
  catalog 行 + lake_cell 事件经 ``_BatchSink`` 一次 ``set_bulk`` 落账;
- ``absorb_corpus`` — 旧 corpus 字节树 CAS 化进 ``lake/corpus/{source}/``,
  ``lake/tmp/rebuild/`` 整树构建 + first-wins rename 发布，catalog
  ``hydrated``/``raw_only`` 终判。

共享 ``_BatchSink`` (批量 sink 适配——ledger 锁内不逐事件 fsync) 与
``_manifest_files`` 展开件，故同城一叶。
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from kernel import events, fsutil, idnorm, ledger, paths
from kernel._import_core import (
    _append_quar,
    _canon_gate,
    _ensure_import_run,
    _load_quar_shas,
    _stats,
)
from kernel.events import iter_jsonl
from kernel.fsutil import dir_size

# ---------------------------------------------------------------------------
# Lake zone — manifest seeding + on-disk corpus absorb (Phase 3, §3.10)
# ---------------------------------------------------------------------------


class _BatchSink:
    """Sink adapter for bulk emits: ledger.emit/_batch apply the sink
    per event inside the ledger lock; index.apply_event commits per call,
    so a 10⁴-event seeding would fsync 10⁴ times while holding the lock.
    Buffer instead and flush once through ``index.apply_events`` — one
    transaction, and the ledger lock is released right after the fsync.
    A crash between ledger-append and flush only leaves the disposable
    index behind — tail_ingest heals it."""

    def __init__(self, index):
        self.index = index
        self.evs: list[dict] = []

    def __call__(self, ev: dict) -> None:
        self.evs.append(ev)

    def flush(self) -> int:
        """One apply_events transaction; returns rows applied. Raises —
        a failed flush is loud to the operator (the ledger is already
        durable, the index rebuilds)."""
        if not self.evs:
            return 0
        n = self.index.apply_events(self.evs)
        self.evs.clear()
        return n


# A manifest row records a fetch dead end worth remembering as 'failed'
# (never in the fetch set): an explicit non-ok status, or a stub payload
# (IA placeholder bytes, not a real tree).
_LAKE_BAD_FORMATS = frozenset({"stub"})


def _lake_row_failed(row: dict) -> bool:
    st = row.get("status")
    if isinstance(st, str) and st and st != "ok":
        return True
    return row.get("format") in _LAKE_BAD_FORMATS


def _manifest_files(manifest_paths) -> list[Path]:
    """Expand a mixed list of manifest files/dirs into concrete
    manifest*.jsonl paths (dirs contribute their glob, sorted)."""
    out: list[Path] = []
    for mpath in manifest_paths or []:
        mp = Path(mpath)
        if mp.is_dir():
            out.extend(sorted(mp.glob("manifest*.jsonl")))
        elif mp.is_file():
            out.append(mp)
    return out


def register_lake_manifests(
    manifest_paths, index, registry=None, dry: bool = False
) -> dict:
    """Seed the lake catalog from corpus manifests (Phase 3).

    Every row canon-gates to an idc; per idc the seed is:

    - ``failed``   — EVERY row for the id is a fetch dead end
                     (status ∉ {None,'ok'} or format=='stub'); tagged
                     ``regen_cost='network'`` since reviving the cell needs
                     the wire.
    - ``skeleton`` — otherwise (manifested, no bytes); the cell dir is
                     created as the anchor.

    Idempotent: an idc whose catalog state is not 'absent' is never
    downgraded — only missing layer/channel memberships merge in (a
    re-run with unchanged manifests appends nothing). Canon failures go
    to quarantine. Catalog rows + lake_cell events land via ONE
    ``LakeCatalog.set_bulk`` (O(1) file rescans, one emit_batch into the
    import run's shard).
    """
    from kernel import lake  # local: keeps the ledger-only import cheap

    stats = _stats()
    stats.update(
        {
            "manifests": 0,
            "seeded_skeleton": 0,
            "seeded_failed": 0,
            "skipped_present": 0,
            "meta_merged": 0,
            "noncanon_ids": [],
        }
    )
    files = _manifest_files(manifest_paths)
    stats["manifests"] = len(files)
    if not files:
        stats["errors"] = 1
        return stats
    date = datetime.fromtimestamp(
        max(f.stat().st_mtime for f in files), tz=UTC
    ).strftime("%Y-%m-%d")
    run_name = "import-lake-register"
    run_seq, rdir, minted, rr = _ensure_import_run(
        index,
        run_name,
        date=date,
        slug="lake-register",
        spec_hash="lake-register",
        dry=dry,
    )
    stats["runs"] += 1
    stats["runs_minted"] += int(minted)
    if rr is not None and index is not None and not dry:
        index.apply_events([rr])
    sink = _BatchSink(index) if index is not None else None

    quar_seen = _load_quar_shas()
    # per-idc merge: last-wins scalars, union on layer/channel, and a
    # failed seed only when EVERY row is a dead end (a mixed history means
    # a fetch could still succeed -> honest state is skeleton).
    merged: dict[str, dict] = {}
    for f in files:
        for _ln, row, _raw in iter_jsonl(f):
            if not isinstance(row, dict) or not row.get("id"):
                stats["bad_lines"] += 1
                continue
            stats["rows"] += 1
            res = _canon_gate(row["id"], registry)
            if not res.ok:
                stats["quarantined"] += 1
                if len(stats["noncanon_ids"]) < 100:
                    stats["noncanon_ids"].append(str(row["id"]))
                _append_quar(
                    {
                        "src": "lake-register",
                        "file": f.name,
                        "reason": res.reason,
                        "row": row,
                    },
                    quar_seen,
                    dry,
                )
                continue
            acc = merged.setdefault(
                res.idc,
                {"layers": set(), "channels": set(), "any_ok": False, "any_bad": False},
            )
            if row.get("layer"):
                acc["layers"].add(str(row["layer"]))
            if row.get("channel"):
                acc["channels"].add(str(row["channel"]))
            if _lake_row_failed(row):
                acc["any_bad"] = True
            else:
                acc["any_ok"] = True

    cat = lake.LakeCatalog.load()
    cat_rows = cat.rows()
    updates = []
    for idc, acc in merged.items():
        layers = sorted(acc["layers"])
        channels = sorted(acc["channels"])
        cur = cat.state(idc)
        if cur == "absent":
            failed = acc["any_bad"] and not acc["any_ok"]
            kw = {
                "source": "arxiv",
                "manifested": True,
                "layers": layers,
                "channels": channels,
            }
            if failed:
                kw["regen_cost"] = "network"
                stats["seeded_failed"] += 1
            else:
                stats["seeded_skeleton"] += 1
            updates.append((idc, "failed" if failed else "skeleton", kw))
            if not dry and not failed:
                # skeletons anchor an (empty) cell dir; failed seeds are
                # catalog-only — nothing on disk to anchor.
                lake.cell_dir(idc, "arxiv").mkdir(parents=True, exist_ok=True)
            continue
        base = cat_rows.get(idc) or {}
        new_layers = sorted(set(base.get("layers") or []) | acc["layers"])
        new_channels = sorted(set(base.get("channels") or []) | acc["channels"])
        if new_layers != (base.get("layers") or []) or new_channels != (
            base.get("channels") or []
        ):
            updates.append((idc, cur, {"layers": new_layers, "channels": new_channels}))
            stats["meta_merged"] += 1
        else:
            stats["skipped_present"] += 1

    if not dry:
        cat.set_bulk(updates, sink=sink, run_dir=rdir)
        stats["emitted"] = stats["events"] = len(updates)
        if updates:
            ev = events.make_event(
                events.T_NOTE,
                run=run_name,
                run_seq=run_seq,
                seq=1,
                level="info",
                text=(
                    f"lake register: {stats['seeded_skeleton']} skeletons, "
                    f"{stats['seeded_failed']} failed seeds, "
                    f"{stats['meta_merged']} membership merges, "
                    f"{stats['skipped_present']} already present, "
                    f"{stats['quarantined']} quarantined"
                ),
            )
            ledger.emit(ev, run_dir=rdir, sink=sink)
            stats["events"] += 1
        if sink is not None:
            stats["applied"] = sink.flush()
    else:
        stats["events"] = len(updates)
    return stats


def _legacy_raw_files(cell: Path, meta: dict) -> list[Path]:
    """Locate the canonical raw payload of a legacy corpus cell: the
    meta-declared ``raw_file`` first, then raw.* probes, then a raw/ dir's
    own entries. Returns [] when the cell carries no raw tier."""
    rf = meta.get("raw_file")
    if isinstance(rf, str) and rf and "/" not in rf:
        p = cell / rf
        if p.is_file():
            return [p]
    for name in ("raw.tar.gz", "raw.tgz", "raw.gz", "raw.pdf", "raw.tex", "raw"):
        p = cell / name
        if p.is_file():
            return [p]
    rawdir = cell / "raw"
    if rawdir.is_dir():
        return sorted(p for p in rawdir.iterdir() if p.is_file())
    return []


def absorb_corpus(
    bytes_root,
    index,
    registry=None,
    manifests=None,
    dry: bool = False,
    source: str = "arxiv",
) -> dict:
    """CAS-ify a legacy corpus tree into ``lake/corpus/{source}/`` (Phase 3).

    Per cell dir (both '0707.0978' and 'astro-ph--0605048' spellings pass
    the same canon gate):

    - raw payload  -> ``cas.store_file(kind='blob')`` -> link_out into
      ``stage/raw/``
    - extracted/** -> ``cas.store_file(kind='file')`` -> link_out into
      ``stage/extracted/`` (read-only 0444 projection; shared .sty/.cls
      inodes dedup across cells for free)
    - meta.json    -> merged with idc/source/n_files/raw_sha256/
      absorbed_from/absorb markers, written fresh (bookkeeping, not CAS)
    - files.txt / mtree.txt -> CAS'd and linked as top-level bookkeeping

    The cell is built whole under ``lake/tmp/rebuild/absorb-{seq}/`` and
    published by first-wins rename under the cell's ``lake_lock`` — a
    racing hydrate/absorb can never interleave a half tree. Catalog:
    'hydrated' when extracted payload exists, 'raw_only' for raw-only
    cells; ``manifested`` reflects membership in the supplied manifest id
    set (unmanifested cells are the first eviction candidates).

    Idempotent: is_complete (or a live raw_only tier) skips the rebuild,
    and a missing catalog row on an already-complete cell is re-seeded —
    a crash between publish and the bulk catalog write self-heals on the
    next run. The SOURCE tree is never modified (store_file always copies
    in, never links).
    """
    from kernel import cas, lake

    stats = _stats()
    stats.update(
        {
            "absorbed": 0,
            "already": 0,
            "raw_only": 0,
            "no_payload": [],
            "noncanon_dirs": [],
            "objs_stored": 0,
            "bytes_in": 0,
        }
    )
    bytes_root = Path(bytes_root)
    manifested = None
    if manifests:
        manifested = set()
        for f in _manifest_files(manifests):
            for _ln, row, _raw in iter_jsonl(f):
                if isinstance(row, dict) and row.get("id"):
                    res = _canon_gate(row["id"], registry)
                    if res.ok:
                        manifested.add(res.idc)
    run_seq, rdir, minted, rr = _ensure_import_run(
        index,
        "import-lake-absorb",
        date=datetime.now(tz=UTC).strftime("%Y-%m-%d"),
        slug="corpus-absorb",
        spec_hash="corpus-absorb",
        dry=dry,
    )
    stats["runs"] += 1
    stats["runs_minted"] += int(minted)
    if rr is not None and index is not None and not dry:
        index.apply_events([rr])
    sink = _BatchSink(index) if index is not None else None

    cat = lake.LakeCatalog.load()
    pending: list[tuple[str, str, dict]] = []
    stage_root = paths.lake_tmp_dir() / "rebuild" / f"absorb-{run_seq}"

    def catalog_kw(idc, n_files, nbytes, state):
        kw = {
            "source": source,
            "n_files": n_files,
            "bytes": nbytes,
            "absorbed_from": str(bytes_root),
        }
        if manifested is not None:
            kw["manifested"] = idc in manifested
        return kw

    for child in sorted(bytes_root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        res = _canon_gate(child.name, registry)
        if not res.ok:
            stats["noncanon_dirs"].append(child.name)
            continue
        idc = res.idc
        sid = idnorm.safe_id(idc)
        dest = lake.cell_dir(idc, source)
        cur = cat.state(idc)
        if lake.is_complete(idc, source) or (
            cur == "raw_only" and (dest / "raw").exists()
        ):
            stats["already"] += 1
            if cur == "absent":
                # published but never catalogued (crashed absorb) — heal
                meta = lake._read_meta(dest)
                n = meta.get("n_files") or 0
                pending.append(
                    (idc, "hydrated", catalog_kw(idc, n, dir_size(dest), cur))
                )
            continue

        meta = lake._read_meta(child)
        raws = _legacy_raw_files(child, meta)
        exdir = child / "extracted"
        extracted = (
            sorted(p for p in exdir.rglob("*") if p.is_file()) if exdir.is_dir() else []
        )
        if not raws and not extracted:
            stats["no_payload"].append(child.name)
            continue
        stats["bytes_in"] += dir_size(child)
        if dry:
            stats["absorbed"] += 1
            stats["raw_only"] += int(not extracted)
            continue

        stage = stage_root / f"{sid}.stage"
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        raw_shas = []
        for rf in raws:
            sha = cas.store_file(rf, kind="blob")
            cas.link_out(sha, stage / "raw" / rf.name, kind="blob")
            raw_shas.append(sha)
            stats["objs_stored"] += 1
        for f in extracted:
            rel = f.relative_to(exdir)
            sha = cas.store_file(f, kind="file")
            cas.link_out(sha, stage / "extracted" / rel, kind="file")
            stats["objs_stored"] += 1
        for keep in ("files.txt", "mtree.txt"):
            bk = child / keep
            if bk.is_file():
                sha = cas.store_file(bk, kind="file")
                cas.link_out(sha, stage / keep, kind="file")
        n = lake._payload_count(stage)
        new_meta = {
            **meta,
            "idc": idc,
            "source": source,
            "n_files": n,
            "raw_sha256": raw_shas[0] if len(raw_shas) == 1 else raw_shas,
            "absorbed_from": str(child),
            "absorb": True,
            "hydrated_at": round(time.time(), 3),
            "run_seq": run_seq,
        }
        fsutil.atomic_write(
            stage / "meta.json",
            json.dumps(new_meta, ensure_ascii=False, sort_keys=True, indent=2).encode(
                "utf-8"
            ),
        )
        with lake.lake_lock(sid):
            if lake.is_complete(idc, source):
                shutil.rmtree(stage, ignore_errors=True)
                stats["already"] += 1
                continue
            won = lake._publish_stage(stage, dest)
        if not won:
            shutil.rmtree(stage, ignore_errors=True)
            stats["already"] += 1
            continue
        state = "hydrated" if extracted else "raw_only"
        stats["absorbed"] += 1
        stats["raw_only"] += int(not extracted)
        pending.append((idc, state, catalog_kw(idc, n, dir_size(dest), state)))

    if not dry and pending:
        cat.set_bulk(pending, sink=sink, run_dir=rdir)
        stats["emitted"] = stats["events"] = len(pending)
        ev = events.make_event(
            events.T_NOTE,
            run="import-lake-absorb",
            run_seq=run_seq,
            seq=1,
            level="info",
            text=(
                f"corpus absorb: {stats['absorbed']} cells "
                f"({stats['raw_only']} raw_only), {stats['already']} "
                f"already present, {len(stats['noncanon_dirs'])} "
                f"noncanon dirs, {stats['objs_stored']} objects"
            ),
        )
        ledger.emit(ev, run_dir=rdir, sink=sink)
        stats["events"] += 1
        if sink is not None:
            stats["applied"] = sink.flush()
    elif dry:
        stats["events"] = len(pending)
    return stats
