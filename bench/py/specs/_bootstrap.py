"""specs 自举件——``src/``（与可选 ``bench/py``）准入 ``sys.path``。

``src/`` 不在 ``bench`` 入口的 sys.path 上（kernel 惰性 import
``texlate.*``）；``TEXLATE_SRC`` env 冻结快照优先，否则本仓 ``src/``。
``_front`` 先摘再插——多 spec 同进程反复 ensure 不堆叠同径条目。

消费形（须在 ``from specs._*``/``from texlate.*`` 之前跑——那些辅助件
顶层直 import texlate）::

    from specs import _bootstrap

    _bootstrap.ensure()

worker 裸跑 ``python specs/x.py --worker`` 的双径形态：``bench/py``
尚未在 sys.path 上、``from specs`` 无从谈起——先把 bench/py 手工立起
（幂等 ``not in`` 守卫），再走上面的两行。
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BENCH_PY = REPO / "bench" / "py"
SRC = Path(os.environ.get("TEXLATE_SRC", str(REPO / "src")))


def _front(p: Path) -> None:
    s = str(p)
    with contextlib.suppress(ValueError):
        sys.path.remove(s)
    sys.path.insert(0, s)


def ensure(*, bench_py: bool = False) -> Path:
    """src/ 置 sys.path 首位；``bench_py=True`` 时再前置 bench/py。返回 SRC。"""
    _front(SRC)
    if bench_py:
        _front(BENCH_PY)
    return SRC
