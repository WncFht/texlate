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
#: 干净 zh 对照件——net/L0/intercept 三臂共享同一夹具串。
_CLEAN_ZH = "甲介绍句。敏捷棕狐反复跳过谷仓旁的懒狗。尾部到此。"


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
        assert residual_en_net(_SRC, _CLEAN_ZH) == []

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

    def test_tech_payload_texttt_no_hit(self) -> None:
        # \texttt{} 参数 verbatim 照抄是正确态 —— tech-token 份额 ≥0.5 豁免
        # （e2e_real 探针批 foldseek run 被 Tier-A 误杀实证）
        src = (
            "We ran \\texttt{foldseek easy-search -s 7.5 -{}-alignment-type 1 "
            "-{}-max-seqs 1000} against the database."
        )
        zh = (
            "我们对数据库运行了（\\texttt{foldseek easy-search -s 7.5 "
            "-{}-alignment-type 1 -{}-max-seqs 1000}）。"
        )
        assert residual_en_net(src, zh) == []

    def test_tech_payload_xml_no_hit(self) -> None:
        # <ccs2012> 分类块 verbatim —— 尖括号/数字 token 密集同样豁免
        payload = (
            "<ccs2012><concept><concept_desc>Computer systems "
            "organization~Embedded systems</concept_desc>"
            "<concept_significance>500</concept_significance></concept>"
            "<concept><concept_desc>Networks~Network reliability"
            "</concept_desc><concept_significance>300</concept_significance>"
            "</concept></ccs2012>"
        )
        src = f"Metadata block. {payload} Tail."
        zh = f"元数据块保留：{payload}。"
        assert residual_en_net(src, zh) == []

    def test_tech_payload_brace_chain_no_hit(self) -> None:
        # {rotate, QRcode}（+37）族动作链 —— Tier-B 路径同样被豁免盖住
        zh = (
            "动作链为 {rotate, QRcode}（+37）、{move, playingcard, away}"
            "（+21）、{move, pillbottle, pad}（+22）、{place, shoe}（+26）。"
        )
        assert residual_en_net(_SRC, zh) == []

    def test_tech_payload_cypher_no_hit(self) -> None:
        # Cypher 查询 verbatim —— ()[]: 扩表后括号/冒号 token 计 tech
        q = "{MATCH (j:Ticket ticket ID: 'ENT-22970') -[:HAS_D]->(d)}"
        src = f"The query {q} returns the ticket node."
        zh = f"查询 {q} 返回票据节点。"
        assert residual_en_net(src, zh) == []

    def test_tech_payload_python_def_no_hit(self) -> None:
        # Python 片段 verbatim —— ()[]:= 密集 token 占多数
        code = "def main(): x = float('nan') return int([x]==[x])"
        src = f"Consider the snippet {code} as an example."
        zh = f"以代码片段 {code} 为例。"
        assert residual_en_net(src, zh) == []

    def test_tech_payload_r_pseudo_no_hit(self) -> None:
        # R 伪码更新式 verbatim —— _/<()*/ 符号密集
        expr = "W_i <- (1 - 0.05) * W_i * exp(0.2 * G_i) / Z"
        src = f"The update rule {expr} is applied each step."
        zh = f"每步应用更新式 {expr}。"
        assert residual_en_net(src, zh) == []

    def test_tech_payload_action_vocab_no_hit(self) -> None:
        # {verb obj} 动作词表块 verbatim —— 花括号 token 密集豁免
        vocab = (
            "{grasp single bottle}, {pick up cup}, {place bottle table}, "
            "{push door open}, {move red block}"
        )
        src = f"Available actions: {vocab}."
        zh = f"可用动作：{vocab}。"
        assert residual_en_net(src, zh) == []

    def test_ident_list_verbatim_no_hit(self) -> None:
        # 模块名 CSV 清单照抄是正确态 —— 逗号小写标识符三闸豁免
        mods = "atexit, builtins, concurrent, ctypes, dataclasses, enum"
        src = f"The modules {mods} are used here."
        zh = f"此处使用模块 {mods}。"
        assert residual_en_net(src, zh) == []

    def test_parens_sentence_still_hit(self) -> None:
        # 括号夹带的普通英文句 tech 份额 <0.5 不放 —— 扩表只吃真 payload
        zh = (
            "结果表明 the model (which we trained earlier) achieves strong "
            "results on benchmarks 成立。"
        )
        assert len(residual_en_net(_SRC, zh)) == 1

    def test_ident_list_non_verbatim_hit(self) -> None:
        # 非 src 照抄的小写清单不在豁免面 —— ident_list 只吃 verbatim 路径
        zh = "参数有 alpha, beta, gamma, delta, epsilon, zeta, eta, theta, kappa 等。"
        assert len(residual_en_net(_SRC, zh)) == 1

    def test_comma_prose_verbatim_hit(self) -> None:
        # 逗号散文 verbatim 仍判 —— 逗号密度 ~0.3 过不了密度闸
        # （verify 回归实证：绝对枚数闸会被 however, 类词骗开）
        sent = "However, the method, when applied, often fails on sparse inputs"
        src = f"Introduction text. {sent}. More content follows here."
        zh = f"介绍文。{sent}。后续内容。"
        assert len(residual_en_net(src, zh)) == 1

    def test_embedded_list_sentence_verbatim_hit(self) -> None:
        # 散文夹名表 verbatim 仍判 —— 整 run 逗号密度 5/13<0.5，
        # 豁免只吃纯清单不吃「清单嵌在句子里」
        sent = (
            "Please use modules atexit, builtins, concurrent, ctypes, "
            "dataclasses, enum for this task"
        )
        src = f"Usage note. {sent}."
        zh = f"用法说明。{sent}。"
        assert len(residual_en_net(src, zh)) == 1

    def test_enum_markers_verbatim_hit(self) -> None:
        # 括号枚举 verbatim 仍判 —— (i)/(ii) 是散文编号不算 tech 票
        enum = "(i) gather (ii) normalize (iii) preprocess (iv) evaluate (v) report"
        src = f"The pipeline steps are {enum} in order."
        zh = f"流水线步骤为 {enum} 依次。"
        assert len(residual_en_net(src, zh)) == 1

    def test_enum_markers_tier_b_hit(self) -> None:
        # 非 verbatim 括号枚举同样不放 —— enum marker 不计 tech 后
        # 份额归零走 Tier-B 词数/字符双闸
        zh = (
            "结果如 (i) computing (ii) comparing (iii) reporting (iv) concluding 所示。"
        )
        assert len(residual_en_net(_SRC, zh)) == 1

    def test_linker_name_run_no_hit(self) -> None:
        # de/e/y 连接词计入豁免覆盖 —— 机构名 Tier-B 误杀实证
        zh = "致谢 Ministerio de Ciencia e Innovación y Universidade 资助。"
        assert residual_en_net(_SRC, zh) == []

    def test_accented_name_linker_no_hit(self) -> None:
        # É/Fé 斩词后靠 de 连接词仍够 70% —— EPFL 机构名 verbatim
        src = (
            "The authors are with École Polytechnique Fédérale de Lausanne "
            "(EPFL), Switzerland."
        )
        zh = "作者单位为 École Polytechnique Fédérale de Lausanne (EPFL)。"
        assert residual_en_net(src, zh) == []

    def test_stats_heavy_sentence_still_hit(self) -> None:
        # 数字/符号夹带但未达 0.5 份额的真英文句仍判 —— 豁免只吃 payload
        zh = (
            "结果显示 the p value < 0.05 with n = 1000 samples shows "
            "significant gains overall 成立。"
        )
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
        rep = validate_pair(_SRC, _CLEAN_ZH)
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
            translation=_CLEAN_ZH,
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
