"""免费集降级臂（spec-xlat #2）：``chat()`` 模型级失败 → 发现链候选补发。

MockTransport 全 fake，断言面：

- BYOK/公网端点：``fallback_candidates``/``chat`` 一个探测请求都不发；
- 内置网关（loopback/tailnet）：请求模型失败后按 ``rank_models`` 序换候选；
- 发现链失败/空集：静默退化为原错误上抛（静态行为不变）。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from _xlatkit import chat_payload, json_resp, mock_client, panel_entry, recording

from texlate.xlat import client as cl

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

GATEWAY = "http://127.0.0.1:3003"
TAILNET_GW = "http://100.64.0.1:3003"  # tailnet/CGNAT 形网关端点（非缺省——缺省为 127.0.0.1:3033）
BYOK = "https://api.deepseek.com"
CUSTOM_PUBLIC = "https://relay.example.com"
KEY = "k"
_MSGS = [{"role": "user", "content": "hi"}]
_PROBE_HINT = "Reply with exactly: OK"

_REQS: list[httpx.Request] = []


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    base_url: str = GATEWAY,
) -> cl.ChatClient:
    """本文件默认 ``GATEWAY``/``KEY`` + ``_REQS`` 登记——透传 ``_xlatkit`` 骨架。"""
    return mock_client(recording(handler, _REQS), base_url=base_url, api_key=KEY)


def _chat_payload(content: str = "译文", *, model: str = "m") -> dict[str, Any]:
    """本文件默认 ``"译文"``/``"m"``/usage 3/2——透传 ``_xlatkit.chat_payload``。"""
    return chat_payload(
        content, model=model, usage={"prompt_tokens": 3, "completion_tokens": 2}
    )


def _panel_entry(uid: str) -> dict[str, Any]:
    """本文件钉 ``disabled=False``/promo 2026-10-16——kit 默认 10-01 漂移面见 kit 注记。"""
    return panel_entry(
        uid, disabled=False, promo={"active": True, "end_date": "2026-10-16"}
    )


def _posted_model(req: httpx.Request) -> str:
    """POST 请求体里的 ``model`` 字段。"""
    return str(json.loads(req.content)["model"])


def _chat_models(*, include_probes: bool = True) -> list[str]:
    """已发 POST /v1/chat/completions 的 model 序列（默认含探活）。"""
    return [
        _posted_model(r)
        for r in _REQS
        if r.url.path == "/v1/chat/completions" and (include_probes or not _is_probe(r))
    ]


def _is_probe(req: httpx.Request) -> bool:
    body = json.loads(req.content)
    msgs = body.get("messages") or []
    return bool(msgs) and msgs[0].get("content") == _PROBE_HINT


@pytest.fixture(autouse=True)
def _clear_reqs(clean_env: pytest.MonkeyPatch) -> Iterator[None]:  # noqa: ARG001 -- fixture 副作用（env 清洗）
    """请求登记清零 + ``TEXLATE_*`` env 全扫——行为旗标（如
    ``TEXLATE_STREAM_FALLBACK``）不得泄入请求计数断言。"""
    _REQS.clear()
    yield
    _REQS.clear()


# ---------------------------------------------------------------- 闸：BYOK/公网零探测


class TestGate:
    def test_is_free_gateway_url(self) -> None:
        for url in (
            "http://127.0.0.1:3003",
            "http://localhost:3003/v1",
            "http://[::1]:3003",
            TAILNET_GW,
            "http://100.100.0.1:3003",  # CGNAT 段另一地址（不随 TAILNET_GW 常量值漂移）
            "https://node.tail12345.ts.net",
        ):
            assert cl.is_free_gateway_url(url), url
        for url in (
            "https://api.deepseek.com",
            "https://api.openai.com",
            "https://api.anthropic.com",
            CUSTOM_PUBLIC,
            "http://203.0.113.9:3003",  # 公网 IP 即使端口像网关也拒
            "http://100.128.0.1:3003",  # CGNAT 段外
        ):
            assert not cl.is_free_gateway_url(url), url

    @pytest.mark.parametrize("base_url", [BYOK, CUSTOM_PUBLIC])
    def test_byok_zero_discovery_requests(self, base_url: str) -> None:
        """BYOK/公网端点：chat 失败后一个探测请求都不发，原错误上抛。"""
        c = _client(lambda _r: json_resp({"e": 1}, status=500), base_url=base_url)

        async def go() -> None:
            with pytest.raises(cl.RetryableHTTPError):
                await c.chat("m1", _MSGS)
            assert await c.fallback_candidates() == []

        asyncio.run(go())
        assert len(_REQS) == 1  # 只有首发 chat POST
        assert _REQS[0].url.path == "/v1/chat/completions"

    @pytest.mark.parametrize("base_url", [BYOK, CUSTOM_PUBLIC])
    def test_byok_never_calls_discovery(self, base_url: str) -> None:
        """闸短路在 ``fallback_candidates`` 入口——连 discover_free_models 都不进。"""
        c = _client(lambda _r: json_resp({}), base_url=base_url)
        calls = 0

        async def spy(*_a: object, **_k: object) -> list[cl.FreeModel]:
            nonlocal calls
            calls += 1
            return []

        c.discover_free_models = spy  # type: ignore[method-assign]
        assert asyncio.run(c.fallback_candidates()) == []
        assert calls == 0
        assert not _REQS


# ---------------------------------------------------------------- 内置网关：候选枚举


class TestGatewayFallback:
    def _gateway(
        self, *, dead: frozenset[str] = frozenset()
    ) -> Callable[[httpx.Request], httpx.Response]:
        """panel 报 swe-2-high+aa-free 两个 free 活模型；chat 按 dead 集合 503。"""

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/panel/api/models":
                return json_resp(
                    {"models": [_panel_entry("aa-free"), _panel_entry("swe-2-high")]}
                )
            if req.url.path == "/v1/models":
                return json_resp({"data": [{"id": "aa-free"}, {"id": "swe-2-high"}]})
            if req.url.path == "/v1/chat/completions":
                uid = _posted_model(req)
                if uid in dead:
                    return json_resp({"e": 1}, status=503)
                return json_resp(_chat_payload(model=uid))
            return httpx.Response(404)

        return handler

    def test_discovered_candidates_after_configured(self) -> None:
        """请求模型失败 → 发现链枚举 → 按偏好序补发（swe-2-high 先于 aa-free）。"""
        c = _client(self._gateway(dead=frozenset({"cfg-model"})))
        r = asyncio.run(c.chat("cfg-model", _MSGS))
        assert r.content == "译文"
        assert r.model == "swe-2-high"  # 偏好序首个活模型接棒

        posts = _chat_models()
        # 候选序：cfg-model 首发 → 探活（aa-free/swe-2-high）→ swe-2-high 补发
        assert posts[0] == "cfg-model"
        assert posts[-1] == "swe-2-high"
        assert {"aa-free", "swe-2-high"} <= set(posts[1:-1])

    def test_tailnet_gateway_allowed(self) -> None:
        """tailnet 形网关 URL（provider_for_url→custom）同样允许发现。"""
        c = _client(self._gateway(), base_url=TAILNET_GW)
        assert asyncio.run(c.fallback_candidates()) == ["swe-2-high", "aa-free"]

    def test_404_switches_model(self) -> None:
        """404（promo 到期模型摘除形态）也切候选——非 retryable 但属模型级。"""
        dead = frozenset({"expired-model"})

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/v1/chat/completions":
                uid = _posted_model(req)
                if uid in dead:
                    return json_resp({"e": 1}, status=404)
                return json_resp(_chat_payload(model=uid))
            return self._gateway()(req)

        c = _client(handler)
        r = asyncio.run(c.chat("expired-model", _MSGS))
        assert r.model == "swe-2-high"

    def test_all_candidates_fail_raises_last(self) -> None:
        """候选全灭 → 上抛最后一次失败（retryable 语义保持）。

        探活放行（探活全死是另一用例）——只让真实 chat 请求失败。
        """
        dead = {"m", "swe-2-high", "aa-free"}
        base = self._gateway()

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/v1/chat/completions" and not _is_probe(req):
                uid = _posted_model(req)
                if uid in dead:
                    return json_resp({"e": 1}, status=503)
            return base(req)

        c = _client(handler)
        with pytest.raises(cl.RetryableHTTPError):
            asyncio.run(c.chat("m", _MSGS))
        real = _chat_models(include_probes=False)
        assert real == ["m", "swe-2-high", "aa-free"]

    def test_non_switchable_no_discovery(self) -> None:
        """auth/请求级错误不切模——panel/v1 一个请求都不发。"""
        c = _client(lambda _r: json_resp({"e": 1}, status=401))
        with pytest.raises(cl.AuthError):
            asyncio.run(c.chat("m", _MSGS))
        assert len(_REQS) == 1

    def test_transport_error_no_discovery(self) -> None:
        """传输级失败（同端点同死）不枚举候选。"""

        def boom(_r: httpx.Request) -> httpx.Response:
            msg = "refused"
            raise httpx.ConnectError(msg)

        c = _client(boom)
        with pytest.raises(cl.RetryableHTTPError):
            asyncio.run(c.chat("m", _MSGS))
        assert len(_REQS) == 1

    def test_discovery_memoized(self) -> None:
        """同一 client 多次 chat 失败只发现一次。"""
        c = _client(self._gateway(dead=frozenset({"m", "swe-2-high", "aa-free"})))

        async def go() -> None:
            for _ in range(2):
                with pytest.raises(cl.ChatError):
                    await c.chat("m", _MSGS)

        asyncio.run(go())
        panels = [r for r in _REQS if r.url.path == "/panel/api/models"]
        assert len(panels) == 1


# ---------------------------------------------------------------- 降级：发现失败静默退化


class TestDegrade:
    def test_panel_error_degrades_to_original(self) -> None:
        """发现链抛错 → 候选空 → 原 ChatError 原样上抛（无新失败形态）。"""

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/panel/api/models":
                return json_resp({"e": 1}, status=503)
            return json_resp({"e": 1}, status=503)

        c = _client(handler)
        with pytest.raises(cl.RetryableHTTPError) as ei:
            asyncio.run(c.chat("m", _MSGS))
        assert ei.value.status == 503  # noqa: PLR2004 -- 原错误非发现链错误
        # chat POST + panel GET；发现链在 panel 处即抛，无 v1/探活
        assert len(_REQS) == 2  # noqa: PLR2004

    def test_empty_free_set_degrades(self) -> None:
        """免费集为空 → 候选空 → 原错误上抛。"""

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/panel/api/models":
                return json_resp({"models": []})
            if req.url.path == "/v1/models":
                return json_resp({"data": []})
            return json_resp({"e": 1}, status=503)

        c = _client(handler)
        with pytest.raises(cl.RetryableHTTPError):
            asyncio.run(c.chat("m", _MSGS))
        assert _chat_models() == ["m"]

    def test_probe_all_dead_degrades(self) -> None:
        """清单有货但探活全死 → 候选空 → 原错误上抛。"""

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/panel/api/models":
                return json_resp({"models": [_panel_entry("ghost")]})
            if req.url.path == "/v1/models":
                return json_resp({"data": [{"id": "ghost"}]})
            return json_resp({"e": 1}, status=503)

        c = _client(handler)
        with pytest.raises(cl.RetryableHTTPError):
            asyncio.run(c.chat("m", _MSGS))


# ---------------------------------------------------------------- rank_models


class TestRankModels:
    def _m(self, uid: str, *, ok: bool = True) -> cl.FreeModel:
        return cl.FreeModel(uid=uid, probe_ok=ok)

    def test_preference_then_lexical(self) -> None:
        got = cl.rank_models(
            [
                self._m("zz"),
                self._m("swe-2-high"),
                self._m("aa"),
                self._m("swe-2-medium"),
            ]
        )
        assert got == ["swe-2-medium", "swe-2-high", "aa", "zz"]

    def test_denylist_and_dead_excluded(self) -> None:
        got = cl.rank_models(
            [self._m("swe-1-7"), self._m("dead", ok=False), self._m("glm-5-2")]
        )
        assert got == ["glm-5-2"]
