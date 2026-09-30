r"""arXiv 原生 HTML 降级链 phase 1（latexml 探针裁决 arxiv-html-first）。

``GET /html/{id}[vN]`` → ``article.ltx_document`` DOM 分块 → ``ChunkIn``：

- 块模型：``div.ltx_para`` → para；``h1–h6.ltx_title*`` → title（``span.ltx_tag``
  编号剥离）；``figcaption.ltx_caption`` → caption（figure/table 保护容器内
  照挖，对齐 latex segmenter 语义）；``li.ltx_bibitem``、``figure.ltx_*``、
  listing/authors/dates → support 块（不译——``\bibitem``/``\author`` 在
  latex 侧即 ``[[BIB]]``/``[[AUTHOR]]`` 保护族，降级链保持同口径）。
  pre-2000 e-print 无 ``ltx_title_document``：首个 ``ltx_titlepage``/
  ``ltx_logical-block`` 容器内首个 ``font-size`` 超过 100% 的元素兜底为
  title 块，宿主 para/p 内联时跳过该元素防文本双计。
- 行内保护：``<math>`` 与 ``*.ltx_equation*`` → ``[[MATH_n]]``；
  ``cite.ltx_cite`` → ``[[CITE_n]]``；``a[href^="#"]`` → ``[[REF_n]]``；
  ``span.ltx_note`` → ``[[NOTE_n]]``（note 体另产 footnote 块，对齐
  ``\footnote`` chunk-arg）；媒体/图形 → ``[[GRAPHICS_n]]``；
  ``span.ltx_ERROR`` → ``[[CMD_n]]``；``*.ltx_tabular`` → ``[[TABLE_n]]``。
  ph 值 = 元素 outer HTML（``alttext`` 内嵌其中——MathML 无需重渲染
  即无损回插，``reinsert`` 单趟替换）。
- chrome：只取 ``article.ltx_document`` 内部（页头/TOC/页脚天然在外）；
  article 内 ``nav``/``ltx_pagination``/``script`` 等经跳过分派剥离。

错误分类同 ``fetch.py`` 族：404 或 200 stub（无 ``ltx_document``——撤稿/
「HTML not available」/abs 回落页同形）→ ``HtmlNotAvailableError``；
其余非 200 → ``HtmlFetchError``；传输瞬时失败走 ``Fetcher._request``
退避纪律（429/406/5xx + TransportError 重试），Parked/Budget 原样上抛。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import TYPE_CHECKING, Final

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.element import Comment, Declaration, Doctype, ProcessingInstruction

from texlate.chunk import ChunkIn, normalize_kind
from texlate.textutil import PH_RX, PhIssuer

from .fetch import Fetcher, req_base_ver

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from bs4.element import PageElement

# ---------------------------------------------------------------- 错误分类


class HtmlError(Exception):
    """arXiv HTML 降级链错误基类。"""


class HtmlNotAvailableError(HtmlError):
    """该 id 无可用 HTML：404 或 200 stub（撤稿/未渲染/abs 回落页）。

    ``status`` 保留线缆状态码（stub 命中时为 200），``detail`` 记判据。
    """

    def __init__(self, arxiv_id: str, *, status: int, detail: str = "") -> None:
        """记录 id + 线缆状态 + 判据。"""
        self.arxiv_id = arxiv_id
        self.status = status
        self.detail = detail
        msg = f"html not available: {arxiv_id} (status={status} {detail})".rstrip()
        super().__init__(msg)


class HtmlFetchError(HtmlError):
    """GET 非 200/404 终态（Fetcher 退避重试后仍失败）。"""

    def __init__(self, arxiv_id: str, *, status: int, detail: str = "") -> None:
        """记录 id + 状态码。"""
        self.arxiv_id = arxiv_id
        self.status = status
        self.detail = detail
        msg = f"html fetch failed: {arxiv_id} (status={status} {detail})".rstrip()
        super().__init__(msg)


# ---------------------------------------------------------------- 块模型


@dataclass(slots=True)
class HtmlBlock:
    """DOM 块。``key`` = 元素稳定 id（缺失合成 ``b{n}``，撞号加 ``#k``）。

    ``context`` 沿用 latex scanner 的 context 词表（para/section/title/
    abstract/caption/keywords/footnote），support 块用自身类名
    （bibitem/figure/listing/authors/dates/equation），``doc_chunks``
    按 :data:`TRANSLATE_CTX` 白名单出 chunk——support 块只占位保序。
    """

    key: str
    context: str
    text: str = ""
    ph: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class HtmlDoc:
    """解析产物：文档序块表 + 全局 ``{token: 原 HTML 片段}`` + 题录。"""

    blocks: list[HtmlBlock]
    ph_map: dict[str, str]
    title: str = ""
    arxiv_id: str = ""


@dataclass(slots=True)
class _InlineCtx:
    """行内抽取共享态：签发器 + 保留字面集 + 全局 ph_map + 迟发 footnote 队列。

    ``issuer`` = 裸名 ``[[TYPE_n]]`` 签发器（单源 :class:`texlate.textutil.
    PhIssuer`——``NOTE``/``TABLE`` 等枚举外 TYPE 不经 ``PhType`` 强类型面）。
    ``reserved`` = 源文自带 ``[[X_n]]`` 字面集——签发撞上会让 reconstruct
    把原文当占位符展开，遇撞顺延编号。``title_el`` = pre-2000 兜底题元
    （``_fallback_title`` 判出）——宿主块内联时整体跳过：title 块独立
    产出，文本不双计入账。
    """

    issuer: PhIssuer
    ph_map: dict[str, str]
    reserved: frozenset[str] = frozenset()
    notes: list[Tag] = field(default_factory=list)
    title_el: Tag | None = None

    def tok(self, typ: str, el: Tag) -> str:
        """元素 → 两侧带空格的 token 串（空格靠 squash 归一）。"""
        return " " + self.issuer.new(typ, str(el), self.ph_map, self.reserved) + " "


# ---------------------------------------------------------------- 行内抽取

#: 不产生文本的 tag（chrome/脚本类——article 内防御，article 外本就不取）
_SKIP_TAGS: Final = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "button",
        "dialog",
        "form",
        "select",
        "nav",
        "footer",
        "header",
    }
)
#: 不产生文本的 class 前缀——ltx_tag=自动编号、ltx_title=标题自成块、
#: ltx_note_mark=脚注标号、TOC/pagination=页内 chrome
_SKIP_CLASS_PREFIX: Final = (
    "ltx_tag",
    "ltx_title",
    "ltx_pagination",
    "ltx_role_newpage",
    "ltx_note_mark",
    "ltx_TOC",
    "ltx_tocentry",
    "ltx_toclist",
)
#: 块级元素——自成块不内联（防嵌套时文本重复入账）
_SKIP_BLOCK_CLS: Final = frozenset(
    {
        "ltx_para",
        "ltx_caption",
        "ltx_bibitem",
        "ltx_figure",
        "ltx_table",
        "ltx_float",
        "ltx_listing",
        "ltx_authors",
        "ltx_dates",
        "ltx_classification",
        "ltx_abstract",
    }
)
#: 行间数学容器 class 前缀（ltx_equation/ltx_equationgroup/ltx_eqn_*）
_EQN_PREFIX: Final = ("ltx_equation", "ltx_eqn")
_MEDIA_TAGS: Final = frozenset(
    {"img", "object", "svg", "video", "audio", "iframe", "embed", "source", "picture"}
)
_NON_TEXT: Final = (Comment, Declaration, Doctype, ProcessingInstruction)


def _classes(el: Tag) -> set[str]:
    return set(el.get("class") or [])


def _attr_str(el: Tag, name: str) -> str:
    """单值属性 → ``str``。

    bs4 ``Tag.get`` 联合类型含 ``AttributeValueList``——那是多值属性
    （``class``/``rel`` 等）的形状，单值属性（``href``/``style``/``id``）
    运行期恒为 ``str``，isinstance 收窄即诚实的静态口径。
    """
    v = el.get(name)
    return v if isinstance(v, str) else ""


def _has_prefix(cls: set[str], prefixes: tuple[str, ...]) -> bool:
    return any(c.startswith(prefixes) for c in cls)


def _inline_text(el: Tag, ctx: _InlineCtx) -> str:
    """元素内联文本：保护元素 token 化，其余按文档序取文本，空白 squash。

    迭代 + 显式栈（栈存子代迭代器）——深层行内嵌套（数千层 span/em）
    不触递归上限：RecursionError 不在 ``HtmlError`` 族内，逃逸会掀翻
    降级链调用方的 ``except HtmlError``。
    """
    parts: list[str] = []
    stack: list[Iterator[PageElement]] = [iter(el.children)]
    while stack:
        node = next(stack[-1], None)
        if node is None:
            stack.pop()
            continue
        child = _inline_node(node, ctx, parts)
        if child is not None:
            stack.append(iter(child.children))
    return " ".join("".join(parts).split())


def _inline_node(  # noqa: C901, PLR0911, PLR0912 -- 行内元素→token/跳过/下钻的分派表，分支即 DOM 契约条目
    node: PageElement, ctx: _InlineCtx, parts: list[str]
) -> Tag | None:
    """单节点分派：token/文本入账返回 ``None``；透明内联容器返回自身。

    由 ``_inline_text`` 显式栈下钻其子代（保文档序、免递归）。
    """
    if isinstance(node, NavigableString):
        if not isinstance(node, _NON_TEXT):
            parts.append(str(node))
        return None
    if not isinstance(node, Tag):
        return None
    name = node.name or ""
    cls = _classes(node)
    if node is ctx.title_el:
        return None  # 兜底题元——title 块已产出，宿主块不吞其文本
    if (
        name in _SKIP_TAGS
        or _has_prefix(cls, _SKIP_CLASS_PREFIX)
        or cls & _SKIP_BLOCK_CLS
    ):
        return None
    if name == "math" or _has_prefix(cls, _EQN_PREFIX):
        parts.append(ctx.tok("MATH", node))
        return None
    if "ltx_cite" in cls:
        parts.append(ctx.tok("CITE", node))
        return None
    if "ltx_note" in cls:
        parts.append(ctx.tok("NOTE", node))
        ctx.notes.append(node)
        return None
    if "ltx_ERROR" in cls:
        parts.append(ctx.tok("CMD", node))
        return None
    if "ltx_tabular" in cls:
        parts.append(ctx.tok("TABLE", node))
        return None
    if name in _MEDIA_TAGS or "ltx_graphics" in cls or "ltx_transformed_outer" in cls:
        parts.append(ctx.tok("GRAPHICS", node))
        return None
    if name == "a":
        href = _attr_str(node, "href")
        if "ltx_url" in cls:
            parts.append(ctx.tok("URL", node))
            return None
        if href.startswith("#"):
            parts.append(ctx.tok("REF", node))
            return None
        # 外链：锚文本照译（latex ``\href{url}{text}`` 文本臂同口径）
    if name in {"ul", "ol"}:
        return None  # item 体自带 ltx_para 块，列表节点不吞文本
    if name == "br":
        parts.append(" ")
        return None
    return node  # 透明内联容器——子代入显式栈续走


# ---------------------------------------------------------------- 块分派

_H_TAGS: Final = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_FIGURE_CLS: Final = frozenset({"ltx_figure", "ltx_table", "ltx_float"})
#: support 祖先——内部只挖 caption/title（latex 保护容器语义：体内不产散文块）
_SUPPORT_ANCESTOR: Final = frozenset(
    {
        "ltx_figure",
        "ltx_table",
        "ltx_float",
        "ltx_listing",
        "ltx_authors",
        "ltx_dates",
        "ltx_bibitem",
        "ltx_pagination",
        "ltx_TOC",
    }
)
_TITLE_SUFFIX_RX: Final = re.compile(r"ltx_title_(\w+)")
#: pre-2000 题录容器——老转换器把 \title 渲成容器内放大字体的 span
_TITLEBOX_CLS: Final = frozenset({"ltx_titlepage", "ltx_logical-block"})
_FONT_PCT_RX: Final = re.compile(r"font-size:\s*(\d+(?:\.\d+)?)\s*%")
#: 容器内放大字体阈值（%）——题面 120%/144%，摘要等缩小体 90% 不入选
_TITLE_FONT_PCT: Final = 100.0
#: ``ltx_title_*`` 后缀 → latex 风 context（normalize_kind 直接消费）
_TITLE_CTX: Final = {
    "document": "title",
    "abstract": "section",
    "bibliography": "section",
    "classification": "section",
    "appendix": "section",
    "section": "section",
    "subsection": "subsection",
    "subsubsection": "subsubsection",
    "paragraph": "paragraph",
    "subparagraph": "subparagraph",
    "chapter": "chapter",
    "part": "part",
    "theorem": "paragraph",
    "proof": "paragraph",
}
#: 产 chunk 的 context 白名单（support context 不在列）
TRANSLATE_CTX: Final = frozenset(
    {
        "para",
        "item",
        "section",
        "subsection",
        "subsubsection",
        "paragraph",
        "subparagraph",
        "chapter",
        "part",
        "title",
        "abstract",
        "caption",
        "keywords",
        "footnote",
    }
)


def _block_kind(el: Tag) -> str:  # noqa: C901, PLR0911 -- 块类分派表，每条 return 一类 DOM 契约
    """元素 → 块类名（"" = 非块，透明容器其子孙自会被枚举到）。"""
    name = el.name or ""
    cls = _classes(el)
    if name == "div" and "ltx_para" in cls:
        return "para"
    if name == "p" and "ltx_p" in cls:
        return "p"  # 裸 p（abstract/theorem 内非 ltx_para 包裹者）
    if name in _H_TAGS and "ltx_title" in cls:
        return "title"
    if name == "figcaption" and "ltx_caption" in cls:
        return "caption"
    if name == "li" and "ltx_bibitem" in cls:
        return "bibitem"
    if name == "figure" and cls & _FIGURE_CLS:
        return "figure"
    if name == "div" and "ltx_listing" in cls:
        return "listing"
    if name == "div" and "ltx_authors" in cls:
        return "authors"
    if name == "div" and "ltx_dates" in cls:
        return "dates"
    if name == "div" and "ltx_classification" in cls:
        return "keywords"
    if name == "table" and _has_prefix(cls, _EQN_PREFIX):
        return "equation"
    return ""


def _inside_support(el: Tag) -> bool:
    """任一祖先命中 support 容器——latex 保护 env 语义（体不产块）。"""
    return any(
        isinstance(p, Tag) and _classes(p) & _SUPPORT_ANCESTOR for p in el.parents
    )


def _title_ctx(cls: set[str]) -> str:
    for c in cls:
        m = _TITLE_SUFFIX_RX.fullmatch(c)
        if m:
            return _TITLE_CTX.get(m.group(1), "section")
    return "section"


def _block_ph(text: str, ph_map: dict[str, str]) -> dict[str, str]:
    """块文本内出现的 token → 片段（``chunk_to_in`` 同口径裁剪）。"""
    return {t: ph_map[t] for t in PH_RX.findall(text) if t in ph_map}


def _fallback_title(art: Tag) -> Tag | None:
    r"""pre-2000 兜底题元（无 ``h1.ltx_title_document`` 时启用）。

    首个 ``ltx_titlepage``/``ltx_logical-block`` 容器内首个 ``font-size``
    超 100% 的元素即文档标题——老转换器把 ``\title`` 渲成容器内放大字体
    而非 ltx_title*。无容器或无放大字体 → ``None``。
    """
    if art.find("h1", class_="ltx_title_document") is not None:
        return None
    for box in art.find_all("div"):
        if not _classes(box) & _TITLEBOX_CLS:
            continue
        for el in (d for d in box.descendants if isinstance(d, Tag)):
            m = _FONT_PCT_RX.search(_attr_str(el, "style"))
            if m and float(m.group(1)) > _TITLE_FONT_PCT:
                return el
    return None


def _enumerate_blocks(  # noqa: C901, PLR0915 -- 块分派 + support/嵌套闸 + footnote 排放，语句即枚举规则
    art: Tag, ctx: _InlineCtx
) -> Iterator[tuple[Tag, str, str, str, dict[str, str]]]:
    """``article.ltx_document`` 内按文档序产 ``(元素，key, context, text, ph)``。

    唯一枚举真源——``parse_arxiv_html`` 与 ``marked_html`` 共用：key 派生
    （元素 ``id`` 优先，缺失合成 ``b{n}``，撞号 ``#k``）与 footnote 排放
    序必须两侧一致，否则 ``data-chunk`` 锚与块表错位。``_inline_text``
    的 note 排队副作用是枚举语义的一部分，标注用途也照跑。
    """
    seen: set[str] = set()
    synth = 0
    ctx.title_el = _fallback_title(art)

    def key_of(el: Tag) -> str:
        nonlocal synth
        base = _attr_str(el, "id")
        if not base:
            synth += 1
            base = f"b{synth}"
        if base in seen:
            k = 2
            while f"{base}#{k}" in seen:
                k += 1
            base = f"{base}#{k}"
        seen.add(base)
        return base

    def drain_notes() -> Iterator[tuple[Tag, str, str, str, dict[str, str]]]:
        # 抽取期排队的 footnote：紧跟宿主块，note 体自身可再产 token/note
        while ctx.notes:
            note = ctx.notes.pop(0)
            content = note.find(class_="ltx_note_content") or note
            text = _inline_text(content, ctx)
            yield note, key_of(note), "footnote", text, _block_ph(text, ctx.ph_map)

    for el in (d for d in art.descendants if isinstance(d, Tag)):
        if el is ctx.title_el:
            # pre-2000 兜底题元——元素本身非块类，在自身文档序位产 title 块
            text = _inline_text(el, ctx)
            yield el, key_of(el), "title", text, _block_ph(text, ctx.ph_map)
            yield from drain_notes()
            continue
        kind = _block_kind(el)
        if not kind:
            continue
        if _inside_support(el):
            if kind not in {"caption", "title"}:
                continue  # 保护容器内只挖 caption/title
        elif kind in {"p", "equation"} and el.find_parent(class_="ltx_para"):
            continue  # ltx_para 抽取已覆盖（p 直子 / 行间公式 token）
        context = kind
        text = ""
        if kind == "para":
            text = _inline_text(el, ctx)
        elif kind == "p":
            context = "abstract" if el.find_parent(class_="ltx_abstract") else "para"
            text = _inline_text(el, ctx)
        elif kind == "title":
            context = _title_ctx(_classes(el))
            text = _inline_text(el, ctx)
        elif kind == "caption":
            context = "caption"
            text = _inline_text(el, ctx)
        elif kind == "keywords":
            context = "keywords"
            text = _inline_text(el, ctx)
        yield el, key_of(el), context, text, _block_ph(text, ctx.ph_map)
        yield from drain_notes()


def _article_ctx(html: str, arxiv_id: str) -> tuple[BeautifulSoup, Tag, _InlineCtx]:
    """soup→``article.ltx_document``→``_InlineCtx`` 公共前奏。

    ``parse_arxiv_html`` 与 ``marked_html`` 同源——stub 判据 detail 串
    单源，两侧枚举的是同一棵 DOM（marked 的 ``data-chunk`` 锚写在返回
    的 soup 上）。无 ``article.ltx_document`` → ``HtmlNotAvailableError``。
    """
    soup = BeautifulSoup(html, "lxml")
    art = soup.find("article", class_="ltx_document")
    if art is None:
        raise HtmlNotAvailableError(
            arxiv_id, status=HTTPStatus.OK, detail="no article.ltx_document"
        )
    ctx = _InlineCtx(PhIssuer(), {}, frozenset(PH_RX.findall(art.get_text())))
    return soup, art, ctx


def parse_arxiv_html(html: str, *, arxiv_id: str = "") -> HtmlDoc:
    """HTML 全文 → 文档序块模型。

    无 ``article.ltx_document`` → ``HtmlNotAvailableError``（stub/回落页
    与 fetch 侧同型判据，parse 单用也安全）。
    """
    _soup, art, ctx = _article_ctx(html, arxiv_id)
    blocks = [
        HtmlBlock(key, context, text, ph)
        for _el, key, context, text, ph in _enumerate_blocks(art, ctx)
    ]
    # ctx.title_el 已在 _enumerate_blocks 枚举时判出（同 h1 短路 + titlepage
    # 容器扫描）——直接复用，不再第二遍扫 DOM
    title_el = art.find("h1", class_="ltx_title_document") or ctx.title_el
    title = (
        " ".join(title_el.get_text(" ", strip=True).split())
        if title_el is not None
        else ""
    )
    return HtmlDoc(blocks, ctx.ph_map, title, arxiv_id)


def marked_html(html: str, *, arxiv_id: str = "") -> str:
    """同源枚举给每个块元素注 ``data-chunk=block.key`` → 序列化全文。

    emit 锚点：en/zh 产物经同一份标记 DOM 派生，``[data-chunk]`` 值与
    ``HtmlDoc.blocks``/chunks 行 ``chunk_id`` 严格 1:1（DomPane 的
    PageGeom 契约）。无 ``article.ltx_document`` → ``HtmlNotAvailableError``。
    """
    soup, art, ctx = _article_ctx(html, arxiv_id)
    for el, key, _context, _text, _ph in _enumerate_blocks(art, ctx):
        el["data-chunk"] = key
    return str(soup)


# ---------------------------------------------------------------- chunk 出口


def doc_chunks(doc: HtmlDoc, *, id_prefix: str = "") -> list[ChunkIn]:
    """``HtmlDoc`` → ``XlatPipeline`` 输入块。

    白名单 context + 非空文本才产块；``kind`` 经 ``normalize_kind`` 归一
    （与 latex scanner chunk 同族——para/caption/section_title/abstract），
    ``ph_fragments`` 携块内 token→片段武装抄回修复臂。
    """
    out: list[ChunkIn] = []
    for b in doc.blocks:
        if b.context not in TRANSLATE_CTX or not b.text.strip():
            continue
        out.append(
            ChunkIn(
                chunk_id=f"{id_prefix}{b.key}",
                content=b.text,
                kind=normalize_kind(b.context),
                ph_fragments=b.ph or None,
            )
        )
    return out


def reinsert(text: str, ph_map: Mapping[str, str]) -> str:
    """译文中 ``[[TYPE_n]]`` 回插原 HTML 片段。

    单趟 ``sub``——片段内部若含类 token 字面不级联展开。
    """
    return PH_RX.sub(lambda m: ph_map.get(m.group(0), m.group(0)), text)


# ---------------------------------------------------------------- 获取


def fetch_html(
    arxiv_id: str, *, version: int | None = None, fetcher: Fetcher | None = None
) -> str:
    """GET ``https://arxiv.org/html/{id}[vN]`` 取 HTML 全文。

    挂 ``Fetcher`` 而非裸 client：同域同限流域（pacing/断路器/日预算）、
    ``_request`` 退避重试、``_across_hosts`` export 镜像故障转移——与
    e-print 获取同一纪律。``fetcher=None`` 自建即用即关。
    """
    base, ver = req_base_ver(arxiv_id, version)
    own = fetcher is None
    f = fetcher or Fetcher()
    try:
        resp = f.get_path(f"/html/{base}{f'v{ver}' if ver else ''}")
    finally:
        if own:
            f.close()
    if resp.status_code == HTTPStatus.NOT_FOUND:
        raise HtmlNotAvailableError(arxiv_id, status=HTTPStatus.NOT_FOUND)
    if resp.status_code != HTTPStatus.OK:
        raise HtmlFetchError(arxiv_id, status=resp.status_code)
    text = resp.text
    if "ltx_document" not in text:
        raise HtmlNotAvailableError(
            arxiv_id, status=HTTPStatus.OK, detail="stub:no_ltx_document"
        )
    return text
