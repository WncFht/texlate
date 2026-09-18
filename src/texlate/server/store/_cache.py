"""translation_cache 聚合 repo：段级缓存读写 + 命中记账（§3.2 表注）。

命中记账缓冲 dict 由门面持有（``store._cache_hits``，测试借道断言面），
本 repo 经构造注入共享同一对象——``cache_get`` 不逐命中 commit（翻译热环
每命中一 fsync 划不来），聚合后由 ``flush_chunk_batch`` 事务顺带落 /
兜底阈值 / ``close`` 冲刷。
"""

from __future__ import annotations

import contextlib
import sqlite3
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.server.store import Store


class CacheRepo:
    """translation_cache 表聚合。构造只存门面回指 + 命中缓冲引用。"""

    #: 命中记账兜底阈值——正常靠 ``flush_chunk_batch``/``close`` 顺带落；
    #: 长串纯命中不触发批写时按此 distinct-key 量自立事务落一次。
    _CACHE_HIT_FLUSH = 64

    def __init__(self, store: Store, hits: dict[str, int]) -> None:
        """回指门面 + 共享命中缓冲（``store._cache_hits`` 同一对象）。"""
        self._s = store
        self._hits = hits

    @property
    def conn(self) -> sqlite3.Connection:
        """门面共享连接——repo 不持有独立连接（单写者纪律由 Store 持有）。"""
        return self._s.conn

    def cache_get(self, key: str) -> str | None:
        """段级缓存读；命中记 hit_count/last_hit_at（聚合批量落）。"""
        row = self.conn.execute(
            "SELECT translation FROM translation_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        self._hits[key] = self._hits.get(key, 0) + 1
        if len(self._hits) >= self._CACHE_HIT_FLUSH:
            self._drain_cache_hits()
        return str(row["translation"])

    def cache_put_batch(self, cache_puts: list[tuple[str, str, str, str]]) -> None:
        """段缓存批量 upsert——不 commit，骑 ``flush_chunk_batch`` 事务。"""
        now = time.time()
        for key, translation, model, lang in cache_puts:
            self.conn.execute(
                "INSERT OR REPLACE INTO translation_cache"
                " (key, translation, model, target_lang, hit_count,"
                "  created_at, last_hit_at) VALUES"
                " (?,?,?,?, COALESCE((SELECT hit_count FROM translation_cache"
                "  WHERE key = ?), 0), COALESCE((SELECT created_at FROM"
                "  translation_cache WHERE key = ?), ?), ?)",
                (
                    key,
                    translation,
                    model,
                    lang,
                    key,
                    key,
                    now,
                    now,
                ),
            )

    def _flush_cache_hits(self) -> None:
        """挂起命中记账 executemany——不 commit，骑调用方事务。"""
        if not self._hits:
            return
        now = time.time()
        self.conn.executemany(
            "UPDATE translation_cache SET hit_count = hit_count + ?,"
            " last_hit_at = ? WHERE key = ?",
            [(n, now, k) for k, n in self._hits.items()],
        )
        self._hits.clear()

    def _drain_cache_hits(self) -> None:
        """自立事务落记账 + commit；失败回滚——命中计数丢得起不炸热环。"""
        try:
            self._flush_cache_hits()
            self.conn.commit()
        except sqlite3.Error:
            with contextlib.suppress(sqlite3.Error):
                self.conn.rollback()
