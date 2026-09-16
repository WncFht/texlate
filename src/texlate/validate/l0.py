r"""L0 规则校验层 —— stdlib always-on，src↔zh 相对判定（规格 docs/08 §2.1）。

定位：校验链第一层，LLM 每返回一个 chunk 立即校验（实测 0.57ms/对）。
独立于任何 LaTeX 解析器（pylatexenc 静默截断的教训——校验器必须异构），
也是 node 不可用时的兜底路径。

设计原则 = "译文不得比原文更坏"：每条检查都是 src↔zh 比较而非 zh 绝对判定，
src 自带的不平衡/不一致不追责（继承容忍），只报 zh 相对 src 的新增损伤。

十一条规则（docs/08 §2.1 表 + E21/E22 修订口径 + 注释区/粘合/回显/ph_in_cs/裸 cs 补丁）：

  placeholder  ``[[TYPE_n]]``/``[[SL]]``/``[[PL]]`` multiset diff + lev≤2 修复建议；
               E22：严格序守恒降为 warn（``of X``→``X 的`` 合法换序占违例 ~95%），
               硬判据留结构占位符脱位（BIBITEM 行首锚定 + COMMENT 整行锚定：
               ``%`` 展开吞到 EOL，同行非注释邻居皆死字节/splice 残留）。
               注释豁免只盖内容差异——zh 注释区净多出的占位符是 splice 字面
               残留，仍报 error（sabotage 实测逃逸：臆造 ``[[MATH_966]]``
               写进 ``%`` 行）。
  brace        ``{}`` 平衡（``\\{`` ``\\}`` 转义、``%`` 注释豁免）。
  env          ``\\begin/\\end`` 栈配对 + 环境名 multiset 签名差分。
  key          ``\\cite*/\\*ref/\\label/\\bibitem/\\bibliography`` key multiset。
  math         未转义 ``$`` 计数 + ``\\(\\)`` ``\\[\\]`` 成对。
  length       zh/src 长度比（E21 下界放宽到 0.25）+ 剥占位符后 CJK 占比。
  macro        zh 新增控制序列 diff（结构族=error，其余=warn；
               含非 ASCII 字符的融合 cs=error——``\\ ``+中文熔成 ``\\和`` 是
               未定义 cs 编译炸弹）；E21/E22：src→zh 方向脆弱间距命令
               （``\\ `` ``\\,`` ``\\;`` ``\\:`` ``\\!`` ``~``）计数差升硬判据
               cs_dropped，其余丢失 cs 报 warn。
  item_glue    ``\\item`` 紧跟 ASCII 字母粘成 ``\\itemFSU`` 类非法 cs（管线引入
               签名，8 篇实证 Undefined cs 编译炸弹）——zh 净多出计数 → warn；
               ``\\itemsep`` 等合法 cs 与 src 自带粘连靠 src↔zh 净差豁免。
  bare_cs     译文裸 cs 注入两子类 → error（realpostfix2 0905.4907：
               ``\alpha 发射体`` 数学 cs 落文本域 → Missing $ 炸弹；
               ``\itemOC``/``\linebreakGF`` 前缀+含大写后缀粘合 → 未定义
               cs 炸弹）。泛新增 cs 仍归 macro warn，本规则只管编译即炸。
  protocol_echo 交付 zh 净多出协议字面 → error（repro-2410b §4b：corrector
               三段式节标/L0 反馈消息/``slot_validation_failures``/
               ``[compile_error]`` 被当正文回显——multiset 可吻合而载荷脏，
               回显行里 ``[[COMMENT_n]]`` splice 出 ``%`` 吞掉同行结构 ``}``
               实测 early_eof）。词表与 bench ``DIRTY_SIGS`` 同款同序；
               ``[这是译文]``/``[word]`` 合法产出不在表内不误伤。

实测基线（tmp/exp/rule-validator，cases.jsonl 1636 例）：10 类破坏 100% 检出、
313 干净对 0 error-FP。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from texlate.textutil import CJK_RX, lev_capped, mask_comments

__all__ = [
    "Issue",
    "L0Report",
    "Severity",
    "validate_pair",
]

# ---------------------------------------------------------------- 常量

#: ``[[TYPE_n]]`` 正规形 + ``[[SL]]``/``[[PL]]`` 无数字后缀结构标记。
#: 刻意是 ``latex.placeholder.PH_RX`` 的超集——校验侧要认出"长得像占位符"
#: 的一切 token（含 issuer 不会产出的畸形变体），故不能复用产品严格形。
PH_ANY_LIKE_RX: Final = re.compile(r"\[\[[A-Z][A-Z0-9_]*(?:_\d+)?\]\]")

#: 模糊占位符候选（zh 侧变体）：完整 [[..]] / 缺右括号 / 单层 [X_n] / 全角【..】。
PH_FUZZY_RX: Final = re.compile(
    r"\[\[[^\[\]\n]{1,48}?\]\]"  # [[..]] 完整（含全角/空格/小写变体）
    r"|\[\[[^\[\]\n]{1,48}?\](?!\])"  # [[..] 缺右括号
    r"|(?<!\[)\[[A-Za-z_]+_?-?\d+\](?!\])"  # [X_1] 单层括号
    r"|【[^【】\n]{1,48}?】"  # 【..】 CJK 括号
)

#: 从模糊候选里剥出核心 token（去括号/空白），供 lev 配对。
_PH_CORE_RX: Final = re.compile(r"[A-Za-z0-9_]+")

#: 占位符嵌进 cs 名中段：``\cs名[[..]]字母`` 双侧夹持——尾邻无字母的
#: ``\cs[[PH]]`` 是合法高频形（``\protect[[REF_n]]``/``\em[[CMD_n]]``），
#: ``\\`` 控制符号 + ``[[PH]]`` 由必需字母排除。
_PH_IN_CS_RX: Final = re.compile(r"\\[a-zA-Z@]+\[\[[^\[\]\n]{1,48}?\]\][a-zA-Z@]")

#: 数学模式专用命令（文本域出现即 ``Missing $`` 编译炸弹——realpostfix2
#: 0905.4907 ``\alpha 发射体`` 实证签名）。收录内核 + amsmath/amssymb
#: 高频名；表外新名退化走 ``macro`` 泛 warn 兜底，不静默。
#: 刻意不收双模式名（``\ldots``/``\quad``/``\phantom``/``\ensuremath``
#: 文本域合法）与文本族名（``\dag``/``\S``/``\pounds``/``\eqref``）。
_MATH_CS: Final = frozenset(
    """
    alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi
    pi rho sigma tau upsilon phi chi psi omega
    varepsilon varphi varpi varrho varsigma vartheta varkappa digamma
    Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega
    aleph beth daleth gimel hbar hslash imath jmath ell wp Re Im partial
    nabla infty prime emptyset varnothing angle measuredangle sphericalangle
    triangle triangledown vartriangle square diamond lozenge complement
    backslash forall exists nexists neg lnot top bot flat natural sharp
    clubsuit diamondsuit heartsuit spadesuit mho Finv Game eth Bbbk
    mathbb mathcal mathfrak mathscr mathbf mathit mathrm mathsf mathtt
    mathnormal boldsymbol bm pmb
    times div pm mp cdot cdots vdots ddots dotsb dotsc dotsi dotsm dotso ldotp cdotp
    ast star circ bullet oplus ominus otimes oslash odot bigodot bigoplus
    bigotimes cup cap uplus sqcap sqcup setminus smallsetminus amalg wr
    triangleleft triangleright vartriangleleft vartriangleright
    trianglelefteq trianglerighteq ntriangleleft ntriangleright
    ntrianglelefteq ntrianglerighteq bigcirc dagger ddagger vee wedge
    barwedge doublebarwedge curlyvee curlywedge lhd rhd unlhd unrhd
    ltimes rtimes leftthreetimes rightthreetimes divideontimes dotplus
    intercal boxdot boxplus boxminus boxtimes doublecap doublecup Cap Cup
    veebar circledast circledcirc circleddash circledS circledR maltese
    checkmark land lor
    leq le geq ge neq ne equiv sim simeq approx approxeq asymp cong ncong
    nsim backsim backsimeq eqsim thicksim thickapprox doteq doteqdot eqcirc
    circeq risingdotseq fallingdotseq triangleq bumpeq Bumpeq iff
    prec succ preceq succeq preccurlyeq succcurlyeq curlyeqprec curlyeqsucc
    precapprox succapprox precsim succsim precnapprox succnapprox nprec
    nsucc npreceq nsucceq ll gg llless ggless
    lessapprox gtrapprox lesssim gtrsim lesseqgtr gtreqless lesseqqgtr
    gtreqqless lessdot gtrdot lessgtr gtrless lneq lneqq gneq gneqq
    leqslant geqslant eqslantless eqslantgtr nleq ngeq nleqslant ngeqslant
    nleqq ngeqq nless ngtr lnsim gnsim lnapprox gnapprox
    subset supset subseteq supseteq sqsubset sqsupset sqsubseteq sqsupseteq
    subsetneq supsetneq subseteqq supseteqq varsubsetneq varsupsetneq
    varsubsetneqq varsupsetneqq nsubseteq nsupseteq nsubseteqq nsupseteqq
    Subset Supset in ni notin owns vdash dashv vDash Vdash Vvdash nvdash
    nvDash nVdash nVDash models perp mid nmid parallel nparallel shortmid
    shortparallel smile smallsmile frown smallfrown bowtie Join propto
    varpropto between pitchfork therefore because multimap implies impliedby
    to gets mapsto mapsfrom hookrightarrow hookleftarrow rightarrow
    leftarrow Rightarrow Leftarrow leftrightarrow Leftrightarrow
    nrightarrow nleftarrow nRightarrow nLeftarrow nleftrightarrow
    nLeftrightarrow rightleftarrows rightrightarrows leftleftarrows
    Lleftarrow Rrightarrow twoheadrightarrow twoheadleftarrow
    rightarrowtail leftarrowtail looparrowleft looparrowright
    circlearrowleft circlearrowright curvearrowleft curvearrowright
    dashrightarrow dashleftarrow uparrow downarrow updownarrow Uparrow
    Downarrow Updownarrow upuparrows downdownarrows upharpoonleft
    upharpoonright downharpoonleft downharpoonright rightharpoonup
    rightharpoondown leftharpoonup leftharpoondown rightleftharpoons
    leftrightharpoons nearrow searrow swarrow nwarrow longrightarrow
    longleftarrow Longrightarrow Longleftarrow longleftrightarrow
    Longleftrightarrow longmapsto rightsquigarrow leadsto xrightarrow
    xleftarrow
    arccos arcsin arctan arg cos cosh cot coth csc deg det dim exp gcd hom
    inf injlim ker lg lim liminf limsup ln log max min mod pmod bmod pod
    Pr projlim sec sin sinh sup tan tanh varinjlim varliminf varlimsup
    varprojlim
    sum prod int iint iiint iiiint oint oiint idotsint coprod bigcap bigcup
    bigvee bigwedge bigsqcup biguplus smallint intop
    left right middle big bigg Big Bigg bigl bigr bigm biggl biggr Bigl
    Bigr Bigm Biggl Biggr biggm Biggm langle rangle lceil rceil lfloor
    rfloor ulcorner urcorner llcorner lrcorner vert Vert lvert rvert lVert
    rVert lgroup rgroup lmoustache rmoustache bracevert arrowvert Arrowvert
    acute grave ddot dddot ddddot tilde bar breve check hat vec dot
    mathring overline overbrace underbrace widehat widetilde overleftarrow
    overrightarrow overleftrightarrow underleftarrow underrightarrow
    underleftrightarrow
    frac dfrac tfrac cfrac binom dbinom tbinom choose sqrt over atop above
    stackrel overset underset sideset substack operatorname mathop mathrel
    mathbin mathord mathopen mathclose mathinner mathpunct displaystyle
    textstyle scriptstyle scriptscriptstyle limits nolimits nonumber smash
    boxed tag intertext shortintertext not colon centerdot
    medspace thickspace negthinspace negmedspace negthickspace sb sp
    """.split()
)

#: key 承载命令：cite 族 / *ref 族 / label / bibitem / bibliography。
#: 只抓第一个 {..}（key 参数），可选 [..] 先吃掉。
KEY_CMD_RX: Final = re.compile(
    r"\\(?:cite[a-zA-Z]*|[a-zA-Z@]*ref|crefrange|label|bibitem|nocite"
    r"|bibliography|bibliographystyle)\*?"
    r"(?:\s*\[[^\]\n]*\])*"
    r"\s*\{([^{}]*)\}"
)

ENV_RX: Final = re.compile(r"\\(begin|end)\s*\{([^{}]*)\}")


#: zh 内剥命令/占位符用。
_CS_OR_SYM_RX: Final = re.compile(r"\\[a-zA-Z@]+\*?|\\.")

#: 非 ASCII 控制序列名 = 融合产物（`\ `+中文 → `\和`，未定义 cs 编译炸弹）。
_NONASCII_RX: Final = re.compile(r"[^\x00-\x7f]")

#: 结构命令族：zh 新增命中 → error（幻觉结构）。
STRUCT_CMDS: Final = frozenset(
    {
        "appendix",
        "begin",
        "bibliography",
        "bibliographystyle",
        "def",
        "documentclass",
        "documentstyle",
        "edef",
        "end",
        "gdef",
        "include",
        "includegraphics",
        "input",
        "maketitle",
        "newcommand",
        "newcounter",
        "newenvironment",
        "newtheorem",
        "printbibliography",
        "providecommand",
        "renewcommand",
        "RequirePackage",
        "setcounter",
        "setlength",
        "tableofcontents",
        "usepackage",
        "xdef",
    }
)

#: 脆弱间距命令（E21/E22 cs_dropped 硬判据覆盖集）：
#: ``\<空格>`` ``\,`` ``\;`` ``\:`` ``\!`` 为词法层 bs token；``~`` 是活动字符。
FRAGILE_BS: Final = frozenset({"\\ ", "\\,", "\\;", "\\:", "\\!"})
FRAGILE_CHARS: Final = frozenset("~")

#: 结构占位符：必须保持行首锚定（`\bibitem` 脱位 mid-paragraph → 编译损伤）。
STRUCTURAL_PH_RX: Final = re.compile(r"\[\[BIBITEM_\d+\]\]")

#: 注释占位符（``%`` 展开吞到 EOL）。src 独占整行的 ``[[COMMENT_n]]`` 在 zh
#: 所在行必须整行只剩注释占位符——同行非注释邻居，前缀是 splice 残留垃圾、
#: 后缀是被注释吃掉的死字节（repro-2410b §4c）；src 行中的（ph 恒行尾，
#: 注释天然吃到换行）zh 尾段同样只许注释占位符。
COMMENT_PH_RX: Final = re.compile(r"\[\[COMMENT_\d+\]\]")
_COMMENT_LINE_RX: Final = re.compile(r"[ \t]*(?:\[\[COMMENT_\d+\]\][ \t]*)+")
_COMMENT_TAIL_RX: Final = re.compile(r"(?:[ \t]*\[\[COMMENT_\d+\]\])*[ \t]*")

#: 协议回显签名（repro-2410b §4b 交付守卫）：与 bench ``DIRTY_SIGS``
#: （``e2e_mock_bench.py``）同一词表同序——L0 反馈消息实际 emit 串 +
#: 重试协议字面（三段式节标/``previous_validation_error`` 尾拼/
#: ``slot_validation_failures`` 字段/``[compile_error]`` L2 回灌标）。
#: 交付 zh 出现即 prompt/反馈被当正文回显；``[这是译文]``/``[word]``
#: 行内合法产出不在表内不误伤。
_ECHO_SIGS: Final = (
    "占位符缺失:",  # _pair_placeholder_typos
    "占位符疑似拼错",  # _pair_placeholder_typos lev 配对臂
    "多余/未识别占位符:",  # _check_placeholder
    "结构占位符",  # _check_ph_anchor "脱离行首位置"
    "注释区内臆造占位符",  # _check_placeholder 注释区专项
    "[Original]",  # prompts.corrector_user 三段式
    "[Translation]",  # prompts.corrector_user
    "[Error]",  # prompts.corrector_user
    "previous_validation_error",  # pipeline 阶梯重试尾拼
    "slot_validation_failures",  # pipeline 批模式失败槽字段
    "[compile_error]",  # pipeline L2 回灌重译
)

#: 阈值常数（E21：长度比下界 0.30 → 0.25，正常 CJK 压缩线）。
LENGTH_RATIO_LO: Final = 0.25
LENGTH_RATIO_HI: Final = 2.50
_MIN_SRC_LEN_FOR_RATIO: Final = 30
CJK_SHARE_MIN: Final = 0.30
_MIN_LATIN_FOR_CJK_CHECK: Final = 8
_LEV_CAP: Final = 2
_ENV_CHECK_TAIL_LIMIT: Final = 50  # end 名偏多 warn 的报告条数上限


class Severity(StrEnum):
    """问题严重度：error=硬判据（不过 → 重译/回退），warn=软信号（聚合参考）。"""

    ERROR = "error"
    WARN = "warn"


@dataclass(frozen=True, slots=True)
class Issue:
    """单条校验发现。

    ``pos`` 是 zh 侧字符偏移（-1 = 无定位）；``expected``/``found``
    承载占位符拼错的修复建议配对。
    """

    rule: str
    severity: Severity
    message: str
    pos: int = -1
    expected: str | None = None
    found: str | None = None

    def to_dict(self) -> dict[str, object]:
        """序列化为 corrector 反馈字段可用的一级字典。"""
        d: dict[str, object] = {
            "rule": self.rule,
            "severity": self.severity.value,
            "message": self.message,
        }
        if self.pos >= 0:
            d["pos"] = self.pos
        if self.expected is not None:
            d["expected"] = self.expected
        if self.found is not None:
            d["found"] = self.found
        return d


@dataclass(slots=True)
class L0Report:
    """一对 (src, zh) 的 L0 校验结果。"""

    src_len: int
    zh_len: int
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """无 error 级发现即过（warn 不阻塞）。"""
        return not any(i.severity is Severity.ERROR for i in self.issues)

    @property
    def n_error(self) -> int:
        """硬判据（error 级）条数。"""
        return sum(1 for i in self.issues if i.severity is Severity.ERROR)

    @property
    def n_warn(self) -> int:
        """软信号（warn 级）条数。"""
        return sum(1 for i in self.issues if i.severity is Severity.WARN)

    def by_rule(self) -> dict[str, list[Issue]]:
        """按规则名分组。"""
        d: dict[str, list[Issue]] = {}
        for i in self.issues:
            d.setdefault(i.rule, []).append(i)
        return d

    def to_dict(self) -> dict[str, object]:
        """序列化（state.json / errors_report 可落盘）。"""
        return {
            "ok": self.ok,
            "src_len": self.src_len,
            "zh_len": self.zh_len,
            "n_error": self.n_error,
            "n_warn": self.n_warn,
            "issues": [i.to_dict() for i in self.issues],
        }

    def feedback(self) -> str:
        """给带错重翻 corrector 的紧凑错误描述（docs/08 §1.2 反馈字段化）。"""
        return "\n".join(i.message for i in self.issues if i.severity is Severity.ERROR)

    def __str__(self) -> str:
        """PASS/FAIL 头 + 逐条 ``[级别] 规则: 描述``。"""
        head = (
            f"{'PASS' if self.ok else 'FAIL'} (err={self.n_error} warn={self.n_warn})"
        )
        if not self.issues:
            return head
        lines = [
            f"  [{i.severity.value:5s}] {i.rule}: {i.message}" for i in self.issues
        ]
        return head + "\n" + "\n".join(lines)


# ---------------------------------------------------------------- 词法层


def _lex(s: str) -> list[tuple[str, str, int]]:
    r"""逐字符扫出 ``(kind, text, pos)`` 三元组。

    kind：``cs`` 控制字（不含反斜杠）、``bs`` 控制符号（``\\`` + 单字符，
    含 ``\\{`` ``\\%`` ``\\ ``）、``cmt`` 注释、``ch`` 其余字符。
    不做解析，只做转义/注释豁免——校验器刻意不依赖完整语法。
    """
    out: list[tuple[str, str, int]] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "%":
            nl = re.search(r"[\r\n]", s[i:])
            j = n if nl is None else i + nl.start()
            out.append(("cmt", s[i:j], i))
            i = j
            continue
        if c == "\\":
            j = i + 1
            if j < n and s[j].isalpha():
                k = j
                while k < n and (s[k].isalpha() or s[k] == "@"):
                    k += 1
                out.append(("cs", s[j:k], i))
                i = k
                continue
            j2 = min(i + 2, n)
            out.append(("bs", s[i:j2], i))
            i = j2
            continue
        out.append(("ch", c, i))
        i += 1
    return out


# ---------------------------------------------------------------- 规则组


def _pair_placeholder_typos(
    missing: list[str], cands: list[str], issues: list[Issue]
) -> set[int]:
    """缺失占位符 ↔ 模糊候选 lev≤2 贪心配对；返回已消耗的候选下标。"""
    used: set[int] = set()
    for ph in missing:
        ph_core = ph.strip("[]")
        best: tuple[int, str] | None = None
        bestd = _LEV_CAP + 1
        for ci, cand in enumerate(cands):
            if ci in used:
                continue
            core = _PH_CORE_RX.search(cand)
            cand_core = core.group(0) if core else cand
            d = lev_capped(ph_core, cand_core, _LEV_CAP)
            if d < bestd:
                best, bestd = (ci, cand), d
        if best is not None:
            used.add(best[0])
            issues.append(
                Issue(
                    "placeholder",
                    Severity.ERROR,
                    f"占位符疑似拼错: '{best[1]}' 应为 '{ph}' (lev={bestd}, 可自动修复)",
                    expected=ph,
                    found=best[1],
                )
            )
        else:
            issues.append(
                Issue("placeholder", Severity.ERROR, f"占位符缺失: {ph}", expected=ph)
            )
    return used


def _line_of(s: str, start: int, end: int) -> str:
    r"""``s`` 中含 ``[start, end)`` 的整行（``\n`` 界，剥尾部 ``\r``）。"""
    lo = s.rfind("\n", 0, start) + 1
    hi = s.find("\n", end)
    line = s[lo:] if hi < 0 else s[lo:hi]
    return line.removesuffix("\r")


def _line_tail(s: str, end: int) -> str:
    r"""``s`` 中 ``end`` 处到行尾的残段（``\n`` 界，剥尾部 ``\r``）。"""
    hi = s.find("\n", end)
    tail = s[end:] if hi < 0 else s[end:hi]
    return tail.removesuffix("\r")


def _check_ph_anchor(snc: str, znc: str, issues: list[Issue]) -> None:
    r"""行锚定占位符脱位 → error（BIBITEM 行首 + COMMENT 整行/行尾两类）。

    BIBITEM 类（E22 硬判据余量）：src 行首锚定的 token 在 zh 带行内前缀
    → ``\\bibitem`` 落进段中编译损伤。
    COMMENT 类（repro-2410b §4c）：``%`` 展开吞到 EOL——src 独占整行的
    ``[[COMMENT_n]]`` 在 zh 同行不得混入非注释内容（前缀是 splice 残留
    垃圾注入注释槽位，后缀是被注释吃掉的死字节）；src 行中的 ph 恒处
    行尾（注释天然吃到换行），zh 尾段混入非注释内容同款报错。
    """
    anchored = {
        m.group(0)
        for m in STRUCTURAL_PH_RX.finditer(snc)
        if not snc[snc.rfind("\n", 0, m.start()) + 1 : m.start()].strip()
    }
    issues.extend(
        Issue(
            "placeholder",
            Severity.ERROR,
            f"结构占位符 {m.group(0)} 脱离行首位置（src 行首锚定，"
            f"脱位会让 \\bibitem 落进段中）",
            m.start(),
            expected=m.group(0),
            found=m.group(0),
        )
        for m in STRUCTURAL_PH_RX.finditer(znc)
        if m.group(0) in anchored
        and znc[znc.rfind("\n", 0, m.start()) + 1 : m.start()].strip()
    )

    cmt_anchored = {
        m.group(0)
        for m in COMMENT_PH_RX.finditer(snc)
        if _COMMENT_LINE_RX.fullmatch(_line_of(snc, m.start(), m.end()))
    }
    for m in COMMENT_PH_RX.finditer(znc):
        if m.group(0) in cmt_anchored:
            seg = _line_of(znc, m.start(), m.end())
            clean = _COMMENT_LINE_RX.fullmatch(seg)
        else:
            seg = _line_tail(znc, m.end())
            clean = _COMMENT_TAIL_RX.fullmatch(seg)
        if clean:
            continue
        issues.append(
            Issue(
                "placeholder",
                Severity.ERROR,
                f"注释占位符 {m.group(0)} 所在行混入非注释内容"
                f"（% 展开吞到行尾，同行邻居是死字节/splice 残留）"
                f": {seg.strip()!r}",
                m.start(),
                expected=m.group(0),
                found=m.group(0),
            )
        )


def _ph_in_comments(s: str) -> Counter[str]:
    r"""注释区（``%``→行尾，``\%`` 豁免）内正规形占位符计数。

    mask 口径下注释区整体不可见，必须单独点算——zh 注释里臆造的占位符
    splice 后字面残留（sabotage 实测逃逸），src 自带注释占位符作净差豁免。
    """
    c: Counter[str] = Counter()
    for kind, text, _ in _lex(s):
        if kind == "cmt":
            c.update(PH_ANY_LIKE_RX.findall(text))
    return c


def _check_placeholder(src: str, zh: str, issues: list[Issue]) -> None:
    """占位符 multiset diff + lev≤2 修复配对 + 序守恒软信号 + 行锚定（BIBITEM/COMMENT）。"""
    snc, znc = mask_comments(src), mask_comments(zh)
    sseq = PH_ANY_LIKE_RX.findall(snc)
    zseq = PH_ANY_LIKE_RX.findall(znc)
    scnt, zcnt = Counter(sseq), Counter(zseq)

    # —— 模糊候选：zh 里所有形似占位符但不合正规形的串（扫未遮盖原文——
    #    注释里的拼错候选一样喂 lev 配对，修复建议方向仍对）。
    #    src 中 verbatim 存在的同形 token（如引用标号 [RS80]）是原文内容而非
    #    臆造占位符——按净差计数豁免（validbench 干净对 FP 修复）——
    src_literal = Counter(
        m.group(0)
        for m in PH_FUZZY_RX.finditer(src)
        if not PH_ANY_LIKE_RX.fullmatch(m.group(0))
    )
    zh_fuzzy = [
        m.group(0)
        for m in PH_FUZZY_RX.finditer(zh)
        if not PH_ANY_LIKE_RX.fullmatch(m.group(0))
    ]
    missing = sorted((scnt - zcnt).elements())
    cands = list((zcnt - scnt).elements())
    cands += list((Counter(zh_fuzzy) - src_literal).elements())
    used = _pair_placeholder_typos(missing, cands, issues)
    issues.extend(
        Issue("placeholder", Severity.ERROR, f"多余/未识别占位符: {cand}", found=cand)
        for ci, cand in enumerate(cands)
        if ci not in used
    )

    # —— E22：序守恒降软信号（of X→X 的 合法中文换序占违例 ~95%）——
    if not (scnt - zcnt) and not (zcnt - scnt) and sseq != zseq:
        issues.append(
            Issue(
                "placeholder",
                Severity.WARN,
                "占位符顺序与原文不一致（合法中文换序常见，splice 不伤）",
            )
        )

    # —— 注释区占位符专项检查：zh 注释内净多出的占位符是 splice 字面残留
    #    （mask 比对看不见，sabotage 实测逃逸）。反向"正文占位符被挪进注释"
    #    已由上方 masked multiset 的 missing 方向捕获，此处只报多出。
    extra_cmt = _ph_in_comments(zh) - _ph_in_comments(src)
    issues.extend(
        Issue(
            "placeholder",
            Severity.ERROR,
            f"注释区内臆造占位符: {tok} ×{n}（splice 后字面残留）",
            found=tok,
        )
        for tok, n in sorted(extra_cmt.items())
    )

    _check_ph_anchor(snc, znc, issues)


def _brace_profile(s: str) -> tuple[int, int, int, int, int]:
    """``(open数, close数, 净深度, 最小前缀深度, 首个负深度pos)``。"""
    depth = opens = closes = minpref = 0
    first_neg = -1
    for kind, ch, pos in _lex(s):
        if kind != "ch":
            continue
        if ch == "{":
            depth += 1
            opens += 1
        elif ch == "}":
            depth -= 1
            closes += 1
            minpref = min(minpref, depth)
            if depth < 0 and first_neg < 0:
                first_neg = pos
    return opens, closes, depth, minpref, first_neg


def _check_brace(src: str, zh: str, issues: list[Issue]) -> None:
    """``{}`` 平衡：zh 最小前缀深度 < src 最小前缀深度，或净余额不同 → error。"""
    so, sc, sd, smin, _ = _brace_profile(src)
    zo, zc, zd, zmin, zneg = _brace_profile(zh)
    if zmin < smin:
        issues.append(
            Issue(
                "brace",
                Severity.ERROR,
                f"'}}' 透支: pos {zneg} 处深度 {zmin} < 原文最小深度 {smin}",
                zneg,
            )
        )
    if zd != sd:
        issues.append(
            Issue(
                "brace",
                Severity.ERROR,
                f"brace 净余额不同: src {sd:+d} vs zh {zd:+d} "
                f"(src open={so} close={sc}, zh open={zo} close={zc})",
            )
        )
    elif (zo, zc) != (so, sc):
        issues.append(
            Issue(
                "brace",
                Severity.WARN,
                f"brace 计数不同但净额一致: src open={so} close={sc} vs "
                f"zh open={zo} close={zc}",
            )
        )


def _env_tokens(s: str) -> list[tuple[str, str, int]]:
    """``(begin|end, 环境名, pos)`` 事件流（注释豁免）。"""
    return [
        (m.group(1), m.group(2).strip(), m.start())
        for m in ENV_RX.finditer(mask_comments(s))
    ]


def _env_signature(
    s: str,
) -> tuple[int, int, Counter[str], Counter[str], Counter[str]]:
    """``(多余end数, 不匹配数, 未闭合begin名, begin名, end名)`` 栈签名。"""
    stack: list[tuple[str, int]] = []
    n_orphan_end = n_mismatch = 0
    toks = _env_tokens(s)
    for kind, name, pos in toks:
        if kind == "begin":
            stack.append((name, pos))
        elif not stack:
            n_orphan_end += 1
        else:
            if stack[-1][0] != name:
                n_mismatch += 1
            stack.pop()
    begins = Counter(n for k, n, _ in toks if k == "begin")
    ends = Counter(n for k, n, _ in toks if k == "end")
    return n_orphan_end, n_mismatch, Counter(n for n, _ in stack), begins, ends


def _check_env(src: str, zh: str, issues: list[Issue]) -> None:
    r"""``\begin{X}``/``\end{X}`` 栈配对 + 环境名 multiset 签名差分。

    src 自身的内部不一致不追责（继承容忍），只报 zh 新增的栈错误类别。
    """
    s_orph, s_mis, s_left, s_beg, s_end = _env_signature(src)
    z_orph, z_mis, z_left, z_beg, z_end = _env_signature(zh)
    if z_orph > s_orph:
        issues.append(
            Issue(
                "env",
                Severity.ERROR,
                f"多余 \\end{{}}: zh {z_orph} 处 > src {s_orph} 处",
            )
        )
    if z_mis > s_mis:
        issues.append(
            Issue(
                "env",
                Severity.ERROR,
                f"\\end{{}} 名称不匹配: zh {z_mis} 处 > src {s_mis} 处",
            )
        )
    issues.extend(
        Issue("env", Severity.ERROR, f"\\begin{{{name}}} 未闭合 ×{cnt}")
        for name, cnt in (z_left - s_left).items()
    )
    issues.extend(
        Issue("env", Severity.ERROR, f"译文新增环境 \\begin{{{name}}} ×{cnt}")
        for name, cnt in (z_beg - s_beg).items()
    )
    issues.extend(
        Issue("env", Severity.ERROR, f"环境 \\begin{{{name}}} 未保留 ×{cnt}")
        for name, cnt in (s_beg - z_beg).items()
    )
    # end 名 diff 多数已被栈签名覆盖，仅补充 begin/end 同改名的对称情形
    issues.extend(
        Issue("env", Severity.WARN, f"\\end{{{name}}} 比原文多 ×{cnt}")
        for name, cnt in list((z_end - s_end).items())[:_ENV_CHECK_TAIL_LIMIT]
        if z_beg.get(name, 0) <= s_beg.get(name, 0)
    )


def _key_multiset(s: str) -> Counter[str]:
    """cite/ref/label/bib key 多重集（逗号拆分，[..] 可选参豁免）。"""
    c: Counter[str] = Counter()
    for m in KEY_CMD_RX.finditer(mask_comments(s)):
        for raw in m.group(1).split(","):
            key = raw.strip()
            if key:
                c[key] += 1
    return c


def _check_key(src: str, zh: str, issues: list[Issue]) -> None:
    """cite/ref/label/bib key multiset：src−zh=error，zh−src=warn（幻觉引用）。"""
    sk, zk = _key_multiset(src), _key_multiset(zh)
    for k, n in sorted((sk - zk).items()):
        issues.append(
            Issue("key", Severity.ERROR, f"引用/标签 key 丢失: '{k}' ×{n}", expected=k)
        )
    for k, n in sorted((zk - sk).items()):
        issues.append(
            Issue(
                "key", Severity.WARN, f"译文新增 key: '{k}' ×{n} (幻觉引用?)", found=k
            )
        )


def _math_profile(s: str) -> tuple[int, int, int, int, int]:
    r"""``($数, \(数, \)数, \[数, \]数)``（未转义，注释豁免）。"""
    d = lp = rp = lb = rb = 0
    for kind, text, _ in _lex(s):
        if kind == "ch":
            if text == "$":
                d += 1
        elif kind == "bs":
            if text == "\\(":
                lp += 1
            elif text == "\\)":
                rp += 1
            elif text == "\\[":
                lb += 1
            elif text == "\\]":
                rb += 1
    return d, lp, rp, lb, rb


def _check_math(src: str, zh: str, issues: list[Issue]) -> None:
    r"""``$`` ``\(\)`` ``\[\]`` 计数一致性（未转义，注释豁免）。"""
    sd, slp, srp, slb, srb = _math_profile(src)
    zd, zlp, zrp, zlb, zrb = _math_profile(zh)
    if zd != sd:
        issues.append(
            Issue("math", Severity.ERROR, f"'$' 计数不同: src {sd} vs zh {zd}")
        )
    elif zd % 2:
        issues.append(
            Issue(
                "math", Severity.WARN, f"'$' 奇数个 ({zd})，行内数学未闭合 (继承自原文)"
            )
        )
    if (zlp, zrp) != (slp, srp):
        issues.append(
            Issue(
                "math",
                Severity.ERROR,
                f"\\( \\) 计数不同: src ({slp},{srp}) vs zh ({zlp},{zrp})",
            )
        )
    if (zlb, zrb) != (slb, srb):
        issues.append(
            Issue(
                "math",
                Severity.ERROR,
                f"\\[ \\] 计数不同: src ({slb},{srb}) vs zh ({zlb},{zrb})",
            )
        )


def _check_length(src: str, zh: str, issues: list[Issue]) -> None:
    """长度比 sanity + 疑似未翻译（拉丁字符占比过高）。阈值见 E21 修订。"""
    ls, lz = len(src.strip()), len(zh.strip())
    if ls >= _MIN_SRC_LEN_FOR_RATIO:
        r = lz / ls
        if not LENGTH_RATIO_LO <= r <= LENGTH_RATIO_HI:
            issues.append(
                Issue(
                    "length",
                    Severity.WARN,
                    f"长度比 {r:.2f} 超出 [{LENGTH_RATIO_LO},{LENGTH_RATIO_HI}] "
                    f"(src={ls} zh={lz})",
                )
            )
    text = PH_ANY_LIKE_RX.sub(" ", zh)
    text = _CS_OR_SYM_RX.sub(" ", text)
    cjk = len(CJK_RX.findall(text))
    lat = sum(1 for c in text if c.isascii() and c.isalpha())
    if lat >= _MIN_LATIN_FOR_CJK_CHECK:
        share = cjk / (cjk + lat)
        if share < CJK_SHARE_MIN:
            issues.append(
                Issue(
                    "length",
                    Severity.WARN,
                    f"CJK 占比 {share:.0%} <{CJK_SHARE_MIN:.0%} "
                    f"(lat={lat} cjk={cjk}) — 疑似未翻译",
                )
            )


def _cs_names(s: str) -> tuple[Counter[str], Counter[str]]:
    """``(cs 名 Counter, 脆弱间距 token Counter)``——脆弱集含 bs 五枚 + ``~``。"""
    cs: Counter[str] = Counter()
    frag: Counter[str] = Counter()
    for kind, text, _ in _lex(s):
        if kind == "cs":
            cs[text] += 1
        elif (kind == "bs" and text in FRAGILE_BS) or (
            kind == "ch" and text in FRAGILE_CHARS
        ):
            frag[text] += 1
    return cs, frag


def _macro_new_issues(sn: Counter[str], zn: Counter[str], issues: list[Issue]) -> None:
    """zh−src 新增方向：结构族/融合 cs=error，其余=warn。"""
    new = zn - sn
    for nme in sorted(new):
        if _NONASCII_RX.search(nme):
            issues.append(
                Issue(
                    "macro",
                    Severity.ERROR,
                    f"译文出现含非 ASCII 的控制序列 \\{nme} ×{new[nme]} "
                    f"(疑似 \\ + 中文熔合，未定义 cs 编译炸弹)",
                )
            )
        elif nme in STRUCT_CMDS:
            issues.append(
                Issue(
                    "macro",
                    Severity.ERROR,
                    f"译文新增结构命令 \\{nme} ×{new[nme]} (幻觉结构)",
                )
            )
        else:
            issues.append(
                Issue("macro", Severity.WARN, f"译文新增控制序列 \\{nme} ×{new[nme]}")
            )


def _check_macro(src: str, zh: str, issues: list[Issue]) -> None:
    """控制序列双向 diff（E21/E22 修订口径）。

    zh−src 新增：结构族=error；含非 ASCII 字符的融合 cs=error；其余=warn。
    src−zh 丢失：脆弱间距命令计数差（cs_dropped）=error；其余丢失=warn。
    """
    sn, sf = _cs_names(src)
    zn, zf = _cs_names(zh)
    _macro_new_issues(sn, zn, issues)

    # —— src 丢失方向（E22：脆弱命令计数差 cs_dropped 升硬判据）——
    for tok in sorted(FRAGILE_BS | {"~"}):
        dropped = sf.get(tok, 0) - zf.get(tok, 0)
        if dropped > 0:
            issues.append(
                Issue(
                    "macro",
                    Severity.ERROR,
                    f"脆弱间距命令 {tok!r} 丢失: src {sf[tok]} 处 → zh {zf.get(tok, 0)} 处 "
                    f"(cs_dropped，\\ +中文熔合/间距丢失高发)",
                )
            )
    issues.extend(
        Issue(
            "macro",
            Severity.WARN,
            f"控制序列 \\{nme} 未保留: src ×{sn[nme]} → zh ×{zn.get(nme, 0)}",
        )
        for nme in sorted(sn - zn)
        if nme not in STRUCT_CMDS  # 结构命令丢失已由 env/brace 覆盖，不重复报
    )


def _check_item_glue(src: str, zh: str, issues: list[Issue]) -> None:
    r"""``\item``+ASCII 字母粘合签名（``\itemFSU`` 类，管线引入，编译炸弹）。

    走 ``_lex`` cs 流而非裸正则：``\\itemX``（``\\`` 断行 + 文本）不误判，
    注释区天然豁免。``\itemsep``/``\itemindent`` 等合法 cs 与 src 自带粘连
    靠 src↔zh 净差豁免；只报 zh 多出计数。
    """
    s = Counter(
        t for k, t, _ in _lex(src) if k == "cs" and t != "item" and t.startswith("item")
    )
    z = Counter(
        t for k, t, _ in _lex(zh) if k == "cs" and t != "item" and t.startswith("item")
    )
    extra = z - s
    if extra:
        toks = ", ".join(f"\\{t} ×{n}" for t, n in sorted(extra.items()))
        issues.append(
            Issue(
                "item_glue",
                Severity.WARN,
                f"\\item 与后随文本粘合成非法控制序列 ×{sum(extra.values())}: "
                f"{toks}（未定义 cs 编译炸弹，应拆回 \\item + 空格）",
                found=toks,
            )
        )


def _check_ph_in_cs(src: str, zh: str, issues: list[Issue]) -> None:
    r"""``\cs名[..[[PH]]..]字母`` 双侧夹持签名（``\fo[[CMD_1]]o`` 类）。

    译文把占位符嵌进 cs 名中段 → splice 逐字节替换后断 cs
    （``\te[[PH]]xtbf``→``\te\cite{…}xtbf``、``\noind[[PH]]ent``→
    ``\noind\Cref{…}ent``——modec 两波实测签名）：未定义 cs 编译炸弹
    且断名 payload 不可复原，不进 fixloop、走重译/回退原文。

    双侧夹持是硬判据：``\cs[[PH]]`` 尾邻是合法高频形（corpus 271 处
    ——``\protect[[REF_n]]``/``\em[[CMD_n]]``/``\S[[REF_n]]``），只查
    前侧会灾难级误报；``\\`` 控制符号 + ``[[PH]]``（display-math 形）
    由 ``[a-zA-Z@]+`` 必需字母排除。注释区屏蔽豁免；src 自带同形
    （占位符本就贴命令名落位，实测 2/5413）按整串净差豁免。盲区
    记档：``\cs[[KEY_n]]`` 类尾邻载荷字母头也会融合，但 validator
    拿不到 ph_map 判不了类型——后续按 ph 类型白名单再补。
    """
    extra = Counter(_PH_IN_CS_RX.findall(mask_comments(zh))) - Counter(
        _PH_IN_CS_RX.findall(mask_comments(src))
    )
    if extra:
        toks = ", ".join(f"{t} ×{n}" for t, n in sorted(extra.items()))
        issues.append(
            Issue(
                "ph_in_cs",
                Severity.ERROR,
                f"占位符嵌进控制序列名 ×{sum(extra.values())}: "
                f"{toks}（splice 后断 cs 成未定义命令，载荷不可复原——"
                f"应整体重译或回退原文）",
                found=toks,
            )
        )


def _math_spans(lexed: list[tuple[str, str, int]]) -> list[tuple[int, int]]:
    r"""配对数学定界符的 ``(start, end)`` span 表——域内 cs 是合法数学用法。

    ``$..$``/``$$..$$``/``\\(..\\)``/``\\[..\\]`` 顺序配对；相邻两 ``$``
    合并为 ``$$``（``$$x$$`` 不切成两对空区间）。未闭合定界符其后全部
    按文本域处理（配对不齐已由 ``math`` 规则兜底报错，这里宁严勿漏）。
    """
    evs: list[tuple[str, int]] = []
    for kind, text, pos in lexed:
        if kind == "ch" and text == "$":
            if evs and evs[-1][0] == "$" and evs[-1][1] + 1 == pos:
                evs[-1] = ("$$", pos - 1)
            else:
                evs.append(("$", pos))
        elif kind == "bs" and text in ("\\(", "\\)", "\\[", "\\]"):
            evs.append((text, pos))
    closer = {"$": "$", "$$": "$$", "\\(": "\\)", "\\[": "\\]"}
    spans: list[tuple[int, int]] = []
    open_: tuple[str, int] | None = None
    for d, p in evs:
        if open_ is None:
            if d in closer:
                open_ = (d, p)
        elif d == closer[open_[0]]:
            spans.append((open_[1], p + len(d)))
            open_ = None
    return spans


def _out_of_math(
    lexed: list[tuple[str, str, int]], spans: list[tuple[int, int]]
) -> tuple[Counter[str], dict[str, int]]:
    """``(文本域 cs 名 Counter, 首个文本域出现 pos)``——span 内 cs 不计。"""
    cnt: Counter[str] = Counter()
    first: dict[str, int] = {}
    for kind, text, pos in lexed:
        if kind == "cs" and not any(a <= pos < b for a, b in spans):
            cnt[text] += 1
            first.setdefault(text, pos)
    return cnt, first


def _check_bare_cs(src: str, zh: str, issues: list[Issue]) -> None:
    r"""译文裸 cs 注入（realpostfix2 0905.4907 实证签名），两类编译炸弹。

    ``macro`` 规则对新增 cs 只报泛 warn；本规则抓其中**编译即炸**的
    两个子类升 error（余下新名仍归 macro warn，不重复报）：

    - **数学域外数学 cs**：``\alpha``/``\to`` 类数学模式命令出现在 zh
      文本域（zh 自带 ``$..$``/``\\(\\)`` 内豁免——那是合法修正方向），
      净超出 src 文本域同计数 → ``Missing $`` 炸弹（``alpha emitters``
      被译成 ``\alpha 发射体``，caption 两处 → Missing $×4）。
    - **粘合 cs**：zh 新增名 = src 某 cs（≥3 字母）前缀 + **含大写**后缀
      ——``\itemOC``/``\linebreakGF``/``\csnamebibitemNoStop``（cs 吞掉
      间隔空格、后随词首字母粘上）→ 未定义 cs 炸弹。后缀须含大写：
      ``\citep``/``\refname``/``\textbf`` 类全小写延申是真实 cs 不炸。
    """
    snc, znc = mask_comments(src), mask_comments(zh)
    slex, zlex = _lex(snc), _lex(znc)
    sn = Counter(t for k, t, _ in slex if k == "cs")
    zn = Counter(t for k, t, _ in zlex if k == "cs")
    new = zn - sn
    if not new:
        return
    zout, zfirst = _out_of_math(zlex, _math_spans(zlex))
    sout, _ = _out_of_math(slex, _math_spans(slex))

    bombs = {nme: n for nme, n in (zout - sout).items() if nme in _MATH_CS}
    if bombs:
        toks = ", ".join(f"\\{nme} ×{n}" for nme, n in sorted(bombs.items()))
        issues.append(
            Issue(
                "bare_cs",
                Severity.ERROR,
                f"译文注入数学控制序列 ×{sum(bombs.values())}: {toks}"
                f"（文本域 Missing $ 编译炸弹——应为普通文字或 $…$ 包裹）",
                min(zfirst[nme] for nme in bombs),
                found=toks,
            )
        )

    fused = {}
    for nme, n in sorted(new.items()):
        if nme in _MATH_CS:
            continue
        pre = max(
            (s for s in sn if len(s) >= 3 and nme.startswith(s)),
            key=len,
            default=None,
        )
        if pre is None:
            continue
        suf = nme[len(pre) :]
        if any(c.isupper() for c in suf):
            fused[nme] = (pre, suf, n)
    if fused:
        toks = ", ".join(
            f"\\{nme}（\\{pre}+{suf} 粘合）×{n}"
            for nme, (pre, suf, n) in fused.items()
        )
        issues.append(
            Issue(
                "bare_cs",
                Severity.ERROR,
                f"译文出现粘合控制序列 ×{sum(n for _, _, n in fused.values())}: "
                f"{toks}（未定义 cs 编译炸弹——应拆回 \\前缀 + 空格）",
                found=toks,
            )
        )


def _check_protocol_echo(src: str, zh: str, issues: list[Issue]) -> None:
    r"""协议回显守卫：zh 净多出 corrector/L0 协议字面 → error。

    repro-2410b §4b：Mode-B mock 把三段式 prompt 当正文翻，交付块带
    节标 + ``占位符缺失:`` 反馈行 + body 重复——占位符 multiset 可吻合
    而载荷脏（反馈行里 ``[[COMMENT_14]]`` splice 出 ``%`` 吞掉 chunk 外
    ``}`` → early_eof）。真模型 parrot prompt furniture 是同款逃逸通道，
    与 ``pipeline._intercept_leftover_ph`` 同层（error → 重译/回退原文）。
    词表 ``_ECHO_SIGS`` 与 bench ``DIRTY_SIGS`` 同款同序——子串直配 +
    src↔zh 净差（src 自带同形串属忠实翻译不追责；校验行话 + ASCII
    冒号/节标形态合法译文不产出）。
    """
    for sig in _ECHO_SIGS:
        n = zh.count(sig) - src.count(sig)
        if n > 0:
            issues.append(
                Issue(
                    "protocol_echo",
                    Severity.ERROR,
                    f"协议字面 {sig!r} 进入交付译文 ×{n}"
                    f"（corrector 反馈/重试协议被当正文回显，载荷脏）",
                    zh.find(sig),
                    found=sig,
                )
            )


# ---------------------------------------------------------------- 主入口


def validate_pair(src: str, zh: str) -> L0Report:
    """对 ``(src_chunk, zh_chunk)`` 跑全部十组检查，返回结构化 verdict。

    ``report.ok`` 为 True 即可送 L1/拼回；False 时 ``report.feedback()``
    的文本可直接进 corrector 的 ``previous_validation_error`` 字段。
    """
    rep = L0Report(src_len=len(src), zh_len=len(zh))
    _check_placeholder(src, zh, rep.issues)
    _check_brace(src, zh, rep.issues)
    _check_env(src, zh, rep.issues)
    _check_key(src, zh, rep.issues)
    _check_math(src, zh, rep.issues)
    _check_length(src, zh, rep.issues)
    _check_macro(src, zh, rep.issues)
    _check_item_glue(src, zh, rep.issues)
    _check_ph_in_cs(src, zh, rep.issues)
    _check_bare_cs(src, zh, rep.issues)
    _check_protocol_echo(src, zh, rep.issues)
    return rep
