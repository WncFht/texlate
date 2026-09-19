r"""LaTeX 2.09 ``\documentstyle`` → LaTeX2e ``\documentclass`` 受限升级器。

compat 模式在内核层禁用 ``\usepackage``（探针实证：A 臂 11/11 同签名全灭，
``tmp/latex209-probe/RESULTS.md``）——2.09 文档唯一的 CJK 注入通路是先升级成
2e 形态。本模块只做有界转换：

- 首个非注释 ``\documentstyle[o]{c}`` 改写为 ``\documentclass`` + ``\usepackage``
  拆分。定位走 :func:`texlate.compile.mask.visible_tex` 等长掩码视图——注释与
  verbatim 里的 ``\documentstyle`` 命中不到，且选项段内的穿插注释被掩成空白，
  offset 与原文逐字节对齐，回原文做 span 替换；
- 209 时代类名映射到存续 2e 类（revtex→revtex4-2 等）；未识别类名原样保留，
  缺 ``.cls`` 交 fixloop missing_file → CTAN fetch；
- 选项三路分派：目标类 ``\incompatible@package`` 硬不兼容名（revtex4-2:
  cite/mcite/multicol——loaded 即 ``\ClassError``+``\stop``）剥除记账 →
  内核/目标类内建选项 → 类选项（未知选项进类只是
  "unused global option" warning，错进 ``\usepackage`` 是 missing_file 硬错）；
  已知宏包名或工程随源 ``<opt>.sty`` → ``\usepackage``；默认落类选项。
  multicol 被剥时附 ``\multicols``/``\col@number``/``\multicolsep`` 透传
  shim 保正文环境与长度赋值可解析；revtex4-2 目标另附
  ``_REVTEX209_SHIM``——cls 刻意删掉的 209 文稿面（``\frontmatter@init``
  武装 + ``\twocolumn``/``\@makecol``/``\wideabs``/``\abstract`` 兜底 +
  ``\pacs`` 闸门解除），partial 稿不进 fixloop，补位只能在升级缝；
- 转换产物尾部附 ``COMPAT_SHIM``——探针实证的 209 内建残留（``\Box`` 系
  latexsym、``\vruleheight``、``\ifoldfss``、``\footheight``、``\tightenlines``、
  ``\@floats``）+ 209 序言面普查件（``\ifnfssone``、旧字体开关
  ``\rm``..``\sc``、``\cal``、plain/lfonts 字体系、``\theorembodyfont``、
  ``\address``/``\collab``/``\abstracts`` 渲染透传——全 ``\@ifundefined``
  守护，原生已定义目标类不吃惊）；
- ``ds@`` 选项机驱动的 style-as-class（ias/jaa/julie，及随源 ``<cls>.sty``/``.cls``
  内检出 ``ds@`` 定义者）不可转——2e 无此分发机制，返回 ``reject`` 状态交
  inject 层按 ``latex209_ds_at`` 拒；
- 改名目标类落盘前做可解析性守卫（盲升闸）：工程树 ``<target>.cls`` 或
  ``kpsewhich`` 双侧均无命中 → 升上去必 missing_file（jpsj3 不在 CTAN），
  按 ``latex209_no_target`` 拒；kpsewhich 缺席/探测失败 fail-open 不阻断。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import TYPE_CHECKING, Final, NamedTuple

from texlate.textutil import (
    CMD_BOUNDARY,
    DOCSTYLE_DECL_RX,
    DOCSTYLE_RX,
    _tar_disguised,
    cs_events_spans,
    decode_tex,
    iter_depth0,
)

from .mask import apply_edits, group_end, visible_tex

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

#: 选项名/类名的 glob 安全字符集——进 ``root.rglob`` 模式串前必须过闸。
_GLOB_SAFE_RE = re.compile(r"[A-Za-z0-9_.+-]+")

#: 内核级选项：任何类都收，恒留类选项位。
_KERNEL_OPTS = frozenset(
    {
        "10pt",
        "11pt",
        "12pt",
        "letterpaper",
        "legalpaper",
        "executivepaper",
        "a4paper",
        "a5paper",
        "b5paper",
        "landscape",
        "oneside",
        "twoside",
        "onecolumn",
        "twocolumn",
        "draft",
        "final",
        "fleqn",
        "leqno",
        "titlepage",
        "notitlepage",
        "openany",
        "openright",
        "openbib",
        "clock",
        "slide",
    }
)

#: 标准 2e 类——永远真类，不做映射也不做 ds@ 探测。
_STD_CLASSES = frozenset(
    {"article", "report", "book", "letter", "slides", "proc", "minimal", "ltxdoc"}
)


class _ClassSpec(NamedTuple):
    """CLASS_MAP 条目：2e 目标类名 + 类内建选项表 + 209→2e 选项改名表。

    ``options`` 表的路由意义只在抢占宏包白名单冲突（revtex4-2 的 showkeys
    是类内建、同名 showkeys.sty 也存在——类表先判，类选项胜出）；未列名选项
    默认也落类选项，故表只收确定的内建名。
    """

    target: str
    options: frozenset[str] = frozenset()
    rename: Mapping[str, str] = {}


#: 209 时代类名 → 存续 2e 类。revtex 的 209 选项名经 ``rename`` 改写进
#: revtex4-2 词汇表（tighten→tightenlines、floats→floatfix）。
_CLASS_MAP: dict[str, _ClassSpec] = {
    "revtex": _ClassSpec(
        "revtex4-2",
        options=frozenset(
            {
                "aps",
                "aip",
                "jmp",
                "bmf",
                "rmp",
                "prl",
                "pra",
                "prb",
                "prc",
                "prd",
                "pre",
                "prstab",
                "prstper",
                "preprint",
                "reprint",
                "manuscript",
                "superscriptaddress",
                "groupedaddress",
                "unsortedaddress",
                "runinaddress",
                "tightenlines",
                "floatfix",
                "endfloats",
                "longbibliography",
                "nofootinbib",
                "footinbib",
                "bibnotes",
                "nobibnotes",
                "showkeys",
                "showpacs",
            }
        ),
        rename={"tighten": "tightenlines", "floats": "floatfix"},
    ),
    "mn": _ClassSpec(
        "mnras",
        options=frozenset(
            {"referee", "letters", "usegraphicx", "useAMS", "usenatbib", "dcolumn"}
        ),
    ),
    "jpsj": _ClassSpec("jpsj3"),
    "elsart": _ClassSpec(
        "elsarticle",
        options=frozenset(
            {
                "preprint",
                "review",
                "doubleblind",
                "longtitle",
                "1p",
                "3p",
                "5p",
                "authoryear",
                "numbered",
                "number",
                "numbers",
                "sort&compress",
            }
        ),
    ),
    "aipproc": _ClassSpec("aipproc"),
    "amsart": _ClassSpec(
        "amsart",
        options=frozenset(
            {
                "psamsfonts",
                "intlimits",
                "nointlimits",
                "sumlimits",
                "nosumlimits",
                "namelimits",
                "nonamelimits",
                "centertags",
                "notags",
                "reqno",
            }
        ),
    ),
}

#: 209 时代 ``\documentstyle`` 选项位上的真实宏包/随源样式名——这些名字是
#: ``.sty`` 文件，进 ``\usepackage`` 才会真正加载；错留类选项位则静默不加载。
_PKG_OPTS = frozenset(
    {
        # graphics 族（普查高频头：epsfig 83 / epsf 71 / psfig 50）
        "epsf",
        "epsfig",
        "psfig",
        "graphicx",
        "graphics",
        "color",
        "pstricks",
        "rotate",
        # axodraw 是真包（Vermaseren 非商用许可 → off-CTAN，vendor/stubs 有
        # 替身）——209 选项位即装载语义，留类选项位则静默不加载，
        # hep-ph/0111339 \LongArrow/\Line undefined_cs 实证（axodraw-lane）。
        "axodraw",
        # AMS 族
        "amsmath",
        "amstex",
        "amssym",
        "amssymb",
        "amsfonts",
        "amsthm",
        "amscd",
        "diagrams",
        # bib/cite 族
        "natbib",
        "cite",
        "citesort",
        "harvard",
        "apalike",
        "chicago",
        "prabib",
        # 版面/工具
        "epic",
        "eepic",
        "a4",
        "a4wide",
        "dina4",
        "fullpage",
        "times",
        "mathptm",
        "mathptmx",
        "palatino",
        "helvet",
        "multicol",
        "rotating",
        "array",
        "tabularx",
        "multirow",
        "verbatim",
        "moreverb",
        "makeidx",
        "subfigure",
        "supertabular",
        "longtable",
        "float",
        "endnotes",
        "url",
        "ifthen",
        "calc",
        "latexsym",
        "eqsecnum",
        "showkeys",
        "flushrt",
        "hangcaption",
        "nato",
        # AAS/journal 随源惯例（普查高频：aaspp4 13 / aasms4 9；CTAN 有档）
        "aaspp4",
        "aasms4",
        "aas2pp4",
        "aastex",
        "espcrc2",
        "emulateapj",
    }
)

#: 目标类硬不兼容宏包——类内 ``\incompatible@package`` 声明，loaded 即
#: ``\ClassError``+``\stop``（revtex4-2.cls:6453-6455：cite/mcite/multicol 与
#: ltxgrid 输出例程互斥）。命中即从选项剥除——留类选项位成 unused-option
#: warning 失语义，进 ``\usepackage`` 必死；剥除名记入 ``info["stripped"]``。
_INCOMPAT_PKGS: dict[str, frozenset[str]] = {
    "revtex4-2": frozenset({"cite", "mcite", "multicol"}),
}

#: 实证 ds@ 选项机类（随源 .sty 以 ``\ds@<opt>``/``\@namedef{ds@<opt>}`` 分发
#: 选项；2e 无此机制，ias.cls 也不存在——无树可调时按名硬拒）。
_DS_AT_CLASSES = frozenset({"ias", "jaa", "julie"})

#: revtex4-2/ltxgrid 毒根：209 时代 preamble 的裸 ``\topskip <dim>`` 赋值。
#: ltxgrid 输出例程以类载入时的 topskip 为分页网格基准，声明后任何改写都
#: 让页盒丈量失同步——``\topskip 0mm`` 实证 ``\end{document}`` ``\clearpage``
#: 死循环（每页 6.66pt overfull 残量重排不尽，7 万页 SIGKILL）；正值不循环
#: 但整页被吞 "No pages of output"（tmp/lane-revtexloop 双侧实证）。只删
#: 语句首位的活赋值（行首/``}``/``;`` 之后），``\ifdim\topskip``、
#: ``\dimen=\topskip`` 这类读用形态不动；花括号内局部赋值作用域自动回滚，
#: ``iter_depth0`` 口径天然豁免。
_TOPSKIP_ASSIGN_RE = re.compile(
    r"\\topskip"
    + CMD_BOUNDARY
    + r"\s*=?\s*[-+]?(?:\d+\.?\d*|\.\d+)\s*(?:true\s*)?"
    + r"(?:pt|mm|cm|in|pc|bp|dd|cc|sp|em|ex|mu)(?![a-zA-Z@])"
)

#: ``ds@`` 选项分发记号——词首边界锚：``\ds@<opt>`` 命令形态与
#: ``\@namedef{ds@<opt>}``/``\csname ds@<opt>`` 调用形态全收（``\``/``{``/空白
#: 均为非字字符、``d`` 处成界）；``\mids@foo``/``\ods@x`` 这类内嵌子串
#: 前接字母不成界，不误伤。检索面过 ``visible_tex`` 等长遮盖——注释/逐字段里
#: 的 ``ds@`` 字样（``% uses ds@ dispatch``）不计。
_DS_AT_RE = re.compile(r"\bds@")

#: 数学域 209 字体开关组 ``{\em/\it/\bf X}`` → 2e 数学字母命令映射。
#: 209 时代 ``\em``/``\it``/``\bf`` 是 switch（组内余生全换体）；2e 下
#: ``\em`` 经 ``\@nomath`` 警告后落到 ``\itshape``——``\not@math@alphabet``
#: 硬报 ``Command \itshape invalid in math mode``（astro-ph/9910310
#: ``\sum_{{\em fields}\,i}`` 实证签名）。``\it``/``\bf`` 经
#: ``\@fontswitch``+``\math@bgroup`` 在数学域本就退化出组 switch 语义
#: 不报错，仍一并归一为参数形消歧。``\rm/\sf/\tt/\cal/\mit`` 同机制
#: 本就正确不动；``\sl/\sc`` 数学域仅 ``\@nomath`` 警告丢字形（无标准
#: 数学字母对应，改写即改语义）不动。
#: 过渡期稿混用 2e 声明形 ``{\bfseries/\itshape/\rmfamily/\sffamily/\ttfamily
#: X}`` 同踩 ``\not@math@alphabet`` 硬报（gr-qc/9901082 实证）——并入映射；
#: ``\slshape/\scshape/\upshape/\mdseries/\normalfont`` 无单义数学字母
#: 对应（sl→mathit 属语义改写）保守不收。
_MATH_SWITCH_209: Final = {
    "em": "mathit",
    "it": "mathit",
    "bf": "mathbf",
    "bfseries": "mathbf",
    "itshape": "mathit",
    "rmfamily": "mathrm",
    "sffamily": "mathsf",
    "ttfamily": "mathtt",
}

#: 候选组定位：``{`` 后仅横向空白接开关系 cs——switch 须为组首
#: token 才可整组转写（``{\xyz\em X}`` 前段不在开关作用域，保守不动）；
#: ``(?<![\\])`` 挡 ``\{`` 转义花括号误中；横向空白口径挡行间注释
#: ``{%c\n\em X}`` 被静默吞进参数形；长名先列防 ``bf`` 前缀截
#: ``bfseries``（``CMD_BOUNDARY`` 本可兜住，显式排序双保险）。
_MATH_SWITCH_RE: Final = re.compile(
    r"(?<!\\)\{[^\S\n]*\\(bfseries|itshape|rmfamily|sffamily|ttfamily|em|it|bf)"
    + CMD_BOUNDARY
)

#: 数学域内 cite 族命令 ``\mbox`` 包裹清单——revtex4-2+natbib 链路
#: ``\cite`` → ``\rtx@citex`` → ``\NAT@citex``/``\@citex`` 的未定义引用标记是
#: ``{\reset@font\bfseries ?}`` **无盒**直排（natbib.sty:385/518；alias 路径
#: :607 同形 ``(alias?)``），``\bfseries`` 在数学域触发 ``\not@math@alphabet``
#: 硬报 ``Command \bfseries invalid in math mode``（gr-qc/9901082
#: ``$\phi^i_{\pm}=0 \cite{HawMos}.$`` 实证，tmp/lane-citemath/EVIDENCE.md）。
#: fixloop halt_on_error 让编译死在 thebibliography 之前、``\bibcite`` 永不
#: 写回 aux → 引用每轮保持未定义 → 同错自续；``\mbox{\cite{..}}`` 把标记
#: 放回文本域（min6 实证首遍净过），已定义引用盒内外渲染一致（min7）——
#: 命中即裹、不判定义与否。清单取 natbib.sty ``\DeclareRobustCommand`` 全
#: 引用面（含 ``\citeyearpar``/``\citefullauthor``/``\citetalias``/``\citepalias``
#: 与大写句首形 ``\Citet`` 系，同走 ``\@citex``/alias 标记路径）；内核
#: ``\@citex`` 的 ``\hbox`` 包壳路径（plain article）与 ``\ref``/``\eqref``
#: 的 ``\nfss@text`` 本就安全不收；``\citetext`` 是字面文本实参、无引用
#: 标记路径不收。长名先列，``CMD_BOUNDARY`` 兜底整词。
_MATH_CITE_CS_209: Final = (
    "citefullauthor",
    "citeyearpar",
    "citeauthor",
    "Citeauthor",
    "citetalias",
    "citepalias",
    "citeyear",
    "citealt",
    "citealp",
    "citenum",
    "Citealt",
    "Citealp",
    "citep",
    "citet",
    "Citep",
    "Citet",
    "cite",
)

_MATH_CITE_RE: Final = re.compile(
    r"\\(" + "|".join(_MATH_CITE_CS_209) + r")" + CMD_BOUNDARY
)

#: ``$`` 系定界之外的数学环境（209 内建 + amsmath/amstex/IEEE/breqn 族）——
#: 环境体整段按数学域处理。同名 begin/end 栈式配对；未闭合 begin 不成域
#: （编译本即死，域内修复无意义，保守弃）。
_MATH_ENVS_209: Final = frozenset(
    {
        "math",
        "displaymath",
        "mathdisplay",
        "equation",
        "equation*",
        "eqnarray",
        "eqnarray*",
        "gather",
        "gather*",
        "align",
        "align*",
        "flalign",
        "flalign*",
        "multline",
        "multline*",
        "alignat",
        "alignat*",
        "xalignat",
        "xalignat*",
        "xxalignat",
        "gathered",
        "aligned",
        "alignedat",
        "split",
        "multlined",
        "IEEEeqnarray",
        "IEEEeqnarray*",
        "dmath",
        "dmath*",
        "dgroup",
        "dgroup*",
    }
)

_MATH_ENV_RE: Final = re.compile(
    r"\\(begin|end)\{("
    + "|".join(re.escape(n) for n in sorted(_MATH_ENVS_209, key=len, reverse=True))
    + r")\}"
)

#: 数学域内实参为文本域的命令及其 ``{...}`` 实参数——``\mbox{...}`` 内是
#: hbox 文本域，``{\em}`` 合法；转 ``\mathit`` 反而报错，作排除域。实参数
#: 逐个消耗防 ``\textbf{A} {\em B}$`` 后组被误吞成命令实参；``[..]``
#: 可选参跳过不计数。
_TEXTARG_CS_209: Final = {
    "mbox": 1,
    "fbox": 1,
    "makebox": 1,
    "framebox": 1,
    "raisebox": 2,
    "parbox": 2,
    "sbox": 1,
    "savebox": 1,
    "hbox": 1,
    "vbox": 1,
    "vtop": 1,
    "text": 1,
    "textrm": 1,
    "textsf": 1,
    "texttt": 1,
    "textmd": 1,
    "textbf": 1,
    "textup": 1,
    "textit": 1,
    "textsl": 1,
    "textsc": 1,
    "textnormal": 1,
    "emph": 1,
    "intertext": 1,
    "shortintertext": 1,
}

_TEXTARG_CS_RE: Final = re.compile(
    r"\\("
    + "|".join(sorted(_TEXTARG_CS_209, key=len, reverse=True))
    + r")"
    + CMD_BOUNDARY
)

#: ``\sbox``/``\savebox`` 首参是盒子寄存器 ``\cs``——非 ``{...}`` 实参，
#: 消耗一 token 不计实参数。
_BOXREG_CS_209: Final = frozenset({"sbox", "savebox"})

_BOXREG_RE: Final = re.compile(r"\s*\\[a-zA-Z@]+\*?")

#: ``\hbox``/``\vbox``/``\vtop`` 可带 ``to <dim>``/``spread <dim>`` 盒规格
#: ——消耗规格词（dimen 可裸值或 ``\cs``）再认 ``{...}`` 实参。
_BOXSPEC_CS_209: Final = frozenset({"hbox", "vbox", "vtop"})

_BOXSPEC_RE: Final = re.compile(
    r"\s*(?:to|spread)(?![a-zA-Z])\s*"
    r"(?:\\[a-zA-Z@]+\*?|[-+]?(?:\d+\.?\d*|\.\d+)\s*[a-zA-Z]{1,3})"
)

#: 209 内建残留的 compat 块——随转换产物注入，全部幂等/守护式定义。
#: 后半块是 209 时代序言面残留：``\ifnfssone``/``\ifnfsstwo``/
#: ``\ifCUPmtlplainloaded``（mn→mnras 稿序言的 CUP 三闸模板：oldfss 已置
#: false 跳 ``{\rm}`` 支；nfssone/nfsstwo 皆置 false——mnras.cls:214-343
#: 已原生吸收 ``\rmn``/``\mathbfss``/``\upi``/``\leqslant`` 全套模板宏，
#: 任一支进真都会 ``\newcommand`` 撞类定义硬错；CUPmtlplainloaded 由
#: mnras.cls:1707 自携，守护只为无类补给的文稿——astro-ph/9901066 实证）；
#: 旧字体开关 ``\rm``..``\sc``（article.cls:490-496
#: 逐字面——elsarticle/瘦 .cls 壳一条不声明，随源 .sty 体在装载期就消费
#: ``\bf``/``\it``：aipproc.sty:74-84,331-334,1189+,1409+，astro-ph/0104245
#: 实证）；``\cal`` 取 latex209.def:290 本家形（amsart.cls:452 系注释掉的
#: compat-only 残留，math-ph/0408053 实证）；plain/lfonts 字体系
#: ``\tenrm``/``\*mi``（hep-th/9901066 ``\tenrm``、hep-th/9703214
#: ``\skewchar\fivmi`` 全族实证）；``\theorembodyfont``→amsthm
#: ``\thm@bodyfont`` 转寄（math/9901046 ``\theorembodyfont{\sl}`` 实证）；
#: ``\address``/``\collab``/``\abstracts`` 渲染型透传（sprocl/elsart 时代
#: 命令，gr-qc/9901019、hep-ex/9703017、hep-ph/0104302 实证——全在正文位
#: 调用，序言位调用形态无实证不收吞参形）。
COMPAT_SHIM = r"""% texlate: LaTeX 2.09 compatibility shim
\usepackage{latexsym}
\providecommand{\vruleheight}{\vrule height}
\providecommand{\tightenlines}{}
\newif\ifoldfss
\makeatletter
\newif\if@floats
\makeatother
\ifx\footheight\undefined\newlength{\footheight}\fi
% 209 revtex d 列 (decimal) → 兜底为居中列; \newcolumntype 撞已注册列型
% 会报错, 须以 array 内部注册点 \NC@find@<char> 的 \@ifundefined 守护。
% d→c 而非 dcolumn D 列: 胞元含裸 $ 对时 D 列数学包壳翻转出 math 报错。
\makeatletter
\@ifundefined{NC@find@d}{\RequirePackage{array}\newcolumntype{d}{c}}{}
\@ifundefined{ifnfssone}{\newif\ifnfssone}{}
\@ifundefined{ifnfsstwo}{\newif\ifnfsstwo}{}
\@ifundefined{ifCUPmtlplainloaded}{\newif\ifCUPmtlplainloaded}{}
\@ifundefined{rm}{\DeclareOldFontCommand{\rm}{\normalfont\rmfamily}{\mathrm}}{}
\@ifundefined{sf}{\DeclareOldFontCommand{\sf}{\normalfont\sffamily}{\mathsf}}{}
\@ifundefined{tt}{\DeclareOldFontCommand{\tt}{\normalfont\ttfamily}{\mathtt}}{}
\@ifundefined{bf}{\DeclareOldFontCommand{\bf}{\normalfont\bfseries}{\mathbf}}{}
\@ifundefined{it}{\DeclareOldFontCommand{\it}{\normalfont\itshape}{\mathit}}{}
\@ifundefined{sl}{\DeclareOldFontCommand{\sl}{\normalfont\slshape}{\@nomath\sl}}{}
\@ifundefined{sc}{\DeclareOldFontCommand{\sc}{\normalfont\scshape}{\@nomath\sc}}{}
\@ifundefined{cal}{\DeclareSymbolFontAlphabet{\cal}{symbols}}{}
\@ifundefined{tenrm}{\font\tenrm=cmr10}{}
\@ifundefined{fivmi}{\font\fivmi=cmmi5}{}
\@ifundefined{sixmi}{\font\sixmi=cmmi6}{}
\@ifundefined{sevmi}{\font\sevmi=cmmi7}{}
\@ifundefined{egtmi}{\font\egtmi=cmmi8}{}
\@ifundefined{ninmi}{\font\ninmi=cmmi9}{}
\@ifundefined{tenmi}{\font\tenmi=cmmi10}{}
\@ifundefined{elvmi}{\font\elvmi=cmmi10 scaled\magstephalf}{}
\@ifundefined{twlmi}{\font\twlmi=cmmi10 scaled\magstep1}{}
\@ifundefined{frtnmi}{\font\frtnmi=cmmi10 scaled\magstep2}{}
\@ifundefined{svtnmi}{\font\svtnmi=cmmi10 scaled\magstep3}{}
\@ifundefined{twtymi}{\font\twtymi=cmmi10 scaled\magstep4}{}
\@ifundefined{theorembodyfont}{\def\theorembodyfont#1{\@ifundefined{thm@bodyfont}{}{\thm@bodyfont{#1}}}}{}
\@ifundefined{address}{\providecommand{\address}[1]{#1}}{}
\@ifundefined{collab}{\providecommand{\collab}[1]{#1}}{}
\@ifundefined{abstracts}{\providecommand{\abstracts}[1]{#1}}{}
% plain-TeX 移植残留家族——209 稿常整段搬 plain 宏（hep-th/9703214
% \supereject/\hang/\textindent/\centerline×12/\ninepoint/\sevenrm/
% \sevenbf/\tenbf/\pageno/\advancepageno/\makefootline/\leftline/
% \pagebody/\almostshipout 全调用实证；\<x>fam 是 plain \newfam 数学族
% 寄存器，tcilatex/AMS-\text 机 \csname<x>fam\endcsname 动态消费，
% quant-ph/9703040 \bffam/\slfam 50 击实证——随族须给 \textfont 赋值
% 否则 \the\textfont 读空族照样炸）
\@ifundefined{supereject}{\def\supereject{\par\penalty-\@MM}}{}
\@ifundefined{leftline}{\long\def\leftline#1{\hbox to\hsize{#1\hss}}}{}
\@ifundefined{centerline}{\long\def\centerline#1{\hbox to\hsize{\hss#1\hss}}}{}
\@ifundefined{hang}{\def\hang{\hangindent\parindent\hangafter\@ne}}{}
\@ifundefined{textindent}{\def\textindent#1{\indent\llap{#1\enspace}\ignorespaces}}{}
\@ifundefined{footline}{\newtoks\footline}{}
\@ifundefined{makefootline}{\def\makefootline{\baselineskip24pt\hbox to\hsize{\the\footline}}}{}
\@ifundefined{pagebody}{\def\pagebody{\vbox to\vsize{\unvbox\@cclv}}}{}
\@ifundefined{almostshipout}{\def\almostshipout#1{\shipout\vbox{#1}}}{}
\@ifundefined{pageno}{\countdef\pageno=\z@}{}
\@ifundefined{advancepageno}{\def\advancepageno{\ifnum\pageno<\z@\global\advance\pageno\m@ne\else\global\advance\pageno\@ne\fi}}{}
\@ifundefined{ninepoint}{\def\ninepoint{\fontsize{9}{11}\selectfont}}{}
\@ifundefined{fivebf}{\font\fivebf=cmbx5}{}
\@ifundefined{sevenrm}{\font\sevenrm=cmr7}{}
\@ifundefined{sevenbf}{\font\sevenbf=cmbx7}{}
\@ifundefined{tenbf}{\font\tenbf=cmbx10}{}
\@ifundefined{tenit}{\font\tenit=cmti10}{}
\@ifundefined{tensl}{\font\tensl=cmsl10}{}
\@ifundefined{bffam}{\newfam\bffam\textfont\bffam=\tenbf\scriptfont\bffam=\sevenbf\scriptscriptfont\bffam=\fivebf}{}
\@ifundefined{itfam}{\newfam\itfam\textfont\itfam=\tenit}{}
\@ifundefined{slfam}{\newfam\slfam\textfont\slfam=\tensl}{}
% multicol 机寄存器——文稿可自携 ``multicols`` 定义不走剥包路
% （revpre:262-273 自携体裸消费 ``\col@number``，cond-mat/9910148 实证；
% ltxgrid ``\ifnum\col@number>\@ne`` 亦读），故分配件放通用块而非
% ``_MULTICOLS_SHIM`` 的环境闸内。``\multicolsep`` 同理（正文裸赋值，
% rnbc8.tex:314）。
\@ifundefined{col@number}{\newcount\col@number}{}
\@ifundefined{multicolsep}{\newlength{\multicolsep}}{}
\@ifundefined{@kludgeins}{\newinsert\@kludgeins}{}
% 209 类环境代供的草稿寄存器——随源 .sty 裸消费不自分配：prx.sty:49-61
% ``\@makethincaption`` 体 ``\setbox\@testboxa``/``\outertabfalse``/
% ``\@testboxb`` + ``\ifdim\wd\@testboxa``（cond-mat/9910148，每 fcaption
% 6 起 undefined + ``\wd`` 缺数级联实证）；``\outertab`` 是 ``\newif`` 旗。
\@ifundefined{@testboxa}{\newbox\@testboxa}{}
\@ifundefined{@testboxb}{\newbox\@testboxb}{}
\@ifundefined{ifoutertab}{\newif\ifoutertab}{}
\makeatother"""


#: 2.09 内核浮体间距寄存器——latex209.def:167-168 在 compat 入口（类/样式
#: 装载之前）分配；2e 内核不分配，209 时代类体在装载期就裸赋值消费
#: （aipproc.sty:207/213 ``\@maxsep 20pt``/``\@dblmaxsep 20pt``,
#: astro-ph/0104245）。必须在 ``\documentclass`` 之前执行——COMPAT_SHIM 落
#: 在 docclass 行后，类装载缝已过，寄存器来不及定义。
_PRE_CLASS_SHIM = r"""% texlate: LaTeX 2.09 kernel registers (pre-class)
\makeatletter
\@ifundefined{@maxsep}{\newdimen\@maxsep}{}
\@ifundefined{@dblmaxsep}{\newdimen\@dblmaxsep}{}
\makeatother"""


#: ``multicols``/``multicols*`` 透传环境——multicol 被剥后正文 ``\begin{multicols}{n}``
#: 仍需可解析（209 revtex 单栏时代作者常用它裹整个正文凑双栏；revtex4-2 的
#: ltxgrid 已接管分页，列数参弃之）。``\newcount\col@number`` 置 0 中和
#: ltxgrid longtable 分支 ``\ifnum\col@number>\@ne`` 的缺数软错。
#: 分配件（``\col@number``/``\multicolsep``）已上移到 COMPAT_SHIM 通用
#: 块——自携 ``multicols`` 定义的文稿不经剥包路也消费寄存器
#: （cond-mat/9910148 实证），本块只剩环境透传。
_MULTICOLS_SHIM = r"""% texlate: multicol incompatible with target class — env passthrough
\makeatletter
\ifx\multicols\@undefined
\newenvironment{multicols}[1]{}{}
\newenvironment{multicols*}[1]{}{}
\fi
\makeatother"""


#: revtex 2.09 文稿面 polyfill——revtex4-2 刻意删掉的 209 面整块补回。
#: 与 fixloop ``_REVTEX209_POLYFILL``（_builtins_shim.py）同义 + 三个
#: 实证扩件；partial 稿不进 fixloop（``--on fail`` 门），补位只能在这里。
#: - ``\frontmatter@init``：209 稿序言裸调 ``\author``/``\address`` 时
#:   ``\collaboration@sw``（cls:2145 在 init 内出生）未定义连锁炸
#:   ``\@argswap``/``\add@AUCO@grp``（cond-mat/9901276 等 8 格实证）；
#:   执行后自封防 init 重入。
#: - ``\twocolumn``：cls:4512 ``\let\twocolumn\@undefined``；209 稿用
#:   ``\twocolumn[\hsize\textwidth...]`` 宽头习惯（cond-mat/0501128:218），
#:   ``[1][]{#1}` 吞可选宽头参透传正文。
#: - ``\@makecol``：cls:3912 同批删；ltxgrid 接管前兜底原 kernel 形。
#: - ``\wideabs``：revtex 3.1 宽摘要命令（hep-ph/0104029 等 5 格实证）。
#: - ``\abstract``/``\endabstract``：cls:2685 ``\frontmatter@maketitle``
#:   内清理删——``\maketitle`` 之后正文调用位必死（hep-ph/0104029
#:   ``\maketitle``:40→``\input{abstract}``:44、cond-mat/9901276
#:   ``\maketitle``:11→``\begin{abstract}``:13 实证）。双位补：shim 期
#:   ``\@ifundefined`` 兜未武装的前置调用；``\appdef`` 挂
#:   ``\frontmatter@maketitle`` 尾在清理后 ``\gdef`` 复活兜后置调用
#:   （init 先行时 cls:3143 ``\let@environment`` 武装真环境优先）；
#:   双 ``\appdef`` 因 init 路由用 ``\let`` 拷贝宏体——``\maketitle``
#:   持旧副本不吃后挂补丁，直挂调用名本身（cls:2702 hyperref 复位
#:   缝则经 frontmatter@maketitle 那份复得）。
#: - ``\pacs``：``\AtBeginDocument`` 重定义压过 cls "must be used before
#:   ``\maketitle``" 闸门（多格二次错误实证）；``\long`` 因实参可含空行。
#: ``\AtBeginDocument`` 参数内单 ``#1``——hook 逐字存 token（f3f013d2）。
_REVTEX209_SHIM = r"""% texlate: revtex 2.09 surface polyfill (revtex4-2 deletes the 209 surface)
\makeatletter
\@ifundefined{frontmatter@init}{}{\frontmatter@init\let\frontmatter@init\relax}
\providecommand{\twocolumn}[1][]{#1}
\@ifundefined{@makecol}{\def\@makecol{\setbox\@outputbox\vbox{\unvbox\@cclv}}}{}
\providecommand{\wideabs}[1]{#1}
\@ifundefined{abstract}{\def\abstract{\par}}{}
\@ifundefined{endabstract}{\def\endabstract{\par}}{}
\@ifundefined{frontmatter@maketitle}{}{\appdef\frontmatter@maketitle{\@ifundefined{abstract}{\gdef\abstract{\par}}{}\@ifundefined{endabstract}{\gdef\endabstract{\par}}{}}}
\@ifundefined{maketitle}{}{\appdef\maketitle{\@ifundefined{abstract}{\gdef\abstract{\par}}{}\@ifundefined{endabstract}{\gdef\endabstract{\par}}{}}}
\AtBeginDocument{\long\def\pacs#1{\par\noindent\textbf{PACS:} #1\par}}
\makeatother"""


def _split_opts(optspan: str | None) -> list[str]:
    """从掩码视图选项段提选项名。

    注释字符已被 ``visible_tex`` 掩成空白、真实空白本就该剥——非空白字符即
    选项文本；逗号切分后空段（被整段注释掉的选项）丢弃。
    """
    if not optspan:
        return []
    compact = "".join(c for c in optspan if not c.isspace())
    return [o for o in compact.split(",") if o]


def _ships_style(root: Path | None, name: str) -> bool:
    """工程树内检出随源 ``<name>.sty``——该选项是随稿样式文件，走 usepackage。"""
    if root is None or ".." in name or not _GLOB_SAFE_RE.fullmatch(name):
        return False
    return any(root.rglob(f"{name}.sty"))


def _uses_ds_at(root: Path | None, cls: str) -> bool:
    """随源 ``<cls>.sty``/``<cls>.cls`` 检出 ``ds@`` 选项分发定义。

    检索面为 ``visible_tex`` 遮盖视图——注释/逐字环境内的 ``ds@`` 字样
    不参与判定（真分发形态见 ``_DS_AT_RE`` 注）。
    """
    if root is None or ".." in cls or not _GLOB_SAFE_RE.fullmatch(cls):
        return False
    for cand in root.rglob(f"{cls}.*"):
        if cand.suffix not in {".sty", ".cls"}:
            continue
        try:
            blob = cand.read_bytes()
        except OSError:
            continue
        if _tar_disguised(blob):
            continue  # tar 伪装件——成员文本可含 ds@ 字样（inject._iter_tex 同闸）
        if _DS_AT_RE.search(visible_tex(decode_tex(blob))):
            return True
    return False


def _target_resolvable(root: Path | None, target: str) -> bool:
    """改名目标类可解析性——工程树 ``<target>.cls`` 或系统 kpsewhich 命中。

    kpsewhich 缺席/探测失败 fail-open：合法映射目标都在系统 texmf，缺工具
    不阻断（``_kpse_resolve`` 同款语义）；真返回空才判不可解析。
    """
    if (
        root is not None
        and _GLOB_SAFE_RE.fullmatch(target)
        and any(root.rglob(f"{target}.cls"))
    ):
        return True
    kpse = shutil.which("kpsewhich")
    if kpse is None:
        return True
    try:
        proc = subprocess.run(  # noqa: S603 — 固定 argv 无 shell
            [kpse, "--", f"{target}.cls"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _route_opts(
    opts: list[str], spec: _ClassSpec | None, root: Path | None, target: str
) -> tuple[list[str], list[str], list[str], list[str]]:
    """选项三路分派 → ``(class_opts, pkg_opts, shipped_hits, stripped)``。

    判别序：209 选项名先经目标类 ``rename`` 表改写成 2e 词汇，再查目标类
    硬不兼容表（剥除）→ 内核选项 → 目标类内建表 → 宏包白名单/随源
    ``.sty`` → 默认落类选项。
    """
    incompat = _INCOMPAT_PKGS.get(target, frozenset())
    cls_opts: list[str] = []
    pkg_opts: list[str] = []
    shipped: list[str] = []
    stripped: list[str] = []
    for opt in opts:
        o = spec.rename.get(opt, opt) if spec is not None else opt
        if o in incompat:
            stripped.append(o)
        elif o in _KERNEL_OPTS or (spec is not None and o in spec.options):
            cls_opts.append(o)
        elif o in _PKG_OPTS or _ships_style(root, o):
            pkg_opts.append(o)
            if o not in _PKG_OPTS:
                shipped.append(o)
        else:
            cls_opts.append(o)
    return cls_opts, pkg_opts, shipped, stripped


def _drop_topskip_assigns(tex: str) -> tuple[str, int]:
    r"""删全文深度 0、语句首位的活 ``\topskip`` 赋值；返回 ``(new_tex, count)``。

    语句首位判定：遮盖视图前缀去空白后尾字符 ∈ ``\n``/``}``/``;``（或文首）。
    该口径挡掉 ``= \topskip``/``\ifdim\topskip``/``\advance\topskip`` 等读用
    位——它们前一位是 ``=`` 或字母，不在白名单。
    """
    vis = visible_tex(tex)
    hits = [
        m
        for m in iter_depth0(_TOPSKIP_ASSIGN_RE, vis)
        if not (prefix := vis[: m.start()].rstrip(" \t")) or prefix[-1] in "\n};"
    ]
    for m in reversed(hits):
        tex = tex[: m.start()] + tex[m.end() :]
    return tex, len(hits)


def _math_env_spans(vis: str) -> list[tuple[int, int]]:
    r"""``\begin{<数学env>}...\end{<同名>}`` 区间——同名栈式配对。

    未闭合 begin 弃（编译本即死）；异名交错由栈深度自然兜底——同名
    env 合法不可嵌套，交错末配对段保守不收。
    """
    stack: dict[str, list[int]] = {}
    spans: list[tuple[int, int]] = []
    for m in _MATH_ENV_RE.finditer(vis):
        kind, name = m.group(1), m.group(2)
        if kind == "begin":
            stack.setdefault(name, []).append(m.start())
        elif stack.get(name):
            spans.append((stack[name].pop(), m.end()))
    return spans


def _textarg_spans(vis: str, pos: int, name: str) -> list[tuple[int, int]]:
    r"""``<name>`` 命令自 ``pos`` 起的 ``{...}`` 实参区间表（文本域排除用）。

    ``[..]`` 可选参跳过不计数；``\sbox`` 系先消耗 ``\cs`` 寄存器参、
    ``\hbox`` 系先消耗 ``to/spread <dim>`` 规格再数 ``{...}``。
    """
    i = pos
    if name in _BOXREG_CS_209:
        m = _BOXREG_RE.match(vis, i)
        if m is not None:
            i = m.end()
    if name in _BOXSPEC_CS_209:
        m = _BOXSPEC_RE.match(vis, i)
        if m is not None:
            i = m.end()
    spans: list[tuple[int, int]] = []
    while len(spans) < _TEXTARG_CS_209[name]:
        while i < len(vis) and vis[i] in " \t\r\n":
            i += 1
        if i >= len(vis) or vis[i] not in "[{":
            break
        e = group_end(vis, i)
        if e <= i:
            break
        if vis[i] == "{":
            spans.append((i, e))
        i = e
    return spans


def _innermost(
    regions: list[tuple[int, int, str]], pos: int
) -> tuple[int, int, str] | None:
    r"""包含 ``pos`` 的最小区间——嵌套域按最内层模态判。

    ``\mbox{${\em}$}`` 内层 ``$`` 域小于 mbox 实参域 → 数学；
    ``$\mbox{{\em}}$`` 反之 → 文本。
    """
    best: tuple[int, int, str] | None = None
    for a, b, mode in regions:
        if a <= pos < b and (best is None or b - a < best[1] - best[0]):
            best = (a, b, mode)
    return best


def _cite_call_end(vis: str, pos: int) -> int:
    r"""``pos`` 起 cite 调用尾端的后一 offset：``*`` + ≤2 ``[..]`` + ``{key}``。

    缺 ``{key}`` 实参返回 ``-1``——裸 ``\cite`` token 裹 ``\mbox{}`` 会让
    ``\@citex`` 把 ``}`` 读成 key 实参，保守不动。``[..]``/``{..}`` 配对
    走 ``group_end``（转义/嵌套/行间注释形态同 ``_textarg_spans`` 口径）。
    """
    i = pos
    n = len(vis)
    for _ in range(3):  # ``*`` 槽 + 两个 ``[..]`` 槽——槽序由实见字符自证
        while i < n and vis[i] in " \t\r\n":
            i += 1
        if i < n and vis[i] == "*":
            i += 1
            continue
        if i < n and vis[i] == "[":
            e = group_end(vis, i)
            if e <= i:
                return -1
            i = e
            continue
        break
    while i < n and vis[i] in " \t\r\n":
        i += 1
    if i >= n or vis[i] != "{":
        return -1
    e = group_end(vis, i)
    return e if e > i else -1


def _math_regions(vis: str) -> list[tuple[int, int, str]]:
    r"""模态域区间表: ``$`` 系定界 + 数学环境体为 ``"m"``, 文本实参域为 ``"t"``。

    ``cs_events_spans`` 配对 ``$..$``/``$$..$$``/``\(..\)``/``\[..]``，
    ``_math_env_spans`` 配对数学环境体；``_TEXTARG_CS_209`` 命令实参为
    文本域——嵌套域由 :func:`_innermost` 按最内层判。无数学域直接返回
    空表（textarg 域无独立意义）。``_fix_math_209`` 与 fixloop
    ``wrap_math_cites`` 共用的模态判定单源。
    """
    _, dollar_spans = cs_events_spans(vis)
    spans = dollar_spans + _math_env_spans(vis)
    if not spans:
        return []
    regions: list[tuple[int, int, str]] = [(a, b, "m") for a, b in spans]
    for m in _TEXTARG_CS_RE.finditer(vis):
        regions.extend((a, b, "t") for a, b in _textarg_spans(vis, m.end(), m.group(1)))
    return regions


def _cite_mbox_edits(
    vis: str, regions: list[tuple[int, int, str]]
) -> tuple[list[tuple[int, int, str]], int]:
    r"""数学域内裸 cite 族调用的两端零宽插入 edits → ``(edits, n_calls)``。

    命中判据与 ``_MATH_CITE_CS_209`` 注同：最内域须数学域、完整调用
    （``_cite_call_end`` 配出 ``{key}``）须含于同一域内。同位插入按
    生成序拼接——相邻调用 ``\cite{a}\cite{b}`` 的左闭 ``}`` 与右开
    ``\mbox{`` 落在同一 offset，``apply_edits`` 同位只按 repl 字典序
    排，须预先拼好（finditer 升序命中保证先闭后开）。
    """
    inserts: dict[int, list[str]] = {}
    n = 0
    for m in _MATH_CITE_RE.finditer(vis):
        inner = _innermost(regions, m.start())
        if inner is None or inner[2] != "m":
            continue
        end = _cite_call_end(vis, m.end())
        if end < 0 or end > inner[1]:
            continue
        inserts.setdefault(m.start(), []).append("\\mbox{")
        inserts.setdefault(end, []).append("}")
        n += 1
    return [(pos, pos, "".join(strs)) for pos, strs in inserts.items()], n


def wrap_math_cites(tex: str) -> tuple[str, int]:
    r"""数学域内裸 cite 族调用 ``\cite[..]{k}`` → ``\mbox{\cite[..]{k}}``；返回 ``(new_tex, n)``。

    ``_fix_math_209`` cite 臂的独立出口——非 209 时代稿 (fixloop
    ``cite_in_math_mbox`` 规则, invalid_in_math 签名) 复用同一模态域
    走查；机制/清单论证见 ``_MATH_CITE_CS_209`` 注。``visible_tex``
    遮盖面定位 + ``apply_edits`` 回填保行号。幂等——已裹调用居
    ``\mbox`` 文本域不再命中。
    """
    vis = visible_tex(tex)
    edits, n = _cite_mbox_edits(vis, _math_regions(vis))
    if not edits:
        return tex, 0
    return apply_edits(tex, edits), n


def _fix_math_209(tex: str) -> tuple[str, int, int]:
    r"""数学域两族受限转写（共用一次模态域走查）→ ``(new_tex, n_switch, n_cite)``。

    switch 组 ``{\em/\it/\bf X}`` → ``\mathit{...}``/``\mathbf{...}``（209 时代
    switch 在 2e 数学域硬报 ``\not@math@alphabet``）；裸 cite 族调用
    ``\cite[..]{k}`` → ``\mbox{\cite[..]{k}}``（未定义引用标记 ``\bfseries``
    同签名硬报且 fixloop 自续，见 ``_MATH_CITE_CS_209`` 注）。

    模态判定：``_math_regions`` 单源——``$`` 系定界 + 数学环境体为数学域、
    ``_TEXTARG_CS_209`` 命令实参为文本域，嵌套域按 :func:`_innermost` 最内层
    判。组/调用整体须含于同一数学域内（越界即残缺形态不动）。定位全在
    ``visible_tex`` 遮盖视图——注释/逐字内容里的同形不参与；回填
    ``apply_edits`` 保行号。cite 包裹是两端零宽插入（``\mbox{``/``}``），
    与 switch 的段替换不争 span——逆序回放下 ``$\cite{{\em x}}$`` 这类
    两族命中互不覆盖。
    """
    vis = visible_tex(tex)
    regions = _math_regions(vis)
    if not regions:
        return tex, 0, 0
    edits: list[tuple[int, int, str]] = []
    n_switch = 0
    for m in _MATH_SWITCH_RE.finditer(vis):
        inner = _innermost(regions, m.start())
        if (
            inner is not None
            and inner[2] == "m"
            and group_end(vis, m.start()) <= inner[1]
        ):
            edits.append(
                (m.start(), m.end(), "\\" + _MATH_SWITCH_209[m.group(1)] + "{")
            )
            n_switch += 1
    cite_edits, n_cite = _cite_mbox_edits(vis, regions)
    edits.extend(cite_edits)
    if not edits:
        return tex, 0, 0
    return apply_edits(tex, edits), n_switch, n_cite


def _primary_docstyle(vis: str) -> re.Match[str] | None:
    r"""首个 brace 深度 0 的 ``\documentstyle``——真声明点。

    深度>0 命中（``\newcommand{\ds}{\documentstyle{..}}`` 宏体、``\ifmain{..}``
    实参）不是声明点——全文搜首个会把 COMPAT_SHIM 塞进 def 体（fuzz I5）。
    """
    return next(iter_depth0(DOCSTYLE_DECL_RX, vis), None)


def upgrade_209(  # noqa: C901 -- 守卫链 + shim 分派逐支对应升级决策条目
    tex: str, *, root: Path | None = None
) -> tuple[str, dict]:
    r"""首个深度 0 ``\documentstyle`` 升级为 2e 形态；返回 ``(new_tex, info)``。

    ``root`` 提供工程树（可选）：选项位检出随源 ``<opt>.sty`` 进 ``\usepackage``；
    未映射类名检出随源 ``<cls>.sty/.cls`` 且含 ``ds@`` 定义 → 拒转。
    残余的活 ``\documentstyle`` 记号（宏体/次分支）逐 token 改名
    ``\documentclass``——compat 下二次声明照样非法。

    ``info["status"]`` ∈ ``converted`` / ``reject`` / ``no-docstyle``；``reject``
    时 ``info["reason"]`` 供 inject 层记 ``inject_reject:<reason>``。
    """
    vis = visible_tex(tex)
    m = _primary_docstyle(vis)
    if m is None:
        if next(iter_depth0(DOCSTYLE_RX, vis), None) is not None:
            # 深度 0 裸 ``\documentstyle`` token 在场但配不出 ``[opt]{cls}``
            # 声明（残缺尾、选项段异常）——inject.find_docclass_ends 同深度
            # 口径会把它当缝走到这里，泛 ``latex209`` 落账混进真 209 拒收，
            # 细分签名供归因。深度>0 宏体残影（未闭合花括号内 token）
            # 不进此桶——inject 同深度口径也不会触达。
            return tex, {"status": "reject", "reason": "latex209_no_decl"}
        return tex, {"status": "no-docstyle"}
    cls = m.group(2).strip()
    if not cls:
        return tex, {"status": "no-docstyle"}
    if cls in _DS_AT_CLASSES or (
        cls not in _CLASS_MAP and cls not in _STD_CLASSES and _uses_ds_at(root, cls)
    ):
        return tex, {
            "status": "reject",
            "reason": "latex209_ds_at",
            "class": cls,
        }
    spec = _CLASS_MAP.get(cls)
    target = spec.target if spec is not None else cls
    if target != cls and not _target_resolvable(root, target):
        # 盲升守卫：改名目标类双侧（工程/系统 texmf）不可解析——升上去
        # missing_file 必死（jpsj→jpsj3 类不在 CTAN），拒转记台账。
        return tex, {
            "status": "reject",
            "reason": "latex209_no_target",
            "class": cls,
            "target": target,
        }
    cls_opts, pkg_opts, shipped, stripped = _route_opts(
        _split_opts(m.group(1)), spec, root, target
    )
    lines = [
        _PRE_CLASS_SHIM,
        f"\\documentclass[{','.join(cls_opts)}]{{{target}}}"
        if cls_opts
        else f"\\documentclass{{{target}}}",
        COMPAT_SHIM,
    ]
    if target == "revtex4-2":
        # revtex4-2 删除面整块 polyfill——209 revtex 文稿习惯
        # （\twocolumn[...] 宽头、序言裸 \author、\wideabs、\pacs）
        # partial 稿不进 fixloop（--on fail 门），补位只能在升级缝。
        lines.append(_REVTEX209_SHIM)
    if "multicol" in stripped:
        lines.append(_MULTICOLS_SHIM)
    if pkg_opts:
        # shim 必须先于路由出的 \usepackage——209 时代 .sty 加载时就要见到
        # \footheight/\ifoldfss 等定义（2501.05407 nips.sty 实证）。
        lines.append("\\usepackage{" + ",".join(pkg_opts) + "}")
    new_tex = tex[: m.start()] + "\n".join(lines) + tex[m.end() :]
    # 残余 \documentstyle 记号改名（遮盖视图定位、原文回填，倒序保 offset）。
    vis2 = visible_tex(new_tex)
    for dm in reversed([*DOCSTYLE_RX.finditer(vis2)]):
        new_tex = new_tex[: dm.start()] + "\\documentclass" + new_tex[dm.end() :]
    dropped_topskip = 0
    if target == "revtex4-2":
        # ltxgrid 输出例程不容运行期 topskip 改写（gr-qc/0104075 实证
        # \topskip 0mm → enddoc \clearpage 7 万页死循环）——209 preamble
        # 的裸 topskip 赋值升上来即毒根，逐语句首位活赋值删除。
        new_tex, dropped_topskip = _drop_topskip_assigns(new_tex)
    # 209 数学域两族转写——``{\em X}`` 升上来在数学域必报
    # ``Command \itshape invalid in math mode``（\em 是 switch 非参数形），
    # ``\it``/``\bf`` 同形态归一消歧；裸 ``\cite{..}`` 的 natbib 未定义标记
    # ``{\reset@font\bfseries ?}`` 同签名硬报且 fixloop 自续，裹 ``\mbox{}``。
    new_tex, math_switch_fixed, math_cite_wrapped = _fix_math_209(new_tex)
    return new_tex, {
        "status": "converted",
        "orig": tex[m.start() : m.end()],
        "class": cls,
        "target": target,
        "class_opts": cls_opts,
        "pkg_opts": pkg_opts,
        "shipped": shipped,
        "stripped": stripped,
        "topskip_dropped": dropped_topskip,
        "math_switch_fixed": math_switch_fixed,
        "math_cite_wrapped": math_cite_wrapped,
    }
