"""EPUB 翻译单元枚举：block owner 判定 + run 切分 + NCX navLabel 单元。

bbm plan 模式的 v1 裁剪——文本节点归最近 block 祖先，嵌套 block 与非
``<pre>`` ``<br>`` 切 run；跳过判据（NON_CONTENT/ruby/exclude/pagebreak/
hidden）与行内 marker 候选判定全在本叶。
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, NavigableString, Tag
from lxml import etree

from texlate.export.common import MalformedEpubError
from texlate.export.filters import (
    is_apparatus_text,
    is_special_text,
    normalize_text,
)
from texlate.export.markers import (
    INLINE_MARKER_MAX_CHARS,
    INLINE_MARKER_WORDLESS_MAX_CHARS,
    Ordinals,
    is_wordless,
)
from texlate.xlat.placeholders import is_placeholder_only

from .model import Unit
from .tags import (
    BLOCK_TAGS,
    CSS_DISPLAY_RE,
    DEFAULT_EXCLUDE_TAGS,
    INVISIBLE_CONTAINERS,
    NON_CONTENT_TAGS,
    NOTE_EPUB_TYPES,
    NOTE_ROLES,
    PUA_SENTINEL_RE,
    RENDERED_VOID_TAGS,
    RUBY_ANNOTATION_TAGS,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from .model import EpubBook

log = logging.getLogger(__name__)

#: NCX 解析器——bs4 "xml" 后端是裸 ``etree.XMLParser``（无实体/网络限制），
#: 上传文档面一律走显式加固
_SAFE_XML = etree.XMLParser(resolve_entities=False, no_network=True)


def _inline_hidden(element: Tag) -> bool:
    """Style 属性内联 ``display:none``，或 HTML ``hidden`` 属性。

    ``aria-hidden`` 刻意不算——它只对辅助技术隐藏，常规出现在完全可见内容上。
    """
    if element.has_attr("hidden"):
        return True
    style = element.get("style")
    if style:
        m = CSS_DISPLAY_RE.search(style)
        return bool(m and m.group(1).lower() == "none")
    return False


def _ancestor_skip_reason(  # noqa: C901, PLR0911 -- 祖先链逐条短路即 bbm skip 判定表，return 数就是规则数
    node: Tag, exclude_tags: Iterable[str]
) -> str | None:
    """文本节点的跳过理由；``None`` = 可翻译。"""
    hidden = False
    note = False
    for ancestor in node.parents:
        name = ancestor.name
        if name in NON_CONTENT_TAGS:
            return "non-content"
        if name in RUBY_ANNOTATION_TAGS:
            return "ruby"
        if name in exclude_tags:
            return "excluded-tag"
        epub_type = ancestor.get("epub:type") or ""
        if "pagebreak" in epub_type or "page-list" in epub_type:
            return "pagebreak"
        role = ancestor.get("role") or ""
        if role == "doc-pagebreak":
            return "pagebreak"
        if any(tok in NOTE_EPUB_TYPES for tok in epub_type.split()):
            note = True
        if role in NOTE_ROLES:
            note = True
        if not hidden and _inline_hidden(ancestor):
            hidden = True
    if hidden and not note:
        return "hidden"
    return None


def _nearest_block(node: Tag) -> Tag | None:
    """最近的 block 祖先（owner 判定的唯一事实源）。"""
    for ancestor in node.parents:
        if ancestor.name in BLOCK_TAGS:
            return ancestor
    return None


def _renders_between(node: Tag, owner: Tag) -> bool:
    """保留但未拥有的文本是否真的渲染在两个 run 之间。

    隐藏文本与 ruby 注音留在 DOM 却不分隔两侧文字（注音渲染在基字*上方*），
    所以都不能切断 segment。
    """
    for ancestor in node.parents:
        if ancestor is owner:
            return True
        if (
            ancestor.name in RUBY_ANNOTATION_TAGS
            or ancestor.name in INVISIBLE_CONTAINERS
            or _inline_hidden(ancestor)
        ):
            return False
    return True


def _visible_text(root: Tag) -> str:
    """子树分类文本：ruby 注音排除、零宽字符剥除、空白折叠。"""
    parts = []
    for node in root.descendants:
        if type(node) is not NavigableString:
            continue
        in_annotation = any(
            a.name in RUBY_ANNOTATION_TAGS for a in node.parents if a is not root
        )
        if not in_annotation:
            parts.append(str(node))
    return normalize_text("".join(parts))


def _marker_candidate(element: Tag, owned_ids: set[int], owner: Tag) -> bool:
    """这个行内元素能否被原子 marker 顶替（bbm ``_marker_candidate`` 移植）。

    只收：不持有本 owner 任何可译文本、渲染得出东西、且短到能站在句子里的
    受保护内容。嵌套 block/``<br>`` 是真正的分隔，token 顶替不了。
    """
    if any(
        id(n) in owned_ids for n in element.descendants if type(n) is NavigableString
    ):
        return False
    rendered = _visible_text(element)
    cap = (
        INLINE_MARKER_WORDLESS_MAX_CHARS
        if is_wordless(rendered)
        else INLINE_MARKER_MAX_CHARS
    )
    if len(rendered) >= cap:
        return False
    if element.name in RENDERED_VOID_TAGS:
        return True
    holds_void = False
    for node in element.descendants:
        if not isinstance(node, Tag):
            continue
        if node.name in BLOCK_TAGS or node.name == "br":
            return False
        if node.name in RENDERED_VOID_TAGS:
            holds_void = True
    if holds_void:
        # ``<a href="full.jpg"><img/></a>``：wrapper 不持有可译文本、渲染的
        # 正是被替换元素渲染的——取 *wrapper* 做 marker 源，写回时图带链接
        return True
    return any(
        type(n) is NavigableString and str(n).strip() and _renders_between(n, owner)
        for n in element.descendants
    )


def _separate_brs(root: Tag | BeautifulSoup) -> None:
    """``one<br/>two`` 不许读成 "onetwo"：每个 ``<br>`` 都要在文本流里留词界。

    ``<wbr>`` 刻意不动（不空格相连正是 word-break opportunity 的语义）。
    非 ``<pre>`` ``<br>`` 后插换行文本（多余空白不渲染）；``<pre>`` 内
    ``<br>`` 直接换成换行文本——pre 保留换行，渲染等价且文本节点天然分隔。
    """
    for br in root.find_all("br"):
        if br.find_parent("pre") is None:
            br.insert_after(NavigableString("\n"))
        else:
            br.replace_with(NavigableString("\n"))


def _owner_events(  # noqa: C901 -- bbm 事件流移植，分支密度即蓝图
    owner: Tag, owned_ids: set[int]
) -> Iterator[tuple[str, object]]:
    """按文档序产出 owner 自身行内内容的事件流（bbm ``_iter_owner_events`` 移植）。

    产出 ``("owned", node)`` / ``("glue", node)`` / ``("marker", element)``；
    barrier 不直接产出——遇到下一个 owned 文本时以 ``("barrier", why)`` 先行
    放出（why ∈ block/br/skipped）。
    """
    pending: list[str | None] = [None]

    def barrier(why: str) -> None:
        if pending[0] is None:
            pending[0] = why

    def walk(element: Tag) -> Iterator[tuple[str, object]]:  # noqa: C901, PLR0912 -- 同上：barrier/marker/递归分派逐分支对应蓝图规则
        for child in element.children:
            if isinstance(child, Tag):
                if child.name in BLOCK_TAGS:
                    barrier("block")
                    continue
                if child.name == "br":
                    if child.find_parent("pre") is None:
                        barrier("br")
                    continue
                if _marker_candidate(child, owned_ids, owner):
                    yield "marker", child
                    continue
                if child.name in RENDERED_VOID_TAGS:
                    # 替换元素大多为空，但 canvas/object/video/iframe 可带
                    # fallback 文本——无该特性阅读器确实显示它，必须可达
                    barrier("skipped")
                    if any(
                        type(n) is NavigableString and id(n) in owned_ids
                        for n in child.descendants
                    ):
                        yield from walk(child)
                        barrier("skipped")
                    continue
                yield from walk(child)
                continue
            if type(child) is not NavigableString:
                continue
            if id(child) in owned_ids:
                if pending[0] is not None:
                    yield "barrier", pending[0]
                    pending[0] = None
                yield "owned", child
            elif not str(child).strip():
                yield "glue", child
            elif _renders_between(child, owner):
                barrier("skipped")
            # 否则 invisible——不入流也不分隔

    yield from walk(owner)


def _runs_for_owner(  # noqa: C901 -- 事件流→run 的 case 分派，拆分只会打散 emit 生命周期
    owner: Tag,
    owned_ids: set[int],
    ordinals: Ordinals,
) -> Iterator[tuple[list, dict[str, Tag], str]]:
    r"""Owner 的事件流 → 各 run 的 ``(run_nodes, markers, text)``。

    两段式分配 marker token：先以 ``{i}`` 哨兵占位组装归一化文本，
    再对成品文本做碰撞回避分配（token 须在送模型文本里恰好出现一次）。
    哨兵用 PUA 而非控制字符：``normalize_text`` 剥 XML 非法字符，\x00 哨兵
    活不到 replace。
    """
    run_nodes: list = []
    parts: list[str] = []
    sentinels: list[tuple[str, Tag]] = []
    seq = 0

    def emit() -> tuple[list, dict[str, Tag], str] | None:
        if not run_nodes and not sentinels:
            return None
        text = normalize_text("".join(parts))
        markers: dict[str, Tag] = {}
        for sentinel, el in sentinels:
            token = ordinals.allocate(el.name, occupied=text, taken=markers)
            markers[token] = el
            text = text.replace(sentinel, f" {token} ", 1)
        return (list(run_nodes), markers, normalize_text(text))

    for kind, node in _owner_events(owner, owned_ids):
        if kind == "barrier":
            out = emit()
            if out is not None:
                yield out
            run_nodes, parts, sentinels, seq = [], [], [], 0
            continue
        if kind == "marker":
            sentinel = f"{seq}"
            seq += 1
            sentinels.append((sentinel, node))
            parts.append(sentinel)
            continue
        # owned / glue 文本片段——glue 只在 run 已开时才带词间空白
        if kind == "owned" or (kind == "glue" and parts):
            if kind == "owned":
                run_nodes.append(node)
            # 源文逐字印着 / 会与哨兵碰撞：先命中字面位、真哨兵
            # 残留进 sent 文本——装配前剥净（PUA 属不可见私有区，同零宽字符）
            parts.append(PUA_SENTINEL_RE.sub("", str(node)))
    out = emit()
    if out is not None:
        yield out


def iter_units(
    book: EpubBook,
    soups: dict[str, BeautifulSoup],
    *,
    exclude_tags: Iterable[str] = DEFAULT_EXCLUDE_TAGS,
) -> Iterator[Unit]:
    """枚举全部翻译单元（bbm plan 模式的 v1 裁剪：block owner + run 切分）。

    超深嵌套 DOM 上 bs4 的递归遍历（``descendants``/``find_all``）撞
    ``RecursionError``——折进 ``MalformedEpubError``，裸内置异常不许逃逸
    ``ExportError`` 族。
    """
    try:
        yield from _iter_units(book, soups, exclude_tags=exclude_tags)
    except RecursionError as e:
        msg = f"EPUB 文档嵌套过深，无法枚举翻译单元: {book.opf_path}"
        raise MalformedEpubError(msg) from e


def _iter_units(  # noqa: C901, PLR0912 -- 枚举主循环：记录趟/owner 趟/NCX 趟三段各有自己的跳过判据
    book: EpubBook,
    soups: dict[str, BeautifulSoup],
    *,
    exclude_tags: Iterable[str] = DEFAULT_EXCLUDE_TAGS,
) -> Iterator[Unit]:
    exclude_tags = tuple(exclude_tags)
    for doc_index, path in enumerate(book.doc_paths):
        soup = soups[path]
        body = soup.find("body") or soup
        _separate_brs(body)

        # 一趟文档序扫描：每个文本节点的 (跳过理由, 归属 block)
        owned_by: dict[int, set[int]] = {}
        owner_order: list[Tag] = []
        for node in body.descendants:
            if type(node) is not NavigableString:
                continue
            if not str(node).strip():
                continue
            if _ancestor_skip_reason(node, exclude_tags) is not None:
                continue
            owner = _nearest_block(node) or body
            if id(owner) not in owned_by:
                owned_by[id(owner)] = set()
                owner_order.append(owner)
            owned_by[id(owner)].add(id(node))

        ordinals = Ordinals()
        seq = 0
        for owner in owner_order:
            runs = list(_runs_for_owner(owner, owned_by[id(owner)], ordinals))
            for run_nodes, markers, text in runs:
                if not text:
                    continue
                if is_special_text(text) or is_apparatus_text(text):
                    continue
                if is_placeholder_only(text):
                    continue
                digest = hashlib.sha256(text.encode()).hexdigest()[:16]
                job_id = f"epub:{doc_index}:{path}:{seq}:{digest}"
                seq += 1
                yield Unit(
                    job_id=job_id,
                    text=text,
                    kind="para",
                    owner=owner,
                    run_nodes=run_nodes,
                    markers=markers,
                    is_multi_run=len(runs) > 1,
                    soup=soup,
                )

    # NCX navLabel/text：EPUB2 目录的可见标签——翻成 ``原文 / 译文`` 双串。
    # 走加固 lxml 而非 bs4 "xml"（后者是裸 XMLParser）；解析失败只弃 NCX 面。
    if book.ncx_path and book.ncx_path in book.members:
        try:
            ncx_root = etree.fromstring(book.members[book.ncx_path], parser=_SAFE_XML)
        except etree.XMLSyntaxError:
            log.warning("NCX 解析失败，跳过目录翻译: %s", book.ncx_path)
        else:
            for i, text_el in enumerate(
                el
                for el in ncx_root.iter()
                if isinstance(el.tag, str) and el.tag.rsplit("}", 1)[-1] == "text"
            ):
                raw = normalize_text("".join(text_el.itertext()))
                if not raw or is_special_text(raw) or is_apparatus_text(raw):
                    continue
                digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
                yield Unit(
                    job_id=f"epub:ncx:{i}:{digest}",
                    text=raw,
                    kind="para",
                    owner=None,
                    run_nodes=[],
                    markers={},
                    is_multi_run=False,
                    soup=None,
                    ncx_text=text_el,
                )
