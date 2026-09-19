"""client：状态码分类（含 429 body retry_after）/ provider 识别 / 脱敏 / 选模。

线路主面（chat/stream/panel/discover）由 test_xlat_client_wire 覆盖；
本文件补钉它没碰的分支：usage_sink 记账、EmptyContentError 合同属性、
anthropic 显式预算/多 system 拼接、stream 传输错误、max_probe 截断等。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from texlate.xlat import client as cl

if TYPE_CHECKING:
    from collections.abc import Callable


def _headers(**kw: str) -> httpx.Headers:
    return httpx.Headers(kw)


_BODY_RA_S = 22.0  # B4a 实测 body retry_after 量级（16~22s）
_HDR_RA_S = 7.0


class TestClassifyStatus:
    def test_auth_billing_notfound(self) -> None:
        h = _headers()
        assert isinstance(cl.classify_status(401, "x", h), cl.AuthError)
        assert isinstance(cl.classify_status(403, "x", h), cl.AuthError)
        assert isinstance(cl.classify_status(402, "x", h), cl.BillingError)
        assert isinstance(cl.classify_status(404, "x", h), cl.EndpointNotFoundError)
        for e in (
            cl.classify_status(401, "x", h),
            cl.classify_status(402, "x", h),
            cl.classify_status(404, "x", h),
        ):
            assert not e.retryable

    def test_retryable_set(self) -> None:
        h = _headers()
        for code in (408, 409, 425, 429, 500, 503):
            e = cl.classify_status(code, "x", h)
            assert isinstance(e, cl.RetryableHTTPError)
            assert e.retryable
        # 其余 4xx 不重试
        e = cl.classify_status(400, "bad request", h)
        assert isinstance(e, cl.ClientRejectedError)
        assert not e.retryable

    def test_429_retry_after_from_body(self) -> None:
        """B4a 实测形态：retry_after 在 body `error.retry_after`（秒），无 header。"""
        body = (
            '{"error":{"code":"rate_limit_exceeded","message":"reset in 22 '
            'seconds","retry_after":22,"type":"rate_limit_error"}}'
        )
        e = cl.classify_status(429, body, _headers())
        assert isinstance(e, cl.RetryableHTTPError)
        assert e.retry_after == _BODY_RA_S

    def test_429_retry_after_header_fallback(self) -> None:
        e = cl.classify_status(429, "plain text", _headers(**{"retry-after": "7"}))
        assert isinstance(e, cl.RetryableHTTPError)
        assert e.retry_after == _HDR_RA_S

    def test_429_retry_after_body_over_header(self) -> None:
        body = '{"error":{"retry_after":12}}'
        e = cl.classify_status(429, body, _headers(**{"retry-after": "3"}))
        assert e.retry_after == 12.0  # noqa: PLR2004 -- body 值覆盖 header 值 3

    def test_429_no_retry_after(self) -> None:
        e = cl.classify_status(429, "{}", _headers())
        assert e.retry_after is None

    def test_retry_after_over_cap_rejected(self) -> None:
        body = '{"error":{"retry_after":600}}'
        e = cl.classify_status(429, body, _headers())
        assert e.retry_after is None  # >60s 不等


class TestProviderAndUrl:
    def test_provider_for_url(self) -> None:
        assert cl.provider_for_url("http://127.0.0.1:3003") == "gateway"
        assert cl.provider_for_url("https://api.anthropic.com") == "anthropic"
        assert cl.provider_for_url("https://api.deepseek.com/v1") == "deepseek"
        assert cl.provider_for_url("https://dashscope.aliyuncs.com") == "qwen"
        assert cl.provider_for_url("https://api.openai.com") == "openai"
        assert cl.provider_for_url("https://example.org") == "custom"

    def test_normalize_base_url(self) -> None:
        b = "http://x:3003"
        assert cl.normalize_base_url("http://x:3003/") == b
        assert cl.normalize_base_url("http://x:3003/v1") == b
        assert cl.normalize_base_url("http://x:3003/v1/chat/completions") == b
        assert cl.normalize_base_url("http://x:3003/chat/completions") == b


class TestRedact:
    def test_api_key_and_bearer(self) -> None:
        out = cl.redact("Bearer s3cr3t-t3st failed", api_key="s3cr3t-t3st")
        assert "s3cr3t-t3st" not in out
        assert "***" in out

    def test_sk_patterns(self) -> None:
        out = cl.redact("key=sk-xxxxxxxxxxxxxxxx leaked")
        assert "sk-xxxxxxxxxxxxxxxx" not in out


class TestPickModel:
    def _m(self, uid: str, *, ok: bool = True) -> cl.FreeModel:
        return cl.FreeModel(uid=uid, probe_ok=ok)

    def test_preference_order(self) -> None:
        got = cl.pick_model([self._m("swe-2-max"), self._m("swe-2-medium")])
        assert got == "swe-2-medium"  # 偏好序第一

    def test_denylist_wins(self) -> None:
        got = cl.pick_model([self._m("swe-1-7"), self._m("glm-5-2")])
        assert got == "glm-5-2"  # swe-1-7 被 denylist 一票否决

    def test_dead_preference_falls_through(self) -> None:
        got = cl.pick_model([self._m("swe-2-medium", ok=False), self._m("glm-5-2")])
        assert got == "glm-5-2"

    def test_empty_alive(self) -> None:
        assert cl.pick_model([self._m("swe-1-7")]) is None
        assert cl.pick_model([]) is None

    def test_unknown_alive_sorted(self) -> None:
        got = cl.pick_model([self._m("zz-model"), self._m("aa-model")])
        assert got == "aa-model"  # 偏好序外按字典序取最小


# ---------------------------------------------------------------- wire 补钉（MockTransport）

_BASE = "http://127.0.0.1:3003"
_ANTHROPIC_BASE = "https://api.anthropic.com"
_MSGS = [{"role": "user", "content": "hi"}]


def _mock(
    handler: Callable[[httpx.Request], httpx.Response],
    base_url: str = _BASE,
    api_key: str = "k",
    usage_sink: Callable[[cl.UsageRecord], None] | None = None,
    dialect: str | None = None,
) -> cl.ChatClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return cl.ChatClient(
        base_url, api_key, http=http, usage_sink=usage_sink, dialect=dialect
    )


def _chat_payload(
    content: str = "OK", *, finish: str = "stop", model: str = "m1"
) -> dict[str, Any]:
    return {
        "model": model,
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish,
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


_ANTHROPIC_OK = {
    "type": "message",
    "stop_reason": "end_turn",
    "content": [{"type": "text", "text": "译"}],
    "usage": {"input_tokens": 3, "output_tokens": 2},
}

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


class TestUsageSink:
    """usage_sink 记账合同：成功一次记一笔；HTTP 失败不记；sink 炸不拖垮调用。"""

    def test_sink_receives_record(self) -> None:
        recs: list[cl.UsageRecord] = []
        c = _mock(
            lambda _r: httpx.Response(200, json=_chat_payload()),
            usage_sink=recs.append,
        )
        r = asyncio.run(c.chat("m1", _MSGS))
        assert r.content == "OK"
        assert len(recs) == 1
        rec = recs[0]
        assert rec["model"] == "m1"
        assert rec["prompt_tokens"] == 11  # noqa: PLR2004
        assert rec["completion_tokens"] == 7  # noqa: PLR2004
        assert rec["latency_s"] >= 0

    def test_sink_not_fired_on_http_error(self) -> None:
        recs: list[cl.UsageRecord] = []
        c = _mock(lambda _r: httpx.Response(500, json={"e": 1}), usage_sink=recs.append)
        with pytest.raises(cl.RetryableHTTPError):
            asyncio.run(c.chat("m1", _MSGS))
        assert recs == []

    def test_sink_exception_swallowed(self) -> None:
        def boom(_rec: cl.UsageRecord) -> None:
            msg = "accounting down"
            raise RuntimeError(msg)

        c = _mock(lambda _r: httpx.Response(200, json=_chat_payload()), usage_sink=boom)
        r = asyncio.run(c.chat("m1", _MSGS))
        assert r.content == "OK"


class TestChatEdges:
    def test_empty_content_error_contract(self) -> None:
        """EmptyContentError：status=200 记真实 HTTP 码 + retryable + 总尝试封顶 2。"""
        c = _mock(lambda _r: httpx.Response(200, json=_chat_payload("  ")))
        with pytest.raises(cl.EmptyContentError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert ei.value.status == 200  # noqa: PLR2004
        assert ei.value.retryable
        assert ei.value.max_tries == 2  # noqa: PLR2004

    def test_error_message_truncated_to_300(self) -> None:
        e = cl.classify_status(500, "y" * 500, httpx.Headers())
        assert str(e) == f"HTTP 500: {'y' * 300}"

    def test_retry_after_http_date_ignored(self) -> None:
        """HTTP-date 形态不解析——文档化降级，不引 email.utils 链。"""
        e = cl.classify_status(
            503,
            "x",
            httpx.Headers({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        )
        assert e.retry_after is None


class TestAnthropicEdges:
    def test_explicit_max_tokens_honored(self) -> None:
        """显式 max_tokens 不被 REASONING_MIN_MAX_TOKENS 默认值覆盖。"""
        reqs: list[httpx.Request] = []

        def handler(r: httpx.Request) -> httpx.Response:
            reqs.append(r)
            return httpx.Response(200, json=_ANTHROPIC_OK)

        c = _mock(handler, base_url=_ANTHROPIC_BASE)
        asyncio.run(c.chat("claude-x", _MSGS, options=cl.ChatOptions(max_tokens=123)))
        assert json.loads(reqs[0].content)["max_tokens"] == 123  # noqa: PLR2004

    def test_multiple_system_messages_joined(self) -> None:
        reqs: list[httpx.Request] = []

        def handler(r: httpx.Request) -> httpx.Response:
            reqs.append(r)
            return httpx.Response(200, json=_ANTHROPIC_OK)

        c = _mock(handler, base_url=_ANTHROPIC_BASE)
        msgs = [
            {"role": "system", "content": "a"},
            {"role": "system", "content": "b"},
            {"role": "user", "content": "x"},
        ]
        asyncio.run(c.chat("claude-x", msgs))
        body = json.loads(reqs[0].content)
        assert body["system"] == "a\nb"
        assert [m["role"] for m in body["messages"]] == ["user"]

    def test_empty_text_block_rejected(self) -> None:
        payload = {
            "type": "message",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "  "}],
        }
        c = _mock(
            lambda _r: httpx.Response(200, json=payload), base_url=_ANTHROPIC_BASE
        )
        with pytest.raises(cl.EmptyContentError):
            asyncio.run(c.chat("m", _MSGS))

    def test_transport_error_retryable(self) -> None:
        def boom(_r: httpx.Request) -> httpx.Response:
            msg = "refused"
            raise httpx.ConnectError(msg)

        c = _mock(boom, base_url=_ANTHROPIC_BASE)
        with pytest.raises(cl.RetryableHTTPError, match="transport error"):
            asyncio.run(c.chat("m", _MSGS))

    def test_http_error_classified_same(self) -> None:
        c = _mock(
            lambda _r: httpx.Response(401, json={"e": 1}), base_url=_ANTHROPIC_BASE
        )
        with pytest.raises(cl.AuthError):
            asyncio.run(c.chat("m", _MSGS))


class TestDialectSelection:
    """``dialect`` 决议：auto 按 host 推导、显式值覆盖、非法值早炸。"""

    def test_auto_derives_from_host(self) -> None:
        c1 = cl.ChatClient(_ANTHROPIC_BASE, "k", http=httpx.AsyncClient())
        assert c1.dialect == "anthropic"
        c2 = cl.ChatClient(_BASE, "k", http=httpx.AsyncClient())
        assert c2.dialect == "openai"

    def test_explicit_overrides_host(self) -> None:
        """anthropic host 显式 openai、custom host 显式 anthropic 都照给。"""
        c = cl.ChatClient(
            _ANTHROPIC_BASE, "k", dialect="openai", http=httpx.AsyncClient()
        )
        assert c.dialect == "openai"
        c = cl.ChatClient(
            "https://proxy.example", "k", dialect="anthropic", http=httpx.AsyncClient()
        )
        assert c.dialect == "anthropic"

    def test_invalid_dialect_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown dialect"):
            cl.ChatClient(_BASE, "k", dialect="bogus", http=httpx.AsyncClient())

    def test_dialect_for_url_matches_client(self) -> None:
        """``dialect_for_url`` 与 ``ChatClient`` 同源推导（doctor 等展示面用）。"""
        assert cl.dialect_for_url(_ANTHROPIC_BASE) == "anthropic"
        assert cl.dialect_for_url(_BASE) == "openai"
        assert cl.dialect_for_url(_BASE, "responses") == "responses"
        with pytest.raises(ValueError, match="unknown dialect"):
            cl.dialect_for_url(_BASE, "bogus")


class TestResponsesDialect:
    """Responses 方言：``/v1/responses`` + instructions/input 体 + output/status 解析。

    ``dialect="responses"`` 面向 responses-only 反代等 host 识别不了的
    BYOK 端点——请求组装/响应解析/错误归约三方各有钉点。
    """

    def test_request_shape(self) -> None:
        reqs: list[httpx.Request] = []

        def handler(r: httpx.Request) -> httpx.Response:
            reqs.append(r)
            return httpx.Response(200, json=_RESPONSES_OK)

        c = _mock(handler, dialect="responses")
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
        req = reqs[0]
        assert req.url.path == "/v1/responses"
        assert req.headers["authorization"] == "Bearer k"
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
        c = _mock(lambda _r: httpx.Response(200, json=payload), dialect="responses")
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
        c = _mock(lambda _r: httpx.Response(200, json=payload), dialect="responses")
        with pytest.raises(cl.LengthTruncatedError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert ei.value.partial_content == "半"

    def test_incomplete_content_filter(self) -> None:
        payload = {
            "status": "incomplete",
            "incomplete_details": {"reason": "content_filter"},
            "output": [],
        }
        c = _mock(lambda _r: httpx.Response(200, json=payload), dialect="responses")
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
        c = _mock(lambda _r: httpx.Response(200, json=payload), dialect="responses")
        with pytest.raises(cl.ContentFilterError):
            asyncio.run(c.chat("m1", _MSGS))

    def test_failed_status(self) -> None:
        payload = {
            "status": "failed",
            "error": {"code": "server_error", "message": "boom"},
        }
        c = _mock(lambda _r: httpx.Response(200, json=payload), dialect="responses")
        with pytest.raises(cl.ChatError, match="boom"):
            asyncio.run(c.chat("m1", _MSGS))

    def test_top_level_error_object(self) -> None:
        payload = {"type": "error", "error": {"code": "x", "message": "bad"}}
        c = _mock(lambda _r: httpx.Response(200, json=payload), dialect="responses")
        with pytest.raises(cl.ChatError, match="bad"):
            asyncio.run(c.chat("m1", _MSGS))

    def test_empty_content(self) -> None:
        payload = {"status": "completed", "output": []}
        c = _mock(lambda _r: httpx.Response(200, json=payload), dialect="responses")
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
        c = _mock(lambda _r: httpx.Response(200, json=payload), dialect="responses")
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
        c = _mock(lambda _r: httpx.Response(200, content=sse), dialect="responses")

        async def collect() -> list[cl.StreamEvent]:
            return [ev async for ev in c.chat_stream("m1", _MSGS)]

        events = asyncio.run(collect())
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
        c = _mock(lambda _r: httpx.Response(200, content=sse), dialect="responses")

        async def collect() -> list[cl.StreamEvent]:
            return [ev async for ev in c.chat_stream("m1", _MSGS)]

        events = asyncio.run(collect())
        assert events[-1].kind == "done"
        assert events[-1].finish_reason == "length"

    def test_stream_failed_raises(self) -> None:
        sse = (
            b'data: {"type":"response.failed","response":'
            b'{"error":{"message":"die"}}}\n\n'
        )
        c = _mock(lambda _r: httpx.Response(200, content=sse), dialect="responses")

        async def collect() -> list[cl.StreamEvent]:
            return [ev async for ev in c.chat_stream("m1", _MSGS)]

        with pytest.raises(cl.ChatError, match="die"):
            asyncio.run(collect())

    def test_probe_model_uses_responses_endpoint(self) -> None:
        """探活随方言——responses client 的 ``probe_model`` 打 ``/v1/responses``。"""
        reqs: list[httpx.Request] = []

        def handler(r: httpx.Request) -> httpx.Response:
            reqs.append(r)
            return httpx.Response(200, json=_RESPONSES_OK)

        c = _mock(handler, dialect="responses")
        fm = asyncio.run(c.probe_model("m1"))
        assert fm.probe_ok
        assert reqs[0].url.path == "/v1/responses"


class TestStreamEdges:
    def test_transport_error_retryable(self) -> None:
        def boom(_r: httpx.Request) -> httpx.Response:
            msg = "reset"
            raise httpx.ConnectError(msg)

        c = _mock(boom)

        async def collect() -> list[cl.StreamEvent]:
            return [ev async for ev in c.chat_stream("m1", _MSGS)]

        with pytest.raises(cl.RetryableHTTPError, match="transport error"):
            asyncio.run(collect())


class TestProbeEdges:
    def test_finish_length_rejected(self) -> None:
        """非 stop 收尾即使 content 非空也判探活失败。"""
        c = _mock(
            lambda _r: httpx.Response(200, json=_chat_payload("OK", finish="length"))
        )
        fm = asyncio.run(c.probe_model("m1"))
        assert not fm.probe_ok
        assert "finish" in fm.probe_error

    def test_finish_absent_accepted(self) -> None:
        payload = {"choices": [{"message": {"content": "OK"}}]}
        c = _mock(lambda _r: httpx.Response(200, json=payload))
        assert asyncio.run(c.probe_model("m1")).probe_ok

    def test_probe_error_redacts_api_key(self) -> None:
        """探活异常文本过 redact——api_key 值不外泄到 probe_error。"""

        def boom(r: httpx.Request) -> httpx.Response:
            msg = f"auth failed for {r.headers['authorization']}"
            raise httpx.ConnectError(msg)

        c = _mock(boom, api_key="supersecret")
        fm = asyncio.run(c.probe_model("m1"))
        assert not fm.probe_ok
        assert "supersecret" not in fm.probe_error
        assert "Bearer" not in fm.probe_error


def _panel_entry(uid: str) -> dict[str, Any]:
    return {
        "uid": uid,
        "cost_tier": "free",
        "promo": {"active": True, "end_date": "2026-10-01"},
        "context_tokens": 131072,
        "max_output_tokens": 8192,
    }


class TestDiscoverCap:
    def _handler(
        self, uids: list[str], probed: list[str]
    ) -> Callable[[httpx.Request], httpx.Response]:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/panel/api/models":
                return httpx.Response(
                    200, json={"models": [_panel_entry(u) for u in uids]}
                )
            if req.url.path == "/v1/models":
                return httpx.Response(503, json={"e": 1})  # 退化为只信 panel
            probed.append(json.loads(req.content)["model"])
            return httpx.Response(200, json=_chat_payload("OK"))

        return handler

    def test_default_cap_drops_overflow(self) -> None:
        """候选超 max_probe（默认 12）时溢出项直接不进返回集。"""
        uids = [f"f{i:02d}" for i in range(13)]
        probed: list[str] = []
        c = _mock(self._handler(uids, probed))
        found = asyncio.run(c.discover_free_models())
        assert {m.uid for m in found} == set(uids[:12])
        assert set(probed) == set(uids[:12])
        assert all(m.probe_ok for m in found)

    def test_max_probe_param(self) -> None:
        probed: list[str] = []
        c = _mock(self._handler(["a", "b", "c"], probed))
        found = asyncio.run(c.discover_free_models(max_probe=2))
        assert len(found) == 2  # noqa: PLR2004
        assert set(probed) == {"a", "b"}

    def test_panel_scalar_payload_empty(self) -> None:
        c = _mock(lambda _r: httpx.Response(200, json="nope"))
        assert asyncio.run(c.panel_models()) == []


class TestProviderAndUrlExtra:
    def test_azure_and_regional_qwen(self) -> None:
        assert cl.provider_for_url("https://my.openai.azure.com") == "openai"
        assert cl.provider_for_url("https://dashscope-intl.aliyuncs.com") == "qwen"
        got = cl.provider_for_url("https://abc123.cn-beijing.maas.aliyuncs.com")
        assert got == "qwen"

    def test_host_case_insensitive(self) -> None:
        assert cl.provider_for_url("https://API.ANTHROPIC.COM") == "anthropic"


class TestContentFilter:
    """content_filter 拒答 → ``ContentFilterError``：retryable（喂换模臂 +
    批面 degrade-to-singles）但 ``max_tries=1`` 不同模翻身——BabelDOC #580 同款。"""

    def test_400_content_filter_code_classified(self) -> None:
        body = '{"error":{"code":"content_filter","message":"filtered"}}'
        e = cl.classify_status(400, body, _headers())
        assert isinstance(e, cl.ContentFilterError)
        assert e.retryable
        assert e.max_tries == 1
        assert e.status == 400  # noqa: PLR2004
        assert cl._model_switchable(e)  # noqa: SLF001 -- 钉换模臂判据

    def test_400_other_code_still_rejected(self) -> None:
        body = '{"error":{"code":"invalid_request","message":"bad"}}'
        e = cl.classify_status(400, body, _headers())
        assert isinstance(e, cl.ClientRejectedError)
        assert not isinstance(e, cl.ContentFilterError)

    def test_finish_content_filter_with_partial_content(self) -> None:
        """200 ``finish_reason=content_filter`` + 非空 content 不许静默落盘。"""
        c = _mock(
            lambda _r: httpx.Response(
                200, json=_chat_payload("半截译文", finish="content_filter")
            )
        )
        with pytest.raises(cl.ContentFilterError):
            asyncio.run(c.chat("m1", _MSGS))

    def test_finish_content_filter_empty_not_empty_error(self) -> None:
        """过滤空响应须归 ``ContentFilterError``——``EmptyContentError`` 同模
        重试必同死，还吃掉 finish 语义。"""
        c = _mock(
            lambda _r: httpx.Response(
                200, json=_chat_payload("", finish="content_filter")
            )
        )
        with pytest.raises(cl.ContentFilterError):
            asyncio.run(c.chat("m1", _MSGS))

    def test_anthropic_refusal(self) -> None:
        payload = {**_ANTHROPIC_OK, "stop_reason": "refusal"}
        c = _mock(
            lambda _r: httpx.Response(200, json=payload),
            base_url=_ANTHROPIC_BASE,
        )
        with pytest.raises(cl.ContentFilterError):
            asyncio.run(c.chat("m1", _MSGS))


class TestRedactExtra:
    def test_google_key_pattern(self) -> None:
        out = cl.redact("k=AIzaSyD4iE2xVSpkLLOXoyq2uexnF3jJ2 end")
        assert "AIzaSyD4iE2xVSpkLLOXoyq2uexnF3jJ2" not in out

    def test_x_api_key_kv_pattern(self) -> None:
        out = cl.redact("x-api-key: supersecretvalue123")
        assert "supersecretvalue123" not in out

    def test_empty_api_key_no_crash(self) -> None:
        assert cl.redact("plain text") == "plain text"


# --------------------------------------------------- 外部 JSON 超深嵌套防御

#: ~100KB 即撞 json C 扫描器递归上限（实测阈值 ~20000 层，此处 50000 留足余量）。
_DEEP_JSON = "[" * 50000 + "]" * 50000


def test_body_retry_after_deep_json_returns_none() -> None:
    """429 body 超深嵌套 → ``_body_retry_after`` 归 None，RecursionError 不逃逸。"""
    assert cl._body_retry_after(_DEEP_JSON) is None  # noqa: SLF001


def test_classify_429_deep_json_body() -> None:
    """``classify_status`` 端到端：深 body 仍归 retryable 429、retry_after=None。"""
    err = cl.classify_status(429, _DEEP_JSON, httpx.Headers())
    assert isinstance(err, cl.RetryableHTTPError)
    assert err.retry_after is None


def test_sse_events_deep_json_line_skipped() -> None:
    """SSE ``data:`` 行超深嵌套 → 按坏行跳过（同坏 JSON 口径），不杀流。"""
    events, done = cl.ChatClient._sse_events(f"data: {_DEEP_JSON}")  # noqa: SLF001
    assert events == []
    assert done is False


@pytest.mark.parametrize("call", ["chat", "list_models", "panel_models"])
def test_client_deep_json_success_body_is_malformed(call: str) -> None:
    """200 成功体超深嵌套 → ``MalformedResponseError``（原 RecursionError 裸逃）。

    ``chat``/``list_models``/``panel_models`` 三处 ``resp.json()`` 同型修复。
    """

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_DEEP_JSON.encode())

    async def go() -> None:
        c = cl.ChatClient(
            "http://gw.test",
            "k",
            http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        if call == "chat":
            coro = c.chat("m", [{"role": "user", "content": "hi"}])
        elif call == "list_models":
            coro = c.list_models()
        else:
            coro = c.panel_models()
        with pytest.raises(cl.MalformedResponseError):
            await coro
        await c.aclose()

    asyncio.run(go())
