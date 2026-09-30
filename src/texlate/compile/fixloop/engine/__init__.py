"""Engine — fixloop 规则引擎主循环 (docs/spec/compile.md, 原型移植)。

管线：``eng.compile → parse_log → taxonomy.classify → gate → match → apply →
重编``, ≤``meta.loop.max_rounds`` 轮 (默认 8)。

与 ``compile/engine/`` 的边界：本模块只依赖 :class:`Engine` Protocol
(docs/spec/compile.md §1.1 Engine 签名), 不实现引擎 —— xelatex/tectonic
引擎实现满足本 Protocol 即可对接。

phase 语义 (rules/ 分片注释复制):
  ``gate``     每轮分类后最先评估 (原型 latex209 硬编码短路)
  ``precheck`` 编译前一次性 (静态路由 + 装包预检)
  ``loop``     每轮错误驱动; 同 phase 按 order 升序，每轮至多一条成功应用

C5 拆叶：实现体按域拆进六个 ``_engine_*`` 私有兄弟叶，本文件化纯
PEP 562 惰性门面 (同 ``seqpos/__init__`` 形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``engine.X`` 公共面与 ``from ... import X``/``M._x`` 属性读面不变。
monkeypatch 锚点注意：patch 叶子不 patch 门面 (docs/dev/seams.md §1)
——``engine.name`` 读到的恒是叶子对象，但 ``setattr(engine, ...)``
只遮蔽门面不改叶子内部互引。叶子间互引走全路径直跨
(``texlate.compile.fixloop._engine_<叶>``), 不经本门面。

叶谱：``engine.proto`` 协议面 + 报告装配 / ``engine.ctx`` LoopCtx /
``engine.aux`` 清场挥发件 / ``engine.disp`` 定位+gate/precheck+ 次级
派发 / ``engine.wire`` 引擎接线 + 装配头 / ``engine.run`` _FixRun
主循环核 (二级拆叶：编译相 ``engine.run.comp`` + 尾段 ``engine.run.tail``
两 mixin 叶 + 装配面 ``engine.run.fixloop``)。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine.aux import (
        _AUX_WRITE_EXTS,
        _BSLASH,
        _LBRACE,
        _RBRACE,
        _VOLATILE_EXTS,
        _aux_file_bad,
        _sweep_bad_aux,
    )
    from texlate.compile.fixloop.engine.ctx import (
        _CTX_FIELD_GROUP,
        LoopCtx,
        _CtxDeps,
        _CtxIO,
        _CtxLedger,
        _CtxRound,
    )
    from texlate.compile.fixloop.engine.disp import (
        _REJECT_PREFIX,
        _REJECT_ROUTE_RE,
        DOCCLASS_RX,
        _apply,
        _apply_landed,
        _apply_scan_install,
        _apply_window,
        _commit_reject,
        _cond_ok,
        _dep_stems,
        _gate_eval,
        _gate_fired_of,
        _inject_find_main_tex,
        _is_misschar_rule,
        _landing_sync,
        _match_apply,
        _match_apply_landing,
        _mc_parse_log,
        _note_route,
        _precheck_phase,
        _probe,
        _rule_needs_pass,
        _substitute,
        _warn_family_due,
        _warn_preempt,
        _when_ok,
        decode_tex,
        find_main_tex,
        precheck_pass,
    )
    from texlate.compile.fixloop.engine.proto import (
        CompRes,
        CompResLike,
        Engine,
        ErrReport,
        LlmHook,
        RunFn,
        _driver_fatal,
        _is_runaway_output,
        _note_dropped_flags,
        _report_of,
        _res_died,
        _res_driver_fatal,
        _res_has_pdf,
        _round_cat,
        normalize_stderr_errors,
        parse_log,
        parse_text,
    )
    from texlate.compile.fixloop.engine.run import (
        _SEC_CAND_MAX,
        _SEC_PROBE_MAX,
        _FixRun,
    )
    from texlate.compile.fixloop.engine.run.comp import _UNRESOLVED_MARKS_RX
    from texlate.compile.fixloop.engine.run.fixloop import (
        _classify_no_main,
        _record_case,
        fixloop,
    )
    from texlate.compile.fixloop.engine.wire import (
        RULES_PATH,
        Rule,
        Ruleset,
        RulesetError,
        _setup_ctx,
        _wire_engine,
        _wire_filemap_overrides,
        ctan,
        load_ruleset,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "aux": (
        "_AUX_WRITE_EXTS",
        "_BSLASH",
        "_LBRACE",
        "_RBRACE",
        "_VOLATILE_EXTS",
        "_aux_file_bad",
        "_sweep_bad_aux",
    ),
    "ctx": (
        "_CTX_FIELD_GROUP",
        "LoopCtx",
        "_CtxDeps",
        "_CtxIO",
        "_CtxLedger",
        "_CtxRound",
    ),
    "disp": (
        "DOCCLASS_RX",
        "_REJECT_PREFIX",
        "_REJECT_ROUTE_RE",
        "_apply",
        "_apply_landed",
        "_apply_scan_install",
        "_apply_window",
        "_commit_reject",
        "_cond_ok",
        "_dep_stems",
        "_gate_eval",
        "_gate_fired_of",
        "_inject_find_main_tex",
        "_is_misschar_rule",
        "_landing_sync",
        "_match_apply",
        "_match_apply_landing",
        "_mc_parse_log",
        "_note_route",
        "_precheck_phase",
        "_probe",
        "_rule_needs_pass",
        "_substitute",
        "_warn_family_due",
        "_warn_preempt",
        "_when_ok",
        "decode_tex",
        "find_main_tex",
        "precheck_pass",
    ),
    "proto": (
        "CompRes",
        "CompResLike",
        "Engine",
        "ErrReport",
        "LlmHook",
        "RunFn",
        "_driver_fatal",
        "_is_runaway_output",
        "_note_dropped_flags",
        "_report_of",
        "_res_died",
        "_res_driver_fatal",
        "_res_has_pdf",
        "_round_cat",
        "normalize_stderr_errors",
        "parse_log",
        "parse_text",
    ),
    "run": (
        "_FixRun",
        "_SEC_CAND_MAX",
        "_SEC_PROBE_MAX",
    ),
    "run.comp": ("_UNRESOLVED_MARKS_RX",),
    "run.fixloop": (
        "_classify_no_main",
        "_record_case",
        "fixloop",
    ),
    "wire": (
        "RULES_PATH",
        "Rule",
        "Ruleset",
        "RulesetError",
        "_setup_ctx",
        "_wire_engine",
        "_wire_filemap_overrides",
        "ctan",
        "load_ruleset",
    ),
}

_LAZY: dict[str, str] = {
    name: leaf for leaf, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集，
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "DOCCLASS_RX",
    "RULES_PATH",
    "_AUX_WRITE_EXTS",
    "_BSLASH",
    "_CTX_FIELD_GROUP",
    "_LBRACE",
    "_RBRACE",
    "_REJECT_PREFIX",
    "_REJECT_ROUTE_RE",
    "_SEC_CAND_MAX",
    "_SEC_PROBE_MAX",
    "_UNRESOLVED_MARKS_RX",
    "_VOLATILE_EXTS",
    "CompRes",
    "CompResLike",
    "Engine",
    "ErrReport",
    "LlmHook",
    "LoopCtx",
    "Rule",
    "Ruleset",
    "RulesetError",
    "RunFn",
    "_CtxDeps",
    "_CtxIO",
    "_CtxLedger",
    "_CtxRound",
    "_FixRun",
    "_apply",
    "_apply_landed",
    "_apply_scan_install",
    "_apply_window",
    "_aux_file_bad",
    "_classify_no_main",
    "_commit_reject",
    "_cond_ok",
    "_dep_stems",
    "_driver_fatal",
    "_gate_eval",
    "_gate_fired_of",
    "_inject_find_main_tex",
    "_is_misschar_rule",
    "_is_runaway_output",
    "_landing_sync",
    "_match_apply",
    "_match_apply_landing",
    "_mc_parse_log",
    "_note_dropped_flags",
    "_note_route",
    "_precheck_phase",
    "_probe",
    "_record_case",
    "_report_of",
    "_res_died",
    "_res_driver_fatal",
    "_res_has_pdf",
    "_round_cat",
    "_rule_needs_pass",
    "_setup_ctx",
    "_substitute",
    "_sweep_bad_aux",
    "_warn_family_due",
    "_warn_preempt",
    "_when_ok",
    "_wire_engine",
    "_wire_filemap_overrides",
    "ctan",
    "decode_tex",
    "find_main_tex",
    "fixloop",
    "load_ruleset",
    "normalize_stderr_errors",
    "parse_log",
    "parse_text",
    "precheck_pass",
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
