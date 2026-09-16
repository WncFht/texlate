"""export 包共享件：错误族 + 统一报告。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


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
