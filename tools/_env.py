"""tools/ 脚本环境自举——import 本件即把仓根 src/ 推上 sys.path。

裸跑 ``python tools/x.py`` 时脚本目录在 sys.path[0]，``import _env`` 可解；
旧 ``sys.path.insert(0, "src")`` 是相对径，非仓根 cwd 会静默找不到包。
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_SRC = str(REPO / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# bench/py 不上 sys.path 是刻意的——顶层 cli/cache/events 等泛名会遮蔽；
# 消费 kernel/specs 的脚本按需 ``sys.path.insert(0, str(BENCH_PY))``。
BENCH_PY = REPO / "bench" / "py"

TEXLATE_ROOT = Path.home() / ".texlate"
TASKS = TEXLATE_ROOT / "tasks"
DB = TEXLATE_ROOT / "texlate.db"
