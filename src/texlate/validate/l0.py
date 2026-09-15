r"""L0 规则校验层 —— stdlib always-on，src↔zh 相对判定（规格 docs/08 §2.1）。

定位：校验链第一层，LLM 每返回一个 chunk 立即校验（实测 0.57ms/对）。
独立于任何 LaTeX 解析器（pylatexenc 静默截断的教训——校验器必须异构），
也是 node 不可用时的兜底路径。

设计原则 = "译文不得比原文更坏"：每条检查都是 src↔zh 比较而非 zh 绝对判定，
src 自带的不平衡/不一致不追责（继承容忍），只报 zh 相对 src 的新增损伤。

七条规则（docs/08 §2.1 表 + E21/E22 修订口径）：

  placeholder  ``[[TYPE_n]]``/``[[SL]]``/``[[PL]]`` multiset diff + lev≤2 修复建议；
               E22：严格序守恒降为 warn（``of X``→``X 的`` 合法换序占违例 ~95%），
               硬判据只留"结构占位符脱离行首"（BIBITEM 类）。
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

实测基线（tmp/exp/rule-validator，cases.jsonl 1636 例）：10 类破坏 100% 检出、
313 干净对 0 error-FP。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

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

#: key 承载命令：cite 族 / *ref 族 / label / bibitem / bibliography。
#: 只抓第一个 {..}（key 参数），可选 [..] 先吃掉。
KEY_CMD_RX: Final = re.compile(
    r"\\(?:cite[a-zA-Z]*|[a-zA-Z@]*ref|crefrange|label|bibitem|nocite"
    r"|bibliography|bibliographystyle)\*?"
    r"(?:\s*\[[^\]\n]*\])*"
    r"\s*\{([^{}]*)\}"
)

ENV_RX: Final = re.compile(r"\\(begin|end)\s*\{([^{}]*)\}")

#: CJK 统一表意文字（基本区 + 扩展 A + 兼容表意）。
CJK_RX: Final = re.compile(r"[㐀-䶿一-鿿豈-﫿]")

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
            k = s.find("\n", i)
            j = n if k < 0 else k
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


def _no_comments(s: str) -> str:
    """注释区间替换为等长空格（保位，供正则使用）；其余逐字节保留。"""
    out = list(s)
    for kind, text, pos in _lex(s):
        if kind == "cmt":
            for i in range(pos, pos + len(text)):
                out[i] = " "
    return "".join(out)


def _lev(a: str, b: str, cap: int) -> int:
    """Levenshtein 距离，超 cap 提前返回 cap+1。"""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        rowmin = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v)
            rowmin = min(rowmin, v)
        if rowmin > cap:
            return cap + 1
        prev = cur
    return prev[-1]


# ---------------------------------------------------------------- 七条规则


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
            d = _lev(ph_core, cand_core, _LEV_CAP)
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


def _check_ph_anchor(snc: str, znc: str, issues: list[Issue]) -> None:
    """行首锚定的结构占位符（BIBITEM 类）脱位 → error（E22 硬判据余量）。"""
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


def _check_placeholder(src: str, zh: str, issues: list[Issue]) -> None:
    """占位符 multiset diff + lev≤2 修复配对 + 序守恒软信号 + BIBITEM 锚定。"""
    snc, znc = _no_comments(src), _no_comments(zh)
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
        for m in PH_FUZZY_RX.finditer(znc)
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
        for m in ENV_RX.finditer(_no_comments(s))
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
    for m in KEY_CMD_RX.finditer(_no_comments(s)):
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


# ---------------------------------------------------------------- 主入口


def validate_pair(src: str, zh: str) -> L0Report:
    """对 ``(src_chunk, zh_chunk)`` 跑全部七组检查，返回结构化 verdict。

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
    return rep
