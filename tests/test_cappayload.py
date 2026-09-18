"""capacity taxonomy payload — bracket 归一 tag + ctx 首层 pending cs。

``TeX capacity exceeded, sorry [<name>=<n>]`` → ``<tag>|<cs>`` 供 triage
路由 (input_stack=递归 / main_memory=暴走 / save_size=组泄漏)。合成 log
覆盖: bang/file-line 双错误格式、sorry 折行、宏/伪层/l.N 三层头取位、
``<to be read again>`` 续行 token、截断缺 bracket、未收名兜底。
"""

from functools import lru_cache

from texlate.compile.fixloop import Ruleset, load_ruleset
from texlate.compile.fixloop.logparse import parse_text


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    return load_ruleset()


def _classify(log: str) -> tuple[str | None, str | None]:
    return _rs().taxonomy.classify(parse_text(log))


def test_input_stack_bang_macro() -> None:
    """input stack + 宏展开层: pay=input_stack|<行首在扩宏>。"""
    log = (
        "! TeX capacity exceeded, sorry [input stack size=10000].\n"
        "\\@restorepar ->\\def \\par \n"
        "                         {\\@par }\n"
        "l.190 ...OP:ALT-SERIES-REPRESENTATIONS-OF-PDF-CDF}\n"
        "If you really absolutely need more capacity,\n"
        "you can ask a wizard to enlarge me.\n"
    )
    assert _classify(log) == ("capacity", "input_stack|@restorepar")


def test_main_memory_fileline_macro() -> None:
    """file-line 形态 main memory: pay=main_memory|reserved@a。"""
    log = (
        "./paper.tex:75: TeX capacity exceeded, sorry [main memory size=5000000].\n"
        "\\reserved@a #1#2->\\let #1#2\\reserved@a \n"
        "                                       \n"
        "l.75 have been obtained in \\Ref{Vanderzande92}\n"
        "If you really absolutely need more capacity,\n"
    )
    assert _classify(log) == ("capacity", "main_memory|reserved@a")


def test_save_size_wrapped_bracket_argument() -> None:
    """sorry 折行 + <argument> 伪层: bracket 跨行仍抓, token 取头行末 cs。"""
    log = (
        "./xeCJK.sty:643: TeX capacity exceeded, s\n"
        "orry [save size=200000].\n"
        "<argument> ..._xeCJK_begin_int =\\l__xeCJK_tmp_int \n"
        "                                                  \\int_incr:N \\l__xeCJK_begi...\n"
        "l.643 \\xeCJKResetCharClass\n"
        "If you really absolutely need more capacity,\n"
    )
    assert _classify(log) == ("capacity", "save_size|l__xeCJK_tmp_int")


def test_to_be_read_again_continuation() -> None:
    """<to be read again> 头行无 token: pending 取续行首 cs。"""
    log = (
        "! TeX capacity exceeded, sorry [input stack size=10000].\n"
        "<to be read again> \n"
        "                   \\iterate\n"
        "l.10 \\foo\n"
    )
    assert _classify(log) == ("capacity", "input_stack|iterate")


def test_ln_row_pending_cs() -> None:
    """顶层 l.N 行末 cs 为 pending token。"""
    log = (
        "! TeX capacity exceeded, sorry [main memory size=5000000].\n"
        "l.75 have been obtained in \\Ref{Vanderzande92}\n"
    )
    assert _classify(log) == ("capacity", "main_memory|Ref")


def test_ln_row_no_cs_falls_to_continuation() -> None:
    """l.N 行内无 cs: 续行首 cs 兜底 (源行后半=待读 token)。"""
    log = (
        "! TeX capacity exceeded, sorry [pool size=8000000].\n"
        "l.9 plain text\n"
        "          \\foo\n"
    )
    assert _classify(log) == ("capacity", "pool_size|foo")


def test_bracket_only_no_ctx() -> None:
    """无 ctx (裸错误行): pay 退 <tag>。"""
    log = "! TeX capacity exceeded, sorry [input stack size=10000].\n"
    assert _classify(log) == ("capacity", "input_stack")


def test_truncated_no_bracket_token_only() -> None:
    """截断 log 无 bracket: pay=?|<cs> 保两字段形。"""
    log = "! TeX capacity exceeded, sorry\n\\iterate ->\\iterate\nl.5 \\iterate\n"
    assert _classify(log) == ("capacity", "?|iterate")


def test_no_bracket_no_ctx_none() -> None:
    """旧签 ``sorry.`` 无 bracket 无 ctx: pay=None (logparse 既有断言口径)。"""
    log = "! TeX capacity exceeded, sorry.\n"
    assert _classify(log) == ("capacity", None)


def test_unlisted_bracket_snake_fallback() -> None:
    """未收 bracket 名走全词 snake 兜底。"""
    log = "! TeX capacity exceeded, sorry [trie size=1000000].\n\\@foo ->\\bar\n"
    assert _classify(log) == ("capacity", "trie_size|@foo")


def test_indented_continuation_not_layer_head() -> None:
    """缩进续行不冒充层头: 首层仍取 \\mac 行首名。"""
    log = (
        "! TeX capacity exceeded, sorry [input stack size=10000].\n"
        "\\@bsphack ->\\relax \\ifhmode \\@savsk \\lastskip \n"
        "                                              \\@savsf \\spacefactor \\fi \n"
        "l.80 }\n"
    )
    assert _classify(log) == ("capacity", "input_stack|@bsphack")


def test_secondary_error_candidates_carry_payload() -> None:
    """err_candidates 次级错误同样带 bracket+token payload。"""
    log = (
        "! Missing $ inserted.\n"
        "l.5 x\n"
        "! TeX capacity exceeded, sorry [input stack size=10000].\n"
        "\\iterate ->\\iterate\n"
        "l.9 \\iterate\n"
    )
    cands = _rs().taxonomy.err_candidates(parse_text(log))
    assert ("capacity", "input_stack|iterate") in [(c, p) for c, p, _e, _b in cands]
