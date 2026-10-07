"""译器包装域（自 ``_common`` 出叶）：三个 ``translate()`` 鸭子型包装。

``_FallbackTranslator`` 是 N 臂失败回退链（primary 抛 ``ChatError``
→ 按臂序同参补发：``retry_model`` 同 client 换模臂 + endpoints.json
跨端点臂）；
``_PerCallTranslator`` 是 ephemeral-loop 消费面的 BYOK translator——
client 按 running loop 懒建复用（分桶/摘除/尽力收尾机制单源在
``server._ttlcache.LoopClientPool``）；``_AbortingTranslator`` 是
``_run_doc`` 的取消传导包装（``cancel_flag`` 置位 → 抛
``_common.errors._SectionAbort`` 快失败收敛）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from texlate.server._ttlcache import LoopClientPool
from texlate.server.worker._common.errors import _SectionAbort
from texlate.xlat.client import (
    AuthError,
    BillingError,
    ChatClient,
    ChatError,
    EndpointNotFoundError,
)
from texlate.xlat.pipeline import GatewayTranslator

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from texlate.xlat.client import UsageRecord
    from texlate.xlat.pipeline import Translator

log = logging.getLogger(__name__)


def _arm_label(tr: object) -> str:
    """``model@base_url`` 日志标签（缺 attr 的鸭子型替身降级为 ``model@?``）。"""
    client = getattr(tr, "client", None)
    return f"{getattr(tr, 'model', '?')}@{getattr(client, 'base_url', '?')}"


def _arm_could_help(frm: object, to: object, e: ChatError) -> bool:
    """本臂错 ``e``、下一臂是否有救：同 client 只看 retryable；异 client 加接 auth/billing/404。

    同 client（同端点同凭据，仅换模型）：``AuthError``/``BillingError``/
    ``EndpointNotFoundError`` 换模无救——同一 key 同一端点必同死。
    异 client（换端点换凭据）：这三个恰恰是最该换端点的错——本端点
    判死的错在异端点可能整臂翻身（key 无效/欠费/模型摘除都随槽走）。
    """
    if e.retryable:
        return True
    if getattr(frm, "client", None) is getattr(to, "client", None):
        return False
    return isinstance(e, (AuthError, BillingError, EndpointNotFoundError))


class _FallbackTranslator:
    """失败回退链：primary 抛 ``ChatError`` → 按臂序同参补发（同 client 换模臂 + 跨端点臂）。

    阶梯（``translate_with_ladder``）属 xlat 属主不在此动——本包装把
    「chunk 重试换臂」落在 HTTP 失败层：模型级故障/限流/端点级死症
    时该块的每次调用自带备选兜底。臂能不能救下一跳按
    ``_arm_could_help`` 分判（同 client 换模只接 retryable；跨 client
    加接 AuthError/BillingError/EndpointNotFoundError）。validation
    反馈驱动的阶梯内重试仍走 primary。``.client`` 暴露 primary 的
    ChatClient——``_stage_translate`` finally 的
    ``isinstance(ChatClient)→aclose`` 探测依赖它；``on_switch`` 是
    切臂事件钩（warning 归因，可 None）。
    """

    def __init__(
        self,
        primary: GatewayTranslator,
        fallbacks: list[GatewayTranslator],
        *,
        on_switch: Callable[[GatewayTranslator, GatewayTranslator, ChatError], None]
        | None = None,
    ) -> None:
        self._primary = primary
        self._fallbacks = list(fallbacks)
        self._on_switch = on_switch
        self.client = getattr(primary, "client", None)

    @property
    def clients(self) -> list[object]:
        """全臂底层 client（identity 去重保序——同 client 臂只列一次，usage_sink/aclose 接线面）。"""
        out: list[object] = []
        for tr in (self._primary, *self._fallbacks):
            c = getattr(tr, "client", None)
            if c is not None and all(c is not seen for seen in out):
                out.append(c)
        return out

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """按臂序补发：本臂失败且下一臂有救 → 切臂；末臂/无救 → 原样上抛。"""
        arms = [self._primary, *self._fallbacks]
        for idx, tr in enumerate(arms):
            try:
                return await tr.translate(
                    system=system,
                    user=user,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                )
            except ChatError as e:
                nxt = arms[idx + 1] if idx + 1 < len(arms) else None
                if nxt is None or not _arm_could_help(tr, nxt, e):
                    raise
                log.warning(
                    "fallback: %s 失败（%s）→ %s",
                    _arm_label(tr),
                    e,
                    _arm_label(nxt),
                )
                if self._on_switch is not None:
                    self._on_switch(tr, nxt, e)
        msg = "unreachable: 末臂 raise 恒退出循环"
        raise ChatError(msg)  # pragma: no cover -- 循环恒经 return/raise 退出


class _PerCallTranslator:
    """ephemeral-loop 消费面的 BYOK translator：client 懒绑**运行中 loop**。

    ``LlmFixer._drive``（llm_hook）与 ``export_document``（doc 路）都把
    消费跑进**自有 ``asyncio.run`` 临时 loop**——共享 ``ChatClient`` 的
    httpx 池跨 loop 复用会炸（"attached to a different loop"，
    ``llm_hook.py`` docstring 明示的坑），aclose 也回不去已关 loop
    （RuntimeError → 连接 FD 泄漏）。原 per-call 即开即关每调用一对
    connect/teardown（TLS 握手 ×N 调用）；改按 ``running loop`` 懒建
    复用——同 loop 内整段共享一条连接池，消费侧收尾经 ``aclose()``
    （须在**该 loop 存活时**于其内 await，export/common.py 的 run 包装
    finally 即此钩）。死 loop 条目在下次 ``_client()`` 按
    ``loop.is_closed`` 摘除（回不了死 loop 关，FD 归 GC——泄漏上界
    同原形态）。``usage_sink`` 仍接同一 meter；``retry_model`` 备选与
    primary 同 loop client（同 endpoint+key）。分桶/摘除/尽力收尾
    机制单源在 ``server._ttlcache.LoopClientPool``（routers 同款池）。
    """

    def __init__(  # noqa: PLR0913 -- BYOK 凭证面平铺（url/key/model/dialect + retry + sink）
        self,
        base_url: str,
        api_key: str,
        model: str,
        sink: Callable[[UsageRecord], None],
        *,
        retry_model: str = "",
        dialect: str = "auto",
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._retry_model = retry_model
        self._dialect = dialect
        self._sink = sink
        self._pool: LoopClientPool[ChatClient] = LoopClientPool(
            self._make_client, label="per-call"
        )

    @property
    def clients(self) -> list[ChatClient]:
        """存活 loop 的 client 面——``_translator_clients`` 接线用（死 loop 不可关不列）。"""
        return self._pool.live()

    def _make_client(self) -> ChatClient:
        """当前 running loop 桶的 client 构造（``LoopClientPool`` 回调）。"""
        return ChatClient(
            self._base_url,
            self._api_key,
            usage_sink=self._sink,
            dialect=self._dialect,
        )

    def _client(self) -> ChatClient:
        """本 running loop 的懒建 client（池顺带摘除死 loop 条目）。"""
        return self._pool.get()

    async def aclose(self) -> None:
        """关**本 running loop** 的 client——消费侧 loop 收尾钩（export run 包装 finally）。"""
        await self._pool.aclose_current()

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        client = self._client()
        primary = GatewayTranslator(client, self._model)
        try:
            return await primary.translate(
                system=system,
                user=user,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
        except ChatError as e:
            if not self._retry_model or not e.retryable:
                raise
            log.warning(
                "retry_model: primary %s 失败（%s）→ 备选 %s",
                self._model,
                e,
                self._retry_model,
            )
        return await GatewayTranslator(client, self._retry_model).translate(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )


class _AbortingTranslator:
    """``_run_doc`` 的取消传导包装：``cancel_flag`` 置位 → ``translate()`` 抛 ``_SectionAbort``。

    ``export_document`` 在 ``to_thread`` 内开 ephemeral loop——外层
    ``task.cancel()`` 递不进去；把旗标折成调用面快失败是唯一收敛通道。
    ``__getattr__`` 透传 ``.client``/``.clients``——``_translator_clients``
    的 aclose/usage_sink 接线面不受影响。
    """

    def __init__(self, inner: Translator, flag: threading.Event) -> None:
        self._inner = inner
        self._flag = flag

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        if self._flag.is_set():
            msg = "task cancelled"
            raise _SectionAbort(msg)
        return await self._inner.translate(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
