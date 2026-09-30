"""vault — the paid-bytes zone (design §3.5, §3.10.4, §3.10.6; risks R4/R5).

Layout (paths.py owns the roots; this module owns everything beneath them)::

    vault/
    ├── .vault-sentinel            # mount proof — writes refuse when missing
    ├── .lock                      # the single global vault write lock (immortal)
    ├── .staging/{tag}/{kind}/     # harvest staging — same volume as vault
    ├── {zh,splice,state}/{safe_id}/{arm}[@{variant}][.{altseq}]/
    │                              # pending/primary/alt copies (zone = metadata)
    ├── quar/{kind}/{safe_id}/{arm}[@{variant}][.{altseq}]/
    │                              # quarantine keeps a physical separate root
    │                              # (§3.10.4 "仅 quar 保留物理分根", mirroring the
    │                              #  kind-first shape: vault/quar/<kind>/...)
    ├── meta/{esc(sid)}.{esc(arm)}[@{esc(variant)}][.{altseq}].json
    │                              # per-copy commit marker — written LAST
    └── manifest.jsonl             # append-only credential ledger rows (in-lock)

Two-phase commit order (§3.5 — the direction is nailed down):

    work bytes -> hardlink into .staging/{tag}/{kind}/ (os.link zero-copy;
    EXDEV -> copyfile) -> .files.jsonl manifest -> chmod -R a-w (fuse) ->
    fsync -> rename() each kind dir into place (same volume, atomic per dir)
    -> meta/*.json written LAST via atomic_write (the commit marker) ->
    manifest.jsonl appended -> lock released -> asset events emitted.

A kill between rename and meta leaves "bytes visible, no meta": directory
existence NEVER counts — the dedup criterion (``bytes_ok``) requires a
parseable meta AND every declared asset present non-empty on disk, so
uncommitted bytes can never satisfy dedup (R4). A catchable failure after
renames (e.g. meta write error) unfuses and deletes the dirs it just moved —
the kernel only ever deletes files it created itself.

Link + fuse semantics: staged files share the *source work tree's* inode,
so ``chmod -R a-w`` makes the work-side file read-only too. That is the
intended fuse direction (harvest fires after the last mutating stage —
the work copy IS the vault copy, immutable everywhere). Consumers that
must write get ``restore(mode='copy')``; ``mode='link'`` hands back the
shared 0444 inode — mutating it fails EACCES loudly, which the design
prefers over a silently poisoned vault (§3.10.4).

Credential = (idc, arm, variant, altseq, zone) — five dimensions, one meta
file per physical copy. ``.{altseq}`` disambiguates multiple copies of one
(idc,arm,variant) in the same namespace; meta filenames and leaf dir names
escape every component via idnorm (injective round-trip: '.'->%2E,
'@'->%40, '%'->%25 first; altseq is charset-restricted, never escaped).
Parse eats the .json suffix then the .altseq suffix, then splits.

Verdicts (§3.8): ``bytes_ok`` is the PHYSICAL criterion — meta parseable
and declared bytes intact (pending included: the bytes are really there).
``dedup_hit`` is the policy criterion — intact AND verdict in
{primary,alt,quar,adopted,verified}; pending/tombstone excluded. The paid
gate composes them with the in-lock claim recheck upstream.

Locks: every vault write serializes through ``vault/.lock`` — EX for
harvest/promote/adopt/tombstone/heal, SH for verify/find_meta_less_dirs/
restore. Meta reads are lock-free (atomic_write means readers only ever
see complete files). Ledger events are emitted AFTER the lock is dropped
so the vault critical section never blocks on the ledger's own lock.

拆分：实现体按子域拆进同包私有叶 —— ``_vault_cred`` (凭证代数：词汇常量/
四异常/五维命名与径定位), ``_vault_io`` (sentinel/fsync/fuse/文件迭代/
meta+manifest 读写), ``_vault_intact`` (完好与产物在场判定+pdf 封口闸),
``_vault_commit`` (harvest 两相提交+adopt 孤儿收编), ``_vault_query``
(dedup 判词与副本列举), ``_vault_verbs`` (promote/tombstone 簿记动词),
``_vault_verify`` (三档校验+heal 自愈), ``_vault_retention`` (CAS 投影/
slim_splice/孤儿扫描), ``_vault_restore`` (最优副本选取+work 物化),
``_vault_rekey`` (variant 跨纪元采用); 本文件是 PEP 562 惰性门面
(同 ``kernel.importer``/``fixloop/builtins`` 形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``vault.X`` 公共面/私有读面与 ``from kernel import vault`` 用法不变;
kernel 子模块名 (``vault.fsutil`` 等) 与 stdlib 名同样惰性解析，故
``monkeypatch.setattr(vault.fsutil, ...)`` 一类跨模块 patch 缝照旧生效。
叶子间互引走全路径直跨 (``kernel._vault_*``), 不经本门面。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # __all__ 名单静态落地——F822 要名可解，F401 以 __all__ re-export 豁免;
    # 私有惰性名不在此列 (不在 __all__, 无 F822 需，导入反吃 F401)。
    from kernel._vault_commit import adopt, harvest
    from kernel._vault_cred import (
        DEDUP_VERDICTS,
        KINDS,
        VERDICTS,
        ZONES,
        AmbiguousDonor,
        DestOccupied,
        MetaMissing,
        VaultError,
        dir_key,
        leaf_dir,
        meta_key,
        meta_path,
        parse_dir_key,
        parse_meta_key,
    )
    from kernel._vault_io import manifest_rows
    from kernel._vault_query import bytes_ok, dedup_hit, pending_metas, query
    from kernel._vault_restore import restore
    from kernel._vault_retention import (
        CAS_LINK_FLOOR,
        cas_link_leaves,
        cas_link_tree,
        find_meta_less_dirs,
        slim_splice,
    )
    from kernel._vault_verbs import promote, tombstone
    from kernel._vault_verify import heal, verify

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_vault_commit": (
        "_FILES_MANIFEST",
        "_choose_altseq",
        "_group_files",
        "_slot_taken",
        "adopt",
        "harvest",
    ),
    "_vault_cred": (
        "_ALTSEQ_RE",
        "_META_SUFFIX",
        "_ZONE_ALIASES",
        "_ZONE_RANK",
        "_ZONE_TAG",
        "DEDUP_VERDICTS",
        "KINDS",
        "VERDICTS",
        "ZONES",
        "AmbiguousDonor",
        "DestOccupied",
        "MetaMissing",
        "VaultError",
        "_check_altseq",
        "_check_idc",
        "_comp",
        "_kind_root",
        "_norm_verdict",
        "_norm_zone",
        "_rel_leaf",
        "_work_dirname",
        "_zone_tag",
        "dir_key",
        "leaf_dir",
        "meta_key",
        "meta_path",
        "parse_dir_key",
        "parse_meta_key",
    ),
    "_vault_intact": (
        "_FIGISH_STEM_RE",
        "_PRODUCT_KINDS",
        "_copy_file_rels",
        "_copy_intact",
        "_copy_product_bad",
        "_copy_product_ok",
        "_corrupt_product_pdfs",
        "_kind_intact",
        "_pdf_intact",
        "_product_pdf_rels",
        "_safe_rel",
    ),
    "_vault_io": (
        "_append_manifest_locked",
        "_chmod_readonly_tree",
        "_fsync_ancestors",
        "_fsync_file",
        "_fsync_tree",
        "_iter_files",
        "_iter_metas",
        "_iter_metas_for",
        "_non_regular",
        "_read_meta",
        "_require_sentinel",
        "_unfuse_dirs",
        "_write_meta",
        "manifest_rows",
    ),
    "_vault_query": (
        "bytes_ok",
        "dedup_hit",
        "pending_metas",
        "query",
    ),
    "_vault_rekey": (
        "_REKEY_ZONES",
        "REKEY_KINDS",
        "rekey",
    ),
    "_vault_restore": (
        "_select_copy",
        "restore",
    ),
    "_vault_retention": (
        "CAS_LINK_FLOOR",
        "_iter_committed_leaves",
        "_scan_meta_less_dirs",
        "_splice_keep",
        "cas_link_leaves",
        "cas_link_tree",
        "find_meta_less_dirs",
        "slim_splice",
    ),
    "_vault_verbs": (
        "promote",
        "tombstone",
    ),
    "_vault_verify": (
        "_HEAL_TMP_SUFFIX",
        "_donor_map",
        "_lift_fuse",
        "_verify_scan",
        "heal",
        "verify",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# HEAD 单件期模块属性面——kernel 依赖子模块与 stdlib 名也按名惰性解析，
# ``vault.fsutil``/``vault.paths``/``vault.os`` 等读面 (含 setattr 型
# monkeypatch 缝，patch 落在共享 module 对象上) 与拆分前逐名等价。
_KERNEL_MODS = ("cas", "events", "fsutil", "idnorm", "ledger", "locks", "paths")
_STDLIB_MODS = (
    "glob",
    "hashlib",
    "json",
    "os",
    "random",
    "re",
    "shutil",
    "stat",
    "tempfile",
    "time",
)
_EXTRA_BINDINGS = {"Path": "pathlib", "suppress": "contextlib"}

# 字面列表——拆分前 __all__ 逐名保留 (公共导出面一字不动); 私有名经
# _LAZY 进属性读面不进 __all__ (``from kernel.vault import *`` 语义不变)。
# ruff F401 re-export 判定要静态 __all__; ``_export_drift`` 是三表同步闸。
__all__ = [
    "CAS_LINK_FLOOR",
    "DEDUP_VERDICTS",
    "KINDS",
    "VERDICTS",
    "ZONES",
    "AmbiguousDonor",
    "DestOccupied",
    "MetaMissing",
    "VaultError",
    "adopt",
    "bytes_ok",
    "cas_link_leaves",
    "cas_link_tree",
    "dedup_hit",
    "dir_key",
    "find_meta_less_dirs",
    "harvest",
    "heal",
    "leaf_dir",
    "manifest_rows",
    "meta_key",
    "meta_path",
    "parse_dir_key",
    "parse_meta_key",
    "pending_metas",
    "promote",
    "query",
    "restore",
    "slim_splice",
    "tombstone",
    "verify",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性 / kernel 子模块 / stdlib 绑定。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"{__package__}.{leaf}"), name)
        globals()[name] = value
        return value
    if name in _KERNEL_MODS:
        value = importlib.import_module(f"{__package__}.{name}")
        globals()[name] = value
        return value
    if name in _STDLIB_MODS:
        value = importlib.import_module(name)
        globals()[name] = value
        return value
    extra = _EXTRA_BINDINGS.get(name)
    if extra is not None:
        value = getattr(importlib.import_module(extra), name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return sorted(
        set(vars())
        | set(__all__)
        | set(_LAZY)
        | set(_KERNEL_MODS)
        | set(_STDLIB_MODS)
        | set(_EXTRA_BINDINGS)
    )


def _export_drift() -> list[str]:
    """``_LAZY``/``__all__``/叶子实体三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。逐名 ``getattr`` 实解：叶子断链
    (``_LEAF_EXPORTS`` 配名叶子不提供) 与幽灵条 (解析不到任何叶子或绑
    定) 在此曝，是首访 ``AttributeError`` 唯一的提前闸。审计实载全部
    叶子，只供测试调用，装载期不自检。
    """
    mod = sys.modules[__name__]
    drift = []
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    for name in _LAZY:
        try:
            getattr(mod, name)
        except Exception as exc:
            drift.append(f"_LEAF_EXPORTS entry {name} does not resolve: {exc}")
    for name in __all__:
        if name in _LAZY:
            continue  # 已解
            # 门面本地公共名 (组合根式实现驻留本文件时豁免 _LAZY)
        try:
            getattr(mod, name)
        except Exception as exc:
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and name not in _KERNEL_MODS
        and name not in _STDLIB_MODS
        and name not in _EXTRA_BINDINGS
        and callable(v)
        and getattr(v, "__module__", None) == __name__
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
