r"""compile.normalize_text — 单文件文本域手术叶 (compile.normalize 域缝叶)。

``docs/spec/compile.md`` 清单的文件内手术段：comment 环境行尾、float
位置参数、pdfTeX 特性降级、px 像素单位、手工断词还原、inputenc/fontenc
剥离、pdfinfo/pdfoutput/驱动 token、legacy CJK → xeCJK/luatexja。
全定位打 ``visible_tex`` 遮蔽视图 + ``apply_edits`` 逆序回填保行号。
"""

from __future__ import annotations

import re
from typing import Final

from texlate.textutil import BEGIN_DOC_RX

from .mask import apply_edits, group_end, visible_tex


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
#: 的 ``foo\-bar`` 是 cs 尾 + 断词，直接剥 ``\-`` 会把 ``bar`` 接进宏名
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
    # 形，实测 12 格 dvips 驱动 token 漏网 (loop3 pasj00/ismdproc/aa.cls 系)
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
