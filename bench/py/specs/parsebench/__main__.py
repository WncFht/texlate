"""``python specs/parsebench``/``python -m specs.parsebench`` worker 入口。

单件期 ``parsebench.py`` 的 ``__main__`` 尾块——包化后搬此；父侧
``parsebench.eval`` 子进程 argv 直钉本文件。裸跑时 bench/py 不在
sys.path，先立起才够得着 specs.*。
"""

import sys
from pathlib import Path

_BENCH_PY = str(Path(__file__).resolve().parents[2])
if _BENCH_PY not in sys.path:
    sys.path.insert(0, _BENCH_PY)

from specs.parsebench.worker import _worker_cli

if __name__ == "__main__":
    raise SystemExit(_worker_cli())
