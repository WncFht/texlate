"""pipeline Translator 协议 + 网关适配域（自 ``pipeline`` 出叶）。

``Translator`` 是协议：真路径 = ``GatewayTranslator``（ChatClient + prompts），
mock 路径 = ``.mock.MockTranslator``（占位译文供 E2E/bench，不触网、确定性）。
``_strip_json_fence``/``_C0_RX`` 是模型输出清洗两件套。
"""

from __future__ import annotations

import re
from typing import Protocol

from texlate.textutil import JSON_FENCE_RX
from texlate.xlat.client import (
    ChatClient,
    ChatError,
    ChatOptions,
    LengthTruncatedError,
)
from texlate.xlat.pipeline.types import LENGTH_RETRY_MAX_TOKENS
from texlate.xlat.retry import RetryPolicy, call_with_backoff

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
    """`ChatClient` 的 Translator 适配：HTTP 退避 + length 截断放大重试。"""

    def __init__(
        self,
        client: ChatClient,
        model: str,
        *,
        policy: RetryPolicy | None = None,
    ) -> None:
        """绑定 client+model；`policy` 覆盖默认 HTTP 退避参数。"""
        self.client = client
        self.model = model
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

        return await call_with_backoff(_go, policy=self.policy)

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
