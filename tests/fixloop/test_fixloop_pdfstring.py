r"""pdfstring_cs_disarm 内建 —— moving-arg 数学 cs 犯 pdfstring 扫描缴械。

实证簇 (2607.10569 loop2+rt1 双池): acmart+hyperref+xelatex 下
``\title{... $\times$ ...}`` → ``\maketitle`` 触发 ``\pdfstringdef``
书签展开, 去 math shift 后做 `` `\<cs> `` 字母常量扫描, 多字符 cs
(`` `\times ``) 非法 → ``Improper alphabetic constant`` + intcalc
级联。修复 = 文档化逃生舱 ``\pdfstringdefDisableCommands{...\csname
\<name>\endcsname{} 空降格}`` ——排版侧零接触, ``\csname`` 形兼容肇事
名含 ``@`` (宿主 @=12 下裸 ``\def\@x{}`` 断名); 肇事名取日志
``<to be read again>`` 行, ``len>2`` 滤单字符合法形 (`` `\x `` TeX 不报)。
"""

from pathlib import Path

from texlate.compile.fixloop import builtins, load_ruleset
from texlate.compile.fixloop.builtins import pdfstring_cs_disarm
from texlate.compile.fixloop.engine import LoopCtx

_ERR_TIMES = (
    "! Improper alphabetic constant.\n"
    "<to be read again> \n"
    "                   \\times\n"
    "l.302 \\maketitle\n"
)
_MAIN = (
    "\\documentclass{acmart}\n"
    "\\title{A Regime $\\times$ Agent-Design Ablation}\n"
    "\\begin{document}\n"
    "\\maketitle\n"
    "\\end{document}\n"
)


def _ctx(tmp_path: Path, err_head: str = "") -> LoopCtx:
    return LoopCtx(
        wdir=tmp_path,
        engine_name="xelatex",
        main_rel="main.tex",
        runner=None,
        err_head=err_head,
    )


def _main(tmp_path: Path, text: str = _MAIN) -> None:
    (tmp_path / "main.tex").write_text(text, encoding="utf-8")


def test_fires_injects_guarded_disarm(tmp_path: Path) -> None:
    r"""err_head 命中 → docclass 缝后注 ``\ifdefined`` 闸 + ``\def\times{}``。"""
    _main(tmp_path)
    ok, note = pdfstring_cs_disarm(_ctx(tmp_path, _ERR_TIMES), None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifdefined\\pdfstringdefDisableCommands" in t
    assert (
        "\\pdfstringdefDisableCommands{\\expandafter\\def\\csname times\\endcsname{}}"
        in t
    )
    assert "\\fi" in t
    # 注入位：docclass 之后，\begin{document} 之前
    assert (
        t.index("\\documentclass")
        < t.index("\\ifdefined")
        < t.index("\\begin{document}")
    )


def test_offender_from_log_not_err_head(tmp_path: Path) -> None:
    r"""err_head 不含签名时回退 ``{stem}.log`` —— 肇事名仍命中。"""
    _main(tmp_path)
    (tmp_path / "main.log").write_text(_ERR_TIMES, encoding="utf-8")
    ok, note = pdfstring_cs_disarm(_ctx(tmp_path), None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\def\\csname times\\endcsname{}" in t


def test_multi_offenders_single_pass(tmp_path: Path) -> None:
    r"""一轮多 offender 全注: ``\times``+``\pdo`` 同段全收。"""
    _main(tmp_path)
    err = _ERR_TIMES + (
        "! Improper alphabetic constant.\n"
        "<to be read again> \n"
        "                   \\pdo\n"
    )
    ok, note = pdfstring_cs_disarm(_ctx(tmp_path, err), None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\def\\csname times\\endcsname{}" in t
    assert "\\def\\csname pdo\\endcsname{}" in t


def test_idempotent_second_call(tmp_path: Path) -> None:
    """二入幂等：首注 True, 再调 False 且文本不变。"""
    _main(tmp_path)
    ctx = _ctx(tmp_path, _ERR_TIMES)
    ok, _note = pdfstring_cs_disarm(ctx, None, None, {})
    assert ok
    after = (tmp_path / "main.tex").read_text(encoding="utf-8")
    ok2, note2 = pdfstring_cs_disarm(ctx, None, None, {})
    assert not ok2
    assert "already disarmed" in note2
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == after


def test_reject_no_offender(tmp_path: Path) -> None:
    r"""签名在但无 ``<to be read again> \<cs>`` → 不动文件。"""
    _main(tmp_path)
    before = (tmp_path / "main.tex").read_text(encoding="utf-8")
    ctx = _ctx(tmp_path, "! Improper alphabetic constant.\nl.1 x\n")
    ok, note = pdfstring_cs_disarm(ctx, None, None, {})
    assert not ok
    assert "no multi-char cs" in note
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == before


def test_reject_single_char_cs(tmp_path: Path) -> None:
    r"""``\x`` 单字符是合法字母常量形 (len>2 滤除) → 不收。"""
    _main(tmp_path)
    err = "! Improper alphabetic constant.\n<to be read again> \\x\nl.5 \\section{A}\n"
    ok, note = pdfstring_cs_disarm(_ctx(tmp_path, err), None, None, {})
    assert not ok
    assert "no multi-char cs" in note


def test_registration_and_rule() -> None:
    """注册钉：TRANSFORM_FNS 直连 + rules/ 装载含同名规则且接线一致。"""
    assert builtins.TRANSFORM_FNS["pdfstring_cs_disarm"] is pdfstring_cs_disarm
    rules = {r.id: r for r in load_ruleset().rules}
    rule = rules["pdfstring_cs_disarm"]
    assert rule.phase == "loop"
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "pdfstring_cs_disarm"
    assert rule.when["category"] == "syntax"
