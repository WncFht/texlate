"""EPUB 插译：原文节点不动，译文按形态集（克隆/受限容器内追加/锚定）插后。"""

from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, NavigableString, Tag

from texlate.export.common import STUB_ONLY_RE
from texlate.export.filters import sanitize_xml_text
from texlate.export.markers import marker_report, reconcile_markers, split_on_markers

from .tags import BLOCK_TAGS, SINGLETON_TAGS

if TYPE_CHECKING:
    from .model import Unit


def _strip_duplicate_ids(element: Tag) -> Tag:
    """剥掉克隆元素及其全部后代的 id。

    译文是同一内容的第二次渲染，不是第二个锚点（epubcheck RSC-005；内部
    链接也不许落到译文上）。
    """
    if isinstance(element, Tag):
        element.attrs.pop("id", None)
        for descendant in element.descendants:
            if isinstance(descendant, Tag):
                descendant.attrs.pop("id", None)
    return element


_LANG_ATTRS = ("xml:lang", "lang")


def _restamp_language(element: Tag, language: str) -> Tag:
    """译文副本是目标语言，无论源声明什么；只动源本就声明过的属性。"""
    if not language or not isinstance(element, Tag):
        return element
    for attr in _LANG_ATTRS:
        if attr in element.attrs:
            element[attr] = language
    return element


def _translation_host(element: Tag) -> Tag:
    """译文可追加进的元素。

    nav ``<li>`` 例外：其内容模型是 ``(a|span),ol?``，落点定位进
    ``<a>/<span>``（bbm ``translation_host``）。
    """
    if element.name == "li" and element.find_parent("nav") is not None:
        label = element.find(["a", "span"], recursive=False)
        if label is not None:
            return label
    return element


def _stamp_translation(span: Tag, source: Tag, language: str) -> Tag:
    """给译文 span 打 ``texlate-zh`` class + 目标语言属性（继承源声明面）。"""
    cls = list(span.get("class") or [])
    if "texlate-zh" not in cls:
        cls.append("texlate-zh")
    span["class"] = cls
    for attr in _LANG_ATTRS:
        if language and attr in source.attrs:
            span[attr] = language
    return span


def _append_inline_translation(
    soup: BeautifulSoup,
    element: Tag,
    text: str,
    language: str,
) -> Tag:
    """译文*追加进*所属元素内部（受限容器路径）。"""
    span = soup.new_tag("span")
    span.string = text
    _stamp_translation(span, element, language)
    host = _translation_host(element)
    host.append(soup.new_tag("br"))
    host.append(span)
    return span


def _inline_subtree_root(node: Tag, owner: Tag) -> object:
    """文本节点最外层行内祖先（block 之下）——锚定插译的落点标记。"""
    root: object = node
    for ancestor in node.parents:
        if ancestor is owner or ancestor.name in BLOCK_TAGS:
            break
        root = ancestor
    return root


def _markup_covers_run(markup: object, owned: set[int]) -> bool:
    """该 markup 是否恰好罩住整段 run 的文本。

    罩住才可克隆承载译文（罩一半则不许——把整句译文交给一个碎片样式，
    正是 <a> 吞句的坑）。
    """
    return isinstance(markup, Tag) and owned <= {
        id(n) for n in markup.descendants if isinstance(n, NavigableString)
    }


def _insert_anchored_translation(
    unit: Unit,
    text: str,
    language: str,
) -> Tag:
    """多 run owner 的锚定插译：译文跟在 run 末尾节点之后。"""
    tail = _inline_subtree_root(unit.run_nodes[-1], unit.owner)
    owned = {id(n) for n in unit.run_nodes}
    if (
        isinstance(tail, Tag)
        and tail.name != "ruby"
        and _markup_covers_run(tail, owned)
    ):
        span = copy(tail)
        span.clear()
        _restamp_language(span, language)
        _strip_duplicate_ids(span)
        _stamp_translation(span, unit.owner, language)
    else:
        span = unit.soup.new_tag("span")
        _stamp_translation(span, unit.owner, language)
    span.string = text
    line_break = unit.soup.new_tag("br")
    tail.insert_after(line_break)
    line_break.insert_after(span)
    return span


def _insert_clone_translation(
    unit: Unit,
    text: str,
    language: str,
) -> Tag | None:
    """常规路径：克隆 owner → 摊平成译文纯文本 → strip id → 插到原文后。"""
    owner = unit.owner
    new_p = copy(owner)
    new_p.clear()
    new_p.string = text
    _strip_duplicate_ids(new_p)
    _restamp_language(new_p, language)
    cls = list(new_p.get("class") or [])
    if "texlate-zh" not in cls:
        cls.append("texlate-zh")
    new_p["class"] = cls
    owner.insert_after(new_p)
    return new_p


def _restore_markers(unit: Unit, inserted: Tag) -> None:
    """把每个 marker 的源元素克隆放回 token 落点（bbm ``_restore_markers``）。

    只在*刚插入的节点*里找 token——扫 owner 或下一个兄弟在两个方向上都错：
    源段自己印着 ``⟦⟧`` 同形字面文本的书会把源节点挪进译文。
    """
    tokens = list(unit.markers)
    if not tokens or not isinstance(inserted, Tag):
        return
    for text_node in [
        n for n in list(inserted.descendants) if isinstance(n, NavigableString)
    ]:
        raw = str(text_node)
        if not any(token in raw for token in tokens):
            continue
        pieces: list[object] = []
        for kind, value in split_on_markers(raw, tokens):
            if kind == "text":
                pieces.append(NavigableString(value))
                continue
            source = unit.markers[value]
            node = copy(source)
            _strip_duplicate_ids(node)
            pieces.append(node)
        if not pieces:
            continue
        text_node.replace_with(pieces[0])
        anchor = pieces[0]
        for piece in pieces[1:]:
            anchor.insert_after(piece)
            anchor = piece


def insert_translation(unit: Unit, zh_text: str, language: str) -> str | None:
    """按 §1.4 形态集插译；返回警告行（marker 调和有动作时）。"""
    zh = reconcile_markers(unit.text, zh_text, issued=unit.markers)
    warn = marker_report(unit.job_id, unit.text, zh_text, issued=unit.markers)
    zh = sanitize_xml_text(zh)  # 译文带 XML 非法字符会把整篇变非法文档
    if unit.ncx_text is not None:
        unit.ncx_text.text = f"{unit.text} / {zh}"
        return warn
    if not zh.strip() or STUB_ONLY_RE.fullmatch(zh):
        return warn  # 空译文/纯 ``[n]`` 序号桩——插出去只是空壳或线渣
    owner = unit.owner
    if zh.strip() == unit.text.strip():
        return warn  # 译文=原文（echo/回退）——插入只会制造同文重复
    # 无 <body> 的畸形文档里 owner 退到 <html> 乃至文档根：克隆会在根部造出
    # 第二个顶层元素（对 BeautifulSoup 根 insert_after 直接抛 NotImplementedError）
    # ——与 <body> 同走锚定，锚点是 run 尾节点、其父非空，insert_after 落得住。
    # fragment 文档（如裸 ``<p>x</p>``）顶层 block 同理：父即文档根的 owner
    # 走克隆照样双根，必须锚定。
    root_owner = (
        owner.name == "html"
        or isinstance(owner, BeautifulSoup)
        or isinstance(owner.parent, BeautifulSoup)
    )
    if (
        owner.name in SINGLETON_TAGS
        or owner.name == "nav"  # 克隆会把 epub:type 复制成第二个 landmark
        or owner.find_parent("nav") is not None
    ):
        inserted = _append_inline_translation(unit.soup, owner, zh, language)
    elif unit.is_multi_run or owner.name == "body" or root_owner:
        inserted = _insert_anchored_translation(unit, zh, language)
        if root_owner:
            note = (
                f"{unit.job_id}: no <body>; owner={owner.name}"
                " — translation anchored after run"
            )
            warn = f"{warn} | {note}" if warn else note
    else:
        inserted = _insert_clone_translation(unit, zh, language)
    if inserted is not None:
        _restore_markers(unit, inserted)
    return warn
