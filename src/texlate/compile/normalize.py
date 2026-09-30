r"""归一化层：pdfTeX 时代源码 → XeTeX/tectonic 可编译形态的无条件手术。

docs/spec/compile.md 十二项清单逐条实现；**条件手术（microtype_off/times→newtx 等错误
驱动修复）留给 fixloop，两边不得重复改同一处**（docs/spec/compile.md 分工铁律）。

所有定位打在 :func:`mask.visible_tex` 遮蔽视图上，编辑逆序回放到原文，
删除类编辑补回换行保持行号稳定（编译错误可回溯源文件行号）。

移植自 texglot `app/compiler.py`（normalize_engine 系），实证依据见
docs/research/latex/texglot-patterns.md §1.1–1.6。

支持件字节转码/净化（PS 注释/aux/intermediate/catch-all）与系统包遮蔽
两切面已拆至 sibling 模块 ``transcode.py``/``shadow.py``，本件回引。
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Any

    from texlate.textutil import EncodingVerdict

from texlate.textutil import (
    BEGIN_DOC_RX,
    CMD_BOUNDARY,
    DOCCLASS_OPTS_RX,
    SUBDOC_CHILD_RX,
    _tar_disguised,
    decode_tex,
    decode_tex_with,
    iter_depth0,
    safe_is_file,
    safe_resolve,
)

# 缝原语回引同 layout.py——inject 不反向依赖 normalize，单向无环。
from ._docseams import _splice_after_seams, find_docclass_ends
from .mask import (
    TEX_SOURCE_SUFFIXES,
    apply_edits,
    group_end,
    visible_tex,
)
from .shadow import _shadow_broken_system_packages
from .transcode import (
    AUX_BIB_SUFFIXES,
    _hidden_path,
    _iter_files,
    _read_tex,
    _read_tex_path,  # noqa: F401  # 转口再导出（与本件 ``_iter_files`` 同款先例）
    _record_verdict,
    _transcode_support_files,
)

log = logging.getLogger(__name__)

#: 源包 bundled 的已知垃圾件——内容非论文（自检/交互工具），翻译臂会当正文
#: parse/splice 腐蚀（1109.2354/1206.0565 ``splice/aipcheck.tex:82`` 实证），
#: 裸编译则 ``\typein`` 挂交互终端读（hep-ph/0111248 early_eof）。覆写为
#: stub 而非删除——``\input`` 目标须保持存在。stub 体与 fixloop
#: ``rules/90-shim-legacy.yaml`` ``legacy_pkg_shim`` 的 aipcheck.tex 条目同文。
JUNK_FILE_STUBS: Final[dict[str, str]] = {
    # aipproc/REVTeX4 版本自检件（~18 处 \typein + \def\next#1/#2/#3 魔术）。
    "aipcheck.tex": (
        "% AIP \\input{aipcheck} 版本自检件 —— 纯 \\typeout, 无排版语义\n\\endinput\n"
    ),
}

#: 垃圾件自证签名——同名件须命中任一签名才按垃圾件覆写（名撞护栏）。
#: 名单名是 bundled 构件名（类发行物），逐名匹配假定「该名即垃圾件」；
#: 同树真件撞名时凭签名区分——真件不可能携带垃圾件的 RCS 自名版本戳、
#: 自检横幅或 ``\typein`` 交互原语（corpus 四件实证：v1.4/v1.9 三件
#: 均带齐三签名）。签名按原始字节做子串匹配（ASCII 标记，编码无关）。
#: 无签名件视为撞名真件放行——中立化只护真实输入，不得反噬真件本体；
#: 签名缺省的名单条目回落逐名无条件覆写（旧契约，名单作者自证）。
JUNK_FILE_MARKERS: Final[dict[str, tuple[bytes, ...]]] = {
    "aipcheck.tex": (
        b"$Id: aipcheck.tex",  # RCS 自名版本戳
        b"Testing for potential problems with this class",  # 自检横幅
        b"\\typein",  # 交互终端读原语——裸编译挂点的本体
    ),
}

# ---------------------------------------------------------------- 兼容前导块
# 注入缝三档（docs/spec/compile.md）：包钩/类选项/字体 shim → 文件顶前置
# （``\documentclass`` 之前——``\PassOptionsTo*`` 必须抢在类装载前）；
# preamble 消费的仿真定义 → ``\documentclass`` 缝后（XETEX_EARLY_DEFS，
# 经 inject 缝原语）；bd 锚块（CJK_MATH_FALLBACK 等）→ ``\begin{document}``
# 之前，归 inject/layout。

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
"""

#: preamble 消费的仿真定义——用户 preamble 代码会调用的 cs，落
#: ``\documentclass`` 缝后逐缝注入（``_splice_early_defs``），抢在全部
#: 用户 preamble 代码之前。
XETEX_EARLY_DEFS = r"""% texlate: emulation defs consumed by user preamble code
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


def _splice_early_defs(text: str) -> str:
    r"""``\documentclass`` 缝后逐缝注入 preamble 消费的仿真定义块。

    刻意不挂 preamble_ok/bd 闸：bd 藏进 ``\input`` 子件时 main 零 bd
    （2609.19376），旧闸把定义整段关在 main 外、落进子件顶=组合
    preamble 中段，``\input`` 点之前的调用仍 undefined_cs。
    ``\providecommand`` 幂等，多缝逐点重放安全；``\documentstyle``
    缝滤除（209 无该 cs）。subdoc 子档（subfiles/standalone 类）同
    preamble_ok 口径放行——其 docclass→bd 区段在母档 ``\subfile``/
    ``\includestandalone`` 语境被整体吞没，preamble 调用永不执行。
    """
    if XETEX_EARLY_DEFS in text:
        return text
    if any(iter_depth0(SUBDOC_CHILD_RX, visible_tex(text))):
        return text
    seams = [hit for hit in find_docclass_ends(text) if hit[2] == "documentclass"]
    return _splice_after_seams(text, seams, XETEX_EARLY_DEFS) if seams else text


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
    r"""`Npx` → `N\pdfpxdimen`（单值键）/ `Nbp`（多值键），**仅限尺寸语境**，非全局 sed。

    语境：\includegraphics 的 width/height/totalheight 与
    bbllx/bblly/bburx/bbury/natwidth/natheight（单值）、trim/viewport/bb
    （空格分隔四值——`N\pdfpxdimen` 的控制词会吞掉分隔空格把
    `\Gread@parse@vp` 四参挤塌，只能落字面 bp，1px=1bp 同 pdfTeX 缺省）、
    \setlength/\addtolength、\hspace/\vspace、\rule、
    \hskip/\vskip/\kern/\hsize 等裸赋值。
    """
    visible = visible_tex(text)
    ranges = []  # (start, end, suffix)
    for match in re.finditer(r"\\includegraphics\*?\s*\[([^]]*)\]", visible):
        ranges.extend(
            (
                match.start(1) + option.start(1),
                match.start(1) + option.end(1),
                r"\pdfpxdimen",
            )
            for option in re.finditer(
                r"(?<![a-zA-Z])(?:width|height|totalheight|bbllx|bblly|bburx|"
                r"bbury|natwidth|natheight)\s*=\s*([^,]+)",
                match[1],
            )
        )
        ranges.extend(
            (
                match.start(1) + option.start(1),
                match.start(1) + option.end(1),
                "bp",
            )
            for option in re.finditer(
                r"(?<![a-zA-Z])(?:trim|viewport|bb)\s*=\s*([^,]+)", match[1]
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
                (*match.span(index), r"\pdfpxdimen")
                for index in range(1, len(match.groups()) + 1)
                if match[index] is not None
            )
    edits = {}
    for start, end, suffix in ranges:
        for match in re.finditer(
            r"(?<![A-Za-z\\])([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*px\b",
            visible[start:end],
        ):
            edits[(start + match.start(), start + match.end())] = match[1] + suffix
    return apply_edits(text, [(s, e, v) for (s, e), v in edits.items()])


# ---------------------------------------------------------------- 手工断词还原
#: 字母夹断词整词匹配——前导字母串不许 ``\``/字母前接：``\foo\-bar``
#: 的 ``foo\-bar`` 是 cs 尾+断词，直接剥 ``\-`` 会把 ``bar`` 接进宏名
#: 变 ``\foobar``（lookbehind 在 ``f`` 与第二个 ``o`` 位双双挡死）；
#: ``(?<!\\-)`` 再挡断词串续段——``\foo\-bar\-baz`` 里 ``bar`` 前位是
#: ``\-`` 尾符，放行会把 ``barbaz`` 接走最后一个断点。
_MANUAL_HYPHEN_RX: Final = re.compile(
    r"(?<![a-zA-Z\\])(?<!\\-)[a-zA-Z]+(?:\\-[a-zA-Z]+)+"
)
#: tabbing 环境里 ``\-`` 是「上一制表位」命令（``x\-y`` 形同断词）——
#: env 面豁免；tabbing 不可嵌套，``.*?`` 跨行扫安全。
_TABBING_ENV_RX: Final = re.compile(
    r"\\begin\s*\{tabbing\}.*?\\end\s*\{tabbing\}", re.DOTALL
)


def normalize_manual_hyphens(text: str) -> str:
    r"""可译文本内手工断词 ``\-`` 还原为整词（``sphe\-ri\-cal`` → ``spherical``）。

    ``\-`` 在散文是断词提示——segmenter 按 token 切分把它打成词碎片
    （``sphe``/``ri``/``cal`` 或占位符夹段）喂翻译（hep-th/9910234 实证族：
    ``cy\-lin\-dri\-cal``/``non-Car\-te\-sian``，东欧/前苏联作者稿高发）。
    还原后整词进 parse/xlat；编译侧仅损失手工断点提示，xelatex 自动
    断词不受影响。verbatim/注释在遮蔽视图外天然保留；tabbing 豁免见上。
    """
    visible = visible_tex(text)
    tabbing = [m.span() for m in _TABBING_ENV_RX.finditer(visible)]
    edits = [
        (
            match.start(),
            match.end(),
            text[match.start() : match.end()].replace(r"\-", ""),
        )
        for match in _MANUAL_HYPHEN_RX.finditer(visible)
        if not any(s <= match.start() < e for s, e in tabbing)
    ]
    return apply_edits(text, edits)


# ---------------------------------------------------------------- 7. inputenc/fontenc
#: ``\usepackage``/``\RequirePackage`` 名表手术共用定位形——
#: ``strip_input_encodings``/``normalize_legacy_cjk`` 同扫。
_USEPACKAGE_NAMES_RX: Final = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^]]*\])?\s*\{([^}]+)\}"
)


def _filter_usepackage_names(
    text: str, visible: str, drop: set[str], *, empty: str, suffix: str = ""
) -> list[tuple[int, int, str]]:
    r"""``\usepackage`` 名表剥 ``drop`` 成员的 ``apply_edits`` 编辑列表骨架。

    两调用方只差三参：``empty`` = 名表剥光时的替换文本（strip 用 ``" "``
    防行内相邻 token 粘连；cjk 用 ``""``——其 ``suffix`` 原生块以 ``\n``
    起行自带隔离）；``suffix`` 追加在每条替换尾部（cjk 注入 xeCJK 装载块，
    strip 为 ``""``）。``visible`` 复用调用方既有遮盖视图，不重复打。
    """
    edits = []
    for match in _USEPACKAGE_NAMES_RX.finditer(visible):
        names = [v.strip() for v in match[1].split(",")]
        kept = [v for v in names if v not in drop]
        if kept != names:
            value = (
                text[match.start() : match.start(1)] + ",".join(kept) + "}"
                if kept
                else empty
            )
            edits.append((match.start(), match.end(), value + suffix))
    return edits


def strip_input_encodings(text: str) -> str:
    r"""剥 `\usepackage{..}` 名字列表里的 inputenc/fontenc，其余保留。

    导入层已把所有 .tex 解码为 UTF-8；旧式输入/字体编码与 XeTeX 原生
    Unicode 字体冲突（latin-5 静默 U+FFFD 教训见 engine-matrix §3.3）。
    """
    # 名表剥光落 " "（span 不含行尾 \n → 整行留空行）防行内相邻 token 粘连
    return apply_edits(
        text,
        _filter_usepackage_names(
            text, visible_tex(text), {"inputenc", "fontenc"}, empty=" "
        ),
    )


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
    # 多包并列形 \usepackage[drv]{a,b}: lookahead 要求花括号表内含至少一枚
    # 整词驱动敏感包 (\b 挡 colortbl/xcolorful 子串伪命中) —— 旧单名面漏此
    # 形, 实测 12 格 dvips 驱动 token 漏网 (loop3 pasj00/ismdproc/aa.cls 系)
    r"\\(?:usepackage|RequirePackage)\s*\[([^]]+)\]"
    r"\s*\{(?=[^}]*\b(?:hyperref|graphicx|graphics|color|xcolor)\b)[^}]*\}"
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


# ---------------------------------------------------------------- 伪装二进制闸
#: tar 伪装件判定宿于 ``textutil.targate._tar_disguised``（本件经 facade
#: import 消费——compile/latex 两层共用的字节闸不能锚在消费层，规格注记
#: 随迁）。本档残留件：支持件兼容前导块注入的 NUL 探测窗——
#: ``_transcode_one`` 漏网二进制闸同族；strict-UTF-8 字节面下 NUL 即非文本
#: 证据（0x00 是合法 UTF-8 码位，仅靠判定族分不出 ASCII+NUL 的 blob）。
_PROLOGUE_NUL_WINDOW: Final = 4096


def _prologue_ok(blob: bytes, verdict: EncodingVerdict) -> bool:
    """支持件兼容前导块注入闸：strict-UTF-8 解码且探测窗内无 NUL。"""
    return verdict.basis == "strict-utf8" and b"\x00" not in blob[:_PROLOGUE_NUL_WINDOW]


#: Mac Finder-info/资源叉前缀剥除窗——首个 ``\documentstyle``/``\documentclass``/
#: ``%&`` 行首锚点须落在窗内才认「真 TeX 起点」（cond-mat/0003309: 129B 垃圾
#: 块 ``TEXT*TEX``/``mBIN`` 压在 ``\documentstyle`` 前 → base 臂 Missing
#: \begin{document}）。窗外命中不剥——大 blob 后段碰巧含锚字面时剥除会腐蚀本体。
_LEAD_JUNK_WINDOW: Final = 4096

#: 行首锚点（``(?m)^`` 要 ``\n`` 或文件头在前）——锚点行是垃圾块的天然终点。
_LEAD_ANCHOR_RX: Final = re.compile(rb"(?m)^(?:\\documentstyle|\\documentclass|%&)")


def _strip_lead_junk(blob: bytes) -> bytes:
    r"""剥首个行首锚点前的 NUL 垃圾前缀；无锚/锚在 0/前缀纯文本 → 原样返回。

    NUL 是垃圾判别子——``\documentclass`` 前的纯文本前缀（许可证头/注释块）
    是合法作者内容，不含 NUL 一律不剥。``_neutralize_junk_files`` 按文件名覆写
    整件，拦不住真主件内嵌的二进制前缀——本臂补字节级缺面。
    """
    for m in _LEAD_ANCHOR_RX.finditer(blob[:_LEAD_JUNK_WINDOW]):
        if b"\x00" in blob[: m.start()]:
            return blob[m.start() :]
    return blob


# ---------------------------------------------------------------- 树遍历/读件共享低层件
# ``_iter_files``/``_read_tex_path``/``_read_tex`` 单源在 ``transcode.py``
# （import 回引，``judge.py``/``mainfile.py``/``layout.py``/``marks.py`` 经
# 本件命名空间再导出仍可达）：``suffixes=None`` 不按后缀过滤——按文件名
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


# ---------------------------------------------------------------- 10. legacy CJK
def normalize_legacy_cjk(text: str, engine: str) -> str:
    r"""`CJK`/`CJKutf8` 包与环境 → xeCJK+Fandol（lualatex → luatexja）。

    `\begin{CJK}{enc}{family}`/`\end{CJK}` 换成分组括号 `{`/`}`——
    保留原分组语义，剥掉 8-bit 字体编码层。
    """
    visible = visible_tex(text)
    package = "luatexja-fontspec" if engine == "lualatex" else "xeCJK"
    command = "setmainjfont" if engine == "lualatex" else "setCJKmainfont"
    loader = "usepackage" if BEGIN_DOC_RX.search(visible) else "RequirePackage"
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
    changes = _filter_usepackage_names(
        text, visible, {"CJK", "CJKutf8"}, empty="", suffix=native
    )
    changes.extend(
        (match.start(), match.end(), "{" if match[0].startswith(r"\begin") else "}")
        for match in re.finditer(
            r"\\begin\s*\{CJK\*?\}\s*\{[^{}]*\}\s*\{[^{}]*\}|\\end\s*\{CJK\*?\}",
            visible,
        )
    )
    return apply_edits(text, changes)


# ---------------------------------------------------------------- 11. bundled .bbl
## REVIEW(bblmath): emit-site 修复（非 yaml 规则）——revtex 系（revtex4-x /
## emulateapj / aastex）`\bibliography` 顺带 `\auto@bib@empty` 解除 end-doc
## `\auto@bib` 探测；裸 `\input` 丢失该解除后 `\test@bbl@sw` 在 \vbox 中把
## `\bibitem` 必需组 cite key 当正文排印（_ / & / $ → Missing$ →
## invalid-in-math 级联；探测为真再三读 → 重复书目 / Lonely \item /
## env_mismatch）。`\input` 改写同时补上等价解除；`\@ifundefined` 使
## 非 revtex 工程为零操作。
## csname 形零字面 `@` —— `\bibliography` 站可落在已 tokenize 的 def
## 体内 (2105.11398 `\newcommand{\showbib}` 实证: 旧 `\makeatletter`
## `\@ifundefined` 形在 @=12 预读体里成 `\@`+裸字母 → 调用点 vmode
## spacefactor 炸), csname 任意 catcode 同读 (同 builtins.bib)。
## 名扫段内每个 `@` 都写 `\string@`: doc 激活 @ (`\MakeShortVerb{\@}`
## → @=13) 时裸 @ token 在 \ifcsname/\csname 名扫里被当 active cs
## 展开 → Missing \endcsname (1107.0063 实证); \string 直接取记号
## 产 catcode-12 字面 @ 字符, @=11/12/13 三态同名同读。
_AUTOBIB_DISARM = (
    r"\ifcsname auto\string@bib\endcsname"
    r"\expandafter\let\csname auto\string@bib\expandafter\endcsname"
    r"\csname \string@empty\endcsname\fi"
)


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
    # target 后接终结符，挡 main.bblx 前缀撞名。CMD_BOUNDARY 防把
    # \inputmain 类控制词误当 \input。
    t = re.escape(target)
    alts = [
        r"\{\s*(?:\./)?" + t + r"\s*\}",
        r'"(?:\./)?' + t + r'"',
    ]
    # 裸名形仅当 target 自身不含终结符才可达——target 带空白/~/&/% 时
    # TeX 扫名提前收束读不到全名（``\input sub dir/x.bbl`` 只读 ``sub``），
    # braced/quoted 形不受此限（评审批六：空白 target 裸名曾误报已填充）
    if not re.search(r"[\s\\~&%]", target):
        alts.append(r"(?:\./)?" + t + r"(?![^\s\\~&%])")
    if re.search(
        r"\\input" + CMD_BOUNDARY + r"\s*(?:" + "|".join(alts) + r")",
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
                    + _AUTOBIB_DISARM
                    + "\n"
                    + r"\input{"
                    + target
                    + "}"
                    + text[match.end() :]
                )
    return text


# ---------------------------------------------------------------- 12. 越界路径 rebase
def _apply_rebase_edits(
    root: Path, path: Path, text: str, edits: list[tuple[int, int, str]]
) -> list[str]:
    """单文件逆序回放 rebase 编辑 → 改动位次表；写失败 → 原样不动、无位次。

    ``text`` 用枚举臂已解码的原文——不重复 read/decode（位次在遮蔽视图
    与原文等长，定位坐标两视图通用）。
    """
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
    `relpath:lineno` 供日志。解不开的越界引用原样保留。
    """
    root = root.resolve()
    cwd = (root / main).parent
    changes: dict[Path, list[tuple[int, int, str]]] = {}
    decoded: dict[Path, str] = {}
    for path in _iter_files(root, TEX_SOURCE_SUFFIXES | AUX_BIB_SUFFIXES):
        raw = _read_tex(path)
        if raw is None:
            continue
        text = visible_tex(raw)
        # 成员集刻意窄收 \input/\include：本站是 ``../`` 前缀改写的手术
        # 面，仅限 tex 包含命令。
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
                decoded[path] = raw
    locations = []
    for path, edits in changes.items():
        locations.extend(_apply_rebase_edits(root, path, decoded[path], edits))
    return sorted(locations)


def _is_within(root: Path, candidate: Path) -> bool:
    """``candidate`` 解后是否落 ``root`` 内；解不开 → 按越界计（审计面宁报不漏）。"""
    resolved = safe_resolve(candidate)
    return resolved is not None and resolved.is_relative_to(root)


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
    for p in _iter_files(root, TEX_SOURCE_SUFFIXES | AUX_BIB_SUFFIXES):
        text = _read_tex(p)
        if text is None:
            continue  # 不可读件/tar 伪装件——成员文本里的路径引用不算越界证据
        text = visible_tex(text)
        # \input 族审计集与 textutil ``INPUT_BRACED_RX``/``INPUT_BARE_RX``、
        # ``arxiv.locate._REF_RES`` 刻意不同集（textutil 注记明写该族不按
        # 单枚正则单源）：本站收「单路径实参」的越界向量——
        # input/include/includegraphics + openin/openout 的 ``\cs=<file>``
        # 形；``_REF_RES`` 拓扑全扫另含双参 import 族/subfile/bibliography
        # 等不适用单名捕获的命令，rebase 手术面则收窄到 input/include。
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
    ``JUNK_FILE_MARKERS`` 带签名条目加一道名撞护栏：同名但不含任一垃圾
    签名的文件按撞名真件放行——覆写会毁掉真件本体（同名 ≠ 同垃圾）。
    """
    hits = []
    for path in sorted(_iter_files(root, None)):
        stub = JUNK_FILE_STUBS.get(path.name)
        if stub is None:
            continue
        try:
            blob = path.read_bytes()
            if blob == stub.encode("utf-8"):
                continue
            markers = JUNK_FILE_MARKERS.get(path.name, ())
            if markers and not any(m in blob for m in markers):
                # 同名无垃圾签名——撞名真件，不覆写（fixloop ``_inject_write``
                # foreign 闸同款口径：外来件永不覆写）
                log.debug("归一化跳过撞名真件 %s（无垃圾签名）", path)
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


def normalize_engine(
    text: str, engine: str, *, doc_source: bool = True, prologue: bool = True
) -> str:
    r"""单文件无条件手术编排（docs/spec/compile.md 清单 1–10 的文件内部分）。

    ``doc_source=False`` 按支持件处理：文档级输出控制删除
    （``\pdfinfo``/``\pdfoutput``/输出设置/``\DisableLigatures``）与
    px 像素改写跳过；驱动 token、microtype 降级、编码剥离等
    装载期语义改写仍生效。``prologue=False`` 再闸掉兼容前导块注入
    （PIXEL/XETEX/TECTONIC 兼容块 + XETEX_EARLY_DEFS + fontspec
    ``no-math`` 选项）——``has_document`` 命中二进制 blob 解出的成员
    文本时不许前置注入（0707.0382 tar 伪装 .sty 实案），调用方按
    字节面判据传闸。
    """
    text = normalize_comment_terminators(text)
    text = normalize_float_positions(text)
    text = normalize_manual_hyphens(text)
    if engine in ("tectonic", "xelatex"):
        text = normalize_pdftex_features(text, engine, doc_source=doc_source)
        if doc_source:
            text = normalize_pixel_dimensions(text)
        if prologue:
            visible = visible_tex(text)
            has_document = BEGIN_DOC_RX.search(visible)
            if r"\pdfpxdimen" in visible and PIXEL_COMPATIBILITY not in text:
                # 用 \pdfpxdimen 的文件就要带定义——子文件被 \input 进主文档时
                # 主文档前导块不一定存在（px 只在子件时主件无注入面），
                # \ifdefined 幂等闸保证多件重复注入也安全。
                text = PIXEL_COMPATIBILITY + text
                visible = visible_tex(text)
            # ``\documentclass[..]{subfiles|standalone}`` 子档：母档 ``\subfile``/
            # standalone 包补丁 ``\input``/``\includestandalone`` 拉入时
            # ``\documentclass`` 起至 bd 区间被吞，声明行**之前**的文本却在
            # 母档 body 语境执行——前置块内 preamble-only ``\PassOptionsTo*``
            # 落 body 即 "Can be used only in preamble"（2310.16788
            # birds_eye_view/side_view :1,14；2609.19210/2609.20069 standalone
            # 图件 :1 实案）。``iter_depth0`` 与 find_docclass_ends 同口径——
            # 宏体/实参内 depth>0 命中不算真声明点。PIXEL 仅
            # \ifdefined/\newdimen（body 合法）且保子件 \pdfpxdimen 覆盖，放行。
            preamble_ok = bool(has_document) and not any(
                iter_depth0(SUBDOC_CHILD_RX, visible)
            )
            if preamble_ok and XETEX_COMPATIBILITY not in text:
                text = XETEX_COMPATIBILITY + text
            if (
                engine == "tectonic"
                and preamble_ok
                and TECTONIC_FONT_COMPATIBILITY not in text
            ):
                text = TECTONIC_FONT_COMPATIBILITY + text
            if (
                preamble_ok
                and r"\PassOptionsToPackage{no-math}{fontspec}" not in visible_tex(text)
            ):
                text = "\\PassOptionsToPackage{no-math}{fontspec}\n" + text
            # preamble 消费的仿真定义落 ``\documentclass`` 缝后（全部用户
            # preamble 代码之前）——限 doc_source：支持件里的声明字样是
            # 条件装载/示例文本而非文档起点，且 GBK 支持件逐跑转码后
            # ``_prologue_ok`` 翻转会二次注入（fuzz 幂等面实证）。
            if doc_source:
                text = _splice_early_defs(text)
        text = strip_input_encodings(text)
        text = normalize_pdf_primitives(text, doc_source=doc_source)
    if engine in ("tectonic", "xelatex", "lualatex"):
        text = normalize_legacy_cjk(text, engine)
    return text


def _normalize_tex_files(
    root: Path,
    engine: str,
    main: str | None,
    stats: dict[str, Any],
    encodings: dict[str, dict[str, str | None]],
) -> None:
    """逐 tex 件主手术：转码 + `normalize_engine` + bbl 替换；累计 files/rewritten。"""
    # skip_hidden=False：隐藏件照计 ``stats["files"]``（先计后跳旧口径），
    # 隐藏路径整体豁免手术的手动闸保留在增量之后。
    for path in _iter_files(root, TEX_SOURCE_SUFFIXES, skip_hidden=False):
        stats["files"] = int(stats["files"]) + 1
        if _hidden_path(path, root):
            continue  # 隐藏路径整体豁免手术（同 _transcode 口径）
        try:
            original = path.read_bytes()
            if _tar_disguised(original):
                # tar 伪装件逐字节不动——转码/手术都腐蚀成员数据；
                # fixloop tar 解包臂（同口径扫描窗）在编译侧兜底补缺
                log.debug("归一化跳过 tar 伪装件 %s", path)
                continue
            blob = _strip_lead_junk(original)
            if blob is not original:
                stats.setdefault("lead_junk_stripped", []).append(
                    path.relative_to(root).as_posix()
                )
            text, verdict = decode_tex_with(blob)
            _record_verdict(encodings, root, path, verdict)
            doc_source = path.suffix.lower() in _DOC_SOURCE_SUFFIXES
            text = normalize_engine(
                text,
                engine,
                doc_source=doc_source,
                prologue=doc_source or _prologue_ok(blob, verdict),
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
