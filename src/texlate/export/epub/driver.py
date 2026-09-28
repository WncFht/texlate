"""EPUB 全链驱动：load → units → XlatPipeline → insert → serialize → save。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from lxml import etree  # ty: ignore[unresolved-import]  # 编译扩展无 stub，同 docx.py

from texlate.export.common import (
    ApplyCounts,
    ExportReport,
    GlossaryArg,
    MalformedEpubError,
    apply_translations,
    run_export,
    safe_language,
)
from texlate.export.filters import sanitize_xml_text
from texlate.export.markers import reconcile_markers
from texlate.xlat.pipeline import ChunkIn, ChunkResult

from .insert import insert_translation
from .load import load_epub
from .serialize import _inject_css, _restamp_opf, _serialize_soup, book_soups, save_epub
from .units import iter_units

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from texlate.xlat.pipeline import Translator

log = logging.getLogger(__name__)

_PIPELINE_VERSION = "export-epub-1"

#: unit kind 一律 ``para``——``_KIND_CLAUSES`` 的合法键是 LaTeX 语境（xlat/
#: 不属本模块），EPUB 散文用 para 的最宽条款 + 占位符契约已够


def translate_epub(  # noqa: PLR0913 -- 驱动主链：公共 API 参数面 + apply/flush 闭包，语句数即编排步骤数
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
    lang = safe_language(target_lang)
    if lang is None:
        log.warning("target_lang 非 BCP47 形态，跳过全部语言章: %r", target_lang)
    try:
        soups = book_soups(book)
        units = list(iter_units(book, soups))
    except RecursionError as e:
        msg = f"EPUB 文档嵌套过深，无法解析: {src.name}"
        raise MalformedEpubError(msg) from e

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
        _restamp_opf(book, lang)
        for path, soup in soups.items():
            book.members[path] = _serialize_soup(soup)
        if book.ncx_path and ncx_root is not None:
            book.members[book.ncx_path] = sanitize_xml_text(
                etree.tostring(ncx_root, encoding="utf-8", xml_declaration=True).decode(
                    "utf-8"
                )
            ).encode("utf-8")
        save_epub(dst, book)

    def _apply(results: Mapping[str, ChunkResult]) -> ApplyCounts:
        # preview 与 insert_translation 同口径（调和+净化）；ncx 单元无条件
        # 写回故不参与 unchanged 预判（见 common.apply_translations）
        return apply_translations(
            units,
            results,
            preview_zh=lambda u, r: sanitize_xml_text(
                reconcile_markers(u.text, r.translation, issued=u.markers)
            ),
            insert=lambda u, r, zh: insert_translation(
                u, r.translation, lang or "", zh=zh
            ),
            counts_unchanged=lambda u: u.ncx_text is None,
        )

    chunks = [ChunkIn(u.job_id, u.text, u.kind) for u in units]
    # 枚举后段（state/pipeline/清理/报告）与 DOCX 臂逐行同构——共享 common.run_export
    return run_export(
        src,
        dst,
        translator,
        lang=lang,
        state_dir=state_dir,
        glossary=glossary,
        on_result=on_result,
        chunks=chunks,
        apply_fn=_apply,
        save_fn=_flush_and_save,
        err_cls=MalformedEpubError,
        fmt="epub",
        documents=len(book.doc_paths),
        pipeline_version=_PIPELINE_VERSION,
    )
