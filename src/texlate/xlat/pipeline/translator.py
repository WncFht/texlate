"""pipeline Translator 协议 + 网关适配域（自 ``pipeline`` 出叶）。

``Translator`` 是协议：真路径 = ``GatewayTranslator``（ChatClient + prompts），
mock 路径 = ``.mock.MockTranslator``（占位译文供 E2E/bench，不触网、确定性）。
``_strip_json_fence``/``_C0_RX`` 是模型输出清洗两件套。
"""

from __future__ import annotations

import asyncio
import re
import threading
from typing import TYPE_CHECKING, Protocol

from texlate.textutil import JSON_FENCE_RX
from texlate.xlat.client import (
    ChatClient,
    ChatError,
    ChatOptions,
    LengthTruncatedError,
)
from texlate.xlat.pipeline.types import LENGTH_RETRY_MAX_TOKENS
from texlate.xlat.retry import RetryPolicy, call_with_backoff

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

# ---------------------------------------------------------------- scope 信号量池


class _ScopePool:
    """``(running loop, scope)`` → ``asyncio.Semaphore`` 分桶池——进程级限流面。

    ``asyncio.Semaphore`` 是 loop-affine（首次阻塞 acquire 绑当时
    loop）——ephemeral loop（doc 路 ``asyncio.run``）与主 loop 的同名
    scope 必须分桶，跨 loop 复用即 "attached to a different loop"。
    桶记 ``(sem, cap, loop)``：cap 变更或 loop 对象轮换（id 复用）
    重建新桶——旧桶的在飞持有者仍 release 旧实例（acquire 返回的释放
    闭包捕获 sem 本体），旧桶归 GC。
    """

    def __init__(self) -> None:
        self._buckets: dict[
            tuple[int, str], tuple[asyncio.Semaphore, int, asyncio.AbstractEventLoop]
        ] = {}
        self._lock = threading.Lock()

    def _sem(
        self, loop: asyncio.AbstractEventLoop, scope: str, cap: int
    ) -> asyncio.Semaphore:
        key = (id(loop), scope)
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or bucket[1] != cap or bucket[2] is not loop:
                bucket = (asyncio.Semaphore(cap), cap, loop)
                self._buckets[key] = bucket
                # 顺捎摘除死 loop 桶——ephemeral 消费面（asyncio.run 临时
                # loop）的条目按 ``is_closed`` 认尸，防表无界积灰
                dead = [
                    k
                    for k, b in self._buckets.items()
                    if b[2] is not loop and b[2].is_closed()
                ]
                for k in dead:
                    del self._buckets[k]
            return bucket[0]

    async def acquire(
        self, scopes: Iterable[tuple[str, int | None]]
    ) -> Callable[[], None]:
        """按序 acquire 全部 ``(scope, cap)``（cap 空/<=0 跳过）；返回 release 闭包。

        取锁序由调用方固定（global → channel → model）——全进程同序即无
        多信号量死锁面。空 ``scopes`` 返无操作闭包。
        """
        loop = asyncio.get_running_loop()
        sems = [
            self._sem(loop, scope, int(cap)) for scope, cap in scopes if cap and cap > 0
        ]
        for sem in sems:
            await sem.acquire()

        def _release() -> None:
            for sem in sems:
                sem.release()

        return _release


#: 进程级 scope 信号量池单例——服务/渠道/模型三层并发上限的承载件；
#: 作用域名由 server.channels 侧构造（``global``/``ch:<id>``/``ch:<id>:<wire>``）
_scope_pool = _ScopePool()

# ---------------------------------------------------------------- Translator 协议


class Translator(Protocol):
    """最小编排面：给定 system+user 出译文（`[[SL]]`/`[[PL]]` 解码在阶梯侧）。"""

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """返回译文原文。"""
        ...


#: LLM 输出裸 C0 控制符（``\x09\x0a\x0d`` 合法空白保留）——剥除防 slots JSON strict
#: 拒收整批弃置、以及 C0 落进 .tex 后 compile ``invalid_char``（``non_utf8_recode``
#: 不管合法 UTF-8 控制符）。上游 BabelDOC PR #612 同坑实证。
_C0_RX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class GatewayTranslator:
    """`ChatClient` 的 Translator 适配：HTTP 退避 + length 截断放大重试 + scope 限流。

    ``channel_id`` 是路由归属性——渠道级冷却落戳/切臂归因的键，空串 =
    非渠道路径（header/env 直配）。``limits`` 是 ``(scope, cap)`` 元组
    序列（global → channel → model 定序），每次 ``translate`` 全量
    acquire——重试期持锁不放（重试仍占一个并发位）。
    """

    def __init__(
        self,
        client: ChatClient,
        model: str,
        *,
        policy: RetryPolicy | None = None,
        channel_id: str = "",
        limits: tuple[tuple[str, int | None], ...] = (),
    ) -> None:
        """绑定 client+model；`policy` 覆盖默认 HTTP 退避参数。"""
        self.client = client
        self.model = model
        self.channel_id = channel_id
        self.limits = limits
        self.policy = policy or RetryPolicy()

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """一次翻译调用（内部已含 HTTP 退避；length → 32k 放大重试一次）。"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        async def _go() -> str:
            try:
                r = await self.client.chat(
                    self.model,
                    messages,
                    options=ChatOptions(
                        temperature=temperature,
                        max_tokens=max_tokens,
                        response_format=response_format,
                    ),
                )
            except ChatError as e:
                retryable_length = (
                    e.retryable
                    and isinstance(e, LengthTruncatedError)
                    and max_tokens < LENGTH_RETRY_MAX_TOKENS
                )
                if not retryable_length:
                    raise
                r = await self.client.chat(
                    self.model,
                    messages,
                    options=ChatOptions(
                        temperature=temperature,
                        max_tokens=LENGTH_RETRY_MAX_TOKENS,
                        response_format=response_format,
                    ),
                )
            return _C0_RX.sub("", r.content)

        release = await _scope_pool.acquire(self.limits)
        try:
            return await call_with_backoff(_go, policy=self.policy)
        finally:
            release()

    async def aclose(self) -> None:
        """关自持 ``ChatClient``——须在消费侧存活 loop 内 await（幂等）。

        ``drive_pipeline`` 经 ``getattr(translator, "aclose")`` 在管线消费
        loop 内回收 httpx 池——无本件时池只能在外层新 loop 上关（连接绑死
        loop 的「foreign loop」坑）。委托 ``client.aclose``——非自持
        client（``_own=False``）在其内短路为 no-op。
        """
        await self.client.aclose()


def _strip_json_fence(raw: str) -> str:
    """剥掉整段 ``` 围栏；非围栏原文原样返回。"""
    m = JSON_FENCE_RX.match(raw)
    return m.group("body") if m else raw
