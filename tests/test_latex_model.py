"""model.py 字符级原语 + macro_table.parse_argspec 的单测。"""

from texlate.latex.macro_table import parse_argspec
from texlate.latex.model import (
    env_name_at,
    match_brace,
    match_bracket,
    read_cmd_name,
    unescaped_dollar_odd,
    ws_skip,
)


def test_ws_skip() -> None:
    assert ws_skip("  \t\nx", 0) == 4  # noqa: PLR2004 - 跳过空白后的 offset 断言
    assert ws_skip("abc", 0) == 0
    assert ws_skip("   ", 0) == 3  # noqa: PLR2004 - 全空白串跳到末尾


def test_match_brace_nested() -> None:
    assert match_brace("{a{b}c}", 0) == 7  # noqa: PLR2004 - 嵌套括号收尾 offset
    assert match_brace("{}", 0) == 2  # noqa: PLR2004 - 空组收尾 offset


def test_match_brace_unclosed() -> None:
    assert match_brace("{abc", 0) is None
    assert match_brace("x{", 0) is None  # tex[i] != '{'


def test_match_brace_skips_comment_and_escape() -> None:
    r"""``%`` 注释里的 ``}`` 不计；``\{`` 转义不 deepen。"""
    assert match_brace("{a%{}\nb}", 0) == 8  # noqa: PLR2004 - 注释内 } 不计后的收尾
    assert match_brace("{\\{x}", 0) == 5  # noqa: PLR2004 - 转义 \{ 不 deepen


def test_match_brace_verbatim_counts_comment_braces() -> None:
    r"""verbatim 模式（url/verb 参数）里 ``%`` 不再是注释。"""
    assert match_brace("{a%}b}", 0, verbatim=True) == 4  # noqa: PLR2004 - verbatim 里 % 非注释
    assert match_brace("{a%}b}", 0) is None  # 非 verbatim：整行是注释 → 未闭


def test_match_bracket_nested_braces() -> None:
    assert match_bracket("[a{b}c]", 0) == 7  # noqa: PLR2004 - 方括号内花括号配平收尾
    assert match_bracket("[x", 0) is None


def test_read_cmd_name() -> None:
    assert read_cmd_name("\\foo123", 0) == ("foo", 4)
    assert read_cmd_name("\\makeatletter@x", 0) == ("makeatletter@x", 15)
    assert read_cmd_name("\\%abc", 0) == ("%", 2)  # 非字母单字符
    assert read_cmd_name("\\[", 0) == ("[", 2)
    assert read_cmd_name("\\", 0) == ("", 1)


def test_env_name_at() -> None:
    assert env_name_at(" {figure} x", 0) == ("figure", 9)
    assert env_name_at("  x", 0) == (None, 0)


def test_unescaped_dollar_odd() -> None:
    assert not unescaped_dollar_odd("$x$")  # 成对 → 偶
    assert unescaped_dollar_odd("$x")  # 未闭合 → 奇（math-debt）
    assert unescaped_dollar_odd("\\$a$b")  # 转义不计
    assert not unescaped_dollar_odd("no dollar")


def test_parse_argspec_letters() -> None:
    kinds = [s.kind for s in parse_argspec("mom")]
    assert kinds == ["m", "o", "m"]
    kinds = [s.kind for s in parse_argspec("so O{d} d<> r() s")]
    assert kinds == ["s", "o", "O", "d", "r", "s"]
    d = parse_argspec("d<>")[0]
    assert d.delim == "<>"
    o = parse_argspec("O{def}")[0]
    assert o.default == "def"
    # 未知字母跳过不抛
    assert [s.kind for s in parse_argspec("m?o")] == ["m", "o"]
