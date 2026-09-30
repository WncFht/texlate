"""kernel._vault_verbs — zone/verdict 簿记动词 (kernel.vault 拆分叶).

``promote``: pending→primary|quar|alt (与 quar→primary|alt 回搬)。
primary/alt 是纯元数据 zone (meta 重写 + manifest 行，零字节 I/O);
quar 有物理根，跨界 rename 逐 kind 搬目录。锁落后发 state='verified'
asset 事件，index vault_meta 投影学到新判词。

``tombstone``: 字节已失登记——manifest tombstone 行 (锁内) + 一等
tombstone 事件 (§3.1 墓碑是事件不是文件), 并给声明该 kind 的每个副本
meta 打 ``tombstoned_kinds`` (coverage/物化/dedup 全让位活 kind)。
"""

from __future__ import annotations

import os
import stat
import time
from contextlib import suppress

from kernel import events, fsutil, idnorm, ledger, locks, paths
from kernel._vault_cred import (
    DestOccupied,
    MetaMissing,
    VaultError,
    _check_altseq,
    _check_idc,
    _comp,
    _kind_root,
    _norm_verdict,
    _norm_zone,
    _rel_leaf,
    _zone_tag,
    dir_key,
    meta_path,
)
from kernel._vault_intact import _copy_intact
from kernel._vault_io import (
    _append_manifest_locked,
    _fsync_ancestors,
    _iter_metas_for,
    _read_meta,
    _require_sentinel,
    _write_meta,
)


def promote(
    idc,
    arm,
    variant,
    altseq,
    zone,
    verdict,
    source_run: str = "reconcile",
    sink=None,
    run_dir=None,
) -> None:
    """pending -> primary|quar|alt (and quar -> primary|alt back).

    primary/alt are pure metadata zones — promote is a meta rewrite plus a
    manifest append row (zero byte I/O, last-row-wins per altseq). quar is
    the exception with a physical root, so crossing the quar boundary
    rename()s each declared kind dir between namespaces. Emits per-kind
    asset events (state='verified') afterwards so the index vault_meta
    projection learns the new verdict.
    """
    idc = _check_idc(idc)
    arm = _comp(arm)
    variant = _comp(variant)
    altseq = _check_altseq(altseq)
    zone = _norm_zone(zone)
    verdict = _norm_verdict(verdict)
    _require_sentinel()
    sid = idnorm.safe_id(idc)
    key = dir_key(arm, variant, altseq)
    with locks.flock(paths.vault_lock_path(), exclusive=True):
        mpath = meta_path(idc, arm, variant, altseq)
        meta = _read_meta(mpath)
        if meta is None:
            msg = f"no parseable meta at {mpath} — nothing to promote"
            raise MetaMissing(msg)
        old_zone = _norm_zone(meta.get("zone", "pending"))
        moved: list[str] = []
        missing: list[str] = []
        try:
            if _zone_tag(old_zone) != _zone_tag(zone):
                for k in meta.get("files", {}):
                    src = _kind_root(old_zone, k) / sid / key
                    dst = _kind_root(zone, k) / sid / key
                    if not src.exists():
                        missing.append(k)
                        continue
                    if dst.exists():
                        msg = f"promote destination occupied: {dst}"
                        raise DestOccupied(msg)  # noqa: TRY301 -- raise 必须留在 try 内：except 回滚已搬动的 moved 集
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    # lift the root fuse so rename() may rewrite '..'
                    # (committed leaf dirs are 0555); re-fuse after landing.
                    st = src.stat()
                    os.chmod(src, stat.S_IMODE(st.st_mode) | stat.S_IWUSR)
                    os.rename(src, dst)
                    st = dst.stat()
                    os.chmod(dst, stat.S_IMODE(st.st_mode) & ~0o222)
                    fsutil.fsync_dir(dst)
                    _fsync_ancestors(dst.parent)
                    _fsync_ancestors(src.parent)
                    moved.append(k)
                if missing and not moved:
                    msg = (
                        f"promote {idc}/{arm}/{variant}/{altseq}: every "
                        f"declared kind missing under {old_zone} "
                        f"({missing}) — nothing to move"
                    )
                    raise VaultError(msg)  # noqa: TRY301 -- 同上：触发回滚的中止点
        except BaseException:
            for k in moved:
                dst = _kind_root(zone, k) / sid / key
                src = _kind_root(old_zone, k) / sid / key
                with suppress(OSError):
                    st = dst.stat()
                    os.chmod(dst, stat.S_IMODE(st.st_mode) | stat.S_IWUSR)
                    os.rename(dst, src)
                    st = src.stat()
                    os.chmod(src, stat.S_IMODE(st.st_mode) & ~0o222)
            raise
        meta["zone"] = zone
        meta["verdict"] = verdict
        meta["prev_zone"] = old_zone
        meta["ts"] = round(time.time(), 3)
        _write_meta(mpath, meta)
        _append_manifest_locked(
            {
                "op": "promote",
                "idc": idc,
                "arm": arm,
                "variant": variant,
                "altseq": altseq,
                "zone": zone,
                "verdict": verdict,
                "from_zone": old_zone,
                "path": f"{sid}/{key}",
                "moved": moved,
                "missing": missing,
                "bytes_ok": _copy_intact(meta),
                "source_run": source_run,
                "ts": round(time.time(), 3),
            }
        )
    for k in meta.get("files", {}):
        ev = events.make_event(
            events.T_ASSET,
            run=source_run,
            seq=None,
            id=idc,
            idc=idc,
            arm=arm,
            variant=variant,
            kind=k,
            path=_rel_leaf(zone, k, sid, key),
            sha=meta.get("asset_sha"),
            state="verified",
            verdict=verdict,
            zone=zone,
            altseq=altseq,
        )
        ledger.emit(ev, run_dir=run_dir, sink=sink)


def tombstone(
    idc,
    arm,
    variant,
    kind,
    reason,
    lost_run: str = "",
    id=None,  # noqa: A002 -- 事件行键名
    sink=None,
    run_dir=None,
) -> None:
    """Register lost bytes: a manifest tombstone row inside the vault lock,
    then a first-class tombstone event in the ledger (§3.1 — tombstones are
    events, not separate files). The regen gate reads these rows upstream."""
    idc = _check_idc(idc)
    arm = _comp(arm)
    variant = _comp(variant)
    _require_sentinel()
    ts = round(time.time(), 3)
    with locks.flock(paths.vault_lock_path(), exclusive=True):
        _append_manifest_locked(
            {
                "op": "tombstone",
                "idc": idc,
                "arm": arm,
                "variant": variant,
                "kind": kind,
                "reason": reason,
                "lost_run": lost_run,
                "zone": "tombstone",
                "ts": ts,
            }
        )
        # 墓碑是 kind 级语义但副本整体留在 primary/intact——不标记则
        # _select_copy/dedup_hit/qc 复测仍把旧字节当现役产物读（2609-28
        # regen 复测误读 altseq=0 实证）。给声明了该 kind 的每个副本 meta
        # 打 tombstoned_kinds 标记：coverage/物化/dedup 全部让位活 kind。
        for mp, mkey, mmeta in _iter_metas_for(idc):
            if mkey is None or mmeta is None or mkey[1:3] != (arm, variant):
                continue
            if kind not in (mmeta.get("files") or {}):
                continue
            tk = mmeta.setdefault("tombstoned_kinds", [])
            if kind not in tk:
                tk.append(kind)
                tk.sort()
                mmeta["ts"] = ts
                _write_meta(mp, mmeta)
    ev = events.make_event(
        events.T_TOMBSTONE,
        id=id or idc,
        idc=idc,
        arm=arm,
        variant=variant,
        kind=kind,
        reason=reason,
        lost_run=lost_run,
        ts=ts,
    )
    ledger.emit(ev, run_dir=run_dir, sink=sink)
