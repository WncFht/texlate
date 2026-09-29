"""LLM 客户端：OpenAI/Anthropic/Responses 三方言、免费集发现、错误分类。

规格 docs/spec/translate.md：

- 默认后端 `http://127.0.0.1:3033`（本地 OpenAI 兼容网关，Chat 协议）；
  **免费集运行时动态筛**——`/panel/api/models` 按 `cost_tier=="free"` ∧
  `promo.active` ∧ `not disabled` 过滤，∩ `/v1/models`，再逐模型探活，
  **不得硬编码免费集**（promo 到期自动降级，如 glm-5-2 2026-09-16）。
- 隐藏开销：网关每请求注入 ~160–566 prompt token 上游系统提示（成本模型计入）。
- reasoning 模型（swe-2-*/deepseek/kimi-k3/inkling）：`reasoning_content` 与
  `content` 分字段返回，reasoning 也吃 max_tokens——翻译请求 max_tokens≥8192。
- BYOK：`provider_for_url` host→provider 预设表（照 texglot providers.py 形状）。

现状注记（2026-09-21）：发现链已接入生产——``chat`` 在内置免费网关上
附带模型降级臂（``fallback_candidates`` 惰性发现 + memoize，BYOK/公网
端点零探测短路）；``chat_stream`` 亦接线生产——``chat`` 的流式兜底臂
（``stream_fallback``/``TEXLATE_STREAM_FALLBACK`` opt-in，默认关）在非
流式路由疑似死亡（传输族/5xx，如 2026-09-19 网关非流式全模型 502、
stream 独活事故）时经它兜底补发，终帧 usage 回填 ``usage_sink`` 同口径
记账。

方言面（2026-09-19）：``dialect`` ∈ ``auto|openai|anthropic|responses``——
``auto``（默认）按 host 推导（仅 ``api.anthropic.com`` 落 anthropic）；
显式值面向 BYOK 异形端点（responses-only 反代、anthropic 兼容代理等
host 识别不了的形态），settings/header/env 三面同源。

出叶（hoist）：错误分类学→``_errors``、三方 dialect 编解码与结果载具
→``_dialects``、免费集发现链与端点闸→``_discovery``、SSE 行/帧解析与
流式兜底执行体→``stream``；本文件经 ``from leaf import`` 回引保持
``texlate.xlat.client.X`` 钉点面不变，``ChatClient`` 原方法名留薄委托
（monkeypatch 锚点 ``client.discover_free_models`` 等缝随调用链迁移——
叶内经 ``client.方法`` 回探，patch 语义不变）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Self, TypedDict
from urllib.parse import urlsplit

import httpx

from texlate.textutil import env_flag, env_raw
from texlate.textutil.osutil import (
    ENV_API_KEY,
    ENV_BASE_URL,
    ENV_DIALECT,
    ENV_GATEWAY_KEY,
    ENV_MODEL,
    ENV_STREAM_FALLBACK,
)
from texlate.xlat._dialects import (  # noqa: F401 -- 出叶回引：方言编解码与结果载具迁 _dialects，钉点名守恒
    _ANTHROPIC_FINISH,
    REASONING_MIN_MAX_TOKENS,
    ChatOptions,
    ChatResult,
    Usage,
    _anthropic_blocks,
    _anthropic_body,
    _anthropic_headers,
    _anthropic_usage,
    _list_field,
    _openai_body,
    _openai_headers,
    _openai_usage,
    _parse_anthropic,
    _parse_openai,
    _parse_responses,
    _require_ascii_key,
    _resp_has_refusal,
    _responses_blocks,
    _responses_body,
    _responses_message_blocks,
    _responses_reasoning_blocks,
    _responses_status_gate,
    _responses_stream_finish,
    _responses_usage,
    _str_field,
    _usage_int,
    dialect_headers,
)
from texlate.xlat._discovery import (  # noqa: F401 -- 出叶回引：发现链与端点闸迁 _discovery，钉点名守恒
    _LOOPBACK_HOSTS,
    _TAILNET_V4,
    DEFAULT_MODEL_DENYLIST,
    DEFAULT_MODEL_PREFERENCE,
    FALLBACK_MAX_CANDIDATES,
    LOOPBACK_HOSTS,
    PROBE_MAX_TOKENS,
    PROBE_TIMEOUT,
    TAILNET_V4,
    FreeModel,
    _get_json,
    _safe_int,
    discover_free_models,
    fallback_candidates,
    is_free_gateway_url,
    list_models,
    model_ids_from,
    normalize_base_url,
    panel_models,
    pick_model,
    probe_model,
    rank_models,
)
from texlate.xlat._errors import (  # noqa: F401 -- 出叶回引：错误分类学/脱敏/传输包装迁 _errors，钉点名守恒
    _SECRET_PATTERNS,
    _TRANSPORT_ERRORS,
    HTTP_BAD_REQUEST,
    HTTP_FORBIDDEN,
    HTTP_NOT_FOUND,
    HTTP_OK,
    HTTP_PAYMENT_REQUIRED,
    HTTP_TOO_MANY_REQUESTS,
    HTTP_UNAUTHORIZED,
    MAX_RETRY_AFTER_S,
    RETRYABLE_4XX,
    SERVER_ERROR_MIN,
    AuthError,
    BillingError,
    ChatError,
    ClientRejectedError,
    ContentFilterError,
    EmptyContentError,
    EndpointNotFoundError,
    LengthTruncatedError,
    MalformedResponseError,
    RetryableHTTPError,
    XlatError,
    _body_retry_after,
    _model_switchable,
    _raise_for_finish,
    _retry_after,
    _stream_rescuable,
    _transport_error,
    classify_status,
    redact,
)
from texlate.xlat.stream import (  # noqa: F401 -- 出叶回引：SSE 面迁 stream
    StreamEvent,
    _anthropic_delta_events,
    _anthropic_start_events,
    _anthropic_tail_events,
    _chat_via_stream,
    _merge_usage,
    _sse_anthropic_data,
    _sse_choice_events,
    _sse_events,
    _sse_line_events,
    _sse_responses_data,
    _stream_rescue,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- 常量

#: read=300 给 bg 类请求的闸内排队留余量——网关 fg/bg 分级下 bg 可排队
#: ~120s 才开始出首字节，read 覆盖 TTFB（每次 read 间隔计时，非全程预算）
DEFAULT_TIMEOUT = httpx.Timeout(180.0, connect=10.0, read=300.0)

#: 网关默认端点/模型——server.settings 与 fixloop.llm_hook 的兜底共同
#: 引这里，防两处字面量漂移（settings 侧是 UX 缺省，hook 侧是 env 兜底，
#: 指向同一网关事实）。默认本地网关；任意 OpenAI 兼容端点可经
#: TEXLATE_BASE_URL / server Settings 页覆盖
DEFAULT_BASE_URL = "http://127.0.0.1:3033"
DEFAULT_MODEL = DEFAULT_MODEL_PREFERENCE[0]

#: ``chat`` 流式兜底臂开关 env（``ChatClient(stream_fallback=)`` 显式值优先）。
#: 默认关：失败路径请求数钉在降级臂合同内（半死网关不放大）；网关非流式
#: 路由退化（2026-09-19 非流式全模型 502、stream 独活形态）时操作员一键开——
#: 名本体注册在 ``textutil.osutil``，同名回引


# ---------------------------------------------------------------- provider 识别（host→provider，照 texglot providers.py）


def provider_for_url(base_url: str) -> str:
    """Hostname → provider id。原则：按可信 API host 识别，绝不看模型名。"""
    try:
        host = (urlsplit(base_url).hostname or "").lower()
    except ValueError:
        host = ""  # 畸形 URL 按未知 host 处理（落空到 "custom"），请求期 InvalidURL→ChatError 再报
    if host in LOOPBACK_HOSTS:
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


#: provider → 环境变量名（BYOK 读 key 的约定，docs/spec/translate.md）
PROVIDER_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "gateway": ENV_GATEWAY_KEY,
    "custom": ENV_API_KEY,
}


def env_key_for_url(base_url: str) -> str:
    """``TEXLATE_API_KEY`` 直读，空则按 ``PROVIDER_KEY_ENV[provider_for_url(base_url)]`` 兜底专名 env。

    provider 键兜底单源——server ``env_key_for`` 与 fixloop ``_env_key_for``
    曾各带一份同逻辑副本（``llm_hook`` 注记「正式单源待提升 ``xlat.client``」）。
    调用方须传**已决议**端点（默认网关也算）才够得着
    ``TEXLATE_GATEWAY_KEY``/``DASHSCOPE_API_KEY`` 等专名 env。
    """
    api_key = env_raw(ENV_API_KEY)
    if api_key:
        return api_key
    env_name = PROVIDER_KEY_ENV.get(provider_for_url(base_url), ENV_API_KEY)
    return env_raw(env_name)


def env_credentials() -> tuple[str, str, str, str]:
    """``TEXLATE_*`` 凭证四件套统一读法 → ``(base_url, api_key, model, dialect)``。

    ``api_key`` 走 ``env_key_for_url``（``TEXLATE_API_KEY`` 优先 + provider
    专名 env 兜底）；provider 按 ``base_url or DEFAULT_BASE_URL`` 决议——
    env 未配端点时默认网关的 ``TEXLATE_GATEWAY_KEY`` 也读得到。
    model/dialect 原样透传——校验归各调用面边界（``validate_*``）。
    """
    base_url = env_raw(ENV_BASE_URL)
    return (
        base_url,
        env_key_for_url(base_url or DEFAULT_BASE_URL),
        env_raw(ENV_MODEL),
        env_raw(ENV_DIALECT),
    )


#: provider → 请求方言（"openai" = /v1/chat/completions；"anthropic" = /v1/messages）
_PROVIDER_DIALECT: dict[str, str] = {
    "anthropic": "anthropic",
}
#: 显式方言值（settings/header/env/ctor 白名单；"auto" = 按 host 推导）
_DIALECT_VALUES = frozenset({"openai", "anthropic", "responses"})
#: settings 写径枚举——含 ``auto`` 缺省值；``ChatClient(dialect=)`` 同款
API_DIALECTS = frozenset({"auto"} | _DIALECT_VALUES)


def _dialect_for(provider: str, dialect: str | None) -> str:
    """生效方言：``auto``/空 → provider 映射；显式值校验原样，非法 ValueError。"""
    if dialect in (None, "", "auto"):
        return _PROVIDER_DIALECT.get(provider, "openai")
    if dialect in _DIALECT_VALUES:
        return dialect
    msg = f"unknown dialect {dialect!r}（expect {sorted(API_DIALECTS)}）"
    raise ValueError(msg)


def dialect_for_url(base_url: str, dialect: str | None = None) -> str:
    """按 base_url + 配置值推生效方言——``ChatClient`` 外的展示面（doctor 等）共用。"""
    return _dialect_for(provider_for_url(base_url), dialect)


class UsageRecord(TypedDict):
    """``usage_sink`` 回调载荷——一次成功 ``chat()`` 的记账单元（T4）。

    ``Translator`` 协议只回 ``str``，token/延迟在边界被丢弃；挂 sink 后
    每次成功响应把 usage+latency 递出（失败的 HTTP 调用无 usage 可报）。
    """

    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float


# ---------------------------------------------------------------- 客户端


class ChatClient:
    """异步 chat 客户端：OpenAI 兼容 / Anthropic 双方言 + 网关免费集发现。

    用法::

        async with ChatClient("http://127.0.0.1:3033", "sk-your-key") as c:
            r = await c.chat("your-model", messages, temperature=0.2, max_tokens=8192)
    """

    def __init__(  # noqa: PLR0913 -- endpoint/key + provider/dialect/timeout/http + usage_sink 全是独立旋钮
        self,
        base_url: str,
        api_key: str = "",
        *,
        provider: str | None = None,
        dialect: str | None = None,
        timeout: httpx.Timeout | None = None,
        http: httpx.AsyncClient | None = None,
        usage_sink: Callable[[UsageRecord], None] | None = None,
        stream_fallback: bool | None = None,
    ) -> None:
        """按 base_url 自动识别 provider/方言；`http` 传入外部 client 时不自持。

        ``dialect``：``None``/``""``/``"auto"`` → 按 provider 推导；显式值
        （``_DIALECT_VALUES``）面向 host 识别不了的 BYOK 异形端点——
        responses-only 反代、非 ``api.anthropic.com`` 的 anthropic 兼容代理。
        ``stream_fallback``：``None`` → ``TEXLATE_STREAM_FALLBACK`` env
        （默认关——失败路径请求数钉在降级臂合同内）；开则 ``chat`` 在
        「非流式路由死亡」形错误上经 ``chat_stream`` 兜底补发。
        """
        self.base_url = normalize_base_url(base_url)
        self.api_key = api_key
        self.provider = provider or provider_for_url(base_url)
        self.dialect = _dialect_for(self.provider, dialect)
        self._own = http is None
        self._http = http or httpx.AsyncClient(
            timeout=timeout or DEFAULT_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
        #: 每次成功 ``chat()`` 后调用的记账回调（可后挂——worker 侧接线点）
        self.usage_sink = usage_sink
        #: ``chat`` 流式兜底臂开关（见 ``ENV_STREAM_FALLBACK`` 注记）
        self._stream_fallback = (
            stream_fallback
            if stream_fallback is not None
            else env_flag(ENV_STREAM_FALLBACK, default=False)
        )
        #: 免费集降级臂 memoize：None=未跑过发现；[]=非内置网关或发现失败
        self._free_uids: list[str] | None = None
        self._discovery_lock = asyncio.Lock()

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

    # ------------------------------------------------------------ 方言薄委托（实现体出叶 _dialects）

    def _require_ascii_key(self) -> None:
        """非 ASCII api_key 前置类型化——实现体出叶 ``_dialects._require_ascii_key``。"""
        _require_ascii_key(self.api_key)

    def _openai_headers(self) -> dict[str, str]:
        """OpenAI Bearer 头——实现体出叶 ``_dialects._openai_headers``。"""
        return _openai_headers(self.api_key)

    @staticmethod
    def _openai_body(
        model: str,
        messages: list[dict[str, str]],
        options: ChatOptions,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        """OpenAI 请求体组装——实现体出叶 ``_dialects._openai_body``。"""
        return _openai_body(model, messages, options, stream=stream)

    @staticmethod
    def _openai_usage(usage_raw: object) -> Usage:
        """OpenAI ``usage`` → ``Usage``——实现体出叶 ``_dialects._openai_usage``。"""
        return _openai_usage(usage_raw)

    def _parse_openai(self, payload: dict[str, Any], latency: float) -> ChatResult:
        """OpenAI 200 体 → ``ChatResult``——实现体出叶 ``_dialects._parse_openai``。"""
        return _parse_openai(payload, latency)

    def _anthropic_headers(self) -> dict[str, str]:
        """Anthropic 头——实现体出叶 ``_dialects._anthropic_headers``。"""
        return _anthropic_headers(self.api_key)

    @staticmethod
    def _anthropic_body(
        model: str,
        messages: list[dict[str, str]],
        options: ChatOptions,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        """Anthropic 请求体——实现体出叶 ``_dialects._anthropic_body``。"""
        return _anthropic_body(model, messages, options, stream=stream)

    @staticmethod
    def _anthropic_blocks(payload: dict[str, Any]) -> tuple[str, str]:
        """Content 块列 → (text 合, thinking 合)——实现体出叶 ``_dialects._anthropic_blocks``。"""
        return _anthropic_blocks(payload)

    @staticmethod
    def _anthropic_usage(u: object, field: str) -> Usage | None:
        """``usage`` 子帧 → ``Usage``——实现体出叶 ``_dialects._anthropic_usage``。"""
        return _anthropic_usage(u, field)

    def _parse_anthropic(self, payload: dict[str, Any], latency: float) -> ChatResult:
        """Anthropic 200 体 → ``ChatResult``——实现体出叶 ``_dialects._parse_anthropic``。"""
        return _parse_anthropic(payload, latency, self.api_key)

    @staticmethod
    def _responses_body(
        model: str,
        messages: list[dict[str, str]],
        options: ChatOptions,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        """Responses 请求体——实现体出叶 ``_dialects._responses_body``。"""
        return _responses_body(model, messages, options, stream=stream)

    @staticmethod
    def _list_field(value: object, what: str) -> list[Any]:
        """列表字段形状闸——实现体出叶 ``_dialects._list_field``。"""
        return _list_field(value, what)

    @staticmethod
    def _str_field(blk: dict[str, Any], key: str, what: str) -> str:
        """标量字段形状闸——实现体出叶 ``_dialects._str_field``。"""
        return _str_field(blk, key, what)

    @staticmethod
    def _responses_message_blocks(
        item: dict[str, Any], texts: list[str], refusals: list[str]
    ) -> None:
        """``message`` item content 块累加——实现体出叶 ``_dialects._responses_message_blocks``。"""
        _responses_message_blocks(item, texts, refusals)

    @staticmethod
    def _responses_reasoning_blocks(item: dict[str, Any], thinks: list[str]) -> None:
        """``reasoning`` item summary 块累加——实现体出叶 ``_dialects._responses_reasoning_blocks``。"""
        _responses_reasoning_blocks(item, thinks)

    @staticmethod
    def _responses_blocks(payload: dict[str, Any]) -> tuple[str, str, list[str]]:
        """``output`` items → (text 合, reasoning 合, refusal 列)——实现体出叶 ``_dialects._responses_blocks``。"""
        return _responses_blocks(payload)

    @staticmethod
    def _responses_usage(usage_raw: object) -> Usage:
        """Responses ``usage`` → ``Usage``——实现体出叶 ``_dialects._responses_usage``。"""
        return _responses_usage(usage_raw)

    def _responses_status_gate(
        self,
        payload: dict[str, Any],
        status: str,
        content: str,
        refusals: list[str],
    ) -> None:
        """``status``/refusal 终态闸——实现体出叶 ``_dialects._responses_status_gate``。"""
        _responses_status_gate(payload, status, content, refusals, self.api_key)

    def _parse_responses(self, payload: dict[str, Any], latency: float) -> ChatResult:
        """Responses 200 体 → ``ChatResult``——实现体出叶 ``_dialects._parse_responses``。"""
        return _parse_responses(payload, latency, self.api_key)

    @staticmethod
    def _responses_stream_finish(resp: object, *, incomplete: bool) -> str:
        """Responses 终帧 → openai 词表 finish_reason——实现体出叶 ``_dialects._responses_stream_finish``。"""
        return _responses_stream_finish(resp, incomplete=incomplete)

    # ------------------------------------------------------------ 公开 API

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: ChatOptions | None = None,
    ) -> ChatResult:
        """一次 chat 调用；模型降级臂 + 流式兜底臂双保险。

        候选序 = 请求模型 → ``fallback_candidates`` 的免费集（偏好序、
        惰性发现、memoize；BYOK/公网端点恒空、零探测）。模型级失败
        （``_model_switchable``：404 摘除/429/5xx/空响应/截断）按序
        换候选各补一发；传输/auth/计费/请求级错误不切模直接上抛。

        流式兜底臂（opt-in：``stream_fallback`` 旋钮/``TEXLATE_STREAM_FALLBACK``
        开才生效，默认关——失败路径请求数钉在降级臂合同内）：对
        ``_stream_rescuable`` 判定的「非流式路由死亡」形错误（传输族/5xx，
        2026-09-19 网关非流式全模型 502、stream 独活实证），非切模型级
        错误原地经 ``chat_stream`` 补一发（无候选可枚举）；切模型级错误
        先走降级枚举，非流式链全员阵亡后再给最后一个路由死亡形的模型
        补一发。补发失败一律回落原错误链语义（``last`` 上抛不变）。
        ``probe_model`` 走 ``_chat_once`` 直发、刻意不经此臂——流式
        半死网关上探活会挂死，须保持单发快败。
        """
        opts = options or ChatOptions()
        try:
            return await self._chat_once(model, messages, opts)
        except ChatError as e:
            if not _model_switchable(e):
                # 非切模型级错误只有「路由死亡」形（传输族）值得流式臂原地
                # 补一发；auth/计费/4xx/畸形 URL 等判死错误直接上抛
                return await self._rescue_or_raise(model, messages, opts, e)
            log.warning("model %s 失败（%s）→ 枚举免费集降级候选", model, e)
            return await self._chat_fallback(model, messages, opts, e)

    async def _rescue_or_raise(
        self,
        model: str,
        messages: list[dict[str, str]],
        opts: ChatOptions,
        err: ChatError,
    ) -> ChatResult:
        """非切模型级错误的流式臂兜底——补发成功回结果，否则原错误上抛。"""
        rescued = await self._stream_rescue(model, messages, opts, err)
        if rescued is not None:
            return rescued
        raise err

    async def _chat_fallback(
        self,
        model: str,
        messages: list[dict[str, str]],
        opts: ChatOptions,
        first_err: ChatError,
    ) -> ChatResult:
        """模型降级臂执行体：枚举免费集逐候选补发，全灭后流式补最后一发。

        中途见过「路由死亡」形错误（``_stream_rescuable``）就记下该模型，
        非流式链全员阵亡后给它经 ``chat_stream`` 补一发（2026-09-19 网关
        非流式 502、stream 独活的事故形态）；补发也死 → 上抛 ``last``
        （最后观察错误语义不变）。
        """
        last = first_err
        rescue_target: tuple[str, ChatError] | None = (
            (model, first_err) if _stream_rescuable(first_err) else None
        )
        for uid in await self.fallback_candidates():
            if uid == model:
                continue
            try:
                return await self._chat_once(uid, messages, opts)
            except ChatError as e:
                if not _model_switchable(e):
                    return await self._rescue_or_raise(uid, messages, opts, e)
                if _stream_rescuable(e):
                    rescue_target = (uid, e)
                log.warning("model %s 失败（%s）→ 换下一免费集候选", uid, e)
                last = e
        if rescue_target is not None:
            rescued = await self._stream_rescue(
                rescue_target[0], messages, opts, rescue_target[1]
            )
            if rescued is not None:
                return rescued
        raise last

    def _request_plan(
        self,
        model: str,
        messages: list[dict[str, str]],
        opts: ChatOptions,
        *,
        stream: bool,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        """方言 → (url, headers, body) 三元组——``_chat_once``/``chat_stream`` 同源。"""
        if self.dialect == "anthropic":
            return (
                f"{self.base_url}/v1/messages",
                self._anthropic_headers(),
                self._anthropic_body(model, messages, opts, stream=stream),
            )
        if self.dialect == "responses":
            return (
                f"{self.base_url}/v1/responses",
                self._openai_headers(),
                self._responses_body(model, messages, opts, stream=stream),
            )
        return (
            f"{self.base_url}/v1/chat/completions",
            self._openai_headers(),
            self._openai_body(model, messages, opts, stream=stream),
        )

    def _parse_payload(self, payload: dict[str, Any], latency: float) -> ChatResult:
        """方言 → 解析器分发。"""
        if self.dialect == "anthropic":
            return self._parse_anthropic(payload, latency)
        if self.dialect == "responses":
            return self._parse_responses(payload, latency)
        return self._parse_openai(payload, latency)

    def _status_gate(self, resp: httpx.Response) -> None:
        """非 200 → ``classify_status`` 分类抛错；``_chat_once``/``chat_stream``/``_get_json`` 同源。"""
        if resp.status_code != HTTP_OK:
            raise classify_status(
                resp.status_code, redact(resp.text, self.api_key), resp.headers
            )

    def _emit_usage(self, result: ChatResult) -> None:
        """``usage_sink`` 记账——成功往返恰一笔；回调炸不拖垮调用。"""
        sink = self.usage_sink
        if sink is None:
            return
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

    async def _chat_once(
        self,
        model: str,
        messages: list[dict[str, str]],
        opts: ChatOptions,
        *,
        req_timeout: httpx.Timeout | None = None,
    ) -> ChatResult:
        """单模型单次 chat 往返。错误已按 `classify_status` 分类；length/empty 也抛错。

        ``req_timeout`` 为单次请求覆盖（探活收紧用）；None = 跟随 client 默认——
        绝不传 ``None`` 进 ``post()``（httpx 的 None 是「关超时」而非「默认」）。
        """
        t0 = time.monotonic()
        kw: dict[str, Any] = {"timeout": req_timeout} if req_timeout is not None else {}
        url, headers, body = self._request_plan(model, messages, opts, stream=False)
        try:
            resp = await self._http.post(url, headers=headers, json=body, **kw)
        except _TRANSPORT_ERRORS as e:
            raise _transport_error(e) from e
        latency = time.monotonic() - t0

        self._status_gate(resp)
        try:
            payload = resp.json()
        except (json.JSONDecodeError, RecursionError) as e:
            msg = f"non-JSON response: {redact(resp.text[:200], self.api_key)}"
            raise MalformedResponseError(msg) from e
        if not isinstance(payload, dict):
            msg = f"non-object JSON response: {redact(resp.text[:200], self.api_key)}"
            raise MalformedResponseError(msg)
        result = self._parse_payload(payload, latency)
        self._emit_usage(result)
        return result

    # ------------------------------------------------------------ SSE 薄委托（实现体出叶 stream）

    async def _stream_rescue(
        self,
        model: str,
        messages: list[dict[str, str]],
        opts: ChatOptions,
        err: ChatError,
    ) -> ChatResult | None:
        """流式兜底臂入口——实现体出叶 ``stream._stream_rescue``。"""
        return await _stream_rescue(self, model, messages, opts, err)

    async def _chat_via_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        opts: ChatOptions,
    ) -> ChatResult:
        """聚 ``chat_stream`` deltas → ``ChatResult``——实现体出叶 ``stream._chat_via_stream``。"""
        return await _chat_via_stream(self, model, messages, opts)

    @staticmethod
    def _sse_choice_events(ch: dict[str, Any]) -> list[StreamEvent]:
        """单个 SSE choice 成员 → 事件列——实现体出叶 ``stream._sse_choice_events``。"""
        return _sse_choice_events(ch)

    @staticmethod
    def _sse_events(line: str) -> tuple[list[StreamEvent], bool]:
        """一行 SSE ``data:`` → (events, done?)——实现体出叶 ``stream._sse_events``。"""
        return _sse_events(line)

    def _sse_line_events(self, line: str) -> tuple[list[StreamEvent], bool]:
        """一行 SSE → (events, done?) 按方言分发——实现体出叶 ``stream._sse_line_events``。"""
        return _sse_line_events(self.dialect, self.api_key, line)

    def _sse_anthropic_data(
        self, chunk: dict[str, Any]
    ) -> tuple[list[StreamEvent], bool]:
        """Anthropic SSE payload → (events, done?)——实现体出叶 ``stream._sse_anthropic_data``。"""
        return _sse_anthropic_data(chunk, self.api_key)

    @staticmethod
    def _anthropic_delta_events(chunk: dict[str, Any]) -> list[StreamEvent]:
        """``content_block_delta`` 帧 → 增量事件——实现体出叶 ``stream._anthropic_delta_events``。"""
        return _anthropic_delta_events(chunk)

    @staticmethod
    def _anthropic_start_events(chunk: dict[str, Any]) -> list[StreamEvent]:
        """``message_start`` 帧 → ``input_tokens`` 载体事件——实现体出叶 ``stream._anthropic_start_events``。"""
        return _anthropic_start_events(chunk)

    @staticmethod
    def _anthropic_tail_events(
        chunk: dict[str, Any],
    ) -> tuple[list[StreamEvent], bool]:
        """``message_delta`` 帧 → 终态/usage 载体事件——实现体出叶 ``stream._anthropic_tail_events``。"""
        return _anthropic_tail_events(chunk)

    def _sse_responses_data(
        self, chunk: dict[str, Any]
    ) -> tuple[list[StreamEvent], bool]:
        """Responses SSE payload → (events, done?)——实现体出叶 ``stream._sse_responses_data``。"""
        return _sse_responses_data(chunk, self.api_key)

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: ChatOptions | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """SSE 流式：逐 delta yield StreamEvent，终帧收 done（三方言各自事件族）。

        B4a 实测注意：swe-2 系是假流式——上游缓存后转发，delta 全挤在末 ~0.3s，
        TTFT≈总时长，stream 不能当进度信号；价值在两块——``stream_options.
        include_usage`` 拿末帧 usage 记账、非流式路由死亡时独活兜底。

        现状：生产消费方 = ``chat`` 的流式兜底臂（``_chat_via_stream``，
        opt-in：``stream_fallback``/``TEXLATE_STREAM_FALLBACK`` 开才生效，
        见模块 docstring 注记）；其余仍仅 tests/smoke 消费。
        """
        opts = options or ChatOptions()
        url, headers, body = self._request_plan(model, messages, opts, stream=True)
        try:
            async with self._http.stream(
                "POST",
                url,
                headers=headers,
                json=body,
            ) as resp:
                if resp.status_code != HTTP_OK:
                    await resp.aread()  # 流式响应须先收齐 body 才有 .text 拼错误消息
                self._status_gate(resp)
                async for line in resp.aiter_lines():
                    events, done = self._sse_line_events(line)
                    for ev in events:
                        yield ev
                    if done:
                        return
        except _TRANSPORT_ERRORS as e:
            raise _transport_error(e) from e

    # ------------------------------------------------------------ 发现薄委托（实现体出叶 _discovery）

    async def _get_json(self, path: str) -> tuple[Any, str]:
        """``GET {base_url}{path}`` → (parsed JSON, 脱敏摘要)——实现体出叶 ``_discovery._get_json``。"""
        return await _get_json(self, path)

    async def list_models(self) -> list[str]:
        """`GET /v1/models` → 模型 id 列表——实现体出叶 ``_discovery.list_models``。"""
        return await list_models(self)

    async def panel_models(self) -> list[dict[str, Any]]:
        """`GET /panel/api/models` → 面板模型表——实现体出叶 ``_discovery.panel_models``。"""
        return await panel_models(self)

    async def probe_model(self, uid: str) -> FreeModel:
        """探活单模型：一次最小 chat 往返——实现体出叶 ``_discovery.probe_model``。"""
        return await probe_model(self, uid)

    async def discover_free_models(
        self, *, probe: bool = True, max_probe: int = 12
    ) -> list[FreeModel]:
        """免费集动态发现——实现体出叶 ``_discovery.discover_free_models``。"""
        return await discover_free_models(self, probe=probe, max_probe=max_probe)

    async def fallback_candidates(self) -> list[str]:
        """免费集降级候选 uid 表——实现体出叶 ``_discovery.fallback_candidates``。"""
        return await fallback_candidates(self)
