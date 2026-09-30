r"""``latex.tables.tail`` — 结构尾参表（``tables`` god-file 机械拆分叶）。

``BOUNDARY_TAIL`` BOUNDARY 命令的结构尾参 spec、``DIMEN_TAIL_KIND``
裸操作数/赋值形命令的尾参种别（dimen/count/arith/rule/font/assign/
boxspec 六别）、``BOX_TAIL_NAMES`` 盒规格尾参族、``TRANSPARENT_HEAD_SPEC``
头参非文本透明命令 spec。
"""

from __future__ import annotations

from texlate.latex.model import ArgSpec

# BOUNDARY 命令的结构尾参表（audit 次要 3）：``\cline{1-2}``/``\vspace*{1em}``
# 这类非文本参消费进 LITERAL 段——否则 ``{1-2}`` 落正文成 chunk 被翻译。
# 只列结构参；``\item[o]`` 的 label、``\newtheorem`` 标题是可译文本不收。
BOUNDARY_TAIL: dict[str, list[ArgSpec]] = {
    "cline": [ArgSpec("m")],
    "cmidrule": [ArgSpec("o"), ArgSpec("d", delim="()"), ArgSpec("m")],
    "toprule": [ArgSpec("o")],
    "midrule": [ArgSpec("o")],
    "bottomrule": [ArgSpec("o")],
    "pagebreak": [ArgSpec("o")],
    "linebreak": [ArgSpec("o")],
    "nopagebreak": [ArgSpec("o")],
    "twocolumn": [ArgSpec("o")],
    "vspace": [ArgSpec("s"), ArgSpec("m")],
    "hspace": [ArgSpec("s"), ArgSpec("m")],
    "newcounter": [ArgSpec("m"), ArgSpec("o")],
    "setcounter": [ArgSpec("m"), ArgSpec("m")],
    "addtocounter": [ArgSpec("m"), ArgSpec("m")],
    # 寄存器族首参是裸 cs 名——``n`` 槽直收 cs token 或 {}/[] 组（``m``
    # 不跨 ``\``）；``setcounter``/``addtocounter`` 首参是计数器名留 ``m``
    "setlength": [ArgSpec("n"), ArgSpec("m")],
    "addtolength": [ArgSpec("n"), ArgSpec("m")],
    # ``\newX\cs`` 声明族：裸 cs 名参同 ``setlength`` 首参走 ``n`` 槽
    "newskip": [ArgSpec("n")],
    "newdimen": [ArgSpec("n")],
    "newcount": [ArgSpec("n")],
    "newbox": [ArgSpec("n")],
    "newtoks": [ArgSpec("n")],
    "newmuskip": [ArgSpec("n")],
    "newinsert": [ArgSpec("n")],
    "newlanguage": [ArgSpec("n")],
    "newfam": [ArgSpec("n")],
    "newhelp": [ArgSpec("n")],
    "newread": [ArgSpec("n")],
    "newwrite": [ArgSpec("n")],
    "settowidth": [ArgSpec("n"), ArgSpec("m")],
    "settoheight": [ArgSpec("n"), ArgSpec("m")],
    "settodepth": [ArgSpec("n"), ArgSpec("m")],
    "setstretch": [ArgSpec("m")],
    "pagestyle": [ArgSpec("m")],
    "thispagestyle": [ArgSpec("m")],
    "pagenumbering": [ArgSpec("m")],
    "documentclass": [ArgSpec("o"), ArgSpec("m")],
    "documentstyle": [ArgSpec("o"), ArgSpec("m")],
    "usepackage": [ArgSpec("o"), ArgSpec("m")],
    "RequirePackage": [ArgSpec("o"), ArgSpec("m")],
}

# 裸操作数/赋值形命令的尾参种别（loop1 slots 修复）：``\vskip3pt``、
# ``\hangindent=.5em``、``\vrule width 2pt``、``\font\cs=cmr10 at 12pt``
# 这类非文本槽位在 ``{}`` 组外——BOUNDARY_TAIL 的组参规则与未知命令
# 探针都够不着，单位字母裸进 surface 即被翻译（illegal_unit 主错因）。
# segmenter 按种别做字节/token 尾扫整体保护：
#   "dimen" — ``[=]?<atom> [plus <atom>] [minus <atom>]``（glue/dimen 寄存器
#             与 skip 原语同式——刚性名多收 plus/minus 无害，该形本就非法）；
#   "rule"  — ``\hrule``/``\vrule`` 的 ``width|height|depth <atom>`` 序；
#   "font"  — ``\font\cs=name [at <atom>|scaled <num>]``。
# 表外未知名走 ``_ASSIGN_TAIL_RX`` 通用 ``=<atom>`` 赋值扫——``\foo=2pt``
# 的 ``=2pt`` 在散文语境不可能是文本。
DIMEN_TAIL_KIND: dict[str, str] = {
    # skip/glue 寄存器与原语
    "vskip": "dimen",
    "hskip": "dimen",
    "mskip": "dimen",
    "vglue": "dimen",
    "hglue": "dimen",
    "spaceskip": "dimen",
    "xspaceskip": "dimen",
    "leftskip": "dimen",
    "rightskip": "dimen",
    "topskip": "dimen",
    "lineskip": "dimen",
    "lineskiplimit": "dimen",
    "baselineskip": "dimen",
    "parskip": "dimen",
    "parfillskip": "dimen",
    "smallskipamount": "dimen",
    "medskipamount": "dimen",
    "bigskipamount": "dimen",
    "jot": "dimen",
    "abovedisplayskip": "dimen",
    "belowdisplayskip": "dimen",
    "abovedisplayshortskip": "dimen",
    "belowdisplayshortskip": "dimen",
    # LaTeX length 寄存器（rubber length = skip）
    "itemsep": "dimen",
    "labelsep": "dimen",
    "labelwidth": "dimen",
    "labelindent": "dimen",
    "tabcolsep": "dimen",
    "arraycolsep": "dimen",
    "textfloatsep": "dimen",
    "floatsep": "dimen",
    "intextsep": "dimen",
    "dblfloatsep": "dimen",
    "dbltextfloatsep": "dimen",
    "topsep": "dimen",
    "partopsep": "dimen",
    "parsep": "dimen",
    "columnsep": "dimen",
    # 刚性 dimen 与位移/字号参
    "kern": "dimen",
    "mkern": "dimen",
    "parindent": "dimen",
    "hangindent": "dimen",
    "hsize": "dimen",
    "vsize": "dimen",
    "textwidth": "dimen",
    "textheight": "dimen",
    "linewidth": "dimen",
    "columnwidth": "dimen",
    "mathsurround": "dimen",
    "emergencystretch": "dimen",
    "moveleft": "dimen",
    "moveright": "dimen",
    "raise": "dimen",
    "lower": "dimen",
    "oddsidemargin": "dimen",
    "evensidemargin": "dimen",
    "topmargin": "dimen",
    "headheight": "dimen",
    "headsep": "dimen",
    "footskip": "dimen",
    "marginparwidth": "dimen",
    "marginparsep": "dimen",
    "paperwidth": "dimen",
    "paperheight": "dimen",
    "prevdepth": "dimen",
    "pagegoal": "dimen",
    "hoffset": "dimen",
    "voffset": "dimen",
    # 计数器/罚分/坏度/追踪寄存器——尾参是裸整数无单位（``\hangafter=1``/
    # ``\tolerance 800``/``\hbadness=10000``），通用 ``assign`` 只罩
    # ``=<atom>``；``=N`` 形由 assign 的 count 兜底（表外名同规），本族
    # 额外买无等号形 ``\hangafter 1``（illegal_unit 波 A 簇实证）。
    "hangafter": "count",
    "looseness": "count",
    "tolerance": "count",
    "pretolerance": "count",
    "hbadness": "count",
    "vbadness": "count",
    "badness": "count",
    "mag": "count",
    "spacefactor": "count",
    "interdisplaylinepenalty": "count",
    "interlinepenalty": "count",
    "interlinepenalties": "count",
    "widowpenalty": "count",
    "widowpenalties": "count",
    "clubpenalty": "count",
    "clubpenalties": "count",
    "displaywidowpenalty": "count",
    "displaywidowpenalties": "count",
    "predisplaypenalty": "count",
    "postdisplaypenalty": "count",
    "interfootnotelinepenalty": "count",
    "brokenpenalty": "count",
    "hyphenpenalty": "count",
    "exhyphenpenalty": "count",
    "binoppenalty": "count",
    "relpenalty": "count",
    "linepenalty": "count",
    "adjdemerits": "count",
    "doublehyphendemerits": "count",
    "finalhyphendemerits": "count",
    "floatingpenalty": "count",
    "outputpenalty": "count",
    "insertpenalties": "count",
    "maxdeadcycles": "count",
    "day": "count",
    "month": "count",
    "year": "count",
    "time": "count",
    "tracingmacros": "count",
    "tracingonline": "count",
    "tracingoutput": "count",
    "tracingstats": "count",
    "tracingcommands": "count",
    "tracinglostchars": "count",
    "tracingparagraphs": "count",
    "tracingpages": "count",
    "showboxbreadth": "count",
    "showboxdepth": "count",
    "errorcontextlines": "count",
    "pausing": "count",
    "holdinginserts": "count",
    "globaldefs": "count",
    "escapechar": "count",
    "endlinechar": "count",
    "newlinechar": "count",
    "uchyph": "count",
    "lefthyphenmin": "count",
    "righthyphenmin": "count",
    "delimiterfactor": "count",
    "defaulthyphenchar": "count",
    "defaultskewchar": "count",
    # 算术/寄存器赋值双操作数：``<op><lval>[by|=]<rval>``——``by``/``=``
    # 间隔关键字裸落 surface 即被译（math/9901091 ``\multiply\ione by 10``
    # 5843 errs 实证；``\skewchar\fivmi='77``/``\setbox0=\hbox to3cm``
    # 同构——rvalue 盒原语再叠 ``to|spread`` 尾由 arith 形自带）。
    "advance": "arith",
    "multiply": "arith",
    "divide": "arith",
    "setbox": "arith",
    "count": "arith",
    "dimen": "arith",
    "skip": "arith",
    "muskip": "arith",
    "toks": "arith",
    "chardef": "arith",
    "mathchardef": "arith",
    "countdef": "arith",
    "dimendef": "arith",
    "skipdef": "arith",
    "muskipdef": "arith",
    "toksdef": "arith",
    "skewchar": "arith",
    "hyphenchar": "arith",
    "fontdimen": "arith",
    # 规则与字体声明
    "hrule": "rule",
    "vrule": "rule",
    "font": "font",
}

# 盒规格尾参（``to|spread <dim>``）命令——``\hbox`` 是透明名（体文续扫），
# ``\vbox``/``\vtop``/``\vcenter`` 走未知命令路；四者同享 boxspec 尾扫，
# ``to``/``spread`` 关键字+dimen 不落 surface（hep-th/9703214 ``\hbox
# to\hsize{`` 的 ``to`` 被译实证）。主分派在透明/未知两路前截获。
BOX_TAIL_NAMES = {"hbox", "vbox", "vtop", "vcenter"}

# 头参非文本、尾参可译的透明命令（loop1 slots③）：``\textcolor{red}{text}``
# 的 ``{red}``/``[model]`` 进 [[CMD]]、``{text}`` 留主流——argspec 同名条目
# 是 chunk-arg policy 但 ``textcolor`` 只挂 xcolor 包（文档靠 color/类定义
# 引入时门控失效），族表先行为确定性修正。
#
# graphicx/内核盒族同理且更强：argspec ``chunk-arg`` 的 in_arg 臂把字面
# 参段裸字节并进 run surface（``\multirow{5}{*}{\rotatebox[origin=c]{90}``
# 的 ``[origin=c]`` 进 chunk 被译——2310.16788 实证），本表 in_arg/组内
# 两路都是 spec 驱动 ``[[CMD]]``，确定性盖过签名表。spec 只列到头参为
# 止——其后 ``{text}`` 组随主流可译。``\makebox``/``\framebox`` 的
# picture-mode ``(x,y)`` 参不收：``(`` 前导在散文里撞真括号（picture
# 环境体本就整段保护，不吃这门）。
TRANSPARENT_HEAD_SPEC: dict[str, list[ArgSpec]] = {
    "textcolor": [ArgSpec("o"), ArgSpec("m")],
    "colorbox": [ArgSpec("o"), ArgSpec("m")],
    # \resizebox*{w}{h}{text}（graphicx，* 变体同形）
    "resizebox": [ArgSpec("s"), ArgSpec("m"), ArgSpec("m")],
    # \scalebox{h}[v]{text}
    "scalebox": [ArgSpec("m"), ArgSpec("o")],
    # \rotatebox[origin]{ang}{text}
    "rotatebox": [ArgSpec("o"), ArgSpec("m")],
    # \raisebox{lift}[above][below]{text}
    "raisebox": [ArgSpec("m"), ArgSpec("o"), ArgSpec("o")],
    # \makebox[w][pos]{text} / \framebox[w][pos]{text}
    "makebox": [ArgSpec("o"), ArgSpec("o")],
    "framebox": [ArgSpec("o"), ArgSpec("o")],
    # \parbox[pos][h][ipos]{w}{text}
    "parbox": [ArgSpec("o"), ArgSpec("o"), ArgSpec("o"), ArgSpec("m")],
    # \savebox{cmd}[w][pos]{text} / \sbox{cmd}{text} / \usebox{cmd}
    "savebox": [ArgSpec("m"), ArgSpec("o"), ArgSpec("o")],
    "sbox": [ArgSpec("m")],
    "usebox": [ArgSpec("m")],
    # titlesec/titletoc 族：全结构参无 text 位——spec 驱动三路径全收
    # （BOUNDARY_TAIL 组内/参内路只数 mand 个数，``m o m m m m o`` 交错
    # 签名在那两条路漏尾参）。签名以 titlesec.sty/titletoc.sty 实测为准：
    # titleformat = 星变体 cmd+fmt 两参 / 全形 cmd shape fmt label sep
    # before after。
    "titleformat": [
        ArgSpec("s"),
        ArgSpec("m"),
        ArgSpec("o"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("o"),
    ],
    # \titlespacing*{cmd}{left}{before}{after}[right]（``s``+4×``m``+
    # 尾 ``o``——.sty ``\ttl@spacing@i`` 是四强制参，mission 手抄三参少一）
    "titlespacing": [
        ArgSpec("s"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("o"),
    ],
    # \titlelabel{fmt} / \titleclass{cmd}[super]{class}——``[super]``
    # 在两序都出现过（.sty 读序 opt-在-class-前，文档常写反），双 ``o`` 盖
    "titlelabel": [ArgSpec("m")],
    "titleclass": [ArgSpec("m"), ArgSpec("o"), ArgSpec("m"), ArgSpec("o")],
    # \titlecontents{sec}[left]{above}{num}{nonum}{filler}[below][after]
    "titlecontents": [
        ArgSpec("s"),
        ArgSpec("m"),
        ArgSpec("o"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("o"),
        ArgSpec("o"),
    ],
}
