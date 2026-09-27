r"""sabotage/perturb 臂注入与台账契约钉——``translators_bench`` + ``e2e_mock_bench``。

钉住的契约面（sabotage-audit 2026-09-17 实证）：

- 臂名 → 工厂：``mock`` 裸 MockTranslator（无台账面）；``sabotage-b`` →
  Mode B 台账臂；``sabotage-c``/``perturb`` → Mode C 位扰臂（别名同构）；
  未知臂 ``ValueError``——不存在静默降级 mock 的路径。
- 注入决策确定性：``_plan_b``/``_apply_c`` = f(段内容哈希 blake2s)，同输入
  跨调用同决策；``_canon`` 把 encoded/corrector-raw 归一→阶梯各阶段同决策。
- ``finalize`` 交付谓词 = ``pipecore.delivered``（ok | partial+译文，
  pipecore.py:132——translators_bench/e2e_mock_bench 同引此单源），与
  splice/e2e 台账同构——partial（阶梯 recovered）译文照进 zh/，严卡 ok
  会把脏 partial 记 caught 漏 escaped（旧 e2e_mock ``_delivered`` 的
  stagerun 侧漂移收敛于此）。
- Mode C 挪位保持占位符 multiset（过 L0 的设计前提）。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_SRC = "Paragraph body carries [[MATH_1]] and [[EQ_2]] tokens here."
_CLEAN_ZH = "译文 [[MATH_1]] 和 [[EQ_2]] 文本。"
_CORRUPT_ZH = "译文 [[MATH_1]] 和 [[EQ_2]] 外加 [[MATH_913]]。"


def _mk(cid: str, source: str, trans: str, status: str, **kw: object) -> ChunkResult:
    return ChunkResult(
        chunk_id=cid, source=source, translation=trans, kind="para", status=status, **kw
    )


def _scan_seg(
    fmt: str,
    pred: Callable[[str], object],
    *,
    tries: int = 3000,
    label: str = "planned",
) -> str:
    """确定性计划扫描：``fmt`` 内 ``{i}`` 逐枚探测段，``pred`` 命中即返。"""
    for i in range(tries):
        s = fmt.format(i=i)
        if pred(s):
            return s
    pytest.fail(f"no {label} seg in {tries}")
    return ""  # unreachable — pytest.fail raises


def _corruptible_seg() -> str:
    return _scan_seg(
        "Probe segment {i} embeds [[MATH_{i}]] plus [[EQ_{i}]] inline.",
        emb._plan_b,  # noqa: SLF001
        tries=500,
        label="corruptible",
    )


def _seg_of_kind(kind: str | None, prefix: str) -> str:
    """找 ``_plan_b`` 判 ``kind``（None = 计划外）的探测段。"""
    return _scan_seg(
        prefix + " {i} embeds [[MATH_{i}]] plus [[EQ_{i}]] inline.",
        lambda s: emb._plan_b(s) == kind,  # noqa: SLF001
        label=str(kind),
    )


def _movable_seg(prefix: str) -> tuple[str, int]:
    """``_apply_c`` 复算 ``moved>0`` 的探测段 + moved 数（同一次扫描返回）。"""
    mv = 0

    def hit(s: str) -> bool:
        nonlocal mv
        _, mv = emb._apply_c(  # noqa: SLF001
            _mock_translate_text(s, "这是译文"), s
        )
        return bool(mv)

    seg = _scan_seg(
        prefix + " {i} has [[MATH_{i}]] and [[EQ_{i}]] plus [[FIG_{i}]] text.",
        hit,
        label="movable",
    )
    return seg, mv


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
        seg = _scan_seg(
            "First line {i} here.\nSecond carries [[MATH_{i}]] plus [[EQ_{i}]].",
            emb._plan_b,  # noqa: SLF001
            tries=500,
            label="corruptible multiline",
        )
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
        seg, mv = _movable_seg("Gamma")
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
            _mk("0:1", _SRC, _SRC, "fault", skip_reason="ladder"),
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
        """交付谓词钉：partial+译文进 splice（``pipecore.delivered``——
        translators_bench 经 ``_delivered`` 别名消费 pipecore.py:132 单源），
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
                _mk("0:2", _SRC, _SRC, "fault", skip_reason="ladder"),
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


class TestResumeRecheck:
    """续跑洞钉（sabotage-resume 2026-09-17）：state 恢复行零事件——
    ``finalize`` 按 blake2s 计划从 ``r.source`` 复算靶向，drop 型逃逸不漏账。"""

    def test_resume_state_row_escape_counted(self, tmp_path: Path) -> None:
        """真实续跑复现：drop 破坏译文 ok 落 state → 第二轮全恢复零事件 →
        ``finalize`` 必须把 state 行的 multiset 破坏记 escaped（修复前静默漏账）。"""
        from texlate.xlat.state import StateStore  # noqa: PLC0415 -- 延迟到用点

        seg = _seg_of_kind("drop_ph", "Resume probe")
        chunks = [ChunkIn(chunk_id="0:0", content=seg, kind="para")]
        # 第一轮：放行校验器 → drop 破坏译文以 ok 落 state（逃逸既成事实；
        # zh⊆src 过 reload 三网，下一轮按 completed 直还原不再发请求）
        tr1 = tb.make_translator("sabotage-b")
        pipe1 = XlatPipeline(
            tr1, state=StateStore(tmp_path), validator=lambda _s, _z: ""
        )
        r1 = asyncio.run(pipe1.run(chunks))
        assert r1[0].status == "ok"
        assert len(tr1.events) == 1
        # 第二轮（续跑语义）：全新 translator + 同 state → 零调用零事件
        tr2 = tb.make_translator("sabotage-b")
        pipe2 = XlatPipeline(
            tr2, state=StateStore(tmp_path), validator=lambda _s, _z: ""
        )
        r2 = asyncio.run(pipe2.run(chunks))
        assert tr2.calls == []
        assert tr2.events == []
        led = tr2.finalize(r2)
        assert led["n_events"] == 0
        assert led["sabotaged"] == 1
        assert led["escaped"] == 1
        assert led["escaped_ids"] == ["0:0"]

    def test_restored_row_without_events_rechecked(self) -> None:
        """台账面直测：零事件 + state 恢复形行（ok + drop 破坏译文）→ escaped。"""
        seg = _seg_of_kind("drop_ph", "Direct probe")
        zh, _detail = emb._apply_b(  # noqa: SLF001
            _mock_translate_text(seg, "这是译文"), seg, "drop_ph"
        )
        tr = tb.make_translator("sabotage-b")  # 全新实例 = 续跑语义（events 空）
        led = tr.finalize([_mk("0:0", seg, zh, "ok")])
        assert led["sabotaged"] == 1
        assert led["escaped"] == 1
        assert led["escaped_ids"] == ["0:0"]

    def test_restored_clean_row_counts_recovered(self) -> None:
        """靶向恢复行交付译文 multiset 对齐 → recovered 不 escaped。"""
        seg = _seg_of_kind("drop_ph", "Clean probe")
        zh = _mock_translate_text(seg, "这是译文")  # token 原位保留 → multiset 对齐
        tr = tb.make_translator("sabotage-b")
        led = tr.finalize([_mk("0:0", seg, zh, "ok")])
        assert led["sabotaged"] == 1
        assert led["recovered"] == 1
        assert led["escaped"] == 0

    def test_restored_fault_row_counts_caught(self) -> None:
        """靶向恢复行未交付（fault 回退原文）→ caught——交付谓词同事件口径。"""
        seg = _seg_of_kind("drop_ph", "Fault probe")
        tr = tb.make_translator("sabotage-b")
        led = tr.finalize([_mk("0:0", seg, seg, "fault", skip_reason="ladder")])
        assert led["sabotaged"] == 1
        assert led["caught"] == 1
        assert led["escaped"] == 0

    def test_untargeted_restored_row_untouched(self) -> None:
        """计划外恢复行（``_plan_b`` None）→ 不计 sabotaged——复算不放大覆盖。"""
        seg = _seg_of_kind(None, "Quiet probe")
        tr = tb.make_translator("sabotage-b")
        led = tr.finalize([_mk("0:0", seg, "译文。", "ok")])
        assert led["sabotaged"] == 0
        assert led["escaped"] == 0

    def test_mixed_event_and_restored_rows(self) -> None:
        """混合轮：本轮发请求块走事件账 + 恢复行走复算——两路并账各记一次。"""
        seg_a = _seg_of_kind("drop_ph", "Alpha probe")
        seg_b = _seg_of_kind("drop_ph", "Beta probe")
        tr = tb.make_translator("sabotage-b")
        out_a = asyncio.run(
            tr.translate(system="s", user=seg_a, temperature=0, max_tokens=99)
        )
        assert len(tr.events) == 1
        zh_b, _detail = emb._apply_b(  # noqa: SLF001
            _mock_translate_text(seg_b, "这是译文"), seg_b, "drop_ph"
        )
        led = tr.finalize(
            [
                _mk("0:0", seg_a, out_a, "ok"),  # 事件块
                _mk("0:1", seg_b, zh_b, "ok"),  # 恢复行（零事件）
            ]
        )
        assert led["sabotaged"] == 2  # noqa: PLR2004
        assert led["escaped"] == 2  # noqa: PLR2004
        assert sorted(led["escaped_ids"]) == ["0:0", "0:1"]

    def test_event_row_not_double_counted(self) -> None:
        """事件块同时被复算命中——evs 优先不双计（事件驱动计数口径不变）。"""
        seg = _seg_of_kind("drop_ph", "Once probe")
        tr = tb.make_translator("sabotage-b")
        out = asyncio.run(
            tr.translate(system="s", user=seg, temperature=0, max_tokens=99)
        )
        assert len(tr.events) == 1
        led = tr.finalize([_mk("0:0", seg, out, "ok")])
        assert led["sabotaged"] == 1
        assert led["escaped"] == 1
        assert led["escaped_ids"] == ["0:0"]

    def test_mode_c_restored_row_spliced(self) -> None:
        """Mode C 恢复行：规范形 ``_apply_c`` 复算 moved>0 → spliced + moved 入账。"""
        seg, mv = _movable_seg("Delta")
        pert, _ = emb._apply_c(  # noqa: SLF001
            _mock_translate_text(seg, "这是译文"), seg
        )
        tr = tb.make_translator("perturb")
        led = tr.finalize([_mk("0:0", seg, pert, "ok")])
        assert led["sabotaged"] == 1
        assert led["spliced"] == 1
        assert led["dropped"] == 0
        assert led["moved"] == mv
