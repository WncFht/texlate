"""export 管线 ``glossary`` 透传：三入参形 → ``XlatPipeline`` → system prompt 术语块。

回归背景：``export_document`` 签名曾无 ``glossary``，epub/docx 两臂建
``XlatPipeline``（今 ``common.drive_pipeline``）时不传——用户传表被静默丢弃。
钉住面：

- ``Glossary``/``dict``/``Path``(yaml|csv|str 形) 入参归一（``coerce_glossary``）；
- 词条经文档级过滤进 ``<Glossary>`` 尾块（``MockTranslator.calls`` 的 system 断言）；
- 路径缺席/格式非法 → ``ExportError``（``Glossary.load`` 对缺席 user_path
  静默跳过，公开入口必须先验存在）；
- CLI ``texlate export --glossary`` 接线（monkeypatch translator 直证 prompt）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from _exportkit import _epub, _write_epub
from docx import Document
from typer.testing import CliRunner

from texlate import cli
from texlate.cli import app
from texlate.export import export_document
from texlate.export.common import ExportError, coerce_glossary
from texlate.export.docx import translate_docx
from texlate.export.epub import translate_epub
from texlate.xlat.glossary import Glossary, TermEntry
from texlate.xlat.pipeline import MockTranslator

if TYPE_CHECKING:
    from pathlib import Path

_RUNNER = CliRunner()

#: 术语必须真实出现在文档正文——``doc_filter`` 按词边界过滤，缺席词不进 prompt。
_BODY = "<p>The transformer architecture relies on attention.</p>"
_TERM_LINE = "- transformer: 变形金刚"
_CH1 = {"ch1.xhtml": _BODY}


def _make_docx(path: Path, paras: list[str]) -> Path:
    doc = Document()
    for text in paras:
        doc.add_paragraph(text)
    doc.save(str(path))
    return path


def _systems(tr: MockTranslator) -> list[str]:
    """``MockTranslator.calls`` 里全部 system prompt。"""
    return [str(c["system"]) for c in tr.calls]


class TestCoerceGlossary:
    def test_none_and_instance_passthrough(self) -> None:
        assert coerce_glossary(None) is None
        g = Glossary(
            terms={"transformer": TermEntry("transformer", "变形金刚", "user")}
        )
        assert coerce_glossary(g) is g

    def test_mapping_becomes_user_layer(self) -> None:
        g = coerce_glossary({"transformer": "变形金刚"})
        assert g is not None
        assert g.terms["transformer"].zh == "变形金刚"
        assert g.terms["transformer"].source == "user"

    def test_mapping_empty_zh_is_identity(self) -> None:
        """空 zh 同文件层语义：保原语。"""
        g = coerce_glossary({"Attention": ""})
        assert g is not None
        assert g.terms["Attention"].zh == "Attention"

    def test_path_yaml_loads_with_default_layer(self, tmp_path: Path) -> None:
        gfile = tmp_path / "g.yaml"
        gfile.write_text("transformer: 变形金刚\n", encoding="utf-8")
        g = coerce_glossary(gfile)
        assert g is not None
        assert g.terms["transformer"].source == "user"
        # Path 形与 tex 主链同构：内建 default.csv 层一并叠入
        assert any(e.source == "default" for e in g.terms.values())

    def test_str_path_accepted(self, tmp_path: Path) -> None:
        gfile = tmp_path / "g.csv"
        gfile.write_text("transformer,变形金刚\n", encoding="utf-8")
        g = coerce_glossary(str(gfile))
        assert g is not None
        assert g.terms["transformer"].zh == "变形金刚"

    def test_missing_path_rejected(self, tmp_path: Path) -> None:
        """路径缺席必须炸——``Glossary.load`` 对缺席 user_path 静默跳过。"""
        with pytest.raises(ExportError, match="glossary"):
            coerce_glossary(tmp_path / "ghost.yaml")

    def test_unsupported_suffix_rejected(self, tmp_path: Path) -> None:
        gfile = tmp_path / "g.txt"
        gfile.write_text("transformer: 变形金刚\n", encoding="utf-8")
        with pytest.raises(ExportError, match="glossary"):
            coerce_glossary(gfile)

    def test_malformed_yaml_rejected(self, tmp_path: Path) -> None:
        gfile = tmp_path / "g.yaml"
        gfile.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(ExportError, match="glossary"):
            coerce_glossary(gfile)


class TestGlossaryReachesPrompt:
    def test_epub_dict_terms_in_system(self, tmp_path: Path) -> None:
        src = _write_epub(tmp_path, _epub(_CH1, ncx=False))
        tr = MockTranslator()
        export_document(
            src, tmp_path / "out.epub", tr, glossary={"transformer": "变形金刚"}
        )
        assert _systems(tr)
        assert all(_TERM_LINE in s for s in _systems(tr))

    def test_epub_path_terms_in_system(self, tmp_path: Path) -> None:
        src = _write_epub(tmp_path, _epub(_CH1, ncx=False))
        gfile = tmp_path / "g.yaml"
        gfile.write_text("transformer: 变形金刚\n", encoding="utf-8")
        tr = MockTranslator()
        export_document(src, tmp_path / "out.epub", tr, glossary=gfile)
        assert any(_TERM_LINE in s for s in _systems(tr))

    def test_epub_glossary_instance(self, tmp_path: Path) -> None:
        src = _write_epub(tmp_path, _epub(_CH1, ncx=False))
        g = Glossary(
            terms={"transformer": TermEntry("transformer", "变形金刚", "user")}
        )
        tr = MockTranslator()
        export_document(src, tmp_path / "out.epub", tr, glossary=g)
        assert any(_TERM_LINE in s for s in _systems(tr))

    def test_epub_placeholder_terms_in_system(self, tmp_path: Path) -> None:
        """spec-xlat#10：export 链占位符恒等注入——``[[IMG_n]]`` marker 进尾块。"""
        src = _write_epub(
            tmp_path,
            _epub({"ch1.xhtml": "<p>Text <img src='i.png'/> tail.</p>"}, ncx=False),
        )
        tr = MockTranslator()
        export_document(src, tmp_path / "out.epub", tr)
        assert _systems(tr)
        assert any("[[IMG_1]]" in s for s in _systems(tr))

    def test_docx_dict_terms_in_system(self, tmp_path: Path) -> None:
        src = _make_docx(
            tmp_path / "in.docx", ["The transformer architecture relies on attention."]
        )
        tr = MockTranslator()
        translate_docx(
            src, tmp_path / "out.docx", tr, glossary={"transformer": "变形金刚"}
        )
        assert any(_TERM_LINE in s for s in _systems(tr))

    def test_term_absent_from_doc_not_in_prompt(self, tmp_path: Path) -> None:
        """文档级过滤：词条未在正文出现 → 不进 system prompt（逐字节恒定）。"""
        src = _write_epub(tmp_path, _epub(_CH1, ncx=False))
        tr = MockTranslator()
        export_document(
            src, tmp_path / "out.epub", tr, glossary={"perceptron": "感知机"}
        )
        assert _systems(tr)
        assert all("perceptron" not in s for s in _systems(tr))

    def test_no_glossary_no_block(self, tmp_path: Path) -> None:
        src = _write_epub(tmp_path, _epub(_CH1, ncx=False))
        tr = MockTranslator()
        translate_epub(src, tmp_path / "out.epub", tr)
        assert _systems(tr)
        assert all("<Glossary>" not in s for s in _systems(tr))

    def test_export_document_bad_path_raises(self, tmp_path: Path) -> None:
        src = _write_epub(tmp_path, _epub(_CH1, ncx=False))
        with pytest.raises(ExportError, match="glossary"):
            export_document(
                src,
                tmp_path / "out.epub",
                MockTranslator(),
                glossary=tmp_path / "ghost.yaml",
            )


class TestCliGlossary:
    def test_glossary_flag_reaches_prompt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--glossary 接线直证：translator 抓在本地，prompt 里查到词条。"""
        src = _write_epub(tmp_path, _epub(_CH1, ncx=False))
        gfile = tmp_path / "g.yaml"
        gfile.write_text("transformer: 变形金刚\n", encoding="utf-8")
        tr = MockTranslator()
        monkeypatch.setattr(
            cli,
            "_export_translator",
            lambda _model, *, mock: tr,  # noqa: ARG005
        )
        result = _RUNNER.invoke(app, ["export", str(src), "--glossary", str(gfile)])
        assert result.exit_code == 0, result.output
        assert any(_TERM_LINE in s for s in _systems(tr))

    def test_missing_glossary_exit_1(self, tmp_path: Path) -> None:
        src = _write_epub(tmp_path, _epub(_CH1, ncx=False))
        result = _RUNNER.invoke(
            app,
            ["export", str(src), "--mock", "--glossary", str(tmp_path / "no.yaml")],
        )
        assert result.exit_code == 1
        assert "export:" in result.stderr
        assert "glossary" in result.stderr
