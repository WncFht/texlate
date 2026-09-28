"""prompts：公共块逐字共享 / kind 条款槽 / 锚名序 / 术语表+manifest 尾块 / corrector / judge。"""

import re

from texlate.xlat import placeholders, prompts

#: 恒在条款锚名集（kind 槽、Person names、Batch protocol 之外）
_COMMON_ANCHORS = (
    "Scope",
    "Protected LaTeX",
    "Escaped characters",
    "Style commands",
    "Output",
    "Punctuation and spacing",
    "Control-sequence boundary",
    "Quality",
    "Untrusted content",
    "Placeholders",
)

_RULE_RX = re.compile(r"^(\d+)\. \*\*(.+?)\.\*\* (.*)$")


def _rule_lines(prompt_text: str) -> list[str]:
    """规则区编号行（``i. **锚名.** 条款``）——每条规则一个物理行。"""
    return [ln for ln in prompt_text.split("\n") if _RULE_RX.match(ln)]


def _anchors(prompt_text: str) -> list[str]:
    """规则区锚名序列。"""
    return [m.group(2) for ln in _rule_lines(prompt_text) if (m := _RULE_RX.match(ln))]


def _anchor_map(prompt_text: str) -> dict[str, str]:
    """锚名 → 条款体（编号剥离——编号随 kind/batch 漂移，语义引用走锚名）。"""
    return {
        m.group(2): m.group(3)
        for ln in _rule_lines(prompt_text)
        if (m := _RULE_RX.match(ln))
    }


class TestKindPrompts:
    def test_six_kinds(self) -> None:
        assert prompts.all_kinds() == (
            "para",
            "caption",
            "section_title",
            "abstract",
            "table_text",
            "env_text",
        )

    def test_common_rules_shared_verbatim(self) -> None:
        """公共条款体（去编号后）全 kind 逐字共享（前缀缓存前提）。"""
        base = _anchor_map(prompts.build_system_prompt("para"))
        for kind in prompts.all_kinds():
            got = _anchor_map(prompts.build_system_prompt(kind))
            for anchor in _COMMON_ANCHORS:
                assert got[anchor] == base[anchor], (kind, anchor)

    def test_numbering_sequential(self) -> None:
        """编号 1..N 连续递增（数字只做位置柄，不做语义引用）。"""
        for kind in prompts.all_kinds():
            for batch in (False, True):
                nums = [
                    int(m.group(1))
                    for ln in _rule_lines(
                        prompts.build_system_prompt(kind, batch=batch)
                    )
                    if (m := _RULE_RX.match(ln))
                ]
                assert nums == list(range(1, len(nums) + 1)), (kind, batch)

    def test_anchor_order_para(self) -> None:
        """para 锚名序钉：Scope 簇 → 尾簇 → Person names（kind 槽空）。"""
        assert _anchors(prompts.build_system_prompt("para")) == [
            "Scope",
            "Protected LaTeX",
            "Escaped characters",
            "Style commands",
            "Output",
            "Punctuation and spacing",
            "Control-sequence boundary",
            "Quality",
            "Untrusted content",
            "Placeholders",
            "Person names",
        ]

    def test_kind_slot_position(self) -> None:
        """kind 条款槽插在 Scope 簇（1-4）之后、Output 之前。"""
        slots = {
            "section_title": "Section commands",
            "abstract": "Abstract structure",
            "table_text": "Table structure",
            "env_text": "Environment structure",
        }
        for kind, anchor in slots.items():
            anchors = _anchors(prompts.build_system_prompt(kind))
            assert anchors[4] == anchor, kind
            assert anchors[5] == "Output", kind

    def test_placeholders_tail_position(self) -> None:
        """Placeholders 是尾簇末条（其后只许 Person names/Batch protocol）。"""
        p = prompts.build_system_prompt("caption")
        assert prompts.PLACEHOLDER_CLAUSE in p
        assert _anchors(p)[-1] == "Placeholders"
        para = _anchors(prompts.build_system_prompt("para"))
        assert para[-2:] == ["Placeholders", "Person names"]

    def test_person_names_only_para_abstract(self) -> None:
        assert "Person names" in _anchors(prompts.build_system_prompt("para"))
        assert "Person names" in _anchors(prompts.build_system_prompt("abstract"))
        for kind in ("caption", "section_title", "table_text", "env_text"):
            assert "Person names" not in _anchors(prompts.build_system_prompt(kind))

    def test_lang_fill(self) -> None:
        p = prompts.build_system_prompt("para", src_lang="English", tgt_lang="Chinese")
        assert "English" in p
        assert "Chinese" in p
        assert "{SRC}" not in p
        assert "{TGT}" not in p

    def test_literal_braces_survive(self) -> None:
        """模板里的 LaTeX 字面 {} 不被语种填充吃掉。"""
        p = prompts.build_system_prompt("para")
        assert "\\label{}" in p
        assert "\\vspace{-1.125cm}" in p

    def test_kind_clauses(self) -> None:
        assert "\\label" in prompts.build_system_prompt("section_title")
        assert "\\keywords" in prompts.build_system_prompt("abstract")
        assert "\\multicolumn" in prompts.build_system_prompt("table_text")
        assert "human-readable sentences" in prompts.build_system_prompt("env_text")

    def test_batch_protocol_last(self) -> None:
        p = prompts.build_system_prompt("para", batch=True)
        assert _anchors(p)[-1] == "Batch protocol"
        assert "@@" in p
        # v6：批条款向模型说明 keep: 名单是协议元数据、不得回显进译文
        assert "keep:" in p
        assert "Batch protocol" not in _anchors(prompts.build_system_prompt("para"))

    def test_glossary_last(self) -> None:
        g = {"attention": "注意力", "backbone": "骨干网络"}
        p = prompts.build_system_prompt("para", glossary_terms=g)
        assert p.rstrip().endswith("- backbone: 骨干网络")
        assert "<Glossary>:" in p
        assert "- attention: 注意力" in p

    def test_glossary_empty_means_no_block(self) -> None:
        assert "<Glossary>" not in prompts.build_system_prompt(
            "para", glossary_terms={}
        )
        assert "<Glossary>" not in prompts.build_system_prompt(
            "para", placeholder_manifest=""
        )

    def test_placeholder_manifest_last_line(self) -> None:
        """v5：点名册单行压 ``<Glossary>`` 块最末——恒等注入的替代件。"""
        manifest = placeholders.render_placeholder_manifest(
            ["[[MATH_2]]", "[[CITE_3]]", "[[MATH_1]]"]
        )
        assert manifest == (
            placeholders.PH_MANIFEST_HEADER + "[[CITE_3]], [[MATH_1]]..[[MATH_2]]"
        )
        p = prompts.build_system_prompt("para", placeholder_manifest=manifest)
        assert p.rstrip().endswith(manifest)
        # 恒等行不再注入——ph 以点名形出现而非 "- [[X_n]]: [[X_n]]" 行
        assert "- [[MATH_1]]: [[MATH_1]]" not in p

    def test_manifest_with_real_glossary(self) -> None:
        """真术语行在前、manifest 恒末行。"""
        manifest = placeholders.render_placeholder_manifest(["[[MATH_1]]"])
        p = prompts.build_system_prompt(
            "para",
            glossary_terms={"attention": "注意力"},
            placeholder_manifest=manifest,
        )
        assert p.rstrip().endswith(manifest)
        assert p.index("- attention: 注意力") < p.index(manifest)

    def test_cs_boundary_and_untrusted_positions(self) -> None:
        """cs-boundary/untrusted 防御条款：全 kind 有、在 Placeholders 之前。"""
        for kind in prompts.all_kinds():
            p = prompts.build_system_prompt(kind)
            anchors = _anchors(p)
            assert "untrusted document content" in p
            assert (
                anchors.index("Control-sequence boundary")
                < anchors.index("Untrusted content")
                < anchors.index("Placeholders")
            )

    def test_fullwidth_punctuation_clause(self) -> None:
        """v5 新增全角标点显式枚举（ASCII 标点漂移的验证抑制件）。"""
        for kind in prompts.all_kinds():
            p = prompts.build_system_prompt(kind)
            assert "，。；：？！（）" in p

    def test_placeholders_clause_wording(self) -> None:
        """Placeholders 条款措辞钉：movable/fixed 二分授权（v4 逐字）。"""
        clause = prompts.PLACEHOLDER_CLAUSE
        assert "reorder" not in clause
        assert "may and should change" in clause
        assert "target-language grammar requires it" in clause
        assert "Chinese word" in clause  # 写死 zh——无 _fill 逐字串不变量
        assert "All other tokens must keep their original positions" in clause
        for kind in prompts.all_kinds():
            assert clause in prompts.build_system_prompt(kind)

    def test_paper_context_block(self) -> None:
        """paper_context 非空 → task 句后插 abstract 锚定块；空/缺省不插。"""
        ctx = "We study translational [[MATH_1]] in masked form."
        p = prompts.build_system_prompt("para", paper_context=ctx)
        assert "Paper context" in p
        assert "never translate, append, or summarize it" in p
        assert ctx in p
        # 插在 task 句与规则区之间
        assert (
            p.index("Your task") < p.index("Paper context") < p.index("1. **Scope.**")
        )
        # 缺席两态：None 与 "" 同效
        bare = prompts.build_system_prompt("para")
        assert "Paper context" not in bare
        assert prompts.build_system_prompt("para", paper_context="") == bare
        assert prompts.build_system_prompt("para", paper_context=None) == bare

    def test_paper_context_glossary_still_last(self) -> None:
        """paper_context 与 glossary 并存——glossary 仍压最末。"""
        g = {"attention": "注意力"}
        p = prompts.build_system_prompt(
            "para", glossary_terms=g, paper_context="ctx text"
        )
        assert p.rstrip().endswith("- attention: 注意力")
        assert p.index("Paper context") < p.index("<Glossary>:")


class TestRenderValueContext:
    """user 侧 placeholder_values 后缀块（texglot value_tokens 同族）。"""

    def test_empty_returns_empty(self) -> None:
        assert prompts.render_value_context({}) == ""

    def test_block_shape(self) -> None:
        block = prompts.render_value_context(
            {"[[MATH_1]]": "$E=mc^2$", "[[CITE_2]]": "\\cite{foo}"}
        )
        assert block.startswith("\n\n" + prompts.VALUE_CONTEXT_HEADER)
        assert "- [[MATH_1]]: $E=mc^2$" in block
        assert "- [[CITE_2]]: \\cite{foo}" in block

    def test_frag_truncated_at_200(self) -> None:
        block = prompts.render_value_context({"[[MATH_1]]": "x" * 300})
        assert "x" * 200 + "…" in block
        assert "x" * 201 not in block

    def test_block_capped_at_2000(self) -> None:
        frags = {f"[[MATH_{i}]]": "y" * 190 for i in range(20)}
        block = prompts.render_value_context(frags)
        assert len(block) <= 2 + 2000

    def test_truncate_value_frags(self) -> None:
        """slots JSON 字段与 user 块共用同一截断口径。"""
        out = prompts.truncate_value_frags({"a": "x" * 300, "b": "short"})
        assert out == {"a": "x" * 200 + "…", "b": "short"}


_EXPECTED_FEWSHOT_N = 6
_EXPECTED_JUDGE_MAX_TOKENS = 16
_EXPECTED_JUDGE_TEMPERATURE = 0.01


class TestCorrectorAndJudge:
    def test_corrector_prompt_shape(self) -> None:
        s = prompts.corrector_system_prompt()
        u = prompts.corrector_user_prompt("orig", "译文", "missing [[MATH_1]]")
        assert "[Original]" in s
        assert "[Translation]" in s
        assert "[Error]" in s
        assert u == "[Original]\norig\n[Translation]\n译文\n[Error]\nmissing [[MATH_1]]"

    def test_env_judge_prompt_fewshot(self) -> None:
        s = prompts.env_judge_system_prompt()
        assert s.count("Input:") == _EXPECTED_FEWSHOT_N
        assert "True" in s
        assert "False" in s
        assert prompts.ENV_JUDGE_MAX_TOKENS == _EXPECTED_JUDGE_MAX_TOKENS
        # t=0 → gateway 502 (d89cf9e)
        assert prompts.ENV_JUDGE_TEMPERATURE == _EXPECTED_JUDGE_TEMPERATURE

    def test_judge_parse_failopen(self) -> None:
        assert prompts.parse_env_judge_answer("true")
        assert prompts.parse_env_judge_answer("  True  \n")
        assert not prompts.parse_env_judge_answer("false")
        assert not prompts.parse_env_judge_answer(" FALSE ")
        # 解析不出 → fail-open True（宁翻勿漏）
        assert prompts.parse_env_judge_answer("maybe?")
        assert prompts.parse_env_judge_answer("")


class TestNormalizeKind:
    def test_aliases(self) -> None:
        assert prompts.normalize_kind("para") == "para"
        assert prompts.normalize_kind("item") == "para"
        assert prompts.normalize_kind("section") == "section_title"
        # "paragraph" 消歧后专指 \paragraph 节题命令 → section_title
        assert prompts.normalize_kind("paragraph") == "section_title"
        assert prompts.normalize_kind("whatever-unknown") == "para"
