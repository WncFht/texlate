r"""归一化层：pdfTeX 时代源码 → XeTeX/tectonic 可编译形态的无条件手术。

docs/08 §3.2 十二项清单逐条实现；**条件手术（microtype_off/times→newtx 等错误
驱动修复）留给 fixloop，两边不得重复改同一处**（docs/08 §3.2 分工铁律）。

所有定位打在 :func:`mask.visible_tex` 遮蔽视图上，编辑逆序回放到原文，
删除类编辑补回换行保持行号稳定（编译错误可回溯源文件行号）。

移植自 texglot `app/compiler.py`（normalize_engine 系），实证依据见
docs/research/latex/texglot-patterns.md §1.1–1.6。
"""

from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

from texlate.textutil import (
    EncodingVerdict,
    decode_tex,
    decode_tex_with,
    safe_is_file,
    safe_resolve,
)

from .mask import (
    TEX_SOURCE_SUFFIXES,
    apply_edits,
    group_end,
    visible_tex,
)

log = logging.getLogger(__name__)

#: 源包 bundled 的已知垃圾件——内容非论文（自检/交互工具），翻译臂会当正文
#: parse/splice 腐蚀（1109.2354/1206.0565 ``splice/aipcheck.tex:82`` 实证），
#: 裸编译则 ``\typein`` 挂交互终端读（hep-ph/0111248 early_eof）。覆写为
#: stub 而非删除——``\input`` 目标须保持存在。stub 体与 fixloop rules.yaml
#: ``legacy_pkg_shim`` 的 aipcheck.tex 条目同文。
JUNK_FILE_STUBS: Final[dict[str, str]] = {
    # aipproc/REVTeX4 版本自检件（~18 处 \typein + \def\next#1/#2/#3 魔术）。
    "aipcheck.tex": (
        "% AIP \\input{aipcheck} 版本自检件 —— 纯 \\typeout, 无排版语义\n\\endinput\n"
    ),
}

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
#: 内含绝对字节偏移）整件跳过。姊妹臂 ``_resolve_atend_bbox``：
#: ``(atend)`` 占位头行强制全件扫描，trailer 实值搬回头行后扫描
#: 在头行即停，数据行坏字节不再入扫。
#: ``.epsi/.epsf/.mps`` 同族归队：corpus_v3 全量 48 件皆 ``%!PS``
#: 文本形态（epsi=EPS Interchange、epsf=EPSF、mps=MetaPost 输出），
#: 真实非 UTF-8 坏点均在 ``%%`` 注释行（cond-mat/9901072
#: ``fig2.epsf`` ``%%Copyright \xa9`` latin-1、0806.2219
#: ``fig02b.epsi`` ``%%CreationDate`` GBK 日期）——走 catch-all 整件
#: 转码会把数据行高字节一并改写，必须走本臂保数据段字节。
PS_GRAPHIC_SUFFIXES = {".eps", ".epsf", ".epsi", ".mps", ".ps"}

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

#: DSC 数据段标记——``%%Begin{Binary,Data,Document,Preview}`` 与配对
#: ``%%End*`` 之间的行是另一消费者的字节负载：其间形似注释的 ``%`` 行
#: 不是 PostScript 惰性区，逐行净化会改写二进制/嵌入件数据。
_PS_DATA_BEGIN_RX: Final = re.compile(
    rb"^[ \t]*%%Begin(?:Binary|Data|Document|Preview)\b"
)
_PS_DATA_END_RX: Final = re.compile(rb"^[ \t]*%%End(?:Binary|Data|Document|Preview)\b")

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
\PassOptionsToClass{nopdfoutputerror,allowfontchangeintitle}{quantumarticle}
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


def normalize_pdftex_features(
    text: str, engine: str, *, doc_source: bool = True
) -> str:
    r"""删除 XeTeX 后端不存在的 pdfTeX 输出控制；microtype 不支持选项降级。

    xdvipdfmx 不吃 pdfTeX 压缩/字形映射设置；microtype 的 expansion/spacing/
    kerning 无 XeTeX 实现，tectonic bundle 版连 tracking 也没有 → 全部改
    `=false`（保留选项位、行数不变）。文档与作者自带 .sty 同策略。
    ``doc_source=False``（.def/.sty 等支持件）只留 microtype 降级——
    输出控制删除在驱动件里是砍实现（1306.0294 hpdftex.def）。
    """
    visible = visible_tex(text)
    edits = []
    if doc_source:
        edits = [
            (m.start(), m.end(), "") for m in PDFTEX_OUTPUT_SETTINGS.finditer(visible)
        ]
        edits.extend(
            (m.start(), group_end(visible, m.end() - 1), "")
            for m in re.finditer(r"\\DisableLigatures\s*(?:\[[^]]*\]\s*)?\{", visible)
        )
    unsupported = {"expansion", "spacing", "kerning"}
    if engine == "tectonic":
        unsupported.add("tracking")
    for pattern in (
        r"\\(?:usepackage|RequirePackage)\s*\[([^]]*)\]\s*\{[^}]*\bmicrotype\b[^}]*\}",
        r"\\PassOptionsToPackage\s*\{([^{}]*)\}\s*\{[^}]*\bmicrotype\b[^}]*\}",
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
    return apply_edits(text, [(s, e, v) for (s, e), v in edits.items()])


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
            # 整行删除留空行（span 不含行尾 \n）；" " 而非 "" 防行内相邻 token 粘连
            value = (
                text[match.start() : match.start(1)] + ",".join(kept) + "}"
                if kept
                else " "
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


def normalize_pdf_primitives(text: str, *, doc_source: bool = True) -> str:
    r"""删 `\pdfinfo{...}` 与 `\pdfoutput=1`；输出驱动 token 统一 `xetex`。

    ``doc_source=False``（支持件）只做驱动 token 改写——``.def`` 驱动件里
    ``\pdfinfo``/``\pdfoutput`` 是条件装载的实现内容，删除即腐蚀
    （hpdftex.def ``\PDF@FinishDoc`` 内 ``\pdfinfo`` 组整段→空行）。

    驱动选项改写面：hyperref/graphicx/graphics/color/xcolor 可选参 +
    `\documentclass` 全局选项 + `\PassOptionsTo{Package,Class}` 首参内的
    独立 token——别处的驱动字样（宏名、注释）不动。``pdftex`` 指向不存在
    的后端；ps 系驱动（dvips 等）让 graphicx 对被 include 文件做
    ``%%BoundingBox`` 逐行文本扫描——二进制图每个坏行一条 invalid_utf8
    （loop1-1404.0103 单格 15.7 万条实证），eps 头注释坏字节同族。
    ``dvipdfm(x)`` 与 XeTeX 兼容，不在改写面。
    """
    visible = visible_tex(text)
    edits = []
    if doc_source:
        edits = [
            (m.start(), group_end(visible, m.end() - 1), "\n")
            for m in re.finditer(r"\\pdfinfo\s*\{", visible)
        ]
        # \pdfoutput=1 是 pdfTeX 专属开关，留着误导老 hyperref 模板的驱动探测。
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


def _tex_sources(root: Path) -> dict[Path, str]:
    """工程内非隐藏 tex 源 → 解码文本；软链/不可读件跳过。"""
    sources: dict[Path, str] = {}
    for path in root.rglob("*"):
        if (
            not path.is_file()
            or path.is_symlink()
            or path.suffix.lower() not in TEX_SOURCE_SUFFIXES
            or _hidden_path(path, root)
        ):
            continue
        try:
            sources[path] = decode_tex(path.read_bytes())
        except OSError:
            continue
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
        if re.search(r"\\documentclass\s*(?:\[[^]]*\]\s*)?\{", text)
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
    written = 0
    for path in changed_files:
        try:
            path.write_text(sources[path], encoding="utf-8")
        except OSError:
            continue  # 单件写不进不拖垮整批
        written += 1
    return written


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
    return apply_edits(text, changes)


# ---------------------------------------------------------------- 11. bundled .bbl
def use_bundled_bibliography(text: str, path: Path, cwd: Path | None = None) -> str:
    r"""当工程附现成 .bbl 而 .bib 缺失时，`\bibliography{x}` → `\input{x.bbl}`。

    定位走 ``visible_tex``（verbatim 体遮盖）——``without_comments`` 只遮
    注释，lstlisting 里展示的 ``\bibliography{x}`` 示例会被真改写。
    ``cwd`` 为编译工作目录（main 所在目录）：`.bib` 存在性判定与
    `\input` 目标名都以它为基准（kpathsea `.` 口径）；缺省退回声明文件目录。
    多只 `\bibliography`（multibib/chapterbib）只替换首个缺库者——单份
    .bbl 只能填一个书目位，二次替换会重复排版整个 thebibliography。
    已注入过 ``\input{<该 .bbl>}``（含 ``./`` 前缀、引号形与裸名形）时
    整体不再改——工程级幂等，防逐跑把后续缺库 ``\bibliography`` 再换
    一遍累加重复书目。
    """
    base = cwd or path.parent
    bbl = path.with_suffix(".bbl")
    try:
        usable = bbl.is_file() and r"\begin{thebibliography}" in decode_tex(
            bbl.read_bytes()
        )
    except OSError:
        # bbl 在但读不动（EACCES 等）只弃书目步——放任上抛会让调用方逐文件
        # OSError 兜底连坐丢掉转码/引擎手术
        log.debug("bbl 读失败，跳过书目替换: %s", bbl)
        return text
    if not usable:
        return text
    target = Path(os.path.relpath(bbl, base)).as_posix()
    if target.startswith(".."):
        return text  # openin_any=p 拒 ../ 引用——不可达的 .bbl 不改写
    visible = visible_tex(text)
    # 开闭符号相关：{...} 只许 } 收、"..." 只许 " 收——失配对（\input{x.bbl"）
    # 在 TeX 里读不出本 bbl（\@iinput 扫描错），不算已填充。
    # 裸名形 \input x.bbl：文件名扫描止于空白/控制序列/~/&/%（}$#^_'" 等
    # catcode≤12 字符反而是名字成分——latex 实证）；(?![^\s\\~&%]) 要求
    # target 后接终结符，挡 main.bblx 前缀撞名。(?![a-zA-Z@]) 防把
    # \inputmain 类控制词误当 \input。
    t = re.escape(target)
    if re.search(
        r"\\input(?![a-zA-Z@])\s*(?:\{\s*(?:\./)?" + t + r"\s*\}"
        r"|\"(?:\./)?" + t + r"\""
        r"|(?:\./)?" + t + r"(?![^\s\\~&%]))",
        visible,
    ):
        return text  # 书目位已由本 .bbl 填充——再换只会重复排版
    for match in re.finditer(r"\\bibliography\s*\{([^}]+)\}", visible):
        for v in match[1].split(","):
            name = v.strip()
            name = name if name.endswith(".bib") else name + ".bib"
            ref = Path(name)
            # openin_any=p 拒绝对路径与 .. 引用——盘上在也编译够不着，按缺席计
            if ref.is_absolute() or ".." in ref.parts or not safe_is_file(base / name):
                return (
                    text[: match.start()]
                    + r"\input{"
                    + target
                    + "}"
                    + text[match.end() :]
                )
    return text


def _hidden_path(path: Path, root: Path) -> bool:
    """任一路径段 ``.`` 前缀——隐藏件（``.git``/``.dotfile``）整体豁免手术与审计。"""
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def _is_within(root: Path, candidate: Path) -> bool:
    """``candidate`` 解后是否落 ``root`` 内；解不开 → 按越界计（审计面宁报不漏）。"""
    resolved = safe_resolve(candidate)
    return resolved is not None and resolved.is_relative_to(root)


# ---------------------------------------------------------------- 12. 越界路径 rebase
def _apply_rebase_edits(
    root: Path, path: Path, edits: list[tuple[int, int, str]]
) -> list[str]:
    """单文件逆序回放 rebase 编辑 → 改动位次表；读/写失败 → 原样不动、无位次。"""
    try:
        text = decode_tex(path.read_bytes())
    except OSError:
        return []
    locations = []
    for start, end, relative in sorted(edits, reverse=True):
        locations.append(
            f"{path.relative_to(root)}:{text.count(chr(10), 0, start) + 1}"
        )
        text = text[:start] + relative + text[end:]
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        return []  # 写不进不记位次，保持原样
    return locations


def rebase_project_paths(root: Path, main: str) -> list[str]:
    r"""`\input/../foo.tex` 越界引用重写为包内正确相对路径。

    只修"剥掉 ../ 后能在包内找到同名文件"的情形；返回改动位置列表
    `relpath:lineno` 供日志。解不开的越界引用由 source_path_violations 报。
    """
    root = root.resolve()
    cwd = (root / main).parent
    changes: dict[Path, list[tuple[int, int, str]]] = {}
    for path in root.rglob("*"):
        if (
            not path.is_file()
            or path.is_symlink()
            or path.suffix.lower() not in (TEX_SOURCE_SUFFIXES | AUX_BIB_SUFFIXES)
            or _hidden_path(path, root)
        ):
            continue
        try:
            text = visible_tex(decode_tex(path.read_bytes()))
        except OSError:
            continue
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
            candidate = safe_resolve(root / name)
            if (
                candidate is not None
                and candidate.is_relative_to(root)
                and safe_is_file(candidate)
            ):
                relative = Path(os.path.relpath(candidate, cwd)).as_posix()
                changes.setdefault(path, []).append((*match.span(group), relative))
    locations = []
    for path, edits in changes.items():
        locations.extend(_apply_rebase_edits(root, path, edits))
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
            p.is_symlink()
            or not p.is_file()
            or p.suffix.lower() not in TEX_SOURCE_SUFFIXES | AUX_BIB_SUFFIXES
            or _hidden_path(p, root)
        ):
            continue
        try:
            text = visible_tex(decode_tex(p.read_bytes()))
        except OSError:
            continue
        for match in re.finditer(
            r"\\(?:input|include|includegraphics)(?![A-Za-z@])\s*"
            r"(?:\[[^]]*\])?\s*(?:\{([^{}]*)\}|([^\s{}%]+))"
            # \openin/\openout 实参是 \cs=<file>（或 <num>=<file>）——
            # 旧式把 `\w=|cmd` 整体当名字，管道符被吞 → 漏检
            r"|\\(?:openin|openout)(?![A-Za-z@])\s*"
            r"(?:\\[a-zA-Z@]+|\d+)\s*=\s*(?:\{([^{}]*)\}|([^\s{}%]+))",
            text,
        ):
            name = next(g for g in match.groups() if g is not None).strip()
            absolute = re.match(r"/|~|[A-Za-z]:", name)
            outside = ".." in Path(name).parts and not _is_within(root, cwd / name)
            if absolute or outside or name.startswith("|"):
                message = (
                    r"源码包含外部命令输入（\input{|cmd}），受限编译不支持"
                    if name.startswith("|")
                    else "引用超出工程目录，请将依赖文件放入源码包并使用相对路径"
                )
                yield p, match, message


# ---------------------------------------------------------------- 13. bundled 垃圾件 stub
def _neutralize_junk_files(root: Path, stats: dict[str, object]) -> None:
    r"""``JUNK_FILE_STUBS`` 名单件逐名覆写为 stub；覆写件记 ``stats["junk_stubbed"]``。

    覆写不删——``\input``/``\include`` 引用目标须保持存在；逐名匹配不限
    目录深度（bundled 件可落任意子目录）。已就位者跳过——幂等不重复记。
    """
    hits = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue  # 软链豁免：写穿会改到 root 外目标
        if _hidden_path(path, root):
            continue  # 隐藏路径整体豁免（同 _transcode 口径）
        stub = JUNK_FILE_STUBS.get(path.name)
        if stub is None:
            continue
        try:
            if path.read_bytes() == stub.encode("utf-8"):
                continue
            path.write_text(stub, encoding="utf-8")
        except OSError:
            continue
        hits.append(path.relative_to(root).as_posix())
    if hits:
        stats["junk_stubbed"] = hits


# ---------------------------------------------------------------- 主编排
#: 文档源后缀——``\pdfinfo``/``\pdfoutput``/输出设置等文档级手术只适用
#: 文档源；``.def/.sty/.clo`` 支持件里同名原语是条件装载的驱动实现,
#: 删除即腐蚀 bundled 件 (1306.0294 hpdftex.def)。
_DOC_SOURCE_SUFFIXES = frozenset({".tex", ".ltx"})


def normalize_engine(text: str, engine: str, *, doc_source: bool = True) -> str:
    r"""单文件无条件手术编排（docs/08 §3.2 清单 1–10 的文件内部分）。

    ``doc_source=False`` 按支持件处理：文档级输出控制删除
    （``\pdfinfo``/``\pdfoutput``/输出设置/``\DisableLigatures``）与
    px 像素改写跳过；驱动 token、microtype 降级、编码剥离等
    装载期语义改写仍生效。
    """
    text = normalize_comment_terminators(text)
    text = normalize_float_positions(text)
    if engine in ("tectonic", "xelatex"):
        text = normalize_pdftex_features(text, engine, doc_source=doc_source)
        if doc_source:
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
        text = normalize_pdf_primitives(text, doc_source=doc_source)
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
    in_data = False
    for raw_line in blob.split(b"\n"):
        line = raw_line
        if _PS_DATA_BEGIN_RX.match(line):
            in_data = True
        elif _PS_DATA_END_RX.match(line):
            in_data = False
        elif not in_data and line.lstrip(b" \t").startswith(b"%"):
            try:
                line.decode("utf-8")
            except UnicodeDecodeError:
                # decode_tex 的 EOL 归一会把行尾 \r 改写成 \n——CRLF 件
                # 净化后凭空多空行；剥尾转码再拼回保住行界字节。
                trail = b"\r" if line.endswith(b"\r") else b""
                body = line[:-1] if trail else line
                new = decode_tex(body).encode("utf-8") + trail
                changed = changed or new != line
                line = new
        out.append(line)
    return b"\n".join(out) if changed else blob


#: DSC 头区 ``%%BoundingBox: (atend)`` 占位行——值延到 trailer 才给。
_BBOX_ATEND_RX: Final = re.compile(rb"^[ \t]*%%BoundingBox:[ \t]*\(atend\)[ \t\r]*$")
#: 实值 ``%%BoundingBox:`` 行——恰好 4 个数值（负值/小数容忍），摄回 group 1。
_BBOX_VALUE_RX: Final = re.compile(
    rb"^[ \t]*%%BoundingBox:[ \t]*"
    rb"((?:[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?[ \t]+){3}"
    rb"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)[ \t\r]*$"
)


def _resolve_atend_bbox(blob: bytes) -> bytes:
    r"""``%%BoundingBox: (atend)`` 头行就地改写为 trailer 实值行。

    graphicx/xetex 的 bbox 逐行扫描命中 ``(atend)`` 占位时被迫全件扫到
    trailer——``(...) show`` 数据行的坏字节随之落入 invalid_utf8 判定
    （数据行字节即语义，``_sanitize_ps_comments`` 刻意不动；utf8-rerun
    复验残 5 格全属此形态）。DSC 约定 atend 实值本就由 trailer 行承载，
    把头行改写为该值后扫描在头行即停——零语义差，trailer 原行保留无害。

    只认 DSC 头注释块（首个非 ``%`` 行 / ``%%EndComments`` 之前）的
    ``(atend)`` 占位行；取全件最后一条实值 ``%%BoundingBox:`` 行作源——
    无实值/畸形值不造值，原样返回。幂等：改写后头行即实值行，二次跑无
    占位可命中。DOS-EPS 二进制头同 sanitize 臂整件跳过。
    """
    if blob.startswith(_DOS_EPS_MAGIC):
        return blob
    lines = blob.split(b"\n")
    atend_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped:
            continue  # 空行不打断头注释块判定（CRLF 件的空行即 \r）
        if stripped.startswith(b"%%EndComments") or not stripped.startswith(b"%"):
            break  # DSC 头注释块边界——atend 占位只认头区
        if _BBOX_ATEND_RX.match(line):
            atend_idx = i
            break
    if atend_idx is None:
        return blob
    values: bytes | None = None
    for line in lines:
        match = _BBOX_VALUE_RX.match(line)
        if match:
            values = match[1]
    if values is None:
        return blob
    out = lines[:]
    trailer_ws = out[atend_idx][len(out[atend_idx].rstrip(b" \t\r")) :]
    out[atend_idx] = b"%%BoundingBox: " + values + trailer_ws
    return b"\n".join(out)


def _transcode_intermediate(
    path: Path, text: str, rel: str, ledgers: dict[str, list[str]]
) -> bool:
    """INTERMEDIATE 件截尾整形；返回 True=已处置（purge/截尾写回）不再转码。"""
    kept = _trim_intermediate_tail(text)
    if kept is None:
        try:
            path.unlink()
        except OSError:
            pass  # 只读目录 purge 不动——文件原样，不留台账
        else:
            ledgers["purged_intermediates"].append(rel)
        return True
    if kept == text:
        return False  # 无尾可截——回落通用转码臂
    try:
        path.write_text(kept, encoding="utf-8")
    except OSError:
        pass
    else:
        ledgers["trimmed_intermediates"].append(rel)
    return True


def _transcode_one(
    path: Path,
    suffix: str,
    encodings: dict[str, dict[str, str | None]],
    ledgers: dict[str, list[str]],
    root: Path,
) -> None:
    """单件解码判定+写回；INTERMEDIATE 截尾整形，其余全件转码落台账。

    读写任一步 OSError（只读件/只读目录）按「未触动」处理——不落台账、
    不中断整树扫描（同 ``_neutralize_junk_files`` 的守卫口径）。
    """
    try:
        original = path.read_bytes()
    except OSError:
        return
    text, verdict = decode_tex_with(original)
    # 漏网二进制闸：NUL 字节且非 UTF-16 形态（utf-16 判定自带 NUL 占比
    # 门槛）→ 拿不准的一律不动，也不进 encodings 归因（非文本件无可归因）。
    if b"\x00" in original and not verdict.encoding.startswith("utf-16"):
        return
    _record_verdict(encodings, root, path, verdict)
    rel = path.relative_to(root).as_posix()
    if suffix in INTERMEDIATE_SUFFIXES and _transcode_intermediate(
        path, text, rel, ledgers
    ):
        return
    if text.encode("utf-8") != original:
        try:
            path.write_text(text, encoding="utf-8")
        except OSError:
            pass
        else:
            aux_family = suffix in AUX_BIB_SUFFIXES or suffix in INTERMEDIATE_SUFFIXES
            ledgers["transcoded_aux" if aux_family else "transcoded_data"].append(rel)


def _process_ps_file(path: Path, rel: str, ledgers: dict[str, list[str]]) -> None:
    """PS 件：DOS 魔数整件豁免落台账；atend 改写 + 注释净化，写成功才记。

    DOS-EPS 二进制头含绝对偏移，任何字节增删即腐——整件留原样落台账
    （残余 invalid_utf8 由引擎归因降到 sys_warn，不阻断 clean）。
    """
    try:
        original = path.read_bytes()
    except OSError:
        return
    if original.startswith(_DOS_EPS_MAGIC):
        ledgers["dos_eps_skipped"].append(rel)
        return
    resolved = _resolve_atend_bbox(original)
    sanitized = _sanitize_ps_comments(resolved)
    if sanitized == original:
        return
    try:
        path.write_bytes(sanitized)
    except OSError:
        return  # 写不进不记台账，保持原样
    if resolved != original:
        ledgers["resolved_atend_bbox"].append(rel)
    if sanitized != resolved:
        ledgers["sanitized_ps_comments"].append(rel)


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
    ``resolved_atend_bbox`` / ``trimmed_intermediates`` /
    ``purged_intermediates`` / ``dos_eps_skipped``。
    """
    ledgers: dict[str, list[str]] = {
        "transcoded_aux": [],
        "transcoded_data": [],
        "sanitized_ps_comments": [],
        "resolved_atend_bbox": [],
        "trimmed_intermediates": [],
        "purged_intermediates": [],
        "dos_eps_skipped": [],
    }
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        if _hidden_path(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        if suffix in TEX_SOURCE_SUFFIXES or suffix in BINARY_SUFFIXES:
            continue  # 手术面由主循环转码；二进制件不读文本层
        if suffix in PS_GRAPHIC_SUFFIXES:
            _process_ps_file(path, rel, ledgers)
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
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        # ValueError：包名含 NUL → argv embedded null byte
        log.debug("kpsewhich 探测失败 %s: %s", filename, e)
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


def _shadow_source(
    name: str,
    suffix: str,
    root: Path,
    resolve: Callable[[str], Path | None],
) -> tuple[Path, bytes] | None:
    """遮蔽源定位+读取；逃逸名/工程内同名/root 内命中/不可读 → None。"""
    req = name + suffix
    # 名字逃逸 + vendored 优先一并早退：工程树内任何位置已有同名件 →
    # 不遮蔽（kpathsea ``.`` 首位会让 main_dir 副本盖掉用户文件；同名件
    # 可能经 \input/自定义 TEXINPUTS 进编译，不写遮蔽面）。
    if (
        name.startswith(("/", "~"))
        or ".." in Path(name).parts
        or any(root.rglob(glob.escape(Path(req).name)))
    ):
        return None
    resolved = resolve(req)
    try:
        if resolved is None or resolved.resolve().is_relative_to(root):
            return None
        return resolved, resolved.read_bytes()
    except (OSError, RuntimeError, ValueError) as e:
        log.debug("系统包遮蔽源不可读 %s: %s", resolved, e)
        return None


def _try_shadow(
    name: str,
    suffix: str,
    root: Path,
    main_dir: Path,
    resolve: Callable[[str], Path | None],
) -> tuple[dict[str, str] | None, set[str]]:
    """单包探测+遮蔽；返回 ``(台账条目, 遮蔽件内新引用包名)``，不遮蔽时 ``(None, set())``。"""
    req = name + suffix
    src = _shadow_source(name, suffix, root, resolve)
    if src is None:
        return None, set()
    resolved, blob = src
    try:
        blob.decode("utf-8")
    except UnicodeDecodeError:
        pass  # 有坏字节才遮蔽
    else:
        return None, set()  # 系统件干净，无需遮蔽
    target = main_dir / req
    if target.exists() or target.is_symlink():
        # 悬挂软链 exists()=False 但 write_text 会写穿到 root 外目标
        return None, set()
    text, verdict = decode_tex_with(blob)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError as e:
        log.debug("遮蔽件写入失败 %s: %s", target, e)
        return None, set()
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


def _collect_pending_refs(root: Path) -> set[tuple[str, str]]:
    r"""工程 tex 源的 ``\usepackage``/``\documentclass`` 名集 → (名, 后缀) 待探集。"""
    pending: set[tuple[str, str]] = set()
    for path in root.rglob("*"):
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix.lower() not in TEX_SOURCE_SUFFIXES
            or _hidden_path(path, root)
        ):
            continue
        try:
            packages, classes = _collect_package_refs(decode_tex(path.read_bytes()))
        except OSError:
            continue
        pending.update((n, ".sty") for n in packages)
        pending.update((n, ".cls") for n in classes)
    return pending


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
    pending = _collect_pending_refs(root)
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


def _normalize_tex_files(
    root: Path,
    engine: str,
    main: str | None,
    stats: dict[str, object],
    encodings: dict[str, dict[str, str | None]],
) -> None:
    """逐 tex 件主手术：转码 + `normalize_engine` + bbl 替换；累计 files/rewritten。"""
    for path in root.rglob("*"):
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix.lower() not in TEX_SOURCE_SUFFIXES
        ):
            continue  # 软链豁免：读写都会穿到 root 外目标（同 _transcode 臂）
        stats["files"] = int(stats["files"]) + 1
        if _hidden_path(path, root):
            continue  # 隐藏路径整体豁免手术（同 _transcode 口径）
        try:
            original = path.read_bytes()
            text, verdict = decode_tex_with(original)
            _record_verdict(encodings, root, path, verdict)
            text = normalize_engine(
                text,
                engine,
                doc_source=path.suffix.lower() in _DOC_SOURCE_SUFFIXES,
            )
            if path.suffix.lower() == ".tex":
                text = use_bundled_bibliography(
                    text, path, cwd=(root / main).parent if main else None
                )
            if text.encode("utf-8") != original:
                path.write_text(text, encoding="utf-8")
                stats["rewritten"] = int(stats["rewritten"]) + 1
        except OSError as e:
            # 单件读/写失败（只读件、权限边界）不拖垮整树——跳过硬保留原样
            log.debug("归一化跳过不可读写件 %s: %s", path, e)


def normalize_project(root: Path, engine: str, main: str | None = None) -> dict:
    """工程级归一化：逐文件 `normalize_engine` + 文件级手术（9/11/12）。

    返回改动统计 dict。`main` 给 rebase/bbl 判定用；缺省时只按文件名猜。
    非平凡解码判定（非 strict-utf8 / 有声明出入注记）逐文件落
    ``stats["encodings"]``——worker 日志与 rec["normalize"] 由此可回溯
    「该文件原来是什么编码、按哪档判定的」。
    """
    stats: dict[str, object] = {"files": 0, "rewritten": 0}
    encodings: dict[str, dict[str, str | None]] = {}
    _neutralize_junk_files(root, stats)
    _normalize_tex_files(root, engine, main, stats, encodings)
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
