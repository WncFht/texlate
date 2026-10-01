"""bench — the single CLI entry point for the trizone-ledger kernel (§2.1).

Every bench verb is a subcommand of one argparse program::

    bench init | run | plan | status | vault | ledger | lake
    bench derive | sweep | prune | backup | doctor | fsck | spec
    bench triage | gate | dossier          (analysis verbs — §5.2 queue)

Contract baked here:

- Write commands run a light sweep first (§2.4 — the reaper has an owner).
  The sweep module is imported lazily; while it cannot be imported the
  hook is a loud no-op, never a silent skip.
- ``run`` refuses while $ROOT/PAUSE exists only for PAID specs
  (locks.pause_engaged + spec.has_paid — Phase 3 rescope: the fence stops
  spend, not free work; ``plan`` always runs).
- ``--detach`` re-execs through locks.detach_with_lock (R22: the child
  holds the lock itself); a paid spec additionally requires --max-cost
  (§3.6 — detach forces the budget flag).
- kernel.kernel (run/plan), kernel.spec, kernel.sweep, kernel.doctor are
  sibling modules imported lazily — the CLI works for every verb
  that only needs foundation/zone modules, and reports a clean
  "not yet available" (exit 2) for the rest instead of crashing.

Exit codes: 0 ok · 1 command ran but reported failure · 2 refused /
unavailable / not yet implemented.

拆分：实现体按子域下沉同包私有叶 —— ``cli.common`` (出口码/惰性装载/
规格面解析/写前轻扫/index 与 registry 开闸/run-dir 归一/尺寸解析)、
``cli.runlike`` (init/run/plan + detach 再执行 + quote 打印)、
``cli.status`` (index 读面)、``cli.vault`` (vault 八动词)、
``cli.ledger`` (import/ingest/rebuild-index/tail-ingest)、
``cli.lake`` (status/pin/unpin/evict/evict-done/register/absorb +
双代 evict-done 裁决)、``cli.cache`` (status/evict/rebuild)、
``cli.ops`` (derive/sweep/prune/backup + 剪枝 keep-list 机件)、
``cli.doctor`` (doctor/fsck 体检)、``cli.spec`` (spec list 创作辅助)、
``cli.verbs`` (verbs.REGISTRY 自注册 + 未实现闸)、
``cli.parser`` (argparse 树)、``cli._main`` (_DISPATCH + main)。
本文件是 PEP 562 惰性门面 (同 ``importer``/``kernel.kernel`` 门面
形制) —— 平名经 ``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访
解析并缓存，``cli.main`` / ``from kernel.cli import _open_index`` 等
公私名面不变 (verbs/rundiff/triage 读 ``cli._open_index`` 等，
test_verbs setattr 锚 ``kernel.cli._open_index`` 亦不变)。
monkeypatch 锚点注意：测试 setattr patch 到门面名上只对「经
``cli.X`` 属性读的消费方」生效 (setattr 写真全局遮蔽 ``__getattr__``);
叶内互调绑定的 patch 须指到叶子模块 (如
``kernel.cli.verbs._verb_registry``)。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kernel.cli._main import _DISPATCH, main
    from kernel.cli.cache import (
        _cmd_cache_evict,
        _cmd_cache_rebuild,
        _cmd_cache_status,
    )
    from kernel.cli.common import (
        EXIT_FAIL,
        EXIT_OK,
        EXIT_REFUSED,
        _collect_params,
        _err,
        _lazy,
        _load_registry,
        _open_index,
        _parse_size,
        _pause_refused,
        _pre_write,
        _print_json,
        _resolve_spec,
        _run_dir_of,
        _rundir_of,
        _shim_path,
        _spec_paidness,
        _specs_dir,
        _try_sweep,
    )
    from kernel.cli.doctor import _cmd_doctor, _cmd_fsck, _print_checks
    from kernel.cli.lake import (
        _PIPELINE_STAGES,
        _cmd_lake_absorb,
        _cmd_lake_evict,
        _cmd_lake_evict_done,
        _cmd_lake_pin,
        _cmd_lake_register,
        _cmd_lake_status,
        _cmd_lake_unpin,
        _evict_done_targets,
    )
    from kernel.cli.ledger import (
        _cmd_ledger_import,
        _cmd_ledger_ingest,
        _cmd_ledger_rebuild,
        _cmd_ledger_tail,
    )
    from kernel.cli.ops import (
        _CHECKPOINT_DIRS,
        _PAID_TREE_PREFIXES,
        _PRUNE_ALWAYS,
        _PRUNE_KEEP,
        _cell_has_paid_bytes,
        _cell_shrinkable,
        _cmd_backup,
        _cmd_derive,
        _cmd_prune,
        _cmd_sweep,
    )
    from kernel.cli.parser import _add_runlike_flags, _build_parser
    from kernel.cli.runlike import (
        _cmd_init,
        _cmd_plan,
        _cmd_run,
        _detach_run,
        _kernel_run_path,
        _print_quote,
        _run_kwargs,
    )
    from kernel.cli.spec import _cmd_spec_list, _spec_doc, _spec_kind
    from kernel.cli.status import _cmd_status, _event_line
    from kernel.cli.vault import (
        _cmd_vault_adopt,
        _cmd_vault_cas_link,
        _cmd_vault_rekey,
        _cmd_vault_restore,
        _cmd_vault_seed,
        _cmd_vault_slim,
        _cmd_vault_tombstone,
        _cmd_vault_verify,
    )
    from kernel.cli.verbs import (
        _NOT_IMPLEMENTED,
        _cmd_not_implemented,
        _cmd_verb,
        _lazy_verb,
        _verb_registry,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "common": (
        "EXIT_FAIL",
        "EXIT_OK",
        "EXIT_REFUSED",
        "_collect_params",
        "_err",
        "_lazy",
        "_load_registry",
        "_open_index",
        "_parse_size",
        "_pause_refused",
        "_pre_write",
        "_print_json",
        "_resolve_spec",
        "_run_dir_of",
        "_rundir_of",
        "_shim_path",
        "_spec_paidness",
        "_specs_dir",
        "_try_sweep",
    ),
    "runlike": (
        "_cmd_init",
        "_cmd_plan",
        "_cmd_run",
        "_detach_run",
        "_kernel_run_path",
        "_print_quote",
        "_run_kwargs",
    ),
    "status": (
        "_cmd_status",
        "_event_line",
    ),
    "vault": (
        "_cmd_vault_adopt",
        "_cmd_vault_cas_link",
        "_cmd_vault_rekey",
        "_cmd_vault_restore",
        "_cmd_vault_seed",
        "_cmd_vault_slim",
        "_cmd_vault_tombstone",
        "_cmd_vault_verify",
    ),
    "ledger": (
        "_cmd_ledger_import",
        "_cmd_ledger_ingest",
        "_cmd_ledger_rebuild",
        "_cmd_ledger_tail",
    ),
    "lake": (
        "_PIPELINE_STAGES",
        "_cmd_lake_absorb",
        "_cmd_lake_evict",
        "_cmd_lake_evict_done",
        "_cmd_lake_pin",
        "_cmd_lake_register",
        "_cmd_lake_status",
        "_cmd_lake_unpin",
        "_evict_done_targets",
    ),
    "cache": (
        "_cmd_cache_evict",
        "_cmd_cache_rebuild",
        "_cmd_cache_status",
    ),
    "ops": (
        "_CHECKPOINT_DIRS",
        "_PAID_TREE_PREFIXES",
        "_PRUNE_ALWAYS",
        "_PRUNE_KEEP",
        "_cell_has_paid_bytes",
        "_cell_shrinkable",
        "_cmd_backup",
        "_cmd_derive",
        "_cmd_prune",
        "_cmd_sweep",
    ),
    "doctor": (
        "_cmd_doctor",
        "_cmd_fsck",
        "_print_checks",
    ),
    "spec": (
        "_cmd_spec_list",
        "_spec_doc",
        "_spec_kind",
    ),
    "verbs": (
        "_NOT_IMPLEMENTED",
        "_cmd_not_implemented",
        "_cmd_verb",
        "_lazy_verb",
        "_verb_registry",
    ),
    "parser": (
        "_add_runlike_flags",
        "_build_parser",
    ),
    "_main": (
        "_DISPATCH",
        "main",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集，
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "EXIT_FAIL",
    "EXIT_OK",
    "EXIT_REFUSED",
    "_CHECKPOINT_DIRS",
    "_DISPATCH",
    "_NOT_IMPLEMENTED",
    "_PAID_TREE_PREFIXES",
    "_PIPELINE_STAGES",
    "_PRUNE_ALWAYS",
    "_PRUNE_KEEP",
    "_add_runlike_flags",
    "_build_parser",
    "_cell_has_paid_bytes",
    "_cell_shrinkable",
    "_cmd_backup",
    "_cmd_cache_evict",
    "_cmd_cache_rebuild",
    "_cmd_cache_status",
    "_cmd_derive",
    "_cmd_doctor",
    "_cmd_fsck",
    "_cmd_init",
    "_cmd_lake_absorb",
    "_cmd_lake_evict",
    "_cmd_lake_evict_done",
    "_cmd_lake_pin",
    "_cmd_lake_register",
    "_cmd_lake_status",
    "_cmd_lake_unpin",
    "_cmd_ledger_import",
    "_cmd_ledger_ingest",
    "_cmd_ledger_rebuild",
    "_cmd_ledger_tail",
    "_cmd_not_implemented",
    "_cmd_plan",
    "_cmd_prune",
    "_cmd_run",
    "_cmd_spec_list",
    "_cmd_status",
    "_cmd_sweep",
    "_cmd_vault_adopt",
    "_cmd_vault_cas_link",
    "_cmd_vault_rekey",
    "_cmd_vault_restore",
    "_cmd_vault_seed",
    "_cmd_vault_slim",
    "_cmd_vault_tombstone",
    "_cmd_vault_verify",
    "_cmd_verb",
    "_collect_params",
    "_detach_run",
    "_err",
    "_event_line",
    "_evict_done_targets",
    "_kernel_run_path",
    "_lazy",
    "_lazy_verb",
    "_load_registry",
    "_open_index",
    "_parse_size",
    "_pause_refused",
    "_pre_write",
    "_print_checks",
    "_print_json",
    "_print_quote",
    "_resolve_spec",
    "_run_dir_of",
    "_run_kwargs",
    "_rundir_of",
    "_shim_path",
    "_spec_doc",
    "_spec_kind",
    "_spec_paidness",
    "_specs_dir",
    "_try_sweep",
    "_verb_registry",
    "main",
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
