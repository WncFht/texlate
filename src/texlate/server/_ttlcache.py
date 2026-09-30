"""server 域共享运行时小件——TTL 缓存 + 按 running loop 分桶的 client 池。

``_TtlCache``：routers 只读代理面（discover/refs）共用的进程内缓存——
弱新鲜度 + 容量有界 LRU 头出（原 discover/refs 逐字节双份，单源于此）。

``LoopClientPool``：httpx ``AsyncClient`` 与 xlat ``ChatClient`` 共撞的
同一坑——连接池绑创建时 running loop，跨环复用炸 "attached to a
different loop"，aclose 也回不去已关 loop（RuntimeError）。按环分桶
懒建 + 死环摘除收敛；键用 loop 对象本体强引用（``id()`` 键在环销毁后
会被新环复用地址，捞到死环绑定的 client 每请求炸 ``RuntimeError``——
非 ``httpx.HTTPError`` 类，归一错误面翻不出 502 直 500）。死环条目
只摘不关——FD 归 GC 是各调用方既定接受形态（原 discover/refs/
``_PerCallTranslator`` 三份同构，单源于此）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)


class _TtlCache[T]:
    """key → (expires_monotonic, value)，容量有界 LRU 头出。"""

    def __init__(self, ttl: float, max_entries: int) -> None:
        """``ttl`` 秒；超 ``max_entries`` 逐最旧键。"""
        self.ttl = ttl
        self.max_entries = max_entries
        self._d: OrderedDict[str, tuple[float, T]] = OrderedDict()

    def get(self, key: str) -> T | None:
        """命中返值；缺席/过期返 ``None``（顺手摘除）。"""
        hit = self._d.get(key)
        if hit is None:
            return None
        exp, val = hit
        if exp < time.monotonic():
            self._d.pop(key, None)
            return None
        self._d.move_to_end(key)
        return val

    def put(self, key: str, val: T) -> None:
        """写入 + LRU 排序 + 容量逐出。"""
        self._d[key] = (time.monotonic() + self.ttl, val)
        self._d.move_to_end(key)
        while len(self._d) > self.max_entries:
            self._d.popitem(last=False)


class _Aclosable(Protocol):
    """``aclose()`` 鸭形面——``httpx.AsyncClient``/``ChatClient`` 同签名。"""

    async def aclose(self) -> None: ...


class LoopClientPool[C: _Aclosable]:
    """按 running loop 分桶的 client 池（懒建 + 死环摘除 + 尽力收尾）。

    ``factory`` 每桶一调、在消费 loop 上建 client（重依赖可在其内惰载）；
    ``label`` 只进收尾失败 debug 日志。``live``/``aclose_current`` 给
    per-call 消费面（ephemeral loop 用后即关本环桶）；``aclose_all``
    给进程级 lifespan 收尾钩。
    """

    def __init__(self, factory: Callable[[], C], *, label: str) -> None:
        """存构造回调与日志前缀——``get()`` 懒建桶的输入面。"""
        self._factory = factory
        self._label = label
        self._clients: dict[asyncio.AbstractEventLoop, C] = {}

    def get(self) -> C:
        """本 running loop 的懒建 client（顺带摘除死环条目）。"""
        loop = asyncio.get_running_loop()
        for dead in [lp for lp in self._clients if lp.is_closed()]:
            del self._clients[dead]
        client = self._clients.get(loop)
        if client is None:
            client = self._factory()
            self._clients[loop] = client
        return client

    def live(self) -> list[C]:
        """存活 loop 的 client 面（死环不可关不列）。"""
        return [c for lp, c in self._clients.items() if not lp.is_closed()]

    async def aclose_current(self) -> None:
        """关**本 running loop** 的 client——ephemeral-loop 消费面收尾钩。"""
        await self._aclose_one(self._clients.pop(asyncio.get_running_loop(), None))

    async def aclose_all(self) -> None:
        """尽力关全部桶——app lifespan 收尾用（单条失败不挡其余）。"""
        while self._clients:
            await self._aclose_one(self._clients.pop(next(iter(self._clients))))

    async def _aclose_one(self, client: C | None) -> None:
        """单条 aclose 尽力而为——坏/半关连接不挡其余桶、不上浮。"""
        if client is None:
            return
        try:
            await client.aclose()
        except Exception as e:  # noqa: BLE001 -- 收尾尽力而为
            log.debug(
                "%s client aclose failed: %s: %s",
                self._label,
                type(e).__name__,
                e,
            )
