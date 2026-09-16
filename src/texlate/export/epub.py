"""EPUB 双语插译管线（doc-formats.md §2——bbm 蓝图 stdlib 自拆，不碰 EbookLib/AGPL）。

七步照抄 ``bilingual_book_maker`` 加固 fork 的语义、剪成 v1 面：

1. 拆包读入：stdlib zipfile + DRM 预检（``rights.check_epub``）+ fixed-layout 拒翻。
2. 文档枚举：manifest ``application/xhtml+xml`` 全集 = spine 序 + spine 外
   nav/封面追加在尾；NCX 不进翻译流但翻 ``navLabel/text``；其余 zip 成员逐字节
   照抄（``encryption.xml`` 与混淆字体免处理的前提：不动 ``dc:identifier``）。
3. 文本提取：run 制——文本节点归最近 block 祖先，嵌套 block 与非 ``<pre>``
   ``<br>`` 切 run；NON_CONTENT/ruby/exclude/pagebreak/hidden 跳过；短保护
   行内元素变 ``[[TAG_n]]`` marker。
4. 插译：原文节点不动，译文克隆插后；受限容器（SINGLETON/nav）改内部追加
   ``<br/><span>``；多 run owner（如 ``<div>前文<p>…</p>后文</div>``）锚定插。
5. marker 协议：防碰撞分配 → 宽容调和 → 写回克隆（``export.markers``）。
6. 批量/对齐：``XlatPipeline`` 原样复用（``[n]`` 协议 + 阶梯 + StateStore
   断点）——``chunk_id`` = ``epub:{doc}:{unit}:{sha256(text)[:16]}`` 的
   job_id，键控断点天然免疫 bbm 位置槽位的错配问题。
7. 写回：``mimetype`` 首条 ZIP_STORED，其余按原 infolist 序 ZIP_DEFLATED。

v1 明确不做（spec §5 边界表）：单译模式、配对 marker、CSS 级联 display 解析
（只查内联 ``display:none``+``hidden`` 属性）、披露页、epubcheck 全量对账、
only/exclude_filelist。
"""

from __future__ import annotations

import hashlib
import logging
import posixpath
import re
import shutil
import zipfile
from copy import copy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import defusedxml.ElementTree
from bs4 import BeautifulSoup, NavigableString, Tag
from defusedxml.common import DefusedXmlException
from lxml import etree

from texlate.xlat.pipeline import ChunkIn, ChunkResult
from texlate.xlat.placeholders import is_placeholder_only
from texlate.xlat.state import StateStore

from .common import (
    ApplyCounts,
    DrmError,
    ExportReport,
    FixedLayoutError,
    GlossaryArg,
    MalformedEpubError,
    drive_pipeline,
)
from .filters import is_apparatus_text, is_special_text, normalize_text
from .markers import (
    INLINE_MARKER_MAX_CHARS,
    INLINE_MARKER_WORDLESS_MAX_CHARS,
    Ordinals,
    is_wordless,
    marker_report,
    reconcile_markers,
    split_on_markers,
)
from .rights import DRM_MESSAGE, check_epub

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping

    from lxml.etree import _Element

    from texlate.xlat.pipeline import Translator

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- 常量

CONTAINER_PATH = "META-INF/container.xml"
_CONTAINER_NS = "{urn:oasis:names:tc:opendocument:xmlns:container}"
_OPF_NS = "{http://www.idpf.org/2007/opf}"

XHTML_MEDIA_TYPES = frozenset({"application/xhtml+xml", "text/html"})

#: HTML 默认块级集（bbm ``DEFAULT_BLOCK_TAGS`` 原样——``dfn`` 是行内，收进来
#: 会把段落切两半，刻意不收）
BLOCK_TAGS = frozenset(
    [
        "address",
        "article",
        "aside",
        "blockquote",
        "body",
        "caption",
        "dd",
        "details",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "html",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    ]
)

#: 其文本永不是文档内容的容器（svg 的 <text>/<title>、math 的 <mtext> 碎片
#: 否则会被并进最近散文 unit，"翻译"它们只会毁掉标记）
NON_CONTENT_TAGS = frozenset(
    ["script", "style", "head", "title", "template", "svg", "math"]
)

#: ruby 注音无条件跳过——不走 exclude 列表：get_text 会把读音拼进基字
RUBY_ANNOTATION_TAGS = frozenset(["rt", "rp", "rtc"])

#: 渲染为空白的容器——其中的跳过节点不切断两侧 run
INVISIBLE_CONTAINERS = frozenset(["script", "style", "template", "head", "title"])

#: 自身有渲染但不产文本的元素；夹在两个已拥有文本节点中间时是 barrier
RENDERED_VOID_TAGS = frozenset(
    [
        "img",
        "svg",
        "math",
        "video",
        "audio",
        "canvas",
        "object",
        "iframe",
        "embed",
        "picture",
        "hr",
        "input",
    ]
)

#: 内容模型只准一个该元素/严格受限的容器——译文兄弟节点是 epubcheck 拒绝的
#: 书：<figure> 只收一个 <figcaption>，nav 文档 <li> 里只有 (a|span),ol?
SINGLETON_TAGS = frozenset(["figcaption", "caption", "legend", "summary"])

#: 弹注语义：携带这些标记的内容即使 CSS/属性隐藏，弹注阅读器照样显示
_NOTE_EPUB_TYPES = frozenset(
    ["footnote", "endnote", "rearnote", "note", "footnotes", "endnotes"]
)
_NOTE_ROLES = frozenset(["doc-footnote", "doc-endnote"])

#: 送模型前排除的 tag（送文本不含其内容，节点本身留在 DOM）
DEFAULT_EXCLUDE_TAGS: tuple[str, ...] = ("sup", "code")

_CSS_DISPLAY_RE = re.compile(r"(?:^|;)\s*display\s*:\s*([\w-]+)", re.IGNORECASE)

#: OPF ``dc:language`` 的外科式改写——整树 ET 重写会把 ``opf:file-as`` 之类
#: 属性换成生成前缀，正则只动这一个元素的文本内容
_DC_LANGUAGE_RE = re.compile(
    r"<([A-Za-z_][\w.-]*):language\b[^>]*>([^<]*)</\1:language>"
)

_PIPELINE_VERSION = "export-epub-1"

#: NCX 解析器——bs4 "xml" 后端是裸 ``etree.XMLParser``（无实体/网络限制），
#: 上传文档面一律走显式加固
_SAFE_XML = etree.XMLParser(resolve_entities=False, no_network=True)

#: unit kind 一律 ``para``——``_KIND_CLAUSES`` 的合法键是 LaTeX 语境（xlat/
#: 不属本模块），EPUB 散文用 para 的最宽条款 + 占位符契约已够


# ---------------------------------------------------------------- 数据结构


@dataclass
class EpubBook:
    """拆包结果：成员表 + 原始序 + 文档面 + OPF/NCX 位置。"""

    members: dict[str, bytes]
    order: list[str]
    doc_paths: list[str]
    opf_path: str
    opf_dir: str
    ncx_path: str | None


@dataclass
class Unit:
    """一个翻译单元（spec §2.5 Unit 契约的 DOM 版）。

    ``markers``: ``token → 源元素``；``run_nodes`` 是该 run 的已拥有文本节点
    （锚定插译的落点）；``is_multi_run`` = owner 还持有别的 run（克隆 owner
    会把别的 run 的原文也复制进去，此时必须锚定）。
    """

    job_id: str
    text: str
    kind: str
    owner: Tag | None
    run_nodes: list
    markers: dict[str, Tag]
    is_multi_run: bool
    soup: BeautifulSoup | None
    ncx_text: _Element | None = None


# ---------------------------------------------------------------- 拆包


def load_epub(src: Path | str) -> EpubBook:  # noqa: C901, PLR0912, PLR0915 -- 拆包校验每分支即一条 spec 拒翻规则，拆开反而对不上 §2
    """读全本：DRM 预检 → zip 成员表 → container → OPF → 文档面枚举。"""
    if check_epub(src) == "drm":
        raise DrmError(DRM_MESSAGE)
    try:
        zf = zipfile.ZipFile(src)
    except (OSError, zipfile.BadZipFile) as e:
        msg = f"不是可读 zip/EPUB: {Path(src).name} ({e})"
        raise MalformedEpubError(msg) from e
    with zf:
        infos = zf.infolist()
        members: dict[str, bytes] = {}
        order: list[str] = []
        for info in infos:
            if info.filename not in members:  # zip 重名条目只取首个
                members[info.filename] = zf.read(info)
                order.append(info.filename)

    if CONTAINER_PATH not in members:
        msg = f"缺 {CONTAINER_PATH}——不是 EPUB"
        raise MalformedEpubError(msg)
    try:
        container = defusedxml.ElementTree.fromstring(members[CONTAINER_PATH])
    except (defusedxml.ElementTree.ParseError, DefusedXmlException) as e:
        msg = f"container.xml 解析失败: {e}"
        raise MalformedEpubError(msg) from e
    rootfile = container.find(f".//{_CONTAINER_NS}rootfile")
    opf_path = rootfile.get("full-path") if rootfile is not None else None
    if not opf_path or opf_path not in members:
        msg = "container.xml 未给出有效 OPF full-path"
        raise MalformedEpubError(msg)
    opf_dir = posixpath.dirname(opf_path)
    try:
        opf = defusedxml.ElementTree.fromstring(members[opf_path])
    except (defusedxml.ElementTree.ParseError, DefusedXmlException) as e:
        msg = f"OPF 解析失败: {e}"
        raise MalformedEpubError(msg) from e

    # fixed-layout（pre-paginated）插译必破版式——警告级拒翻（spec §2.6）
    for meta in opf.iter(f"{_OPF_NS}meta"):
        if (
            meta.get("property") == "rendition:layout"
            and (meta.text or "").strip() == "pre-paginated"
        ):
            msg = "fixed-layout（pre-paginated）EPUB 不支持插译"
            raise FixedLayoutError(msg)

    manifest: dict[str, tuple[str, str, str]] = {}
    ncx_path: str | None = None
    for it in opf.iter(f"{_OPF_NS}item"):
        iid = it.get("id")
        href = it.get("href")
        mtype = it.get("media-type") or ""
        if not iid or not href:
            continue
        manifest[iid] = (href, mtype, it.get("properties") or "")
        if mtype == "application/x-dtbncx+xml":
            ncx_path = posixpath.join(opf_dir, href) if opf_dir else href

    spine: list[str] = [ir.get("idref") or "" for ir in opf.iter(f"{_OPF_NS}itemref")]
    docs: list[str] = []
    for idref in spine:
        entry = manifest.get(idref)
        if entry is None or entry[1] not in XHTML_MEDIA_TYPES:
            continue
        path = posixpath.join(opf_dir, entry[0]) if opf_dir else entry[0]
        if path in members and path not in docs:
            docs.append(path)
    # spine 之外、manifest 里仍是 xhtml 的（不在 spine 的 nav/封面页）追加在尾
    for href, mtype, _props in manifest.values():
        if mtype not in XHTML_MEDIA_TYPES:
            continue
        path = posixpath.join(opf_dir, href) if opf_dir else href
        if path in members and path not in docs:
            docs.append(path)
    if not docs:
        msg = "manifest 里没有可翻的 xhtml 文档"
        raise MalformedEpubError(msg)
    return EpubBook(members, order, docs, opf_path, opf_dir, ncx_path)


# ---------------------------------------------------------------- unit 枚举


def _inline_hidden(element: Tag) -> bool:
    """Style 属性内联 ``display:none``，或 HTML ``hidden`` 属性。

    ``aria-hidden`` 刻意不算——它只对辅助技术隐藏，常规出现在完全可见内容上。
    """
    if element.has_attr("hidden"):
        return True
    style = element.get("style")
    if style:
        m = _CSS_DISPLAY_RE.search(style)
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
        if any(tok in _NOTE_EPUB_TYPES for tok in epub_type.split()):
            note = True
        if role in _NOTE_ROLES:
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
    """``one<br/>two`` 不许读成 "onetwo"：每个非 ``<pre>`` ``<br>`` 后插换行文本。

    ``<wbr>`` 刻意不动（不空格相连正是 word-break opportunity 的语义），
    ``<pre>`` 内的 ``<br>`` 也不动（插入的空白会真实渲染）。
    """
    for br in root.find_all("br"):
        if br.find_parent("pre") is None:
            br.insert_after(NavigableString("\n"))


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

    两段式分配 marker token：先以 ``\x00{i}\x00`` 哨兵占位组装归一化文本，
    再对成品文本做碰撞回避分配（token 须在送模型文本里恰好出现一次）。
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
            sentinel = f"\x00{seq}\x00"
            seq += 1
            sentinels.append((sentinel, node))
            parts.append(sentinel)
            continue
        # owned / glue 文本片段——glue 只在 run 已开时才带词间空白
        if kind == "owned" or (kind == "glue" and parts):
            if kind == "owned":
                run_nodes.append(node)
            parts.append(str(node))
    out = emit()
    if out is not None:
        yield out


def iter_units(  # noqa: C901, PLR0912 -- 枚举主循环：记录趟/owner 趟/NCX 趟三段各有自己的跳过判据
    book: EpubBook,
    soups: dict[str, BeautifulSoup],
    *,
    exclude_tags: Iterable[str] = DEFAULT_EXCLUDE_TAGS,
) -> Iterator[Unit]:
    """枚举全部翻译单元（bbm plan 模式的 v1 裁剪：block owner + run 切分）。"""
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


# ---------------------------------------------------------------- 插译


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
        if attr in source.attrs:
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
    if unit.ncx_text is not None:
        unit.ncx_text.text = f"{unit.text} / {zh}"
        return warn
    owner = unit.owner
    if zh.strip() == unit.text.strip():
        return warn  # 译文=原文（echo/回退）——插入只会制造同文重复
    if owner.name in SINGLETON_TAGS or owner.find_parent("nav") is not None:
        inserted = _append_inline_translation(unit.soup, owner, zh, language)
    elif unit.is_multi_run or owner.name == "body":
        inserted = _insert_anchored_translation(unit, zh, language)
    else:
        inserted = _insert_clone_translation(unit, zh, language)
    if inserted is not None:
        _restore_markers(unit, inserted)
    return warn


# ---------------------------------------------------------------- 写回


_ZH_CSS = ".texlate-zh{color:#555}"


def _inject_css(soups: dict[str, BeautifulSoup]) -> None:
    """每篇 XHTML ``<head>`` 内嵌 ``<style>``——EPUB2/3 都合法，不动 manifest。"""
    for soup in soups.values():
        head = soup.find("head")
        if head is None:
            continue
        style = soup.new_tag("style")
        style.string = _ZH_CSS
        head.append(style)


def _restamp_opf(book: EpubBook, language: str) -> None:
    """首条 ``dc:language`` → 目标语言。

    ``dc:identifier`` 不动——它是字体混淆的密钥源，照抄 zip 条目即免处理
    （spec §2.6）。
    """
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


def save_epub(dst: Path | str, book: EpubBook) -> None:
    """OCF 硬约束：``mimetype`` 第一且 ZIP_STORED；其余按原 infolist 序 DEFLATED。"""
    with zipfile.ZipFile(dst, "w") as out:
        if "mimetype" in book.members:
            out.writestr(
                "mimetype",
                book.members["mimetype"],
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


# ---------------------------------------------------------------- 驱动


def translate_epub(  # noqa: C901, PLR0913 -- 驱动主链：公共 API 参数面 + apply/flush 闭包
    src: Path | str,
    dst: Path | str,
    translator: Translator,
    *,
    target_lang: str = "zh-CN",
    state_dir: Path | None = None,
    glossary: GlossaryArg | None = None,
    on_result: Callable[[ChunkResult], None] | None = None,
) -> ExportReport:
    """EPUB → 双语 EPUB 全链。

    ``translator`` 走 ``XlatPipeline`` 全编排（批量/阶梯/断点复用，零改动）；
    ``state_dir`` 缺省 ``{dst}.state/``——中断残留自动续跑，成功即清理。
    ``glossary`` 入参归一见 ``common.coerce_glossary``。
    Ctrl-C/异常时按已完成译文写一本半成品双语书再抛出（bbm ``_save_temp_book``
    语义）。
    """
    src = Path(src)
    dst = Path(dst)
    book = load_epub(src)
    soups: dict[str, BeautifulSoup] = {
        p: BeautifulSoup(book.members[p], "html.parser") for p in book.doc_paths
    }
    units = list(iter_units(book, soups))
    state_dir = state_dir or dst.with_name(dst.name + ".state")
    store = StateStore(state_dir, model="export", pipeline_version=_PIPELINE_VERSION)

    ncx_root = next(
        (u.ncx_text.getroottree().getroot() for u in units if u.ncx_text is not None),
        None,
    )

    def _flush_and_save(translated: int) -> None:
        """DOM 改动 → members 字节 → 出包（成功与半成品两路共用）。

        ``translated == 0`` 时不注 CSS——无 ``texlate-zh`` 节点的书不该
        长出一个引用空类的 ``<style>``。
        """
        if translated:
            _inject_css(soups)
        _restamp_opf(book, target_lang)
        for path, soup in soups.items():
            book.members[path] = soup.encode("utf-8")
        if book.ncx_path and ncx_root is not None:
            book.members[book.ncx_path] = etree.tostring(
                ncx_root, encoding="utf-8", xml_declaration=True
            )
        save_epub(dst, book)

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
            if r.translation.strip() == u.text.strip():
                counts.unchanged += 1
                continue
            warn = insert_translation(u, r.translation, target_lang)
            if warn:
                counts.warnings.append(warn)
            counts.translated += 1
        return counts

    chunks = [ChunkIn(u.job_id, u.text, u.kind) for u in units]
    results, counts = drive_pipeline(
        chunks,
        translator=translator,
        store=store,
        glossary=glossary,
        on_result=on_result,
        apply_fn=_apply,
        save_fn=_flush_and_save,
    )

    if state_dir.exists():
        shutil.rmtree(state_dir, ignore_errors=True)
    n_skipped = sum(1 for r in results.values() if r.status == "skipped")
    return ExportReport(
        src=src,
        dst=dst,
        format="epub",
        units=len(units),
        translated=counts.translated,
        unchanged=counts.unchanged,
        skipped=n_skipped,
        fault=counts.fault,
        documents=len(book.doc_paths),
        warnings=counts.warnings,
    )
