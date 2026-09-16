"""logparse — ErrReport 提取 + Taxonomy 分类单测 (合成 log)。

双错误格式: `^!` (spike 原义) + `file:line:` (impl xelatex -file-line-error);
tail/warnings scope 与 undefined_cs→pdftex_prim subclassify 逐条覆盖。
"""

from pathlib import Path

import pytest

from texlate.compile.fixloop import load_ruleset
from texlate.compile.fixloop.logparse import parse_log, parse_text

RS = load_ruleset()
TAX = RS.taxonomy
WARN = RS.warn_patterns


def classify(text: str, *, timed_out: bool = False) -> tuple[str | None, str | None]:
    return TAX.classify(parse_text(text, WARN), timed_out=timed_out)


# ---------------------------------------------------------------- ErrReport
def test_bang_and_ctx_and_line_no() -> None:
    rep = parse_text("pre\n! Undefined control sequence.\nl.12 \\foo\npost\n", WARN)
    assert rep.n_bang == 1
    assert rep.first == "! Undefined control sequence."
    assert "l.12" in rep.ctx
    assert rep.line_no == 12  # noqa: PLR2004 - 样本行号
    assert "post" in rep.tail


def test_file_line_error_format_counts() -> None:
    # impl xelatex 命令行带 -file-line-error: 错误是 path:line: 无 '!' 前缀
    rep = parse_text("./main.tex:5: Undefined control sequence.\nl.5 \\foo\nok\n", WARN)
    assert rep.n_bang == 1
    assert rep.first == "./main.tex:5: Undefined control sequence."


def test_file_line_warning_not_error() -> None:
    # 同格式的 Warning 行不算错误, 否则 clean 门 (n_bang==0) 永不通过
    rep = parse_text(
        "./main.tex:5: LaTeX Warning: Reference `x' undefined\n./main.tex:9: Package foo Warning: bar\n",
        WARN,
    )
    assert rep.n_bang == 0
    assert rep.first is None


def test_file_stack_tracked() -> None:
    rep = parse_text(
        "(./main.tex\n(./sub/chap.tex\n! Package soul Error: Reconstruction failed.\n",
        WARN,
    )
    assert rep.file_stack == ["./main.tex", "./sub/chap.tex"]


def test_parse_log_missing_path() -> None:
    rep = parse_log(None, WARN)
    assert rep.n_bang == 0
    assert rep.first is None
    assert rep.tail == ""


def test_parse_log_reads_file(tmp_path: Path) -> None:
    p = tmp_path / "main.log"
    p.write_text("x\n! Emergency stop.\n")
    rep = parse_log(p, WARN)
    assert rep.n_bang == 1


def test_warn_patterns_scanned() -> None:
    rep = parse_text("Missing character: There is no (U+FFFD) in font cmr10\n", WARN)
    assert "invalid_utf8" in rep.warnings
    assert "missing_char" in rep.warnings


# ---------------------------------------------------------------- taxonomy: head scope
@pytest.mark.parametrize(
    ("log", "cat", "pay"),
    [
        ("! LaTeX Error: File `import.sty' not found.", "missing_file", "import.sty"),
        ("! I can't find file `foo.sty'.", "missing_file", "foo.sty"),
        (
            "! Font \\iclrtenhv=phvb at 8.0pt not loadable: Metric (TFM) file",
            "missing_tfm",
            "phvb",
        ),
        # (\S+) 连句号一起吃进 payload —— spike 原样语义, 不修剪
        ("! Cannot use XeTeXglyph with ptmr8c.", "xetexglyph_tfm", "ptmr8c."),
        (
            '! xdvipdfmx:fatal: Cannot proceed without .vf or "physical" font',
            "missing_pfb",
            None,
        ),
        (
            '! Package fontspec Error: The font "FandolSong-Regular" cannot be found',
            "fontspec_missing",
            "FandolSong-Regular",
        ),
        ("! Illegal unit of measure (pt inserted).", "illegal_unit", None),
        (
            "! LaTeX Error: Option clash for package hyperref.",
            "option_clash",
            "hyperref",
        ),
        (
            "! LaTeX Error: Command \\c@thm already defined.",
            "already_def",
            "c@thm",
        ),
        ("! Package soul Error: Reconstruction failed.", "soul_err", None),
        ("! Not a letter.\nl.3 \\hyphenation{中-文}", "hyphenation", None),
        ("! Package minted Error: frozencache file missing.", "minted_froz", None),
        (
            "! LaTeX2e command \\usepackage in LaTeX 2.09 document.",
            "latex209",
            None,
        ),
        # v2: undefined_cs payload 改抓 l.N 行末 cs 名 (供 polyfill/shadow 定位)
        ("! Undefined control sequence.\nl.5 \\foo", "undefined_cs", "foo"),
        # 2026-09-16: inputenc 拒载 Unicode 引擎 (inputenc.sty:164)
        (
            "! Package inputenc Error: inputenc is not designed for xetex or luatex.",
            "inputenc_unicode",
            None,
        ),
        (
            "./main.tex:12: Package inputenc Error: inputenc is not designed for xetex or lua",
            "inputenc_unicode",
            None,
        ),
        # 2026-09-16: Extra } 族归 syntax (原落 other 兜底)
        ("! Extra }, or forgotten $.", "syntax", None),
        ("! Extra \\fi.", "syntax", None),
        ("! Forgotten \\endgroup.", "syntax", None),
        ("! TeX capacity exceeded, sorry.", "capacity", None),
        ("! Emergency stop.", "emergency", None),
        (
            "! LaTeX Error: \\begin{foo} on input line 5 ended by \\end{bar}.",
            "env_mismatch",
            None,
        ),
        ("! Missing $ inserted.", "syntax", None),
        ("! Something utterly bizarre", "other", None),
    ],
)
def test_head_categories(log: str, cat: str, pay: str | None) -> None:
    assert classify(log) == (cat, pay)


def test_undefined_cs_subclassifies_pdftex_prim() -> None:
    cat, pay = classify("! Undefined control sequence.\nl.5 \\pdfoutput=1")
    assert (cat, pay) == ("pdftex_prim", "pdfoutput")


def test_undefined_cs_blank_lineno_variant() -> None:
    """1909.05039 实证: l.N 行空白时取展开上下文尾行的末位 cs。"""
    log = (
        "! Undefined control sequence.\n"
        "\\__hook shipout/firstpage ...geHook \\headerps@out \n"
        "                                                  {/burl@stx null def /BU.S ...\n"
        "l.196 \n"
    )
    cat, pay = classify(log)
    assert (cat, pay) == ("undefined_cs", "headerps@out")


def test_undefined_cs_blank_lineno_pdftex_subclass() -> None:
    """空 l.N 变体同样走 pdftex_prim 细分。"""
    log = "! Undefined control sequence.\n\\foo \\pdfoutput \nl.9 \n"
    cat, pay = classify(log)
    assert (cat, pay) == ("pdftex_prim", "pdfoutput")


def test_undefined_cs_no_subclassify_when_absent() -> None:
    cat, _pay = classify("! Undefined control sequence.\nl.5 \\mycs")
    assert cat == "undefined_cs"


def test_first_error_wins_order() -> None:
    # 两个 '!' 行: 只有首个进 head —— 第二个错误不影响分类
    cat, _ = classify("! Illegal unit of measure.\n! Package soul Error: x\n")
    assert cat == "illegal_unit"


# ---------------------------------------------------------------- taxonomy: tail scope
def test_tail_missing_file_with_guard() -> None:
    cat, pay = classify("lots of text\nFile `epsf.sty' not found.\nEnter file name:\n")
    assert (cat, pay) == ("missing_file", "epsf.sty")


def test_tail_enter_file_name_alone() -> None:
    cat, pay = classify("blah\nEnter file name: \n")
    assert (cat, pay) == ("missing_file", None)


def test_tail_latex209() -> None:
    cat, _ = classify("...\nThis is a \\documentstyle era document\n")
    assert cat == "latex209"


def test_head_beats_tail() -> None:
    # 有 '!' 行时 tail 段不评估; 把 tail 标记推到 ctx (8行) 范围外
    log = (
        "! Emergency stop.\n"
        + "pad line\n" * 12
        + "File `x.sty' not found.\nEnter file name:"
    )
    cat, _ = classify(log)
    assert cat == "emergency"


# ---------------------------------------------------------------- taxonomy: warnings/timeout/clean
def test_warn_utf8_when_no_bang() -> None:
    cat, _ = classify("Missing character: There is no (U+FFFD) in font cmr10\n")
    assert cat == "warn_utf8"


def test_warn_utf8_not_reached_when_bang() -> None:
    # 有 '!' 行 → head 命中优先, warning 不升级
    cat, _ = classify(
        "! Package soul Error: x\nMissing character: There is no (U+FFFD) in font\n"
    )
    assert cat == "soul_err"


def test_timeout_overrides() -> None:
    cat, _ = classify("! Emergency stop.\n", timed_out=True)
    assert cat == "timeout"


def test_clean_log() -> None:
    cat, pay = classify(
        "This is pdfTeX, Version 3\nOutput written on main.pdf (1 page).\n"
    )
    assert (cat, pay) == ("clean", None)
