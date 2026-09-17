"""DOCX 双语插译管线（doc-formats.md §3——python-docx deepcopy ``w:p`` + ``addnext``）。

遍历面（spec §3.1 六行表的 v1 落地）：

- 正文段落 + 表格 + 文本框 + ``w:sdt`` 内容控件：``body.iter(w:p)`` 一次全
  覆盖——``w:p`` 不可能嵌套，descendant iter 按文档序命中全部（含表格
  单元格、``w:txbxContent``、``w:sdtContent`` 内的段落）。外层 ``w:p`` 的
  文本抽取经"嵌套 ``w:p`` 祖先"判据跳过文本框段落，防双重计词。
- 页眉页脚/脚注/尾注/批注：``doc.part.package`` 的裸 part——``header*.xml``/
  ``footer*.xml`` 各自成 part；``footnotes.xml``/``endnotes.xml``/
  ``comments.xml`` 未被 python-docx 建模（plain ``Part``），走 ``part.blob``
  lxml 解析、插译后写回 ``part._blob``。
- 跳过：``w:instrText``/``w:fldSimple``（域代码/TOC 域）、``w:del``/``w:delText``
  /``w:moveFrom``（修订删除/移出侧）、``m:oMath`` 系、``w:rt`` 注音、
  ``w:vanish``/``w:specVanish`` 隐藏 run、``mc:Fallback`` 子树（与
  ``mc:Choice`` 同内容的重复序列化）、TOC 样式段落（域内残留 ``w:t``——
  页码反正失效，不花请求）。
- 图文/公式段：抽取只拼非保护 ``w:t``；保护物是整段主体 → 无 ``w:t`` →
  unit 不成立自然跳过（双语模式原文段反正留着）。

插译 = ``deepcopy(w:p)`` → 剥到只剩 ``w:pPr``（numPr/缩进/段落样式 id 连坐
继承——译文列表项拿到自己的编号）→ ``addnext`` → ``add_run`` 译文 +
首个 run 的 ``rPr`` 深拷（字体字号继承）+ ``w:eastAsia=SimSun`` +
``w:color=555555``。重打包零成本：``doc.save()`` 全量保 part。

断点与 EPUB 同构：job_id = ``docx:{part}:{index}:{sha256(text)[:16]}``，
``StateStore`` 键控续跑。
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.oxml.parser import parse_xml
from docx.shared import RGBColor
from docx.text.paragraph import Paragraph
from lxml import etree

from texlate.xlat.pipeline import ChunkIn, ChunkResult
from texlate.xlat.placeholders import is_placeholder_only
from texlate.xlat.state import StateStore

from .common import (
    STUB_ONLY_RE,
    ApplyCounts,
    ExportReport,
    GlossaryArg,
    UnsupportedFormatError,
    drive_pipeline,
    safe_language,
)
from .filters import (
    is_apparatus_text,
    is_special_text,
    normalize_text,
    sanitize_xml_text,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from docx.document import Document as DocumentObject
    from docx.opc.part import Part
    from lxml.etree import _Element

    from texlate.xlat.pipeline import Translator

log = logging.getLogger(__name__)

_PIPELINE_VERSION = "export-docx-1"

#: ``w:p`` 段落内保护子树——其 ``w:t`` 不拼进送模型文本。``w:p`` 自身在内：
#: 外层段落的 descendant iter 会摸到文本框/``w:sdt`` 内嵌套 ``w:p`` 的
#: ``w:t``——那些文字归内层自己的 unit，本判据防双重计词。
_PROTECTED_ANCESTOR = frozenset(
    {
        qn("m:oMath"),
        qn("m:oMathPara"),
        qn("w:fldSimple"),
        qn("w:del"),
        qn("w:moveFrom"),
        qn("w:rt"),
        qn("w:p"),
    }
)

#: ``w:rPr`` 下把 run 渲染成不可见的属性——其文本不送模型，rPr 也不做译文模板
_HIDDEN_PROPS = (qn("w:vanish"), qn("w:specVanish"))

#: 永不送模型的文本节点（``w:instrText`` 是域代码本体；``w:delText`` 是已删文本）
_SKIP_NODE = frozenset({qn("w:instrText"), qn("w:delText")})

#: 字面字符贡献节点：``w:tab``→``\t``，``w:br``/``w:cr``→``\n``（归一化时折叠），
#: ``w:noBreakHyphen``→``-``（丢掉会把 ``non-breaking`` 粘成一个错词）
_LITERAL_NODE = {
    qn("w:tab"): "\t",
    qn("w:br"): "\n",
    qn("w:cr"): "\n",
    qn("w:noBreakHyphen"): "-",
}

#: ``mc:AlternateContent`` 的 ``mc:Fallback`` 与 ``mc:Choice`` 是同一份内容的
#: 双份序列化（如文本框的 VML 兜底）——其 ``w:p`` 不枚举，否则同一文本送两遍
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"

#: 页眉页脚/脚注/尾注/批注 part 的文件名形态
_EXTRA_PART_RE = re.compile(
    r"^/word/(header\d*|footer\d*|footnotes|endnotes|comments)\.xml$"
)

#: TOC 段落样式名（中英文模板常见形态）
_TOC_STYLE_RE = re.compile(r"(?i)^(toc|tableofcontents|contents)\s*\d*$")


@dataclass
class DocxUnit:
    """一个 DOCX 翻译单元：``p_el`` = 待插译的 ``w:p`` lxml 元素。"""

    job_id: str
    text: str
    p_el: _Element
    part_name: str


# ---------------------------------------------------------------- 文本抽取


def _protected(node: _Element, stop: _Element) -> bool:
    """``node``（``w:t`` 等）在 ``stop``（所属 ``w:p``）之下是否位于保护子树。

    额外查 ``w:r`` 祖先的 ``w:rPr`` 隐藏标记——隐藏 run 不送模型。
    """
    el = node.getparent()
    while el is not None and el is not stop:
        if el.tag in _PROTECTED_ANCESTOR:
            return True
        if el.tag == qn("w:r"):
            rpr = el.find(qn("w:rPr"))
            if rpr is not None and any(
                rpr.find(prop) is not None for prop in _HIDDEN_PROPS
            ):
                return True
        el = el.getparent()
    return False


def _para_text(p_el: _Element) -> str:
    """``w:p`` 的送模型文本：只拼非保护 ``w:t``，``w:tab``/``w:br`` 折成空白。"""
    parts: list[str] = []
    for node in p_el.iter():
        tag = node.tag
        if tag in _SKIP_NODE:
            continue
        if tag == qn("w:t"):
            if not _protected(node, p_el):
                parts.append(node.text or "")
        elif tag in _LITERAL_NODE and not _protected(node, p_el):
            parts.append(_LITERAL_NODE[tag])
    return normalize_text("".join(parts))


def _toc_styled(p_el: _Element) -> bool:
    """段落样式是 TOC 系（``w:pPr/w:pStyle @w:val``）——目录项不送模型。"""
    ppr = p_el.find(qn("w:pPr"))
    if ppr is None:
        return False
    style = ppr.find(qn("w:pStyle"))
    if style is None:
        return False
    return bool(_TOC_STYLE_RE.match(style.get(qn("w:val")) or ""))


# ---------------------------------------------------------------- 遍历面


def _part_root(part: Part) -> _Element | None:
    """裸 part → 可编辑 lxml 根。

    python-docx 建模的 part（``XmlPart`` 系）直接改 ``_element``；未建模的
    （footnotes/endnotes/comments 等 plain ``Part``）解 ``blob``，插译完由
    调用方 ``_commit_part`` 写回 ``part._blob``。解析走 ``oxml_parser``
    （``resolve_entities=False`` 加固 + 自定义元素类表）——``w:p`` 落到
    ``CT_P``，插译的 ``add_run``/``get_or_add_*`` 对全部 part 一致可用。
    """
    element = getattr(part, "_element", None)
    if element is not None:
        return element
    blob = getattr(part, "blob", None)
    if not blob:
        return None
    try:
        return parse_xml(blob)
    except etree.XMLSyntaxError:
        log.warning("DOCX part %s XML 解析失败——该面跳过翻译", part.partname)
        return None


def _commit_part(part: Part, root: _Element) -> None:
    """Plain ``Part`` 的改动回写（``part.blob`` 读 ``_blob``——赋新值即生效）。

    ``XmlPart`` 的 ``_element`` 是原地改的，无需提交。
    """
    if getattr(part, "_element", None) is not None:
        return
    part._blob = etree.tostring(  # noqa: SLF001 -- 裸 part 唯一写回面
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )


def _in_mc_fallback(p_el: _Element) -> bool:
    """``w:p`` 的祖先链含 ``mc:Fallback``——重复序列化分支，不枚举。"""
    el = p_el.getparent()
    while el is not None:
        if el.tag == _MC_FALLBACK:
            return True
        el = el.getparent()
    return False


def _iter_paras(root: _Element) -> Iterator[_Element]:
    """``root`` 下全部可枚举 ``w:p``——``mc:Fallback`` 副本除外。"""
    for p_el in root.iter(qn("w:p")):
        if _in_mc_fallback(p_el):
            continue
        yield p_el


def _iter_surfaces(
    doc: DocumentObject,
) -> Iterator[tuple[str, _Element, Part | None, _Element | None]]:
    """``(part_name, w:p, part, part_root)``——body + 附属 part 两面。

    body 用 ``doc.element.body.iter(w:p)`` 全覆盖（表格/文本框/sdt 嵌套段落
    一网打尽）；其余面按 partname 扫 package parts，``part_root`` 回传供
    ``_commit_part`` 写回。
    """
    body = doc.element.body
    if body is None:
        msg = "document.xml 缺少 w:body——不是可翻的 DOCX"
        raise UnsupportedFormatError(msg)
    for p_el in _iter_paras(body):
        yield "/word/document.xml", p_el, None, None
    for part in doc.part.package.parts:
        name = str(part.partname)
        if not _EXTRA_PART_RE.match(name):
            continue
        root = _part_root(part)
        if root is None:
            continue
        for p_el in _iter_paras(root):
            yield name, p_el, part, root


def iter_units(
    doc: DocumentObject,
) -> Iterator[tuple[DocxUnit, Part | None, _Element | None]]:
    """全部翻译单元：``(unit, part_for_commit, part_root)``。"""
    counters: dict[str, int] = {}
    for part_name, p_el, part, root in _iter_surfaces(doc):
        if _toc_styled(p_el):
            continue
        text = _para_text(p_el)
        if not text:
            continue
        if is_special_text(text) or is_apparatus_text(text):
            continue
        if is_placeholder_only(text):
            continue
        idx = counters.get(part_name, 0)
        counters[part_name] = idx + 1
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        yield (
            DocxUnit(
                job_id=f"docx:{part_name}:{idx}:{digest}",
                text=text,
                p_el=p_el,
                part_name=part_name,
            ),
            part,
            root,
        )


# ---------------------------------------------------------------- 插译


def _first_rpr(p_el: _Element) -> _Element | None:
    """首个可见文本 run 的 ``w:rPr``——译文 run 的格式模板。

    经 ``w:t`` 定位而非直系 ``w:r``：``w:hyperlink``/``w:sdt``/``w:smartTag``
    包裹的 run 也能命中；``_protected`` 顺带排掉隐藏 run——隐藏 run 的 rPr
    克隆过去译文会跟着隐形。
    """
    for t in p_el.iter(qn("w:t")):
        if _protected(t, p_el):
            continue
        r = t.getparent()
        if r is not None and r.tag == qn("w:r"):
            rpr = r.find(qn("w:rPr"))
            if rpr is not None:
                return rpr
    return None


def insert_after(p_el: _Element, zh_text: str, language: str) -> None:
    """Deepcopy ``w:p`` → 剥到 ``w:pPr`` → ``addnext`` → 写入译文 run。

    pPr 深拷把 numPr/缩进/段落样式一起继承（spec §3.2）；书签/修订标记随
    非 pPr 子树剥掉，不产生重复锚点/域 id；``w14:paraId``/``w14:textId``
    是逐段唯一锚点 id，克隆必须剥除。``rPr`` 子元素走 ``get_or_add_*``
    按 schema 序落位；``w:lang`` 是 docx 侧的 texlate-zh 标记等价物。
    """
    zh_text = sanitize_xml_text(zh_text)  # 控制字符会让 lxml 序列化硬炸全链
    new_ct_p = deepcopy(p_el)
    for child in list(new_ct_p):
        if child.tag != qn("w:pPr"):
            new_ct_p.remove(child)
    # sectPr 是结构边界不是样式：克隆携带会在源段后复制出一个空分节
    new_ppr = new_ct_p.find(qn("w:pPr"))
    if new_ppr is not None:
        for sect in new_ppr.findall(qn("w:sectPr")):
            new_ppr.remove(sect)
    for attr in (qn("w14:paraId"), qn("w14:textId")):
        new_ct_p.attrib.pop(attr, None)
    p_el.addnext(new_ct_p)
    para = Paragraph(new_ct_p, None)
    run = para.add_run(zh_text)
    src_rpr = _first_rpr(p_el)
    if src_rpr is not None:
        run._r.insert(0, deepcopy(src_rpr))  # noqa: SLF001 -- oxml 内部面即接口
    rpr = run._r.get_or_add_rPr()  # noqa: SLF001
    rpr.get_or_add_rFonts().set(qn("w:eastAsia"), "SimSun")
    rpr.get_or_add_color().val = RGBColor(0x55, 0x55, 0x55)  # 双语区分色（v1 钉值）
    if language:
        lang = rpr.find(qn("w:lang"))
        if lang is None:
            lang = OxmlElement("w:lang")
            # w:lang 在 rPr schema 序里位于 eastAsianLayout/specVanish/oMath 之前
            rpr.insert_element_before(
                lang, "w:eastAsianLayout", "w:specVanish", "w:oMath"
            )
        lang.set(qn("w:val"), language)
        lang.set(qn("w:eastAsia"), language)


# ---------------------------------------------------------------- 驱动


def translate_docx(  # noqa: C901, PLR0913, PLR0915 -- 驱动主链：公共 API 参数面 + apply/commit 闭包
    src: Path | str,
    dst: Path | str,
    translator: Translator,
    *,
    target_lang: str = "zh-CN",
    state_dir: Path | None = None,
    glossary: GlossaryArg | None = None,
    on_result: Callable[[ChunkResult], None] | None = None,
) -> ExportReport:
    """DOCX → 双语 DOCX 全链（断点/批量/阶梯与 EPUB 同构，见 ``epub.py``）。

    ``glossary`` 入参归一见 ``common.coerce_glossary``。
    Ctrl-C/异常时按已完成译文写一本半成品双语书再抛出（bbm ``_save_temp_book``
    语义）；``state_dir`` 缺省 ``{dst}.state/``，成功即清理。
    """
    src = Path(src)
    dst = Path(dst)
    lang = safe_language(target_lang)
    if lang is None:
        log.warning("target_lang 非 BCP47 形态，跳过全部语言章: %r", target_lang)
    try:
        doc = Document(str(src))
    except Exception as e:
        msg = f"不是可读 DOCX: {src.name} ({e})"
        raise UnsupportedFormatError(msg) from e

    try:
        pairs = list(iter_units(doc))
    except RecursionError as e:
        msg = f"DOCX 文档嵌套过深，无法解析: {src.name}"
        raise UnsupportedFormatError(msg) from e
    units = [u for u, _part, _root in pairs]
    # part → (part_obj, root) 去重表：同一 part 的多个段落共享一次提交
    parts_to_commit: dict[str, tuple[Part, _Element]] = {}
    for u, part, root in pairs:
        if part is not None:
            parts_to_commit[u.part_name] = (part, root)

    state_dir = state_dir or dst.with_name(dst.name + ".state")
    store = StateStore(state_dir, model="export", pipeline_version=_PIPELINE_VERSION)

    def _apply(results: Mapping[str, ChunkResult]) -> ApplyCounts:
        counts = ApplyCounts()
        for u in units:
            r = results.get(u.job_id)
            if r is None:
                continue
            if r.status in ("skipped", "fault"):
                if r.status == "fault":
                    counts.fault += 1
                continue
            # 与 insert_after 的 sanitize 同口径预判：空译文/echo 不插不计
            # （插了也只是无字空壳段，zh_total 计数不变量会破）
            zh = sanitize_xml_text(r.translation)
            if (
                not zh.strip()
                or STUB_ONLY_RE.fullmatch(zh)
                or zh.strip() == u.text.strip()
            ):
                counts.unchanged += 1
                continue
            insert_after(u.p_el, r.translation, lang or "")
            counts.translated += 1
        return counts

    def _commit_and_save(_translated: int) -> None:
        for part, root in parts_to_commit.values():
            _commit_part(part, root)
        if lang is not None:
            doc.core_properties.language = lang
        doc.save(str(dst))

    chunks = [ChunkIn(u.job_id, u.text, "para") for u in units]
    try:
        results, counts = drive_pipeline(
            chunks,
            translator=translator,
            store=store,
            glossary=glossary,
            on_result=on_result,
            apply_fn=_apply,
            save_fn=_commit_and_save,
        )
    except RecursionError as e:
        # 超深 ``w:p`` 子树在 ``insert_after`` 的 deepcopy/序列化路径同样
        # 撞 RecursionError——折进 ExportError 族，裸内置异常不许逃逸
        msg = f"DOCX 文档嵌套过深，无法翻译: {src.name}"
        raise UnsupportedFormatError(msg) from e

    if state_dir.exists():
        shutil.rmtree(state_dir, ignore_errors=True)
    n_skipped = sum(1 for r in results.values() if r.status == "skipped")
    return ExportReport(
        src=src,
        dst=dst,
        format="docx",
        units=len(units),
        translated=counts.translated,
        unchanged=counts.unchanged,
        skipped=n_skipped,
        fault=counts.fault,
        documents=len(parts_to_commit) + 1,
    )
