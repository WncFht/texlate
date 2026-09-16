"""engine.py（parse_log/classify/route/deps）与 judge.py 的单测。

引擎实跑不进单测——由 bench/py/e2e_mock_bench.py 驱动覆盖。
"""

import importlib
import json
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
    assert cat == "ps_image"


def test_classify_inputenc_unicode() -> None:
    """inputenc 对 Unicode 引擎整包拒载 → inputenc_unicode（rules.yaml 同名）。"""
    cat, _ = classify_error(
        "inputenc.sty:164: Package inputenc Error: inputenc is not designed for",
        None,
        "",
        timed_out=False,
    )
    assert cat == "inputenc_unicode"


# ---------------------------------------------------------------- 路由表
def test_route_documentstyle_suspect(tmp_path: Path) -> None:
    """documentstyle 降级: 不再 reject, 打 latex209_suspect + 默认引擎序试编。"""
    (tmp_path / "main.tex").write_text(
        "\\documentstyle{ptptex}\n\\begin{document}\nx\\end{document}"
    )
    d = route_project(tmp_path)
    assert d.reject is None
    assert d.latex209_suspect is True
    assert d.engines == ["tectonic", "xelatex"]
    assert any("latex209_suspect" in r for r in d.reasons)


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


# ---------------------------------------------------------------- tlmgr 装包层
def test_filemap_disk_cache_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """落盘缓存优先于索引/tlmgr——远端仓库知识的跨进程复用。"""
    cache_file = tmp_path / "c.json"
    cache_file.write_text(json.dumps({"/revtex4.cls": ["revtex4"]}))
    monkeypatch.setenv("TEXLATE_TLMGR_CACHE", str(cache_file))
    eng = XelatexEngine()
    monkeypatch.setattr(eng, "_filemap_index", lambda _f: ["WRONG-INDEX"])
    monkeypatch.setattr(eng, "_filemap_tlmgr", lambda _f: ["WRONG-TLMGR"])
    assert eng.filemap("revtex4.cls") == ["revtex4"]


def test_filemap_index_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """tlpdb 离线索引命中 → 不走 tlmgr; 索引自身即持久层, 不重复落盘。"""
    cache_file = tmp_path / "c.json"
    monkeypatch.setenv("TEXLATE_TLMGR_CACHE", str(cache_file))
    eng = XelatexEngine()
    monkeypatch.setattr(eng, "_filemap_index", lambda _f: ["revtex4"])

    def _no_tlmgr(f: str) -> list[str]:
        pytest.fail(f"索引命中不应回退 tlmgr: {f}")

    monkeypatch.setattr(eng, "_filemap_tlmgr", _no_tlmgr)
    assert eng.filemap("revtex4.cls") == ["revtex4"]
    assert not cache_file.exists()


def test_filemap_tlmgr_fallback_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """索引缺席 → tlmgr 在线通路兜底, 新结果落盘缓存。"""
    cache_file = tmp_path / "c.json"
    monkeypatch.setenv("TEXLATE_TLMGR_CACHE", str(cache_file))
    eng = XelatexEngine()
    monkeypatch.setattr(eng, "_filemap_index", lambda _f: None)
    monkeypatch.setattr(eng, "_filemap_tlmgr", lambda _f: ["pkg-from-tlmgr"])
    assert eng.filemap("x.sty") == ["pkg-from-tlmgr"]
    assert json.loads(cache_file.read_text())["/x.sty"] == ["pkg-from-tlmgr"]


def test_install_lock_creates_lockfile(tmp_path: Path) -> None:
    """同 usertree 的 tlmgr install 经 flock 串行化（锁文件在 texmfhome）。"""
    eng = XelatexEngine(texmfhome=tmp_path)
    with eng._install_lock():  # noqa: SLF001 -- 内部锁行为的直接断言
        assert (tmp_path / ".texlate-install.lock").exists()


# ---------------------------------------------------------------- flags seam
def test_xelatex_split_flags_drops_output_rekey() -> None:
    """重键输出落点的 flag（-output-directory/-jobname 系）→ dropped。"""
    applied, dropped = XelatexEngine._split_flags(  # noqa: SLF001
        ["-shell-escape", "-output-directory=/x", "-jobname", "y"]
    )
    assert applied == ["-shell-escape", "y"]
    assert dropped == ["-output-directory=/x", "-jobname"]


def test_xelatex_compile_flags_in_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """flags 端到端：argv 追加在基线旗标后 + CompRes.flags_* 记账。"""
    main = tmp_path / "main.tex"
    main.write_text("\\documentclass{article}\\begin{document}x\\end{document}")
    captured: dict[str, list[str]] = {}

    def fake_run(
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        out_cap: int = 8 * 1024 * 1024,
    ) -> tuple[int | None, str, float, bool]:
        _ = (cwd, env, timeout, out_cap)  # mock 签名对齐 run_process
        captured["cmd"] = cmd
        (tmp_path / "main.pdf").write_bytes(b"%PDF-fake")
        (tmp_path / "main.log").write_text("Output written\n", encoding="utf-8")
        return 0, "", 1.0, False

    monkeypatch.setattr("texlate.compile.engine.run_process", fake_run)
    eng = XelatexEngine(binary="/bin/true")
    res = eng.compile(
        tmp_path,
        "main.tex",
        passes=1,
        sandbox=False,
        flags=["-shell-escape", "-output-directory=/x"],
    )
    cmd = captured["cmd"]
    assert "-shell-escape" in cmd
    assert cmd.index("-shell-escape") > cmd.index("-no-shell-escape")
    assert "-output-directory=/x" not in cmd  # 重键 flag 拒放
    assert res.flags_applied == ["-shell-escape"]
    assert res.flags_dropped == ["-output-directory=/x"]


def test_tectonic_map_flags_subset() -> None:
    """放行面 = 显式映射 + -Z 两式直通；-shell-escape 与未知项 → dropped。"""
    toks, dropped = TectonicEngine._map_flags(  # noqa: SLF001
        ["-synctex=1", "-Z", "keep-going", "-Zfoo", "-shell-escape", "--x"]
    )
    assert toks == ["--synctex", "-Z", "keep-going", "-Zfoo"]
    assert dropped == ["-shell-escape", "--x"]


def test_tectonic_compile_flags_map_and_drop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """受支持子集进 argv；dropped 进 CompRes 记账（e2e 换引擎凭据）。"""
    main = tmp_path / "main.tex"
    main.write_text("\\documentclass{article}\\begin{document}x\\end{document}")
    outdir = tmp_path / "out"
    captured: dict[str, list[str]] = {}

    def fake_run(
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        out_cap: int = 8 * 1024 * 1024,
    ) -> tuple[int | None, str, float, bool]:
        _ = (cwd, env, timeout, out_cap)  # mock 签名对齐 run_process
        captured["cmd"] = cmd
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "main.pdf").write_bytes(b"%PDF-fake")
        (outdir / "main.log").write_text("Output written\n", encoding="utf-8")
        return 0, "", 1.0, False

    monkeypatch.setattr("texlate.compile.engine.run_process", fake_run)
    eng = TectonicEngine(binary="/bin/true", bundle="")
    res = eng.compile(
        tmp_path,
        "main.tex",
        outdir=outdir,
        sandbox=False,
        flags=["-synctex=1", "-shell-escape"],
    )
    cmd = captured["cmd"]
    assert "--synctex" in cmd
    assert "-shell-escape" not in cmd
    assert cmd[-1] == "main.tex"  # flag 追加在 main 前
    assert res.flags_applied == ["-synctex=1"]
    assert res.flags_dropped == ["-shell-escape"]


# ---------------------------------------------------------------- bundle flag
def test_bundle_flag_web_bundle_pre_017(monkeypatch: pytest.MonkeyPatch) -> None:
    """<0.17 + URL bundle → --web-bundle（老 --bundle 只认本地路径）。"""
    monkeypatch.setattr(
        "texlate.compile.engine.tectonic_version", lambda _b: (0, 15, 0)
    )
    eng = TectonicEngine(binary="/x/tectonic", bundle="https://b/x.tar")
    cmd = eng._cmd("/x/tectonic", Path("/o"), "main.tex")  # noqa: SLF001
    i = cmd.index("--web-bundle")
    assert cmd[i + 1] == "https://b/x.tar"


def test_bundle_flag_bundle_for_017_and_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """≥0.17 + URL → --bundle；探不出版本同样 --bundle（新语法是默认）。"""
    monkeypatch.setattr(
        "texlate.compile.engine.tectonic_version", lambda _b: (0, 17, 0)
    )
    eng = TectonicEngine(binary="/x/tectonic", bundle="https://b/x.tar")
    cmd = eng._cmd("/x/tectonic", Path("/o"), "main.tex")  # noqa: SLF001
    assert "--web-bundle" not in cmd
    i = cmd.index("--bundle")
    assert cmd[i + 1] == "https://b/x.tar"

    monkeypatch.setattr("texlate.compile.engine.tectonic_version", lambda _b: None)
    cmd = eng._cmd("/x/tectonic", Path("/o"), "main.tex")  # noqa: SLF001
    assert "--web-bundle" not in cmd
    assert "--bundle" in cmd


def test_bundle_flag_local_path_skips_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """本地路径恒 --bundle，且不浪费一次 --version 子进程。"""
    monkeypatch.setattr(
        "texlate.compile.engine.tectonic_version",
        lambda _b: pytest.fail("本地路径不该探版本"),
    )
    eng = TectonicEngine(binary="/x/tectonic", bundle="/opt/b.tar")
    cmd = eng._cmd("/x/tectonic", Path("/o"), "main.tex")  # noqa: SLF001
    i = cmd.index("--bundle")
    assert cmd[i + 1] == "/opt/b.tar"
