"""EPUB DOM 词法常量：tag 集合与各阶段共享的小型词法表。

``BLOCK_TAGS`` 是 units（owner 判定）与 insert（锚定落点）共用的唯一事实源；
其余集合按使用面归位——content 判定族供 units 枚举，SINGLETON 供 insert
受限容器分派。
"""

from __future__ import annotations

import re

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
NOTE_EPUB_TYPES = frozenset(
    ["footnote", "endnote", "rearnote", "note", "footnotes", "endnotes"]
)
NOTE_ROLES = frozenset(["doc-footnote", "doc-endnote"])

#: 送模型前排除的 tag（送文本不含其内容，节点本身留在 DOM）
DEFAULT_EXCLUDE_TAGS: tuple[str, ...] = ("sup", "code")

CSS_DISPLAY_RE = re.compile(r"(?:^|;)\s*display\s*:\s*([\w-]+)", re.IGNORECASE)

#: ``units._runs_for_owner`` 的 marker 哨兵 ``{seq}`` 所用的两个 PUA
#: 码点——源文逐字印着它们时必须剥除（防 ``text.replace`` 先命中字面位）
PUA_SENTINEL_RE = re.compile("[]")
