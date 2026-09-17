"""xlat/client.py 对抗性 fuzz——协议形状容忍、URL 闸、脱敏、降级臂不变量。

与既有覆盖的分工：``test_xlat_client.py``/``test_xlat_client_wire.py``/
``test_xlat_freemodel.py`` 钉正向线路与已知分支；本文件做随机/对抗变异，
把「只许 ``ChatError`` 逃逸」的文档化契约逐面压一遍。

不变量清单（观测语义均经 ``tmp/client-fuzz/`` 探针实证）：

- ``classify_status``：任意 int 状态码 + 任意 ASCII body/header → 按表分类
  且只回 ``ChatError`` 子类；``retry_after ∈ {None} ∪ [0, 60]``；消息体
  ``HTTP {status}:`` 前缀 + body 截 300。
- ``_body_retry_after``：任意 JSON 文本 → ``None`` 或 ``[0,60]`` float，
  绝不抛（含 NaN/Infinity/超深嵌套/bool/负值/超限——bool 与越界一律拒）。
- ``_sse_events``：非 ``data:`` 行与坏 JSON 一律 ``([], False)``；``[DONE]``
  （strip 后）是唯一 done 触发；well-formed chunk 的事件序保序且
  kind ∈ {reasoning, content, done}。
- ``_parse_openai``/``_parse_anthropic``：产出 ``ChatResult`` 时
  ``content.strip()`` 非空、``finish_reason`` 非截断标记、usage 字段为
  int、``latency_s == round(x, 3)``；不静默造 content。
- ``discover_free_models``：返回集 == 独立 oracle 过滤序（free ∧ promo.active
  ∧ 非 disabled ∧ 非空 uid ∧ 非空 ``/v1/models`` 交集），panel 序即返回序。
- ``rank_models``：结果 ⊆ 探活集 ∧ denylist 剔除 ∧ 偏好序在前其余字典序，
  无重复、确定性。
- ``probe_model``：任意响应形态只回 ``FreeModel`` 绝不抛（``Exception`` 层
  全兜）；``probe_ok`` iff 200 ∧ 非空 content ∧ finish ∈ {None, "stop"}。
- ``is_free_gateway_url``/``provider_for_url``/``normalize_base_url``/
  ``redact``：任意 str 输入绝不抛；``redact`` 幂等且显式 api_key 值绝不留存。
- ``chat`` 降级臂：非 switchable 错误（auth/计费/其余 4xx/传输）零探测请求；
  臂中遇非 switchable 立即上抛该错误；候选全灭上抛**最后**一次失败；
  候选表不含请求模型自身；``usage_sink`` 每次成功往返恰记一笔。
- ``fallback_candidates``：并发调用只跑一次发现（锁 + memoize）；结果
  ≤ ``FALLBACK_MAX_CANDIDATES``；非网关端点恒 ``[]`` 零请求。

缺陷钉账（本文件 `xfail(strict=True)` 钉住**期望**契约——修复落地后
XPASS 转红即拆钉；观测语义类钉用普通断言 + CONFIRMED/PLAUSIBLE 注脚）：

- C1 ``_retry_after`` Unicode 数字缝（client.py:176-178）：``str.isdigit()``
  覆盖 ``float()`` 不可解析的 No 类字符（上标 ¹²³）——``Retry-After``
  值为 latin-1 线上字节 0xB9/0xB2/0xB3（``httpx.Headers`` 按 latin-1
  解码）→ ``ValueError`` 裸逃出 ``classify_status`` → 穿透 ``chat``/
  ``list_models``/``chat_stream``/``panel_models`` 全部公开面。**CONFIRMED**。
- C2 ``_sse_events`` 形状缝（client.py:702-722）：``data: <非 dict JSON>``
  （``5``/``null``/``"x"``/``[1]``/``true``）、``choices`` 非 list、成员/
  ``delta`` 非 dict → ``AttributeError``/``TypeError`` 裸逃出
  ``chat_stream``——docstring 承诺「坏行跳过」且公开面只许 ``ChatError``。
  **CONFIRMED**。
- C3 ``_parse_openai`` 形状缝（client.py:494-532）：JSON 合法但形状错的
  200 体（choices 成员/message/usage 非 dict、content 非 str、usage
  token 非数值、``1e999`` inf → ``int()``）→ ``AttributeError``/``TypeError``/
  ``ValueError``/``KeyError``/``OverflowError`` 裸逃出 ``chat()``——
  ``MalformedResponseError`` docstring 明言覆盖「形状不符」。**CONFIRMED**。
  次生后果：逃逸绕过 ``chat`` 降级臂（``except ChatError`` 捕不到），
  零候选探测直接崩出。
- C4 ``_parse_anthropic`` 同族（client.py:566-603）：error/content/usage
  非 dict、blk 非 dict、text/thinking 非 str（join 炸）、usage 非数值。
  **CONFIRMED**。
- C5 ``discover_free_models`` 成员字段缝（client.py:882-895）：``promo``
  非 dict → ``AttributeError``；``context_tokens`` 非数值/``1e999`` →
  ``ValueError``/``TypeError``/``OverflowError``——直调裸逃；
  ``fallback_candidates`` 里被 ``except Exception`` 兜底成 ``[]``（降级臂
  路径无感）。**CONFIRMED**。
- C6 ``panel_models`` ``models`` 字段不可迭代缝（client.py:817）：
  ``{"models": 5}``/``true`` → ``TypeError`` 裸逃——姊妹面
  ``list_models`` 对同形态 ``data`` 字段回 ``MalformedResponseError``。
  **CONFIRMED**。
- C7 非 ASCII ``api_key``（如 ``künstlîch``）→ 请求头 ASCII 编码在
  ``_chat_once`` 请求构造期炸 ``UnicodeEncodeError`` 裸逃。**CONFIRMED**。
- P1 ``LengthTruncatedError.status == -1``（client.py:136-138）：同族
  200-合同违约错误里 Empty/Malformed 显式记 200，唯独它漏记——
  ``retry._backoff_delay`` 把 ``status<0`` 当传输超时走 ``timeout_floor``
  （≥10s）而非 ``base·2^attempt``；且 status=-1 对记账/日志谎称
  「传输层失败」（实际 200 已回）。**PLAUSIBLE**（三兄弟语义不齐）。
- P2 ``httpx.LocalProtocolError``（客户端协议违例——真线上非法 header
  值如含换行的 api_key 触发）被归 ``RetryableHTTPError`` 传输重试族，
  会烧满退避再死。**PLAUSIBLE**（误分类非破坏）。
- P3 ``usage_sink`` 记 ``payload.model``（响应自报）而非请求模型——
  网关不回 ``model`` 字段时记 ``""``，回错名时错账。观测语义钉。
- P4 ``list_models``/``discover`` uid 走 ``str()`` 强转：``None``→``"None"``、
  ``5``→``"5"``、``""`` 原样收、``true``→``"True"``——垃圾 id 流进
  模型清单/发现交集。观测语义钉。
- P5 ``ChatOptions.extra`` 可覆盖 ``model``/``messages``/``stream``
  键（``body.update(extra)`` 在最后）。观测语义钉——调用方 footgun。
- P6 ``_anthropic_body`` 对缺 ``role``/``content`` 键或非 dict 成员的
  messages 裸抛 ``KeyError``/``TypeError``——调用方输入边界无校验。
  **PLAUSIBLE**（caller-side 输入面，纪律归属可议）。
- P7 ``is_free_gateway_url`` 观测面：只看 host 不看 scheme
  （``ftp://127.0.0.1`` → True——下游 ``InvalidURL`` fail-closed 兜底）；
  schemeless ``127.0.0.1:3003`` → False；``urlsplit`` 剥 ``\\t\\r\\n``
  与 httpx 解析口径分叉（gate 说 loopback、请求期 httpx 拒——
  分歧方向保守、不放大探测面）。观测语义钉。
- P8 ``normalize_base_url`` 单次只剥一层已知后缀——
  ``http://x/v1/v1`` → ``http://x/v1``（非幂等）；大小写敏感
  （``/V1`` 不剥）。观测语义钉。
- P9 ``finish_reason``/``model``/``reasoning_content``/``stop_reason``
  非 str 原样进 ``ChatResult``/``StreamEvent`` 字段（类型污染：
  ``finish_reason=5``、``model=5``、``delta=["x"]``）。观测语义钉。
- P10 ``redact`` 模式缝（观测）：``token = x``（``=`` 前空格破模式）/
  ``password=x``/``key=x`` 不命中模式表；``sk-`` 需 ≥8 位、``sk-ant-``
  需 ≥4 位；显式 ``api_key`` 字面替换兜底实值。观测语义钉。
- P11 ``pick_model`` 可对 ``FreeModel(uid="", probe_ok=True)`` 回 ``""``
  （falsy 非 None）。观测语义钉。
- P12 ``panel_models`` 与 ``list_models`` 容忍度不对称：顶层标量
  ``"nope"`` → panel 回 ``[]``、list 抛 ``MalformedResponseError``。
  观测语义钉。
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from texlate.xlat import client as cl
from texlate.xlat.retry import RetryPolicy, _backoff_delay

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------- 常量与 fake

_BASE = "http://127.0.0.1:3003"
_BYOK = "https://example.com"  # custom 公网——发现/探活面零放行，隔离单往返语义
_ANTHROPIC = "https://api.anthropic.com"
_MSGS = [{"role": "user", "content": "hi"}]
_KEY = "test-key-123"
#: ``probe_model`` 的探活请求指纹（client.py:831）——fake 网关据此区分
#: 探测与真实请求，否则候选的探活会被错误表打死、降级臂无从枚举。
_PROBE_TEXT = "Reply with exactly: OK"

_FUZZ_ITERS = 2000
_FUZZ_ITERS_MED = 800
_FUZZ_ITERS_WIRE = 250

#: C3/C4 形状缝的观测逃逸族（CONFIRMED 缺陷——修复后本集合应收空）
_PARSE_ESCAPES = (AttributeError, TypeError, ValueError, KeyError, OverflowError)
#: C2 SSE 形状缝的观测逃逸族
_SSE_ESCAPES = (AttributeError, TypeError)
#: C5 discover 成员字段缝的观测逃逸族
_DISCOVER_ESCAPES = (AttributeError, TypeError, ValueError, OverflowError)


def _mock(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    base_url: str = _BASE,
    api_key: str = _KEY,
    usage_sink: Callable[[cl.UsageRecord], None] | None = None,
) -> cl.ChatClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return cl.ChatClient(base_url, api_key, http=http, usage_sink=usage_sink)


def _json(payload: object, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, json=payload, headers=httpx.Headers(headers))


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


def _panel_entry(uid: object, **kw: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "uid": uid,
        "cost_tier": "free",
        "promo": {"active": True, "end_date": "2026-10-01"},
        "context_tokens": 131072,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------- JSON 形状发生器

_JSON_LEAVES: list[Any] = [
    None,
    True,
    False,
    0,
    1,
    -1,
    5,
    1.5,
    -2.5,
    float("inf"),
    float("-inf"),
    float("nan"),
    "",
    "x",
    "stop",
    "length",
    "max_tokens",
    "0",
    "abc",
    "  ",
    "你好",
    [],
    {},
    [None],
]
_JSON_KEYS = [
    "choices",
    "message",
    "content",
    "reasoning_content",
    "finish_reason",
    "usage",
    "prompt_tokens",
    "completion_tokens",
    "prompt_tokens_details",
    "cached_tokens",
    "model",
    "role",
    "type",
    "stop_reason",
    "error",
    "data",
    "id",
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "delta",
    "uid",
    "cost_tier",
    "promo",
    "disabled",
    "active",
    "context_tokens",
    "end_date",
    "supports_thinking",
    "retry_after",
    "models",
    "text",
    "thinking",
]


def _gen_json(rng: random.Random, depth: int = 0) -> Any:  # noqa: ANN401 -- fuzz 生成器本就要返回任意 JSON 值
    """随机 JSON 形值（含 inf/nan——``json.loads`` 许可面内）。"""
    r = rng.random()
    if depth > 3 or r < 0.45:  # noqa: PLR2004
        return rng.choice(_JSON_LEAVES)
    if r < 0.75:  # noqa: PLR2004
        return [_gen_json(rng, depth + 1) for _ in range(rng.randint(0, 3))]
    return {
        rng.choice(_JSON_KEYS): _gen_json(rng, depth + 1)
        for _ in range(rng.randint(0, 3))
    }


def _gen_openai_payload(rng: random.Random) -> dict[str, Any]:
    """偏向协议形状的 OpenAI 200 载荷——三出路（result/ChatError/逃逸）都高频。"""
    payload: dict[str, Any] = {}
    roll = rng.random()
    if roll < 0.45:  # noqa: PLR2004 -- 良形 choices 臂
        payload["choices"] = [
            {
                "message": rng.choice(
                    [
                        {"content": rng.choice(["x", "OK", "", "  "])},
                        {"content": rng.choice([5, None, [1], "x"])},
                        _gen_json(rng, 2),
                    ]
                ),
                "finish_reason": rng.choice(
                    ["stop", "length", "", None, 5, "tool_calls"]
                ),
            }
            for _ in range(rng.randint(0, 2))
        ]
    elif roll < 0.75:  # noqa: PLR2004 -- choices 字段本身异形
        payload["choices"] = _gen_json(rng)
    else:
        payload["choices"] = [_gen_json(rng, 2) for _ in range(rng.randint(0, 2))]
    if rng.random() < 0.6:  # noqa: PLR2004
        payload["usage"] = rng.choice(
            [
                {"prompt_tokens": rng.randint(0, 50), "completion_tokens": 3},
                {
                    "prompt_tokens": rng.choice(["abc", float("inf"), None, True, [1]]),
                    "prompt_tokens_details": rng.choice(
                        [{"cached_tokens": 2}, 5, "x", None]
                    ),
                },
                _gen_json(rng, 2),
            ]
        )
    if rng.random() < 0.3:  # noqa: PLR2004
        payload["model"] = _gen_json(rng)
    return payload


def _gen_anthropic_payload(rng: random.Random) -> dict[str, Any]:
    """偏向协议形状的 Anthropic 200 载荷。"""
    payload: dict[str, Any] = {}
    if rng.random() < 0.15:  # noqa: PLR2004
        payload["type"] = "error"
        payload["error"] = rng.choice(
            [{"message": "bad", "type": "rate_limit"}, "x", 5, None, {}]
        )
    if rng.random() < 0.25:  # noqa: PLR2004
        payload["type"] = rng.choice(["message", "x", 5])
    if rng.random() < 0.7:  # noqa: PLR2004
        payload["content"] = [
            rng.choice(
                [
                    {"type": "text", "text": rng.choice(["x", "", "OK"])},
                    {"type": "text", "text": rng.choice([5, None, [1]])},
                    {"type": "thinking", "thinking": rng.choice(["t", 5, None])},
                    {"type": "weird"},
                    _gen_json(rng, 2),
                ]
            )
            for _ in range(rng.randint(0, 3))
        ]
    else:
        payload["content"] = _gen_json(rng)
    if rng.random() < 0.6:  # noqa: PLR2004
        payload["stop_reason"] = rng.choice(
            ["end_turn", "max_tokens", "", None, 5, "stop_sequence"]
        )
    if rng.random() < 0.4:  # noqa: PLR2004
        payload["usage"] = rng.choice(
            [
                {"input_tokens": 9, "output_tokens": 4},
                {
                    "input_tokens": rng.choice(["abc", float("inf"), None, [1]]),
                    "cache_read_input_tokens": rng.choice([2, "x", True]),
                },
                _gen_json(rng, 2),
            ]
        )
    return payload


# ---------------------------------------------------------------- classify_status / retry_after


class TestClassifyStatusFuzz:
    def test_fuzz_status_sweep_table(self) -> None:
        """全表扫描：任意 int 状态码按表分类，绝不抛。"""
        h = httpx.Headers()
        for status in range(-10, 1200):
            e = cl.classify_status(status, "body", h)
            assert isinstance(e, cl.ChatError)
            assert e.status == status
            assert str(e).startswith(f"HTTP {status}:")
            if status in (401, 403):
                assert isinstance(e, cl.AuthError)
                assert not e.retryable
            elif status == 402:  # noqa: PLR2004
                assert isinstance(e, cl.BillingError)
                assert not e.retryable
            elif status == 404:  # noqa: PLR2004
                assert isinstance(e, cl.EndpointNotFoundError)
                assert not e.retryable
            elif status in cl.RETRYABLE_4XX or status == 429 or status >= 500:  # noqa: PLR2004
                assert isinstance(e, cl.RetryableHTTPError)
                assert e.retryable
            else:
                assert isinstance(e, cl.ClientRejectedError)
                assert not e.retryable

    def test_fuzz_body_retry_after_oracle(self) -> None:
        """``_body_retry_after``：任意 JSON body → None 或 [0,60]，绝不抛。"""
        rng = random.Random(20261102)  # noqa: S311
        for _ in range(_FUZZ_ITERS):
            body = json.dumps({"error": {"retry_after": _gen_json(rng)}})
            out = cl._body_retry_after(body)  # noqa: SLF001
            assert out is None or 0 <= out <= cl.MAX_RETRY_AFTER_S
        # 垃圾字节/截断 JSON/超深嵌套同样不抛
        for _ in range(200):
            body = "".join(rng.choice('{["a:,012') for _ in range(rng.randint(0, 60)))
            out = cl._body_retry_after(body)  # noqa: SLF001
            assert out is None or 0 <= out <= cl.MAX_RETRY_AFTER_S
        deep = "[" * 5000 + "]" * 5000
        assert cl._body_retry_after(deep) is None  # noqa: SLF001

    def test_body_retry_after_type_table(self) -> None:
        """body retry_after 类型表：bool/str/负/超限/NaN/inf 一律 None。"""
        cases: list[tuple[object, float | None]] = [
            (True, None),
            ("5", None),
            (-3, None),
            (61, None),
            (5, 5.0),
            (0, 0.0),
            (5.5, 5.5),
            (float("nan"), None),
            (float("inf"), None),
            (None, None),
            ([5], None),
            ({"x": 1}, None),
        ]
        for v, want in cases:
            body = f'{{"error": {{"retry_after": {json.dumps(v)}}}}}'
            assert cl._body_retry_after(body) == want, v  # noqa: SLF001

    def test_fuzz_header_retry_after_ascii(self) -> None:
        """ASCII 头面：``_retry_after`` → None 或 [0,60]；isdigit 数串被接受。"""
        rng = random.Random(20261103)  # noqa: S311
        soup = "0123456789 +-eE.\t abcGMT:"
        for _ in range(_FUZZ_ITERS):
            raw = "".join(rng.choice(soup) for _ in range(rng.randint(0, 12)))
            h = httpx.Headers([(b"retry-after", raw.encode())])
            out = cl._retry_after(h)  # noqa: SLF001
            assert out is None or 0 <= out <= cl.MAX_RETRY_AFTER_S, raw
            if raw.strip().isdigit():
                secs = float(raw.strip())
                assert out == (secs if secs <= cl.MAX_RETRY_AFTER_S else None)

    def test_retry_after_digit_boundaries(self) -> None:
        """isdigit 数字串边界：``60`` 收、``61`` 拒、前导零照常、HTTP-date 退化。"""
        for raw, want in [(b"60", 60.0), (b"61", None), (b"060", 60.0), (b"0", 0.0)]:
            h = httpx.Headers([(b"retry-after", raw)])
            assert cl._retry_after(h) == want  # noqa: SLF001
        h = httpx.Headers({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
        assert cl._retry_after(h) is None  # noqa: SLF001

    @pytest.mark.xfail(
        reason=(
            "CONFIRMED defect C1: str.isdigit() 覆盖 float() 不可解析的 "
            "No 类字符——Retry-After 线上字节 0xB9/0xB2/0xB3（latin-1 解码为 "
            "上标数字）炸 ValueError 裸逃出 classify_status；期望退化为 "
            "None（同 HTTP-date 待遇）"
        ),
        strict=True,
    )
    @pytest.mark.parametrize("raw", [b"\xb2", b"\xb3", b"\xb9"])
    def test_retry_after_superscript_digit_degrades(self, raw: bytes) -> None:
        """C1：上标数字头应退化 ``None`` 而非炸 ``ValueError``。"""
        h = httpx.Headers([(b"retry-after", raw)])
        e = cl.classify_status(503, "x", h)
        assert e.retry_after is None

    def test_fuzz_classify_msg_bounded(self) -> None:
        """消息恒 ``HTTP {status}: {body[:300]}``——body 任长截 300。"""
        rng = random.Random(20261104)  # noqa: S311
        for _ in range(500):
            body = "".join(
                rng.choice("ab{}\"'\x00é") for _ in range(rng.randint(0, 700))
            )
            e = cl.classify_status(rng.randint(400, 599), body, httpx.Headers())
            assert str(e) == f"HTTP {e.status}: {body[:300]}"


# ---------------------------------------------------------------- _model_switchable


class TestModelSwitchable:
    def test_truth_table(self) -> None:
        sw = cl._model_switchable  # noqa: SLF001
        for status in (-1, 0, 400, 500):
            assert not sw(cl.AuthError("x", status=status))
            assert not sw(cl.BillingError("x", status=status))
            assert not sw(cl.ClientRejectedError("x", status=status))
            assert sw(cl.EndpointNotFoundError("x", status=status))
        assert not sw(cl.RetryableHTTPError("x", status=-1, retryable=True))
        assert sw(cl.RetryableHTTPError("x", status=429, retryable=True))
        assert sw(cl.RetryableHTTPError("x", status=500, retryable=True))
        # 非 retryable ChatError 不切；裸 retryable ChatError 切
        assert not sw(cl.ChatError("x", status=500, retryable=False))
        assert sw(cl.ChatError("x", status=500, retryable=True))
        # 200-合同违约族全切
        assert sw(cl.EmptyContentError("x"))
        assert sw(cl.MalformedResponseError("x"))
        assert sw(cl.LengthTruncatedError("x"))

    def test_fuzz_oracle(self) -> None:
        """随机 ChatError 组合 → 与独立判据一致。"""
        rng = random.Random(20261105)  # noqa: S311
        kinds: list[Callable[..., cl.ChatError]] = [
            cl.ChatError,
            cl.AuthError,
            cl.BillingError,
            cl.EndpointNotFoundError,
            cl.ClientRejectedError,
            cl.RetryableHTTPError,
        ]
        for _ in range(_FUZZ_ITERS):
            cls = rng.choice(kinds)
            status = rng.choice([-2, -1, 0, 200, 400, 404, 429, 500, 503])
            retryable = rng.random() < 0.5  # noqa: PLR2004
            e = cls("m", status=status, retryable=retryable)
            want = isinstance(e, cl.EndpointNotFoundError) or (
                e.retryable
                and not (isinstance(e, cl.RetryableHTTPError) and e.status < 0)
            )
            assert cl._model_switchable(e) == want  # noqa: SLF001


# ---------------------------------------------------------------- _sse_events / chat_stream


class TestSseEvents:
    _sse = staticmethod(cl.ChatClient._sse_events)  # noqa: SLF001

    def test_fuzz_non_data_lines_never_done(self) -> None:
        """非 ``data:`` 前缀行恒 ``([], False)``。"""
        rng = random.Random(20261106)  # noqa: S311
        for _ in range(_FUZZ_ITERS):
            line = "".join(
                rng.choice('data: [DONE]{}"x,5 \r') for _ in range(rng.randint(0, 20))
            )
            if line.startswith("data:"):
                continue
            events, done = self._sse(line)
            assert events == []
            assert not done

    def test_done_token_forms(self) -> None:
        """strip 后恰为 ``[DONE]`` 才 done；``data:[DONE]``（无空格）同样。"""
        for line in ("data: [DONE]", "data:[DONE]", "data:   [DONE]   "):
            events, done = self._sse(line)
            assert done
            assert [e.kind for e in events] == ["done"]
        for line in ("data: [DONE", "data: [DONE]x", "data: [done]"):
            events, done = self._sse(line)
            assert not done
            assert events == []

    def test_fuzz_json_lines_escape_family(self) -> None:
        """``data: <随机 JSON>``：产出事件或落 C2 逃逸族——绝不静默出 done。"""
        rng = random.Random(20261107)  # noqa: S311
        escapes: dict[str, int] = {}
        for _ in range(_FUZZ_ITERS):
            line = f"data: {json.dumps(_gen_json(rng))}"
            try:
                events, done = self._sse(line)
            except _SSE_ESCAPES as e:
                # CONFIRMED defect C2：非 dict/形状错 chunk 裸逃——记账到族
                escapes[type(e).__name__] = escapes.get(type(e).__name__, 0) + 1
                continue
            assert not done  # 只有 [DONE] 字面触发 done
            for ev in events:
                assert ev.kind in ("reasoning", "content", "done")
        assert escapes  # C2 逃逸面确实被 fuzz 命中过

    @pytest.mark.xfail(
        reason=(
            "CONFIRMED defect C2: data: <非 dict JSON> / choices 非 list / "
            "成员或 delta 非 dict → AttributeError/TypeError 裸逃；"
            "期望与坏 JSON 同待遇——跳过"
        ),
        strict=True,
    )
    @pytest.mark.parametrize(
        "line",
        [
            "data: 5",
            "data: null",
            'data: "x"',
            "data: [1,2]",
            "data: true",
            'data: {"choices": 5}',
            'data: {"choices": "x"}',
            'data: {"choices": [null]}',
            'data: {"choices": ["s"]}',
            'data: {"choices": [{"delta": "x"}]}',
        ],
    )
    def test_bad_shape_lines_skipped(self, line: str) -> None:
        """C2：非协议形状 data 行应被跳过而非抛出。"""
        events, done = self._sse(line)
        assert events == []
        assert not done

    def test_event_field_type_pollution_observed(self) -> None:
        """P9 观测：delta/finish_reason 非 str 原样进 ``StreamEvent`` 字段。"""
        events, _ = self._sse('data: {"choices": [{"delta": {"content": 5}}]}')
        assert events[0].delta == 5  # noqa: PLR2004 -- 观测：非 str 穿透
        events, _ = self._sse('data: {"choices": [{"finish_reason": 5}]}')
        assert events[0].finish_reason == 5  # noqa: PLR2004
        events, _ = self._sse(
            'data: {"choices": [{"delta": {"reasoning_content": ["x"]}}]}'
        )
        assert events[0].delta == ["x"]

    def test_multi_event_per_line_order(self) -> None:
        """单 chunk 多事件保序：reasoning → content → done。"""
        events, done = self._sse(
            'data: {"choices": [{"delta": {"reasoning_content": "r", '
            '"content": "c"}, "finish_reason": "stop"}]}'
        )
        assert not done
        assert [e.kind for e in events] == ["reasoning", "content", "done"]
        assert events[2].finish_reason == "stop"

    @pytest.mark.xfail(
        reason=(
            "CONFIRMED defect C2 wire-level: chat_stream 遇形状错 data 行 "
            "裸抛 AttributeError；期望跳过（流续走）或 ChatError"
        ),
        strict=True,
    )
    def test_stream_bad_chunk_survivable(self) -> None:
        """C2 e2e：流中夹杂 ``data: 5`` 应不炸流。"""
        sse = (
            b'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
            b"data: 5\n\n"
            b'data: {"choices":[{"delta":{"content":"b"}}]}\n\n'
            b"data: [DONE]\n\n"
        )
        c = _mock(lambda _r: httpx.Response(200, content=sse))

        async def collect() -> list[cl.StreamEvent]:
            return [ev async for ev in c.chat_stream("m", _MSGS)]

        events = asyncio.run(collect())
        assert [e.delta for e in events if e.kind == "content"] == ["a", "b"]

    def test_stream_dialect_ignored_observed(self) -> None:
        """观测语义：``chat_stream`` 恒走 OpenAI 方言——anthropic client 也
        打 ``/v1/chat/completions`` + Bearer 头（docstring 已声明仅 OpenAI）。"""
        reqs: list[httpx.Request] = []

        def handler(r: httpx.Request) -> httpx.Response:
            reqs.append(r)
            return httpx.Response(200, content=b"data: [DONE]\n\n")

        c = _mock(handler, base_url=_ANTHROPIC)

        async def collect() -> list[cl.StreamEvent]:
            return [ev async for ev in c.chat_stream("m", _MSGS)]

        asyncio.run(collect())
        assert reqs[0].url.path == "/v1/chat/completions"
        assert reqs[0].headers["authorization"] == f"Bearer {_KEY}"
        assert "x-api-key" not in reqs[0].headers


# ---------------------------------------------------------------- _parse_openai / _parse_anthropic


def _result_invariants(r: cl.ChatResult, latency: float) -> None:
    """产出 ChatResult 的硬不变量——任何形状下不得违反。"""
    assert r.content.strip(), "empty content must raise, not fabricate"
    assert r.finish_reason != "length"
    assert r.latency_s == round(latency, 3)
    assert isinstance(r.usage.prompt_tokens, int)
    assert isinstance(r.usage.completion_tokens, int)
    assert isinstance(r.usage.cached_tokens, int)


class TestParseOpenaiFuzz:
    def test_fuzz_payload_escape_family(self) -> None:
        """随机协议形状载荷 → ChatResult | ChatError | C3 逃逸族，三分天下。"""
        rng = random.Random(20261108)  # noqa: S311
        c = _mock(lambda _r: _json({}))
        outcomes: dict[str, int] = {"result": 0, "chaterror": 0, "escape": 0}
        for _ in range(_FUZZ_ITERS):
            payload = _gen_openai_payload(rng)
            try:
                r = c._parse_openai(payload, 0.5)  # noqa: SLF001
            except cl.ChatError:
                outcomes["chaterror"] += 1
            except _PARSE_ESCAPES:
                # CONFIRMED defect C3：形状错非 MalformedResponseError
                outcomes["escape"] += 1
            else:
                outcomes["result"] += 1
                _result_invariants(r, 0.5)
        assert outcomes["result"] > 0
        assert outcomes["escape"] > 0  # C3 逃逸面被命中
        assert outcomes["chaterror"] > 0

    @pytest.mark.xfail(
        reason=(
            "CONFIRMED defect C3: JSON 合法但形状错的 200 体裸抛 "
            "AttributeError/TypeError/ValueError——MalformedResponseError "
            "docstring 明言覆盖「形状不符」"
        ),
        strict=True,
    )
    @pytest.mark.parametrize(
        "payload",
        [
            {"choices": [None]},
            {"choices": ["x"]},
            {"choices": [5]},
            {"choices": "abc"},
            {"choices": 5},
            {"choices": {"0": {}}},
            {"choices": [{"message": "x"}]},
            {"choices": [{"message": 5}]},
            {"choices": [{"message": {"content": 5}, "finish_reason": "stop"}]},
            {"choices": [{"message": {"content": [1]}, "finish_reason": "stop"}]},
            {
                "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
                "usage": 5,
            },
            {
                "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": "abc"},
            },
            {
                "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens_details": 5},
            },
        ],
    )
    def test_malformed_shapes_typed_error(self, payload: dict[str, Any]) -> None:
        """C3：形状错 200 体应抛 ``MalformedResponseError`` 而非裸逃逸。"""
        c = _mock(lambda _r: _json(payload), base_url=_BYOK)
        with pytest.raises(cl.MalformedResponseError):
            asyncio.run(c.chat("m1", _MSGS))

    def test_wire_nonfinite_usage_escapes(self) -> None:
        """C3 wire 面：``1e999`` JSON 数值 → ``int(inf)`` ``OverflowError`` 裸逃。"""
        body = (
            '{"choices":[{"message":{"content":"x"},"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":1e999}}'
        )
        c = _mock(lambda _r: httpx.Response(200, text=body), base_url=_BYOK)
        # CONFIRMED defect C3 观测钉：OverflowError 而非 MalformedResponseError
        with pytest.raises(OverflowError):
            asyncio.run(c.chat("m1", _MSGS))

    def test_result_field_type_pollution_observed(self) -> None:
        """P9 观测：``model``/``finish_reason``/``reasoning_content`` 非 str
        原样进 ``ChatResult``——不校验不强转。"""
        c = _mock(lambda _r: _json({}))
        r = c._parse_openai(  # noqa: SLF001
            {
                "choices": [
                    {
                        "message": {"content": "x", "reasoning_content": 5},
                        "finish_reason": 5,
                    }
                ],
                "model": 5,
            },
            0.1,
        )
        assert r.model == 5  # noqa: PLR2004 -- 观测：非 str 穿透
        assert r.finish_reason == 5  # noqa: PLR2004
        assert r.reasoning == 5  # noqa: PLR2004

    def test_escape_bypasses_fallback_arm_observed(self) -> None:
        """C3 次生后果观测钉：解析逃逸不是 ``ChatError`` → 降级臂整体不触发。"""
        reqs: list[str] = []

        def handler(r: httpx.Request) -> httpx.Response:
            reqs.append(r.url.path)
            if r.url.path == "/v1/chat/completions":
                return _json({"choices": [None]})
            if r.url.path == "/panel/api/models":
                return _json({"models": [_panel_entry("alt")]})
            return _json({"data": [{"id": "alt"}]})

        c = _mock(handler)  # loopback 网关——本应触发发现
        with pytest.raises(AttributeError):  # CONFIRMED C3：裸逃且零探测
            asyncio.run(c.chat("m1", _MSGS))
        assert reqs == ["/v1/chat/completions"]


class TestParseAnthropicFuzz:
    def test_fuzz_payload_escape_family(self) -> None:
        rng = random.Random(20261109)  # noqa: S311
        c = _mock(lambda _r: _json({}), base_url=_ANTHROPIC)
        outcomes: dict[str, int] = {"result": 0, "chaterror": 0, "escape": 0}
        for _ in range(_FUZZ_ITERS):
            payload = _gen_anthropic_payload(rng)
            try:
                r = c._parse_anthropic(payload, 0.5)  # noqa: SLF001
            except cl.ChatError:
                outcomes["chaterror"] += 1
            except _PARSE_ESCAPES:
                # CONFIRMED defect C4
                outcomes["escape"] += 1
            else:
                outcomes["result"] += 1
                assert r.content.strip()
                assert r.finish_reason != "max_tokens"
        assert outcomes["result"] > 0
        assert outcomes["escape"] > 0  # C4 逃逸面被命中
        assert outcomes["chaterror"] > 0

    @pytest.mark.xfail(
        reason=(
            "CONFIRMED defect C4: anthropic 方言同族形状缝——error/content/"
            "usage 非 dict、blk 非 dict、text 非 str 全裸逃"
        ),
        strict=True,
    )
    @pytest.mark.parametrize(
        "payload",
        [
            {"type": "error", "error": "x"},
            {"type": "error", "error": 5},
            {"type": "message", "content": "text", "stop_reason": "end_turn"},
            {"type": "message", "content": 5, "stop_reason": "end_turn"},
            {"type": "message", "content": [None], "stop_reason": "end_turn"},
            {"type": "message", "content": ["x"], "stop_reason": "end_turn"},
            {
                "type": "message",
                "content": [{"type": "text", "text": "x"}],
                "stop_reason": "end_turn",
                "usage": 5,
            },
            {
                "type": "message",
                "content": [{"type": "text", "text": "x"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": "abc"},
            },
            {
                "type": "message",
                "content": [{"type": "text", "text": 5}],
                "stop_reason": "end_turn",
            },
        ],
    )
    def test_malformed_shapes_typed_error(self, payload: dict[str, Any]) -> None:
        """C4：anthropic 形状错 200 体应抛类型化错误而非裸逃逸。"""
        c = _mock(lambda _r: _json(payload), base_url=_ANTHROPIC)
        with pytest.raises(cl.ChatError):
            asyncio.run(c.chat("m", _MSGS))

    def test_anthropic_body_malformed_messages_observed(self) -> None:
        """P6 观测钉：缺键/非 dict messages → ``KeyError``/``TypeError`` 裸逃
        ``chat()``（调用方输入边界无校验）。"""
        c = _mock(lambda _r: _json({}), base_url=_ANTHROPIC)
        with pytest.raises(KeyError):  # CONFIRMED P6：缺 content
            asyncio.run(c.chat("m", [{"role": "system"}]))
        with pytest.raises(KeyError):  # 缺 role
            asyncio.run(c.chat("m", [{"content": "x"}]))
        with pytest.raises(TypeError):  # 非 dict 成员
            asyncio.run(c.chat("m", ["notadict"]))


# ---------------------------------------------------------------- discover / panel / list_models


class TestDiscoverFuzz:
    def _gateway(
        self,
        members: list[dict[str, Any]],
        v1: list[str],
        probed: list[str],
    ) -> Callable[[httpx.Request], httpx.Response]:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/panel/api/models":
                return _json({"models": members})
            if req.url.path == "/v1/models":
                return _json({"data": [{"id": u} for u in v1]})
            if req.url.path == "/v1/chat/completions":
                probed.append(str(json.loads(req.content)["model"]))
                return _json(_chat_payload("OK"))
            return httpx.Response(404)

        return handler

    @staticmethod
    def _oracle(members: list[dict[str, Any]], v1: set[str]) -> list[str]:
        """发现过滤的独立重放（只覆盖良形字段——畸形属 C5 逃逸面）。

        镜像 client.py:877-887 判定序：cost_tier → disabled → promo.active
        → uid 非空 → 非空 v1 交集（空 v1 不过滤——``/v1/models`` 挂了
        退化为只信 panel）。
        """
        out = []
        for m in members:
            if m.get("cost_tier") != "free":
                continue
            if m.get("disabled"):
                continue
            promo = m.get("promo")
            if not isinstance(promo, dict) or not promo.get("active"):
                continue
            uid = str(m.get("uid") or "")
            if not uid or (v1 and uid not in v1):
                continue
            out.append(uid)
        return out

    def test_fuzz_members_oracle(self) -> None:
        """随机 panel 成员集 → 返回 uid 序 == 独立 oracle 或落 C5 逃逸族。"""
        rng = random.Random(20261110)  # noqa: S311
        escapes = 0
        for _ in range(_FUZZ_ITERS_MED):
            members = [
                {
                    "uid": rng.choice(["a", "b", "c", "", 5, None]),
                    "cost_tier": rng.choice(["free", "paid", "FREE", 5]),
                    "disabled": rng.choice([False, True, "", "yes"]),
                    "promo": rng.choice(
                        [
                            {"active": True},
                            {"active": False},
                            {"active": 1},
                            {},
                            "yes",
                            None,
                        ]
                    ),
                    "context_tokens": rng.choice([0, 131072, "abc", True, None]),
                }
                for _ in range(rng.randint(0, 5))
            ]
            v1 = rng.choice([[], ["a"], ["a", "b", "c"]])
            probed: list[str] = []
            c = _mock(self._gateway(members, v1, probed))
            try:
                got = asyncio.run(c.discover_free_models(probe=False))
            except _DISCOVER_ESCAPES:
                escapes += 1  # CONFIRMED defect C5：promo 非 dict / ctx 非数值
                continue
            # 无逃逸 ⇒ 成员全良形或提前被滤——oracle 必须精确复现
            assert [m.uid for m in got] == self._oracle(members, set(v1))
        assert escapes > 0  # C5 逃逸面被命中

    @pytest.mark.xfail(
        reason=(
            "CONFIRMED defect C5: promo 非 dict → AttributeError、"
            "context_tokens 非数值/inf → ValueError/TypeError/OverflowError "
            "裸逃 discover_free_models；期望类型化错误或跳过该成员"
        ),
        strict=True,
    )
    @pytest.mark.parametrize(
        "member",
        [
            _panel_entry("a", promo="yes"),
            _panel_entry("a", promo=1),
            _panel_entry("a", promo=[{"active": True}]),
            _panel_entry("a", context_tokens="abc"),
            _panel_entry("a", context_tokens=[1]),
        ],
    )
    def test_malformed_member_typed(self, member: dict[str, Any]) -> None:
        """C5：畸形成员应类型化报错或跳过，不裸逃。"""
        probed: list[str] = []
        c = _mock(self._gateway([member], ["a"], probed))
        try:
            out = asyncio.run(c.discover_free_models(probe=False))
        except cl.ChatError:
            return  # 类型化错误属可接受修复
        assert isinstance(out, list)

    def test_context_tokens_inf_escapes_observed(self) -> None:
        """C5 观测钉：``context_tokens: 1e999`` → ``OverflowError`` 裸逃。"""

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/panel/api/models":
                return httpx.Response(
                    200,
                    text=(
                        '{"models":[{"uid":"a","cost_tier":"free",'
                        '"promo":{"active":true},"context_tokens":1e999}]}'
                    ),
                )
            if req.url.path == "/v1/models":
                return _json({"data": [{"id": "a"}]})
            return _json(_chat_payload("OK"))

        c = _mock(handler)
        # CONFIRMED defect C5：OverflowError 而非类型化错误
        with pytest.raises(OverflowError):
            asyncio.run(c.discover_free_models(probe=False))

    def test_malformed_member_swallowed_via_fallback_observed(self) -> None:
        """C5 两层观测：同一畸形成员经 ``fallback_candidates`` 被兜底成 ``[]``。"""
        c = _mock(self._gateway([_panel_entry("a", promo="yes")], ["a"], []))
        assert asyncio.run(c.fallback_candidates()) == []

    def test_member_field_coercion_observed(self) -> None:
        """P4 观测：uid/end_date 走 ``str()`` 强转——``5``→``"5"``、
        ``["x"]``→``"['x']"``、``2026``→``"2026"``；truthy ``active``/
        ``disabled`` 按真值计。"""
        probed: list[str] = []
        members = [
            _panel_entry(5),
            _panel_entry(["x"]),
            _panel_entry("gone", disabled="yes"),
            _panel_entry("live", promo={"active": "yes", "end_date": 2026}),
        ]
        c = _mock(self._gateway(members, [], probed))
        out = asyncio.run(c.discover_free_models(probe=False))
        assert [m.uid for m in out] == ["5", "['x']", "live"]
        assert out[-1].promo_end == "2026"


class TestListPanelAsymmetry:
    def test_scalar_toplevel_asymmetry_observed(self) -> None:
        """P12 观测：顶层标量 ``"nope"`` → panel 回 ``[]``、list 抛 Malformed。"""
        c = _mock(lambda _r: _json("nope"), base_url=_BYOK)
        assert asyncio.run(c.panel_models()) == []
        with pytest.raises(cl.MalformedResponseError):
            asyncio.run(c.list_models())

    @pytest.mark.xfail(
        reason=(
            "CONFIRMED defect C6: models 字段不可迭代（int/bool）→ TypeError "
            "裸逃；期望与 list_models 同口径 MalformedResponseError 或 []"
        ),
        strict=True,
    )
    @pytest.mark.parametrize("field", [5, True])
    def test_noniterable_models_field_typed(self, field: object) -> None:
        """C6：``{"models": <非可迭代>}`` 应类型化报错或回 ``[]``。"""
        c = _mock(lambda _r: _json({"models": field}), base_url=_BYOK)
        try:
            out = asyncio.run(c.panel_models())
        except cl.MalformedResponseError:
            return
        assert out == []

    def test_iterable_nondict_models_filtered_observed(self) -> None:
        """观测：``models`` 为 str/dict/混合 list → 逐成员 dict 过滤。"""
        for field, want in [
            ("s", []),
            ({"a": 1}, []),
            ([[1], {"uid": "x"}, "junk"], [{"uid": "x"}]),
            (None, []),
        ]:
            c = _mock(lambda _r, f=field: _json({"models": f}), base_url=_BYOK)
            assert asyncio.run(c.panel_models()) == want

    def test_list_models_id_coercion_observed(self) -> None:
        """P4 观测：``str(m["id"])`` 强转——``None``→``"None"``、``""`` 原样、
        ``true``→``"True"``、容器转 repr。"""
        c = _mock(
            lambda _r: _json(
                {
                    "data": [
                        {"id": None},
                        {"id": 5},
                        {"id": ""},
                        {"id": True},
                        {"id": ["x"]},
                    ]
                }
            ),
            base_url=_BYOK,
        )
        assert asyncio.run(c.list_models()) == ["None", "5", "", "True", "['x']"]


# ---------------------------------------------------------------- rank_models / pick_model


class TestRankModelsFuzz:
    def test_fuzz_oracle(self) -> None:
        """随机 FreeModel 集 → 偏好序前缀 + 其余字典序，无重复、∈ 探活集。"""
        rng = random.Random(20261111)  # noqa: S311
        pool = [
            "swe-2-medium",
            "swe-2-high",
            "swe-2-max",
            "glm-5-2",
            "a",
            "zz",
            "swe-1-7",
        ]
        for _ in range(_FUZZ_ITERS):
            discovered = [
                cl.FreeModel(uid=u, probe_ok=rng.random() < 0.6)  # noqa: PLR2004
                for u in (rng.choice(pool) for _ in range(rng.randint(0, 8)))
            ]
            out = cl.rank_models(discovered)
            alive = {m.uid for m in discovered if m.probe_ok} - set(
                cl.DEFAULT_MODEL_DENYLIST
            )
            assert set(out) == alive
            assert len(out) == len(set(out))
            pref = [u for u in cl.DEFAULT_MODEL_PREFERENCE if u in alive]
            assert out[: len(pref)] == pref
            assert out[len(pref) :] == sorted(set(out[len(pref) :]))

    def test_empty_uid_edge_observed(self) -> None:
        """P11 观测：``uid=""`` 探活成员 → ``pick_model`` 回 ``""``（falsy 非 None）。"""
        assert cl.rank_models([cl.FreeModel(uid="", probe_ok=True)]) == [""]
        assert cl.pick_model([cl.FreeModel(uid="", probe_ok=True)]) == ""

    def test_denylist_beats_preference(self) -> None:
        """denylist 一票否决优先于偏好序。"""
        out = cl.rank_models(
            [
                cl.FreeModel(uid="swe-1-7", probe_ok=True),
                cl.FreeModel(uid="swe-2-medium", probe_ok=True),
            ],
            preference=("swe-1-7", "swe-2-medium"),
        )
        assert out == ["swe-2-medium"]

    def test_dup_uid_alive_wins_observed(self) -> None:
        """观测：同 uid 死/活两条 → 活者胜（set 语义）。"""
        out = cl.rank_models(
            [
                cl.FreeModel(uid="a", probe_ok=True),
                cl.FreeModel(uid="a", probe_ok=False),
            ]
        )
        assert out == ["a"]


# ---------------------------------------------------------------- URL 面


class TestUrlSurfaces:
    def test_fuzz_never_raises(self) -> None:
        """三 URL 函数对任意 str 绝不抛。"""
        rng = random.Random(20261112)  # noqa: S311
        soup = "htp:/@.[]abcXYZ01234:/\t\n\x00é²-_%~?#&="
        for _ in range(_FUZZ_ITERS):
            u = "".join(rng.choice(soup) for _ in range(rng.randint(0, 30)))
            assert cl.provider_for_url(u) in (
                "gateway",
                "anthropic",
                "deepseek",
                "qwen",
                "openai",
                "custom",
            )
            assert isinstance(cl.is_free_gateway_url(u), bool)
            assert isinstance(cl.normalize_base_url(u), str)

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1.evil.com:3003",
            "http://localhost.attacker.example:3003",
            "http://evil.ts.net.attacker.example:3003",
            "http://100.63.255.255:3003",
            "http://100.128.0.0:3003",
            "http://2130706433:3003",  # 127.0.0.1 十进制编码——严格闸不认
            "http://0x7f.0.0.1:3003",  # 十六进制编码——同上
            "http://127.0.0.1.:3003",  # 尾点 loopback——保守 miss
            "http://ts.net:3003",  # 裸 ts.net 无子域
            "http://%6cocalhost:3003",  # %-编码不展开
            "http://[fd7a:115c:a1e0::1]:3003",  # tailnet IPv6——V4 网段外保守 miss
        ],
    )
    def test_hostile_lookalikes_rejected(self, url: str) -> None:
        """自由网关闸的敌意同形面一律拒——探活面不外溢。"""
        assert not cl.is_free_gateway_url(url)

    def test_scheme_ignored_observed(self) -> None:
        """P7 观测：闸只看 host——``ftp://``/protocol-relative 也认 loopback。"""
        assert cl.is_free_gateway_url("ftp://127.0.0.1:3003")
        assert cl.is_free_gateway_url("//127.0.0.1:3003")
        # schemeless 无 host → 保守 miss
        assert not cl.is_free_gateway_url("127.0.0.1:3003")

    def test_urlsplit_ws_stripping_divergence_observed(self) -> None:
        """P7 观测：``urlsplit`` 剥 ``\\t\\r\\n`` → 闸/provider 认 ``localhost``；
        httpx 请求期以 ``InvalidURL`` 拒——gate/actual 分歧方向保守（探测
        请求根本发不出）。"""
        u = "http://local\nhost:3003"
        assert cl.provider_for_url(u) == "gateway"
        assert cl.is_free_gateway_url(u)
        c = _mock(lambda _r: _json(_chat_payload()), base_url=u)
        with pytest.raises(cl.ChatError, match="invalid request URL"):
            asyncio.run(c.chat("m1", _MSGS))

    def test_userinfo_host_resolution(self) -> None:
        """``@`` 后才是真 host——userinfo 伪装不改变判定。"""
        assert cl.provider_for_url("http://evil.com@127.0.0.1:3003") == "gateway"
        assert cl.provider_for_url("http://127.0.0.1@evil.com:3003") == "custom"
        assert cl.is_free_gateway_url("http://user:pass@100.64.0.1:3003")
        assert not cl.is_free_gateway_url("http://user:pass@100.64.0.1.evil.com")

    def test_normalize_not_idempotent_observed(self) -> None:
        """P8 观测：单调用只剥一层已知后缀——叠层后缀需多次调用。"""
        assert cl.normalize_base_url("http://x/v1/v1") == "http://x/v1"
        assert cl.normalize_base_url(cl.normalize_base_url("http://x/v1/v1")) == (
            "http://x"
        )
        assert cl.normalize_base_url("http://x/V1") == "http://x/V1"  # 大小写敏感

    def test_fuzz_normalize_invariants(self) -> None:
        """归一输出恒无尾 ``/``；剥后缀只认三个已知形。"""
        rng = random.Random(20261113)  # noqa: S311
        suffixes = [
            "",
            "/",
            "/v1",
            "/V1",
            "/chat/completions",
            "/v1/chat/completions",
            "/api",
        ]
        for _ in range(_FUZZ_ITERS):
            u = "http://" + "".join(
                rng.choice("ab.:/01234") for _ in range(rng.randint(0, 10))
            )
            u += "".join(rng.choice(suffixes) for _ in range(rng.randint(0, 2)))
            out = cl.normalize_base_url(u)
            assert not out.endswith("/")


# ---------------------------------------------------------------- redact


class TestRedactFuzz:
    def test_fuzz_key_never_survives(self) -> None:
        """非空 api_key 值绝不留存输出；``redact`` 幂等。"""
        rng = random.Random(20261114)  # noqa: S311
        soup = [
            "Bearer ",
            "sk-",
            "abc",
            "token",
            "=",
            ":",
            " ",
            "12345678",
            "x",
            "***",
        ]
        for _ in range(_FUZZ_ITERS):
            t = "".join(rng.choice(soup) for _ in range(rng.randint(0, 8)))
            key = f"k{rng.randbytes(4).hex()}"
            once = cl.redact(t, key)
            assert key not in once, (t, key)
            assert cl.redact(once, key) == once  # 幂等

    def test_fuzz_secret_forms_covered(self) -> None:
        """已知 secret 形全灭：Bearer/sk-/sk-ant-/AIza/kv 族。"""
        rng = random.Random(20261115)  # noqa: S311
        for _ in range(_FUZZ_ITERS):
            tok = "".join(
                rng.choice("abcdefghijABCDEFGH_0123456789-")
                for _ in range(rng.randint(10, 24))
            )
            form = rng.choice(
                [
                    f"Bearer {tok}",
                    f"bearer {tok}",
                    f"sk-{tok}",
                    f"sk-ant-{tok}",
                    f"AIza{tok}",
                    f"token={tok}",
                    f"token:{tok}",
                    f"api_key={tok}",
                    f"x-api-key: {tok}",
                ]
            )
            out = cl.redact(f"prefix {form} suffix")
            assert tok not in out, form

    @pytest.mark.parametrize(
        ("text", "kept"),
        [
            ("token = abcdef", "abcdef"),  # ``=`` 前空格破 kv 模式
            ("password=abcdef", "abcdef"),  # 不在模式表
            ("key=abcdef", "abcdef"),  # 裸 key 不在模式表
            ("sk-short", "sk-short"),  # sk- 需 ≥8 位
            ("sk-ant-xy", "sk-ant-xy"),  # sk-ant- 需 ≥4 位
            ("api key=abcdef", "abcdef"),  # 空格破 api_key 形
        ],
    )
    def test_pattern_gaps_observed(self, text: str, kept: str) -> None:
        """P10 观测：模式表未覆盖的 secret 形原样留存——显式 api_key
        字面替换是唯一兜底。"""
        assert kept in cl.redact(text)


# ---------------------------------------------------------------- 请求组装 / 头


class TestRequestAssembly:
    def test_openai_headers_empty_key(self) -> None:
        """空 key → 零 Authorization 头（不发明凭证）。"""
        c = _mock(lambda _r: _json({}), api_key="")
        assert c._openai_headers() == {}  # noqa: SLF001

    def test_anthropic_headers_always_send_key_observed(self) -> None:
        """观测：anthropic 头恒发 ``x-api-key``——空 key 也发空值。"""
        c = _mock(lambda _r: _json({}), api_key="")
        h = c._anthropic_headers()  # noqa: SLF001
        assert h["x-api-key"] == ""
        assert h["anthropic-version"] == "2023-06-01"

    def test_extra_overrides_protocol_keys_observed(self) -> None:
        """P5 观测：``extra`` 可覆盖 ``model``/``messages``/``stream``。"""
        body = cl.ChatClient._openai_body(  # noqa: SLF001
            "m1",
            _MSGS,
            cl.ChatOptions(extra={"model": "evil", "messages": [], "stream": False}),
            stream=True,
        )
        assert body["model"] == "evil"
        assert body["messages"] == []
        assert body["stream"] is False

    def test_provider_override_wins(self) -> None:
        """显式 ``provider`` 压过 host 识别——custom host 走 anthropic 方言。"""
        reqs: list[httpx.Request] = []

        def handler(r: httpx.Request) -> httpx.Response:
            reqs.append(r)
            return _json(
                {
                    "type": "message",
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "x"}],
                }
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        c = cl.ChatClient(_BYOK, _KEY, provider="anthropic", http=http)
        asyncio.run(c.chat("m", _MSGS))
        assert reqs[0].url.path == "/v1/messages"

    @pytest.mark.xfail(
        reason=(
            "CONFIRMED defect C7: 非 ASCII api_key 在请求头编码期炸 "
            "UnicodeEncodeError 裸逃 chat()；期望类型化 ChatError"
        ),
        strict=True,
    )
    def test_nonascii_api_key_typed(self) -> None:
        """C7：``künstlîch`` 类 key 应报 ``ChatError`` 而非裸 UnicodeEncodeError。"""
        c = _mock(lambda _r: _json(_chat_payload()), api_key="künstlîch")
        with pytest.raises(cl.ChatError):
            asyncio.run(c.chat("m1", _MSGS))

    def test_local_protocol_error_retryable_observed(self) -> None:
        """P2 观测：``LocalProtocolError``（真线上非法 header 值形态）被归
        ``RetryableHTTPError`` 传输族——客户端配置错烧满退避。"""

        def boom(req: httpx.Request) -> httpx.Response:
            msg = "illegal header value"
            raise httpx.LocalProtocolError(msg, request=req)

        c = _mock(boom, base_url=_BYOK)
        with pytest.raises(cl.RetryableHTTPError) as ei:
            asyncio.run(c.chat("m1", _MSGS))
        assert ei.value.retryable
        assert ei.value.status < 0


# ---------------------------------------------------------------- chat() 降级臂 / sink


class TestFallbackArm:
    def _gateway(
        self,
        chat_status: dict[str, int],
        uids: tuple[str, ...] = ("aa-free", "zz-free"),
    ) -> Callable[[httpx.Request], httpx.Response]:
        """panel 报 uids 全活（探活恒 200）；真实 chat 按 chat_status 回码。"""

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/panel/api/models":
                return _json({"models": [_panel_entry(u) for u in uids]})
            if req.url.path == "/v1/models":
                return _json({"data": [{"id": u} for u in uids]})
            if req.url.path == "/v1/chat/completions":
                body = json.loads(req.content)
                uid = str(body["model"])
                if body["messages"][0]["content"] == _PROBE_TEXT:
                    return _json(_chat_payload("OK", model=uid))  # 探活恒活
                status = chat_status.get(uid, 200)
                if status != 200:  # noqa: PLR2004
                    return _json({"e": 1}, status=status)
                return _json(_chat_payload("OK", model=uid))
            return httpx.Response(404)

        return handler

    def test_mid_arm_non_switchable_aborts(self) -> None:
        """臂中遇非 switchable（401）立即上抛该错误——后续候选不再试。"""
        posts: list[str] = []

        def spy(r: httpx.Request) -> httpx.Response:
            if r.url.path == "/v1/chat/completions":
                body = json.loads(r.content)
                if body["messages"][0]["content"] != _PROBE_TEXT:
                    posts.append(str(body["model"]))
            return self._gateway({"first": 503, "aa-free": 401})(r)

        c = _mock(spy)
        with pytest.raises(cl.AuthError):
            asyncio.run(c.chat("first", _MSGS))
        assert posts == ["first", "aa-free"]  # zz-free 未被触及

    def test_all_fail_raises_last_observed(self) -> None:
        """候选全灭上抛**最后**一次失败——非首发错误。"""
        c = _mock(self._gateway({"m": 500, "aa-free": 503, "zz-free": 429}))
        with pytest.raises(cl.RetryableHTTPError) as ei:
            asyncio.run(c.chat("m", _MSGS))
        assert ei.value.status == 429  # noqa: PLR2004 -- 最后一个候选的错误

    def test_requested_model_skipped_in_candidates(self) -> None:
        """候选表含请求模型自身时跳过——不原地重打。"""
        posts: list[str] = []

        def spy(r: httpx.Request) -> httpx.Response:
            if r.url.path == "/v1/chat/completions":
                body = json.loads(r.content)
                if body["messages"][0]["content"] != _PROBE_TEXT:
                    posts.append(str(body["model"]))
            return self._gateway({"aa-free": 503}, uids=("aa-free", "zz-free"))(r)

        c = _mock(spy)
        r = asyncio.run(c.chat("aa-free", _MSGS))
        assert r.model == "zz-free"
        assert posts == ["aa-free", "zz-free"]

    def test_concurrent_discovery_single_flight(self) -> None:
        """并发 ``fallback_candidates`` 只跑一次发现（锁 + memoize）。"""
        panels: list[httpx.Request] = []

        def spy(r: httpx.Request) -> httpx.Response:
            if r.url.path == "/panel/api/models":
                panels.append(r)
            return self._gateway({})(r)

        c = _mock(spy)

        async def go() -> list[list[str]]:
            return list(
                await asyncio.gather(*(c.fallback_candidates() for _ in range(8)))
            )

        outs = asyncio.run(go())
        assert len(panels) == 1
        assert all(o == outs[0] for o in outs)

    def test_candidates_capped(self) -> None:
        """候选表 ≤ ``FALLBACK_MAX_CANDIDATES``——发现更多也截。"""
        uids = ("swe-2-medium", "swe-2-high", "swe-2-max", "glm-5-2", "zz5")
        c = _mock(self._gateway({}, uids=uids))
        out = asyncio.run(c.fallback_candidates())
        assert out == list(uids[: cl.FALLBACK_MAX_CANDIDATES])
        assert cl.FALLBACK_MAX_CANDIDATES == 3  # noqa: PLR2004


class TestUsageSinkFuzz:
    def test_fuzz_sink_once_per_success(self) -> None:
        """任意 (status, body) 下 sink 恰记一笔 iff 拿到 ChatResult。"""
        rng = random.Random(20261116)  # noqa: S311
        for _ in range(_FUZZ_ITERS_WIRE):
            recs: list[cl.UsageRecord] = []
            status = rng.choice([200, 200, 200, 400, 401, 404, 429, 500, 503])
            payload = _gen_openai_payload(rng) if status == 200 else {"e": 1}  # noqa: PLR2004
            c = _mock(
                lambda _r, p=payload, s=status: httpx.Response(s, text=json.dumps(p)),
                base_url=_BYOK,
                usage_sink=recs.append,
            )
            try:
                r = asyncio.run(c.chat("m1", _MSGS))
            except cl.ChatError:
                assert recs == []
            except _PARSE_ESCAPES:
                # CONFIRMED defect C3 wire 面：形状逃逸同样不记账
                assert recs == []
            else:
                _result_invariants(r, r.latency_s)
                assert len(recs) == 1
                rec = recs[0]
                assert rec["prompt_tokens"] == r.usage.prompt_tokens
                assert rec["completion_tokens"] == r.usage.completion_tokens

    def test_sink_records_payload_model_observed(self) -> None:
        """P3 观测：sink 记响应自报 ``model``——缺字段记 ``""``，非请求模型。"""
        recs: list[cl.UsageRecord] = []
        c = _mock(
            lambda _r: _json({"choices": [{"message": {"content": "OK"}}]}),
            usage_sink=recs.append,
        )
        asyncio.run(c.chat("requested-model", _MSGS))
        assert recs[0]["model"] == ""


# ---------------------------------------------------------------- probe_model


class TestProbeFuzz:
    def test_fuzz_never_raises_oracle(self) -> None:
        """任意响应形态只回 ``FreeModel``——``probe_ok`` 与独立判据一致。"""
        rng = random.Random(20261117)  # noqa: S311
        for _ in range(_FUZZ_ITERS_WIRE):
            status = rng.choice([200, 200, 200, 429, 500, 503])
            payload = _gen_openai_payload(rng)
            c = _mock(
                lambda _r, p=payload, s=status: httpx.Response(s, text=json.dumps(p))
            )
            fm = asyncio.run(c.probe_model("m1"))  # 任意形状绝不抛
            assert isinstance(fm, cl.FreeModel)
            assert fm.probe_latency_s >= 0
            if status != 200:  # noqa: PLR2004
                assert not fm.probe_ok
                assert fm.probe_error == f"HTTP {status}"
            elif fm.probe_ok:
                # oracle：content 非空白 ∧ finish ∈ {None, "stop"}
                choices = payload.get("choices")
                ch = choices[0] if isinstance(choices, list) and choices else {}
                content = (ch.get("message") or {}).get("content") or ""
                assert content.strip()
                assert ch.get("finish_reason") in (None, "stop")
            else:
                assert fm.probe_error

    def test_probe_error_capped_200(self) -> None:
        """观测：异常文本进 ``probe_error`` 截 200 字符。"""

        def boom(_r: httpx.Request) -> httpx.Response:
            msg = "x" * 500
            raise httpx.ConnectError(msg)

        c = _mock(boom)
        fm = asyncio.run(c.probe_model("m1"))
        assert not fm.probe_ok
        assert len(fm.probe_error) <= 200  # noqa: PLR2004


# ---------------------------------------------------------------- 合同违约错误字段语义


class TestErrorFieldSemantics:
    def test_length_status_minus_one_observed(self) -> None:
        """P1 观测钉：``LengthTruncatedError.status == -1``——同族
        Empty/Malformed 记 200，独它谎称传输层。"""
        e = cl.LengthTruncatedError("x")
        assert e.status == -1  # PLAUSIBLE defect：应为 200
        assert cl.EmptyContentError("x").status == 200  # noqa: PLR2004
        assert cl.MalformedResponseError("x").status == 200  # noqa: PLR2004

    def test_length_backoff_timeout_floor_observed(self) -> None:
        """P1 次生观测：status<0 走 ``timeout_floor``——合同违约拿传输级退避。"""
        p = RetryPolicy()
        d_length = _backoff_delay(cl.LengthTruncatedError("x"), 0, p)
        d_empty = _backoff_delay(cl.EmptyContentError("x"), 0, p)
        assert d_length is not None
        assert d_empty is not None
        assert d_length == p.timeout_floor
        assert d_empty == p.base_delay
        assert d_length > d_empty  # 10s vs 1s——观测倒挂

    def test_error_fields_roundtrip(self) -> None:
        """``ChatError`` 字段构造面：status/retryable/retry_after/max_tries。"""
        e = cl.ChatError("m", status=418, retryable=True, retry_after=3.0, max_tries=7)
        assert (e.status, e.retryable, e.retry_after, e.max_tries) == (
            418,
            True,
            3.0,
            7,
        )
        # 子类默认参数面
        assert cl.AuthError("x").max_tries is None
        assert cl.RetryableHTTPError("x", retryable=True).max_tries is None
        e2 = cl.LengthTruncatedError("x", partial_content="半")
        assert e2.partial_content == "半"
        assert e2.max_tries == 2  # noqa: PLR2004


# ---------------------------------------------------------------- chat() 综合不变量


class TestChatWireFuzz:
    def test_fuzz_only_known_outcomes(self) -> None:
        """任意 (status, payload) 下 ``chat()`` 三分天下：
        ChatResult | ChatError | C3 逃逸族——绝不静默返回错误内容。"""
        rng = random.Random(20261118)  # noqa: S311
        escapes = 0
        for _ in range(_FUZZ_ITERS_WIRE):
            status = rng.choice([200, 200, 200, 400, 401, 402, 404, 408, 429, 500, 503])
            payload = _gen_openai_payload(rng) if status == 200 else {"e": "x"}  # noqa: PLR2004
            c = _mock(
                lambda _r, p=payload, s=status: httpx.Response(s, text=json.dumps(p)),
                base_url=_BYOK,
            )
            err: cl.ChatError | None = None
            try:
                r = asyncio.run(c.chat("m1", _MSGS))
            except cl.ChatError as e:
                err = e
            except _PARSE_ESCAPES:
                escapes += 1  # CONFIRMED defect C3：200 形状缝裸逃
            else:
                _result_invariants(r, r.latency_s)
            if err is not None and status != 200:  # noqa: PLR2004
                assert err.status == status
        assert escapes > 0  # C3 逃逸面被命中

    def test_fuzz_stream_only_known_outcomes(self) -> None:
        """随机 SSE 字节汤 → 事件流 | ChatError | C2 逃逸族；
        ``[DONE]`` 之后绝不再产事件。"""
        rng = random.Random(20261119)  # noqa: S311
        soup_lines = [
            'data: {"choices":[{"delta":{"content":"x"}}]}',
            'data: {"choices":[{"finish_reason":"stop"}]}',
            "data: [DONE]",
            "data: {bad json}",
            "data: 5",
            ": comment",
            "",
            "data: null",
            "junk line",
        ]
        for _ in range(_FUZZ_ITERS_WIRE):
            lines = [rng.choice(soup_lines) for _ in range(rng.randint(0, 8))]
            body = ("\n\n".join(lines) + "\n\n").encode()
            c = _mock(lambda _r, b=body: httpx.Response(200, content=b))
            try:

                async def collect(
                    client: cl.ChatClient = c,
                ) -> list[cl.StreamEvent]:
                    return [ev async for ev in client.chat_stream("m", _MSGS)]

                events = asyncio.run(collect())
            except cl.ChatError:
                continue
            except _SSE_ESCAPES:
                continue  # CONFIRMED defect C2：形状缝裸逃
            # [DONE] 命中即 return——其后行不得产事件
            done_idx = next(
                (i for i, ln in enumerate(lines) if ln.strip() == "data: [DONE]"),
                len(lines),
            )
            live = lines[:done_idx]
            max_content = sum('content":"x"' in ln for ln in live)
            got_content = sum(
                1 for e in events if e.kind == "content" and e.delta == "x"
            )
            assert got_content == max_content
