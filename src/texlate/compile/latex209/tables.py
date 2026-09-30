r"""compile.latex209.tables — 选项路由静态表叶 (compile.latex209 域缝叶)。

选项名/类名安全字符集、内核/标准类/宏包白名单、209→2e 类名映射
（``_ClassSpec``/``_CLASS_MAP``）、目标类硬不兼容表、``ds@`` 探测与
``\topskip`` 赋值定位正则——纯数据件，零逻辑。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

from texlate.textutil import CMD_BOUNDARY

if TYPE_CHECKING:
    from collections.abc import Mapping

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
    # jpsj → jpsj2：JPSJ 官方 2e 继任类（TL 在库；jpsj3 从未发行，
    # 盲升必 missing_file——seceq/twocolumn 等内建选项原生收）。
    "jpsj": _ClassSpec("jpsj2"),
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
        # hep-ph/0111339 \LongArrow/\Line undefined_cs 实证（axodraw 车道）。
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
#: 但整页被吞 "No pages of output"（双侧实证）。只删
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
