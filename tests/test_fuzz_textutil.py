"""textutil.py 性质 fuzz——遮盖等长/幂等、lev_capped 契约、解码永不抛、净差对称。

核心不变量：

- ``mask_comments``：等长遮盖、换行位不动、幂等；独立 oracle 逐位重算
  （``%`` 前奇数连续 ``\\`` = 转义存活，偶数 = 注释起点）全等；
- ``mask_tex``：等长、逐字符「原样或空格」、换行保留、三种 flag 组合下
  均幂等；无 ``\\``+字母 的受限 alphabet 上与 ``mask_comments`` 全等；
- ``lev_capped``：== min(无上限 DP 真距离, cap+1)，对称，自身距离 0；
- ``decode_tex``/``sniff_tex_encoding``：任意字节不抛、确定性、产物无
  ``\\r``、verdict basis 在登记集内；合法 UTF-8 文本 round-trip 还原
  （``\\x00`` 与文首 U+FEFF 属编码内禀歧义面，发生器回避）；
- ``ph_in_cs_net``：``net(a,b)`` 与 ``net(b,a)`` 键集恒不交（Counter
  净差反对称）、自净差恒空、键恒 fullmatch 夹持形；
- ``bare_cs_net``：自净差恒空、产出键必为 zh 遮盖面内实存 cs 名且计数
  不超 zh 计数；
- ``_eol_norm``：与独立 ``re.sub(r"\\r\\n|\\r", "\\n")`` oracle 全等、
  幂等、产物无 ``\\r``；
- ``is_cjk_cp``/``CJK_RX`` 两表互洽；``VERBATIM_ENVS``/``DEAD_ENVS``
  注册表名逐一经 ``\\begin{env}`` 匹配且 ``mask_tex`` 真遮 env 体。
"""

from __future__ import annotations

import codecs
import re
import sys
from collections import Counter
from typing import TYPE_CHECKING

from _fuzzkit import fuzz_rng

from texlate import textutil
from texlate.textutil import (
    CJK_RANGES,
    CJK_RX,
    DEAD_ENVS,
    JSON_FENCE_RX,
    MATH_CS,
    VERBATIM_ENVS,
    _eol_norm,
    bare_cs_net,
    decode_tex,
    decode_tex_with,
    is_cjk_cp,
    lev_capped,
    mask_comments,
    mask_tex,
    ph_in_cs_net,
    sniff_tex_encoding,
)

if TYPE_CHECKING:
    import random

# ---------------------------------------------------------------- mask_comments


#: ``%`` 起点判定 oracle——逐位「前导连续反斜杠计数奇偶」口径（独立代码路径，
#: 不复用 jump-2 扫描结构）。
def _oracle_mask_comments(text: str) -> str:
    out = list(text)
    in_comment = False
    for i, c in enumerate(text):
        if c in "\r\n":
            in_comment = False
            continue
        if in_comment:
            out[i] = " "
            continue
        if c == "%":
            run = 0
            j = i - 1
            while j >= 0 and text[j] == "\\":
                run += 1
                j -= 1
            if run % 2 == 0:
                in_comment = True
                out[i] = " "
    return "".join(out)


_COMMENT_ALPHA = [
    *"ab %~{}()[]^_0123456789数据",
    "\\",
    "\\%",
    "\\\\",
    "\\a",
    "\\ ",
    "\n",
    "\r\n",
    "\r",
]


def test_fuzz_mask_comments_oracle() -> None:
    """随机 %/\\/换行汤：oracle 全等 + 等长 + 换行位不动 + 幂等 + 存活 ``%``
    恒为奇数反斜杠 run 后。"""
    rng = fuzz_rng(20260917)
    for _ in range(4000):
        t = "".join(rng.choice(_COMMENT_ALPHA) for _ in range(rng.randint(0, 50)))
        m = mask_comments(t)
        assert m == _oracle_mask_comments(t), repr(t)
        assert len(m) == len(t)
        for a, b in zip(t, m, strict=True):
            assert b in {a, " "}
            if a in "\r\n":
                assert b == a
        assert mask_comments(m) == m, f"非幂等: {t!r} -> {m!r}"


# ---------------------------------------------------------------- mask_tex

#: mask_tex 汤 alphabet——逐字环境/失活环境/行内 verb/注释/畸形形态混排。
_TEX_TOKENS = [
    "word ",
    "\\textbf{x}",
    "\\alpha",
    "% comment",
    "%",
    "a%b",
    "\\%esc",
    "\\\\",
    "{",
    "}",
    "[",
    "]",
    "$x$",
    "$$y$$",
    "\\(z\\)",
    "\n",
    "\r\n",
    "\r",
    "  ",
    "\\begin{verbatim}",
    "\\end{verbatim}",
    "\\begin{verbatim*}",
    "\\end{verbatim*}",
    "\\begin{lstlisting}",
    "\\end{lstlisting}",
    "\\begin{minted}{py}",
    "\\end{minted}",
    "\\begin{comment}",
    "\\end{comment}",
    "\\begin{unknown}",
    "\\end{unknown}",
    "\\verb|lit%|",
    "\\verb*!x%!",
    "\\verb{g}",
    "\\verb",
    "\\lstinline|c%|",
    "\\lstinline[lang=rs]|d%|",
    "数据中",
    "\\begin{verbatim}x",
]


def _check_mask_view(src: str, masked: str) -> None:
    """等长遮盖视图公共不变量。"""
    assert len(masked) == len(src)
    for a, b in zip(src, masked, strict=True):
        assert b in {a, " "}
        if a in "\r\n":
            assert b == a, "换行位被遮盖"


def test_fuzz_mask_tex_invariants() -> None:
    """随机 TeX 汤 × 三种 flag 组合：等长 + 逐字白名单 + 换行保留 + 幂等。"""
    rng = fuzz_rng(20260918)
    kws = [{}, {"mask_dead": False}, {"keep_verbatim": True}]
    for _ in range(3000):
        t = "".join(rng.choice(_TEX_TOKENS) for _ in range(rng.randint(0, 40)))
        for kw in kws:
            m = mask_tex(t, **kw)
            _check_mask_view(t, m)
            m2 = mask_tex(m, **kw)
            assert m2 == m, f"kw={kw} 非幂等: {t!r} -> {m!r} -> {m2!r}"


def test_fuzz_mask_tex_equals_mask_comments_no_cs() -> None:
    """受限 alphabet（``\\`` 后不随字母——verbatim env/``\\verb``/cs 均不可能
    成形）下 ``mask_tex`` 与 ``mask_comments`` 逐字节全等。"""
    rng = fuzz_rng(20260919)
    alpha = [
        *"ab %~{}()[]0123456789",
        "\\\\",
        "\\%",
        "\\$",
        "\\ ",
        "\\,",
        "\\{",
        "\n",
        "\r\n",
        "\r",
    ]
    for _ in range(3000):
        t = "".join(rng.choice(alpha) for _ in range(rng.randint(0, 60)))
        assert mask_tex(t) == mask_comments(t), repr(t)


# ---------------------------------------------------------------- lev_capped


def _lev_full(a: str, b: str) -> int:
    """无上限 Levenshtein 全 DP oracle。"""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def test_fuzz_lev_capped_matches_full_oracle() -> None:
    """小 alphabet 随机串 × 随机 cap：``lev_capped == min(真距离, cap+1)``，
    对称、自身距离 0、返回值恒 ``≤ cap+1``。"""
    rng = fuzz_rng(20260920)
    alpha = "abc中"
    for _ in range(20000):
        a = "".join(rng.choice(alpha) for _ in range(rng.randint(0, 7)))
        b = "".join(rng.choice(alpha) for _ in range(rng.randint(0, 7)))
        cap = rng.randint(0, 6)
        got = lev_capped(a, b, cap)
        want = min(_lev_full(a, b), cap + 1)
        assert got == want, f"{a!r}/{b!r} cap={cap}: {got} != {want}"
        assert lev_capped(b, a, cap) == got, "非对称"
        assert lev_capped(a, a, cap) == 0
        assert got <= cap + 1


# ---------------------------------------------------------------- 解码层

_BASIS = frozenset({"bom", "strict-utf8", "declared", "mixed", "detector", "fallback"})

_DECL_HEADERS = [
    b"\\usepackage[latin1]{inputenc}\n",
    b"\\usepackage[utf8]{inputenc}\n",
    b"\\usepackage[cp936]{inputenc}\n",
    b"\\inputencoding{latin9}\n",
    b"% !TEX encoding = UTF-8\n",
    b"% !TEX encoding = cp866\n",
    b"% -*- coding: iso-8859-1 -*-\n",
    b"% CodePage: 1252\n",
    b"% CodePage: 54936\n",
    b"% \\usepackage[cp866]{inputenc}\n",  # 注释掉的假声明
]

_CJK_TEXT = "干涉仪相位灵敏度分析结果如下，引力波探测器。"

#: 发生器概率常量（PLR2004：阈值字面量一律提名）——blob 段选择为累计区间。
_P_BLOB_HDR = 0.4
_P_BLOB_NOISE = 0.3
_P_BLOB_UTF8 = 0.5
_P_BLOB_TRUNC = 0.3
_P_BLOB_GB = 0.6
_P_BLOB_BIG5 = 0.7
_P_BLOB_SJIS = 0.8
_P_BLOB_UTF16 = 0.9
_P_BLOB_BOM = 0.1
_P_BLOB_DOC = 0.2


def _gen_blob(rng: random.Random) -> bytes:
    """对抗字节汤：随机噪声/截断 UTF-8/BOM/utf-16/latin-1/双字节编码段
    + 声明头拼接。"""
    parts: list[bytes] = []
    if rng.random() < _P_BLOB_HDR:
        parts.append(rng.choice(_DECL_HEADERS))
    r = rng.random()
    if r < _P_BLOB_NOISE:
        parts.append(rng.randbytes(rng.randint(0, 400)))
    elif r < _P_BLOB_UTF8:
        s = "".join(rng.choice("ab\\%{} \né中") for _ in range(rng.randint(0, 100)))
        blob = s.encode("utf-8")
        parts.append(
            blob[: rng.randrange(len(blob))]
            if blob and rng.random() < _P_BLOB_TRUNC
            else blob
        )
    elif r < _P_BLOB_GB:
        parts.append(_CJK_TEXT.encode("gb18030"))
    elif r < _P_BLOB_BIG5:
        parts.append(_CJK_TEXT.encode("big5", errors="ignore"))
    elif r < _P_BLOB_SJIS:
        parts.append("これはテスト".encode("shift_jis"))
    elif r < _P_BLOB_UTF16:
        parts.append("ascii only".encode("utf-16-le"))
    else:
        parts.append(bytes(rng.choice(range(256)) for _ in range(rng.randint(0, 60))))
    if rng.random() < _P_BLOB_BOM:
        parts.insert(0, rng.choice([b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff"]))
    if rng.random() < _P_BLOB_DOC:
        parts.append(b"\\documentclass{article}\n\\begin{document}\nx\n")
    return b"".join(parts)


def test_fuzz_decode_tex_never_raises() -> None:
    """任意对抗字节：``decode_tex`` 不抛、返回 str、无 ``\\r``、与
    ``decode_tex_with`` 一致、双调确定。"""
    rng = fuzz_rng(20260921)
    for _ in range(1500):
        blob = _gen_blob(rng)
        out = decode_tex(blob)
        assert isinstance(out, str)
        assert "\r" not in out
        text2, verdict = decode_tex_with(blob)
        assert out == text2
        assert verdict.basis in _BASIS
        assert decode_tex(blob) == out, "decode_tex 非确定"


def test_fuzz_sniff_verdict_shape() -> None:
    """verdict 结构不变量：basis 登记集内、双调相等、非 mixed 的 encoding
    必为可 lookup codec、declared 为 None 或 str。"""
    rng = fuzz_rng(20260922)
    for _ in range(1500):
        blob = _gen_blob(rng)
        v1 = sniff_tex_encoding(blob)
        v2 = sniff_tex_encoding(blob)
        assert v1 == v2, "sniff 非确定"
        assert v1.basis in _BASIS
        if v1.encoding != "utf-8-mixed":
            codecs.lookup(v1.encoding)  # 未注册名 → LookupError 逃逸即缺陷
        assert v1.declared is None or isinstance(v1.declared, str)


def test_fuzz_decode_tex_utf8_roundtrip() -> None:
    """合法 UTF-8 文本 round-trip 还原（经 ``_eol_norm`` oracle 比对）。

    发生器排除：``\\x00``（NUL 密度 ≥1/4 触发 utf-16 无 BOM 判定——合法
    UTF-8 与 utf-16 文本的内禀歧义，判定序是刻意的）与文首 U+FEFF
    （与 BOM 字节不可区分，utf-8-sig 语义剥除）。
    """
    rng = fuzz_rng(20260923)
    pool = (
        [chr(c) for c in range(0x20, 0x7F)]
        + ["é", "中", "文", "字", "α", "β", "—", "“", "”", "\U0001f600", "ß", "َ"]
        + ["\t", "\n", "\\", "%", "{", "}", "$", "\r", "\r\n"]
    )
    for _ in range(3000):
        s = "".join(rng.choice(pool) for _ in range(rng.randint(0, 80)))
        if s.startswith("\ufeff"):
            continue
        want = _eol_norm(s)
        assert decode_tex(s.encode("utf-8")) == want, repr(s[:60])


# ---------------------------------------------------------------- 净差对账

_NET_ALPHA = [
    *"ab 数据",
    "\\alpha",
    "\\textbf",
    "\\protect[[REF_1]]",
    "\\te[[MATH_1]]xtbf",
    "[[MATH_1]]",
    "[[X]]",
    "$x$",
    "$$y$$",
    "\\(z\\)",
    "%c",
    "\n",
    "\\citep",
    "\\itemOC",
    "\\alphaXY",
]

#: ``_PH_IN_CS_RX`` 的独立 fullmatch 形态（键即匹配串——``{1,48}?`` lazy 在
#: fullmatch 语义下与 ``{1,48}`` 同义）。
_PH_KEY_RX = re.compile(r"\\[a-zA-Z@]+\[\[[^\[\]\n]{1,48}\]\][a-zA-Z@]")
_CS_NAME_RX = re.compile(r"\\([a-zA-Z][a-zA-Z@]*)")


def test_fuzz_ph_in_cs_net_properties() -> None:
    """``net(a,b)``/``net(b,a)`` 键集恒不交、自净差空、键恒夹持形、计数正。"""
    rng = fuzz_rng(20260924)
    for _ in range(3000):
        src = "".join(rng.choice(_NET_ALPHA) for _ in range(rng.randint(0, 25)))
        zh = "".join(rng.choice(_NET_ALPHA) for _ in range(rng.randint(0, 25)))
        fwd = ph_in_cs_net(src, zh)
        rev = ph_in_cs_net(zh, src)
        assert set(fwd).isdisjoint(set(rev)), (src, zh, fwd, rev)
        assert all(v > 0 for v in fwd.values())
        assert all(_PH_KEY_RX.fullmatch(k) for k in fwd)
        assert not ph_in_cs_net(src, src)
        assert not ph_in_cs_net(zh, zh)


def test_fuzz_bare_cs_net_properties() -> None:
    """自净差空；产出键恒为 zh 遮盖面实存 cs 名且计数不超 zh 实计数。"""
    rng = fuzz_rng(20260925)
    for _ in range(3000):
        src = "".join(rng.choice(_NET_ALPHA) for _ in range(rng.randint(0, 25)))
        zh = "".join(rng.choice(_NET_ALPHA) for _ in range(rng.randint(0, 25)))
        out = bare_cs_net(src, zh)
        assert all(v > 0 for v in out.values())
        zh_names = _CS_NAME_RX.findall(mask_comments(zh))
        zh_counter = Counter(zh_names)
        for k, v in out.items():
            assert zh_counter[k] >= v, (k, v, zh_counter[k])
        assert not bare_cs_net(src, src)
        assert not bare_cs_net(zh, zh)


# ---------------------------------------------------------------- _eol_norm


def test_fuzz_eol_norm_oracle() -> None:
    """``\\r\\n``/``\\r`` → ``\\n``：独立 regex oracle 全等 + 幂等 + 无 ``\\r``。"""
    rng = fuzz_rng(20260926)
    oracle = re.compile(r"\r\n|\r")
    alpha = [*"ab\t", "\r\n", "\n", "\r", "\n\r", "\r\r\n"]
    for _ in range(3000):
        t = "".join(rng.choice(alpha) for _ in range(rng.randint(0, 60)))
        out = _eol_norm(t)
        assert out == oracle.sub("\n", t)
        assert "\r" not in out
        assert _eol_norm(out) == out


# ---------------------------------------------------------------- 注册表/正则小件


def test_json_fence_rx_roundtrip() -> None:
    """构造 fence 串：body 组逐字还原；非 fence 形不匹配。"""
    rng = fuzz_rng(20260927)
    for _ in range(300):
        inner = "".join(
            rng.choice("ab{} \n\t\"':,数据") for _ in range(rng.randint(0, 40))
        )
        # body 组逐字还原要求 inner 首尾不带会被 ``\s*\n``/``\n?\s*`` 吞掉的空白。
        if (
            "```" in inner
            or re.match(r"[^\S\n]*\n", inner)
            or (inner and inner[-1].isspace())
        ):
            continue
        lang = rng.choice(["json", "JSON", "", "js"])
        s = f"```{lang}\n{inner}\n```"
        m = JSON_FENCE_RX.match(s)
        assert m, repr(s)
        assert m["body"] == inner
    for s in ("plain text", "```json\n{}", "", "x```\ny\n```", "```\nb\n``` tail"):
        assert JSON_FENCE_RX.match(s) is None


def test_verbatim_envs_registry_consistent() -> None:
    """注册表逐名实证：``\\begin{env}`` 匹配 begin rx 且 ``mask_tex`` 真遮 env 体。"""
    for env in VERBATIM_ENVS:
        m = textutil._VERBATIM_BEGIN_RX.match(f"\\begin{{{env}}}")  # noqa: SLF001
        assert m, env
        assert m[1] == env, env
        body = "X % not-comment \n"
        tail = "TAIL"
        src = f"\\begin{{{env}}}{body}\\end{{{env}}}{tail}"
        masked = mask_tex(src)
        stop = len(f"\\begin{{{env}}}{body}\\end{{{env}}}")
        assert masked[:stop] == " " * stop or masked[:stop].strip() == "", (
            f"{env}: env 体未遮盖"
        )
        assert masked[stop:] == tail, env


def test_dead_envs_masked_by_default() -> None:
    """``comment`` 族默认遮盖、``mask_dead=False`` 放行。"""
    for env in DEAD_ENVS:
        # comment.sty 终结是行锚定整行比对——``\end{env}`` 须独占一行才生效。
        src = f"\\begin{{{env}}}\nDEAD\n\\end{{{env}}}\nLIVE"
        masked = mask_tex(src)
        assert masked.endswith("LIVE")
        assert "DEAD" not in masked
        kept = mask_tex(src, mask_dead=False)
        assert "DEAD" in kept, env


def test_fuzz_is_cjk_cp_cross_check() -> None:
    """``is_cjk_cp``（bisect 面）与线性 spec + ``CJK_RX`` 三方互洽——随机码点
    + 区间边界邻域。"""
    rng = fuzz_rng(20260928)
    spec = lambda cp: any(lo <= cp <= hi for lo, hi in CJK_RANGES)  # noqa: E731
    cps = {rng.randint(0, 0x10FFFF) for _ in range(4000)}
    for lo, hi in CJK_RANGES:
        cps |= {lo - 1, lo, lo + 1, hi - 1, hi, hi + 1}
    for cp in cps:
        if not 0 <= cp <= sys.maxunicode:
            continue
        want = spec(cp)
        assert is_cjk_cp(cp) == want, hex(cp)
        assert bool(CJK_RX.match(chr(cp))) == want, hex(cp)


def test_math_cs_registry_shape() -> None:
    """MATH_CS 结构钉：非空 frozenset、全 ASCII 字母名（无 ``@``/数字/空串）。"""
    assert isinstance(MATH_CS, frozenset)
    assert MATH_CS
    for n in MATH_CS:
        assert re.fullmatch(r"[a-zA-Z]+", n), n


def test_env_registries_shape() -> None:
    """VERBATIM/DEAD 注册表形态：非空 frozenset、基名+*变体成对在场。"""
    assert isinstance(VERBATIM_ENVS, frozenset)
    assert isinstance(DEAD_ENVS, frozenset)
    for e in VERBATIM_ENVS | DEAD_ENVS:
        assert re.fullmatch(r"[a-zA-Z+*]+", e), e
        if e.endswith("*"):
            assert e[:-1] in VERBATIM_ENVS or e[:-1] in DEAD_ENVS
        else:
            assert (e + "*") in (VERBATIM_ENVS | DEAD_ENVS) or e in DEAD_ENVS
