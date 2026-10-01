"""``python -m kernel.cli`` / 直跑本文件——bench 主入口（kernel.cli.main）。"""

import sys
from pathlib import Path

# 裸跑 ``python bench/py/kernel/cli/__main__.py`` 时 bench/py 不在
# sys.path——先立起才够得着 kernel.*。
_BENCH_PY = str(Path(__file__).resolve().parents[2])
if _BENCH_PY not in sys.path:
    sys.path.insert(0, _BENCH_PY)

from kernel.cli._main import main

raise SystemExit(main())
