"""L2 warning 分类侧合成边界钉 —— l2edges-scout-2026-09-17 可补清单 11 项。

全部经 ``parse_log_text`` 内联合成（无需真 log）：``NONERR_MSG_RE``
豁免（生产引擎按 docs/08 §4.1 带 ``-file-line-error``，``./x.tex:N:
LaTeX/Package/Class … Warning:`` 行每编译必走，回归即 n_errors 膨胀全判
dirty）、``file_not_found``/``rerun`` 零正向类、error ctx 帮助文本预筛
豁免、``eof_file`` 弹出窗界、Underfull/generic 归类、samples 留存上限、
sys_hits/redlines 去重、``parse_log`` OSError→log_missing、畸形码点
回落 missing_glyph。
"""

from pathlib import Path

from texlate.validate.l2 import parse_log, parse_log_text

WARN_SAMPLE_CAP = 5  # _MAX_WARN_SAMPLES 同值：每类 warning 样例留存上限
N_CITATION_WARNS = 7  # 超上限的同类 warning 条数
EOF_POP_WINDOW = 16  # _EOF_POP_WINDOW 同值：``)`` 弹出→错误打印最大行距
FNF_LINES = 3  # file_not_found 变体合成条数


def test_file_line_warning_lines_exempt() -> None:
    """scout#1　``file:line:`` 前缀 Warning 豁免——生产 ``-file-line-error``
    log 海量存在此形态；``NONERR_MSG_RE``（texlog 单源、fixloop 层同词素）
    锚定消息起点，豁免行照走 warning 归类、不计错。"""
    text = (
        "./main.tex:12: LaTeX Warning: Reference `r' undefined on input line 12.\n"
        "./sub.sty:3: Package foo Warning: bar\n"
        "./c.cls:7: Class my Warning: baz\n"
        "! Undefined control sequence.\n"
        "l.5 \\x\n"
    )
    v = parse_log_text(text)
    assert v.n_errors == 1
    assert v.first_error is not None
    assert "Undefined control sequence" in v.first_error.head
    wc = v.warnings.by_class
    assert v.warnings.total == 3  # noqa: PLR2004 - 两条 Warning 豁免行+一条泛型
    assert wc.get("reference") == 1  # file:line 前缀 Warning 仍入归类
    assert wc.get("generic") == 2  # noqa: PLR2004 - Package/Class Warning 无规则落 generic


def test_file_not_found_redline_positive() -> None:
    """scout#2　``file_not_found`` 红线类首个正向钉——``File `x' not found``
    warning 形态（非 ``!`` 错）归本类且每条入 redlines。"""
    text = (
        "Package pdftex.def Warning: File `fig.pdf' not found on input line 9.\n"
        "LaTeX Warning: File `x.png' not found on input line 5.\n"
    )
    v = parse_log_text(text)
    assert v.n_errors == 0
    assert v.warnings.by_class.get("file_not_found") == 2  # noqa: PLR2004 - 两行同类
    reds = [r for r in v.warnings.redlines if r.startswith("file_not_found")]
    assert len(reds) == 2  # noqa: PLR2004 - 每行各一条红线


def test_file_not_found_straight_quote_falls_generic() -> None:
    """scout#2 补　直引号 ``File 'x.png' not found`` 不中模式——TeX 消息系统
    固定 `` `x' `` 反引号开引；pattern 与 engine ``missing_graphic``/rules
    同口径只收反引号形，直引号形落 generic（钉实际严格度）。"""
    v = parse_log_text("LaTeX Warning: File 'x.png' not found on input line 5.\n")
    assert v.warnings.by_class.get("file_not_found") is None
    assert v.warnings.by_class.get("generic") == 1


def test_file_not_found_variants() -> None:
    """scout#3　``cannot open``/``Could not locate`` 备选同归 file_not_found；
    ``cannot find|open`` 是 markerless 硬 warning 形，裸行也归类。"""
    text = (
        "LaTeX Warning: cannot open file `data.dat' for reading.\n"
        "kpathsea: cannot open file for reading\n"  # 裸 markerless 形
        "Package hyperref Warning: Could not locate file `x.out'.\n"
    )
    v = parse_log_text(text)
    assert v.warnings.by_class.get("file_not_found") == FNF_LINES
    assert v.warnings.total == FNF_LINES
    reds = [r for r in v.warnings.redlines if r.startswith("file_not_found")]
    assert len(reds) == FNF_LINES


def test_could_not_locate_bare_not_markerless() -> None:
    """scout#3 补　``Could not locate`` 在归类 pattern 内但**不在**
    ``_MARKERLESS_WARN_RX`` 预筛——裸行（无 ``Warning:`` 标）整行跳过
    不计；与 ``cannot open`` 的 markerless 收录不对称，钉实际行为。"""
    v = parse_log_text("Could not locate file `x.out'.\n")
    assert v.warnings.total == 0


def test_rerun_positive_not_redline() -> None:
    """scout#4　``rerun`` 类首个正向钉——``may have changed``/``Rerun``
    触发；非红线类（不入 redlines，勿与 reference 前缀规则混淆）。"""
    v = parse_log_text(
        "LaTeX Warning: Label(s) may have changed. "
        "Rerun to get cross-references right.\n"
    )
    assert v.warnings.by_class.get("rerun") == 1
    assert v.warnings.total == 1
    assert v.warnings.redlines == []


def test_error_ctx_help_text_not_warning() -> None:
    """scout#5　error ctx 帮助文本豁免——``type `I\\font<same font id>…'``
    这类无 ``Warning:`` 标行曾被 font_subst 误吃；预筛先于规则：rule 形
    （``Some font shapes``）但无 warning 形的行同被挡。"""
    text = (
        "! Undefined control sequence.\n"
        "l.5 \\x\n"
        "The control sequence at the end of the top line\n"
        "of your error message was never \\def'ed. If you have\n"
        "misspelled it (e.g., `\\hobx'), type `I' and the correct\n"
        "spelling (e.g., `I\\hbox'). Otherwise just continue,\n"
        "and I'll forget about whatever was undefined.\n"
        "e.g., type `I\\font<same font id>=<substitute font id>'.\n"
        "Some font shapes were substituted silently\n"
    )
    v = parse_log_text(text)
    assert v.n_errors == 1
    assert v.warnings.total == 0
    assert v.warnings.by_class == {}


def _eof_log(gap: int) -> str:
    """``(./sub.tex`` 在第 2 行弹出，``gap`` 行填充后出 ``File ended`` 错。"""
    lines = [
        "(./main.tex",
        "(./sub.tex",
        "some text)",
        *[f"filler {n}" for n in range(gap)],
        "! File ended while scanning use of \\foo.",
        "l.9 \\foo",
    ]
    return "\n".join(lines) + "\n"


def test_eof_culprit_within_window() -> None:
    """scout#6a　弹出后 ≤``_EOF_POP_WINDOW``（含端点，行距 16）的
    ``File ended while scanning`` 错归因最近弹出文件。"""
    v = parse_log_text(_eof_log(EOF_POP_WINDOW - 1))
    assert v.n_errors == 1
    fe = v.first_error
    assert fe is not None
    assert fe.eof_file == "./sub.tex"


def test_eof_culprit_beyond_window() -> None:
    """scout#6b　弹出 >16 行才出 ``File ended`` → 不归因（防过归因）。"""
    v = parse_log_text(_eof_log(EOF_POP_WINDOW))
    assert v.n_errors == 1
    fe = v.first_error
    assert fe is not None
    assert fe.eof_file is None


def test_eof_no_attribution_for_non_eof_error() -> None:
    """scout#6c　相邻弹出 + 普通错 → 无 eof 归因——头判
    ``File ended while scanning``，不是"刚弹出就补"。"""
    text = "(./main.tex\n(./sub.tex\n)\n! Undefined control sequence.\nl.5 \\x\n"
    v = parse_log_text(text)
    assert v.n_errors == 1
    fe = v.first_error
    assert fe is not None
    assert fe.eof_file is None


def test_underfull_and_bare_warning_generic() -> None:
    """scout#7　Underfull 正向（markerless 硬 warning 形收 ``Over|Underfull
    \\[hv]box``）+ 裸 ``Xxx Warning:`` 行无规则命中落 generic。"""
    text = "Underfull \\vbox (badness 10000) detected at line 7\nFoo Warning: bar\n"
    v = parse_log_text(text)
    wc = v.warnings.by_class
    assert wc.get("overfull") == 1
    assert wc.get("generic") == 1
    assert v.warnings.total == 2  # noqa: PLR2004 - 两类各一


def test_warn_samples_capped_at_five() -> None:
    """scout#8　``samples`` 每类 ≤5——计数（by_class/total）精确不受留存
    上限影响。"""
    text = "\n".join(
        f"LaTeX Warning: Citation `ref{n}' on page 1 undefined on input line {n}."
        for n in range(N_CITATION_WARNS)
    )
    v = parse_log_text(text + "\n")
    assert v.warnings.by_class.get("citation") == N_CITATION_WARNS
    assert v.warnings.total == N_CITATION_WARNS
    assert len(v.warnings.samples["citation"]) == WARN_SAMPLE_CAP


def test_sys_hits_dedup_same_file() -> None:
    """scout#9a　同系统件 invalid_utf8 重复命中 → ``sys_hits`` 单条
    （``{cls}@{file}`` 去重），by_class/total 仍精确。"""
    text = (
        "(/usr/share/texmf-dist/tex/latex/foo/foo.sty\n"
        "Invalid UTF-8 byte or sequence at line 11 replaced by U+FFFD.\n"
        "Invalid UTF-8 byte or sequence at line 42 replaced by U+FFFD.\n"
        ")\n"
    )
    v = parse_log_text(text)
    assert v.warnings.by_class.get("invalid_utf8") == 2  # noqa: PLR2004 - 同件两条
    assert v.warnings.sys_hits == ["invalid_utf8@foo.sty"]
    assert not any("invalid_utf8" in r for r in v.warnings.redlines)


def test_redlines_dedup_identical_lines() -> None:
    """scout#9b　``redlines`` 按 ``{cls}: {line}`` 串去重——完全相同的
    缺字形行 ×2 只留一条，by_class 仍计 2。"""
    line = 'Missing character: There is no ; ("3B) in font cmr10!\n'
    v = parse_log_text(line * 2)
    assert v.warnings.by_class.get("missing_glyph") == 2  # noqa: PLR2004 - 同文两条
    assert len(v.warnings.redlines) == 1


def test_parse_log_directory_is_log_missing(tmp_path: Path) -> None:
    """scout#10　``parse_log`` 遇目录（``read_text`` → IsADirectoryError
    ⊂ OSError）→ ``log_missing`` verdict，不抛。"""
    v = parse_log(tmp_path)
    assert v.log_missing
    assert v.n_errors == 0


def test_malformed_codepoint_stays_missing_glyph() -> None:
    """scout#11　``("12)``/``("123)`` 短 hex 不中 ``("HEX)`` 4–6 位形 →
    码点不可解不触发 CJK/FFFD 细分，仍 ``missing_glyph`` 红线。"""
    text = (
        'Missing character: There is no X ("12) in font cmr10!\n'
        'Missing character: There is no Y ("123) in font cmr10!\n'
    )
    v = parse_log_text(text)
    assert v.warnings.by_class.get("missing_glyph") == 2  # noqa: PLR2004 - 两种短 hex 各一
    assert v.warnings.cjk_missing == 0
    reds = [r for r in v.warnings.redlines if r.startswith("missing_glyph")]
    assert len(reds) == 2  # noqa: PLR2004 - 不同行各一条
