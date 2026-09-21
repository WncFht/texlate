"""xlat SSE 流式面：StreamEvent 词汇 + 三方言 SSE 行/帧解析 + 流式兜底臂。

``client.py`` 出叶（hoist）：``StreamEvent`` 增量事件、openai ``data:``
行解析（``_sse_events``/``_sse_choice_events``）、anthropic/responses
``data:`` payload 帧→事件装配、按方言分发的 ``_sse_line_events``、
``chat`` 流式兜底臂执行体（``_stream_rescue``/``_chat_via_stream``）。
函数吃 ``client``/``api_key``/``dialect`` 形参；``ChatClient`` 侧留薄
委托（``chat_stream`` 传输循环真身仍在 ``client``——吃 ``self._http``
stream 上下文）。叶子不引 ``client``（环断）。
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from texlate.xlat._dialects import (
    _ANTHROPIC_FINISH,
    ChatResult,
    Usage,
    _anthropic_usage,
    _openai_usage,
    _responses_stream_finish,
    _responses_usage,
)
from texlate.xlat._errors import (
    HTTP_OK,
    ChatError,
    MalformedResponseError,
    _raise_for_finish,
    _stream_rescuable,
    redact,
)

if TYPE_CHECKING:
    from texlate.xlat.client import ChatClient, ChatOptions

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- 事件类型


@dataclass
class StreamEvent:
    """流式增量：`kind` ∈ content/reasoning/done。

    ``done`` 事件可携 ``usage``——openai 末帧 usage（请求侧
    ``stream_options.include_usage``）与各方言原生 usage 帧（anthropic
    ``message_*``、responses 终帧 ``response.usage``）借 ``done`` 壳递出
    （事件词表被 fuzz 钉死三类，不扩 kind）；终态判别看
    ``finish_reason``/流终止标记而非 kind——usage 载体帧非终态。
    """

    kind: str
    delta: str = ""
    finish_reason: str = ""
    usage: Usage | None = None


def _merge_usage(acc: Usage, new: Usage) -> Usage:
    """流式分帧 usage 合并——后到非零字段覆盖（anthropic input/output 分两帧到）。"""
    return Usage(
        prompt_tokens=new.prompt_tokens or acc.prompt_tokens,
        completion_tokens=new.completion_tokens or acc.completion_tokens,
        cached_tokens=new.cached_tokens or acc.cached_tokens,
        raw=new.raw or acc.raw,
    )


# ---------------------------------------------------------------- OpenAI SSE 行解析


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
            events.extend(_sse_choice_events(ch))
    # ``include_usage`` 末帧：``choices`` 空、``usage`` 顶置——借 ``done``
    # 壳递出记账（事件词表被 fuzz 钉死三类，不扩 kind；``done`` flag 不动，
    # 终端判别仍在 ``[DONE]`` 字面）；畸形 usage 帧按行级容错跳过
    # （同坏 JSON 口径）
    u = chunk.get("usage")
    if isinstance(u, dict):
        with contextlib.suppress(MalformedResponseError):
            events.append(StreamEvent("done", usage=_openai_usage(u)))
    return events, False


# ---------------------------------------------------------------- 方言分发


def _sse_line_events(
    dialect: str, api_key: str, line: str
) -> tuple[list[StreamEvent], bool]:
    """一行 SSE → (events, done?)——按方言分发 payload 解析。

    openai 走 ``_sse_events``（choices/[DONE] 族）；anthropic/responses
    的 ``event:`` 行冗余（``data:`` payload 自带 ``type`` 字段），
    只解 ``data:`` JSON 分发。
    """
    if dialect == "openai":
        return _sse_events(line)
    events: list[StreamEvent] = []
    done = False
    if line.startswith("data:"):
        try:
            chunk = json.loads(line[5:].strip())
        except (json.JSONDecodeError, RecursionError):
            chunk = None
        if isinstance(chunk, dict):
            if dialect == "anthropic":
                events, done = _sse_anthropic_data(chunk, api_key)
            elif dialect == "responses":
                events, done = _sse_responses_data(chunk, api_key)
    return events, done


# ---------------------------------------------------------------- Anthropic SSE 帧


def _sse_anthropic_data(
    chunk: dict[str, Any], api_key: str
) -> tuple[list[StreamEvent], bool]:
    """Anthropic SSE payload → (events, done?)；``error`` 帧抛 ``ChatError``。"""
    t = chunk.get("type")
    if t == "content_block_delta":
        return _anthropic_delta_events(chunk), False
    if t == "message_start":
        return _anthropic_start_events(chunk), False
    if t == "message_delta":
        return _anthropic_tail_events(chunk)
    if t == "message_stop":
        return [StreamEvent(kind="done")], True
    if t == "error":
        err = chunk.get("error") or {}
        # ``message`` 缺/空时回退整帧 repr——不得渲染成 "None"
        detail = (err.get("message") or str(chunk)) if isinstance(err, dict) else str(chunk)
        msg = f"anthropic stream error: {redact(str(detail), api_key)}"
        raise ChatError(msg)
    return [], False


def _anthropic_delta_events(chunk: dict[str, Any]) -> list[StreamEvent]:
    """``content_block_delta`` 帧 → 增量事件（text_delta/thinking_delta）。"""
    d = chunk.get("delta") or {}
    if not isinstance(d, dict):
        return []
    if d.get("type") == "text_delta" and d.get("text"):
        return [StreamEvent("content", str(d["text"]))]
    if d.get("type") == "thinking_delta" and d.get("thinking"):
        return [StreamEvent("reasoning", str(d["thinking"]))]
    return []


def _anthropic_start_events(chunk: dict[str, Any]) -> list[StreamEvent]:
    """``message_start`` 帧 → ``input_tokens`` 载体事件（``done`` 壳递出）。

    ``usage.input_tokens`` 只此帧报（``message_delta`` 只报
    ``output_tokens`` 终值）；``done`` flag 不动——本帧非终态。
    """
    m = chunk.get("message") or {}
    if not isinstance(m, dict):
        return []
    usage = _anthropic_usage(m.get("usage"), "input_tokens")
    if usage is None:
        return []
    return [StreamEvent("done", usage=usage)]


def _anthropic_tail_events(
    chunk: dict[str, Any],
) -> tuple[list[StreamEvent], bool]:
    """``message_delta`` 帧 → 终态/usage 载体事件。

    ``stop_reason`` 出现即终帧（``done`` flag 立），可同帧捎
    ``output_tokens`` 终值；无 ``stop_reason`` 的纯 usage 帧仍借
    ``done`` 壳递出、flag 不动。
    """
    d = chunk.get("delta") or {}
    stop = d.get("stop_reason") if isinstance(d, dict) else None
    usage = _anthropic_usage(chunk.get("usage"), "output_tokens")
    if stop:
        return [StreamEvent("done", finish_reason=str(stop), usage=usage)], True
    if usage is not None:
        return [StreamEvent("done", usage=usage)], False
    return [], False


# ---------------------------------------------------------------- Responses SSE 帧


def _sse_responses_data(
    chunk: dict[str, Any], api_key: str
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
        resp_obj = chunk.get("response")
        u = resp_obj.get("usage") if isinstance(resp_obj, dict) else None
        usage = None
        if isinstance(u, dict):
            try:
                usage = _responses_usage(u)
            except MalformedResponseError:
                usage = None  # usage 畸形不挡终帧本身
        events.append(
            StreamEvent(
                "done",
                finish_reason=_responses_stream_finish(
                    resp_obj, incomplete=t == "response.incomplete"
                ),
                usage=usage,
            )
        )
        done = True
    elif t in ("response.failed", "error"):
        resp = chunk.get("response") or chunk
        err = resp.get("error") or {} if isinstance(resp, dict) else {}
        # ``message`` 缺/空时回退整帧 repr——不得渲染成 "None"
        detail = (err.get("message") or str(chunk)) if isinstance(err, dict) else str(chunk)
        msg = f"responses stream error: {redact(str(detail), api_key)}"
        raise ChatError(msg)
    return events, done


# ---------------------------------------------------------------- 流式兜底臂


async def _stream_rescue(
    client: ChatClient,
    model: str,
    messages: list[dict[str, str]],
    opts: ChatOptions,
    err: ChatError,
) -> ChatResult | None:
    """流式兜底臂入口——opt-in 旋钮 ∧ ``_stream_rescuable`` 双闸放行才补发。

    ``client._stream_fallback`` 关（默认）恒 ``None``——失败路径请求数
    钉在降级臂合同内。补发拿到响应级判定（``status==200`` 合同违约族：
    截断/过滤/空/畸形）直接上抛——比原始路由死亡错误更新鲜、更可行
    动（带 ``partial_content``/max_tries 语义）；路由级失败（传输/
    HTTP 状态/非 ChatError 逃逸）一律 ``None`` 回落原降级链，绝不放大
    爆炸半径。
    """
    if not client._stream_fallback or not _stream_rescuable(err):  # noqa: SLF001 -- 出叶委托面（同模块实现组）
        return None
    try:
        return await client._chat_via_stream(model, messages, opts)  # noqa: SLF001 -- 出叶委托面（同模块实现组）
    except ChatError as e:
        if e.status == HTTP_OK:
            raise
        log.warning("model %s 流式兜底失败（%s）——回落原降级链", model, e)
        return None
    except Exception as e:  # noqa: BLE001 -- 兜底臂绝不挡原降级链（含非 ChatError 逃逸）
        log.warning("model %s 流式兜底失败（%s）——回落原降级链", model, e)
        return None


async def _chat_via_stream(
    client: ChatClient,
    model: str,
    messages: list[dict[str, str]],
    opts: ChatOptions,
) -> ChatResult:
    """聚 ``chat_stream`` deltas → ``ChatResult``——``chat`` 流式兜底臂的执行体。

    终帧 usage 经各方言 usage 帧回填（openai 靠请求侧
    ``stream_options.include_usage``，端点不回则按零记账）；终态
    ``finish_reason`` 归一到 ``_raise_for_finish`` 同口径（anthropic
    先过 ``_ANTHROPIC_FINISH`` 词表映射，responses 已在
    ``_sse_responses_data`` 归一）。``model`` 记请求模型——流式无
    顶层 model 汇总帧可钉。无终帧收尾（连接中途断）按
    ``MalformedResponseError`` 判——半截正文不得当成功译文放行。
    """
    t0 = time.monotonic()
    parts: list[str] = []
    thinks: list[str] = []
    finish = ""
    usage = Usage()
    saw_terminal = False
    async for ev in client.chat_stream(model, messages, options=opts):
        if ev.kind == "content":
            parts.append(ev.delta)
        elif ev.kind == "reasoning":
            thinks.append(ev.delta)
        elif ev.kind == "done":
            if ev.usage is not None:
                usage = _merge_usage(usage, ev.usage)
            if ev.finish_reason:
                finish = str(ev.finish_reason)
            if ev.usage is None or ev.finish_reason:
                saw_terminal = True
    if not saw_terminal:
        msg = "SSE stream ended without terminal frame"
        raise MalformedResponseError(msg)
    content = "".join(parts)
    detail = ""
    if client.dialect == "anthropic":
        mapped = _ANTHROPIC_FINISH.get(finish, finish)
        detail = f"stop_reason={finish}" if finish else ""
    else:
        mapped = finish
    _raise_for_finish(mapped, content, detail=detail)
    result = ChatResult(
        content=content,
        reasoning="".join(thinks),
        finish_reason=finish,
        usage=usage,
        model=model,
        latency_s=round(time.monotonic() - t0, 3),
    )
    client._emit_usage(result)  # noqa: SLF001 -- 出叶委托面（同模块实现组）
    return result
