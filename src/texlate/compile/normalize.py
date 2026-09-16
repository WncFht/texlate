r"""归一化层：pdfTeX 时代源码 → XeTeX/tectonic 可编译形态的无条件手术。

docs/08 §3.2 十二项清单逐条实现；**条件手术（microtype_off/times→newtx 等错误
驱动修复）留给 fixloop，两边不得重复改同一处**（docs/08 §3.2 分工铁律）。

所有定位打在 :func:`mask.visible_tex` 遮蔽视图上，编辑逆序回放到原文，
删除类编辑补回换行保持行号稳定（编译错误可回溯源文件行号）。

移植自 texglot `app/compiler.py`（normalize_engine 系），实证依据见
docs/research/latex/texglot-patterns.md §1.1–1.6。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

from texlate.textutil import EncodingVerdict, decode_tex, decode_tex_with

from .mask import (
    TEX_SOURCE_SUFFIXES,
    apply_edits,
    group_end,
    visible_tex,
)

#: 随附文献/书目数据后缀——不是 TeX 手术面，但 XeTeX/biber 一律按
#: UTF-8 读它们，非 UTF-8 字节须与 .tex 同档判定转码。
AUX_BIB_SUFFIXES = {".bib", ".bbl", ".bst"}
#: 引擎 pass 间回读的可再生中间产物（aux/out/toc/lof/lot/nav/snm/vrb/ent）：
#: shipped 件若带非 UTF-8 字节，首遍回读即 "Invalid UTF-8 byte" —— .aux 的
#: ``\@newl@bel`` EOF 实证 2211.13013 同族。不进 rebase/violations 扫描面
#: （机器生成内容，\input 审计无意义），只随 _transcode_support_files 转码。
INTERMEDIATE_SUFFIXES = {
    ".aux",
    ".out",
    ".toc",
    ".lof",
    ".lot",
    ".nav",
    ".snm",
    ".vrb",
    ".ent",
}

#: PostScript 图形后缀——graphicx 对 ``\includegraphics`` 目标做
#: ``%%BoundingBox`` 逐行文本扫描（xetex 驱动同此），头注释里的
#: latin-1/GBK 字节（Word2TeX 导出的 Windows 路径等）触发
#: invalid_utf8（loop1-0707.4363 ``Fig*.eps`` 实证）。整件转码会腐
#: ``%%BeginBinary``/内嵌预览的字节数据——只净化 ``%`` 注释行
#: （PostScript 语义惰性区），DOS-EPS 二进制头（``0xC5D0D3C6`` 魔数，
#: 内含绝对字节偏移）整件跳过。
PS_GRAPHIC_SUFFIXES = {".eps", ".ps"}

#: 已知二进制后缀——catch-all 转码豁免名单。漏网的冷门二进制最坏被
#: latin-1→UTF-8 改写：编译树内只有 TeX 文本读取会触它（原样也只会
#: U+FFFD），源归档保持原样——宁可多转不可漏文本件。
BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".tif",
    ".tiff",
    ".webp",
    ".bmp",
    ".jfif",
    ".jbig2",
    ".jb2",
    ".ico",
    ".icns",
    ".heic",
    ".avif",
    ".jp2",
    ".pdf",
    ".dvi",
    ".xdv",
    ".tfm",
    ".ofm",
    ".vf",
    ".pfb",
    ".pfa",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
    ".pk",
    ".gf",
    ".gz",
    ".bz2",
    ".xz",
    ".zip",
    ".tar",
    ".7z",
    ".rar",
    ".lz4",
    ".zst",
    ".jar",
    ".class",
    ".pyc",
    ".pyo",
    ".o",
    ".so",
    ".a",
    ".dll",
    ".exe",
    ".dylib",
    ".mat",
    ".pickle",
    ".pkl",
    ".npy",
    ".npz",
    ".h5",
    ".hdf5",
    ".fits",
    ".sav",
    ".dta",
    ".parquet",
    ".feather",
    ".arrow",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".sobj",
    ".iwa",
    ".plist",
    ".wav",
    ".mp3",
    ".ogg",
    ".flac",
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".webm",
    ".m4a",
    ".docx",
    ".xlsx",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".iso",
    ".img",
    ".dmg",
}

#: DOS-EPS 二进制头魔数——头部含 PS 段的绝对偏移，任何字节增删即腐，
#: 整件放弃净化（此类件本就带二进制预览，扫描面只会更糟）。
_DOS_EPS_MAGIC: Final = b"\xc5\xd0\xd3\xc6"

# ---------------------------------------------------------------- 兼容前导块
# 注入缝统一为 \begin{document} 之前（docs/08 §3.3）；字体系块例外，
# 走 \documentclass{} 之后（见 prepare_legacy_latin_fonts / inject.py）。

PIXEL_COMPATIBILITY = r"""% texlate: pdfTeX pixel dimensions for XeTeX
\ifdefined\pdfpxdimen\else\newdimen\pdfpxdimen\pdfpxdimen=65782sp\fi
"""

XETEX_COMPATIBILITY = r"""% texlate: native XeTeX font and PDF-driver capabilities
\AddToHook{package/microtype/after}{%
\DeclareMicrotypeSet{texlate-native}{encoding={TU,EU1,EU2}}%
\UseMicrotypeSet[protrusion]{texlate-native}%
}
% breakurl already has a native-PDF branch; limit its PDF-mode override to loading.
\AddToHook{package/breakurl/before}{%
\RequirePackage{xkeyval,ifpdf}%
\let\TeXlateSavedIfpdf\ifpdf\let\ifpdf\iftrue
}
\AddToHook{package/breakurl/after}{\let\ifpdf\TeXlateSavedIfpdf}
% This class's optional arXiv check assumes every non-pdfTeX engine writes DVI.
\PassOptionsToClass{nopdfoutputerror,allowfontchageintitle}{quantumarticle}
% Embedded PostScript can silently disappear with restricted XeTeX drivers.
% Record actual drawing operations; merely loading an unused package is harmless.
\AddToHook{package/pstricks/after}{%
\ifcsname pst@object\endcsname
\expandafter\let\expandafter\TeXlatePstObject\csname pst@object\endcsname
\expandafter\def\csname pst@object\endcsname#1{%
\typeout{TeXlate-PostScript-object: #1}\TeXlatePstObject{#1}}%
\fi
}
% \DeclareUnicodeCharacter is pdfTeX/inputenc-only and undefined under XeTeX,
% but e-print preambles still call it (2501.14787). Emulate via the lccode
% idiom: make the code point an active char expanding to the replacement.
\providecommand{\DeclareUnicodeCharacter}[2]{%
\begingroup\lccode`\~="#1\relax
\lowercase{\endgroup\catcode`~\active\protected\def~}{#2}}
"""

TECTONIC_FONT_COMPATIBILITY = r"""% texlate: vector double-stroke fonts; Tectonic cannot generate PK fonts
\AddToHook{package/bbm/after}{%
\SetMathAlphabet{\mathbbm}{normal}{U}{dsrom}{m}{n}%
\SetMathAlphabet{\mathbbm}{bold}{U}{dsrom}{m}{n}%
\SetMathAlphabet{\mathbbmss}{normal}{U}{dsss}{m}{n}%
\SetMathAlphabet{\mathbbmss}{bold}{U}{dsss}{m}{n}%
\SetMathAlphabet{\mathbbmtt}{normal}{U}{dsrom}{m}{n}%
\SetMathAlphabet{\mathbbmtt}{bold}{U}{dsrom}{m}{n}%
}
"""


def inject_preamble(text: str, block: str) -> str:
    r"""在 `\begin{document}` 前插入前导块；找不到 document 环境则原样返回。"""
    marker = re.search(r"\\begin\s*\{document\}", visible_tex(text))
    if not marker:
        return text
    return text[: marker.start()] + block + text[marker.start() :]


# ---------------------------------------------------------------- 1. comment 环境行尾
def normalize_comment_terminators(text: str) -> str:
    r"""剥掉 `\end{comment}` 行尾空白。

    comment.sty 按整行比对终结行；行尾 tab/空格被 TeX 普通扫描器接受、
    却会让 comment 环境吞到 EOF。
    """
    visible = visible_tex(text, mask_comment_environments=False)
    edits = [
        (m.start(), m.end(), r"\end{comment}")
        for m in re.finditer(r"(?m)^[ \t]*(\\end\s*\{comment\})[ \t]+(?=\r?$)", visible)
    ]
    return apply_edits(text, edits)


# ---------------------------------------------------------------- 2. float 位置参数
def normalize_float_positions(text: str) -> str:
    r"""剥 float 位置参数里的非法字符（`[!htbpX]` → `[!htbp]`；剥光则整参删）。

    只作用于纯字母/! 参数；含 `^@` 等符号的参数不匹配定位正则，原样保留
    （与上游 texglot 语义一致——符号形参数没有安全改写空间）。
    """
    visible = visible_tex(text)
    edits = []
    for match in re.finditer(
        r"\\begin\s*\{(?:figure|table)\*?\}\s*(\[([A-Za-z!\s]+)\])", visible
    ):
        positions = "".join(c for c in match[2] if c in "htbpH!" or c.isspace())
        if positions == match[2]:
            continue
        replacement = (
            "[" + positions + "]" if any(c in "htbpH" for c in positions) else ""
        )
        edits.append((match.start(1), match.end(1), replacement))
    return apply_edits(text, edits)


# ---------------------------------------------------------------- 3. pdfTeX 特性
PDFTEX_OUTPUT_SETTINGS = re.compile(
    r"(?:\\global\s*)?\\(?P<control>pdf(?:compresslevel|objcompresslevel|"
    r"minorversion|majorversion|optionpdfminorversion|gentounicode))\s*=?\s*\d+\b"
    r"|\\input\s*(?:\{glyphtounicode(?:\.tex)?\}|glyphtounicode(?:\.tex)?\b)"
)


def normalize_pdftex_features(text: str, engine: str) -> str:
    r"""删除 XeTeX 后端不存在的 pdfTeX 输出控制；microtype 不支持选项降级。

    xdvipdfmx 不吃 pdfTeX 压缩/字形映射设置；microtype 的 expansion/spacing/
    kerning 无 XeTeX 实现，tectonic bundle 版连 tracking 也没有 → 全部改
    `=false`（保留选项位、行数不变）。文档与作者自带 .sty 同策略。
    """
    visible = visible_tex(text)
    edits = [(m.start(), m.end(), "") for m in PDFTEX_OUTPUT_SETTINGS.finditer(visible)]
    edits.extend(
        (m.start(), group_end(visible, m.end() - 1), "")
        for m in re.finditer(r"\\DisableLigatures\s*(?:\[[^]]*\]\s*)?\{", visible)
    )
    unsupported = {"expansion", "spacing", "kerning"}
    if engine == "tectonic":
        unsupported.add("tracking")
    for pattern in (
        r"\\(?:usepackage|RequirePackage)\s*\[([^]]*)\]\s*\{microtype\}",
        r"\\PassOptionsToPackage\s*\{([^{}]*)\}\s*\{microtype\}",
        r"\\microtypesetup\s*\{([^{}]*)\}",
    ):
        for match in re.finditer(pattern, visible):
            options = text[match.start(1) : match.end(1)]
            edits.extend(
                (
                    match.start(1) + option.start(1),
                    match.start(1) + option.end(),
                    option[1] + "=false",
                )
                for option in re.finditer(
                    r"(?:^|,)\s*([A-Za-z]+)(?:\s*=\s*([^,]*))?", options
                )
                if option[1] in unsupported and (option[2] or "").strip() != "false"
            )
    return apply_edits(text, edits)


# ---------------------------------------------------------------- 4. px 像素单位
def normalize_pixel_dimensions(text: str) -> str:
    r"""`Npx` → `N\pdfpxdimen`，**仅限尺寸语境**，非全局 sed。

    语境：\includegraphics 的 width/height/totalheight、\setlength/\addtolength、
    \hspace/\vspace、\rule、\hskip/\vskip/\kern/\hsize 等裸赋值。
    """
    visible = visible_tex(text)
    ranges = []
    for match in re.finditer(r"\\includegraphics\*?\s*\[([^]]*)\]", visible):
        ranges.extend(
            (match.start(1) + option.start(1), match.start(1) + option.end(1))
            for option in re.finditer(
                r"(?:width|height|totalheight)\s*=\s*([^,]+)", match[1]
            )
        )
    patterns = [
        r"\\(?:setlength|addtolength)\s*\{[^{}]+\}\s*\{([^{}]+)\}",
        r"\\(?:hspace|vspace)\*?\s*\{([^{}]+)\}",
        r"\\rule\s*(?:\[([^]]*)\])?\s*\{([^{}]+)\}\s*\{([^{}]+)\}",
        (
            r"\\(?:hskip|vskip|kern|hsize|vsize|textwidth|textheight|linewidth|"
            r"columnwidth|parindent|parskip)\s*=?\s*"
            r"([+-]?\s*(?:\d+(?:\.\d*)?|\.\d+)\s*px)\b"
        ),
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, visible):
            ranges.extend(
                match.span(index)
                for index in range(1, len(match.groups()) + 1)
                if match[index] is not None
            )
    edits = {}
    for start, end in ranges:
        for match in re.finditer(
            r"(?<![A-Za-z\\])([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*px\b",
            visible[start:end],
        ):
            edits[(start + match.start(), start + match.end())] = (
                match[1] + r"\pdfpxdimen"
            )
    for (start, end), value in sorted(edits.items(), reverse=True):
        text = text[:start] + value + text[end:]
    return text


# ---------------------------------------------------------------- 7. inputenc/fontenc
def strip_input_encodings(text: str) -> str:
    r"""剥 `\usepackage{..}` 名字列表里的 inputenc/fontenc，其余保留。

    导入层已把所有 .tex 解码为 UTF-8；旧式输入/字体编码与 XeTeX 原生
    Unicode 字体冲突（latin-5 静默 U+FFFD 教训见 engine-matrix §3.3）。
    """
    visible = visible_tex(text)
    removals = []
    for match in re.finditer(
        r"\\(?:usepackage|RequirePackage)\s*(?:\[[^]]*\])?\s*\{([^}]+)\}", visible
    ):
        names = [v.strip() for v in match[1].split(",")]
        kept = [v for v in names if v not in {"inputenc", "fontenc"}]
        if kept != names:
            value = (
                text[match.start() : match.start(1)] + ",".join(kept) + "}"
                if kept
                else "\n"
            )
            removals.append((match.start(), match.end(), value))
    return apply_edits(text, removals)


# ---------------------------------------------------------------- 8. pdfinfo/pdfoutput/驱动选项
#: ps 系 + pdftex 驱动 token（``dvipdfm(x)``/``xetex``/``luatex`` 不在列）。
_DRIVER_TOKENS: Final = (
    "dvips",
    "dvipsone",
    "dviwindo",
    "oztex",
    "textures",
    "pctexps",
    "pctexwin",
    "pctexhp",
    "pctex32",
    "truetex",
    "tcidvi",
    "emtex",
    "dviwin",
    "dvi2ps",
    "ps2pdf",
    "psprint",
    "pubps",
    "dvitops",
    "ln",
    "xdvi",
    "pdftex",
)
_DRIVER_TOKEN_RX: Final = re.compile(
    r"(?:^|,)\s*(" + "|".join(_DRIVER_TOKENS) + r")\s*(?=,|$)"
)
_DRIVER_SCOPE_RX: Final = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*\[([^]]+)\]"
    r"\s*\{(?:hyperref|graphicx|graphics|color|xcolor)\}"
    r"|\\documentclass\s*\[([^]]+)\]"
    r"|\\PassOptionsTo(?:Package|Class)\s*\{([^}]+)\}"
)


def normalize_pdf_primitives(text: str) -> str:
    r"""删 `\pdfinfo{...}` 与 `\pdfoutput=1`；输出驱动 token 统一 `xetex`。

    驱动选项改写面：hyperref/graphicx/graphics/color/xcolor 可选参 +
    `\documentclass` 全局选项 + `\PassOptionsTo{Package,Class}` 首参内的
    独立 token——别处的驱动字样（宏名、注释）不动。``pdftex`` 指向不存在
    的后端；ps 系驱动（dvips 等）让 graphicx 对被 include 文件做
    ``%%BoundingBox`` 逐行文本扫描——二进制图每个坏行一条 invalid_utf8
    （loop1-1404.0103 单格 15.7 万条实证），eps 头注释坏字节同族。
    ``dvipdfm(x)`` 与 XeTeX 兼容，不在改写面。
    """
    visible = visible_tex(text)
    edits = [
        (m.start(), group_end(visible, m.end() - 1), "\n")
        for m in re.finditer(r"\\pdfinfo\s*\{", visible)
    ]
    # \pdfoutput=1 是 pdfTeX 专属开关，留着会误导老 hyperref 模板的驱动探测。
    edits.extend(
        (m.start(), m.end(), " ")
        for m in re.finditer(r"\\pdfoutput\s*=?\s*1\b", visible)
    )
    text = apply_edits(text, edits)

    visible = visible_tex(text)
    for match in reversed(list(_DRIVER_SCOPE_RX.finditer(visible))):
        group = next(
            i for i in range(1, len(match.groups()) + 1) if match[i] is not None
        )
        for option in reversed(list(_DRIVER_TOKEN_RX.finditer(match[group]))):
            start = match.start(group) + option.start(1)
            end = match.start(group) + option.end(1)
            text = text[:start] + "xetex" + text[end:]
    return text


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


def prepare_legacy_latin_fonts(root: Path) -> int:
    r"""显式 Type1 拉丁字体选择 → Unicode 等价物（TeX Gyre）。

    `\usefont{OT1|T1|LY1}{ptm}` → `{TU}{texlate-ptm}`；`\fontfamily{ptm}` →
    前补 `\fontencoding{TU}` + 族名加前缀。自定义 NFSS 族跳过；
    **不改作者默认字体**——只给显式 Type1 选择提供 Unicode 等价物，
    定义块插 `\documentclass{}` 之后。返回改写的文件数。
    """
    sources = {
        path: decode_tex(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in TEX_SOURCE_SUFFIXES
    }
    visible = {path: visible_tex(text) for path, text in sources.items()}
    documents = {
        path
        for path, text in visible.items()
        if re.search(r"\\documentclass\b", text)
        and re.search(r"\\begin\s*\{document\}", text)
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
        match = re.search(r"\\documentclass\s*(?:\[[^]]*\]\s*)?\{", visible_tex(text))
        if match:
            end = group_end(text, match.end() - 1)
            sources[path] = text[:end] + block + text[end:]
            changed_files.add(path)
    for path in changed_files:
        path.write_text(sources[path], encoding="utf-8")
    return len(changed_files)


# ---------------------------------------------------------------- 10. legacy CJK
def normalize_legacy_cjk(text: str, engine: str) -> str:
    r"""`CJK`/`CJKutf8` 包与环境 → xeCJK+Fandol（lualatex → luatexja）。

    `\begin{CJK}{enc}{family}`/`\end{CJK}` 换成分组括号 `{`/`}`——
    保留原分组语义，剥掉 8-bit 字体编码层。
    """
    visible = visible_tex(text)
    changes = []
    package = "luatexja-fontspec" if engine == "lualatex" else "xeCJK"
    command = "setmainjfont" if engine == "lualatex" else "setCJKmainfont"
    loader = (
        "usepackage"
        if re.search(r"\\begin\s*\{document\}", visible)
        else "RequirePackage"
    )
    native = (
        "\n% texlate: adapted legacy CJK\n\\"
        + loader
        + "{"
        + package
        + "}\n"
        + "\\"
        + command
        + "{FandolSong-Regular.otf}"
        + "[BoldFont=FandolSong-Bold.otf,ItalicFont=FandolKai-Regular.otf]\n"
        + (
            "\\setCJKsansfont{FandolHei-Regular.otf}[BoldFont=FandolHei-Bold.otf]\n"
            "\\setCJKmonofont{FandolFang-Regular.otf}\n"
            if engine != "lualatex"
            else ""
        )
    )
    for match in re.finditer(
        r"\\(?:usepackage|RequirePackage)\s*(?:\[[^]]*\])?\s*\{([^}]+)\}", visible
    ):
        names = [name.strip() for name in match[1].split(",")]
        kept = [name for name in names if name not in {"CJK", "CJKutf8"}]
        if len(kept) != len(names):
            replacement = (
                text[match.start() : match.start(1)] + ",".join(kept) + "}"
                if kept
                else ""
            )
            changes.append((match.start(), match.end(), replacement + native))
    changes.extend(
        (match.start(), match.end(), "{" if match[0].startswith(r"\begin") else "}")
        for match in re.finditer(
            r"\\begin\s*\{CJK\*?\}\s*\{[^{}]*\}\s*\{[^{}]*\}|\\end\s*\{CJK\*?\}",
            visible,
        )
    )
    for start, end, value in sorted(changes, reverse=True):
        text = text[:start] + value + text[end:]
    return text


# ---------------------------------------------------------------- 11. bundled .bbl
def use_bundled_bibliography(text: str, path: Path) -> str:
    r"""当工程附现成 .bbl 而 .bib 缺失时，`\bibliography{x}` → `\input{x.bbl}`。

    定位走 ``visible_tex``（verbatim 体遮盖）——``without_comments`` 只遮
    注释，lstlisting 里展示的 ``\bibliography{x}`` 示例会被真改写。
    """
    bbl = path.with_suffix(".bbl")
    if not bbl.is_file() or r"\begin{thebibliography}" not in decode_tex(
        bbl.read_bytes()
    ):
        return text
    for match in reversed(
        list(re.finditer(r"\\bibliography\s*\{([^}]+)\}", visible_tex(text)))
    ):
        databases = [
            path.parent
            / (v.strip() if v.strip().endswith(".bib") else v.strip() + ".bib")
            for v in match[1].split(",")
        ]
        if any(not p.is_file() for p in databases):
            text = (
                text[: match.start()]
                + r"\input{"
                + bbl.name
                + "}"
                + text[match.end() :]
            )
    return text


# ---------------------------------------------------------------- 12. 越界路径 rebase
def rebase_project_paths(root: Path, main: str) -> list[str]:
    r"""`\input/../foo.tex` 越界引用重写为包内正确相对路径。

    只修"剥掉 ../ 后能在包内找到同名文件"的情形；返回改动位置列表
    `relpath:lineno` 供日志。解不开的越界引用由 source_path_violations 报。
    """
    root = root.resolve()
    cwd = (root / main).parent
    changes: dict[Path, list[tuple[int, int, str]]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in (
            TEX_SOURCE_SUFFIXES | AUX_BIB_SUFFIXES
        ):
            continue
        text = visible_tex(decode_tex(path.read_bytes()))
        for match in re.finditer(
            r"\\(?:input|include)(?![A-Za-z@])\s*"
            r"(?:\{([^{}]*)\}|([^\s{}%]+))",
            text,
        ):
            group = 1 if match[1] is not None else 2
            name = match[group].strip()
            if not name.startswith("../") or re.search(r"[\\#{}~]", name):
                continue
            while name.startswith("../"):
                name = name[3:]
            candidate = (root / name).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                relative = Path(os.path.relpath(candidate, cwd)).as_posix()
                changes.setdefault(path, []).append((*match.span(group), relative))
    locations = []
    for path, edits in changes.items():
        text = decode_tex(path.read_bytes())
        for start, end, relative in sorted(edits, reverse=True):
            locations.append(
                f"{path.relative_to(root)}:{text.count(chr(10), 0, start) + 1}"
            )
            text = text[:start] + relative + text[end:]
        path.write_text(text, encoding="utf-8")
    return sorted(locations)


def source_path_violations(
    root: Path, main: str | None = None
) -> Iterator[tuple[Path, re.Match[str], str]]:
    r"""审计 `\input/\include/\includegraphics/\openin/\openout` 越界/绝对路径/管道。

    逐文件 yield `(path, match, message)`；编译本身另有
    `-no-shell-escape`/`--untrusted` + env 白名单兜底（§4.4），这里是
    "早失败 + 可诊断"层。`rebase_project_paths` 修不掉的在这暴露。
    """
    root = root.resolve()
    cwd = (root / main).parent if main else root
    for p in root.rglob("*"):
        if (
            not p.is_file()
            or p.suffix.lower() not in TEX_SOURCE_SUFFIXES | AUX_BIB_SUFFIXES
        ):
            continue
        text = visible_tex(decode_tex(p.read_bytes()))
        for match in re.finditer(
            r"\\(?:input|include|includegraphics|openin|openout)(?![A-Za-z@])\s*"
            r"(?:\[[^]]*\])?\s*(?:\{([^{}]*)\}|([^\s{}%]+))",
            text,
        ):
            name = (match[1] if match[1] is not None else match[2]).strip()
            absolute = re.match(r"/|~|[A-Za-z]:", name)
            outside = ".." in Path(name).parts and not (
                cwd / name
            ).resolve().is_relative_to(root)
            if absolute or outside or name.startswith("|"):
                message = (
                    r"源码包含外部命令输入（\input{|cmd}），受限编译不支持"
                    if name.startswith("|")
                    else "引用超出工程目录，请将依赖文件放入源码包并使用相对路径"
                )
                yield p, match, message


# ---------------------------------------------------------------- 主编排
def normalize_engine(text: str, engine: str) -> str:
    """单文件无条件手术编排（docs/08 §3.2 清单 1–10 的文件内部分）。"""
    text = normalize_comment_terminators(text)
    text = normalize_float_positions(text)
    if engine in ("tectonic", "xelatex"):
        text = normalize_pdftex_features(text, engine)
        text = normalize_pixel_dimensions(text)
        visible = visible_tex(text)
        has_document = re.search(r"\\begin\s*\{document\}", visible)
        if (
            r"\pdfpxdimen" in visible
            and has_document
            and PIXEL_COMPATIBILITY not in text
        ):
            text = PIXEL_COMPATIBILITY + text
            visible = visible_tex(text)
        if has_document and XETEX_COMPATIBILITY not in text:
            text = XETEX_COMPATIBILITY + text
        if (
            engine == "tectonic"
            and has_document
            and TECTONIC_FONT_COMPATIBILITY not in text
        ):
            text = TECTONIC_FONT_COMPATIBILITY + text
        if (
            has_document
            and r"\PassOptionsToPackage{no-math}{fontspec}" not in visible_tex(text)
        ):
            text = "\\PassOptionsToPackage{no-math}{fontspec}\n" + text
        text = strip_input_encodings(text)
        text = normalize_pdf_primitives(text)
    if engine in ("tectonic", "xelatex", "lualatex"):
        text = normalize_legacy_cjk(text, engine)
    return text


def _record_verdict(
    encodings: dict[str, dict[str, str | None]],
    root: Path,
    path: Path,
    verdict: EncodingVerdict,
) -> None:
    """非平凡判定（非 strict-utf8 / 有声明出入注记）逐文件落账。"""
    if verdict.basis != "strict-utf8" or verdict.note:
        encodings[path.relative_to(root).as_posix()] = {
            "encoding": verdict.encoding,
            "basis": verdict.basis,
            "declared": verdict.declared,
            "note": verdict.note,
        }


def _trim_intermediate_tail(text: str) -> str | None:
    r"""可再生中间产物的截尾整形：砍回最后一个完整行界；无完整行可留 → None。

    XeTeX 写缓冲在 8192B 边界劈断多字节字符 → 自产/shipped ``.aux`` 系
    文件可能终结于半截 ``\newlabel``——只转码不整形回读时
    ``\@newl@bel`` 照样扫过 EOF（2211.13013）。TeX 写出的完整行必以
    ``\n`` 收尾，``text`` 已是解码后字符面，按行界回退即完整字符边界；
    砍掉的部分引擎下遍重长，零数据损失。仅适用可再生中间产物——
    .bib/.bbl/.bst 是数据文件，无尾换行的完整末行是合法形态，不能砍。
    """
    if not text or text.endswith("\n"):
        return text
    end = text.rfind("\n") + 1
    return text[:end] if end else None


def _sanitize_ps_comments(blob: bytes) -> bytes:
    r"""EPS/PS 的 ``%`` 注释行逐行转码 UTF-8；非注释行与 DOS 二进制头原样。

    graphicx ``%%BoundingBox`` 扫描逐行读 PS 件——注释行坏字节即
    invalid_utf8；注释是 PostScript 惰性区，改写零语义差。非注释行
    （``%%BeginBinary``/字符串/hex 数据）字节即语义不许动——残余坏点
    只在 ``(atend)`` 全扫路径才再报，稀有可接受。DOS-EPS 头存绝对偏移，
    任何字节增删即腐，整件跳过。
    """
    if blob.startswith(_DOS_EPS_MAGIC):
        return blob
    try:
        blob.decode("utf-8")
    except UnicodeDecodeError:
        pass  # 有坏字节才进逐行净化
    else:
        return blob
    out: list[bytes] = []
    changed = False
    for raw_line in blob.split(b"\n"):
        line = raw_line
        if line.lstrip(b" \t").startswith(b"%"):
            try:
                line.decode("utf-8")
            except UnicodeDecodeError:
                new = decode_tex(line).encode("utf-8")
                changed = changed or new != line
                line = new
        out.append(line)
    return b"\n".join(out) if changed else blob


def _transcode_one(
    path: Path,
    suffix: str,
    encodings: dict[str, dict[str, str | None]],
    ledgers: dict[str, list[str]],
    root: Path,
) -> None:
    """单件解码判定+写回；INTERMEDIATE 截尾整形，其余全件转码落台账。"""
    original = path.read_bytes()
    text, verdict = decode_tex_with(original)
    # 漏网二进制闸：NUL 字节且非 UTF-16 形态（utf-16 判定自带 NUL 占比
    # 门槛）→ 拿不准的一律不动，也不进 encodings 归因（非文本件无可归因）。
    if b"\x00" in original and not (verdict.encoding or "").startswith("utf-16"):
        return
    _record_verdict(encodings, root, path, verdict)
    rel = path.relative_to(root).as_posix()
    if suffix in INTERMEDIATE_SUFFIXES:
        kept = _trim_intermediate_tail(text)
        if kept is None:
            path.unlink()
            ledgers["purged_intermediates"].append(rel)
            return
        if kept != text:
            path.write_text(kept, encoding="utf-8")
            ledgers["trimmed_intermediates"].append(rel)
            return
    if text.encode("utf-8") != original:
        path.write_text(text, encoding="utf-8")
        aux_family = suffix in AUX_BIB_SUFFIXES or suffix in INTERMEDIATE_SUFFIXES
        ledgers["transcoded_aux" if aux_family else "transcoded_data"].append(rel)


def _transcode_support_files(
    root: Path, encodings: dict[str, dict[str, str | None]]
) -> dict[str, list[str]]:
    r"""非手术面文件按需转 UTF-8：aux/bib + 中间产物 + PS 注释行 + catch-all。

    只动字节不动字节序义：aux 由引擎下遍重写，转码只为消掉 shipped
    非 UTF-8 件首遍回读的 invalid_utf8（docs/research/latex/
    2026-09-16-aux-cjk-truncation.md 立项臂二；loop1 归因补充：工程
    内残留警告 = EPS 头注释/``\openin`` 数据件/未列名文本件）。中间
    产物另加截尾整形（``_trim_intermediate_tail``）——不完整末行比
    非法字节更致命：``\@newl@bel`` 的 EOF 扫描发生在参数层，合法
    UTF-8 也救不回来。

    catch-all：编译树内一切非 ``BINARY_SUFFIXES`` 后缀件必须可
    strict-UTF-8 解码——``.svn``/``.git`` 等隐藏目录、软链（写穿会
    改到 root 外目标）与二进制件豁免；``BINARY_SUFFIXES`` 漏网件另由
    ``_transcode_one`` 的 NUL 闸兜底（含 NUL 且非 UTF-16 → 不动）。

    返回 ``stats`` 片段（仅非空台账）：``transcoded_aux`` /
    ``transcoded_data`` / ``sanitized_ps_comments`` /
    ``trimmed_intermediates`` / ``purged_intermediates``。
    """
    ledgers: dict[str, list[str]] = {
        "transcoded_aux": [],
        "transcoded_data": [],
        "sanitized_ps_comments": [],
        "trimmed_intermediates": [],
        "purged_intermediates": [],
    }
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in parts):
            continue
        rel = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        if suffix in TEX_SOURCE_SUFFIXES or suffix in BINARY_SUFFIXES:
            continue  # 手术面由主循环转码；二进制件不读文本层
        if suffix in PS_GRAPHIC_SUFFIXES:
            original = path.read_bytes()
            sanitized = _sanitize_ps_comments(original)
            if sanitized != original:
                path.write_bytes(sanitized)
                ledgers["sanitized_ps_comments"].append(rel)
            continue
        _transcode_one(path, suffix, encodings, ledgers, root)
    return {k: sorted(v) for k, v in ledgers.items() if v}


# ---------------------------------------------------------------- invalid_utf8 臂三：系统包遮蔽
#: 工程源里显式引用的包/类名采集面——``\input`` 工程件已转码不查。
_PACKAGE_USE_RX: Final = re.compile(
    r"\\(?:usepackage|RequirePackage|RequirePackageWithOptions)\s*"
    r"(?:\[[^]]*\]\s*)?\{([^}]+)\}"
    r"|\\PassOptionsTo(?:Package|Class)\s*\{[^}]*\}\s*\{([^}]+)\}"
)
_CLASS_USE_RX: Final = re.compile(
    r"\\(?:documentclass|LoadClass|LoadClassWithOptions)\s*"
    r"(?:\[[^]]*\]\s*)?\{([^}]+)\}"
)
#: 遮蔽传递闭包轮数上限——遮蔽件自身 ``\RequirePackage`` 再拉系统件时补探。
_SHADOW_MAX_ROUNDS: Final = 8


def _kpse_resolve(filename: str, progname: str, cwd: Path, kpse: str) -> Path | None:
    """``kpsewhich`` 单名解析；``cwd`` 取 main 目录即 ``.`` 元素镜像编译工作目录。"""
    try:
        proc = subprocess.run(  # noqa: S603 — 固定 argv 无 shell
            [kpse, "-progname", progname, "--", filename],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.splitlines()[0].strip())


def _collect_package_refs(text: str) -> tuple[set[str], set[str]]:
    """可见视图上采集 ``(包名集, 类名集)``——逗号列表拆开逐项。"""
    packages: set[str] = set()
    classes: set[str] = set()
    visible = visible_tex(text)
    for match in _PACKAGE_USE_RX.finditer(visible):
        for raw in match.groups():
            if raw:
                packages.update(n.strip() for n in raw.split(",") if n.strip())
    for match in _CLASS_USE_RX.finditer(visible):
        classes.add(match[1].strip())
    return packages, classes


def _try_shadow(
    name: str,
    suffix: str,
    root: Path,
    main_dir: Path,
    resolve: Callable[[str], Path | None],
) -> tuple[dict[str, str] | None, set[str]]:
    """单包探测+遮蔽；返回 ``(台账条目, 遮蔽件内新引用包名)``，不遮蔽时 ``(None, set())``。"""
    req = name + suffix
    # 名字逃逸 + vendored 优先一并早退：工程树内任何位置已有同名件 →
    # 不遮蔽（kpathsea ``.`` 首位会让 main_dir 副本盖掉用户文件；同名件
    # 可能经 \input/自定义 TEXINPUTS 进编译，不写遮蔽面）。
    if (
        name.startswith(("/", "~"))
        or ".." in Path(name).parts
        or any(root.rglob(Path(req).name))
    ):
        return None, set()
    resolved = resolve(req)
    try:
        if resolved is None or resolved.resolve().is_relative_to(root):
            return None, set()
        blob = resolved.read_bytes()
    except OSError:
        return None, set()
    try:
        blob.decode("utf-8")
    except UnicodeDecodeError:
        pass  # 有坏字节才遮蔽
    else:
        return None, set()  # 系统件干净，无需遮蔽
    target = main_dir / req
    if target.exists():
        return None, set()
    text, verdict = decode_tex_with(blob)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    # 传递闭包：遮蔽件自引的包名下轮补探（algorithm.sty 内部
    # \RequirePackage 再拉一个坏件的场景）
    more, _ = _collect_package_refs(text)
    entry = {
        "package": req,
        "from": str(resolved),
        "encoding": verdict.encoding,
        "basis": verdict.basis,
    }
    return entry, {(n, ".sty") for n in more}


def _shadow_broken_system_packages(
    root: Path, main: str | None, engine: str
) -> list[dict[str, str]]:
    r"""工程引用但落在工程外的包/类文件：非 UTF-8 者净化副本落 main 目录遮蔽。

    kpathsea 的 ``.``（编译 cwd = main 所在目录）先于一切 texmf 树——把
    ``decode_tex`` 净化后的同名副本写进 main 目录，``\usepackage`` 即命中
    本副本而非 latin-1 注释污染的系统件（loop1 invalid_utf8 归因：96% 格
    的警告只来自 ``~/texmf``/texmf-dist 的老 CTAN 包 ``algorithm``/
    ``algorithmic``/``algorithm2e`` 系——上游源码即非 UTF-8，系统树不可
    写、也不应被产品改写，遮蔽是唯一输入侧手段）。遮蔽只动字节面：
    latin-1→UTF-8 是码点恒等改写，宏体零语义差。遮蔽件内部的
    ``\RequirePackage`` 引用做有界传递闭包。``tectonic`` 不经 kpathsea、
    ``kpsewhich`` 缺席即整体跳过。

    边界纪律：``root`` 恒为 copytree 下游工作副本（stagerun zh 树 /
    worker ``ctx.base_dir`` / e2e work），遮蔽写不到用户原始归档；
    工程树内任何位置的同名件（vendored 优先）与 kpsewhich 命中 root
    内的件一律跳过——``.fd/.def/.clo`` 等隐式加载不走 ``\usepackage``
    采集面，其系统件坏字节属已知残留不追。
    """
    if engine not in ("xelatex", "lualatex"):
        return []
    kpse = shutil.which("kpsewhich")
    if not kpse:
        return []
    root = root.resolve()
    main_dir = (root / main).parent if main else root
    pending: set[tuple[str, str]] = set()
    for path in root.rglob("*"):
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix.lower() not in TEX_SOURCE_SUFFIXES
        ):
            continue
        packages, classes = _collect_package_refs(decode_tex(path.read_bytes()))
        pending.update((n, ".sty") for n in packages)
        pending.update((n, ".cls") for n in classes)
    shadows: list[dict[str, str]] = []
    probed: set[str] = set()

    def resolve(req: str) -> Path | None:
        return _kpse_resolve(req, engine, main_dir, kpse)

    for _ in range(_SHADOW_MAX_ROUNDS):
        fresh = [item for item in pending if "".join(item) not in probed]
        if not fresh:
            break
        for name, suffix in fresh:
            probed.add(name + suffix)
            entry, more = _try_shadow(name, suffix, root, main_dir, resolve)
            if entry is None:
                continue
            shadows.append(entry)
            pending.update(more)
    return shadows


def normalize_project(root: Path, engine: str, main: str | None = None) -> dict:
    """工程级归一化：逐文件 `normalize_engine` + 文件级手术（9/11/12）。

    返回改动统计 dict。`main` 给 rebase/bbl 判定用；缺省时只按文件名猜。
    非平凡解码判定（非 strict-utf8 / 有声明出入注记）逐文件落
    ``stats["encodings"]``——worker 日志与 rec["normalize"] 由此可回溯
    「该文件原来是什么编码、按哪档判定的」。
    """
    stats: dict[str, object] = {"files": 0, "rewritten": 0}
    encodings: dict[str, dict[str, str | None]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEX_SOURCE_SUFFIXES:
            continue
        stats["files"] = int(stats["files"]) + 1
        original = path.read_bytes()
        text, verdict = decode_tex_with(original)
        _record_verdict(encodings, root, path, verdict)
        text = normalize_engine(text, engine)
        if path.suffix.lower() == ".tex":
            text = use_bundled_bibliography(text, path)
        if text.encode("utf-8") != original:
            path.write_text(text, encoding="utf-8")
            stats["rewritten"] = int(stats["rewritten"]) + 1
    stats.update(_transcode_support_files(root, encodings))
    if encodings:
        stats["encodings"] = encodings
    latin = prepare_legacy_latin_fonts(root)
    if latin:
        stats["legacy_latin_files"] = latin
    if main:
        rebased = rebase_project_paths(root, main)
        if rebased:
            stats["rebased_paths"] = rebased
    shadows = _shadow_broken_system_packages(root, main, engine)
    if shadows:
        stats["package_shadows"] = shadows
    return stats
