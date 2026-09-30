r"""if_phantom_protect 内建 —— phantom Incomplete \if → 前稿 cs 族 \protected 重定义。

实证簇 (corpus flipcheck7): 1206.0701 (amsproc ``\footnote``-in-``\author``
→ ``\shortauthors``→``\markboth`` ``\edef`` 链 → ``\@nmbrlistfalse`` 替换体
``\if@nmbrlist`` 执行), 1306.0364 (myectaart ``\bf``-in-``\title`` →
``\xdef\@argi`` 链 → ``\@forced@seriesfalse`` 同理)。两稿源件字面
``\if*/\fi`` 平衡 → ``unclosed_if_close``(196) 扫描 noop 烧 dedup 位,
同签复发才轮到本规则。修 = eTeX ``\protected`` let-wrap: 属性钉在 cs
本体不被 ``\let\protect\relax`` 剥除, edef 扫描内整体带过。
"""

from pathlib import Path

from texlate.compile.fixloop import builtins, load_ruleset
from texlate.compile.fixloop.builtins import if_phantom_protect
from texlate.compile.fixloop.engine import LoopCtx

_FAMILY = (
    "footnote",
    "thanks",
    "bf",
    "it",
    "rm",
    "sf",
    "tt",
    "sc",
    "sl",
)
_MAIN = (
    "\\documentclass{amsproc}\n"
    "\\title{T}\n"
    "\\author{A\\footnote{f}}\n"
    "\\begin{document}\n"
    "\\maketitle\n"
    "\\end{document}\n"
)
_NOOP_ENTRY = {
    "round": 1,
    "rule": "unclosed_if_close",
    "detail": "rc=0 ifclose: noop opens=4 closes=4 deficits=0",
}
_INJECT_ENTRY = {
    "round": 1,
    "rule": "unclosed_if_close",
    "detail": "rc=0 ifclose: injected \\fi x2 into ./main.tex @line~40",
}
_CRASH_ENTRY = {
    "round": 1,
    "rule": "unclosed_if_close",
    "detail": "rc=1 Traceback (most recent call last): ...",
}


def _ctx(
    tmp_path: Path,
    actions: list[dict] | None = None,
    err_head: str = "",
) -> LoopCtx:
    return LoopCtx(
        wdir=tmp_path,
        engine_name="xelatex",
        main_rel="main.tex",
        actions=actions or [],
        err_head=err_head,
    )


def _main(tmp_path: Path, text: str = _MAIN) -> None:
    (tmp_path / "main.tex").write_text(text, encoding="utf-8")


def test_fires_on_scanner_noop_verdict(tmp_path: Path) -> None:
    r"""phantom 判词 ``ifclose: noop`` 在账 → 注 ``\AtBeginDocument`` 保护块。"""
    _main(tmp_path)
    ok, note = if_phantom_protect(_ctx(tmp_path, [_NOOP_ENTRY]), None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\AtBeginDocument" in t
    assert (
        t.index("\\documentclass")
        < t.index("\\AtBeginDocument")
        < t.index("\\begin{document}")
    )


def test_family_completeness(tmp_path: Path) -> None:
    r"""9 cs 全覆盖: 逐名 ``\ifdefined`` 闸 + ``\protected\def`` let-wrap。"""
    _main(tmp_path)
    ok, _note = if_phantom_protect(_ctx(tmp_path, [_NOOP_ENTRY]), None, None, {})
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    for name in _FAMILY:
        assert f"\\ifdefined\\{name}" in t, name
        assert f"\\let\\TXLorig{name}\\{name}" in t, name
        assert f"\\protected\\def\\{name}{{\\TXLorig{name}}}" in t, name


def test_fires_after_literal_fix_residual(tmp_path: Path) -> None:
    r"""``ifclose: injected`` 判词也收: 字面部分已修, 复发 = 残余 phantom。"""
    _main(tmp_path)
    ok, note = if_phantom_protect(_ctx(tmp_path, [_INJECT_ENTRY]), None, None, {})
    assert ok, note


def test_decline_scanner_never_ran(tmp_path: Path) -> None:
    r"""账上无 ``unclosed_if_close`` 条目 (cond-skip/python3 缺位) → 不收。"""
    _main(tmp_path)
    before = (tmp_path / "main.tex").read_text(encoding="utf-8")
    ok, note = if_phantom_protect(_ctx(tmp_path), None, None, {})
    assert not ok
    assert "verdict" in note
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == before


def test_decline_scanner_crashed(tmp_path: Path) -> None:
    r"""扫描器 rc!=0 无 ``ifclose:`` 判词 → 字面亏格未排, 保守不收。"""
    _main(tmp_path)
    ok, note = if_phantom_protect(_ctx(tmp_path, [_CRASH_ENTRY]), None, None, {})
    assert not ok
    assert "verdict" in note


def test_decline_unrelated_actions_only(tmp_path: Path) -> None:
    r"""账上只有别家规则条目 → 扫描器未跑过, 不收。"""
    _main(tmp_path)
    other = {"round": 1, "rule": "font_sub_shim", "detail": "shimmed x.sty"}
    ok, note = if_phantom_protect(_ctx(tmp_path, [other]), None, None, {})
    assert not ok
    assert "verdict" in note


def test_decline_no_docclass_seam(tmp_path: Path) -> None:
    r"""无 ``\documentclass`` 缝 (plain/残稿) → ``\AtBeginDocument`` 未定义, 不注。"""
    _main(tmp_path, "\\title{T}\n\\maketitle\n\\bye\n")
    ok, note = if_phantom_protect(_ctx(tmp_path, [_NOOP_ENTRY]), None, None, {})
    assert not ok
    assert "docclass" in note


def test_idempotent_second_call(tmp_path: Path) -> None:
    """二入幂等：snippet 指纹在件即跳，文本不变。"""
    _main(tmp_path)
    ctx = _ctx(tmp_path, [_NOOP_ENTRY])
    ok, _note = if_phantom_protect(ctx, None, None, {})
    assert ok
    after = (tmp_path / "main.tex").read_text(encoding="utf-8")
    ok2, note2 = if_phantom_protect(ctx, None, None, {})
    assert not ok2
    assert "already" in note2
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == after


def test_params_cs_override(tmp_path: Path) -> None:
    """``params.cs`` 可收窄族面 —— 只注给定名。"""
    _main(tmp_path)
    ok, _note = if_phantom_protect(
        _ctx(tmp_path, [_NOOP_ENTRY]), None, None, {"cs": ["footnote"]}
    )
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\protected\\def\\footnote" in t
    assert "\\protected\\def\\bf" not in t


def test_registration_and_rule() -> None:
    """注册钉：TRANSFORM_FNS 直连 + rules/ 装载含同名规则且接线/序位一致。"""
    assert builtins.TRANSFORM_FNS["if_phantom_protect"] is if_phantom_protect
    rules = {r.id: r for r in load_ruleset().rules}
    rule = rules["if_phantom_protect"]
    assert rule.phase == "loop"
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "if_phantom_protect"
    cats = {c.get("category") for c in rule.when["any"]}
    assert cats == {"other", "incomplete_if"}
    assert 196.5 < rule.order < 200  # noqa: PLR2004 - 序位钉 (扫描双臂 196/196.5 之后)
