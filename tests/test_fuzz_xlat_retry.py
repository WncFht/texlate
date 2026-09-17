"""retry.py 阶梯机械对抗/性质测试——test_fuzz_xlat_batch 已钉面之外的残余面。

分工：batch 文件钉死 ``_valid_slot_text`` 契约矩阵与非规范形、``_make_slots``
基础形态、``_assemble_slots`` identity oracle、``_slots_round`` 分组/反馈/
失败形态、``_stage_slots`` 三端（exhaustion/重问/无散文）；``test_xlat_retry``
钉退避节奏与阶梯 happy/sad 主路径。本文件收残余面：

- ``call_with_backoff`` 退化策略面：``max_tries<1`` 入口即拒
  （``ValueError``——曾落名不副实的 ``"unreachable"`` ChatError，可达且
  ``fn`` 零调用）、错误自带 ``max_tries`` 收窄/不可放宽、
  非 ``(ChatError, TimeoutError)`` 异常零翻身直接穿透、``retry_after``
  对非 429 同样优先；
- ``_split_lines_scoped`` 平铺不变量（``join(parts)`` 恒为 ``text``——
  切点后纯 ``\\t``/``\\xa0`` 尾片并入前片保字节；含转义句号/``{}`` 深度/
  未闭合 ``{``/``\\t``/``\\xa0`` 非分隔的对抗形）；
- ``_make_slots``：seq 平铺编码文的覆盖 oracle、>``SLOT_MAX_CHARS`` 空白
  run 整片按 ``raw`` 记账保 seq 平铺（曾整片丢弃静默丢字节）、cs 名与其
  ``{arg}`` 之间不再允许切分、槽号 ``%04d`` 超 4 位仍规范、槽散文含
  字面 ``[[x]]`` 的拒收张力（echo 必拒、丢弃零信号）；
- ``_slots_round``：跨组应答键被忽略（不提前落 ``translated``）、非 dict
  Mapping 拒收、``CancelledError`` 穿透 ``except Exception``、跨轮
  ``failures`` 反馈含 ``"no answer"`` 项、组参 ``group`` mutation 不再丢答
  （结算按发送时键快照迭代——曾重读可变 dict，回调清空连自己应答一并弃，
  失败归因误记 ``"no answer"``）、组内 ``ChatError`` 即抛截断本轮；
- 阶梯不变量：乱注 chaos 下终止有界 + ``status``↔``stage`` 一致 +
  ``fallback_orig`` 时 ``translation==source`` 逐字节 + warning 序列定式 +
  ``best-effort`` 200 字截断、slots 阶段 ``ChatError`` 直接穿透弃
  ``best_zh``（不走 fallback）、``translate_fn`` 收编码文 vs
  ``corrector_fn`` 收原文的不对称、``repair_fn`` 抄回警告面、默认校验的
  echo 盲点、行级逐行必发 + 行败可互消、槽位进展不续轮、部分答成全弃；
- ``_valid_slot_text`` 象形括号面：``⟦⟧《》「」［］⟨⟩｟｠`` 贴
  ``S\\d{4,}`` 的形变回显拒收（``_SLOT_ECHO_RX``——``diff`` 看不见这类
  残码，入口拒是唯一兜网；裸 ``S0000``/``［1］`` 不误伤）、
  ``\\u200b``/``\\ufeff`` 零宽-only 值按无可见字符拒收。
"""

from __future__ import annotations

import asyncio
import json
import random
import types
from collections.abc import Awaitable, Callable

import pytest

from texlate.xlat import placeholders as ph
from texlate.xlat import retry as rt
from texlate.xlat.client import AuthError, ChatError, RetryableHTTPError

# ---------------------------------------------------------------- 私有面薄封装

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
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """observed: ``retry_after`` 优先于一切分类分支——500 携带也从其值。"""
        sleeps: list[float] = []

        async def fake_sleep(d: float) -> None:
            sleeps.append(d)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        async def five_hundred() -> str:
            msg = "err"
            raise RetryableHTTPError(msg, status=500, retryable=True, retry_after=3.0)

        pol = rt.RetryPolicy(
            max_tries=2, base_delay=1.0, rate_limit_floor=9.0, timeout_floor=9.0
        )
        with pytest.raises(RetryableHTTPError):
            asyncio.run(rt.call_with_backoff(five_hundred, policy=pol))
        assert sleeps == [3.0]


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
        assert _split_lines("a. \t") == ["a. \t"]
        assert _split_lines("a. \xa0") == ["a. \xa0"]
        assert _split_lines("a. b. \t") == ["a. ", "b. \t"]
        assert "".join(_split_lines("a. \t b. ")) == "a. \t b. "
        # " "/"\\n" 尾随照旧被切点消费进前片
        assert "".join(_split_lines("a.   ")) == "a.   "
        assert "".join(_split_lines("a. \n")) == "a. \n"

    def test_fuzz_join_prefix_whitespace_tail(self) -> None:
        """随机 ``{``/``}``/``\\``/``.!?``/空白汤不变量：
        ``join(parts)`` 恒为 ``text`` 前缀，余部只允许纯空白
        （被丢的只可能是尾片——中间片必含分隔符）。"""
        rng = random.Random(20260917)  # noqa: S311 -- 确定性种子
        alphabet = ["a", "b", ".", "!", "?", "{", "}", "\\", " ", "\n", "\t", "z"]
        for _ in range(4000):
            t = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
            joined = "".join(_split_lines(t))
            assert t.startswith(joined), t
            assert not t[len(joined) :].strip(), t

    def test_delimiter_boundary_shapes(self) -> None:
        """observed: 切点 = 深度 0 的 ``.!?`` + 紧随 `` ``/``\\n``；分隔符
        与其后空白并入前片（除尾片外各片以 ``[.!?]\\s*$`` 收尾）。"""
        parts = _split_lines("One. Two! Three? Four")
        assert parts == ["One. ", "Two! ", "Three? ", "Four"]
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
        assert _split_lines("esc\\. mid. tail") == ["esc\\. mid. ", "tail"]
        assert _split_lines("end with bs\\") == ["end with bs\\"]

    def test_brace_depth_suppresses_splits(self) -> None:
        """observed: ``{`` 内 ``.`` 不切；``}`` 深度钳 0——游离 ``}`` 不抑制
        后续切分；未闭合 ``{`` 之后深度永 >0，残余文本成一整片。"""
        assert _split_lines("{a. b} c. d") == ["{a. b} c. ", "d"]
        assert _split_lines("a } b. c") == ["a } b. ", "c"]
        assert _split_lines("x {y. z. w") == ["x {y. z. w"]


# ---------------------------------------------------------------- _make_slots 对抗面


class TestMakeSlotsAdversarial:
    def test_seq_tiles_encoded_oracle(self) -> None:
        """observed: seq 载荷解析回源即平铺——``slot→slots[sid]``、
        ``ph``/``raw`` 原样，``join == encoded``。"""
        for enc in [
            "alpha [[MATH_1]] beta [[CITE_2]] gamma",
            "a  [[MATH_1]]   b",
            "lead [[MATH_1]]",
            "[[MATH_1]] tail",
            "x [[SL]] y [[PL]] z",
            "see [[math_1]] literal [[MATH_1]] tail",
        ]:
            slots, seq = _make_slots(enc)
            recon = "".join(slots[p] if k == "slot" else p for k, p in seq)
            assert recon == enc, enc

    def test_fuzz_seq_tiles_encoded(self) -> None:
        """随机编码文：seq 平铺恒等（生成面不含 >``SLOT_MAX_CHARS`` 空白
        run——那是下方 CONFIRMED 丢片缺陷的独立触发面）。"""
        rng = random.Random(20260917)  # noqa: S311 -- 确定性种子
        soup = ["word ", "[[MATH_1]]", "[[CITE_2]]", "[[SL]]", " ", "x", " t", "~"]
        for _ in range(_FUZZ_MED):
            enc = "".join(rng.choice(soup) for _ in range(rng.randint(0, 15)))
            slots, seq = _make_slots(enc)
            recon = "".join(slots[p] if k == "slot" else p for k, p in seq)
            assert recon == enc, enc

    def test_whitespace_run_piece_kept_as_raw(self) -> None:
        """散文段内 >``SLOT_MAX_CHARS`` 的纯空白 run 经 ``split_long_chunk``
        拆出的整片按 ``raw`` 记账——seq 仍平铺覆盖 encoded，装配译文不丢
        字节（曾整体丢弃：seq 无痕迹、静默丢 ~1500 字符空白）。"""
        seg = "a" + " " * (rt.SLOT_MAX_CHARS * 2) + "b"
        slots, seq = _make_slots(seg)
        recon = "".join(slots[p] if k == "slot" else p for k, p in seq)
        assert recon == seg
        # 空白整片以 raw 项留在 seq——两槽之间不再无声
        assert [k for k, _ in seq] == ["slot", "raw", "slot"]

    def test_no_cut_between_cs_name_and_arg(self) -> None:
        """cs 名与其 ``{arg}`` 是复合原子——切点不再落在 ``\\textbf`` 与
        ``{AAAA}`` 之间（曾：前一槽悬 ``\\textbf`` 收尾、后一槽孤儿 ``{arg}``
        起头，两槽独立送翻模型看不到配对结构）。"""
        head = "x" * (rt.SLOT_MAX_CHARS - 7)
        seg = head + "\\textbf{AAAA} " + "y" * 800
        slots, _seq = _make_slots(seg)
        vals = list(slots.values())
        assert vals[0].endswith("x")
        assert vals[1].startswith("\\textbf{AAAA}")

    def test_slot_names_canonical_past_four_digits(self) -> None:
        """observed: ``%04d`` 是最小宽度——第 10001 槽 ``⟪S10000⟫`` 仍命中
        ``⟪S\\d{4,}⟫`` 规范形（位数只增不破）。"""
        enc = " [[MATH_1]] ".join(f"p{i}" for i in range(10_001))
        slots, _seq = _make_slots(enc)
        assert len(slots) == 10_001  # noqa: PLR2004 -- 万槽直数
        last = f"⟪S{10_000:04d}⟫"
        assert last == "⟪S10000⟫"
        assert last in slots
        assert rt.SLOT_NAME_RX.fullmatch(last)

    def test_fuzz_slot_names_canonical_sequential(self) -> None:
        """随机输入：槽键恰为 ``⟪S{i:04d}⟫`` 连续枚举，seq 槽序同构。"""
        rng = random.Random(20260917)  # noqa: S311 -- 确定性种子
        soup = ["a", " [[MATH_1]] ", "[[CITE_2]]", " ", "b ", "\n"]
        for _ in range(600):
            enc = ph.encode_newlines(
                "".join(rng.choice(soup) for _ in range(rng.randint(0, 20)))
            )[0]
            slots, seq = _make_slots(enc)
            want = [f"⟪S{i:04d}⟫" for i in range(len(slots))]
            assert sorted(slots) == want
            assert [p for k, p in seq if k == "slot"] == want
            assert all(rt.SLOT_NAME_RX.fullmatch(k) for k in slots)

    def test_literal_double_bracket_lives_in_slot_prose(self) -> None:
        """CONFIRMED 拒收张力：非规范字面 ``[[math_1]]`` 不是 ANY_PH_RX
        占位符——留在散文槽值里；模型忠实 echo 必被 ``_valid_slot_text``
        拒（``[[`` 字符在册），丢弃它则 ``diff`` 零信号静默放行——
        槽内容两端都难全须全尾。"""
        enc = "see [[math_1]] literal [[MATH_1]] tail"
        slots, _seq = _make_slots(enc)
        assert slots["⟪S0000⟫"] == "see [[math_1]] literal "
        assert not _vst("see [[math_1]] literal ")  # echo 拒收

        async def drop_lit(group: dict[str, str], _f: str) -> dict[str, str]:
            return {k: v.replace("[[math_1]] ", "") for k, v in group.items()}

        # 丢弃字面后整链放行——内容损失无任何校验信号
        res = asyncio.run(
            rt.translate_with_ladder(
                "see [[math_1]] literal [[MATH_1]] tail",
                translate_fn=_drop_ph,
                slots_fn=drop_lit,
            )
        )
        assert res.status == "recovered"
        assert res.translation == "see literal [[MATH_1]] tail"


# ---------------------------------------------------------------- _slots_round 对抗面


class TestSlotsRoundAdversarial:
    def test_cross_group_answer_keys_ignored(self) -> None:
        """observed: ``for sid in group`` 只读本组键——应答夹带后续组的
        sid 不提前落 ``translated``，该槽仍留 pending 等本组重问。"""
        seen: list[list[str]] = []

        async def fn(group: dict[str, str], _fb: str) -> dict[str, str]:
            seen.append(sorted(group))
            if "⟪S0000⟫" in group:
                return {"⟪S0008⟫": "early"}  # 组0 只回组1 的键
            return dict.fromkeys(group, "zh")

        ctx = _SlotCtx(fn)
        pending = {f"⟪S{i:04d}⟫": f"p{i}" for i in range(10)}
        translated: dict[str, str] = {}
        failures: dict[str, str] = {}
        asyncio.run(_slots_round(ctx, pending, translated, failures))
        assert len(seen) == 2  # noqa: PLR2004 -- 8+2 两组
        # "early" 应答被丢——S0008 靠本组应答落地
        assert translated == {"⟪S0008⟫": "zh", "⟪S0009⟫": "zh"}
        # 组0 全留 pending；failures 记 "empty/..."（键缺席走 get→None→
        # invalid 分支），不是 exception 路径的 "no answer"
        assert set(pending) == {f"⟪S{i:04d}⟫" for i in range(8)}
        assert all("empty" in failures[sid] for sid in pending)

    def test_non_dict_mapping_rejected(self) -> None:
        """observed: ``isinstance(got, dict)`` 硬判定——MappingProxy 等
        Mapping 亚型一律按无效收（契约面是 dict，不是 Mapping）。"""

        async def mp(group: dict[str, str], _fb: str) -> dict[str, str]:
            return types.MappingProxyType(dict.fromkeys(group, "zh"))  # type: ignore[return-value]

        ctx = _SlotCtx(mp)
        pending = {f"⟪S{i:04d}⟫": f"p{i}" for i in range(3)}
        failures: dict[str, str] = {}
        asyncio.run(_slots_round(ctx, pending, {}, failures))
        assert set(failures) == set(pending)

    def test_structured_slot_values_rejected(self) -> None:
        """observed: 槽值必须 str——嵌套 dict/list/数字/None/False 一律
        ``_valid_slot_text`` 拒收。"""
        for bad in [{"zh": "x"}, ["x"], 42, None, False]:
            translated: dict[str, str] = {}

            async def fn(
                group: dict[str, str],
                _fb: str,
                _b: object = bad,
            ) -> dict[str, str]:
                return dict.fromkeys(group, _b)  # type: ignore[return-value]

            ctx = _SlotCtx(fn)
            pending = {"⟪S0000⟫": "p"}
            asyncio.run(_slots_round(ctx, pending, translated, {}))
            assert not translated, bad
            assert "⟪S0000⟫" in pending

    def test_cancelled_error_propagates(self) -> None:
        """observed: ``except Exception`` 不吃 BaseException——
        ``CancelledError`` 穿透槽位臂（取消语义不被吞）。"""

        async def cancel(_g: dict[str, str], _f: str) -> dict[str, str]:
            raise asyncio.CancelledError

        ctx = _SlotCtx(cancel)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(_slots_round(ctx, {"⟪S0000⟫": "p"}, {}, {}))

    def test_group_arg_mutation_cannot_drop_answers(self) -> None:
        """结算循环按发送时键快照迭代——回调清空/弹出入参 ``group`` 不再
        丢弃自己的有效应答（曾重读可变 dict：应答全丢 + ``failures`` 把
        "框架丢答"误记成 ``"no answer"``）。``pending`` 账本正常结算。"""

        async def vandal(group: dict[str, str], _fb: str) -> dict[str, str]:
            out = dict.fromkeys(group, "zh")
            group.clear()
            return out

        ctx = _SlotCtx(vandal)
        pending = {f"⟪S{i:04d}⟫": f"p{i}" for i in range(3)}
        translated: dict[str, str] = {}
        failures: dict[str, str] = {}
        asyncio.run(_slots_round(ctx, pending, translated, failures))
        assert translated == {f"⟪S{i:04d}⟫": "zh" for i in range(3)}
        assert not pending
        assert not failures

    def test_cross_round_feedback_carries_no_answer(self) -> None:
        """observed: 首轮整组崩 → 第二轮 feedback JSON 带
        ``"no answer"`` 项（``failures.setdefault`` 只在轮末兜底）。"""
        calls: list[str] = []

        async def flaky(group: dict[str, str], fb: str) -> dict[str, str]:
            calls.append(fb)
            if len(calls) == 1:
                msg = "boom"
                raise ValueError(msg)
            return dict.fromkeys(group, "zh")

        ctx = _SlotCtx(flaky)
        pending = {"⟪S0000⟫": "p0", "⟪S0001⟫": "p1"}
        translated: dict[str, str] = {}
        fails: dict[str, str] = {}
        asyncio.run(_slots_round(ctx, pending, translated, fails))
        asyncio.run(_slots_round(ctx, pending, translated, fails))
        assert json.loads(calls[1]) == {
            "⟪S0000⟫": "no answer",
            "⟪S0001⟫": "no answer",
        }
        assert not pending

    def test_attempts_counted_per_group_not_per_slot(self) -> None:
        """observed: attempts 按组计——含崩掉的组（请求已发出）。"""
        calls = 0

        async def fn(group: dict[str, str], _fb: str) -> dict[str, str]:
            nonlocal calls
            calls += 1
            return dict.fromkeys(group, "zh")

        ctx = _SlotCtx(fn)
        pending = {f"⟪S{i:04d}⟫": f"p{i}" for i in range(17)}
        asyncio.run(_slots_round(ctx, pending, {}, {}))
        assert ctx.attempts == calls == 3  # noqa: PLR2004 -- 8+8+1

    def test_chaterror_mid_round_stops_later_groups(self) -> None:
        """observed: 组内 ``ChatError`` 即抛——后续组不再发问
        （未问组留 pending 一并弃疗）。"""
        seen: list[list[str]] = []

        async def fn(group: dict[str, str], _fb: str) -> dict[str, str]:
            seen.append(sorted(group))
            if len(seen) == 2:  # noqa: PLR2004 -- 组2 即抛
                msg = "401"
                raise AuthError(msg, status=401)
            return dict.fromkeys(group, "zh")

        ctx = _SlotCtx(fn)
        pending = {f"⟪S{i:04d}⟫": f"p{i}" for i in range(20)}
        with pytest.raises(AuthError):
            asyncio.run(_slots_round(ctx, pending, {}, {}))
        assert len(seen) == 2  # noqa: PLR2004 -- 组2 即抛，组3 未发


# ---------------------------------------------------------------- 阶梯不变量


class TestLadderInvariants:
    def test_chaos_fuzz_terminates_bounded(self) -> None:  # noqa: C901 -- chaos 分支即目的
        """乱注 chaos：translate_fn 回随机垃圾（含 echo/丢 token/空串），
        slots_fn 回随机 dict/非 dict/崩——阶梯必终止且 attempts 有界：
        ``≤ 2 + nlines + 2·ceil(nslots/8)``。"""
        rng = random.Random(20260917)  # noqa: S311 -- 确定性种子
        soup = [
            "Hello world. ",
            "Second sentence ",
            "[[MATH_1]]",
            "[[CITE_2]]",
            "中文。",
            "tail ",
        ]
        out_soup = ["译文", "丢 [[MATH_1]]", "", "x [[BAD]]", "全部占位符文本"]

        for _ in range(400):
            src = "".join(rng.choice(soup) for _ in range(rng.randint(1, 8)))
            enc = ph.encode_newlines(src)[0]
            lines = _split_lines(enc)
            nlines = len(lines) if len(lines) > 1 else 0
            nslots = len(_make_slots(enc)[0])
            slot_groups = -(-nslots // rt.SLOTS_PER_BATCH)
            bound = 2 + nlines + rt.SLOTS_MAX_ROUNDS * slot_groups

            async def t_fn(_t: str, _f: str, _e: str = enc) -> str:
                return rng.choice([*out_soup, _e])  # echo 是合法输出形态

            async def s_fn(g: dict[str, str], _f: str) -> dict[str, str]:
                r = rng.random()
                if r < 0.15:  # noqa: PLR2004 -- chaos 概率
                    msg = "slots crash"
                    raise ValueError(msg)
                if r < 0.3:  # noqa: PLR2004 -- chaos 概率
                    return rng.choice([["not dict"], "str", None, 42])  # type: ignore[return-value]
                out: dict[str, str] = {}
                for k in g:
                    rr = rng.random()
                    if rr < 0.7:  # noqa: PLR2004 -- chaos 概率
                        out[k] = "槽译文"
                    elif rr < 0.8:  # noqa: PLR2004 -- chaos 概率
                        out[k] = "bad [[MATH_1]]"  # 非法槽值
                    # 其余缺失键——pending 留档
                return out

            res = asyncio.run(
                rt.translate_with_ladder(src, translate_fn=t_fn, slots_fn=s_fn)
            )
            assert res.status in ("ok", "recovered", "fallback_orig")
            assert res.attempts <= bound, (
                f"{src!r}: attempts={res.attempts} bound={bound}"
            )
            if res.status == "fallback_orig":
                assert res.translation == src
                assert res.warnings[-1] == (
                    "all ladder stages exhausted → fallback to original"
                )
            if res.status == "ok":
                assert res.stage == "whole"
                assert res.warnings == []  # 无 repair_fn——ok 必干净
            if res.status == "recovered":
                assert res.stage in ("lines", "slots")

    def test_fallback_translation_is_source_never_best_zh(self) -> None:
        """observed: 三振时 ``translation`` 恒为原文逐字节——``best_zh``
        只折进 ``warnings`` 诊断（``[:200]`` 截断），绝不进 ``translation``
        字段给下游误拼。"""
        long_zh = "译文" * 300

        async def bad_long(_t: str, _f: str) -> str:
            return long_zh

        src = "Alpha [[MATH_1]] omega [[CITE_2]]"
        res = asyncio.run(
            rt.translate_with_ladder(src, translate_fn=bad_long, slots_fn=_empty_slots)
        )
        assert res.status == "fallback_orig"
        assert res.translation == src
        bw = [w for w in res.warnings if "best-effort" in w]
        assert bw
        assert long_zh[:200] in bw[0]
        assert long_zh not in bw[0]  # 截断生效——600 字不全塞

    def test_fallback_warning_sequence_shape(self) -> None:
        """observed: 全败 warning 定式 = ``whole×2 failed`` → ``lines failed``
        → ``slots unanswered`` → ``best-effort`` → ``all ladder stages``。"""
        src = (
            "One [[MATH_1]] here. Two [[CITE_2]] there. "
            "Three [[ENV_3]] end. tail words [[TABLE_4]]"
        )
        res = asyncio.run(
            rt.translate_with_ladder(src, translate_fn=_drop_ph, slots_fn=_empty_slots)
        )
        kinds = [
            "whole×2 failed",
            "lines failed",
            "slots unanswered",
            "best-effort zh",
            "all ladder stages exhausted",
        ]
        assert len(res.warnings) == len(kinds)
        for w, k in zip(res.warnings, kinds, strict=True):
            assert k in w

    def test_chaterror_in_slots_discards_best_zh(self) -> None:
        """observed: slots 阶段 ``ChatError`` 直接穿透——不走
        ``fallback_orig``、不回 ``LadderResult``，``best_zh`` 随异常弃
        （调用方拿到的只有异常本身）。"""

        async def chatfail(_g: dict[str, str], _f: str) -> dict[str, str]:
            msg = "500"
            raise RetryableHTTPError(msg, status=500, retryable=True)

        with pytest.raises(RetryableHTTPError):
            asyncio.run(
                rt.translate_with_ladder(
                    "Alpha [[MATH_1]] omega",
                    translate_fn=_drop_ph,
                    slots_fn=chatfail,
                )
            )

    def test_translate_gets_encoded_corrector_gets_raw(self) -> None:
        """observed 不对称：``translate_fn`` 收 ``encode_newlines`` 产物
        （``\\n``→``[[SL]]``）；``corrector_fn`` 收原始 ``source``
        （裸 ``\\n`` 保留——corrector prompt 层自管编码）。"""
        seen: dict[str, str] = {}

        async def t_fn(text: str, _f: str) -> str:
            seen["translate"] = text
            return "丢占位符"

        async def c_fn(orig: str, _zh: str, _err: str) -> str:
            seen["corrector"] = orig
            return "还是丢"

        asyncio.run(
            rt.translate_with_ladder(
                "line1\nline2 [[MATH_1]]",
                translate_fn=t_fn,
                corrector_fn=c_fn,
                slots_fn=_empty_slots,
            )
        )
        assert seen["translate"] == "line1[[SL]]line2 [[MATH_1]]"
        assert seen["corrector"] == "line1\nline2 [[MATH_1]]"

    def test_repair_fn_warning_and_rescue(self) -> None:
        """observed: ``repair_fn`` 抄回成功 → warning
        ``recovered copied placeholders: …``——``ok`` 状态可携带 warning。"""

        def repair(_src: str, zh: str) -> tuple[str, list[str]]:
            return zh + " [[MATH_1]]", ["[[MATH_1]]"]

        res = asyncio.run(
            rt.translate_with_ladder(
                "Alpha [[MATH_1]] omega",
                translate_fn=_drop_ph,
                slots_fn=_empty_slots,
                repair_fn=repair,
            )
        )
        assert res.status == "ok"
        assert res.warnings == ["recovered copied placeholders: [[MATH_1]]"]

    def test_identity_echo_passes_default_validator(self) -> None:
        """observed 盲点（文档化契约非缺陷）：默认 ``validate_fn`` 只做
        占位符对账——逐字 echo 原文即 ``ok``；真「翻了没」判定由
        pipeline 注入的 L0 validator 负责。"""

        async def echo(text: str, _f: str) -> str:
            return text

        res = asyncio.run(
            rt.translate_with_ladder(
                "Alpha text [[MATH_1]] omega",
                translate_fn=echo,
                slots_fn=_empty_slots,
            )
        )
        assert res.status == "ok"
        assert res.translation == "Alpha text [[MATH_1]] omega"

    def test_single_line_source_skips_lines_stage(self) -> None:
        """observed: 单行源（切不出 >1 片）直接跳行级——``translate_fn``
        只烧整段×2，不进 stage-2。"""
        calls = 0

        async def t_fn(_t: str, _f: str) -> str:
            nonlocal calls
            calls += 1
            return "丢占位符"

        asyncio.run(
            rt.translate_with_ladder(
                "Single line [[MATH_1]] no period split",
                translate_fn=t_fn,
                slots_fn=_empty_slots,
            )
        )
        assert calls == 2  # noqa: PLR2004 -- whole×2，lines 零调

    def test_lines_stage_requests_every_line_and_cancels(self) -> None:
        """observed: 行级不早退——逐行全发，坏行照样进 ``fixed`` 候选；
        行间失败可在整段对账互消（行1 丢 MATH_1、行2 多 MATH_1
        净零 → 救回），``bad_lines`` 计数进 warning。"""
        calls: list[str] = []

        async def swapper(text: str, _f: str) -> str:
            calls.append(text)
            if "MATH_1" in text and "CITE_2" in text:
                return "整段两占位符全丢"  # whole 阶段必败
            if "MATH_1" in text:
                return "甲"  # 行1：丢 MATH_1
            return "乙 [[MATH_1]] [[CITE_2]]"  # 行2：多 MATH_1

        res = asyncio.run(
            rt.translate_with_ladder(
                "First [[MATH_1]] here. Second [[CITE_2]] there.",
                translate_fn=swapper,
                slots_fn=_empty_slots,
            )
        )
        assert res.status == "recovered"
        assert res.stage == "lines"
        assert len(calls) == 4  # noqa: PLR2004 -- 整段 2 + 逐行 2
        assert "2 bad lines" in res.warnings[1]
        assert "[[MATH_1]]" in res.translation
        assert "[[CITE_2]]" in res.translation

    def test_whitespace_source_still_calls_translate(self) -> None:
        """observed: 阶梯不做空输入短路——空白源照样发整段请求，
        ``diff`` 无占位符差异即 ``ok``（守卫在 pipeline 的
        ``is_placeholder_only``，不在本层）。"""
        calls: list[str] = []

        async def t_fn(text: str, _f: str) -> str:
            calls.append(text)
            return text

        res = asyncio.run(
            rt.translate_with_ladder("   ", translate_fn=t_fn, slots_fn=_empty_slots)
        )
        assert res.status == "ok"
        assert calls == ["   "]

    def test_progress_does_not_extend_slot_rounds(self) -> None:
        """observed: ``SLOTS_MAX_ROUNDS=2`` 硬帽——每轮都在净进展
        （每 call 补一槽）也照样两轮封顶 → ``fallback_orig``。"""
        groups = 0

        async def one_per(group: dict[str, str], _f: str) -> dict[str, str]:
            nonlocal groups
            groups += 1
            return {min(group): "槽译"}  # 每 call 只补一槽

        res = asyncio.run(
            rt.translate_with_ladder(
                "a [[MATH_1]] b [[CITE_2]] c [[ENV_3]] d",
                translate_fn=_drop_ph,
                slots_fn=one_per,
            )
        )
        assert res.status == "fallback_orig"
        assert groups == rt.SLOTS_MAX_ROUNDS  # 两轮即弃——进展不续命

    def test_partially_answered_slots_all_or_nothing(self) -> None:
        """observed: 槽位部分答成也整体弃——不拼半成品译文，
        ``fallback_orig`` 回原文（``translated`` 里的好答案全丢）。"""

        async def half(group: dict[str, str], _f: str) -> dict[str, str]:
            return {k: ("槽译" if k == "⟪S0000⟫" else "") for k in group}

        res = asyncio.run(
            rt.translate_with_ladder(
                "a [[MATH_1]] b [[CITE_2]] c",
                translate_fn=_drop_ph,
                slots_fn=half,
            )
        )
        assert res.status == "fallback_orig"
        assert res.translation == "a [[MATH_1]] b [[CITE_2]] c"

    def test_validate_fn_exception_propagates(self) -> None:
        """observed: 校验器崩溃不当翻译失败——异常穿透阶梯（validator
        是受信内部代码，崩=bug 上抛，不落 ``fallback_orig`` 掩盖）。"""

        def bad_validate(_s: str, _z: str) -> str:
            msg = "validator bug"
            raise RuntimeError(msg)

        async def t_fn(text: str, _f: str) -> str:
            return text

        with pytest.raises(RuntimeError, match="validator bug"):
            asyncio.run(
                rt.translate_with_ladder(
                    "x",
                    translate_fn=t_fn,
                    slots_fn=_empty_slots,
                    validate_fn=bad_validate,
                )
            )


# ---------------------------------------------------------------- _valid_slot_text 象形面


class TestValidSlotTextLookalikes:
    def test_lookalike_bracket_slot_echo_rejected(self) -> None:
        """``⟦⟧《》「」［］⟨⟩｟｠`` 象形括号贴 ``S``+四位数的槽 token 形变
        回显在 ``_valid_slot_text`` 拒收——这些括号本身是合法中文标点不能进
        ``_SLOT_PH_BRACKETS`` 字符黑名单，但括号+``S\\d{4,}`` 只会是
        ``⟪S0000⟫`` 形变；``diff`` 看不见它（下游无兜网，须入口拒）。"""
        for tok in [
            "⟦S0000⟧",
            "《S0000》",
            "「S0000」",
            "［S0000］",
            "⟨S0000⟩",
            "｟S0000｠",
            "⟦S0000",  # 半边形态同拒
            "S0000⟧",
        ]:
            assert not _vst(f"译文 {tok}"), tok
            d = ph.diff("alpha [[MATH_1]]", f"译文 {tok} [[MATH_1]]")
            assert d.ok, tok  # diff 确实看不见——入口拒是唯一兜网

    def test_cjk_corner_bracket_caught_at_entry_and_downstream(self) -> None:
        """``【S0000】`` 现在 ``_valid_slot_text`` 即拒（``_SLOT_ECHO_RX``
        含 ``【】``）；下游 ``PH_FUZZY_RX`` 的 ``【..】`` 臂仍是第二道兜网。"""
        assert not _vst("译文 【S0000】")
        d = ph.diff("alpha [[MATH_1]]", "译文 【S0000】 [[MATH_1]]")
        assert "【S0000】" in d.extra

    def test_zero_width_only_values_rejected(self) -> None:
        """``\\u200b`` ZWSP/``\\ufeff`` BOM/``\\u200d`` ZWJ 等零宽-only
        槽值按"无可见字符"拒收——零宽应答等于该槽正文静默丢进装配译文
        （``str.strip()`` 不吃零宽字符；可见字符夹杂零宽不误伤）。"""
        assert not _vst("\u200b")
        assert not _vst("\ufeff")
        assert not _vst("\u200b \u200d\ufeff")
        assert not _vst(" ")
        assert not _vst("\u3000")
        assert _vst("译\u200b文")  # 零宽夹在可见字符间放行
        assert _vst("\u200c\u200djoiner")  # 零宽起头的真实文本放行

    def test_bare_slot_id_text_accepted(self) -> None:
        """observed 不误伤：裸 ``S0000``（无括号）是合法译文成分——
        引用 ``S0000`` 节号/全角 ``［1］`` 引用号的译文不该被拒。"""
        assert _vst("见 S0000 节")
        assert _vst("在文献 ［1］ 中")

    def test_fuzz_bracket_charset_only_gate(self) -> None:
        """随机 soup：``_valid_slot_text`` 判定 ⟺ 有可见字符（非空白非零宽）
        + 无 ``⟪⟫[[ ]]`` 四字符 + 无象形括号 ``S\\d{4,}`` 形变——oracle
        逐条对账（口径随零宽/象形族修复同步更新）。"""
        rng = random.Random(20260917)  # noqa: S311 -- 确定性种子
        soup = [
            "a",
            " ",
            "⟪",
            "⟫",
            "⟦",
            "⟧",
            "[",
            "]",
            "[[",
            "]]",
            "【",
            "】",
            "S0000",
            "译文",
            "\u200b",
            "\xa0",
            "\n",
        ]
        for _ in range(_FUZZ_MED):
            v = "".join(rng.choice(soup) for _ in range(rng.randint(0, 8)))
            want = (
                any(
                    not c.isspace() and c not in rt._SLOT_ZW_CHARS  # noqa: SLF001
                    for c in v
                )
                and not any(
                    m in v
                    for m in rt._SLOT_PH_BRACKETS  # noqa: SLF001
                )
                and rt._SLOT_ECHO_RX.search(v) is None  # noqa: SLF001
            )
            assert _vst(v) == want, v
