"""EPUB 写回：soups → 成员字节 → OCF 合法 zip（mimetype 首位 STORED）。

含 ``book_soups``（成员字节 → 净化 soup 表）、``_serialize_soup``（soup →
utf-8 字节 + xml decl 改写）、CSS 内嵌、``dc:language`` 外科式改写、
出包成员名门禁与 ``save_epub``。
"""

from __future__ import annotations

import logging
import re
import zipfile
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from texlate.export.common import MalformedEpubError
from texlate.export.filters import sanitize_xml_text

from .sanitize import _sanitize_dom

if TYPE_CHECKING:
    from pathlib import Path

    from .model import EpubBook

log = logging.getLogger(__name__)

_ZH_CSS = ".texlate-zh{color:#555}"

#: 文档开头 ``<?xml ... encoding="X"?>`` 声明的 encoding 值——bs4 序列化原样
#: 保留 PI（只改写 meta charset），源声明（如 ISO-8859-1）会对 utf-8 字节说谎
_XML_DECL_ENCODING_RE = re.compile(
    r"\A(\ufeff?\s*<\?xml\b[^>]*?\bencoding\s*=\s*)([\"'])[^\"']*([\"'])"
)

#: OPF ``dc:language`` 的外科式改写——整树 ET 重写会把 ``opf:file-as`` 之类
#: 属性换成生成前缀，正则只动这一个元素的文本内容
_DC_LANGUAGE_RE = re.compile(
    r"<([A-Za-z_][\w.-]*):language\b[^>]*>([^<]*)</\1:language>"
)

#: Windows 驱动器绝对形（``C:/x``）——POSIX 侧不挡但对按名落盘的
#: Windows 提取器是 zip-slip 同族。
_DRIVE_ABS_RE = re.compile(r"[A-Za-z]:")


def book_soups(book: EpubBook) -> dict[str, BeautifulSoup]:
    """``doc_paths`` → 净化 soup 表（成员字节经 ``html.parser`` + ``_sanitize_dom``）。

    ``translate_epub`` 与外部逐 soup 操作面（测试锚点/工具）共用同一构造口——
    保证插译锚点落到的 DOM 与出包序列化的 DOM 是同一份净化形。
    """
    soups = {p: BeautifulSoup(book.members[p], "html.parser") for p in book.doc_paths}
    for soup in soups.values():
        _sanitize_dom(soup)
    return soups


def _serialize_soup(soup: BeautifulSoup) -> bytes:
    """DOM → utf-8 成员字节：剥 XML 非法字符 + 改写 xml decl encoding。

    净化在 str 层做（utf-8 多字节续字节 ≥0x80，不会误伤双字节序列）；
    decl 改写只认文档开头的 ``<?xml``（合法 decl 位置，顶多前带 BOM/空白）。
    """
    text = sanitize_xml_text(soup.encode("utf-8").decode("utf-8"))
    text = _XML_DECL_ENCODING_RE.sub(r"\g<1>\g<2>utf-8\g<3>", text, count=1)
    return text.encode("utf-8")


def _inject_css(soups: dict[str, BeautifulSoup]) -> None:
    """每篇 XHTML ``<head>`` 内嵌 ``<style>``——EPUB2/3 都合法，不动 manifest。"""
    for soup in soups.values():
        head = soup.find("head")
        if head is None:
            continue
        style = soup.new_tag("style")
        style.string = _ZH_CSS
        head.append(style)


def _restamp_opf(book: EpubBook, language: str | None) -> None:
    """首条 ``dc:language`` → 目标语言。

    ``dc:identifier`` 不动——它是字体混淆的密钥源，照抄 zip 条目即免处理
    （spec §2.6）。``language=None``（非法 ``target_lang``）时整步跳过——
    正则文本替换面对注入值没有转义层。
    """
    if language is None:
        return
    raw = book.members[book.opf_path]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        log.warning("OPF 非 UTF-8，跳过 dc:language 改写: %s", book.opf_path)
        return
    m = _DC_LANGUAGE_RE.search(text)
    if m:
        # span 替换而非字符串 replace——语言码（la/an/gu…）可能是标签名/属性的
        # 子串，replace 会先命中它们把元素改残（`dc:zh-CNnguage` 事故）
        text = text[: m.start(2)] + language + text[m.end(2) :]
    elif "</metadata>" in text and "xmlns:dc" in text:
        # 只在 dc 前缀已声明时才补元素——裸 ``<dc:language>`` 是非法 XML
        text = text.replace(
            "</metadata>",
            f"<dc:language>{language}</dc:language></metadata>",
            1,
        )
    book.members[book.opf_path] = text.encode("utf-8")


def _is_traversal_segment(seg: str) -> bool:
    """``..`` 段及其 Windows 归一化同族（``".. "``/``"..."``——尾随空白/点被提取器剥落后仍是父目录引用形）。"""
    dots = seg.replace(" ", "")
    return dots.startswith("..") and not dots.strip(".")


def _validate_member_name(name: str) -> None:
    r"""出包成员名门禁：OCF 成员名是受限相对路径，敌意形态一律拒写。

    ``load_epub`` 对成员名入侧宽容是刻意的（逐字节收进 ``members``），
    但写出侧原样透传会把 zip-slip 形（``..`` 段、``/`` 绝对、``\\``
    分隔、``X:`` 驱动器）流给下游按名落盘的提取器；NUL/控制字符更糟——
    ``zipfile.ZipInfo`` 读写两侧都在首个 NUL 截断，``a\\x00evil`` 会写成
    ``a`` 与真成员撞名顶替。stdlib 层没有「逐字节保留」支路，唯一诚实
    的契约是拒绝。
    """
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or _DRIVE_ABS_RE.match(name)
        or any(ord(c) < 0x20 for c in name)  # noqa: PLR2004 -- ASCII 控制字符界即语义（含 NUL）
        or any(_is_traversal_segment(seg) for seg in name.split("/"))
    ):
        msg = f"非法 zip 成员名，拒绝出包: {name!r}"
        raise MalformedEpubError(msg)


def save_epub(dst: Path | str, book: EpubBook) -> None:
    """OCF 硬约束：``mimetype`` 第一且 ZIP_STORED；其余按原 infolist 序 DEFLATED。

    成员名先全量过 ``_validate_member_name``——先于建包拒绝，不在 ``dst``
    留半截 zip。
    """
    for name in book.members:
        _validate_member_name(name)
    with zipfile.ZipFile(dst, "w") as out:
        # 输入缺 mimetype 是畸形但可翻——产出侧必须产合法包：写规范值兜底
        # 输入缺/坏 mimetype 都可能出现（畸形输入可翻），产出侧必须写规范值——
        # 照抄会让 sniff_format 连自家出包都认不出
        out.writestr(
            "mimetype",
            b"application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        written = {"mimetype"}
        for name in book.order:
            if name in written:
                continue
            out.writestr(name, book.members[name], compress_type=zipfile.ZIP_DEFLATED)
            written.add(name)
        for name, blob in book.members.items():
            if name not in written:  # 防御：枚举后新增的成员（v1 不应出现）
                out.writestr(name, blob, compress_type=zipfile.ZIP_DEFLATED)
