r"""validate.rules.struct — 结构配对规则域叶 (validate.rules 域缝叶)。

四族 src↔zh 结构相对判定：``{}`` 平衡（``_check_brace``）、
``\\begin/\\end`` 栈配对 + 环境名 multiset 签名（``_check_env``）、
cite/ref/label/bib key multiset（``_check_key``）、``$``/``\\(\\)``/
``\\[\\]`` 计数（``_check_math``）。token 流入参的共享件
（``_*_toks``/``_*_masked``）+ 字符串入口 fuzz oracle
（``_brace_profile``/``_env_signature``/``_key_multiset``/``_math_profile``）
同域共置；``KEY_CMD_RX``/``ENV_RX``/``_BRACE_SEQ_RX`` 抓取正则随域。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING, Final

from texlate.textutil import mask_comments
from texlate.validate.rules.lex import _lex
from texlate.validate.rules.report import Issue, Severity

if TYPE_CHECKING:
    from texlate.validate.rules.lex import _Ctx

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

_ENV_CHECK_TAIL_LIMIT: Final = 50  # end 名偏多 warn 的报告条数上限


def _brace_profile_toks(
    toks: list[tuple[str, str, int]],
) -> tuple[int, int, int, int, int]:
    """``(open 数，close 数，净深度，最小前缀深度，首个负深度 pos)``——``_lex`` token 流入参。"""
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
    """``(begin|end, 环境名，pos)`` 事件流——入参须为 ``mask_comments`` 遮盖视图。"""
    return [(m.group(1), m.group(2).strip(), m.start()) for m in ENV_RX.finditer(snc)]


def _env_signature_masked(
    snc: str,
) -> tuple[int, int, Counter[str], Counter[str], Counter[str]]:
    """``(多余 end 数，不匹配数，未闭合 begin 名，begin 名，end 名)`` 栈签名——遮盖视图入参。"""
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
