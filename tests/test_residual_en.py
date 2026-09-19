"""residual_en：段内残英句检测网 + L0 规则 + pipeline 第四拦截（不触网）。"""

from __future__ import annotations

from conftest import mk_chunk, run_pipeline

from texlate.textutil import residual_en_net
from texlate.validate.l0 import Severity, validate_pair
from texlate.xlat import pipeline as pl

_SRC = (
    "Alpha intro sentence. The quick brown fox jumps over the lazy dog "
    "repeatedly near the barn. Tail part ends here."
)
_ZH_ECHO = (
    "甲介绍句。The quick brown fox jumps over the lazy dog repeatedly "
    "near the barn. 尾部到此。"
)


class TestNet:
    def test_verbatim_echo_hit(self) -> None:
        hits = residual_en_net(_SRC, _ZH_ECHO)
        assert len(hits) == 1
        assert "quick brown fox" in hits[0]

    def test_multi_runs_multi_hits(self) -> None:
        zh = (
            "甲。The quick brown fox jumps over the lazy dog repeatedly "
            "near the barn. 乙。The quick brown fox jumps over the lazy "
            "dog repeatedly near the barn. 丙。"
        )
        assert len(residual_en_net(_SRC, zh)) == 2  # noqa: PLR2004

    def test_clean_zh_no_hit(self) -> None:
        zh = "甲介绍句。敏捷棕狐反复跳过谷仓旁的懒狗。尾部到此。"
        assert residual_en_net(_SRC, zh) == []

    def test_inline_term_no_hit(self) -> None:
        assert residual_en_net(_SRC, "这个 Transformer 架构很强。") == []

    def test_short_verbatim_below_est_no_hit(self) -> None:
        # "Tail part ends here" ⊆src 但 est<10、词<8 —— 短残段不判
        zh = "前文很长很长很长很长很长。Tail part ends here. 后文。"
        assert residual_en_net(_SRC, zh) == []

    def test_tier_b_non_src_run_hit(self) -> None:
        zh = "前句。This sentence was never present in the source text at all. 后句。"
        hits = residual_en_net(_SRC, zh)
        assert len(hits) == 1
        assert "never present" in hits[0]

    def test_tier_b_latin_gate(self) -> None:
        # ≥8 词但拉丁字符 <40 —— 短语堆叠不是整句英文
        zh = "前文 a an is it we do go up off 后文"
        assert residual_en_net(_SRC, zh) == []

    def test_tier_b_word_gate(self) -> None:
        # ≥40 拉丁字符但 <8 词 —— 长单词堆叠不是句子
        zh = (
            "前文 supercalifragilisticexpialidocious "
            "antidisestablishmentarianism "
            "pneumonoultramicroscopicsilicovolcanoconiosis 后文"
        )
        assert residual_en_net(_SRC, zh) == []

    def test_name_list_exempt(self) -> None:
        zh = "作者有 John Smith, Jane Doe, Alan Turing 等人。"
        assert residual_en_net(_SRC, zh) == []

    def test_lowercase_name_run_not_exempt(self) -> None:
        # 全小写不满足 ≥70% 首字母大写 —— 人名豁免不成立，按混血长句判
        zh = "作者有 john smith jane doe alan turing bob jones amy lee 等人。"
        assert len(residual_en_net(_SRC, zh)) == 1

    def test_bib_passthrough_no_hit(self) -> None:
        zh = (
            "文献。The quick brown fox jumps over the lazy dog "
            "repeatedly near the barn."
        )
        assert residual_en_net("[[BIB_1]] " + _SRC, zh) == []

    def test_all_english_zh_no_hit(self) -> None:
        # 零 CJK 归 same_source/length 管辖 —— 本网只收「中文里夹英文」
        assert residual_en_net(_SRC, _SRC) == []

    def test_english_comment_masked(self) -> None:
        zh = (
            "正文译文。% The quick brown fox jumps over the lazy dog "
            "repeatedly near the barn"
        )
        assert residual_en_net(_SRC, zh) == []


class TestL0Rule:
    def test_residual_en_error(self) -> None:
        rep = validate_pair(_SRC, _ZH_ECHO)
        hits = [i for i in rep.issues if i.rule == "residual_en"]
        assert len(hits) == 1
        assert hits[0].severity == Severity.ERROR
        assert hits[0].found is not None
        assert "quick brown fox" in hits[0].found
        assert not rep.ok

    def test_clean_pair_no_issue(self) -> None:
        zh = "甲介绍句。敏捷棕狐反复跳过谷仓旁的懒狗。尾部到此。"
        rep = validate_pair(_SRC, zh)
        assert all(i.rule != "residual_en" for i in rep.issues)


class TestIntercept:
    def _result(self, *, status: str = "ok", attempts: int = 1) -> pl.ChunkResult:
        return pl.ChunkResult(
            chunk_id="c",
            source=_SRC,
            translation=_ZH_ECHO,
            kind="para",
            status=status,
            attempts=attempts,
        )

    def test_fault_shape(self) -> None:
        r = self._result()
        pl._intercept_residual_en(r)  # noqa: SLF001
        assert r.status == "fault"
        assert r.translation == r.source
        assert r.error_kind == "validate"
        assert r.warnings == ["residual_en:1"]
        assert "untranslated english" in r.skip_reason
        assert r.fell_back

    def test_partial_also_guarded(self) -> None:
        r = self._result(status="partial")
        pl._intercept_residual_en(r)  # noqa: SLF001
        assert r.status == "fault"
        assert r.translation == r.source

    def test_skipped_untouched(self) -> None:
        r = self._result(status="skipped")
        pl._intercept_residual_en(r)  # noqa: SLF001
        assert r.status == "skipped"
        assert r.translation == _ZH_ECHO

    def test_zero_attempts_no_error_kind(self) -> None:
        # 缓存命中形（attempts=0）不记 validate——没发请求不算非-auth 证据
        r = self._result(attempts=0)
        pl._intercept_residual_en(r)  # noqa: SLF001
        assert r.status == "fault"
        assert r.error_kind == ""

    def test_clean_translation_passes(self) -> None:
        r = pl.ChunkResult(
            chunk_id="c",
            source=_SRC,
            translation="甲介绍句。敏捷棕狐反复跳过谷仓旁的懒狗。尾部到此。",
            kind="para",
            status="ok",
            attempts=1,
        )
        pl._intercept_residual_en(r)  # noqa: SLF001
        assert r.status == "ok"

    def test_interceptable_merge(self) -> None:
        assert pl._interceptable(_SRC, _ZH_ECHO)  # noqa: SLF001
        assert not pl._interceptable(_SRC, "全部中文没有残留。")  # noqa: SLF001


class _HalfEcho:
    """半译应答 fake——任何调用都回同一份「中文夹整句英文」译文。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def translate(self, **kw: object) -> str:
        self.calls.append({"user": str(kw.get("user", ""))})
        return _ZH_ECHO


class TestCache:
    def test_residual_en_translation_not_cached(self) -> None:
        """过 residual_en 网的译文不入段级缓存——防续跑反复命中。"""
        cache: dict[str, str] = {}
        c = mk_chunk(_SRC, "c1")
        out = run_pipeline(
            [c],
            translator=_HalfEcho(),
            cache=cache,
            validator=lambda _s, _z: "",
        )
        assert out[0].status == "fault"
        assert out[0].translation == _SRC
        assert cache == {}

    def test_poisoned_entry_evicted_on_hit(self) -> None:
        """旧版写入侧放行过的残英条目：命中即清 + 落回重翻自愈。"""
        cache: dict[str, str] = {}
        c = mk_chunk(_SRC, "c1")
        pipe = pl.XlatPipeline(translator=pl.MockTranslator(), cache=cache)
        key = pipe._seg_key(c)  # noqa: SLF001
        cache[key] = _ZH_ECHO

        t2 = pl.MockTranslator()
        out = run_pipeline([c], translator=t2, cache=cache, validator=lambda _s, _z: "")
        assert t2.calls  # 毒条目被逐 → 真实重翻
        assert out[0].status == "ok"
        assert cache[key] != _ZH_ECHO

    def test_cache_store_rejects_residual_en(self) -> None:
        """写入侧直测：残英译文拒存，干净译文照常入库。"""
        cache: dict[str, str] = {}
        pipe = pl.XlatPipeline(translator=pl.MockTranslator(), cache=cache)
        c = mk_chunk(_SRC, "c")
        pipe._cache_store(c, _ZH_ECHO)  # noqa: SLF001
        assert cache == {}
        pipe._cache_store(c, "全部中文译文没有残留。")  # noqa: SLF001
        assert len(cache) == 1
