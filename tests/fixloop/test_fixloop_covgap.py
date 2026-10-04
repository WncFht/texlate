"""failmine4-covgap 三臂单测 —— missing_graphic xetex 措辞 / 位错件归位 / preamble \\if 界注入。

实证背景 (failmine4 soak-2026-09-18 census):

A) ``Unable to load picture or PDF file 'x.png'`` 是 xetex/xdvipdfmx 图形
   域缺件措辞 → missing_graphic 类目 (6 格：2501.01402/2501.01329/
   2509.14901/2501.01425/2603.08153/2604.03907).``graphic_missing_placeholder``
   原 ``when: missing_file`` 单臂永不 dispatch; 扩为 missing_file +
   missing_graphic 双臂，condition 加 xetex 措辞臂，builtin 按后缀分发
   真格式占位 (PNG/JPEG/PDF 二进制 + EPS 文本), 落盘基址改
   ``main_path().parent`` (TeX cwd 解析位 —— 子目录 main 时 wdir 根位
   不可见)。

B) ``ifacconf.cls``/``jmlr2e.sty``/``fairmeta.cls``/``acronyms1.tex`` 是
   e-print 自带件在 wdir 但不在 TeX 解析位 (compile cwd = main_dir,
   子目录 main 对根部位件不可见) —— install_file 探测 cwd=wdir 假命中
   → fired-unfixed (4 格：2609.17927/2609.19170/2609.19664/2609.20640)。
   ``fileset_relocate`` builtin 逐字节拷贝 ``<main_dir>/<payload>``,
   order:9 族首 —— 真件归位优于 stub/generate/install; 瞬态扩展名
   (.aux/.bbl/.toc…) 不搬 (2609.20323 main.aux = unclosed \\if 下游
   产物，搬陈件遮蔽真因)。

C) preamble 内开的 ``\\if`` 若任 file-end ``\\fi`` 裹住整 body, false 臂
   把 ``\\document`` (``\\@mainaux`` open) 一并吞掉 →
   ``I can't find file 'main.aux'`` emergency (2609.20323 实证)。
   ``unclosed_if_close``/``unclosed_if_close_eof`` 脚本分两段：
   ``\\begin{document}`` 前开的 ``\\if`` 注在 begdoc 行头，body 内开的
   仍注 boundary。
"""

from pathlib import Path

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport, parse_text

_RULE_GFX = "graphic_missing_placeholder"
_RULE_RELOC = "fileset_relocate"
_RULE_IFCLOSE = "unclosed_if_close"


class _EngStub:
    """builtin 直驱引擎替身 —— 三本 builtin 均 ``del eng`` 不触引擎面。"""

    def probe_file(self, fname: str, cwd: Path | None = None) -> None:
        del fname, cwd

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return False


def _rule(rid: str) -> Rule:
    return next(r for r in load_ruleset().rules if r.id == rid)


def _classify(text: str) -> tuple[str | None, str | None]:
    return load_ruleset().taxonomy.classify(parse_text(text + "\n"))


def _ctx(tmp_path: Path, main_rel: str | None = "main.tex") -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel=main_rel)


def _gfx(ctx: LoopCtx, payload: str | None) -> tuple[bool, str]:
    return TRANSFORM_FNS[_RULE_GFX](ctx, _EngStub(), payload, {})


def _reloc(ctx: LoopCtx, payload: str | None) -> tuple[bool, str]:
    return TRANSFORM_FNS[_RULE_RELOC](ctx, _EngStub(), payload, {})


def _apply(rule: Rule, wdir: Path) -> tuple[bool, str]:
    ctx = LoopCtx(wdir=wdir, engine_name="xelatex")
    return actions._apply(rule, ctx, None, None, ErrReport())  # noqa: SLF001


# ════════════════════════════ A: missing_graphic xetex 措辞臂 ════


def test_taxonomy_unable_to_load_is_missing_graphic() -> None:
    """xetex 措辞 → missing_graphic + 路径 payload (failmine4 6 格标记)。"""
    cat, pay = _classify("! Unable to load picture or PDF file 'figs/x.png'.")
    assert cat == "missing_graphic"
    assert pay == "figs/x.png"


def test_rule_gfx_when_covers_both_categories() -> None:
    """when 扩为双臂：missing_file + missing_graphic 均 payload_required。"""
    rule = _rule(_RULE_GFX)
    ctx = LoopCtx(wdir=Path("/nonexistent"), engine_name="xelatex")
    assert actions._when_ok(rule.when, "missing_file", "x.eps", ctx)  # noqa: SLF001
    assert actions._when_ok(rule.when, "missing_graphic", "x.png", ctx)  # noqa: SLF001
    # payload_required: missing_graphic 裸标记 (无路径) 不 dispatch
    assert not actions._when_ok(rule.when, "missing_graphic", None, ctx)  # noqa: SLF001
    assert not actions._when_ok(rule.when, "other", "x.png", ctx)  # noqa: SLF001


def test_rule_gfx_cond_xetex_phrasing(tmp_path: Path) -> None:
    """condition.any 含 xetex 措辞臂 —— err_head 带标记即过闸。"""
    ctx = _ctx(tmp_path)
    ctx.err_head = (
        "! Unable to load picture or PDF file 'figs/x.png'.\nl.42 \\includegraphics"
    )
    ok, why = actions._cond_ok(  # noqa: SLF001
        _rule(_RULE_GFX).condition, _rule(_RULE_GFX), ctx, None, None
    )
    assert ok, why


def test_rule_gfx_order_before_repair() -> None:
    """序自洽：includepdf_stub(17.5) < placeholder < graphic_repair(18)。"""
    orders = {r.id: r.order for r in load_ruleset().phase("loop")}
    assert orders["includepdf_missing_stub"] < orders[_RULE_GFX]
    assert orders[_RULE_GFX] < orders["graphic_repair"]


def test_gfx_placeholder_png_magic(tmp_path: Path) -> None:
    """.png payload → PNG magic 二进制占位落 wdir (main 在根)。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    ok, note = _gfx(_ctx(tmp_path), "figs/x.png")
    assert ok, note
    blob = (tmp_path / "figs" / "x.png").read_bytes()
    assert blob.startswith(b"\x89PNG\r\n\x1a\n")


def test_gfx_placeholder_jpeg_subdir_main(tmp_path: Path) -> None:
    """main 住子目录 → 占位落 main_dir (TeX cwd 解析位) 非 wdir 根。"""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "main.tex").write_text(
        "\\documentclass{article}\n", encoding="utf-8"
    )
    ctx = _ctx(tmp_path, main_rel="sub/main.tex")
    ok, note = _gfx(ctx, "img/pic.jpg")
    assert ok, note
    blob = (tmp_path / "sub" / "img" / "pic.jpg").read_bytes()
    assert blob.startswith(b"\xff\xd8\xff")
    assert not (tmp_path / "img" / "pic.jpg").exists()


def test_gfx_placeholder_pdf_magic(tmp_path: Path) -> None:
    """.pdf payload → %PDF 占位。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    ok, note = _gfx(_ctx(tmp_path), "x.pdf")
    assert ok, note
    assert (tmp_path / "x.pdf").read_bytes().startswith(b"%PDF")


def test_gfx_placeholder_eps_text(tmp_path: Path) -> None:
    """.eps payload → 文本 EPS 占位 (原有行为不回退)。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    ok, note = _gfx(_ctx(tmp_path), "x.eps")
    assert ok, note
    assert (tmp_path / "x.eps").read_text(encoding="utf-8").startswith("%!PS")


def test_gfx_decline_non_graphic_ext(tmp_path: Path) -> None:
    """非图形后缀 (.sty/.tex) → decline 不落档。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    ok, note = _gfx(_ctx(tmp_path), "missing.sty")
    assert not ok
    assert "not a known graphic ext" in note
    assert not (tmp_path / "missing.sty").exists()


def test_gfx_decline_traversal(tmp_path: Path) -> None:
    """``..`` 段 payload → 拒。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    ok, _ = _gfx(_ctx(tmp_path), "../evil.png")
    assert not ok


def test_gfx_decline_resolved_already(tmp_path: Path) -> None:
    """解析位已有档 (前轮已补/大小写变体) → False 让路。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    (tmp_path / "x.png").write_bytes(b"real")
    ok, _ = _gfx(_ctx(tmp_path), "x.png")
    assert not ok
    assert (tmp_path / "x.png").read_bytes() == b"real"


def test_gfx_extless_live_ref_drops_eps(tmp_path: Path) -> None:
    """无扩展 payload + 存活 \\includegraphics 引用 → .eps 占位。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\includegraphics{plot}\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _gfx(_ctx(tmp_path), "plot")
    assert ok, note
    assert (tmp_path / "plot.eps").is_file()


def test_gfx_extless_no_ref_declines(tmp_path: Path) -> None:
    """无扩展 payload 且无存活图形引用 → decline (\\input 裸缺件不落图占位)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{plot}\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _ = _gfx(_ctx(tmp_path), "plot")
    assert not ok
    assert not (tmp_path / "plot.eps").exists()


# ════════════════════════════ B: fileset_relocate 位错件归位 ════


def test_rule_reloc_wired() -> None:
    """order:9 族首，missing_file+missing_graphic 双臂，builtin_transform。"""
    rule = _rule(_RULE_RELOC)
    assert rule.order == 9  # noqa: PLR2004 - schema 断言值
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "fileset_relocate"
    ctx = LoopCtx(wdir=Path("/nonexistent"), engine_name="xelatex")
    assert actions._when_ok(rule.when, "missing_file", "x.cls", ctx)  # noqa: SLF001
    assert actions._when_ok(rule.when, "missing_graphic", "x.png", ctx)  # noqa: SLF001
    assert not actions._when_ok(rule.when, "missing_file", None, ctx)  # noqa: SLF001


def test_rule_reloc_dispatch_before_install_family() -> None:
    """调度序：relocate 先于 rungen_stub/docstrip/install_file —— 真件优先。"""
    ids = [r.id for r in load_ruleset().phase("loop")]
    assert ids.index(_RULE_RELOC) < ids.index("rungen_stub")
    assert ids.index(_RULE_RELOC) < ids.index("install_file")


def test_reloc_root_src_to_subdir_main(tmp_path: Path) -> None:
    """2609.17927 形：wdir 根 ifacconf.cls + main@Artigo/ → Artigo/ifacconf.cls。"""
    (tmp_path / "Artigo").mkdir()
    (tmp_path / "Artigo" / "sbaconf.tex").write_text(
        "\\documentclass{ifacconf}\n", encoding="utf-8"
    )
    (tmp_path / "ifacconf.cls").write_bytes(b"% real ifacconf\n")
    ctx = _ctx(tmp_path, main_rel="Artigo/sbaconf.tex")
    ok, note = _reloc(ctx, "ifacconf.cls")
    assert ok, note
    assert (tmp_path / "Artigo" / "ifacconf.cls").read_bytes() == b"% real ifacconf\n"
    assert (tmp_path / "ifacconf.cls").is_file()  # 原件保留 (copy 非 move)


def test_reloc_rglob_basename_fallback(tmp_path: Path) -> None:
    """2609.19170 形：main@sections/ + jmlr2e.sty 在旁枝 → basename 兜底命中。"""
    (tmp_path / "sections").mkdir()
    (tmp_path / "sections" / "00_preamble.tex").write_text(
        "\\documentclass{article}\n", encoding="utf-8"
    )
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "jmlr2e.sty").write_bytes(b"% jmlr2e\n")
    ctx = _ctx(tmp_path, main_rel="sections/00_preamble.tex")
    ok, note = _reloc(ctx, "jmlr2e.sty")
    assert ok, note
    assert (tmp_path / "sections" / "jmlr2e.sty").read_bytes() == b"% jmlr2e\n"


def test_reloc_nested_payload_dir(tmp_path: Path) -> None:
    """2609.19664 形：\\documentclass{templates/arxiv/fairmeta} → 嵌套拷贝位。"""
    deep = tmp_path / "templates" / "arxiv"
    deep.mkdir(parents=True)
    (deep / "main.tex").write_text(
        "\\documentclass{templates/arxiv/fairmeta}\n", encoding="utf-8"
    )
    (deep / "fairmeta.cls").write_bytes(b"% fairmeta\n")
    ctx = _ctx(tmp_path, main_rel="templates/arxiv/main.tex")
    ok, note = _reloc(ctx, "templates/arxiv/fairmeta.cls")
    assert ok, note
    assert (
        deep / "templates" / "arxiv" / "fairmeta.cls"
    ).read_bytes() == b"% fairmeta\n"


def test_reloc_input_file_subdir(tmp_path: Path) -> None:
    """2609.20640 形：\\input{acronyms1} main@IEEEtran/ → IEEEtran/acronyms1.tex。"""
    (tmp_path / "IEEEtran").mkdir()
    (tmp_path / "IEEEtran" / "main.tex").write_text(
        "\\documentclass{article}\n", encoding="utf-8"
    )
    (tmp_path / "acronyms1.tex").write_bytes(b"\\newacronym{x}{X}{x}\n")
    ctx = _ctx(tmp_path, main_rel="IEEEtran/main.tex")
    ok, note = _reloc(ctx, "acronyms1.tex")
    assert ok, note
    assert (tmp_path / "IEEEtran" / "acronyms1.tex").is_file()


def test_reloc_decline_target_exists(tmp_path: Path) -> None:
    """解析位已有档 → False (payload 可达，缺件另有真因不遮蔽)。"""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "main.tex").write_text("x\n", encoding="utf-8")
    (tmp_path / "sub" / "ifacconf.cls").write_bytes(b"at site\n")
    (tmp_path / "ifacconf.cls").write_bytes(b"at root\n")
    ok, note = _reloc(_ctx(tmp_path, main_rel="sub/main.tex"), "ifacconf.cls")
    assert not ok
    assert "already at resolve site" in note
    assert (tmp_path / "sub" / "ifacconf.cls").read_bytes() == b"at site\n"


def test_reloc_decline_transient_ext(tmp_path: Path) -> None:
    """2609.20323 形：main.aux 是 unclosed \\if 下游产物 —— 瞬态件不搬。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    (tmp_path / "main.aux").write_bytes(b"stale\n")
    for pay in ("main.aux", "main.bbl", "main.toc", "main.run.xml"):
        ok, note = _reloc(_ctx(tmp_path), pay)
        assert not ok, pay
        assert "transient artifact" in note


def test_reloc_decline_main_unknown(tmp_path: Path) -> None:
    """main_rel 未定 → 解析位不可定 → False。"""
    (tmp_path / "x.cls").write_bytes(b"c\n")
    ok, note = _reloc(_ctx(tmp_path, main_rel=None), "x.cls")
    assert not ok
    assert "main unknown" in note


def test_reloc_decline_source_absent(tmp_path: Path) -> None:
    """fileset 无真身 → False 让位 install_file。"""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "main.tex").write_text("x\n", encoding="utf-8")
    ok, note = _reloc(_ctx(tmp_path, main_rel="sub/main.tex"), "nope.cls")
    assert not ok
    assert "not present in fileset" in note


def test_reloc_decline_unsafe_name(tmp_path: Path) -> None:
    """``..``/绝对路径 payload → 拒。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    for pay in ("../x.cls", "/abs/x.cls"):
        ok, _ = _reloc(_ctx(tmp_path), pay)
        assert not ok, pay


def test_reloc_dotdir_src_skipped(tmp_path: Path) -> None:
    """隐藏目录内同名件不算真身 (工程件不住 dot-dir)。"""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "main.tex").write_text("x\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "x.cls").write_bytes(b"hidden\n")
    ok, _ = _reloc(_ctx(tmp_path, main_rel="sub/main.tex"), "x.cls")
    assert not ok


# ════════════════════════ C: preamble \\if 界注入 ════


def test_ifclose_preamble_open_injects_before_begdoc(tmp_path: Path) -> None:
    """2609.20323 机理：preamble 内开的 \\if → \\fi 注在 \\begin{document} 行头
    (守卫域限 preamble) —— 不再裹住整 body。"""
    main = (
        "\\documentclass{IEEEtran}\n"
        "\\usepackage{foo}\n"
        "\\ifCLASSINFOpdf\n"
        "\\usepackage{graphicx}\n"
        "\\begin{document}\n"
        "body\n"
        "\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    ok, note = _apply(_rule(_RULE_IFCLOSE), tmp_path)
    assert ok, note
    patched = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "before \\begin{document}" in patched
    assert patched.index("\\fi % texlate-fixloop-injected") < patched.index(
        "\\begin{document}"
    )
    assert patched.index("body") < patched.index("\\end{document}")


def test_ifclose_mixed_pre_post_two_sites(tmp_path: Path) -> None:
    """preamble + body 双亏格 → 两位各注 (pre 注 begdoc 行头，post 注 boundary)。"""
    main = (
        "\\documentclass{article}\n"
        "\\ifodd1\n"
        "preamble-tail\n"
        "\\begin{document}\n"
        "\\ifx\\a\\b\n"
        "body\n"
        "\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    ok, note = _apply(_rule(_RULE_IFCLOSE), tmp_path)
    assert ok, note
    patched = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "closed 1 unclosed preamble \\if* before \\begin{document}" in patched
    assert "closed 1 unclosed \\if* at file end" in patched
    assert patched.index("\\fi % texlate-fixloop-injected") < patched.index(
        "\\begin{document}"
    )
    assert patched.index("body") < patched.index("at file end")
    assert patched.index("at file end") < patched.index("\\end{document}")


def test_ifclose_no_begdoc_falls_back_to_boundary(tmp_path: Path) -> None:
    """无 \\begin{document} 件 (sty/cls/裸 tex) → 全部 boundary 注入。"""
    main = "\\documentclass{article}\n\\ifx\\a\\b\npreamble-only\n"
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    ok, note = _apply(_rule(_RULE_IFCLOSE), tmp_path)
    assert ok, note
    patched = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "at file end" in patched
    assert "before \\begin{document}" not in patched
    assert patched.index("preamble-only") < patched.index("\\fi %")


def test_ifclose_commented_begdoc_boundary(tmp_path: Path) -> None:
    """注释内 \\begin{document} 不算界 (mask_tex 面) → boundary 注入。"""
    main = "\\documentclass{article}\n\\ifx\\a\\b\n% \\begin{document}\nbody\n"
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    ok, note = _apply(_rule(_RULE_IFCLOSE), tmp_path)
    assert ok, note
    patched = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "at file end" in patched
    assert patched.index("body") < patched.index("\\fi %")


def test_ifclose_preamble_body_boundary_untouched(tmp_path: Path) -> None:
    """body 内开的 \\if 仍注 boundary (行为不回退 —— ifclose 既有面)。"""
    main = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "hello\n"
        "\\iffalse\n"
        "hidden\n"
        "\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    ok, note = _apply(_rule(_RULE_IFCLOSE), tmp_path)
    assert ok, note
    patched = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "at file end" in patched
    assert patched.index("hidden") < patched.index("\\fi %")
    assert patched.index("\\fi %") < patched.index("\\end{document}")


def test_ifclose_eof_arm_preamble_same_logic(tmp_path: Path) -> None:
    """early_eof 臂 (196.5) 共用同款两段注入。"""
    main = (
        "\\documentclass{article}\n"
        "\\ifx\\a\\b\n"
        "\\begin{document}\n"
        "body\n"
        "\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    ok, note = _apply(_rule("unclosed_if_close_eof"), tmp_path)
    assert ok, note
    patched = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert patched.index("\\fi % texlate-fixloop-injected") < patched.index(
        "\\begin{document}"
    )
