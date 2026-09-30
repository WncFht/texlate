r"""capacity input_stack verdict 路由 —— 上游递归帧 → ``unfixable:input_stack``。

``input_stack|<cs>`` pay 的 pending cs 属上游宏递归帧 (内核 ``\@nomath``
守卫 / expl3 quark 扫描哨兵) 时, ``classify_head`` 把 cat 重路由成
``input_stack`` —— verdict ``unfixable:{cat}`` 直挂 cat, 真递归帧不再
混进 ``unfixable:capacity`` 的可修假簇 (ifdiag 车道 2026-09-19 三格普查:
``@nomath``/``__quark_if_recursion_tail:w`` 皆 paper-authentic;
``cref@resetstack`` 是 texlate 可修面, 留 capacity 走修复派发)。
"""

from pathlib import Path

from _fixloopkit import MockEngine, classify, make_proj, rs

from texlate.compile.fixloop import fixloop
from texlate.compile.logparse import parse_text

_QUARK_LOG = (
    "! TeX capacity exceeded, sorry [input stack size=10000].\n"
    "\\__quark_if_recursion_tail:w ...ion_tail #2?#3?!->\n"
    "                                                  #1#2\n"
    "l.325 \n"
    "If you really absolutely need more capacity,\n"
    "you can ask a wizard to enlarge me.\n"
)

_NOMATH_LOG = (
    "! TeX capacity exceeded, sorry [input stack size=10000].\n"
    "\\@nomath ...e \\@font@warning {Command \\noexpand #1\n"
    "                                                  invalid in math mode}\\fi \n"
    "l.307 \\tableofcontents\n"
    "If you really absolutely need more capacity,\n"
)

_RESETSTACK_LOG = (
    "! TeX capacity exceeded, sorry [input stack size=10000].\n"
    "\\cref@resetstack ->\n"
    "                   paragraph,\\@nil \n"
    "l.20 \\end{restatable}\n"
    "If you really absolutely need more capacity,\n"
)


def test_quark_frame_routes_input_stack() -> None:
    """expl3 quark 哨兵 pending → ``input_stack`` 类 (非 capacity)。"""
    assert classify(_QUARK_LOG) == (
        "input_stack",
        "input_stack|__quark_if_recursion_tail:w",
    )


def test_nomath_frame_routes_input_stack() -> None:
    """内核 ``\\@nomath`` 守卫帧 pending → ``input_stack`` 类。"""
    assert classify(_NOMATH_LOG) == ("input_stack", "input_stack|@nomath")


def test_resetstack_stays_capacity() -> None:
    """``\\cref@resetstack`` 可修族不抢路由——留 capacity 走修复派发。"""
    assert classify(_RESETSTACK_LOG) == (
        "capacity",
        "input_stack|cref@resetstack",
    )


def test_generic_frame_stays_capacity() -> None:
    """名单外 pending cs 不重路由——``\\iterate`` 真递归面照归 capacity。"""
    log = (
        "! TeX capacity exceeded, sorry [input stack size=10000].\n"
        "\\iterate ->\\iterate\n"
        "l.10 \\foo\n"
    )
    assert classify(log) == ("capacity", "input_stack|iterate")


def test_non_input_stack_tag_unaffected() -> None:
    """main_memory 等其他容量类不涉路由——名单只闸 input_stack tag。"""
    log = (
        "! TeX capacity exceeded, sorry [main memory size=5000000].\n"
        "\\@nomath ->\\foo\n"
    )
    assert classify(log) == ("capacity", "main_memory|@nomath")


def test_verdict_unfixable_input_stack(tmp_path: Path) -> None:
    """端到端: quark 帧格 → ``unfixable:input_stack``, 不烧修复轮。"""
    cell = fixloop(make_proj(tmp_path), MockEngine([{"log": _QUARK_LOG}]))
    assert cell["verdict"] == "unfixable:input_stack"
    assert cell["rounds"][0]["category"] == "input_stack"
    assert cell["rounds"][0]["payload"] == "input_stack|__quark_if_recursion_tail:w"


def test_verdict_resetstack_stays_repair_dispatch(tmp_path: Path) -> None:
    """端到端: ``\\cref@resetstack`` 格仍走修复派发——非 article 源上
    revtex4 规则 cond-skip 后落 ``unfixable:capacity``, 不进 verdict-only 簇。"""
    cell = fixloop(make_proj(tmp_path), MockEngine([{"log": _RESETSTACK_LOG}]))
    assert cell["verdict"] == "unfixable:capacity"
    assert cell["rounds"][0]["category"] == "capacity"
    assert cell["rounds"][0]["payload"] == "input_stack|cref@resetstack"


def test_err_candidates_carry_routed_cat() -> None:
    """次级错误派发同口径——capacity 孪生候选同样重路由。"""
    log = "! Missing $ inserted.\nl.5 x\n" + _QUARK_LOG
    cands = rs().taxonomy.err_candidates(parse_text(log))
    assert ("input_stack", "input_stack|__quark_if_recursion_tail:w") in [
        (c, p) for c, p, _e, _b in cands
    ]
