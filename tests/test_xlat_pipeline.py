"""pipeline：MockTranslator E2E——批量/单翻/退化/续跑/切分/缓存，不触网。"""

import asyncio
import json
from pathlib import Path

import pytest

from texlate.xlat import pipeline as pl
from texlate.xlat.client import AuthError
from texlate.xlat.state import StateStore


def _run(chunks: list[pl.ChunkIn], **kw: object) -> list[pl.ChunkResult]:
    return asyncio.run(pl.XlatPipeline(**kw).run(chunks))


def _mk(content: str, cid: str, kind: str = "para") -> pl.ChunkIn:
    return pl.ChunkIn(chunk_id=cid, content=content, kind=kind)


class _BadBatchTranslator(pl.MockTranslator):
    """批量调用返回坏格式（无编号无 @@），单翻正常——触发整批退单翻。"""

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        if user.startswith("[1]"):
            self.calls.append({"system": system, "user": user})
            return "garbage response without markers"
        return await super().translate(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )


class _AuthFailTranslator:
    """非可重试错误——整批成员应直接 skip 不丢块。"""

    async def translate(self, **_kw: object) -> str:
        msg = "denied"
        raise AuthError(msg, status=401)


class TestEndToEnd:
    def test_mixed_chunks_all_ok(self) -> None:
        t = pl.MockTranslator()
        chunks = [
            _mk("Short one [[MATH_1]]", "s1"),
            _mk("Short two [[CITE_2]]", "s2"),
            _mk("Long prose " + "x" * 400 + " [[REF_3]]", "l1"),
            _mk("[[MATH_9]]", "ph1"),
        ]
        out = _run(chunks, translator=t)
        assert [r.chunk_id for r in out] == ["s1", "s2", "l1", "ph1"]
        assert all(r.status == "ok" for r in out)
        # 短块走了批量路径
        assert out[0].batched
        assert out[0].batch_id == "batch_0000"
        assert out[1].batched
        assert out[1].batch_id == "batch_0000"
        # 长块单翻
        assert not out[2].batched
        # 纯占位符不发请求、原样落盘
        assert out[3].translation == "[[MATH_9]]"
        # 占位符契约
        assert "[[MATH_1]]" in out[0].translation
        assert "[[CITE_2]]" in out[1].translation
        assert "[[REF_3]]" in out[2].translation

    def test_batch_degrade_to_singles(self) -> None:
        t = _BadBatchTranslator()
        chunks = [_mk("A [[MATH_1]]", "a"), _mk("B [[CITE_2]]", "b")]
        out = _run(chunks, translator=t)
        assert all(r.status == "ok" for r in out)
        # 批解析失败 → 成员走单块阶梯，仍拿到含占位符的译文
        assert "[[MATH_1]]" in out[0].translation
        assert "[[CITE_2]]" in out[1].translation
        # 批调用 1 次 + 每成员单翻至少 1 次
        assert len(t.calls) >= 3  # noqa: PLR2004 -- 批1+单翻2

    def test_batch_auth_error_skips_all(self) -> None:
        chunks = [_mk("A", "a"), _mk("B", "b")]
        out = _run(chunks, translator=_AuthFailTranslator())
        assert all(r.status == "skipped" for r in out)
        assert all(r.skipped for r in out)
        assert all(r.translation == r.source for r in out)
        assert all("denied" in r.skip_reason for r in out)

    def test_split_chunk_merged_under_parent_id(self) -> None:
        cfg = pl.PipelineConfig(hard_limit=80, short_limit=40)
        big = "Sentence one here. " * 20  # ~380 chars → 切多片
        out = _run([_mk(big, "big")], translator=pl.MockTranslator(), config=cfg)
        assert len(out) == 1
        assert out[0].chunk_id == "big"
        assert out[0].status == "ok"
        assert pl.MOCK_ZH in out[0].translation

    def test_validator_failure_falls_back(self) -> None:
        """validator 恒败 → fallback_orig → status=fault + skipped。"""

        def always_bad(_src: str, _zh: str) -> str:
            return "always fails"

        out = _run(
            [_mk("Long prose " + "y" * 400, "l")],
            translator=pl.MockTranslator(),
            validator=always_bad,
        )
        assert out[0].status == "fault"
        assert out[0].skipped
        assert out[0].skip_reason


class TestResumeAndCache:
    def test_resume_skips_completed(self, tmp_path: Path) -> None:
        outdir = tmp_path / "out"
        chunks = [_mk("Long prose " + "x" * 400 + " [[MATH_1]]", "c1")]
        t1 = pl.MockTranslator()
        r1 = _run(chunks, translator=t1, state=StateStore(outdir))
        assert r1[0].status == "ok"

        # 第二轮：全新 translator + 同 outdir → completed 跳过、零调用
        t2 = pl.MockTranslator()
        r2 = _run(chunks, translator=t2, state=StateStore(outdir))
        assert t2.calls == []
        assert r2[0].translation == r1[0].translation

    def test_resume_retries_fault(self, tmp_path: Path) -> None:
        """fault/skipped 块不进 completed——续跑必须重试（瞬时失败不该永久冻结）。"""
        outdir = tmp_path / "out"
        chunks = [_mk("Long prose " + "x" * 400 + " [[MATH_1]]", "c1")]
        r1 = _run(
            chunks,
            translator=pl.MockTranslator(),
            state=StateStore(outdir),
            validator=lambda _s, _z: "always fails",
        )
        assert r1[0].status == "fault"

        t2 = pl.MockTranslator()
        r2 = _run(chunks, translator=t2, state=StateStore(outdir))
        assert t2.calls  # 重试真实发生
        assert r2[0].status == "ok"

    def test_resume_source_drift_retranslates(self, tmp_path: Path) -> None:
        """同 chunk_id 但 source 漂移 → 旧记录不命中、重翻覆盖（splice 残留防线）。"""
        outdir = tmp_path / "out"
        old = [_mk("Long prose " + "x" * 400 + " [[MATH_1]]", "c1")]
        r1 = _run(old, translator=pl.MockTranslator(), state=StateStore(outdir))
        assert r1[0].status == "ok"

        new = [_mk("Long prose " + "y" * 400 + " [[MATH_1]]", "c1")]
        t2 = pl.MockTranslator()
        r2 = _run(new, translator=t2, state=StateStore(outdir))
        assert t2.calls  # 漂移不命中 → 真实重翻
        assert r2[0].source == new[0].content
        assert r2[0].status == "ok"

    def test_worker_survives_emit_failure(self) -> None:
        """on_result/state 落盘抛错不能杀 worker——一死 queue.join() 就死等。"""
        chunks = [
            _mk("Long prose " + "x" * 400 + f" [[MATH_{i}]]", f"c{i}")
            for i in range(1, 5)
        ]

        def bad_callback(_r: pl.ChunkResult) -> None:
            msg = "emit exploded"
            raise RuntimeError(msg)

        out = _run(chunks, translator=pl.MockTranslator(), on_result=bad_callback)
        assert len(out) == len(chunks)
        assert all(r.status == "ok" for r in out)

    def test_segment_cache_hit(self) -> None:
        cache: dict[str, str] = {}
        chunks = [_mk("Long prose " + "x" * 400 + " [[MATH_1]]", "c1")]
        r1 = _run(chunks, translator=pl.MockTranslator(), cache=cache)
        assert cache  # 段级缓存已写

        t2 = pl.MockTranslator()
        r2 = _run(chunks, translator=t2, cache=cache)
        assert t2.calls == []
        assert r2[0].translation == r1[0].translation

    def test_state_records_five_tables(self, tmp_path: Path) -> None:
        outdir = tmp_path / "out"
        chunks = [_mk("Long prose " + "x" * 400, "c1")]
        _run(chunks, translator=pl.MockTranslator(), state=StateStore(outdir))
        data = json.loads((outdir / "state.json").read_text(encoding="utf-8"))
        assert data["completed"] == ["c1"]
        assert data["results"][0]["status"] == "ok"
        assert data["meta"]["total_chunks"] == 1


class _SelectiveAuthTranslator(pl.MockTranslator):
    """user 含 ``BAD`` 的块抛 AuthError(401)，其余走 Mock——闸清零测试用。"""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[str] = []

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        self.seen.append(user)
        if "BAD" in user:
            msg = "denied"
            raise AuthError(msg, status=401)
        return await super().translate(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )


def _auth_rec(cid: str) -> pl.ChunkResult:
    """合成一条 auth-fail 结果（AuthGate 单元测试用）。"""
    return pl.ChunkResult(
        chunk_id=cid,
        source="s",
        translation="s",
        kind="para",
        status="skipped",
        skipped=True,
        error_kind="auth",
    )


class TestAuthGate:
    """T2：连续 N 块 auth 失败 → AuthTrippedError（论文 fault 信号）。"""

    def test_trip_raises(self) -> None:
        pipe = pl.XlatPipeline(translator=_AuthFailTranslator())
        chunks = [_mk(f"para {i} text", f"a{i}") for i in range(4)]
        with pytest.raises(pl.AuthTrippedError):
            asyncio.run(pipe.run(chunks))
        assert pipe.auth_gate.tripped
        assert pipe.auth_gate.all_failed

    def test_under_threshold_returns(self) -> None:
        """2 块全 auth-fail 不够闸——run 正常返回，但 all_failed 置证
        （跨篇熔断器读这个：连续全 auth 败的论文数）。"""
        pipe = pl.XlatPipeline(translator=_AuthFailTranslator())
        out = asyncio.run(pipe.run([_mk("a", "a"), _mk("b", "b")]))
        assert all(r.skipped and r.error_kind == "auth" for r in out)
        assert not pipe.auth_gate.tripped
        assert pipe.auth_gate.all_failed

    def test_success_resets_consecutive(self) -> None:
        """bad,bad,ok,bad,bad：ok 清零连续计数——不熔断、正常返回。"""
        cfg = pl.PipelineConfig(concurrency=1, short_limit=0)
        t = _SelectiveAuthTranslator()
        chunks = [
            _mk("BAD one", "b1"),
            _mk("BAD two", "b2"),
            _mk("good para", "g1"),
            _mk("BAD three", "b3"),
            _mk("BAD four", "b4"),
        ]
        out = asyncio.run(pl.XlatPipeline(t, config=cfg).run(chunks))
        assert len(t.seen) == len(chunks)  # 每块真发过请求
        assert [r.chunk_id for r in out] == ["b1", "b2", "g1", "b3", "b4"]
        assert out[2].status == "ok"
        assert all(r.error_kind == "auth" for r in out if r.chunk_id != "g1")

    def test_tripped_short_circuits_rest(self) -> None:
        """闸断后剩余块不再发请求——直接按 auth 失败记账。"""
        cfg = pl.PipelineConfig(concurrency=1, short_limit=0)
        t = _SelectiveAuthTranslator()
        pipe = pl.XlatPipeline(t, config=cfg)
        chunks = [_mk(f"BAD text {i}", f"c{i}") for i in range(6)]
        with pytest.raises(pl.AuthTrippedError):
            asyncio.run(pipe.run(chunks))
        assert len(t.seen) == 3  # noqa: PLR2004 -- 闸断后零请求
        assert pipe.auth_gate.auth_failures == len(chunks)

    def test_gate_reset_between_runs(self) -> None:
        """run() 开头重置闸——同一 pipe 二跑不吃上篇的连续计数。"""
        cfg = pl.PipelineConfig(concurrency=1, short_limit=0)
        pipe = pl.XlatPipeline(_AuthFailTranslator(), config=cfg)
        bad = [_mk(f"text {i}", f"c{i}") for i in range(3)]
        with pytest.raises(pl.AuthTrippedError):
            asyncio.run(pipe.run(bad))
        pipe.translator = pl.MockTranslator()
        out = asyncio.run(pipe.run([_mk("fine", "g1")]))
        assert out[0].status == "ok"
        assert not pipe.auth_gate.tripped
        assert not pipe.auth_gate.all_failed

    def test_cache_hit_does_not_reset(self) -> None:
        """attempts==0 且无 error_kind 的结果（缓存命中）不清零连续计数。"""
        g = pl.AuthGate(threshold=3)
        g.record(_auth_rec("a"))
        g.record(_auth_rec("b"))
        g.record(
            pl.ChunkResult(chunk_id="c", source="s", translation="t", kind="para")
        )  # 缓存命中：attempts=0、error_kind="" → 中性
        assert g.consecutive == 2  # noqa: PLR2004 -- 二连不清零
        g.record(_auth_rec("d"))
        assert g.tripped

    def test_threshold_zero_disables(self) -> None:
        """auth_fail_threshold<=0 → 闸停用（auth-fail 仍照常记 skipped）。"""
        cfg = pl.PipelineConfig(auth_fail_threshold=0)
        pipe = pl.XlatPipeline(_AuthFailTranslator(), config=cfg)
        out = asyncio.run(pipe.run([_mk(f"t{i}", f"c{i}") for i in range(4)]))
        assert all(r.skipped for r in out)
        assert not pipe.auth_gate.tripped
