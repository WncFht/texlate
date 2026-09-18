r"""mask.py 遮蔽层对抗 fuzz——span 级 oracle + group_end/apply_edits 性质。

`mask_tex`/`mask_comments` 的不变量（等长/逐字白名单/换行保留/幂等）已由
``test_fuzz_textutil.py`` 覆盖；本文件补其未盖的 span 级 oracle：以
**事件流 + 认领状态机**（位置排序的 begin/verb/% 事件，先占先得）独立重算
遮盖区间集合，与 ``mask_tex`` 的扁平字符环逐字节比对——结构不同构，同规格。

核心不变量：

- ``mask_tex``：遮盖区间与事件流 oracle 全等（4 种 flag 组合）；等长；
  逐位「原样或空格」；``\r\n`` 位不动；双调确定且幂等（verb 遮盖只作用
  在定界符间内容——``\verb`` 本体与定界符原位保留，二遍扫描在同一
  ``\verb`` 上得到同一 parse、content 已是空格故再遮为 no-op；配套
  guard：定界符扫描跳过水平空白后落 ``\r\n`` 不定界，否则被遮区段留下
  的空格会桥到行间换行上产出假 span）；
- 消费契约：遮盖视图上的正则命中段回切原文逐字节同（offset 对齐是
  normalize/probe/inject splice 的地基）；
- ``visible_tex`` 与 ``mask_tex`` 的参数映射（``mask_comment_environments``
  ↔ ``mask_dead``）；``without_comments`` ≡ ``mask_comments``；
- ``group_end``：显式栈 oracle 全等（转义/注释/嵌套/``[``-组语义——
  ``{`` 恒嵌套、``[`` 不嵌套、``}``/``]`` 只看栈顶期望）；返回值界
  ``pos <= ret <= len(s)``；``ret < len`` 时 ``s[ret-1]`` 即所求闭括号；
- ``apply_edits``：非重叠编辑与「正序单遍构造」oracle 全等；行数账
  ``out.nl - in.nl == Σ max(0, repl_nl - span_nl)``；输入序无关；双调确定；
- 全家族对 NUL/裸 ``\r``/lone ``\``/未闭合 env/``\verb`` 残骸/深括号
  （限深避开已钉递归缺陷）不抛。

已修复的缺陷（原 ``xfail(strict=True)`` 钉，修复后拆钉为普通断言；
verbatim 族语义均已用 latex 实编译验证，见 tmp/mask-fuzz/texprobe/ 与
tmp/mask-fix/probe/）：

- ``_env_stop`` 的 ``\\end\s*\{env\}`` ``\s*`` 过配 → verbatim 族改逐字
  token 序列 ``\\end\{env\}``（kernel ``\@xverbatim`` 定界字串 / listings
  逐 ``\`` 探测），``\end {verbatim}`` 空白断序列不终结；
- 失活 ``comment`` 终结改**行锚定整行比对**（comment.sty ``\ifx`` 比行
  内容 == ``\end{env}``：行首空格是 catcode-12 字面符不匹配、行尾空格
  被输入层剥除故容许）——行内 ``x\end{comment}`` 与 ``\end {comment}``
  均不终结；
- ``_inline_verb_end`` 的 ``isspace() → None`` → ``\verb``/``\verb*`` 定界
  符扫描跳过水平空白（``\verb |x|`` ≡ ``\verb|x|``），取换行本身为定界
  符时下一整行是逐字内容（latex 实证）。配套两处幂等性结构修正：
  遮盖只作用在定界符间内容（``\verb`` 本体与定界符原位保留——二遍
  parse 同一定界符、content 已遮故 no-op），以及空白跳过后落 ``\r\n``
  不定界（防被遮区段空格桥到行尾换行上吞掉真实行内容）；
- ``group_end`` 的 ``%`` 注释 ``find('\n')`` → ``[\r\n]`` 搜索，与
  ``mask_tex``/``mask_comments`` 防御口径对齐；
- ``_LSTINLINE_OPT_RX`` 的 ``\s*`` → ``[ \t]*``：opt-skip 不跨换行，二遍
  遮盖不再把被遮的 ``%``-注释区（含行尾 ``\n`` 前的空白段）桥接成假 verb
  span。

观察项（非钉）：``group_end`` 对 ``\verb`` 盲（``{\verb|}|x}`` 提前收尾）
——``\verb`` 在命令实参里本属非法，只影响病态输入；``group_end(pos>len)``
返回 ``pos``（超界 offset 原样回传）契约有毛边；``\begin\n\n{env}``
（空行=``\par`` token，TeX 实不开环境）被 ``\s*`` 开侧匹配 → 过遮盖
（安全方向）；``apply_edits`` 对重叠/重复同 span 编辑语义未定义（调用方
契约保证非重叠）；fancyvrb 族（``Verbatim``/``minted`` 等）真实终结是
「行内首个 ``\end{name}`` 即终」，与逐字子串搜仅在「同行先出现异名
``\end{other}``」病态行上有别，按 verbatim 族同口径处理。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from _fuzzkit import fuzz_rng

from texlate.compile.mask import (
    TEX_SOURCE_SUFFIXES,
    apply_edits,
    group_end,
    visible_tex,
    without_comments,
)
from texlate.textutil import DEAD_ENVS, VERBATIM_ENVS, mask_comments, mask_tex

if TYPE_CHECKING:
    import random

# ---------------------------------------------------------------- 事件流 oracle

_ALL_ENVS = sorted(VERBATIM_ENVS | DEAD_ENVS)
_ORACLE_BEGIN_RX = re.compile(
    r"\\begin\s*\{(" + "|".join(re.escape(e) for e in _ALL_ENVS) + r")\}"
)
_ORACLE_VERB_RX = re.compile(r"\\(verb\*?|lstinline\*?)(?![A-Za-z@])")
_ORACLE_LSTOPT_RX = re.compile(r"[ \t]*(?:\[[^\]\n]*\][ \t]*)?")
_ORACLE_NL_RX = re.compile(r"[\r\n]")


def _oracle_verb_span(text: str, m: re.Match[str]) -> tuple[int, int, int] | None:
    """``\\verb``/``\\lstinline`` 的 ``(content_a, content_b, end)``——与 impl
    同口径的独立写法：只遮定界符间内容，``\\verb`` 本体与定界符保留。"""
    start = m.end()
    skipped = False
    if m[1].startswith("lstinline"):
        opt = _ORACLE_LSTOPT_RX.match(text, start)
        if opt is not None:
            start = opt.end()
        if start >= len(text) or text[start].isspace():
            return None
    else:
        while start < len(text) and text[start] in " \t":
            start += 1
            skipped = True
        if start >= len(text):
            return None
    delim = text[start]
    if delim in "\r\n":
        off = 2 if text[start : start + 2] == "\r\n" else 1
        nl = None if skipped else _ORACLE_NL_RX.search(text, start + off)
        return None if nl is None else (start + off, nl.start(), nl.start() + 1)
    end = text.find("}" if delim == "{" else delim, start + 1)
    nl = _ORACLE_NL_RX.search(text, start)
    if end < 0 or (nl is not None and nl.start() < end):
        return None
    return (start + 1, end, end + 1)


def _oracle_events(
    text: str, *, mask_dead: bool
) -> list[tuple[int, str, re.Match[str] | None]]:
    """候选事件流：env begin / 行内 verb / ``%``——位置排序、未做存活判定。"""
    events: list[tuple[int, str, re.Match[str] | None]] = [
        (m.start(), "env", m)
        for m in _ORACLE_BEGIN_RX.finditer(text)
        if mask_dead or m[1] not in DEAD_ENVS
    ]
    events.extend((m.start(), "verb", m) for m in _ORACLE_VERB_RX.finditer(text))
    i = 0
    while (i := text.find("%", i)) >= 0:
        events.append((i, "comment", None))
        i += 1
    events.sort(key=lambda e: e[0])
    return events


def _oracle_span(
    text: str,
    pos: int,
    kind: str,
    m: re.Match[str] | None,
    *,
    keep_verbatim: bool,
) -> tuple[str, int, int] | None:
    """单个存活事件认领的 ``(tag, claim_a, claim_b, mask_a, mask_b)``——claim

    区间压存活判定与事件抑制，mask 区间才是实际遮盖（verb 只遮定界符间
    内容，claim 仍含 ``\\verb`` 本体与定界符）；不合法形态为 None。
    """
    if kind == "comment":
        nl = _ORACLE_NL_RX.search(text, pos)
        end = len(text) if nl is None else nl.start()
        return ("mask", pos, end, pos, end)
    if kind == "verb":
        assert m is not None
        span = _oracle_verb_span(text, m)
        if span is None:
            return None
        a, b, end = span
        return ("mask", pos, end, a, b)
    assert m is not None
    if m[1] in DEAD_ENVS:
        em = re.compile(
            r"(?<=[\r\n])\\end\{" + re.escape(m[1]) + r"\} *(?=[\r\n]|\Z)"
        ).search(text, m.end())
    else:
        em = re.compile(r"\\end\{" + re.escape(m[1]) + r"\}").search(text, m.end())
    end = len(text) if em is None else em.end()
    tag = "block" if keep_verbatim and m[1] in VERBATIM_ENVS else "mask"
    return (tag, pos, end, pos, end)


def _oracle_mask_tex(
    text: str, *, mask_dead: bool = True, keep_verbatim: bool = False
) -> str:
    """事件流状态机 oracle：先占先得的区间认领，与 mask_tex 结构不同构。"""
    events = _oracle_events(text, mask_dead=mask_dead)
    spans: list[tuple[int, int]] = []  # 认领区间（事件抑制 + live 判定）
    blocked: list[tuple[int, int]] = []  # keep_verbatim 的逐字 env：认领但不遮
    masks: list[tuple[int, int]] = []  # 实际遮盖区间（verb 只遮内容段）

    def claimed(p: int) -> bool:
        return any(a <= p < b for a, b in spans) or any(a <= p < b for a, b in blocked)

    def live(pos: int) -> bool:
        """事件存活＝pos 前紧邻的**未认领**连续 ``\\`` 数为偶数——奇数时该

        ``\\`` 被 ``_COMMAND_RX`` 与前一 ``\\`` 成对吃掉；认领区间可劈开
        run（``\\verb\\\\`` 以 ``\\`` 为定界符时收尾 ``\\`` 在认领内），
        故须逐位查 claimed 而非全文数 run。
        """
        run = 0
        j = pos - 1
        while j >= 0 and text[j] == "\\" and not claimed(j):
            run += 1
            j -= 1
        return run % 2 == 0

    for pos, kind, m in events:
        if claimed(pos) or not live(pos):
            continue
        hit = _oracle_span(text, pos, kind, m, keep_verbatim=keep_verbatim)
        if hit is None:
            continue
        tag, ca, cb, ma, mb = hit
        (blocked if tag == "block" else spans).append((ca, cb))
        if tag == "mask":
            masks.append((ma, mb))
    out = list(text)
    for a, b in masks:
        out[a:b] = [c if c in "\r\n" else " " for c in out[a:b]]
    return "".join(out)


# ---------------------------------------------------------------- 语料发生器
_SOUP_TOKENS = [
    "word ",
    "x",
    "  ",
    "\n",
    "\r\n",
    "\r",
    "\t",
    "{",
    "}",
    "[",
    "]",
    "$x$",
    "%",
    "%%",
    "\\textbf{a}",
    "\\alpha ",
    "\\%esc",
    "\\\\",
    "\\ ",
    "\\\n",
    "\\begin{document}",
    "\\end{document}",
    "\\input{f}",
    "% comment",
    "% \\begin{verbatim}",
    "a%b",
    "%\n",
    "% tail-no-eol",
    "\\begin{verbatim}",
    "\\end{verbatim}",
    "\\begin{verbatim*}",
    "\\end{verbatim*}",
    "\\begin{Verbatim}",
    "\\end{Verbatim}",
    "\\begin{lstlisting}",
    "\\end{lstlisting}",
    "\\begin{minted}{py}",
    "\\end{minted}",
    "\\begin{filecontents}{x}",
    "\\end{filecontents}",
    "\\begin{comment}",
    "\\end{comment}",
    "\\begin{comment*}",
    "\\end{comment*}",
    "\\begin{unknownenv}",
    "\\end{unknownenv}",
    "\\begin {verbatim}",
    "\\end {verbatim}",
    "\\end\t{lstlisting}",
    "\\begin\n{verbatim}",
    "\\end\n{verbatim}",
    "\\begins{verbatim}",
    "\\begin{verbatimx}",
    "\\begin{VerbatimX}",
    "x\\end{verbatim}",
    "\\verb|lit|",
    "\\verb*|s|",
    "\\verb!x!",
    "\\verb{g}",
    "\\verb |x|",
    "\\verb",
    "\\verb|unclosed",
    "\\verb||",
    "\\lstinline|c|",
    "\\lstinline[lang=rs]|d|",
    "\\lstinline |e|",
    "\\lstinline[opt]",
    "\\lstinline",
    "\\lstinline\n|crossline|",
    "\x00",
    "中文字",
    "café",
    "\ud800",
    "\\begin{verbatim}head",
]

_P_ENV_WRAP = 0.08
_P_ENV_UNCLOSED = 0.03
_P_LONE_END = 0.04
_MASK_ITERS = 2500
_FLAG_COMBOS = (
    {},
    {"mask_dead": False},
    {"keep_verbatim": True},
    {"mask_dead": False, "keep_verbatim": True},
)


def _soup(rng: random.Random, n_tok: int) -> str:
    """token 汤 + 偶发成对环境包裹 / 未闭合 begin / 孤立 end。"""
    toks = [rng.choice(_SOUP_TOKENS) for _ in range(n_tok)]
    if rng.random() < _P_ENV_WRAP and toks:
        env = rng.choice(
            [
                "verbatim",
                "verbatim*",
                "Verbatim",
                "lstlisting",
                "minted",
                "comment",
                "filecontents",
            ]
        )
        a, b = sorted((rng.randrange(len(toks)), rng.randrange(len(toks))))
        toks[a] = f"\\begin{{{env}}}" + rng.choice(["", " "]) + toks[a]
        toks[b] = toks[b] + rng.choice(["", "x", " "]) + f"\\end{{{env}}}"
    if rng.random() < _P_ENV_UNCLOSED:
        toks.insert(
            rng.randrange(len(toks) + 1),
            f"\\begin{{{rng.choice(['verbatim', 'comment', 'lstlisting'])}}}",
        )
    if rng.random() < _P_LONE_END:
        toks.insert(
            rng.randrange(len(toks) + 1),
            f"\\end{{{rng.choice(['verbatim', 'comment', 'minted'])}}}",
        )
    return "".join(toks)


def _check_view(src: str, masked: str) -> None:
    """等长 + 逐位白名单 + 换行位不动（splice 地基的最小不变量）。"""
    assert len(masked) == len(src)
    for a, b in zip(src, masked, strict=True):
        assert b in {a, " "}
        if a in "\r\n":
            assert b == a


def test_fuzz_mask_tex_span_oracle() -> None:
    """随机 TeX 汤 × 4 flag 组合：事件流 oracle 逐字节全等 + 不变量 + 幂等。"""
    rng = fuzz_rng(20260917)
    for _ in range(_MASK_ITERS):
        t = _soup(rng, rng.randint(0, 45))
        for kw in _FLAG_COMBOS:
            want = _oracle_mask_tex(t, **kw)
            got = mask_tex(t, **kw)
            assert got == want, f"kw={kw} span 分歧: {t!r}\n{got!r}\n{want!r}"
            _check_view(t, got)
            # 幂等逐点断言（lstinline ``\s*`` 桥接缺陷 bfd1d17 已修，
            # 原 xfail 拆钉——此处即拆钉后常驻回归断言）。
            assert mask_tex(t, **kw) == got, "非确定"


def test_fuzz_visible_tex_wrapper_equiv() -> None:
    """``visible_tex`` 与 ``mask_tex`` 的 flag 映射逐字节全等。"""
    rng = fuzz_rng(20260918)
    for _ in range(800):
        t = _soup(rng, rng.randint(0, 30))
        assert visible_tex(t) == mask_tex(t)
        assert visible_tex(t, mask_comment_environments=False) == mask_tex(
            t, mask_dead=False
        )
        assert without_comments(t) == mask_comments(t)


def test_fuzz_masked_view_splice_alignment() -> None:
    """消费契约：遮盖视图上的 cs/``\\begin`` 命中段回切原文逐字节同。"""
    rng = fuzz_rng(20260919)
    cs_rx = re.compile(r"\\[a-zA-Z@]+\*?|\\begin\s*\{[a-zA-Z*]+\}")
    for _ in range(800):
        t = _soup(rng, rng.randint(0, 40))
        vis = visible_tex(t)
        for m in cs_rx.finditer(vis):
            assert t[m.start() : m.end()] == m.group(0), repr(t)


# ---------------------------------------------------------------- group_end
_GE_CMD_RX = re.compile(r"\\(?:[a-zA-Z@]+\*?|.)", re.DOTALL)


def _oracle_group_end(s: str, pos: int) -> int:
    """显式栈配对 oracle（``{`` 恒压 ``}``、``[`` 仅外层、闭括号看栈顶）。"""
    if pos >= len(s) or s[pos] not in "[{":
        return pos
    stack = ["}" if s[pos] == "{" else "]"]
    i = pos + 1
    while i < len(s) and stack:
        c = s[i]
        if c == "\\":
            m = _GE_CMD_RX.match(s, i)
            i = m.end() if m else i + 2
            continue
        if c == "%":
            m = _ORACLE_NL_RX.search(s, i)
            i = len(s) if m is None else m.start() + 1
            continue
        if c == "{":
            stack.append("}")
        elif c == stack[-1]:
            stack.pop()
        i += 1
    return i if not stack else len(s)


_GE_TOKENS = [
    "{",
    "}",
    "[",
    "]",
    "a",
    "b",
    " ",
    "\n",
    "\\{",
    "\\}",
    "\\[",
    "\\]",
    "\\\\",
    "\\foo",
    "\\%",
    "\\\n",
    "%",
    "%c\n",
    "%\n",
    "%noeol",
    "\\%inside",
]
_GE_ITERS = 2500
_GE_DEPTH = 80  # 远低于递归上限——深嵌套 RecursionError 已由 test_fuzz_normalize 钉


def _ge_soup(rng: random.Random) -> str:
    parts = [rng.choice(_GE_TOKENS) for _ in range(rng.randint(0, 30))]
    if rng.random() < 0.25:  # noqa: PLR2004 -- 偶发有界深嵌套
        d = rng.randint(1, _GE_DEPTH)
        parts.insert(rng.randrange(len(parts) + 1), "{" * d + "}" * d)
    if rng.random() < 0.2:  # noqa: PLR2004 -- 偶发不平衡尾
        parts.append("{" * rng.randint(1, 20))
    return "".join(parts)


def test_fuzz_group_end_stack_oracle() -> None:
    """brace/escape/comment 汤 × 全 opener 位：栈 oracle 逐点全等。"""
    rng = fuzz_rng(20260920)
    for _ in range(_GE_ITERS):
        s = _ge_soup(rng)
        positions = [i for i, c in enumerate(s) if c in "[{"]
        positions += [rng.randrange(len(s) + 2) for _ in range(min(4, len(s) + 2))]
        for p in positions:
            got = group_end(s, p)
            want = _oracle_group_end(s, p)
            assert got == want, f"{s!r} @{p}: {got} != {want}"
            if p < len(s):
                assert p <= got <= len(s)
                if got < len(s) and s[p] in "[{":
                    assert s[got - 1] == ("]" if s[p] == "[" else "}")


def test_fuzz_group_end_never_raise() -> None:
    """对抗字符面（含裸 ``\\r``/NUL/lone ``\\``）：不抛 + 返回值界。"""
    rng = fuzz_rng(20260921)
    alpha = [*_GE_TOKENS, "\r", "\r\n", "\x00", "\ud800", "%\rx", "中"]
    for _ in range(2000):
        s = "".join(rng.choice(alpha) for _ in range(rng.randint(0, 30)))
        if rng.random() < 0.15:  # noqa: PLR2004
            s += "{" * rng.randint(1, _GE_DEPTH)
        for _ in range(3):
            p = rng.randrange(len(s) + 2)
            got = group_end(s, p)
            if p >= len(s):
                assert got == p
            else:
                assert p <= got <= len(s)
                if s[p] not in "[{":
                    assert got == p


# ---------------------------------------------------------------- apply_edits
def _oracle_apply_edits(text: str, edits: list[tuple[int, int, str]]) -> str:
    """正序单遍构造 oracle——与 impl 的逆序 splice 不同构。"""
    out: list[str] = []
    cur = 0
    for start, end, repl in sorted(edits):
        out.append(text[cur:start])
        pad = text[start:end].count("\n") - repl.count("\n")
        out.append(repl + "\n" * max(0, pad))
        cur = end
    out.append(text[cur:])
    return "".join(out)


def test_fuzz_apply_edits_oracle() -> None:
    """非重叠随机编辑：oracle 全等 + 行数账公式 + 输入序无关 + 确定。"""
    rng = fuzz_rng(20260922)
    repl_pool = ["", "X", "\n", "a\nb", "  ", "line\nline\n", "\\cs{v}", "%"]
    for _ in range(2000):
        text = _soup(rng, rng.randint(0, 25))
        n = len(text)
        points = sorted(rng.sample(range(n + 1), min(n + 1, rng.randint(0, 12))))
        edits: list[tuple[int, int, str]] = []
        cursor = 0
        for p in points:
            end = rng.randint(p, min(n, p + 8))
            if p >= cursor:
                edits.append((p, end, rng.choice(repl_pool)))
                cursor = end
        rng.shuffle(edits)
        got = apply_edits(text, edits)
        want = _oracle_apply_edits(text, edits)
        assert got == want, f"{text!r} {edits}: {got!r} != {want!r}"
        delta = sum(max(0, r.count("\n") - text[s:e].count("\n")) for s, e, r in edits)
        assert got.count("\n") - text.count("\n") == delta
        assert apply_edits(text, edits) == got
        assert apply_edits(text, sorted(edits)) == got


def test_apply_edits_edge_pins() -> None:
    """空编辑/纯插入/换行增减的形态钉。"""
    assert apply_edits("abc", []) == "abc"
    assert apply_edits("abc", [(1, 1, "ZZ")]) == "aZZbc"
    out = apply_edits("a\nb\nc", [(2, 3, "x\ny\nz")])
    assert out == "a\nx\ny\nz\nc"
    assert out.count("\n") == 4  # noqa: PLR2004 - 替换多出的换行是净增


# ---------------------------------------------------------------- 全家族不抛
_NASTY = [
    "",
    "\x00" * 10,
    "\r" * 20 + "%",
    "\\",
    "\\verb",
    "\\verb|",
    "\\verb\n",
    "\\begin{verbatim}",
    "\\end{comment}",
    "{" * 120 + "}" * 120,
    "[" * 100,
    "%" * 200,
    "\\" * 150,
    "\ud800a\ud800",
    " \t" * 50,
    "\\begin{verbatim}\n\x00\x00\n\\end{verbatim}\n",
    "a%b\rc%d\ne",
    "\\lstinline[\x00]|x|",
]


def test_fuzz_never_raise_matrix() -> None:
    """对抗载荷 × 全家族函数：不抛 + 返回类型契约。"""
    for t in _NASTY:
        assert isinstance(visible_tex(t), str)
        assert isinstance(without_comments(t), str)
        for kw in _FLAG_COMBOS:
            assert isinstance(mask_tex(t, **kw), str)
        r = group_end(t, 0)
        assert r == 0 or 0 < r <= len(t)
        r = group_end(t, len(t) // 2)
        assert len(t) // 2 <= r
        assert isinstance(apply_edits(t, [(0, min(1, len(t)), "x")]), str)


def test_edge_boundary_semantics() -> None:
    """非 xfail 边界语义钉：当前 impl 与 TeX 一致的行为面。"""
    # 未闭合 verbatim → 遮到 EOF（安全方向）
    vis = visible_tex("\\begin{verbatim}\nSECRET \\cmd\n")
    assert "SECRET" not in vis
    assert "\\cmd" not in vis
    # 行内连续 ``\end{verbatim}`` 真实终结（latex 实证）→ 其后可见
    vis = visible_tex("\\begin{verbatim}\nx\\end{verbatim} AFTER\n")
    assert "AFTER" in vis
    # 注释掉的 begin 不开环境
    vis = visible_tex("% \\begin{verbatim}\nBODY % c\n")
    assert "BODY" in vis
    # ``%`` 裸挂 EOF
    vis = visible_tex("a %")
    assert vis == "a  "
    # ``\\verb`` 残骸不炸且本体仍可见
    vis = visible_tex("\\verb|unclosed\n")
    assert "unclosed" in vis
    vis = visible_tex("\\verb")
    assert vis == "\\verb"


def test_tex_source_suffixes_shape() -> None:
    """后缀集形态：非空、小写、点起、含 ``.tex``。"""
    assert TEX_SOURCE_SUFFIXES
    assert ".tex" in TEX_SOURCE_SUFFIXES
    for s in TEX_SOURCE_SUFFIXES:
        assert s.startswith(".")
        assert s == s.lower()


# ---------------------------------------------------------------- 修复后钉
@pytest.mark.parametrize("gap", [" ", "\t", "\n"])
@pytest.mark.parametrize("env", ["verbatim", "Verbatim", "lstlisting", "minted"])
def test_env_spaced_end_undermasks(env: str, gap: str) -> None:
    """``\\end <gap>{env}`` 不应终结遮盖——其后 verbatim 字面体应仍不可见。"""
    if env == "minted":
        begin, end = "\\begin{minted}{py}", "\\end{minted}"
    else:
        begin, end = f"\\begin{{{env}}}", f"\\end{{{env}}}"
    tex = (
        f"{begin}\nbody\n\\end{gap}{{{env}}}\nLEAK \\pdfcompresslevel=9\n{end}\nLIVE\n"
    )
    masked = visible_tex(tex)
    assert "LEAK" not in masked
    assert "LIVE" in masked


def test_dead_env_midline_end() -> None:
    """``x\\end{comment}`` 行内出现不应终结 comment 遮盖。"""
    tex = (
        "\\begin{comment}\nx\\end{comment} dead\nLEAK \\pdfoutput=1\n"
        "\\end{comment}\nLIVE\n"
    )
    masked = visible_tex(tex)
    assert "LEAK" not in masked
    assert "LIVE" in masked


def test_dead_env_spaced_end() -> None:
    """``\\end {comment}`` 行首出现不应终结 comment 遮盖。"""
    tex = (
        "\\begin{comment}\ndead\n\\end {comment}\nLEAK \\pdfoutput=1\n"
        "\\end{comment}\nLIVE\n"
    )
    masked = visible_tex(tex)
    assert "LEAK" not in masked
    assert "LIVE" in masked


@pytest.mark.parametrize(
    "form", ["\\verb |%s|", "\\verb\t|%s|", "\\verb* |%s|", "\\verb  !%s!"]
)
def test_verb_space_delimiter(form: str) -> None:
    """``\\verb``+空白+定界符是合法 verb——字面体应被遮盖。"""
    tex = "pre " + form % "\\pdfcompresslevel=9" + " post\nNEXT\n"
    masked = visible_tex(tex)
    assert "\\pdfcompresslevel" not in masked
    assert "NEXT" in masked


def test_verb_newline_delimiter() -> None:
    """``\\verb\\n`` 以换行为定界符——下一行字面体应被遮盖。"""
    tex = "pre \\verb\n|pdfcs| more\nNEXT\n"
    masked = visible_tex(tex)
    assert "|pdfcs|" not in masked
    assert "NEXT" in masked


def test_verb_space_env_blowup() -> None:
    """verb 字面体内的 ``\\begin{verbatim}`` 不得开环境遮盖。"""
    tex = "a \\verb |\\begin{verbatim}| b\n\\begin{document}\nx\n\\end{document}\n"
    masked = visible_tex(tex)
    assert "\\begin{document}" in masked


@pytest.mark.parametrize(
    ("s", "want"), [("{x %\r}tail", 6), ("[x %\r]tail", 6), ("{%\r}x", 4)]
)
def test_group_end_cr_comment(s: str, want: int) -> None:
    """``\\r``-only 行尾的 ``%`` 注释应就地终结，不吞后续配对括号。"""
    assert group_end(s, 0) == want


@pytest.mark.parametrize(
    ("tex", "kw"),
    [
        ("\\lstinline %\n\\a\\b", {}),
        (
            "\\lstinline\\verb||\r\\verb|a|\\end{x}\\begin{verbatim}\\begin{verbatim}",
            {"keep_verbatim": True},
        ),
    ],
)
def test_lstinline_opt_skip_idempotence(tex: str, kw: dict) -> None:
    """``mask_tex`` 幂等：``f(f(x)) == f(x)``。"""
    assert mask_tex(mask_tex(tex, **kw), **kw) == mask_tex(tex, **kw)
