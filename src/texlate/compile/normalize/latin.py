r"""compile.normalize.latin — 显式 Type1 拉丁字体 → Unicode 等价物叶 (compile.normalize 域缝叶)。

``\usefont{OT1|T1|LY1}{ptm}`` → ``{TU}{texlate-ptm}``、``\fontfamily{ptm}``
前补 ``\fontencoding{TU}`` 并加前缀；``_latin_family_block`` 生成 TeX Gyre
``\newfontfamily`` 定义块；``prepare_legacy_latin_fonts`` 工程级编排
（不改作者默认字体）。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from texlate.compile.mask import (
    TEX_SOURCE_SUFFIXES,
    apply_edits,
    group_end,
    visible_tex,
)
from texlate.compile.transcode import _iter_files, _read_tex
from texlate.textutil import BEGIN_DOC_RX, DOCCLASS_OPTS_RX

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------- 9. OT1/T1/LY1 → TU
LEGACY_LATIN_FAMILIES = {
    "ptm": "texgyretermes",
    "phv": "texgyreheros",
    "pcr": "texgyrecursor",
    "ppl": "texgyrepagella",
    "pbk": "texgyrebonum",
    "pnc": "texgyreschola",
    "pag": "texgyreadventor",
}


def _latin_family_block(needed: set[str]) -> str:
    r"""生成 `\newfontfamily` 定义块（暂存/恢复作者默认字体族）。"""
    definitions = []
    for name in sorted(needed):
        font = LEGACY_LATIN_FAMILIES[name]
        definitions.append(
            rf"\newfontfamily\TeXlateLatin{name}{{{font}-regular.otf}}"
            rf"[NFSSFamily=texlate-{name},BoldFont={font}-bold.otf,"
            rf"ItalicFont={font}-italic.otf,BoldItalicFont={font}-bolditalic.otf,"
            rf"SlantedFont={font}-italic.otf,BoldSlantedFont={font}-bolditalic.otf]"
        )
    return (
        "\n% texlate: Unicode equivalents for explicit legacy Latin families\n"
        r"\let\TeXlateSavedRmDefault\rmdefault" + "\n"
        r"\let\TeXlateSavedSfDefault\sfdefault" + "\n"
        r"\let\TeXlateSavedTtDefault\ttdefault" + "\n"
        r"\RequirePackage[no-math]{fontspec}" + "\n" + "\n".join(definitions) + "\n"
        r"\let\rmdefault\TeXlateSavedRmDefault" + "\n"
        r"\let\sfdefault\TeXlateSavedSfDefault" + "\n"
        r"\let\ttdefault\TeXlateSavedTtDefault" + "\n"
        "% texlate: end legacy Latin families\n"
    )


def _latin_font_edits(
    visible: str,
    usefont: re.Pattern[str],
    family: re.Pattern[str],
    custom_families: set[str],
    needed: set[str],
) -> list[tuple[int, int, str]]:
    r"""单文件内收集 `\usefont`/`\fontfamily` 的 Type1→TU 改写编辑。"""
    edits = []
    for match in usefont.finditer(visible):
        needed.add(match[2])
        edits.extend(
            [
                (*match.span(1), "TU"),
                (*match.span(2), "texlate-" + match[2]),
            ]
        )
    for match in family.finditer(visible):
        name = match[1]
        if name in custom_families:
            continue
        needed.add(name)
        edits.extend(
            [
                (*match.span(1), "texlate-" + name),
                (match.start(), match.start(), r"\fontencoding{TU}"),
            ]
        )
    return edits


# ---------------------------------------------------------------- 树遍历/读件共享低层件
# ``_iter_files``/``_read_tex_path``/``_read_tex`` 单源在 ``transcode.py``
# （import 回引，``judge.py``/``mainfile.py``/``layout.py``/``marks.py`` 经
# ``normalize`` 门面再导出仍可达）：``suffixes=None`` 不按后缀过滤——按文件名
# 判定或排除式 catch-all 面用；``skip_hidden=False`` 留给统计口径须含隐藏件
# 的调用方（``_normalize_tex_files`` 的 ``stats["files"]`` 先计后跳）。
def _tex_sources(root: Path) -> dict[Path, str]:
    """工程内非隐藏 tex 源 → 解码文本；软链/不可读件/tar 伪装件跳过。"""
    sources: dict[Path, str] = {}
    for path in _iter_files(root, TEX_SOURCE_SUFFIXES):
        text = _read_tex(path)
        if text is not None:
            sources[path] = text
    return sources


def prepare_legacy_latin_fonts(root: Path) -> int:
    r"""显式 Type1 拉丁字体选择 → Unicode 等价物（TeX Gyre）。

    `\usefont{OT1|T1|LY1}{ptm}` → `{TU}{texlate-ptm}`；`\fontfamily{ptm}` →
    前补 `\fontencoding{TU}` + 族名加前缀。自定义 NFSS 族跳过；
    **不改作者默认字体**——只给显式 Type1 选择提供 Unicode 等价物，
    定义块插 `\documentclass{}` 之后。返回改写的文件数。
    """
    sources = _tex_sources(root)
    visible = {path: visible_tex(text) for path, text in sources.items()}
    # 判定正则与下方注入定位同形：``\documentclass`` 无 ``{...}`` 实参的文件
    # 进不了注入循环，若仍计入 documents 会让已改写的 texlate-* 族名悬空。
    documents = {
        path
        for path, text in visible.items()
        if DOCCLASS_OPTS_RX.search(text) and BEGIN_DOC_RX.search(text)
    }
    if not documents:
        return 0
    context = "\n".join(visible.values())
    custom_families = set(
        re.findall(r"NFSSFamily\s*=\s*\{?([A-Za-z0-9-]+)", context)
    ) | set(re.findall(r"\\DeclareFontFamily\s*\{TU\}\s*\{([^{}]+)\}", context))
    names = "|".join(LEGACY_LATIN_FAMILIES)
    usefont = re.compile(rf"\\usefont\s*\{{(OT1|T1|LY1)\}}\s*\{{({names})\}}")
    family = re.compile(rf"\\fontfamily\s*\{{({names})\}}")
    needed: set[str] = set()
    changed_files = set()
    for path, text in sources.items():
        edits = _latin_font_edits(
            visible[path], usefont, family, custom_families, needed
        )
        if edits:
            sources[path] = apply_edits(text, edits)
            changed_files.add(path)
    if not needed:
        return 0
    block = _latin_family_block(needed)
    for path in documents:
        text = sources[path]
        match = DOCCLASS_OPTS_RX.search(visible_tex(text))
        if match:
            end = group_end(text, match.end() - 1)
            sources[path] = text[:end] + block + text[end:]
            changed_files.add(path)
    written = 0
    for path in changed_files:
        try:
            path.write_text(sources[path], encoding="utf-8")
        except OSError:
            continue  # 单件写不进不拖垮整批
        written += 1
    return written
