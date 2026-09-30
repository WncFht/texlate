"""kernel._cli_vault — vault 子动词叶 (kernel.cli 拆分叶).

``bench vault`` 的七个写/读动词: verify (三层校验, clean 才刷新
首火闸 freshness stamp)、restore、adopt、tombstone、seed (Phase-2
zh-store 字节普查入 vault)、slim (P3 splice 留存)、cas-link
(≥256KiB 硬链 retroverb)、rekey (variant 键域收养)。写动词一律先
``_pre_write()`` 轻扫 (§2.4)。

门面回引名单见 ``kernel.cli._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from kernel import fsutil, importer, paths, vault
from kernel._cli_common import (
    EXIT_FAIL,
    EXIT_OK,
    EXIT_REFUSED,
    _err,
    _load_registry,
    _open_index,
    _pre_write,
    _print_json,
)


def _cmd_vault_verify(args) -> int:
    rep = vault.verify(level=args.level)
    print(
        f"vault verify[{rep['level']}]: metas={rep['metas']}"
        f" checked={rep['checked']} inodes={rep['inodes']}"
        f" bad={len(rep['bad'])} meta_bad={len(rep['meta_bad'])}"
        f" meta_missing={len(rep['meta_missing'])}"
        f" extra={len(rep['extra'])}"
    )
    for b in rep["bad"][:20]:
        print(f"  bad: {b.get('reason')} {b.get('paths')}")
    for m in rep["meta_bad"][:20]:
        print(f"  meta_bad: {m}")
    for m in rep["meta_missing"][:20]:
        print(f"  meta_missing (orphan dir): {m}")
    bad = rep["bad"] or rep["meta_bad"]
    if not bad:
        # first-fire gate evidence (§6 Phase-3 首火闸): only a CLEAN pass
        # refreshes freshness — a verify that found rot must not stamp.
        stamp = {
            "ts": round(time.time(), 3),
            "level": rep["level"],
            "metas": rep["metas"],
            "checked": rep["checked"],
            "meta_missing": len(rep["meta_missing"]),
        }
        fsutil.atomic_write(
            paths.vault_verify_stamp_path(),
            (json.dumps(stamp, sort_keys=True) + "\n").encode("utf-8"),
        )
    return EXIT_FAIL if bad else EXIT_OK


def _cmd_vault_restore(args) -> int:
    _pre_write()
    try:
        n = vault.restore(
            args.idc,
            args.arm,
            args.variant,
            args.dest,
            altseq=args.altseq,
            mode=args.mode,
        )
    except Exception as exc:
        _err(f"vault restore failed: {exc}")
        return EXIT_FAIL
    print(f"restored {n} file(s) -> {args.dest} (mode={args.mode})")
    return EXIT_OK


def _cmd_vault_adopt(args) -> int:
    _pre_write()
    try:
        leaf = vault.adopt(
            args.dir,
            args.idc,
            arm=args.arm,
            variant=args.variant,
            reason=args.reason,
            kind=args.kind,
        )
    except Exception as exc:
        _err(f"vault adopt failed: {exc}")
        return EXIT_FAIL
    print(f"adopted -> {leaf}")
    return EXIT_OK


def _cmd_vault_tombstone(args) -> int:
    _pre_write()
    try:
        vault.tombstone(
            args.idc,
            args.arm,
            args.variant,
            args.kind,
            args.reason,
            lost_run=args.lost_run or "",
        )
    except Exception as exc:
        _err(f"vault tombstone failed: {exc}")
        return EXIT_FAIL
    print(
        f"tombstoned ({args.idc},{args.arm},{args.variant},{args.kind})"
        f" reason={args.reason}"
    )
    return EXIT_OK


def _cmd_vault_seed(args) -> int:
    """Phase-2 live-byte census — zh-store bytes -> vault (§3.10.9)."""
    _pre_write()
    if not Path(args.manifest).is_file():
        _err(f"manifest not found: {args.manifest}")
        return EXIT_REFUSED
    if not Path(args.bytes_root).is_dir():
        _err(f"bytes root not found: {args.bytes_root}")
        return EXIT_REFUSED
    idx = _open_index()
    try:
        res = importer.seed_vault_zhstore(
            args.manifest,
            args.bytes_root,
            idx,
            registry=_load_registry(),
            dry=args.dry,
        )
    except Exception as exc:
        _err(f"vault seed failed: {exc}")
        return EXIT_FAIL
    finally:
        idx.close()
    _print_json(res)
    return EXIT_OK


def _cmd_vault_slim(args) -> int:
    """P3 retention: committed splice leaves → final pdf + arm json + logs."""
    _pre_write()
    rows = vault.slim_splice(idc=args.idc, dry=args.dry)
    freed = sum(r["dropped_bytes"] for r in rows)
    verb = "would slim" if args.dry else "slimmed"
    for r in rows:
        print(
            f"  {verb} {r['zone']}/{r['sid']}/{r['key']}"
            f"  kept={len(r['kept'])} dropped_bytes={r['dropped_bytes']}"
            + ("" if r.get("meta", True) else "  (no meta)")
        )
    print(
        f"vault slim: {len(rows)} leaf(s) {verb},"
        f" freed={freed} bytes ({freed / 2**20:.1f} MiB)"
    )
    return EXIT_OK


def _cmd_vault_cas_link(args) -> int:
    """P3 retention: CAS-link committed leaves (retroverb for pre-hook
    harvests); new writes link inside harvest itself."""
    _pre_write()
    rows = vault.cas_link_leaves(kind=args.kind, idc=args.idc, dry=args.dry)
    moved = sum(r["bytes"] for r in rows)
    linked = sum(r["linked"] for r in rows)
    cand = sum(r.get("candidates", r["linked"]) for r in rows)
    verb = "would link" if args.dry else "linked"
    print(
        f"vault cas-link: {len(rows)} leaf(s) scanned,"
        f" {cand} candidate file(s) ≥{vault.CAS_LINK_FLOOR}B,"
        f" {linked} {verb}, {moved} bytes ({moved / 2**20:.1f} MiB) projected"
    )
    return EXIT_OK


def _cmd_vault_rekey(args) -> int:
    """Variant adopt: intact src-variant paid kinds -> dst keyspace."""
    _pre_write()
    kinds = (
        [k.strip() for k in args.kinds.split(",") if k.strip()] if args.kinds else None
    )
    try:
        rows = vault.rekey(
            args.src,
            args.dst,
            arm=args.arm,
            idc=args.idc,
            kinds=kinds,
            dry=args.dry,
        )
    except Exception as exc:
        _err(f"vault rekey failed: {exc}")
        return EXIT_FAIL
    n_err = sum(1 for r in rows if "error" in r)
    verb = "would rekey" if args.dry else "rekeyed"
    for r in rows:
        print(
            f"  {verb} ({r['idc']},{r['arm']})"
            f" {'+'.join(r['kinds'])}"
            f" {r['src_variant']}->{r['dst_variant']}"
            + (
                f"  skipped={'+'.join(r['skipped_kinds'])}"
                if r["skipped_kinds"]
                else ""
            )
            + (f"  ERROR {r['error']}" if "error" in r else "")
        )
    print(f"vault rekey: {len(rows)} cell(s) {verb}, errors={n_err}")
    return EXIT_FAIL if n_err else EXIT_OK
