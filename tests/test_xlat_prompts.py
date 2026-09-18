"""prompts：公共块逐字共享 / kind 条款 / C9-C10 压轴 / 术语表尾块 / corrector / judge。"""

from texlate.xlat import prompts


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

    def test_common_block_shared_verbatim(self) -> None:
        """C1..C8 公共块在全部 kind 间逐字共享（前缀缓存前提）。"""
        p1 = prompts.build_system_prompt("para")
        p2 = prompts.build_system_prompt("caption")
        # 公共块 = C1 行到 C8 行尾
        c1 = p1.index("C1.")
        c8_end = p1.index("no comments.") + len("no comments.")
        common1 = p1[c1:c8_end]
        assert common1 in p2
        for kind in prompts.all_kinds():
            assert common1 in prompts.build_system_prompt(kind)

    def test_c9_tail_position(self) -> None:
        """C9 是条款列表末位（其后只允许 C10/术语表）。"""
        p = prompts.build_system_prompt("caption")
        assert prompts.PLACEHOLDER_CLAUSE in p
        tail = p[p.index("C9.") :]
        assert "C1." not in tail
        assert "C8." not in tail

    def test_c10_only_para_abstract(self) -> None:
        assert "C10." in prompts.build_system_prompt("para")
        assert "C10." in prompts.build_system_prompt("abstract")
        for kind in ("caption", "section_title", "table_text", "env_text"):
            assert "C10." not in prompts.build_system_prompt(kind)

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

    def test_batch_clause(self) -> None:
        p = prompts.build_system_prompt("para", batch=True)
        assert "B1." in p
        assert "@@" in p
        assert "B1." not in prompts.build_system_prompt("para")

    def test_glossary_last(self) -> None:
        g = {"attention": "注意力", "[[MATH_1]]": "[[MATH_1]]"}
        p = prompts.build_system_prompt("para", glossary_terms=g)
        assert p.rstrip().endswith("- [[MATH_1]]: [[MATH_1]]")
        assert "<Glossary>:" in p
        assert "- attention: 注意力" in p

    def test_glossary_empty_means_no_block(self) -> None:
        assert "<Glossary>" not in prompts.build_system_prompt(
            "para", glossary_terms={}
        )

    def test_fusion_clause_all_kinds_before_c9(self) -> None:
        """C8a 反熔合条款（B4a 跨模型通病防御）：全 kind 有、在 C9 之前。"""
        for kind in prompts.all_kinds():
            p = prompts.build_system_prompt(kind)
            assert "C8a." in p
            assert p.index("C8a.") < p.index("C9.")

    def test_untrusted_clause_all_kinds(self) -> None:
        """C8b untrusted 条款：全 kind 有、在 C8a 之后 C9 之前。"""
        for kind in prompts.all_kinds():
            p = prompts.build_system_prompt(kind)
            assert "C8b." in p
            assert "untrusted document content" in p
            assert p.index("C8a.") < p.index("C8b.") < p.index("C9.")

    def test_c9_movable_license(self) -> None:
        """C9 v4 改写：删 reorder 禁令 + movable/fixed 二分授权句。"""
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
        # 插在 task 句与 C1 公共块之间
        assert p.index("Your task") < p.index("Paper context") < p.index("C1.")
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
