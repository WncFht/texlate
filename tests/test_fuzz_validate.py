"""validate/l0+l1 对抗性性质 fuzz。

l0 ``validate_pair`` 侧（oracle 全部独立代码路径）：

- 通用不变量：任意 src/zh 对恒不抛；``L0Report`` 字段形态合法（rule 注册
  表、severity、pos 界、to_dict JSON 可序列化、by_rule 划分、feedback 恰为
  error 消息拼接、双跑确定性）；
- 恒等对 ``(x, x)`` 不产 error——「译文不得比原文更坏」的零基线，warn 只许
  math 奇数 ``$`` 与 length CJK 占比两类继承信号；
- ``_lex`` 结构不变量：token 拼接恒还原输入、pos 对齐、kind 合法；
- 占位符分类全量 oracle：独立「前导反斜杠 run 奇偶」遮盖器 + 自写
  ``[[..]]`` 严格形/模糊四臂/注释区/行锚定扫描器 + lev≤2 递归增广路
  最大匹配，预测 missing/extra/typo/cmtfab/order/anchor 签名多重集
  与实现一致；
- ``src_literal`` 净差豁免口径（src 自带模糊形 verbatim 不算臆造）；
- ``%`` 前 ``\\`` run 奇偶决定 token 落「注释区臆造」还是「正文多出」；
- key/brace/math/env/cs_names/item_glue/macro/echo/length 逐规则独立
  oracle 交叉验证；bare_cs/ph_in_cs 存在性谓词。

l1 ``TsValidator`` 侧（全离线——fake proc + monkeypatch 传输层，不依赖 node）：

- ``TsBaseline``/``TsResult`` dict round-trip 与 ``verdict_ok`` 契约；
- ``_one`` 按 id 配对丢弃迟到/错序/重复行，EOF 哨兵即死，非 JSON → L1Error；
- ``validate_batch`` 非零退出/行数不符/非 JSON/spawn 失败 → L1Error；
- ``available()`` = node + worker.js + 双 npm 依赖的三因子合取；
- ``_pump`` 恒投 ``None`` 哨兵；``open``/``close`` 幂等；``_drain_lines``
  清滞留；``sign``/``validate`` 请求记录成形正确；
- env 覆盖优先级：参数 > ``TEXLATE_*`` env > 默认/PATH。
"""

from __future__ import annotations

import ast
import json
import os
import queue
import re
import shutil
import string
import subprocess
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import random
    from collections.abc import Callable

import pytest
from _fuzzkit import (
    assert_deterministic,
    fuzz_rng,
    short,
    soup_join,
    soup_pick,
)

from texlate.redlines import L2_REDLINE_CLASSES
from texlate.textutil import bare_cs_net, is_cjk_cp, ph_in_cs_net
from texlate.validate.l0 import (
    STRUCT_CMDS,
    Issue,
    Severity,
    _brace_profile,
    _cs_names,
    _env_signature,
    _key_multiset,
    _lex,
    _math_profile,
    validate_pair,
)
from texlate.validate.l1 import L1Error, TsBaseline, TsResult, TsValidator
from texlate.validate.l2 import L2Verdict, parse_log, parse_log_text
from texlate.validate.report import aggregate

_RULES = {
    "placeholder",
    "brace",
    "env",
    "key",
    "math",
    "length",
    "macro",
    "item_glue",
    "ph_in_cs",
    "bare_cs",
    "protocol_echo",
}

# ------------------------------------------------------------------ 汤料

#: 通用 soup——LaTeX 结构碎片/占位符/注释/逃逸/协议字面/Unicode 混排。
_SOUP = [
    "word ",
    "text",
    "中文",
    "词语。",
    "，",
    "：",
    "\\textbf{x}",
    "\\emph{a}",
    "\\alpha",
    "\\foo",
    "\\bar",
    "\\和",
    "\\ ",
    "\\,",
    "\\;",
    "\\!",
    "~",
    "{",
    "}",
    "\\{",
    "\\}",
    "$",
    "$$",
    "\\(",
    "\\)",
    "\\[",
    "\\]",
    "\\begin{equation}",
    "\\end{equation}",
    "\\begin{a}",
    "\\end{b}",
    "\\begin{itemize}",
    "\\end{itemize}",
    "\\item ",
    "\\cite{a}",
    "\\cite{a,b}",
    "\\parencite{k}",
    "\\ref{fig:1}",
    "\\label{s:x}",
    "\\crefrange{a}{b}",
    "\\bibitem{k}",
    "\\bibliography{refs}",
    "[[MATH_1]]",
    "[[MATH_2]]",
    "[[CITE_1]]",
    "[[REF_3]]",
    "[[SL]]",
    "[[PL]]",
    "[[MTH_1]]",
    "[[math_1]]",
    "【MATH_1】",
    "[X_1]",
    "[RS80]",
    "[[MATH_1]",
    "[[5]]",
    "【图1】",
    "% 注释 \n",
    "\\%",
    "\\\\",
    "\\\\%",
    "%",
    "\n",
    "\n\n",
    "\r\n",
    " ",
    "\t",
    "\\fo[[CMD_1]]o",
    "\\protect[[REF_1]]",
    "占位符缺失:",
    "[Original]",
    "[Error]",
    "\\itemFSU",
    "\\itemOC",
    "\\documentclass{article}",
    "\\newcommand{\\x}{y}",
    "\\",
    "[[",
    "]]",
    "[",
    "]",
    "\\\n",
    "\\itemsep",
    "[[BIBITEM_1]]",
    "[[COMMENT_1]]",
]

#: 恒等对 alphabet——剔除 ``[[COMMENT_n]]``（行中带尾形态触发 zh 侧绝对
#: 尾段判据）与 ``[[BIBITEM_n]]``（同 token 一处行首一处行中时锚定集按
#: 类型判定、逐出现检查 → 行中出现被报）；两者都只在畸形 src 出现。
_SOUP_ID = [
    t
    for t in _SOUP
    if not t.startswith("[[COMMENT")
    and not t.startswith("[[BIBITEM")
    and "占位符缺失:" not in t
]

#: 占位符专项 soup——ph 类 token 占比高，供分类 oracle 压测。
_PH_SOUP = [
    "见 ",
    "文。",
    "和",
    "的",
    "x",
    " ",
    "\n",
    "\n\n",
    "  ",
    "[[MATH_1]]",
    "[[MATH_2]]",
    "[[MATH_12]]",
    "[[CITE_1]]",
    "[[REF_1]]",
    "[[ENV_2]]",
    "[[SL]]",
    "[[PL]]",
    "[[AAAA]]",
    "[[AABB]]",
    "[[MTH_1]]",
    "[[math_2]]",
    "【MATH_1】",
    "[X_1]",
    "[RS80]",
    "[[MATH_1]",
    "[[5]]",
    "【图1】",
    "[[BIBITEM_1]]",
    "[[BIBITEM_2]]",
    "[[COMMENT_1]]",
    "[[COMMENT_2]]",
    "%",
    " \\%",
    "\\\\%",
    "% note\n",
    "\\textbf{x}",
    "\\cite{a}",
    "\\",
    "\\\\",
]

#: key 命令 soup——族内/族缘/族外名 + 可选参/星号/畸形括号。
_KEY_SOUP = [
    "\\cite{a}",
    "\\cite{a,b,c}",
    "\\cite {a}",
    "\\cite[see]{a}",
    "\\cite[pre][post]{a}",
    "\\cite*{a}",
    "\\parencite{vaswani2017}",
    "\\footcite{k}",
    "\\textcite{smith20}",
    "\\nocite{*}",
    "\\citeauthor{au1}",
    "\\citeyear{y1}",
    "\\mcite{m1,m2}",
    "\\cites{a}{b}",
    "\\Cite{cap1}",
    "\\parenCite{pc}",
    "\\zlabel{zl}",
    "\\ref{fig:1}",
    "\\eqref{eq:x}",
    "\\pageref{p}",
    "\\autoref{a}",
    "\\cref{c1}",
    "\\Cref{c2}",
    "\\vref{v}",
    "\\ref*{r}",
    "\\label{sec:x}",
    "\\zref{z}",
    "\\bibitem{b1}",
    "\\bibliography{refs}",
    "\\bibliographystyle{plain}",
    "\\mybibliography{mb}",
    "\\addbibresource{x.bib}",
    "\\addsectionbib{s.bib}",
    "\\addglobalbib{g.bib}",
    "\\crefrange{a}{b}",
    "\\cpagerefrange{a}{b}",
    "\\refrange{x}{y}",
    "\\crefrange{a} {b}",
    "\\prefer{pr}",
    "\\refname{rn}",
    "\\cite1{bad}",
    "\\cite@x{at}",
    "\\x@cite{atpre}",
    "\\textbf{nb}",
    "\\foo{bar}",
    "{lone}",
    "\\cite{",
    "\\cite{unclosed",
    "\\cite{a\\cite{b}}",
    "\\\\cite{esc}",
    "% \\cite{cmt}\n",
    "\\cite{%\n}",
    "普通文本",
    "，",
    " ",
    "\n",
]

#: env 命令 soup——配对/孤儿/错配/畸形/注释内环境标记。
_ENV_SOUP = [
    "\\begin{equation}",
    "\\end{equation}",
    "\\begin{a}",
    "\\end{a}",
    "\\begin{b}",
    "\\end{b}",
    "\\begin{itemize}",
    "\\end{itemize}",
    "\\begin{thm*}",
    "\\end{thm*}",
    "\\begin {}",
    "\\begin{x",
    "\\begin{{x}}",
    "\\end",
    "\\begin",
    "\\\\begin{esc}",
    "% \\begin{cmt}\n",
    "\\begin{%\n}",
    "text ",
    "中",
    "{",
    "}",
    "\n",
    " ",
]

#: math/brace/cs 通用碎片 soup。
_STRUCT_SOUP = [
    "$",
    "$$",
    "\\$",
    "\\(",
    "\\)",
    "\\[",
    "\\]",
    "\\\\(",
    "\\(",
    "{",
    "}",
    "\\{",
    "\\}",
    "{{",
    "}}",
    "\\alpha",
    "\\textbf",
    "\\item",
    "\\itemsep",
    "\\itemFSU",
    "\\itemOC",
    "\\和x",
    "\\ ",
    "\\,",
    "\\;",
    "\\:",
    "\\!",
    "\\\n",
    "\\\t",
    "~",
    "\\~",
    "a~b",
    "% cmt { $ \\alpha\n",
    "\\% {",
    "\\\\{",
    "\\\\%",
    "word ",
    "中",
    "\n",
    "\r\n",
    " ",
    "\\",
]

# ------------------------------------------------------------------ oracle 件

_UPPER_DIG_US = frozenset(string.ascii_uppercase + string.digits + "_")
_ASCII_ALPHA_US = frozenset(string.ascii_letters + "_")
_HAS_LATIN_RX = re.compile(r"[A-Za-z]")
_PH_CORE_RX = re.compile(r"[A-Za-z0-9_]+")
_COMMENT_TOK_RX = re.compile(r"\[\[COMMENT_\d+\]\]")
_BIBITEM_TOK_RX = re.compile(r"\[\[BIBITEM_\d+\]\]")
_NONASCII_RX = re.compile(r"[^\x00-\x7f]")
_FRAGILE_BS_SET = {"\\ ", "\\,", "\\;", "\\:", "\\!"}
_CJK_RX = re.compile("[一-鿿㐀-䶿豈-﫿〇]")  # 与 textutil.CJK_RX 同集的核心面（BMP 内）

_LEV_CAP = 2
_FUZZY_MAX = 48  # PH_FUZZY_RX inner 上限（``{1,48}`` 口径）


def _o_mask(s: str) -> str:
    r"""独立注释遮盖：``%`` 前导连续 ``\\`` run 偶数→注释起点（奇数=``\%`` 转义）。

    与 ``mask_comments`` 的 jump-2 消费不同代码路径——逐位向右回看 run 长度；
    换行（``\r``/``\n``）终止注释态且自身不遮盖。
    """
    out = list(s)
    in_cmt = False
    for i, c in enumerate(s):
        if c in "\r\n":
            in_cmt = False
            continue
        if in_cmt:
            out[i] = " "
            continue
        if c == "%":
            run = 0
            j = i - 1
            while j >= 0 and s[j] == "\\":
                run += 1
                j -= 1
            if run % 2 == 0:
                in_cmt = True
                out[i] = " "
    return "".join(out)


def _o_ph_scan(s: str) -> list[tuple[str, int]]:
    """严格形 ``[[X]]`` 左到右非重叠扫描：inner 全 ``[A-Z0-9_]`` 且首字符 ``A-Z``。"""
    out: list[tuple[str, int]] = []
    i, n = 0, len(s)
    while i < n:
        if s.startswith("[[", i) and i + 2 < n and s[i + 2] in string.ascii_uppercase:
            j = i + 3
            while j < n and s[j] in _UPPER_DIG_US:
                j += 1
            if s[j : j + 2] == "]]":
                out.append((s[i : j + 2], i))
                i = j + 2
                continue
        i += 1
    return out


_O_PH_FULL_RX = re.compile(r"\[\[[A-Z][A-Z0-9_]*\]\]")


def _o_is_ph(tok: str) -> bool:
    """是否严格形占位符（``[[A-Z][A-Z0-9_]*]]``）。"""
    return bool(_O_PH_FULL_RX.fullmatch(tok))


def _o_fuzzy_scan(s: str) -> list[str]:  # noqa: C901,PLR0912 -- 四臂逐位扫内在复杂
    """模糊占位符候选四臂独立实现：``[[..]]`` / ``[[..]`` / ``[X_1]`` / ``【..】``。"""
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        tok: str | None = None
        if s.startswith("[[", i):
            # 臂1/2：inner 为到首个 [] 或换行的 run，须含 ASCII 字母且 ≤48
            j = i + 2
            while j < n and s[j] not in "[]\n":
                j += 1
            inner = s[i + 2 : j]
            if 1 <= len(inner) <= _FUZZY_MAX and _HAS_LATIN_RX.search(inner):
                if s[j : j + 2] == "]]":
                    tok = s[i : j + 2]
                elif j < n and s[j] == "]" and s[j + 1 : j + 2] != "]":
                    tok = s[i : j + 1]
        elif s[i] == "[" and (i == 0 or s[i - 1] != "["):
            # 臂3：[A-Za-z_]+ _? -? \d+ ]（后非 ]；_? 被 + 先行吃掉恒空转）
            k = i + 1
            while k < n and s[k] in _ASCII_ALPHA_US:
                k += 1
            if k > i + 1:
                if k < n and s[k] == "-":
                    k += 1
                d = k
                while d < n and s[d].isdecimal():  # \d = Unicode Nd（非 isdigit 超集）
                    d += 1
                if d > k and d < n and s[d] == "]" and s[d + 1 : d + 2] != "]":
                    tok = s[i : d + 1]
        elif s[i] == "【":
            j = i + 1
            while j < n and s[j] not in "【】\n":
                j += 1
            inner = s[i + 1 : j]
            if (
                1 <= len(inner) <= _FUZZY_MAX
                and _HAS_LATIN_RX.search(inner)
                and s[j : j + 1] == "】"
            ):
                tok = s[i : j + 1]
        if tok is not None:
            out.append(tok)
            i += len(tok)
        else:
            i += 1
    return out


def _o_cmt_ph(s: str) -> Counter[str]:
    """注释区内严格形占位符计数（parity 注释区间 + 独立 token 扫描）。"""
    c: Counter[str] = Counter()
    in_cmt = False
    start = 0
    spans: list[tuple[int, int]] = []
    for idx, ch in enumerate(s):
        if ch in "\r\n":
            if in_cmt:
                spans.append((start, idx))
                in_cmt = False
            continue
        if in_cmt:
            continue
        if ch == "%":
            run = 0
            j = idx - 1
            while j >= 0 and s[j] == "\\":
                run += 1
                j -= 1
            if run % 2 == 0:
                in_cmt = True
                start = idx
    if in_cmt:
        spans.append((start, len(s)))
    for a, b in spans:
        c.update(t for t, _ in _o_ph_scan(s[a:b]))
    return c


def _o_lev(a: str, b: str) -> int:
    """无上限 Levenshtein（oracle 用全量 DP）。"""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _o_line_of(s: str, start: int, end: int) -> str:
    lo = s.rfind("\n", 0, start) + 1
    hi = s.find("\n", end)
    line = s[lo:] if hi < 0 else s[lo:hi]
    return line.removesuffix("\r")


def _o_comment_line_only(line: str) -> bool:
    """``[ \\t]*(?:[[COMMENT_n]][ \\t]*)+`` 行形判定。"""
    i, n = 0, len(line)
    cnt = 0
    while True:
        while i < n and line[i] in " \t":
            i += 1
        m = _COMMENT_TOK_RX.match(line, i)
        if m is None:
            return cnt > 0 and i == n
        cnt += 1
        i = m.end()


def _o_comment_tail_only(tail: str) -> bool:
    """``(?:[ \\t]*[[COMMENT_n]])*[ \\t]*`` 尾段判定。"""
    i, n = 0, len(tail)
    while True:
        while i < n and tail[i] in " \t":
            i += 1
        m = _COMMENT_TOK_RX.match(tail, i)
        if m is None:
            return i == n
        i = m.end()


def _o_ph_match(missing: list[str], cands: list[str]) -> dict[int, int]:
    """拼错配对 oracle：与 impl 同义的 Kuhn 增广路最大匹配 → ``{missing: cand}``。

    邻接按 (lev, 下标) 升序、逐 missing 一轮 DFS、seen 按轮隔离；
    递归形与 impl ``_ph_max_pairs`` 迭代栈异路径。
    """
    adj: list[list[int]] = []
    for ph_tok in missing:
        core = ph_tok.strip("[]")
        row: list[tuple[int, int]] = []
        for ci, cand in enumerate(cands):
            m = _PH_CORE_RX.search(cand)
            ccore = m.group(0) if m else cand
            d = min(_o_lev(core.upper(), ccore.upper()), _LEV_CAP + 1)
            if d <= _LEV_CAP:
                row.append((d, ci))
        adj.append([ci for _, ci in sorted(row)])
    match_of = [-1] * len(cands)

    def _aug(mi: int, seen: set[int]) -> bool:
        for ci in adj[mi]:
            if ci in seen:
                continue
            seen.add(ci)
            if match_of[ci] < 0 or _aug(match_of[ci], seen):
                match_of[ci] = mi
                return True
        return False

    for mi in range(len(missing)):
        _aug(mi, set())
    return {mi: ci for ci, mi in enumerate(match_of) if mi >= 0}


def _o_ph_sigs(src: str, zh: str) -> list[tuple[str, ...]]:  # noqa: C901,PLR0912 -- 全规则重放内在复杂
    """``_check_placeholder`` 全量签名 oracle——每条产 issue 归一为一枚签名。"""
    sm, zm = _o_mask(src), _o_mask(zh)
    sscan, zscan = _o_ph_scan(sm), _o_ph_scan(zm)
    sseq = [t for t, _ in sscan]
    zseq = [t for t, _ in zscan]
    scnt, zcnt = Counter(sseq), Counter(zseq)
    src_lit = Counter(t for t in _o_fuzzy_scan(src) if not _o_is_ph(t))
    zfz = [t for t in _o_fuzzy_scan(zh) if not _o_is_ph(t)]
    missing = sorted((scnt - zcnt).elements())
    cands = list((zcnt - scnt).elements())
    cands += list((Counter(zfz) - src_lit).elements())
    paired = _o_ph_match(missing, cands)
    sigs: list[tuple[str, ...]] = []
    for mi, ph_tok in enumerate(missing):
        if mi in paired:
            sigs.append(("typo", ph_tok, cands[paired[mi]]))
        else:
            sigs.append(("missing", ph_tok))
    used = set(paired.values())
    for ci, cand in enumerate(cands):
        if ci not in used:
            sigs.append(("extra", cand))
    if not (scnt - zcnt) and not (zcnt - scnt) and sseq != zseq:
        sigs.append(("order",))
    sigs.extend(("cmtfab", tok) for tok in sorted(_o_cmt_ph(zh) - _o_cmt_ph(src)))
    anchored = {
        t
        for t, p in sscan
        if _BIBITEM_TOK_RX.fullmatch(t) and not sm[sm.rfind("\n", 0, p) + 1 : p].strip()
    }
    for t, p in zscan:
        if (
            _BIBITEM_TOK_RX.fullmatch(t)
            and t in anchored
            and zm[zm.rfind("\n", 0, p) + 1 : p].strip()
        ):
            sigs.append(("bibanchor", t))
    cmt_anchor = {
        t
        for t, p in sscan
        if _COMMENT_TOK_RX.fullmatch(t)
        and _o_comment_line_only(_o_line_of(sm, p, p + len(t)))
    }
    for t, p in zscan:
        if not _COMMENT_TOK_RX.fullmatch(t):
            continue
        if t in cmt_anchor:
            clean = _o_comment_line_only(_o_line_of(zm, p, p + len(t)))
        else:
            hi = zm.find("\n", p + len(t))
            tail = zm[p + len(t) :] if hi < 0 else zm[p + len(t) : hi]
            clean = _o_comment_tail_only(tail.removesuffix("\r"))
        if not clean:
            sigs.append(("cmtanchor", t))
    return sigs


def _impl_ph_sigs(issues: list[Issue]) -> list[tuple[str, ...]]:
    """实现侧 placeholder 规则 issue → 同形签名。"""
    out: list[tuple[str, ...]] = []
    for i in issues:
        if i.rule != "placeholder":
            continue
        m = i.message
        if "拼错" in m:
            out.append(("typo", i.expected or "", i.found or ""))
        elif "缺失" in m:
            out.append(("missing", i.expected or ""))
        elif "多余" in m:
            out.append(("extra", i.found or ""))
        elif "臆造" in m:
            out.append(("cmtfab", i.found or ""))
        elif "顺序" in m:
            out.append(("order",))
        elif "行首" in m:
            out.append(("bibanchor", i.expected or ""))
        elif "混入" in m:
            out.append(("cmtanchor", i.expected or ""))
        else:  # pragma: no cover - 未知占位符消息形态
            out.append(("unknown", m))
    return out


def _o_run_escaped(t: str, i: int) -> bool:
    """``t[i]`` 是否被奇数 ``\\`` run 转义（True=转义/不算独立 token）。"""
    run = 0
    j = i - 1
    while j >= 0 and t[j] == "\\":
        run += 1
        j -= 1
    return run % 2 == 1


def _o_brace_profile(s: str) -> tuple[int, int, int, int, int]:
    """``{}`` 记账 oracle：遮盖后仅未转义 ``{/}`` 参与。"""
    t = _o_mask(s)
    opens = closes = depth = minpref = 0
    first_neg = -1
    for i, c in enumerate(t):
        if c not in "{}" or _o_run_escaped(t, i):
            continue
        if c == "{":
            depth += 1
            opens += 1
        else:
            depth -= 1
            closes += 1
            minpref = min(minpref, depth)
            if depth < 0 and first_neg < 0:
                first_neg = i
    return opens, closes, depth, minpref, first_neg


def _o_math_profile(s: str) -> tuple[int, int, int, int, int]:
    """``($,\\(,\\),\\[,\\])`` 计数 oracle——定界符的 ``\\`` 自身须未被转义。"""
    t = _o_mask(s)
    d = lp = rp = lb = rb = 0
    for i, c in enumerate(t):
        if c == "$":
            if not _o_run_escaped(t, i):
                d += 1
        elif (
            c in "()[]" and i > 0 and t[i - 1] == "\\" and not _o_run_escaped(t, i - 1)
        ):
            if c == "(":
                lp += 1
            elif c == ")":
                rp += 1
            elif c == "[":
                lb += 1
            else:
                rb += 1
    return d, lp, rp, lb, rb


def _o_cs_names(s: str) -> tuple[Counter[str], Counter[str]]:
    """cs 名 + 脆弱间距 token oracle（遮盖 + 自写序扫）。"""
    t = _o_mask(s)
    cs: Counter[str] = Counter()
    frag: Counter[str] = Counter()
    i, n = 0, len(t)
    while i < n:
        c = t[i]
        if c == "\\":
            if i + 1 < n and t[i + 1].isalpha():
                j = i + 1
                while j < n and (t[j].isalpha() or t[j] == "@"):
                    j += 1
                cs[t[i + 1 : j]] += 1
                i = j
                continue
            tok = t[i : i + 2]
            norm = "\\ " if tok[1:].isspace() else tok
            if norm in _FRAGILE_BS_SET:
                frag[norm] += 1
            i += 2
            continue
        if c == "~":
            frag["~"] += 1
        i += 1
    return cs, frag


def _o_grab_brace(t: str, i: int) -> tuple[str, int] | None:
    """``{[^{}]*}`` 组取：``{`` 起、内部无花括号、``}`` 止 → ``(内容, 止后)``。"""
    if i >= len(t) or t[i] != "{":
        return None
    j = i + 1
    while j < len(t) and t[j] not in "{}":
        j += 1
    if j >= len(t) or t[j] != "}":
        return None
    return t[i + 1 : j], j + 1


def _o_skip_ws(t: str, i: int) -> int:
    while i < len(t) and t[i].isspace():
        i += 1
    return i


def _o_skip_star_opts(t: str, i: int) -> int:
    """``\\*?`` + ``(?:\\s*\\[[^\\]\\n]*\\])*`` 等价位移（失败迭代整体回退）。"""
    if i < len(t) and t[i] == "*":
        i += 1
    while True:
        j = _o_skip_ws(t, i)
        if j < len(t) and t[j] == "[":
            k = j + 1
            while k < len(t) and t[k] not in "]\n":
                k += 1
            if k < len(t) and t[k] == "]":
                i = k + 1
                continue
            return i
        return i


_O_KEY_NAME_RX = re.compile(r"[a-zA-Z@]+")
_O_CITES_RX = re.compile(r"[a-zA-Z@]*[Cc]ites")
_O_KEY_CMD_RX = re.compile(
    r"[a-zA-Z@]*[Cc]ite[a-zA-Z]*|[a-zA-Z@]*ref|[a-zA-Z@]*label|bibitem"
    r"|addbibresource|addglobalbib|addsectionbib|[a-zA-Z@]*bibliography(?:style)?"
)
_O_REFRANGE_RX = re.compile(r"[a-zA-Z@]*refrange")


def _o_add_keys(c: Counter[str], grp: str) -> None:
    for raw in grp.split(","):
        key = raw.strip()
        if key:
            c[key] += 1


def _o_extra_braces(t: str, i: int, c: Counter[str], limit: int | None) -> int:
    """从 i 起相邻 ``{..}`` 逐对入 c（至多 limit 个，None 不限），返回新位置。"""
    n = len(t)
    taken = 0
    while i < n and t[i] == "{" and (limit is None or taken < limit):
        g = _o_grab_brace(t, i)
        if g is None:
            break
        _o_add_keys(c, g[0])
        i, taken = g[1], taken + 1
    return i


def _o_key_multiset(s: str) -> Counter[str]:
    """key 多重集 oracle：自写命令名扫描 + 族属判定 + ``{..}`` 组取。"""
    t = _o_mask(s)
    c: Counter[str] = Counter()
    i, n = 0, len(t)
    while i < n:
        if t[i] != "\\":
            i += 1
            continue
        m = _O_KEY_NAME_RX.match(t, i + 1)
        if m is None:
            i += 1
            continue
        name = m.group(0)
        end = i + 1  # 匹配失败时与 finditer 同义：起点 +1 重扫
        if _O_CITES_RX.fullmatch(name):
            j = _o_skip_ws(t, _o_skip_star_opts(t, m.end()))
            g1 = _o_grab_brace(t, j)
            if g1 is not None:
                _o_add_keys(c, g1[0])
                end = _o_extra_braces(t, g1[1], c, None)  # 相邻 {..} 连写全算
        elif _O_REFRANGE_RX.fullmatch(name):
            j = _o_skip_ws(t, _o_skip_star_opts(t, m.end()))
            g1 = _o_grab_brace(t, j)
            if g1 is not None:
                _o_add_keys(c, g1[0])
                end = _o_extra_braces(t, g1[1], c, 1)  # 第二参相邻才算
        elif _O_KEY_CMD_RX.fullmatch(name):
            j = _o_skip_ws(t, _o_skip_star_opts(t, m.end()))
            g1 = _o_grab_brace(t, j)
            if g1 is not None:
                _o_add_keys(c, g1[0])
                end = g1[1]
        i = max(end, i + 1)
    return c


def _o_env_tokens(s: str) -> list[tuple[str, str]]:
    """``\\begin|\\end`` + ``\\s*{[^{}]*}`` 事件流 oracle（遮盖 + 自写扫描）。"""
    t = _o_mask(s)
    out: list[tuple[str, str]] = []
    i, n = 0, len(t)
    while i < n:
        kind = ""
        if t.startswith("\\begin", i):
            kind = "begin"
        elif t.startswith("\\end", i):
            kind = "end"
        if kind:
            j = _o_skip_ws(t, i + 1 + len(kind))
            g = _o_grab_brace(t, j)
            if g is not None:
                out.append((kind, g[0].strip()))
                i = g[1]
                continue
        i += 1
    return out


def _o_env_signature(
    s: str,
) -> tuple[int, int, Counter[str], Counter[str], Counter[str]]:
    """env 栈签名 oracle：多余 end / 错配 / 未闭合 begin 名 / begin 名 / end 名。"""
    stack: list[str] = []
    n_orphan = n_mis = 0
    toks = _o_env_tokens(s)
    for kind, name in toks:
        if kind == "begin":
            stack.append(name)
        elif not stack:
            n_orphan += 1
        else:
            if stack[-1] != name:
                n_mis += 1
            stack.pop()
    begins = Counter(nme for k, nme in toks if k == "begin")
    ends = Counter(nme for k, nme in toks if k == "end")
    return n_orphan, n_mis, Counter(stack), begins, ends


def _o_strip_ph(s: str) -> str:
    """剥严格 ``[[A-Z…]]`` 占位符——impl ``PH_ANY_LIKE_RX.sub`` 同序第一遍。"""
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s.startswith("[[", i):
            j = i + 2
            while j < n and s[j] in _UPPER_DIG_US:
                j += 1
            if (
                j > i + 2
                and s[i + 2] in string.ascii_uppercase
                and s[j : j + 2] == "]]"
            ):
                out.append(" ")
                i = j + 2
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _o_strip_cs(s: str) -> str:
    """剥 ``\\[a-zA-Z@]+\\*?``/``\\<任意>`` token——impl ``_CS_OR_SYM_RX.sub``
    同序第二遍。

    cs 名是 ASCII 集（非 ``isalpha``）——``\\和x`` 只剥 ``\\和`` 留下 ``x``
    计入拉丁。``\\<换行>`` 亦按控制符号剥（``[\\s\\S]`` 口径）。
    """
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt.isascii() and (nxt.isalpha() or nxt == "@"):
                j = i + 1
                while j < n and s[j].isascii() and (s[j].isalpha() or s[j] == "@"):
                    j += 1
                if j < n and s[j] == "*":
                    j += 1
                out.append(" ")
                i = j
                continue
            out.append(" ")
            i += 2
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _o_strip_for_length(s: str) -> str:
    """剥占位符→剥 cs 两遍序（impl ``_prose`` 同序——``\\[[MTH_1]]`` 类
    cs 前缀占位符须先 ph 后 cs 才剥净）。"""
    return _o_strip_cs(_o_strip_ph(s))


_LEN_MIN_TOKENS = 10
_LEN_RATIO_LO = 0.30
_LEN_RATIO_HI = 3.00
_LEN_LAT_MIN = 8
_LEN_CJK_SHARE = 0.30


def _o_est_tokens(s: str) -> float:
    """token 代理 oracle（l0 ``_est_tokens`` 同款）：CJK 1 + 其余可见/4。"""
    cjk = len(_CJK_RX.findall(s))
    nonws = sum(1 for ch in s if not ch.isspace())
    return cjk + (nonws - cjk) / 4


def _o_length_sigs(src: str, zh: str) -> set[str]:
    """length 规则签名集 oracle：``{"ratio","cjk"}`` 子集。

    E24：ratio 臂改 token 代理口径且升 error（签名解析不分 severity）。
    """
    sigs: set[str] = set()
    ss = _o_strip_for_length(src)
    sz = _o_strip_for_length(zh)
    ts = _o_est_tokens(ss)
    if ts >= _LEN_MIN_TOKENS:
        r = _o_est_tokens(sz) / ts
        if not _LEN_RATIO_LO <= r <= _LEN_RATIO_HI:
            sigs.add("ratio")
    cjk = len(_CJK_RX.findall(sz))
    lat = sum(1 for ch in sz if ch.isascii() and ch.isalpha())
    if lat >= _LEN_LAT_MIN and cjk / (cjk + lat) < _LEN_CJK_SHARE:
        sigs.add("cjk")
    return sigs


def _o_same_source_hit(src: str, zh: str) -> bool:
    """same_source 规则 oracle：bib/短残段豁免 + 规范化等值 + 拉丁主导。"""
    if "[[BIB_" in src:
        return False
    ss = _o_strip_for_length(src).lower()
    sz = _o_strip_for_length(zh).lower()
    ss = re.sub(r"\s+", " ", ss).strip()
    sz = re.sub(r"\s+", " ", sz).strip()
    if _o_est_tokens(ss) < _LEN_MIN_TOKENS or ss != sz:
        return False
    cjk = len(_CJK_RX.findall(ss))
    lat = sum(1 for ch in ss if ch.isascii() and ch.isalpha())
    return lat >= _LEN_LAT_MIN and cjk / (cjk + lat) < _LEN_CJK_SHARE


def _o_macro_sigs(src: str, zh: str) -> list[tuple[str, str]]:
    """macro 规则签名 oracle：(类别, 名) 多重集。"""
    sn, sf = _o_cs_names(src)
    zn, zf = _o_cs_names(zh)
    sigs: list[tuple[str, str]] = []
    for nme in zn - sn:
        if _NONASCII_RX.search(nme):
            sigs.append(("nonascii", nme))
        elif nme in STRUCT_CMDS:
            sigs.append(("struct", nme))
        else:
            sigs.append(("new", nme))
    sigs.extend(
        ("fragile", tok)
        for tok in _FRAGILE_BS_SET | {"~"}
        if sf.get(tok, 0) - zf.get(tok, 0) > 0
    )
    sigs.extend(("dropped", nme) for nme in sn - zn if nme not in STRUCT_CMDS)
    return sigs


def _impl_macro_sigs(issues: list[Issue]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for i in issues:
        if i.rule != "macro":
            continue
        m = i.message
        if "非 ASCII" in m:
            name = re.search(r"控制序列 \\(\S+) ×", m)
            out.append(("nonascii", name.group(1) if name else "?"))
        elif "幻觉结构" in m:
            name = re.search(r"\\(\S+) ×", m)
            out.append(("struct", name.group(1) if name else "?"))
        elif "新增控制序列" in m:
            name = re.search(r"\\(\S+) ×", m)
            out.append(("new", name.group(1) if name else "?"))
        elif "脆弱间距" in m:
            name = re.search(r"脆弱间距命令 ('.*?') 丢失", m)
            out.append(("fragile", ast.literal_eval(name.group(1)) if name else "?"))
        elif "未保留" in m:
            name = re.search(r"控制序列 \\(\S+) 未保留", m)
            out.append(("dropped", name.group(1) if name else "?"))
    return out


def _soup(rng: random.Random, alpha: list[str], lo: int, hi: int) -> str:
    return "".join(rng.choice(alpha) for _ in range(rng.randint(lo, hi)))


# ================================================================== l0 通用


def test_fuzz_lex_invariants() -> None:
    """``_lex`` 结构不变量：token 拼接还原输入、pos 对齐、kind 语义合法。"""
    rng = fuzz_rng(20260930)
    for _ in range(1500):
        s = _soup(rng, _SOUP, 0, 14)
        toks = _lex(s)
        i_expect = 0  # 连续无缝覆盖：cs 占 ``\\``+名长，其余按 text 长
        for kind, text, pos in toks:
            assert pos == i_expect
            assert kind in {"cs", "bs", "cmt", "ch"}
            if kind == "ch":
                assert len(text) == 1
                assert text not in {"\\", "%"}
                assert s[pos] == text
                i_expect += 1
            elif kind == "bs":
                assert text.startswith("\\")
                assert len(text) in {1, 2}
                assert s[pos : pos + len(text)] == text
                i_expect += len(text)
            elif kind == "cmt":
                assert text.startswith("%")
                assert "\n" not in text
                assert "\r" not in text
                end = pos + len(text)
                assert end == len(s) or s[end] in "\r\n"
                i_expect += len(text)
            else:
                assert s[pos] == "\\"
                assert text
                assert text[0].isalpha()
                assert all(ch.isalpha() or ch == "@" for ch in text)
                assert s[pos + 1 : pos + 1 + len(text)] == text
                i_expect += 1 + len(text)
        assert i_expect == len(s)


def test_fuzz_validate_pair_never_throws_and_shape() -> None:
    """随机 src/zh 对恒不抛 + Issue/Report 字段形态合法。"""
    rng = fuzz_rng(20261001)
    for _ in range(2000):
        src = _soup(rng, _SOUP, 0, 14)
        zh = _soup(rng, _SOUP, 0, 14)
        rep = validate_pair(src, zh)
        assert rep.src_len == len(src)
        assert rep.zh_len == len(zh)
        assert rep.n_error + rep.n_warn == len(rep.issues)
        assert rep.ok == (rep.n_error == 0)
        for iss in rep.issues:
            assert iss.rule in _RULES, iss.rule
            assert iss.severity in (Severity.ERROR, Severity.WARN)
            assert iss.pos == -1 or 0 <= iss.pos < len(zh)
            assert iss.expected is None or isinstance(iss.expected, str)
            assert iss.found is None or isinstance(iss.found, str)
        json.dumps(rep.to_dict())
        grouped = rep.by_rule()
        assert set(grouped) == {i.rule for i in rep.issues}
        flat = [i for sub in grouped.values() for i in sub]
        assert Counter(map(id, rep.issues)) == Counter(map(id, flat))
        errs = [i.message for i in rep.issues if i.severity is Severity.ERROR]
        assert rep.feedback() == "\n".join(errs)
        rep2 = validate_pair(src, zh)
        assert rep2.issues == rep.issues  # 确定性


def test_fuzz_identity_pair_no_error() -> None:
    """``(x,x)`` 恒不产 error——译文不得比原文更坏的零基线。

    warn 只许两类继承信号：math 奇数 ``$``、length CJK 占比。
    E24 唯一例外：拉丁主导恒等对即「整段未翻译」——same_source error
    是新门的本意判（``zh==en`` 含 CJK 合法恒等不受影响）。
    """
    rng = fuzz_rng(20261002)
    fixed = [
        "[[COMMENT_1]]\n段落 [[MATH_1]]。",
        "段一 [[COMMENT_1]]\n段二。",
        "  [[COMMENT_1]] [[COMMENT_2]]\n文。",
        "[[BIBITEM_1]] 条目文本。",
        "成本 $5 美元。",
        "\\begin{a}x\\end{b}",
        "见 \\cite{a} 与 [[MATH_1]]。",
    ]
    cases = fixed + [_soup(rng, _SOUP_ID, 0, 16) for _ in range(1500)]
    for x in cases:
        rep = validate_pair(x, x)
        echo = _o_same_source_hit(x, x)
        assert rep.n_error == (1 if echo else 0), f"{x!r}\n{rep}"
        allowed = {"math", "length"} | ({"same_source"} if echo else set())
        assert {i.rule for i in rep.issues} <= allowed, f"{x!r}\n{rep}"


def test_identity_comment_ph_midline_tail_flagged() -> None:
    """钉档（非缺陷）：src 自带行中 ``[[COMMENT_n]]`` + 行尾文本时恒等对仍报。

    非锚定注释占位符的 zh 侧尾段是绝对判据（splice 后 ``%`` 吞到 EOL，
    同行文本恒死字节），不看 src 形状；真实 src 中注释占位符恒行尾，
    此形状只在合成输入出现。
    """
    rep = validate_pair("文字 [[COMMENT_1]] 文字", "文字 [[COMMENT_1]] 文字")
    assert any(i.rule == "placeholder" and "混入" in i.message for i in rep.issues)


def test_identity_bibitem_mixed_anchor_flagged() -> None:
    """钉档（同上证）：同一 ``[[BIBITEM_n]]`` 一处行首一处行中——锚定集按
    token 类型判、zh 逐出现查行前缀 → 恒等对也报脱位。真实 src 中 bibitem
    占位符恒行首且每枚 n 唯一，此形状只在合成输入出现。"""
    x = "[[BIBITEM_1]] 条目甲。\n中段 [[BIBITEM_1]] 文。"
    rep = validate_pair(x, x)
    assert any("行首" in i.message for i in rep.issues), str(rep)


# ================================================================== placeholder


def test_fuzz_placeholder_oracle() -> None:
    """占位符规则全量签名 oracle——missing/extra/typo/cmtfab/order/anchor 全等。"""
    rng = fuzz_rng(20261003)
    for _ in range(700):
        src = _soup(rng, _PH_SOUP, 0, 10)
        zh = _soup(rng, _PH_SOUP, 0, 10)
        rep = validate_pair(src, zh)
        assert Counter(_impl_ph_sigs(rep.issues)) == Counter(_o_ph_sigs(src, zh)), (
            f"src={src!r}\nzh={zh!r}\n{rep}"
        )


def test_fuzz_ph_missing_exact_multiset() -> None:
    """zh 只丢不添：缺失集合 == 丢失多重集，且无多余/拼错混入。"""
    rng = fuzz_rng(20261004)
    pool = [
        "[[MATH_1]]",
        "[[MATH_2]]",
        "[[CITE_1]]",
        "[[REF_3]]",
        "[[ENV_2]]",
        "[[SL]]",
    ]
    for _ in range(400):
        toks = [rng.choice(pool) for _ in range(rng.randint(1, 6))]
        kept = [t for t in toks if rng.random() > 0.35]  # noqa: PLR2004 -- 掉落概率
        src = "文" + "和".join(toks) + "。"
        zh = "文" + "和".join(kept) + "。"
        rep = validate_pair(src, zh)
        iss = [i for i in rep.issues if i.rule == "placeholder"]
        dropped = Counter(toks) - Counter(kept)
        assert Counter(i.expected for i in iss if "缺失" in i.message) == dropped, (
            f"{src!r} -> {zh!r}\n{rep}"
        )
        assert not [i for i in iss if "多余" in i.message or "拼错" in i.message]


def test_fuzz_ph_extra_strict_multiset() -> None:
    """zh 注入 src 不存在的严格形 token → 全部按多余报。"""
    rng = fuzz_rng(20261005)
    for _ in range(400):
        base = ["[[MATH_1]]", "[[MATH_2]]", "[[CITE_1]]"]
        extra = [f"[[NEW_{i}]]" for i in range(rng.randint(1, 4))]
        kept = rng.sample(base, rng.randint(0, 3))
        src = "文" + "和".join(kept) + "。"
        zh = "文" + "和".join(kept + extra) + "。"
        rep = validate_pair(src, zh)
        iss = [i for i in rep.issues if i.rule == "placeholder" and "多余" in i.message]
        assert Counter(i.found for i in iss) == Counter(extra), str(rep)


def test_fuzz_ph_typo_variants_pair() -> None:
    """同核心变体（小写/全角/缺括号/错号）lev≤2 配对成拼错而非缺失+多余。"""
    rng = fuzz_rng(20261006)
    pairs = [
        ("[[MATH_1]]", "[[math_1]]"),
        ("[[MATH_1]]", "【MATH_1】"),
        ("[[MATH_1]]", "[[MATH_1]"),
        ("[[MATH_12]]", "[[MATH_1]]"),
        ("[[CITE_3]]", "[[CIT_3]]"),
    ]
    for src_ph, zh_var in pairs:
        rep = validate_pair(f"见 {src_ph} 式。", f"见 {zh_var} 式。")
        typos = [i for i in rep.issues if "拼错" in i.message]
        assert typos, f"{src_ph} -> {zh_var}\n{rep}"
        assert typos[0].expected == src_ph
        assert typos[0].found == zh_var
    for _ in range(300):
        n = rng.randint(1, 99)
        rep = validate_pair(f"见 [[MATH_{n}]] 式。", f"见 [[MTH_{n}]] 式。")
        typos = [i for i in rep.issues if "拼错" in i.message]
        assert typos, str(rep)
        assert typos[0].expected == f"[[MATH_{n}]]", str(rep)


def test_src_literal_net_exemption() -> None:
    """``src_literal`` 净差口径：src 自带模糊形 verbatim 不计臆造。"""
    base_src = "结果见 [RS80] 与 [[MATH_1]]。"
    # 同数照搬 → 无 placeholder issue
    rep = validate_pair(base_src, base_src)
    assert not [i for i in rep.issues if i.rule == "placeholder"], str(rep)
    # zh 净多一枚模糊形 → 多余 error
    rep = validate_pair(base_src, "结果见 [RS80] [RS81] 与 [[MATH_1]]。")
    assert [i.found for i in rep.issues if "多余" in i.message] == ["[RS81]"]
    # zh 丢掉 src 字面 → 不算缺失（模糊形不进严格多重集）
    rep = validate_pair(base_src, "结果见 [[MATH_1]]。")
    assert not [i for i in rep.issues if i.rule == "placeholder"], str(rep)
    # zh 重复引用 src 字面 → 净多按多余计
    rep = validate_pair(base_src, "结果见 [RS80] 与 [RS80] 和 [[MATH_1]]。")
    assert [i.found for i in rep.issues if "多余" in i.message] == ["[RS80]"]
    # src 字面存在时 zh 的真臆造仍抓：【MATH_9】无 src 对应
    rep = validate_pair(base_src, "结果见 [RS80] 与 [[MATH_1]] 加【MATH_9】。")
    assert [i.found for i in rep.issues if "多余" in i.message] == ["【MATH_9】"]


@pytest.mark.parametrize("nbs", [0, 1, 2, 3, 4, 5])
def test_comment_backslash_parity_classification(nbs: int) -> None:
    r"""``%`` 前 ``\\`` run 奇偶分流：偶→注释区臆造 error；奇→正文多余 error。"""
    src = "见 [[MATH_1]] 文。"
    zh = "见 [[MATH_1]] 文。" + "\\" * nbs + "% [[MATH_9]]"
    rep = validate_pair(src, zh)
    iss = [i for i in rep.issues if i.rule == "placeholder"]
    if nbs % 2 == 0:
        assert any("臆造" in i.message for i in iss), str(rep)
        assert not any("多余" in i.message for i in iss)
    else:
        assert any("多余" in i.message for i in iss), str(rep)
        assert not any("臆造" in i.message for i in iss)


def test_fuzz_ph_anchor_metamorphic() -> None:
    """BIBITEM 行首锚定：脱位即 error；合法换行保行首不报。"""
    rng = fuzz_rng(20261007)
    for _ in range(300):
        ph = rng.choice(["[[BIBITEM_1]]", "[[BIBITEM_7]]"])
        src = f"{ph} 条目作者甲。"
        for zh, want_flag in [
            (f"{ph} 条目作者甲。", False),
            (f"作者甲 {ph} 条目。", True),
            (f"前文。\n{ph} 条目作者甲。", False),
            (f"前文。{ph}\n条目作者甲。", True),
        ]:
            rep = validate_pair(src, zh)
            has = any("行首" in i.message for i in rep.issues)
            assert has == want_flag, f"{zh!r}\n{rep}"


# ================================================================== 逐规则 oracle


def test_fuzz_brace_profile_oracle() -> None:
    rng = fuzz_rng(20261008)
    for _ in range(1500):
        s = _soup(rng, _STRUCT_SOUP, 0, 16)
        assert _brace_profile(s) == _o_brace_profile(s), repr(s)


def test_fuzz_math_profile_oracle() -> None:
    rng = fuzz_rng(20261009)
    for _ in range(1500):
        s = _soup(rng, _STRUCT_SOUP, 0, 16)
        assert _math_profile(s) == _o_math_profile(s), repr(s)


def test_fuzz_cs_names_oracle() -> None:
    rng = fuzz_rng(20261010)
    for _ in range(1500):
        s = _soup(rng, _STRUCT_SOUP, 0, 16)
        assert _cs_names(s) == _o_cs_names(s), repr(s)


def test_fuzz_key_multiset_oracle() -> None:
    rng = fuzz_rng(20261011)
    for _ in range(1500):
        s = _soup(rng, _KEY_SOUP, 0, 8)
        assert _key_multiset(s) == _o_key_multiset(s), repr(s)


def test_fuzz_env_signature_oracle() -> None:
    rng = fuzz_rng(20261012)
    for _ in range(1500):
        s = _soup(rng, _ENV_SOUP, 0, 10)
        assert _env_signature(s) == _o_env_signature(s), repr(s)


def test_fuzz_macro_classification_oracle() -> None:
    """macro 规则分类签名（nonascii/struct/new/fragile/dropped）与 oracle 全等。"""
    rng = fuzz_rng(20261013)
    for _ in range(800):
        src = _soup(rng, _STRUCT_SOUP, 0, 12)
        zh = _soup(rng, _STRUCT_SOUP, 0, 12)
        rep = validate_pair(src, zh)
        assert Counter(_impl_macro_sigs(rep.issues)) == Counter(
            _o_macro_sigs(src, zh)
        ), f"src={src!r}\nzh={zh!r}\n{rep}"


def test_fuzz_length_sig_oracle() -> None:
    """length 签名集 == oracle（E24：ratio 臂 token 代理 + error 档）。"""
    rng = fuzz_rng(20261014)
    words = ["word ", "text ", "中", "文", "[[MATH_1]]", "\\textbf{x}", "$x$", " "]
    for _ in range(800):
        src = _soup(rng, words, 0, 30)
        zh = _soup(rng, words, 0, 30)
        rep = validate_pair(src, zh)
        got: set[str] = set()
        for i in rep.issues:
            if i.rule != "length":
                continue
            if "长度比" in i.message:
                got.add("ratio")
            elif "CJK" in i.message:
                got.add("cjk")
        assert got == _o_length_sigs(src, zh), f"{src!r} -> {zh!r}\n{rep}"


def test_fuzz_item_glue_oracle() -> None:
    """``\\item``+大写尾粘合：净差非空 ↔ 恰好一条 warn 且 ×N 一致。"""
    rng = fuzz_rng(20261015)
    for _ in range(500):
        src = _soup(rng, _STRUCT_SOUP, 0, 10)
        zh = _soup(rng, _STRUCT_SOUP, 0, 10)
        rep = validate_pair(src, zh)
        iss = [i for i in rep.issues if i.rule == "item_glue"]
        scs, _ = _o_cs_names(src)
        zcs, _ = _o_cs_names(zh)

        def glued(cnt: Counter[str]) -> Counter[str]:
            return Counter(
                {
                    n: k
                    for n, k in cnt.items()
                    if n != "item"
                    and n.startswith("item")
                    and any(ch.isupper() for ch in n[4:])
                }
            )

        extra = glued(zcs) - glued(scs)
        assert bool(iss) == bool(extra), f"{src!r} -> {zh!r}\n{rep}"
        if iss:
            assert iss[0].severity is Severity.WARN
            assert f"×{sum(extra.values())}" in iss[0].message
            for nme in extra:
                assert f"\\{nme}" in iss[0].message


def test_fuzz_protocol_echo_oracle() -> None:
    """协议字面净差 → error，×N 与净差一致。"""
    rng = fuzz_rng(20261016)
    sigs = [
        "占位符缺失:",
        "[Original]",
        "[Translation]",
        "[Error]",
        "previous_validation_error",
        "slot_validation_failures",
        "[compile_error]",
    ]
    for _ in range(400):
        src = "文 [[MATH_1]]。" + rng.choice(sigs) * rng.randint(0, 2)
        zh = "文 [[MATH_1]]。" + "".join(
            rng.choice(sigs) for _ in range(rng.randint(0, 3))
        )
        rep = validate_pair(src, zh)
        got = {i.found: i for i in rep.issues if i.rule == "protocol_echo"}
        for sig in sigs:
            diff = zh.count(sig) - src.count(sig)
            if diff > 0:
                assert sig in got, f"{sig}: {src!r} -> {zh!r}\n{rep}"
                assert f"×{diff}" in got[sig].message
                assert got[sig].severity is Severity.ERROR
            else:
                assert sig not in got


def test_fuzz_bare_cs_ph_in_cs_existence() -> None:
    """bare_cs/ph_in_cs issue 存在性 == textutil 净差谓词；子类拆分一致。"""
    rng = fuzz_rng(20261017)
    for _ in range(600):
        src = _soup(rng, _STRUCT_SOUP, 0, 10)
        zh = _soup(rng, _STRUCT_SOUP, 0, 10)
        rep = validate_pair(src, zh)
        bnet = bare_cs_net(src, zh)
        b_iss = [i for i in rep.issues if i.rule == "bare_cs"]
        assert bool(b_iss) == bool(bnet), f"{src!r} -> {zh!r}\n{rep}"
        if b_iss:
            assert all(i.severity is Severity.ERROR for i in b_iss)
        pnet = ph_in_cs_net(src, zh)
        p_iss = [i for i in rep.issues if i.rule == "ph_in_cs"]
        assert bool(p_iss) == bool(pnet), f"{src!r} -> {zh!r}\n{rep}"
        if p_iss:
            assert len(p_iss) == 1
            assert f"×{sum(pnet.values())}" in p_iss[0].message


# ================================================================== key 规则


def test_fuzz_key_family_drop_detected() -> None:
    """族内命令丢 key → error 且 expected 指名；幻觉新增 → warn。"""
    rng = fuzz_rng(20261018)
    names = [
        "cite",
        "parencite",
        "footcite",
        "nocite",
        "mcite",
        "textcite",
        "autocite",
        "smartcite",
        "citeauthor",
        "citeyear",
        "ref",
        "eqref",
        "pageref",
        "autoref",
        "cref",
        "Cref",
        "vref",
        "label",
        "bibitem",
        "bibliography",
        "bibliographystyle",
        "mybibliography",
        "addbibresource",
        "addsectionbib",
        "refrange",
        "crefrange",
        "cpagerefrange",
    ]
    for _ in range(500):
        name = rng.choice(names)
        key = f"k{rng.randint(0, 999)}"
        rep = validate_pair(f"见 \\{name}{{{key}}} 文。", "见文。")
        iss = [
            i for i in rep.issues if i.rule == "key" and i.severity is Severity.ERROR
        ]
        assert any(i.expected == key for i in iss), f"\\{name}\n{rep}"
        rep2 = validate_pair("见文。", f"见 \\{name}{{{key}}} 文。")
        iss2 = [
            i for i in rep2.issues if i.rule == "key" and i.severity is Severity.WARN
        ]
        assert any(i.found == key for i in iss2), f"\\{name}\n{rep2}"


def test_fuzz_key_comma_list_partial_drop() -> None:
    """逗号 key 表部分丢失：缺失多重集精确。"""
    rng = fuzz_rng(20261019)
    for _ in range(300):
        keys = rng.sample(["a", "b", "c", "d", "e"], rng.randint(2, 5))
        kept = [k for k in keys if rng.random() > 0.4]  # noqa: PLR2004 -- 掉落概率
        src = f"见 \\cite{{{','.join(keys)}}} 文。"
        zh = f"见 \\cite{{{','.join(kept)}}} 文。"
        rep = validate_pair(src, zh)
        iss = [
            i for i in rep.issues if i.rule == "key" and i.severity is Severity.ERROR
        ]
        want = Counter(keys) - Counter(kept)
        got: Counter[str] = Counter()
        for i in iss:
            m = re.search(r"'([^']+)' ×(\d+)", i.message)
            if m:
                got[m.group(1)] += int(m.group(2))
        assert got == want, f"{src!r} -> {zh!r}\n{rep}"


@pytest.mark.parametrize(
    ("src", "zh", "lost_key"),
    [
        ("见 \\Cite{vaswani2017} 所述。", "见所述。", "vaswani2017"),
        ("见 \\Citet{kingma2015} 所述。", "见所述。", "kingma2015"),
        ("见 \\parenCite{ho2020} 所述。", "见所述。", "ho2020"),
        ("见 \\zlabel{sec:x} 所述。", "见所述。", "sec:x"),
        ("书 \\addglobalbib{refs.bib} 文。", "书文。", "refs.bib"),
        ("见 \\cites{a1}{b2} 所述。", "见 \\cites{a1} 所述。", "b2"),
    ],
    ids=["Cite", "Citet", "parenCite", "zlabel", "addglobalbib", "cites-2nd"],
)
def test_key_gap_family(src: str, zh: str, lost_key: str) -> None:
    rep = validate_pair(src, zh)
    iss = [i for i in rep.issues if i.rule == "key" and i.severity is Severity.ERROR]
    assert any(i.expected == lost_key for i in iss), str(rep)


def test_ph_pairing_maximum_matching() -> None:
    """lev≤2 配对是最大匹配而非逐缺失贪心：``AAAA`` 让位 ``CCAA``（d=2）、
    ``AABB`` 配对 ``AAAB``（d=1）——两枚拼错修复建议，无缺报/多报。"""
    rep = validate_pair("见 [[AAAA]] 与 [[AABB]] 结。", "见 [[AAAB]] 与 [[CCAA]] 结。")
    iss = [i for i in rep.issues if i.rule == "placeholder"]
    assert len(iss) == 2, str(rep)  # noqa: PLR2004 -- 两枚拼错修复建议是断言目标
    assert all("拼错" in i.message for i in iss), str(rep)


# ================================================================== l1 通道


def test_fuzz_ts_baseline_roundtrip() -> None:
    """TsBaseline dict round-trip：随机整数字段（含负/巨）恒等。"""
    rng = fuzz_rng(20261020)
    for _ in range(300):
        b = TsBaseline(
            parse_errors=rng.randint(-100, 10**9),
            env_mismatches=rng.randint(-100, 10**9),
            unclosed_math=rng.randint(-100, 10**9),
            brace_balance=rng.randint(-100, 10**9),
        )
        assert TsBaseline.from_dict(b.to_dict()) == b
    assert TsBaseline.from_dict({}) == TsBaseline()
    got = TsBaseline.from_dict({"parse_errors": "7"})
    assert got.parse_errors == 7  # noqa: PLR2004 -- 字符串数字经 int() 强转


def test_fuzz_ts_result_from_dict_verdict() -> None:
    """TsResult.from_dict 合法 schema 任意值 → 字段保真 + verdict_ok 契约。"""
    rng = fuzz_rng(20261021)
    for _ in range(400):
        d: dict[str, Any] = {
            "id": rng.choice([None, "x", "c1", 7]),
            "ok": rng.choice([True, False, 1, 0, "yes", ""]),
            "ok_relative": rng.choice([None, True, False]),
            "parse_errors": [{"row": j} for j in range(rng.randint(0, 3))],
            "env_mismatches": [{"env": "a"} for _ in range(rng.randint(0, 2))],
            "unclosed_math": rng.randint(0, 50),
            "brace_balance": rng.randint(-50, 50),
            "placeholders": {"missing": [f"M{i}" for i in range(rng.randint(0, 3))]},
            "parse_ms": rng.random() * 100,
            "error": rng.choice([None, "boom"]),
        }
        r = TsResult.from_dict(d)
        assert r.id == d["id"]
        assert r.ok == bool(d["ok"])
        want = d["ok_relative"] if d["ok_relative"] is not None else bool(d["ok"])
        assert r.verdict_ok == want
        assert len(r.parse_errors) == len(d["parse_errors"])


class _FakeStdin:
    """常驻 worker stdin 假桩——write 时把预设响应行喂回队列。"""

    def __init__(self, v: TsValidator, replies: list[str | None]) -> None:
        self._v = v
        self._replies = replies
        self.writes: list[str] = []

    def write(self, s: str) -> int:
        self.writes.append(s)
        for r in self._replies:
            self._v._lines.put(r)  # noqa: SLF001 -- 假桩模拟泵线程回灌
        return len(s)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeProc:
    """假常驻进程：poll/wait/kill 可定生死，stdin 回灌预设行。"""

    def __init__(
        self, v: TsValidator, replies: list[str | None], *, alive: bool = True
    ) -> None:
        self.stdin = _FakeStdin(v, replies)
        self._rc = None if alive else 1

    def poll(self) -> int | None:
        return self._rc

    def wait(self, timeout: float = 0) -> int:  # noqa: ARG002 -- Popen.wait 签名对齐
        return self._rc or 0

    def kill(self) -> None:
        pass


def _inject(v: TsValidator, replies: list[str | None]) -> _FakeProc:
    proc = _FakeProc(v, replies)
    v._proc = proc  # noqa: SLF001 -- 注入假常驻通道是测试目的
    return proc


def test_fuzz_one_id_pairing() -> None:
    """``_one`` 按 id 配对：乱序/迟到/重复行中首个配对者胜。"""
    rng = fuzz_rng(20261022)
    for _ in range(300):
        want = f"c{rng.randint(0, 3)}"
        noise = [
            json.dumps({"id": f"o{j}", "ok": j % 2 == 0}) + "\n"
            for j in range(rng.randint(0, 4))
        ]
        target = json.dumps({"id": want, "ok": True, "unclosed_math": 2}) + "\n"
        dup = json.dumps({"id": want, "ok": False}) + "\n"
        rng.shuffle(noise)  # 前缀噪声自身乱序（target 恒在 noise 后）
        v = TsValidator(timeout=5)
        _inject(v, [*noise, target, dup])
        res = v._one({"id": want, "tex": "x"})  # noqa: SLF001 -- 测私有通道
        assert res.id == want
        assert res.ok
        assert res.unclosed_math == 2  # noqa: PLR2004 -- 注入的回复字段原样回读


def test_one_eof_before_match_fails() -> None:
    """EOF 哨兵先于配对行到达 → L1Error 且通道关闭。"""
    v = TsValidator(timeout=5)
    _inject(v, ['{"id":"o","ok":true}\n', None, '{"id":"x","ok":true}\n'])
    with pytest.raises(L1Error, match="EOF"):
        v._one({"id": "x", "tex": "t"})  # noqa: SLF001
    assert v._proc is None  # noqa: SLF001


def test_one_non_json_line_fails() -> None:
    """配对前遇非 JSON 行 → L1Error（不跳过）。"""
    v = TsValidator(timeout=5)
    _inject(v, ["not json\n", '{"id":"x","ok":true}\n'])
    with pytest.raises(L1Error, match="非 JSON"):
        v._one({"id": "x", "tex": "t"})  # noqa: SLF001


@pytest.mark.parametrize(
    "line",
    [
        '{"id":"x","parse_errors":5}',
        '{"id":"x","unclosed_math":"abc"}',
        "[1,2,3]",
        '"just a string"',
    ],
    ids=["int-field", "str-int-field", "toplevel-list", "toplevel-str"],
)
def test_one_schema_violation_l1error(line: str) -> None:
    """通道 schema 违例 → ``L1Error``（协议错误统一异常契约，不泄内建异常）。"""
    v = TsValidator(timeout=5)
    _inject(v, [line + "\n"])
    with pytest.raises(L1Error):
        v._one({"id": "x", "tex": "t"})  # noqa: SLF001


def _batch_validator(tmp_path: Path) -> TsValidator:
    (tmp_path / "validator.js").write_text("// stub\n", encoding="utf-8")
    return TsValidator(node="/bin/true", worker_dir=tmp_path)


def test_validate_batch_channel_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """批处理通道故障面：非零退出/行数不符/非 JSON/spawn 异常 → L1Error。"""
    v = _batch_validator(tmp_path)
    recs = [{"id": "a", "tex": "x"}, {"id": "b", "tex": "y"}]
    good = "".join(f'{{"id":"{r["id"]}","ok":true}}\n' for r in recs)

    def fake_run(ret: int = 0, out: str = "") -> Callable[..., SimpleNamespace]:
        def _run(*_a: object, **_k: object) -> SimpleNamespace:
            return SimpleNamespace(returncode=ret, stdout=out, stderr="err tail")

        return _run

    monkeypatch.setattr(subprocess, "run", fake_run(0, good))
    res = v.validate_batch(recs)
    assert [r.id for r in res] == ["a", "b"]
    assert all(r.ok for r in res)

    monkeypatch.setattr(subprocess, "run", fake_run(3, ""))
    with pytest.raises(L1Error, match="退出码"):
        v.validate_batch(recs)

    monkeypatch.setattr(subprocess, "run", fake_run(0, '{"id":"a"}\n'))
    with pytest.raises(L1Error, match="响应数"):
        v.validate_batch(recs)

    monkeypatch.setattr(subprocess, "run", fake_run(0, "garbage\nmore\n"))
    with pytest.raises(L1Error, match="非 JSON"):
        v.validate_batch(recs)

    def boom(*_a: object, **_k: object) -> None:
        msg = "spawn fail"
        raise OSError(msg)

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(L1Error, match="spawn"):
        v.validate_batch(recs)

    def hang(*_a: object, **_k: object) -> None:
        raise subprocess.TimeoutExpired(cmd="node", timeout=1)

    monkeypatch.setattr(subprocess, "run", hang)
    with pytest.raises(L1Error, match="spawn"):
        v.validate_batch(recs)


def test_batch_schema_violation_l1error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """批处理通道 schema 违例 → ``L1Error``（同 _one 通道契约）。"""
    v = _batch_validator(tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(
            returncode=0, stdout='{"id":"x","parse_errors":5}\n', stderr=""
        ),
    )
    with pytest.raises(L1Error):
        v.validate_batch([{"id": "x", "tex": "t"}])


def test_available_three_factor_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``available()`` = node 在场 × worker.js × 双 npm 依赖——全组合矩阵。"""
    monkeypatch.delenv("TEXLATE_NODE", raising=False)
    monkeypatch.delenv("TEXLATE_TS_WORKER", raising=False)
    monkeypatch.delenv("TEXLATE_TS_NODE_PATH", raising=False)
    node_on = {"v": True}
    monkeypatch.setattr(
        shutil, "which", lambda _c: "/usr/bin/node" if node_on["v"] else None
    )
    combos = 0
    for has_node in (False, True):
        for has_worker in (False, True):
            for dep_ts in (False, True):
                for dep_grammar in (False, True):
                    wdir = tmp_path / f"w{combos}"
                    ndir = tmp_path / f"n{combos}"
                    combos += 1
                    wdir.mkdir()
                    ndir.mkdir()
                    if has_worker:
                        (wdir / "validator.js").write_text("//\n")
                    if dep_ts:
                        (ndir / "tree-sitter").mkdir()
                    if dep_grammar:
                        (ndir / "@pfoerster" / "tree-sitter-latex").mkdir(parents=True)
                    node_on["v"] = has_node
                    v = TsValidator(worker_dir=wdir, node_path=ndir)
                    want = bool(has_node and has_worker and dep_ts and dep_grammar)
                    assert v.available() is want, (
                        has_node,
                        has_worker,
                        dep_ts,
                        dep_grammar,
                    )


def test_env_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """构造参数 > ``TEXLATE_*`` env > 默认/PATH。"""
    monkeypatch.setenv("TEXLATE_NODE", "/env/node")
    monkeypatch.setenv("TEXLATE_TS_WORKER", str(tmp_path / "w"))
    monkeypatch.setenv("TEXLATE_TS_NODE_PATH", str(tmp_path / "nm"))
    v = TsValidator()
    assert v._node == "/env/node"  # noqa: SLF001
    assert v._worker_dir == tmp_path / "w"  # noqa: SLF001
    assert v._node_path == tmp_path / "nm"  # noqa: SLF001
    v2 = TsValidator(
        node="/arg/node", worker_dir=tmp_path / "w2", node_path=tmp_path / "nm2"
    )
    assert v2._node == "/arg/node"  # noqa: SLF001
    assert v2._worker_dir == tmp_path / "w2"  # noqa: SLF001
    assert v2._node_path == tmp_path / "nm2"  # noqa: SLF001
    monkeypatch.delenv("TEXLATE_TS_NODE_PATH")
    v3 = TsValidator(worker_dir=tmp_path / "w3")
    assert v3._node_path == tmp_path / "w3" / "node_modules"  # noqa: SLF001


def test_pump_always_sends_sentinel() -> None:
    """``_pump`` 把 stdout 行全部转投队列后恒补 ``None`` 哨兵。"""
    q: queue.Queue[str | None] = queue.Queue()
    TsValidator._pump(  # noqa: SLF001 -- 直调泵函数
        SimpleNamespace(stdout=iter(["a\n", "b\n"])),  # type: ignore[arg-type]
        q,
    )
    assert [q.get(), q.get(), q.get()] == ["a\n", "b\n", None]
    q2: queue.Queue[str | None] = queue.Queue()
    TsValidator._pump(  # noqa: SLF001
        SimpleNamespace(stdout=iter([])),  # type: ignore[arg-type]
        q2,
    )
    assert q2.get_nowait() is None


def test_open_idempotent_and_close() -> None:
    """open 已有通道不重开；close 幂等且清 ``_proc``。"""
    v = TsValidator()
    fake = _inject(v, [])
    v.open()
    assert v._proc is fake  # noqa: SLF001
    v.close()
    assert v._proc is None  # noqa: SLF001
    v.close()
    assert v._proc is None  # noqa: SLF001


def test_drain_lines_clears_stale() -> None:
    v = TsValidator()
    v._lines.put("stale1\n")  # noqa: SLF001
    v._lines.put(None)  # noqa: SLF001
    v._lines.put("stale2\n")  # noqa: SLF001
    v._drain_lines()  # noqa: SLF001
    assert v._lines.empty()  # noqa: SLF001


def test_one_dead_proc_falls_back_but_none_left() -> None:
    """``_proc.stdin is None`` 分支：进程壳无 stdin → 批处理降级。"""
    v = TsValidator()
    v._proc = SimpleNamespace(stdin=None, poll=lambda: None)  # noqa: SLF001
    sentinel = TsResult(id="x", ok=True)
    v.validate_batch = lambda _recs: [sentinel]  # 实例覆写降级通道
    assert v._one({"id": "x", "tex": "t"}) is sentinel  # noqa: SLF001


def test_sign_and_validate_record_shaping() -> None:
    """sign/validate 请求记录成形：id/tex/expect/baseline 键位。"""
    v = TsValidator()
    seen: list[dict[str, Any]] = []
    v._one = lambda rec: (seen.append(rec), TsResult(ok=True))[1]  # noqa: SLF001
    base = v.sign("TEX", doc_id="d1")
    assert seen[-1] == {"id": "d1", "tex": "TEX"}
    assert base == TsBaseline()
    v.validate(
        "ZH",
        baseline=TsBaseline(1, 2, 3, -4),
        expect=["MATH_1"],
        doc_id="c9",
    )
    assert seen[-1]["baseline"] == {
        "parse_errors": 1,
        "env_mismatches": 2,
        "unclosed_math": 3,
        "brace_balance": -4,
    }
    assert seen[-1]["expect"] == ["MATH_1"]
    assert seen[-1]["id"] == "c9"
    v.validate("ZH2")
    assert seen[-1] == {"id": "chunk", "tex": "ZH2"}


def test_sign_error_raises() -> None:
    v = TsValidator()
    v._one = lambda _rec: TsResult(error="sign boom")  # noqa: SLF001
    with pytest.raises(L1Error, match="sign"):
        v.sign("x")


# ================================================================ 波 2：L2/report 面
#
# 首波（上）打 l0 规则 + l1 传输层；本波补 ``l2.parse_log_text``/``parse_log``
# 与 ``report.aggregate`` 的零覆盖面 + l1 schema 契约残余（``from_dict``
# 只兜 coercion 异常、深层类型违例静默穿透）。对拍 oracle 全部独立实现：
# fileline 用 ``split(":")``、warning 归类用子串/字符步进、nullfont 限界窗
# 手写状态机——不抄 l2/redlines 的 regex。

_LOGS_DIR = Path(__file__).resolve().parent / "fixtures" / "logs"

#: log 行 soup——引擎签名/文件栈括号/双格式错误/l.NNN/九类 warning 形态/
#: 边界形（空 msg、长扩展名、==> 复述、unicode 引擎名）混合。
_LOG_SOUP = [
    "This is XeTeX, Version 3.141592653 (TeX Live 2026)",
    "This is pdfTeX, Version 3.14159265",
    "This is 中文引擎, Version 9",
    "This is",
    "**main.tex",
    "(./main.tex",
    "(./sub/chap.tex",
    "(/usr/share/texmf-dist/tex/latex/base/article.cls",
    "(fig1.eps",
    "(fig,2.eps",
    "(draft",
    "(v2.0",
    "(52.00102pt",
    ")",
    ")))",
    "(a)(b.tex)",
    "text (paren) tail",
    "! Undefined control sequence.",
    "!",
    "! Missing character: There is no x in font y",
    "! File ended while scanning use of \\foo.",
    "! Emergency stop.",
    "!  ==> Fatal error occurred, no output PDF file produced!",
    "./main.tex:44: Undefined control sequence.",
    "./sub.tex:12: Missing $ inserted.",
    "x.tex:5: msg",
    "x.abcdefghijk:5: msg",  # 11 字符扩展名——超 {1,10} 不收
    "x.tex:5: ",  # 空 msg 不收
    "x.tex:5:==> x",  # `: ` 单空格硬约定不收
    "./fig/diag.pdf_t:7: Undefined control sequence.",
    "./main.bib:1: LaTeX Error: Missing \\begin{document}.",
    "./colt2020.cls:5:  ==> Fatal error occurred, no output PDF file produced!",
    "./x.tex:9: ==> Fatal error occurred, no output PDF file produced!",
    "./x.tex:12: LaTeX Warning: Reference `r' undefined on input line 12.",
    "./x.tex:3: Package foo Warning: bar",
    "l.44 \\foo{bar}",
    "l.5 \\x",
    "l.",
    "l.0",
    "LaTeX Warning: Citation `a' on page 1 undefined on input line 3.",
    "LaTeX Warning: Reference `r' undefined on input line 9.",
    "LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.",
    "LaTeX Warning: There were undefined references.",
    "LaTeX Warning: There were multiply-defined labels.",
    "Package hyperref Warning: Token not allowed",
    "Foo Warning: bar",
    "warning: lowercase bare",
    "random words Warning: mid-line",
    "Missing character: There is no 中 (U+4E2D) in font cmr10!",
    'Missing character: There is no ; ("3B) in font cmr10!',
    "Missing character: There is no (U+FFFD) in font cmr10!",
    'Missing character: There is no ("FFFD) in font cmr10!',
    "Missing character: There is no x (U+8FD9) in font nullfont!",
    "Missing character: There is no x",  # 无 in font——join 续行探测面
    "in font nullfont",
    "in font cmr10!",
    "Missing character: There is no y in font nullfont",
    "Invalid UTF-8 byte or sequence at line 11 replaced by U+FFFD.",
    "invalid utf-8 byte 9F at line 3",
    "Overfull \\hbox (12.0pt too wide) in paragraph at lines 1--2",
    "Underfull \\vbox (badness 10000) detected at line 7",
    "LaTeX Font Warning: Font shape `TU/ptm/m/n' undefined",
    "Some font shapes were substituted silently",
    "Package pdftex.def Warning: File `fig.pdf' not found on input line 9.",
    "LaTeX Warning: File `x.png' not found on input line 5.",
    "LaTeX Warning: cannot open file `data.dat' for reading.",
    "Package hyperref Warning: Could not locate file `x.out'.",
    "Could not locate file `x.out'.",  # 无 Warning: 标记——预筛不收
    "kpathsea: cannot open file for reading",
    "cannot find image x",
    "Package rerunfilecheck Info: File `x.out' has not changed.",
    "LaTeX Font Info:    Checking defaults",
    "",
    " ",
    "plain text line",
    "Output written on main.pdf (1 page).",
    "No pages of output.",
    "*** (cannot \\read from terminal in nonstop modes)",
    "<read *>",
    "\x00 nul line",
    "tab\there",
    "trailing space ",
    "ｆｕｌｌｗｉｄｔｈ",
    "entering extended mode",
    " %&-line parsing enabled.",
    "?",
    "Type X to quit or <RETURN> to proceed,",
    "Enter file name: ",
    "./x.tex:1: File ended while scanning use of \\foo.",
    "x.tex:٥: unicode digit line no",
]

_MISSCHAR_MARK = "missing character:"


def _o_fileline(ln: str) -> tuple[str, str, str] | None:
    """fileline 形独立解析（split 口径）；非错误形态行返回 ``(fname, lnum, msg)``。"""
    parts = ln.split(":", 2)
    if len(parts) < 3:  # noqa: PLR2004 -- split(":",2) 三段形
        return None
    fname, lnum, rest = parts
    if (
        not fname
        or re.search(r"[()\s]", fname)
        or not lnum.isdecimal()
        or not re.match(r" \S", rest)
    ):
        return None
    dot = fname.rfind(".")
    if dot <= 0 or not re.fullmatch(r"[A-Za-z0-9_-]{1,10}", fname[dot + 1 :]):
        return None
    return fname, lnum, rest[1:]


def _o_nonerr(msg: str) -> bool:
    """fileline 消息面非错误豁免：Warning 前缀行 / ``==>`` 复述行。"""
    if msg.startswith("==>"):
        return True
    return bool(
        re.match(r"(?:LaTeX|Package|Class)\b", msg) and re.search(r"\bWarning\b", msg)
    )


def _o_errs(lines: list[str]) -> list[tuple[int, str | None, int | None]]:
    """独立错误行扫描：``(行idx, tex_file, tex_line直取)``——bang 行 tex 位 None。"""
    out: list[tuple[int, str | None, int | None]] = []
    for i, ln in enumerate(lines):
        if ln.startswith("!"):
            out.append((i, None, None))
            continue
        fl = _o_fileline(ln)
        if fl is not None and not _o_nonerr(fl[2]):
            out.append((i, fl[0], int(fl[1])))
    return out


def _o_is_err(ln: str) -> bool:
    """独立错误行谓词：``!`` 行或非豁免 ``file:line:`` 行。"""
    if ln.startswith("!"):
        return True
    fl = _o_fileline(ln)
    return fl is not None and not _o_nonerr(fl[2])


def _o_err_ctx(lines: list[str], i: int) -> list[str]:
    """错误行 ctx 期望切片——截断于下一错误行（D5 修复口径）。"""
    out: list[str] = []
    for cln in lines[i + 1 : i + 9]:
        if _o_is_err(cln):
            break
        out.append(cln)
    return out


def _o_lnum_ctx(lines: list[str], i: int) -> int | None:
    """ctx 窗口内首个 ``l.NNN``（窗口即 ``_o_err_ctx`` 截断面）。"""
    for ln in _o_err_ctx(lines, i):
        m = re.match(r"l\.(\d+)", ln.strip())
        if m:
            return int(m.group(1))
    return None


def _o_file_btq(low: str) -> bool:
    """``File `x' not found`` 子串谓词——逐次 ``file ` `` 出现位扫描。"""
    pos = 0
    while True:
        i = low.find("file `", pos)
        if i < 0:
            return False
        j = low.find("'", i + 6)
        if j < 0:
            return False
        if j > i + 6 and low[j + 1 : j + 11] == " not found":
            return True
        pos = i + 1


def _o_warnish(ln: str) -> bool:
    """warning 预筛独立实现：``warning:`` 裸串或五类无标记硬 warning。"""
    low = ln.lower()
    return (
        "warning:" in low
        or _MISSCHAR_MARK in low
        or "invalid utf-8 byte" in low
        or "overfull \\hbox" in low
        or "overfull \\vbox" in low
        or "underfull \\hbox" in low
        or "underfull \\vbox" in low
        or _o_file_btq(low)
        or "cannot find" in low
        or "cannot open" in low
    )


def _o_nullfont(low: str) -> bool:
    """nullfont 限界窗状态机：任一 ``missing character:`` 后 ≤90 字符、
    至多跨一个 ``\\n`` 内出现 ``in font nullfont`` 边界即中。"""
    start = 0
    while True:
        i = low.find(_MISSCHAR_MARK, start)
        if i < 0:
            return False
        p = i + len(_MISSCHAR_MARK)
        nl = False
        seg = 0
        while p < len(low):
            if low.startswith("in font ", p):
                if low.startswith("in font nullfont", p):
                    return True
                break
            if low.startswith("missing character", p):
                break
            c = low[p]
            if c == "\n":
                if nl:
                    break
                nl = True
                seg = 0
            else:
                seg += 1
                if seg > 90:  # noqa: PLR2004 -- 窗口上限即实现 {0,90} 语义
                    break
            p += 1
        start = i + 1


def _o_glyph_cp(line: str) -> int | None:
    """``("HEX)``/``(U+HEX)`` 码点独立解析（4-6 位、大小写敏感字面锚）。"""
    anchor = "Missing character: There is no "
    start = 0
    while True:
        i = line.find(anchor, start)
        if i < 0:
            return None
        rest0 = line[i + len(anchor) :]
        cands = []
        sp = rest0.find(" ")
        tok = rest0[:sp] if sp > 0 else ""
        if tok and not any(c.isspace() for c in tok):
            cands.append(rest0[sp + 1 :])  # \S+ token 先行（regex 贪婪序）
        cands.append(rest0)
        for rest in cands:
            hexpart = (
                rest[2:]
                if rest.startswith('("')
                else rest[3:]
                if rest.startswith("(U+")
                else ""
            )
            if not hexpart:
                continue
            digits = []
            for c in hexpart:
                if c in "0123456789abcdefABCDEF":
                    digits.append(c)
                else:
                    break
            hexs = "".join(digits)
            n_dig = len(hexs)
            if not 4 <= n_dig <= 6 or hexpart[n_dig] != ")":  # noqa: PLR2004 -- {4,6} hex 窗即实现语义
                continue
            return int(hexs, 16)
        start = i + 1


def _o_cls(probe_low: str) -> str:  # noqa: PLR0911 -- 规则序即早退序，拍平伤读
    """warning 归类独立实现——规则序同实现，判据全部子串/字符级。"""
    low = probe_low
    if "invalid utf-8 byte" in low or "replaced by u+fffd" in low:
        return "invalid_utf8"
    if _o_nullfont(low):
        return "missing_glyph_nullfont"
    if _MISSCHAR_MARK in low:
        return "missing_glyph"
    if re.search(r"citation[^\n]*undefined", low) or "undefined citations" in low:
        return "citation"
    if (
        re.search(
            r"(?:reference|label|citation)[^\n]*(?:multiply[- ]defined|undefined)",
            low,
        )
        or "undefined references" in low
        or "multiply defined" in low
        or "multiply-defined" in low
    ):
        return "reference"
    if re.search(r"\brerun\b", low) or "may have changed" in low:
        return "rerun"
    if re.search(r"font shape[^\n]*undefined", low) or "some font shapes" in low:
        return "font_subst"
    if (
        _o_file_btq(low)
        or "cannot find" in low
        or "cannot open" in low
        or "could not locate" in low
    ):
        return "file_not_found"
    if (
        "overfull \\hbox" in low
        or "overfull \\vbox" in low
        or "underfull \\hbox" in low
        or "underfull \\vbox" in low
    ):
        return "overfull"
    return "generic"


def _o_warn_counts(
    lines: list[str], err_idx: set[int]
) -> tuple[int, dict[str, int], int]:
    """``(total, by_class, cjk_missing)`` 独立预测——错误行不参与归类。"""
    by_class: dict[str, int] = {}
    total = cjk = 0
    for i, ln in enumerate(lines):
        if i in err_idx or not _o_warnish(ln):
            continue
        nxt = (
            lines[i + 1]
            if "Missing character:" in ln
            and "in font " not in ln
            and i + 1 < len(lines)
            and "in font" in lines[i + 1]
            and not _o_warnish(lines[i + 1])  # 独立 warning 行不拼（D4 修复口径）
            else ""
        )
        probe = (ln + "\n" + nxt).lower() if nxt else ln.lower()
        cls = _o_cls(probe)
        if cls == "missing_glyph":
            cp = _o_glyph_cp(ln)
            if cp == 0xFFFD:  # noqa: PLR2004 -- U+FFFD 码点字面量
                cls = "fffd_glyph"
            elif cp is not None and is_cjk_cp(cp):
                cls = "missing_glyph_cjk"
                cjk += 1
        total += 1
        by_class[cls] = by_class.get(cls, 0) + 1
    return total, by_class, cjk


def _check_l2(text: str) -> L2Verdict:
    """l2 全量对拍：oracle 等值 + 结构不变量 + 序列化/确定性。"""
    assert_deterministic(lambda: parse_log_text(text).to_dict())
    v = parse_log_text(text)
    lines = text.splitlines()

    # —— 引擎签名：仅首行 ``This is (\w+)`` ——
    m = re.match(r"This is (\w+)", lines[0]) if lines else None
    assert v.engine == (m.group(1) if m else None), short(text)

    # —— 错误面 ——
    oerrs = _o_errs(lines)
    assert v.n_errors == len(oerrs), short(text)
    assert v.ok == (v.n_errors == 0)
    assert len(v.errors) == min(len(oerrs), 200), short(text)
    assert (v.first_error is None) == (v.n_errors == 0)
    if v.errors:
        assert v.first_error is v.errors[0]
    for e, (i, ofile, oline) in zip(
        v.errors, oerrs, strict=False
    ):  # 长度已钉 min(oerrs,200)
        assert e.line_no == i + 1
        assert e.head == lines[i].strip()
        assert e.tex_file == ofile
        assert e.tex_line == (oline if oline is not None else _o_lnum_ctx(lines, i)), (
            short(text)
        )
        assert len(e.ctx) <= 8  # noqa: PLR2004 -- CTX_LINES 窗口上限
        assert e.ctx == tuple(_o_err_ctx(lines, i))
        assert all(isinstance(s, str) and s for s in e.file_stack)
        if e.eof_file is not None:
            assert "File ended while scanning" in e.head

    # —— warning 面 ——
    ws = v.warnings
    o_total, o_by_class, o_cjk = _o_warn_counts(lines, {i for i, _, _ in oerrs})
    assert ws.total == o_total, short(text)
    assert ws.by_class == o_by_class, short(text)
    assert ws.cjk_missing == o_cjk, short(text)
    assert set(ws.samples) == set(ws.hits) == set(ws.by_class)
    for cls, cnt in ws.by_class.items():
        assert len(ws.samples[cls]) == min(cnt, 5) == len(ws.hits[cls])
        for h in ws.hits[cls]:
            assert set(h) == {"file", "line", "head", "log_line"}
            assert h["line"] is None
            assert isinstance(h["log_line"], int)
            assert h["head"] == lines[int(h["log_line"]) - 1].strip()
    assert len(ws.redlines) == len(set(ws.redlines))  # 去重
    for r in ws.redlines:
        cls, sep, head = r.partition(": ")
        assert sep
        assert cls in L2_REDLINE_CLASSES
        assert len(head) <= 120  # noqa: PLR2004 -- 截断上限
    assert all(s.startswith("invalid_utf8@") for s in ws.sys_hits)
    assert len(ws.sys_hits) == len(set(ws.sys_hits))

    # —— tail/序列化 ——
    assert v.tail == tuple(lines[-30:])
    json.dumps(v.to_dict())
    ad = v.attribution_dict()
    json.dumps(ad)
    assert ad["n_errors"] == v.n_errors
    assert ad["warn_by_class"] == ws.by_class
    hits = ad["hits"]
    assert [h["log_line"] for h in hits] == sorted(h["log_line"] for h in hits)
    assert sum(1 for h in hits if h["kind"] == "error") <= 50  # noqa: PLR2004
    return v


def test_l2_soup_oracle() -> None:
    """soup log 全量对拍：错误计数/归类/码点细分/归一化全部独立预测。"""
    rng = fuzz_rng(20261101)
    for _ in range(800):
        text = soup_join(rng, _LOG_SOUP, 1, 60, "\n")
        _check_l2(text)


def _load_fixture_logs() -> list[tuple[str, str]]:
    return [
        (p.name, p.read_text("utf-8", errors="replace"))
        for p in sorted(_LOGS_DIR.glob("*.log"))
    ]


def _mutate_lines(  # noqa: PLR0911 -- 算子派发即早退表
    rng: random.Random, lines: list[str]
) -> tuple[list[str], str]:
    """log 行级变异算子；返回 ``(新行表, 算子名)``。"""
    op = soup_pick(
        rng, ["trunc", "drop", "bang+1", "fl+1", "warn+1", "dup", "shuffle", "inject"]
    )
    if op == "trunc" and lines:
        return lines[: rng.randrange(len(lines) + 1)], "trunc"
    if op == "drop" and lines:
        a = rng.randrange(len(lines))
        b = min(len(lines), a + rng.randrange(1, 40))
        return [*lines[:a], *lines[b:]], "drop"
    if op == "bang+1":
        i = rng.randrange(len(lines) + 1)
        return [*lines[:i], "! fuzz injected error", *lines[i:]], "bang+1"
    if op == "fl+1":
        i = rng.randrange(len(lines) + 1)
        return [*lines[:i], "./fuzz.tex:7: injected fileline error", *lines[i:]], "fl+1"
    if op == "warn+1":
        i = rng.randrange(len(lines) + 1)
        return [
            *lines[:i],
            "LaTeX Warning: Citation `fz' undefined on input line 3.",
            *lines[i:],
        ], "warn+1"
    if op == "dup" and lines:
        a = rng.randrange(len(lines))
        b = min(len(lines), a + rng.randrange(1, 20))
        i = rng.randrange(len(lines) + 1)
        return [*lines[:i], *lines[a:b], *lines[i:]], "dup"
    if op == "shuffle" and len(lines) > 2:  # noqa: PLR2004 -- 乱序最小片段长
        a = rng.randrange(len(lines) - 1)
        b = min(len(lines), a + rng.randrange(1, 12))
        seg = lines[a:b]
        rng.shuffle(seg)
        return [*lines[:a], *seg, *lines[b:]], "shuffle"
    i = rng.randrange(len(lines) + 1)
    return [*lines[:i], soup_pick(rng, _LOG_SOUP), *lines[i:]], "inject"


def test_l2_fixture_mutation() -> None:
    """真 fixture log 变异 fuzz：每次变异后全量 oracle + 算子级变质断言。"""
    rng = fuzz_rng(20261102)
    fixtures = _load_fixture_logs()
    assert fixtures, "tests/fixtures/logs 为空"
    for name, text in fixtures:
        base = _check_l2(text)
        lines = text.splitlines()
        for _ in range(40):
            mlines, op = _mutate_lines(rng, lines)
            mv = _check_l2("\n".join(mlines))
            if op in {"bang+1", "fl+1"}:
                assert mv.n_errors == base.n_errors + 1, (name, op)
            elif op == "warn+1":
                assert mv.warnings.total == base.warnings.total + 1, name
                assert (
                    mv.warnings.by_class.get("citation", 0)
                    == base.warnings.by_class.get("citation", 0) + 1
                ), name


def test_l2_fixture_splice_additivity() -> None:
    """两 log 拼接：错误数/warning 总数可加；engine/first_error 随前半。"""
    rng = fuzz_rng(20261103)
    fixtures = _load_fixture_logs()
    for _ in range(60):
        (na, ta), (nb, tb) = rng.choice(fixtures), rng.choice(fixtures)
        va, vb = parse_log_text(ta), parse_log_text(tb)
        vc = _check_l2(ta + "\n" + tb)
        assert vc.n_errors == va.n_errors + vb.n_errors, (na, nb)
        assert vc.warnings.total == va.warnings.total + vb.warnings.total, (na, nb)
        assert vc.engine == va.engine
        if va.first_error is not None:
            assert vc.first_error is not None
            assert vc.first_error.line_no == va.first_error.line_no
        elif vb.first_error is not None:
            off = len((ta + "\n").splitlines())
            assert vc.first_error is not None
            assert vc.first_error.line_no == vb.first_error.line_no + off


def test_l2_parse_log_path(tmp_path: Path) -> None:
    """路径入口一致性 + 缺席/目录/坏字节降级为 log_missing 或 replace 解码。"""
    rng = fuzz_rng(20261104)
    text = soup_join(rng, _LOG_SOUP, 5, 40, "\n")
    p = tmp_path / "x.log"
    p.write_bytes(text.encode("utf-8") + b"\xff\xfe trailing")
    decoded = p.read_bytes().decode("utf-8", "replace")
    assert parse_log(p).to_dict() == parse_log_text(decoded).to_dict()
    assert parse_log(tmp_path / "absent.log").log_missing is True
    assert parse_log(tmp_path).log_missing is True  # 目录 → is_file 闸
    assert parse_log("\x00nul").log_missing is True  # NUL 路径不抛


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="os.mkfifo 缺席平台")
def test_p3_parse_log_fifo_is_missing(tmp_path: Path) -> None:
    """P3 回归：fifo/特殊文件先吃 ``is_file`` 闸——``exists()`` 对 fifo 为真，
    无闸时 ``read_text`` 阻塞至有 writer。"""
    fifo = tmp_path / "x.log"
    os.mkfifo(fifo)
    assert parse_log(fifo).log_missing is True


def test_l2_eof_attribution() -> None:
    """eof_file 归因：``)`` 弹出后 ≤16 行内的 File-ended 错回填弹出件。"""
    v = parse_log_text("(./a.tex\n)\n! File ended while scanning use of \\x.\n")
    assert v.errors[0].eof_file == "./a.tex"
    v = parse_log_text("(./a.tex\n! File ended while scanning use of \\x.\n")
    assert v.errors[0].eof_file is None  # 无弹出 → 不归因
    pad = "\n".join(f"pad{i}" for i in range(20))
    v = parse_log_text(f"(./a.tex\n)\n{pad}\n! File ended while scanning use of \\x.\n")
    assert v.errors[0].eof_file is None  # 弹窗 >16 → 不归因
    v = parse_log_text("(./a.tex\n)\n! Undefined control sequence.\n")
    assert v.errors[0].eof_file is None  # 非 File-ended 错不套用


def test_l2_warn_oracle_directed() -> None:
    """归类 oracle 定向锚——oracle 自身的正确性证据（失配即实现 bug 非 oracle bug）。"""
    cases = {
        "Invalid UTF-8 byte or sequence": "invalid_utf8",
        "invalid utf-8 byte 9F": "invalid_utf8",
        "Warning: replaced by U+FFFD.": "invalid_utf8",
        "Missing character: There is no x in font nullfont": "missing_glyph_nullfont",
        "Missing character: There is no x in font cmr10": "missing_glyph",
        "Missing character: There is no 中 (U+4E2D) in font cmr10!": "missing_glyph_cjk",
        "Missing character: There is no (U+FFFD) in font cmr10!": "fffd_glyph",
        "LaTeX Warning: Citation `a' undefined on input line 3.": "citation",
        "LaTeX Warning: Reference `r' undefined on input line 9.": "reference",
        "LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.": "rerun",
        "LaTeX Font Warning: Font shape `TU/x' undefined": "font_subst",
        "Package pdftex.def Warning: File `fig.pdf' not found on input line 9.": "file_not_found",
        "LaTeX Warning: cannot open file `d.dat' for reading.": "file_not_found",
        "Overfull \\hbox (12.0pt too wide) in paragraph": "overfull",
        "Underfull \\vbox (badness 10000)": "overfull",
        "Foo Warning: something odd": "generic",
        "plain text": "NONE",
        "Missing character:": "missing_glyph",
    }
    for ln, want in cases.items():
        v = parse_log_text(ln + "\n")
        got = next(iter(v.warnings.by_class), "NONE")
        assert got == want, (ln, v.warnings.by_class)


# ---------------------------------------------------------------- l1 schema 残余


def test_d1_ok_relative_must_be_bool() -> None:
    """D1 回归：``ok_relative`` 非 bool/None → ``L1Error``（真值串 ``"no"``
    曾穿透进 ``verdict_ok`` 使聚合 fail-open）。"""
    with pytest.raises(L1Error):
        TsResult.from_dict({"ok": False, "ok_relative": "no"})


@pytest.mark.parametrize(
    "payload",
    [
        {"ok": False, "parse_errors": ["oops"]},
        {"ok": False, "env_mismatches": [42]},
        {"ok": False, "placeholders": {"typos": ["x"]}},
    ],
)
def test_d2_detail_items_must_be_dicts(payload: dict[str, Any]) -> None:
    """D2 回归：明细列表项非 dict → ``L1Error``（曾在 ``report.feedback``
    消费侧泄 ``AttributeError``）。"""
    with pytest.raises(L1Error):
        TsResult.from_dict(payload)


@pytest.mark.parametrize(
    "ph",
    [
        {"missing": None},
        {"missing": "MATH_1"},
        {"unexpected": 7},
        {"typos": None},
    ],
)
def test_d3_placeholder_values_must_be_lists(ph: dict[str, Any]) -> None:
    """D3 回归：``placeholders`` 三键值非 list → ``L1Error``（``missing=None``
    曾炸 ``len(None)``、``missing=str`` 曾产逐字符垃圾反馈）。"""
    with pytest.raises(L1Error):
        TsResult.from_dict({"ok": False, "placeholders": ph})


def test_d4_misschar_join_steals_class() -> None:
    """D4 回归：misschar 续行拼接在次行是独立 warning 行时不拼——
    ``in font nullfont`` 属次行自身锚点，不得窃走本行 CJK 归类。"""
    v = parse_log_text(
        "Missing character: There is no 中 (U+4E2D)\n"
        "Missing character: There is no y in font nullfont\n"
    )
    assert v.warnings.by_class.get("missing_glyph_cjk") == 1
    assert v.warnings.by_class.get("missing_glyph_nullfont") == 1
    assert v.warnings.cjk_missing == 1
    assert any("missing_glyph_cjk" in r for r in v.warnings.redlines)


def test_d4_misschar_join_wrap_still_works() -> None:
    """D4 回归补：真折行续行（裸 ``in font nullfont`` 碎片非 warning 形态）
    仍拼接——nullfont 豁免面不回退。"""
    v = parse_log_text("Missing character: There is no 中\nin font nullfont\n")
    assert v.warnings.by_class.get("missing_glyph_nullfont") == 1
    assert v.warnings.cjk_missing == 0


def test_d5_bang_ctx_borrows_next_error_lnum() -> None:
    """D5 回归：``!`` 错 ctx 截断于下一错误行——``l.NNN`` 属邻错定位，
    errA 不得借用 errB 行号。"""
    v = parse_log_text("! errA\n! errB\nl.9 \\y\n")
    assert v.errors[0].tex_line is None
    assert v.errors[0].ctx == ()
    assert v.errors[1].tex_line == 9  # noqa: PLR2004 -- 字面行号即输入语料


def test_l1_schema_positive_shapes() -> None:
    """反向钉：合法形态不得被误收 L1Error——防修 D1-D3 时过度收紧。"""
    r = TsResult.from_dict(
        {
            "id": "c1",
            "ok": True,
            "ok_relative": None,
            "parse_errors": [{"type": "ERROR", "row": 1, "snippet": "s"}],
            "env_mismatches": [
                {"kind": "end_name", "begin_env": "a", "end_env": "b", "line": 3}
            ],
            "unclosed_math": 0,
            "brace_balance": 0,
            "placeholders": {"missing": [], "unexpected": [], "typos": []},
            "parse_ms": 1.5,
        }
    )
    assert r.ok
    assert r.verdict_ok
    assert r.parse_errors[0]["row"] == 1
    r2 = TsResult.from_dict({"ok": True, "ok_relative": False})
    assert r2.verdict_ok is False


# ---------------------------------------------------------------- report 聚合面


def _rand_ts(rng: random.Random) -> TsResult:
    """合法形态 TsResult 生成器（坏形态归 D1-D3 钉，不进绿路径）。"""
    return TsResult(
        ok=rng.random() < 0.5,  # noqa: PLR2004 -- 概率阈值字面量
        ok_relative=rng.choice([None, None, True, False]),
        parse_errors=[
            {"type": "ERROR", "row": i, "snippet": f"s{i}"}
            for i in range(rng.randint(0, 8))
        ],
        env_mismatches=[
            {"kind": "end_name", "begin_env": f"b{i}", "end_env": f"e{i}", "line": i}
            for i in range(rng.randint(0, 6))
        ],
        unclosed_math=rng.randint(-2, 4),
        brace_balance=rng.randint(-4, 4),
        placeholders={
            "missing": [f"M{i}" for i in range(rng.randint(0, 4))],
            "unexpected": [f"U{i}" for i in range(rng.randint(0, 4))],
            "typos": [
                {"found": f"f{i}", "expected": f"e{i}"}
                for i in range(rng.randint(0, 4))
            ],
        },
        parse_ms=rng.random() * 10,
        error=rng.choice([None, "boom"]),
    )


def test_report_aggregate_fuzz() -> None:
    """``aggregate`` 三级组合 fuzz：ok/n_error/n_warn/hard_failures/feedback/
    summary 全 oracle；to_dict JSON 可落盘。"""
    rng = fuzz_rng(20261105)
    for _ in range(400):
        l0 = (
            validate_pair(soup_join(rng, _SOUP, 0, 12), soup_join(rng, _SOUP, 0, 12))
            if rng.random() < 0.7  # noqa: PLR2004 -- 在场层概率阈值
            else None
        )
        l1 = _rand_ts(rng) if rng.random() < 0.7 else None  # noqa: PLR2004
        l2 = (
            parse_log_text(soup_join(rng, _LOG_SOUP, 0, 40, "\n"))
            if rng.random() < 0.5  # noqa: PLR2004
            else (
                L2Verdict(log_missing=True) if rng.random() < 0.3 else None  # noqa: PLR2004
            )
        )
        rep = aggregate(chunk_id=f"c{rng.randint(0, 9)}", l0=l0, l1=l1, l2=l2)

        exp_ok = (
            (l0 is None or l0.ok)
            and (l1 is None or bool(l1.verdict_ok))
            and (l2 is None or l2.log_missing or l2.ok)
        )
        assert rep.ok == exp_ok
        exp_err = (
            (l0.n_error if l0 else 0)
            + (0 if l1 is None or l1.verdict_ok else 1)
            + (0 if l2 is None or l2.log_missing else l2.n_errors)
        )
        assert rep.n_error == exp_err
        assert rep.ok == (rep.n_error == 0)
        exp_warn = (l0.n_warn if l0 else 0) + (
            0 if l2 is None or l2.log_missing else l2.warnings.total
        )
        assert rep.n_warn == exp_warn

        hf = rep.hard_failures()
        exp_hf = (
            (l0.n_error if l0 else 0)
            + (0 if l1 is None or l1.verdict_ok else 1)
            + (0 if l2 is None or l2.log_missing or l2.ok else 1)
        )
        assert len(hf) == exp_hf
        assert all(h.startswith(("l0:", "l1:", "l2:")) for h in hf)
        fb = rep.feedback()  # 合法形态恒不抛
        if rep.ok:
            assert fb == ""
            assert hf == []

        s = rep.summary()
        parts = s.rsplit(" ", 5)
        exp_marks = [
            "L0-" if l0 is None else ("L0✓" if l0.ok else "L0✗"),
            "L1-" if l1 is None else ("L1✓" if l1.verdict_ok else "L1✗"),
            "L2-"
            if l2 is None
            else ("L2?" if l2.log_missing else ("L2✓" if l2.ok else "L2✗")),
        ]
        assert parts[-5:-2] == exp_marks, short(s)
        assert parts[-2] == f"err={rep.n_error}"
        assert parts[-1] == f"warn={rep.n_warn}"
        json.dumps(rep.to_dict())


def test_obs_log_missing_overrides_nerrors() -> None:
    """OBSERVED 钉：手造 ``log_missing=True, n_errors=3`` 的不一致 verdict，
    aggregate 只信 log_missing——pin 当前行为防静默改语义。"""
    rep = aggregate(l2=L2Verdict(log_missing=True, n_errors=3))
    assert rep.ok is True
    assert rep.n_error == 0


def test_obs_tsresult_error_field_unread() -> None:
    """OBSERVED 钉：``error`` 字段只被 sign() 读——validate/aggregate 不看，
    ``ok=True, error='boom'`` 照常过。"""
    rep = aggregate(l1=TsResult(ok=True, error="boom"))
    assert rep.ok is True
    assert rep.n_error == 0


# ---------------------------------------------------------------- l0 残余钉


def test_l0_env_tail_cap() -> None:
    """``_ENV_CHECK_TAIL_LIMIT=50``：60 个互异多余 ``\\end{X}`` → 1 error + 50 warn。"""
    zh = "".join(f"\\end{{env{i}}}" for i in range(60))
    rep = validate_pair("", zh)
    envs = [i for i in rep.issues if i.rule == "env"]
    # 60 互异 end 名：orphan 签名 1 error + tail-diff warn 截断 50（其余规则
    # 如 macro 结构命令计数另算，不钉死 n_error 总数）
    assert sum(i.severity is Severity.WARN for i in envs) == 50  # noqa: PLR2004
    assert any(i.severity is Severity.ERROR and "多余" in i.message for i in envs)


def test_l0_issue_to_dict_pos_edge() -> None:
    """``Issue.to_dict`` pos=-1 省略键、pos≥0 写入——边界 pin。"""
    assert "pos" not in Issue("env", Severity.ERROR, "m").to_dict()
    assert Issue("env", Severity.ERROR, "m", pos=0).to_dict()["pos"] == 0
