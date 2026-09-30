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

o2-builtin-cs 批 (env_polyfill/undefine/font_cs_shim/cs_rebind) 已拆
``test_fixloop_orphan_bcs.py``。
"""

import shutil
from pathlib import Path

import pytest
from _fixloopkit import mk_ctx, rs, which_only

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx, RunFn

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
        mk_ctx(tmp_path), None, "foots.tmp", {"faces": ["openout"]}
    )
    assert ok, note
    assert "openout-stub" in note
    assert "% fixloop" in (tmp_path / "foots.tmp").read_text()


def test_rungen_stub_bare_digit_stream(tmp_path: Path) -> None:
    """plain 形 ``\\openout0=refs.tmp`` (stream 为裸数字) 同收。"""
    (tmp_path / "main.tex").write_text("\\openout0=refs.tmp\n\\bye\n")
    ok, _note = TRANSFORM_FNS["generated_stub"](
        mk_ctx(tmp_path), None, "refs.tmp", {"faces": ["openout"]}
    )
    assert ok


def test_rungen_stub_braced_and_immediate(tmp_path: Path) -> None:
    """花括号名 ``\\openout\\w={x.tmp}`` 与 ``\\immediate\\openout`` 前缀同收。"""
    (tmp_path / "main.tex").write_text(
        "\\immediate\\openout\\w={notes.tmp}\n\\openout\\z = data.tmp\n"
    )
    for name in ("notes.tmp", "data.tmp"):
        ok, note = TRANSFORM_FNS["generated_stub"](
            mk_ctx(tmp_path), None, name, {"faces": ["openout"]}
        )
        assert ok, (name, note)


def test_rungen_stub_comment_masked(tmp_path: Path) -> None:
    """``%\\openout\\w=x.tmp`` 注释内目标不算数。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n%\\openout\\w=x.tmp\n\\begin{document}\\end{document}\n"
    )
    ok, note = TRANSFORM_FNS["generated_stub"](
        mk_ctx(tmp_path), None, "x.tmp", {"faces": ["openout"]}
    )
    assert not ok
    assert "not a generated" in note


def test_rungen_stub_not_target_declines(tmp_path: Path) -> None:
    """真 CTAN 件名 (不在 openout 集) → False 落 install_file。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    ok, _note = TRANSFORM_FNS["generated_stub"](
        mk_ctx(tmp_path), None, "real.sty", {"faces": ["openout"]}
    )
    assert not ok


def test_generated_stub_unsafe_payload(tmp_path: Path) -> None:
    """绝对路径/../逃逸/NUL → False 不写 (vendored_fetch 同款闸)。"""
    (tmp_path / "main.tex").write_text("\\openout\\w=evil.tmp\n")
    for bad in ("../evil.tmp", "/abs/evil.tmp", "a\x00b.tmp"):
        ok, note = TRANSFORM_FNS["generated_stub"](
            mk_ctx(tmp_path), None, bad, {"faces": ["openout", "overlay"]}
        )
        assert not ok, bad
        assert "unsafe" in note


def test_rungen_stub_existing_not_overwritten(tmp_path: Path) -> None:
    """盘上已有真件 → False 不覆盖 (L10 指纹闸: 无指纹无名分=外来件)。"""
    (tmp_path / "main.tex").write_text("\\openout\\w=foots.tmp\n")
    (tmp_path / "foots.tmp").write_text("real content\n")
    ok, note = TRANSFORM_FNS["generated_stub"](
        mk_ctx(tmp_path), None, "foots.tmp", {"faces": ["openout"]}
    )
    assert not ok
    assert "foreign" in note or "already on disk" in note
    assert (tmp_path / "foots.tmp").read_text() == "real content\n"


def test_rungen_stub_idempotent(tmp_path: Path) -> None:
    """二次触火: stub 已在盘 → False。"""
    (tmp_path / "main.tex").write_text("\\openout\\w=foots.tmp\n")
    ctx = mk_ctx(tmp_path)
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
            mk_ctx(tmp_path), None, name, {"faces": ["overlay"]}
        )
        assert ok, (name, note)
        assert "overlay-stub" in note


def test_overlay_stub_non_overlay_declines(tmp_path: Path) -> None:
    """普通缺件扩展名 → False 落 install_file。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    ok, _note = TRANSFORM_FNS["generated_stub"](
        mk_ctx(tmp_path), None, "pic.pdf", {"faces": ["overlay"]}
    )
    assert not ok


def test_overlay_stub_subdir_relpath(tmp_path: Path) -> None:
    """payload 带目录前缀 → stub 落同名相对路径下 (父目录自动建)。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    ok, _note = TRANSFORM_FNS["generated_stub"](
        mk_ctx(tmp_path), None, "figs/plot.pdf_t", {"faces": ["overlay"]}
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


def test_docstrip_stem_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``aipproc.ins`` stem 匹配 payload ``aipproc.cls`` → 抽取成功 applied。"""
    monkeypatch.setattr(shutil, "which", which_only("latex"))
    (tmp_path / "aipproc.ins").write_text("\\input aipproc.dtx\n")
    (tmp_path / "main.tex").write_text("\\documentclass{aipproc}\n")
    ctx = mk_ctx(tmp_path, runner=_docstrip_ok("aipproc.cls"))
    ok, note = TRANSFORM_FNS["docstrip_generate"](ctx, None, "aipproc.cls", {})
    assert ok, note
    assert "aipproc.ins" in note
    assert (tmp_path / "aipproc.cls").is_file()
    assert any("docstrip" in e for e in ctx.events)


def test_docstrip_unique_ins_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stem 不对应但包内唯一 .ins → 兜底试一次 (aipproc.ins 出 fix2col.sty 族)。"""
    monkeypatch.setattr(shutil, "which", which_only("latex"))
    (tmp_path / "bundle.ins").write_text("\\input bundle.dtx\n")
    (tmp_path / "main.tex").write_text("x\n")
    ctx = mk_ctx(tmp_path, runner=_docstrip_ok("fix2col.sty"))
    ok, _note = TRANSFORM_FNS["docstrip_generate"](ctx, None, "fix2col.sty", {})
    assert ok


def test_docstrip_no_ins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", which_only("latex"))
    (tmp_path / "main.tex").write_text("x\n")
    ok, note = TRANSFORM_FNS["docstrip_generate"](mk_ctx(tmp_path), None, "x.cls", {})
    assert not ok
    assert "no .ins" in note


def test_docstrip_no_driver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """latex 系 driver 全缺席 → False 落 install_file 装 TL 版。"""
    monkeypatch.setattr(shutil, "which", which_only())
    (tmp_path / "aipproc.ins").write_text("\\input aipproc.dtx\n")
    ok, note = TRANSFORM_FNS["docstrip_generate"](
        mk_ctx(tmp_path), None, "aipproc.cls", {}
    )
    assert not ok
    assert "no latex-family driver" in note


def test_docstrip_run_but_not_produced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ins 跑完但 payload 未落盘 → False (同轮 install_file 兜底)。"""
    monkeypatch.setattr(shutil, "which", which_only("latex"))
    (tmp_path / "aipproc.ins").write_text("x\n")

    def _noop(_argv: list[str], _t: int, _w: Path) -> tuple:
        return 0, "", 0.1, False

    ok, note = TRANSFORM_FNS["docstrip_generate"](
        mk_ctx(tmp_path, runner=_noop), None, "aipproc.cls", {}
    )
    assert not ok
    assert "not produced" in note


def test_docstrip_unsafe_payload(tmp_path: Path) -> None:
    (tmp_path / "aipproc.ins").write_text("x\n")
    ok, note = TRANSFORM_FNS["docstrip_generate"](
        mk_ctx(tmp_path), None, "../evil.cls", {}
    )
    assert not ok
    assert "unsafe" in note


# ------------------------------------------- docstrip 兄弟产出缓存失效 (logcache 病族)
def _docstrip(ctx: LoopCtx, payload: str) -> tuple[bool, str]:
    return TRANSFORM_FNS["docstrip_generate"](ctx, None, payload, {"drivers": ["sh"]})


def test_docstrip_sibling_outputs_invalidated(tmp_path: Path) -> None:
    """None-poison 主案: pre-run 读过缺件缓存 miss→None, docstrip 一次
    抽多件落地后, 请求件与兄弟产出的缓存同让位 (旧码只 invalidate hit,
    兄弟 stale-None 毒化下游)。runner 注入面写两件, 不跑真 latex。"""
    (tmp_path / "foo.ins").write_text("\\input docstrip\n", encoding="utf-8")

    def _runner(_argv: list[str], _timeout: int, wdir: Path) -> tuple:
        (wdir / "foo.cls").write_text("\\ProvidesClass{foo}\n", encoding="utf-8")
        (wdir / "foosub.sty").write_text(
            "\\ProvidesPackage{foosub}\n", encoding="utf-8"
        )
        return 0, "ok", 0.0, False

    ctx = mk_ctx(tmp_path, runner=_runner)
    assert ctx.read(tmp_path / "foo.cls") is None
    assert ctx.read(tmp_path / "foosub.sty") is None  # miss→None 毒化入缓存
    ok, note = _docstrip(ctx, "foo.cls")
    assert ok, note
    assert ctx.read(tmp_path / "foo.cls") == "\\ProvidesClass{foo}\n"
    assert ctx.read(tmp_path / "foosub.sty") == "\\ProvidesPackage{foosub}\n"


def test_docstrip_rewritten_sibling_invalidated(tmp_path: Path) -> None:
    """改写臂: 既有件 v1 已入缓存, docstrip 重写 v2 → 缓存让位见新文
    (mtime+size 指纹 diff 命中改写, 不只新建)。"""
    (tmp_path / "foo.ins").write_text("\\input docstrip\n", encoding="utf-8")
    sibling = tmp_path / "foo.cfg"
    sibling.write_text("% v1\n", encoding="utf-8")

    def _runner(_argv: list[str], _timeout: int, wdir: Path) -> tuple:
        (wdir / "foo.cls").write_text("\\ProvidesClass{foo}\n", encoding="utf-8")
        (wdir / "foo.cfg").write_text("% v2 rewritten\n", encoding="utf-8")
        return 0, "ok", 0.0, False

    ctx = mk_ctx(tmp_path, runner=_runner)
    assert ctx.read(sibling) == "% v1\n"  # 旧文入缓存
    ok, note = _docstrip(ctx, "foo.cls")
    assert ok, note
    assert ctx.read(sibling) == "% v2 rewritten\n"


# ════════════════════ plain_format_detect (W37/W68) ═════════════════════


def test_plain_format_magnification_bye(tmp_path: Path) -> None:
    """``\\magnification`` + ``\\font\\cs=cm*`` + ``^\\bye$`` → REJECT tex-plain。"""
    (tmp_path / "main.tex").write_text(
        "\\magnification=1200\n\\font\\big=cmr12\nplain text\n\\bye\n"
    )
    ok, note = TRANSFORM_FNS["plain_format_detect"](
        mk_ctx(tmp_path), None, "\\magnification", {"route": "tex-plain"}
    )
    assert ok
    assert note.startswith("REJECT: route=tex-plain")


def test_plain_format_comment_trap_docstyle(tmp_path: Path) -> None:
    """主检出被 ``%\\documentstyle`` 骗入主的 plain 稿 —— 遮盖视图照样判 plain。"""
    (tmp_path / "main.tex").write_text(
        "%\\documentstyle{article}  % commented legacy line\n"
        "\\magnification=1200\nbody\n\\bye\n"
    )
    ok, note = TRANSFORM_FNS["plain_format_detect"](mk_ctx(tmp_path), None, None, {})
    assert ok
    assert "REJECT" in note


def test_plain_format_bare_end_and_amstex(tmp_path: Path) -> None:
    """``\\input amstex`` 装载 + 裸行 ``\\end`` → plain。"""
    (tmp_path / "main.tex").write_text("\\input amstex\nsome text\n\\end\n")
    ok, note = TRANSFORM_FNS["plain_format_detect"](mk_ctx(tmp_path), None, None, {})
    assert ok
    assert "input-amstex" in note or "end" in note


def test_plain_format_latex_with_plain_ism_declines(tmp_path: Path) -> None:
    """活 ``\\documentclass`` + ``\\font\\small=cmr8`` 遗留写法 → 非 plain。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\font\\small=cmr8\n\\begin{document}\\end{document}\n"
    )
    ok, note = TRANSFORM_FNS["plain_format_detect"](mk_ctx(tmp_path), None, None, {})
    assert not ok
    assert "documentclass" in note


def test_plain_format_sig_only_in_comment(tmp_path: Path) -> None:
    """签名只活在注释里 → False (遮盖视图口径)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n%\\bye\n\\begin{document}\\end{document}\n"
    )
    ok, _note = TRANSFORM_FNS["plain_format_detect"](mk_ctx(tmp_path), None, None, {})
    assert not ok


def test_plain_format_no_sigs(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text("just prose, no cs at all\n")
    ok, note = TRANSFORM_FNS["plain_format_detect"](mk_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no plain-format" in note


# ════════════════════ harvest_build_directives (W58) ════════════════════


def test_harvest_arara_shell_flag(tmp_path: Path) -> None:
    """``% arara: pdflatex: { shell: on }`` → engine_flags 请 -shell-escape + advisory。"""
    (tmp_path / "main.tex").write_text(
        "% arara: pdflatex: { shell: on }\n\\documentclass{article}\n"
    )
    ctx = mk_ctx(tmp_path)
    ok, note = TRANSFORM_FNS["harvest_build_directives"](ctx, None, None, {})
    assert ok, note
    assert "-shell-escape" in ctx.engine_flags
    assert any("arara" in a for a in ctx.advisories)


def test_harvest_tex_program_advisory(tmp_path: Path) -> None:
    """``% !TEX program = lualatex`` → route hint 记 advisories, 不请 flag。"""
    (tmp_path / "main.tex").write_text(
        "% !TEX program = lualatex\n\\documentclass{article}\n"
    )
    ctx = mk_ctx(tmp_path)
    ok, _note = TRANSFORM_FNS["harvest_build_directives"](ctx, None, None, {})
    assert ok
    assert any("lualatex" in a for a in ctx.advisories)
    assert not ctx.engine_flags


def test_harvest_tex_options_shell(tmp_path: Path) -> None:
    """``% !TEX options = --shell-escape`` 同进 flag 面。"""
    (tmp_path / "main.tex").write_text(
        "% !TEX options = --shell-escape\n\\documentclass{article}\n"
    )
    ctx = mk_ctx(tmp_path)
    ok, _note = TRANSFORM_FNS["harvest_build_directives"](ctx, None, None, {})
    assert ok
    assert "-shell-escape" in ctx.engine_flags


def test_harvest_nothing(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\\end{document}\n"
    )
    ctx = mk_ctx(tmp_path)
    ok, _note = TRANSFORM_FNS["harvest_build_directives"](ctx, None, None, {})
    assert not ok


def test_harvest_flag_no_dupe(tmp_path: Path) -> None:
    """flag 已在 engine_flags → 不重复请 (幂等)。"""
    (tmp_path / "main.tex").write_text(
        "% arara: pdflatex: { shell: yes }\n% arara: makeglossaries\n"
        "\\documentclass{article}\n"
    )
    ctx = mk_ctx(tmp_path)
    ctx.engine_flags.append("-shell-escape")
    ok, _note = TRANSFORM_FNS["harvest_build_directives"](ctx, None, None, {})
    assert ok
    assert ctx.engine_flags == ["-shell-escape"]


# ═══════════════════════════ svg_prepare (W31) ══════════════════════════

SVG_MAIN = (
    "\\documentclass{article}\n\\usepackage{svg}\n\\begin{document}\n"
    "\\includesvg[width=0.8\\linewidth,pretex=\\small]{figs/a.svg}\n\\end{document}\n"
)


def _svg_conv_ok(argv: list[str], _t: int, _w: Path) -> tuple:
    """假 rsvg-convert: ``-o`` 目标写伪 pdf。"""
    Path(argv[argv.index("-o") + 1]).write_bytes(b"%PDF-fake")
    return 0, "", 0.1, False


def test_svg_prepare_flag_arm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """inkscape 在 → engine_flags 请 -shell-escape, 不改写源; 二次触火 False。"""
    monkeypatch.setattr(shutil, "which", which_only("inkscape"))
    (tmp_path / "figs").mkdir()
    (tmp_path / "figs" / "a.svg").write_bytes(b"<svg/>")
    (tmp_path / "main.tex").write_text(SVG_MAIN)
    ctx = mk_ctx(tmp_path)
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
    monkeypatch.setattr(shutil, "which", which_only("rsvg-convert"))
    (tmp_path / "figs").mkdir()
    (tmp_path / "figs" / "a.svg").write_bytes(b"<svg/>")
    (tmp_path / "main.tex").write_text(SVG_MAIN)
    ctx = mk_ctx(tmp_path, runner=_svg_conv_ok)
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
    monkeypatch.setattr(shutil, "which", which_only("inkscape", "rsvg-convert"))
    (tmp_path / "a.svg").write_bytes(b"<svg/>")
    (tmp_path / "main.tex").write_text(SVG_MAIN.replace("figs/a.svg", "a.svg"))
    ctx = mk_ctx(tmp_path, runner=_svg_conv_ok)
    ctx.engine_flags.append("-shell-escape")
    ctx.flags_dropped.append("-shell-escape")
    ok, _note = TRANSFORM_FNS["svg_prepare"](ctx, None, None, {})
    assert ok
    assert (tmp_path / "a.pdf").is_file()


def test_svg_prepare_no_svg_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注释掉的 ``%\\usepackage{svg}`` 不算在用 → False (遮盖视图口径)。"""
    monkeypatch.setattr(shutil, "which", which_only("rsvg-convert"))
    (tmp_path / "a.svg").write_bytes(b"<svg/>")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n%\\usepackage{svg}\n\\begin{document}\\end{document}\n"
    )
    ok, note = TRANSFORM_FNS["svg_prepare"](mk_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no live svg" in note


def test_svg_prepare_no_svg_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """inkscape 缺席且盘上无 .svg → False 让位。"""
    monkeypatch.setattr(shutil, "which", which_only())
    (tmp_path / "main.tex").write_text(SVG_MAIN)
    ok, note = TRANSFORM_FNS["svg_prepare"](mk_ctx(tmp_path), None, "a_svg-tex.pdf", {})
    assert not ok
    assert "no .svg" in note


def test_svg_prepare_convert_all_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """转换器全败 → False 不谎报, 无残留半文件。"""
    monkeypatch.setattr(shutil, "which", which_only("rsvg-convert"))
    (tmp_path / "a.svg").write_bytes(b"<svg/>")
    (tmp_path / "main.tex").write_text(SVG_MAIN.replace("figs/a.svg", "a.svg"))

    def _fail(_argv: list[str], _t: int, _w: Path) -> tuple:
        return 1, "boom", 0.1, False

    ok, note = TRANSFORM_FNS["svg_prepare"](
        mk_ctx(tmp_path, runner=_fail), None, None, {}
    )
    assert not ok
    assert "all failed" in note
    assert not (tmp_path / "a.pdf").exists()


def test_svg_prepare_convert_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """二次触火: pdf 复用 + 无活 \\includesvg → False。"""
    monkeypatch.setattr(shutil, "which", which_only("rsvg-convert"))
    (tmp_path / "a.svg").write_bytes(b"<svg/>")
    (tmp_path / "main.tex").write_text(SVG_MAIN.replace("figs/a.svg", "a.svg"))
    ctx = mk_ctx(tmp_path, runner=_svg_conv_ok)
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
        mk_ctx(tmp_path), None, "supp.pdf", {}
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
        mk_ctx(tmp_path), None, "supp.pdf", {}
    )
    assert not ok
    assert "\\includepdf{supp.pdf}" in (tmp_path / "main.tex").read_text()


def test_includepdf_stub_comment_masked(tmp_path: Path) -> None:
    """注释内 ``%\\includepdf{gone.pdf}`` 不动; payload 不中的活引用也不动。"""
    (tmp_path / "main.tex").write_text(
        "%\\includepdf{gone.pdf}\n\\includepdf{other.pdf}\n"
    )
    ok, note = TRANSFORM_FNS["includepdf_missing_stub"](
        mk_ctx(tmp_path), None, "gone.pdf", {}
    )
    assert not ok
    assert "no live" in note
    assert "\\includepdf{other.pdf}" in (tmp_path / "main.tex").read_text()


def test_includepdf_stub_idempotent(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text("\\includepdf{gone.pdf}\n")
    ctx = mk_ctx(tmp_path)
    ok1, _ = TRANSFORM_FNS["includepdf_missing_stub"](ctx, None, "gone.pdf", {})
    ok2, _ = TRANSFORM_FNS["includepdf_missing_stub"](ctx, None, "gone.pdf", {})
    assert ok1
    assert not ok2


def test_includepdf_stub_ci_hit(tmp_path: Path) -> None:
    """payload ``SUPP.PDF`` vs 引用 ``{supp.pdf}`` —— ci 命中同 stub。"""
    (tmp_path / "main.tex").write_text("\\includepdf{supp.pdf}\n")
    ok, _note = TRANSFORM_FNS["includepdf_missing_stub"](
        mk_ctx(tmp_path), None, "SUPP.PDF", {}
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
    ok, _note = TRANSFORM_FNS["graphic_case_link"](
        mk_ctx(tmp_path), None, "supp.pdf", {}
    )
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
    by_id = {r.id: r for r in rs().rules}
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
