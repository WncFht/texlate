"""ops.status_panel 环境叶 —— REPO/账根解析 + kernel 桥 + 面板常量面
（status_panel.py 拆分叶）。

``_kpaths`` 在 kernel 缺席的裸跑降级面绑 None（原未绑——差异只在降级面
``hasattr`` 可见）。门面回引名单见 ``ops.status_panel._LEAF_EXPORTS``。
"""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
try:
    from kernel import events as _kevents
    from kernel import paths as _kpaths

    BENCH_ROOT = _kpaths.root()
    RUNS_DIR = _kpaths.runs_dir()
except Exception:  # kernel is stdlib-only; fallback mirrors it
    _kevents = None
    _kpaths = None
    BENCH_ROOT = Path(
        os.environ.get(
            "TEXLATE_BENCH_ROOT", Path.home() / ".local" / "share" / "texlate-bench"
        )
    ).expanduser()
    RUNS_DIR = BENCH_ROOT / "runs"
PANEL_DIR = BENCH_ROOT / "state" / "status-panel"
PIDFILE = PANEL_DIR / "panel.pid"
TASKS_DIR = PANEL_DIR / "tasks.d"
#: run 目录由 _n200_dir() 自动发现（realn200-*/e2e-* 最新含账者）——
#: 原硬钉目录名已在归档后失效，常亮空账不如无候选时的显式空态。
N200_PID = 439968
SESSIONS_GLOB = os.path.expanduser("~/.claude/sessions/*.json")
VENV_PY = REPO / ".venv" / "bin" / "python"
REFRESH_SECONDS = 45
STALE_TASK_SECONDS = 900
HOST = "127.0.0.1"
PORT = int(os.environ.get("PANEL_PORT", "8766"))

C_CLEAN = "#2da44e"
C_FAIL = "#cf222e"
C_PART = "#d4a72c"
C_SKIP = "#8b949e"
C_INFO = "#0969da"
C_PURPLE = "#8250df"

STATUS_COLOR = {
    "clean": C_CLEAN,
    "fail": C_FAIL,
    "partial": C_PART,
    "skipped": C_SKIP,
    "reject": C_FAIL,
}
STATUS_ZH = {
    "clean": "干净",
    "fail": "失败",
    "partial": "部分",
    "skipped": "跳过",
    "reject": "拒收",
}
TASK_STATUS_COLOR = {
    "starting": C_SKIP,
    "running": C_INFO,
    "blocked": C_PART,
    "done": C_CLEAN,
    "failed": C_FAIL,
}
TASK_STATUS_ZH = {
    "starting": "启动",
    "running": "运行",
    "blocked": "阻塞",
    "done": "完成",
    "failed": "失败",
}
