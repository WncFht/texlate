"""specs.validbench.judge — 单 case rules/cst 判定叶 (validbench 拆分叶).

``_rules_one`` 跑产品 ``validate_pair`` → 紧凑判定行; ``_cst_*`` 三件套管
TsValidator 常驻 daemon —— thread executor 下每 worker 线程一个懒单例
(``_CST_LOCAL`` threading.local), 对齐旧「每进程单例×jobs」语义。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from specs import _bootstrap

_bootstrap.ensure()

from texlate.validate import rules
from texlate.validate.rules import Severity, validate_pair

REPO = Path(__file__).resolve().parents[4]
BENCH_TS_NM = REPO / "bench" / "ts" / "node_modules"


def _rules_one(cs: dict) -> dict:
    """单 case 跑 validate_pair → 紧凑判定行 (emit_case 负载)."""
    t0 = time.perf_counter_ns()
    rep = validate_pair(cs["src"], cs["zh"])
    ms = (time.perf_counter_ns() - t0) / 1e6
    return {
        "ok": rep.ok,
        "n_err": rep.n_error,
        "n_warn": rep.n_warn,
        "rules_err": sorted(
            {i.rule for i in rep.issues if i.severity is Severity.ERROR}
        ),
        "rules_warn": sorted(
            {i.rule for i in rep.issues if i.severity is Severity.WARN}
        ),
        "suggest": sum(1 for i in rep.issues if i.expected and i.found),
        "ms": round(ms, 4),
    }


def _expect_names(src: str) -> list[str]:
    """src 内 [[TYPE_n]] → worker expect 契约名 (剥括号)."""
    return [m[2:-2] for m in rules.PH_ANY_LIKE_RX.findall(src)]


def _cst_daemon():
    """TsValidator 常驻实例（未 enter）→ (v|None, 不可用原因|None)."""
    try:
        from texlate.validate.cst import TsValidator
    except ImportError as e:
        return None, f"import cst 失败: {e}"
    node_path = BENCH_TS_NM if (BENCH_TS_NM / "tree-sitter").is_dir() else None
    v = TsValidator(node_path=node_path)
    if not v.available():
        return None, "node/tree-sitter 依赖不在场 (TEXLATE_TS_NODE_PATH 可指)"
    return v, None


# thread executor 下的 cst 形态：每 worker 线程一个懒单例（= jobs 个常驻
# node 进程，对齐旧「每进程单例×jobs」语义）。未 close —— 进程退出即收。
_CST_LOCAL = threading.local()


def _cst_here():
    tried = getattr(_CST_LOCAL, "tried", False)
    if not tried:
        _CST_LOCAL.tried = True
        _CST_LOCAL.daemon, _CST_LOCAL.why = _cst_daemon()
    return getattr(_CST_LOCAL, "daemon", None), getattr(_CST_LOCAL, "why", None)


def _cst_one(daemon, cs: dict, baselines: dict) -> dict:
    """常驻 daemon 跑单 case cst 同口径; baseline 缓存按 (paper,chunk,level) 共享 src."""
    key = (cs["paper"], cs["chunk"], cs["level"])
    if key not in baselines:
        baselines[key] = daemon.sign(cs["src"], doc_id=f"{cs['id']}#src")
    res = daemon.validate(
        cs["zh"],
        baseline=baselines[key],
        expect=_expect_names(cs["src"]),
        doc_id=cs["id"],
    )
    ph = res.placeholders
    out = {
        "ok": res.ok,
        "ok_rel": res.ok_relative,
        "detected": not res.verdict_ok,
        "parse_ms": res.parse_ms,
        "signals": {
            "err": len(res.parse_errors),
            "env": len(res.env_mismatches),
            "math": res.unclosed_math,
            "brace": res.brace_balance,
            "ph_miss": len(ph.get("missing", [])),
            "ph_unexp": len(ph.get("unexpected", [])),
            "ph_typo": len(ph.get("typos", [])),
        },
    }
    if res.error:
        out["error"] = res.error
    return out
