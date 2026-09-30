"""Phase 1 import pipeline — legacy data plane -> trizone ledger.

Implements the import scope of docs/spec/bench-trizone.md §6
Phase 1 with the §3.3 ordering contract and the §3.10.7 canon gate:

- Sources: bench.db (records/eval_records/cases/cells tables), worktree
  records*.jsonl / cases.jsonl files, and the zh-store manifest.jsonl +
  byte census.
- Idempotent by line-content hash: every emitted event is deterministic
  (timestamps come from row data, never wall clock), so a re-import
  produces identical payload_shas and is filtered against the index
  dedupe table BEFORE hitting the ledger. Quarantine rows get the same
  treatment via a sha-set over quarantine.jsonl.
- Secrets are redacted on the way in (R1): the configured gateway key
  substrings (env-resolved), tailscale 100.64.0.0/10 addresses, and auth-ish JSON field
  values are replaced with {"$redact": sha256_of_original} so the ledger
  keeps verifiability without keeping the secret.
- Canon gate (§3.10.7): canon_id() Ok -> event carries idc;
  Ambig/Invalid -> the whole row goes to ledger/quarantine.jsonl.
- Ordering (§3.3): runs sort by (run_meta.started_at -> dir mtime ->
  run name); run_seq is minted in that order so the (run_seq, seq)
  total order approximates chronology. Order-sensitive cell keys (same
  key, multiple terminal statuses) are reported to quarantine and
  resolved CONSERVATIVE: paid cells prefer done-ish terminal
  (ok|partial|clean — protects quota), free cells prefer non-terminal
  (protects truth — the cell reruns).
- Writes go through ledger.emit_batch in ~5000-event chunks (never
  per-row emit() — the 197k-line/7min trap) and index.apply_events in
  the same chunks. Ledger stays the source of truth; the index is
  disposable.

Known simplifications (flagged, not hidden):
- Paidness is an ARM property here: PAID_ARMS = {"real"}. bench.db has
  no per-stage paid flag; arm=='real' is the gateway arm.
- eval_records/cases/cells rows become stage='<table>' cell events with
  the whole (redacted) raw payload in metrics; status = row.status /
  raw.status / 'ok'. A non-vocab status maps to 'fault' + the original
  in metrics._orig_status (fail-loud, never silently retriable).
- records rows with NULL status map to 'fault' (conservative terminal);
  case-type rows default to 'ok' (the row's existence IS the record).

C5 拆分：实现体按源域拆进同包私有叶 —— ``_import_core`` (共享机件：
密钥面/脱敏/隔离/闸/run 注册/行规整/事件转换/落账)、
``_import_records`` (bench.db + worktree jsonl 源)、
``_import_zhstore`` (zh-store manifest + Phase 2 vault 播种)、
``_import_lake`` (lake manifest 注册 + corpus 吸收); 本文件是 PEP 562
惰性门面 (同 ``fixloop/builtins/__init__`` 形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``importer.X`` 公共面与 ``from ... import X`` 测试面不变。
monkeypatch 锚点注意：测试若做 setattr patch 须指到叶子模块
(惰性解析下 ``importer._x`` 可读，但 setattr 只遮蔽门面不改叶子)。
``import_all`` 是各源组合根而非源实现，留驻本门面 (调用点已到运行期
才惰性拉叶，同 builtins 门面 ``graphics_kv_strip_obsolete`` 先例)。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kernel._import_core import (
        EMIT_CHUNK,
        PAID_ARMS,
        SECRET_PATTERNS,
        _norm_db_record,
        _rec_to_event,
        _status_of,
        redact,
    )
    from kernel._import_lake import absorb_corpus, register_lake_manifests
    from kernel._import_records import import_benchdb, import_jsonl_file
    from kernel._import_zhstore import import_zhstore, seed_vault_zhstore

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_import_core": (
        "EMIT_CHUNK",
        "PAID_ARMS",
        "SECRET_PATTERNS",
        "_norm_db_record",
        "_rec_to_event",
        "_status_of",
        "redact",
    ),
    "_import_lake": (
        "absorb_corpus",
        "register_lake_manifests",
    ),
    "_import_records": (
        "import_benchdb",
        "import_jsonl_file",
    ),
    "_import_zhstore": (
        "import_zhstore",
        "seed_vault_zhstore",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集 +
# 本地组合根 import_all, 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "EMIT_CHUNK",
    "PAID_ARMS",
    "SECRET_PATTERNS",
    "_norm_db_record",
    "_rec_to_event",
    "_status_of",
    "absorb_corpus",
    "import_all",
    "import_benchdb",
    "import_jsonl_file",
    "import_zhstore",
    "redact",
    "register_lake_manifests",
    "seed_vault_zhstore",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"{__package__}.{leaf}"), name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return __all__


def _export_drift() -> list[str]:
    """``__all__``/``_LEAF_EXPORTS``/本地公共名三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。三向覆盖：

    - ``_LAZY`` 键全进 ``__all__``;
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链 (``_LEAF_EXPORTS``
      配名叶子不提供) 与幽灵条 (既非叶子名也非本地名) 在此曝，是首访
      ``AttributeError`` 唯一的提前闸;
    - 本地公共名 (本模块定义的函数/类) 全进 ``__all__``。

    审计实载全部叶子，只供测试调用，装载期不自检。
    """
    mod = sys.modules[__name__]
    drift = [
        f"{name} in _LEAF_EXPORTS but missing from __all__"
        for name in _LAZY
        if name not in __all__
    ]
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    drift += [
        f"leaf stem {stem!r} shadows an exported name (rename the leaf)"
        for stem in _LEAF_EXPORTS
        if stem in _LAZY
    ]
    for name in __all__:
        try:
            getattr(mod, name)
        except Exception as exc:  # 审计兜全漂移，非首错即死
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and callable(v)
        and getattr(v, "__module__", None) == __name__
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift


# ---------------------------------------------------------------------------
# Umbrella
# ---------------------------------------------------------------------------

# scan_root sweep patterns: flat ledgers + case files + recovered
# eval/cells ledgers; stagerun stage files (records/{stage}.jsonl)
# are picked up via records/ dir contents in import_all.
_SCAN_PATTERNS = (
    "records*.jsonl",
    "cases.jsonl",
    "eval-records*.jsonl",
    "cells*.jsonl",
)


def import_all(sources: dict, index, registry=None, dry: bool = False) -> dict:
    """Drive every configured source and merge counters.

    sources keys:
        benchdb     -> path to bench.db
        jsonl_files -> iterable of records*.jsonl/cases.jsonl paths
        scan_root   -> dir; every records*.jsonl/cases.jsonl under it is
                       imported, one ledger run per file
        zhstore     -> {"manifest": path, "bytes_root": path} or a
                       (manifest, bytes_root) tuple
    """
    # 组合根惰性拉叶——门面装载保持 ledger-only 廉价 (同 builtins 门面先例)。
    from kernel._import_core import _slugify, _stats
    from kernel._import_records import import_benchdb, import_jsonl_file
    from kernel._import_zhstore import import_zhstore

    total = _stats()
    total["per_source"] = {}

    def merge(key, res):
        total["per_source"][key] = res
        for k, v in res.items():
            if isinstance(v, int) and k in total:
                total[k] += v

    if sources.get("benchdb"):
        merge(
            "benchdb",
            import_benchdb(sources["benchdb"], index, registry=registry, dry=dry),
        )

    # jsonl files: one ledger run per FILE — per-file seqs can never
    # collide on (run_seq, seq). Explicit files get a name-derived run;
    # scan_root files carry their scan-relative path so two same-named
    # files in different dirs stay distinct.
    files = [(Path(f), None) for f in sources.get("jsonl_files") or []]
    scan = sources.get("scan_root")
    if scan:
        scan = Path(scan)
        seen: set[Path] = set()

        def _add(f: Path) -> None:
            if not f.is_file() or f in seen:
                return
            seen.add(f)
            rel = f.relative_to(scan).with_suffix("").as_posix()
            files.append((f, f"import-{_slugify(rel)}"))

        for pat in _SCAN_PATTERNS:
            for f in sorted(scan.rglob(pat)):
                _add(f)
        # stagerun stage ledgers live as records/{stage}.jsonl — the
        # stage name is the file stem, so the records-dir sweep is the
        # only way "records jsonl 全扫" actually reaches them.
        for d in sorted(scan.rglob("records")):
            if d.is_dir():
                for f in sorted(d.glob("*.jsonl")):
                    _add(f)
    acc = _stats()
    for f, run_name in files:
        stage_map = {f.name: f.stem} if f.parent.name == "records" else None
        r = import_jsonl_file(
            f,
            run=run_name,
            index=index,
            stage_map=stage_map,
            registry=registry,
            dry=dry,
        )
        for k, v in r.items():
            if isinstance(v, int) and k in acc:
                acc[k] += v
    if files:
        merge("jsonl", acc)

    if sources.get("zhstore"):
        zs = sources["zhstore"]
        if isinstance(zs, dict):
            mpath, broot_ = zs["manifest"], zs["bytes_root"]
        else:
            mpath, broot_ = zs
        merge(
            "zhstore", import_zhstore(mpath, broot_, index, registry=registry, dry=dry)
        )
    return total
