"""leftover_ph 升格拦截：zh 残留 splice 不可解析 token → fault + 回退原文。

sabotage 基线实测：幻觉 ``[[MATH_966]]`` 穿透校验字面进 1012.5411 产物——
warning 时代只观测不拦截。升格后命中即 fallback_orig 同形
（``fault`` + ``skipped`` + ``translation=source``）：不进 splice、续跑
重试、落库 failed → 论文级 partial 而非静默 ok。判定 = zh token ∉ src
占位符集合（splice 按 ph_map 成员解析）：src 字面 ``[[..]]`` 回显、同
token 多次引用、zh 注释回显 src 注释 token 均不误伤。
"""

import asyncio
from pathlib import Path

from conftest import big_para, mk_chunk, pass_validate, run_pipeline

from texlate.latex import parse_tex, reconstruct
from texlate.xlat import pipeline as pl
from texlate.xlat.placeholders import ANY_PH_RX
from texlate.xlat.state import ChunkRecord, StateStore

#: 公共散文负载（历史：凑过 SHORT_CHAR_LIMIT=300 单翻路径闸——闸已随
#: 73ffa4c0 拆除，今仅作批量/单翻路径的定型填充）。
_PROSE = "Long prose " + "x" * 400


class _Hallucinator(pl.MockTranslator):
    """应答尾部臆造源外 ``[[MATH_99]]``——B7/sabotage 穿透形态复现。

    ``marker`` 给了就只污染含该字样的输入（净块对照用）；批量应答逐行污染。
    """

    def __init__(self, marker: str | None = None) -> None:
        """``marker``：只污染 ``user`` 含此字样的调用；None = 全污染。"""
        super().__init__()
        self.marker = marker

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """mock 译文 + 尾部 ``[[MATH_99]]``（批量形态逐成员行尾追加）。"""
        raw = await super().translate(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        if self.marker is not None and self.marker not in user:
            return raw
        if user.startswith("[1]"):  # 批量应答：逐成员行尾污染
            return "\n".join(f"{ln} [[MATH_99]]" for ln in raw.split("\n"))
        return f"{raw} [[MATH_99]]"


class TestIntercept:
    """命中即 fault + skipped + 回退原文——残留 ``[[X_n]]`` 绝不进 splice。"""

    def test_leftover_chunk_faults_and_falls_back(self) -> None:
        """单翻路径：幻觉 token → fault，translation=源文，warning 仍落库。"""
        src = _PROSE
        out = run_pipeline(
            [big_para("c1")], translator=_Hallucinator(), validator=pass_validate
        )
        r = out[0]
        assert r.status == "fault"
        assert r.fell_back
        assert r.translation == src
        assert r.error_kind == "validate"
        assert "[[MATH_99]]" in r.skip_reason
        assert "placeholder" in r.skip_reason  # → 落库 placeholder_mismatch
        assert "leftover_ph:1" in r.warnings

    def test_batch_member_leftover_faults(self) -> None:
        """批量路径同受拦截——member 级残留不随批成功蒙混。"""
        chunks = [mk_chunk("A", "a"), mk_chunk("B", "b")]
        out = run_pipeline(chunks, translator=_Hallucinator(), validator=pass_validate)
        assert all(r.batched for r in out)
        assert all(r.status == "fault" and r.fell_back for r in out)
        assert all(r.translation == r.source for r in out)

    def test_split_parent_faults_on_piece_leftover(self) -> None:
        """切分块任一片段带残留 → 父块整体回退原文（保守口径）。"""
        cfg = pl.PipelineConfig(hard_limit=80)
        big = "Sentence one here. " * 20
        out = run_pipeline(
            [mk_chunk(big, "big")],
            translator=_Hallucinator(),
            config=cfg,
            validator=pass_validate,
        )
        assert out[0].status == "fault"
        assert out[0].fell_back
        assert out[0].translation == big

    def test_mixed_run_only_dirty_chunk_faults(self) -> None:
        """论文级降格粒度：脏块 fault、净块 ok——不拖全篇。"""
        chunks = [
            big_para("dirty", prefix="dirty-marker prose "),
            # 异 kind 分 request——同批则 marker 命中批载荷，净块译文同被污染
            mk_chunk("clean prose " + "y" * 400, "clean", kind="caption"),
        ]
        out = run_pipeline(
            chunks,
            translator=_Hallucinator(marker="dirty-marker"),
            validator=pass_validate,
        )
        by_id = {r.chunk_id: r for r in out}
        assert by_id["dirty"].status == "fault"
        assert by_id["clean"].status == "ok"


class TestNoFalsePositive:
    """合法 ``[[..]]`` 形态不误伤——判定只看 splice 可解析性。"""

    def test_literal_double_bracket_echo_ok(self) -> None:
        """src 字面 ``[[NOTE]]`` 被 zh 原样回显——在 src 集内，不拦。"""
        out = run_pipeline(
            [big_para("c1", tail=" see [[NOTE]] marker")],
            translator=pl.MockTranslator(),
            validator=pass_validate,
        )
        assert out[0].status == "ok"
        assert "[[NOTE]]" in out[0].translation
        assert not any(w.startswith("leftover_ph") for w in out[0].warnings)

    def test_src_token_duplicated_in_zh_ok(self) -> None:
        """zh 重复引用同一 src token——splice 照常展开两处，不算残留。"""

        class Duplicator(pl.MockTranslator):
            async def translate(self, *, user: str, **kw: object) -> str:
                raw = await super().translate(user=user, **kw)
                return f"{raw} [[MATH_1]]"

        out = run_pipeline(
            [big_para("c1", tail=" [[MATH_1]]")],
            translator=Duplicator(),
            validator=pass_validate,
        )
        assert out[0].status == "ok"  # 集合差为空——同 token 重复引用不冤杀
        assert out[0].translation.count("[[MATH_1]]") == 2  # noqa: PLR2004

    def test_zh_comment_echoing_src_comment_token_ok(self) -> None:
        """zh 注释回显 src 注释内 token（755487c 豁免口径）——净差零不拦。"""
        out = run_pipeline(
            [big_para("c1", tail=" % TODO check [[MATH_3]]")],
            translator=pl.MockTranslator(),
            validator=pass_validate,
        )
        assert out[0].status == "ok"
        assert not any(w.startswith("leftover_ph") for w in out[0].warnings)

    def test_zh_comment_fabricated_token_faults(self) -> None:
        """zh 注释内臆造 src 没有的 token（1012.5411 逃逸形态）——照拦。"""

        class CommentHallucinator(pl.MockTranslator):
            async def translate(self, *, user: str, **kw: object) -> str:
                raw = await super().translate(user=user, **kw)
                return f"{raw}\n% 备注 [[MATH_966]]"

        src = _PROSE + " [[MATH_1]]"
        out = run_pipeline(
            [big_para("c1", tail=" [[MATH_1]]")],
            translator=CommentHallucinator(),
            validator=pass_validate,
        )
        assert out[0].status == "fault"
        assert out[0].translation == src


class TestCacheAndResume:
    """缓存/续跑两路存量污染的拦截与自愈。"""

    def test_poisoned_cache_hit_evicted_and_retranslated(self) -> None:
        """脏缓存命中（宽松校验时代写入）→ 命中即清 + 落回重翻自愈（曾永远 fault 冻结）。"""
        c = big_para("c1")
        cache: dict[str, str] = {}
        t = pl.MockTranslator()
        pipe = pl.XlatPipeline(t, cache=cache)
        key = pipe._seg_key(c)  # noqa: SLF001 -- 造毒须触键
        cache[key] = "这是译文 [[MATH_99]]"
        out = asyncio.run(pipe.run([c]))
        r = out[0]
        assert r.status == "ok"  # 毒条目被清 → 真重翻 → 痊愈
        assert t.calls
        assert "[[MATH_99]]" not in cache[key]  # 同键已被干净译文改写

    def test_leftover_zh_not_cached_self_heals(self) -> None:
        """毒译文不落缓存——续跑换新 translator 能重翻出 ok，而非永久 fault。"""
        cache: dict[str, str] = {}
        chunks = [big_para("c1")]
        out = run_pipeline(
            chunks, translator=_Hallucinator(), cache=cache, validator=pass_validate
        )
        assert out[0].status == "fault"
        assert cache == {}  # 拦截臂前置到写缓存——污染源不进

        out2 = run_pipeline(chunks, translator=pl.MockTranslator(), cache=cache)
        assert out2[0].status == "ok"
        assert "[[MATH_99]]" not in out2[0].translation

    def test_resume_stale_ok_record_retranslates(self, tmp_path: Path) -> None:
        """warning 时代落盘的 ok 残留记录 → 续跑降 fault 重翻，不再 splice 字面。"""
        outdir = tmp_path / "out"
        src = _PROSE
        store = StateStore(outdir)
        store.start(1)
        store.record(
            ChunkRecord(
                chunk_id="c1",
                source=src,
                translation="这是译文 [[MATH_99]]",
                status="ok",
            )
        )
        store.finish()

        t = pl.MockTranslator()
        out = run_pipeline(
            [big_para("c1")], translator=t, state=StateStore(outdir)
        )
        assert t.calls  # 旧记录被拦截踢出 completed——真重翻发生
        assert out[0].status == "ok"
        assert "[[MATH_99]]" not in out[0].translation


class TestDownstreamContract:
    """拦截结果与 splice / L2 回灌 / auth 闸的契约面。"""

    def test_splice_never_sees_polluted_zh(self) -> None:
        """真 splice 验证：fault 块不进 trans → reconstruct 回原文、零字面残留。"""
        doc = (
            "\\documentclass{article}\n\\begin{document}\n"
            "First paragraph with some english text for translation.\n\n"
            "Second paragraph also has english prose content here.\n"
            "\\end{document}\n"
        )
        res = parse_tex(doc)
        assert len(res.chunks) >= 2  # noqa: PLR2004 -- 合成文档至少两块
        chunks = [
            pl.chunk_to_in(c, chunk_id=str(c.id), ph_map=res.ph_map) for c in res.chunks
        ]
        out = run_pipeline(chunks, translator=_Hallucinator(), validator=pass_validate)
        assert any(r.status == "fault" for r in out)

        # e2e 口径：仅 status==ok 进 trans dict，其余 reconstruct 回源文
        trans = {int(r.chunk_id): r.translation for r in out if r.status == "ok"}
        spliced = reconstruct(res, trans)
        assert "[[MATH_99]]" not in spliced
        assert not ANY_PH_RX.search(spliced)

    def test_retranslate_leftover_falls_back(self) -> None:
        """L2 回灌同受拦截——重译产物带残留 → fault，调用方回落原文。"""
        pipe = pl.XlatPipeline(translator=_Hallucinator(), validator=pass_validate)
        c = big_para("c1")
        r = asyncio.run(pipe.retranslate_chunk(c, "compile error here"))
        assert r is not None
        assert r.status == "fault"
        assert r.fell_back
        assert r.translation == c.content
        assert r.error_kind == "validate"

    def test_intercepted_chunk_is_non_auth_outcome(self) -> None:
        """真发过请求的拦截块计 non_auth——与正常非-auth 结果同口径。"""
        pipe = pl.XlatPipeline(translator=_Hallucinator(), validator=pass_validate)
        out = asyncio.run(pipe.run([big_para("c1")]))
        assert out[0].error_kind == "validate"
        assert pipe.auth_gate.non_auth == 1
        assert not pipe.auth_gate.tripped
