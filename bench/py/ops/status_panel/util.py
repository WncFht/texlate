"""ops.status_panel 小件叶 —— ttl 缓存 + run_cmd 子进程 + pid/时长/转义
工具件（status_panel.py 拆分叶）。

门面回引名单见 ``ops.status_panel._LEAF_EXPORTS``。
"""

from __future__ import annotations

import html
import os
import subprocess
import time

from ops.status_panel.env import REPO

_cache: dict[str, tuple[float, object]] = {}


def cached(key: str, ttl: float, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def run_cmd(argv: list[str], timeout: float) -> str:
    proc = subprocess.run(
        argv,
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    out = (proc.stdout + proc.stderr).strip()
    return out or f"(exit {proc.returncode}, no output)"


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def fmt_age(ts: float) -> str:
    delta = max(0, time.time() - ts)
    if delta < 60:
        return f"{delta:.0f} 秒前"
    if delta < 3600:
        return f"{delta / 60:.0f} 分钟前"
    if delta < 86400:
        return f"{delta / 3600:.1f} 小时前"
    return f"{delta / 86400:.1f} 天前"


def fmt_dur(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h} 小时 {m:02d} 分" if h else f"{m} 分钟"


def esc(s: object) -> str:
    return html.escape(str(s))
