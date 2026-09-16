"""export 包共享件：错误族 + 统一报告 + ``glossary`` 入参归一。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from texlate.xlat.glossary import Glossary, TermEntry


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
