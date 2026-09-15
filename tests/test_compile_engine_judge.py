"""engine.py（parse_log/classify/route/deps）与 judge.py 的单测。

引擎实跑不进单测——由 bench/py/e2e_mock_bench.py 驱动覆盖。
"""

import importlib
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

from texlate.compile.engine import (
    CompRes,
    TectonicEngine,
    XelatexEngine,
    classify_error,
    compiled_dependencies,
    parse_log,
    route_project,
)
from texlate.compile.judge import count_missing_chars, judge
from texlate.compile.sandbox import child_env, sandbox_wrap


# ---------------------------------------------------------------- parse_log
def test_parse_log_bang_errors() -> None:
    log = "noise\n! Undefined control sequence.\nl.123 \\foo\nmore\n"
    info = parse_log(log)
    assert info.n_errors == 1
    assert info.first_error == "! Undefined control sequence."
    assert info.error_line == 123  # noqa: PLR2004 - l.NNN 提取的样本行号


def test_parse_log_file_line_format() -> None:
    """双格式计数：`file:line:` 引擎级错误也要数到（docs/08 §2.3）。"""
    log = "./main.tex:10: Undefined control sequence\nnext\n"
    info = parse_log(log)
    assert info.n_errors == 1


def test_parse_log_warning_red_lines() -> None:
    log = "Invalid UTF-8 byte or sequence at line 5 replaced by U+FFFD.\n"
    info = parse_log(log)
    assert "invalid_utf8" in info.warnings_hit


def test_parse_log_missing_character_fffd() -> None:
    log = "Missing character: There is no (U+FFFD) in font cmr10!\n"
    info = parse_log(log)
    assert "fffd_glyph" in info.warnings_hit
    assert "missing_chars" in info.warnings_hit


def test_parse_log_tail_kept() -> None:
    log = "\n".join(f"line{i}" for i in range(100))
    info = parse_log(log)
    assert "line99" in info.tail


# ---------------------------------------------------------------- classify
def test_classify_missing_file() -> None:
    cat, pay = classify_error(
        "! LaTeX Error: File `tabulary.sty' not found.", None, "", timed_out=False
    )
    assert cat == "missing_file"
    assert pay == "tabulary.sty"


def test_classify_pdftex_prim_via_undefined_cs() -> None:
    cat, pay = classify_error(
        "! Undefined control sequence.\nl.5 \\pdfoutput", None, "", timed_out=False
    )
    assert cat == "pdftex_prim"
    assert pay == "pdfoutput"


def test_classify_latex209() -> None:
    cat, _ = classify_error(
        "! LaTeX2e command \\usepackage in LaTeX 2.09 document",
        None,
        "",
        timed_out=False,
    )
    assert cat == "latex209"


def test_classify_timeout() -> None:
    assert classify_error(None, None, "", timed_out=True) == ("timeout", None)


def test_classify_clean() -> None:
    assert classify_error(None, None, "", timed_out=False) == ("clean", None)


def test_classify_enter_filename_tail() -> None:
    """无 '!' 首错时回溯 tail：文件名提示符死 → missing_file。"""
    tail = "! File `foo.sty' not found.\nEnter file name:\n! Emergency stop."
    cat, _pay = classify_error("! Emergency stop.", None, tail, timed_out=False)
    assert cat in {"emergency", "missing_file"}


def test_classify_eps_hard_wall() -> None:
    cat, _ = classify_error(
        "error: xdvipdfmx: image inclusion failed for fig.eps",
        None,
        "",
        timed_out=False,
    )
    assert cat == "eps_image"


# ---------------------------------------------------------------- 路由表
def test_route_documentstyle_reject(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentstyle{ptptex}\n\\begin{document}\nx\\end{document}"
    )
    d = route_project(tmp_path)
    assert d.reject == "latex209_documentstyle"
    assert d.engines == []


def test_route_eps_to_xelatex(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}"
    )
    (tmp_path / "fig.eps").write_text("%!PS-Adobe")
    d = route_project(tmp_path)
    assert d.reject is None
    assert d.engines[0] == "xelatex"


def test_route_pstricks_to_xelatex(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{pstricks}\n"
        "\\begin{document}\nx\\end{document}"
    )
    d = route_project(tmp_path)
    assert d.engines[0] == "xelatex"


def test_route_minted_frozencache_tectonic(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage[frozencache=true]{minted}\n"
        "\\begin{document}\nx\\end{document}"
    )
    d = route_project(tmp_path)
    assert d.engines[0] == "tectonic"


def test_route_default_tectonic_first(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}"
    )
    d = route_project(tmp_path)
    assert d.engines == ["tectonic", "xelatex"]


def test_route_bitmap_font_flag(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{bbm}\n"
        "\\begin{document}\nx\\end{document}"
    )
    d = route_project(tmp_path)
    assert any("位图字体" in r or "bbm" in r for r in d.reasons)


def test_route_non_utf8_flag(tmp_path: Path) -> None:
    # \xdc = latin-5 Ü（非 UTF-8 源标记的触发字节）
    (tmp_path / "main.tex").write_bytes(
        b"\\documentclass{article}\n\\begin{document}\nT\\'\xdc\nx\\end{document}"
    )
    d = route_project(tmp_path)
    assert d.non_utf8


# ---------------------------------------------------------------- judge
def _res(
    tmp_path: Path,
    *,
    pdf: bool = True,
    log_text: str = "",
    timed_out: bool = False,
    rc: int | None = 0,
) -> CompRes:
    res = CompRes(engine="xelatex")
    res.ok = not timed_out
    res.timed_out = timed_out
    res.rc = rc
    if pdf:
        p = tmp_path / "main.pdf"
        p.write_bytes(b"%PDF-fake")
        res.pdf = p
        res.pdf_bytes = p.stat().st_size
    res.log = parse_log(log_text)
    return res


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
    """hep-th 教训：有 pdf 但 0 中文字节 → dirty。"""
    monkeypatch.setattr(_judge_mod(), "pdf_cjk_chars", lambda _p: 0)
    v = judge(_res(tmp_path, pdf=True), expect_cjk=True)
    assert v.status == "partial"
    assert "cjk_chars=0" in v.reasons


def test_judge_cjk_rendered_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_judge_mod(), "pdf_cjk_chars", lambda _p: 5000)
    v = judge(_res(tmp_path, pdf=True), expect_cjk=True)
    assert v.status == "clean"


def test_judge_cjk_unverified_not_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pdftotext 缺席且无负信号 → 不判 dirty，只记 note。"""
    monkeypatch.setattr(_judge_mod(), "pdf_cjk_chars", lambda _p: -1)
    v = judge(_res(tmp_path, pdf=True), expect_cjk=True)
    assert v.status == "clean"
    assert any("cjk_unverified" in n for n in v.notes)


def test_count_missing_chars() -> None:
    log = "Missing character: There is no a in font\nMissing character: x\n"
    assert count_missing_chars(log) == 2  # noqa: PLR2004 - 两行 Missing character


# ---------------------------------------------------------------- compiled_dependencies
def test_compiled_dependencies_fls(tmp_path: Path) -> None:
    out = tmp_path
    (tmp_path / "main.tex").write_text("\\documentclass{article}\nx")
    (tmp_path / "main.fls").write_text(
        "PWD /x\nINPUT ./main.tex\nINPUT ./macros.tex\n"
        "INPUT /usr/local/texlive/2026/texmf-dist/tex/latex/base/article.cls\n"
        "OUTPUT ./main.pdf\n"
    )
    (tmp_path / "macros.tex").write_text("% m")
    deps = compiled_dependencies(tmp_path, "main.tex", out, "xelatex")
    assert deps is not None
    assert "main.tex" in deps
    assert "macros.tex" in deps
    assert not any("texmf-dist" in d for d in deps)


def test_compiled_dependencies_missing_record(tmp_path: Path) -> None:
    assert compiled_dependencies(tmp_path, "main.tex", tmp_path, "xelatex") is None


# ---------------------------------------------------------------- sandbox
def test_child_env_whitelist_strips_secrets() -> None:
    os.environ["TEST_TEXLATE_MUST_STRIP"] = "leakme"
    env = child_env()
    assert "TEST_TEXLATE_MUST_STRIP" not in env
    assert env["openin_any"] == "p"
    assert env["shell_escape"] == "f"
    assert env["TECTONIC_UNTRUSTED_MODE"] == "1"
    del os.environ["TEST_TEXLATE_MUST_STRIP"]


def test_sandbox_wrap_passthrough_on_nondarwin(tmp_path: Path) -> None:
    cmd = ["echo", "hi"]
    wrapped = sandbox_wrap(cmd, root=tmp_path, out=tmp_path)
    if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists():
        assert wrapped[0].endswith("sandbox-exec")
        assert wrapped[-2:] == cmd
    else:
        assert wrapped == cmd


def test_sandbox_profile_shape(tmp_path: Path) -> None:
    """profile 结构性回归——2211.13013 SIGPIPE 三案根的防护：

    - ``literal``+``subpath`` 双发：subpath 不含目录自身，cd/stat 会漏；
    - TMPDIR canonical 形：/var→/private/var 软链，字面路径打不中；
    - ``file-read-metadata`` on $HOME：shell cd/getcwd 要 stat 祖先目录。
    三者缺一，mktexpk 装 pk 字体失败 → xdvipdfmx 死 → xelatex SIGPIPE。
    """
    if not (sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists()):
        pytest.skip("sandbox-exec 仅 macOS")
    wrapped = sandbox_wrap(["xelatex"], root=tmp_path, out=tmp_path)
    profile = wrapped[2]
    assert "(literal" in profile
    assert "(subpath" in profile
    assert "file-read-metadata" in profile
    assert "/private/var/" in profile  # canonical TMPDIR
    assert "Library/texlive" in profile  # TEXMFVAR 读白名单


# ---------------------------------------------------------------- 引擎检测
def test_engine_protocol_caps() -> None:
    xe = XelatexEngine()
    te = TectonicEngine()
    assert "tlmgr" in xe.caps
    assert "tlmgr" not in te.caps
    assert "bundle" in te.caps


def test_tectonic_retry_success_clears_timed_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """冷 bundle 首拉超时 → 二次尝试成功出 pdf：timed_out 必须清掉。

    旧实现 timed_out 粘住 → res.ok=False → judge timeout 短路 →
    成功编译被判 fail。
    """
    eng = TectonicEngine(binary="/bin/true")
    main = tmp_path / "main.tex"
    main.write_text("\\documentclass{article}\\begin{document}x\\end{document}")
    outdir = tmp_path / "out"
    calls = {"n": 0}

    def fake_run(
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        out_cap: int = 8 * 1024 * 1024,
    ) -> tuple[int | None, str, float, bool]:
        _ = (cmd, cwd, env, out_cap)  # mock 签名对齐 run_process
        calls["n"] += 1
        if calls["n"] == 1:
            return None, "", timeout, True  # 首拉超时
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "main.pdf").write_bytes(b"%PDF-fake")
        return 0, "", 5.0, False

    monkeypatch.setattr("texlate.compile.engine.run_process", fake_run)
    res = eng.compile(tmp_path, "main.tex", outdir=outdir, sandbox=False)
    assert calls["n"] == 2  # noqa: PLR2004 -- 超时重试恰一次
    assert res.timed_out is False
    assert res.ok is True
    assert res.has_pdf
