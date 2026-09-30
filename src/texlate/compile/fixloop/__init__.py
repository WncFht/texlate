"""fixloop — yaml 规则驱动的 LaTeX 编译自动修复循环 (docs/spec/compile.md)。

原型 fixloop (16 规则, 22 格 16/16 救回) 的产品化移植:
``rules/`` 目录多分片两层声明式规则库 (taxonomy + rules) + ``engine.fixloop``
主循环 + ``cases`` 沉淀/回放机制。
(``ctan``/``logparse`` 已归位 ``texlate.compile.*``, 直引, 不经本门面。)

引擎边界: 只依赖 :class:`~.engine.Engine` Protocol, 不实现引擎本体。

惰性门面 (PEP 562, 同 ``xlat/__init__`` 形制): ``__all__`` 平名经
``__getattr__`` 映射回子模块惰性解析——``cases`` 顶层 ``import fcntl``
是 POSIX-only, 急切导入会让 ``import texlate.compile.fixloop`` 在非
POSIX 环境 (以及只需 engine 的轻场景) 无谓炸掉或白付成本。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.compile.fixloop.cases import (
        CaseSink,
        ReplayResult,
        load_cases,
        proj_resolver,
        replay_all,
        replay_case,
        stats_backfill,
        triage,
        xelatex_factory,
    )
    from texlate.compile.fixloop.engine import (
        Engine,
        LoopCtx,
        Ruleset,
        RulesetError,
        find_main_tex,
        fixloop,
        load_ruleset,
        precheck_pass,
    )

_SUBMODULE_EXPORTS: dict[str, tuple[str, ...]] = {
    "cases": (
        "CaseSink",
        "ReplayResult",
        "load_cases",
        "proj_resolver",
        "replay_all",
        "replay_case",
        "stats_backfill",
        "triage",
        "xelatex_factory",
    ),
    "engine": (
        "Engine",
        "LoopCtx",
        "Ruleset",
        "RulesetError",
        "find_main_tex",
        "fixloop",
        "load_ruleset",
        "precheck_pass",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _SUBMODULE_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集,
# 新增导出两侧同步。
__all__ = [
    "CaseSink",
    "Engine",
    "LoopCtx",
    "ReplayResult",
    "Ruleset",
    "RulesetError",
    "find_main_tex",
    "fixloop",
    "load_cases",
    "load_ruleset",
    "precheck_pass",
    "proj_resolver",
    "replay_all",
    "replay_case",
    "stats_backfill",
    "triage",
    "xelatex_factory",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 子模块属性; 子模块名本身也走惰性 import。"""
    mod = _LAZY.get(name)
    if mod is not None:
        value = getattr(importlib.import_module(f".{mod}", __name__), name)
        globals()[name] = value
        return value
    if name in _SUBMODULE_EXPORTS:
        return importlib.import_module(f".{name}", __name__)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return __all__
