"""xlat 错误面：ChatError 分类学 + HTTP 状态归类 + 臂级判据 + 脱敏/传输包装。

``client.py`` 出叶（hoist）：HTTP/协议层错误分类学、``classify_status``
状态码→异常映射（docs/spec/translate.md HTTP 层）、``_model_switchable``
（``chat`` 降级臂切模判据）/``_stream_rescuable``（流式兜底臂补发判据）、
``_raise_for_finish`` 终态闸、secret 脱敏原语与传输族异常包装——全部经
``client`` 门面回引，``from texlate.xlat.client import X`` 钉点面不变。
叶子不引 ``client``（环断）。
"""

from __future__ import annotations

import json
import ssl

import httpx

from texlate.textutil.secrets import SECRET_PATTERNS as _SECRET_PATTERNS

# ---------------------------------------------------------------- 常量

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


def _stream_rescuable(e: ChatError) -> bool:
    """非流式路由疑似死亡（传输族/5xx）——``chat`` 流式兜底臂的补发判据。

    200 合同违约族（空响应/截断/畸形/过滤）与 4xx 判定级错误不补——换协议
    不更换算/判定结果，只白多一请求。传输族（``status<0``）与 5xx 才是
    「非流式路由死了、stream 可能独活」的实测形态（2026-09-19 网关非流式
    全模型 502 事故）。注意与 ``_model_switchable`` 正交：传输错误不切模
    （同端点同死）但值得补发——换的是协议路径不是模型。
    """
    return isinstance(e, RetryableHTTPError) and (
        e.status < 0 or e.status >= SERVER_ERROR_MIN
    )


def _raise_for_finish(finish: str, content: str, *, detail: str = "") -> None:
    """finish_reason 异常态早抛——``length``/``content_filter``/空正文三分支。

    ``content_filter`` 携带的半截正文不可用——静默接受会把过滤截断译文落盘。
    ``detail`` 带方言侧原始诊断（anthropic ``stop_reason`` 原文、responses
    ``incomplete_details.reason``/refusal 文本），``[..]`` 尾缀进错误消息。
    """
    suffix = f" [{detail}]" if detail else ""
    if finish == "length" and not content:
        msg = (
            "finish_reason=length with empty content "
            f"(reasoning model burned the whole budget?){suffix}"
        )
        raise LengthTruncatedError(msg)
    if finish == "length":
        msg = f"finish_reason=length: output truncated{suffix}"
        raise LengthTruncatedError(msg, partial_content=content)
    if finish == "content_filter":
        msg = (
            f"finish_reason=content_filter: provider filtered request/response{suffix}"
        )
        raise ContentFilterError(msg)
    if not content.strip():
        msg = f"empty content in response{suffix}"
        raise EmptyContentError(msg)


# ---------------------------------------------------------------- 脱敏

#: 严档 secret 形态表——单源 ``textutil.secrets.SECRET_PATTERNS``，本模块
#: 别名转口保 ``xlat._errors._SECRET_PATTERNS``（及 ``client`` 回引链）
#: 钉点名不变；覆盖不变量 ``tests/test_secret_patterns.py`` 钉住。


def redact(text: str, api_key: str = "") -> str:
    """抹掉已知 secret 形态 + 显式 api_key 值（provider 无关脱敏）。"""
    out = text
    if api_key:
        out = out.replace(api_key, "***")
    for rx in _SECRET_PATTERNS:
        out = rx.sub("***", out)
    return out


#: 传输族异常四元组——``except`` 子句直接吃元组；``_chat_once``/``chat_stream``/``_get_json`` 同源
_TRANSPORT_ERRORS = (
    httpx.InvalidURL,
    httpx.TransportError,
    httpx.DecodingError,
    ssl.SSLError,
)


def _transport_error(e: Exception) -> ChatError:
    """HTTP 传输族异常 → ChatError 分类：``httpx.InvalidURL``→``ChatError``（非重试），其余→``RetryableHTTPError``。"""
    if isinstance(e, httpx.InvalidURL):
        return ChatError(f"invalid request URL: {e}")
    return RetryableHTTPError(f"transport error: {e}", retryable=True)
