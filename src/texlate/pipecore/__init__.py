r"""管线核心契约层——e2e / worker / bench 三臂共享的 policy 脊。

``repair/`` 包已把修复机械单源化（``run_fixloop``/
``consume_engine_flags``/``logfix_round``/``embed_tounicode_quiet``…）；
本层收编两臂仍各自复写的**策略脊**，让 4× 接线的管线契约只剩一个事实源：

- 状态空间：pipe 空间（``ok/partial/skipped/fault``）↔ DB 空间
  （``ok/fallback_orig/failed``）映射 + 两空间的 delivered 谓词；
- 扫描/翻译脊：``scan_tree`` 四级分流 + ``translate_tree_run`` 全树翻译
  写回——``scan_fn``/``validator``/``engine_fn``/``probe_fn`` 注入面保住
  各臂模块全局 monkeypatch 缝（e2e 别名绑定、worker ``seams.*`` 直传）；
- 编译尾段：``probe_report``/``compile_judge``/``judge_res``/``tail_dict``
  + job 形 ``compile_judge_tail``/``logfix_job``/``fixloop_job``；
- 修复链编排：``fixloop_round``（轮实况经 ``ReportSink`` 出口）+
  ``fixloop_flags_tail``（engine_flags/reject_route 消费尾）+
  ``logfix``（done 帧同口）；开关决议 ``RepairPolicy``（显式 >
  options > ``TEXLATE_NO_*`` env 缺省皆开）与 ``reject:<rid>`` 判词
  （``reject_verdict``/``precheck_reject``）是 e2e/worker 两臂
  修复链 policy 的单源；整链 ``repair_chain``（precheck→logfix→fixloop
  三级直铺）+ 翻前快照 ``baseline_snapshot`` 收 e2e/bench 两臂
  修复段单件。

观测约定：e2e/bench 臂走 ``NULL_SINK`` 零事件面（报告经 rec dict 投影，
与重构前一致）；worker 臂经 ``_Sink`` 绑 ``_log``/``_repair_event``——
同一份实况键集。

拆分：实现体按子域下沉同目录私有叶——``pipecore.state``（状态映射 +
注入协议）、``pipecore.policy``（开关决议 + reject 判词）、
``pipecore.scan``（front_matter 域 + scan_tree + 术语装配）、
``pipecore.translate``（translate_tree_run 全树写回脊）、
``pipecore.tail``（编译尾段 + PipeJob + precheck_job）、
``pipecore._logfix``（logfix 回灌执行件）、``pipecore.fixloop``（fixloop
执行件）、``pipecore.chain``（baseline_snapshot + repair_chain
编排）。本文件是 PEP 562 惰性门面（同 ``kernel.kernel``/
``latex.reconstruct`` 门面形制）——平名经 ``_LEAF_EXPORTS`` 映射回
叶子，``__getattr__`` 首访解析并缓存，``pipecore.X`` 公共面与
``from  import X`` 消费面不变；叶子私名（``_opt_switch``/
``_texmf_eng`` 等原门面名面）同经映射回引，新代码请直引叶子模块。
monkeypatch 锚点注意：setattr 只遮蔽门面不改叶子——patch 须指向叶子
模块同名（如 ``texlate.pipecore.scan.scan_tree``/
``texlate.pipecore.tail.engine_for``/``texlate.pipecore.tail.target_probe``/
``texlate.pipecore.fixloop.engine_for``）。
"""

from __future__ import annotations

import importlib
import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.pipecore._logfix import logfix, logfix_job
    from texlate.pipecore.chain import baseline_snapshot, repair_chain
    from texlate.pipecore.fixloop import (
        _slim_cell,
        fixloop_flags_tail,
        fixloop_job,
        fixloop_round,
    )
    from texlate.pipecore.policy import (
        RepairPolicy,
        _opt_switch,
        precheck_reject,
        reject_verdict,
    )
    from texlate.pipecore.scan import (
        _FRONT_MATTER_DEFAULT,
        ENV_FRONT_MATTER,
        FRONT_MATTER_NAMES,
        auto_glossary_fn,
        default_front_matter,
        front_matter_of,
        ran_front_matter,
        scan_tree,
    )
    from texlate.pipecore.state import (
        DB_TO_PIPE,
        NULL_SINK,
        PIPE_TO_DB,
        CompileRunner,
        ReportSink,
        _NullSink,
        delivered,
        delivered_db,
    )
    from texlate.pipecore.tail import (
        PipeJob,
        _compile_judge_job,
        _texmf_eng,
        _texmf_wire,
        compile_judge,
        compile_judge_tail,
        judge_res,
        precheck_job,
        probe_report,
        tail_dict,
    )
    from texlate.pipecore.translate import (
        PH_RX,
        _auto_glossary_fn,
        translate_tree_run,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "state": (
        "DB_TO_PIPE",
        "NULL_SINK",
        "PIPE_TO_DB",
        "CompileRunner",
        "ReportSink",
        "_NullSink",
        "delivered",
        "delivered_db",
    ),
    "policy": (
        "RepairPolicy",
        "_opt_switch",
        "precheck_reject",
        "reject_verdict",
    ),
    "scan": (
        "ENV_FRONT_MATTER",
        "FRONT_MATTER_NAMES",
        "_FRONT_MATTER_DEFAULT",
        "auto_glossary_fn",
        "default_front_matter",
        "front_matter_of",
        "ran_front_matter",
        "scan_tree",
    ),
    "translate": (
        "PH_RX",
        "_auto_glossary_fn",
        "translate_tree_run",
    ),
    "tail": (
        "PipeJob",
        "_compile_judge_job",
        "_texmf_eng",
        "_texmf_wire",
        "compile_judge",
        "compile_judge_tail",
        "judge_res",
        "precheck_job",
        "probe_report",
        "tail_dict",
    ),
    "_logfix": (
        "logfix",
        "logfix_job",
    ),
    "fixloop": (
        "_slim_cell",
        "fixloop_flags_tail",
        "fixloop_job",
        "fixloop_round",
    ),
    "chain": (
        "baseline_snapshot",
        "repair_chain",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__；键集 = _LAZY 键集，
# 新增导出两侧同步（``_export_drift`` 是三表同步闸）。
__all__ = [
    "DB_TO_PIPE",
    "ENV_FRONT_MATTER",
    "FRONT_MATTER_NAMES",
    "NULL_SINK",
    "PH_RX",
    "PIPE_TO_DB",
    "_FRONT_MATTER_DEFAULT",
    "CompileRunner",
    "PipeJob",
    "RepairPolicy",
    "ReportSink",
    "_NullSink",
    "_auto_glossary_fn",
    "_compile_judge_job",
    "_opt_switch",
    "_slim_cell",
    "_texmf_eng",
    "_texmf_wire",
    "auto_glossary_fn",
    "baseline_snapshot",
    "compile_judge",
    "compile_judge_tail",
    "default_front_matter",
    "delivered",
    "delivered_db",
    "fixloop_flags_tail",
    "fixloop_job",
    "fixloop_round",
    "front_matter_of",
    "judge_res",
    "logfix",
    "logfix_job",
    "precheck_job",
    "precheck_reject",
    "probe_report",
    "ran_front_matter",
    "reject_verdict",
    "repair_chain",
    "scan_tree",
    "tail_dict",
    "translate_tree_run",
]

log = logging.getLogger(__name__)


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

    - ``_LAZY`` 键全进 ``__all__``；
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链（``_LEAF_EXPORTS``
      配名叶子不提供）与幽灵条在此曝，是首访 ``AttributeError`` 唯一
      的提前闸；
    - 本地公共名（本模块定义的函数/类/dict）全进 ``__all__``。

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
        except Exception as exc:  # noqa: BLE001 -- 审计兜全漂移，非首错即死
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and (
            isinstance(v, dict)
            or (callable(v) and getattr(v, "__module__", None) == __name__)
        )
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
