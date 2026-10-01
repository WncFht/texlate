"""kernel — the 8-step run pipeline + the cell critical section (§2.1).

    run(spec_or_path, params=None, *, date=None, slug=None, resume=False,
        replan=False, max_cost=None, regen=False, sel=None, yes=False,
        allow_regen=False, gateway_factory=None, jobs=4, emit=print)
        -> dict
    plan(spec_or_path, params=None, **kw) -> dict        # dry-run quote

Pipeline (design §2.1):

    1. spec load + compile_checks + param coercion (stringly params die
       here — unknown/uncoercible params are refused before side effects)
    2. item enumeration + canon resolution (registry-gated unless
       spec.eval; ambig/invalid ids drop with a note, never silently)
    3. run materialization — create_run (auto-slug) or load_run (resume);
       spec.json/spec_env/invocations frozen beside the events shard
    4. frozen plan — freeze_plan writes {cells} once; resume reads it
       verbatim unless --replan
    5. seq allocator (per-run monotonic mint seeded above existing shard
       seqs) + Index + tail_ingest + DedupOracle snapshot
    6. cell_queued batch — one emit_batch for every plan cell lacking a
       terminal in THIS run (accounting's queued set, §3.1)
    7. executor pass — cells grouped by stage executor, same-idc serial
    8. reconcile — this run's pending vault metas promoted by cell
       verdicts; accounting_check; finished event; report dict

Cell critical section (§2.1, §3.6, §3.10.6), inside cell_lock:

    this-run terminal recheck -> cross-run done -> paid oracle
    (unsealed->error/index_unsealed | claimed->claimed | verified->dedup
     | missing->regen gate | absent->proceed) -> meter pre-check ->
    needs eval (no domain DONE row -> skip; done but product lost ->
    fault/upstream-lost) -> PAUSE (paid cells only) -> AUTH_DEAD ->
    claim NB-acquire ->
    claim acquire event + cell_started -> fn(ctx) -> status_class
    classify (unclassified -> fault + note) -> last-mutating harvest
    BEFORE terminal emit (§3.5) -> ONE emit_batch {terminal + outbox +
    claim-release fate} -> lease.release()

Lock order honored: run.lock -> cell.lock -> claim.lock -> leaf {slot,
ledger, index, vault}. Everything under cell.lock that isn't a leaf is
NB-only.

拆分：实现体按子域下沉同包私有叶 —— ``kernel.frame`` (规划面：spec
解析/参数规整/item 枚举/canon 闸/选择子)、``kernel.needs`` (needs 域
求值)、``kernel.emit`` (outbox 折叠/终态戳/note/emit 批量写)、
``kernel.lookahead`` (lake 预取窗口 + _Lookahead 守护线程)、
``kernel.cell`` (cell 临界段 _run_cell/§3.5 收割/线程本 Index)、
``kernel._run`` (run/plan 编排 + RunError + 首火闸 + _RunEnv + 收尾
对账)。本文件是 PEP 562 惰性门面 (同 ``importer``/vault 门面形制) ——
平名经 ``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``kernel.kernel.run`` / ``from kernel.kernel import _run_cell`` 等公私
名面不变。``sys.modules["kernel.kernel"]`` fake 缝 (test_kernel_cli)
落在模块位，不受影响。
monkeypatch 锚点注意：测试 setattr patch 须指到叶子模块 (如
``kernel.kernel.lookahead.LOOKAHEAD_CELLS``); setattr 门面只遮蔽
门面自身命名空间，叶子代码仍读叶内绑定。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kernel.kernel._run import (
        _VERIFY_FRESH_S,
        RunError,
        _first_fire_gate,
        _max_shard_seq,
        _reconcile_pending,
        _RunEnv,
        _SeqAlloc,
        _shard_terminal_keys,
        _tally,
        _verdict_for,
        _wrap_factory,
        plan,
        run,
    )
    from kernel.kernel.cell import (
        _harvest_last_mutating,
        _run_cell,
        _thread_index,
    )
    from kernel.kernel.emit import (
        _CELL_MERGE_KEYS,
        _CELL_RESERVED,
        _emit,
        _emit_batch,
        _merge_outbox,
        _note,
        _synth_sig,
        _terminal_ev,
    )
    from kernel.kernel.frame import (
        _coerce_params,
        _enumerate_cells,
        _resolve_spec,
        _sel_hit,
        _spec_env,
    )
    from kernel.kernel.lookahead import (
        LOOKAHEAD_BYTES,
        LOOKAHEAD_CELLS,
        _Lookahead,
    )
    from kernel.kernel.needs import (
        _dir_has_files,
        _last_outcome,
        _last_rec,
        _needs_eval,
        _product_ok,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "frame": (
        "_coerce_params",
        "_enumerate_cells",
        "_resolve_spec",
        "_sel_hit",
        "_spec_env",
    ),
    "needs": (
        "_dir_has_files",
        "_last_outcome",
        "_last_rec",
        "_needs_eval",
        "_product_ok",
    ),
    "emit": (
        "_CELL_MERGE_KEYS",
        "_CELL_RESERVED",
        "_emit",
        "_emit_batch",
        "_merge_outbox",
        "_note",
        "_synth_sig",
        "_terminal_ev",
    ),
    "lookahead": (
        "LOOKAHEAD_BYTES",
        "LOOKAHEAD_CELLS",
        "_Lookahead",
    ),
    "cell": (
        "_harvest_last_mutating",
        "_run_cell",
        "_thread_index",
    ),
    "_run": (
        "_VERIFY_FRESH_S",
        "RunError",
        "_RunEnv",
        "_SeqAlloc",
        "_first_fire_gate",
        "_max_shard_seq",
        "_reconcile_pending",
        "_shard_terminal_keys",
        "_tally",
        "_verdict_for",
        "_wrap_factory",
        "plan",
        "run",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集，
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "LOOKAHEAD_BYTES",
    "LOOKAHEAD_CELLS",
    "_CELL_MERGE_KEYS",
    "_CELL_RESERVED",
    "_VERIFY_FRESH_S",
    "RunError",
    "_Lookahead",
    "_RunEnv",
    "_SeqAlloc",
    "_coerce_params",
    "_dir_has_files",
    "_emit",
    "_emit_batch",
    "_enumerate_cells",
    "_first_fire_gate",
    "_harvest_last_mutating",
    "_last_outcome",
    "_last_rec",
    "_max_shard_seq",
    "_merge_outbox",
    "_needs_eval",
    "_note",
    "_product_ok",
    "_reconcile_pending",
    "_resolve_spec",
    "_run_cell",
    "_sel_hit",
    "_shard_terminal_keys",
    "_spec_env",
    "_synth_sig",
    "_tally",
    "_terminal_ev",
    "_thread_index",
    "_verdict_for",
    "_wrap_factory",
    "plan",
    "run",
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
