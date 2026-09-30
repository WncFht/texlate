"""retry：HTTP 退避节奏 + 四段语义阶梯（fake translate/slots，不触网）。"""

import asyncio

import pytest

from texlate.textutil import residual_en_net
from texlate.validate.l0 import validate_pair
from texlate.xlat import retry as rt
from texlate.xlat.client import (
    AuthError,
    ChatError,
    EmptyContentError,
    RetryableHTTPError,
)


def _policy(
    *,
    max_tries: int = 3,
    rate_limit_floor: float = 0.0,
    timeout_floor: float = 0.0,
) -> rt.RetryPolicy:
    """零延迟策略——floor 全归零，退避节奏靠断言不靠真睡。"""
    return rt.RetryPolicy(
        max_tries=max_tries,
        base_delay=0.0,
        rate_limit_floor=rate_limit_floor,
        timeout_floor=timeout_floor,
    )


class TestBackoff:
    def test_success_first_try(self) -> None:
        async def go() -> str:
            return "ok"

        assert asyncio.run(rt.call_with_backoff(go, policy=_policy())) == "ok"

    def test_retryable_then_success(self) -> None:
        calls = {"n": 0}

        async def flaky() -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                msg = "boom"
                raise RetryableHTTPError(msg, status=500, retryable=True)
            return "ok"

        retries: list[tuple[int, BaseException, float]] = []

        def on_retry(a: int, e: BaseException, d: float) -> None:
            retries.append((a, e, d))

        out = asyncio.run(
            rt.call_with_backoff(flaky, policy=_policy(), on_retry=on_retry)
        )
        assert out == "ok"
        assert calls["n"] == 2  # noqa: PLR2004 -- 第 2 次成功
        assert len(retries) == 1

    def test_non_retryable_raises_immediately(self) -> None:
        calls = {"n": 0}

        async def bad() -> str:
            calls["n"] += 1
            msg = "no auth"
            raise AuthError(msg, status=401)

        with pytest.raises(AuthError):
            asyncio.run(rt.call_with_backoff(bad, policy=_policy()))
        assert calls["n"] == 1

    def test_exhaustion_raises(self) -> None:
        async def always() -> str:
            msg = "server dead"
            raise RetryableHTTPError(msg, status=503, retryable=True)

        with pytest.raises(RetryableHTTPError):
            asyncio.run(rt.call_with_backoff(always, policy=_policy(max_tries=2)))

    def test_empty_content_retried_once_then_raises(self) -> None:
        """T7a：EmptyContentError retryable 但 max_tries=2——只翻身一次
        （原先 non-retryable 直接穿透；也不该烧满 policy 上限）。"""
        calls = {"n": 0}

        async def empty() -> str:
            calls["n"] += 1
            msg = "empty content"
            raise EmptyContentError(msg)

        with pytest.raises(EmptyContentError):
            asyncio.run(rt.call_with_backoff(empty, policy=_policy(max_tries=5)))
        assert calls["n"] == 2  # noqa: PLR2004 -- 首发 + 一次翻身

    def test_empty_content_second_try_success(self) -> None:
        """第一次空、第二次出正文 → 正常返回（reasoning 模型偶发空响应）。"""
        calls = {"n": 0}

        async def flaky() -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                msg = "empty content"
                raise EmptyContentError(msg)
            return "ok"

        out = asyncio.run(rt.call_with_backoff(flaky, policy=_policy()))
        assert out == "ok"
        assert calls["n"] == 2  # noqa: PLR2004 -- 第二试成功

    def test_429_floor_and_retry_after(self, recorded_sleeps: list[float]) -> None:
        """429 → 3^attempt 且 ≥rate_limit_floor；Retry-After 从其值。"""

        async def rate_limited() -> str:
            msg = "slow down"
            raise RetryableHTTPError(msg, status=429, retryable=True)

        pol = rt.RetryPolicy(
            max_tries=3, base_delay=1.0, rate_limit_floor=5.0, timeout_floor=0.0
        )
        with pytest.raises(RetryableHTTPError):
            asyncio.run(rt.call_with_backoff(rate_limited, policy=pol))
        # attempt0: max(5, 1·3^0)=5；attempt1: max(5, 1·3^1)=5
        assert recorded_sleeps == [5.0, 5.0]

        recorded_sleeps.clear()

        async def retry_after_err() -> str:
            msg = "with header"
            raise RetryableHTTPError(msg, status=429, retryable=True, retry_after=2.5)

        with pytest.raises(RetryableHTTPError):
            asyncio.run(rt.call_with_backoff(retry_after_err, policy=pol))
        assert recorded_sleeps == [2.5, 2.5]

    def test_timeout_floor(self, recorded_sleeps: list[float]) -> None:
        async def slow() -> str:
            raise TimeoutError

        pol = rt.RetryPolicy(
            max_tries=2, base_delay=1.0, rate_limit_floor=0.0, timeout_floor=10.0
        )
        with pytest.raises(ChatError, match="timeout"):
            asyncio.run(rt.call_with_backoff(slow, policy=pol))
        assert recorded_sleeps == [10.0]


class TestLadder:
    def _src(self) -> str:
        return "First sentence [[MATH_1]]. Second sentence [[CITE_2]]."

    async def _empty_slots(
        self, _slots: dict[str, str], _failures: str
    ) -> dict[str, str]:
        return {}

    def test_whole_pass(self) -> None:
        async def ok_translate(_text: str, _feedback: str) -> str:
            return "第一句 [[MATH_1]]。第二句 [[CITE_2]]。"

        res = asyncio.run(
            rt.translate_with_ladder(
                self._src(),
                translate_fn=ok_translate,
                slots_fn=self._empty_slots,
            )
        )
        assert res.status == "ok"
        assert res.stage == "whole"
        assert res.attempts == 1
        assert res.warnings == []

    def test_second_try_with_fielded_feedback(self) -> None:
        """第一试丢占位符 → 第二试带 previous_validation_error 修复。"""
        seen_feedback: list[str] = []

        async def flaky(_text: str, feedback: str) -> str:
            seen_feedback.append(feedback)
            if not feedback:
                return "第一句。第二句 [[CITE_2]]。"  # 丢 MATH_1
            return "第一句 [[MATH_1]]。第二句 [[CITE_2]]。"

        res = asyncio.run(
            rt.translate_with_ladder(
                self._src(),
                translate_fn=flaky,
                slots_fn=self._empty_slots,
            )
        )
        assert res.status == "ok"
        assert res.attempts == 2  # noqa: PLR2004 -- 第二试过
        assert "missing placeholder: [[MATH_1]]" in seen_feedback[1]

    def test_corrector_replaces_second_try(self) -> None:
        """corrector_fn 接管 stage-1 第二试。"""
        calls = {"translate": 0, "corrector": 0}

        async def bad_translate(_text: str, _feedback: str) -> str:
            calls["translate"] += 1
            return "译文丢了占位符"

        async def corrector(_orig: str, _zh: str, err: str) -> str:
            calls["corrector"] += 1
            assert "[[MATH_1]]" in err
            return "第一句 [[MATH_1]]。第二句 [[CITE_2]]。"

        res = asyncio.run(
            rt.translate_with_ladder(
                self._src(),
                translate_fn=bad_translate,
                slots_fn=self._empty_slots,
                corrector_fn=corrector,
            )
        )
        assert res.status == "ok"
        assert calls == {"translate": 1, "corrector": 1}

    def test_line_repair_rescues(self) -> None:
        """整段×2 败 → 句号切行级修复，行译文带齐占位符 → recovered/lines。"""
        src = self._src()

        async def per_line(text: str, _feedback: str) -> str:
            if "MATH_1" in text and "CITE_2" in text:
                return "整段译文丢了一号但有 [[CITE_2]]"  # 整段必败（真丢 token）
            if "MATH_1" in text:
                return "第一句 [[MATH_1]]。"
            return "第二句 [[CITE_2]]。"

        res = asyncio.run(
            rt.translate_with_ladder(
                src, translate_fn=per_line, slots_fn=self._empty_slots
            )
        )
        assert res.status == "recovered"
        assert res.stage == "lines"
        assert "[[MATH_1]]" in res.translation
        assert "[[CITE_2]]" in res.translation

    def test_line_audit_retry_rescues(self) -> None:
        """行应答丢 ``[[SP]]`` → 带 audit err 重试一次救回（seq-51 臂 1）。"""
        src = "Alpha body text\\ second part stays long enough here. Tail sentence follows now."
        calls: list[tuple[str, str]] = []

        async def flaky(text: str, feedback: str) -> str:
            calls.append((text, feedback))
            if "second part" in text and "Tail" in text:
                return "整段译文没有标记"  # 整段两试都丢 [[SP]]（audit 死）
            if "Tail" in text:
                return "尾句译文在此。"
            if feedback:
                return "甲体 [[SP]] 文本第二部分够长。"
            return "甲体文本第二部分够长。"

        res = asyncio.run(
            rt.translate_with_ladder(
                src, translate_fn=flaky, slots_fn=self._empty_slots
            )
        )
        assert res.status == "recovered"
        assert res.stage == "lines"
        assert res.attempts == 5  # noqa: PLR2004 -- whole×2 + 行 1×2 + 行 2×1
        assert "[[SP]]" in calls[3][1]

    def test_line_validate_retry_rescues(self) -> None:
        """行译文 validate 败 → 带 err 重试一次救回（seq-51 臂 2）。"""
        src = "Alpha body [[MATH_1]] text here. Tail sentence follows now."

        async def flaky(text: str, feedback: str) -> str:
            if "Alpha" in text and "Tail" in text:
                return "整段丢了标记"  # 整段两试都丢 [[MATH_1]]
            if "Tail" in text:
                return "尾句译文在此。"
            if feedback:
                return "甲体 [[MATH_1]] 文本。"
            return "甲体文本没有标记。"

        res = asyncio.run(
            rt.translate_with_ladder(
                src, translate_fn=flaky, slots_fn=self._empty_slots
            )
        )
        assert res.status == "recovered"
        assert res.stage == "lines"
        assert "[[MATH_1]]" in res.translation
        assert res.attempts == 5  # noqa: PLR2004 -- whole×2 + 行 1×2 + 行 2×1

    def test_line_fallback_residual_en_reroutes_to_slots(self) -> None:
        """seq-51 核心回归：行译文整句英文回显 → validate 败 → 重试仍回显 →
        ``zh_l``（英文原句）装进装配体 → 真 ``validate_pair`` 的
        ``residual_en`` 网整段拒收 → 升 slots 救回，不再静默出货。"""
        src = (
            "Lead in sentence. The quick brown fox jumps over the lazy dog "
            "repeatedly near the barn every day."
        )
        barn_line = (
            "The quick brown fox jumps over the lazy dog repeatedly near "
            "the barn every day."
        )

        async def flaky(text: str, _feedback: str) -> str:
            if "Lead" in text and "barn" in text:
                return "整段 [[MATH_9]] 译文"  # whole×2 多余占位符死
            if "Lead" in text:
                return "引导句。"
            return barn_line  # 行级整句英文回显（same_source 死，重试同形）

        async def good_slots(slots: dict[str, str], _failures: str) -> dict[str, str]:
            return dict.fromkeys(
                slots, "引导句。敏捷的棕色狐狸每天都在谷仓附近反复跳过那只懒狗。"
            )

        def real_validate(s: str, z: str) -> str:
            rep = validate_pair(s, z)
            return "" if rep.ok else rep.feedback()

        res = asyncio.run(
            rt.translate_with_ladder(
                src,
                translate_fn=flaky,
                slots_fn=good_slots,
                validate_fn=real_validate,
            )
        )
        assert res.status == "recovered"
        assert res.stage == "slots"
        assert residual_en_net(src, res.translation) == []
        assert res.attempts == 6  # noqa: PLR2004 -- whole×2 + 行 1×1 + 行 2×2 + slots×1

    def test_slots_rescue(self) -> None:
        """整段 + 行级全败 → slots JSON 装配 → recovered/slots。"""
        src = "Alpha text [[MATH_1]] omega text"  # 无句号 → 单行跳过 stage2

        async def bad_translate(_text: str, _feedback: str) -> str:
            return "译文没有占位符"  # 永远丢 ph

        async def good_slots(slots: dict[str, str], _failures: str) -> dict[str, str]:
            return {sid: f"槽译文{i}" for i, sid in enumerate(slots)}

        res = asyncio.run(
            rt.translate_with_ladder(
                src, translate_fn=bad_translate, slots_fn=good_slots
            )
        )
        assert res.status == "recovered"
        assert res.stage == "slots"
        assert "[[MATH_1]]" in res.translation

    def test_slots_partial_failure_retried(self) -> None:
        """失败槽只重问失败批——第一轮回一个坏槽，第二轮补齐。"""
        src = "A [[MATH_1]] B [[CITE_2]] C"
        rounds = {"n": 0}

        async def bad_translate(_text: str, _feedback: str) -> str:
            return "x"

        async def flaky_slots(slots: dict[str, str], _failures: str) -> dict[str, str]:
            rounds["n"] += 1
            out = {}
            for sid in slots:
                # 第一轮让 S0001 返回非法槽（带占位符 token → 拒收）
                if rounds["n"] == 1 and sid.endswith("0001⟫"):
                    out[sid] = "bad [[MATH_1]]"
                else:
                    out[sid] = "槽译"
            return out

        res = asyncio.run(
            rt.translate_with_ladder(
                src, translate_fn=bad_translate, slots_fn=flaky_slots
            )
        )
        assert res.status == "recovered"
        assert res.stage == "slots"
        assert rounds["n"] == 2  # noqa: PLR2004 -- 重问一轮补齐

    def test_slots_decode_newline_ph(self) -> None:
        """slots 装配必须把 ``[[SL]]``/``[[PL]]`` 解码回换行——否则校验按多余
        占位符判死（s40 多行 chunk 阶梯全军覆没的根因回归）。"""
        src = "Alpha [[MATH_1]] beta\ngamma delta"  # 有句内换行、无句号切点

        async def bad_translate(_text: str, _feedback: str) -> str:
            return "译文没有占位符"

        async def good_slots(slots: dict[str, str], _failures: str) -> dict[str, str]:
            return dict.fromkeys(slots, "槽译文")

        res = asyncio.run(
            rt.translate_with_ladder(
                src, translate_fn=bad_translate, slots_fn=good_slots
            )
        )
        assert res.status == "recovered"
        assert res.stage == "slots"
        assert "[[SL]]" not in res.translation
        assert "\n" in res.translation
        assert "[[MATH_1]]" in res.translation

    def test_fallback_orig(self) -> None:
        """全阶段败 → fallback_orig + translation=原文 + warnings。"""

        async def bad_translate(_text: str, _feedback: str) -> str:
            return "译文没有占位符"

        res = asyncio.run(
            rt.translate_with_ladder(
                self._src(),
                translate_fn=bad_translate,
                slots_fn=self._empty_slots,
            )
        )
        assert res.status == "fallback_orig"
        assert res.stage == "fallback"
        assert res.warnings
        assert "fallback to original" in res.warnings[-1]

    def test_chat_error_propagates(self) -> None:
        """认证/余额类 ChatError 不被阶梯吞掉。"""

        async def auth_fail(_text: str, _feedback: str) -> str:
            msg = "401"
            raise AuthError(msg, status=401)

        with pytest.raises(AuthError):
            asyncio.run(
                rt.translate_with_ladder(
                    self._src(),
                    translate_fn=auth_fail,
                    slots_fn=self._empty_slots,
                )
            )


def test_make_slots_bisects_long_prose() -> None:
    """超 ``SLOT_MAX_CHARS`` 散文段按句界拆连续槽位——docs/spec/translate.md §1.6 spec 参数实装。"""
    sentence = "This is a fairly long sentence chunk with words. "
    seg = sentence * (rt.SLOT_MAX_CHARS // len(sentence) + 2)
    encoded = seg + "[[MATH_1]]tail words"
    slots, seq = rt._make_slots(encoded)  # noqa: SLF001
    assert len(slots) >= 2  # noqa: PLR2004 -- 二分生效
    assert all(len(v) <= rt.SLOT_MAX_CHARS for v in slots.values())
    # seq 保序：连续 slot 项 + ph + 尾 slot
    kinds = [k for k, _ in seq]
    assert kinds == ["slot"] * (len(slots) - 1) + ["ph", "slot"]
    # 槽文重组覆盖源文非空白全部内容（切点不丢字）
    joined = "".join(slots[p] for k, p in seq if k == "slot")
    assert joined.replace("\n", "") == (seg + "tail words").replace("\n", "")


def test_make_slots_short_prose_unsplit() -> None:
    """短散文不二分——每段散文 run 各成一槽（本例 ph 两侧两个 run → 两槽）。"""
    slots, seq = rt._make_slots("short prose [[MATH_1]] tail")  # noqa: SLF001
    assert len(slots) == 2  # noqa: PLR2004
    assert [k for k, _ in seq] == ["slot", "ph", "slot"]


def test_split_lines_abbrev_guard() -> None:
    """``_split_lines_scoped`` 缩写守卫（E24）——``Fig.``/``e.g.`` 尾点不切，
    真句尾照常断。"""
    parts = rt._split_lines_scoped("see Fig. 2 now. e.g. that holds. done now.")  # noqa: SLF001
    assert "".join(parts) == "see Fig. 2 now. e.g. that holds. done now."
    assert any("Fig. 2" in p for p in parts)
    assert not any(p.rstrip().endswith(("Fig.", "e.g.")) for p in parts)
    # 真句尾仍切："holds. done" 处断开
    assert any(p.rstrip().endswith("holds.") for p in parts)
