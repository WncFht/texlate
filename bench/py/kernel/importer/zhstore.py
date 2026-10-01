"""kernel.importer.zhstore — zh-store 域导入 (kernel.importer 拆分叶).

zh-store 字节树的两段导入：

- ``import_zhstore`` (Phase 1) — manifest.jsonl 行 → asset/tombstone 事件
  (declared bytes 存在 → verified asset, 缺失 → tombstone); 字节普查
  (盘上 dir 无 manifest 行) 只报 orphan, 收编是 Phase 2 的事;
- ``seed_vault_zhstore`` (Phase 2, §3.10.9) — 实况字节普查：盘上行走
  zh/splice/state 子树三面 reconcile manifest, ``vault.harvest`` 进库，
  物理容器 (_quarantine/) 压过行内 zone 宣言; noncanon 字节只报不收。

两函数共享 ``_QUAR_CONTAINERS``/``_zh_dir_candidates``/``_ZONE_VERDICT``
字节定位件，故同城一叶。
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from kernel import events, idnorm, ledger
from kernel.events import iter_jsonl
from kernel.fsutil import dir_size
from kernel.importer.core import (
    _canon_gate,
    _commit,
    _ensure_import_run,
    _flush_quar,
    _load_quar_shas,
    _parse_ts,
    _redact_str,
    _scalar_secret,
    _sha,
    _stats,
    redact,
)

# ---------------------------------------------------------------------------
# zh-store manifest + byte census
# ---------------------------------------------------------------------------

_ZONE_VERDICT = {
    "primary": "primary",
    "alt": "alt",
    "quarantine": "quarantine",
    "_quarantine": "quarantine",
}


def _tree_has_file(d: Path) -> bool:
    try:
        for _root, _dirs, files in os.walk(d):
            if files:
                return True
    except OSError:
        return False
    return False


_QUAR_CONTAINERS = ("_quarantine", "quarantine")


def _zh_dir_candidates(bytes_root: Path, row: dict, idc: str) -> list:
    """Possible byte dirs for a manifest row, preferred first."""
    sid = idnorm.safe_id(idc)
    raw = str(row.get("id") or "")
    zone = row.get("zone")
    cands = []
    if zone in ("quarantine", "_quarantine"):
        cands.extend(
            bytes_root / cont / n
            for cont in _QUAR_CONTAINERS
            for n in dict.fromkeys((raw, sid))
            if n
        )
    cands.extend(bytes_root / n for n in dict.fromkeys((raw, sid)) if n)
    cands.extend(
        bytes_root / cont / n
        for cont in _QUAR_CONTAINERS
        for n in dict.fromkeys((raw, sid))
        if n
    )
    seen = set()
    out = []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def import_zhstore(
    manifest_path, bytes_root, index, registry=None, dry: bool = False
) -> dict:
    """Manifest rows -> asset events (verified when declared bytes exist,
    tombstone when missing); census dirs without rows -> orphan report.

    Byte lookup prefers row['id'] then safe_id(idc) under bytes_root,
    with the _quarantine/ subtree consulted first for quarantine zones.
    Adopting orphans is Phase 2's job — here they are only counted +
    noted, never claimed.
    """
    stats = _stats()
    manifest_path = Path(manifest_path)
    bytes_root = Path(bytes_root)
    run_name = "import-zhstore"
    file_ts = manifest_path.stat().st_mtime
    date = datetime.fromtimestamp(file_ts, tz=UTC).strftime("%Y-%m-%d")
    run_seq, rdir, minted, rr = _ensure_import_run(
        index,
        run_name,
        date=date,
        slug="zhstore",
        spec_hash="zhstore-manifest",
        dry=dry,
    )
    stats["runs"] += 1
    stats["runs_minted"] += int(minted)

    quar: list = []
    quar_seen = _load_quar_shas()
    evs: list = []
    seq = 0
    referenced: set[str] = set()
    orphans: list = []
    undeclared: list = []

    def next_seq() -> int:
        nonlocal seq
        seq += 1
        return seq

    for _ln, row, raw in iter_jsonl(manifest_path):
        stats["rows"] += 1
        if row is None:
            payload, n_red = redact(raw)
            stats["redacted"] += n_red
            quar.append(
                {
                    "type": "import_quarantine",
                    "src": "zhstore",
                    "run": run_name,
                    "reason": "bad_line",
                    "payload": payload,
                    "dedup_sha": _sha(raw),
                    "ts": file_ts,
                }
            )
            stats["quarantined"] += 1
            stats["bad_lines"] += 1
            continue
        if not isinstance(row, dict):
            payload, n_red = redact(row)
            stats["redacted"] += n_red
            quar.append(
                {
                    "type": "import_quarantine",
                    "src": "zhstore",
                    "run": run_name,
                    "reason": "non_object",
                    "payload": payload,
                    "dedup_sha": _sha(raw),
                    "ts": file_ts,
                }
            )
            stats["quarantined"] += 1
            stats["bad_lines"] += 1
            continue
        id_raw = row.get("id")
        if id_raw is not None:
            referenced.add(str(id_raw))
        res = _canon_gate(id_raw, registry)
        ts = _parse_ts(row.get("moved_at")) or _parse_ts(row.get("xlat_ts")) or file_ts
        if not res.ok:
            payload, n_red = redact(row)
            stats["redacted"] += n_red
            quar_row, n_red2 = redact(
                {
                    "type": "import_quarantine",
                    "src": "zhstore",
                    "run": run_name,
                    "reason": "canon",
                    "canon_state": res.state,
                    "canon_reason": res.reason,
                    "candidates": res.candidates,
                    "id": id_raw,
                    "payload": payload,
                    "dedup_sha": _sha(raw),
                    "ts": ts,
                }
            )
            stats["redacted"] += n_red2
            quar.append(quar_row)
            stats["quarantined"] += 1
            continue
        idc = res.idc
        referenced.add(idnorm.safe_id(idc))
        zone_key = str(row.get("zone") or "primary")
        zone = _ZONE_VERDICT.get(zone_key)
        if zone is None:
            # unknown zone is fail-closed: an uninterpretable zone must
            # never promote bytes into the dedup-hit set.
            quar_row, n_red = redact(
                {
                    "type": "import_quarantine",
                    "src": "zhstore",
                    "run": run_name,
                    "reason": "zone_unknown",
                    "id": id_raw,
                    "payload": {"zone": row.get("zone")},
                    "dedup_sha": _sha(raw),
                    "ts": ts,
                }
            )
            stats["redacted"] += n_red
            quar.append(quar_row)
            stats["quarantined"] += 1
            continue

        def _clean(v, default: str) -> str:
            """Manifest string fields are data-controlled — a secret in
            arm/model/source_run must not reach the ledger verbatim."""
            s = str(v) if v is not None else default
            if isinstance(s, str) and _scalar_secret(s):
                stats["redacted"] += 1
                s = _redact_str(s)
            return s

        arm = _clean(row.get("arm"), "-")
        model = _clean(row.get("model"), "")
        source_run = _clean(row.get("source_run"), "")
        altseq = _clean(row.get("altseq"), "0")
        id_clean = _clean(id_raw, str(id_raw)) if id_raw is not None else None
        base = None
        for cand in _zh_dir_candidates(bytes_root, row, idc):
            if cand.is_dir():
                base = cand
                break
        for kind in ("zh", "splice"):
            declared = bool(row.get(f"has_{kind}"))
            kdir = base / kind if base is not None else None
            has_bytes = kdir is not None and kdir.is_dir() and _tree_has_file(kdir)
            if not declared:
                if has_bytes:
                    undeclared.append(f"{id_raw}/{kind}")
                continue
            if has_bytes:
                try:
                    rel = kdir.relative_to(bytes_root).as_posix()
                except ValueError:
                    rel = str(kdir)
                evs.append(
                    {
                        "type": events.T_ASSET,
                        "v": events.SCHEMA_V,
                        "ts": ts,
                        "run": run_name,
                        "run_seq": run_seq,
                        "seq": next_seq(),
                        "id": id_clean,
                        "idc": idc,
                        "arm": arm,
                        "variant": "-",
                        "kind": kind,
                        "path": rel,
                        "sha": None,
                        "bytes": dir_size(kdir),
                        "state": "verified",
                        "zone": zone,
                        "verdict": zone,
                        "altseq": altseq,
                        "model": model,
                        "source_run": source_run,
                        "import_src": "zhstore",
                    }
                )
            else:
                evs.append(
                    {
                        "type": events.T_TOMBSTONE,
                        "v": events.SCHEMA_V,
                        "ts": ts,
                        "id": id_clean,
                        "idc": idc,
                        "arm": arm,
                        "variant": "-",
                        "kind": kind,
                        "reason": "zhstore_declared_missing",
                        "lost_run": source_run or "zhstore",
                        "zone": zone,
                        "import_src": "zhstore",
                    }
                )
            stats["events"] += 1

    # Byte census: payload dirs present without a manifest row. Report
    # only — Phase 2's adopt owns them (design: report+ 收编，never delete).
    census = []
    for container in [bytes_root] + [bytes_root / c for c in _QUAR_CONTAINERS]:
        if not container.is_dir():
            continue
        for child in sorted(container.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if container == bytes_root and child.name in _QUAR_CONTAINERS:
                continue  # the quarantine containers themselves, not payload
            census.append((container, child.name))
    for container, name in census:
        if name not in referenced:
            try:
                orphans.append(str((container / name).relative_to(bytes_root)))
            except ValueError:
                orphans.append(name)
    if orphans:
        evs.append(
            {
                "type": events.T_NOTE,
                "v": events.SCHEMA_V,
                "ts": file_ts,
                "run": run_name,
                "run_seq": run_seq,
                "seq": next_seq(),
                "text": f"zhstore census: {len(orphans)} orphan byte dirs "
                "without manifest rows (adopt deferred to Phase 2)",
                "level": "warn",
                "import_src": "zhstore",
            }
        )
        stats["events"] += 1
    if undeclared:
        evs.append(
            {
                "type": events.T_NOTE,
                "v": events.SCHEMA_V,
                "ts": file_ts,
                "run": run_name,
                "run_seq": run_seq,
                "seq": next_seq(),
                "text": f"zhstore census: {len(undeclared)} dirs hold bytes "
                "for kinds the manifest does not declare",
                "level": "warn",
                "import_src": "zhstore",
            }
        )
        stats["events"] += 1

    if rr is not None and index is not None and not dry:
        index.apply_events([rr])
    _commit(evs, rdir=rdir, index=index, stats=stats, dry=dry)
    _flush_quar(quar, quar_seen, stats, dry)
    stats["orphans"] = len(orphans)
    stats["orphan_dirs"] = orphans
    stats["undeclared_bytes"] = undeclared
    return stats


# ---------------------------------------------------------------------------
# Phase 2 — vault seeding (live-byte census, §3.10.9)
# ---------------------------------------------------------------------------

# zh-store kinds the census harvests — 'state' (xlat-state) joins the
# manifest-declared pair only when a state/ subtree physically exists.
_VAULT_SCAN_KINDS = ("zh", "splice", "state")


def _provenance(base: Path, stats: dict) -> dict | None:
    """zh-store <id>/provenance.json -> redacted dict for meta['provenance']."""
    p = base / "provenance.json"
    if not p.is_file():
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stats["errors"] += 1
        return None
    out, n = redact(obj)
    stats["redacted"] += n
    return out if isinstance(out, dict) else {"_raw": out}


def seed_vault_zhstore(
    manifest_path, bytes_root, index, registry=None, dry: bool = False
) -> dict:
    """Phase-2 live-byte census: physically seed zh-store bytes into vault.

    This is a byte census, not a manifest replay (§3.10.9): the disk is
    walked and reconciled three ways against the manifest rows.

    - Row + bytes present -> vault.harvest() the non-empty {zh,splice,
      state} subtrees. The physical container beats the claimed zone:
      anything found under _quarantine/ lands quar/quar regardless of the
      manifest's zone field. primary rows land primary/verified (the
      census itself is the verification — harvest sha256s every file into
      files.sha256). alt rows land alt/alt.
    - Row declared but bytes absent -> already tombstoned by
      import_zhstore; counted as still_missing, nothing re-emitted.
    - Dir on disk whose id never canon-resolves (no manifest row, or a
      canon-fail row like *.bak-mock) -> noncanon_bytes report. The vault
      _check_idc gate refuses them by design; mock/junk payloads never
      enter the paid-byte store. They stay in place for the operator.
    - provenance.json (per-id) merges into the harvested meta under
      'provenance'.
    - Manifest rows may carry an optional ``pinned`` field (append-only,
      last-wins — harvest.py's reindex propagates it from a row's
      provenance.json). It is tolerated and passed through into the
      harvested meta verbatim; no delete verb consumes it yet (schema
      placeholder).

    Idempotent: a (idc, arm, '-') copy that already bytes_ok and declares
    every on-disk kind is skipped, so a crashed census re-run continues
    without duplicating copies (altseq bumps) or events.
    """
    from kernel import vault  # local: keeps the ledger-only import cheap

    stats = _stats()
    stats.update(
        {
            "harvested": 0,
            "kinds_harvested": 0,
            "bytes": 0,
            "already": 0,
            "still_missing": 0,
            "partial": 0,
            "orphan_dirs": [],
            "noncanon_dirs": [],
            "conflicts": [],
        }
    )
    manifest_path = Path(manifest_path)
    bytes_root = Path(bytes_root)
    file_ts = manifest_path.stat().st_mtime
    date = datetime.fromtimestamp(file_ts, tz=UTC).strftime("%Y-%m-%d")
    run_name = "import-zhstore-vault-seed"
    run_seq, rdir, minted, rr = _ensure_import_run(
        index,
        run_name,
        date=date,
        slug="vault-seed",
        spec_hash="zhstore-vault-seed",
        dry=dry,
    )
    stats["runs"] += 1
    stats["runs_minted"] += int(minted)
    if rr is not None and index is not None and not dry:
        index.apply_events([rr])
    sink = index.apply_event if index is not None else None

    seq = 0

    def next_seq() -> int:
        nonlocal seq
        seq += 1
        return seq

    def _in_quar(base: Path) -> bool:
        for cont in _QUAR_CONTAINERS:
            try:
                base.relative_to(bytes_root / cont)
            except ValueError:
                continue
            else:
                return True
        return False

    def _patch_meta(
        mpath: Path, base: Path, adopted: bool, row: dict | None = None
    ) -> None:
        meta = vault._read_meta(mpath) or {}
        prov = _provenance(base, stats)
        if prov:
            meta["provenance"] = prov
        if adopted:
            meta["adopted_from"] = str(base)
        # import_src marks migration-seeded bytes: payment predates the
        # claim machinery, so doctor's paid reconciliation exempts them
        # (the meta-plane mirror of the events' import_src convention).
        meta["import_src"] = run_name
        if row is not None and row.get("pinned"):
            # zh-store manifest `pinned` — tolerated passthrough into the
            # vault meta (placeholder: no delete verb consumes it yet).
            meta["pinned"] = True
        vault._write_meta(mpath, meta)
        stats["bytes"] += int(meta.get("bytes") or 0)

    # -- pass 1: manifest rows (last-wins per id, file order = claim order) --
    rows_by_id: dict[str, dict] = {}
    for _ln, row, _raw in iter_jsonl(manifest_path):
        if isinstance(row, dict) and row.get("id"):
            rows_by_id[str(row["id"])] = row
    stats["rows"] = len(rows_by_id)

    claimed_dirs: set[Path] = set()

    for raw_id, row in rows_by_id.items():
        res = _canon_gate(raw_id, registry)
        # resolve the physical dir even for canon-fail rows (dir name is
        # the manifest id spelled verbatim, e.g. *.bak-mock)
        if res.ok:
            cands = _zh_dir_candidates(bytes_root, row, res.idc)
        else:
            cands = [bytes_root / raw_id] + [
                bytes_root / cont / raw_id for cont in _QUAR_CONTAINERS
            ]
        base = next((c for c in cands if c.is_dir()), None)
        if base is None:
            # byte-less row — tombstone already on the ledger
            if res.ok:
                stats["still_missing"] += 1
            continue
        claimed_dirs.add(base)
        assets = {
            k: base / k
            for k in _VAULT_SCAN_KINDS
            if (base / k).is_dir() and _tree_has_file(base / k)
        }
        if not res.ok:
            if assets:
                stats["noncanon_dirs"].append(str(base.relative_to(bytes_root)))
            continue
        if not assets:
            stats["still_missing"] += 1
            continue
        idc = res.idc
        arm = str(row.get("arm") or "-")
        # kinds the manifest claims but the dir does not carry -> partial
        declared = {k for k in ("zh", "splice") if row.get(f"has_{k}")}
        if declared - set(assets):
            stats["partial"] += 1
        # idempotency: an intact copy declaring every on-disk kind already
        # vouches for this cell — re-runs must not mint altseq duplicates.
        covered = set()
        for m in vault.query(idc, arm, "-"):
            if m.get("bytes_ok") and isinstance(m.get("files"), dict):
                covered.update(m["files"].keys())
        if covered and set(assets) <= covered:
            stats["already"] += 1
            # converge metas on re-run — a copy committed before the
            # provenance/import_src merge picks the markers up here
            # (vault-plane rewrite only; the ledger stays quiet).
            prov = _provenance(base, stats)
            for m in vault.query(idc, arm, "-"):
                if not m.get("bytes_ok") or not m.get("meta_path"):
                    continue
                meta = vault._read_meta(Path(m["meta_path"])) or {}
                changed = False
                if prov and "provenance" not in meta:
                    meta["provenance"] = prov
                    changed = True
                if meta.get("import_src") != run_name:
                    meta["import_src"] = run_name
                    changed = True
                if row.get("pinned") and not meta.get("pinned"):
                    meta["pinned"] = True
                    changed = True
                if changed and not dry:
                    vault._write_meta(Path(m["meta_path"]), meta)
            continue
        if _in_quar(base):
            zone = verdict = "quar"
        else:
            zone = _ZONE_VERDICT.get(str(row.get("zone") or "primary"), "quar")
            verdict = {"primary": "verified", "alt": "alt", "quarantine": "quar"}[zone]
        if dry:
            stats["harvested"] += 1
            stats["kinds_harvested"] += len(assets)
            continue
        try:
            mpath = vault.harvest(
                idc,
                arm,
                "-",
                assets,
                source_run=str(row.get("source_run") or "zhstore"),
                zone=zone,
                verdict=verdict,
                model=str(row.get("model") or "") or None,
                id=str(row.get("id") or idc),
                seq=next_seq,
                run_dir=rdir,
                sink=sink,
            )
        except vault.DestOccupied as exc:
            stats["conflicts"].append(f"{idc}: {exc}")
            stats["errors"] += 1
            continue
        _patch_meta(mpath, base, adopted=False, row=row)
        stats["harvested"] += 1
        stats["kinds_harvested"] += len(assets)
        stats["events"] += len(assets)
        stats["emitted"] += len(assets)
        if index is not None:
            stats["applied"] += len(assets)

    # -- pass 2: byte dirs with no canon-resolvable row -> quar --
    containers = [("", bytes_root)] + [(c, bytes_root / c) for c in _QUAR_CONTAINERS]
    for cont, cdir in containers:
        if not cdir.is_dir():
            continue
        for child in sorted(cdir.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if not cont and child.name in _QUAR_CONTAINERS:
                continue
            if child in claimed_dirs:
                continue
            assets = {
                k: child / k
                for k in _VAULT_SCAN_KINDS
                if (child / k).is_dir() and _tree_has_file(child / k)
            }
            if not assets:
                continue
            stats["orphan_dirs"].append(str(child.relative_to(bytes_root)))
            res = _canon_gate(idnorm.idc_from_safe(child.name), registry)
            if not res.ok:
                stats["noncanon_dirs"].append(str(child.relative_to(bytes_root)))
                continue
            # the dir carries no arm identity of its own — an intact copy
            # covering its kinds under ANY arm already vouches for it
            covered = set()
            for m in vault.query(res.idc):
                if m.get("bytes_ok") and isinstance(m.get("files"), dict):
                    covered.update(m["files"].keys())
            if covered and set(assets) <= covered:
                stats["already"] += 1
                continue
            if dry:
                stats["harvested"] += 1
                continue
            prov = _provenance(child, stats) or {}
            try:
                mpath = vault.harvest(
                    res.idc,
                    str(prov.get("arm") or "-"),
                    "-",
                    assets,
                    source_run=str(prov.get("source_run") or "orphan"),
                    zone="quar",
                    verdict="quar",
                    model=str(prov.get("model") or "") or None,
                    id=child.name,
                    seq=next_seq,
                    run_dir=rdir,
                    sink=sink,
                )
            except vault.DestOccupied as exc:
                stats["conflicts"].append(f"{child.name}: {exc}")
                stats["errors"] += 1
                continue
            _patch_meta(mpath, child, adopted=True)
            stats["harvested"] += 1
            stats["kinds_harvested"] += len(assets)
            stats["events"] += len(assets)
            stats["emitted"] += len(assets)
            if index is not None:
                stats["applied"] += len(assets)

    # -- census note (the summary row lives on the ledger, not stdout) --
    # gated on harvested alone: a quiet re-run (noncanon dirs still sit on
    # disk by design) must not append an identical note every census.
    if not dry and stats["harvested"]:
        ev = events.make_event(
            events.T_NOTE,
            run=run_name,
            run_seq=run_seq,
            seq=next_seq(),
            level="info",
            text=(
                f"vault seed census: {stats['harvested']} copies "
                f"harvested, {stats['already']} already present, "
                f"{stats['still_missing']} still missing, "
                f"{len(stats['orphan_dirs'])} orphan dirs, "
                f"{len(stats['noncanon_dirs'])} noncanon byte dirs"
            ),
        )
        ledger.emit(ev, run_dir=rdir, sink=sink)
        stats["events"] += 1
    return stats
