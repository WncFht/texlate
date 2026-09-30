"""lake 容量闸叶 —— admit 双闸 (cap 水位 + fs floor) 与
DiskPressureError 抓取余量闸。

原 ``kernel.lake`` 顶层「capacity gate」段 + env 常量
(``TEXLATE_LAKE_CAP_GB``/``TEXLATE_LAKE_FLOOR_GB``/
``TEXLATE_BENCH_MIN_FREE_GB``)。env 一律读期现取——测试
``monkeypatch.setenv`` 与 ``monkeypatch.setattr(shutil,
"disk_usage", ...)`` 钉点语义不变。``DiskPressureError.__module__``
钉回 ``kernel.lake``。门面回引名单见 ``kernel.lake._LEAF_EXPORTS``;
monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import os
import shutil

from kernel import fsutil, paths

_ENV_LAKE_CAP_GB = "TEXLATE_LAKE_CAP_GB"
_ENV_LAKE_FLOOR_GB = "TEXLATE_LAKE_FLOOR_GB"
_ENV_MIN_FREE_GB = "TEXLATE_BENCH_MIN_FREE_GB"
_GIB = 1024**3


def admit(
    n_bytes: int, cap_gb: float | None = None, floor_gb: float | None = None
) -> bool:
    """Admission control for lake writes (§3.10.1, R9).

    Two gates, both must pass:

    - cap: lake zone apparent bytes + ``n_bytes`` ≤
      ``TEXLATE_LAKE_CAP_GB`` GiB (default 100 — a watermark, not a target;
      the lake stays lazy).
    - fs floor: filesystem free space minus ``n_bytes`` must leave ≥
      ``TEXLATE_LAKE_FLOOR_GB`` GiB (default 27 = the §3.10.1
      ``fs_avail−25GB−2GB`` reserve: 25G vault + 2G ledger).
    """
    if cap_gb is None:
        cap_gb = float(os.environ.get(_ENV_LAKE_CAP_GB, "100"))
    if floor_gb is None:
        floor_gb = float(os.environ.get(_ENV_LAKE_FLOOR_GB, "27"))
    lake = paths.lake_dir()
    used = fsutil.dir_size(lake) if lake.exists() else 0
    if used + n_bytes > cap_gb * _GIB:
        return False
    try:
        free = shutil.disk_usage(lake).free
    except OSError:
        lake.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(lake).free
    return free - n_bytes >= floor_gb * _GIB


class DiskPressureError(Exception):
    """Retriable free-space gate: raised by ``hydrate`` before starting a
    NEW network fetch when the lake filesystem has less than
    ``TEXLATE_BENCH_MIN_FREE_GB`` GiB free (default 60). A plain
    exception surfaces through stage.fn as cell status ``error`` —
    STATUS_RETRIABLE, never ``fault`` — so the run retries once headroom
    returns, and the lookahead prefetcher logs it as a warn note.

    Two deliberate exemptions:

    - the local raw_only→hydrated re-extract is never gated: no fetch_fn,
      no network, and its bytes are mostly hardlink-shared with the raw
      layer it re-projects;
    - a filesystem whose TOTAL capacity is below the floor can never
      satisfy the watermark — the gate would be a permanent deadlock,
      not backpressure — so scratch roots (tmpfs test dirs, small CI
      volumes) skip it by construction. Per-write absolute protection on
      those stays with ``admit``'s fs-floor leg."""


DiskPressureError.__module__ = "kernel.lake"


def _check_fetch_headroom() -> None:
    """The DiskPressureError gate — see the class docstring."""
    lake = paths.lake_dir()
    try:
        usage = shutil.disk_usage(lake)
    except OSError:
        lake.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(lake)
    floor = float(os.environ.get(_ENV_MIN_FREE_GB, "60")) * _GIB
    if usage.total < floor:
        return
    if usage.free < floor:
        msg = (
            f"lake disk pressure: {usage.free / _GIB:.1f} GiB free < "
            f"{floor / _GIB:.1f} GiB floor ({_ENV_MIN_FREE_GB}) — "
            "refusing new fetch"
        )
        raise DiskPressureError(msg)
