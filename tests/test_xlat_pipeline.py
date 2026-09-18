"""pipeline：MockTranslator E2E——批量/单翻/退化/续跑/切分/缓存，不触网。"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from conftest import mk_chunk, run_pipeline

from texlate.xlat import pipeline as pl
from texlate.xlat import prompts
from texlate.xlat.client import AuthError
from texlate.xlat.glossary import Glossary, TermEntry
from texlate.xlat.state import StateStore


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
            mk_chunk("Short one [[MATH_1]]", "s1"),
            mk_chunk("Short two [[CITE_2]]", "s2"),
            mk_chunk("Long prose " + "x" * 400 + " [[REF_3]]", "l1"),
            mk_chunk("Caption text " + "y" * 50, "cap1", kind="caption"),
            mk_chunk("[[MATH_9]]", "ph1"),
        ]
        out = run_pipeline(chunks, translator=t)
        assert [r.chunk_id for r in out] == ["s1", "s2", "l1", "cap1", "ph1"]
        assert all(r.status == "ok" for r in out)
        # 全量入批——para 三块不分长短同批
        assert out[0].batched
        assert out[0].batch_id == "batch_0000"
        assert out[1].batched
        assert out[1].batch_id == "batch_0000"
        assert out[2].batched
        assert out[2].batch_id == "batch_0000"
        # 独员 kind 组退化成 single 阶梯路径
        assert not out[3].batched
        # 纯占位符不发请求、原样落盘
        assert out[4].translation == "[[MATH_9]]"
        # 占位符契约
        assert "[[MATH_1]]" in out[0].translation
        assert "[[CITE_2]]" in out[1].translation
        assert "[[REF_3]]" in out[2].translation

    def test_bib_passthrough(self) -> None:
        """``[[BIB_`` 块=文献域——直通留英不送翻（裁决①），占位符下游还原。"""
        t = pl.MockTranslator()
        bib = "[[BIB_1]] P.D. BATISTA, Some title, Phys. Rev. 1999"
        chunks = [
            mk_chunk(bib, "b1"),
            mk_chunk("Real prose [[MATH_1]]", "p1"),
        ]
        out = run_pipeline(chunks, translator=t)
        assert out[0].translation == bib
        assert out[0].status == "ok"
        assert "bib_passthrough" in out[0].warnings
        assert not out[0].batched
        # 直通块零请求——只有 p1 进了模型载荷
        assert len(t.calls) == 1
        assert "[[BIB_" not in t.calls[0]["user"]

    def test_bib_passthrough_oversize_no_split(self) -> None:
        """bib 直通先于切分判定——超长 bib 块不切、整段原样。"""
        t = pl.MockTranslator()
        bib = "[[BIB_1]] " + "Author Title Journal " * 80
        chunks = [mk_chunk(bib, "big")]
        out = run_pipeline(
            chunks, translator=t, config=pl.PipelineConfig(hard_limit=200)
        )
        assert len(out) == 1
        assert out[0].translation == bib
        assert not t.calls

    def test_batch_degrade_to_singles(self) -> None:
        t = _BadBatchTranslator()
        chunks = [mk_chunk("A [[MATH_1]]", "a"), mk_chunk("B [[CITE_2]]", "b")]
        out = run_pipeline(chunks, translator=t)
        assert all(r.status == "ok" for r in out)
        # 批解析失败 → 成员走单块阶梯，仍拿到含占位符的译文
        assert "[[MATH_1]]" in out[0].translation
        assert "[[CITE_2]]" in out[1].translation
        # 批调用 1 次 + 每成员单翻至少 1 次
        assert len(t.calls) >= 3  # noqa: PLR2004 -- 批1+单翻2

    def test_batch_auth_error_skips_all(self) -> None:
        chunks = [mk_chunk("A", "a"), mk_chunk("B", "b")]
        out = run_pipeline(chunks, translator=_AuthFailTranslator())
        assert all(r.status == "skipped" for r in out)
        assert all(r.skipped for r in out)
        assert all(r.translation == r.source for r in out)
        assert all("denied" in r.skip_reason for r in out)

    def test_split_chunk_merged_under_parent_id(self) -> None:
        cfg = pl.PipelineConfig(hard_limit=80)
        big = "Sentence one here. " * 20  # ~380 chars → 切多片
        out = run_pipeline(
            [mk_chunk(big, "big")], translator=pl.MockTranslator(), config=cfg
        )
        assert len(out) == 1
        assert out[0].chunk_id == "big"
        assert out[0].status == "ok"
        assert pl.MOCK_ZH in out[0].translation

    def test_validator_failure_falls_back(self) -> None:
        """validator 恒败 → fallback_orig → status=fault + skipped。"""

        def always_bad(_src: str, _zh: str) -> str:
            return "always fails"

        out = run_pipeline(
            [mk_chunk("Long prose " + "y" * 400, "l")],
            translator=pl.MockTranslator(),
            validator=always_bad,
        )
        assert out[0].status == "fault"
        assert out[0].skipped
        assert out[0].skip_reason

    def test_leftover_ph_flagged(self) -> None:
        """B7 观测面：译文残留源外占位符 token → 升格 fault + 回退原文 + warning 落库。"""

        class Hallucinator(pl.MockTranslator):
            async def translate(self, *, user: str, **_kw: object) -> str:
                return user + " [[MATH_99]]"  # 幻觉 token 穿透

        out = run_pipeline(
            [mk_chunk("Long prose " + "x" * 400, "c1")],
            translator=Hallucinator(),
            validator=lambda _s, _z: "",  # 校验放行——模拟 B7 穿透路径
        )
        assert out[0].status == "fault"
        assert out[0].translation == out[0].source
        assert "leftover_ph:1" in out[0].warnings

        clean = run_pipeline(
            [mk_chunk("Long prose " + "x" * 400, "c2")],
            translator=pl.MockTranslator(),
        )
        assert not any(w.startswith("leftover_ph") for w in clean[0].warnings)

    def test_punct_run_collapse(self) -> None:
        """E24 退化清理件：模型输出 20+ 连排句读 → 坍成单 ``.``。"""

        class Degenerate(pl.MockTranslator):
            async def translate(self, **_kw: object) -> str:
                return "译文 [[MATH_1]] " + "。" * 25

        out = run_pipeline(
            [mk_chunk("Some prose [[MATH_1]]", "p1", kind="caption")],
            translator=Degenerate(),
        )
        assert out[0].status == "ok"
        assert "。" * 2 not in out[0].translation
        assert out[0].translation.endswith("[[MATH_1]] .")


class TestResumeAndCache:
    def test_resume_skips_completed(self, tmp_path: Path) -> None:
        outdir = tmp_path / "out"
        chunks = [mk_chunk("Long prose " + "x" * 400 + " [[MATH_1]]", "c1")]
        t1 = pl.MockTranslator()
        r1 = run_pipeline(chunks, translator=t1, state=StateStore(outdir))
        assert r1[0].status == "ok"

        # 第二轮：全新 translator + 同 outdir → completed 跳过、零调用
        t2 = pl.MockTranslator()
        r2 = run_pipeline(chunks, translator=t2, state=StateStore(outdir))
        assert t2.calls == []
        assert r2[0].translation == r1[0].translation

    def test_resume_retries_fault(self, tmp_path: Path) -> None:
        """fault/skipped 块不进 completed——续跑必须重试（瞬时失败不该永久冻结）。"""
        outdir = tmp_path / "out"
        chunks = [mk_chunk("Long prose " + "x" * 400 + " [[MATH_1]]", "c1")]
        r1 = run_pipeline(
            chunks,
            translator=pl.MockTranslator(),
            state=StateStore(outdir),
            validator=lambda _s, _z: "always fails",
        )
        assert r1[0].status == "fault"

        t2 = pl.MockTranslator()
        r2 = run_pipeline(chunks, translator=t2, state=StateStore(outdir))
        assert t2.calls  # 重试真实发生
        assert r2[0].status == "ok"

    def test_resume_source_drift_retranslates(self, tmp_path: Path) -> None:
        """同 chunk_id 但 source 漂移 → 旧记录不命中、重翻覆盖（splice 残留防线）。"""
        outdir = tmp_path / "out"
        old = [mk_chunk("Long prose " + "x" * 400 + " [[MATH_1]]", "c1")]
        r1 = run_pipeline(old, translator=pl.MockTranslator(), state=StateStore(outdir))
        assert r1[0].status == "ok"

        new = [mk_chunk("Long prose " + "y" * 400 + " [[MATH_1]]", "c1")]
        t2 = pl.MockTranslator()
        r2 = run_pipeline(new, translator=t2, state=StateStore(outdir))
        assert t2.calls  # 漂移不命中 → 真实重翻
        assert r2[0].source == new[0].content
        assert r2[0].status == "ok"

    def test_worker_survives_emit_failure(self) -> None:
        """on_result/state 落盘抛错不能杀 worker——一死 queue.join() 就死等。"""
        chunks = [
            mk_chunk("Long prose " + "x" * 400 + f" [[MATH_{i}]]", f"c{i}")
            for i in range(1, 5)
        ]

        def bad_callback(_r: pl.ChunkResult) -> None:
            msg = "emit exploded"
            raise RuntimeError(msg)

        out = run_pipeline(
            chunks, translator=pl.MockTranslator(), on_result=bad_callback
        )
        assert len(out) == len(chunks)
        assert all(r.status == "ok" for r in out)

    def test_segment_cache_hit(self) -> None:
        cache: dict[str, str] = {}
        chunks = [mk_chunk("Long prose " + "x" * 400 + " [[MATH_1]]", "c1")]
        r1 = run_pipeline(chunks, translator=pl.MockTranslator(), cache=cache)
        assert cache  # 段级缓存已写

        t2 = pl.MockTranslator()
        r2 = run_pipeline(chunks, translator=t2, cache=cache)
        assert t2.calls == []
        assert r2[0].translation == r1[0].translation

    def test_state_records_five_tables(self, tmp_path: Path) -> None:
        outdir = tmp_path / "out"
        chunks = [mk_chunk("Long prose " + "x" * 400, "c1")]
        run_pipeline(chunks, translator=pl.MockTranslator(), state=StateStore(outdir))
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
        chunks = [mk_chunk(f"para {i} text", f"a{i}") for i in range(4)]
        with pytest.raises(pl.AuthTrippedError):
            asyncio.run(pipe.run(chunks))
        assert pipe.auth_gate.tripped
        assert pipe.auth_gate.all_failed

    def test_under_threshold_returns(self) -> None:
        """2 块全 auth-fail 不够闸——run 正常返回，但 all_failed 置证
        （跨篇熔断器读这个：连续全 auth 败的论文数）。"""
        pipe = pl.XlatPipeline(translator=_AuthFailTranslator())
        out = asyncio.run(pipe.run([mk_chunk("a", "a"), mk_chunk("b", "b")]))
        assert all(r.skipped and r.error_kind == "auth" for r in out)
        assert not pipe.auth_gate.tripped
        assert pipe.auth_gate.all_failed

    def test_success_resets_consecutive(self) -> None:
        """bad,bad,ok,bad,bad：ok 清零连续计数——不熔断、正常返回。"""
        cfg = pl.PipelineConfig(concurrency=1, batch_max_items=1)
        t = _SelectiveAuthTranslator()
        chunks = [
            mk_chunk("BAD one", "b1"),
            mk_chunk("BAD two", "b2"),
            mk_chunk("good para", "g1"),
            mk_chunk("BAD three", "b3"),
            mk_chunk("BAD four", "b4"),
        ]
        out = asyncio.run(pl.XlatPipeline(t, config=cfg).run(chunks))
        assert len(t.seen) == len(chunks)  # 每块真发过请求
        assert [r.chunk_id for r in out] == ["b1", "b2", "g1", "b3", "b4"]
        assert out[2].status == "ok"
        assert all(r.error_kind == "auth" for r in out if r.chunk_id != "g1")

    def test_tripped_short_circuits_rest(self) -> None:
        """闸断后剩余块不再发请求——直接按 auth 失败记账。"""
        cfg = pl.PipelineConfig(concurrency=1, batch_max_items=1)
        t = _SelectiveAuthTranslator()
        pipe = pl.XlatPipeline(t, config=cfg)
        chunks = [mk_chunk(f"BAD text {i}", f"c{i}") for i in range(6)]
        with pytest.raises(pl.AuthTrippedError):
            asyncio.run(pipe.run(chunks))
        assert len(t.seen) == 3  # noqa: PLR2004 -- 闸断后零请求
        assert pipe.auth_gate.auth_failures == len(chunks)

    def test_gate_reset_between_runs(self) -> None:
        """run() 开头重置闸——同一 pipe 二跑不吃上篇的连续计数。"""
        cfg = pl.PipelineConfig(concurrency=1, batch_max_items=1)
        pipe = pl.XlatPipeline(_AuthFailTranslator(), config=cfg)
        bad = [mk_chunk(f"text {i}", f"c{i}") for i in range(3)]
        with pytest.raises(pl.AuthTrippedError):
            asyncio.run(pipe.run(bad))
        pipe.translator = pl.MockTranslator()
        out = asyncio.run(pipe.run([mk_chunk("fine", "g1")]))
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
        out = asyncio.run(pipe.run([mk_chunk(f"t{i}", f"c{i}") for i in range(4)]))
        assert all(r.skipped for r in out)
        assert not pipe.auth_gate.tripped


class TestConfigClamps:
    def test_concurrency_zero_clamped(self) -> None:
        """concurrency=0 曾饿死 worker → queue.join() 死等；钳到 ≥1。"""
        cfg = pl.PipelineConfig(concurrency=0)
        assert cfg.concurrency == 1
        out = run_pipeline(
            [mk_chunk("Long prose " + "x" * 400, "c")],
            translator=pl.MockTranslator(),
            config=cfg,
        )
        assert out[0].status == "ok"

    def test_hard_limit_floor(self) -> None:
        """hard_limit<1 曾让 split_long_chunk 死循环（cut=0 rest 不变）。"""
        assert pl.PipelineConfig(hard_limit=0).hard_limit == 1
        assert pl.PipelineConfig(hard_limit=-9).hard_limit == 1


class TestSplitPieces:
    def test_split_pieces_keep_ph_fragments(self) -> None:
        """超大块切出的子片曾丢 ph_fragments——抄回修复臂对切片整体失效。"""
        frags = {"[[MATH_1]]": "$x$"}
        pipe = pl.XlatPipeline(
            translator=pl.MockTranslator(), config=pl.PipelineConfig(hard_limit=80)
        )
        c = pl.ChunkIn(
            "big",
            "Sentence one here. " * 30 + " [[MATH_1]]",
            "para",
            ph_fragments=frags,
        )
        pending, split_items = pipe._route_chunks([c], set(), {}, [])  # noqa: SLF001
        assert not pending
        assert len(split_items) == 1
        _parent, subs = split_items[0][1]
        assert len(subs) > 1
        assert all(s.ph_fragments == frags for s in subs)


class TestPromptReset:
    def test_prompts_reset_between_runs(self) -> None:
        """同实例二次 run 换文档 → 文档级术语变 → prompt memo 必须失效（曾陈旧）。"""
        g = Glossary(terms={"attention": TermEntry("attention", "注意力", "user")})
        t = pl.MockTranslator()
        pipe = pl.XlatPipeline(translator=t, glossary=g)

        asyncio.run(pipe.run([mk_chunk("attention mechanism " + "x" * 400, "a")]))
        sys1 = t.calls[0]["system"]
        assert "注意力" in sys1

        asyncio.run(pipe.run([mk_chunk("totally different " + "y" * 400, "b")]))
        sys2 = t.calls[-1]["system"]
        assert "注意力" not in sys2


class TestCachePoisonGuard:
    def test_interceptable_translation_not_cached(self) -> None:
        """过升格拦截三网的译文不入段级缓存——防续跑反复命中永不自愈。"""

        class Fuser(pl.MockTranslator):
            async def translate(self, **_kw: object) -> str:
                return "译文 \\fo[[MATH_1]]o 其余照旧 " + "译" * 100

        cache: dict[str, str] = {}
        c = mk_chunk("Long prose " + "x" * 400 + " [[MATH_1]]", "c1")
        r1 = run_pipeline(
            [c], translator=Fuser(), cache=cache, validator=lambda _s, _z: ""
        )
        assert r1[0].status == "fault"
        assert cache == {}  # ph_in_cs 毒译未落缓存

    def test_legacy_poisoned_entry_evicted_on_hit(self) -> None:
        """旧版写入侧放行过的毒条目：命中即清 + 落回重翻自愈。"""
        cache: dict[str, str] = {}
        c = mk_chunk("Long prose " + "x" * 400 + " [[MATH_1]]", "c1")
        pipe = pl.XlatPipeline(translator=pl.MockTranslator(), cache=cache)
        key = pipe._seg_key(c)  # noqa: SLF001
        cache[key] = "译文 \\fo[[MATH_1]]o 其余照旧"

        t2 = pl.MockTranslator()
        r2 = run_pipeline([c], translator=t2, cache=cache, validator=lambda _s, _z: "")
        assert t2.calls  # 毒条目被清 → 真实重翻
        assert r2[0].status == "ok"
        assert "\\fo[[MATH_1]]o" not in cache[key]  # 已改写为干净译文

    def test_cache_store_rejects_all_three_nets(self) -> None:
        """写入侧三网同拒：leftover_ph / ph_in_cs / bare_cs。"""
        cache: dict[str, str] = {}
        pipe = pl.XlatPipeline(translator=pl.MockTranslator(), cache=cache)
        c = mk_chunk("src text [[MATH_1]]", "c")
        pipe._cache_store(c, "译 [[MATH_99]]")  # noqa: SLF001 -- leftover_ph
        pipe._cache_store(c, "译 \\fo[[MATH_1]]o")  # noqa: SLF001 -- ph_in_cs
        pipe._cache_store(c, "译 \\alpha 发射体")  # noqa: SLF001 -- bare_cs
        assert cache == {}
        pipe._cache_store(c, "干净译文 [[MATH_1]]")  # noqa: SLF001
        assert len(cache) == 1


class TestValueContextInjection:
    """v4-C：ph_fragments → user 侧 placeholder_values 块 / slots JSON 字段。"""

    def test_single_chunk_appends_block(self) -> None:
        t = pl.MockTranslator()
        c = pl.ChunkIn(
            "c1",
            "Prose " + "x" * 400 + " [[MATH_1]]",
            "para",
            ph_fragments={"[[MATH_1]]": "$E=mc^2$"},
        )
        out = run_pipeline([c], translator=t)
        assert out[0].status == "ok"
        user = t.calls[0]["user"]
        assert prompts.VALUE_CONTEXT_HEADER in user
        assert "- [[MATH_1]]: $E=mc^2$" in user
        # 块挂正文之后
        assert user.index("Prose") < user.index(prompts.VALUE_CONTEXT_HEADER)

    def test_no_frags_no_block(self) -> None:
        t = pl.MockTranslator()
        run_pipeline([mk_chunk("Prose " + "x" * 400, "c1")], translator=t)
        assert prompts.VALUE_CONTEXT_HEADER not in t.calls[0]["user"]

    def test_frag_truncated_in_user(self) -> None:
        t = pl.MockTranslator()
        c = pl.ChunkIn(
            "c1",
            "Prose " + "x" * 400 + " [[MATH_1]]",
            "para",
            ph_fragments={"[[MATH_1]]": "v" * 300},
        )
        run_pipeline([c], translator=t)
        user = t.calls[0]["user"]
        assert "v" * 200 + "…" in user
        assert "v" * 201 not in user

    def test_batch_merges_frags(self) -> None:
        """批 user = 编号行 + 合并 value 块；mock 批回显不受尾挂块影响。"""
        t = pl.MockTranslator()
        chunks = [
            pl.ChunkIn(
                "a",
                "Alpha " + "x" * 400 + " [[MATH_1]]",
                "para",
                ph_fragments={"[[MATH_1]]": "$x$"},
            ),
            pl.ChunkIn(
                "b",
                "Beta " + "y" * 400 + " [[CITE_2]]",
                "para",
                ph_fragments={"[[CITE_2]]": "\\cite{z}"},
            ),
        ]
        out = run_pipeline(chunks, translator=t)
        assert all(r.batched for r in out)  # 批协议真走到（非退单翻）
        batch_user = t.calls[0]["user"]
        assert batch_user.startswith("[1]")
        assert prompts.VALUE_CONTEXT_HEADER in batch_user
        assert "- [[MATH_1]]: $x$" in batch_user
        assert "- [[CITE_2]]: \\cite{z}" in batch_user
        assert batch_user.index("[2]") < batch_user.index(prompts.VALUE_CONTEXT_HEADER)

    def test_retranslate_block_before_error_tag(self) -> None:
        """L2 回灌 user：content → value 块 → [compile_error]。"""
        t = pl.MockTranslator()
        pipe = pl.XlatPipeline(translator=t)
        c = pl.ChunkIn(
            "c",
            "Body [[MATH_1]] text",
            "para",
            ph_fragments={"[[MATH_1]]": "$x$"},
        )
        r = asyncio.run(pipe.retranslate_chunk(c, "Missing $"))
        assert r is not None
        user = t.calls[0]["user"]
        assert "- [[MATH_1]]: $x$" in user
        assert user.index(prompts.VALUE_CONTEXT_HEADER) < user.index("[compile_error]")


class _SlotsOnlyTranslator:
    """非 JSON 调用恒答缺 token 废文逼 ladder 走 slots 臂；JSON 调用正常。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,  # noqa: ARG002 -- Translator 协议签名固定
        max_tokens: int,  # noqa: ARG002 -- Translator 协议签名固定
        response_format: dict[str, str] | None = None,
    ) -> str:
        self.calls.append(
            {"system": system, "user": user, "response_format": response_format}
        )
        if response_format and response_format.get("type") == "json_object":
            payload = json.loads(user)
            return json.dumps(
                dict.fromkeys(payload["slots"], "译文"), ensure_ascii=False
            )
        return "missing every token"  # 占位符 diff 恒败 → whole/lines 全灭


class TestSlotsValueContext:
    def test_slots_placeholder_values_field(self) -> None:
        """slots JSON user 带截断口径一致的 placeholder_values 字段。"""
        t = _SlotsOnlyTranslator()
        chunks = [
            pl.ChunkIn(
                "p1",
                "Alpha prose [[MATH_1]] omega.",
                "para",
                ph_fragments={"[[MATH_1]]": "$x$"},
            ),
        ]
        run_pipeline(chunks, translator=t)
        slots_calls = [c for c in t.calls if c["response_format"]]
        assert slots_calls  # 确实走到 slots 臂
        payloads = [json.loads(c["user"]) for c in slots_calls]
        assert all(p["placeholder_values"] == {"[[MATH_1]]": "$x$"} for p in payloads)

    def test_slots_system_has_no_paper_ctx(self) -> None:
        """slots system 不挂 paper-context 锚定块（主路径同 kind prompt 带）。"""
        t = _SlotsOnlyTranslator()
        chunks = [
            mk_chunk("Anchoring abstract text.", "abs", kind="abstract"),
            pl.ChunkIn(
                "p1",
                "Alpha prose [[MATH_1]] omega.",
                "para",
                ph_fragments={"[[MATH_1]]": "$x$"},
            ),
        ]
        run_pipeline(chunks, translator=t)
        slots_calls = [c for c in t.calls if c["response_format"]]
        assert slots_calls
        assert all("Paper context" not in c["system"] for c in slots_calls)
        # 对照：主路径 kind system 带锚定块（corrector 专用 prompt 不挂，剔出）
        main_calls = [
            c
            for c in t.calls
            if not c["response_format"] and not c["user"].startswith("[Original]")
        ]
        assert main_calls
        assert all("Paper context" in c["system"] for c in main_calls)


class TestPaperContext:
    """v4-D：首个 abstract 块 masked 原文 → 全 kind system 锚定块。"""

    def test_abstract_anchors_all_kinds(self) -> None:
        t = pl.MockTranslator()
        abstract = "We present a masked study of [[MATH_1]] dynamics."
        chunks = [
            mk_chunk(abstract, "abs", kind="abstract"),
            mk_chunk("Body prose " + "x" * 400, "p1"),
            mk_chunk("Caption " + "y" * 60, "cap", kind="caption"),
        ]
        run_pipeline(chunks, translator=t)
        assert len(t.calls) == 3  # noqa: PLR2004 -- 三 kind 各一单发
        for call in t.calls:
            assert "Paper context" in call["system"]
            assert "never translate, append, or summarize it" in call["system"]
            assert abstract in call["system"]

    def test_no_abstract_no_block(self) -> None:
        t = pl.MockTranslator()
        run_pipeline([mk_chunk("Prose " + "x" * 400, "c1")], translator=t)
        assert "Paper context" not in t.calls[0]["system"]

    def test_abstract_truncated_at_6000(self) -> None:
        t = pl.MockTranslator()
        chunks = [
            mk_chunk("A" * 7000, "abs", kind="abstract"),
            mk_chunk("Body " + "x" * 400, "p1"),
        ]
        run_pipeline(chunks, translator=t)
        for call in t.calls:
            assert "A" * pl.PAPER_CTX_MAX_CHARS in call["system"]
            assert "A" * (pl.PAPER_CTX_MAX_CHARS + 1) not in call["system"]

    def test_second_run_without_abstract_clears_ctx(self) -> None:
        """同实例二次 run 换无 abstract 文档 → 锚定块不残留。"""
        t = pl.MockTranslator()
        pipe = pl.XlatPipeline(translator=t)
        asyncio.run(pipe.run([mk_chunk("Abstract here.", "a1", kind="abstract")]))
        assert "Paper context" in t.calls[0]["system"]
        asyncio.run(pipe.run([mk_chunk("Plain prose " + "x" * 400, "p1")]))
        assert "Paper context" not in t.calls[-1]["system"]
