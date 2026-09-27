r"""``ChatClient`` 线路层离线测试——``httpx.MockTransport`` 全 fake，不触真网关。

覆盖 test_xlat_client 之外的线路面：``chat``/``chat_stream``/
``list_models``/``panel_models``/``probe_model``/``discover_free_models``
的请求构造、响应解析、错误分类与免费集发现流水线；anthropic 与
responses 方言全线套件（请求组装/响应解析/错误归约/SSE/探活）同归此。

seam 是既有的 ``http`` 构造参数（外部 client 注入、不自持）——
``ChatClient(base_url, key, http=httpx.AsyncClient(transport=MockTransport))``。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from _xlatkit import (
    chat_payload,
    connect_error,
    drain,
    json_resp,
    mock_client,
    panel_entry,
    recording,
)

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
    *,
    dialect: str | None = None,
    stream_fallback: bool | None = None,
) -> cl.ChatClient:
    """本文件默认 BASE/KEY 的 mock client（外部 http，aclose 不关）。"""
    return mock_client(
        handler,
        base_url=base_url,
        api_key=api_key,
        dialect=dialect,
        stream_fallback=stream_fallback,
    )


def _recording(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[[httpx.Request], httpx.Response]:
    """包一层把请求录进 _REQS（请求体/头断言用）。"""
    return recording(handler, _REQS)


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
                lambda _r: json_resp(
                    chat_payload(
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
        c = _client(_recording(lambda _r: json_resp(chat_payload())))
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
            c = _client(lambda _r, s=status: json_resp({"error": "x"}, status=s))
            with pytest.raises(exc_t):
                asyncio.run(c.chat("m1", _MSGS))

    def test_429_retry_after_end_to_end(self) -> None:
        body = {"error": {"message": "slow down", "retry_after": 16}}
        c = _client(lambda _r: json_resp(body, status=429))
        with pytest.raises(cl.RetryableHTTPError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert ei.value.retry_after == 16.0  # noqa: PLR2004
        assert ei.value.status == 429  # noqa: PLR2004

    def test_transport_error_retryable(self) -> None:
        c = _client(connect_error("refused"))
        with pytest.raises(cl.RetryableHTTPError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert ei.value.status == -1
        assert "transport error" in str(ei.value)

    def test_non_json_200(self) -> None:
        c = _client(lambda _r: httpx.Response(200, text="<html>oops</html>"))
        with pytest.raises(cl.ChatError, match="non-JSON"):
            asyncio.run(c.chat("m1", _MSGS))

    def test_no_choices(self) -> None:
        c = _client(lambda _r: json_resp({"choices": []}))
        with pytest.raises(cl.ChatError, match="no choices"):
            asyncio.run(c.chat("m1", _MSGS))

    def test_length_truncated_with_partial(self) -> None:
        c = _client(lambda _r: json_resp(chat_payload("半截译文", finish="length")))
        with pytest.raises(cl.LengthTruncatedError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert ei.value.partial_content == "半截译文"
        assert ei.value.retryable

    def test_length_truncated_empty(self) -> None:
        c = _client(lambda _r: json_resp(chat_payload("", finish="length")))
        with pytest.raises(cl.LengthTruncatedError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert ei.value.partial_content == ""

    def test_empty_content(self) -> None:
        c = _client(lambda _r: json_resp(chat_payload("   ")))
        with pytest.raises(cl.EmptyContentError):
            asyncio.run(c.chat("m1", _MSGS))

    def test_reasoning_field(self) -> None:
        c = _client(lambda _r: json_resp(chat_payload("正文", reasoning="思考链")))
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
            _recording(lambda _r: json_resp(payload)),
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
            lambda _r: json_resp(
                {"type": "error", "error": {"type": "overloaded", "message": "x"}}
            ),
            base_url="https://api.anthropic.com",
        )
        with pytest.raises(cl.ChatError, match="overloaded"):
            asyncio.run(c.chat("m", _MSGS))

    def test_max_tokens_stop(self) -> None:
        c = _client(
            lambda _r: json_resp(
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


# ---------------------------------------------------------------- responses 方言

_RESPONSES_OK = {
    "id": "resp_1",
    "status": "completed",
    "model": "m1",
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "译"}],
        }
    ],
    "usage": {
        "input_tokens": 11,
        "output_tokens": 7,
        "input_tokens_details": {"cached_tokens": 3},
    },
}


class TestResponsesDialect:
    """Responses 方言：``/v1/responses`` + instructions/input 体 + output/status 解析。

    ``dialect="responses"`` 面向 responses-only 反代等 host 识别不了的
    BYOK 端点——请求组装/响应解析/错误归约三方各有钉点。
    """

    def test_request_shape(self) -> None:
        def handler(_r: httpx.Request) -> httpx.Response:
            return json_resp(_RESPONSES_OK)

        c = _client(_recording(handler), dialect="responses")
        msgs = [
            {"role": "system", "content": "s1"},
            {"role": "system", "content": "s2"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
        ]
        asyncio.run(
            c.chat(
                "m1",
                msgs,
                options=cl.ChatOptions(
                    max_tokens=64, response_format={"type": "json_object"}
                ),
            )
        )
        req = _REQS[0]
        assert req.url.path == "/v1/responses"
        assert req.headers["authorization"] == f"Bearer {KEY}"
        body = json.loads(req.content)
        assert body["model"] == "m1"
        assert body["instructions"] == "s1\ns2"
        assert [i["role"] for i in body["input"]] == ["user", "assistant"]
        assert body["input"][0]["content"] == [{"type": "input_text", "text": "u"}]
        assert body["input"][1]["content"] == [{"type": "output_text", "text": "a"}]
        assert body["max_output_tokens"] == 64  # noqa: PLR2004
        assert body["text"] == {"format": {"type": "json_object"}}
        assert "messages" not in body
        assert "max_tokens" not in body

    def test_parse_completed(self) -> None:
        payload = {
            "status": "completed",
            "model": "m1",
            "output": [
                {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "想"}],
                },
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "译"}],
                },
            ],
            "usage": {
                "input_tokens": 11,
                "output_tokens": 7,
                "input_tokens_details": {"cached_tokens": 3},
            },
        }
        c = _client(lambda _r: json_resp(payload), dialect="responses")
        r = asyncio.run(c.chat("m1", _MSGS))
        assert r.content == "译"
        assert r.reasoning == "想"
        assert r.finish_reason == "stop"
        assert r.usage.prompt_tokens == 11  # noqa: PLR2004
        assert r.usage.completion_tokens == 7  # noqa: PLR2004
        assert r.usage.cached_tokens == 3  # noqa: PLR2004
        assert r.model == "m1"

    def test_incomplete_maps_length(self) -> None:
        """``incomplete`` + 非 filter reason → ``LengthTruncatedError`` 带 partial。"""
        payload = {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "半"}],
                }
            ],
        }
        c = _client(lambda _r: json_resp(payload), dialect="responses")
        with pytest.raises(cl.LengthTruncatedError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert ei.value.partial_content == "半"

    def test_incomplete_content_filter(self) -> None:
        payload = {
            "status": "incomplete",
            "incomplete_details": {"reason": "content_filter"},
            "output": [],
        }
        c = _client(lambda _r: json_resp(payload), dialect="responses")
        with pytest.raises(cl.ContentFilterError):
            asyncio.run(c.chat("m1", _MSGS))

    def test_refusal_block(self) -> None:
        payload = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "refusal", "refusal": "拒答"}],
                }
            ],
        }
        c = _client(lambda _r: json_resp(payload), dialect="responses")
        with pytest.raises(cl.ContentFilterError):
            asyncio.run(c.chat("m1", _MSGS))

    def test_failed_status(self) -> None:
        payload = {
            "status": "failed",
            "error": {"code": "server_error", "message": "boom"},
        }
        c = _client(lambda _r: json_resp(payload), dialect="responses")
        with pytest.raises(cl.ChatError, match="boom"):
            asyncio.run(c.chat("m1", _MSGS))

    def test_top_level_error_object(self) -> None:
        payload = {"type": "error", "error": {"code": "x", "message": "bad"}}
        c = _client(lambda _r: json_resp(payload), dialect="responses")
        with pytest.raises(cl.ChatError, match="bad"):
            asyncio.run(c.chat("m1", _MSGS))

    def test_empty_content(self) -> None:
        payload = {"status": "completed", "output": []}
        c = _client(lambda _r: json_resp(payload), dialect="responses")
        with pytest.raises(cl.EmptyContentError):
            asyncio.run(c.chat("m1", _MSGS))

    @pytest.mark.parametrize(
        "payload",
        [
            {"status": "completed", "output": "not-a-list"},
            {"status": "queued", "output": []},
            {"status": "completed", "output": [5]},
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": 5}],
                    }
                ],
            },
        ],
    )
    def test_malformed_shapes(self, payload: dict[str, Any]) -> None:
        """output 非 list / 非终态 status / 非 dict 成员 / text 非 str → Malformed。"""
        c = _client(lambda _r: json_resp(payload), dialect="responses")
        with pytest.raises(cl.MalformedResponseError):
            asyncio.run(c.chat("m1", _MSGS))

    def test_stream_events(self) -> None:
        """SSE：output_text.delta→content、reasoning_summary→reasoning、completed→done。"""
        sse = (
            b'data: {"type":"response.output_text.delta","delta":"x"}\n\n'
            b'data: {"type":"response.reasoning_summary_text.delta",'
            b'"delta":"r"}\n\n'
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        )
        c = _client(lambda _r: httpx.Response(200, content=sse), dialect="responses")

        events = asyncio.run(drain(c, "m1", _MSGS))
        assert [(e.kind, e.delta) for e in events[:2]] == [
            ("content", "x"),
            ("reasoning", "r"),
        ]
        assert events[-1].kind == "done"
        assert events[-1].finish_reason == "stop"

    def test_stream_incomplete_finish(self) -> None:
        sse = (
            b'data: {"type":"response.incomplete","response":'
            b'{"incomplete_details":{"reason":"max_output_tokens"}}}\n\n'
        )
        c = _client(lambda _r: httpx.Response(200, content=sse), dialect="responses")

        events = asyncio.run(drain(c, "m1", _MSGS))
        assert events[-1].kind == "done"
        assert events[-1].finish_reason == "length"

    def test_stream_failed_raises(self) -> None:
        sse = (
            b'data: {"type":"response.failed","response":'
            b'{"error":{"message":"die"}}}\n\n'
        )
        c = _client(lambda _r: httpx.Response(200, content=sse), dialect="responses")

        with pytest.raises(cl.ChatError, match="die"):
            asyncio.run(drain(c, "m1", _MSGS))

    def test_probe_model_uses_responses_endpoint(self) -> None:
        """探活随方言——responses client 的 ``probe_model`` 打 ``/v1/responses``。"""

        def handler(_r: httpx.Request) -> httpx.Response:
            return json_resp(_RESPONSES_OK)

        c = _client(_recording(handler), dialect="responses")
        fm = asyncio.run(c.probe_model("m1"))
        assert fm.probe_ok
        assert _REQS[0].url.path == "/v1/responses"


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

        events = asyncio.run(drain(c, "m1", _MSGS))
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

        kinds = [ev.kind for ev in asyncio.run(drain(c, "m", _MSGS))]
        assert kinds == ["content", "done"]

    def test_stream_error_status(self) -> None:
        c = _client(lambda _r: json_resp({"error": "x"}, status=503))

        with pytest.raises(cl.RetryableHTTPError):
            asyncio.run(drain(c, "m", _MSGS))


# ---------------------------------------------------------------- models / panel


class TestModelEndpoints:
    def test_list_models(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            assert req.url.path == "/v1/models"
            assert req.method == "GET"
            return json_resp({"data": [{"id": "a"}, {"id": "b"}, {"noid": 1}]})

        c = _client(handler)
        assert asyncio.run(c.list_models()) == ["a", "b"]

    def test_list_models_error(self) -> None:
        c = _client(lambda _r: json_resp({"e": 1}, status=401))
        with pytest.raises(cl.AuthError):
            asyncio.run(c.list_models())

    def test_panel_models_dict_and_list(self) -> None:
        for payload in ({"models": [{"uid": "x"}]}, [{"uid": "x"}]):
            c = _client(lambda _r, p=payload: json_resp(p))
            out = asyncio.run(c.panel_models())
            assert out == [{"uid": "x"}]


# ---------------------------------------------------------------- probe / discover


class TestProbeModel:
    def test_probe_ok(self) -> None:
        c = _client(_recording(lambda _r: json_resp(chat_payload("OK"))))
        fm = asyncio.run(c.probe_model("m1"))
        assert fm.probe_ok
        assert fm.probe_error == ""
        assert fm.probe_latency_s >= 0
        body = json.loads(_REQS[0].content)
        assert body["model"] == "m1"
        assert body["max_tokens"] == cl.PROBE_MAX_TOKENS

    def test_probe_http_error(self) -> None:
        c = _client(lambda _r: json_resp({"e": 1}, status=429))
        fm = asyncio.run(c.probe_model("m1"))
        assert not fm.probe_ok
        # probe 走 _chat_once——classify_status 口径带 body 摘要
        assert fm.probe_error.startswith("HTTP 429:")

    def test_probe_empty_content(self) -> None:
        c = _client(lambda _r: json_resp(chat_payload("")))
        fm = asyncio.run(c.probe_model("m1"))
        assert not fm.probe_ok
        assert "empty" in fm.probe_error

    def test_probe_never_raises(self) -> None:
        c = _client(connect_error("down"))
        fm = asyncio.run(c.probe_model("m1"))
        assert not fm.probe_ok
        assert fm.probe_error  # 异常文本进 error，不抛出


class TestDiscoverFreeModels:
    def _gateway(
        self, probe_fail: frozenset[str] = frozenset()
    ) -> Callable[[httpx.Request], httpx.Response]:
        panel = [
            panel_entry("free-ok"),
            panel_entry("free-dead"),
            panel_entry("disabled", disabled=True),
            panel_entry("inactive", promo={"active": False}),
            panel_entry("paid", cost_tier="paid"),
            panel_entry("not-in-v1"),
        ]

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/panel/api/models":
                return json_resp({"models": panel})
            if req.url.path == "/v1/models":
                return json_resp(
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
                    return json_resp({"e": 1}, status=500)
                return json_resp(chat_payload("OK"))
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
        assert by_uid["free-dead"].probe_error.startswith("HTTP 500:")
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
                return json_resp({"models": [panel_entry("only-panel")]})
            if req.url.path == "/v1/models":
                return json_resp({"e": 1}, status=503)
            return json_resp(chat_payload("OK"))

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
                return json_resp({"models": [panel_entry("a")]})
            return json_resp({"data": [{"id": "a"}]})

        c = _client(handler)
        found = asyncio.run(c.discover_free_models(probe=False))
        assert [m.uid for m in found] == ["a"]
        assert posts == 0

    def test_panel_error_propagates(self) -> None:
        c = _client(lambda _r: json_resp({"e": 1}, status=401))
        with pytest.raises(cl.AuthError):
            asyncio.run(c.discover_free_models())


# ---------------------------------------------------------------- 生命周期


class TestOwnership:
    def test_external_http_not_closed(self) -> None:
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: json_resp({}))
        )
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


# ---------------------------------------------------------------- 传输/合同边界（audit 2026-09-17）


class TestTransportAndContract:
    def test_decoding_error_wrapped_retryable(self) -> None:
        """gzip 损坏同款 ``DecodingError``——RequestError 非 TransportError，曾逃逸 ChatError 契约。"""

        def boom(req: httpx.Request) -> httpx.Response:
            err = httpx.DecodingError("corrupt gzip", request=req)
            raise err

        c = _client(boom)
        with pytest.raises(cl.RetryableHTTPError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert ei.value.retryable
        assert ei.value.status < 0  # 传输族 status=-1 → 降级臂不切模

    def test_decoding_error_wrapped_in_stream(self) -> None:
        def boom(req: httpx.Request) -> httpx.Response:
            err = httpx.DecodingError("corrupt gzip", request=req)
            raise err

        c = _client(boom)

        with pytest.raises(cl.RetryableHTTPError):
            asyncio.run(drain(c, "m1", _MSGS))

    def test_invalid_url_non_retryable(self) -> None:
        """坏 base_url 的 ``InvalidURL`` 是 plain Exception——曾逃逸成 crash 类。"""
        c = _client(
            lambda _r: json_resp(chat_payload()), base_url="http://host:badport"
        )
        with pytest.raises(cl.ChatError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert not ei.value.retryable
        assert not isinstance(ei.value, cl.RetryableHTTPError)

    def test_error_body_api_key_redacted(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """网关回显 Authorization 头 → api_key 不得进异常消息与日志。"""
        key = "sk-test-secret-abcdef123456"

        def echo(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                500,
                text=f'{{"error": "upstream rejected auth {req.headers["authorization"]}"}}',
            )

        c = _client(echo, api_key=key)
        with pytest.raises(cl.ChatError) as ei, caplog.at_level("WARNING"):
            asyncio.run(c.chat("m1", _MSGS))
        assert key not in str(ei.value)
        assert "***" in str(ei.value)
        assert key not in caplog.text  # 降级臂 log.warning 同样过 redact

    def test_non_json_200_malformed_retryable(self) -> None:
        """200 + 非 JSON 体（代理 HTML 错误页）→ retryable 合同违约而非永久 skipped。"""
        c = _client(lambda _r: httpx.Response(200, text="<html>proxy oops</html>"))
        with pytest.raises(cl.MalformedResponseError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert ei.value.retryable
        assert ei.value.status == 200  # noqa: PLR2004 -- 记真实 HTTP 码
        assert ei.value.max_tries == 2  # noqa: PLR2004 -- 只翻身一次

    def test_non_object_json_200_malformed(self) -> None:
        """200 + JSON list（非协议 dict）→ MalformedResponseError 而非 AttributeError。"""
        c = _client(lambda _r: json_resp(["m1", "m2"]))
        with pytest.raises(cl.MalformedResponseError):
            asyncio.run(c.chat("m1", _MSGS))

    def test_no_choices_malformed(self) -> None:
        """200 + choices 空 → MalformedResponseError（曾是不重试的 ChatError）。"""
        c = _client(lambda _r: json_resp({"choices": [], "usage": {}}))
        with pytest.raises(cl.MalformedResponseError):
            asyncio.run(c.chat("m1", _MSGS))

    def test_list_models_malformed_payloads(self) -> None:
        """list_models 三种畸形：list 顶层 / 非 JSON / data 非 list。"""
        for resp in (
            json_resp(["m1"]),
            httpx.Response(200, text="<html>"),
            json_resp({"data": {"x": 1}}),
        ):
            c = _client(lambda _r, r=resp: r)
            with pytest.raises(cl.MalformedResponseError):
                asyncio.run(c.list_models())

    def test_list_models_filters_malformed_members(self) -> None:
        """data 成员按 dict+id 过滤——裸字符串成员不再有 "id" in m 子串误判。"""
        c = _client(
            lambda _r: json_resp({"data": [{"id": "ok"}, "junk", 5, {"noid": 1}]})
        )
        assert asyncio.run(c.list_models()) == ["ok"]

    def test_anthropic_error_payload_redacted(self) -> None:
        """anthropic ``type==error`` 的 200 体——message 里的 key 过 redact。"""
        key = "sk-ant-secret-xyz-9999"
        payload = {
            "type": "error",
            "error": {"type": "overloaded_error", "message": f"key {key} rejected"},
        }
        c = _client(
            lambda _r: json_resp(payload),
            base_url="https://api.anthropic.com",
            api_key=key,
        )
        with pytest.raises(cl.ChatError) as ei:
            asyncio.run(c.chat("claude-x", _MSGS))
        assert key not in str(ei.value)
        assert "overloaded_error" in str(ei.value)

    def test_malformed_base_url_no_crash_at_init(self) -> None:
        """畸形 base_url：构造/provider 识别/网关判定不炸——请求期以非重试 ChatError 报出。"""
        bad = "http://[bad::url"
        assert cl.provider_for_url(bad) == "custom"
        assert not cl.is_free_gateway_url(bad)
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: json_resp({}))
        )
        c = cl.ChatClient(bad, KEY, http=http)
        with pytest.raises(cl.ChatError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert not ei.value.retryable


# ---------------------------------------------------------------- 流式兜底臂（stream_fallback）


def _sse(content: str, finish: str = "stop") -> bytes:
    """单 content delta + finish 终帧 + [DONE] 的 OpenAI SSE 体。"""
    d = json.dumps({"choices": [{"delta": {"content": content}}]}, ensure_ascii=False)
    f = json.dumps({"choices": [{"delta": {}, "finish_reason": finish}]})
    return f"data: {d}\n\ndata: {f}\n\ndata: [DONE]\n\n".encode()


class TestStreamRescue:
    """``stream_fallback`` opt-in 兜底臂——非流式路由死亡 → ``chat_stream`` 补发。

    钉的是 2026-09-19 网关非流式全模型 502、stream 独活的事故形态：
    ``_stream_rescuable``（传输族 status<0 / 5xx）∧ 旋钮双闸才补发；
    补发侧 status==200 合同违约直接上抛（比原路由死亡更新鲜、可行动）。
    """

    def test_transport_error_rescued_by_stream(self) -> None:
        """ConnectError（status=-1，非切模型级）→ 原地流式补发成功。"""
        calls = {"n": 0}

        def handler(_r: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                msg = "non-stream route dead"
                raise httpx.ConnectError(msg)
            return httpx.Response(200, content=_sse("流式兜底译文"))

        c = _client(_recording(handler), stream_fallback=True)
        r = asyncio.run(c.chat("m1", _MSGS))
        assert r.content == "流式兜底译文"
        assert len(_REQS) == 2  # noqa: PLR2004 -- 原发 + 流式补发各一
        assert _REQS[1].url.path == "/v1/chat/completions"
        assert json.loads(_REQS[1].content)["stream"] is True

    def test_5xx_rescued_by_stream(self) -> None:
        """502（切模型级）→ 候选枚举空 → 末位 rescue_target 流式补发。"""
        calls = {"n": 0}

        def handler(_r: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return json_resp({"error": "x"}, status=502)
            return httpx.Response(200, content=_sse("流式译文"))

        # 非 loopback base_url：is_free_gateway_url False → 降级臂零探测请求
        c = _client(
            _recording(handler), base_url="http://gw.test", stream_fallback=True
        )
        r = asyncio.run(c.chat("m1", _MSGS))
        assert r.content == "流式译文"
        assert len(_REQS) == 2  # noqa: PLR2004 -- 无 /panel//v1/models 探测噪音
        posts = [q for q in _REQS if q.url.path == "/v1/chat/completions"]
        assert len(posts) == 2  # noqa: PLR2004
        assert json.loads(posts[1].content)["stream"] is True

    def test_knob_off_no_reissue(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """默认关——原 RetryableHTTPError 直接上抛，一个补发请求都不发。"""
        monkeypatch.delenv(cl.ENV_STREAM_FALLBACK, raising=False)
        c = _client(_recording(connect_error("refused")))
        with pytest.raises(cl.RetryableHTTPError):
            asyncio.run(c.chat("m1", _MSGS))
        assert len(_REQS) == 1

    def test_auth_error_not_rescued(self) -> None:
        """401 AuthError 是判定级错误——非 ``_stream_rescuable``，不补发。"""
        c = _client(
            _recording(lambda _r: json_resp({"error": "x"}, status=401)),
            stream_fallback=True,
        )
        with pytest.raises(cl.AuthError):
            asyncio.run(c.chat("m1", _MSGS))
        assert len(_REQS) == 1

    def test_empty_content_not_rescued(self) -> None:
        """200 空 content（合同违约族 status=200）不在补发面——只发一次。"""
        c = _client(
            _recording(lambda _r: json_resp(chat_payload("   "))),
            base_url="http://gw.test",  # 免降级臂对 loopback 网关发发现请求
            stream_fallback=True,
        )
        with pytest.raises(cl.EmptyContentError):
            asyncio.run(c.chat("m1", _MSGS))
        assert len(_REQS) == 1

    def test_rescue_stream_contract_violation_reraises(self) -> None:
        """补发 stream 自身 200 合同违约（finish=length）→ 上抛不回落原链。"""
        calls = {"n": 0}

        def handler(_r: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                msg = "dead"
                raise httpx.ConnectError(msg)
            return httpx.Response(200, content=_sse("半截", finish="length"))

        c = _client(_recording(handler), stream_fallback=True)
        with pytest.raises(cl.LengthTruncatedError):
            asyncio.run(c.chat("m1", _MSGS))
        assert len(_REQS) == 2  # noqa: PLR2004
