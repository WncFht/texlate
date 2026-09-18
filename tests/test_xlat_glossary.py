"""glossary：三级合并优先级 / ph 恒等注入 / 文档级过滤 / yaml 装载归一。"""

from pathlib import Path

import pytest

from texlate.xlat import glossary as gl


@pytest.fixture
def terms_dir(tmp_path: Path) -> Path:
    d = tmp_path / "terms"
    d.mkdir()
    (d / "default.csv").write_text(
        "attention,注意力\nAGI,AGI\nmodel,模型\n", encoding="utf-8"
    )
    (d / "cs.LG.csv").write_text("model,模型(LG)\nloss,损失\n", encoding="utf-8")
    (d / "cs.CV.csv").write_text("model,模型(CV)\nfeature,特征\n", encoding="utf-8")
    (d / "index.yaml").write_text(
        "cs.LG: cs.LG.csv\ncs.CV: cs.CV.csv\n", encoding="utf-8"
    )
    return d


class TestTieredMerge:
    def test_default_fallback(self, terms_dir: Path) -> None:
        g = gl.Glossary.load(terms_dir=terms_dir, user_path=Path("/nonexistent"))
        assert g.terms["attention"].zh == "注意力"
        assert g.terms["AGI"].zh == "AGI"  # 保原语条目

    def test_category_union_first_hit_wins(self, terms_dir: Path) -> None:
        g = gl.Glossary.load(
            terms_dir=terms_dir,
            categories=["cs.LG", "cs.CV"],
            user_path=Path("/nonexistent"),
        )
        assert g.terms["loss"].zh == "损失"
        assert g.terms["feature"].zh == "特征"
        # 同 term 双 category 命中：声明序先写者胜
        assert g.terms["model"].zh == "模型(LG)"

    def test_user_overrides_category(self, terms_dir: Path, tmp_path: Path) -> None:
        user = tmp_path / "glossary.yaml"
        user.write_text("model: 用户模型\n", encoding="utf-8")
        g = gl.Glossary.load(terms_dir=terms_dir, categories=["cs.LG"], user_path=user)
        assert g.terms["model"].zh == "用户模型"

    def test_local_between_user_and_category(
        self, terms_dir: Path, tmp_path: Path
    ) -> None:
        local = tmp_path / "glossary.local.yaml"
        local.write_text("model: 本地模型\nloss: 本地损失\n", encoding="utf-8")
        g = gl.Glossary.load(
            terms_dir=terms_dir,
            categories=["cs.LG"],
            user_path=Path("/nonexistent"),
            local_path=local,
        )
        assert g.terms["model"].zh == "本地模型"
        assert g.terms["loss"].zh == "本地损失"

    def test_csv_single_column_is_identity(self, tmp_path: Path) -> None:
        f = tmp_path / "t.csv"
        f.write_text("Transformer\n", encoding="utf-8")
        assert gl.load_table(f) == {"Transformer": "Transformer"}


class TestPlaceholderIdentity:
    def test_ph_injected_lowest_priority(self, terms_dir: Path) -> None:
        g = gl.Glossary.load(
            terms_dir=terms_dir,
            user_path=Path("/nonexistent"),
            placeholders=["[[MATH_2]]", "[[MATH_10]]", "[[SL]]"],
        )
        assert g.terms["[[MATH_2]]"].zh == "[[MATH_2]]"
        assert g.terms["[[MATH_2]]"].source == "placeholder"
        # 排序键在 doc_filter 里体现

    def test_ph_never_overrides_real_term(
        self, terms_dir: Path, tmp_path: Path
    ) -> None:
        user = tmp_path / "u.yaml"
        user.write_text('"[[MATH_1]]": 占位一号\n', encoding="utf-8")
        g = gl.Glossary.load(
            terms_dir=terms_dir, user_path=user, placeholders=["[[MATH_1]]"]
        )
        assert g.terms["[[MATH_1]]"].zh == "占位一号"
        assert g.terms["[[MATH_1]]"].source == "user"


class TestDocFilter:
    def test_filters_to_doc_occurrence(self, terms_dir: Path) -> None:
        g = gl.Glossary.load(terms_dir=terms_dir, user_path=Path("/nonexistent"))
        out = g.doc_filter(["we use attention here", "no match text"])
        assert "attention" in out
        assert "model" not in out  # 未出现则不入表

    def test_boundary_respects_word_chars(self, terms_dir: Path) -> None:
        g = gl.Glossary.load(terms_dir=terms_dir, user_path=Path("/nonexistent"))
        out = g.doc_filter(["the models are great"])  # "models" 不命中 "model"
        assert "model" not in out

    def test_case_insensitive(self, terms_dir: Path) -> None:
        g = gl.Glossary.load(terms_dir=terms_dir, user_path=Path("/nonexistent"))
        out = g.doc_filter(["ATTENTION is all you need"])
        assert "attention" in out

    def test_placeholders_always_included_sorted(self, terms_dir: Path) -> None:
        g = gl.Glossary.load(
            terms_dir=terms_dir,
            user_path=Path("/nonexistent"),
            placeholders=["[[MATH_10]]", "[[CITE_1]]", "[[MATH_2]]"],
        )
        out = g.doc_filter(["irrelevant text"])
        keys = list(out)
        # 占位符按 sort_key 排在真术语后；本文真术语全不命中
        assert keys == ["[[CITE_1]]", "[[MATH_2]]", "[[MATH_10]]"]


class TestDocFilterWsFlex:
    """E24 qual:glossary-ws-flex——多词术语词内空白/``~`` 折缝化匹配。"""

    @pytest.fixture
    def g(self, tmp_path: Path) -> gl.Glossary:
        d = tmp_path / "terms"
        d.mkdir()
        (d / "default.csv").write_text(
            "computer vision,计算机视觉\nMaximum Likelihood,最大似然\n"
            "domain adaptation,域适应\nsingle,单词\n",
            encoding="utf-8",
        )
        return gl.Glossary.load(terms_dir=d, user_path=Path("/nonexistent"))

    def test_tilde_joined(self, g: gl.Glossary) -> None:
        assert "computer vision" in g.doc_filter(["we use computer~vision here"])

    def test_newline_broken(self, g: gl.Glossary) -> None:
        assert "Maximum Likelihood" in g.doc_filter(["the Maximum\nLikelihood est"])

    def test_multi_space_and_tab(self, g: gl.Glossary) -> None:
        assert "domain adaptation" in g.doc_filter(["domain  adaptation"])
        assert "domain adaptation" in g.doc_filter(["domain\tadaptation"])

    def test_normal_form_still_hits(self, g: gl.Glossary) -> None:
        assert "computer vision" in g.doc_filter(["computer vision works"])

    def test_boundary_still_enforced(self, g: gl.Glossary) -> None:
        # 折缝化只松词内空隙——词边界 lookaround 不动：singles 不命中 single
        assert "single" not in g.doc_filter(["the singles club"])
        # 缝跨不进字母：computerXvision 不命中
        assert "computer vision" not in g.doc_filter(["computerXvision"])

    def test_term_with_literal_tilde_splits_clean(self, tmp_path: Path) -> None:
        d = tmp_path / "terms"
        d.mkdir()
        (d / "default.csv").write_text("a~b,甲乙\n", encoding="utf-8")
        g = gl.Glossary.load(terms_dir=d, user_path=Path("/nonexistent"))
        assert "a~b" in g.doc_filter(["x a b y"])
        assert "a~b" in g.doc_filter(["x a~b y"])


class TestLoadIndex:
    def test_comma_string_and_list_forms(self, tmp_path: Path) -> None:
        p = tmp_path / "index.yaml"
        p.write_text(
            "cs.LG: lg.csv, ml.csv\ncs.CV: [cv.csv, extra.csv]\n", encoding="utf-8"
        )
        assert gl.load_index(p) == {
            "cs.LG": ["lg.csv", "ml.csv"],
            "cs.CV": ["cv.csv", "extra.csv"],
        }

    def test_missing_file_empty(self, tmp_path: Path) -> None:
        assert gl.load_index(tmp_path / "none.yaml") == {}

    def test_reject_non_string_list_value(self, tmp_path: Path) -> None:
        p = tmp_path / "index.yaml"
        p.write_text("cs.LG:\n  a: 1\n", encoding="utf-8")
        with pytest.raises(TypeError, match="string or list"):
            gl.load_index(p)


class TestLoadYaml:
    def test_flat_map(self, tmp_path: Path) -> None:
        p = tmp_path / "g.yaml"
        p.write_text("a: 1\nb: 2\n# comment\nc: 三\n", encoding="utf-8")
        assert gl.load_yaml(p) == {"a": "1", "b": "2", "c": "三"}

    def test_nested_map(self, tmp_path: Path) -> None:
        p = tmp_path / "g.yaml"
        p.write_text("term:\n  target: 译\n  context: ctx\n", encoding="utf-8")
        assert gl.load_yaml(p) == {"term": "译"}

    def test_flatten_structured(self) -> None:
        out = gl.flatten_terms(
            {"a": "1", "b": {"target": "2", "context": "x"}}, name="t"
        )
        assert out == {"a": "1", "b": "2"}

    def test_reject_top_level_list(self, tmp_path: Path) -> None:
        p = tmp_path / "g.yaml"
        p.write_text("- list item\n", encoding="utf-8")
        with pytest.raises(TypeError, match="must be a mapping"):
            gl.load_yaml(p)

    def test_reject_list_value(self, tmp_path: Path) -> None:
        p = tmp_path / "g.yaml"
        p.write_text("term:\n  - a\n  - b\n", encoding="utf-8")
        with pytest.raises(TypeError, match="list value"):
            gl.load_yaml(p)

    def test_inline_comment(self, tmp_path: Path) -> None:
        p = tmp_path / "g.yaml"
        p.write_text("a: b # note\n", encoding="utf-8")
        assert gl.load_yaml(p) == {"a": "b"}


class TestLoadCsv:
    def test_bom_csv(self, tmp_path: Path) -> None:
        """utf-8-sig：Excel 导出的 BOM 文件首行 en 不黏 U+FEFF（曾静默查无此词）。"""
        f = tmp_path / "g.csv"
        f.write_text("attention,注意力\nmodel,模型\n", encoding="utf-8-sig")
        assert gl.load_csv(f) == {"attention": "注意力", "model": "模型"}
