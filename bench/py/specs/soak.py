r"""soak — 生产翻译链单 spec 化。

ingest → parse → xlat(paid) → compile → fixloop(paid) 单 run 内串行——
``same_id_serial`` 把同一篇的五个 cell 钉在同一 worker 按 plan 序执行，
论文间跨 ``--jobs`` 并行。取代旧「5 run/日」stagerun 管线（续跑语义经
ledger 而非共享 work/ 目录）。

逐格口径移植自 stage_{ingest,parse,xlat,compile,fixloop}.py：

- ingest：catalog 状态机 → ``ctx.src_path()`` 硬链接场——**先按
  catalog state 分类再调 src_path**（``empty`` 态的 cell 目录会经
  src_path 投影成伪 ok 树）。fetch_fn=None：湖外抓取归 corpus
  builders（corpus_v3/expand/layers/hot 各 spec），本 spec 只消费
  已在湖/可自愈的格。
- parse：route → ``.zh-build`` 暂存 → normalize → scan_tex_tree →
  swap_in ``zh.-`` + ``zh.-/parse.json``（随树进 vault，跨 run 消费
  者另读 ``upstream_rec("parse").metrics``）。
- xlat：zh.- → ``.zh-xlat`` 暂存 → XlatPipeline(session 桥接网关) →
  swap_in + ``state.-/``（StateStore + xlat-detail.jsonl）+
  ``zh.-/.xlat-arm.json`` provenance marker。``AuthTrippedError`` →
  ``PaidAbortCell``（fail + auth_dead + auth_tripped，§3.6 对拍单列）。
- compile：zh.- → splice.- 重建 → inject → judge；base 归因臂折进
  ``metrics.base``（一格一 compile_base 观测——旧 2-record 口径的
  2→1 折叠白名单项）。
- fixloop：**恒自 zh.- 重建 splice.-**（rerun-only 语义——上波就地
  变异不进新轮，2211.04482 脏 splice 实证）；on 谓词不中的格回
  ``ok`` + ``metrics.fixloop_ran=False``——这是 DONE 终态让
  §3.5 harvest 把付费 zh.-/state.- 字节封进 vault 的命门（skip 是
  retriable 不触发 harvest，付费字节会整批滞留 work/）。

执行器：全 stage ``thread``——kernel 按 executor 分组**串行**跑
（``for ex, group in by_exec.items()``），混 executor 会把链拆成两波
让下游集体 needs-skip；``process`` 被 run() 明拒（env/meter 不可
pickle）。xlat 的 async 编排由 fn 内 ``asyncio.run`` 自持。

拆分（facade 化 god-split）：实现体按 stage 段拆进同包私有叶——
``_soak_items``（corpus 行投影/catalog 缓存/抽样/items+select 挂点与
ROOT/CORPUS/EPOCH/_HYDRATABLE 常量）、``_soak_ingest``（src 物化段）、
``_soak_parse``（route→normalize→scan 段）、``_soak_xlat``（翻译段）、
``_soak_compile``（splice 重建小件 + compile 段）、``_soak_fixloop``
（修复段）、``_soak_spec``（spec 组合根）。本文件是 PEP 562 惰性门面
（同 ``specs/corpus_v3.py`` 形制）——平名经 ``_LEAF_EXPORTS`` 映射回
叶子，``soak.X`` 与 ``from ... import X`` 面不变；``spec`` 住
``_soak_spec`` 叶（``load_spec`` 首访惰性解析）。叶间直引
``from specs._soak_X import Y`` 不绕本门面（避环）。monkeypatch 锚点
注意：实现名住叶子模块——setattr patch 须指到叶子，门面 setattr
只遮蔽门面不改叶子（同 corpus_v3 先例）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from kernel import fsutil, lake, paths, vault
from kernel import paid as paidmod
from kernel.spec import EVAL_LAYERS, SC_SPECTRUM_UP, Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

import importlib
import sys
from typing import TYPE_CHECKING

from specs import _benchlite as benchlib
from specs import _fixloop as flb  # 冷 usertree 引擎配方单源
from specs import _qmetrics as qp  # S5 指标单源（quality_proxies 叶化）
from specs import _select as _sel  # run 期收窄单源（ids/layers/only/n 管道）
from specs._shared import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    PaidEscape,
    SessionClient,
    SessionTranslator,
    TimedTranslator,
    _compile_judge,
    _ensure_kind,
    _gate,
    _last_done,
    _swap_in,
    _xlat_marker,
    case_bridge,
    devin_factory,
)
from specs._xlat_async import translate_tree_async
from texlate.compile.engine import XelatexEngine, route_project
from texlate.compile.fixloop import Ruleset, fixloop
from texlate.compile.fixloop.llm_hook import make_llm_hook
from texlate.compile.inject import (
    InjectRejectError,
    classify_no_main,
    find_main_tex,
    prepare_chinese,
)
from texlate.compile.normalize import normalize_project
from texlate.latex.api import scan_tex_tree
from texlate.pipecore import delivered
from texlate.pipecore import scan_tree as _scan_tree
from texlate.repair import ResProxy
from texlate.validate.l0 import validate_pair
from texlate.xlat.glossary import LOCAL_GLOSSARY_NAME, Glossary
from texlate.xlat.pipeline import (
    AuthTrippedError,
    GatewayTranslator,
    PipelineConfig,
    RetryPolicy,
)
from texlate.xlat.prompts import PROMPT_VERSION

if TYPE_CHECKING:
    from specs._soak_compile import (
        _compile,
        _engine,
        _ensure_translated,
        _main_rel,
        _rebuild,
    )
    from specs._soak_fixloop import (
        _ON_PRED,
        _fixloop,
    )
    from specs._soak_ingest import (
        _BAD_FMTS,
        _ingest,
    )
    from specs._soak_items import (
        _CAT_MEMO,
        _HYDRATABLE,
        _ITEMS,
        _SAMPLE_MEMO,
        CORPUS,
        EPOCH,
        ROOT,
        _catalog,
        _corpus_rows,
        _items,
        _n_sample,
        _sample_ids,
        _sampleable,
        _select,
    )
    from specs._soak_parse import _parse
    from specs._soak_spec import spec
    from specs._soak_xlat import _xlat


_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_soak_items": (
        "CORPUS",
        "EPOCH",
        "ROOT",
        "_CAT_MEMO",
        "_HYDRATABLE",
        "_ITEMS",
        "_SAMPLE_MEMO",
        "_catalog",
        "_corpus_rows",
        "_items",
        "_n_sample",
        "_sample_ids",
        "_sampleable",
        "_select",
    ),
    "_soak_ingest": (
        "_BAD_FMTS",
        "_ingest",
    ),
    "_soak_parse": ("_parse",),
    "_soak_xlat": ("_xlat",),
    "_soak_compile": (
        "_compile",
        "_engine",
        "_ensure_translated",
        "_main_rel",
        "_rebuild",
    ),
    "_soak_fixloop": (
        "_ON_PRED",
        "_fixloop",
    ),
    "_soak_spec": ("spec",),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

_PKG = __package__ or "specs"  # load_spec exec 径下 __package__ 是 ""

# 字面列表——ruff F401 re-export 判定要静态 __all__；键集 = _LAZY 键集 +
# import 期名面（HEAD 全量 import 的平名）。新增导出两侧同步
# （``_export_drift`` 是三表同步闸）。
__all__ = [
    "CORPUS",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "EPOCH",
    "EVAL_LAYERS",
    "LOCAL_GLOSSARY_NAME",
    "PROMPT_VERSION",
    "ROOT",
    "SC_SPECTRUM_UP",
    "UTC",
    "_BAD_FMTS",
    "_CAT_MEMO",
    "_HYDRATABLE",
    "_ITEMS",
    "_ON_PRED",
    "_SAMPLE_MEMO",
    "AuthTrippedError",
    "GatewayTranslator",
    "Glossary",
    "InjectRejectError",
    "PaidEscape",
    "Param",
    "Path",
    "PipelineConfig",
    "ResProxy",
    "RetryPolicy",
    "Ruleset",
    "SessionClient",
    "SessionTranslator",
    "Spec",
    "Stage",
    "TimedTranslator",
    "XelatexEngine",
    "_bootstrap",
    "_catalog",
    "_compile",
    "_compile_judge",
    "_corpus_rows",
    "_engine",
    "_ensure_kind",
    "_ensure_translated",
    "_fixloop",
    "_gate",
    "_ingest",
    "_items",
    "_last_done",
    "_main_rel",
    "_n_sample",
    "_parse",
    "_rebuild",
    "_sample_ids",
    "_sampleable",
    "_scan_tree",
    "_sel",
    "_select",
    "_swap_in",
    "_xlat",
    "_xlat_marker",
    "asyncio",
    "benchlib",
    "case_bridge",
    "classify_no_main",
    "contextlib",
    "datetime",
    "delivered",
    "devin_factory",
    "find_main_tex",
    "fixloop",
    "flb",
    "fsutil",
    "json",
    "lake",
    "make_llm_hook",
    "normalize_project",
    "os",
    "paidmod",
    "paths",
    "prepare_chinese",
    "qp",
    "route_project",
    "scan_tex_tree",
    "shutil",
    "spec",
    "time",
    "translate_tree_async",
    "validate_pair",
    "vault",
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
