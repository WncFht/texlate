"""段缓存桥域（自 ``_common`` 出叶）：``SegmentCache`` + ``_repend_puts``。

``SegmentCache`` 是 ``translation_cache`` 表的 dict 门面（XlatPipeline
``cache`` 参数契约）：键 = ``{cfg_hash}:{seg_key}``，``prewarm`` 后读面纯
内存（``_pending ∪ _written ∪ _pre``），写进 pending 由 ``drain`` 随
chunk flush 事务落盘。``_repend_puts`` 是 drain 后落盘失败的回挂就地
实现（类无公共 repend 面）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from texlate.server.store import Store


class SegmentCache:
    """``translation_cache`` 表的 dict 门面（XlatPipeline ``cache`` 参数契约）。

    键 = ``{cfg_hash}:{seg_key}``——``cfg_hash`` 由
    ``sha256(model|prompt_ver|target_lang|base_url|glossary)[:16]`` 派生，管线内部
    ``_seg_key`` 再叠 src_text+kind+masked 快照。``prewarm`` 后读面 =
    ``_pending ∪ _written ∪ _pre`` 纯内存；未预载保持逐键读穿透。
    写进 pending 缓冲由 ``drain`` 随 chunk flush 事务落盘。
    """

    def __init__(
        self,
        store: Store,
        *,
        prefix: str,
        model: str,
        target_lang: str,
    ) -> None:
        """Prefix = 配置指纹前缀（含 key 指纹若 cache_scope=per_key）。"""
        self._store = store
        self._prefix = prefix
        self._model = model
        self._lang = target_lang
        self._pending: dict[str, str] = {}
        #: drain 落盘后的本 run 内可读副本——run 内 dedup（同文档重复段）
        #: 靠它保持命中语义，不靠回表 SELECT
        self._written: dict[str, str] = {}
        #: prewarm 预载命中表；None = 未预载（走逐键读穿透旧路）
        self._pre: dict[str, str] | None = None
        self.hits = 0

    def _full(self, seg_key: str) -> str:
        return f"{self._prefix}:{seg_key}"

    def prewarm(self, seg_keys: Iterable[str]) -> None:
        """一次性 ``IN`` 批查预载命中——替掉 ``__contains__``/``__getitem__`` 逐键 SELECT。

        逐键读的代价：5k 块 = 5k 次 loop 线程同步查询（单写者纪律下 conn
        只在 loop 线程用，缓存读全部堵在主循环上）；分批 ``IN`` 单源在
        ``CacheRepo.cache_get_many``。预载后单写者下本 run 期间无第三方
        写入，漏读不存在；run 内自写经 ``_written`` 续命。只能在 loop
        线程调（conn 线程亲和）。
        """
        full = [self._full(k) for k in dict.fromkeys(seg_keys)]
        cut = len(self._prefix) + 1
        self._pre = {k[cut:]: v for k, v in self._store.cache_get_many(full).items()}

    def __contains__(self, seg_key: object) -> bool:
        """存在性探测（不 bump hit_count——命中计数只在 ``__getitem__``）。"""
        if not isinstance(seg_key, str):
            return False
        if seg_key in self._pending or seg_key in self._written:
            return True
        if self._pre is not None:
            return seg_key in self._pre
        return self._store.cache_contains(self._full(seg_key))

    def __getitem__(self, seg_key: str) -> str:
        """读穿透：pending/written → 预载表/表（命中记 hit_count）。"""
        hit = self._pending.get(seg_key)
        if hit is None:
            hit = self._written.get(seg_key)
        if hit is not None:
            self.hits += 1
            return hit
        if self._pre is not None:
            if seg_key not in self._pre:
                raise KeyError(seg_key)
            self._count_hit(seg_key)
            self.hits += 1
            return self._pre[seg_key]
        hit = self._store.cache_get(self._full(seg_key))
        if hit is None:
            raise KeyError(seg_key)
        self.hits += 1
        return hit

    def _count_hit(self, seg_key: str) -> None:
        """预载命中的 ``hit_count`` 记账——``CacheRepo.count_hit`` 公共面。

        ``Store.__getattr__`` repo 透传到 ``CacheRepo.count_hit``——同一
        聚合桶（``store._cache_hits``）+ 同一 ``_CACHE_HIT_FLUSH`` 兜底
        落盘阈值，与逐键 ``cache_get`` 命中记账口径一致（无 SELECT 开销）。
        """
        self._store.count_hit(self._full(seg_key))

    def __setitem__(self, seg_key: str, translation: str) -> None:
        """写进 pending 缓冲（drain 前对同 key 读可见）。"""
        self._pending[seg_key] = translation

    def __delitem__(self, seg_key: str) -> None:
        """毒条目摘除（``_cache_hit`` 的 ``del self.cache[key]``）：内存面 + 库行同清。

        此前类上无 ``__delitem__``——``del`` 直接 TypeError，毒条目逃逸成
        worker crash-skip 而非自愈重翻。DELETE 只能 loop 线程跑（conn 亲和）。
        """
        self._pending.pop(seg_key, None)
        self._written.pop(seg_key, None)
        if self._pre is not None:
            self._pre.pop(seg_key, None)
        self._store.cache_delete(self._full(seg_key))

    def __len__(self) -> int:
        """待写缓冲长度。"""
        return len(self._pending)

    def drain(self) -> list[tuple[str, str, str, str]]:
        """取走待写缓存项 → ``[(key, translation, model, lang)]``。"""
        out = [
            (self._full(k), v, self._model, self._lang)
            for k, v in self._pending.items()
        ]
        self._written.update(self._pending)
        self._pending.clear()
        return out


def _repend_puts(cache: SegmentCache, puts: list[tuple[str, str, str, str]]) -> None:
    """``drain()`` 已取走但落盘失败 → 回挂 pending 等下轮 flush 重投。

    drain 元组是全键（``{prefix}:{seg_key}``）——剥前缀还原 seg_key 走
    ``__setitem__`` 口径回挂；``_written`` 内读副本留着无碍（重投写库
    幂等）。回挂本是 ``SegmentCache`` 接口义务（类无公共 repend 面），
    本函数是就地实现。
    """
    cut = len(cache._prefix) + 1  # noqa: SLF001 -- 回挂须剥全键前缀（类无公共面）
    for key, translation, _model, _lang in puts:
        cache[key[cut:]] = translation
