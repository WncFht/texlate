r"""``export.docx`` 双语插译测试——python-docx 现造最小 docx，不碰真文档/真网关。

覆盖：deepcopy ``w:p`` + ``addnext`` 插译、``pPr`` 样式继承、译文 run 的
``w:eastAsia``/颜色戳、echo 不重复插、脚注 part（plain ``Part`` → ``blob``
解析 → ``_blob`` 写回）、``sniff_format``/``export_document`` 分派、
``w:sectPr`` 不连坐克隆、hyperlink/域代码/隐藏 run/表格/页眉遍历面。
"""

from __future__ import annotations

import re
import zipfile
from typing import TYPE_CHECKING

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.oxml.parser import parse_xml
from lxml import etree

from texlate.export import export_document, sniff_format
from texlate.export.common import UnsupportedFormatError
from texlate.export.docx import iter_units, translate_docx
from texlate.xlat.pipeline import MockTranslator

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

FOOTNOTES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>
  <w:footnote w:id="1"><w:p><w:r><w:t>Footnote body text here.</w:t></w:r></w:p></w:footnote>
</w:footnotes>
"""

_FOOTNOTE_CT = (
    '<Override PartName="/word/footnotes.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>'
)
_FOOTNOTE_REL = (
    '<Relationship Id="rIdTexlateFootnotes" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
    'footnotes" Target="footnotes.xml"/>'
)


def _make_docx(path: Path, paras: list[tuple[str, str | None]]) -> Path:
    doc = Document()
    for text, style in paras:
        doc.add_paragraph(text, style=style)
    doc.save(str(path))
    return path


def _inject_footnotes(path: Path) -> None:
    """给已存 docx 追加 ``word/footnotes.xml`` part（content-type + rel 全配）。"""
    with zipfile.ZipFile(path) as z:
        members = {i.filename: z.read(i) for i in z.infolist()}
    ct = (
        members["[Content_Types].xml"]
        .decode("utf-8")
        .replace("</Types>", f"{_FOOTNOTE_CT}</Types>")
    )
    rels = (
        members["word/_rels/document.xml.rels"]
        .decode("utf-8")
        .replace("</Relationships>", f"{_FOOTNOTE_REL}</Relationships>")
    )
    members["[Content_Types].xml"] = ct.encode("utf-8")
    members["word/_rels/document.xml.rels"] = rels.encode("utf-8")
    members["word/footnotes.xml"] = FOOTNOTES_XML.encode("utf-8")
    with zipfile.ZipFile(path, "w") as z:
        for name, blob in members.items():
            z.writestr(name, blob, compress_type=zipfile.ZIP_DEFLATED)


class _EchoTranslator:
    """原样回显（剥掉批行 ``[n]`` 前缀）——译文 == 原文走 unchanged 分支。"""

    async def translate(self, **_kw: object) -> str:
        user = str(_kw["user"])
        return "\n".join(re.sub(r"^\[\d+\]\s?", "", ln) for ln in user.split("\n"))


def test_translate_docx_bilingual(tmp_path: Path) -> None:
    src = _make_docx(
        tmp_path / "in.docx",
        [
            ("First paragraph of the document.", None),
            ("List item text here.", "List Number"),
            ("Third and final paragraph.", None),
        ],
    )
    dst = tmp_path / "out.docx"
    report = translate_docx(src, dst, MockTranslator())
    assert report.format == "docx"
    assert report.translated == report.units == 3  # noqa: PLR2004 -- 三段正文

    doc = Document(str(dst))
    paras = doc.paragraphs
    assert len(paras) == 6  # noqa: PLR2004 -- 每段后跟译文克隆
    assert paras[0].text == "First paragraph of the document."
    assert "这是译文" in paras[1].text
    assert paras[2].text == "List item text here."
    assert "这是译文" in paras[3].text

    # 译文 run：eastAsia 字体 + 区分色；列表段 pPr 样式继承
    zh_run = paras[1].runs[0]
    rpr = zh_run._r.find(qn("w:rPr"))  # noqa: SLF001 -- oxml 断言面
    assert rpr is not None
    rfonts = rpr.find(qn("w:rFonts"))
    assert rfonts is not None
    assert rfonts.get(qn("w:eastAsia")) == "SimSun"
    color = rpr.find(qn("w:color"))
    assert color is not None
    assert color.get(qn("w:val")) == "555555"

    zh_ppr = paras[3]._p.find(qn("w:pPr"))  # noqa: SLF001 -- oxml 断言面
    assert zh_ppr is not None
    pstyle = zh_ppr.find(qn("w:pStyle"))
    assert pstyle is not None
    assert pstyle.get(qn("w:val")) == "ListNumber"


def test_footnotes_part_translated(tmp_path: Path) -> None:
    src = _make_docx(tmp_path / "in.docx", [("Body paragraph with a note.", None)])
    _inject_footnotes(src)
    dst = tmp_path / "out.docx"
    report = translate_docx(src, dst, MockTranslator())
    assert report.units == 2  # noqa: PLR2004 -- 正文段 + 脚注段
    assert report.documents == 2  # noqa: PLR2004 -- document.xml + footnotes.xml

    with zipfile.ZipFile(dst) as z:
        footnotes = z.read("word/footnotes.xml").decode("utf-8")
    assert "Footnote body text here." in footnotes
    assert "这是译文" in footnotes


def test_echo_translation_not_duplicated(tmp_path: Path) -> None:
    src = _make_docx(tmp_path / "in.docx", [("Only paragraph stays same.", None)])
    dst = tmp_path / "out.docx"
    report = translate_docx(src, dst, _EchoTranslator())
    assert report.unchanged == report.units
    doc = Document(str(dst))
    assert len(doc.paragraphs) == 1  # echo 不插重


def test_sniff_and_dispatch(tmp_path: Path) -> None:
    src = _make_docx(tmp_path / "in.docx", [("Dispatch me please.", None)])
    assert sniff_format(src) == "docx"
    report = export_document(src, None, MockTranslator())
    dst = tmp_path / "in_bilingual.docx"
    assert report.dst == dst
    assert dst.exists()
    doc = Document(str(dst))
    assert len(doc.paragraphs) == 2  # noqa: PLR2004 -- 原段+译文段


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def test_sectpr_not_cloned(tmp_path: Path) -> None:
    """节尾段（``w:pPr/w:sectPr`` 带正文）插译时克隆不得携带分节边界。

    sectPr 是结构不是样式——克隆携带会在源段后复制出一个空分节（Word 里
    nextPage 型就是一张空白页）。真书 manuscript.docx 有 47 个 sectPr 段。
    """
    doc = Document()
    p = doc.add_paragraph("Last paragraph ending a section.")
    ppr = p._p.get_or_add_pPr()  # noqa: SLF001 -- oxml 断言面
    ppr.append(
        parse_xml(
            f'<w:sectPr xmlns:w="{W_NS}"><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>'
        )
    )
    src = tmp_path / "in.docx"
    doc.save(str(src))
    dst = tmp_path / "out.docx"
    report = translate_docx(src, dst, MockTranslator())
    assert report.translated == 1
    with zipfile.ZipFile(dst) as z:
        raw = z.read("word/document.xml")
    # 源 sectPr 恰好一份：段级 1（原段）+ body 级 1（模板自带）
    assert raw.count(b"<w:sectPr") == 2  # noqa: PLR2004 -- 克隆不得新增
    out = Document(str(dst))
    assert "这是译文" in out.paragraphs[1].text


def test_hyperlink_text_extracted(tmp_path: Path) -> None:
    """``w:hyperlink`` 包裹的 run 是普通文本——抽取进 unit 并插译。"""
    doc = Document()
    p = doc.add_paragraph("Intro ")
    p._p.append(  # noqa: SLF001 -- oxml 构造面
        parse_xml(
            f'<w:hyperlink xmlns:w="{W_NS}">'
            "<w:r><w:t>link label text</w:t></w:r></w:hyperlink>"
        )
    )
    src = tmp_path / "in.docx"
    doc.save(str(src))
    dst = tmp_path / "out.docx"
    report = translate_docx(src, dst, MockTranslator())
    assert report.units == 1
    assert report.translated == 1
    out = Document(str(dst))
    assert len(out.paragraphs) == 2  # noqa: PLR2004 -- 原段+译文段
    assert "这是译文" in out.paragraphs[1].text


def test_field_codes_and_hidden_runs_skipped(tmp_path: Path) -> None:
    """``w:fldSimple`` 内缓存文本、``w:vanish`` 隐藏 run 都不进送模型文本。"""
    doc = Document()
    p_fld = doc.add_paragraph()
    p_fld._p.append(  # noqa: SLF001
        parse_xml(
            f'<w:fldSimple xmlns:w="{W_NS}" w:instr=" TOC \\o ">'
            "<w:r><w:t>Cached TOC result line</w:t></w:r></w:fldSimple>"
        )
    )
    p_vis = doc.add_paragraph()
    p_vis.add_run("visible text run")
    hidden = p_vis.add_run("hidden secret run")
    rpr = hidden._r.get_or_add_rPr()  # noqa: SLF001
    rpr.append(parse_xml(f'<w:vanish xmlns:w="{W_NS}"/>'))
    src = tmp_path / "in.docx"
    doc.save(str(src))

    doc2 = Document(str(src))
    texts = [u.text for u, _part, _root in iter_units(doc2)]
    assert len(texts) == 1
    assert texts[0] == "visible text run"  # 隐藏 run 不混入

    dst = tmp_path / "out.docx"
    report = translate_docx(src, dst, MockTranslator())
    assert report.units == 1
    with zipfile.ZipFile(dst) as z:
        raw = z.read("word/document.xml")
    # 域缓存文本不被翻译复制（仍是独份）
    assert raw.count(b"Cached TOC result line") == 1


def test_table_cell_translated(tmp_path: Path) -> None:
    """表格单元格段落照常插译——译文克隆落在同一 ``w:tc`` 内。"""
    doc = Document()
    doc.add_paragraph("Before the table.")
    tbl = doc.add_table(1, 1)
    tbl.cell(0, 0).paragraphs[0].add_run("Cell text here.")
    src = tmp_path / "in.docx"
    doc.save(str(src))
    dst = tmp_path / "out.docx"
    report = translate_docx(src, dst, MockTranslator())
    assert report.translated == 2  # noqa: PLR2004 -- 表前段+单元格段
    out = Document(str(dst))
    cell_paras = out.tables[0].cell(0, 0).paragraphs
    assert len(cell_paras) == 2  # noqa: PLR2004 -- 原段+译文段
    assert "这是译文" in cell_paras[1].text


def test_header_part_translated(tmp_path: Path) -> None:
    """页眉 part（``header*.xml``）走 ``_iter_surfaces`` 附属面照常插译。"""
    doc = Document()
    doc.add_paragraph("Body text.")
    header = doc.sections[0].header
    header.is_linked_to_previous = False
    header.paragraphs[0].text = "Running header text."
    src = tmp_path / "in.docx"
    doc.save(str(src))
    dst = tmp_path / "out.docx"
    report = translate_docx(src, dst, MockTranslator())
    assert report.translated == 2  # noqa: PLR2004 -- 正文+页眉
    with zipfile.ZipFile(dst) as z:
        header_names = [n for n in z.namelist() if re.match(r"word/header\d*\.xml", n)]
        assert header_names
        raw = z.read(header_names[0])
    assert "这是译文".encode() in raw


def _rewrite_member(path: Path, name: str, transform: Callable[[bytes], bytes]) -> None:
    """把 zip 成员 ``name`` 读出 → ``transform(bytes)->bytes`` → 原样写回。"""
    with zipfile.ZipFile(path) as z:
        members = {i.filename: z.read(i) for i in z.infolist()}
    members[name] = transform(members[name])
    with zipfile.ZipFile(path, "w") as z:
        for n, blob in members.items():
            z.writestr(n, blob, compress_type=zipfile.ZIP_DEFLATED)


def test_no_body_rejected(tmp_path: Path) -> None:
    """``document.xml`` 没有 ``w:body`` 的畸形件——可识别 DOCX 但不可翻。

    此前 ``doc.element.body`` 为 ``None``，``body.iter`` 崩裸 AttributeError；
    归到 ``UnsupportedFormatError``（worker/cli 统一 catch ``ExportError``）。
    """
    src = _make_docx(tmp_path / "in.docx", [("Some text.", None)])
    _rewrite_member(
        src,
        "word/document.xml",
        lambda b: re.sub(rb"<w:body>.*</w:body>", b"", b, flags=re.DOTALL),
    )
    with pytest.raises(UnsupportedFormatError, match="w:body"):
        translate_docx(src, tmp_path / "out.docx", MockTranslator())


def test_hidden_rpr_not_inherited(tmp_path: Path) -> None:
    """首个 run 是 ``w:vanish`` 隐藏 run 时，其 rPr 不得克隆进译文 run——
    否则译文段在 Word 里整段隐形。"""
    doc = Document()
    p = doc.add_paragraph()
    hidden = p.add_run("secret")
    hrpr = hidden._r.get_or_add_rPr()  # noqa: SLF001
    hrpr.append(parse_xml(f'<w:vanish xmlns:w="{W_NS}"/>'))
    visible = p.add_run("shown text")
    vrpr = visible._r.get_or_add_rPr()  # noqa: SLF001
    vrpr.append(parse_xml(f'<w:b xmlns:w="{W_NS}"/>'))
    src = tmp_path / "in.docx"
    doc.save(str(src))
    dst = tmp_path / "out.docx"
    report = translate_docx(src, dst, MockTranslator())
    assert report.translated == 1
    zh_rpr = Document(str(dst)).paragraphs[1].runs[0]._r.find(qn("w:rPr"))  # noqa: SLF001
    assert zh_rpr is not None
    assert zh_rpr.find(qn("w:vanish")) is None  # 译文不得隐形
    assert zh_rpr.find(qn("w:b")) is not None  # 继承的是可见 run 的 rPr


def test_hyperlink_rpr_inherited(tmp_path: Path) -> None:
    """全文在 ``w:hyperlink`` 内的段落，译文 run 也能拿到 hyperlink run 的 rPr。"""
    doc = Document()
    p = doc.add_paragraph()
    p._p.append(  # noqa: SLF001
        parse_xml(
            f'<w:hyperlink xmlns:w="{W_NS}"><w:r><w:rPr><w:b/></w:rPr>'
            "<w:t>link only text</w:t></w:r></w:hyperlink>"
        )
    )
    src = tmp_path / "in.docx"
    doc.save(str(src))
    dst = tmp_path / "out.docx"
    assert translate_docx(src, dst, MockTranslator()).translated == 1
    zh_rpr = Document(str(dst)).paragraphs[1].runs[0]._r.find(qn("w:rPr"))  # noqa: SLF001
    assert zh_rpr is not None
    assert zh_rpr.find(qn("w:b")) is not None


def test_para_id_not_duplicated(tmp_path: Path) -> None:
    """``w14:paraId``/``w14:textId`` 是逐段唯一锚点 id——克隆译文段必须剥掉。"""
    doc = Document()
    p = doc.add_paragraph("Para carrying w14 ids.")
    p._p.set(qn("w14:paraId"), "0A3B4C5D")  # noqa: SLF001
    p._p.set(qn("w14:textId"), "77777777")  # noqa: SLF001
    src = tmp_path / "in.docx"
    doc.save(str(src))
    dst = tmp_path / "out.docx"
    assert translate_docx(src, dst, MockTranslator()).translated == 1
    with zipfile.ZipFile(dst) as z:
        raw = z.read("word/document.xml")
    assert raw.count(b"0A3B4C5D") == 1  # 仅源段持有
    assert raw.count(b'w14:textId="77777777"') == 1


def test_specvanish_skipped(tmp_path: Path) -> None:
    """``w:specVanish`` 隐藏 run 与 ``w:vanish`` 同族——不送模型。"""
    doc = Document()
    p = doc.add_paragraph("visible part ")
    spec = p.add_run("hidden spec text")
    spec._r.get_or_add_rPr().append(  # noqa: SLF001
        parse_xml(f'<w:specVanish xmlns:w="{W_NS}"/>')
    )
    src = tmp_path / "in.docx"
    doc.save(str(src))
    texts = [u.text for u, _part, _root in iter_units(Document(str(src)))]
    assert texts == ["visible part"]


def test_nobreakhyphen_keeps_hyphen(tmp_path: Path) -> None:
    """``w:noBreakHyphen`` 是可见字符——抽取须补 ``-``，否则词被粘错。"""
    doc = Document()
    p = doc.add_paragraph()
    p._p.append(  # noqa: SLF001
        parse_xml(
            f'<w:r xmlns:w="{W_NS}"><w:t xml:space="preserve">non</w:t>'
            "<w:noBreakHyphen/><w:t>breaking change</w:t></w:r>"
        )
    )
    src = tmp_path / "in.docx"
    doc.save(str(src))
    texts = [u.text for u, _part, _root in iter_units(Document(str(src)))]
    assert texts == ["non-breaking change"]


def test_mc_fallback_not_double_translated(tmp_path: Path) -> None:
    """``mc:AlternateContent`` 的 Choice/Fallback 是同一份内容双份序列化——
    文本框文字只枚举 Choice 侧，Fallback 不重复送模型。"""
    mc = "http://schemas.openxmlformats.org/markup-compatibility/2006"
    doc = Document()
    p = doc.add_paragraph("Lead-in text.")
    txbx = (
        "<w:txbxContent><w:p><w:r><w:t>Textbox inner text</w:t></w:r>"
        "</w:p></w:txbxContent>"
    )
    p._p.append(  # noqa: SLF001
        parse_xml(
            f'<w:r xmlns:w="{W_NS}" xmlns:mc="{mc}"><mc:AlternateContent>'
            f"<mc:Choice>{txbx}</mc:Choice>"
            f"<mc:Fallback><w:pict><v:shape "
            f'xmlns:v="urn:schemas-microsoft-com:vml"><v:textbox>{txbx}'
            "</v:textbox></v:shape></w:pict></mc:Fallback>"
            "</mc:AlternateContent></w:r>"
        )
    )
    src = tmp_path / "in.docx"
    doc.save(str(src))
    units = [u.text for u, _part, _root in iter_units(Document(str(src)))]
    assert units == ["Lead-in text.", "Textbox inner text"]  # Fallback 双计已排除


def test_translation_run_lang_stamped(tmp_path: Path) -> None:
    """译文 run 的 ``w:lang``——docx 侧 texlate-zh 标记等价物（语言声明）。"""
    src = _make_docx(tmp_path / "in.docx", [("Some source text.", None)])
    dst = tmp_path / "out.docx"
    translate_docx(src, dst, MockTranslator())
    zh_rpr = Document(str(dst)).paragraphs[1].runs[0]._r.find(qn("w:rPr"))  # noqa: SLF001
    assert zh_rpr is not None
    lang = zh_rpr.find(qn("w:lang"))
    assert lang is not None
    assert lang.get(qn("w:eastAsia")) == "zh-CN"
    assert lang.get(qn("w:val")) == "zh-CN"


# ------------------------------------------------------------------ 审计增量
# 控制字符译文 / 注入型 target_lang


class _CtrlTranslator:
    """译文带 XML 非法控制字符——``insert_after`` 侧必须先剥除。

    回归：``w:t.text = "\\x0b..."`` lxml 直接 ``ValueError``，一条脏译文炸掉
    整次导出（``_apply`` 无逐条护栏）。
    """

    async def translate(self, **_kw: object) -> str:
        return "译\x0b文\x01控\x00制"


def test_control_chars_in_translation_stripped(tmp_path: Path) -> None:
    src = _make_docx(tmp_path / "in.docx", [("Some source text.", None)])
    dst = tmp_path / "out.docx"
    report = translate_docx(src, dst, _CtrlTranslator())
    assert report.translated == 1
    out = Document(str(dst))
    assert out.paragraphs[1].text == "译文控制"


def test_hostile_target_lang_no_stamp(tmp_path: Path) -> None:
    """``target_lang`` 带 XML 元字符 → ``safe_language`` 拒章：run ``w:lang``
    与 core ``dc:language`` 都不写，core.xml 仍合法。"""
    src = _make_docx(tmp_path / "in.docx", [("Some source text.", None)])
    dst = tmp_path / "out.docx"
    report = translate_docx(src, dst, MockTranslator(), target_lang='zh<x="1">')
    assert report.translated == 1
    out = Document(str(dst))
    zh_rpr = out.paragraphs[1].runs[0]._r.find(qn("w:rPr"))  # noqa: SLF001
    assert zh_rpr is not None
    assert zh_rpr.find(qn("w:lang")) is None  # 非法语言码不落章
    with zipfile.ZipFile(dst) as z:
        core = z.read("docProps/core.xml")
    etree.fromstring(core)
    assert b"zh<" not in core
