"""kernel._vault_query — dedup 判词与副本列举 (kernel.vault 拆分叶).

``bytes_ok`` 是物理判据 (meta 可解析 + 声明件全部在场非空——目录存在
永不作数，pending 也算真字节); ``dedup_hit`` 是 §3.8 政策判据 (完好
且 verdict ∈ DEDUP_VERDICTS, pending/tombstone 不抵)。``query``/
``pending_metas`` 是逐格 meta 行列举 (sweep 的 promote 队列源头)。
"""

from __future__ import annotations

from kernel._vault_cred import DEDUP_VERDICTS, _check_idc, _comp
from kernel._vault_intact import _copy_intact
from kernel._vault_io import _iter_metas, _iter_metas_for


def bytes_ok(idc, arm, variant, altseq=None) -> bool:
    """THE physical dedup criterion: some matching copy has a parseable meta
    AND every asset it declares present non-empty on disk. Directory
    existence NEVER counts. Verdict policy is NOT applied here — see
    dedup_hit() for the §3.8 composition."""
    idc = _check_idc(idc)
    arm = _comp(arm)
    variant = _comp(variant)
    for _mp, key, meta in _iter_metas():
        if key is None or meta is None:
            continue
        if key[:3] != (idc, arm, variant):
            continue
        if altseq is not None and key[3] != str(altseq):
            continue
        if _copy_intact(meta):
            return True
    return False


def dedup_hit(idc, arm, variant) -> bool:
    """§3.8 dedup oracle: an intact copy whose verdict dedups
    (primary|alt|quar|adopted|verified). pending and tombstone copies do
    not count — the claim lock-recheck and regen gate own those states."""
    for row in query(idc, arm, variant):
        if row.get("_parse_error") or row.get("verdict") not in DEDUP_VERDICTS:
            continue
        files = row.get("files") or {}
        if files and len(set(files) - set(row.get("tombstoned_kinds") or ())) == 0:
            continue  # 全 kind 墓碑化的副本不抵 dedup——字节已判失，须重产
        if row["bytes_ok"]:
            return True
    return False


def query(idc, arm: str = "*", variant: str = "*") -> list[dict]:
    """All copies (metas) for a cell — '*' wildcards on arm/variant.
    Rows are the meta content plus filename-authoritative idc/arm/variant/
    altseq, meta_path, bytes_ok (physical intactness), and _parse_error on
    corrupt metas. Sorted by (altseq, name)."""
    idc = _check_idc(idc)
    rows = []
    for mp, key, meta in _iter_metas_for(idc):
        if key is None:
            continue
        kidc, karm, kvar, kalt = key
        if kidc != idc:
            continue
        if arm not in ("*", karm):
            continue
        if variant not in ("*", kvar):
            continue
        row = dict(meta) if meta is not None else {}
        row.update(
            {
                "idc": kidc,
                "arm": karm,
                "variant": kvar,
                "altseq": kalt,
                "meta_path": str(mp),
            }
        )
        if meta is None:
            row["_parse_error"] = True
            row["bytes_ok"] = False
        else:
            row["bytes_ok"] = _copy_intact(meta)
        rows.append(row)
    rows.sort(key=lambda r: (r["altseq"], r["meta_path"]))
    return rows


def pending_metas() -> list[dict]:
    """Metas still in zone='pending' — the sweep's promote queue."""
    out = []
    for mp, key, meta in _iter_metas():
        if key is None or meta is None:
            continue
        if meta.get("zone") == "pending":
            row = dict(meta)
            row.update(
                {
                    "idc": key[0],
                    "arm": key[1],
                    "variant": key[2],
                    "altseq": key[3],
                    "meta_path": str(mp),
                }
            )
            out.append(row)
    return out
