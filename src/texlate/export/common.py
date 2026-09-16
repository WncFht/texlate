"""export 包共享件：错误族 + 统一报告 + ``glossary`` 入参归一 + 双驱骨架。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from texlate.xlat.glossary import Glossary, TermEntry
from texlate.xlat.pipeline import ChunkIn, ChunkResult, XlatPipeline
from texlate.xlat.placeholders import collect_doc_placeholders

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.xlat.pipeline import Translator
    from texlate.xlat.state import StateStore

log = logging.getLogger(__name__)


class ExportError(Exception):
    """导出管线基错。"""


class UnsupportedFormatError(ExportError):
    """输入不是可识别的 epub/docx。"""


class DrmError(ExportError):
    """EPUB 声明了技术保护措施（``rights.check_epub`` 判定）。"""


class FixedLayoutError(ExportError):
    """``rendition:layout=pre-paginated`` 的书插译必破版式——检测后拒翻。"""


class MalformedEpubError(ExportError):
    """zip/container/OPF 结构不合法。"""


@dataclass
class ExportReport:
    """EPUB/DOCX 导出统一报告。

    ``units`` = 送编排层的单元数（占位/纯装饰段不列入）；``translated`` =
    实际插译段数；``unchanged`` = 译文逐字同原文（echo/回退，不重复插入）；
    ``skipped``/``fault`` = 编排层三振回退原文/真失败。
    """

    src: Path
    dst: Path
    format: str
    units: int
    translated: int
    unchanged: int
    skipped: int
    fault: int
    documents: int
    warnings: list[str] = field(default_factory=list)


#: ``export_*``/``translate_*`` 的 ``glossary`` 入参并集——归一处 ``coerce_glossary``。
GlossaryArg = Glossary | Mapping[str, str] | str | Path


def coerce_glossary(glossary: GlossaryArg | None) -> Glossary | None:
    """``glossary`` 便利入参 → ``Glossary | None``（``XlatPipeline`` 契约形）。

    - ``None``/``Glossary`` → 原样（``None`` = 无术语层，行为同旧版）；
    - ``Mapping`` → 逐条成 ``user`` 层 ``TermEntry``——内存输入不隐式叠
      文件层（``~/.texlate/glossary.yaml``/``default.csv`` 不混入），空 zh
      同文件层语义落保原语；
    - ``str``/``Path`` → ``Glossary.load(user_path=…)``——与 tex 主链
      ``worker._make_glossary`` 同形（user 表叠内建 default 层；``~`` 展开）；
    - 路径缺席/不可读/格式非法 → ``ExportError``：``Glossary.load`` 对缺席
      ``user_path`` 静默跳过（分层 API 语义），公开入口先验存在——
      否则用户表又是静默丢弃。
    """
    if glossary is None or isinstance(glossary, Glossary):
        return glossary
    if isinstance(glossary, Mapping):
        return Glossary(
            terms={
                en: TermEntry(en, str(zh).strip() or en, "user")
                for k, zh in glossary.items()
                if (en := str(k).strip())
            }
        )
    path = Path(glossary).expanduser()
    if not path.is_file():
        msg = f"glossary 文件不可读: {path}"
        raise ExportError(msg)
    try:
        return Glossary.load(user_path=path)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as e:
        msg = f"glossary 加载失败: {path} ({e})"
        raise ExportError(msg) from e


# ---------------------------------------------------------------- 双驱骨架


@dataclass
class ApplyCounts:
    """``apply_fn`` 计数包：插译成功/逐字同原文/真失败 + 插译警告。"""

    translated: int = 0
    unchanged: int = 0
    fault: int = 0
    warnings: list[str] = field(default_factory=list)


def drive_pipeline(  # noqa: PLR0913 -- 骨架即双驱共享参数面（chunks/翻译/断点/回调/apply/save 七件）
    chunks: list[ChunkIn],
    *,
    translator: Translator,
    store: StateStore,
    glossary: GlossaryArg | None,
    on_result: Callable[[ChunkResult], None] | None,
    apply_fn: Callable[[Mapping[str, ChunkResult]], ApplyCounts],
    save_fn: Callable[[int], None],
) -> tuple[dict[str, ChunkResult], ApplyCounts]:
    """``XlatPipeline`` 全编排 + 半成品落盘——EPUB/DOCX 两驱动共用骨架。

    ``apply_fn`` 把结果表插进文档模型返回计数；``save_fn`` 按插译成功数出包。
    Ctrl-C/异常按 ``store`` 已落盘译文回放 apply+save 后再抛（bbm
    ``_save_temp_book`` 语义——半成品双语件总比没有强）。返回
    ``(结果表, 计数)`` 供调用方组 ``ExportReport``。
    """
    g = coerce_glossary(glossary)
    for ph in collect_doc_placeholders(c.content for c in chunks):
        g = g or Glossary()
        g.terms.setdefault(ph, TermEntry(ph, ph, "placeholder"))
    pipe = XlatPipeline(
        translator,
        state=store,
        glossary=g,
        on_result=on_result,
    )
    try:
        results = {r.chunk_id: r for r in asyncio.run(pipe.run(chunks))}
    except BaseException:
        _completed, recs = store.load()
        partial = {
            cid: ChunkResult(
                chunk_id=cid,
                source=rec.source,
                translation=rec.translation,
                kind=rec.kind,
                status=rec.status,
            )
            for cid, rec in recs.items()
        }
        try:
            save_fn(apply_fn(partial).translated)
        except Exception:
            log.exception("partial export save failed")
        raise
    counts = apply_fn(results)
    save_fn(counts.translated)
    return results, counts
