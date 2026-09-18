"""fixloop — yaml 规则驱动的 LaTeX 编译自动修复循环 (docs/08 §5)。

bench/py/fixloop.py spike (16 规则, 22 格 16/16 救回) 的产品化移植:
``rules/`` 目录多分片两层声明式规则库 (taxonomy + rules) + ``engine.fixloop``
主循环 + ``ctan`` tectonic 降级原语 + ``cases`` 沉淀/回放机制。

引擎边界: 只依赖 :class:`~.engine.Engine` Protocol, 不实现引擎本体。

惰性门面 (PEP 562, 同 ``xlat/__init__`` 形制): ``__all__`` 平名经
``__getattr__`` 映射回子模块惰性解析——``cases`` 顶层 ``import fcntl``
是 POSIX-only, 急切导入会让 ``import texlate.compile.fixloop`` 在非
POSIX 环境 (以及只需 engine/logparse 的轻场景) 无谓炸掉或白付成本。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.compile.fixloop.cases import (
        CaseSink,
        ReplayResult,
        load_cases,
        replay_all,
        replay_case,
        stats_backfill,
        triage,
    )
    from texlate.compile.fixloop.ctan import (
        CtanFetcher,
        FetchResult,
        TlpdbIndex,
        check_version_compat,
        ctan_fetch,
        fetch_package,
    )
    from texlate.compile.fixloop.engine import (
        Engine,
        LoopCtx,
        Ruleset,
        RulesetError,
        find_main_tex,
        fixloop,
        load_ruleset,
    )
    from texlate.compile.fixloop.logparse import ErrReport, Taxonomy, parse_log

_SUBMODULE_EXPORTS: dict[str, tuple[str, ...]] = {
    "cases": (
        "CaseSink",
        "ReplayResult",
        "load_cases",
        "replay_all",
        "replay_case",
        "stats_backfill",
        "triage",
    ),
    "ctan": (
        "CtanFetcher",
        "FetchResult",
        "TlpdbIndex",
        "check_version_compat",
        "ctan_fetch",
        "fetch_package",
    ),
    "engine": (
        "Engine",
        "LoopCtx",
        "Ruleset",
        "RulesetError",
        "find_main_tex",
        "fixloop",
        "load_ruleset",
    ),
    "logparse": ("ErrReport", "Taxonomy", "parse_log"),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _SUBMODULE_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集,
# 新增导出两侧同步。
__all__ = [
    "CaseSink",
    "CtanFetcher",
    "Engine",
    "ErrReport",
    "FetchResult",
    "LoopCtx",
    "ReplayResult",
    "Ruleset",
    "RulesetError",
    "Taxonomy",
    "TlpdbIndex",
    "check_version_compat",
    "ctan_fetch",
    "fetch_package",
    "find_main_tex",
    "fixloop",
    "load_cases",
    "load_ruleset",
    "parse_log",
    "replay_all",
    "replay_case",
    "stats_backfill",
    "triage",
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
