"""LLM 客户端：OpenAI 兼容 + Anthropic messages 方言、免费集动态发现、错误分类。

规格 docs/08 §1.6–1.7 + docs/research/gateway/{probe-3003,free-model-ranking,xlat}：

- 默认后端 `http://127.0.0.1:3003`（Devin 系网关，OpenAI Chat 协议）；
  **免费集运行时动态筛**——`/panel/api/models` 按 `cost_tier=="free"` ∧
  `promo.active` ∧ `not disabled` 过滤，∩ `/v1/models`，再逐模型探活，
  **不得硬编码免费集**（promo 到期自动降级，如 glm-5-2 2026-09-16）。
- 隐藏开销：网关每请求注入 ~160–566 prompt token 上游系统提示（成本模型计入）。
- reasoning 模型（swe-2-*/deepseek/kimi-k3/inkling）：`reasoning_content` 与
  `content` 分字段返回，reasoning 也吃 max_tokens——翻译请求 max_tokens≥8192。
- BYOK：`provider_for_url` host→provider 预设表（照 texglot providers.py 形状）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import ssl
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Self, TypedDict
from urllib.parse import urlsplit

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- 常量

#: 网关注入的隐藏 prompt token 量级（探针实测 154–566，取保守中值供成本估算）
HIDDEN_PROMPT_TOKENS = 465
#: reasoning 模型最小输出预算（思考先烧预算，16 token 会全耗在思考上 → content 空）
REASONING_MIN_MAX_TOKENS = 8192
#: 探活请求预算（只要求非空 content，给思考留 1k 余量足够）
PROBE_MAX_TOKENS = 1024
DEFAULT_TIMEOUT = httpx.Timeout(180.0, connect=10.0)
PROBE_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

#: 免费集偏好序（动态发现后按此排序——不是免费集本身，命中才选）
DEFAULT_MODEL_PREFERENCE = ("swe-2-medium", "swe-2-high", "swe-2-max", "glm-5-2")
#: 免费集禁用名单（契约事故史/不可预算，docs/research/gateway/free-model-ranking §5）
DEFAULT_MODEL_DENYLIST = frozenset({"swe-1-7", "swe-1-7-medium"})

#: HTTP 状态码（classify 判定表）
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_PAYMENT_REQUIRED = 402
HTTP_NOT_FOUND = 404
HTTP_TOO_MANY_REQUESTS = 429
#: 除 429 外的可重试 4xx
RETRYABLE_4XX = frozenset({408, 409, 425})
#: 5xx 下限
SERVER_ERROR_MIN = 500
#: Retry-After 尊重上限（超过直接拒，不等）
MAX_RETRY_AFTER_S = 60.0


# ---------------------------------------------------------------- 错误分类（docs/08 §1.6 HTTP 层）


class XlatError(Exception):
    """xlat 层异常基类。"""


class ChatError(XlatError):
    """HTTP/协议层错误。`status` 为 HTTP 码（传输层错误为 -1），`retryable` 供退避判定。"""

    def __init__(
        self,
        message: str,
        *,
        status: int = -1,
        retryable: bool = False,
        retry_after: float | None = None,
        max_tries: int | None = None,
    ) -> None:
        """HTTP 层错误：status（传输层 -1）+ retryable + retry_after。

        ``max_tries`` 收窄该错误在 ``call_with_backoff`` 里的总尝试数
        （None = 跟随 RetryPolicy.max_tries）。
        """
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after
        self.max_tries = max_tries


class AuthError(ChatError):
    """401/403 认证失败——重试无意义。"""


class BillingError(ChatError):
    """402 余额不足——重试无意义。"""


class EndpointNotFoundError(ChatError):
    """404 地址/模型错——重试无意义（清单≠可用须换模型）。"""


class ClientRejectedError(ChatError):
    """其余 4xx——请求本身被拒，重试无意义。"""


class RetryableHTTPError(ChatError):
    """408/409/425/429/5xx——可重试（429 用 `3^attempt`、下限 5s；Retry-After 从其值）。"""


class LengthTruncatedError(ChatError):
    """`finish_reason=="length"`——输出被截断，属可重试的合同违约（调大 max_tokens）。"""

    def __init__(self, message: str, *, partial_content: str = "") -> None:
        """截断错误：携带已收到的部分正文（可留作降级材料）。"""
        super().__init__(message, retryable=True)
        self.partial_content = partial_content


class EmptyContentError(ChatError):
    """HTTP 200 但 content 为空（reasoning 模型预算被思考烧光的典型形态）。

    retryable 但 ``max_tries=2``（只翻身一次——连续空响应多半是模型/预算
    问题而非瞬时抖动；原先 non-retryable 让空响应直接穿透成 skipped）。
    ``status`` 记真实 HTTP 码 200：这是合同违约不是传输故障，退避走
    base·2^attempt 而非 timeout_floor。
    """

    def __init__(self, message: str) -> None:
        """空响应：retryable + 总尝试数封顶 2。"""
        super().__init__(message, status=HTTP_OK, retryable=True, max_tries=2)


def _retry_after(headers: httpx.Headers) -> float | None:
    """解析 Retry-After 头（秒数或 HTTP-date）；>60s 不等直接拒。"""
    raw = headers.get("retry-after")
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        secs = float(raw)
        return secs if secs <= MAX_RETRY_AFTER_S else None
    # HTTP-date 形态退化为 None（不值得为它引 email.utils 解析链）
    return None


def _body_retry_after(body: str) -> float | None:
    """从错误 JSON body 的 `error.retry_after` 读秒数。

    B4a 实测：本网关 429 的 retry_after 在 body（`error.retry_after` 秒，
    观测 16~22s），HTTP 层无 Retry-After 头——body 优先、header 兜底。
    """
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
    err = data.get("error") if isinstance(data, dict) else None
    raw = err.get("retry_after") if isinstance(err, dict) else None
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        secs = float(raw)
        return secs if 0 <= secs <= MAX_RETRY_AFTER_S else None
    return None


def classify_status(status: int, body: str, headers: httpx.Headers) -> ChatError:
    """HTTP 状态码 → 异常类型（docs/08 §1.6 状态码分类表 + B4a 429 body 修订）。

    429 的 retry_after 解析序：body `error.retry_after` → header `Retry-After`
    → 无（退 `3^attempt` 下限 5s）。429 是多租户共享流量触发（healthz 常驻他户
    22~26 active），与本地并发宽度无关——不为它缩 Semaphore。
    """
    msg = f"HTTP {status}: {body[:300]}"
    if status in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
        return AuthError(msg, status=status)
    if status == HTTP_PAYMENT_REQUIRED:
        return BillingError(msg, status=status)
    if status == HTTP_NOT_FOUND:
        return EndpointNotFoundError(msg, status=status)
    if (
        status == HTTP_TOO_MANY_REQUESTS
        or status in RETRYABLE_4XX
        or status >= SERVER_ERROR_MIN
    ):
        retry_after = _retry_after(headers)
        if status == HTTP_TOO_MANY_REQUESTS:
            retry_after = _body_retry_after(body) or retry_after
        return RetryableHTTPError(
            msg, status=status, retryable=True, retry_after=retry_after
        )
    return ClientRejectedError(msg, status=status)


# ---------------------------------------------------------------- 结果类型


@dataclass
class Usage:
    """token 用量（网关按 provider 注入隐藏提示，量级因上游而异——计费须按档分开估）。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResult:
    """一次 chat 调用结果。`content` 为正文；reasoning 模型的思考链在 `reasoning`。"""

    content: str
    reasoning: str
    finish_reason: str
    usage: Usage
    model: str
    latency_s: float


@dataclass
class StreamEvent:
    """流式增量：`kind` ∈ content/reasoning/done。"""

    kind: str
    delta: str = ""
    finish_reason: str = ""


class UsageRecord(TypedDict):
    """``usage_sink`` 回调载荷——一次成功 ``chat()`` 的记账单元（T4）。

    ``Translator`` 协议只回 ``str``，token/延迟在边界被丢弃；挂 sink 后
    每次成功响应把 usage+latency 递出（失败的 HTTP 调用无 usage 可报）。
    """

    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float


@dataclass(frozen=True)
class ChatOptions:
    """一次 chat 调用的可选参数包（None 字段不写进请求体）。"""

    temperature: float | None = None
    max_tokens: int | None = None
    response_format: dict[str, str] | None = None
    extra: dict[str, Any] | None = None


@dataclass
class FreeModel:
    """动态发现的一个免费模型（panel 元数据 + 探活结果）。"""

    uid: str
    promo_end: str = ""
    context_tokens: int = 0
    max_output_tokens: int = 0
    supports_thinking: bool = False
    probe_ok: bool = False
    probe_latency_s: float = 0.0
    probe_error: str = ""


# ---------------------------------------------------------------- provider 识别（host→provider，照 texglot providers.py）


def provider_for_url(base_url: str) -> str:
    """Hostname → provider id。原则：按可信 API host 识别，绝不看模型名。"""
    host = (urlsplit(base_url).hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return "gateway"
    if host == "api.anthropic.com":
        return "anthropic"
    if host == "api.deepseek.com":
        return "deepseek"
    if host in {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "dashscope-us.aliyuncs.com",
    } or re.fullmatch(
        r"[a-z0-9-]+\.(?:cn-beijing|ap-southeast-1|ap-northeast-1"
        r"|eu-central-1|cn-hongkong)\.maas\.aliyuncs\.com",
        host,
    ):
        return "qwen"
    if host.endswith(".openai.azure.com") or host == "api.openai.com":
        return "openai"
    return "custom"


#: provider → 环境变量名（BYOK 读 key 的约定，docs/08 §1.7）
PROVIDER_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "gateway": "TEXLATE_GATEWAY_KEY",
    "custom": "TEXLATE_API_KEY",
}

#: provider → 请求方言（"openai" = /v1/chat/completions；"anthropic" = /v1/messages）
_PROVIDER_DIALECT: dict[str, str] = {
    "anthropic": "anthropic",
}


def normalize_base_url(base_url: str) -> str:
    """宽容归一：剥尾 `/`、`/chat/completions`、`/v1` 后缀，得到裸服务根。"""
    url = base_url.strip().rstrip("/")
    for suffix in ("/v1/chat/completions", "/chat/completions", "/v1"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return url.rstrip("/")


# ---------------------------------------------------------------- 脱敏

_SECRET_PATTERNS = [
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{4,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{10,}"),
    re.compile(r"(?:api[_-]?key|x-api-key|token)[=:]\s*[\"']?\S+", re.IGNORECASE),
]


def redact(text: str, api_key: str = "") -> str:
    """抹掉已知 secret 形态 + 显式 api_key 值（provider 无关脱敏）。"""
    out = text
    if api_key:
        out = out.replace(api_key, "***")
    for rx in _SECRET_PATTERNS:
        out = rx.sub("***", out)
    return out


# ---------------------------------------------------------------- 客户端


class ChatClient:
    """异步 chat 客户端：OpenAI 兼容 / Anthropic 双方言 + 网关免费集发现。

    用法::

        async with ChatClient("http://127.0.0.1:3003", "240127") as c:
            r = await c.chat("swe-2-medium", messages, temperature=0.2, max_tokens=8192)
    """

    def __init__(  # noqa: PLR0913 -- endpoint/key + provider/timeout/http + usage_sink 全是独立旋钮
        self,
        base_url: str,
        api_key: str = "",
        *,
        provider: str | None = None,
        timeout: httpx.Timeout | None = None,
        http: httpx.AsyncClient | None = None,
        usage_sink: Callable[[UsageRecord], None] | None = None,
    ) -> None:
        """按 base_url 自动识别 provider/方言；`http` 传入外部 client 时不自持。"""
        self.base_url = normalize_base_url(base_url)
        self.api_key = api_key
        self.provider = provider or provider_for_url(base_url)
        self.dialect = _PROVIDER_DIALECT.get(self.provider, "openai")
        self._own = http is None
        self._http = http or httpx.AsyncClient(
            timeout=timeout or DEFAULT_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
        #: 每次成功 ``chat()`` 后调用的记账回调（可后挂——worker 侧接线点）
        self.usage_sink = usage_sink

    async def __aenter__(self) -> Self:
        """进入 async with——返回自身。"""
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """退出 async with——关闭自持 http client。"""
        await self.aclose()

    async def aclose(self) -> None:
        """关闭底层 http client（仅当自持时）。"""
        if self._own:
            await self._http.aclose()

    # ------------------------------------------------------------ OpenAI 方言

    def _openai_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    @staticmethod
    def _openai_body(
        model: str,
        messages: list[dict[str, str]],
        options: ChatOptions,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        """OpenAI 请求体组装——options 的 None 字段不落盘。"""
        body: dict[str, Any] = {"model": model, "messages": messages}
        if options.temperature is not None:
            body["temperature"] = options.temperature
        if options.max_tokens is not None:
            body["max_tokens"] = options.max_tokens
        if options.response_format is not None:
            body["response_format"] = options.response_format
        if stream:
            body["stream"] = True
        if options.extra:
            body.update(options.extra)
        return body

    @staticmethod
    def _parse_openai(payload: dict[str, Any], latency: float) -> ChatResult:
        choices = payload.get("choices") or []
        if not choices:
            msg = "response has no choices"
            raise ChatError(msg)
        ch = choices[0]
        msg_obj = ch.get("message") or {}
        content = msg_obj.get("content") or ""
        reasoning = msg_obj.get("reasoning_content") or ""
        finish = ch.get("finish_reason") or ""
        usage_raw = payload.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
            completion_tokens=int(usage_raw.get("completion_tokens") or 0),
            cached_tokens=int(
                (usage_raw.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
            ),
            raw=usage_raw,
        )
        if finish == "length" and not content:
            msg = (
                "finish_reason=length with empty content "
                "(reasoning model burned the whole budget?)"
            )
            raise LengthTruncatedError(msg)
        if finish == "length":
            msg = "finish_reason=length: output truncated"
            raise LengthTruncatedError(msg, partial_content=content)
        if not content.strip():
            msg = "empty content in response"
            raise EmptyContentError(msg)
        return ChatResult(
            content=content,
            reasoning=reasoning,
            finish_reason=finish,
            usage=usage,
            model=payload.get("model") or "",
            latency_s=round(latency, 3),
        )

    # ------------------------------------------------------------ Anthropic 方言

    def _anthropic_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

    @staticmethod
    def _anthropic_body(
        model: str,
        messages: list[dict[str, str]],
        options: ChatOptions,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        """Anthropic 请求体：system 抽顶层、messages 只留会话角色。"""
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        conv = [m for m in messages if m["role"] != "system"]
        body: dict[str, Any] = {
            "model": model,
            "messages": conv,
            "max_tokens": options.max_tokens or REASONING_MIN_MAX_TOKENS,
        }
        if system:
            body["system"] = system
        if options.temperature is not None:
            body["temperature"] = options.temperature
        if stream:
            body["stream"] = True
        return body

    @staticmethod
    def _parse_anthropic(payload: dict[str, Any], latency: float) -> ChatResult:
        if payload.get("type") == "error":
            err = payload.get("error") or {}
            msg = f"anthropic error {err.get('type')}: {err.get('message')}"
            raise ChatError(msg)
        texts: list[str] = []
        thinks: list[str] = []
        for blk in payload.get("content") or []:
            if blk.get("type") == "text":
                texts.append(blk.get("text") or "")
            elif blk.get("type") == "thinking":
                thinks.append(blk.get("thinking") or "")
        content = "".join(texts)
        finish = payload.get("stop_reason") or ""
        if finish == "max_tokens" and not content:
            msg = "anthropic stop_reason=max_tokens, empty"
            raise LengthTruncatedError(msg)
        if finish == "max_tokens":
            msg = "anthropic stop_reason=max_tokens"
            raise LengthTruncatedError(msg, partial_content=content)
        if not content.strip():
            msg = "empty content in response"
            raise EmptyContentError(msg)
        u = payload.get("usage") or {}
        return ChatResult(
            content=content,
            reasoning="".join(thinks),
            finish_reason=finish,
            usage=Usage(
                prompt_tokens=int(u.get("input_tokens") or 0),
                completion_tokens=int(u.get("output_tokens") or 0),
                cached_tokens=int(u.get("cache_read_input_tokens") or 0),
                raw=u,
            ),
            model=payload.get("model") or "",
            latency_s=round(latency, 3),
        )

    # ------------------------------------------------------------ 公开 API

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: ChatOptions | None = None,
    ) -> ChatResult:
        """一次 chat 往返。错误已按 `classify_status` 分类；length/empty 也抛错。"""
        opts = options or ChatOptions()
        t0 = time.monotonic()
        try:
            if self.dialect == "anthropic":
                resp = await self._http.post(
                    f"{self.base_url}/v1/messages",
                    headers=self._anthropic_headers(),
                    json=self._anthropic_body(model, messages, opts, stream=False),
                )
            else:
                resp = await self._http.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers=self._openai_headers(),
                    json=self._openai_body(model, messages, opts, stream=False),
                )
        except (httpx.TransportError, ssl.SSLError) as e:
            msg = f"transport error: {e}"
            raise RetryableHTTPError(msg, retryable=True) from e
        latency = time.monotonic() - t0

        if resp.status_code != HTTP_OK:
            raise classify_status(resp.status_code, resp.text, resp.headers)
        try:
            payload = resp.json()
        except json.JSONDecodeError as e:
            msg = f"non-JSON response: {resp.text[:200]}"
            raise ChatError(msg) from e
        if self.dialect == "anthropic":
            result = self._parse_anthropic(payload, latency)
        else:
            result = self._parse_openai(payload, latency)
        sink = self.usage_sink
        if sink is not None:
            try:
                sink(
                    {
                        "model": result.model,
                        "prompt_tokens": result.usage.prompt_tokens,
                        "completion_tokens": result.usage.completion_tokens,
                        "latency_s": result.latency_s,
                    }
                )
            except Exception:
                log.exception("usage_sink failed")  # 记账回调绝不拖垮调用
        return result

    @staticmethod
    def _sse_events(line: str) -> tuple[list[StreamEvent], bool]:
        """解析一行 SSE `data:` payload → (events, done?)；非 data/坏 JSON 跳过。"""
        events: list[StreamEvent] = []
        if not line.startswith("data:"):
            return events, False
        data = line[5:].strip()
        if data == "[DONE]":
            return [StreamEvent(kind="done")], True
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            return events, False
        for ch in chunk.get("choices") or []:
            delta = ch.get("delta") or {}
            if delta.get("reasoning_content"):
                events.append(StreamEvent("reasoning", delta["reasoning_content"]))
            if delta.get("content"):
                events.append(StreamEvent("content", delta["content"]))
            if ch.get("finish_reason"):
                events.append(StreamEvent("done", finish_reason=ch["finish_reason"]))
        return events, False

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: ChatOptions | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """SSE 流式（仅 OpenAI 方言）：逐 delta yield StreamEvent，`[DONE]` 收 done。

        B4a 实测注意：swe-2 系是假流式——上游缓存后转发，delta 全挤在末 ~0.3s，
        TTFT≈总时长，stream 不能当进度信号；仅剩价值是 `stream_options.
        include_usage` 拿末帧 usage。
        """
        opts = options or ChatOptions()
        try:
            async with self._http.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                headers=self._openai_headers(),
                json=self._openai_body(model, messages, opts, stream=True),
            ) as resp:
                if resp.status_code != HTTP_OK:
                    await resp.aread()
                    raise classify_status(resp.status_code, resp.text, resp.headers)
                async for line in resp.aiter_lines():
                    events, done = self._sse_events(line)
                    for ev in events:
                        yield ev
                    if done:
                        return
        except (httpx.TransportError, ssl.SSLError) as e:
            msg = f"transport error: {e}"
            raise RetryableHTTPError(msg, retryable=True) from e

    async def list_models(self) -> list[str]:
        """`GET /v1/models` → 模型 id 列表。"""
        resp = await self._http.get(
            f"{self.base_url}/v1/models", headers=self._openai_headers()
        )
        if resp.status_code != HTTP_OK:
            raise classify_status(resp.status_code, resp.text, resp.headers)
        data = resp.json()
        return [m["id"] for m in data.get("data") or [] if "id" in m]

    async def panel_models(self) -> list[dict[str, Any]]:
        """`GET /panel/api/models` → 面板模型表（含 cost_tier/promo/disabled）。"""
        resp = await self._http.get(
            f"{self.base_url}/panel/api/models", headers=self._openai_headers()
        )
        if resp.status_code != HTTP_OK:
            raise classify_status(resp.status_code, resp.text, resp.headers)
        data = resp.json()
        if isinstance(data, dict):
            return [m for m in data.get("models") or [] if isinstance(m, dict)]
        if isinstance(data, list):
            return [m for m in data if isinstance(m, dict)]
        return []

    async def probe_model(self, uid: str) -> FreeModel:
        """探活单模型：一次最小 chat 往返，要求 200 + 非空 content。"""
        t0 = time.monotonic()
        try:
            resp = await self._http.post(
                f"{self.base_url}/v1/chat/completions",
                headers=self._openai_headers(),
                json={
                    "model": uid,
                    "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                    "max_tokens": PROBE_MAX_TOKENS,
                },
                timeout=PROBE_TIMEOUT,
            )
            latency = time.monotonic() - t0
            if resp.status_code != HTTP_OK:
                return FreeModel(
                    uid=uid,
                    probe_ok=False,
                    probe_error=f"HTTP {resp.status_code}",
                    probe_latency_s=round(latency, 2),
                )
            ch = (resp.json().get("choices") or [{}])[0]
            content = ((ch.get("message") or {}).get("content") or "").strip()
            ok = bool(content) and ch.get("finish_reason") in (None, "stop")
            return FreeModel(
                uid=uid,
                probe_ok=ok,
                probe_error="" if ok else "empty content or bad finish",
                probe_latency_s=round(latency, 2),
            )
        except Exception as e:  # noqa: BLE001 -- 探活对任意失败都返回不可用，绝不抛出
            return FreeModel(
                uid=uid,
                probe_ok=False,
                probe_error=redact(str(e), self.api_key)[:200],
                probe_latency_s=round(time.monotonic() - t0, 2),
            )

    async def discover_free_models(
        self, *, probe: bool = True, max_probe: int = 12
    ) -> list[FreeModel]:
        """免费集动态发现：panel 筛 free+promo.active+enabled ∩ /v1/models ∩ 探活。

        promo 到期（如 glm-5-2 2026-09-16）后该 uid 自然掉出——绝不硬编码。
        `probe=False` 只做两步交集（清单≠可用，正式选路必须 probe）。
        """
        panel = await self.panel_models()
        try:
            v1_ids = set(await self.list_models())
        except ChatError:
            v1_ids = set()  # /v1/models 挂了不挡发现路（退化为只信 panel）

        candidates: list[FreeModel] = []
        for m in panel:
            if m.get("cost_tier") != "free":
                continue
            if m.get("disabled"):
                continue
            promo = m.get("promo") or {}
            if not promo.get("active"):
                continue
            uid = str(m.get("uid") or "")
            if not uid or (v1_ids and uid not in v1_ids):
                continue
            candidates.append(
                FreeModel(
                    uid=uid,
                    promo_end=str(promo.get("end_date") or ""),
                    context_tokens=int(m.get("context_tokens") or 0),
                    max_output_tokens=int(m.get("max_output_tokens") or 0),
                    supports_thinking=bool(m.get("supports_thinking")),
                )
            )
        if not probe or not candidates:
            return candidates

        sem = asyncio.Semaphore(4)

        async def _probe(fm: FreeModel) -> FreeModel:
            async with sem:
                probed = await self.probe_model(fm.uid)
                fm.probe_ok = probed.probe_ok
                fm.probe_latency_s = probed.probe_latency_s
                fm.probe_error = probed.probe_error
                return fm

        return list(
            await asyncio.gather(*(_probe(fm) for fm in candidates[:max_probe]))
        )


def pick_model(
    discovered: list[FreeModel],
    *,
    preference: tuple[str, ...] = DEFAULT_MODEL_PREFERENCE,
    denylist: frozenset[str] = DEFAULT_MODEL_DENYLIST,
) -> str | None:
    """从探活通过的免费集里按偏好序选模型（denylist 一票否决）。"""
    alive = {m.uid for m in discovered if m.probe_ok} - set(denylist)
    pref = [u for u in preference if u in alive]
    if pref:
        return pref[0]
    return min(alive, default=None)
