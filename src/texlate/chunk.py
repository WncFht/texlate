r"""xlat 输入契约的低层共享位（refactor-sweep 边界修复）。

``ChunkIn`` 是 ``xlat.pipeline`` 的输入块类型；``KIND_ALIASES``/
``normalize_kind`` 是 scanner context → 六 kind 的归一表。消费方横跨层级：
``xlat.pipeline``（编排本家）、``latex`` scanner 适配（``chunk_to_in``）、
``arxiv.html``（HTML 降级链出块）、``e2e``/worker——arxiv 是底层获取层，
向上 import ``latex``/``xlat`` 即成倒挂，故契约沉于顶层共享位
（``texlog``/``repair`` 同款模式）。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["KIND_ALIASES", "ChunkIn", "normalize_kind"]


@dataclass
class ChunkIn:
    """xlat 输入块（scanner Chunk 的轻量映射：`context` → `kind` 归一）。"""

    chunk_id: str
    content: str
    kind: str = "para"
    #: ``{ph_token: 原文 fragment}``——recover_copied_tokens 的判定底账；
    #: 给了才启用阶梯的抄回修复臂（None = 不武装，行为同旧版）。
    ph_fragments: dict[str, str] | None = None


#: 上游 scanner context → xlat kind 归一表（docs/spec/latex-pipeline.md Chunk.context → docs/spec/compile.md 六 kind）
KIND_ALIASES: dict[str, str] = {
    "para": "para",
    "item": "para",
    "caption": "caption",
    "subcaption": "caption",
    "captionof": "caption",
    "title": "caption",
    "subtitle": "caption",
    "keywords": "caption",
    "section": "section_title",
    "subsection": "section_title",
    "subsubsection": "section_title",
    "chapter": "section_title",
    "section_title": "section_title",
    # 以下均为 CHUNK_ARG_NAMES 里的节题命令——\paragraph{} 的 arg 是 run-in
    # 标题，不是正文段（context="paragraph" 消歧后专指该命令，不再兼作正文 context）
    "paragraph": "section_title",
    "subparagraph": "section_title",
    "part": "section_title",
    "sect": "section_title",
    "subsect": "section_title",
    "abstract": "abstract",
    "abst": "abstract",
    # ``\author{...}`` 前置发射的 context——人名/机构混合内容走 para 条款
    "author": "para",
    "table_text": "table_text",
    "table": "table_text",
    "env_text": "env_text",
}


def normalize_kind(context: str) -> str:
    """Scanner context → 六 kind 之一；未知一律归 `para`（最宽条款兜底）。"""
    return KIND_ALIASES.get(context.strip().lower(), "para")
