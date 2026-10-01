"""pipeline 结果账本域（自 ``pipeline`` 出叶）：skip/直通落形 + 拦截网/auth 闸/emit 双档收账。

``_XlatLedger`` 是 ``XlatPipeline`` 的账本臂 mixin——每个 ChunkResult 走
「拦截网序列 → auth 闸入账 → state/on_result emit」的统一点列，普通
``Exception`` 记 log 续走、``BaseException`` 收 ``_FatalLedger`` 由
``_drain``/``run()`` 序章尾重抛（worker 不死 → ``queue.join()`` 不锁，E3）。

``_net_apply_fn`` 经 ``.pipeline`` 门面回取——其 ``globals()`` 晚绑定钉在
门面命名空间，tests ``setattr(pl, _intercept_*)`` 补丁照常触达账本调用点
（docs/dev/seams.md §5）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from texlate.xlat.intercept import _INTERCEPT_NETS
from texlate.xlat.pipeline import _net_apply_fn
from texlate.xlat.pipeline.types import ChunkResult

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from texlate.chunk import ChunkIn

log = logging.getLogger(__name__)


class _FatalLedger:
    """``BaseException`` 收账本——双档网的致命档归集位（替代裸 ``list`` 穿透）。

    普通 ``Exception`` 逐点 log 续走；``BaseException``（KI/SE/GE）收进本账
    绝不外泄——逃逸即杀 worker → ``queue.join()`` 死锁（E3）。消费约定：
    ``bool(fatal)`` 为「已挂」判据（worker 排空臂只摘不做），``raise_first``
    在 ``_drain`` 收敛后 / ``run()`` 序章尾统一重抛首笔。
    """

    __slots__ = ("_items",)

    def __init__(self) -> None:
        self._items: list[BaseException] = []

    def append(self, exc: BaseException) -> None:
        """收一笔致命异常（账本语义等价于旧裸 ``list.append``）。"""
        self._items.append(exc)

    def raise_first(self) -> None:
        """重抛首笔——收敛位唯一出口；空账无操作。"""
        if self._items:
            raise self._items[0]

    def __bool__(self) -> bool:
        return bool(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[BaseException]:
        return iter(self._items)


class _XlatLedger:
    """结果入账/拦截网/auth 闸 mixin（实例状态由 ``XlatPipeline.__init__`` 初始化）。"""

    # ------------------------------------------------------------ 账本

    @staticmethod
    def _skip(
        c: ChunkIn, reason: str, batch_id: str = "", *, kind: str = ""
    ) -> ChunkResult:
        """失败回退原文——不阻塞整批（docs/spec/translate.md）。``kind`` 记失败成因。"""
        return ChunkResult(
            chunk_id=c.chunk_id,
            source=c.content,
            translation=c.content,
            kind=c.kind,
            status="skipped",
            batch_id=batch_id,
            skip_reason=reason,
            error_kind=kind,
        )

    @staticmethod
    def _passthrough_result(
        c: ChunkIn, *, warnings: list[str] | None = None
    ) -> ChunkResult:
        """zh≡src 直通结果——placeholder_only 与 ``[[BIB_`` 文献域共用落形。"""
        return ChunkResult(
            chunk_id=c.chunk_id,
            source=c.content,
            translation=c.content,
            kind=c.kind,
            status="ok",
            warnings=warnings or [],
        )

    def _emit(self, r: ChunkResult) -> None:
        if self.state is not None:
            self.state.record(
                r.to_record(),
                error=({"error": r.skip_reason} if r.fell_back else None),
            )
        if self.on_result is not None:
            self.on_result(r)

    @staticmethod
    def _ledger_call(
        fatal: _FatalLedger,
        r: ChunkResult,
        name: str,
        fn: Callable[[ChunkResult], None],
    ) -> None:
        """账本调用统一双档网。

        普通 ``Exception`` 记 log 续走（绝不外泄）；``BaseException``
        （KI/SE/GE）收 ``fatal`` 账本——逃逸即杀 worker → ``queue.join()``
        死锁（E3），由 ``_drain`` 收敛后重抛。
        """
        try:
            fn(r)
        except Exception:
            log.exception("%s failed for %s", name, r.chunk_id)
        except BaseException as e:
            log.exception("%s crashed fatally for %s", name, r.chunk_id)
            fatal.append(e)

    def _ledger_intercepts(self, fatal: _FatalLedger, r: ChunkResult) -> None:
        """升格拦截网注册表的统一账本序列（``_load_resumed`` 与 ``_ledger_outcome`` 共用）。"""
        for net in _INTERCEPT_NETS:
            self._ledger_call(fatal, r, f"{net.name} intercept", _net_apply_fn(net))

    def _ledger_outcome(self, fatal: _FatalLedger, r: ChunkResult) -> None:
        """拦截网 + auth 闸 + emit 的账本序列（``_route_chunks`` 与 ``_collect`` 共用；点数随 ``_INTERCEPT_NETS`` 注册表走）。"""
        self._ledger_intercepts(fatal, r)
        self._ledger_call(fatal, r, "auth_gate.record", self.auth_gate.record)
        self._ledger_call(fatal, r, "emit", self._emit)

    def _collect(
        self,
        results: list[ChunkResult],
        done_map: dict[str, ChunkResult],
        fatal: _FatalLedger,
    ) -> None:
        """结果入账 + 落盘（worker 与 warmup 共用）。

        state.record/on_result 抛错绝不外泄——worker 一死，队列里剩余 item
        永远等不到 task_done，``queue.join()`` 挂死；warmup 侧则直接炸掉整 run。
        ``BaseException`` 族（KI/SE）同此理：逃逸即杀 worker → join 死锁，
        逐调用收进 ``fatal`` 由 ``_drain`` 收敛后重抛（E3 同族第二注入点）。
        """
        for r in results:
            done_map[r.chunk_id] = r
            self._ledger_outcome(fatal, r)
