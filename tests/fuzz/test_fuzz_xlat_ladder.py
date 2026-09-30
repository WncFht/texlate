"""``translate_with_ladder`` 阶梯不变量 + ``_valid_slot_text`` 象形面——
``test_fuzz_xlat_retry`` 拆出。

分工见 ``test_fuzz_xlat_retry`` 首行；共享脚手架（私有面薄封装 +
``_drop_ph``/``_empty_slots`` 伪件）经 ``from test_fuzz_xlat_retry import``
取件。本文件收：

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

import pytest
from _fuzzkit import fuzz_rng
from test_fuzz_xlat_retry import (
    _FUZZ_MED,
    _drop_ph,
    _empty_slots,
    _make_slots,
    _split_lines,
    _vst,
)

from texlate.xlat import placeholders as ph
from texlate.xlat import retry as rt
from texlate.xlat.client import RetryableHTTPError

# ---------------------------------------------------------------- 阶梯不变量


class TestLadderInvariants:
    def test_chaos_fuzz_terminates_bounded(self) -> None:  # noqa: C901 -- chaos 分支即目的
        """乱注 chaos：translate_fn 回随机垃圾（含 echo/丢 token/空串），
        slots_fn 回随机 dict/非 dict/崩——阶梯必终止且 attempts 有界：
        ``≤ 2 + 3·nlines + 2·ceil(nslots/8)``（行级 audit/validate
        各带 feedback 重试一次 → 单行上限 3 发）。"""
        rng = fuzz_rng(20260917)
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
            bound = 2 + 3 * nlines + rt.SLOTS_MAX_ROUNDS * slot_groups

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
        assert len(calls) == 6  # noqa: PLR2004 -- 整段 2 + 逐行 2×2（坏行各带 err 重试 1 发）
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
        rng = fuzz_rng(20260917)
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
