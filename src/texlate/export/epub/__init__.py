"""EPUB 双语插译管线（doc-formats.md §2——bbm 蓝图 stdlib 自拆，不碰 EbookLib/AGPL）。

七步照抄 ``bilingual_book_maker`` 加固 fork 的语义、剪成 v1 面：

1. 拆包读入（``load``）：stdlib zipfile + DRM 预检（``rights.check_epub``）
   + fixed-layout 拒翻。
2. 文档枚举（``load``）：manifest ``application/xhtml+xml`` 全集 = spine 序
   + spine 外 nav/封面追加在尾；NCX 不进翻译流但翻 ``navLabel/text``；其余
   zip 成员逐字节照抄（``encryption.xml`` 与混淆字体免处理的前提：不动
   ``dc:identifier``）。
3. 文本提取（``units``）：run 制——文本节点归最近 block 祖先，嵌套 block
   与非 ``<pre>`` ``<br>`` 切 run；NON_CONTENT/ruby/exclude/pagebreak/
   hidden 跳过；短保护行内元素变 ``[[TAG_n]]`` marker。
4. 插译（``insert``）：原文节点不动，译文克隆插后；受限容器
   （SINGLETON/nav）改内部追加 ``<br/><span>``；多 run owner（如
   ``<div>前文<p>…</p>后文</div>``）锚定插。
5. marker 协议：防碰撞分配 → 宽容调和 → 写回克隆（``export.markers``）。
6. 批量/对齐（``driver``）：``XlatPipeline`` 原样复用（``[n]`` 协议 +
   阶梯 + StateStore 断点）——``chunk_id`` =
   ``epub:{doc}:{unit}:{sha256(text)[:16]}`` 的 job_id，键控断点天然免疫
   bbm 位置槽位的错配问题。
7. 写回（``serialize``）：``mimetype`` 首条 ZIP_STORED，其余按原
   infolist 序 ZIP_DEFLATED。

包结构：``tags`` DOM 词法常量 → ``model`` 数据结构 → ``load`` 拆包 →
``units`` 单元枚举 → ``insert`` 插译 → ``sanitize`` DOM 净化 →
``serialize`` 写回 → ``driver`` 全链驱动；本 ``__init__`` 是唯一对外面。

v1 明确不做（doc-formats.md §5 边界一览）：单译模式、配对 marker、CSS 级联 display 解析
（只查内联 ``display:none``+``hidden`` 属性）、披露页、epubcheck 全量对账、
only/exclude_filelist。
"""

from __future__ import annotations

from .driver import translate_epub
from .insert import insert_translation
from .load import _EPUB_INFLATED_MAX, _EPUB_MEMBER_MAX, load_epub
from .model import EpubBook, Unit
from .sanitize import _sanitize_dom
from .serialize import book_soups, save_epub
from .units import iter_units

__all__ = [
    "_EPUB_INFLATED_MAX",
    "_EPUB_MEMBER_MAX",
    "EpubBook",
    "Unit",
    "_sanitize_dom",
    "book_soups",
    "insert_translation",
    "iter_units",
    "load_epub",
    "save_epub",
    "translate_epub",
]
