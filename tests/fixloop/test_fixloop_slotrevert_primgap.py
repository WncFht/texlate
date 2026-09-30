r"""slot_arg_revert primgap 机位 —— 原语 pre-{ gap (2026-09-20)。

``\vadjust pre{..}``/``\leaders\hbox to <dimen>{..}`` 原语 cs 与
``{``-组之间的 keyword/dimen gap 被 zh 化 → 序号对齐还原; 计数分歧时
unique-src gap 值广播到全部 CJK gap, 多值分歧整跳。
"""

from pathlib import Path

from _fixloopkit import mk_ctx

from texlate.compile.fixloop.builtins import slot_arg_revert


def _trees(root: Path) -> tuple[Path, Path]:
    """wdir + baseline 双子树 —— baseline 必须在 wdir 外。"""
    work, base = root / "work", root / "baseline"
    work.mkdir()
    base.mkdir()
    return work, base


def _pair(work: Path, base: Path, name: str, src: str, zh: str) -> None:
    (base / name).write_text(src, encoding="utf-8")
    (work / name).write_text(zh, encoding="utf-8")


def _run(work: Path, base: Path) -> tuple[bool, str]:
    return slot_arg_revert(mk_ctx(work), None, None, {"baseline_dir": str(base)})


def test_primgap_vadjust_reverted(tmp_path: Path) -> None:
    """2609.19815 实证: ``\\vadjust 这是译文{\\vskip 1pt}`` —— CJK 落在
    原语 cs 与 ``{``-组之间 (``pre`` keyword 被译), 3↔3 序号还原。"""
    work, base = _trees(tmp_path)
    src = (
        "$r^2$\\vadjust pre{\\vskip 1pt}\n"
        "$s^2$\\vadjust pre{\\vskip 1pt}\n"
        "$t^2$\\vadjust pre{\\vskip 1pt}\n"
    )
    zh = (
        "$r^2$\\vadjust 这是译文{\\vskip 1pt}\n"
        "$s^2$\\vadjust 这是译文{\\vskip 1pt}\n"
        "$t^2$\\vadjust 这是译文{\\vskip 1pt}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_primgap_leaders_broadcast(tmp_path: Path) -> None:
    """2609.20633 实证: baseline ``\\leaders\\hbox to .55em{...}`` 只在
    ``\\tocdots`` def 站 ×1, zh 展开把字面量倍增到调用站 → 计数分歧,
    unique-src ``\\hbox to .55em`` 广播到全部 CJK gap; def 站 zh 双侧
    一致不动, 无关 ``\\hbox`` 站不碰。"""
    work, base = _trees(tmp_path)
    src = (
        "\\newcommand{\\tocdots}{\\leaders\\hbox to .55em{\\hfil.\\hfil}\\hfill}\n"
        "\\newcommand{\\tocmain}[1]{#1 \\tocdots}\n"
        "\\tocmain{Alpha}\n\\tocmain{Beta}\n"
    )
    zh = (
        "\\newcommand{\\tocdots}{\\leaders\\hbox to .55em{\\hfil.\\hfil}\\hfill}\n"
        "\\newcommand{\\tocmain}[1]{#1 \\tocdots}\n"
        "条目甲 \\leaders\\hbox 这是译文{\\hfil.\\hfil}\\hfill\n"
        "条目乙 \\leaders\\hbox 这是译文{\\hfil.\\hfil}\\hfill\n"
        "条目丙 \\leaders\\hbox 这是译文{\\hfil.\\hfil}\\hfill\n"
        "\\hbox to\\texlate@floatwidth{injected}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, note = _run(work, base)
    assert ok
    assert "broadcast" in note
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert "这是译文" not in out
    for tag in "甲乙丙":
        assert f"条目{tag} \\leaders\\hbox to .55em{{\\hfil.\\hfil}}\\hfill" in out
    assert "\\leaders\\hbox to .55em" in out.splitlines()[0]  # def 站原样
    assert "\\hbox to\\texlate@floatwidth{injected}" in out  # 非 CJK gap 不动


def test_primgap_multi_src_values_skip(tmp_path: Path) -> None:
    """src gap 多值 (``pre``/``to .55em``) 遇计数分歧 → 不广播整跳。"""
    work, base = _trees(tmp_path)
    src = "\\vadjust pre{\\vskip 1pt}\n\\hbox to .55em{x}\n"
    zh = (
        "\\vadjust 这是译文{\\vskip 1pt}\n"
        "\\hbox 这是译文{x}\n"
        "\\vadjust 这是译文{\\vskip 1pt}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, note = _run(work, base)
    assert not ok
    assert "primgap(2!=3)" in note
    assert (work / "main.tex").read_text(encoding="utf-8") == zh


def test_primgap_non_cjk_gap_untouched(tmp_path: Path) -> None:
    """zh gap 相异但零 CJK (``to 4em`` vs ``to 3em`` ASCII 改动) → 不动。"""
    work, base = _trees(tmp_path)
    _pair(
        work,
        base,
        "main.tex",
        "\\vadjust pre{\\vskip 1pt}\n\\hbox to 3em{x}\n",
        "\\vadjust pre{\\vskip 1pt}\n\\hbox to 4em{x}\n",
    )
    ok, _note = _run(work, base)
    assert not ok
    assert "\\hbox to 4em{x}" in (work / "main.tex").read_text(encoding="utf-8")


def test_primgap_empty_src_gap_skip(tmp_path: Path) -> None:
    """``\\hbox{`` → ``\\hbox 这是译文{`` 形: 空 gap 非 ident → 不还原
    (strip 臂有意不做 —— 丢 ``to <dimen>`` 语义, 仅证不误伤)。"""
    work, base = _trees(tmp_path)
    _pair(work, base, "main.tex", "\\hbox{x}\n", "\\hbox 这是译文{x}\n")
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "main.tex").read_text(encoding="utf-8") == "\\hbox 这是译文{x}\n"


def test_primgap_idempotent(tmp_path: Path) -> None:
    """改写后重跑 → gap 双侧一致, False 空转。"""
    work, base = _trees(tmp_path)
    _pair(
        work,
        base,
        "main.tex",
        "\\vadjust pre{\\vskip 1pt}\n",
        "\\vadjust 这是译文{\\vskip 1pt}\n",
    )
    ok, _note = _run(work, base)
    assert ok
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "main.tex").read_text(
        encoding="utf-8"
    ) == "\\vadjust pre{\\vskip 1pt}\n"
