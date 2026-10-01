r"""e2e_real — real-arm 全链路付费评测。

``bench/py/e2e_real_bench.py`` 的 spec 化：route → xlat(paid) → compile →
fixloop → base 五段链。与 soak（生产主线）是同构兄弟——soak 走
ingest→parse→xlat→compile→fixloop 的资产流，本 spec 是旧 B5 驱动的
逐格平移，条件臂落为独立 stage 而非 rec 键：

- route   ：src 物化 → find_main_tex → route_project（meta 四键+frame sha
  进 metrics）。无 extracted/无 main/路由拒绝 → ``reject`` +
  ``metrics.reject_at='route'``（旧 ``partial+reject_at`` 折叠为 terminal
  reject——reject_at provenance 进 metrics 保留报表口径）。
- xlat    ：paid。fn 头 ``vault.restore`` 水合 ``state.-``（chunk 断点
  升格——旧 ``work_e2ereal/_xlat_state/`` 全局目录的 vault 形态）；
  copy→normalize→``translate_tree_async``（SessionClient 桥 PaidSession，
  fn 内 ``asyncio.run``——单 thread executor 下不得让 async cell 分波）→
  swap_in ``zh.-`` + ``state.-``。stats→status：oversize→reject；
  leftover_ph>0→fail；fault|skipped>0→error（retriable——``_paper_done``
  的坏块重译语义；「全坏」被本支吞掉属刻意，旧谓词同样重试）；
  partial|fault_files>0→partial；else ok。
- compile ：needs xlat {ok,partial}。zh.- → splice.- → prepare_chinese
  （InjectRejectError→reject+reject_at='inject'）→ xelatex best-effort +
  judge(expect_cjk=translate.chunks!=0——0-delivered 篇目同口径 False)。
- fixloop ：**needs-free 收割汇**——on={compile:…} 只给 topo 边不给闸
  （``_needs_eval`` 只迭代 needs）。末段 mutates 格恒到达 DONE 才能恒
  harvest：xlat/compile 半途死掉的篇目 zh.-/state.- 不困死 work/（soak
  的 needs={clean,partial}+on={fail,dirty_pdf} 在 compile=reject 时
  needs-skip → 付费字节滞留 work/ 只能等 sweep/adopt——本 spec 不复制
  该洞）。fn 内三段闸：route DONE≠ok → reject+gate='route_dead'；
  compile 无 DONE 账且 xlat DONE∈{fail,reject} → reject+gate=
  'no_compile'（链永死）；compile 无 DONE 账但上游仍在 flux → error
  retriable（续跑重评，不提前固化 decline）；compile DONE →
  ``_want_fix`` 谓词，decline→reject+gate='not_wanted'（报告侧按
  gate 分桶，非真 reject）。跑则 copy splice → 冷 usertree+TUNA+
  tlpdb fixloop → 复判 → 修复树 swap 回 splice.-。
- base    ：needs route {ok,reject}（路由拒绝篇也跑归因臂）。topo 序
  base 先于 xlat（Kahn 字母 ready 队列：indeg-0 集合 route 之后
  {base,xlat} 按字典序 base 先）——同 run 内 upstream_rec('xlat')
  恒 None，onfail 抑制只能靠跨 run 账（_last_done 全域）：oversize→
  reject+gate='oversize'、compile clean→reject+gate='compile_clean'；
  无账照跑=onfail→always 的文档化漂移（base 编译免费，宁多勿缺）。

语义决策点（相对旧驱动的漂移，全部有意）：

- ``--time-budget`` 墙钟保险丝 kernel 无等价物——弃参，run 级中止走
  kernel abort/PAUSE 面。
- ``--fixloop-llm`` 付费面：llm_hook 使 fixloop 变付费，而 paid 是静态
  旗标——本 spec 恒 ``llm_hook=None``（fixloop 非 paid 格），付费修复
  臂归 sibling spec（e2e-fixllm），不在本文件。
- ``--rerun``/``--recode``：由 kernel dedup/regen + code_deps/freeze_plan
  覆盖（fp 漂移即重排），无 spec 参数。
- ``--no-preflight``：源码树自检是 run 级前奏非 cell 语义，env_probes
  管二进制在场；弃参。
- probe：``session.probe_model()`` 对 GatewayChat 是无线调用真值返回
  （无 probe_model attr）——nonstream 502 事故面不触线；真实探活由
  401-breaker（PAPER_401_LIMIT=3/RUN_ALL_FAILED_LIMIT=2≡旧
  AUTH_DEAD_STREAK=2）承担。
- items=冻结帧 ``bench/nominations/e2e_real_frame.jsonl``（bake 锁死
  样本集=旧 run_meta.sample_ids 防漂移语义）；``--ids``/``--only``
  窄化经 select()。帧 sha 经 route metrics.frame 留痕（不进 cell
  键域——帧改版不烧付费 dedup）。

拆分（facade 化 god-split）：实现体按 stage 段拆进同包私有叶——
``e2e_real.frame``（冻结帧装载/items+select 与 ROOT/FRAME/EPOCH/ARM）、
``e2e_real.route``（route 段）、``e2e_real.xlat``（翻译段）、
``e2e_real.compile``（compile 段）、``e2e_real.fixloop``（修复+qc
wanted 闸）、``e2e_real.base``（base 归因臂）、``e2e_real.layoutqc``
（T0 质检段）、``e2e_real._spec``（spec 组合根——叶干 ``_`` 前缀脱
导出名 ``spec`` 碰撞）。本文件是 PEP 562
惰性门面（同 ``specs/corpus_v3/__init__.py`` 形制）——平名经 ``_LEAF_EXPORTS``
映射回叶子，``e2e_real.X`` 与 ``from  import X`` 面不变；``spec``
住 ``e2e_real._spec`` 叶（``load_spec`` 首访惰性解析）。叶间直引
``from specs._e2e_real_X import Y`` 不绕本门面（避环）。monkeypatch
锚点注意：tests 钉在本门面的 ``fixloop``/``XelatexEngine`` 由
``e2e_real.fixloop`` 叶内 ``_er.`` 属性读面晚绑定回取（xlat/pipeline
``_net_apply_fn`` 先例），其余实现名住叶子模块——setattr patch 指到
叶子，门面 setattr 只遮蔽门面不改叶子。
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import hashlib
import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from kernel import fsutil, vault
from kernel import paid as paidmod
from kernel.spec import SC_OK_REJECT, SC_SPECTRUM_UP, Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

import importlib
import sys
from typing import TYPE_CHECKING

from specs import _benchlite as benchlib
from specs import _fixloop as flb  # 冷 usertree 引擎配方单源
from specs import _select as _sel  # run 期收窄单源（ids/only 管道）
from specs._layoutqc import qc_paper
from specs._shared import (
    DEFAULT_MODEL,
    PaidEscape,
    SessionClient,
    TimedTranslator,
    _compile_judge,
    _ensure_kind,
    _gate,
    _last_done,
    _last_row,
    _swap_in,
    _xlat_marker,
    case_bridge,
    devin_factory,
)
from specs._xlat_async import translate_tree_async
from texlate.compile.engine import XelatexEngine, route_project
from texlate.compile.fixloop import Ruleset, fixloop
from texlate.compile.inject import (
    InjectRejectError,
    classify_no_main,
    find_main_tex,
    prepare_chinese,
)
from texlate.compile.marks import inject_layout_marks
from texlate.compile.normalize import normalize_project
from texlate.e2e import base_condition
from texlate.pipecore import scan_tree as _scan_tree
from texlate.validate.rules import validate_pair
from texlate.xlat.pipeline import (
    AuthTrippedError,
    GatewayTranslator,
    PipelineConfig,
    RetryPolicy,
)

if TYPE_CHECKING:
    from specs.e2e_real._spec import spec
    from specs.e2e_real.base import _base
    from specs.e2e_real.compile import _compile
    from specs.e2e_real.fixloop import (
        _QC_WANTED_MIN,
        _fixloop,
        _qc_wanted,
        _want_fix,
    )
    from specs.e2e_real.frame import (
        ARM,
        EPOCH,
        FRAME,
        ROOT,
        _frame_sha,
        _items,
        _select,
        _sha256,
    )
    from specs.e2e_real.layoutqc import _layoutqc
    from specs.e2e_real.route import _route
    from specs.e2e_real.xlat import _xlat


_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "frame": (
        "ARM",
        "EPOCH",
        "FRAME",
        "ROOT",
        "_frame_sha",
        "_items",
        "_select",
        "_sha256",
    ),
    "route": ("_route",),
    "xlat": ("_xlat",),
    "compile": ("_compile",),
    "fixloop": (
        "_QC_WANTED_MIN",
        "_fixloop",
        "_qc_wanted",
        "_want_fix",
    ),
    "base": ("_base",),
    "layoutqc": ("_layoutqc",),
    "_spec": ("spec",),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

_PKG = "specs.e2e_real"  # load_spec exec 径下 __package__ 是 ""

# 字面列表——ruff F401 re-export 判定要静态 __all__；键集 = _LAZY 键集 +
# import 期名面（HEAD 全量 import 的平名）。新增导出两侧同步
# （``_export_drift`` 是三表同步闸）。
__all__ = [
    "ARM",
    "DEFAULT_MODEL",
    "EPOCH",
    "FRAME",
    "ROOT",
    "SC_OK_REJECT",
    "SC_SPECTRUM_UP",
    "UTC",
    "_QC_WANTED_MIN",
    "AuthTrippedError",
    "GatewayTranslator",
    "InjectRejectError",
    "PaidEscape",
    "Param",
    "Path",
    "PipelineConfig",
    "RetryPolicy",
    "Ruleset",
    "SessionClient",
    "Spec",
    "Stage",
    "TimedTranslator",
    "XelatexEngine",
    "_base",
    "_bootstrap",
    "_compile",
    "_compile_judge",
    "_ensure_kind",
    "_fixloop",
    "_frame_sha",
    "_gate",
    "_items",
    "_last_done",
    "_last_row",
    "_layoutqc",
    "_qc_wanted",
    "_route",
    "_scan_tree",
    "_sel",
    "_select",
    "_sha256",
    "_swap_in",
    "_want_fix",
    "_xlat",
    "_xlat_marker",
    "asyncio",
    "base_condition",
    "benchlib",
    "case_bridge",
    "classify_no_main",
    "contextlib",
    "datetime",
    "devin_factory",
    "find_main_tex",
    "fixloop",
    "flb",
    "fsutil",
    "functools",
    "hashlib",
    "inject_layout_marks",
    "json",
    "normalize_project",
    "paidmod",
    "prepare_chinese",
    "qc_paper",
    "route_project",
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
