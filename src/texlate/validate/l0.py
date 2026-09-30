r"""L0 规则校验层 —— stdlib always-on，src↔zh 相对判定（规格 docs/spec/validate.md）。

定位：校验链第一层，LLM 每返回一个 chunk 立即校验（实测 0.57ms/对）。
独立于任何 LaTeX 解析器（pylatexenc 静默截断的教训——校验器必须异构），
也是 node 不可用时的兜底路径。

设计原则 = "译文不得比原文更坏"：每条检查都是 src↔zh 比较而非 zh 绝对判定，
src 自带的不平衡/不一致不追责（继承容忍），只报 zh 相对 src 的新增损伤。

十四条规则（docs/spec/validate.md 表 + E21/E22 修订口径 + 注释区/粘合/回显/ph_in_cs/裸 cs/注释尾段/残英补丁）：

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
  length       剥占位符/cs 后 token 代理比带 [0.3,3.0] 外 → error（退化
               坍缩/膨胀拒收，E24——char 级旧口径因 CJK 密度 241 假离群
               弃用，token 代理带经 qualbase-2026-09-18 全池标定零误伤）；
               人名/专名列 src 上界放宽 4.0（音译+原文括号注释合法膨胀）；
               剥占位符后 CJK 占比「疑似未翻译」仍 warn。
  same_source  剥占位符/cs + 空白折叠 + 小写后 src==zh 整段回显 → error
               （``[[BIB_`` bib 直通/剥后 <10 token 短残段豁免——输出=输入
               是正确态；人名/专名列 verbatim 回显豁免——名单留拉丁原名
               即正确态；仅规范化等值比较，近似匹配会误伤邮箱/数学残段）。
  residual_en  zh prose 按 CJK 切非 CJK run，verbatim ⊆src（est≥10）或
               混血长句（≥8 词且 ≥40 拉丁字母）→ error（seq-49/51 实证：
               行级修复原文回退/模型半译在中文段里留整句英文，same_source
               只拦整段回显、length 的 CJK 占比 warn 不闸）；``[[BIB_`` 与
               零 CJK zh 豁免归 same_source/length 管辖，人名/专名列
               （≥70% 首字母大写）豁免。判定口径 = ``textutil.residual_en_net``，
               与 pipeline ``_intercept_residual_en`` 逐字节一致。
  macro        zh 新增控制序列 diff=error（E24 全档拒收：texglot 同口径
               ``\\[a-zA-Z@]`` 控制词可携 prompt-injection 直进 .tex；
               ``\\.`` 转义族是 bs 类本不入 cs 计数天然豁免；含非 ASCII
               融合 cs ``\\和`` 与结构族同档）；E21/E22：src→zh 方向
               脆弱间距命令（``\\ `` ``\\,`` ``\\;`` ``\\:`` ``\\!`` ``~``）
               计数差升硬判据 cs_dropped，其余丢失 cs 报 warn。
  item_glue    ``\\item`` 紧跟 ASCII 字母粘成 ``\\itemFSU`` 类非法 cs（管线引入
               签名，8 篇实证 Undefined cs 编译炸弹）——zh 净多出计数 → warn；
               ``\\itemsep`` 等合法 cs 与 src 自带粘连靠 src↔zh 净差豁免。
  ph_in_cs     ``\\cs名[[PH]]字母`` 双侧夹持签名 → error（splice 逐字节替换
               后断 cs 成未定义命令、载荷不可复原——不进 fixloop，走重译/
               回退；``\\cs[[PH]]`` 尾邻是合法高频形不判，注释区豁免，
               src 同形按净差豁免）。
  bare_cs     译文裸 cs 注入两子类 → error（realpostfix2 0905.4907：
               ``\alpha 发射体`` 数学 cs 落文本域 → Missing $ 炸弹；
               ``\itemOC``/``\linebreakGF`` 前缀+含大写后缀粘合 → 未定义
               cs 炸弹）。泛新增 cs E24 起归 macro error，本规则只管
               编译即炸的位置签名——命中名在 macro 泛 error 报表同现
               一条（有意分层双报：泛条目不带文本域/粘合前缀定位）。
  protocol_echo 交付 zh 净多出协议字面 → error（repro-2410b §4b：corrector
               三段式节标/L0 反馈消息/``slot_validation_failures``/
               ``[compile_error]`` 被当正文回显——multiset 可吻合而载荷脏，
               回显行里 ``[[COMMENT_n]]`` splice 出 ``%`` 吞掉同行结构 ``}``
               实测 early_eof）。词表与 bench ``DIRTY_SIGS`` 同款同序；
               ``[这是译文]``/``[word]`` 合法产出不在表内不误伤。
  comment_eof  zh 尾段未终结注释（``[[COMMENT_n]]``/字面 ``%`` 到 EOF 无
               ``\n``）→ error（stagerun-rt1 ``\@xdblarg`` runaway 族 ×4
               cell 同形：corrector 臂丢注释终结换行，splice 接缝把 ``}``
               吞进 ``%`` 行）；src 尾段同形豁免。

实测基线（1636 例）：10 类破坏 100% 检出、
313 干净对 0 error-FP。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property
from typing import TYPE_CHECKING, Final

from texlate.textutil import (
    CJK_RX,
    MATH_CS,
    PH_ANY_LIKE_RX,
    PH_FUZZY_RX,
    bare_cs_net,
    dangerous_cs_net,
    lev_capped,
    mask_comments,
    name_list_prose,
    ph_in_cs_net,
    residual_en_net,
)
from texlate.textutil import est_tokens as _est_tokens
from texlate.textutil import prose_text as _prose

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "Issue",
    "L0Report",
    "Severity",
    "validate_pair",
]

# ---------------------------------------------------------------- 常量

#: 从模糊候选里剥出核心 token（去括号/空白），供 lev 配对。
_PH_CORE_RX: Final = re.compile(r"[A-Za-z0-9_]+")

#: key 承载命令：*cite* 族（cite/Cite/paracite/footcite/nocite/mcite……
#: 前后缀皆收、首字母大小写皆收）/ *cites 多 key 参族（整段 {..}{..}
#: 连写抓一组，消费端逐对剥）/ *ref 族 / *refrange 双 key 族
#: （crefrange/cpagerefrange）/ *label 族（label/zlabel……）/ bibitem /
#: addbibresource / addglobalbib / bibliography 族。只抓 {..} key
#: 参数，可选 [..] 先吃掉；refrange 臂多抓第二个 {..}。
KEY_CMD_RX: Final = re.compile(
    r"\\[a-zA-Z@]*[Cc]ites\*?"
    r"(?:\s*\[[^\]\n]*\])*"
    r"\s*((?:\{[^{}]*\})+)"  # *cites 相邻 {..} 连写整段抓——带空格多为正文 {..}
    r"|\\(?:[a-zA-Z@]*[Cc]ite[a-zA-Z]*|[a-zA-Z@]*ref|[a-zA-Z@]*label|bibitem"
    r"|addbibresource|addglobalbib|addsectionbib|[a-zA-Z@]*bibliography(?:style)?)\*?"
    r"(?:\s*\[[^\]\n]*\])*"
    r"\s*\{([^{}]*)\}"
    r"|\\[a-zA-Z@]*refrange\*?"
    r"(?:\s*\[[^\]\n]*\])*"
    r"\s*\{([^{}]*)\}(?:\{([^{}]*)\})?"  # 第二参相邻才算——带空格多为正文 {..}
)

#: ``*cites`` 臂组内逐对 ``{..}`` 剥 key 用（其余臂组内容本就不含花括号，
#: findall 空集时回落整组原文）。
_BRACE_SEQ_RX: Final = re.compile(r"\{([^{}]*)\}")

ENV_RX: Final = re.compile(r"\\(begin|end)\s*\{([^{}]*)\}")


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

#: 协议回显签名（repro-2410b §4b 交付守卫）：L0 反馈消息实际 emit 串 +
#: 重试协议字面（三段式节标/``previous_validation_error`` 尾拼/
#: ``slot_validation_failures`` 字段/``[compile_error]`` L2 回灌标）。
#: 本表为唯一词表单源——bench ``DIRTY_SIGS``（``e2e_mock_bench.py``）
#: 经 import 同源，勿再复抄副本（复抄面曾静默漂移：词表项的全角冒号
#: 改写脱离了 emit 串）。交付 zh 出现即 prompt/反馈被当正文回显；
#: ``[这是译文]``/``[word]`` 行内合法产出不在表内不误伤。
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

#: 长度比带（E24 token 代理口径）：剥占位符/cs 后 est_token 比出带 →
#: error。char 级旧带 [0.25,2.5] 因 CJK 密度 241 假离群弃用；本带经
#: qualbase-2026-09-18 全池标定（p0=0.76 / p50=1.18 / p99.5=1.80），
#: 合法件双侧留 ~4x 余量，带外即退化坍缩/膨胀。
TOKEN_RATIO_LO: Final = 0.30
TOKEN_RATIO_HI: Final = 3.00
#: 人名/专名列 src 的长度比上界——音译+原文括号注释风格（每名 →
#: 中文音译+``(拉丁原名)``）合法膨胀 ~2.6-3.4x，标准 3.0 上界误杀
#: （web t_25e3f4d1 seq-67..77 实测 3.04-3.32）。下界不放宽——
#: 名单译空/截断仍是退化。
TOKEN_RATIO_HI_NAMELIST: Final = 4.00
#: 剥后 src est_token 下界——之下按纯占位符/短残段豁免（输出=输入是正确态，
#: babeldoc ``input_token_count>10`` 同口径）。
_MIN_PROSE_TOKENS: Final = 10
CJK_SHARE_MIN: Final = 0.30
_MIN_LATIN_FOR_CJK_CHECK: Final = 8
_LEV_CAP: Final = 2
_ENV_CHECK_TAIL_LIMIT: Final = 50  # end 名偏多 warn 的报告条数上限
#: 非语言成分 span（same_source 恒等豁免用）：已包裹 ``\url/\href/\doi/\path``、
#: 裸 URL、裸 DOI（``doi:`` 前缀与 ``10.NNNN/`` 两形）、邮箱。整段剥净这些后
#: 无拉丁字母残量 → 输出=输入是正确态而非回显——est 阈值挡不住裸链的 token
#: 计数（t_887e62c5f741ccbe 实证：裸 huggingface 链 est=12 越线被死锁）。
_NONLING_RX: Final = re.compile(
    r"\\(?:url|href|doi|path)\{[^{}]*\}(?:\{[^{}]*\})?"
    r"|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
    r"|(?:https?://|www\.)[^\s{}\[\]()<>'\"]+"
    r"|\bdoi:\s*\S+"
    r"|\b10\.\d{4,9}/[^\s{}\[\]()<>'\"]+"
)


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
        """给带错重翻 corrector 的紧凑错误描述（docs/spec/translate.md 反馈字段化）。"""
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


class _Ctx:
    """``(src, zh)`` 校验对的共享预处理视图缓存（``_CHECKERS`` 入参）。

    各 checker 曾按 ``(src, zh, issues)`` 签名各自重推同一批词法/遮盖/
    散文视图（每对 ``_lex`` ×13、``mask_comments`` ×9、``_prose`` ×4）；
    全部改为随本对象惰性派生——每视图每对只算一次，未消费的侧不付成本。
    """

    def __init__(self, src: str, zh: str, issues: list[Issue]) -> None:
        """记下双侧原文与共享 issues 槽；视图全部惰性。"""
        self.src = src
        self.zh = zh
        self.issues = issues

    @cached_property
    def lex_src(self) -> list[tuple[str, str, int]]:
        r"""``_lex(src)``——注释区整体是 ``cmt`` token，区内 ``\foo`` 本就不入 cs 计数。"""
        return _lex(self.src)

    @cached_property
    def lex_zh(self) -> list[tuple[str, str, int]]:
        """``_lex(zh)``。"""
        return _lex(self.zh)

    @cached_property
    def masked_src(self) -> str:
        """``mask_comments(src)`` 等长遮盖视图。"""
        return mask_comments(self.src)

    @cached_property
    def masked_zh(self) -> str:
        """``mask_comments(zh)`` 等长遮盖视图。"""
        return mask_comments(self.zh)

    @cached_property
    def prose_src(self) -> str:
        """``prose_text(src)`` 剥占位符/cs 后的散文本体（length/same_source 共用）。"""
        return _prose(self.src)

    @cached_property
    def prose_zh(self) -> str:
        """``prose_text(zh)``。"""
        return _prose(self.zh)

    @cached_property
    def est_src(self) -> float:
        """``est_tokens(prose_src)``——大小写不变量（CJK 数+非空白数），``ss.lower()`` 视图同值。"""
        return _est_tokens(self.prose_src)

    @cached_property
    def est_zh(self) -> float:
        """``est_tokens(prose_zh)``。"""
        return _est_tokens(self.prose_zh)


# ---------------------------------------------------------------- 规则组


def _ph_typo_adjacency(
    missing: list[str], cands: list[str]
) -> tuple[list[list[int]], list[dict[int, int]]]:
    """缺失↔候选 lev≤2 邻接表（(lev, 下标) 升序）+ 距离表。

    大小写折叠后比较：issuer 恒产大写形，``[[math_1]]`` 类小写变体视为
    同一 token 的拼错（lev 只差在大小写上），给出修复建议。
    """
    adj: list[list[int]] = []
    cost: list[dict[int, int]] = []
    for ph in missing:
        ph_core = ph.strip("[]")
        row: list[tuple[int, int]] = []
        cmap: dict[int, int] = {}
        for ci, cand in enumerate(cands):
            core = _PH_CORE_RX.search(cand)
            cand_core = core.group(0) if core else cand
            d = lev_capped(ph_core.upper(), cand_core.upper(), _LEV_CAP)
            if d <= _LEV_CAP:
                row.append((d, ci))
                cmap[ci] = d
        adj.append([ci for _, ci in sorted(row)])
        cost.append(cmap)
    return adj, cost


def _ph_max_pairs(adj: list[list[int]], n_cands: int) -> list[int]:
    """Kuhn 增广路最大二分匹配 → ``match_of[cand]=missing``（-1=未配）。

    逐缺失贪心先抓近候选会让后位缺失饿死（``AAAA`` 抢走 ``AAAB`` 致
    ``AABB`` 误报缺失 + ``CCAA`` 误报多余——同 lev 界内本可配两对）。
    DFS 用迭代栈——缺失规模随输入走，不赌解释器递归深限。
    """
    match_of = [-1] * n_cands
    for start in range(len(adj)):
        seen: set[int] = set()  # 本轮已试探的 cand
        it = [0] * len(adj)  # 各 missing 邻接扫描游标
        stack = [start]  # DFS 路径上的 missing 下标
        pc = [-1]  # 与 stack 平行：stack[k] 经由 pc[k] 号 cand 被引入
        free = -1
        while stack and free < 0:
            cur = stack[-1]
            ci = -1
            while it[cur] < len(adj[cur]):
                cand = adj[cur][it[cur]]
                it[cur] += 1
                if cand not in seen:
                    seen.add(cand)
                    ci = cand
                    break
            if ci < 0:
                stack.pop()
                pc.pop()
            elif match_of[ci] < 0:
                free = ci
            else:
                stack.append(match_of[ci])
                pc.append(ci)
        if free >= 0:  # 沿 DFS 路径回翻转整链匹配
            ci = free
            for j in range(len(stack) - 1, 0, -1):
                match_of[ci] = stack[j]
                ci = pc[j]
            match_of[ci] = stack[0]
    return match_of


def _pair_placeholder_typos(
    missing: list[str], cands: list[str], issues: list[Issue]
) -> set[int]:
    """缺失占位符 ↔ 模糊候选 lev≤2 最大匹配配对；返回已消耗的候选下标。"""
    adj, cost = _ph_typo_adjacency(missing, cands)
    match_of = _ph_max_pairs(adj, len(cands))
    paired = {mi: ci for ci, mi in enumerate(match_of) if mi >= 0}
    used: set[int] = set()
    for mi, ph in enumerate(missing):
        ci = paired.get(mi)
        if ci is None:
            issues.append(
                Issue("placeholder", Severity.ERROR, f"占位符缺失: {ph}", expected=ph)
            )
            continue
        used.add(ci)
        issues.append(
            Issue(
                "placeholder",
                Severity.ERROR,
                f"占位符疑似拼错: '{cands[ci]}' 应为 '{ph}' "
                f"(lev={cost[mi][ci]}, 可自动修复)",
                expected=ph,
                found=cands[ci],
            )
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


def _ph_in_comments(toks: list[tuple[str, str, int]]) -> Counter[str]:
    r"""注释区（``%``→行尾，``\%`` 豁免）内正规形占位符计数。

    mask 口径下注释区整体不可见，必须单独点算——zh 注释里臆造的占位符
    splice 后字面残留（sabotage 实测逃逸），src 自带注释占位符作净差豁免。
    入参为 ``_lex`` token 流（``_Ctx.lex_src``/``lex_zh`` 共享视图）。
    """
    c: Counter[str] = Counter()
    for kind, text, _ in toks:
        if kind == "cmt":
            c.update(PH_ANY_LIKE_RX.findall(text))
    return c


def _check_placeholder(ctx: _Ctx) -> None:
    """占位符 multiset diff + lev≤2 修复配对 + 序守恒软信号 + 行锚定（BIBITEM/COMMENT）。"""
    src, zh, issues = ctx.src, ctx.zh, ctx.issues
    snc, znc = ctx.masked_src, ctx.masked_zh
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
    extra_cmt = _ph_in_comments(ctx.lex_zh) - _ph_in_comments(ctx.lex_src)
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


def _brace_profile_toks(
    toks: list[tuple[str, str, int]],
) -> tuple[int, int, int, int, int]:
    """``(open数, close数, 净深度, 最小前缀深度, 首个负深度pos)``——``_lex`` token 流入参。"""
    depth = opens = closes = minpref = 0
    first_neg = -1
    for kind, ch, pos in toks:
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


def _brace_profile(s: str) -> tuple[int, int, int, int, int]:
    """``_brace_profile_toks(_lex(s))``——fuzz oracle 用的字符串入口。"""
    return _brace_profile_toks(_lex(s))


def _check_brace(ctx: _Ctx) -> None:
    """``{}`` 平衡：zh 最小前缀深度 < src 最小前缀深度，或净余额不同 → error。"""
    issues = ctx.issues
    so, sc, sd, smin, _ = _brace_profile_toks(ctx.lex_src)
    zo, zc, zd, zmin, zneg = _brace_profile_toks(ctx.lex_zh)
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


def _env_tokens(snc: str) -> list[tuple[str, str, int]]:
    """``(begin|end, 环境名, pos)`` 事件流——入参须为 ``mask_comments`` 遮盖视图。"""
    return [(m.group(1), m.group(2).strip(), m.start()) for m in ENV_RX.finditer(snc)]


def _env_signature_masked(
    snc: str,
) -> tuple[int, int, Counter[str], Counter[str], Counter[str]]:
    """``(多余end数, 不匹配数, 未闭合begin名, begin名, end名)`` 栈签名——遮盖视图入参。"""
    stack: list[tuple[str, int]] = []
    n_orphan_end = n_mismatch = 0
    toks = _env_tokens(snc)
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


def _env_signature(
    s: str,
) -> tuple[int, int, Counter[str], Counter[str], Counter[str]]:
    """``_env_signature_masked(mask_comments(s))``——fuzz oracle 用的原文入口。"""
    return _env_signature_masked(mask_comments(s))


def _check_env(ctx: _Ctx) -> None:
    r"""``\begin{X}``/``\end{X}`` 栈配对 + 环境名 multiset 签名差分。

    src 自身的内部不一致不追责（继承容忍），只报 zh 新增的栈错误类别。
    """
    issues = ctx.issues
    s_orph, s_mis, s_left, s_beg, s_end = _env_signature_masked(ctx.masked_src)
    z_orph, z_mis, z_left, z_beg, z_end = _env_signature_masked(ctx.masked_zh)
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
    # end 名 diff 多数已被栈签名覆盖，仅补充 begin/end 同改名的对称情形；
    # 先过滤再截断——被 begin 净增覆盖的条目不消耗报告条数上限。
    issues.extend(
        Issue("env", Severity.WARN, f"\\end{{{name}}} 比原文多 ×{cnt}")
        for name, cnt in [
            (nme, c)
            for nme, c in (z_end - s_end).items()
            if z_beg.get(nme, 0) <= s_beg.get(nme, 0)
        ][:_ENV_CHECK_TAIL_LIMIT]
    )


def _key_multiset_masked(snc: str) -> Counter[str]:
    r"""cite/ref/label/bib key 多重集（逗号拆分，[..] 可选参豁免）——遮盖视图入参。

    refrange 臂的第二 {..} 也是 key 参数（``\crefrange{a}{b}``），
    group 1-3 逐组点算。
    """
    c: Counter[str] = Counter()
    for m in KEY_CMD_RX.finditer(snc):
        for gi in (1, 2, 3, 4):
            grp = m.group(gi)
            if grp is None:
                continue
            for piece in _BRACE_SEQ_RX.findall(grp) or [grp]:
                for raw in piece.split(","):
                    key = raw.strip()
                    if key:
                        c[key] += 1
    return c


def _key_multiset(s: str) -> Counter[str]:
    """``_key_multiset_masked(mask_comments(s))``——fuzz oracle 用的原文入口。"""
    return _key_multiset_masked(mask_comments(s))


def _check_key(ctx: _Ctx) -> None:
    """cite/ref/label/bib key multiset：src−zh=error，zh−src=warn（幻觉引用）。"""
    issues = ctx.issues
    sk = _key_multiset_masked(ctx.masked_src)
    zk = _key_multiset_masked(ctx.masked_zh)
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


def _math_profile_toks(
    toks: list[tuple[str, str, int]],
) -> tuple[int, int, int, int, int]:
    r"""``($数, \(数, \)数, \[数, \]数)``（未转义）——``_lex`` token 流入参。"""
    d = lp = rp = lb = rb = 0
    for kind, text, _ in toks:
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


def _math_profile(s: str) -> tuple[int, int, int, int, int]:
    """``_math_profile_toks(_lex(s))``——fuzz oracle 用的字符串入口。"""
    return _math_profile_toks(_lex(s))


def _check_math(ctx: _Ctx) -> None:
    r"""``$`` ``\(\)`` ``\[\]`` 计数一致性（未转义，注释豁免）。"""
    issues = ctx.issues
    sd, slp, srp, slb, srb = _math_profile_toks(ctx.lex_src)
    zd, zlp, zrp, zlb, zrb = _math_profile_toks(ctx.lex_zh)
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


def _cjk_latin_counts(s: str) -> tuple[int, int]:
    """``(CJK 字符数, ASCII 拉丁字母数)``——same_source/length 的 CJK 占比判定共用口径。"""
    return len(CJK_RX.findall(s)), sum(1 for c in s if c.isascii() and c.isalpha())


def _check_same_source(ctx: _Ctx) -> None:
    r"""整段原文回显拒收（E24）：规范化等值 src==zh 且拉丁主导 → error。

    豁免：``[[BIB_`` bib 直通块（留英合法）、剥后 src <10 est_token
    （纯占位符/短残段——输出=输入是正确态，babeldoc ``input_token_count>10``
    同口径）、整段纯非语言成分（URL/DOI/邮箱/``\url`` 包裹类——恒等即
    正确译文，裸链 est 可越 10 线）、人名/专名列 src（verbatim 回显即
    正确态——``name_list_prose`` 判据，与 ``residual_en`` run 级豁免
    同签名；web t_4000988e seq-234 est=629 贡献者名单实证）。仅规范化
    等值比较不取近似度——qualbase 实测 >0.85 相似档唯一命中是合法邮箱块；
    拉丁主导门槛豁免 ``zh==en`` 含 CJK 的合法恒等译文（share.py 收录
    口径同款情形）。
    """
    if "[[BIB_" in ctx.src:
        return
    # ``est_tokens`` 只数 CJK + 非空白字符，大小写不变——共享未小写视图的
    # est 与 ``ss`` 上重算同值（length 臂消费同一 ``ctx.est_src``）。
    # ``name_list_prose`` 须吃未小写 ``prose_src``——首字母大写占比是判据本体。
    ss, sz = ctx.prose_src.lower(), ctx.prose_zh.lower()
    if ctx.est_src < _MIN_PROSE_TOKENS or ss != sz or name_list_prose(ctx.prose_src):
        return
    if not re.search(r"[a-z]", _NONLING_RX.sub("", ss)):
        return
    cjk, lat = _cjk_latin_counts(ss)
    if lat >= _MIN_LATIN_FOR_CJK_CHECK and cjk / (cjk + lat) < CJK_SHARE_MIN:
        ctx.issues.append(
            Issue(
                "same_source",
                Severity.ERROR,
                f"整段原文回显（剥占位符规范化后 src==zh，est={ctx.est_src:.0f}）",
            )
        )


def _check_length(ctx: _Ctx) -> None:
    """长度比 sanity（E24 token 代理口径）+ 疑似未翻译（拉丁字符占比）。

    长度比：剥后 est_token 比出 [0.3,3.0] → error 拒收（src est<10 豁免）。
    CJK 占比：zh 剥后拉丁主导（share<0.30）→ warn 疑似未翻译。
    """
    issues = ctx.issues
    sz = ctx.prose_zh
    ts = ctx.est_src
    if ts >= _MIN_PROSE_TOKENS:
        tz = ctx.est_zh
        r = tz / ts
        hi = (
            TOKEN_RATIO_HI_NAMELIST
            if name_list_prose(ctx.prose_src)
            else TOKEN_RATIO_HI
        )
        if not TOKEN_RATIO_LO <= r <= hi:
            issues.append(
                Issue(
                    "length",
                    Severity.ERROR,
                    f"长度比(token 代理) {r:.2f} 超出 "
                    f"[{TOKEN_RATIO_LO},{hi}] "
                    f"(src~{ts:.0f} zh~{tz:.0f})",
                )
            )
    cjk, lat = _cjk_latin_counts(sz)
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


#: 残英 issue 消息的 run 展示截断。
_RESID_EN_SHOW: Final = 80


def _check_residual_en(ctx: _Ctx) -> None:
    """段内残英句拒收（seq-49/51 实证补网）：zh 夹未翻译英文 run → error。

    ``_check_same_source`` 只拦整段回显、``_check_length`` CJK 占比是
    warn 且要拉丁主导——行级修复把 audit 失败的行按原文装回、或模型
    半译应答，都会在中文段里留下整句英文而两网全盲（阶梯 ``recovered``
    落 DB ``ok`` 静默出货）。判定口径全在 ``textutil.residual_en_net``
    （CJK 切 run / verbatim 子串 + 混血长句 / 人名豁免 / BIB 直通豁免），
    与 pipeline ``_intercept_residual_en`` 逐字节一致。
    """
    ctx.issues.extend(
        Issue(
            "residual_en",
            Severity.ERROR,
            f"译文残留未翻译英文 run: {run[:_RESID_EN_SHOW]}"
            f"{'…' if len(run) > _RESID_EN_SHOW else ''}"
            "（行级修复原文回退/半译签名）",
            found=run,
        )
        for run in residual_en_net(ctx.src, ctx.zh)
    )


def _cs_names_toks(
    toks: list[tuple[str, str, int]],
) -> tuple[Counter[str], Counter[str]]:
    """``(cs 名 Counter, 脆弱间距 token Counter)``——``_lex`` token 流入参。脆弱集含 bs 五枚 + ``~``。"""
    cs: Counter[str] = Counter()
    frag: Counter[str] = Counter()
    for kind, text, _ in toks:
        if kind == "cs":
            cs[text] += 1
        elif kind == "bs":
            # ``\<newline>``/``\<tab>`` 与 ``\ `` 同义（TeX 控制空格）——
            # 归一后再比，否则等价形互换被误报 cs_dropped。
            tok = "\\ " if text[1:].isspace() else text
            if tok in FRAGILE_BS:
                frag[tok] += 1
        elif kind == "ch" and text in FRAGILE_CHARS:
            frag[text] += 1
    return cs, frag


def _cs_names(s: str) -> tuple[Counter[str], Counter[str]]:
    """``_cs_names_toks(_lex(s))``——fuzz oracle 用的字符串入口。"""
    return _cs_names_toks(_lex(s))


def _macro_new_issues(sn: Counter[str], zn: Counter[str], issues: list[Issue]) -> None:
    """zh−src 新增方向：E24 全档 error（新控制词即拒收，转义族 bs 天然豁免）。"""
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
                Issue(
                    "macro",
                    Severity.ERROR,
                    f"译文新增控制序列 \\{nme} ×{new[nme]} "
                    f"(新控制词可携 prompt-injection 直进 .tex，拒收)",
                )
            )


def _check_macro(ctx: _Ctx) -> None:
    """控制序列双向 diff（E21/E22/E24 修订口径）。

    zh−src 新增：全档 error（结构族/非 ASCII 融合 cs 同档处理）。
    src−zh 丢失：脆弱间距命令计数差（cs_dropped）=error；其余丢失=warn。
    """
    issues = ctx.issues
    sn, sf = _cs_names_toks(ctx.lex_src)
    zn, zf = _cs_names_toks(ctx.lex_zh)
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


def _check_item_glue(ctx: _Ctx) -> None:
    r"""``\item``+ASCII 字母粘合签名（``\itemFSU`` 类，管线引入，编译炸弹）。

    走 ``_lex`` cs 流而非裸正则：``\\itemX``（``\\`` 断行 + 文本）不误判，
    注释区天然豁免。后缀须含大写字母——与 ``textutil.bare_cs_net`` 同口径，
    全小写延申按真实 cs 豁免（``\itemsep``/``\itemize``/``\itemindent``）。
    src 自带粘连靠 src↔zh 净差豁免；只报 zh 多出计数。
    """

    def glued(toks: list[tuple[str, str, int]]) -> Counter[str]:
        return Counter(
            t
            for k, t, _ in toks
            if k == "cs"
            and t != "item"
            and t.startswith("item")
            and any(c.isupper() for c in t[4:])
        )

    s, z = glued(ctx.lex_src), glued(ctx.lex_zh)
    extra = z - s
    if extra:
        toks = ", ".join(f"\\{t} ×{n}" for t, n in sorted(extra.items()))
        ctx.issues.append(
            Issue(
                "item_glue",
                Severity.WARN,
                f"\\item 与后随文本粘合成非法控制序列 ×{sum(extra.values())}: "
                f"{toks}（未定义 cs 编译炸弹，应拆回 \\item + 空格）",
                found=toks,
            )
        )


def _check_ph_in_cs(ctx: _Ctx) -> None:
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
    extra = ph_in_cs_net(ctx.src, ctx.zh)
    if extra:
        toks = ", ".join(f"{t} ×{n}" for t, n in sorted(extra.items()))
        ctx.issues.append(
            Issue(
                "ph_in_cs",
                Severity.ERROR,
                f"占位符嵌进控制序列名 ×{sum(extra.values())}: "
                f"{toks}（splice 后断 cs 成未定义命令，载荷不可复原——"
                f"应整体重译或回退原文）",
                found=toks,
            )
        )


def _check_bare_cs(ctx: _Ctx) -> None:
    r"""译文裸 cs 注入（realpostfix2 0905.4907 实证签名），两类编译炸弹。

    E24 起 ``macro`` 规则对**全部**新增 cs 已报泛 error——本规则把其中
    **编译即炸**的两个子类再以位置签名单列 error（命中名在 macro
    报表同现一条泛条目：有意分层而非重复缺陷——泛条目不带文本域/
    粘合前缀定位，corrector 反馈与子类聚类需要本条的诊断载荷；
    ``macro`` 的全名覆盖由 fuzz 分类 oracle 钉死，剔除会破坏钉面）。
    判定口径单源在 ``textutil.bare_cs_net``（pipeline ``_intercept_bare_cs``
    副层共用），``nme in MATH_CS`` 拆子类：

    - **数学域外数学 cs**：``\alpha``/``\to`` 类数学模式命令出现在 zh
      文本域（zh 自带 ``$..$``/``\\(\\)`` 内豁免——那是合法修正方向），
      净超出 src 文本域同计数 → ``Missing $`` 炸弹（``alpha emitters``
      被译成 ``\alpha 发射体``，caption 两处 → Missing $×4）。
    - **粘合 cs**：zh 新增名 = src 某 cs（≥3 字母）前缀 + **含大写**后缀
      ——``\itemOC``/``\linebreakGF``/``\csnamebibitemNoStop``（cs 吞掉
      间隔空格、后随词首字母粘上）→ 未定义 cs 炸弹。后缀须含大写：
      ``\citep``/``\refname``/``\textbf`` 类全小写延申是真实 cs 不炸。
    """
    net = bare_cs_net(ctx.src, ctx.zh)
    if not net:
        return
    issues = ctx.issues
    bombs = {nme: n for nme, n in net.items() if nme in MATH_CS}
    if bombs:
        toks = ", ".join(f"\\{nme} ×{n}" for nme, n in sorted(bombs.items()))
        issues.append(
            Issue(
                "bare_cs",
                Severity.ERROR,
                f"译文注入数学控制序列 ×{sum(bombs.values())}: {toks}"
                f"（文本域 Missing $ 编译炸弹——应为普通文字或 $…$ 包裹）",
                found=toks,
            )
        )
    fused = {nme: n for nme, n in net.items() if nme not in MATH_CS}
    if fused:
        # cs 名集与 ``_lex(mask_comments(src))`` 同集——注释区 ``\foo`` 在
        # 原始 token 流里本就裹在 cmt token 内不可见，无需再遮盖重扫。
        sn = {t for k, t, _ in ctx.lex_src if k == "cs"}
        parts = []
        for nme, n in sorted(fused.items()):
            pre = max((s for s in sn if nme.startswith(s)), key=len, default=None)
            parts.append(
                f"\\{nme}（\\{pre}+{nme[len(pre) :]} 粘合）×{n}"
                if pre is not None
                else f"\\{nme} ×{n}"
            )
        issues.append(
            Issue(
                "bare_cs",
                Severity.ERROR,
                f"译文出现粘合控制序列 ×{sum(fused.values())}: "
                f"{', '.join(parts)}"
                f"（未定义 cs 编译炸弹——应拆回 \\前缀 + 空格）",
                found=", ".join(parts),
            )
        )


def _check_dangerous_cs(ctx: _Ctx) -> None:
    r"""译文新增危险控制序列（``DANGEROUS_CS`` 表名净差）——注入签名。

    ``macro`` 泛条目同现属有意分层（见 ``_check_bare_cs`` 约定），本网兜
    ``bare_cs`` 未管的良形非数学危险 cs：``\input{/etc/passwd}``/
    ``\write18``（词法 ``write``+``18``）/``\def``/``\catcode``/
    ``\csname`` 逃逸族——数学域不豁免（``$\input$`` 照样执行）。判定口径
    单源在 ``textutil.dangerous_cs_net``（pipeline
    ``_intercept_dangerous_cs`` 副层共用）。已知盲区挂账：
    ``\begin{filecontents}`` 类 env 名参数写文件不产 cs 事件，归 env
    名面另网。
    """
    net = dangerous_cs_net(ctx.src, ctx.zh)
    if net:
        toks = ", ".join(f"\\{nme} ×{n}" for nme, n in sorted(net.items()))
        ctx.issues.append(
            Issue(
                "dangerous_cs",
                Severity.ERROR,
                f"译文注入危险控制序列 ×{sum(net.values())}: {toks}"
                f"（IO/定义覆写/catcode/装包逃逸族——应整体重译或回退原文）",
                found=toks,
            )
        )


def _tail_unterminated_comment(toks: list[tuple[str, str, int]], sm: str) -> str | None:
    r"""文本尾段未终结注释的签名（字面 ``%`` → ``"%"``、``[[COMMENT_n]]`` → token）；无 → ``None``。

    ``%`` 展开吞到 EOL——尾段注释未终结时，splice 后随字面首行被接进注释行。
    字面 ``%`` 走 ``_lex`` 末 token 判（``\%`` 转义天然豁免）；``[[COMMENT_n]]``
    形在遮盖视图上判——token 后只剩 ``[ \t]*`` 到 EOF 即未终结（``\n`` 是注释
    终结符；后随非空白属 ``_check_ph_anchor`` 混入判据，此处不重复报）。
    入参 ``toks``/``sm`` 分别为 ``_lex`` 流与 ``mask_comments`` 视图
    （``_Ctx.lex_*``/``masked_*`` 共享件）。
    """
    if toks and toks[-1][0] == "cmt":
        return "%"
    # 末个 ``[[COMMENT_`` 前缀位即候选——若非良形 token，则任一更早 token 的
    # 尾段都含该残码（非空白）必非未终结，无需往前再扫。
    i = sm.rfind("[[COMMENT_")
    if i < 0:
        return None
    m = COMMENT_PH_RX.match(sm, i)
    if m is not None and not sm[m.end() :].strip(" \t"):
        return m.group(0)
    return None


def _check_comment_eof(ctx: _Ctx) -> None:
    r"""译文尾段未终结注释 → error（rt1 ``\@xdblarg`` runaway 族实证，4 cell 同形）。

    ``[[COMMENT_n]]``/字面 ``%`` 到 zh EOF 无 ``\n``：splice 接缝把 chunk 后
    字面首行吞进注释——``\caption{`` 的 ``}`` 落进 ``%`` 行 → ``\@xdblarg``
    runaway（1109.5754/0905.1718/1306.5799/2003.10917：corrector 臂丢尾
    ``\n``，``bare_token_audit`` 对未编码 src 的 ``[[SL]]`` 基线恒 0 看不见）。
    src 尾段同形豁免——源 chunk 以未终结注释收尾时后随字面本就以该注释的
    ``\n`` 终结符起头，zh 同形即忠实复现。
    """
    tok = _tail_unterminated_comment(ctx.lex_zh, ctx.masked_zh)
    if (
        tok is None
        or _tail_unterminated_comment(ctx.lex_src, ctx.masked_src) is not None
    ):
        return
    ctx.issues.append(
        Issue(
            "comment_eof",
            Severity.ERROR,
            f"译文尾段注释未终结到行尾: {tok}"
            f"（splice 后紧随字面首行被注释吞掉——}} 类结构字节死字节化，"
            f"\\caption{{ 类参数不闭合 → runaway）",
            found=tok,
        )
    )


def _check_protocol_echo(ctx: _Ctx) -> None:
    r"""协议回显守卫：zh 净多出 corrector/L0 协议字面 → error。

    repro-2410b §4b：Mode-B mock 把三段式 prompt 当正文翻，交付块带
    节标 + ``占位符缺失:`` 反馈行 + body 重复——占位符 multiset 可吻合
    而载荷脏（反馈行里 ``[[COMMENT_14]]`` splice 出 ``%`` 吞掉 chunk 外
    ``}`` → early_eof）。真模型 parrot prompt furniture 是同款逃逸通道，
    与 ``pipeline._intercept_leftover_ph`` 同层（error → 重译/回退原文）。
    词表 ``_ECHO_SIGS`` 单源（bench ``DIRTY_SIGS`` 同源 import）——
    子串直配 + src↔zh 净差（src 自带同形串属忠实翻译不追责；校验行话
    + ASCII 冒号/节标形态合法译文不产出）。
    """
    for sig in _ECHO_SIGS:
        n = ctx.zh.count(sig) - ctx.src.count(sig)
        if n > 0:
            ctx.issues.append(
                Issue(
                    "protocol_echo",
                    Severity.ERROR,
                    f"协议字面 {sig!r} 进入交付译文 ×{n}"
                    f"（corrector 反馈/重试协议被当正文回显，载荷脏）",
                    ctx.zh.find(sig),
                    found=sig,
                )
            )


# ---------------------------------------------------------------- 主入口

#: 缓存否决级规则 id 集——pipeline 升格拦截网（``xlat.pipeline._INTERCEPT_NETS``
#: 各条 ``l0_rule`` 字段）镜像复判的 l0 规则集：段级缓存命中与续跑装载旁路
#: ``validate_pair``，这五类 error 级签名由拦截网兜底防毒译出货
#: （``placeholder`` 网只镜像 zh−src 净多出占位符臂——缺失/锚定臂归阶梯
#: 修复管辖）。与注册表成员双向钉，漂移由 ``TestInterceptRegistry`` 拦截。
CACHE_VETO_RULES: Final = frozenset(
    {"placeholder", "ph_in_cs", "bare_cs", "residual_en", "dangerous_cs"}
)


#: ``validate_pair`` 全量检查表（序即执行序）——新增/移除检查只动本表
#: 一条目，调用点迭代驱动自动并入，不再逐名点名。入参 ``_Ctx`` 携
#: 共享预处理视图，各 checker 按需取用不再重复推导。
_CHECKERS: Final[tuple[Callable[[_Ctx], None], ...]] = (
    _check_placeholder,
    _check_brace,
    _check_env,
    _check_key,
    _check_math,
    _check_same_source,
    _check_length,
    _check_residual_en,
    _check_macro,
    _check_item_glue,
    _check_ph_in_cs,
    _check_bare_cs,
    _check_dangerous_cs,
    _check_protocol_echo,
    _check_comment_eof,
)


def validate_pair(src: str, zh: str) -> L0Report:
    """对 ``(src_chunk, zh_chunk)`` 跑 ``_CHECKERS`` 全表检查，返回结构化 verdict。

    ``report.ok`` 为 True 即可送 L1/拼回；False 时 ``report.feedback()``
    的文本可直接进 corrector 的 ``previous_validation_error`` 字段。
    """
    rep = L0Report(src_len=len(src), zh_len=len(zh))
    ctx = _Ctx(src, zh, rep.issues)
    for check in _CHECKERS:
        check(ctx)
    return rep


def pair_feedback(src: str, zh: str) -> str:
    """``validate_pair(src, zh).feedback()``——pipeline.validator 签名对齐版。

    四个调用臂（e2e/pipecore/worker×2）曾各手写同一 L0Report→str lambda
    适配；反馈文本语义归本层。
    """
    return validate_pair(src, zh).feedback()
