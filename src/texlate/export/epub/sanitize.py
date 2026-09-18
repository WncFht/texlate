"""EPUB DOM 净化：html.parser 宽容构造 → 可序列化为合法 XML。

载入时一次性做（在 DOM 上做而非 ``_serialize_soup`` 每次做——后者非幂等）：
raw-text 预转义、Comment/Declaration/Doctype/PI/顶层 CDATA 整形、tag/attr
名与未绑定前缀整形、多根/裸文本成员套 ``<html><body>`` 保单一根元素。
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.element import (
    CData,
    Comment,
    Declaration,
    Doctype,
    ProcessingInstruction,
    Script,
    Stylesheet,
    TemplateString,
)

#: XML Name 字符集（保守 ASCII 子集）：首字符字母/``_``，后续加数字/``.-:``
_XML_NAME_START = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_XML_NAME_CHARS = _XML_NAME_START | frozenset("0123456789.-:")

#: doctype 名的合法尾：``PUBLIC "lit" "lit"`` 或 ``SYSTEM "lit"``（引号配对）
_DOCTYPE_TAIL_RE = re.compile(
    r"""(?:PUBLIC\s+(['"]).*?\1\s+(['"]).*?\2|SYSTEM\s+(['"]).*?\3)\s*\Z""",
    re.DOTALL,
)


def _is_xml_name(s: str) -> bool:
    return bool(s) and s[0] in _XML_NAME_START and all(c in _XML_NAME_CHARS for c in s)


def _clean_xml_name(name: str, fallback: str) -> str:
    """剥掉 XML Name 非法字符；剥到 NameStartChar 起算，剥空回退 ``fallback``。"""
    kept = "".join(c for c in name if c in _XML_NAME_CHARS)
    i = 0
    while i < len(kept) and kept[i] not in _XML_NAME_START:
        i += 1
    return kept[i:] or fallback


def _prefix_bound(tag: Tag, prefix: str) -> bool:
    """``prefix`` 在 tag 自身或祖先上有 ``xmlns:prefix`` 声明才算绑定。"""
    for anc in (tag, *tag.parents):
        if isinstance(anc, Tag) and f"xmlns:{prefix}" in anc.attrs:
            return True
    return False


def _ensure_single_root(soup: BeautifulSoup) -> None:
    """文档树整根：top-level 恰一个元素才可能是合法 XML。

    fragment 多根/裸文本/顶层 CDATA 成员 → 内容整体套进 ``<html><body>``
    （doctype/``<?xml`` 等 prolog 构造随之沉入 body，由逐节点规则清位）。
    """
    tags = 0
    stray = False
    for c in soup.contents:
        if isinstance(c, Tag):
            tags += 1
        elif isinstance(c, (Comment, Doctype, ProcessingInstruction, Declaration)):
            continue  # prolog/misc 构造本身在顶层合法
        elif isinstance(c, CData) or str(c).strip():
            stray = True  # 顶层字符数据/CDATA 非法；空白 Misc 放行
    if tags == 1 and not stray:
        return
    html = soup.new_tag("html")
    body = soup.new_tag("body")
    html.append(body)
    for child in list(soup.contents):
        body.append(child)
    soup.append(html)


def _sanitize_tag(tag: Tag) -> None:
    """tag/attr 名整形：非法字符剥除；未绑定命名空间前缀取本地名。"""
    if ":" in tag.name:
        prefix, _sep, local = tag.name.partition(":")
        src = tag.name if prefix == "xml" or _prefix_bound(tag, prefix) else local
        tag.name = _clean_xml_name(src, "div")
    else:
        tag.name = _clean_xml_name(tag.name, "div")
    new_attrs: dict[str, object] = {}
    for key, val in tag.attrs.items():
        if key == "xmlns" or key.startswith("xmlns:"):
            clean_key = key  # 命名空间声明自身即绑定源，原样保留
        elif ":" in key:
            prefix, _sep, local = key.partition(":")
            src = key if prefix == "xml" or _prefix_bound(tag, prefix) else local
            clean_key = _clean_xml_name(src, "")
        else:
            clean_key = _clean_xml_name(key, "")
        if not clean_key or clean_key in new_attrs:
            continue  # 剥空/重名属性没有合法落位
        new_attrs[clean_key] = val
    tag.attrs = new_attrs


def _sanitize_pi(soup: BeautifulSoup, node: ProcessingInstruction) -> None:
    """PI 整形为可序列化形（bs4 序列化为 ``<?``+text+``>``，text 须 ``?`` 收尾）。

    剥掉 ``<``/``&``/``?`` 防提前终结与残留字符数据；target 须为合法
    Name，``xml`` target 只在文档首位（XML decl 位）合法。
    """
    body = str(node).replace("<", "").replace("&", "").replace("?", "")
    parts = body.split(None, 1)
    target = parts[0] if parts else ""
    if not _is_xml_name(target):
        node.extract()
        return
    if target.lower() == "xml" and (
        node.parent is not soup or node.find_previous_siblings()
    ):
        node.extract()
        return
    node.replace_with(ProcessingInstruction(body + "?"))


def _sanitize_doctype(soup: BeautifulSoup, node: Doctype) -> None:
    """Doctype 整形：只在 prolog（根元素前、唯一）合法。

    html.parser 把内部子集截断在首个 ``>`` 必残，非 ``PUBLIC``/``SYSTEM``
    合法尾一律压回裸名。
    """
    if node.parent is not soup or any(
        isinstance(s, (Tag, Doctype)) for s in node.find_previous_siblings()
    ):
        node.extract()
        return
    parts = str(node).strip().split(None, 1)
    name = _clean_xml_name(parts[0] if parts else "", "html")
    tail = parts[1] if len(parts) > 1 else ""
    if tail and _DOCTYPE_TAIL_RE.fullmatch(tail):
        node.replace_with(Doctype(f"{name} {tail}"))
    else:
        node.replace_with(Doctype(name))


_RAW_TEXT_AMP_RE = re.compile(
    r"&(?!#[0-9]+;|#[xX][0-9a-fA-F]+;|amp;|lt;|gt;|quot;|apos;)"
)


def _escape_raw_text(text: str) -> str:
    """raw-text 节点内容的 XML 化转义：``&`` 只在不构成合法 XML 实体时补转。

    ``html.parser`` 对 ``<script>``/``<style>``/``<template>`` 不解实体——
    源里的 ``&amp;`` 已是序列化形，``saxutils.escape`` 无脑转 ``&`` 会产出
    ``&amp;amp;``，产出重进管线逐轮累积 ``amp;``（非幂等）。裸 ``&`` 与
    ``<``/``>`` 仍须转义（``<`` 防提前终结、``>`` 防 ``]]>`` 非法序列）；
    ``&nbsp;`` 等非预定义实体转为字面量 ``&amp;nbsp;``——EPUB XHTML 无 DTD，
    保留原名会产出未定义实体非法件。
    """
    text = _RAW_TEXT_AMP_RE.sub("&amp;", text)
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _sanitize_dom(soup: BeautifulSoup) -> None:
    """载入时一次性 DOM 净化：html.parser 宽容构造 → 可序列化为合法 XML。

    - ``Script``/``Stylesheet``/``TemplateString`` 内容走 cdata 直通面不转义
      → 预转义一次（在 DOM 上做而非 ``_serialize_soup`` 每次做——后者非幂等）；
    - ``Comment`` 折叠 ``-{2,}``/剥尾 ``-``；``Declaration`` 独立节点必非法；
    - ``Doctype``/PI/顶层 CDATA 见各自子规则；tag/attr 名与未绑定前缀整形；
    - 多根/裸文本成员套 ``<html><body>`` 保单一根元素。
    """
    _ensure_single_root(soup)
    for node in list(soup.descendants):
        if isinstance(node, (Script, Stylesheet, TemplateString)):
            node.replace_with(type(node)(_escape_raw_text(str(node))))
        elif isinstance(node, Comment):
            node.replace_with(Comment(re.sub(r"-{2,}", "-", str(node)).rstrip("-")))
        elif isinstance(node, ProcessingInstruction):
            _sanitize_pi(soup, node)
        elif isinstance(node, Doctype):
            _sanitize_doctype(soup, node)
        elif isinstance(node, Declaration):
            node.extract()  # markup decl 只在 doctype 子集内合法
        elif isinstance(node, CData):
            if isinstance(node.parent, BeautifulSoup):
                node.replace_with(NavigableString(str(node)))
        elif isinstance(node, Tag):
            _sanitize_tag(node)
