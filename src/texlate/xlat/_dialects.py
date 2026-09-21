"""xlat 方言编解码：openai/anthropic/responses 三族的请求头/请求体/响应解析。

``client.py`` 出叶（hoist）：原 ``ChatClient`` 方法体转模块级纯函数——
要凭证的吃 ``api_key`` 形参，``ChatClient`` 侧留薄委托方法（钉点名不变）。
usage/结果载具 ``Usage``/``ChatResult``/``ChatOptions`` 同驻本叶——三族
解析器与 ``stream``/``client`` 的共用词汇表；``_ANTHROPIC_FINISH`` 词表
与 ``_responses_stream_finish`` 归一亦在此（非流式 status 闸与
``stream`` 的 SSE 终帧两侧共用）。叶子不引 ``client``（环断）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from texlate.xlat._errors import (
    ChatError,
    MalformedResponseError,
    _raise_for_finish,
    redact,
)

#: reasoning 模型最小输出预算（思考先烧预算，16 token 会全耗在思考上 → content 空）
REASONING_MIN_MAX_TOKENS = 8192


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


@dataclass(frozen=True)
class ChatOptions:
    """一次 chat 调用的可选参数包（None 字段不写进请求体）。"""

    temperature: float | None = None
    max_tokens: int | None = None
    response_format: dict[str, str] | None = None
    extra: dict[str, Any] | None = None


# ---------------------------------------------------------------- 共用形状闸


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


def _require_ascii_key(api_key: str) -> None:
    """非 ASCII api_key 前置类型化——否则在请求头 ASCII 编码期炸 UnicodeEncodeError 裸逃。"""
    if not api_key.isascii():
        msg = "api_key contains non-ASCII characters"
        raise ChatError(msg)


# ---------------------------------------------------------------- OpenAI 方言


def _openai_headers(api_key: str) -> dict[str, str]:
    """OpenAI Bearer 头——空 key 不发 Authorization。"""
    if not api_key:
        return {}
    _require_ascii_key(api_key)
    return {"Authorization": f"Bearer {api_key}"}


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
        # 末帧 usage 是流式唯一的记账来源——``chat`` 流式兜底臂靠它回填
        # ``usage_sink``（不带此参的端点静默不返 usage 帧，兜底按零记账）
        body["stream_options"] = {"include_usage": True}
    if options.extra:
        body.update(options.extra)
    return body


def _openai_usage(usage_raw: object) -> Usage:
    """OpenAI ``usage`` 对象 → ``Usage``——``_parse_openai`` 与 SSE 末帧同闸。"""
    if not isinstance(usage_raw, dict):
        msg = "usage field is not an object"
        raise MalformedResponseError(msg)
    details = usage_raw.get("prompt_tokens_details") or {}
    if not isinstance(details, dict):
        msg = "usage.prompt_tokens_details is not an object"
        raise MalformedResponseError(msg)
    return Usage(
        prompt_tokens=_usage_int(usage_raw.get("prompt_tokens")),
        completion_tokens=_usage_int(usage_raw.get("completion_tokens")),
        cached_tokens=_usage_int(details.get("cached_tokens")),
        raw=usage_raw,
    )


def _parse_openai(payload: dict[str, Any], latency: float) -> ChatResult:
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
    usage = _openai_usage(payload.get("usage") or {})
    _raise_for_finish(finish, content)
    return ChatResult(
        content=content,
        reasoning=reasoning,
        finish_reason=finish,
        usage=usage,
        model=payload.get("model") or "",
        latency_s=round(latency, 3),
    )


# ---------------------------------------------------------------- Anthropic 方言

#: anthropic ``stop_reason`` → openai ``finish_reason`` 词表（``_raise_for_finish``
#: 只吃后者）——``_parse_anthropic`` 的唯一映射点；未收录值原样穿透，
#: ``end_turn``/``stop_sequence``/``tool_use`` 等非异常终态不进异常分支，
#: 原词保留进 ``ChatResult.finish_reason``（``probe_model`` 认 ``end_turn``/
#: ``stop_sequence``——``tool_use`` 不在其接受集，探活无 tools 正常不会出现）
_ANTHROPIC_FINISH: dict[str, str] = {
    "max_tokens": "length",
    "refusal": "content_filter",
}


def _anthropic_headers(api_key: str) -> dict[str, str]:
    """Anthropic 头——恒发 ``x-api-key``（空 key 也发空值）+ 版本钉。"""
    _require_ascii_key(api_key)
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }


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
    if options.extra:
        body.update(options.extra)
    return body


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


def _anthropic_usage(u: object, field: str) -> Usage | None:
    """``usage`` 子帧 → ``Usage``；畸形回 ``None``（行级容错，不挡流本身）。

    ``field`` ∈ ``input_tokens``（``message_start`` 帧）/
    ``output_tokens``（``message_delta`` 帧）——anthropic 把两侧计数
    拆在两帧报，``_chat_via_stream`` 端靠 ``_merge_usage`` 合并。
    """
    if not isinstance(u, dict):
        return None
    try:
        n = _usage_int(u.get(field))
    except MalformedResponseError:
        return None
    if field == "input_tokens":
        return Usage(prompt_tokens=n, raw=u)
    return Usage(completion_tokens=n, raw=u)


def _parse_anthropic(
    payload: dict[str, Any], latency: float, api_key: str
) -> ChatResult:
    """Anthropic 200 体 → ``ChatResult``；结构形状不符一律 ``MalformedResponseError``。"""
    if payload.get("type") == "error":
        err = payload.get("error") or {}
        if not isinstance(err, dict):
            msg = "error field is not an object"
            raise MalformedResponseError(msg)
        detail = redact(str(err.get("message") or ""), api_key)
        msg = f"anthropic error {err.get('type')}: {detail}"
        raise ChatError(msg)
    content, reasoning = _anthropic_blocks(payload)
    finish = payload.get("stop_reason") or ""
    _raise_for_finish(
        _ANTHROPIC_FINISH.get(finish, finish),
        content,
        detail=f"stop_reason={finish}" if finish else "",
    )
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


# ---------------------------------------------------------------- Responses 方言


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
    instructions = "\n".join(m["content"] for m in messages if m["role"] == "system")
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


def _list_field(value: object, what: str) -> list[Any]:
    """Responses ``payload`` 列表字段形状闸——非 list 一律 ``MalformedResponseError``。"""
    if isinstance(value, list):
        return value
    msg = f"{what} field is not a list"
    raise MalformedResponseError(msg)


def _str_field(blk: dict[str, Any], key: str, what: str) -> str:
    """Responses 块标量字段形状闸——非 str 一律 ``MalformedResponseError``。"""
    v = blk.get(key) or ""
    if not isinstance(v, str):
        msg = f"{what} value is not a string"
        raise MalformedResponseError(msg)
    return v


def _responses_message_blocks(
    item: dict[str, Any], texts: list[str], refusals: list[str]
) -> None:
    """``message`` item 的 content 块 → texts/refusals 累加（形状闸同 ``_list/_str_field``）。"""
    for blk in _list_field(item.get("content") or [], "message content"):
        if not isinstance(blk, dict):
            msg = "content block is not an object"
            raise MalformedResponseError(msg)
        bt = blk.get("type")
        if bt == "output_text":
            texts.append(_str_field(blk, "text", "output_text"))
        elif bt == "refusal":
            refusals.append(_str_field(blk, "refusal", "refusal"))


def _responses_reasoning_blocks(item: dict[str, Any], thinks: list[str]) -> None:
    """``reasoning`` item 的 summary 块 → thinks 累加。"""
    for s in _list_field(item.get("summary") or [], "reasoning summary"):
        if not isinstance(s, dict):
            msg = "summary item is not an object"
            raise MalformedResponseError(msg)
        if s.get("type") == "summary_text":
            thinks.append(_str_field(s, "text", "summary_text"))


def _responses_blocks(payload: dict[str, Any]) -> tuple[str, str, list[str]]:
    """``output`` items → (text 合, reasoning summary 合, refusal 列)；形状不符一律 ``MalformedResponseError``。"""
    texts: list[str] = []
    thinks: list[str] = []
    refusals: list[str] = []
    for item in _list_field(payload.get("output") or [], "output"):
        if not isinstance(item, dict):
            msg = "output item is not an object"
            raise MalformedResponseError(msg)
        it = item.get("type")
        if it == "message":
            _responses_message_blocks(item, texts, refusals)
        elif it == "reasoning":
            _responses_reasoning_blocks(item, thinks)
    return "".join(texts), "".join(thinks), refusals


def _responses_usage(usage_raw: object) -> Usage:
    """Responses ``usage`` 对象 → ``Usage``——``_parse_responses`` 与 SSE 终帧同闸。"""
    if not isinstance(usage_raw, dict):
        msg = "usage field is not an object"
        raise MalformedResponseError(msg)
    details = usage_raw.get("input_tokens_details") or {}
    if not isinstance(details, dict):
        msg = "usage.input_tokens_details is not an object"
        raise MalformedResponseError(msg)
    return Usage(
        prompt_tokens=_usage_int(usage_raw.get("input_tokens")),
        completion_tokens=_usage_int(usage_raw.get("output_tokens")),
        cached_tokens=_usage_int(details.get("cached_tokens")),
        raw=usage_raw,
    )


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


def _responses_status_gate(
    payload: dict[str, Any],
    status: str,
    content: str,
    refusals: list[str],
    api_key: str,
) -> None:
    """``status``/refusal 终态闸——异常态全在此抛错（``_parse_responses`` 分支减压）。

    映射：refusal 块→``content_filter`` 委托 ``_raise_for_finish``（refusal
    文本经 ``detail`` 进消息）；``failed``/``cancelled``→``ChatError``
    （非 finish 词表概念，门内保留）；``completed``/``incomplete`` 经
    ``_responses_stream_finish`` 归一 openai 词表后委托 ``_raise_for_finish``
    （``incomplete_details.reason`` 原文进 ``detail``——产出未完的归约与
    ``finish_reason=length`` 同族）；``queued``/``in_progress`` 等非终态→
    ``MalformedResponseError``（非 background 模式不应出现）。
    """
    if refusals:
        detail = redact(" ".join(refusals), api_key)[:200]
        _raise_for_finish("content_filter", content, detail=detail)
    if status in ("failed", "cancelled"):
        err = payload.get("error") or {}
        if not isinstance(err, dict):
            msg = "error field is not an object"
            raise MalformedResponseError(msg)
        detail = redact(str(err.get("message") or status), api_key)
        msg = f"responses status={status}: {detail}"
        raise ChatError(msg)
    if status not in ("completed", "incomplete"):
        msg = f"unexpected response status {status!r}"
        raise MalformedResponseError(msg)
    detail = ""
    if status == "incomplete":
        det = payload.get("incomplete_details") or {}
        if not isinstance(det, dict):
            msg = "incomplete_details field is not an object"
            raise MalformedResponseError(msg)
        detail = str(det.get("reason") or "unknown")
    finish = _responses_stream_finish(payload, incomplete=status == "incomplete")
    _raise_for_finish(finish, content, detail=detail)


def _parse_responses(
    payload: dict[str, Any], latency: float, api_key: str
) -> ChatResult:
    """Responses 200 体 → ``ChatResult``；``finish_reason`` 归一成 openai 词表。"""
    if payload.get("type") == "error":
        err = payload.get("error") or {}
        if not isinstance(err, dict):
            msg = "error field is not an object"
            raise MalformedResponseError(msg)
        detail = redact(str(err.get("message") or ""), api_key)
        msg = f"responses error {err.get('code')}: {detail}"
        raise ChatError(msg)
    content, reasoning, refusals = _responses_blocks(payload)
    status = str(payload.get("status") or "completed")
    _responses_status_gate(payload, status, content, refusals, api_key)
    return ChatResult(
        content=content,
        reasoning=reasoning,
        finish_reason="stop",
        usage=_responses_usage(payload.get("usage") or {}),
        model=payload.get("model") or "",
        latency_s=round(latency, 3),
    )
