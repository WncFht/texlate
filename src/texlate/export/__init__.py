"""EPUB/DOCX 双语插译导出（doc-formats.md spec；bbm 蓝图照抄，不碰 EbookLib/AGPL）。

输入是上传的 ``.epub``/``.docx`` 文档（server ``/api/upload`` 的 docx/epub
路由面）；输出是原文段落后跟译文的双语同构文档。翻译编排复用
``xlat.XlatPipeline``——``[n]`` 批量协议、retry 阶梯、``StateStore`` 断点
全部零改动。

用法::

    from texlate.export import export_document
    report = export_document(Path("book.epub"), Path("book.zh.epub"), translator)
"""

from __future__ import annotations

import zipfile
import zlib
from pathlib import Path
from typing import TYPE_CHECKING

from .common import (
    DrmError,
    ExportError,
    ExportReport,
    FixedLayoutError,
    GlossaryArg,
    MalformedEpubError,
    UnsupportedFormatError,
)
from .docx import translate_docx
from .epub import translate_epub

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.xlat.pipeline import ChunkResult, Translator

__all__ = [
    "DrmError",
    "ExportError",
    "ExportReport",
    "FixedLayoutError",
    "GlossaryArg",
    "MalformedEpubError",
    "UnsupportedFormatError",
    "export_document",
    "export_docx",
    "export_epub",
    "sniff_format",
]

#: mimetype 嗅探有界读上限——``zf.read`` 会把整个成员解进内存，
#: 上传 EPUB 是不可信面（inflate 炸弹），嗅探只用头 64B
_SNIFF_HEAD_BYTES = 64


def sniff_format(path: Path) -> str | None:
    """Zip 内容嗅探：``mimetype``/``word/document.xml`` → ``"epub"``/``"docx"``。

    后缀只作参考——内容为准（与 arxiv 层 sniff 同纪律）。
    """
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "mimetype" in names:
                # 有界读：嗅探只用头 ``_SNIFF_HEAD_BYTES`` B——zf.read 会把
                # 整个成员解进内存，上传 EPUB 是不可信面（inflate 炸弹）
                with zf.open("mimetype") as fp:
                    head = fp.read(_SNIFF_HEAD_BYTES).strip()
                if head == b"application/epub+zip":
                    return "epub"
            if "word/document.xml" in names:
                return "docx"
    except (
        OSError,
        ValueError,
        RuntimeError,
        NotImplementedError,
        zipfile.BadZipFile,
        zlib.error,  # 成员 deflate 流中段坏——解压失败同属"无法识别"
    ):
        # 加密/未知压缩方法的条目也会走到这里——嗅探失败即"无法识别"；
        # ValueError 面 = 内嵌 NUL 的病态路径（io.open 抛，非 OSError 子类）
        pass
    return None


def export_epub(  # noqa: PLR0913 -- 公共 API 面，关键字参数
    src: Path,
    dst: Path,
    translator: Translator,
    *,
    target_lang: str = "zh-CN",
    state_dir: Path | None = None,
    glossary: GlossaryArg | None = None,
    on_result: Callable[[ChunkResult], None] | None = None,
) -> ExportReport:
    """EPUB → 双语 EPUB（``epub.translate_epub`` 的转调包装）。"""
    return translate_epub(
        src,
        dst,
        translator,
        target_lang=target_lang,
        state_dir=state_dir,
        glossary=glossary,
        on_result=on_result,
    )


def export_docx(  # noqa: PLR0913 -- 公共 API 面，关键字参数
    src: Path,
    dst: Path,
    translator: Translator,
    *,
    target_lang: str = "zh-CN",
    state_dir: Path | None = None,
    glossary: GlossaryArg | None = None,
    on_result: Callable[[ChunkResult], None] | None = None,
) -> ExportReport:
    """DOCX → 双语 DOCX（``docx.translate_docx`` 的转调包装）。"""
    return translate_docx(
        src,
        dst,
        translator,
        target_lang=target_lang,
        state_dir=state_dir,
        glossary=glossary,
        on_result=on_result,
    )


def export_document(  # noqa: PLR0913 -- 公共 API 面，关键字参数
    src: Path,
    dst: Path | None,
    translator: Translator,
    *,
    target_lang: str = "zh-CN",
    state_dir: Path | None = None,
    glossary: GlossaryArg | None = None,
    on_result: Callable[[ChunkResult], None] | None = None,
) -> ExportReport:
    """按内容嗅探分派 EPUB/DOCX；``dst`` 缺省 ``{stem}_bilingual.{ext}``。

    ``{ext}`` 沿用 ``src`` 后缀而非嗅探结果——嗅探只选引擎不改写文件名
    （``odd.bin`` 装的 EPUB 字节产 ``odd_bilingual.bin``，pinned 于
    ``test_suffix_ignored_content_sniffed``）。
    ``glossary`` 三形皆可：``Glossary`` 实例 / ``{en: zh}`` 平表 /
    yaml|csv 路径（归一见 ``common.coerce_glossary``）。
    """
    src = Path(src)
    fmt = sniff_format(src)
    if fmt is None:
        msg = f"无法识别的导出格式（非 epub/docx zip）: {src.name}"
        raise UnsupportedFormatError(msg)
    if dst is None:
        dst = src.with_name(f"{src.stem}_bilingual{src.suffix}")
    if fmt == "epub":
        return export_epub(
            src,
            dst,
            translator,
            target_lang=target_lang,
            state_dir=state_dir,
            glossary=glossary,
            on_result=on_result,
        )
    return export_docx(
        src,
        dst,
        translator,
        target_lang=target_lang,
        state_dir=state_dir,
        glossary=glossary,
        on_result=on_result,
    )
