"""EPUB 管线的数据结构：拆包结果 ``EpubBook`` 与翻译单元 ``Unit``。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag
    from lxml.etree import _Element  # ty: ignore[unresolved-import]  # 编译扩展无 stub


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
    """一个翻译单元（doc-formats.md §2 Unit 契约的 DOM 版）。

    ``markers``: ``token → 源元素 ``；``run_nodes`` 是该 run 的已拥有文本节点
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
