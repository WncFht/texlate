"""kernel._cli_lake — lake 子动词叶 (kernel.cli 拆分叶).

``bench lake`` 的七个动词: status (catalog + 容量 + CAS 对象账)、
pin/unpin (PINNED marker + catalog pinned 字段)、evict (LRU 向目标
字节)、evict-done (已入 vault 的 paid zh 格淘汰——e2e_real 期与
soak 期双代凭据)、register (manifest 骨架行)、absorb (旧语料树
CAS 化吸入)。写动词一律先 ``_pre_write()`` 轻扫 (§2.4)。

门面回引名单见 ``kernel.cli._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import os
from pathlib import Path

from kernel import cas, events, fsutil, idnorm, importer, lake, paths, vault
from kernel._cli_common import (
    EXIT_FAIL,
    EXIT_OK,
    EXIT_REFUSED,
    _err,
    _load_registry,
    _open_index,
    _parse_size,
    _pre_write,
    _print_json,
)


def _cmd_lake_status(_args) -> int:
    cat = lake.LakeCatalog.load()
    rows = cat.rows()
    tally: dict[str, int] = {}
    pinned_rows: list[dict] = []
    for r in rows.values():
        st = str(r.get("state", "?"))
        tally[st] = tally.get(st, 0) + 1
        if lake._pinned(r):
            pinned_rows.append(r)
    corpus = paths.lake_corpus_dir()
    nbytes = fsutil.dir_size(corpus) if corpus.exists() else 0
    pin_bytes = 0
    for r in pinned_rows:
        d = lake.cell_dir(r["idc"], r.get("source") or "arxiv")
        if d.is_dir():
            pin_bytes += fsutil.dir_size(d)
    cap_gb = os.environ.get("TEXLATE_LAKE_CAP_GB", "100")
    print(f"lake: {paths.lake_dir()}")
    print(f"  cells={len(rows)} corpus_bytes={nbytes} cap_gb={cap_gb}")
    for st, n in sorted(tally.items()):
        print(f"  {st:<12} {n}")
    print(f"  pinned={len(pinned_rows)} pinned_bytes={pin_bytes}")
    try:
        ostat = cas.stat()
    except Exception:
        ostat = None
    if ostat:
        print(
            f"  objects: blobs={ostat.get('blob', {}).get('n', 0)}"
            f" files={ostat.get('file', {}).get('n', 0)}"
        )
    return EXIT_OK


def _cmd_lake_pin(args, *, unpin: bool = False) -> int:
    """``bench lake pin|unpin <id>...`` — cell-side PINNED marker + catalog
    ``pinned`` field; canon 归一 same as the register arm."""
    _pre_write()
    verb = "unpin" if unpin else "pin"
    cat = lake.LakeCatalog.load()
    bad = 0
    for raw in args.ids:
        res = idnorm.canon_id(raw)
        if not res.ok:
            _err(f"{verb}: {raw!r} is not canon ({res.state} {res.reason})")
            bad += 1
            continue
        if unpin:
            row = cat.unpin(res.idc, source=args.source)
            if row is None:
                print(f"{res.idc}: not pinned (absent)")
            else:
                print(f"unpinned {res.idc}")
        else:
            cat.pin(res.idc, source=args.source)
            print(f"pinned {res.idc} -> {lake.cell_dir(res.idc, args.source)}")
    return EXIT_FAIL if bad else EXIT_OK


def _cmd_lake_unpin(args) -> int:
    return _cmd_lake_pin(args, unpin=True)


def _cmd_lake_evict(args) -> int:
    _pre_write()
    try:
        target = _parse_size(args.to_free)
    except ValueError as exc:
        _err(str(exc))
        return EXIT_REFUSED
    removed = lake.evict(target)
    print(f"evicted {len(removed)} path(s) toward {target} freed bytes:")
    for p in removed:
        print(f"  {p}")
    return EXIT_OK


_PIPELINE_STAGES = (
    "route",
    "ingest",
    "parse",
    "xlat",
    "splice",
    "compile",
    "fixloop",
    "layoutqc",
)


def _evict_done_targets(idx) -> list[str]:
    """idcs whose paid product no longer needs the lake cell, two eras:

    - e2e_real 期：the LAST ``records`` row at stage='layoutqc' is 'ok'
      (rowid order = ledger order, the _last_done convention) AND an
      arm='real' vault meta vouches intact zh bytes.
    - soak 期（无 layoutqc 段、封 '-' arm）：末条非 dedup 管线账
      ∈ {ok,clean}（rowid 序）AND arm='-' meta zh 完好。

    filename key is the credential; _kind_intact stat-verifies every
    declared file. Both legs fail-closed: a torn meta or a missing file
    drops the idc off the list.

    KERNEL 状态（dedup/claimed/lost/unpaid_gate）非格态裁决——dedup 是
    借用前判、lost 是 run 级僵尸回收标记（回收时机晚于格在后续 run
    完成时会逆序遮蔽真实终态）——两脈都只取最后一条真裁决账。"""
    kph = ",".join("?" for _ in events.STATUS_KERNEL)
    rows = idx.conn.execute(
        f"SELECT idc, status FROM records WHERE stage='layoutqc'"  # noqa: S608 -- marks 是 "?"*n 占位符
        f" AND status NOT IN ({kph}) ORDER BY rowid",
        tuple(sorted(events.STATUS_KERNEL)),
    ).fetchall()
    last: dict[str, str] = {}
    for r in rows:
        last[r["idc"]] = r["status"]
    qc_ok = {i for i, s in last.items() if s == "ok"}

    ph = ",".join("?" * len(_PIPELINE_STAGES))
    rows2 = idx.conn.execute(
        f"SELECT idc, status FROM records"  # noqa: S608 -- 两段 IN 都是 "?"*n 占位符
        f" WHERE status NOT IN ({kph})"
        f" AND stage IN ({ph}) ORDER BY rowid",
        (*sorted(events.STATUS_KERNEL), *_PIPELINE_STAGES),
    ).fetchall()
    last2: dict[str, str] = {}
    for r in rows2:
        last2[r["idc"]] = r["status"]
    term_ok = {i for i, s in last2.items() if s in ("ok", "clean")}

    vaulted_real: set[str] = set()
    vaulted_dash: set[str] = set()
    for _mp, key, meta in vault._iter_metas():
        if key is None or meta is None:
            continue
        if key[1] == "real" and key[0] in qc_ok and vault._kind_intact(meta, "zh"):
            vaulted_real.add(key[0])
        elif key[1] == "-" and key[0] in term_ok and vault._kind_intact(meta, "zh"):
            vaulted_dash.add(key[0])
    return sorted((qc_ok & vaulted_real) | (term_ok & vaulted_dash))


def _cmd_lake_evict_done(args) -> int:
    """Evict lake cells whose zh is already vaulted (done-with pipeline)."""
    _pre_write()
    idx = _open_index()
    try:
        targets = _evict_done_targets(idx)
    finally:
        idx.close()
    if not targets:
        print(
            "lake evict-done: no eligible cells (need last layoutqc ok "
            "+ intact real-arm zh, or soak-era last pipeline record "
            "ok/clean + intact '-' arm zh in vault)"
        )
        return EXIT_OK
    tally: dict[str, int] = {}
    freed = 0
    n_err = 0
    cat = lake.LakeCatalog.load()
    for idc in targets:
        if args.dry:
            row = cat.rows().get(idc, {})
            d = lake.cell_dir(idc, row.get("source") or "arxiv")
            size = fsutil.dir_size(d) if d.is_dir() else 0
            pin_note = "  (pinned — would skip)" if lake._pinned(row) else ""
            print(
                f"  would evict {idc}  state={row.get('state', 'absent')}"
                f" cell_bytes={size}{pin_note}"
            )
            continue
        try:
            res = lake.evict_cell(idc, keep_raw=args.keep_raw)
        except Exception as exc:
            n_err += 1
            _err(f"  evict-done {idc}: {exc}")
            continue
        result = res["result"]
        tally[result] = tally.get(result, 0) + 1
        freed += res["freed"]
        detail = (
            f" ({res['reason']})" if result == "skipped" else f" freed={res['freed']}"
        )
        print(f"  {result:<8} {idc}{detail}")
    verb = "would evict" if args.dry else "done"
    print(
        f"lake evict-done: {len(targets)} eligible, {verb}"
        + (
            ""
            if args.dry
            else f" — {' '.join(f'{k}={v}' for k, v in sorted(tally.items()))}"
            f" freed={freed} bytes ({freed / 2**20:.1f} MiB)"
            f" errors={n_err}"
        )
    )
    return EXIT_FAIL if n_err else EXIT_OK


def _cmd_lake_register(args) -> int:
    _pre_write()
    if args.manifests:
        idx = _open_index()
        try:
            res = importer.register_lake_manifests(
                args.manifests, idx, registry=_load_registry(), dry=args.dry
            )
        except Exception as exc:
            _err(f"lake register failed: {exc}")
            return EXIT_FAIL
        finally:
            idx.close()
        _print_json(res)
        return EXIT_OK
    if not args.ids:
        _err("register: give ids or --manifests")
        return EXIT_REFUSED
    bad = 0
    for raw in args.ids:
        res = idnorm.canon_id(raw)
        if not res.ok:
            _err(f"register: {raw!r} is not canon ({res.state} {res.reason})")
            bad += 1
            continue
        d = lake.register_skeleton(res.idc)
        print(f"registered {res.idc} -> {d}")
    return EXIT_FAIL if bad else EXIT_OK


def _cmd_lake_absorb(args) -> int:
    _pre_write()
    if not Path(args.root).is_dir():
        _err(f"absorb root not found: {args.root}")
        return EXIT_REFUSED
    idx = _open_index()
    try:
        res = importer.absorb_corpus(
            args.root,
            idx,
            registry=_load_registry(),
            manifests=args.manifests,
            dry=args.dry,
            source=args.source,
        )
    except Exception as exc:
        _err(f"lake absorb failed: {exc}")
        return EXIT_FAIL
    finally:
        idx.close()
    _print_json(res)
    return EXIT_OK
