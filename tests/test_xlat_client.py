"""client：状态码分类（含 429 body retry_after）/ provider 识别 / 脱敏 / 选模。"""

import httpx

from texlate.xlat import client as cl


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
        out = cl.redact("Bearer 240127 failed", api_key="240127")
        assert "240127" not in out
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
