"""pipeline：MockTranslator E2E——批量/单翻/退化/续跑/切分/缓存，不触网。"""

import asyncio
import json
from pathlib import Path

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
