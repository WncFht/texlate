r"""``latex/segmenter`` 共享层——常量/helper/数据类（原模块级原样搬移）。"""

from __future__ import annotations

import re
from bisect import (
    bisect_left,
)
from collections import (
    deque,
)
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    TYPE_CHECKING,
    NamedTuple,
    Protocol,
)

from texlate.latex.macro_table import (
    parse_argspec,
)
from texlate.latex.model import (
    ArgSpec,
    PhType,
    Span,
)
from texlate.latex.placeholder import (
    PH_RX,
)
from texlate.latex.tables import (
    CHUNK_MAX,
    CITE_NAMES,
    MATH_ENVS,
    PROTECTED_ENVS,
    REF_NAMES,
    TRANSPARENT_NAMES,
    VERBATIM_ENVS,
)
from texlate.textutil import (
    mask_tex,
)

if TYPE_CHECKING:
    from texlate.latex.gullet import (
        EnvDef,
    )
    from texlate.latex.model import ArgspecEntry
    from texlate.latex.mouth import (
        Tok,
    )

# 与 scanner.py 同源逐字：可译性口径随 v1（``+`` 折叠会把临界 run 压过
# CHUNK_MIN 阈值 → chunk 召回降，验收门不许）
_CLEAN_CMD_RX = re.compile(r"\\[a-zA-Z@]+\*?|\\[^a-zA-Z]")
_CLEAN_NONALPHA_RX = re.compile(r"[^a-zA-Z]")
_LEAD_WS_RX = re.compile(r"\s*")
_TRAIL_WS_RX = re.compile(r"\s*$")
_COMMENT_GAP_RX = re.compile(r"%[^\n]*")
# 参数体内裸 ``%`` 注释（``\%`` 转义由 ``\\.`` 分支先吃掉）——in_arg 渲染串
# 的 ``%`` 必为真注释（token 层已证非 \verb/url 体内）
_ARG_COMMENT_RX = re.compile(r"\\.|%[^\n]*")
# —— 与 scanner.py 同源的保护/豁免表（S2 scanner 退役时合入 tables.py）
_LETTER_TAIL_RX = re.compile(r"\\[a-zA-Z@]+\Z")


def _starts_letter(s: str) -> bool:
    r"""首字符是 ASCII 字母（TeX 控制词名续名判据——``\\foo``+``中`` 不算熔合）。"""
    return bool(s) and s[0].isascii() and s[0].isalpha()


_PROTECT_TYP = {
    "includegraphics": PhType.GRAPHICS,
    "url": PhType.URL,
    "path": PhType.URL,
    "label": PhType.LABEL,
    "bibliography": PhType.BIB,
    "bibliographystyle": PhType.BIB,
    "bibitem": PhType.BIB,
}
# 组内再生保护段的配对前瞻上限（env/math/delim 扫描步数）
_GRP_SCAN_CAP = 4000
#: 组内 consumed marker 的非副作用白名单（input 换源 / if 选支回放）；
#: 其余 tag（def 族/let/catcode/newif/ifundefined…）都在展开时改过宏表，
#: surface 无法再生其副作用——命中即整组回 literal（_close_group）。
_GRP_FLOW_TAGS = ("input:", "input_tag:", "endinput", "if:", "fi:")

# ---------------------------------------------------------------- 非文本尾参扫
# 裸操作数/赋值形命令的 dimension 尾（loop1 slots 修复）：``\vskip3pt``、
# ``\\[5pt]``、``\hangindent=.5em``、``\vrule width 2pt``、``\font\cs=cmr10
# at 12pt`` 的非文本槽位不在 ``{}`` 组内——探针与组参规则都够不着，单位
# 字母裸进 surface 即被翻译（illegal_unit 主错因）。原子 = cs 操作数
# （``\hskip \labelsep``）或 NUM+UNIT——UNIT 硬性要求（裸数字不是
# dimension）。UNIT 不做字母词界前瞻：TeX 单位扫描是定长关键字匹配，
# ``10ptReceived`` = ``10pt`` + ``Received`` 文本（physics/9901057 实证——
# ``\baselineskip=10pt`` 后紧跟 Received 无空格，前瞻拒配曾致整尾漏进
# surface）。``1in`` 后 ``put`` 等同理。
_DIMEN_NUM = r"(?:\d+[.,]\d*|[.,]\d+|\d+|\.)"
_DIMEN_UNIT = (
    r"(?:true[ \t]*)?"
    r"(?:filll|fill|fil|pt|pc|in|bp|cm|mm|dd|cc|sp|em|ex|mu|zw|zh|px|Q|H)"
)
# 尾参间隙：TeX 空白语义——空格/制表/单换行/``%`` 行注释皆可分隔操作数
# （``\hskip\n 1em`` 2105.00030、``\\\n[8pt]`` hep-ph/0307181、
# ``\\[0pt%\n]`` 1511.06628 实证）；``\n\n`` 段界不跨（par 后是正文）。
# 原子组：三选一首字符互斥（ws/`%`/`\n`），但 ``%[^\n]*`` 变长片在
# ``(?:W)*`` 外层星号下对 ``%%%%``/``%====`` 注释墙有 2^N 重分段——
# ATOM 失配即 ReDoS（illegal_unit 波 held6 实证：老论文头部注释横幅）。
# ``(?>`` 提交单次选择消重分段，语义不变。
_WS_NOPAR = r"(?>[^\S\n]|%[^\n]*|\n(?![ \t\n]*\n))"
# cs 名带 ``(?![a-zA-Z@])`` 边界：切片窗可能切在名中（``_TAIL_CAP``），
# 无边界则 ``\\foo``|``bar`` 斩名半吞。
# 尾参操作数 = ``[+-]? FACTOR* BASE``（TeX ``<number>/<dimen>/<glue>``
# 扫描的因子×基复合）：FACTOR = cs 内部量或裸数（``4\fontdimen``、
# ``\BIBentryALTinterwordstretchfactor\fontdimen``、``0.5\baselineskip``
# 的前件）；BASE = ``NUM[ \t]*UNIT``（物理单位）/``'oct``/``"hex``/cs/
# 裸数。``\fontdimen2\font``/``4\fontdimen3\font``/``\count0`` 皆此形
# （M1-B 残漏实证：natbib ``\BIBentryALTinterwordspacing`` 展开体、
# ``\multiply\ione by 10`` 族）。两硬界：项间零间隙（邻接才成链——
# ``\vskip1em \section`` 的空格断链防误吃下行命令）；NUMUNIT 必为链尾
# （物理单位后 TeX 只续 plus/minus——``2pt\foo`` 的 ``\foo`` 不收）。
_OPERAND_FACTOR = r"(?:\\[a-zA-Z@]+(?![a-zA-Z@])|" + _DIMEN_NUM + r")"
_OPERAND_BASE = (
    _DIMEN_NUM
    + r"[ \t]*"
    + _DIMEN_UNIT
    + r"|'[0-7]+|\"[0-9A-Fa-f]+|\\[a-zA-Z@]+(?![a-zA-Z@])|"
    + _DIMEN_NUM
)
_TAIL_OPERAND = (
    r"(?:"
    + _WS_NOPAR
    + r")*[+-]?(?:"
    + _WS_NOPAR
    + r")*(?:"
    + _OPERAND_FACTOR
    + r")*(?:"
    + _OPERAND_BASE
    + r")"
)
# 扫描终止符：TeX 数/胶扫描遇 ``\relax`` 即停——``1em plus..\relax``/``=1\relax``
# 是惯用收束形，尾随 ``\relax`` 随操作数同收（裸 ``\relax`` 留在表面会被
# INLINE_LITERAL 原样进 chunk）。``(?![a-zA-Z@])`` 防 ``\relaxX`` 长名腰斩。
_TAIL_RELAX = r"(?:(?:" + _WS_NOPAR + r")*\\relax(?![a-zA-Z@]))?"
_TAIL_RX = {
    # skip/dimen：``[=]?<operand> [plus|minus <operand>]* [\relax]``
    "dimen": re.compile(
        r"(?:"
        + _WS_NOPAR
        + r")*=?"
        + _TAIL_OPERAND
        + r"(?:(?:"
        + _WS_NOPAR
        + r")*(?:plus|minus)(?![a-zA-Z])"
        + _TAIL_OPERAND
        + r")*"
        + _TAIL_RELAX
    ),
    # 计数器赋值/操作数：``[=]?<operand> [\relax]``（``\hangafter 1`` 无等
    # 号形同收——operand 的裸数项即原 count 形）
    "count": re.compile(r"(?:" + _WS_NOPAR + r")*=?" + _TAIL_OPERAND + _TAIL_RELAX),
    # ``\hrule``/``\vrule``：``(width|height|depth [=]?<operand>)+``
    "rule": re.compile(
        r"(?:(?:"
        + _WS_NOPAR
        + r")*(?:width|height|depth)(?![a-zA-Z])(?:"
        + _WS_NOPAR
        + r")*=?"
        + _TAIL_OPERAND
        + r")+"
        + _TAIL_RELAX
    ),
    # ``\font\cs=name [at <operand>|scaled NUM]``
    "font": re.compile(
        r"(?:" + _WS_NOPAR + r")*\\[a-zA-Z@]+[ \t]*=?[ \t]*[A-Za-z0-9._/-]+"
        r"(?:[ \t]+at(?![a-zA-Z])[ \t]*"
        + _TAIL_OPERAND
        + r"|[ \t]+scaled(?![a-zA-Z])[ \t]*[+-]?"
        + _DIMEN_NUM
        + r")?"
        + _TAIL_RELAX
    ),
    # 通用赋值：``=<operand>``（``\foo=2pt``/``\foo=2`` 的 ``=N`` 永不
    # 可能是散文——count 形兜底一切表外名，``\hangafter=1`` 同收）
    "assign": re.compile(r"(?:" + _WS_NOPAR + r")*=" + _TAIL_OPERAND + _TAIL_RELAX),
    # 算术/寄存器赋值双操作数：``\multiply\I by 10``/``\advance\D by \G``/
    # ``\divide\I by 2``、``\skewchar\F='77``/``\hyphenchar\F=45``/
    # ``\fontdimen2\font=5pt``/``\countdef\I=5``/``\count0=5``/
    # ``\setbox0=\hbox to3cm``——``by``/``=`` 间隔可省（``\advance\X\Y``），
    # rvalue 后允许 glue 尾（``\advance\S by -2pt plus1pt``）与盒规格尾
    # （``\setbox`` 的 ``\hbox to<dim>``——``to`` 裸落被译的实证在
    # hep-th/9703214、``by`` 在 math/9901091）。
    "arith": re.compile(
        r"(?:"
        + _WS_NOPAR
        + r")*"
        + _TAIL_OPERAND
        + r"(?:(?:"
        + _WS_NOPAR
        + r")*(?:by(?![a-zA-Z])|=)"
        + _TAIL_OPERAND
        + r"(?:(?:"
        + _WS_NOPAR
        + r")*(?:plus|minus)(?![a-zA-Z])"
        + _TAIL_OPERAND
        + r")*"
        + r")?"
        + r"(?:(?:"
        + _WS_NOPAR
        + r")*(?:to|spread)(?![a-zA-Z])"
        + _TAIL_OPERAND
        + r")?"
        + _TAIL_RELAX
    ),
    # 盒规格：``\vbox to3cm{..}``/``\vtop spread-2pt``——``to|spread`` 必在
    # （纯 ``\vbox{..}`` 无尾参，留给常规探针）；``\hbox`` 同形但走
    # 主流透明档前的截获（体文要续扫进 chunk）。
    "boxspec": re.compile(
        r"(?:"
        + _WS_NOPAR
        + r")*(?:to|spread)(?![a-zA-Z])"
        + _TAIL_OPERAND
        + _TAIL_RELAX
    ),
}
# ``\\[5pt]``/``\\*[2em]`` 的可选 dimen 参（``\\`` 走单字符字面行，
# ``[5pt]`` 裸落 surface → illegal_unit——slots① 第二形态）；``\\`` 与
# ``[`` 间允许单换行/注释（``\\\n[8pt]``/``\\[0pt%\n]`` 同收）。
_BSBS_OPT_RX = re.compile(
    r"\*?(?:" + _WS_NOPAR + r")*\[" + _TAIL_OPERAND + r"(?:" + _WS_NOPAR + r")*\]"
)
# 组内 ``\\`` opt 参的内容判据（``_grp_bsbs`` 的 fullmatch 版）
_GRP_BSBS_CONTENT_RX = re.compile(
    r"[ \t]*[+-]?[ \t]*(?:"
    + _OPERAND_FACTOR
    + r")*(?:"
    + _OPERAND_BASE
    + r")(?:[ \t\n]*|%[^\n]*)*"
)
# 组内尾参扫的 surface join 字符窗上限
_GRP_TAIL_CAP = 96
# 主路尾参扫的字节窗上限——尾参物理上数十字节级（数+单位+plus/minus 项），
# 窗帽让任何未来正则病灶代价有界（held6 ReDoS 教训：嵌 _WS_NOPAR 的匹配
# 一律不裸跑全文 haystack）
_TAIL_CAP = 512

# ---- 跨边界待绑参（key-arg 泄漏修复）：展开组尾 cs 的调用点参数吸回组内 ----
# ``\def\r{\ref}``+``\r{key}``：``\ref`` 是展开产物（pos=定义体、origin=
# 调用区间），``{key}`` 是 gen=0 调用点 token（pos==origin 末——`_in_group`
# 的 ``a < o[2]`` 开区间把它挡在组外）→ 无吸纳则 ``{key}`` 落 chunk 被译。
# 槽形 = ``_grp_call_end``/``_grp_probe_end``/``_grp_spec_args_end`` 各步的
# 通用化（组内列扫 ``_slots_walk_toks``、流侧拉取 ``_absorb_slots`` 共用）：
#   s   = 紧邻 ``*``（不跳 ws——``\ref *{k}`` 的星不是星参，call_end 同规）
#   o   = ws + ``[..]`` 平衡组（可选——失配过给下一槽）
#   m   = ws + ``{..}`` 平衡组（失配即调用终止）
#   e   = ws + ``{..}``|``[..]`` 任选一组（hyperref 首参形；失配终止）
#   a   = accent 参（``{..}``|单 letter/other|单字符名 cs；失配终止）
#   b   = ws + ``[dimen]``（``\\`` 尾参；内容须 fullmatch _GRP_BSBS_CONTENT_RX）
#   n   = ws + 单 cs token 或 ``{..}``/``[..]`` 组（``\setlength\parskip``
#         裸名参；强制——失配即调用终止）
#   dXY = ws + ``X..Y`` 定界对（argspec d/D/r/R；可选——失配过槽）
#   tC  = ws + 单测试字符（argspec t；可选）
_PEND_CALL1 = ("s", "o", "o", "o", "m")  # ``_grp_call_end`` mand=1 形
_PEND_CALL2 = ("s", "o", "o", "o", "m", "m")  # inputminted 双 ``{m}``
_PEND_PROBE = ("o", "m", "m", "m", "m", "m", "m")  # ``_grp_probe_end`` 形
_SLOT_PAIR_LEN = 3  # ``dXY`` 槽宽（d + 开/闭定界符）
_SLOT_TEST_LEN = 2  # ``tC`` 槽宽（t + 测试字符）
# 字符串宏体尾 cs 提取（``_keyarg_tail`` 的 MacroEntry 臂）
_KEYARG_TAIL_RX = re.compile(r"\\([a-zA-Z@]+)\s*$")
_KEYARG_TAIL_DEPTH = 4  # ``\a``→``\b``→``\ref`` 别名链递归上限（防环）

# 数学内正文参命令：``{..}`` 参重进文本态，体内 ``$`` 属组内配对、不关外
# 层数学——``_on_math`` 体扫遇此族整参跳扫（``\text{...$x$...}`` 在内层
# ``$`` 截断外层 = 0806.3472 ``missing_character`` 残留面）。``parbox`` 类
# 多参命令不在列（正文非首参，定序跳扫够不着）。
_MATH_TEXTARG_OPT_CAP = 2  # ``makebox``/``framebox`` 式 ``[opt]`` 前缀上限
_MATH_TEXTARG = frozenset(
    {
        "text",
        "intertext",
        "shortintertext",
        "mbox",
        "hbox",
        "fbox",
        "makebox",
        "framebox",
        "emph",
        "textnormal",
        "textrm",
        "textit",
        "textbf",
        "textsf",
        "texttt",
        "textsc",
        "textsl",
        "textup",
        "textmd",
    }
)


def _cite_ref_type(name: str) -> PhType | None:
    r"""cite/ref 词族 → ``PhType``（``_dispatch`` 6/7 行与 ``_group_surface`` 共用）。

    ``href``/``hyperref`` 带可译 text 参不在 REF 列——``*ref`` 后缀规则会把
    ``[label]{text}`` 的 text 整吞进 ``[[REF]]``（两处分派必须同一排除集，
    单边漂移即丢 text 参）。
    """
    if name in CITE_NAMES or name.startswith("cite"):
        return PhType.CITE
    if name in REF_NAMES or (
        name.endswith("ref")
        and name not in TRANSPARENT_NAMES
        and name not in ("href", "hyperref")
    ):
        return PhType.REF
    return None


def _pend_call_slots(name: str) -> list[str]:
    r"""Key-arg 名 → 待绑参槽列（``_grp_call_end`` 同形）。

    ``url``/``path`` 只认 ``{..}`` 形（定界形参无法 token 配对回吸）。
    """
    if name in ("url", "path"):
        return ["m"]
    return list(_PEND_CALL2 if name == "inputminted" else _PEND_CALL1)


def _pend_slot_of(s: ArgSpec) -> str | None:  # noqa: PLR0911 — 槽字母各一分支，平铺即映射表
    r"""``ArgSpec`` → 待绑参槽字母；``e``/``b``/无 delim 形 → ``None``（槽形截尾）。"""
    k = s.kind
    if k in ("m", "v"):
        return "m"
    if k == "n":
        return "n"
    if k in ("o", "O"):
        return "o"
    if k == "s":
        return "s"
    if k == "t" and s.delim:
        return "t" + s.delim[0]
    if k in ("d", "D", "r", "R") and s.delim:
        return "d" + s.delim[0] + s.delim[-1]
    return None


def _env_ph_type(
    env: str, ae: ArgspecEntry | None = None, reg: EnvDef | None = None
) -> PhType | None:
    r"""Env 名 → 保护 ``PhType``（math/verbatim/protected 三族分类单源）。

    ``_group_surface``/``_handle_env_begin`` 共用——三族集合两两不相交，
    判定序无关；``ae.body_role``/``reg.body_role`` 分别是 argspec env 条目
    与用户 ``\newenvironment`` 登记的同名分类（verbatim/math/protect 逐项
    对映）。族表名优先——body_role 不覆盖既有族表分类。
    """
    roles = (
        ae.body_role if ae is not None else "",
        reg.body_role if reg is not None else "",
    )
    if env in VERBATIM_ENVS or "verbatim" in roles:
        return PhType.VERB
    if env in MATH_ENVS or "math" in roles:
        return PhType.MATH
    if env in PROTECTED_ENVS or "protect" in roles:
        return PhType.ENV
    return None


def _pick_cut(s: str, i: int, hard: int) -> int:  # noqa: C901 — 切点优先级链，平铺即 §3.8 规则序
    r"""切点优先级链（§3.8）：``[[X_n]]`` 尾 > 段界 ``\n\n`` > 句读空白 > 硬切。

    返回相对 ``i`` 的切长。硬切兜底：找横跨 ``hard`` 的占位符切到它尾后
    （scanner-audit F7——ph 不腰斩）。``_split_bounds``/``_split_rendered``
    共用（v1 ``_split_core`` 是同源字节版）。
    """
    window = s[i:hard]
    cut = -1
    for m in PH_RX.finditer(window):  # 占位符尾是最安全切点
        cut = m.end()
    if cut <= 0:
        ws = window.rfind("\n\n")
        if ws > 0:
            cut = ws + 2
    if cut <= 0:
        for ch in (". ", "} ", " "):
            ws = window.rfind(ch)
            if ws > CHUNK_MAX // 2:
                cut = ws + len(ch)
                break
    if cut <= 0:
        # 硬切：找横跨 hard 的 token 切到它尾后（scanner-audit F7）
        cut = hard - i
        for m in PH_RX.finditer(s, i):
            if m.start() >= hard:
                break
            if m.end() > hard:
                cut = m.end() - i
                break
    return cut


# 包加载命令：已加载包名集入 ``ScanState.pkgs`` → argspec 门控输入。
# 全部已在 BOUNDARY_NAMES（非 preamble 文档走 row 14 字面档时同步登记）。
_PKG_CMDS = frozenset(
    {"usepackage", "RequirePackage", "documentclass", "documentstyle"}
)
_PKG_ARG_SPEC = [ArgSpec("o"), ArgSpec("m")]


# ------------------------------------------------------------------ vtex


class _Vtex:
    r"""叙事序虚拟文本：``(fid,a,b)`` 源区间按到达序追加为连续坐标。

    ``parts``/``base`` 只增；``slice(a,b)`` 取 vtex 区间内容。
    """

    def __init__(self) -> None:
        """空文档。"""
        self.parts: list[str] = []
        self.base: list[int] = []  # parts[k] 的 vtex 终点

    def __len__(self) -> int:
        """当前 vtex 总长。"""
        return self.base[-1] if self.base else 0

    def cover(self, text: str) -> Span:
        """追加一段源文本，返回其 vtex 区间。"""
        start = len(self)
        self.parts.append(text)
        self.base.append(start + len(text))
        return Span(start, start + len(text))

    def slice(self, a: int, b: int) -> str:
        """``vtex[a:b]``——跨 part 区间逐段收集。"""
        if b <= a:
            return ""
        k = bisect_left(self.base, a + 1)
        out: list[str] = []
        while k < len(self.parts):
            lo = self.base[k - 1] if k else 0
            hi = self.base[k]
            if lo >= b:
                break
            out.append(self.parts[k][max(a, lo) - lo : min(b, hi) - lo])
            if hi >= b:
                break
            k += 1
        return "".join(out)

    def text(self) -> str:
        """全量物化（``res.vtex`` 语义位）。"""
        return "".join(self.parts)


# ------------------------------------------------------------------ token 源


class TokenSource(Protocol):
    """分段器输入抽象——gullet（顶层）或 token 列表（in_arg 子扫）。"""

    def next_expanded(self) -> Tok | None:
        """拉下一枚展开后 token；耗尽 ``None``。"""
        ...

    def read(self) -> Tok | None:
        """原始（不展开）拉取——前瞻/收集用。"""
        ...

    def unread(self, toks: list[Tok]) -> None:
        """回吐前端。"""
        ...

    def skip_past(self, fid: int, end: int) -> None:
        """``fid`` 源对齐到 ``end``——raw 消费段内 token 残骸剔除。"""
        ...


class _ListSource:
    """in_arg 子扫的 token 列表源（token 已展开，read==next_expanded）。

    ``deque`` 而非 list：大体 env/arg 子扫下 ``pop(0)`` 是 O(n)
    memmove——2410.17998 实测 2.4M 次出队吃掉 22s。
    """

    def __init__(self, toks: list[Tok]) -> None:
        """持有待发 token 队列。"""
        self._q = deque(toks)
        # ``_collect_group`` 扫到队尾未配对的 open 位 (pos, gen)：token 列
        # 构造即定（unread 只回放已见 token、skip_past 只删），「无配对」
        # 判终身成立——同 open 的后续探针 O(1) fast-fail，不再 O(尾长) 重扫
        # （2410.17998 实测 145 次失败重扫 = 18.6M/19M token 拉取）。
        self._unmatched_open: set[tuple[tuple[int, int, int], int]] = set()

    def next_expanded(self) -> Tok | None:
        """队首出队。"""
        return self._q.popleft() if self._q else None

    def read(self) -> Tok | None:
        """同 next_expanded（子扫内不再有展开副作用）。"""
        return self.next_expanded()

    def unread(self, toks: list[Tok]) -> None:
        """回插队首（保序）。"""
        self._q.extendleft(reversed(toks))

    def skip_past(self, fid: int, end: int) -> None:
        r"""丢弃 ``pos`` 完全落在 ``end`` 前的队首 token（raw 消费对齐）。

        ``\verb`` 定界体/verbatim env 体在文件字节上找闭合，其间的
        token 早已展开入队——不剔除会被二次分派（体内 ``\end`` 假命中）。
        """
        while self._q and self._q[0].pos[0] == fid and self._q[0].pos[2] <= end:
            self._q.popleft()


# ------------------------------------------------------------------ segmenter


@dataclass(slots=True)
class _RunItem:
    """run 双轨项：surface 进译文面，ident 进 identity 面。"""

    surface: str
    ident: str
    vstart: int  # 本项覆盖的 vtex 区间起点（ph 项 = token 落位）
    vend: int


class _EnvDeadTok(NamedTuple):
    r"""``_find_env_end`` 失败墓标（F12 token 版）：同 target 后续查询免重扫。

    事件位 = 失败扫描 ``collected`` 内的**拉取序号**（seq——天然跨 fid
    全序；不用源侧游标计数器：展开消费/``process_if`` 选支丢弃/unread
    重拉会复用游标槽位，pos 锚才稳定）。查询定位 = 本次 ``\begin`` tag
    首 token 的 ``pos`` 在 ``begin_pos`` 命中（失败扫描到过 EOF，本查询
    tag 必已录；verbatim 跳读区内的除外——未录即落正常扫描）。盈余判据
    ``S(seq)`` 与 v1 ``_EnvDead`` 同式；命中后按 ``end_tag`` 文件区间
    ``(fid, tag_start, tag_end)`` 回放拉取（end_ret 的 token 版）。
    """

    sig: frozenset  # target 端点宏签名（scope 链快照——迟到 \def 即废标）
    begins: list[int]  # \begin{target}/env_begin 宏事件 seq
    begin_pos: list[tuple[int, int, int]]  # 各事件首 token pos（查询锚）
    bidx: dict[tuple[int, int, int], int]  # begin_pos → begins 下标
    ends: list[int]  # \end{target}/env_end 宏事件 seq
    end_tag: list[tuple[int, int, int]]  # (fid, tag_start, tag_end) 回放界
    s_end: list[int]  # S(ends[k]) = bisect_left(begins, ends[k]) - k


@dataclass(slots=True)
class _ArgTok:
    """token 版 ``ArgSpan``：content/full 的文件区间 + 去括号内容 token。

    ``all_toks`` = 本参数消费的全部 token（含括号/定界符）——调用方放弃
    参数路径时整体 ``unread`` 回放（字节版 ``pos`` 不前进的等价物）。
    缺省可选参 = 零宽占位（``fs==fe``，``all_toks`` 空），保 spec 位序。
    """

    fid: int
    cs: int  # content 起点（去括号）
    ce: int
    fs: int  # full 起点（含括号；单 token 参数 fs==cs 且 fe==ce）
    fe: int
    toks: list[Tok] = field(default_factory=list)  # 去括号内容 token
    all_toks: list[Tok] = field(default_factory=list)
    spec: ArgSpec | None = None


_CHUNK_SPEC_CACHE: dict[str, list[ArgSpec]] = {}


def _chunk_spec_cached(spec_str: str) -> list[ArgSpec]:
    """``CHUNK_ARG_SPEC`` 签名串 → ``list[ArgSpec]``（解析一次缓存）。"""
    if spec_str not in _CHUNK_SPEC_CACHE:
        _CHUNK_SPEC_CACHE[spec_str] = parse_argspec(spec_str)
    return _CHUNK_SPEC_CACHE[spec_str]


_PREAMBLE_RX = re.compile(r"\\(documentclass|documentstyle)(?![a-zA-Z])")
_DOC_BEGIN_RX = re.compile(r"\\begin\s*\{document\}")


def _doc_begin_of(tex0: str) -> int:
    r"""fid-0 ``\\begin{document}`` 的 ``\\begin`` 起点（v1 mask 视图双门同规则）。"""
    masked = mask_tex(tex0)
    mdoc = _DOC_BEGIN_RX.search(masked)
    mpream = _PREAMBLE_RX.search(masked)
    return mdoc.start() if (mpream and mdoc) else -1
