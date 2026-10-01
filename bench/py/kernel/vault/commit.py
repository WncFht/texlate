"""kernel.vault.commit — 两相提交径 (kernel.vault 拆分叶).

``harvest`` 是唯一入库闸：stage→hardlink 零拷 (EXDEV→copyfile)→
.files.jsonl→chmod -R a-w (fuse 串到工作侧 inode)→fsync→同卷 rename 逐
kind 落位→meta/*.json LAST (atomic commit marker)→manifest 锁内追加→
锁落后发 asset 事件。``adopt`` 是孤儿字节进 quar 的同构提交 (verdict=
'quar', state='adopted') + note 事件。

Refusals 全响亮，handled error 绝不半截入库; 封口闸把 pdf_corrupt 类的
坏成品 pdf 逐 kind 剔除 (seal_refused 记 meta/manifest), 全 kind 拒则抛。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
from contextlib import suppress
from pathlib import Path

from kernel import events, fsutil, idnorm, ledger, locks, paths
from kernel.vault.cred import (
    KINDS,
    DestOccupied,
    VaultError,
    _check_altseq,
    _check_idc,
    _comp,
    _kind_root,
    _norm_verdict,
    _norm_zone,
    _rel_leaf,
    dir_key,
    leaf_dir,
    meta_path,
)
from kernel.vault.intact import _corrupt_product_pdfs
from kernel.vault.io import (
    _append_manifest_locked,
    _chmod_readonly_tree,
    _fsync_ancestors,
    _fsync_file,
    _fsync_tree,
    _iter_files,
    _non_regular,
    _read_meta,
    _require_sentinel,
    _unfuse_dirs,
    _write_meta,
)
from kernel.vault.retention import cas_link_tree

_FILES_MANIFEST = ".files.jsonl"


def _slot_taken(idc: str, arm: str, variant: str, altseq: str) -> bool:
    """Credential occupancy: meta exists OR any kind dir exists in EITHER
    physical namespace (primary roots and quar roots). A meta-less squatter
    dir also blocks the slot — occupied is occupied."""
    if meta_path(idc, arm, variant, altseq).exists():
        return True
    sid = idnorm.safe_id(idc)
    key = dir_key(arm, variant, altseq)
    for zone in ("primary", "quar"):
        for kind in KINDS:
            if (_kind_root(zone, kind) / sid / key).exists():
                return True
    return False


def _choose_altseq(
    idc: str,
    arm: str,
    variant: str,
    altseq,
) -> str:
    """altseq=None -> first free slot '0','1','2',... (the ``.{altseq}``
    disambiguation of §3.10.4); explicit altseq -> use it or refuse."""
    if altseq is not None:
        a = _check_altseq(altseq)
        if _slot_taken(idc, arm, variant, a):
            msg = (
                f"vault copy ({idc},{arm},{variant},{a}) already occupied — "
                "refusing to nest into an existing destination"
            )
            raise DestOccupied(msg)
        return a
    for i in range(10000):
        a = str(i)
        if not _slot_taken(idc, arm, variant, a):
            return a
    msg = f"no free altseq slot for ({idc},{arm},{variant})"
    raise VaultError(msg)


def _group_files(rows: list[dict]) -> dict:
    """[{kind,path,size,sha256}] -> {kind: [{path,size,sha256}]} for meta."""
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["kind"], []).append(
            {"path": r["path"], "size": r["size"], "sha256": r["sha256"]}
        )
    return out


def harvest(
    idc,
    arm,
    variant,
    assets: dict,
    source_run: str = "adhoc",
    altseq=None,
    verdict: str = "pending",
    zone=None,
    model=None,
    id=None,  # noqa: A002 -- id=/seq= 是事件行键名，调用方以 kwarg 传入
    seq=None,
    staged: bool = False,
    sink=None,
    run_dir=None,
    _op: str = "harvest",
) -> Path:
    """THE commit path — stage, fuse, rename, meta-last, manifest, emit.

    assets = {kind: src_dir} for kind in {zh,splice,state}. The whole write
    serializes through vault/.lock; asset events emit AFTER the lock drops.
    Returns the meta path (the commit marker).

    Refusals (all loud, nothing partially committed by a handled error):
    missing/non-dir source, non-regular files inside (links/fifos — the
    vault holds regular bytes only), all-empty asset trees, occupied
    destination (explicit altseq), missing sentinel, cross-device staging.

    Seal gate: a kind whose DELIVERABLE pdf fails _pdf_intact (truncated or
    foreign bytes — the pdf_corrupt class) is refused per-kind: it is
    excluded from the copy and recorded in meta/manifest as seal_refused,
    so the corrupt pdf never enters the vault and no verdict/product claim
    can ever vouch for it. When every kind is refused the harvest raises —
    an empty copy is not a copy."""
    idc = _check_idc(idc)
    arm = _comp(arm)
    variant = _comp(variant)
    verdict = _norm_verdict(verdict)
    zone = (
        _norm_zone(zone)
        if zone is not None
        else ("quar" if verdict == "quar" else "pending")
    )
    _require_sentinel()
    paths.assert_vault_same_volume()
    if not isinstance(assets, dict) or not assets:
        msg = "harvest needs a non-empty {kind: src_dir} dict"
        raise ValueError(msg)
    kinds = sorted(assets)
    unknown = set(kinds) - KINDS
    if unknown:
        msg = f"unknown asset kinds {sorted(unknown)} (allowed: {sorted(KINDS)})"
        raise ValueError(msg)
    srcs: dict[str, Path] = {}
    refused: dict[str, list[dict]] = {}
    for k in kinds:
        src = Path(assets[k])
        if not src.is_dir():
            msg = f"asset {k} source is not a directory: {src}"
            raise VaultError(msg)
        offenders = _non_regular(src)
        if offenders:
            msg = (
                f"asset {k} holds non-regular files (vault stores regular "
                f"bytes only): {[str(o) for o in offenders[:5]]}"
            )
            raise VaultError(msg)
        files = _iter_files(src)
        if not files or all(p.stat().st_size == 0 for p, _ in files):
            msg = f"asset {k} carries no non-empty bytes: {src}"
            raise VaultError(msg)
        bad = _corrupt_product_pdfs(k, files)
        if bad:
            refused[k] = bad
            continue
        srcs[k] = src
    if not srcs:
        msg = (
            "every asset kind refused at seal — corrupt deliverable pdf: "
            f"{json.dumps(refused, ensure_ascii=False, sort_keys=True)}"
        )
        raise VaultError(msg)
    kinds = sorted(srcs)
    sid = idnorm.safe_id(idc)
    with locks.flock(paths.vault_lock_path(), exclusive=True):
        chosen = _choose_altseq(idc, arm, variant, altseq)
        key = dir_key(arm, variant, chosen)
        dests = {k: _kind_root(zone, k) / sid / key for k in kinds}
        paths.vault_staging_dir().mkdir(parents=True, exist_ok=True)
        tag = Path(
            tempfile.mkdtemp(
                prefix=f"hv-{sid[:32]}-", dir=str(paths.vault_staging_dir())
            )
        )
        mpath = meta_path(idc, arm, variant, chosen)
        moved: list[str] = []
        fused: dict[str, dict] = {}
        kind_bytes: dict[str, int] = {}
        try:
            rows: list[dict] = []
            for k in kinds:
                fsutil.hardlink_farm(srcs[k], tag / k)
                total = 0
                for p, rel in _iter_files(tag / k):
                    st = p.stat()
                    rows.append(
                        {
                            "kind": k,
                            "path": rel,
                            "size": st.st_size,
                            "sha256": fsutil._sha256_file(p),
                        }
                    )
                    total += st.st_size
                kind_bytes[k] = total
                cas_link_tree(
                    tag / k,
                    {r["path"]: r["sha256"] for r in rows if r["kind"] == k},
                )
            rows.sort(key=lambda r: (r["kind"], r["path"]))
            blob = "".join(events.dumps(r) + "\n" for r in rows).encode("utf-8")
            asset_sha = hashlib.sha256(blob).hexdigest()
            fman = tag / _FILES_MANIFEST
            fman.write_bytes(blob)
            _fsync_file(fman)
            for k in kinds:
                fused[k] = _chmod_readonly_tree(tag / k, include_root=False)
                _fsync_tree(tag / k)
            fsutil.fsync_dir(tag)
            # rename() each kind dir into place — same volume, so each move
            # is atomic; a crash here leaves meta-less bytes (R4, sweep's).
            for k in kinds:
                dst = dests[k]
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.rename(tag / k, dst)
                # deferred root fuse — a 0555 source dir makes rename() fail
                # (the kernel rewrites its '..' entry on the move).
                st = dst.stat()
                os.chmod(dst, stat.S_IMODE(st.st_mode) & ~0o222)
                fsutil.fsync_dir(dst)
                _fsync_ancestors(dst.parent)
                moved.append(k)
            # meta is the commit marker — it lands LAST, durably.
            meta = {
                "v": 1,
                "idc": idc,
                "arm": arm,
                "variant": variant,
                "altseq": chosen,
                "zone": zone,
                "verdict": verdict,
                "asset_sha": asset_sha,
                "files": _group_files(rows),
                "kinds": kinds,
                "bytes": sum(kind_bytes.values()),
                "source_run": source_run,
                "staged": True,
                "ts": round(time.time(), 3),
            }
            if model is not None:
                meta["model"] = model
            if refused:
                meta["seal_refused"] = refused
            _write_meta(mpath, meta)
            row = {
                "op": _op,
                "idc": idc,
                "arm": arm,
                "variant": variant,
                "altseq": chosen,
                "zone": zone,
                "verdict": verdict,
                "path": f"{sid}/{key}",
                "dirs": {k: _rel_leaf(zone, k, sid, key) for k in kinds},
                "kinds": kinds,
                "bytes": sum(kind_bytes.values()),
                "bytes_ok": True,
                "sha": asset_sha,
                "source_run": source_run,
                "ts": round(time.time(), 3),
            }
            if model is not None:
                row["model"] = model
            if refused:
                row["seal_refused"] = refused
            _append_manifest_locked(row)
            fsutil.fsync_dir(paths.vault_dir())
        except BaseException:
            # Best-effort rollback of the kinds we already moved — these are
            # files this harvest created seconds ago inside its own critical
            # section, so removing them is the self-cleaning direction. The
            # committed trees are already fused, so lift the fuse on dirs
            # first (rename-back of a 0555 dir fails on the '..' rewrite).
            for k in moved:
                _unfuse_dirs(dests[k])
                shutil.rmtree(dests[k], ignore_errors=True)
                # prune the {sid} parent iff this aborted commit left it empty
                with suppress(OSError):
                    dests[k].parent.rmdir()
            # Un-fuse the work-source inodes this commit fused — the tag
            # tree dies with staging, but the source-side aliases share the
            # inodes and would stay 0444 forever otherwise. Only nodes this
            # pass actually fused are restored, and only regular files: the
            # tag-side dirs were fresh inodes (the source's own dirs were
            # never touched) and a swapped-in symlink must not chmod a
            # foreign target.
            for k, changed in fused.items():
                for rel, mode in changed.items():
                    with suppress(OSError):
                        p = srcs[k] / rel
                        if stat.S_ISREG(os.lstat(p).st_mode):
                            os.chmod(p, mode)
            shutil.rmtree(tag, ignore_errors=True)
            raise
        shutil.rmtree(tag, ignore_errors=True)

    # Lock released — asset events never block the vault critical section on
    # the ledger lock. state: 'adopted' for quar-born copies, 'staged' for
    # secure-then-evict pre-staging, else 'pending'. seq may be a callable
    # (per-kind mint — a shared int would stamp duplicate (run_seq,seq)
    # keys and the index would drop every kind after the first).
    state = "adopted" if zone == "quar" else ("staged" if staged else "pending")
    seq_fn = seq if callable(seq) else (lambda: seq)
    for k in kinds:
        ev = events.make_event(
            events.T_ASSET,
            run=source_run,
            seq=seq_fn(),
            id=id or idc,
            idc=idc,
            arm=arm,
            variant=variant,
            kind=k,
            path=_rel_leaf(zone, k, sid, key),
            sha=asset_sha,
            bytes=kind_bytes[k],
            state=state,
            verdict=verdict,
            zone=zone,
            altseq=chosen,
        )
        ledger.emit(ev, run_dir=run_dir, sink=sink)
    return mpath


def adopt(
    src_dir,
    idc,
    arm: str = "-",
    variant: str = "-",
    reason: str = "orphan",
    kind: str = "zh",
    id=None,  # noqa: A002 -- 事件行键名
    sink=None,
    run_dir=None,
) -> Path:
    """Orphan bytes -> quarantine. The whole tree becomes one quar-zone copy
    via the normal two-phase commit (verdict='quar', state='adopted'), then
    a note event records the adoption. Refuses non-regular files — a stray
    fifo or symlink never enters the vault."""
    idc = _check_idc(idc)
    arm = _comp(arm)
    variant = _comp(variant)
    if kind not in KINDS:
        msg = f"adopt kind must be one of {sorted(KINDS)}, got {kind!r}"
        raise ValueError(msg)
    src = Path(src_dir)
    if not src.is_dir():
        msg = f"adopt source is not a directory: {src}"
        raise VaultError(msg)
    offenders = _non_regular(src)
    if offenders:
        msg = f"adopt refuses non-regular files: {[str(o) for o in offenders[:5]]}"
        raise VaultError(msg)
    mpath = harvest(
        idc,
        arm,
        variant,
        {kind: src},
        source_run="adopt",
        verdict="quar",
        zone="quar",
        id=id,
        sink=sink,
        run_dir=run_dir,
        _op="adopt",
    )
    meta = _read_meta(mpath) or {}
    ev = events.make_event(
        events.T_NOTE,
        run="adopt",
        seq=None,
        id=id or idc,
        idc=idc,
        text=(
            f"adopted orphan bytes {src} -> vault quar "
            f"({idc},{arm},{variant},{meta.get('altseq', '0')}) "
            f"reason={reason}"
        ),
        level="warn",
    )
    ledger.emit(ev, run_dir=run_dir, sink=sink)
    return leaf_dir("quar", kind, idc, arm, variant, meta.get("altseq", "0"))
