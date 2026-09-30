"""``_make_slots``/``_slots_round`` 槽位机械对抗面——``test_fuzz_xlat_retry`` 拆出。

分工见 ``test_fuzz_xlat_retry`` 首行；共享脚手架（私有面薄封装 + ``_SlotCtx``
伪件 + ``_recon`` 平铺 oracle）经 ``from test_fuzz_xlat_retry import`` 取件。
本文件收：

- ``_make_slots``：seq 平铺编码文的覆盖 oracle、>``SLOT_MAX_CHARS`` 空白
  run 整片按 ``raw`` 记账保 seq 平铺（曾整片丢弃静默丢字节）、cs 名与其
  ``{arg}`` 之间不再允许切分、槽号 ``%04d`` 超 4 位仍规范、槽散文含
  字面 ``[[x]]`` 的拒收张力（echo 必拒、丢弃零信号）；
- ``_slots_round``：跨组应答键被忽略（不提前落 ``translated``）、非 dict
  Mapping 拒收、``CancelledError`` 穿透 ``except Exception``、跨轮
  ``failures`` 反馈含 ``"no answer"`` 项、组参 ``group`` mutation 不再丢答
  （结算按发送时键快照迭代——曾重读可变 dict，回调清空连自己应答一并弃，
  失败归因误记 ``"no answer"``）、组内 ``ChatError`` 即抛截断本轮。
"""

from __future__ import annotations

import asyncio
import json
import types

import pytest
from _fuzzkit import fuzz_rng
from test_fuzz_xlat_retry import (
    _FUZZ_MED,
    _drop_ph,
    _make_slots,
    _recon,
    _SlotCtx,
    _slots_round,
    _vst,
)

from texlate.xlat import placeholders as ph
from texlate.xlat import retry as rt
from texlate.xlat.client import AuthError

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
            assert _recon(slots, seq) == enc, enc

    def test_fuzz_seq_tiles_encoded(self) -> None:
        """随机编码文：seq 平铺恒等（生成面不含 >``SLOT_MAX_CHARS`` 空白
        run——那是下方 CONFIRMED 丢片缺陷的独立触发面）。"""
        rng = fuzz_rng(20260917)
        soup = ["word ", "[[MATH_1]]", "[[CITE_2]]", "[[SL]]", " ", "x", " t", "~"]
        for _ in range(_FUZZ_MED):
            enc = "".join(rng.choice(soup) for _ in range(rng.randint(0, 15)))
            slots, seq = _make_slots(enc)
            assert _recon(slots, seq) == enc, enc

    def test_whitespace_run_piece_kept_as_raw(self) -> None:
        """散文段内 >``SLOT_MAX_CHARS`` 的纯空白 run 经 ``split_long_chunk``
        拆出的整片按 ``raw`` 记账——seq 仍平铺覆盖 encoded，装配译文不丢
        字节（曾整体丢弃：seq 无痕迹、静默丢 ~1500 字符空白）。"""
        seg = "a" + " " * (rt.SLOT_MAX_CHARS * 2) + "b"
        slots, seq = _make_slots(seg)
        assert _recon(slots, seq) == seg
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
        rng = fuzz_rng(20260917)
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
