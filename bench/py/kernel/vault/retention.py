"""kernel.vault.retention — CAS 投影 + splice slim + 孤儿扫描 (kernel.vault 拆分叶).

- ``cas_link_tree`` — 收割钩内/P3 retroverb 共用：≥CAS_LINK_FLOOR 的叶件
  经 CAS 折成共享 inode 硬链 (extracted↔vault↔workdir 三方去重，
  sty/cls 跨件资源受益)。
- ``slim_splice``/``_splice_keep`` — P3 留存：splice 叶瘦到成品面
  (final pdf + arm json + log), figs/anc/中间件死, meta.files 收缩并记
  op='slim' manifest 行。
- ``find_meta_less_dirs``/``_scan_meta_less_dirs`` — R4 崩溃窗孤儿目录
  枚举 (只报不删; 硬删除谓词归 sweep)。
- ``_iter_committed_leaves`` — 全物理根 (main+quar) 叶迭代器，本叶
  retroverb 与 verify 共用。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from kernel import cas, idnorm, locks, paths
from kernel.vault.cred import (
    KINDS,
    _check_idc,
    _kind_root,
    _norm_zone,
    _zone_tag,
    dir_key,
    meta_path,
    parse_dir_key,
)
from kernel.vault.io import (
    _append_manifest_locked,
    _chmod_readonly_tree,
    _iter_files,
    _iter_metas,
    _read_meta,
    _unfuse_dirs,
    _write_meta,
)

#: Files below this never CAS-link — the inode churn beats the win.
CAS_LINK_FLOOR = 256 * 1024


def cas_link_tree(root, sha_map: dict[str, str] | None = None) -> dict:
    """Project every regular file ≥ CAS_LINK_FLOOR under ``root`` through the
    CAS: store the bytes (kind='file'), then swap the leaf entry for a
    hardlink to the object. Never worse than the private copy — on a miss the
    object IS the only inode until a second projection shares it; on a hit the
    leaf folds onto the shared inode and frees its private bytes (dedup across
    extracted↔vault↔workdir copies and cross-paper assets like sty/cls).

    ``sha_map`` (posix-rel → sha256) lets a caller who already hashed the tree
    skip the pre-hash read on dedup hits — known sha + live object is a pure
    link_out. Missing/stale entries fall back to store_file (which rehashes).
    """
    linked = 0
    moved = 0
    for p, rel in _iter_files(Path(root)):
        size = p.stat().st_size
        if size < CAS_LINK_FLOOR:
            continue
        sha = (sha_map or {}).get(rel)
        if not (sha and cas.has(sha, kind="file")):
            sha = cas.store_file(p, kind="file")
        cas.link_out(sha, p, kind="file")
        linked += 1
        moved += size
    return {"linked": linked, "bytes": moved}


def _iter_committed_leaves(kind: str | None = None):
    """Yield (zone, kind, sid, key, leaf_path) over every physical root.
    pending/primary/alt share ``vault/{kind}`` (the logical zone lives in
    meta, not the path) so they collapse to a single 'main' scan — the
    yielded zone is physical ('main'|'quar'); callers needing the logical
    zone read it from meta."""
    kinds = KINDS if kind is None else (kind,)
    for zone in ("main", "quar"):
        for k in kinds:
            root = (
                paths.vault_dir() / "quar" / k
                if zone == "quar"
                else paths.vault_dir() / k
            )
            if not root.is_dir():
                continue
            for sid_dir in sorted(root.iterdir()):
                if not sid_dir.is_dir():
                    continue
                for leaf in sorted(sid_dir.iterdir()):
                    if leaf.is_dir():
                        yield zone, k, sid_dir.name, leaf.name, leaf


def cas_link_leaves(kind=None, idc=None, dry: bool = False) -> list[dict]:
    """Retroverb: CAS-link already-committed leaves in place (the harvest hook
    covers new writes; this sweeps history). Dirs are unfused for the swap and
    re-fused after — bytes and meta are untouched, so no manifest row."""
    sid = idnorm.safe_id(_check_idc(idc)) if idc else None
    out = []
    for zone, k, s, key, leaf in _iter_committed_leaves(kind):
        if sid and s != sid:
            continue
        if dry:
            cand = [p.stat().st_size for p, _rel in _iter_files(leaf)]
            cand = [n for n in cand if n >= CAS_LINK_FLOOR]
            out.append(
                {
                    "zone": zone,
                    "kind": k,
                    "sid": s,
                    "key": key,
                    "candidates": len(cand),
                    "bytes": sum(cand),
                    "linked": 0,
                }
            )
            continue
        _unfuse_dirs(leaf)
        try:
            stats = cas_link_tree(leaf)
        finally:
            _chmod_readonly_tree(leaf, include_root=True)
        out.append({"zone": zone, "kind": k, "sid": s, "key": key, **stats})
    return out


def _splice_keep(leaf: Path) -> set[Path]:
    """Durable surface of a splice leaf: root pdf(s) whose stem matches a root
    *.tex (the compiled final), .xlat-arm.json, and root *.log. No stem match
    → keep the largest root pdf as the final (covers leaves where the tex stem
    and pdf name diverge)."""
    keep: set[Path] = set()
    tex_stems = {p.stem for p in leaf.glob("*.tex") if p.is_file()}
    pdfs = [p for p in leaf.glob("*.pdf") if p.is_file()]
    matched = {p for p in pdfs if p.stem in tex_stems}
    if matched:
        keep |= matched
    elif pdfs:
        keep.add(max(pdfs, key=lambda p: p.stat().st_size))
    arm = leaf / ".xlat-arm.json"
    if arm.is_file():
        keep.add(arm)
    keep |= {p for p in leaf.glob("*.log") if p.is_file()}
    return keep


def slim_splice(idc=None, dry: bool = False) -> list[dict]:
    """P3 verb: shrink every committed splice leaf to ``_splice_keep`` —
    final pdf + arm json + logs; figs/, anc/, intermediates and duplicate
    pdfs die. meta.files.splice shrinks to the kept rows, meta.bytes is
    recomputed, meta.slimmed records the audit, and the manifest takes an
    op='slim' row. Leaves already at surface (nothing removable) are skipped.
    """
    out = []
    sid = idnorm.safe_id(_check_idc(idc)) if idc else None
    for zone, _k, s, key, leaf in _iter_committed_leaves("splice"):
        if sid and s != sid:
            continue
        keep = _splice_keep(leaf)
        doomed = [p for p in leaf.iterdir() if p not in keep]
        if not doomed:
            continue
        dropped_bytes = 0
        for p in doomed:
            if p.is_dir():
                for f, _rel in _iter_files(p):
                    dropped_bytes += f.stat().st_size
            else:
                dropped_bytes += p.stat().st_size
        arm_, variant_, altseq_ = parse_dir_key(key)
        idc_ = idnorm.idc_from_safe(s)
        mp = meta_path(idc_, arm_, variant_, altseq_)
        meta = _read_meta(mp)
        kept_rel = sorted(p.relative_to(leaf).as_posix() for p in keep)
        if dry:
            out.append(
                {
                    "zone": zone,
                    "sid": s,
                    "key": key,
                    "kept": kept_rel,
                    "dropped": len(doomed),
                    "dropped_bytes": dropped_bytes,
                    "meta": mp.exists(),
                }
            )
            continue
        _unfuse_dirs(leaf)
        try:
            for p in doomed:
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
        finally:
            _chmod_readonly_tree(leaf, include_root=True)
        if meta is not None:
            flist = meta.get("files")
            if isinstance(flist, dict) and isinstance(flist.get("splice"), list):
                flist["splice"] = [
                    r for r in flist["splice"] if r.get("path") in kept_rel
                ]
            if isinstance(flist, dict):
                meta["bytes"] = sum(
                    r.get("size", 0)
                    for rows in flist.values()
                    if isinstance(rows, list)
                    for r in rows
                    if isinstance(r, dict)
                )
            meta["slimmed"] = {
                "ts": round(time.time(), 3),
                "kept": kept_rel,
                "dropped_bytes": dropped_bytes,
            }
            _write_meta(mp, meta)
        row_zone = (meta or {}).get("zone") or zone
        _append_manifest_locked(
            {
                "op": "slim",
                "idc": idc_,
                "arm": arm_,
                "variant": variant_,
                "altseq": altseq_,
                "zone": row_zone,
                "path": f"{s}/{key}",
                "kept": kept_rel,
                "dropped_bytes": dropped_bytes,
                "bytes": meta.get("bytes") if meta else None,
                "ts": round(time.time(), 3),
            }
        )
        out.append(
            {
                "zone": row_zone,
                "sid": s,
                "key": key,
                "kept": kept_rel,
                "dropped": len(doomed),
                "dropped_bytes": dropped_bytes,
                "meta": meta is not None,
            }
        )
    return out


def find_meta_less_dirs() -> list[Path]:
    """Orphan detector: leaf dirs under the kind roots (primary AND quar
    namespaces) with no covering meta — the R4 crash window made visible.

    REPORT ONLY — deletion is deliberately not here. The hardened delete
    predicate (sibling metas + manifest alt rows + age + dedup-domain check)
    belongs to the sweep; this just enumerates candidates under a shared
    vault lock."""
    with locks.flock(paths.vault_lock_path(), exclusive=False):
        return _scan_meta_less_dirs()


def _scan_meta_less_dirs() -> list[Path]:
    covered = set()
    for _mp, key, meta in _iter_metas():
        if key is None or meta is None:
            continue
        try:
            zone = _norm_zone(meta.get("zone", "pending"))
        except ValueError:
            continue
        files = meta.get("files")
        if not isinstance(files, dict):
            continue
        sid = idnorm.safe_id(key[0])
        k = dir_key(key[1], key[2], key[3])
        for kind in files:
            covered.add((_zone_tag(zone), kind, sid, k))
    out = []
    for tag in ("primary", "quar"):
        for kind in sorted(KINDS):
            root = _kind_root("quar" if tag == "quar" else "primary", kind)
            if not root.is_dir():
                continue
            for sid_d in sorted(root.iterdir()):
                if not sid_d.is_dir():
                    continue
                for leaf in sorted(sid_d.iterdir()):
                    if not leaf.is_dir():
                        continue
                    if (tag, kind, sid_d.name, leaf.name) not in covered:
                        out.append(leaf)
    return out
