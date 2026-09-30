"""kernel._cli_ledger — ledger 子动词叶 (kernel.cli 拆分叶).

``bench ledger`` 的四动词: import (bench.db / jsonl / scan 目录 / zhstore
manifest 三源分派)、ingest (外部写者道 run='external' 固定)、
rebuild-index (抹平重放派生 index)、tail-ingest (增量追平)。
写动词一律先 ``_pre_write()`` 轻扫 (§2.4)。

门面回引名单见 ``kernel.cli._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

from pathlib import Path

from kernel import importer
from kernel import index as index_mod
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


def _cmd_ledger_import(args) -> int:
    _pre_write()
    p = Path(args.path)
    if not p.exists():
        _err(f"import source not found: {p}")
        return EXIT_REFUSED
    idx = _open_index()
    try:
        reg = _load_registry()
        if args.manifest or args.bytes_root:
            if not (args.manifest and args.bytes_root):
                _err("zhstore import needs --manifest AND --bytes-root")
                return EXIT_REFUSED
            res = importer.import_zhstore(
                args.manifest, args.bytes_root, idx, registry=reg, dry=args.dry
            )
        elif p.is_dir():
            res = importer.import_all({"scan_root": p}, idx, registry=reg, dry=args.dry)
        elif p.suffix in (".db", ".sqlite", ".sqlite3"):
            res = importer.import_benchdb(p, idx, registry=reg, dry=args.dry)
        else:
            res = importer.import_jsonl_file(
                p, run=args.run, index=idx, registry=reg, dry=args.dry
            )
    except Exception as exc:
        _err(f"ledger import failed: {exc}")
        return EXIT_FAIL
    finally:
        idx.close()
    _print_json(res)
    return EXIT_OK


def _cmd_ledger_ingest(args) -> int:
    """External-writer lane (§5): run='external', ledger-assigned seqs."""
    _pre_write()
    p = Path(args.external)
    if not p.is_file():
        _err(f"ingest source not found: {p}")
        return EXIT_REFUSED
    idx = _open_index()
    try:
        res = importer.import_jsonl_file(
            p,
            run=args.run or "external",
            index=idx,
            registry=_load_registry(),
            dry=args.dry,
        )
    except Exception as exc:
        _err(f"ledger ingest failed: {exc}")
        return EXIT_FAIL
    finally:
        idx.close()
    _print_json(res)
    return EXIT_OK


def _cmd_ledger_rebuild(_args) -> int:
    _pre_write()
    try:
        idx = index_mod.rebuild_index()
    except Exception as exc:
        _err(f"rebuild-index failed: {exc}")
        return EXIT_FAIL
    try:
        gen, wm = idx.sealed_state()
        print(f"rebuild-index: sealed_gen={gen} watermark={wm}")
    finally:
        idx.close()
    return EXIT_OK


def _cmd_ledger_tail(_args) -> int:
    _pre_write()
    idx = index_mod.Index()
    try:
        n = idx.tail_ingest()
        gen, wm = idx.sealed_state()
    finally:
        idx.close()
    print(f"tail-ingest: applied={n} sealed_gen={gen} watermark={wm}")
    return EXIT_OK
