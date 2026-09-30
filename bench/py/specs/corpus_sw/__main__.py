"""``python specs/corpus_sw``/``python -m specs.corpus_sw`` worker 入口。

单件期 ``corpus_sw.py`` 的 ``__main__`` 尾块——包化后搬此。裸跑时
bench/py 不在 sys.path，先立起才够得着 specs.*。
"""

import sys
from pathlib import Path

_BENCH_PY = str(Path(__file__).resolve().parents[2])
if _BENCH_PY not in sys.path:
    sys.path.insert(0, _BENCH_PY)

from specs.corpus_sw.worker import _worker_cli

if __name__ == "__main__":
    sys.exit(_worker_cli(sys.argv))
