"""``ChatClient`` MockTransport 测试公共骨架——``test_xlat_client*``/``fuzz_xlat_client`` 簇共用。

``_workerkit``/``_fixloopkit``/``_fuzzkit`` 先例同法：逐文件复刻的同构
脚手架归此一处。各文件默认值曾有漂移（content ``"OK"``/``"你好世界"``/
``"译文"``、usage ``11/7`` vs ``3/2``、promo_end ``2026-10-01`` vs
``"2026-10-16"``）——**调用侧按需显式钉值**，本 kit 的默认形只是其中一
族（wire 系），不是跨文件契约。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from texlate.xlat import client as cl

if TYPE_CHECKING:
    from collections.abc import Callable


def mock_client(  # noqa: PLR0913 -- 透传 ChatClient 构造面，kwarg 名即接口
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    base_url: str,
    api_key: str,
    usage_sink: Callable[[cl.UsageRecord], None] | None = None,
    dialect: str | None = None,
    stream_fallback: bool | None = None,
) -> cl.ChatClient:
    """MockTransport 注入的 ChatClient（外部 http client，``_own=False``）。"""
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return cl.ChatClient(
        base_url,
        api_key,
        http=http,
        usage_sink=usage_sink,
        dialect=dialect,
        stream_fallback=stream_fallback,
    )


def recording(
    handler: Callable[[httpx.Request], httpx.Response],
    reqs: list[httpx.Request],
) -> Callable[[httpx.Request], httpx.Response]:
    """包一层把请求录进 ``reqs``（请求体/头断言用）。"""

    def wrapped(req: httpx.Request) -> httpx.Response:
        reqs.append(req)
        return handler(req)

    return wrapped


def chat_payload(
    content: str = "你好世界",
    *,
    finish: str = "stop",
    model: str = "m1",
    reasoning: str = "",
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """OpenAI ``chat.completion`` 响应体合成（reasoning/usage 可选挂载）。"""
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning:
        msg["reasoning_content"] = reasoning
    return {
        "model": model,
        "choices": [{"message": msg, "finish_reason": finish}],
        "usage": usage or {"prompt_tokens": 11, "completion_tokens": 7},
    }


def json_resp(payload: object, status: int = 200, **headers: str) -> httpx.Response:
    """JSON ``httpx.Response`` 合成——``**headers`` 逐键进响应头。"""
    return httpx.Response(status, json=payload, headers=httpx.Headers(headers))


def panel_entry(uid: object, **kw: object) -> dict[str, Any]:
    """``/panel/api/models`` 条目合成——``**kw`` 覆盖/附加任意字段。

    ``uid`` 刻意不收 ``str``——fuzz/对抗面会喂 ``5``/``["x"]`` 等非 str 成员。
    """
    base: dict[str, Any] = {
        "uid": uid,
        "cost_tier": "free",
        "promo": {"active": True, "end_date": "2026-10-01"},
        "context_tokens": 131072,
        "max_output_tokens": 8192,
        "supports_thinking": True,
    }
    base.update(kw)
    return base


def connect_error(msg: str) -> Callable[[httpx.Request], httpx.Response]:
    """恒 ``httpx.ConnectError`` 的 boom handler（传输错误族钉件）。"""

    def boom(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(msg)

    return boom


async def drain(
    c: cl.ChatClient, model: str, msgs: list[dict[str, str]]
) -> list[cl.StreamEvent]:
    """``chat_stream`` 全量收集——MockTransport 下的 drain idiom 单源。"""
    return [ev async for ev in c.chat_stream(model, msgs)]
