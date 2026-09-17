"""fixloop — yaml 规则驱动的 LaTeX 编译自动修复循环 (docs/08 §5)。

bench/py/fixloop.py spike (16 规则, 22 格 16/16 救回) 的产品化移植:
``rules/`` 目录多分片两层声明式规则库 (taxonomy + rules) + ``engine.fixloop``
主循环 + ``ctan`` tectonic 降级原语 + ``cases`` 沉淀/回放机制。

引擎边界: 只依赖 :class:`~.engine.Engine` Protocol, 不实现引擎本体。
"""

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
