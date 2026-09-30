"""corpus_layers — 扩库层构建器 spec（holdout / dev_vol / dev_failmine / dev_recent）。

build_corpus_layers.py 的 spec 重写（trizone-ledger v2，无旧兼容）：
items = 每层一 cell（id=层名，params.layer 注入）；bulk 链
plan→scan→extract→qc，recent 正交臂（needs=[]，ids_file 闸）声明在 qc 前，
使 qc 见到本 run eprint 实收。

    bench run bench/py/specs/corpus_layers.py
    bench run corpus_layers --param layers=holdout,dev_vol
    bench run corpus_layers --param ids_file='sw/assign_{layer}.jsonl'

层剖面（PROFILES verbatim）：

- ``holdout``      flat 2700（core cell 配比直扩，月份与 30 个 core 簇月
                   不相交 → 时间外推）+ ~300 eprint（acquire_source 全量
                   blob——holdout 必须带图不走 sw 脱水 → figures_stripped=false）。
- ``dev_vol``      fbias 2000（失败率偏置 λ=bias，expand 同 rates_source 解析）。
- ``dev_failmine`` flags 1500（deadpkg/pdftex_prim/babel_german/docstyle209/
                   minted/pstricks/epsfig 旗标配额稀有优先填充，短收 →
                   old-era 随机合格成员回填 'failmine_fill'）。
- ``dev_recent``   recent-only——bulk 链全 ok-noop，账本靠 recent 臂。

口径/资产变化（旧世界已灭处全部 fail-closed 或显式标注）：

- work_v3 已灭 → 工作区 ``~/.local/state/texlate/corpus-build/layers/{layer}/``
  （TarDirs 同构布局）；plan/select_stats/records/qc.md/recent_fail 落层目录。
- frame 资产（item-index/tiger-files/allocation-core/cluster-cat-mix +
  frame_lookup）由 frame_build(ord-0) 供——缺一件 bulk 链 plan=fail；
  recent 臂不需要 frame（cat_group 来自 assign 行）。
- n100 故障率文件已灭 → fbias 走 ``rates_source`` 三路（run ref / rates
  json / flat fallback），与 corpus_expand 同一解析码（verbatim 复制保持
  文件级解耦）；flat_fallback 时 ``rates_mode`` metric 显式标注。
- ``ids_file`` 支持 ``{layer}`` 占位；缺省自动解析
  ``{lake_durable}/sw/assign_{layer}.jsonl``（corpus_sw assign 臂产物），
  不存在 → eprint 层 recent=skip 等待，bulk-only 层 recent=ok noop。
- recent 臂预算：``recent_limit``=单轮尝试封顶（默认 85），``day_budget``
  走持久化 RateLimiter（``{lwd}/ratelimit.json``，默认 180/日）；截断 →
  ``{"status":"error","errors":[{cat:"budget"}]}`` retriable 续跑（corpus_hot
  同口径——DONE 态跨 run dedup 会把截尾误记完成，error 是唯一可续跑词）。

拆分（facade 化 god-split）：实现体按 stage 段拆进同包私有叶——
``_corpus_layers_base``（PROFILES/FLAG_QUOTAS 层定义词表 + _ts/_layer/
_dirs 路径解析）、``_corpus_layers_plan``（plan 段）、
``_corpus_layers_scan``（scan 段）、``_corpus_layers_extract``（池装载 +
配额/旗标选样 + extract 段）、``_corpus_layers_recent``（eprint 正交臂）、
``_corpus_layers_qc``（qc 段）、``_corpus_layers_spec``（_select + spec
组合根）。本文件是 PEP 562 惰性门面（同 ``specs/soak.py`` 形制）——平名
经 ``_LEAF_EXPORTS`` 映射回叶子，``corpus_layers.X`` 与
``from specs.corpus_layers import X`` 读面与拆分前逐名等价；``spec``
住 ``_corpus_layers_spec`` 叶（``load_spec`` 首访惰性解析）。叶间直引
``from specs._corpus_layers_X import Y`` 不绕本门面（避环）。spec 文件
经 load_spec exec（非包内导入，``__package__`` 为空）——叶名走
``_PKG = __package__ or "specs"`` 归一。
"""

from __future__ import annotations

import json
import math
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

from kernel import lake, paths
from kernel.spec import Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

import importlib
import sys
from typing import TYPE_CHECKING

from specs import _corpus_common as cc

if TYPE_CHECKING:
    # __all__ 名单静态落地——F822 要名可解, F401 以 __all__ re-export 豁免。
    from specs._corpus_layers_base import (
        _FAILMINE_FILL_CAP,
        _FLAG_BAND_FRAC,
        EPRINT_LAYERS,
        FLAG_QUOTAS,
        LAYER_NAMES,
        POOL_MARGIN,
        PROFILES,
        YIELD_PER_CHUNK,
        _dirs,
        _layer,
        _ts,
    )
    from specs._corpus_layers_extract import (
        _extract,
        _flag_hit,
        _frame_lut,
        _load_pool,
        _select_flags,
        _select_quota,
    )
    from specs._corpus_layers_plan import _plan, _scanned_items
    from specs._corpus_layers_qc import _qc
    from specs._corpus_layers_recent import (
        _eprint_fetch_fn,
        _load_recent_ids,
        _recent,
    )
    from specs._corpus_layers_scan import _scan
    from specs._corpus_layers_spec import _select, spec

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_corpus_layers_base": (
        "EPRINT_LAYERS",
        "FLAG_QUOTAS",
        "LAYER_NAMES",
        "POOL_MARGIN",
        "PROFILES",
        "YIELD_PER_CHUNK",
        "_dirs",
        "_FAILMINE_FILL_CAP",
        "_FLAG_BAND_FRAC",
        "_layer",
        "_ts",
    ),
    "_corpus_layers_extract": (
        "_extract",
        "_flag_hit",
        "_frame_lut",
        "_load_pool",
        "_select_flags",
        "_select_quota",
    ),
    "_corpus_layers_plan": (
        "_plan",
        "_scanned_items",
    ),
    "_corpus_layers_qc": ("_qc",),
    "_corpus_layers_recent": (
        "_eprint_fetch_fn",
        "_load_recent_ids",
        "_recent",
    ),
    "_corpus_layers_scan": ("_scan",),
    "_corpus_layers_spec": (
        "_select",
        "spec",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

_PKG = __package__ or "specs"  # load_spec exec 径下 __package__ 是 ""

# 字面列表——拆分前顶层名面 (import/常量/函数/spec 全量) 逐名保留；新增导出
# 两侧同步（``_export_drift`` 是三表同步闸）。
__all__ = [
    "EPRINT_LAYERS",
    "FLAG_QUOTAS",
    "LAYER_NAMES",
    "POOL_MARGIN",
    "PROFILES",
    "YIELD_PER_CHUNK",
    "_FAILMINE_FILL_CAP",
    "_FLAG_BAND_FRAC",
    "Counter",
    "Param",
    "Path",
    "Spec",
    "Stage",
    "_bootstrap",
    "_dirs",
    "_eprint_fetch_fn",
    "_extract",
    "_flag_hit",
    "_frame_lut",
    "_layer",
    "_load_pool",
    "_load_recent_ids",
    "_plan",
    "_qc",
    "_recent",
    "_scan",
    "_scanned_items",
    "_select",
    "_select_flags",
    "_select_quota",
    "_ts",
    "cc",
    "defaultdict",
    "json",
    "lake",
    "math",
    "paths",
    "random",
    "spec",
    "time",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"{_PKG}.{leaf}"), name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return __all__


def _export_drift() -> list[str]:
    """``__all__``/``_LEAF_EXPORTS``/本地公共名三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。三向覆盖:

    - ``_LAZY`` 键全进 ``__all__``;
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链 (``_LEAF_EXPORTS``
      配名叶子不提供) 与幽灵条 (既非叶子名也非本地名) 在此曝, 是首访
      ``AttributeError`` 唯一的提前闸;
    - 本地公共名 (本模块定义的函数/类) 全进 ``__all__``。

    审计实载全部叶子, 只供测试调用, 装载期不自检。
    """
    mod = sys.modules[__name__]
    drift = [
        f"{name} in _LEAF_EXPORTS but missing from __all__"
        for name in _LAZY
        if name not in __all__
    ]
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    for name in __all__:
        try:
            getattr(mod, name)
        except Exception as exc:  # 审计兜全漂移, 非首错即死
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
