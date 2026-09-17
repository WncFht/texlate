"""L2 编译 log 解析测试 —— tests/fixtures/ 入库真 log 常跑 + bench/work_compile 大样例独例 + 合成 file:line: 格式。"""

from pathlib import Path

import pytest

from texlate.validate.l2 import parse_log, parse_log_text

WORK = Path(__file__).resolve().parents[1] / "bench" / "work_compile"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# 入库真 log（裁自 bench/results/stagerun-loop1-2026-09-16/work/，本机绝对路径归一为 ./）：
# 干净 clone 也必跑，不得加 skip 门
_MISSING_FILE_LOG = (
    FIXTURES / "xelatex-missing-file.log"
)  # 0707.0128: File `setstack.sty' not found → Emergency stop
_FILELINE_LOG = (
    FIXTURES / "xelatex-fileline-syntax.log"
)  # 0707.0382: file:line:error 格式 Missing \begin{document}

_ERR_LOG = WORK / "1810.04805" / "baseline" / "main.log"  # 21 个 ! 错误

ERR_COUNT_MAIN = 21  # _ERR_LOG 实测 ! 行数
ERR_LINE_MAIN = 44  # 首错 l.NNN 源码行号
ERR_LINE_SUB = 12  # 合成样例第二处错误行号
CTX_MAX = 8  # 错误上下文留存上限（docs/08 §2.3）
TAIL_LEN = 30  # log 尾部留存行数
N_ERR_SYNTH = 2
N_ERR_FIXTURE = 2  # 两条 fixture 各 2 错：! 主错 + file:line Emergency stop
FIXTURE_ESTOP_LINE = 31  # missing-file fixture 的 file:line Emergency stop 行号
FILELINE_ERR_LINE = 24  # fileline fixture 首错 ./AMSbsy.sty:24

# 唯一残留 gated 面：``^!`` 格式错的 tex_line 走 ctx ``l.NNN`` 兜底
# （``_tex_line_from_ctx``）——fixtures/logs/manifest.json 全部
# first_error.tex_line 均出自 ``file:line:`` 格式（``^!`` 首错一律 null），
# 此归因路径无入库件覆盖，仍需 bench 重产物在场才跑。
NEED_ERR_LOG = pytest.mark.skipif(
    not _ERR_LOG.is_file(),
    reason="bench/work_compile 重产物不在场（l.N ctx→tex_line 独例）",
)


@NEED_ERR_LOG
def test_real_log_bang_count() -> None:
    v = parse_log(_ERR_LOG)
    assert not v.ok
    assert v.n_errors == ERR_COUNT_MAIN
    assert v.first_error is not None
    assert "Illegal unit" in v.first_error.head
    assert v.first_error.tex_line == ERR_LINE_MAIN  # ctx 内 l.44——^! 格式唯一锚
    assert v.engine == "XeTeX"
    assert not v.log_missing


def test_fixture_missing_file_log() -> None:
    """入库真 log：File not found ! 错 + file:line Emergency stop 双格式共存。"""
    v = parse_log(_MISSING_FILE_LOG)
    assert not v.ok
    assert not v.log_missing
    assert v.n_errors == N_ERR_FIXTURE
    assert v.engine == "XeTeX"
    fe = v.first_error
    assert fe is not None
    assert "File `setstack.sty' not found" in fe.head
    assert fe.tex_line is None  # missing-file ! 错无 l.N 锚
    assert len(fe.ctx) <= CTX_MAX
    assert fe.file_stack
    assert fe.file_stack[0].endswith("GWDAW11_MLDC1_proc.tex")
    second = v.errors[1]
    assert second.tex_file == "./GWDAW11_MLDC1_proc.tex"
    assert second.tex_line == FIXTURE_ESTOP_LINE
    assert v.tail[-1] == "No pages of output."


def test_fixture_fileline_syntax_log() -> None:
    """入库真 log：file:line:error 格式 + 深层 file_stack + l.N ctx 锚。"""
    v = parse_log(_FILELINE_LOG)
    assert not v.ok
    assert not v.log_missing
    assert v.n_errors == N_ERR_FIXTURE
    assert v.engine == "XeTeX"
    fe = v.first_error
    assert fe is not None
    assert fe.tex_file == "./AMSbsy.sty"
    assert fe.tex_line == FILELINE_ERR_LINE
    assert "Missing \\begin{document}" in fe.head
    assert any(f"l.{FILELINE_ERR_LINE}" in ln for ln in fe.ctx)
    assert fe.file_stack == (
        "./gregory.tex",
        "./iaus.cls",
        "./upmath.sty",
        "./AMSbsy.sty",
    )
    assert v.tail[-1] == "No pages of output."


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


_UTF8_WARN = "Invalid UTF-8 byte or sequence at line 11 replaced by U+FFFD.\n"


def test_invalid_utf8_attributed_by_file(tmp_path: Path) -> None:
    """invalid_utf8 红线按产生文件归因：texmf 系统件降 sys_hits 观察项，
    工程件照计 redline；观察计数（by_class/total）不降。"""
    log = (
        "(./main.tex\n"
        "(/usr/share/texmf-dist/tex/latex/algorithms/algorithm.sty\n"
        f"{_UTF8_WARN}"
        "Package: algorithm 2009/08/24 v0.1\n"
        ") body\n"
        "(./sec.tex\n"
        f"{_UTF8_WARN}"
        "))\n"
    )
    v = parse_log_text(log, project_root=tmp_path)
    assert v.warnings.by_class.get("invalid_utf8", 0) == 2  # noqa: PLR2004 - 两源各一
    assert v.warnings.sys_hits == ["invalid_utf8@algorithm.sty"]
    reds = [r for r in v.warnings.redlines if "invalid_utf8" in r]
    assert len(reds) == 1  # 仅 ./sec.tex 工程源那条


def test_invalid_utf8_bare_name_no_root_conservative() -> None:
    """root 缺席时 tectonic 式裸名不可归因 → 保守归工程，红线保留。"""
    v = parse_log_text(f"(lineno.sty\n{_UTF8_WARN})\n")
    assert any("invalid_utf8" in r for r in v.warnings.redlines)
    assert v.warnings.sys_hits == []


def test_invalid_utf8_usertree_under_root_is_sys(tmp_path: Path) -> None:
    """fixloop usertree 落 wdir/_texmf——root 之内仍是系统语义。"""
    log = f"({tmp_path}/_texmf/home/tex/latex/foo/foo.sty\n{_UTF8_WARN})\n"
    v = parse_log_text(log, project_root=tmp_path)
    assert v.warnings.sys_hits == ["invalid_utf8@foo.sty"]
    assert not any("invalid_utf8" in r for r in v.warnings.redlines)


def test_invalid_utf8_dos_eps_demoted(tmp_path: Path) -> None:
    """dos_eps_skipped 件（DOS 魔数二进制 EPS，normalize 原样保留）降 sys
    ——engine ``_scan_error_lines`` 同口径；graphic 打开帧须补真名归因，
    否则归因落父 .tex 误报工程红线。"""
    (tmp_path / "fig.eps").write_bytes(b"\xc5\xd0\xd3\xc6" + b"\x00" * 28)
    log = f"(./main.tex\n(./fig.eps\n{_UTF8_WARN}))\n"
    v = parse_log_text(log, project_root=tmp_path)
    assert v.warnings.sys_hits == ["invalid_utf8@fig.eps(dos-eps)"]
    assert not any("invalid_utf8" in r for r in v.warnings.redlines)
    # 普通文本 eps（%!PS 头）仍属工程件——红线照计
    (tmp_path / "fig2.eps").write_bytes(b"%!PS-Adobe-3.0 EPSF-3.0\n")
    v2 = parse_log_text(f"(./fig2.eps\n{_UTF8_WARN})\n", project_root=tmp_path)
    assert any("invalid_utf8" in r for r in v2.warnings.redlines)
    assert v2.warnings.sys_hits == []


# ---------------------------------------------------------------- 审计修复面


def test_missing_char_uplus_format_cjk() -> None:
    """fontspec 时代 ``(U+8BD1)`` 缺字形：归 missing_glyph_cjk 且入红线——
    只认 ``("HEX)`` 旧格式会漏掉新工具链全部 CJK 缺字。"""
    log = "Missing character: There is no 译 (U+8BD1) in font [lmroman10-regular]:mapping=tex-text;\n"
    v = parse_log_text(log)
    assert v.warnings.by_class.get("missing_glyph_cjk") == 1
    assert v.warnings.cjk_missing == 1
    assert any("missing_glyph_cjk" in r for r in v.warnings.redlines)


def test_missing_char_fffd_redline() -> None:
    """``(U+FFFD)`` 缺字 = invalid_utf8 排版产物——§4.3 具名红线。"""
    log = "Missing character: There is no (U+FFFD) in font cmr10!\n"
    v = parse_log_text(log)
    assert v.warnings.by_class.get("fffd_glyph") == 1
    assert any("fffd_glyph" in r for r in v.warnings.redlines)


def test_missing_char_non_cjk_redline() -> None:
    """非 CJK 缺字形同入红线——judge ``missing_chars`` 对全部缺字形判
    dirty（§4.3 渲染检查要求 Missing character 计数==0）。"""
    log = 'Missing character: There is no ; ("3B) in font cmr10!\n'
    v = parse_log_text(log)
    assert v.warnings.by_class.get("missing_glyph") == 1
    assert v.warnings.cjk_missing == 0
    assert any("missing_glyph" in r for r in v.warnings.redlines)


def test_missing_char_fffd_quote_form_redline() -> None:
    """老 TL ``("FFFD)`` 引号形缺字同挂 ffd_glyph 红线——与 ``(U+FFFD)``
    新形并吃（码点形态随引擎代际分叉，corpus 两形并存）。"""
    v = parse_log_text('Missing character: There is no ("FFFD) in font cmr10!\n')
    assert v.warnings.by_class.get("fffd_glyph") == 1
    assert any("fffd_glyph" in r for r in v.warnings.redlines)


def test_file_line_error_non_tex_ext() -> None:
    """``file:line:`` 错误不限 tex 系扩展名——``.pdf_t``/``.eps``/``.lbx``
    等非白名单扩展名行同样是真错误（loop1 语料 7814 log 全扫：白名单口径
    漏 586 行真错 / 13 log，其中 3 例整体翻转 ok=True 假干净）。"""
    text = "./fig/diag.pdf_t:7: Undefined control sequence.\nl.7 \\foo\n"
    v = parse_log_text(text)
    assert v.n_errors == 1
    fe = v.first_error
    assert fe is not None
    assert fe.tex_file == "./fig/diag.pdf_t"
    assert fe.tex_line == 7  # noqa: PLR2004 - file:line: 提取的样本行号
