"""C5 孤儿机制规则单测 (mechmap-2026-09-17 裁决 W31/W37/W68/W79/W18/W102/W66/W58)。

覆盖面:
  - ``generated_stub`` —— rungen(W79 ``\\openout`` 面) + nonctan_input(W18
    覆盖层扩展名面) 同 builtin 两检测面;
  - ``docstrip_generate`` —— 包内 .ins 抽取缺件 (stem 匹配/唯一 ins 兜底);
  - ``plain_format_detect`` —— gate 拒 tex-plain, 遮盖视图抗注释伪装;
  - ``harvest_build_directives`` —— arara/!TEX 注释指令收割 (注释本体即信号);
  - ``svg_prepare`` —— flag 臂 (inkscape 在请 -shell-escape) / 转换臂
    (svg→pdf + \\includesvg 改写), flags_dropped 自适应落臂;
  - ``includepdf_missing_stub`` —— \\includepdf 缺件整调用 \\clearpage\\null;
  - ``graphic_case_link`` W66 扩面 —— \\includepdf 参数同进 ci-glob 改写。
"""

import shutil
from pathlib import Path

import pytest

from texlate.compile.fixloop import builtins, load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx, RunFn


def _ctx(tmp_path: Path, runner: RunFn | None = None) -> LoopCtx:
    return LoopCtx(
        wdir=tmp_path, engine_name="xelatex", main_rel="main.tex", runner=runner
    )


def _which_none(_name: str) -> None:
    return None


# ═══════════════════════════ generated_stub: openout 面 (W79) ═══════════


def test_rungen_stub_openout_target(tmp_path: Path) -> None:
    """hep-th/9703214 形: ``\\openout\\ftfile=foots.tmp`` → payload 命中写空 stub。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\newwrite\\ftfile\n"
        "\\openout\\ftfile=foots.tmp\n\\begin{document}\n"
        "\\input{foots.tmp}\n\\closeout\\ftfile\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = TRANSFORM_FNS["generated_stub"](
        _ctx(tmp_path), None, "foots.tmp", {"faces": ["openout"]}
    )
    assert ok, note
    assert "openout-stub" in note
    assert "% fixloop" in (tmp_path / "foots.tmp").read_text()


def test_rungen_stub_bare_digit_stream(tmp_path: Path) -> None:
    """plain 形 ``\\openout0=refs.tmp`` (stream 为裸数字) 同收。"""
    (tmp_path / "main.tex").write_text("\\openout0=refs.tmp\n\\bye\n")
    ok, _note = TRANSFORM_FNS["generated_stub"](
        _ctx(tmp_path), None, "refs.tmp", {"faces": ["openout"]}
    )
    assert ok


def test_rungen_stub_braced_and_immediate(tmp_path: Path) -> None:
    """花括号名 ``\\openout\\w={x.tmp}`` 与 ``\\immediate\\openout`` 前缀同收。"""
    (tmp_path / "main.tex").write_text(
        "\\immediate\\openout\\w={notes.tmp}\n\\openout\\z = data.tmp\n"
    )
    for name in ("notes.tmp", "data.tmp"):
        ok, note = TRANSFORM_FNS["generated_stub"](
            _ctx(tmp_path), None, name, {"faces": ["openout"]}
        )
        assert ok, (name, note)


def test_rungen_stub_comment_masked(tmp_path: Path) -> None:
    """``%\\openout\\w=x.tmp`` 注释内目标不算数。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n%\\openout\\w=x.tmp\n\\begin{document}\\end{document}\n"
    )
    ok, note = TRANSFORM_FNS["generated_stub"](
        _ctx(tmp_path), None, "x.tmp", {"faces": ["openout"]}
    )
    assert not ok
    assert "not a generated" in note


def test_rungen_stub_not_target_declines(tmp_path: Path) -> None:
    """真 CTAN 件名 (不在 openout 集) → False 落 install_file。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    ok, _note = TRANSFORM_FNS["generated_stub"](
        _ctx(tmp_path), None, "real.sty", {"faces": ["openout"]}
    )
    assert not ok


def test_generated_stub_unsafe_payload(tmp_path: Path) -> None:
    """绝对路径/../逃逸/NUL → False 不写 (vendored_fetch 同款闸)。"""
    (tmp_path / "main.tex").write_text("\\openout\\w=evil.tmp\n")
    for bad in ("../evil.tmp", "/abs/evil.tmp", "a\x00b.tmp"):
        ok, note = TRANSFORM_FNS["generated_stub"](
            _ctx(tmp_path), None, bad, {"faces": ["openout", "overlay"]}
        )
        assert not ok, bad
        assert "unsafe" in note


def test_rungen_stub_existing_not_overwritten(tmp_path: Path) -> None:
    """盘上已有真件 → False 不覆盖 (L10 指纹闸: 无指纹无名分=外来件)。"""
    (tmp_path / "main.tex").write_text("\\openout\\w=foots.tmp\n")
    (tmp_path / "foots.tmp").write_text("real content\n")
    ok, note = TRANSFORM_FNS["generated_stub"](
        _ctx(tmp_path), None, "foots.tmp", {"faces": ["openout"]}
    )
    assert not ok
    assert "foreign" in note or "already on disk" in note
    assert (tmp_path / "foots.tmp").read_text() == "real content\n"


def test_rungen_stub_idempotent(tmp_path: Path) -> None:
    """二次触火: stub 已在盘 → False。"""
    (tmp_path / "main.tex").write_text("\\openout\\w=foots.tmp\n")
    ctx = _ctx(tmp_path)
    ok1, _ = TRANSFORM_FNS["generated_stub"](
        ctx, None, "foots.tmp", {"faces": ["openout"]}
    )
    ok2, _ = TRANSFORM_FNS["generated_stub"](
        ctx, None, "foots.tmp", {"faces": ["openout"]}
    )
    assert ok1
    assert not ok2


# ═══════════════════════════ generated_stub: overlay 面 (W18) ═══════════


def test_overlay_stub_exts(tmp_path: Path) -> None:
    """0707.1954 形: .pstex_t/.pdf_t/.pdftex_t 覆盖层缺档 → 空 stub。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    for name in ("fig.pstex_t", "fig.pdf_t", "fig.pdftex_t"):
        ok, note = TRANSFORM_FNS["generated_stub"](
            _ctx(tmp_path), None, name, {"faces": ["overlay"]}
        )
        assert ok, (name, note)
        assert "overlay-stub" in note


def test_overlay_stub_non_overlay_declines(tmp_path: Path) -> None:
    """普通缺件扩展名 → False 落 install_file。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    ok, _note = TRANSFORM_FNS["generated_stub"](
        _ctx(tmp_path), None, "pic.pdf", {"faces": ["overlay"]}
    )
    assert not ok


def test_overlay_stub_subdir_relpath(tmp_path: Path) -> None:
    """payload 带目录前缀 → stub 落同名相对路径下 (父目录自动建)。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    ok, _note = TRANSFORM_FNS["generated_stub"](
        _ctx(tmp_path), None, "figs/plot.pdf_t", {"faces": ["overlay"]}
    )
    assert ok
    assert (tmp_path / "figs" / "plot.pdf_t").is_file()


# ═══════════════════════════ docstrip_generate (W102) ═══════════════════


def _docstrip_ok(payload_name: str) -> RunFn:
    """假 latex driver: 跑 ins 即把 payload 写进 wdir (docstrip 语义)。"""

    def _run(_argv: list[str], _timeout: int, wdir: Path) -> tuple:
        (wdir / payload_name).write_text("% generated by docstrip\n")
        return 0, "generated", 0.1, False

    return _run


def _which_latex(name: str) -> str | None:
    return "/usr/bin/latex" if name == "latex" else None


def test_docstrip_stem_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``aipproc.ins`` stem 匹配 payload ``aipproc.cls`` → 抽取成功 applied。"""
    monkeypatch.setattr(shutil, "which", _which_latex)
    (tmp_path / "aipproc.ins").write_text("\\input aipproc.dtx\n")
    (tmp_path / "main.tex").write_text("\\documentclass{aipproc}\n")
    ctx = _ctx(tmp_path, runner=_docstrip_ok("aipproc.cls"))
    ok, note = TRANSFORM_FNS["docstrip_generate"](ctx, None, "aipproc.cls", {})
    assert ok, note
    assert "aipproc.ins" in note
    assert (tmp_path / "aipproc.cls").is_file()
    assert any("docstrip" in e for e in ctx.events)


def test_docstrip_unique_ins_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stem 不对应但包内唯一 .ins → 兜底试一次 (aipproc.ins 出 fix2col.sty 族)。"""
    monkeypatch.setattr(shutil, "which", _which_latex)
    (tmp_path / "bundle.ins").write_text("\\input bundle.dtx\n")
    (tmp_path / "main.tex").write_text("x\n")
    ctx = _ctx(tmp_path, runner=_docstrip_ok("fix2col.sty"))
    ok, _note = TRANSFORM_FNS["docstrip_generate"](ctx, None, "fix2col.sty", {})
    assert ok


def test_docstrip_no_ins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", _which_latex)
    (tmp_path / "main.tex").write_text("x\n")
    ok, note = TRANSFORM_FNS["docstrip_generate"](_ctx(tmp_path), None, "x.cls", {})
    assert not ok
    assert "no .ins" in note


def test_docstrip_no_driver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """latex 系 driver 全缺席 → False 落 install_file 装 TL 版。"""
    monkeypatch.setattr(shutil, "which", _which_none)
    (tmp_path / "aipproc.ins").write_text("\\input aipproc.dtx\n")
    ok, note = TRANSFORM_FNS["docstrip_generate"](
        _ctx(tmp_path), None, "aipproc.cls", {}
    )
    assert not ok
    assert "no latex-family driver" in note


def test_docstrip_run_but_not_produced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ins 跑完但 payload 未落盘 → False (同轮 install_file 兜底)。"""
    monkeypatch.setattr(shutil, "which", _which_latex)
    (tmp_path / "aipproc.ins").write_text("x\n")

    def _noop(_argv: list[str], _t: int, _w: Path) -> tuple:
        return 0, "", 0.1, False

    ok, note = TRANSFORM_FNS["docstrip_generate"](
        _ctx(tmp_path, runner=_noop), None, "aipproc.cls", {}
    )
    assert not ok
    assert "not produced" in note


def test_docstrip_unsafe_payload(tmp_path: Path) -> None:
    (tmp_path / "aipproc.ins").write_text("x\n")
    ok, note = TRANSFORM_FNS["docstrip_generate"](
        _ctx(tmp_path), None, "../evil.cls", {}
    )
    assert not ok
    assert "unsafe" in note


# ════════════════════ plain_format_detect (W37/W68) ═════════════════════


def test_plain_format_magnification_bye(tmp_path: Path) -> None:
    """``\\magnification`` + ``\\font\\cs=cm*`` + ``^\\bye$`` → REJECT tex-plain。"""
    (tmp_path / "main.tex").write_text(
        "\\magnification=1200\n\\font\\big=cmr12\nplain text\n\\bye\n"
    )
    ok, note = TRANSFORM_FNS["plain_format_detect"](
        _ctx(tmp_path), None, "\\magnification", {"route": "tex-plain"}
    )
    assert ok
    assert note.startswith("REJECT: route=tex-plain")


def test_plain_format_comment_trap_docstyle(tmp_path: Path) -> None:
    """主检出被 ``%\\documentstyle`` 骗入主的 plain 稿 —— 遮盖视图照样判 plain。"""
    (tmp_path / "main.tex").write_text(
        "%\\documentstyle{article}  % commented legacy line\n"
        "\\magnification=1200\nbody\n\\bye\n"
    )
    ok, note = TRANSFORM_FNS["plain_format_detect"](_ctx(tmp_path), None, None, {})
    assert ok
    assert "REJECT" in note


def test_plain_format_bare_end_and_amstex(tmp_path: Path) -> None:
    """``\\input amstex`` 装载 + 裸行 ``\\end`` → plain。"""
    (tmp_path / "main.tex").write_text("\\input amstex\nsome text\n\\end\n")
    ok, note = TRANSFORM_FNS["plain_format_detect"](_ctx(tmp_path), None, None, {})
    assert ok
    assert "input-amstex" in note or "end" in note


def test_plain_format_latex_with_plain_ism_declines(tmp_path: Path) -> None:
    """活 ``\\documentclass`` + ``\\font\\small=cmr8`` 遗留写法 → 非 plain。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\font\\small=cmr8\n\\begin{document}\\end{document}\n"
    )
    ok, note = TRANSFORM_FNS["plain_format_detect"](_ctx(tmp_path), None, None, {})
    assert not ok
    assert "documentclass" in note


def test_plain_format_sig_only_in_comment(tmp_path: Path) -> None:
    """签名只活在注释里 → False (遮盖视图口径)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n%\\bye\n\\begin{document}\\end{document}\n"
    )
    ok, _note = TRANSFORM_FNS["plain_format_detect"](_ctx(tmp_path), None, None, {})
    assert not ok


def test_plain_format_no_sigs(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text("just prose, no cs at all\n")
    ok, note = TRANSFORM_FNS["plain_format_detect"](_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no plain-format" in note


# ════════════════════ harvest_build_directives (W58) ════════════════════


def test_harvest_arara_shell_flag(tmp_path: Path) -> None:
    """``% arara: pdflatex: { shell: on }`` → engine_flags 请 -shell-escape + advisory。"""
    (tmp_path / "main.tex").write_text(
        "% arara: pdflatex: { shell: on }\n\\documentclass{article}\n"
    )
    ctx = _ctx(tmp_path)
    ok, note = TRANSFORM_FNS["harvest_build_directives"](ctx, None, None, {})
    assert ok, note
    assert "-shell-escape" in ctx.engine_flags
    assert any("arara" in a for a in ctx.advisories)


def test_harvest_tex_program_advisory(tmp_path: Path) -> None:
    """``% !TEX program = lualatex`` → route hint 记 advisories, 不请 flag。"""
    (tmp_path / "main.tex").write_text(
        "% !TEX program = lualatex\n\\documentclass{article}\n"
    )
    ctx = _ctx(tmp_path)
    ok, _note = TRANSFORM_FNS["harvest_build_directives"](ctx, None, None, {})
    assert ok
    assert any("lualatex" in a for a in ctx.advisories)
    assert not ctx.engine_flags


def test_harvest_tex_options_shell(tmp_path: Path) -> None:
    """``% !TEX options = --shell-escape`` 同进 flag 面。"""
    (tmp_path / "main.tex").write_text(
        "% !TEX options = --shell-escape\n\\documentclass{article}\n"
    )
    ctx = _ctx(tmp_path)
    ok, _note = TRANSFORM_FNS["harvest_build_directives"](ctx, None, None, {})
    assert ok
    assert "-shell-escape" in ctx.engine_flags


def test_harvest_nothing(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\\end{document}\n"
    )
    ctx = _ctx(tmp_path)
    ok, _note = TRANSFORM_FNS["harvest_build_directives"](ctx, None, None, {})
    assert not ok


def test_harvest_flag_no_dupe(tmp_path: Path) -> None:
    """flag 已在 engine_flags → 不重复请 (幂等)。"""
    (tmp_path / "main.tex").write_text(
        "% arara: pdflatex: { shell: yes }\n% arara: makeglossaries\n"
        "\\documentclass{article}\n"
    )
    ctx = _ctx(tmp_path)
    ctx.engine_flags.append("-shell-escape")
    ok, _note = TRANSFORM_FNS["harvest_build_directives"](ctx, None, None, {})
    assert ok
    assert ctx.engine_flags == ["-shell-escape"]


# ═══════════════════════════ svg_prepare (W31) ══════════════════════════

SVG_MAIN = (
    "\\documentclass{article}\n\\usepackage{svg}\n\\begin{document}\n"
    "\\includesvg[width=0.8\\linewidth,pretex=\\small]{figs/a.svg}\n\\end{document}\n"
)


def _which_inkscape(name: str) -> str | None:
    return "/usr/bin/inkscape" if name == "inkscape" else None


def _which_rsvg(name: str) -> str | None:
    return "/usr/bin/rsvg-convert" if name == "rsvg-convert" else None


def _svg_conv_ok(argv: list[str], _t: int, _w: Path) -> tuple:
    """假 rsvg-convert: ``-o`` 目标写伪 pdf。"""
    Path(argv[argv.index("-o") + 1]).write_bytes(b"%PDF-fake")
    return 0, "", 0.1, False


def test_svg_prepare_flag_arm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """inkscape 在 → engine_flags 请 -shell-escape, 不改写源; 二次触火 False。"""
    monkeypatch.setattr(shutil, "which", _which_inkscape)
    (tmp_path / "figs").mkdir()
    (tmp_path / "figs" / "a.svg").write_bytes(b"<svg/>")
    (tmp_path / "main.tex").write_text(SVG_MAIN)
    ctx = _ctx(tmp_path)
    ok, note = TRANSFORM_FNS["svg_prepare"](ctx, None, "a_svg-tex.pdf", {})
    assert ok, note
    assert "-shell-escape" in ctx.engine_flags
    assert "\\includesvg" in (tmp_path / "main.tex").read_text()  # flag 臂不动源
    ok2, _note2 = TRANSFORM_FNS["svg_prepare"](ctx, None, "a_svg-tex.pdf", {})
    assert not ok2


def test_svg_prepare_convert_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """inkscape 缺席 → rsvg-convert 预转换 + \\includesvg→\\includegraphics (opts 白名单)。"""
    monkeypatch.setattr(shutil, "which", _which_rsvg)
    (tmp_path / "figs").mkdir()
    (tmp_path / "figs" / "a.svg").write_bytes(b"<svg/>")
    (tmp_path / "main.tex").write_text(SVG_MAIN)
    ctx = _ctx(tmp_path, runner=_svg_conv_ok)
    ok, note = TRANSFORM_FNS["svg_prepare"](ctx, None, "a_svg-tex.pdf", {})
    assert ok, note
    assert (tmp_path / "figs" / "a.pdf").is_file()
    t = (tmp_path / "main.tex").read_text()
    assert "\\includegraphics[width=0.8\\linewidth]{figs/a.pdf}" in t
    assert "pretex" not in t  # svg 私有键被白名单剥掉
    assert "% fixloop" in t


def test_svg_prepare_flag_dropped_falls_to_convert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """flag 上轮被引擎 seam 拒放 (flags_dropped) → 自适应落转换臂。"""
    monkeypatch.setattr(
        shutil,
        "which",
        lambda n: f"/usr/bin/{n}" if n in {"inkscape", "rsvg-convert"} else None,
    )
    (tmp_path / "a.svg").write_bytes(b"<svg/>")
    (tmp_path / "main.tex").write_text(SVG_MAIN.replace("figs/a.svg", "a.svg"))
    ctx = _ctx(tmp_path, runner=_svg_conv_ok)
    ctx.engine_flags.append("-shell-escape")
    ctx.flags_dropped.append("-shell-escape")
    ok, _note = TRANSFORM_FNS["svg_prepare"](ctx, None, None, {})
    assert ok
    assert (tmp_path / "a.pdf").is_file()


def test_svg_prepare_no_svg_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注释掉的 ``%\\usepackage{svg}`` 不算在用 → False (遮盖视图口径)。"""
    monkeypatch.setattr(shutil, "which", _which_rsvg)
    (tmp_path / "a.svg").write_bytes(b"<svg/>")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n%\\usepackage{svg}\n\\begin{document}\\end{document}\n"
    )
    ok, note = TRANSFORM_FNS["svg_prepare"](_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no live svg" in note


def test_svg_prepare_no_svg_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """inkscape 缺席且盘上无 .svg → False 让位。"""
    monkeypatch.setattr(shutil, "which", _which_none)
    (tmp_path / "main.tex").write_text(SVG_MAIN)
    ok, note = TRANSFORM_FNS["svg_prepare"](_ctx(tmp_path), None, "a_svg-tex.pdf", {})
    assert not ok
    assert "no .svg" in note


def test_svg_prepare_convert_all_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """转换器全败 → False 不谎报, 无残留半文件。"""
    monkeypatch.setattr(shutil, "which", _which_rsvg)
    (tmp_path / "a.svg").write_bytes(b"<svg/>")
    (tmp_path / "main.tex").write_text(SVG_MAIN.replace("figs/a.svg", "a.svg"))

    def _fail(_argv: list[str], _t: int, _w: Path) -> tuple:
        return 1, "boom", 0.1, False

    ok, note = TRANSFORM_FNS["svg_prepare"](
        _ctx(tmp_path, runner=_fail), None, None, {}
    )
    assert not ok
    assert "all failed" in note
    assert not (tmp_path / "a.pdf").exists()


def test_svg_prepare_convert_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """二次触火: pdf 复用 + 无活 \\includesvg → False。"""
    monkeypatch.setattr(shutil, "which", _which_rsvg)
    (tmp_path / "a.svg").write_bytes(b"<svg/>")
    (tmp_path / "main.tex").write_text(SVG_MAIN.replace("figs/a.svg", "a.svg"))
    ctx = _ctx(tmp_path, runner=_svg_conv_ok)
    ok1, _ = TRANSFORM_FNS["svg_prepare"](ctx, None, None, {})
    ok2, _ = TRANSFORM_FNS["svg_prepare"](ctx, None, None, {})
    assert ok1
    assert not ok2


# ════════════════════ includepdf_missing_stub (W66) ═════════════════════


def test_includepdf_stub_rewrites_call(tmp_path: Path) -> None:
    """``\\includepdf[pages=-]{supp.pdf}`` 缺件 → 整调用 → 注释 + ``\\clearpage\\null``。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{pdfpages}\n\\begin{document}\n"
        "body\n\\includepdf[pages=-]{supp.pdf}\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = TRANSFORM_FNS["includepdf_missing_stub"](
        _ctx(tmp_path), None, "supp.pdf", {}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\includepdf[pages=-]{supp.pdf}" not in t  # 活调用被替换
    assert "\\clearpage\\null" in t
    assert "% fixloop" in t  # 前缀注释留痕 (含 \includepdf 字样属正常)


def test_includepdf_stub_resolving_ref_untouched(tmp_path: Path) -> None:
    """引用本可在 wdir 解析 → 非本 payload 病灶 → False 不动。"""
    (tmp_path / "supp.pdf").write_bytes(b"%PDF")
    (tmp_path / "main.tex").write_text("\\includepdf{supp.pdf}\n")
    ok, _note = TRANSFORM_FNS["includepdf_missing_stub"](
        _ctx(tmp_path), None, "supp.pdf", {}
    )
    assert not ok
    assert "\\includepdf{supp.pdf}" in (tmp_path / "main.tex").read_text()


def test_includepdf_stub_comment_masked(tmp_path: Path) -> None:
    """注释内 ``%\\includepdf{gone.pdf}`` 不动; payload 不中的活引用也不动。"""
    (tmp_path / "main.tex").write_text(
        "%\\includepdf{gone.pdf}\n\\includepdf{other.pdf}\n"
    )
    ok, note = TRANSFORM_FNS["includepdf_missing_stub"](
        _ctx(tmp_path), None, "gone.pdf", {}
    )
    assert not ok
    assert "no live" in note
    assert "\\includepdf{other.pdf}" in (tmp_path / "main.tex").read_text()


def test_includepdf_stub_idempotent(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text("\\includepdf{gone.pdf}\n")
    ctx = _ctx(tmp_path)
    ok1, _ = TRANSFORM_FNS["includepdf_missing_stub"](ctx, None, "gone.pdf", {})
    ok2, _ = TRANSFORM_FNS["includepdf_missing_stub"](ctx, None, "gone.pdf", {})
    assert ok1
    assert not ok2


def test_includepdf_stub_ci_hit(tmp_path: Path) -> None:
    """payload ``SUPP.PDF`` vs 引用 ``{supp.pdf}`` —— ci 命中同 stub。"""
    (tmp_path / "main.tex").write_text("\\includepdf{supp.pdf}\n")
    ok, _note = TRANSFORM_FNS["includepdf_missing_stub"](
        _ctx(tmp_path), None, "SUPP.PDF", {}
    )
    assert ok


def test_case_link_extends_to_includepdf(tmp_path: Path) -> None:
    """W66 side-effect: ``\\includepdf`` 参数同进 ci-glob 改写真名面。"""
    (tmp_path / "SUPP.pdf").write_bytes(b"%PDF")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{pdfpages}\n\\begin{document}\n"
        "\\includepdf{supp.pdf}\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _note = TRANSFORM_FNS["graphic_case_link"](_ctx(tmp_path), None, "supp.pdf", {})
    assert ok
    assert "\\includepdf{SUPP.pdf}" in (tmp_path / "main.tex").read_text()


# ═══════════════════════════ 注册/装载面 ════════════════════════════════


def test_orphan_builtins_registered() -> None:
    """六个新 builtin 注册进 TRANSFORM_FNS (rules.yaml function: 面)。"""
    for name in (
        "generated_stub",
        "docstrip_generate",
        "plain_format_detect",
        "harvest_build_directives",
        "svg_prepare",
        "includepdf_missing_stub",
    ):
        assert callable(TRANSFORM_FNS[name])


def test_orphan_rule_ids_in_ruleset() -> None:
    """八条新规则 id 在合并 ruleset 内且 function 字段对上注册名。"""
    by_id = {r.id: r for r in load_ruleset().rules}
    want = {
        "plain_format_route": "plain_format_detect",
        "svg_route": None,  # reject_route 原语, 无 builtin
        "build_directive_harvest": "harvest_build_directives",
        "rungen_stub": "generated_stub",
        "nonctan_input_stub": "generated_stub",
        "docstrip_generate": "docstrip_generate",
        "svg_prepare": "svg_prepare",
        "includepdf_missing_stub": "includepdf_missing_stub",
    }
    for rid, fn in want.items():
        assert rid in by_id, rid
        if fn is not None:
            assert (by_id[rid].raw.get("action") or {}).get("function") == fn
    assert builtins.generated_stub is TRANSFORM_FNS["generated_stub"]


# ═══════════════ o2-builtin-cs 面 (m1b-residue-routes-2026-09-17) ═══════════
# 四个 builtin: undefined_env_polyfill / undefine_for_redef 批量+站点 /
# font_cs_shim (AMS 上古字体) / cs_rebind (produced-by-cs 缺字)。
# log 侧固定走 ``{main stem}.log`` (_fixloop_log 定位序)。

_MAIN_DOCCLASS = "\\documentclass{article}\n"


def _write_main(tmp_path: Path, body: str) -> None:
    (tmp_path / "main.tex").write_text(_MAIN_DOCCLASS + body)


# ─── undefined_env_polyfill ───


def test_env_polyfill_multi_env_batch(tmp_path: Path) -> None:
    """1012.1059 形: 一轮 log 三 env 同缺 → 一次全清 (\\ifcsname 守卫 noop)。"""
    _write_main(
        tmp_path,
        "\\begin{document}\n"
        "\\begin{example}e\\end{example}\n"
        "\\begin{definition}d\\end{definition}\n"
        "\\begin{theorem}t\\end{theorem}\n"
        "\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:3: LaTeX Error: Environment example undefined.\n"
        "main.tex:4: LaTeX Error: Environment definition undefined.\n"
        "main.tex:5: LaTeX Error: Environment theorem undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        _ctx(tmp_path), None, "example", {"deny": ["document"]}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    for e in ("example", "definition", "theorem"):
        assert f"\\newenvironment{{{e}}}{{}}" in t, e
        assert f"\\ifcsname {e}\\endcsname" in t


def test_env_polyfill_math_env_shell(tmp_path: Path) -> None:
    """数学 env 给 ``\\[..\\]`` 壳兜底数学域 (MATH_ENVS 表)。"""
    _write_main(
        tmp_path,
        "\\begin{document}\n$\\begin{gather}a=b\\end{gather}$\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment gather undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        _ctx(tmp_path), None, "gather", {}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\newenvironment{gather}{\\[}{\\]}" in t


def test_env_polyfill_unused_env_declines(tmp_path: Path) -> None:
    """log 报了但源无 ``\\begin{env}`` 站点 → 不注 (窄谓词)。"""
    _write_main(tmp_path, "\\begin{document}\nx\n\\end{document}\n")
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment sidebar undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        _ctx(tmp_path), None, "sidebar", {}
    )
    assert not ok
    assert "not \\begin-used" in note


def test_env_polyfill_halt_expansion(tmp_path: Path) -> None:
    r"""halt_on_error 单行 log 只见 ``example`` —— 批扩把全部在用且无
    in-doc 定义证据的 env 一轮清 (1012.1059 实证 8env); 内核 env
    (figure) 与 ``\\newtheorem`` 已定义名 (corollary) 不注; 注入位在
    ``\\begin{document}`` 前 (``\\ifcsname`` 才能见包定义名)。"""
    _write_main(
        tmp_path,
        "\\usepackage{amsmath}\n"
        "\\newtheorem{corollary}{Cor}\n"
        "\\begin{document}\n"
        "\\begin{example}e\\end{example}\n"
        "\\begin{lemma}l\\end{lemma}\n"
        "\\begin{corollary}c\\end{corollary}\n"
        "\\begin{figure}f\\end{figure}\n"
        "\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:4: LaTeX Error: Environment example undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        _ctx(tmp_path), None, "example", {}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    for e in ("example", "lemma"):
        assert f"\\ifcsname {e}\\endcsname" in t, e
    # corollary 有 \newtheorem 活定义 → 扩面剔除; figure 内核 env → 不注
    assert "\\ifcsname corollary\\endcsname" not in t
    assert "\\ifcsname figure\\endcsname" not in t
    # 注入位在 \begin{document} 行首之前 (包装载已执行, 守卫才正确)
    assert t.index("\\ifcsname example\\endcsname") < t.index("\\begin{document}")
    # amsmath 在载 → gather 类包定义 env 若在用, 守卫行是死化无操作 ——
    # 本例未用 gather 故无其行
    assert "\\ifcsname gather\\endcsname" not in t


def test_env_polyfill_idempotent(tmp_path: Path) -> None:
    """二轮再点火: \\ifcsname 标记已见 → applied=False 不占轮次。"""
    _write_main(
        tmp_path,
        "\\begin{document}\n\\begin{lemma}l\\end{lemma}\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment lemma undefined.\n"
    )
    ctx = _ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["undefined_env_polyfill"](ctx, None, "lemma", {})
    assert ok
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](ctx, None, "lemma", {})
    assert not ok
    assert "already polyfilled" in note


def test_env_polyfill_deny_document(tmp_path: Path) -> None:
    """document 环境在 deny 表 —— 永不 noop 化。"""
    _write_main(tmp_path, "\\begin{document}\nx\n\\end{document}\n")
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment document undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        _ctx(tmp_path), None, "document", {"deny": ["document"]}
    )
    assert not ok
    assert "no undefined env" in note


# ─── undefined_env_polyfill: preamble renew 站点前置臂 ───


def test_env_polyfill_preamble_renew_site(tmp_path: Path) -> None:
    """0806.0904 形: ``\\renewenvironment{proof}`` 在序言报错 —— 守卫 noop
    前置到站点行首 (pre-begindoc 注入位在站点之后, 批扩够不到);
    renew 闸过后稿自带定义覆盖 noop, 站点行内容不动。"""
    _write_main(
        tmp_path,
        "\\usepackage{amsmath}\n"
        "\\renewenvironment{proof}{\\par\\noindent\\textbf{Pf.}}{\\par}\n"
        "\\begin{document}\n"
        "\\begin{proof}body\\end{proof}\n"
        "\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:3: LaTeX Error: Environment proof undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        _ctx(tmp_path), None, "proof", {}
    )
    assert ok, note
    assert "pre-renew noop: proof" in note
    t = (tmp_path / "main.tex").read_text()
    guard = "\\ifcsname proof\\endcsname\\else\\newenvironment{proof}{}{}\\fi"
    assert guard in t
    # 守卫落在 renew 站点行首之前, 而非 pre-begindoc 批块位
    assert t.index(guard) < t.index("\\renewenvironment{proof}")
    # proof 已站点前置 → 不占 pre-begindoc 批块
    assert t.count(guard) == 1


def test_env_polyfill_renew_site_no_begin_use(tmp_path: Path) -> None:
    """renew 站点本身即消费点 —— 无 ``\\begin{proof}`` 也修 (旧窄谓词会拒)。"""
    _write_main(
        tmp_path,
        "\\renewenvironment{sidebar}{}{}\n\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment sidebar undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        _ctx(tmp_path), None, "sidebar", {}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert t.index("\\ifcsname sidebar\\endcsname") < t.index(
        "\\renewenvironment{sidebar}"
    )


def test_env_polyfill_renew_site_in_other_file(tmp_path: Path) -> None:
    """renew 站点在非主文件 → 该文件行首前置; 主文件批块照注兜底
    (站点文件可能不被 ``\\input`` 抵达)。"""
    _write_main(
        tmp_path,
        "\\input{pre}\n"
        "\\begin{document}\n"
        "\\begin{proof}body\\end{proof}\n"
        "\\end{document}\n",
    )
    (tmp_path / "pre.tex").write_text(
        "% preamble helpers\n\\renewenvironment{proof}{}{}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "pre.tex:2: LaTeX Error: Environment proof undefined.\n"
    )
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](
        _ctx(tmp_path), None, "proof", {}
    )
    assert ok, note
    pre = (tmp_path / "pre.tex").read_text()
    assert pre.index("\\ifcsname proof\\endcsname") < pre.index(
        "\\renewenvironment{proof}"
    )
    # proof 仍在 fresh → 主文件 pre-begindoc 批块同注 (双保险)
    main = (tmp_path / "main.tex").read_text()
    assert "\\ifcsname proof\\endcsname" in main
    assert main.index("\\ifcsname proof\\endcsname") < main.index("\\begin{document}")


def test_env_polyfill_renew_dead_zone_ignored(tmp_path: Path) -> None:
    """注释掉的 ``%\\renewenvironment`` 不是站点 —— 不前置, 批块照常。"""
    _write_main(
        tmp_path,
        "%\\renewenvironment{proof}{}{}\n"
        "\\begin{document}\n"
        "\\begin{proof}body\\end{proof}\n"
        "\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:3: LaTeX Error: Environment proof undefined.\n"
    )
    ok, _note = TRANSFORM_FNS["undefined_env_polyfill"](
        _ctx(tmp_path), None, "proof", {}
    )
    assert ok
    t = (tmp_path / "main.tex").read_text()
    # 守卫只来自批块, 落在 \begin{document} 行首前, 而非注释行处
    assert t.index("\\ifcsname proof\\endcsname") < t.index("\\begin{document}")
    assert t.index("\\ifcsname proof\\endcsname") > t.index(
        "%\\renewenvironment{proof}"
    )


def test_env_polyfill_renew_inside_atbegindocument(tmp_path: Path) -> None:
    """站点裹在 ``\\AtBeginDocument{...}`` 实参里 —— 行首锚前置落活区,
    hook 执行时 env 已定义。"""
    _write_main(
        tmp_path,
        "\\AtBeginDocument{\\renewenvironment{proof}{}{}}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment proof undefined.\n"
    )
    ok, _note = TRANSFORM_FNS["undefined_env_polyfill"](
        _ctx(tmp_path), None, "proof", {}
    )
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert t.index("\\ifcsname proof\\endcsname") < t.index("\\AtBeginDocument")


def test_env_polyfill_renew_site_no_double_prepend(tmp_path: Path) -> None:
    """再点火幂等: 首轮站点前置+批扩已全覆盖 (lemma 在批扩面),
    二轮拒修且 proof 站点守卫不重复前置。"""
    _write_main(
        tmp_path,
        "\\renewenvironment{proof}{}{}\n"
        "\\begin{document}\n"
        "\\begin{proof}p\\end{proof}\n"
        "\\begin{lemma}l\\end{lemma}\n"
        "\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Environment proof undefined.\n"
    )
    ctx = _ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["undefined_env_polyfill"](ctx, None, "proof", {})
    assert ok
    (tmp_path / "main.log").write_text(
        "main.tex:4: LaTeX Error: Environment lemma undefined.\n"
    )
    ctx.invalidate(tmp_path / "main.log")
    ok, note = TRANSFORM_FNS["undefined_env_polyfill"](ctx, None, "lemma", {})
    assert not ok
    assert "already polyfilled" in note
    t = (tmp_path / "main.tex").read_text()
    assert t.count("\\ifcsname proof\\endcsname") == 1


# ─── undefine_for_redef: 批量 + 站点前置 + other 签 ───


def test_undefine_batch_journal_cluster(tmp_path: Path) -> None:
    """1206.0299 形 (halt_on_error 实证): log 只报首撞名 \\aj, 同文件
    \\newcommand 站点簇扩 → 一轮全清 (站点前置, 不靠多行 log)。"""
    _write_main(
        tmp_path,
        "\\newcommand{\\aj}{AJ}\n"
        "\\newcommand{\\jcap}{JCAP}\n"
        "\\newcommand{\\mnras}{MNRAS}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "odg.tex:221: LaTeX Error: Command \\aj already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, "aj", {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    for cs in ("aj", "jcap", "mnras"):
        assert f"\\let\\{cs}\\@undefined" in t, cs
    # 站点前置在 \newcommand 行紧邻处
    assert (
        "\\makeatletter\\let\\mnras\\@undefined\\makeatother\n\\newcommand{\\mnras}"
        in t
    )


def test_undefine_batch_multiline_log_still_batch(tmp_path: Path) -> None:
    """非 halt 轮 (post-verify/salvage) 多行 log: 撞名集全扫仍一轮批清。"""
    _write_main(
        tmp_path,
        "\\newcommand{\\aj}{AJ}\n"
        "\\newcommand{\\jcap}{JCAP}\n"
        "\\newcommand{\\mnras}{MNRAS}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "odg.tex:221: LaTeX Error: Command \\aj already defined.\n"
        "odg.tex:222: LaTeX Error: Command \\jcap already defined.\n"
        "odg.tex:226: LaTeX Error: Command \\mnras already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, "aj", {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    for cs in ("aj", "jcap", "mnras"):
        assert f"\\let\\{cs}\\@undefined" in t, cs


def test_undefine_batch_single_collision_declines(tmp_path: Path) -> None:
    """min_batch=2 门: 孤站单撞名格 (文件仅一处站点) 让位 renew(111)。"""
    _write_main(
        tmp_path,
        "\\newcommand{\\Ref}[1]{(\\ref{#1})}\n\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\Ref already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, "Ref", {"min_batch": 2}
    )
    assert not ok
    assert "<2" in note  # 撞名∪站点兄弟 <2 → 单撞名路径


def test_undefine_single_default_path(tmp_path: Path) -> None:
    """缺省 min_batch=1 (already_def_undefine@113 路径) —— 单撞名仍修。"""
    _write_main(
        tmp_path,
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\liningnums already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, "liningnums", {}
    )
    assert ok, note
    assert "\\let\\liningnums\\@undefined" in (tmp_path / "main.tex").read_text()


def test_undefine_backtick_other_signature(tmp_path: Path) -> None:
    r"""astro-ph/0408445 形: ``Command `\X' already defined`` 反引号签
    (taxonomy 落 other, payload=None → min_batch 恒 1); halt 单行 log
    只见 \\mathbfit, 站点簇扩把 \\mathbfss 同轮清。"""
    _write_main(
        tmp_path,
        "\\usepackage{bm}\n"
        "\\DeclareMathAlphabet{\\mathbfit}{OT1}{cmm}{b}{it}\n"
        "\\DeclareMathAlphabet{\\mathbfss}{OT1}{cmss}{bx}{n}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "PolarShapelets.tex:342: LaTeX Error: Command `\\mathbfit' already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, None, {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert (
        "\\makeatletter\\let\\mathbfit\\@undefined\\makeatother\n"
        "\\DeclareMathAlphabet{\\mathbfit}"
    ) in t
    assert "\\let\\mathbfss\\@undefined" in t


def test_undefine_allocated_name_guard(tmp_path: Path) -> None:
    """2211.04482 护栏: \\newbox\\splitbox 分配名 → 弃修 (Let 后名被抢占炸 Missing number)。"""
    _write_main(
        tmp_path,
        "\\newbox\\splitbox\n\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\splitbox already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](_ctx(tmp_path), None, "splitbox", {})
    assert not ok
    assert "allocated" in note  # 与 bblwall 钉同一 abstain 注记面


def test_undefine_cls_site_no_catcode_wrap(tmp_path: Path) -> None:
    r"""1706.00221 实证: .cls/.sty 内 @ 本是 letter —— 站点前置在包文件
    内必须裸 ``\\let`` (无 ``\\makeatletter`` 对); 尾部 ``\\makeatother``
    会把 @ 翻回 catcode-12, 其后 ``\\define@key`` 族全烂。"""
    _write_main(tmp_path, "\\begin{document}\nx\n\\end{document}\n")
    (tmp_path / "foo.cls").write_text(
        "\\newcommand{\\aj}{AJ}\n\\newcommand{\\jcap}{J}\n\\def\\define@key#1{#1}\n",
    )
    (tmp_path / "main.log").write_text(
        "foo.cls:1: LaTeX Error: Command \\aj already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, "aj", {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "foo.cls").read_text()
    assert "\\let\\aj\\@undefined\n\\newcommand{\\aj}" in t
    assert "\\let\\jcap\\@undefined\n\\newcommand{\\jcap}" in t
    assert "makeatletter" not in t
    assert "makeatother" not in t


def test_undefine_theorem_style_payload_dropped(tmp_path: Path) -> None:
    """Theorem-style payload (plain, 非 cs) 不在 Command 扫集 → 丢弃只信 log。"""
    _write_main(tmp_path, "\\begin{document}\nx\n\\end{document}\n")
    (tmp_path / "main.log").write_text(
        "ntheorem.sty:524: LaTeX Error: Theorem style plain already defined.\n"
        "main.tex:9: LaTeX Error: Command \\foo already defined.\n"
        "main.tex:10: LaTeX Error: Command \\bar already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, "plain", {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\let\\plain\\@undefined" not in t  # 非 Command 签 payload 不送信
    assert "\\let\\foo\\@undefined" in t
    assert "\\let\\bar\\@undefined" in t


def test_undefine_site_prepend_idempotent(tmp_path: Path) -> None:
    """二轮: 站点已有 \\let 前置 + docclass 块已注 → applied=False。"""
    _write_main(
        tmp_path,
        "\\newcommand{\\aj}{AJ}\n\\newcommand{\\mnras}{M}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\aj already defined.\n"
        "main.tex:2: LaTeX Error: Command \\mnras already defined.\n"
    )
    ctx = _ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["undefine_for_redef"](ctx, None, "aj", {"min_batch": 2})
    assert ok
    ok, note = TRANSFORM_FNS["undefine_for_redef"](ctx, None, "aj", {"min_batch": 2})
    assert not ok
    assert "already cleared" in note


# ─── W151: end* 恒拒名形 (\@ifdefinable \@qend 前缀拒, 与定义态无关) ───


def test_undefine_endstar_provide_site_rc_bypass(tmp_path: Path) -> None:
    r"""W151 主钉 (o2-stub-fill ``\providecommand{\endproof}`` r1→r2 死循环
    实证): undefined 态 ``\endproof`` + provide 站点 → ``\@ifdefinable``
    恒炸 already_def; ``\let\endproof\@undefined`` 清位徒劳。
    end* 名 × ``\@ifdefinable`` 路由命令 → rc@ 单发旁路前置。"""
    _write_main(
        tmp_path,
        "\\providecommand{\\endproof}{\\endtrivlist}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\endproof already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](_ctx(tmp_path), None, "endproof", {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert (
        "\\makeatletter\\let\\@ifdefinable\\@rc@ifdefinable\\makeatother\n"
        "\\providecommand{\\endproof}"
    ) in t
    # 恒拒名不注无效的 \@undefined 清位 (docclass 块亦不收)
    assert "\\let\\endproof\\@undefined" not in t


def test_undefine_endstar_newcommand_batch_mixed(tmp_path: Path) -> None:
    r"""end* + 非 end* 混合撞名批清: ``\newcommand{\endproof}`` 站走 rc@,
    ``\newcommand{\aj}`` 站仍走 ``\let``; end* 名不进 docclass 块。"""
    _write_main(
        tmp_path,
        "\\newcommand{\\endproof}{P}\n\\newcommand{\\aj}{A}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\endproof already defined.\n"
        "main.tex:2: LaTeX Error: Command \\aj already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, "endproof", {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert (
        "\\makeatletter\\let\\@ifdefinable\\@rc@ifdefinable\\makeatother\n"
        "\\newcommand{\\endproof}"
    ) in t
    assert "\\let\\aj\\@undefined" in t  # 非 end* 路径不变 (站点+docclass 双修)
    assert "\\let\\endproof\\@undefined" not in t


def test_undefine_endstar_min_batch_collapses(tmp_path: Path) -> None:
    r"""孤站单 end* 撞名 (min_batch=2 门): renew(111) 对 undefined-end* 的
    ``\@ifundefined`` 报错在 halt_on_error 下同卡死 → 该名形不能让位,
    fire_set 含 end* 名即坍缩 min_batch=1 由批路径收。"""
    _write_main(
        tmp_path,
        "\\newcommand{\\endnote}{N}\n\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\endnote already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, "endnote", {"min_batch": 2}
    )
    assert ok, note
    assert "\\let\\@ifdefinable\\@rc@ifdefinable" in (tmp_path / "main.tex").read_text()


def test_undefine_endstar_ltcmd_site_keeps_let(tmp_path: Path) -> None:
    r"""``\NewDocumentCommand`` 站 (ltcmd ``\cs_if_exist``, 无 end 守卫):
    end* 名仍走 ``\let\X\@undefined`` —— rc@ 前置不食 ``\@ifdefinable``
    会泄给下个用户。"""
    _write_main(
        tmp_path,
        "\\NewDocumentCommand{\\endnote}{}\n"
        "\\newcommand{\\aj}{A}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX cmd Error: Command '\\endnote' already defined.\n"
        "main.tex:2: LaTeX Error: Command \\aj already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](_ctx(tmp_path), None, "endnote", {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert (
        "\\makeatletter\\let\\endnote\\@undefined\\makeatother\n"
        "\\NewDocumentCommand{\\endnote}"
    ) in t


def test_undefine_endstar_siteless_declines(tmp_path: Path) -> None:
    r"""end* 撞名无站点可指 (包内/csname 构名) → 不注徒劳 ``\let`` (毁既有
    义且重定义侧仍恒拒) —— decline 交下位规则。"""
    _write_main(tmp_path, "\\begin{document}\nx\n\\end{document}\n")
    (tmp_path / "main.log").write_text(
        "pkg.sty:9: LaTeX Error: Command \\endfoo already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](_ctx(tmp_path), None, "endfoo", {})
    assert not ok
    assert "endfoo" in note
    assert "\\let\\endfoo" not in (tmp_path / "main.tex").read_text()


def test_undefine_relax_reserved_abstains(tmp_path: Path) -> None:
    r"""``\@qrelax`` 同恒拒 + ``\relax`` 是 primitive: ``\let\@undefined``
    注毁其义, rc@ 旁路真重定义 —— 皆全局灾难, 弃修。"""
    _write_main(
        tmp_path,
        "\\newcommand{\\relax}{X}\n\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\relax already defined.\n"
    )
    ok, _note = TRANSFORM_FNS["undefine_for_redef"](_ctx(tmp_path), None, "relax", {})
    assert not ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\let\\relax" not in t
    assert "rc@ifdefinable" not in t


def test_undefine_endstar_provide_nonendstar_untouched(tmp_path: Path) -> None:
    r"""非 end* 名 ``\providecommand`` 站点不入列: 撞名静默族前置清位反夺
    cls 定义 —— guilty 文件内 ``\providecommand{\foo}`` 不吃 prepend。"""
    _write_main(
        tmp_path,
        "\\providecommand{\\foo}{F}\n\\newcommand{\\aj}{A}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Command \\aj already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](_ctx(tmp_path), None, "aj", {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\let\\aj\\@undefined" in t
    assert "\\let\\foo" not in t  # provide 站点非恒拒名 —— 不动


def test_undefine_endstar_rc_prepend_idempotent(tmp_path: Path) -> None:
    """二轮: rc@ 前置已见 (64 字窗幂等) → applied=False 不占轮次。"""
    _write_main(
        tmp_path,
        "\\providecommand{\\endproof}{P}\n\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command \\endproof already defined.\n"
    )
    ctx = _ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["undefine_for_redef"](ctx, None, "endproof", {})
    assert ok
    ok, note = TRANSFORM_FNS["undefine_for_redef"](ctx, None, "endproof", {})
    assert not ok
    assert "endproof" in note  # end* 无新站点可做 → defer 注记


# ─── font_cs_shim (AMS 上古字体 cs) ───


def test_font_cs_shim_skewchar_chain(tmp_path: Path) -> None:
    r"""hep-th/9703214 形: \\doit{0} 死块内 \\font 定义不执行 →
    活 \\skewchar\\fivmi 链 undefined_cs → \\font\\fivmi=cmmi10 at 5pt 注入
    (eng=None 不可探 tfm → at-尺寸兜底)。"""
    _write_main(
        tmp_path,
        "\\def\\doit#1#2{\\ifnum#1>0 #2\\fi}\n"
        "\\doit{0}{\\font\\fivmi=cmmi5 \\font\\fivsy=cmsy5}\n"
        "\\begin{document}\n\\skewchar\\fivmi=127 \\skewchar\\fivsy=48 x\n"
        "\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:4: Undefined control sequence.\nl.4 \\skewchar\\fivmi\n"
        "main.tex:4: Undefined control sequence.\nl.4 \\skewchar\\fivsy\n"
    )
    ok, note = TRANSFORM_FNS["font_cs_shim"](_ctx(tmp_path), None, "fivmi", {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\font\\fivmi=cmmi10 at 5pt" in t
    assert "\\font\\fivsy=cmsy10 at 5pt" in t


def test_font_cs_shim_nonfont_payload_declines(tmp_path: Path) -> None:
    """窄谓词: payload 不匹 <size><fam> 模式 → 落穿 cs_targeted_fix/guess。"""
    _write_main(tmp_path, "\\begin{document}\n\\textbf x\n\\end{document}\n")
    (tmp_path / "main.log").write_text(
        "main.tex:2: Undefined control sequence.\nl.2 \\textbf\n"
    )
    ok, note = TRANSFORM_FNS["font_cs_shim"](_ctx(tmp_path), None, "textbf", {})
    assert not ok
    assert "not an AMS-era font name" in note


def test_font_cs_shim_def_evidence_excluded(tmp_path: Path) -> None:
    """<size><fam> 名若另有 \\def 系定义证据 → 不接管 (真宏撞名防毁)。"""
    _write_main(
        tmp_path,
        "\\def\\tenbf{bold macro}\n\\begin{document}\n\\textfont9=\\tenbf\n"
        "\\end{document}\n",
    )
    (tmp_path / "main.log").write_text("")  # log 无 undefined 报错
    ok, note = TRANSFORM_FNS["font_cs_shim"](_ctx(tmp_path), None, "tenbf", {})
    assert not ok
    assert "no AMS font cs" in note


def test_font_cs_shim_idempotent(tmp_path: Path) -> None:
    """二轮: \\font\\<cs>= 已在文本且该 cs 本轮未报错 → applied=False。"""
    _write_main(
        tmp_path,
        "\\begin{document}\n\\skewchar\\ninmi=60 x\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: Undefined control sequence.\nl.2 \\skewchar\\ninmi\n"
    )
    ctx = _ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["font_cs_shim"](ctx, None, "ninmi", {})
    assert ok
    # 二轮 log 无报错 (清干净后) → pos_used 名有活 \\font 定义 → 跳
    (tmp_path / "main.log").write_text("This is XeTeX log — clean\n")
    ctx.invalidate(tmp_path / "main.log")
    ok, note = TRANSFORM_FNS["font_cs_shim"](ctx, None, "ninmi", {})
    assert not ok
    assert "already shimmed" in note


# ─── cs_rebind (produced-by-cs 缺字) ───


def test_cs_rebind_section_sign(tmp_path: Path) -> None:
    r"""2403.15096 形: \\S→§ 在 cmr10 缺字, 源无字面 § →
    \\protected\\def\\S 绑 txlatefallback。"""
    _write_main(
        tmp_path,
        "\\begin{document}\nSee \\S 7 and \\S 9 for details.\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        'Missing character: There is no § ("A7) in font cmr10!\n'
    )
    ok, note = TRANSFORM_FNS["cs_rebind"](_ctx(tmp_path), None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\newfontfamily\\txlatefallback{Libertinus Serif}" in t
    assert "\\protected\\def\\S{\\ifmmode\\mbox{\\txlatefallback §}" in t


def test_cs_rebind_literal_char_owns(tmp_path: Path) -> None:
    """字面 § 在源 → literal 面 (missing_char_fix/font_fallback) 先修, 本规退。"""
    _write_main(
        tmp_path,
        "\\begin{document}\nSee § 7 and \\S 9.\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        'Missing character: There is no § ("A7) in font cmr10!\n'
    )
    ok, note = TRANSFORM_FNS["cs_rebind"](_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no produced-by-cs" in note


def test_cs_rebind_no_producer_declines(tmp_path: Path) -> None:
    """缺字码位无 cs 生产者 (源无 \\o) → 不落本规。"""
    _write_main(tmp_path, "\\begin{document}\nplain text\n\\end{document}\n")
    (tmp_path / "main.log").write_text(
        'Missing character: There is no ø ("F8) in font cmr9!\n'
    )
    ok, note = TRANSFORM_FNS["cs_rebind"](_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no produced-by-cs" in note


def test_cs_rebind_producers_param(tmp_path: Path) -> None:
    """params.producers hex 键扩面: 0x2022(\\bullet 产出)→\\textbullet 式 cs。"""
    _write_main(
        tmp_path,
        "\\begin{document}\n\\mydotsep item\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        'Missing character: There is no • ("2022) in font cmr10!\n'
    )
    ok, note = TRANSFORM_FNS["cs_rebind"](
        _ctx(tmp_path), None, None, {"producers": {"2022": "mydotsep"}}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\protected\\def\\mydotsep" in t
    assert "•" in t


def test_cs_rebind_idempotent(tmp_path: Path) -> None:
    """二轮: 注入块自带字面 ø → ``ch in blob`` 先行短路 → applied=False 不重注。"""
    _write_main(
        tmp_path,
        "\\begin{document}\nFr\\o{}berg\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        'Missing character: There is no ø ("F8) in font cmr9!\n'
    )
    ctx = _ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["cs_rebind"](ctx, None, None, {})
    assert ok
    ok, _note = TRANSFORM_FNS["cs_rebind"](ctx, None, None, {})
    assert not ok
    t = (tmp_path / "main.tex").read_text()
    assert t.count("\\protected\\def\\o") == 1  # 不重注


# ─── 注册/装载面 (本批) ───


def test_bcs_builtins_registered() -> None:
    """本批三个新 builtin + 复用 undefine_for_redef 均注册进 TRANSFORM_FNS。"""
    for name in (
        "undefined_env_polyfill",
        "font_cs_shim",
        "cs_rebind",
        "undefine_for_redef",
    ):
        assert callable(TRANSFORM_FNS[name])


def test_bcs_rule_ids_in_ruleset() -> None:
    """四条新规则 id 在合并 ruleset 内且 function/序位对上。"""
    by_id = {r.id: r for r in load_ruleset().rules}
    want = {
        "missing_char_cs_rebind": "cs_rebind",
        "already_def_batch_undefine": "undefine_for_redef",
        "ams_font_cs_shim": "font_cs_shim",
        "undefined_env_polyfill": "undefined_env_polyfill",
    }
    for rid, fn in want.items():
        assert rid in by_id, rid
        assert (by_id[rid].raw.get("action") or {}).get("function") == fn
    # 序位钉: 批清位在 renew(111) 前; cs_rebind 在 font_fallback(26) 前;
    # font shim 在 cs_targeted_fix(165) 前; env polyfill 在 abstract(168) 后
    orders = {r.id: r.order for r in load_ruleset().rules}
    assert orders["already_def_batch_undefine"] < orders["already_def_newcmd_renew"]
    assert orders["missing_char_cs_rebind"] < orders["font_fallback"]
    assert orders["ams_font_cs_shim"] < orders["cs_targeted_fix"]
    assert orders["undefined_env_polyfill"] > orders["abstract_frontmatter_hoist"]
