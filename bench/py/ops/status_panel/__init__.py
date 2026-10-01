#!/usr/bin/env python3
"""Read-only local status panel for texlate bench/fleet monitoring.

stdlib-only. Serves a single self-refreshing HTML page on 127.0.0.1.
All data sources are files or read-only commands; collectors are
independently fault-isolated and cached.

Run detached:
    setsid nohup python3 bench/py/ops/status_panel \
        >> "$TEXLATE_BENCH_ROOT/state/status-panel/run.log" 2>&1 </dev/null &
Stop:
    kill "$(cat "$TEXLATE_BENCH_ROOT/state/status-panel/panel.pid")"

Task board convention: agents report progress via
    python3 bench/py/ops/task_ping.py <name> --status running --done N --total M
(board lives at $TEXLATE_BENCH_ROOT/state/status-panel/tasks.d)

拆分：实现体按子域下沉同包私有叶 —— ``status_panel.env`` (REPO/账根
解析/kernel 桥/常量面)、``status_panel.util`` (ttl 缓存/run_cmd/pid/
时长/转义小件)、``status_panel.frag`` (chip/hbar/stacked/badge/table/
minibar html 片段)、``status_panel.collect`` (scorecard/rate/n200/gw/
milestones/tasks/kernel index 采集)、``status_panel.sections``
(sec_* 各节渲染 + SECTIONS 目录)、``status_panel.page`` (PAGE 模板)、
``status_panel.serve`` (render/Handler/pidfile 生命周期)。本文件是
PEP 562 惰性门面 (同 ``kernel.kernel``/``kernel.cli``/``verbs.dossier``
门面形制) —— 平名经 ``_LEAF_EXPORTS`` 映射回叶子，``__getattr__``
首访解析并缓存，公私名面不变。脚本直跑 (``python3 status_panel.py``)
路径：下行 ``sys.path.insert`` 立起 bench/py 后 ``ops.status_panel.<叶>``
叶可导，``__package__`` 缺省回退 ``ops``。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# 包内脚本直跑时 bench/py 不在 sys.path——先立起再引 kernel/ops 叶
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if TYPE_CHECKING:
    from ops.status_panel.collect import (
        _BLOB_SHA_RE,
        _N200_KINDS,
        _N200_STAGES,
        _PDF_STATUS,
        RATE_KEEP_S,
        RATE_MIN_SPAN_S,
        RATE_STATE,
        RATE_WINDOW_S,
        _kernel_index,
        _n200_empty,
        _n200_run,
        _paper_status,
        _rate_sample,
        _unblob,
        collections,
        contextlib,
        dt,
        glob,
        gw_status,
        json,
        milestones,
        n200_stats,
        re,
        scorecard_data,
        scorecard_raw,
        sqlite3,
        tasks,
        urllib,
    )
    from ops.status_panel.env import (
        BENCH_ROOT,
        C_CLEAN,
        C_FAIL,
        C_INFO,
        C_PART,
        C_PURPLE,
        C_SKIP,
        HOST,
        N200_PID,
        PANEL_DIR,
        PIDFILE,
        PORT,
        REFRESH_SECONDS,
        REPO,
        RUNS_DIR,
        SESSIONS_GLOB,
        STALE_TASK_SECONDS,
        STATUS_COLOR,
        STATUS_ZH,
        TASK_STATUS_COLOR,
        TASK_STATUS_ZH,
        TASKS_DIR,
        VENV_PY,
        _kevents,
        _kpaths,
        os,
    )
    from ops.status_panel.frag import (
        badge,
        chip,
        hbar,
        minibar,
        stacked,
        table,
    )
    from ops.status_panel.page import PAGE
    from ops.status_panel.sections import (
        SECTIONS,
        sec_chips,
        sec_jobs,
        sec_kernel,
        sec_ledger,
        sec_milestones,
        sec_n200,
        sec_reports,
        sec_resources,
        sec_scorecard,
        sec_sessions,
        sec_tasks,
    )
    from ops.status_panel.serve import (
        BaseHTTPRequestHandler,
        Handler,
        ThreadingHTTPServer,
        _stop,
        main,
        render,
        signal,
    )
    from ops.status_panel.util import (
        _cache,
        cached,
        esc,
        fmt_age,
        fmt_dur,
        html,
        pid_alive,
        run_cmd,
        subprocess,
        time,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "env": (
        "BENCH_ROOT",
        "C_CLEAN",
        "C_FAIL",
        "C_INFO",
        "C_PART",
        "C_PURPLE",
        "C_SKIP",
        "HOST",
        "N200_PID",
        "PANEL_DIR",
        "PIDFILE",
        "PORT",
        "REFRESH_SECONDS",
        "REPO",
        "RUNS_DIR",
        "SESSIONS_GLOB",
        "STALE_TASK_SECONDS",
        "STATUS_COLOR",
        "STATUS_ZH",
        "TASKS_DIR",
        "TASK_STATUS_COLOR",
        "TASK_STATUS_ZH",
        "VENV_PY",
        "_kevents",
        "_kpaths",
        "os",
    ),
    "util": (
        "_cache",
        "cached",
        "esc",
        "fmt_age",
        "fmt_dur",
        "html",
        "pid_alive",
        "run_cmd",
        "subprocess",
        "time",
    ),
    "frag": (
        "badge",
        "chip",
        "hbar",
        "minibar",
        "stacked",
        "table",
    ),
    "collect": (
        "RATE_KEEP_S",
        "RATE_MIN_SPAN_S",
        "RATE_STATE",
        "RATE_WINDOW_S",
        "_BLOB_SHA_RE",
        "_N200_KINDS",
        "_N200_STAGES",
        "_PDF_STATUS",
        "_kernel_index",
        "_n200_empty",
        "_n200_run",
        "_paper_status",
        "_rate_sample",
        "_unblob",
        "collections",
        "contextlib",
        "dt",
        "glob",
        "gw_status",
        "json",
        "milestones",
        "n200_stats",
        "re",
        "scorecard_data",
        "scorecard_raw",
        "sqlite3",
        "tasks",
        "urllib",
    ),
    "sections": (
        "SECTIONS",
        "sec_chips",
        "sec_jobs",
        "sec_kernel",
        "sec_ledger",
        "sec_milestones",
        "sec_n200",
        "sec_reports",
        "sec_resources",
        "sec_scorecard",
        "sec_sessions",
        "sec_tasks",
    ),
    "page": ("PAGE",),
    "serve": (
        "BaseHTTPRequestHandler",
        "Handler",
        "ThreadingHTTPServer",
        "_stop",
        "main",
        "render",
        "signal",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集 +
# 门面自持名 (``Path``/``sys``/``annotations``)。新增导出两侧同步
# (``_export_drift`` 是三表同步闸)。
__all__ = [
    "BENCH_ROOT",
    "C_CLEAN",
    "C_FAIL",
    "C_INFO",
    "C_PART",
    "C_PURPLE",
    "C_SKIP",
    "HOST",
    "N200_PID",
    "PAGE",
    "PANEL_DIR",
    "PIDFILE",
    "PORT",
    "RATE_KEEP_S",
    "RATE_MIN_SPAN_S",
    "RATE_STATE",
    "RATE_WINDOW_S",
    "REFRESH_SECONDS",
    "REPO",
    "RUNS_DIR",
    "SECTIONS",
    "SESSIONS_GLOB",
    "STALE_TASK_SECONDS",
    "STATUS_COLOR",
    "STATUS_ZH",
    "TASKS_DIR",
    "TASK_STATUS_COLOR",
    "TASK_STATUS_ZH",
    "VENV_PY",
    "_BLOB_SHA_RE",
    "_N200_KINDS",
    "_N200_STAGES",
    "_PDF_STATUS",
    "BaseHTTPRequestHandler",
    "Handler",
    "Path",
    "ThreadingHTTPServer",
    "_cache",
    "_kernel_index",
    "_kevents",
    "_kpaths",
    "_n200_empty",
    "_n200_run",
    "_paper_status",
    "_rate_sample",
    "_stop",
    "_unblob",
    "annotations",
    "badge",
    "cached",
    "chip",
    "collections",
    "contextlib",
    "dt",
    "esc",
    "fmt_age",
    "fmt_dur",
    "glob",
    "gw_status",
    "hbar",
    "html",
    "json",
    "main",
    "milestones",
    "minibar",
    "n200_stats",
    "os",
    "pid_alive",
    "re",
    "render",
    "run_cmd",
    "scorecard_data",
    "scorecard_raw",
    "sec_chips",
    "sec_jobs",
    "sec_kernel",
    "sec_ledger",
    "sec_milestones",
    "sec_n200",
    "sec_reports",
    "sec_resources",
    "sec_scorecard",
    "sec_sessions",
    "sec_tasks",
    "signal",
    "sqlite3",
    "stacked",
    "subprocess",
    "sys",
    "table",
    "tasks",
    "time",
    "urllib",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(
            importlib.import_module(f"{__package__ or 'ops.status_panel'}.{leaf}"), name
        )
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
