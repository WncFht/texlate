"""judge.py 的单测（verdict 构成/信号归因/CJK 否决 + 机位审计探针）。

``CompRes`` 原料厂 ``_res`` 借自 ``test_compile_engine_judge``——
``_fixloopkit`` 公共骨架共享测试替身的同款先例。引擎实跑不进单测。
"""

import importlib
from pathlib import Path
from types import ModuleType

import pytest
from test_compile_engine_judge import _res

from texlate.compile.engine import CompRes
from texlate.compile.judge import count_missing_chars, judge, log_died_mid_doc


# ---------------------------------------------------------------- judge
def test_judge_no_pdf_fail(tmp_path: Path) -> None:
    v = judge(_res(tmp_path, pdf=False))
    assert v.status == "fail"
    assert "no_pdf" in v.reasons


def test_judge_timeout_fail(tmp_path: Path) -> None:
    v = judge(_res(tmp_path, pdf=False, timed_out=True))
    assert v.status == "fail"
    assert "timeout" in v.reasons


def test_judge_clean(tmp_path: Path) -> None:
    v = judge(_res(tmp_path, pdf=True, log_text="all good\n"))
    assert v.status == "clean"


def test_judge_many_errors_partial(tmp_path: Path) -> None:
    log = "".join(f"! error {i}\nl.{i}\n" for i in range(10))
    v = judge(_res(tmp_path, pdf=True, log_text=log))
    assert v.status == "partial"


def test_judge_missing_file_first_error_dirty(tmp_path: Path) -> None:
    log = "! LaTeX Error: File `x.sty' not found.\nl.1\n"
    v = judge(_res(tmp_path, pdf=True, log_text=log))
    assert v.status == "partial"
    assert v.category == "missing_file"


def test_judge_error_composition(tmp_path: Path) -> None:
    """error_cats 收全量错误行构成；首错复用 ctx 权威对（payload 不丢）。

    quant-ph/9703040 形态：首错与 bulk 不同族——构成数据让标记聚合
    能纠「首错遮 bulk」。
    """
    log = "! Undefined control sequence.\nl.1 \\x\n" + "".join(
        f"! Missing number, treated as zero.\nl.{i} \\bffam\n" for i in range(2, 8)
    )
    v = judge(_res(tmp_path, pdf=True, log_text=log))
    assert v.error_cats == {"undefined_cs": 1, "syntax": 6}
    assert v.error_pay == {"undefined_cs": "x"}
    assert v.category == "undefined_cs"  # category 仍是首错语义


def test_judge_error_composition_no_pdf(tmp_path: Path) -> None:
    """no_pdf 早退支路同样收构成（构成覆盖全部错误行）。"""
    log = "! Missing number, treated as zero.\nl.1 \\x\n! Undefined control sequence.\n"
    v = judge(_res(tmp_path, pdf=False, log_text=log))
    assert v.status == "fail"
    assert sum(v.error_cats.values()) == v.n_errors


def test_judge_error_composition_empty(tmp_path: Path) -> None:
    """无错误行 → 空构成（sig 回退首错路径）。"""
    v = judge(_res(tmp_path, pdf=True, log_text="all good\n"))
    assert v.error_cats == {}
    assert v.error_pay == {}


def test_judge_utf8_warning_dirty(tmp_path: Path) -> None:
    log = "Invalid UTF-8 byte or sequence at line 9 replaced by U+FFFD.\n"
    v = judge(_res(tmp_path, pdf=True, log_text=log))
    assert v.status == "partial"


def test_judge_signal_death_attribution(tmp_path: Path) -> None:
    """2211.13013 实证：xdvipdfmx 死 → xelatex 收 SIGPIPE(rc=-13)，
    aux/log 截断的下游症状（invalid_utf8）曾顶包归因——rc<0 必须
    单独进 reasons/notes，且有 pdf 也判 partial（死进程产出不可信）。"""
    log = "Invalid UTF-8 byte or sequence at line 9 replaced by U+FFFD.\n"
    v = judge(_res(tmp_path, pdf=True, log_text=log, rc=-13))
    assert v.status == "partial"
    assert "killed_by_signal:13" in v.reasons
    assert any("engine_killed:SIG13" in n for n in v.notes)


def test_judge_signal_death_no_pdf(tmp_path: Path) -> None:
    """信号杀死 + 无 pdf：fail 且真凶在 reasons，不是哑巴 no_pdf。"""
    v = judge(_res(tmp_path, pdf=False, rc=-9))
    assert v.status == "fail"
    assert "killed_by_signal:9" in v.reasons
    assert "no_pdf" in v.reasons


def test_judge_signal_death_clean_log_still_dirty(tmp_path: Path) -> None:
    """log 表面干净但引擎被杀（罕见：写完 pdf 后崩）——仍判 partial。"""
    v = judge(_res(tmp_path, pdf=True, log_text="all good\n", rc=-13))
    assert v.status == "partial"
    assert "killed_by_signal:13" in v.reasons


def test_judge_signal_death_masked_by_later_pass(tmp_path: Path) -> None:
    """pass1 被杀、pass2 跑完 rc=0：res.rc 末值掩不掉 killed_signal 归因。"""
    res = _res(tmp_path, pdf=True, log_text="all good\n", rc=0)
    res.killed_signal = 13  # 引擎侧 mid-loop 死亡记录
    v = judge(res)
    assert v.status == "partial"
    assert "killed_by_signal:13" in v.reasons


def _judge_mod() -> ModuleType:
    """judge 子模块对象（包级 re-export 的同名函数遮蔽了模块属性路径）。"""
    return importlib.import_module("texlate.compile.judge")


def test_judge_cjk_zero_dirty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """hep-th 教训：有 pdf 但 0 中文字节 → tofu 否决 fail（非 partial 交付）。"""
    monkeypatch.setattr(_judge_mod(), "pdf_text_stats", lambda _p: (0, 0))
    v = judge(_res(tmp_path, pdf=True), expect_cjk=True)
    assert v.status == "fail"
    assert "cjk_chars=0" in v.reasons
    assert "tofu_veto" in v.notes


def test_judge_cjk_rendered_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_judge_mod(), "pdf_text_stats", lambda _p: (5000, 0))
    v = judge(_res(tmp_path, pdf=True), expect_cjk=True)
    assert v.status == "clean"


def test_judge_cjk_unverified_not_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pdftotext 缺席且无负信号 → 不判 dirty，只记 note。"""
    monkeypatch.setattr(_judge_mod(), "pdf_text_stats", lambda _p: None)
    v = judge(_res(tmp_path, pdf=True), expect_cjk=True)
    assert v.status == "clean"
    assert any("cjk_unverified" in n for n in v.notes)


def test_count_missing_chars() -> None:
    log = "Missing character: There is no a in font\nMissing character: x\n"
    assert count_missing_chars(log) == 2  # noqa: PLR2004 - 两行 Missing character


# ---------------------------------------------------------------- 截断/死字形
def test_judge_died_mid_doc_reason(tmp_path: Path) -> None:
    """e116 实证：xelatex ``Emergency stop`` 中段死亡仍印 ``Output written``。

    log 终止符不是截断信号——致命中止词素才是唯一可靠分界；出半截 pdf
    判 partial（可交付残件），不进 clean。
    """
    log = (
        "! Undefined control sequence.\nl.35 \\badcs\n"
        "! Emergency stop.\nOutput written on main.pdf (35 pages).\n"
    )
    v = judge(_res(tmp_path, pdf=True, log_text=log), log_text=log)
    assert v.status == "partial"
    assert "died_mid_doc" in v.reasons
    assert "died:Emergency stop" in v.notes


def test_judge_died_mid_doc_no_pdf_silent(tmp_path: Path) -> None:
    """无 pdf 早退臂不挂 ``died_mid_doc``——``no_pdf`` 已归 fail，标记冗余。"""
    v = judge(_res(tmp_path, pdf=False, log_text="! Emergency stop.\n"))
    assert v.status == "fail"
    assert "died_mid_doc" not in v.reasons


def test_judge_dead_glyphs_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """c32920 实证：部分死层 cjk>0 逃过 tofu 否决——U+FFFD 抽取面补判 partial。

    ``Missing character`` 告警计数够不到「字形在但 ToUnicode 死」形态
    （Identity-H 断 CMap）；复制/搜索/对位锚全死的 pdf 不配 clean。
    """
    monkeypatch.setattr(_judge_mod(), "pdf_text_stats", lambda _p: (3000, 12741))
    v = judge(_res(tmp_path, pdf=True), expect_cjk=True)
    assert v.status == "partial"
    assert "dead_glyphs:ufffd×12741" in v.reasons
    assert v.dead_chars == 12741  # noqa: PLR2004 - c32920 死层实测面值


def test_judge_dead_glyphs_below_min(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FFFD 低位噪声（作者稿手输孤例）不判红——计数照记、阈值不误报。"""
    monkeypatch.setattr(_judge_mod(), "pdf_text_stats", lambda _p: (3000, 5))
    v = judge(_res(tmp_path, pdf=True), expect_cjk=True)
    assert v.status == "clean"
    assert v.dead_chars == 5  # noqa: PLR2004 - 低位噪声阈值内
    assert not any(r.startswith("dead_glyphs") for r in v.reasons)


def test_log_died_mid_doc_lexemes() -> None:
    """taxonomy ``emergency`` 词族逐词命中 + 干净 log（含 ``Output written``）不回。"""
    assert log_died_mid_doc("x\n! Emergency stop.\n") == "Emergency stop"
    assert (
        log_died_mid_doc("!  Fatal error occurred, no output PDF produced!\n")
        == "Fatal error"
    )
    assert log_died_mid_doc("!  cannot \\read from x\n") == "cannot \\read"
    assert log_died_mid_doc("job aborted, file error\n") == "job aborted"
    # errorlimit 硬顶中止（e116:100 错强停 35 页残件、无 Emergency 词素）
    assert (
        log_died_mid_doc("(That makes 100 errors; please try again.)\n")
        == "makes 100 errors"
    )
    assert log_died_mid_doc("all good\nOutput written on main.pdf (1 page).\n") is None


# ---------------------------------------------------------------- 机位审计
def _slot_res(tmp_path: Path, tex_body: str, name: str = "main.tex") -> CompRes:
    """pdf-clean CompRes + workdir 内置一份 .tex——机位审计的最小输入。"""
    res = _res(tmp_path, pdf=True, log_text="all good\n")
    res.workdir = tmp_path
    (tmp_path / name).write_text(tex_body, encoding="utf-8")
    return res


def _slot_notes(v) -> list[str]:  # noqa: ANN001 - Verdict 私有探针面
    return [n for n in v.notes if n.startswith("machine_slot_nonascii:")]


def test_machine_slot_fires_per_kind(tmp_path: Path) -> None:
    """全机位命中：env/label/cite/bib/csname/input 路径/restatable 头。"""
    body = (
        "\\begin{定理环境}\n"
        "\\label{sec:引理}\n"
        "\\citep{张三2020}\n"
        "\\bibliography{中文文献}\n"
        "\\csname 中文体\\endcsname\n"
        "\\input{中文文件}\n"
        "\\end{定理环境}\n"
    )
    v = judge(_slot_res(tmp_path, body))
    kinds = {n.split(":")[1] for n in _slot_notes(v)}
    assert {"env", "ref", "cite", "bib", "csname", "input"} <= kinds
    assert v.status == "clean"  # note 级——不污染 verdict


def test_machine_slot_restatable_double_args(tmp_path: Path) -> None:
    """restatable 头双机位参：env 名或 cskey 任一中招都记（原窄探针面）。"""
    v = judge(_slot_res(tmp_path, "\\begin{restatable}{定理}{main}\nx\n"))
    assert any(n.startswith("machine_slot_nonascii:restatable:") for n in v.notes)
    v2 = judge(_slot_res(tmp_path, "\\begin{restatable}{theorem}{中文键}\nx\n"))
    assert any(n.startswith("machine_slot_nonascii:restatable:") for n in v2.notes)


def test_machine_slot_optional_and_text_args_silent(tmp_path: Path) -> None:
    """FP 闸：可选位/文位 CJK 不命中——\\section/\\caption/[opt] 全哑。"""
    body = (
        "\\section{中文标题}\n"
        "\\caption{中文说明}\n"
        "\\citep[见][中文注]{key}\n"
        "\\includegraphics[width=中文]{fig.png}\n"
        "\\footnote{中文脚注}\n"
        "\\begin{restatable}[中文注]{theorem}{main}\nx\\end{restatable}\n"
    )
    v = judge(_slot_res(tmp_path, body))
    assert _slot_notes(v) == []


def test_machine_slot_ascii_silent(tmp_path: Path) -> None:
    """ASCII 机位参全静默：label/cite/env/input/bib 零命中。"""
    body = (
        "\\begin{theorem}\\label{thm:a}\\end{theorem}\n"
        "\\cite{knuth84}\\ref{thm:a}\\eqref{eq:1}\\bibliography{refs}\n"
        "\\input{macros}\\include{ch1}\\includegraphics{fig.png}\n"
        "\\csname foo\\endcsname\n"
    )
    v = judge(_slot_res(tmp_path, body))
    assert _slot_notes(v) == []


def test_machine_slot_masked_regions_silent(tmp_path: Path) -> None:
    """注释/verbatim/死区同形 token 非活机位——mask_tex 视图挡 FP。"""
    body = (
        "% \\label{注释键}\n"
        "\\begin{verbatim}\n\\cite{逐字键}\n\\end{verbatim}\n"
        "\\begin{document}\nx\n\\end{document}\n"
        "\\label{死区键}\n"
    )
    v = judge(_slot_res(tmp_path, body))
    assert _slot_notes(v) == []


def test_machine_slot_no_workdir_no_crash(tmp_path: Path) -> None:
    """workdir 缺席 → 探针短路不炸（手工 CompRes 面）。"""
    v = judge(_res(tmp_path, pdf=True, log_text="all good\n"))
    assert _slot_notes(v) == []


def test_machine_slot_includegraphics_required_arg(tmp_path: Path) -> None:
    """``\\includegraphics{中文.png}`` 必填路径中招（可选位排除不误伤）。"""
    v = judge(_slot_res(tmp_path, "\\includegraphics[width=2cm]{中文.png}\n"))
    assert any(n == "machine_slot_nonascii:path:main.tex:'中文.png'" for n in v.notes)


def test_machine_slot_note_cap(tmp_path: Path) -> None:
    """note 封顶：>20 命中截断 + capped 标记，不刷屏。"""
    body = "".join(f"\\label{{k{i}:中文}}\n" for i in range(25))
    v = judge(_slot_res(tmp_path, body))
    notes = _slot_notes(v)
    assert len(notes) == 21  # noqa: PLR2004 - 20 命中 + capped 标记
    assert notes[-1] == "machine_slot_nonascii:capped@20"
