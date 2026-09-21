"""retry.py 退避/切分机械对抗/性质测试——test_fuzz_xlat_batch 已钉面之外的残余面。

分工：batch 文件钉死 ``_valid_slot_text`` 契约矩阵与非规范形、``_make_slots``
基础形态、``_assemble_slots`` identity oracle、``_slots_round`` 分组/反馈/
失败形态、``_stage_slots`` 三端（exhaustion/重问/无散文）；``test_xlat_retry``
钉退避节奏与阶梯 happy/sad 主路径；槽位机械归 ``test_fuzz_xlat_slots``、
阶梯不变量与槽文象形面归 ``test_fuzz_xlat_ladder``。本文件收残余面：

- ``call_with_backoff`` 退化策略面：``max_tries<1`` 入口即拒
  （``ValueError``——曾落名不副实的 ``"unreachable"`` ChatError，可达且
  ``fn`` 零调用）、错误自带 ``max_tries`` 收窄/不可放宽、
  非 ``(ChatError, TimeoutError)`` 异常零翻身直接穿透、``retry_after``
  对非 429 同样优先；
- ``_split_lines_scoped`` 平铺不变量（``join(parts)`` 恒为 ``text``——
  切点后纯 ``\\t``/``\\xa0`` 尾片并入前片保字节；含转义句号/``{}`` 深度/
  未闭合 ``{``/``\\t``/``\\xa0`` 非分隔的对抗形）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from _fuzzkit import fuzz_rng

from texlate.xlat import retry as rt
from texlate.xlat.client import ChatError, RetryableHTTPError

# ---------------------------------------------------------------- 私有面薄封装
# 下方薄封装/伪件同时是 ``test_fuzz_xlat_slots``/``test_fuzz_xlat_ladder`` 的
# 共享脚手架——两文件经 ``from test_fuzz_xlat_retry import`` 取件
# （``test_fixloop_loop`` 枢纽先例同法），勿因本文件未直用而删。

_vst = rt._valid_slot_text  # noqa: SLF001 -- 私有契约正是被测面
_make_slots = rt._make_slots  # noqa: SLF001
_slots_round = rt._slots_round  # noqa: SLF001
_split_lines = rt._split_lines_scoped  # noqa: SLF001

_FUZZ_MED = 1500

_SlotsFn = Callable[[dict[str, str], str], Awaitable[dict[str, str]]]


class _SlotCtx:
    """``_slots_round`` 的最小伪 ctx——该方法只触 ``attempts``/``slots_fn``。"""

    def __init__(self, slots_fn: _SlotsFn) -> None:
        self.attempts = 0
        self.slots_fn = slots_fn


async def _drop_ph(_text: str, _feedback: str) -> str:
    """永丢占位符的 translate_fn——整段/行级必败，直通 slots 阶段。"""
    return "译文没有任何占位符"


async def _empty_slots(_group: dict[str, str], _failures: str) -> dict[str, str]:
    return {}


def _recon(slots: dict[str, str], seq: list[tuple[str, str]]) -> str:
    """seq 平铺 oracle——``slot`` 项查 ``slots``、``ph``/``raw`` 原样回拼。"""
    return "".join(slots[p] if k == "slot" else p for k, p in seq)


# ---------------------------------------------------------------- call_with_backoff 退化面


class TestBackoffEdges:
    def test_zero_max_tries_rejected_without_calling(self) -> None:
        """``max_tries<1`` 入口即拒 ``ValueError``——原先循环体不执行、
        ``last=None`` 落到 ``ChatError("unreachable")`` 名不副实（可达）；
        策略配置错误应响，``fn`` 零调用不变。"""
        calls: list[int] = []

        async def fn() -> str:
            calls.append(1)
            return "x"

        with pytest.raises(ValueError, match="max_tries"):
            asyncio.run(
                rt.call_with_backoff(
                    fn, policy=rt.RetryPolicy(max_tries=0, base_delay=0.0)
                )
            )
        assert calls == []

    def test_max_tries_one_never_sleeps(self) -> None:
        """observed: ``max_tries=1`` 首发即终试——retryable 错误也直接抛。"""
        calls = 0

        async def flaky() -> str:
            nonlocal calls
            calls += 1
            msg = "boom"
            raise RetryableHTTPError(msg, status=500, retryable=True)

        with pytest.raises(RetryableHTTPError):
            asyncio.run(
                rt.call_with_backoff(
                    flaky, policy=rt.RetryPolicy(max_tries=1, base_delay=0.0)
                )
            )
        assert calls == 1

    def test_non_chaterror_exception_no_retry(self) -> None:
        """observed: ``except (ChatError, TimeoutError)`` 之外的原生异常
        （RuntimeError…）零翻身直接穿透——退避网只罩传输层。"""
        calls = 0

        async def boom() -> str:
            nonlocal calls
            calls += 1
            msg = "bare crash"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError):
            asyncio.run(
                rt.call_with_backoff(
                    boom, policy=rt.RetryPolicy(max_tries=5, base_delay=0.0)
                )
            )
        assert calls == 1

    def test_error_own_max_tries_narrows_policy(self) -> None:
        """observed: ``e.max_tries`` 独立于 policy 收窄总试数——
        ``max_tries=1`` 的错误在 ``max_tries=5`` 策略下也零翻身。"""
        calls = 0

        async def one_shot() -> str:
            nonlocal calls
            calls += 1
            msg = "narrow"
            raise ChatError(msg, status=500, retryable=True, max_tries=1)

        with pytest.raises(ChatError):
            asyncio.run(
                rt.call_with_backoff(
                    one_shot, policy=rt.RetryPolicy(max_tries=5, base_delay=0.0)
                )
            )
        assert calls == 1

    def test_error_max_tries_cannot_widen_policy(self) -> None:
        """observed: ``min(policy, e.max_tries)``——错误 ``max_tries=99``
        在 ``max_tries=2`` 策略下仍只试 2 次。"""
        calls = 0

        async def wide() -> str:
            nonlocal calls
            calls += 1
            msg = "wide"
            raise ChatError(msg, status=500, retryable=True, max_tries=99)

        with pytest.raises(ChatError):
            asyncio.run(
                rt.call_with_backoff(
                    wide, policy=rt.RetryPolicy(max_tries=2, base_delay=0.0)
                )
            )
        assert calls == 2  # noqa: PLR2004 -- policy 封顶

    def test_retry_after_honored_on_non_429(
        self, recorded_sleeps: list[float]
    ) -> None:
        """observed: ``retry_after`` 优先于一切分类分支——500 携带也从其值。"""

        async def five_hundred() -> str:
            msg = "err"
            raise RetryableHTTPError(msg, status=500, retryable=True, retry_after=3.0)

        pol = rt.RetryPolicy(
            max_tries=2, base_delay=1.0, rate_limit_floor=9.0, timeout_floor=9.0
        )
        with pytest.raises(RetryableHTTPError):
            asyncio.run(rt.call_with_backoff(five_hundred, policy=pol))
        assert recorded_sleeps == [3.0]


# ---------------------------------------------------------------- _split_lines_scoped


class TestSplitLinesScoped:
    def test_join_is_lossless_identity(self) -> None:
        """observed: parts 平铺 ``[0, n)``——``join(parts)==text`` 对常规
        输入恒等（每片必含分隔符本身；唯一例外是尾片，见下）。"""
        for t in [
            "Hello. World. Bye.",
            "a {b. c} d. e",
            "esc\\. not split. yes.",
            "trailing.",
            "no split",
            "",
            "a } b. c",
            "unclosed {depth. stays one",
            "x! y? z",
            "dot.\ttab not delimiter",
            "dot.\xa0nbsp not delimiter",
        ]:
            assert "".join(_split_lines(t)) == t

    def test_trailing_whitespace_only_tail_merged(self) -> None:
        """``\\t``/``\\xa0`` 不在分隔符后随空白消费集（``" \\n"``）——
        切点后残留的纯空白尾片并入前片而非独立成项（独立项过不了非空判定
        会被丢：``join(parts)`` 丢尾部字节——已修为并入语义，平铺恒等）。"""
        assert _split_lines("aaaa. \t") == ["aaaa. \t"]
        assert _split_lines("aaaa. \xa0") == ["aaaa. \xa0"]
        assert _split_lines("aaaa. bbbb. \t") == ["aaaa. ", "bbbb. \t"]
        assert "".join(_split_lines("a. \t b. ")) == "a. \t b. "
        # " "/"\\n" 尾随照旧被切点消费进前片
        assert "".join(_split_lines("a.   ")) == "a.   "
        assert "".join(_split_lines("a. \n")) == "a. \n"

    def test_fuzz_join_prefix_whitespace_tail(self) -> None:
        """随机 ``{``/``}``/``\\``/``.!?``/空白汤不变量：
        ``join(parts)`` 恒为 ``text`` 前缀，余部只允许纯空白
        （被丢的只可能是尾片——中间片必含分隔符）。"""
        rng = fuzz_rng(20260917)
        alphabet = ["a", "b", ".", "!", "?", "{", "}", "\\", " ", "\n", "\t", "z"]
        for _ in range(4000):
            t = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
            joined = "".join(_split_lines(t))
            assert t.startswith(joined), t
            assert not t[len(joined) :].strip(), t

    def test_delimiter_boundary_shapes(self) -> None:
        """observed: 切点 = 深度 0 的 ``.!?`` + 紧随 `` ``/``\\n``；分隔符
        与其后空白并入前片（除尾片外各片以 ``[.!?]\\s*$`` 收尾）。"""
        parts = _split_lines("Onex. Twox! Three? Four")
        assert parts == ["Onex. ", "Twox! ", "Three? ", "Four"]
        for p in parts[:-1]:
            assert p[-1] == " "
            assert p[-2] in ".!?"

    def test_tab_and_nbsp_not_delimiters(self) -> None:
        """observed: ``.\\t``/``.\\xa0`` 不切——后继字符白名单只有 `` ``/``\\n``。"""
        assert _split_lines("a.\tb") == ["a.\tb"]
        assert _split_lines("a.\xa0b") == ["a.\xa0b"]

    def test_escaped_delimiter_never_splits(self) -> None:
        """observed: ``\\.`` 被 ``\\`` 双跳吞掉——转义句号不产生切点；
        尾置反斜杠 ``i+=2`` 越界自然终止不炸。"""
        assert _split_lines("esc\\. midd. tail") == ["esc\\. midd. ", "tail"]
        assert _split_lines("end with bs\\") == ["end with bs\\"]

    def test_brace_depth_suppresses_splits(self) -> None:
        """observed: ``{`` 内 ``.`` 不切；``}`` 深度钳 0——游离 ``}`` 不抑制
        后续切分；未闭合 ``{`` 之后深度永 >0，残余文本成一整片。"""
        assert _split_lines("{aaaa. b} cccc. d") == ["{aaaa. b} cccc. ", "d"]
        assert _split_lines("aaaa } bbbb. c") == ["aaaa } bbbb. ", "c"]
        assert _split_lines("xxxx {yyyy. zzzz. w") == ["xxxx {yyyy. zzzz. w"]
