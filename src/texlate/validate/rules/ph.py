"""validate.rules.ph — 占位符规则域叶 (validate.rules 域缝叶)。

``_check_placeholder`` 全族：``[[TYPE_n]]``/``[[SL]]``/``[[PL]]`` multiset
diff + lev≤2 二分最大匹配修复配对（``_ph_typo_adjacency``/``_ph_max_pairs``/
``_pair_placeholder_typos``）+ E22 序守恒 warn + ``_check_ph_anchor``
行锚定双类（BIBITEM 行首锚定 + COMMENT 整行/行尾锚定）+ ``_ph_in_comments``
注释区臆造占位符专项（mask 比对盲区，sabotage 实测逃逸网）。
``_line_of``/``_line_tail`` 行截取件与锚定判据常量同域共置。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING, Final

from texlate.textutil import PH_ANY_LIKE_RX, PH_FUZZY_RX, lev_capped
from texlate.validate.rules.report import Issue, Severity

if TYPE_CHECKING:
    from texlate.validate.rules.lex import _Ctx

#: 从模糊候选里剥出核心 token（去括号/空白），供 lev 配对。
_PH_CORE_RX: Final = re.compile(r"[A-Za-z0-9_]+")

#: 结构占位符：必须保持行首锚定（`\bibitem` 脱位 mid-paragraph → 编译损伤）。
STRUCTURAL_PH_RX: Final = re.compile(r"\[\[BIBITEM_\d+\]\]")

#: 注释占位符（``%`` 展开吞到 EOL）。src 独占整行的 ``[[COMMENT_n]]`` 在 zh
#: 所在行必须整行只剩注释占位符——同行非注释邻居，前缀是 splice 残留垃圾、
#: 后缀是被注释吃掉的死字节（repro-2410b §4c）；src 行中的（ph 恒行尾，
#: 注释天然吃到换行）zh 尾段同样只许注释占位符。
COMMENT_PH_RX: Final = re.compile(r"\[\[COMMENT_\d+\]\]")
_COMMENT_LINE_RX: Final = re.compile(r"[ \t]*(?:\[\[COMMENT_\d+\]\][ \t]*)+")
_COMMENT_TAIL_RX: Final = re.compile(r"(?:[ \t]*\[\[COMMENT_\d+\]\])*[ \t]*")

_LEV_CAP: Final = 2


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
