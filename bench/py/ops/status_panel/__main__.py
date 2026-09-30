"""``python bench/py/ops/status_panel``/``python -m ops.status_panel`` 入口。

单件期 ``status_panel.py`` 的 ``__main__`` 尾块——包化后搬此。裸跑时
bench/py 不在 sys.path，先立起才够得着 ops.*/kernel.*。
"""

import sys
from pathlib import Path

_BENCH_PY = str(Path(__file__).resolve().parents[2])
if _BENCH_PY not in sys.path:
    sys.path.insert(0, _BENCH_PY)

from ops.status_panel.serve import main

if __name__ == "__main__":
    main()
