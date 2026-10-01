"""validbench — B6 validator-coverage spec (docs/spec/benchmark.md §B6).

Measures ``texlate.validate``'s detection of corrupted LLM translations:
the validator itself is benchmarked against constructed corruptions.

Cells (two disjoint item families pinned by ``item["stage"]``):

- ``vb_run`` — one cell per lake catalog idc: ``ctx.src_path()`` → root
  pick → subprocess parse (30s isolation — SIGALRM is banned in worker
  threads and kernel's process executor is unpicklable, G8) → chunk
  window [min_len,max_len] → per (chunk, level∈{ph,raw}) clean + c01–c10
  corruption cases → per-case rules ``validate_pair`` (+cst TsValidator when
  node/tree-sitter present) → compact verdict rows via ctx.emit_case.
- ``vb_probes`` — single synthetic cell (``__probes__``): the 14
  adversarial PROBES assertions vs validate_pair.

Epoch / re-measurement: cross-run dedup is forever — a DONE cell key
never re-measures. ``EPOCH`` rides every variant (``run@<EPOCH>`` /
``p@<EPOCH>``); bump it to open a new measurement generation. Content
knobs (max_per_paper/min_len/max_len/gen_seed/no_cst) are fp=True params —
they mark same-key cells stale on change but cannot themselves trigger
re-measurement (items() is zero-arg; variant is fixed at enumeration).

Determinism contract: chunk pick uses a per-paper seed
``Random(f"{gen_seed}:{pid}")`` — cell results are stable under subset
runs, a DELIBERATE DELTA from the old driver whose global-rng shuffle
made a paper's picked chunks depend on the other papers in the run.
Per-case corruption rng is ``crc32(cid+kind)`` exactly as before, so the
same (chunk,level,kind) produces the same corruption under any layout.

Aggregation/gates do NOT live here (analysis verbs) — the cell emits every
field needed to rebuild by_kind_level + clean-FP + the four gates:
n_cases, per (kind,level) n/detected/missed ids, clean error_fp ids,
rules_wall_s, cst coverage. error(retriable) cells are UNEVALUATED — any
downstream gate must count them as undetected (fail-closed), never drop
them from the denominator.

Full src/zh case text is written to ``rundir.derived()/validbench-cases/
{safe}.jsonl`` (replay substrate — the old --replay lane's corpus).

拆分：实现体按职域拆进同包私有叶 —— ``validbench.pseudo`` (VOCAB 词表 +
构造性伪译文/rehydrate), ``validbench.corrupt`` (c01–c10 破坏算子 +
CORRUPTIONS), ``validbench.cases`` (root pick + 30s 子进程解析 +
_gen_paper_cases), ``validbench.judge`` (_rules_one + cst 常驻 daemon 三件套),
``validbench.probes`` (PROBES + _probe_eval), ``validbench.main``
(items/select/_vb_run/_vb_probes/spec 装配)。本文件是 PEP 562 惰性门面
(同 ``kernel.vault``/``kernel.importer`` 形制) —— 平名经 ``_LEAF_EXPORTS``
映射回叶子，``__getattr__`` 首访解析并缓存，``getattr(module, "spec")`` 与
``from specs.validbench import X`` 读面与拆分前逐名等价; HEAD 期模块属性
面 (stdlib 模块名/kernel/texlate 顶层绑定) 同样惰性解析。叶子间互引走全
路径直跨 (``specs.validbench.<叶>``), 不经本门面。spec 文件经 load_spec
exec (非包内导入，``__package__`` 为空) —— 叶名一律写死 ``specs.`` 前缀，
不靠 ``__package__``。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

from specs import _bootstrap

_bootstrap.ensure()

if TYPE_CHECKING:
    # __all__ 名单静态落地——F822 要名可解，F401 以 __all__ re-export 豁免;
    # 私有惰性名不在此列 (不在 __all__, 无 F822 需，导入反吃 F401)。
    import bisect
    import json
    import random
    import re
    import subprocess
    import threading
    import time
    import zlib
    from collections import Counter
    from pathlib import Path
    from types import SimpleNamespace

    from kernel import fsutil, lake
    from kernel.spec import Param, Spec, Stage

    from specs.validbench.cases import PARSE_TIMEOUT_S
    from specs.validbench.corrupt import (
        CORRUPTIONS,
        c01_drop_rbrace,
        c02_drop_dollar,
        c03_rename_end,
        c04_drop_end,
        c05_drop_ph,
        c06_typo_ph,
        c07_unpair_lbrack,
        c08_halluc_macro,
        c09_drop_key,
        c10_extra_ph,
    )
    from specs.validbench.judge import BENCH_TS_NM, REPO
    from specs.validbench.main import EPOCH, MAX_LEN, MIN_LEN, SEED, spec
    from specs.validbench.probes import PROBES
    from specs.validbench.pseudo import (
        KEEP_ARG_RX,
        MATH_ENV_NAMES,
        VOCAB,
        pseudo_translate,
        rehydrate,
    )
    from texlate.validate import rules
    from texlate.validate.rules import Severity, validate_pair

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "cases": (
        "PARSE_TIMEOUT_S",
        "_CHILD_SRC",
        "_ParseFail",
        "_gen_paper_cases",
        "_parse_subprocess",
        "_pick_root",
    ),
    "corrupt": (
        "CORRUPTIONS",
        "_END_RX",
        "_comment_spans",
        "_in_comment",
        "_live_insert_positions",
        "_pick_uncommented",
        "_unescaped_positions",
        "c01_drop_rbrace",
        "c02_drop_dollar",
        "c03_rename_end",
        "c04_drop_end",
        "c05_drop_ph",
        "c06_typo_ph",
        "c07_unpair_lbrack",
        "c08_halluc_macro",
        "c09_drop_key",
        "c10_extra_ph",
    ),
    "judge": (
        "BENCH_TS_NM",
        "REPO",
        "_CST_LOCAL",
        "_expect_names",
        "_rules_one",
        "_cst_daemon",
        "_cst_here",
        "_cst_one",
    ),
    "main": (
        "EPOCH",
        "MAX_LEN",
        "MIN_LEN",
        "SEED",
        "_ITEMS_POOL",
        "_items",
        "_items_full",
        "_n_run",
        "_select",
        "_vb_probes",
        "_vb_run",
        "spec",
    ),
    "probes": (
        "PROBES",
        "_probe_eval",
    ),
    "pseudo": (
        "KEEP_ARG_RX",
        "MATH_ENV_NAMES",
        "VOCAB",
        "_cjk_for",
        "_find_env_end",
        "pseudo_translate",
        "rehydrate",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# HEAD 单件期模块属性面——stdlib 模块名与 kernel/texlate 顶层绑定也按名
# 惰性解析，``validbench.rules``/``validbench.fsutil`` 等读面 (含 setattr 型
# monkeypatch 缝，patch 落在共享 module 对象上) 与拆分前逐名等价。
_STDLIB_MODS = (
    "bisect",
    "json",
    "random",
    "re",
    "subprocess",
    "sys",
    "threading",
    "time",
    "zlib",
)
_MODULE_ATTRS = {
    "_bootstrap": "specs._bootstrap",
    "_sel": "specs._select",
    "fsutil": "kernel.fsutil",
    "rules": "texlate.validate.rules",
    "lake": "kernel.lake",
}
_EXTRA_BINDINGS = {
    "Counter": "collections",
    "Param": "kernel.spec",
    "Path": "pathlib",
    "Severity": "texlate.validate.rules",
    "SimpleNamespace": "types",
    "Spec": "kernel.spec",
    "Stage": "kernel.spec",
    "validate_pair": "texlate.validate.rules",
}

# 字面列表——拆分前 ``import *`` 面 (无 __all__ 期全量非下划线名) 逐名保留;
# 私有名经 _LAZY/_MODULE_ATTRS 进属性读面不进 __all__。ruff F401 re-export
# 判定要静态 __all__; ``_export_drift`` 是三表同步闸。
__all__ = [
    "BENCH_TS_NM",
    "CORRUPTIONS",
    "EPOCH",
    "KEEP_ARG_RX",
    "MATH_ENV_NAMES",
    "MAX_LEN",
    "MIN_LEN",
    "PARSE_TIMEOUT_S",
    "PROBES",
    "REPO",
    "SEED",
    "VOCAB",
    "Counter",
    "Param",
    "Path",
    "Severity",
    "SimpleNamespace",
    "Spec",
    "Stage",
    "bisect",
    "c01_drop_rbrace",
    "c02_drop_dollar",
    "c03_rename_end",
    "c04_drop_end",
    "c05_drop_ph",
    "c06_typo_ph",
    "c07_unpair_lbrack",
    "c08_halluc_macro",
    "c09_drop_key",
    "c10_extra_ph",
    "fsutil",
    "json",
    "lake",
    "pseudo_translate",
    "random",
    "re",
    "rehydrate",
    "rules",
    "spec",
    "subprocess",
    "sys",
    "threading",
    "time",
    "validate_pair",
    "zlib",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性 / stdlib 绑定 / kernel·texlate 顶层名。

    spec 文件经 ``load_spec`` 以 ``spec_from_file_location`` exec——此时
    ``__package__`` 为空串，叶名必须写死 ``specs.`` 前缀 (正常
    ``import specs.validbench`` 径下等价)。
    """
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"specs.validbench.{leaf}"), name)
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
    mod_path = _MODULE_ATTRS.get(name)
    if mod_path is not None:
        value = importlib.import_module(mod_path)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return sorted(
        set(globals())
        | set(__all__)
        | set(_LAZY)
        | set(_STDLIB_MODS)
        | set(_MODULE_ATTRS)
        | set(_EXTRA_BINDINGS)
    )


def _export_drift() -> list[str]:
    """``_LAZY``/``__all__``/叶子实体三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。逐名 ``getattr`` 实解：叶子断链
    (``_LEAF_EXPORTS`` 配名叶子不提供) 与幽灵条 (解析不到任何叶子或绑
    定) 在此曝，是首访 ``AttributeError`` 唯一的提前闸。审计实载全部
    叶子，只供测试调用，装载期不自检。

    注意：本模块经 load_spec exec 装载后被弹出 ``sys.modules``, 审计只在
    正常 ``import specs.validbench`` 的常驻对象上有效。
    """
    mod = sys.modules[__name__]
    drift = []
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    drift += [
        f"leaf stem {stem!r} shadows an exported name (rename the leaf)"
        for stem in _LEAF_EXPORTS
        if stem in _LAZY
    ]
    for name in _LAZY:
        try:
            getattr(mod, name)
        except Exception as exc:
            drift.append(f"_LEAF_EXPORTS entry {name} does not resolve: {exc}")
    for name in __all__:
        if name in _LAZY:
            continue  # 已解
        try:
            getattr(mod, name)
        except Exception as exc:
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and name not in _STDLIB_MODS
        and name not in _MODULE_ATTRS
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
