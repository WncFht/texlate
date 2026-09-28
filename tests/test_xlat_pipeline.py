"""pipeline：MockTranslator E2E——批量/单翻/退化/续跑/切分/缓存，不触网。"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from conftest import big_para, mk_chunk, pass_validate, run_pipeline

from texlate.validate.l0 import CACHE_VETO_RULES, Severity, validate_pair
from texlate.xlat import pipeline as pl
from texlate.xlat import prompts
from texlate.xlat.client import AuthError
from texlate.xlat.glossary import Glossary, TermEntry
from texlate.xlat.retry import SLOTS_MAX_ROUNDS
from texlate.xlat.state import StateStore


def fail_validate(_src: str, _zh: str) -> str:
    """恒败 validate hook——触发 fallback_orig/fault 路径。"""
    return "always fails"


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
            big_para("l1", tail=" [[REF_3]]"),
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
        assert all(r.fell_back for r in out)
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
        out = run_pipeline(
            [big_para("l", fill="y")],
            translator=pl.MockTranslator(),
            validator=fail_validate,
        )
        assert out[0].status == "fault"
        assert out[0].fell_back
        assert out[0].skip_reason

    def test_leftover_ph_flagged(self) -> None:
        """B7 观测面：译文残留源外占位符 token → 升格 fault + 回退原文 + warning 落库。"""

        class Hallucinator(pl.MockTranslator):
            async def translate(self, *, user: str, **_kw: object) -> str:
                return user + " [[MATH_99]]"  # 幻觉 token 穿透

        out = run_pipeline(
            [big_para("c1")],
            translator=Hallucinator(),
            validator=pass_validate,  # 校验放行——模拟 B7 穿透路径
        )
        assert out[0].status == "fault"
        assert out[0].translation == out[0].source
        assert "leftover_ph:1" in out[0].warnings

        clean = run_pipeline(
            [big_para("c2")],
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


class _ExplodingState:
    """``record()`` 恒抛的 StateStore 替身——``_emit`` state 臂注入面。

    只实现 run() 实际触达的四个方法（load/start/record/finish）；
    record 抛 RuntimeError 走 ``_ledger_call`` 的 Exception 档（log 续走）。
    """

    def load(self) -> tuple[set[str], dict[str, Any]]:
        return set(), {}

    def start(self, _total_chunks: int) -> None:
        pass

    def record(self, *_a: object, **_kw: object) -> None:
        msg = "state exploded"
        raise RuntimeError(msg)

    def finish(self) -> None:
        pass


class TestResumeAndCache:
    def test_resume_skips_completed(self, tmp_path: Path) -> None:
        outdir = tmp_path / "out"
        chunks = [big_para("c1", tail=" [[MATH_1]]")]
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
        chunks = [big_para("c1", tail=" [[MATH_1]]")]
        r1 = run_pipeline(
            chunks,
            translator=pl.MockTranslator(),
            state=StateStore(outdir),
            validator=fail_validate,
        )
        assert r1[0].status == "fault"

        t2 = pl.MockTranslator()
        r2 = run_pipeline(chunks, translator=t2, state=StateStore(outdir))
        assert t2.calls  # 重试真实发生
        assert r2[0].status == "ok"

    def test_resume_source_drift_retranslates(self, tmp_path: Path) -> None:
        """同 chunk_id 但 source 漂移 → 旧记录不命中、重翻覆盖（splice 残留防线）。"""
        outdir = tmp_path / "out"
        old = [big_para("c1", tail=" [[MATH_1]]")]
        r1 = run_pipeline(old, translator=pl.MockTranslator(), state=StateStore(outdir))
        assert r1[0].status == "ok"

        new = [big_para("c1", fill="y", tail=" [[MATH_1]]")]
        t2 = pl.MockTranslator()
        r2 = run_pipeline(new, translator=t2, state=StateStore(outdir))
        assert t2.calls  # 漂移不命中 → 真实重翻
        assert r2[0].source == new[0].content
        assert r2[0].status == "ok"

    def test_worker_survives_emit_failure(self) -> None:
        """on_result/state 落盘抛错不能杀 worker——一死 queue.join() 就死等。"""
        chunks = [big_para(f"c{i}", tail=f" [[MATH_{i}]]") for i in range(1, 5)]

        def bad_callback(_r: pl.ChunkResult) -> None:
            msg = "emit exploded"
            raise RuntimeError(msg)

        out = run_pipeline(
            chunks, translator=pl.MockTranslator(), on_result=bad_callback
        )
        assert len(out) == len(chunks)
        assert all(r.status == "ok" for r in out)

    def test_worker_survives_state_record_failure(self) -> None:
        """``_emit`` 的 state.record 臂同样收账——record 恒抛不杀 worker，
        且同一账本调用内 on_result 随之跳过（pipeline ``_emit`` 先 record
        后 on_result，record 抛错即整臂短路）。"""
        chunks = [big_para(f"c{i}", tail=f" [[MATH_{i}]]") for i in range(1, 4)]
        seen: list[str] = []

        out = run_pipeline(
            chunks,
            translator=pl.MockTranslator(),
            state=_ExplodingState(),
            on_result=lambda r: seen.append(r.chunk_id),
        )
        assert len(out) == len(chunks)
        assert all(r.status == "ok" for r in out)
        assert seen == []  # record 抛错 → 同 _ledger_call 内 on_result 不触达

    def test_segment_cache_hit(self) -> None:
        cache: dict[str, str] = {}
        chunks = [big_para("c1", tail=" [[MATH_1]]")]
        r1 = run_pipeline(chunks, translator=pl.MockTranslator(), cache=cache)
        assert cache  # 段级缓存已写

        t2 = pl.MockTranslator()
        r2 = run_pipeline(chunks, translator=t2, cache=cache)
        assert t2.calls == []
        assert r2[0].translation == r1[0].translation

    def test_pipeline_writes_state_completed_results_meta(self, tmp_path: Path) -> None:
        outdir = tmp_path / "out"
        chunks = [big_para("c1")]
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
        assert all(r.fell_back and r.error_kind == "auth" for r in out)
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
        assert all(r.fell_back for r in out)
        assert not pipe.auth_gate.tripped


class TestConfigClamps:
    def test_concurrency_zero_clamped(self) -> None:
        """concurrency=0 曾饿死 worker → queue.join() 死等；钳到 ≥1。"""
        cfg = pl.PipelineConfig(concurrency=0)
        assert cfg.concurrency == 1
        out = run_pipeline(
            [big_para("c")],
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

        asyncio.run(pipe.run([big_para("a", prefix="attention mechanism ")]))
        sys1 = t.calls[0]["system"]
        assert "注意力" in sys1

        asyncio.run(pipe.run([big_para("b", fill="y", prefix="totally different ")]))
        sys2 = t.calls[-1]["system"]
        assert "注意力" not in sys2


class TestCachePoisonGuard:
    def test_interceptable_translation_not_cached(self) -> None:
        """过升格拦截三网的译文不入段级缓存——防续跑反复命中永不自愈。"""

        class Fuser(pl.MockTranslator):
            async def translate(self, **_kw: object) -> str:
                return "译文 \\fo[[MATH_1]]o 其余照旧 " + "译" * 100

        cache: dict[str, str] = {}
        c = big_para("c1", tail=" [[MATH_1]]")
        r1 = run_pipeline([c], translator=Fuser(), cache=cache, validator=pass_validate)
        assert r1[0].status == "fault"
        assert cache == {}  # ph_in_cs 毒译未落缓存

    def test_legacy_poisoned_entry_evicted_on_hit(self) -> None:
        """旧版写入侧放行过的毒条目：命中即清 + 落回重翻自愈。"""
        cache: dict[str, str] = {}
        c = big_para("c1", tail=" [[MATH_1]]")
        pipe = pl.XlatPipeline(translator=pl.MockTranslator(), cache=cache)
        key = pipe._seg_key(c)  # noqa: SLF001
        cache[key] = "译文 \\fo[[MATH_1]]o 其余照旧"

        t2 = pl.MockTranslator()
        r2 = run_pipeline([c], translator=t2, cache=cache, validator=pass_validate)
        assert t2.calls  # 毒条目被清 → 真实重翻
        assert r2[0].status == "ok"
        assert "\\fo[[MATH_1]]o" not in cache[key]  # 已改写为干净译文

    def test_cache_store_rejects_all_nets(self) -> None:
        """写入侧注册表各网同拒：leftover_ph / ph_in_cs / bare_cs / residual_en。"""
        cache: dict[str, str] = {}
        pipe = pl.XlatPipeline(translator=pl.MockTranslator(), cache=cache)
        c = mk_chunk("src text [[MATH_1]]", "c")
        pipe._cache_store(c, "译 [[MATH_99]]")  # noqa: SLF001 -- leftover_ph
        pipe._cache_store(c, "译 \\fo[[MATH_1]]o")  # noqa: SLF001 -- ph_in_cs
        pipe._cache_store(c, "译 \\alpha 发射体")  # noqa: SLF001 -- bare_cs
        pipe._cache_store(c, "译文 \\input{main} 尾")  # noqa: SLF001 -- dangerous_cs
        pipe._cache_store(  # noqa: SLF001 -- residual_en（tier-B 混血长句臂）
            c,
            "前文。The quick brown fox jumps over the lazy dog "
            "repeatedly near the barn. 后文。",
        )
        assert cache == {}
        pipe._cache_store(c, "干净译文 [[MATH_1]]")  # noqa: SLF001
        assert len(cache) == 1


class TestInterceptRegistry:
    """升格拦截网注册表钉：唯一枚举面 + 三消费形同表 + l0 否决规则双向钉。"""

    def test_registry_membership_pinned(self) -> None:
        """注册表成员集钉——加网/除网必过本钉，防静默漂移。"""
        assert {n.name for n in pl._INTERCEPT_NETS} == {  # noqa: SLF001
            "leftover_ph",
            "ph_in_cs",
            "bare_cs",
            "residual_en",
            "dangerous_cs",
        }

    def test_l0_rule_set_matches_cache_veto(self) -> None:
        """``l0_rule`` 集 ≡ l0 ``CACHE_VETO_RULES``——加网改镜像任一侧漏更即红。"""
        assert {n.l0_rule for n in pl._INTERCEPT_NETS} == CACHE_VETO_RULES  # noqa: SLF001

    def test_every_net_has_apply_wrapper(self) -> None:
        """``_intercept_<name>`` 包装函存在钉——消费形经词根晚绑定取件，
        缺席即 ``_net_apply_fn`` KeyError 的静默漏网。"""
        for net in pl._INTERCEPT_NETS:  # noqa: SLF001
            assert callable(getattr(pl, f"_intercept_{net.name}"))

    @pytest.mark.parametrize(
        ("net_name", "src", "zh"),
        [
            ("leftover_ph", "plain English sentence here.", "译文 [[MATH_9]] 尾"),
            ("ph_in_cs", "plain English sentence here.", "译文 \\fo[[X_1]]o 尾"),
            ("bare_cs", "alpha emitters in the lab.", "\\alpha 发射体"),
            ("dangerous_cs", "plain English sentence here.", "译文 \\input{main} 尾"),
            (
                "residual_en",
                (
                    "Alpha intro sentence. The quick brown fox jumps over the "
                    "lazy dog repeatedly near the barn. Tail part ends here."
                ),
                (
                    "甲介绍句。The quick brown fox jumps over the lazy dog "
                    "repeatedly near the barn. 尾部到此。"
                ),
            ),
        ],
    )
    def test_net_detect_mirrors_l0_rule(self, net_name: str, src: str, zh: str) -> None:
        """每网一对实证料：``net.detect`` 命中 ⇒ ``validate_pair`` 必报
        ``net.l0_rule`` error——镜像关系语义钉而非仅名钉。"""
        net = next(n for n in pl._INTERCEPT_NETS if n.name == net_name)  # noqa: SLF001
        assert net.detect(src, zh)
        rep = validate_pair(src, zh)
        assert any(
            i.rule == net.l0_rule and i.severity is Severity.ERROR for i in rep.issues
        )

    def test_retranslate_consumes_registry_late_binding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """裸形 apply 臂与账本形同表晚绑定——补丁模块属性后 ``retranslate_chunk``
        仍触达，第 5 网不会在本臂漏挂。"""
        calls: list[str] = []
        orig = pl._intercept_leftover_ph  # noqa: SLF001 -- 私有拦截网正是注入面

        def _spy(r: pl.ChunkResult) -> None:
            calls.append(r.chunk_id)
            orig(r)

        monkeypatch.setattr(pl, "_intercept_leftover_ph", _spy)
        pipe = pl.XlatPipeline(translator=pl.MockTranslator())
        r = asyncio.run(
            pipe.retranslate_chunk(pl.ChunkIn("c", "plain src text", "para"), "err")
        )
        assert calls == ["c"]
        assert r is not None
        assert r.status == "ok"


class TestValueContextInjection:
    """v4-C：ph_fragments → user 侧 placeholder_values 块 / slots JSON 字段。"""

    def test_single_chunk_appends_block(self) -> None:
        t = pl.MockTranslator()
        c = big_para(
            "c1",
            tail=" [[MATH_1]]",
            prefix="Prose ",
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
        run_pipeline([big_para("c1", prefix="Prose ")], translator=t)
        assert prompts.VALUE_CONTEXT_HEADER not in t.calls[0]["user"]

    def test_frag_truncated_in_user(self) -> None:
        t = pl.MockTranslator()
        c = big_para(
            "c1",
            tail=" [[MATH_1]]",
            prefix="Prose ",
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
            big_para(
                "a",
                tail=" [[MATH_1]]",
                prefix="Alpha ",
                ph_fragments={"[[MATH_1]]": "$x$"},
            ),
            big_para(
                "b",
                fill="y",
                tail=" [[CITE_2]]",
                prefix="Beta ",
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
            big_para("p1", prefix="Body prose "),
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
        run_pipeline([big_para("c1", prefix="Prose ")], translator=t)
        assert "Paper context" not in t.calls[0]["system"]

    def test_abstract_truncated_at_6000(self) -> None:
        t = pl.MockTranslator()
        chunks = [
            mk_chunk("A" * 7000, "abs", kind="abstract"),
            big_para("p1", prefix="Body "),
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
        asyncio.run(pipe.run([big_para("p1", prefix="Plain prose ")]))
        assert "Paper context" not in t.calls[-1]["system"]


# ----------------------------------------------------- slots 超深 JSON 防御

#: ~100KB 即撞 json C 扫描器递归上限（实测阈值 ~20000 层，此处 50000 留足余量）。
_DEEP_JSON = "[" * 50000 + "]" * 50000


def test_slots_fn_deep_model_output_counts_as_bad_json() -> None:
    """slots 阶段模型吐超深 JSON → 同坏 JSON 计：``{}`` → 槽全败带反馈重问。

    修复前 ``RecursionError`` 逃逸到阶梯兜底 catch——``failures`` 不记录、
    次轮 ``slot_validation_failures`` 反馈字段缺失（钉：次轮 payload 带该字段）。
    """

    class DeepSlots(pl.MockTranslator):
        def __init__(self) -> None:
            super().__init__()
            self.slot_payloads: list[str] = []

        async def translate(
            self,
            *,
            user: str,
            response_format: dict[str, str] | None = None,
            **_kw: object,
        ) -> str:
            if response_format and response_format.get("type") == "json_object":
                self.slot_payloads.append(user)
                return _DEEP_JSON
            return "whatever"  # whole/lines 译文——validator 恒败照样进 slots

    spy = DeepSlots()
    out = run_pipeline(
        [big_para("deep")],
        translator=spy,
        validator=fail_validate,
    )
    assert out[0].status == "fault"
    assert len(spy.slot_payloads) == SLOTS_MAX_ROUNDS  # 单批槽：每轮一次调用
    assert "slot_validation_failures" in spy.slot_payloads[1]
