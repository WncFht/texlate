r"""slot_arg_revert tcbopt 机位 —— tcb kv 组 (2026-09-20)。

``tcolorbox``/``tcblisting`` env 与 ``\newtcblisting``/``\NewTColorBox``
def 尾的多行嵌套 kv 组 zh 化 → ``_ARGB`` 平衡组捕获 + kvnl ident
整组换回; kv 形 (``=``/``,``/``#``) 门控兜底拒收散文组与裸键站。
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


def test_tcbopt_env_multiline_group_reverted(tmp_path: Path) -> None:
    r"""2609.20423 实证: ``\begin{tcblisting}{multi-line nested kv}``
    整组 zh 化 → ``/tcb/这是译文`` pgfkeys 错; ``_ARGB`` 平衡组 (≤2
    层嵌套+跨行) 捕获 + kvnl ident 整组换回; 体内散文保 zh。"""
    work, base = _trees(tmp_path)
    src = (
        "\\begin{tcblisting}{\n"
        "  enhanced,\n"
        "  breakable,\n"
        "  listing options={\n"
        "    basicstyle=\\ttfamily\\footnotesize,\n"
        "    breaklines=true,\n"
        "  }\n"
        "}\n"
        "body\n\\end{tcblisting}\n"
    )
    zh = (
        "\\begin{tcblisting}{  这是译文这是译文={  这是译文=\\ttfamily"
        "\\footnotesize,  这是译文  } }\n"
        "正文\n\\end{tcblisting}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    out = (work / "main.tex").read_text(encoding="utf-8")
    assert out.startswith(src.split("body", maxsplit=1)[0])  # 整组换回 baseline 字节
    assert "正文\n\\end{tcblisting}" in out  # env 体内散文保 zh


def test_tcbopt_opt_head_reverted(tmp_path: Path) -> None:
    """``\\begin{tcolorbox}[multi-line kv]`` ``[]`` 头形 zh 化 → 还原。"""
    work, base = _trees(tmp_path)
    src = "\\begin{tcolorbox}[\n  enhanced,\n  colback=red!5,\n]\nx\n\\end{tcolorbox}\n"
    zh = "\\begin{tcolorbox}[这是译文这是译文]\nx\n\\end{tcolorbox}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_tcbopt_def_tail_reverted(tmp_path: Path) -> None:
    """``\\newtcblisting{name}[n]{kv}``/``\\newtcolorbox`` def 尾选项
    组 zh 化 → 整组还原 (``#n`` 形参位同域, 2609.19556 def 站实证)。"""
    work, base = _trees(tmp_path)
    src = (
        "\\newtcblisting{promptbox}[2]{\n"
        "  enhanced, title=#1,\n"
        "  listing options={breaklines=true},\n"
        "  #2\n"
        "}\n"
        "\\newtcolorbox{mybox}[2][red]{colback=#2, title=#1}\n"
        "\\NewTColorBox{xbox}{m O{red}}{colback=#2}\n"
    )
    zh = (
        "\\newtcblisting{promptbox}[2]{\n"
        "  这是译文, title=#1,\n"
        "  listing options={这是译文=true},\n"
        "  #2\n"
        "}\n"
        "\\newtcolorbox{mybox}[2][red]{这是译文这是译文}\n"
        "\\NewTColorBox{xbox}{m O{red}}{这是译文}\n"
    )
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


def test_tcbopt_flat_arg_dedup(tmp_path: Path) -> None:
    """tcb env 单行平参 —— envarg 严格 ident 与 tcbopt kvnl 双面同位
    重扫去重, 行为不变 (``listing only`` 裸键 + ``,`` kv 形)。"""
    work, base = _trees(tmp_path)
    src = "\\begin{tcblisting}{listing only, breakable}\nx\n\\end{tcblisting}\n"
    zh = "\\begin{tcblisting}{这是译文这是译文}\nx\n\\end{tcblisting}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert ok
    assert (work / "main.tex").read_text(encoding="utf-8") == src


# ------------------------------------- 负向: 散文组/裸键/非 tcb 面


def test_tcbopt_prose_group_not_reverted(tmp_path: Path) -> None:
    r"""``\begin{tcolorbox}`` 后散文 ``{multi\nline prose}`` 组 ——
    kvnl 白名单能 fullmatch 纯 ASCII 散文, kv 形断言 (``=``/``,``/
    ``#``) 兜底拒收。"""
    work, base = _trees(tmp_path)
    src = "\\begin{tcolorbox}\n{Dear reviewer\nwe thank you}\n"
    zh = "\\begin{tcolorbox}\n{尊敬的审稿人\n我们感谢您}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "main.tex").read_text(encoding="utf-8") == zh


def test_tcbopt_bare_key_not_reverted(tmp_path: Path) -> None:
    """``{listing only}`` 裸键站 —— 无 ``=``/``,``/``#`` kv 形宁可
    漏收 (错位 revert 比不复原更糟)。"""
    work, base = _trees(tmp_path)
    src = "\\begin{tcblisting}{listing only}\nx\n\\end{tcblisting}\n"
    zh = "\\begin{tcblisting}{这是译文这是译文}\nx\n\\end{tcblisting}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert not ok


def test_tcbopt_non_tcb_env_untouched(tmp_path: Path) -> None:
    """非 tcb env 跨行 kv 形组 —— envarg ``_ARGNL`` 捕到但严格
    ident 拒 (空格/换行), tcbopt 名单不盖 → 不还原。"""
    work, base = _trees(tmp_path)
    src = "\\begin{myenv}{key=value\nfoo=bar}\nx\n\\end{myenv}\n"
    zh = "\\begin{myenv}{这是译文=这是译文\n这是译文=这是译文}\nx\n\\end{myenv}\n"
    _pair(work, base, "main.tex", src, zh)
    ok, _note = _run(work, base)
    assert not ok
    assert (work / "main.tex").read_text(encoding="utf-8") == zh
