"""L2 编译 log 解析测试 —— 真实 bench/work_compile 样例 + 合成 file:line: 格式。"""

from pathlib import Path

import pytest

from texlate.validate.l2 import parse_log, parse_log_text

WORK = Path(__file__).resolve().parents[1] / "bench" / "work_compile"

_ERR_LOG = WORK / "1810.04805" / "baseline" / "main.log"  # 21 个 ! 错误
_WARN_LOG = (
    WORK / "1511.06432" / "baseline" / "_tect_out" / "iclr2016_conference.log"
)  # tectonic 格式 + natbib citation warning
_CLEAN_LOG = WORK / "1512.03385" / "baseline" / "residual_v1_arxiv_release.log"  # 0 错
_CJK_LOG = WORK / "2203.02155" / "zh" / "neurips_2021.log"  # CJK 缺字形
_UTF8_LOG = WORK / "2501.14787" / "zh" / "_tect_out" / "main.log"  # Invalid UTF-8 红线

ERR_COUNT_MAIN = 21  # _ERR_LOG 实测 ! 行数
ERR_LINE_MAIN = 44  # 首错 l.NNN 源码行号
ERR_LINE_SUB = 12  # 合成样例第二处错误行号
CTX_MAX = 8  # 错误上下文留存上限（docs/08 §2.3）
TAIL_LEN = 30  # log 尾部留存行数
N_ERR_SYNTH = 2

NEED_LOGS = pytest.mark.skipif(
    not _ERR_LOG.is_file(), reason="bench/work_compile 重产物不在场"
)


@NEED_LOGS
def test_real_log_bang_count() -> None:
    v = parse_log(_ERR_LOG)
    assert not v.ok
    assert v.n_errors == ERR_COUNT_MAIN
    assert v.first_error is not None
    assert "Illegal unit" in v.first_error.head
    assert v.first_error.tex_line == ERR_LINE_MAIN  # ctx 内 l.44
    assert v.engine == "XeTeX"
    assert not v.log_missing


@NEED_LOGS
def test_real_log_first_error_ctx_and_stack() -> None:
    v = parse_log(_ERR_LOG)
    fe = v.first_error
    assert fe is not None
    assert len(fe.ctx) <= CTX_MAX
    assert any(f"l.{ERR_LINE_MAIN}" in ln for ln in fe.ctx)
    assert fe.file_stack  # (./main.tex 或包文件至少一层
    assert any(s.endswith((".tex", ".sty", ".cls")) for s in fe.file_stack)


@NEED_LOGS
def test_real_log_clean() -> None:
    v = parse_log(_CLEAN_LOG)
    assert v.ok
    assert v.n_errors == 0
    assert v.first_error is None


@NEED_LOGS
def test_real_log_warnings_classified() -> None:
    v = parse_log(_WARN_LOG)
    wc = v.warnings.by_class
    assert v.warnings.total > 0
    assert "citation" in wc  # natbib undefined citations


@NEED_LOGS
def test_real_log_cjk_missing_glyph_redline() -> None:
    v = parse_log(_CJK_LOG)
    assert v.warnings.cjk_missing > 0
    assert v.warnings.by_class.get("missing_glyph_cjk", 0) > 0
    assert any("missing_glyph_cjk" in r for r in v.warnings.redlines)


@NEED_LOGS
def test_real_log_invalid_utf8_redline() -> None:
    v = parse_log(_UTF8_LOG)
    assert v.warnings.by_class.get("invalid_utf8", 0) > 0
    assert any("invalid_utf8" in r for r in v.warnings.redlines)


def test_missing_log() -> None:
    v = parse_log("/nonexistent/path/x.log")
    assert v.log_missing
    assert v.n_errors == 0


def test_file_line_error_format() -> None:
    """-file-line-error 格式（生产引擎旗标，bench 语料未覆盖须合成）。"""
    text = """This is XeTeX, Version 3.141592653 (TeX Live 2026)
**main.tex
(./main.tex
LaTeX2e <2026-06-01>
./main.tex:44: Undefined control sequence.
l.44 \\foo{bar}

./sub/chap.tex:12: Missing $ inserted.
l.12 x=
"""
    v = parse_log_text(text)
    assert v.n_errors == N_ERR_SYNTH
    fe = v.first_error
    assert fe is not None
    assert fe.tex_file == "./main.tex"
    assert fe.tex_line == ERR_LINE_MAIN
    assert v.errors[1].tex_file == "./sub/chap.tex"
    assert v.errors[1].tex_line == ERR_LINE_SUB


def test_bang_and_file_line_mixed_no_double_count() -> None:
    """file:line: 行带 ! 前缀不重复计数。"""
    text = "./main.tex:5: ! Undefined control sequence.\nl.5 \\x\n! Another error.\nl.9 \\y\n"
    v = parse_log_text(text)
    assert v.n_errors == N_ERR_SYNTH


def test_warning_classes_synthetic() -> None:
    text = """LaTeX Warning: Citation `a' on page 1 undefined on input line 3.
LaTeX Warning: Reference `r' on page 2 undefined on input line 9.
LaTeX Font Warning: Font shape `TU/ptm/m/n' undefined
Missing character: There is no 这 ("8FD9) in font ptmr8t!
Overfull \\hbox (12.0pt too wide) in paragraph at lines 1--2
Package rerunfilecheck Info: File `x.out' has not changed.
LaTeX Warning: There were undefined references.
"""
    v = parse_log_text(text)
    wc = v.warnings.by_class
    assert wc.get("citation") == 1
    assert wc.get("reference") == 2  # noqa: PLR2004 - 两类 reference 行各一
    assert wc.get("font_subst") == 1
    assert wc.get("missing_glyph_cjk") == 1
    assert wc.get("overfull") == 1
    assert "rerunfilecheck Info" not in str(v.warnings.samples)  # Info 非 warning


def test_tail_retained() -> None:
    body = "\n".join(f"line {i}" for i in range(100)) + "\n! boom\n"
    v = parse_log_text(body)
    assert len(v.tail) == TAIL_LEN
    assert v.n_errors == 1


def test_verdict_serialization() -> None:
    v = parse_log_text(
        "! err\nl.1 x\nLaTeX Warning: Reference `r' undefined on input line 1.\n"
    )
    d = v.to_dict()
    assert d["n_errors"] == 1
    assert d["first_error"]["tex_line"] == 1
    assert d["warnings"]["total"] == 1
    assert "FAIL" in str(v)
