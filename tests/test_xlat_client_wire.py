r"""``ChatClient`` 线路层离线测试——``httpx.MockTransport`` 全 fake，不触真网关。

覆盖 test_xlat_client 之外的 ~350 行线路面：``chat``/``chat_stream``/
``list_models``/``panel_models``/``probe_model``/``discover_free_models``
的请求构造、响应解析、错误分类与免费集发现流水线。

seam 是既有的 ``http`` 构造参数（外部 client 注入、不自持）——
``ChatClient(base_url, key, http=httpx.AsyncClient(transport=MockTransport))``。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from texlate.xlat import client as cl

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

BASE = "http://127.0.0.1:3003"
KEY = "test-key-123"
_MSGS = [{"role": "user", "content": "hello"}]

_REQS: list[httpx.Request] = []


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    base_url: str = BASE,
    api_key: str = KEY,
) -> cl.ChatClient:
    """MockTransport 注入的 ChatClient（_own=False，aclose 不关外部 client）。"""
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return cl.ChatClient(base_url, api_key, http=http)


def _recording(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[[httpx.Request], httpx.Response]:
    """包一层把请求录进 _REQS（请求体/头断言用）。"""

    def wrapped(req: httpx.Request) -> httpx.Response:
        _REQS.append(req)
        return handler(req)

    return wrapped


def _chat_payload(
    content: str = "你好世界",
    *,
    finish: str = "stop",
    model: str = "m1",
    reasoning: str = "",
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """OpenAI chat.completion 响应体合成。"""
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning:
        msg["reasoning_content"] = reasoning
    return {
        "model": model,
        "choices": [{"message": msg, "finish_reason": finish}],
        "usage": usage or {"prompt_tokens": 11, "completion_tokens": 7},
    }


def _json(payload: object, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, json=payload, headers=httpx.Headers(headers))


@pytest.fixture(autouse=True)
def _clear_reqs() -> Iterator[None]:
    _REQS.clear()
    yield
    _REQS.clear()


# ---------------------------------------------------------------- chat


class TestChat:
    def test_success_shape(self) -> None:
        c = _client(
            _recording(
                lambda _r: _json(
                    _chat_payload(
                        usage={
                            "prompt_tokens": 11,
                            "completion_tokens": 7,
                            "prompt_tokens_details": {"cached_tokens": 5},
                        }
                    )
                )
            )
        )
        r = asyncio.run(c.chat("m1", _MSGS, options=cl.ChatOptions(max_tokens=99)))
        assert r.content == "你好世界"
        assert r.finish_reason == "stop"
        assert r.model == "m1"
        assert r.usage.prompt_tokens == 11  # noqa: PLR2004
        assert r.usage.cached_tokens == 5  # noqa: PLR2004
        assert r.latency_s >= 0

        req = _REQS[0]
        assert req.url.path == "/v1/chat/completions"
        assert req.headers["authorization"] == f"Bearer {KEY}"
        body = json.loads(req.content)
        assert body == {
            "model": "m1",
            "messages": _MSGS,
            "max_tokens": 99,
        }

    def test_body_none_fields_omitted(self) -> None:
        """ChatOptions 的 None 字段不落盘；extra 合并进顶层。"""
        c = _client(_recording(lambda _r: _json(_chat_payload())))
        asyncio.run(
            c.chat(
                "m1",
                _MSGS,
                options=cl.ChatOptions(
                    temperature=0.2,
                    response_format={"type": "json_object"},
                    extra={"stream_options": {"include_usage": True}},
                ),
            )
        )
        body = json.loads(_REQS[0].content)
        assert body["temperature"] == 0.2  # noqa: PLR2004
        assert body["response_format"] == {"type": "json_object"}
        assert body["stream_options"] == {"include_usage": True}
        assert "max_tokens" not in body
        assert "stream" not in body  # 非流式不写 stream 键

    def test_error_status_classified(self) -> None:
        cases = {
            401: cl.AuthError,
            402: cl.BillingError,
            404: cl.EndpointNotFoundError,
            429: cl.RetryableHTTPError,
            500: cl.RetryableHTTPError,
            400: cl.ClientRejectedError,
        }
        for status, exc_t in cases.items():
            c = _client(lambda _r, s=status: _json({"error": "x"}, status=s))
            with pytest.raises(exc_t):
                asyncio.run(c.chat("m1", _MSGS))

    def test_429_retry_after_end_to_end(self) -> None:
        body = {"error": {"message": "slow down", "retry_after": 16}}
        c = _client(lambda _r: _json(body, status=429))
        with pytest.raises(cl.RetryableHTTPError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert ei.value.retry_after == 16.0  # noqa: PLR2004
        assert ei.value.status == 429  # noqa: PLR2004

    def test_transport_error_retryable(self) -> None:
        def boom(_r: httpx.Request) -> httpx.Response:
            msg = "refused"
            raise httpx.ConnectError(msg)

        c = _client(boom)
        with pytest.raises(cl.RetryableHTTPError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert ei.value.status == -1
        assert "transport error" in str(ei.value)

    def test_non_json_200(self) -> None:
        c = _client(lambda _r: httpx.Response(200, text="<html>oops</html>"))
        with pytest.raises(cl.ChatError, match="non-JSON"):
            asyncio.run(c.chat("m1", _MSGS))

    def test_no_choices(self) -> None:
        c = _client(lambda _r: _json({"choices": []}))
        with pytest.raises(cl.ChatError, match="no choices"):
            asyncio.run(c.chat("m1", _MSGS))

    def test_length_truncated_with_partial(self) -> None:
        c = _client(lambda _r: _json(_chat_payload("半截译文", finish="length")))
        with pytest.raises(cl.LengthTruncatedError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert ei.value.partial_content == "半截译文"
        assert ei.value.retryable

    def test_length_truncated_empty(self) -> None:
        c = _client(lambda _r: _json(_chat_payload("", finish="length")))
        with pytest.raises(cl.LengthTruncatedError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert ei.value.partial_content == ""

    def test_empty_content(self) -> None:
        c = _client(lambda _r: _json(_chat_payload("   ")))
        with pytest.raises(cl.EmptyContentError):
            asyncio.run(c.chat("m1", _MSGS))

    def test_reasoning_field(self) -> None:
        c = _client(lambda _r: _json(_chat_payload("正文", reasoning="思考链")))
        r = asyncio.run(c.chat("m1", _MSGS))
        assert r.content == "正文"
        assert r.reasoning == "思考链"


# ---------------------------------------------------------------- anthropic 方言


class TestAnthropicDialect:
    def test_messages_endpoint_and_shape(self) -> None:
        payload = {
            "model": "claude-x",
            "type": "message",
            "stop_reason": "end_turn",
            "content": [
                {"type": "thinking", "thinking": "想"},
                {"type": "text", "text": "译"},
            ],
            "usage": {
                "input_tokens": 9,
                "output_tokens": 4,
                "cache_read_input_tokens": 3,
            },
        }
        c = _client(
            _recording(lambda _r: _json(payload)),
            base_url="https://api.anthropic.com",
        )
        msgs = [
            {"role": "system", "content": "sys prompt"},
            {"role": "user", "content": "hi"},
        ]
        r = asyncio.run(c.chat("claude-x", msgs))

        req = _REQS[0]
        assert req.url.path == "/v1/messages"
        assert req.headers["x-api-key"] == KEY
        assert req.headers["anthropic-version"] == "2023-06-01"
        assert "authorization" not in req.headers

        body = json.loads(req.content)
        assert body["system"] == "sys prompt"  # system 抽顶层
        assert [m["role"] for m in body["messages"]] == ["user"]
        assert body["max_tokens"] == cl.REASONING_MIN_MAX_TOKENS  # 默认预算

        assert r.content == "译"
        assert r.reasoning == "想"
        assert r.usage.prompt_tokens == 9  # noqa: PLR2004
        assert r.usage.cached_tokens == 3  # noqa: PLR2004

    def test_error_payload(self) -> None:
        c = _client(
            lambda _r: _json(
                {"type": "error", "error": {"type": "overloaded", "message": "x"}}
            ),
            base_url="https://api.anthropic.com",
        )
        with pytest.raises(cl.ChatError, match="overloaded"):
            asyncio.run(c.chat("m", _MSGS))

    def test_max_tokens_stop(self) -> None:
        c = _client(
            lambda _r: _json(
                {
                    "type": "message",
                    "stop_reason": "max_tokens",
                    "content": [{"type": "text", "text": "半"}],
                }
            ),
            base_url="https://api.anthropic.com",
        )
        with pytest.raises(cl.LengthTruncatedError) as ei:
            asyncio.run(c.chat("m", _MSGS))
        assert ei.value.partial_content == "半"


# ---------------------------------------------------------------- chat_stream


class TestChatStream:
    def test_sse_event_sequence(self) -> None:
        sse = (
            b'data: {"choices":[{"delta":{"reasoning_content":"\xe6\x80\x9d"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"\xe4\xbd\xa0"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"\xe5\xa5\xbd"}}]}\n\n'
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            b"data: [DONE]\n\n"
        )
        c = _client(_recording(lambda _r: httpx.Response(200, content=sse)))

        async def collect() -> list[cl.StreamEvent]:
            return [ev async for ev in c.chat_stream("m1", _MSGS)]

        events = asyncio.run(collect())
        kinds = [ev.kind for ev in events]
        assert kinds == ["reasoning", "content", "content", "done", "done"]
        assert events[1].delta == "你"
        assert events[3].finish_reason == "stop"

        body = json.loads(_REQS[0].content)
        assert body["stream"] is True

    def test_bad_lines_skipped(self) -> None:
        sse = (
            b": comment\n"
            b"data: {not json}\n"
            b'data: {"choices":[{"delta":{"content":"x"}}]}\n\n'
            b"data: [DONE]\n\n"
        )
        c = _client(lambda _r: httpx.Response(200, content=sse))

        async def collect() -> list[cl.StreamEvent]:
            return [ev async for ev in c.chat_stream("m", _MSGS)]

        kinds = [ev.kind for ev in asyncio.run(collect())]
        assert kinds == ["content", "done"]

    def test_stream_error_status(self) -> None:
        c = _client(lambda _r: _json({"error": "x"}, status=503))

        async def collect() -> list[cl.StreamEvent]:
            return [ev async for ev in c.chat_stream("m", _MSGS)]

        with pytest.raises(cl.RetryableHTTPError):
            asyncio.run(collect())


# ---------------------------------------------------------------- models / panel


class TestModelEndpoints:
    def test_list_models(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            assert req.url.path == "/v1/models"
            assert req.method == "GET"
            return _json({"data": [{"id": "a"}, {"id": "b"}, {"noid": 1}]})

        c = _client(handler)
        assert asyncio.run(c.list_models()) == ["a", "b"]

    def test_list_models_error(self) -> None:
        c = _client(lambda _r: _json({"e": 1}, status=401))
        with pytest.raises(cl.AuthError):
            asyncio.run(c.list_models())

    def test_panel_models_dict_and_list(self) -> None:
        for payload in ({"models": [{"uid": "x"}]}, [{"uid": "x"}]):
            c = _client(lambda _r, p=payload: _json(p))
            out = asyncio.run(c.panel_models())
            assert out == [{"uid": "x"}]


# ---------------------------------------------------------------- probe / discover


def _panel_entry(uid: str, **kw: object) -> dict[str, Any]:
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


class TestProbeModel:
    def test_probe_ok(self) -> None:
        c = _client(_recording(lambda _r: _json(_chat_payload("OK"))))
        fm = asyncio.run(c.probe_model("m1"))
        assert fm.probe_ok
        assert fm.probe_error == ""
        assert fm.probe_latency_s >= 0
        body = json.loads(_REQS[0].content)
        assert body["model"] == "m1"
        assert body["max_tokens"] == cl.PROBE_MAX_TOKENS

    def test_probe_http_error(self) -> None:
        c = _client(lambda _r: _json({"e": 1}, status=429))
        fm = asyncio.run(c.probe_model("m1"))
        assert not fm.probe_ok
        assert fm.probe_error == "HTTP 429"

    def test_probe_empty_content(self) -> None:
        c = _client(lambda _r: _json(_chat_payload("")))
        fm = asyncio.run(c.probe_model("m1"))
        assert not fm.probe_ok
        assert "empty" in fm.probe_error

    def test_probe_never_raises(self) -> None:
        def boom(_r: httpx.Request) -> httpx.Response:
            msg = "down"
            raise httpx.ConnectError(msg)

        c = _client(boom)
        fm = asyncio.run(c.probe_model("m1"))
        assert not fm.probe_ok
        assert fm.probe_error  # 异常文本进 error，不抛出


class TestDiscoverFreeModels:
    def _gateway(
        self, probe_fail: frozenset[str] = frozenset()
    ) -> Callable[[httpx.Request], httpx.Response]:
        panel = [
            _panel_entry("free-ok"),
            _panel_entry("free-dead"),
            _panel_entry("disabled", disabled=True),
            _panel_entry("inactive", promo={"active": False}),
            _panel_entry("paid", cost_tier="paid"),
            _panel_entry("not-in-v1"),
        ]

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/panel/api/models":
                return _json({"models": panel})
            if req.url.path == "/v1/models":
                return _json(
                    {
                        "data": [
                            {"id": u}
                            for u in (
                                "free-ok",
                                "free-dead",
                                "disabled",
                                "inactive",
                                "paid",
                            )
                        ]
                    }
                )
            if req.url.path == "/v1/chat/completions":
                uid = json.loads(req.content)["model"]
                if uid in probe_fail:
                    return _json({"e": 1}, status=500)
                return _json(_chat_payload("OK"))
            return httpx.Response(404)

        return handler

    def test_filter_intersection_and_probe(self) -> None:
        c = _client(_recording(self._gateway(probe_fail=frozenset({"free-dead"}))))
        found = asyncio.run(c.discover_free_models())
        by_uid = {m.uid: m for m in found}

        # 交集：free + promo.active + 未 disabled + ∈/v1/models
        assert set(by_uid) == {"free-ok", "free-dead"}
        assert by_uid["free-ok"].probe_ok
        assert by_uid["free-ok"].probe_error == ""
        assert not by_uid["free-dead"].probe_ok
        assert by_uid["free-dead"].probe_error == "HTTP 500"
        # panel 元数据搬进 FreeModel
        assert by_uid["free-ok"].promo_end == "2026-10-01"
        assert by_uid["free-ok"].context_tokens == 131072  # noqa: PLR2004
        assert by_uid["free-ok"].supports_thinking

        # 探活只对候选发 POST
        probed = {
            json.loads(r.content)["model"]
            for r in _REQS
            if r.url.path == "/v1/chat/completions"
        }
        assert probed == {"free-ok", "free-dead"}

    def test_v1_models_down_degrades(self) -> None:
        """/v1/models 挂 → 退化为只信 panel 过滤（不挡发现路）。"""

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/panel/api/models":
                return _json({"models": [_panel_entry("only-panel")]})
            if req.url.path == "/v1/models":
                return _json({"e": 1}, status=503)
            return _json(_chat_payload("OK"))

        c = _client(handler)
        found = asyncio.run(c.discover_free_models())
        assert [m.uid for m in found] == ["only-panel"]
        assert found[0].probe_ok

    def test_no_probe_mode(self) -> None:
        posts = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal posts
            if req.method == "POST":
                posts += 1
            if req.url.path == "/panel/api/models":
                return _json({"models": [_panel_entry("a")]})
            return _json({"data": [{"id": "a"}]})

        c = _client(handler)
        found = asyncio.run(c.discover_free_models(probe=False))
        assert [m.uid for m in found] == ["a"]
        assert posts == 0

    def test_panel_error_propagates(self) -> None:
        c = _client(lambda _r: _json({"e": 1}, status=401))
        with pytest.raises(cl.AuthError):
            asyncio.run(c.discover_free_models())


# ---------------------------------------------------------------- 生命周期


class TestOwnership:
    def test_external_http_not_closed(self) -> None:
        http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: _json({})))
        c = cl.ChatClient(BASE, KEY, http=http)
        asyncio.run(c.aclose())
        assert not http.is_closed  # 外部 client 不自持

    def test_owned_http_closed(self) -> None:
        c = cl.ChatClient(BASE, KEY)
        asyncio.run(c.aclose())
        assert c._http.is_closed  # noqa: SLF001 -- 自持 client 确已关闭

    def test_async_with(self) -> None:
        async def go() -> cl.ChatClient:
            async with cl.ChatClient(BASE, KEY) as c:
                pass
            return c

        c = asyncio.run(go())
        assert c._http.is_closed  # noqa: SLF001
