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
