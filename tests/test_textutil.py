"""textutil 杂件钉点：lev_capped 契约界 + 数学定界配对机 + 声明扫描遮盖面。

配对机口径实证锚点：``$a\\alpha$$b\\beta$$``（inline 闭 ``$`` 与相邻
``$`` 不得预并成 ``$$``——旧实现挂起开区间吞掉全文配对，两枚数学域
cs 被误报文本域裸 cs）。
"""

from texlate import textutil
from texlate.textutil import (
    _cs_events_spans,
    _declared_name,
    bare_cs_net,
    decode_tex,
    decode_tex_with,
    lev_capped,
    mask_comments,
    mask_tex,
    sniff_tex_encoding,
)


# ---------------------------------------------------------------- lev_capped 契约
def test_lev_capped_exact_within_cap() -> None:
    assert lev_capped("kitten", "sitting", 3) == 3  # noqa: PLR2004 -- 钉距离值
    assert lev_capped("abc", "abc", 0) == 0
    assert lev_capped("", "ab", 2) == 2  # noqa: PLR2004 -- 钉距离值


def test_lev_capped_over_cap_returns_cap_plus_one() -> None:
    """超界恒回 cap+1——含「行最小值未越界但终值越界」的末行形态
    （旧实现漏压，``aaab``/``babbbbb`` cap=3 曾回真实距离 5）。"""
    assert lev_capped("aaab", "babbbbb", 3) == 4  # noqa: PLR2004 -- cap+1
    assert lev_capped("aabb", "bbbbbb", 2) == 3  # noqa: PLR2004 -- cap+1
    assert lev_capped("abc", "xyz", 0) == 1
    assert lev_capped("", "abcd", 3) == 4  # noqa: PLR2004 -- cap+1


# ---------------------------------------------------------------- 数学定界配对机
def _spans(s: str) -> list[tuple[int, int]]:
    return _cs_events_spans(mask_comments(s))[1]


def test_math_spans_basic_forms() -> None:
    assert _spans(r"a $x$ b") == [(2, 5)]
    assert _spans(r"a $$x$$ b") == [(2, 7)]
    assert _spans(r"a \(x\) b \[y\]") == [(2, 7), (10, 15)]


def test_math_spans_adjacent_inline_pair() -> None:
    r"""``$a\alpha$$b\beta$$``：闭 ``$``+相邻 ``$`` 是两个 inline 域，
    不是 ``$$``——配对不得挂起。"""
    spans = _spans(r"text $a\alpha$$b\beta$$ end")
    assert spans == [(5, 14), (14, 22)]
    assert not bare_cs_net("", r"text $a\alpha$$b\beta$$ end")


def test_math_spans_inline_then_display() -> None:
    r"""``$a\alpha$$$b\beta$$``：inline + 贴邻 display，两侧 cs 皆数学域。"""
    s = r"text $a\alpha$$$b\beta$$ end"
    assert _spans(s) == [(5, 14), (14, 24)]
    assert not bare_cs_net("", s)


def test_math_spans_display_then_inline_pair() -> None:
    s = r"$$\alpha x$$ tail $y\beta$$z$ more"
    assert _spans(s) == [(0, 12), (18, 26), (26, 29)]
    assert not bare_cs_net("", s)


def test_math_spans_text_cs_still_flagged() -> None:
    """不误赦：真文本域数学 cs 仍报（配对修复不得反向放大豁免面）。"""
    out = bare_cs_net("", r"text $a$$b$$ more \alpha here")
    assert out["alpha"] == 1


def test_math_spans_unclosed_dollar_rest_is_text() -> None:
    assert _spans(r"$x and \alpha after") == []
    assert bare_cs_net("", r"$x and \alpha after")["alpha"] == 1


def test_math_spans_paren_env_forms() -> None:
    assert _spans(r"\(x\) and \[y\]") == [(0, 5), (10, 15)]
    # 裸 \)/\] 在文本态不接管、不配对
    assert _spans(r"a \) b \(x\)") == [(7, 12)]


# ---------------------------------------------------------------- declared 遮盖面
def test_declared_inputenc_in_comment_ignored() -> None:
    """注释掉的旧声明不是作者先验（verbatim/comment 遮盖面同口径）。"""
    blob = b"% \\usepackage[cp866]{inputenc}\n\\documentclass{article}\n"
    assert _declared_name(blob) is None


def test_declared_inputenc_in_verbatim_ignored() -> None:
    blob = (
        b"\\begin{verbatim}\n\\usepackage[cp866]{inputenc}\n"
        b"\\end{verbatim}\n\\documentclass{article}\n"
    )
    assert _declared_name(blob) is None


def test_declared_inputenc_active_still_read() -> None:
    blob = b"% prior comment\n\\usepackage[latin9]{inputenc}\n"
    assert _declared_name(blob) == "latin9"


def test_declared_magic_comment_still_read() -> None:
    """``% !TEX encoding`` 是注释形态声明——遮盖面不得误吞。"""
    blob = b"% !TEX encoding = UTF-8\n\\documentclass{article}\n"
    assert _declared_name(blob) == "utf-8"


# ---------------------------------------------------------------- utf-16 奇字节尾
def test_utf16_odd_tail_parity_pick() -> None:
    """无 BOM utf-16le 奇数字节截断：两端 strict 皆败时按 NUL 奇偶位
    选端 + replace 兜底——不回 utf-8 档产出 NUL 夹心乱文。"""
    blob = "x\\alpha y".encode("utf-16-le")[:-1]
    v = sniff_tex_encoding(blob)
    assert v.encoding == "utf-16-le"
    assert "bad-tail" in v.note
    assert decode_tex(blob).startswith("x\\alpha")


def test_utf16be_odd_tail_parity_pick() -> None:
    blob = "x\\alpha y".encode("utf-16-be")[:-1]
    v = sniff_tex_encoding(blob)
    assert v.encoding == "utf-16-be"
    assert decode_tex(blob).startswith("x\\alpha")


# ---------------------------------------------------------------- memo 层
def test_mask_tex_memo_hit_same_content() -> None:
    """同内容不同对象 → 命中不重算；flag 组合各占独立键。"""
    textutil._mask_tex_memo.cache_clear()  # noqa: SLF001 — 钉 memo 计数面
    t1 = "\\begin{comment}\nx\n\\end{comment}\nbody\n"
    t2 = t1[:-1] + chr(10)  # 同内容新对象——字面量/全片切片在 CPython 会复用
    a = mask_tex(t1)
    b = mask_tex(t2)
    info = textutil._mask_tex_memo.cache_info()  # noqa: SLF001
    assert a == b
    assert a is b
    assert (info.hits, info.misses) == (1, 1)
    c = mask_tex(t1, mask_dead=False)
    info2 = textutil._mask_tex_memo.cache_info()  # noqa: SLF001
    assert c != a  # comment 体可见 vs 遮蔽——flag 进键不错位
    assert (info2.hits, info2.misses) == (1, 2)


def test_decode_tex_with_memo_hit_and_shared_verdict() -> None:
    """同字节新对象 → 命中；verdict 是 frozen 实例可安全共享。"""
    textutil._decode_tex_with_memo.cache_clear()  # noqa: SLF001
    b1 = b"caf\xe9 latin\n"
    b2 = bytes(bytearray(b1))
    t1, v1 = decode_tex_with(b1)
    t2, v2 = decode_tex_with(b2)
    info = textutil._decode_tex_with_memo.cache_info()  # noqa: SLF001
    assert t1 == t2
    assert t1 is t2
    assert v1 is v2
    assert (info.hits, info.misses) == (1, 1)


def test_memo_size_guard_bypasses_cache() -> None:
    """超阈输入直调实现——巨型件不 pin 缓存槽。"""
    textutil._decode_tex_with_memo.cache_clear()  # noqa: SLF001
    big = b"x" * (textutil._MEMO_MAX_INPUT + 1)  # noqa: SLF001
    decode_tex_with(big)
    decode_tex_with(big)
    info = textutil._decode_tex_with_memo.cache_info()  # noqa: SLF001
    assert info.misses == 0
    assert info.hits == 0
