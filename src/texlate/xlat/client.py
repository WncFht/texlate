"""LLM 客户端：OpenAI/Anthropic/Responses 三方言、免费集发现、错误分类。

规格 docs/spec/translate.md

- 默认后端 `http://127.0.0.1:3033`（本地 OpenAI 兼容网关，Chat 协议）；
  **免费集运行时动态筛**——`/panel/api/models` 按 `cost_tier=="free"` ∧
  `promo.active` ∧ `not disabled` 过滤，∩ `/v1/models`，再逐模型探活，
  **不得硬编码免费集**（promo 到期自动降级，如 glm-5-2 2026-09-16）。
- 隐藏开销：网关每请求注入 ~160–566 prompt token 上游系统提示（成本模型计入）。
- reasoning 模型（swe-2-*/deepseek/kimi-k3/inkling）：`reasoning_content` 与
  `content` 分字段返回，reasoning 也吃 max_tokens——翻译请求 max_tokens≥8192。
- BYOK：`provider_for_url` host→provider 预设表（照 texglot providers.py 形状）。

现状注记（2026-09-17）：发现链已接入生产——``chat`` 在内置免费网关上
附带模型降级臂（``fallback_candidates`` 惰性发现 + memoize，BYOK/公网
端点零探测短路）；``chat_stream`` 仍仅 bench/test/网关 smoke 消费。

方言面（2026-09-19）：``dialect`` ∈ ``auto|openai|anthropic|responses``——
``auto``（默认）按 host 推导（仅 ``api.anthropic.com`` 落 anthropic）；
显式值面向 BYOK 异形端点（responses-only 反代、anthropic 兼容代理等
host 识别不了的形态），settings/header/env 三面同源。
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import ssl
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Self, TypedDict
from urllib.parse import urlsplit

import httpx

from texlate.textutil import env_raw

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- 常量

#: reasoning 模型最小输出预算（思考先烧预算，16 token 会全耗在思考上 → content 空）
REASONING_MIN_MAX_TOKENS = 8192
#: 探活请求预算（只要求非空 content，给思考留 1k 余量足够）
PROBE_MAX_TOKENS = 1024
#: read=300 给 bg 类请求的闸内排队留余量——网关 fg/bg 分级下 bg 可排队
#: ~120s 才开始出首字节，read 覆盖 TTFB（每次 read 间隔计时，非全程预算）
DEFAULT_TIMEOUT = httpx.Timeout(180.0, connect=10.0, read=300.0)
PROBE_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

#: 网关默认端点/模型——server.settings 与 fixloop.llm_hook 的兜底共同
#: 引这里，防两处字面量漂移（settings 侧是 UX 缺省，hook 侧是 env 兜底，
#: 指向同一网关事实）。默认本地网关；任意 OpenAI 兼容端点可经
#: TEXLATE_BASE_URL / server Settings 页覆盖
DEFAULT_BASE_URL = "http://127.0.0.1:3033"
#: 免费集偏好序（动态发现后按此排序——不是免费集本身，命中才选；
#: 自有网关按实际模型集调整或经 TEXLATE_MODEL 指定）
DEFAULT_MODEL_PREFERENCE = ("swe-2-medium", "swe-2-high", "swe-2-max", "glm-5-2")
DEFAULT_MODEL = DEFAULT_MODEL_PREFERENCE[0]
#: 免费集禁用名单（契约事故史/不可预算）
DEFAULT_MODEL_DENYLIST = frozenset({"swe-1-7", "swe-1-7-medium"})
#: 单次 chat 降级臂最多补发候选数（对齐 §1.7 备选链深度 medium→high→max，
#: 防半死网关上一次调用放大成十数发——外层 ``call_with_backoff`` 还会整体重试）
FALLBACK_MAX_CANDIDATES = 3

#: HTTP 状态码（classify 判定表）
HTTP_OK = 200
HTTP_BAD_REQUEST = 400
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


# ---------------------------------------------------------------- 错误分类（docs/spec/translate.md HTTP 层）


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


class ContentFilterError(ChatError):
    """上游内容过滤拒答（400 ``error.code`` / 200 ``finish_reason`` / anthropic ``refusal``）。

    按内容判死的确定性拒绝：同模重试必同死，但**换模有救**（过滤策略随
    provider/模型而异；上游 BabelDOC #580 多模降级臂生产实证同判）。
    ``retryable=True`` 不为同模退避（``max_tries=1`` 零翻身防放大），
    是喂两处既有臂：``_model_switchable`` 末行 ``e.retryable`` 放行进
    ``fallback_candidates`` 换模；``_batch_call`` ``not retryable→整批
    skip`` 短路转 degrade-to-singles——一个毒 chunk 不再把整批拖回原文。
    ``status`` 记真实 HTTP 码（200 形=合同违约族，400 形=请求拒绝）。
    """

    def __init__(self, message: str, *, status: int = HTTP_OK) -> None:
        """过滤拒答：retryable + 总尝试数封顶 1（换模臂内消化，不同模重试）。"""
        super().__init__(message, status=status, retryable=True, max_tries=1)


class RetryableHTTPError(ChatError):
    """408/409/425/429/5xx——可重试（429 用 `3^attempt`、下限 5s；Retry-After 从其值）。"""


class LengthTruncatedError(ChatError):
    """`finish_reason=="length"`——输出被截断，属可重试的合同违约（调大 max_tokens）。

    ``max_tries=2`` 对齐 EmptyContentError：调用点内层已做 8k→32k 放大
    重试，外层再吃满 policy.max_tries 会把慢性截断块放大到 ~10 请求/块
    （audit 2026-09-16）。封顶后单模型 ≤4 次 API 调用；免费集降级臂命中时
    每个候选再各起一轮（≤ ``FALLBACK_MAX_CANDIDATES`` 个）。
    ``status`` 记 200——与 Empty/Malformed 同族合同违约，退避走
    base·2^attempt 而非 timeout_floor（status<0 会被当传输超时）。
    """

    def __init__(self, message: str, *, partial_content: str = "") -> None:
        """截断错误：携带已收到的部分正文（可留作降级材料）。"""
        super().__init__(message, status=HTTP_OK, retryable=True, max_tries=2)
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


class MalformedResponseError(ChatError):
    """HTTP 200 但响应体非协议形态（非 JSON / choices 空 / 形状不符）。

    与 ``EmptyContentError`` 同族——200 合同违约而非传输故障：网关/前置
    代理瞬时吐 HTML 错误页或半截 JSON 是实测形态，retryable 才有翻身机会；
    ``max_tries=2`` 封顶（持续畸形 = 端点坏了，不烧满 policy 上限）。
    ``status`` 记 200 让退避走 base·2^attempt、降级臂判定 switchable。
    """

    def __init__(self, message: str) -> None:
        """畸形 200 响应：retryable + 总尝试数封顶 2。"""
        super().__init__(message, status=HTTP_OK, retryable=True, max_tries=2)


def _retry_after(headers: httpx.Headers) -> float | None:
    """解析 Retry-After 头（秒数或 HTTP-date）；>60s 不等直接拒。"""
    raw = headers.get("retry-after")
    if not raw:
        return None
    raw = raw.strip()
    # isascii 闸：str.isdigit 覆盖 Unicode No 类（²³¹ 等上标——latin-1 线上字节
    # 0xB9/0xB2/0xB3 解码形态），float() 解析不了它们，不闸会漏 ValueError
    if raw.isascii() and raw.isdigit():
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
    except (json.JSONDecodeError, TypeError, RecursionError):
        # RecursionError：网关可构造 KB 级超深嵌套（[~20000 层撞解释器上限）
        return None
    err = data.get("error") if isinstance(data, dict) else None
    raw = err.get("retry_after") if isinstance(err, dict) else None
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        secs = float(raw)
        return secs if 0 <= secs <= MAX_RETRY_AFTER_S else None
    return None


def classify_status(
    status: int, redacted_body: str, headers: httpx.Headers
) -> ChatError:
    """HTTP 状态码 → 异常类型（docs/spec/translate.md 状态码分类表 + B4a 429 body 修订）。

    429 的 retry_after 解析序：body `error.retry_after` → header `Retry-After`
    → 无（退 `3^attempt` 下限 5s）。429 是多租户共享流量触发（healthz 常驻他户
    22~26 active），与本地并发宽度无关——不为它缩 Semaphore。

    ``redacted_body`` 契约=调用侧已按自家 api_key 脱敏的响应体（字面 key
    只有调用侧知道，函数内模式级 ``redact`` 管不了它）；进异常消息前再
    过一次 ``redact``（幂等——pattern 级 secret 形态的防御兜底，预脱敏
    文本二次过不变）。``_body_retry_after`` 吃同一脱敏串——脱敏可能把
    JSON 搅坏致 retry_after 解析不到，属可接受降级（回退 header/默认）。
    """
    msg = f"HTTP {status}: {redact(redacted_body)[:300]}"
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
            retry_after = _body_retry_after(redacted_body) or retry_after
        return RetryableHTTPError(
            msg, status=status, retryable=True, retry_after=retry_after
        )
    if status == HTTP_BAD_REQUEST and "content_filter" in redacted_body:
        return ContentFilterError(msg, status=status)
    return ClientRejectedError(msg, status=status)


def _model_switchable(e: ChatError) -> bool:
    """换模型可能有救的失败（免费集降级臂的切模判据）。

    404 = 模型从清单摘除（promo 到期形态）；HTTP/合同级 retryable
    （429/5xx/408/409/425/空响应/截断）换候选有救。传输错误
    （status<0——同端点同死）、auth/计费/其余 4xx 不切。
    本地闸门快败（"local gate"）不切：拒绝发自令牌级排队预算而非
    模型/上游，换候选同令牌同队列只是白占闸位，交回上层按
    retry_after 退避等本模型窗口。
    """
    if isinstance(e, EndpointNotFoundError):
        return True
    if isinstance(e, RetryableHTTPError) and e.status < 0:
        return False
    if e.status == HTTP_TOO_MANY_REQUESTS and "local gate" in str(e):
        return False
    return e.retryable


def _raise_for_finish(finish: str, content: str) -> None:
    """finish_reason 异常态早抛——``length``/``content_filter``/空正文三分支。

    ``content_filter`` 携带的半截正文不可用——静默接受会把过滤截断译文落盘。
    """
    if finish == "length" and not content:
        msg = (
            "finish_reason=length with empty content "
            "(reasoning model burned the whole budget?)"
        )
        raise LengthTruncatedError(msg)
    if finish == "length":
        msg = "finish_reason=length: output truncated"
        raise LengthTruncatedError(msg, partial_content=content)
    if finish == "content_filter":
        msg = "finish_reason=content_filter: provider filtered request/response"
        raise ContentFilterError(msg)
    if not content.strip():
        msg = "empty content in response"
        raise EmptyContentError(msg)


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
    supports_thinking: bool = False
    probe_ok: bool = False
    probe_latency_s: float = 0.0
    probe_error: str = ""


# ---------------------------------------------------------------- provider 识别（host→provider，照 texglot providers.py）


def provider_for_url(base_url: str) -> str:
    """Hostname → provider id。原则：按可信 API host 识别，绝不看模型名。"""
    try:
        host = (urlsplit(base_url).hostname or "").lower()
    except ValueError:
        host = ""  # 畸形 URL 按未知 host 处理（落空到 "custom"），请求期 InvalidURL→ChatError 再报
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


#: provider → 环境变量名（BYOK 读 key 的约定，docs/spec/translate.md）
PROVIDER_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "gateway": "TEXLATE_GATEWAY_KEY",
    "custom": "TEXLATE_API_KEY",
}


def env_credentials() -> tuple[str, str, str, str]:
    """``TEXLATE_*`` 凭证四件套统一读法 → ``(base_url, api_key, model, dialect)``。

    ``api_key`` 按 provider 映射兜底：``TEXLATE_API_KEY`` 优先、空则按
    ``PROVIDER_KEY_ENV`` 的 host 专名 env 再读——server ``env_key_for``
    与 cli/llm_hook 裸读曾在此分叉（BYOK 专名 env 在非 server 臂读不到）。
    model/dialect 原样透传——校验归各调用面边界（``validate_*``）。
    """
    base_url = env_raw("TEXLATE_BASE_URL")
    api_key = env_raw("TEXLATE_API_KEY")
    if not api_key:
        env_name = PROVIDER_KEY_ENV.get(provider_for_url(base_url), "TEXLATE_API_KEY")
        api_key = env_raw(env_name)
    return (
        base_url,
        api_key,
        env_raw("TEXLATE_MODEL"),
        env_raw("TEXLATE_DIALECT"),
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


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
#: tailnet CGNAT 段（与 ``settings._is_plaintext_ok_host`` 同信任域——
#: 自有网段上跑的只会是部署方自有服务，探活打过去不烧第三方 quota）
_TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")


def is_free_gateway_url(base_url: str) -> bool:
    """内置免费网关判定：host ∈ loopback ∪ tailnet（CGNAT / ``*.ts.net``）。

    发现/探活链只准打这个面——公网 BYOK 预设（anthropic/deepseek/qwen/
    openai）与任意 custom 公网端点一律 False，一个探测请求都不发。
    ``provider_for_url`` 单独不能当闸：默认 tailnet 网关解析成
    ``"custom"``，BYOK 也可以是 custom——端点身份只能看网络位置。
    """
    try:
        host = (urlsplit(normalize_base_url(base_url)).hostname or "").lower()
    except ValueError:
        return False  # 畸形 URL 必非内置网关——发现/探活面零放行
    if host in _LOOPBACK_HOSTS or host.endswith(".ts.net"):
        return True
    try:
        return ipaddress.ip_address(host) in _TAILNET_V4
    except ValueError:
        return False


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


def _usage_int(value: object) -> int:
    """响应 usage 数值字段 → int；非数值/非有限值（str 不可解析、容器、NaN/inf）一律 ``MalformedResponseError``。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError) as e:
        msg = f"usage field is not a finite integer (got {type(value).__name__})"
        raise MalformedResponseError(msg) from e


def _resp_has_refusal(resp: dict[str, Any]) -> bool:
    """Responses 终帧 ``response`` 对象是否含 refusal 块（``_sse_responses_data`` 用）。"""
    output = resp.get("output")
    if not isinstance(output, list):
        return False
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "refusal":
                return True
    return False


def _transport_error(e: Exception) -> ChatError:
    """HTTP 传输族异常 → ChatError 分类：``httpx.InvalidURL``→``ChatError``（非重试），其余→``RetryableHTTPError``。"""
    if isinstance(e, httpx.InvalidURL):
        return ChatError(f"invalid request URL: {e}")
    return RetryableHTTPError(f"transport error: {e}", retryable=True)


def _safe_int(value: object) -> int:
    """面板元数据字段 → int；coerce 失败退化 0——展示元数据非合同字段，单字段畸形不挡成员入集。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


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
    ) -> None:
        """按 base_url 自动识别 provider/方言；`http` 传入外部 client 时不自持。

        ``dialect``：``None``/``""``/``"auto"`` → 按 provider 推导；显式值
        （``_DIALECT_VALUES``）面向 host 识别不了的 BYOK 异形端点——
        responses-only 反代、非 ``api.anthropic.com`` 的 anthropic 兼容代理。
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

    # ------------------------------------------------------------ OpenAI 方言

    def _require_ascii_key(self) -> None:
        """非 ASCII api_key 前置类型化——否则在请求头 ASCII 编码期炸 UnicodeEncodeError 裸逃。"""
        if not self.api_key.isascii():
            msg = "api_key contains non-ASCII characters"
            raise ChatError(msg)

    def _openai_headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        self._require_ascii_key()
        return {"Authorization": f"Bearer {self.api_key}"}

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

    def _parse_openai(self, payload: dict[str, Any], latency: float) -> ChatResult:
        """OpenAI 200 体 → ``ChatResult``；结构形状不符一律 ``MalformedResponseError``。

        强校验只覆盖结构形状（choices/message/usage 容器类型、content 为
        str、usage 字段可数值化）；标量字段类型污染（finish_reason/model/
        reasoning_content 非 str 原样穿透）属观测容忍面，不在此拦。
        """
        choices = payload.get("choices") or []
        if not isinstance(choices, list) or not choices:
            msg = "response has no choices"
            raise MalformedResponseError(msg)
        ch = choices[0]
        if not isinstance(ch, dict):
            msg = "choices[0] is not an object"
            raise MalformedResponseError(msg)
        msg_obj = ch.get("message") or {}
        if not isinstance(msg_obj, dict):
            msg = "message field is not an object"
            raise MalformedResponseError(msg)
        content = msg_obj.get("content") or ""
        if not isinstance(content, str):
            msg = "message.content is not a string"
            raise MalformedResponseError(msg)
        reasoning = msg_obj.get("reasoning_content") or ""
        finish = ch.get("finish_reason") or ""
        usage_raw = payload.get("usage") or {}
        if not isinstance(usage_raw, dict):
            msg = "usage field is not an object"
            raise MalformedResponseError(msg)
        details = usage_raw.get("prompt_tokens_details") or {}
        if not isinstance(details, dict):
            msg = "usage.prompt_tokens_details is not an object"
            raise MalformedResponseError(msg)
        usage = Usage(
            prompt_tokens=_usage_int(usage_raw.get("prompt_tokens")),
            completion_tokens=_usage_int(usage_raw.get("completion_tokens")),
            cached_tokens=_usage_int(details.get("cached_tokens")),
            raw=usage_raw,
        )
        _raise_for_finish(finish, content)
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
        self._require_ascii_key()
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
    def _anthropic_blocks(payload: dict[str, Any]) -> tuple[str, str]:
        """响应 content 块列 → (text 合, thinking 合)；形状不符一律 ``MalformedResponseError``。"""
        raw = payload.get("content") or []
        if not isinstance(raw, list):
            msg = "content field is not a list"
            raise MalformedResponseError(msg)
        texts: list[str] = []
        thinks: list[str] = []
        for blk in raw:
            if not isinstance(blk, dict):
                msg = "content block is not an object"
                raise MalformedResponseError(msg)
            if blk.get("type") == "text":
                text = blk.get("text") or ""
                if not isinstance(text, str):
                    msg = "text block value is not a string"
                    raise MalformedResponseError(msg)
                texts.append(text)
            elif blk.get("type") == "thinking":
                thinking = blk.get("thinking") or ""
                if not isinstance(thinking, str):
                    msg = "thinking block value is not a string"
                    raise MalformedResponseError(msg)
                thinks.append(thinking)
        return "".join(texts), "".join(thinks)

    def _parse_anthropic(self, payload: dict[str, Any], latency: float) -> ChatResult:
        """Anthropic 200 体 → ``ChatResult``；结构形状不符一律 ``MalformedResponseError``。"""
        if payload.get("type") == "error":
            err = payload.get("error") or {}
            if not isinstance(err, dict):
                msg = "error field is not an object"
                raise MalformedResponseError(msg)
            detail = redact(str(err.get("message") or ""), self.api_key)
            msg = f"anthropic error {err.get('type')}: {detail}"
            raise ChatError(msg)
        content, reasoning = self._anthropic_blocks(payload)
        finish = payload.get("stop_reason") or ""
        if finish == "max_tokens" and not content:
            msg = "anthropic stop_reason=max_tokens, empty"
            raise LengthTruncatedError(msg)
        if finish == "max_tokens":
            msg = "anthropic stop_reason=max_tokens"
            raise LengthTruncatedError(msg, partial_content=content)
        if finish == "refusal":
            msg = "anthropic stop_reason=refusal"
            raise ContentFilterError(msg)
        if not content.strip():
            msg = "empty content in response"
            raise EmptyContentError(msg)
        u = payload.get("usage") or {}
        if not isinstance(u, dict):
            msg = "usage field is not an object"
            raise MalformedResponseError(msg)
        return ChatResult(
            content=content,
            reasoning=reasoning,
            finish_reason=finish,
            usage=Usage(
                prompt_tokens=_usage_int(u.get("input_tokens")),
                completion_tokens=_usage_int(u.get("output_tokens")),
                cached_tokens=_usage_int(u.get("cache_read_input_tokens")),
                raw=u,
            ),
            model=payload.get("model") or "",
            latency_s=round(latency, 3),
        )

    # ------------------------------------------------------------ Responses 方言

    @staticmethod
    def _responses_body(
        model: str,
        messages: list[dict[str, str]],
        options: ChatOptions,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        """Responses 请求体：system→``instructions``；会话角色→``input`` message items。

        ``max_tokens``→``max_output_tokens``；``response_format``→``text.format``
        原样透传（``{"type": "json_object"}`` 等形状两家同构）。
        """
        instructions = "\n".join(
            m["content"] for m in messages if m["role"] == "system"
        )
        items: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "system":
                continue
            ctype = "output_text" if m["role"] == "assistant" else "input_text"
            items.append(
                {
                    "type": "message",
                    "role": m["role"],
                    "content": [{"type": ctype, "text": m["content"]}],
                }
            )
        body: dict[str, Any] = {"model": model, "input": items}
        if instructions:
            body["instructions"] = instructions
        if options.temperature is not None:
            body["temperature"] = options.temperature
        if options.max_tokens is not None:
            body["max_output_tokens"] = options.max_tokens
        if options.response_format is not None:
            body["text"] = {"format": options.response_format}
        if stream:
            body["stream"] = True
        if options.extra:
            body.update(options.extra)
        return body

    @staticmethod
    def _list_field(value: object, what: str) -> list[Any]:
        """Responses ``payload`` 列表字段形状闸——非 list 一律 ``MalformedResponseError``。"""
        if isinstance(value, list):
            return value
        msg = f"{what} field is not a list"
        raise MalformedResponseError(msg)

    @staticmethod
    def _str_field(blk: dict[str, Any], key: str, what: str) -> str:
        """Responses 块标量字段形状闸——非 str 一律 ``MalformedResponseError``。"""
        v = blk.get(key) or ""
        if not isinstance(v, str):
            msg = f"{what} value is not a string"
            raise MalformedResponseError(msg)
        return v

    @staticmethod
    def _responses_message_blocks(
        item: dict[str, Any], texts: list[str], refusals: list[str]
    ) -> None:
        """``message`` item 的 content 块 → texts/refusals 累加（形状闸同 ``_list/_str_field``）。"""
        for blk in ChatClient._list_field(item.get("content") or [], "message content"):
            if not isinstance(blk, dict):
                msg = "content block is not an object"
                raise MalformedResponseError(msg)
            bt = blk.get("type")
            if bt == "output_text":
                texts.append(ChatClient._str_field(blk, "text", "output_text"))
            elif bt == "refusal":
                refusals.append(ChatClient._str_field(blk, "refusal", "refusal"))

    @staticmethod
    def _responses_reasoning_blocks(item: dict[str, Any], thinks: list[str]) -> None:
        """``reasoning`` item 的 summary 块 → thinks 累加。"""
        for s in ChatClient._list_field(item.get("summary") or [], "reasoning summary"):
            if not isinstance(s, dict):
                msg = "summary item is not an object"
                raise MalformedResponseError(msg)
            if s.get("type") == "summary_text":
                thinks.append(ChatClient._str_field(s, "text", "summary_text"))

    @staticmethod
    def _responses_blocks(payload: dict[str, Any]) -> tuple[str, str, list[str]]:
        """``output`` items → (text 合, reasoning summary 合, refusal 列)；形状不符一律 ``MalformedResponseError``。"""
        texts: list[str] = []
        thinks: list[str] = []
        refusals: list[str] = []
        for item in ChatClient._list_field(payload.get("output") or [], "output"):
            if not isinstance(item, dict):
                msg = "output item is not an object"
                raise MalformedResponseError(msg)
            it = item.get("type")
            if it == "message":
                ChatClient._responses_message_blocks(item, texts, refusals)
            elif it == "reasoning":
                ChatClient._responses_reasoning_blocks(item, thinks)
        return "".join(texts), "".join(thinks), refusals

    def _responses_status_gate(
        self, payload: dict[str, Any], status: str, content: str, refusals: list[str]
    ) -> None:
        """``status``/refusal 终态闸——异常态全在此抛错（``_parse_responses`` 分支减压）。

        映射：refusal 块→``ContentFilterError``；``failed``/``cancelled``→
        ``ChatError``；``incomplete``→reason 分 ``content_filter``/``length``
        （其余 reason 一律 length——产出未完的归约与 ``finish_reason=length``
        同族）；``queued``/``in_progress`` 等非终态→``MalformedResponseError``
        （非 background 模式不应出现）。
        """
        if refusals:
            detail = redact(" ".join(refusals), self.api_key)
            msg = f"responses refusal block: {detail[:200]}"
            raise ContentFilterError(msg)
        if status in ("failed", "cancelled"):
            err = payload.get("error") or {}
            if not isinstance(err, dict):
                msg = "error field is not an object"
                raise MalformedResponseError(msg)
            detail = redact(str(err.get("message") or status), self.api_key)
            msg = f"responses status={status}: {detail}"
            raise ChatError(msg)
        if status == "incomplete":
            det = payload.get("incomplete_details") or {}
            if not isinstance(det, dict):
                msg = "incomplete_details field is not an object"
                raise MalformedResponseError(msg)
            reason = str(det.get("reason") or "")
            if reason == "content_filter":
                msg = f"responses incomplete: {reason}"
                raise ContentFilterError(msg)
            msg = f"responses incomplete: {reason or 'unknown'}"
            raise LengthTruncatedError(msg, partial_content=content)
        if status != "completed":
            msg = f"unexpected response status {status!r}"
            raise MalformedResponseError(msg)

    def _parse_responses(self, payload: dict[str, Any], latency: float) -> ChatResult:
        """Responses 200 体 → ``ChatResult``；``finish_reason`` 归一成 openai 词表。"""
        if payload.get("type") == "error":
            err = payload.get("error") or {}
            if not isinstance(err, dict):
                msg = "error field is not an object"
                raise MalformedResponseError(msg)
            detail = redact(str(err.get("message") or ""), self.api_key)
            msg = f"responses error {err.get('code')}: {detail}"
            raise ChatError(msg)
        content, reasoning, refusals = self._responses_blocks(payload)
        status = str(payload.get("status") or "completed")
        self._responses_status_gate(payload, status, content, refusals)
        if not content.strip():
            msg = "empty content in response"
            raise EmptyContentError(msg)
        usage_raw = payload.get("usage") or {}
        if not isinstance(usage_raw, dict):
            msg = "usage field is not an object"
            raise MalformedResponseError(msg)
        details = usage_raw.get("input_tokens_details") or {}
        if not isinstance(details, dict):
            msg = "usage.input_tokens_details is not an object"
            raise MalformedResponseError(msg)
        return ChatResult(
            content=content,
            reasoning=reasoning,
            finish_reason="stop",
            usage=Usage(
                prompt_tokens=_usage_int(usage_raw.get("input_tokens")),
                completion_tokens=_usage_int(usage_raw.get("output_tokens")),
                cached_tokens=_usage_int(details.get("cached_tokens")),
                raw=usage_raw,
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
        """一次 chat 调用；内置免费网关上附带模型降级臂。

        候选序 = 请求模型 → ``fallback_candidates`` 的免费集（偏好序、
        惰性发现、memoize；BYOK/公网端点恒空、零探测）。模型级失败
        （``_model_switchable``：404 摘除/429/5xx/空响应/截断）按序
        换候选各补一发；传输/auth/计费/请求级错误不切模直接上抛。
        """
        opts = options or ChatOptions()
        try:
            return await self._chat_once(model, messages, opts)
        except ChatError as e:
            if not _model_switchable(e):
                raise
            last = e
            log.warning("model %s 失败（%s）→ 枚举免费集降级候选", model, e)
        for uid in await self.fallback_candidates():
            if uid == model:
                continue
            try:
                return await self._chat_once(uid, messages, opts)
            except ChatError as e:
                if not _model_switchable(e):
                    raise
                log.warning("model %s 失败（%s）→ 换下一免费集候选", uid, e)
                last = e
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
        except (
            httpx.InvalidURL,
            httpx.TransportError,
            httpx.DecodingError,
            ssl.SSLError,
        ) as e:
            raise _transport_error(e) from e
        latency = time.monotonic() - t0

        if resp.status_code != HTTP_OK:
            raise classify_status(
                resp.status_code, redact(resp.text, self.api_key), resp.headers
            )
        try:
            payload = resp.json()
        except (json.JSONDecodeError, RecursionError) as e:
            msg = f"non-JSON response: {redact(resp.text[:200], self.api_key)}"
            raise MalformedResponseError(msg) from e
        if not isinstance(payload, dict):
            msg = f"non-object JSON response: {redact(resp.text[:200], self.api_key)}"
            raise MalformedResponseError(msg)
        result = self._parse_payload(payload, latency)
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
    def _sse_choice_events(ch: dict[str, Any]) -> list[StreamEvent]:
        """单个 SSE choice 成员 → 事件列；``delta`` 非 dict 的畸形成员回空。"""
        delta = ch.get("delta") or {}
        if not isinstance(delta, dict):
            return []
        events: list[StreamEvent] = []
        if delta.get("reasoning_content"):
            events.append(StreamEvent("reasoning", delta["reasoning_content"]))
        if delta.get("content"):
            events.append(StreamEvent("content", delta["content"]))
        if ch.get("finish_reason"):
            events.append(StreamEvent("done", finish_reason=ch["finish_reason"]))
        return events

    @staticmethod
    def _sse_events(line: str) -> tuple[list[StreamEvent], bool]:
        """解析一行 SSE `data:` payload → (events, done?)；非 data/坏 JSON/形状错一律跳过。"""
        events: list[StreamEvent] = []
        if not line.startswith("data:"):
            return events, False
        data = line[5:].strip()
        if data == "[DONE]":
            return [StreamEvent(kind="done")], True
        try:
            chunk = json.loads(data)
        except (json.JSONDecodeError, RecursionError):
            return events, False
        if not isinstance(chunk, dict):
            return events, False
        choices = chunk.get("choices") or []
        if not isinstance(choices, list):
            return events, False
        for ch in choices:
            if isinstance(ch, dict):
                events.extend(ChatClient._sse_choice_events(ch))
        return events, False

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: ChatOptions | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """SSE 流式：逐 delta yield StreamEvent，终帧收 done（三方言各自事件族）。

        B4a 实测注意：swe-2 系是假流式——上游缓存后转发，delta 全挤在末 ~0.3s，
        TTFT≈总时长，stream 不能当进度信号；仅剩价值是 `stream_options.
        include_usage` 拿末帧 usage。

        现状：无生产调用方（仅 tests/bench 消费，见模块 docstring 注记）。
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
                    await resp.aread()
                    raise classify_status(
                        resp.status_code, redact(resp.text, self.api_key), resp.headers
                    )
                async for line in resp.aiter_lines():
                    events, done = self._sse_line_events(line)
                    for ev in events:
                        yield ev
                    if done:
                        return
        except (
            httpx.InvalidURL,
            httpx.TransportError,
            httpx.DecodingError,
            ssl.SSLError,
        ) as e:
            raise _transport_error(e) from e

    def _sse_line_events(self, line: str) -> tuple[list[StreamEvent], bool]:
        """一行 SSE → (events, done?)——按方言分发 payload 解析。

        openai 走 ``_sse_events``（choices/[DONE] 族）；anthropic/responses
        的 ``event:`` 行冗余（``data:`` payload 自带 ``type`` 字段），
        只解 ``data:`` JSON 分发。
        """
        if self.dialect == "openai":
            return self._sse_events(line)
        events: list[StreamEvent] = []
        done = False
        if line.startswith("data:"):
            try:
                chunk = json.loads(line[5:].strip())
            except (json.JSONDecodeError, RecursionError):
                chunk = None
            if isinstance(chunk, dict):
                if self.dialect == "anthropic":
                    events, done = self._sse_anthropic_data(chunk)
                elif self.dialect == "responses":
                    events, done = self._sse_responses_data(chunk)
        return events, done

    def _sse_anthropic_data(
        self, chunk: dict[str, Any]
    ) -> tuple[list[StreamEvent], bool]:
        """Anthropic SSE payload → (events, done?)；``error`` 帧抛 ``ChatError``。"""
        t = chunk.get("type")
        events: list[StreamEvent] = []
        done = False
        if t == "content_block_delta":
            d = chunk.get("delta") or {}
            if isinstance(d, dict):
                if d.get("type") == "text_delta" and d.get("text"):
                    events.append(StreamEvent("content", str(d["text"])))
                elif d.get("type") == "thinking_delta" and d.get("thinking"):
                    events.append(StreamEvent("reasoning", str(d["thinking"])))
        elif t == "message_delta":
            d = chunk.get("delta") or {}
            stop = d.get("stop_reason") if isinstance(d, dict) else None
            if stop:
                events.append(StreamEvent("done", finish_reason=str(stop)))
                done = True
        elif t == "message_stop":
            events.append(StreamEvent(kind="done"))
            done = True
        elif t == "error":
            err = chunk.get("error") or {}
            detail = err.get("message") if isinstance(err, dict) else str(chunk)
            msg = f"anthropic stream error: {redact(str(detail), self.api_key)}"
            raise ChatError(msg)
        return events, done

    def _sse_responses_data(
        self, chunk: dict[str, Any]
    ) -> tuple[list[StreamEvent], bool]:
        """Responses SSE payload → (events, done?)；``error``/``response.failed`` 帧抛 ``ChatError``。

        终帧 ``finish_reason`` 归一到 openai 词表：completed→stop；
        incomplete→reason 分 content_filter/length（refusal 块同判 filter）；
        ``response.completed``/``incomplete`` 带完整 response 对象——refusal
        只在终帧层查，逐 ``refusal.delta`` 不单独成事件（与非流式
        ``_parse_responses`` 同口径）。
        """
        t = chunk.get("type")
        events: list[StreamEvent] = []
        done = False
        if t in (
            "response.output_text.delta",
            "response.reasoning_text.delta",
            "response.reasoning_summary_text.delta",
        ):
            delta = chunk.get("delta")
            if isinstance(delta, str) and delta:
                kind = "content" if t == "response.output_text.delta" else "reasoning"
                events.append(StreamEvent(kind, delta))
        elif t in ("response.completed", "response.incomplete"):
            events.append(
                StreamEvent(
                    "done",
                    finish_reason=self._responses_stream_finish(
                        chunk.get("response"), incomplete=t == "response.incomplete"
                    ),
                )
            )
            done = True
        elif t in ("response.failed", "error"):
            resp = chunk.get("response") or chunk
            err = resp.get("error") or {} if isinstance(resp, dict) else {}
            detail = err.get("message") if isinstance(err, dict) else str(chunk)
            msg = f"responses stream error: {redact(str(detail), self.api_key)}"
            raise ChatError(msg)
        return events, done

    @staticmethod
    def _responses_stream_finish(resp: object, *, incomplete: bool) -> str:
        """Responses 终帧 ``response`` 对象 → openai 词表 finish_reason。

        completed→stop；incomplete→reason 分 content_filter/length；
        refusal 块任何终态都判 content_filter。
        """
        if not isinstance(resp, dict):
            return "length" if incomplete else "stop"
        if _resp_has_refusal(resp):
            return "content_filter"
        if not incomplete:
            return "stop"
        det = resp.get("incomplete_details") or {}
        reason = det.get("reason") if isinstance(det, dict) else None
        return "content_filter" if reason == "content_filter" else "length"

    async def _get_json(self, path: str) -> tuple[Any, str]:
        """``GET {base_url}{path}`` → (parsed JSON, 脱敏 body 摘要)。

        传输/HTTP 状态/JSON 解析错误按 ``_chat_once`` 同口径分类抛出；
        返回的 ``snippet``（响应体前 200 字符脱敏）留给调用方拼形状错误消息。
        """
        try:
            resp = await self._http.get(
                f"{self.base_url}{path}", headers=self._openai_headers()
            )
        except (
            httpx.InvalidURL,
            httpx.TransportError,
            httpx.DecodingError,
            ssl.SSLError,
        ) as e:
            raise _transport_error(e) from e
        if resp.status_code != HTTP_OK:
            raise classify_status(
                resp.status_code, redact(resp.text, self.api_key), resp.headers
            )
        snippet = redact(resp.text[:200], self.api_key)
        try:
            return resp.json(), snippet
        except (json.JSONDecodeError, RecursionError) as e:
            msg = f"non-JSON response: {snippet}"
            raise MalformedResponseError(msg) from e

    async def list_models(self) -> list[str]:
        """`GET /v1/models` → 模型 id 列表。"""
        data, snippet = await self._get_json("/v1/models")
        if not isinstance(data, dict):
            msg = f"non-object JSON response: {snippet}"
            raise MalformedResponseError(msg)
        items = data.get("data") or []
        if not isinstance(items, list):
            msg = f"unexpected data field: {snippet}"
            raise MalformedResponseError(msg)
        return [str(m["id"]) for m in items if isinstance(m, dict) and "id" in m]

    async def panel_models(self) -> list[dict[str, Any]]:
        """`GET /panel/api/models` → 面板模型表（含 cost_tier/promo/disabled）。"""
        data, snippet = await self._get_json("/panel/api/models")
        if isinstance(data, dict):
            models = data.get("models") or []
            # 可迭代但非 list（str/dict）走逐成员过滤回 []；不可迭代标量
            # （int/bool/float）与 list_models 的 data 字段同口径报畸形
            if not isinstance(models, Iterable):
                msg = f"unexpected models field: {snippet}"
                raise MalformedResponseError(msg)
            return [m for m in models if isinstance(m, dict)]
        if isinstance(data, list):
            return [m for m in data if isinstance(m, dict)]
        return []

    async def probe_model(self, uid: str) -> FreeModel:
        """探活单模型：一次最小 chat 往返（方言随 ``self.dialect``），要求非空 content。

        复用 ``_chat_once``——request 组装/响应解析/错误分类三方口径一致，
        ``PROBE_TIMEOUT`` 经其单次请求覆盖收紧。
        """
        t0 = time.monotonic()
        try:
            r = await self._chat_once(
                uid,
                [{"role": "user", "content": "Reply with exactly: OK"}],
                ChatOptions(max_tokens=PROBE_MAX_TOKENS),
                req_timeout=PROBE_TIMEOUT,
            )
        except Exception as e:  # noqa: BLE001 -- 探活对任意失败都返回不可用，绝不抛出
            return FreeModel(
                uid=uid,
                probe_ok=False,
                probe_error=redact(str(e), self.api_key)[:200],
                probe_latency_s=round(time.monotonic() - t0, 2),
            )
        ok = bool(r.content.strip()) and r.finish_reason in (
            "",
            "stop",
            "end_turn",
            "stop_sequence",
        )
        return FreeModel(
            uid=uid,
            probe_ok=ok,
            probe_error=""
            if ok
            else f"empty content or bad finish ({r.finish_reason})",
            probe_latency_s=round(r.latency_s, 2),
        )

    async def discover_free_models(
        self, *, probe: bool = True, max_probe: int = 12
    ) -> list[FreeModel]:
        """免费集动态发现：panel 筛 free+promo.active+enabled ∩ /v1/models ∩ 探活。

        promo 到期（如 glm-5-2 2026-09-16）后该 uid 自然掉出——绝不硬编码。
        `probe=False` 只做两步交集（清单≠可用，正式选路必须 probe）。
        生产调用方：``fallback_candidates``（``chat`` 降级臂经此枚举）。
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
            promo = m.get("promo")
            if not isinstance(promo, dict) or not promo.get("active"):
                continue
            uid = str(m.get("uid") or "")
            if not uid or (v1_ids and uid not in v1_ids):
                continue
            candidates.append(
                FreeModel(
                    uid=uid,
                    promo_end=str(promo.get("end_date") or ""),
                    context_tokens=_safe_int(m.get("context_tokens")),
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

    async def fallback_candidates(self) -> list[str]:
        """免费集降级候选 uid 表（``rank_models`` 偏好序）：惰性发现 + memoize。

        非内置网关（``is_free_gateway_url`` False）与发现链任何失败一律
        返回 []——BYOK/公网端点一个探测请求都不发，调用方静默退化为
        静态模型行为。``chat`` 降级臂与 worker 侧枚举共用此面。
        候选数封顶 ``FALLBACK_MAX_CANDIDATES``。
        """
        if not is_free_gateway_url(self.base_url):
            return []
        if self._free_uids is None:
            async with self._discovery_lock:
                if self._free_uids is None:
                    try:
                        self._free_uids = rank_models(await self.discover_free_models())
                    except Exception as e:  # noqa: BLE001 -- 发现失败静默退化，绝不挡 chat
                        log.warning("免费集发现失败（%s）——模型降级臂停用", e)
                        self._free_uids = []
        return self._free_uids[:FALLBACK_MAX_CANDIDATES]


def rank_models(
    discovered: list[FreeModel],
    *,
    preference: tuple[str, ...] = DEFAULT_MODEL_PREFERENCE,
    denylist: frozenset[str] = DEFAULT_MODEL_DENYLIST,
) -> list[str]:
    """探活通过的免费集 → 有序候选 uid 表（denylist 剔除；偏好序在前，其余按 uid 字典序）。"""
    alive = {m.uid for m in discovered if m.probe_ok} - set(denylist)
    pref = [u for u in preference if u in alive]
    return pref + sorted(alive - set(pref))


def pick_model(
    discovered: list[FreeModel],
    *,
    preference: tuple[str, ...] = DEFAULT_MODEL_PREFERENCE,
    denylist: frozenset[str] = DEFAULT_MODEL_DENYLIST,
) -> str | None:
    """从探活通过的免费集里按偏好序选模型（denylist 一票否决）。"""
    ranked = rank_models(discovered, preference=preference, denylist=denylist)
    return ranked[0] if ranked else None
