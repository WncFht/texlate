"""kernel._vault_restore — vault→work 物化 (kernel.vault 拆分叶).

``restore`` 按 (coverage desc, product-bad asc, zone_rank, altseq) 选最
优完好副本，逐声明 kind 物化到 ``dest/{kind}.{arm}[@{variant}]/``:
mode='copy' 出主可写新字节 (mutating 消费方安全项), mode='link' 共押
0444 inode 零拷 (只读消费方契约——写入即响亮 EACCES, 绝不沉默毒库，
§3.10.4)。墓碑 kind 不物化。无完好副本只抛不哑补。
"""

from __future__ import annotations

from pathlib import Path

from kernel import fsutil, idnorm, locks, paths
from kernel._vault_cred import (
    _ZONE_RANK,
    VaultError,
    _check_idc,
    _comp,
    _kind_root,
    _norm_zone,
    _work_dirname,
    dir_key,
)
from kernel._vault_intact import _copy_intact, _copy_product_bad
from kernel._vault_io import _iter_files, _iter_metas, _require_sentinel


def restore(idc, arm, variant, dest, altseq=None, mode: str = "copy") -> int:
    """vault -> work materialization of the best intact copy.

    Picks the first intact copy by zone preference (primary > alt > quar >
    pending), then materializes each declared kind under
    ``dest/{kind}.{arm}[@{variant}]/``:

    - mode='copy' (default): fsutil.copy_mutating — fresh owner-writable
      bytes; the safe choice for mutating consumers (fixloop/replay would
      otherwise hit the 0444 fuse as EACCES).
    - mode='link': fsutil.hardlink_farm — zero-copy sharing of the vault
      inodes, which stay read-only. CALLER CONTRACT: read-only consumers
      only; a mutating consumer gets a loud EACCES, never silent poisoning.

    Raises VaultError when no intact copy exists — damaged credentials are
    restored only by explicit operator handling, never silently."""
    idc = _check_idc(idc)
    arm = _comp(arm)
    variant = _comp(variant)
    if mode not in ("copy", "link"):
        msg = f"restore mode must be 'copy'|'link', got {mode!r}"
        raise ValueError(msg)
    _require_sentinel()
    dest = Path(dest)
    with locks.flock(paths.vault_lock_path(), exclusive=False):
        meta = _select_copy(idc, arm, variant, altseq)
        if meta is None:
            msg = f"no intact committed copy for ({idc},{arm},{variant},{altseq})"
            raise VaultError(msg)
        zone = _norm_zone(meta.get("zone", "pending"))
        sid = idnorm.safe_id(idc)
        key = dir_key(arm, variant, meta.get("altseq", "0"))
        dead = set(meta.get("tombstoned_kinds") or ())
        made = 0
        for kind in meta.get("files", {}):
            if kind in dead:
                continue  # 墓碑 kind 不物化——字节已判失，送出即沉默喂旧货
            src = _kind_root(zone, kind) / sid / key
            d = dest / _work_dirname(kind, arm, variant)
            if mode == "link":
                fsutil.hardlink_farm(src, d)
            else:
                fsutil.copy_mutating(src, d)
            made += len(_iter_files(d))
        return made


def _select_copy(idc: str, arm: str, variant: str, altseq) -> dict | None:
    """Best intact copy for restore: exact altseq when given, else by kind
    coverage, product presence, zone preference, then lowest altseq.

    Ranking order is (coverage desc, product-bad asc, zone_rank, altseq):
    richer-kind copies serve more consumers (state hydration must not lose
    to a fuller copy), and among equal-coverage copies a product-bearing
    one always wins — a pdf-less splice shell can never shadow a repaired
    sibling (the reseal/clobber rescue). Product-badness demotes, never
    excludes: when every copy is product-less the last-resort copy still
    serves tex-workspace/zh hydrators — a hard gate would deadlock the
    fixloop repair path it is meant to unblock."""
    cands = []
    for _mp, key, meta in _iter_metas():
        if key is None or meta is None or key[:3] != (idc, arm, variant):
            continue
        if altseq is not None and key[3] != str(altseq):
            continue
        try:
            z = _norm_zone(meta.get("zone", "pending"))
        except ValueError:
            continue
        if not _copy_intact(meta):
            continue
        files = meta.get("files")
        live = (
            len(set(files) - set(meta.get("tombstoned_kinds") or ()))
            if isinstance(files, dict)
            else 0
        )
        coverage = -live
        cands.append(
            (coverage, _copy_product_bad(meta), _ZONE_RANK.get(z, 4), key[3], meta)
        )
    if not cands:
        return None
    cands.sort(key=lambda t: t[:4])
    return cands[0][4]
