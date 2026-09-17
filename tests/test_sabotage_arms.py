r"""sabotage/perturb 臂注入与台账契约钉——``translators_bench`` + ``e2e_mock_bench``。

钉住的契约面（sabotage-audit 2026-09-17 实证）：

- 臂名 → 工厂：``mock`` 裸 MockTranslator（无台账面）；``sabotage-b`` →
  Mode B 台账臂；``sabotage-c``/``perturb`` → Mode C 位扰臂（别名同构）；
  未知臂 ``ValueError``——不存在静默降级 mock 的路径。
- 注入决策确定性：``_plan_b``/``_apply_c`` = f(段内容哈希 blake2s)，同输入
  跨调用同决策；``_canon`` 把 encoded/corrector-raw 归一→阶梯各阶段同决策。
- ``finalize`` 交付谓词 = ``e2e._delivered``（ok | partial+译文），与
  splice/e2e 台账同构——partial（阶梯 recovered）译文照进 zh/，严卡 ok
  会把脏 partial 记 caught 漏 escaped（e2e_mock:424 同款修复的 stagerun 侧
  漂移，本次收敛单源）。
- Mode C 挪位保持占位符 multiset（过 L0 的设计前提）。
"""

from __future__ import annotations

import asyncio

import pytest

tb = pytest.importorskip("translators_bench")  # 重链 texlate.* + e2e_mock_bench
emb = pytest.importorskip("e2e_mock_bench")

from texlate.latex.placeholder import PH_RX  # noqa: E402
from texlate.xlat.pipeline import (  # noqa: E402
    ChunkIn,
    ChunkResult,
    XlatPipeline,
    _mock_translate_text,
)
from texlate.xlat.placeholders import encode_newlines  # noqa: E402

_SRC = "Paragraph body carries [[MATH_1]] and [[EQ_2]] tokens here."
_CLEAN_ZH = "译文 [[MATH_1]] 和 [[EQ_2]] 文本。"
_CORRUPT_ZH = "译文 [[MATH_1]] 和 [[EQ_2]] 外加 [[MATH_913]]。"


def _mk(cid: str, source: str, trans: str, status: str, **kw: object) -> ChunkResult:
    return ChunkResult(
        chunk_id=cid, source=source, translation=trans, kind="para", status=status, **kw
    )


def _corruptible_seg() -> str:
    for i in range(500):
        s = f"Probe segment {i} embeds [[MATH_{i}]] plus [[EQ_{i}]] inline."
        if emb._plan_b(s):  # noqa: SLF001
            return s
    pytest.fail("no corruptible seg in 500")
    return ""  # unreachable — pytest.fail raises


class TestArmFactory:
    def test_arm_mapping(self) -> None:
        assert type(tb.make_translator("mock")).__name__ == "MockTranslator"
        assert getattr(tb.make_translator("mock"), "finalize", None) is None
        assert isinstance(tb.make_translator("sabotage-b"), tb.SabotageTranslator)
        assert isinstance(tb.make_translator("sabotage-c"), tb.PerturbTranslator)
        assert isinstance(tb.make_translator("perturb"), tb.PerturbTranslator)

    def test_unknown_arm_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown xlat arm"):
            tb.make_translator("real")  # real 由 stagerun 装配，不在工厂表
        with pytest.raises(ValueError, match="unknown xlat arm"):
            tb.make_translator("sabotage")


class TestInjection:
    def test_b_injects_and_records(self) -> None:
        seg = _corruptible_seg()
        kind = emb._plan_b(seg)  # noqa: SLF001
        tr = tb.make_translator("sabotage-b")
        out = asyncio.run(
            tr.translate(system="s", user=seg, temperature=0, max_tokens=99)
        )
        assert len(tr.events) == 1
        ev = tr.events[0]
        assert ev["seg"] == seg
        assert ev["kind"] == kind
        if kind == "drop_ph":
            assert len(PH_RX.findall(out)) == len(PH_RX.findall(seg)) - 1
        else:
            extra = set(PH_RX.findall(out)) - set(PH_RX.findall(seg))
            assert extra
            assert all(t.startswith("[[MATH_9") for t in extra)

    def test_b_deterministic_across_forms(self) -> None:
        """encoded 单块 / corrector 三段式 / 重试尾拼 → 同一段同决策。"""
        for i in range(500):
            seg = f"First line {i} here.\nSecond carries [[MATH_{i}]] plus [[EQ_{i}]]."
            if emb._plan_b(seg):  # noqa: SLF001
                break
        else:
            pytest.fail("no corruptible multiline seg")
        enc = encode_newlines(seg)[0]
        assert emb._plan_b(enc) == emb._plan_b(seg)  # noqa: SLF001 -- canon 归一
        forms = [
            enc,  # 阶梯单块形（encoded）
            f"[Original]\n{seg}\n[Translation]\n旧译\n[Error]\n占位符缺失",
            f"{enc}\n\n[previous_validation_error]\nerr",
        ]
        for user in forms:
            tr = tb.make_translator("sabotage-b")
            asyncio.run(
                tr.translate(system="s", user=user, temperature=0, max_tokens=99)
            )
            assert len(tr.events) == 1, user

    def test_b_batch_path(self) -> None:
        segs = [
            f"Batch probe {i} has [[MATH_{i}]] and [[EQ_{i}]] inside."
            for i in range(60)
        ]
        user = "\n".join(f"[{i + 1}] {s}" for i, s in enumerate(segs))
        tr = tb.make_translator("sabotage-b")
        asyncio.run(tr.translate(system="s", user=user, temperature=0, max_tokens=999))
        flagged = sum(1 for s in segs if emb._plan_b(s))  # noqa: SLF001
        assert len(tr.events) == flagged
        assert all(e["seg"] in segs for e in tr.events)

    def test_b_json_mode_untouched(self) -> None:
        tr = tb.make_translator("sabotage-b")
        asyncio.run(
            tr.translate(
                system="s",
                user='{"slots":{"s1":"x"}}',
                temperature=0,
                max_tokens=9,
                response_format={"type": "json_object"},
            )
        )
        assert tr.events == []

    def test_c_moves_and_keeps_multiset(self) -> None:
        seg = ""
        mv = 0
        for i in range(3000):
            cand = f"Gamma {i} has [[MATH_{i}]] and [[EQ_{i}]] plus [[FIG_{i}]] text."
            _, mv = emb._apply_c(  # noqa: SLF001
                _mock_translate_text(cand, "这是译文"), cand
            )
            if mv:
                seg = cand
                break
        if not seg:
            pytest.fail("no movable seg in 3000")
        tr = tb.make_translator("perturb")
        out = asyncio.run(
            tr.translate(system="s", user=seg, temperature=0, max_tokens=99)
        )
        assert sorted(PH_RX.findall(out)) == sorted(PH_RX.findall(seg))
        assert len(tr.events) == 1
        assert tr.events[0]["moved"] == mv


class TestFinalizeLedger:
    def _b_tr_with_event(self) -> object:
        tr = tb.make_translator("sabotage-b")
        tr.events.append({"seg": _SRC, "kind": "fabricate_ph", "detail": "fab"})
        return tr

    def test_b_buckets(self) -> None:
        tr = self._b_tr_with_event()
        results = [
            _mk("0:0", _SRC, _CLEAN_ZH, "ok"),
            _mk("0:1", _SRC, _SRC, "fault", skipped=True),
            _mk("0:2", _SRC, _CORRUPT_ZH, "ok"),
            _mk("0:3", _SRC, _CLEAN_ZH, "partial"),
        ]
        led = tr.finalize(results)
        assert led["sabotaged"] == 4  # noqa: PLR2004
        assert led["caught"] == 1
        assert led["recovered"] == 2  # noqa: PLR2004
        assert led["escaped"] == 1
        assert led["escaped_ids"] == ["0:2"]

    def test_b_partial_corrupt_is_escaped_not_caught(self) -> None:
        """交付谓词钉：partial+译文进 splice（stage_xlat:142/_delivered），
        残留破坏必须记 escaped——严卡 ok 会把脏 partial 吞成 caught 绕过门槛。"""
        tr = self._b_tr_with_event()
        led = tr.finalize([_mk("0:0", _SRC, _CORRUPT_ZH, "partial")])
        assert led["escaped"] == 1
        assert led["escaped_ids"] == ["0:0"]
        assert led["caught"] == 0

    def test_b_partial_without_zh_counts_caught(self) -> None:
        tr = self._b_tr_with_event()
        led = tr.finalize([_mk("0:0", _SRC, "", "partial")])
        assert led["caught"] == 1
        assert led["escaped"] == 0

    def test_c_partial_is_spliced(self) -> None:
        tr = tb.make_translator("perturb")
        tr.events.append({"seg": _SRC, "moved": 1})
        led = tr.finalize(
            [
                _mk("0:0", _SRC, _CLEAN_ZH, "ok"),
                _mk("0:1", _SRC, _CLEAN_ZH, "partial"),
                _mk("0:2", _SRC, _SRC, "fault", skipped=True),
            ]
        )
        assert led["spliced"] == 2  # noqa: PLR2004
        assert led["dropped"] == 1
        assert led["moved"] == 3  # noqa: PLR2004

    def test_finalize_idempotent(self) -> None:
        tr = self._b_tr_with_event()
        results = [_mk("0:0", _SRC, _CORRUPT_ZH, "ok")]
        first = tr.finalize(results)
        assert tr.finalize(results)["escaped"] == first["escaped"] == 1


class TestEndToEnd:
    def test_pipeline_blindspot_escape_lands_in_ledger(self) -> None:
        """校验器全放行的盲区内，破坏译文 ok 交付 → finalize 必须记 escaped。"""
        seg = _corruptible_seg()
        tr = tb.make_translator("sabotage-b")
        pipe = XlatPipeline(tr, validator=lambda _s, _z: "")
        results = asyncio.run(
            pipe.run([ChunkIn(chunk_id="0:0", content=seg, kind="para")])
        )
        led = tr.finalize(results)
        assert led["sabotaged"] == 1
        assert led["escaped"] == 1
        assert led["escaped_ids"] == ["0:0"]

    def test_pipeline_l0_catches_sabotage(self) -> None:
        """真 L0 校验器下破坏块三振回退 → caught 不 escaped（产品链自证）。"""
        from texlate.validate.l0 import (  # noqa: PLC0415 -- 延迟到用点: 重链
            validate_pair,
        )

        seg = _corruptible_seg()
        tr = tb.make_translator("sabotage-b")
        pipe = XlatPipeline(tr, validator=lambda s, z: validate_pair(s, z).feedback())
        results = asyncio.run(
            pipe.run([ChunkIn(chunk_id="0:0", content=seg, kind="para")])
        )
        led = tr.finalize(results)
        assert led["sabotaged"] == 1
        assert led["escaped"] == 0
        assert led["caught"] + led["recovered"] == 1
