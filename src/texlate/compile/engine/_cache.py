"""tlmgr file→pkg 搜索的跨进程落盘缓存 —— ``engine.py`` 拆分叶。"""

from __future__ import annotations

import json
from pathlib import Path

from texlate.textutil import env_raw
from texlate.textutil.osutil import ENV_TLMGR_CACHE


def tlmgr_search_cache_path() -> Path:
    """定位 tlmgr file→pkg 搜索的跨进程落盘缓存位（fixloop 共用约定）。"""
    return Path(
        env_raw(ENV_TLMGR_CACHE)
        or str(Path.home() / ".cache" / "texlate" / "tlmgr-search-cache.json")
    )


def load_search_cache() -> dict[str, list[str]]:
    """读 tlmgr 搜索缓存；缺席/损坏返回空表。

    空命中（阴性）载入即弃：镜像 round-robin 假 "no package provides"
    （``filemap`` docstring 记档）落盘后曾永久遮蔽索引——载入时滤掉
    空表，历史阴性一并自愈，索引/在线通路重获查询权。
    """
    try:
        raw = json.loads(tlmgr_search_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    # 值型闸：truthy 非标量（str/int/dict）原样进缓存会让 filemap 返回
    # 非 list[str]，下游 splat 把 "notalist" 散成单字符包名喂 tlmgr。
    return {
        k: v
        for k, v in raw.items()
        if isinstance(v, list) and v and all(isinstance(e, str) for e in v)
    }


def save_search_cache(cache: dict[str, list[str]]) -> None:
    """写 tlmgr 搜索缓存（父目录自动建）。空命中不落盘——阴性不跨进程固化。"""
    p = tlmgr_search_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({k: v for k, v in cache.items() if v}, indent=0, sort_keys=True),
        encoding="utf-8",
        newline="",
    )
