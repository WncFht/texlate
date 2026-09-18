"""L1 verify-flip 钉测：15 条「规则/修复已落地」机制的活性核验。

车道 L1（tmp/lane-c1-scout/family-plan.md §L1）：verdict=rule/covered
机制逐一最小复现 —— 活则钉死，防回退。语料无关（corpus_v3 数据
gitignored），全部 tmp_path 合成源，干净 clone 全绿。

机制 → 落点对照：

- W37/W68 → ``30-route.yaml:plain_format_route`` + ``plain_format_detect``
- W58 → ``30-route.yaml:build_directive_harvest`` + ``harvest_build_directives``
- W79 → ``40-install.yaml:rungen_stub`` + ``generated_stub``(openout)
- W18 → ``40-install.yaml:nonctan_input_stub`` + ``generated_stub``(overlay)
- W102 → ``40-install.yaml:docstrip_generate`` + ``docstrip_generate``
- W66 → ``45-graphics.yaml:includepdf_missing_stub`` + ``includepdf_missing_stub``
- W31 → ``30-route.yaml:svg_route`` + ``45-graphics.yaml:svg_prepare`` + ``svg_prepare``
- W49 → ``75-syntax.yaml`` already_def 三链（mechanisms 标签面）
- W67 → ``textutil/decls.py`` BEGIN/END_DOC_RX ``\\s*``
- W110 → ``latex/flatten.py`` ``_seen`` 祖先栈断环
- T14 → ``latex/flatten.py`` 裸 ``\\input file`` 形态
- W05 → ``arxiv/_texutil.py`` TEX_EXT 含 .ltx/.latex
- W01 → mask 先剥注释再读参（caption 参数内注释不进 chunk）
- W02 → ``arxiv/locate.py`` multi_doc 多根裁决
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from texlate.arxiv._texutil import TEX_EXT
from texlate.arxiv.locate import locate
from texlate.compile.fixloop import load_ruleset
from texlate.compile.fixloop._builtins_misc import (
    docstrip_generate,
    harvest_build_directives,
    plain_format_detect,
)
from texlate.compile.fixloop._builtins_shim import generated_stub
from texlate.compile.fixloop.builtins import includepdf_missing_stub, svg_prepare
from texlate.compile.fixloop.engine import LoopCtx, Rule, _cond_ok
from texlate.latex.api import parse_tex, parse_tex_v1
from texlate.latex.flatten import flatten_inputs
from texlate.textutil import BEGIN_DOC_RX, END_DOC_RX


class _Eng:
    """cond 评估的最小引擎替身（与 test_fixloop_rules 同款）。"""

    name = "xelatex"
    caps = frozenset({"kpsewhich", "tlmgr", "updmap"})

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _ctx(tmp_path: Path, files: dict[str, str], engine: str = "xelatex") -> LoopCtx:
    """wdir 落文件树 + LoopCtx（main_rel 取首个文件）。"""
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return LoopCtx(wdir=tmp_path, engine_name=engine, main_rel=next(iter(files)))


def _rule(rid: str) -> Rule:
    """ruleset 里按 id 取规则。"""
    rule = next(r for r in load_ruleset().rules if r.id == rid)
    assert isinstance(rule, Rule)
    return rule


def _mech_set(rid: str) -> set[str]:
    return set(_rule(rid).mechanisms)


# ═══════════════════════════════════════════════════════════════
# W37/W68 — plain_format_route gate + plain_format_detect builtin
# ═══════════════════════════════════════════════════════════════


def test_w37_plain_sigs_reject(tmp_path: Path) -> None:
    """纯 plain TeX（\\font cm 签名 + \\bye 收尾）→ REJECT route=tex-plain。"""
    ctx = _ctx(
        tmp_path,
        {"main.tex": "\\font\\tenrm=cmr10\n\\magnification=1200\nHello\n\\bye\n"},
    )
    applied, note = plain_format_detect(ctx, _Eng(), None, {})
    assert applied
    assert "tex-plain" in note


def test_w37_latex_docclass_not_rejected(tmp_path: Path) -> None:
    """活 \\documentclass 在场 → 不拒（负例防误伤）。"""
    ctx = _ctx(
        tmp_path,
        {"m.tex": "\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n"},
    )
    applied, note = plain_format_detect(ctx, _Eng(), None, {})
    assert not applied
    assert "documentclass" in note


def test_w68_pure_amstex_bye_rejected(tmp_path: Path) -> None:
    """amsTeX 系 \\input amstex + 裸 \\bye → 同签名面拒收。"""
    ctx = _ctx(tmp_path, {"m.tex": "\\input amstex\n\\topmatter\n\\bye\n"})
    applied, note = plain_format_detect(ctx, _Eng(), None, {})
    assert applied
    assert "tex-plain" in note


def test_w68_documentstyle_arm_not_rejected(tmp_path: Path) -> None:
    """\\documentstyle{amsppt} 在场 → plain_format_detect 不拒（latex209 臂接管）。"""
    ctx = _ctx(
        tmp_path,
        {"m.tex": "\\input amstex\n\\documentstyle{amsppt}\n\\topmatter\n\\end\n"},
    )
    applied, _ = plain_format_detect(ctx, _Eng(), None, {})
    assert not applied


def test_w37_w68_route_rule_mechanisms() -> None:
    """gate 层 plain_format_route 规则带 W37/W68 mechanisms 标签。"""
    rule = _rule("plain_format_route")
    assert rule.phase == "gate"
    assert {"W37", "W68"} <= _mech_set("plain_format_route")


# ═══════════════════════════════════════════════════════════════
# W58 — build_directive_harvest precheck + harvest builtin
# ═══════════════════════════════════════════════════════════════


def test_w58_arara_shell_on(tmp_path: Path) -> None:
    """``% arara: pdflatex: { shell: on }`` → engine_flags + advisory。"""
    ctx = _ctx(
        tmp_path,
        {"m.tex": "% arara: pdflatex: { shell: on }\n\\documentclass{a}\n"},
    )
    applied, _ = harvest_build_directives(ctx, _Eng(), None, {})
    assert applied
    assert "-shell-escape" in ctx.engine_flags
    assert any("arara" in a for a in ctx.advisories)


def test_w58_tex_program_advisory(tmp_path: Path) -> None:
    """``% !TEX program = xelatex`` → advisory 账本（不改源不请 flag）。"""
    ctx = _ctx(tmp_path, {"m.tex": "% !TEX program = xelatex\n\\documentclass{a}\n"})
    applied, _ = harvest_build_directives(ctx, _Eng(), None, {})
    assert applied
    assert any("xelatex" in a for a in ctx.advisories)
    assert "-shell-escape" not in ctx.engine_flags


def test_w58_no_directive_noop(tmp_path: Path) -> None:
    """无构建指令 → False 不占轮。"""
    ctx = _ctx(tmp_path, {"m.tex": "\\documentclass{article}\n"})
    applied, _ = harvest_build_directives(ctx, _Eng(), None, {})
    assert not applied


def test_w58_rule_mechanisms() -> None:
    rule = _rule("build_directive_harvest")
    assert rule.phase == "precheck"
    assert "W58" in _mech_set("build_directive_harvest")


# ═══════════════════════════════════════════════════════════════
# W79 — rungen_stub + generated_stub(openout)
# ═══════════════════════════════════════════════════════════════


def test_w79_openout_target_stubbed(tmp_path: Path) -> None:
    r"""``\immediate\openout\ftfile=foots.tmp`` 目标缺档 → wdir 空 stub。"""
    ctx = _ctx(
        tmp_path,
        {"main.tex": "\\immediate\\openout\\ftfile=foots.tmp\n\\input foots.tmp\n"},
    )
    applied, note = generated_stub(ctx, _Eng(), "foots.tmp", {"faces": ["openout"]})
    assert applied
    assert "openout" in note
    assert (tmp_path / "foots.tmp").is_file()


def test_w79_non_openout_miss(tmp_path: Path) -> None:
    """payload 不在 \\openout 目标集 → False 让位 install_file。"""
    ctx = _ctx(
        tmp_path,
        {"main.tex": "\\immediate\\openout\\ftfile=foots.tmp\n"},
    )
    applied, _ = generated_stub(ctx, _Eng(), "ordinary.sty", {"faces": ["openout"]})
    assert not applied


def test_w79_rule_mechanisms() -> None:
    rule = _rule("rungen_stub")
    assert rule.phase == "loop"
    assert "W79" in _mech_set("rungen_stub")


# ═══════════════════════════════════════════════════════════════
# W18 — nonctan_input_stub + generated_stub(overlay)
# ═══════════════════════════════════════════════════════════════


def test_w18_pstex_t_stubbed(tmp_path: Path) -> None:
    """.pstex_t 覆盖层缺档 → wdir 空 stub（惠及宏体间接 \\input 全部调用点）。"""
    ctx = _ctx(tmp_path, {"s.tex": "\\newcommand{\\x}{\\input #2.pstex_t}\n"})
    applied, note = generated_stub(ctx, _Eng(), "fig1.pstex_t", {"faces": ["overlay"]})
    assert applied
    assert "overlay" in note
    assert (tmp_path / "fig1.pstex_t").is_file()


def test_w18_non_overlay_miss(tmp_path: Path) -> None:
    """普通 .sty payload → False。"""
    ctx = _ctx(tmp_path, {"s.tex": "x\n"})
    applied, _ = generated_stub(ctx, _Eng(), "normal.sty", {"faces": ["overlay"]})
    assert not applied


def test_w18_rule_mechanisms() -> None:
    assert "W18" in _mech_set("nonctan_input_stub")


# ═══════════════════════════════════════════════════════════════
# W102 — docstrip_generate（hermetic：patch which + 注入 runner）
# ═══════════════════════════════════════════════════════════════


def test_w102_docstrip_generates_cls(tmp_path: Path) -> None:
    """包内 aipproc.ins → runner 模拟 docstrip 产出 aipproc.cls → applied。"""

    def fake_runner(
        argv: list[str], timeout: int, wdir: Path
    ) -> tuple[int, str, float, bool]:
        del timeout
        assert "aipproc.ins" in argv[-1]
        (wdir / "aipproc.cls").write_text("\\ProvidesClass{aipproc}\n")
        return 0, "generated", 0.1, False

    ctx = _ctx(
        tmp_path,
        {"aipproc.ins": "% fake ins\n", "aipproc.dtx": "% fake dtx\n"},
    )
    ctx.runner = fake_runner
    misc = "texlate.compile.fixloop._builtins_misc.shutil.which"
    with patch(misc, return_value="/usr/bin/latex"):
        applied, note = docstrip_generate(ctx, _Eng(), "aipproc.cls", {})
    assert applied
    assert "aipproc.cls" in note


def test_w102_no_matching_ins(tmp_path: Path) -> None:
    """多个 .ins 且 stem 全不对应 → False 落 install_file 兜底。"""
    ctx = _ctx(
        tmp_path,
        {"a.ins": "x", "b.ins": "x"},
    )
    applied, _ = docstrip_generate(ctx, _Eng(), "other.cls", {})
    assert not applied


def test_w102_rule_mechanisms() -> None:
    assert {"W102", "B05"} <= _mech_set("docstrip_generate")


def test_w102_real_latex_driver(tmp_path: Path) -> None:
    """真 latex 驱动端到端（可选臂：无 latex 可跳过）。"""
    if not shutil.which("latex"):
        pytest.skip("latex driver not on PATH")
    (tmp_path / "mini.ins").write_text(
        "\\input docstrip\n\\generate{\\file{mini.cls}{\\from{mini.dtx}{cls}}}\n\\endbatchfile\n"
    )
    (tmp_path / "mini.dtx").write_text(
        "%    \\begin{macrocode}\n%<*cls>\n\\ProvidesClass{mini}\n%</cls>\n%    \\end{macrocode}\n"
    )
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    applied, _ = docstrip_generate(ctx, _Eng(), "mini.cls", {"timeout": 90})
    assert applied
    assert (tmp_path / "mini.cls").is_file()


# ═══════════════════════════════════════════════════════════════
# W66 — includepdf_missing_stub
# ═══════════════════════════════════════════════════════════════


def test_w66_missing_includepdf_stubbed(tmp_path: Path) -> None:
    """\\includepdf{supp.pdf} 缺件 → 整调用改写 \\clearpage\\null。"""
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{pdfpages}\n"
                "\\begin{document}\nBody.\n\\includepdf{supp.pdf}\n\\end{document}\n"
            )
        },
    )
    applied, _ = includepdf_missing_stub(ctx, _Eng(), "supp.pdf", {})
    assert applied
    assert "\\clearpage\\null" in (tmp_path / "main.tex").read_text()


def test_w66_present_pdf_untouched(tmp_path: Path) -> None:
    """payload 在盘 → 引用本可解析，不改写。"""
    (tmp_path / "supp.pdf").write_bytes(b"%PDF-1.4 x")
    ctx = _ctx(
        tmp_path,
        {"m.tex": "\\begin{document}\n\\includepdf{supp.pdf}\n\\end{document}\n"},
    )
    applied, _ = includepdf_missing_stub(ctx, _Eng(), "supp.pdf", {})
    assert not applied


def test_w66_rule_mechanisms() -> None:
    assert "W66" in _mech_set("includepdf_missing_stub")


# ═══════════════════════════════════════════════════════════════
# W31 — svg_route precheck cond + svg_prepare 两臂
# ═══════════════════════════════════════════════════════════════


def test_w31_svg_route_cond_matches(tmp_path: Path) -> None:
    """tectonic 臂 + \\usepackage{svg} → svg_route 条件命中（行锚注释安全）。"""
    ctx = _ctx(
        tmp_path,
        {"main.tex": "\\documentclass{a}\n\\usepackage{svg}\n\\begin{document}\n"},
        engine="tectonic",
    )
    rule = _rule("svg_route")
    ok, _ = _cond_ok(rule.condition, rule, ctx, _Eng(), None)
    assert ok


def test_w31_svg_route_cond_xelatex_arm_skipped(tmp_path: Path) -> None:
    """xelatex 引擎不触 svg_route 条件（engine_in tectonic；xelatex 臂走 svg_prepare）。"""
    ctx = _ctx(tmp_path, {"m.tex": "\\usepackage{svg}\n"})
    rule = _rule("svg_route")
    ok, _ = _cond_ok(rule.condition, rule, ctx, _Eng(), None)
    assert not ok


def test_w31_svg_route_cond_comment_immune(tmp_path: Path) -> None:
    """注释掉的 \\usepackage{svg} 不触条件（行锚 ^ 起）。"""
    ctx = _ctx(
        tmp_path,
        {"m.tex": "% \\usepackage{svg}\n\\documentclass{a}\n"},
        engine="tectonic",
    )
    rule = _rule("svg_route")
    ok, _ = _cond_ok(rule.condition, rule, ctx, _Eng(), None)
    assert not ok


def test_w31_svg_prepare_flag_arm(tmp_path: Path) -> None:
    """inkscape 在 PATH → engine_flags 请 -shell-escape。"""
    ctx = _ctx(
        tmp_path,
        {"m.tex": "\\usepackage{svg}\n\\begin{document}\n\\includesvg{d}\n"},
    )
    bi = "texlate.compile.fixloop._builtins_graphics.shutil.which"
    with patch(bi, side_effect=lambda n: "/fake/inkscape" if n == "inkscape" else None):
        applied, _ = svg_prepare(ctx, _Eng(), None, {})
    assert applied
    assert "-shell-escape" in ctx.engine_flags


def test_w31_svg_prepare_convert_arm(tmp_path: Path) -> None:
    """inkscape 缺席 → svg→pdf 预转换 + \\includesvg 改写 \\includegraphics。"""

    def fake_runner(
        argv: list[str], timeout: int, wdir: Path
    ) -> tuple[int, str, float, bool]:
        del timeout, wdir
        # rsvg-convert argv: [tool, -f, pdf, -o, dst, src]
        dst = Path(argv[4])
        dst.write_bytes(b"%PDF-1.4 fake")
        return 0, "", 0.1, False

    svg = '<svg xmlns="http://www.w3.org/2000/svg"/>'
    ctx = _ctx(
        tmp_path,
        {
            "m.tex": "\\usepackage{svg}\n\\begin{document}\n\\includesvg{diagram}\n",
            "diagram.svg": svg,
        },
    )
    ctx.runner = fake_runner
    bi = "texlate.compile.fixloop._builtins_graphics.shutil.which"

    def fake_which(name: str) -> str | None:
        return "/fake/rsvg-convert" if name == "rsvg-convert" else None

    with patch(bi, side_effect=fake_which):
        applied, note = svg_prepare(ctx, _Eng(), None, {})
    assert applied
    assert "svg->pdf" in note
    assert "\\includegraphics" in (tmp_path / "m.tex").read_text()


def test_w31_no_svg_noop(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"m.tex": "\\documentclass{a}\n\\begin{document}\n"})
    applied, _ = svg_prepare(ctx, _Eng(), None, {})
    assert not applied


def test_w31_rules_mechanisms() -> None:
    assert {"W31", "B05"} <= _mech_set("svg_route")
    assert {"W31", "B05"} <= _mech_set("svg_prepare")


# ═══════════════════════════════════════════════════════════════
# W49 — already_def 三链 mechanisms 标签面（行为面 test_fixloop_orphan_rules 已钉）
# ═══════════════════════════════════════════════════════════════


def test_w49_covering_rules_tagged() -> None:
    """mechmap 裁定的 already_def 三链规则均带 W49 mechanisms 标签。"""
    covering = {
        "already_def_newcmd_renew",
        "ntheorem_style_undefine",
        "already_def_undefine",
    }
    tagged = {rid for rid in covering if "W49" in _mech_set(rid)}
    assert covering <= tagged


# ═══════════════════════════════════════════════════════════════
# W67 — BEGIN/END_DOC_RX \s* 空格容忍
# ═══════════════════════════════════════════════════════════════


def test_w67_spaced_doc_markers_parse() -> None:
    """``\\end {document}`` 空格形截断：正文进 chunk、尾随正文切除。"""
    src = (
        "\\documentclass{article}\n\\begin {document}\n"
        "Body paragraph one is long enough to be a real chunk of prose.\n"
        "\\end {document}\n"
        "TRAILING_SECRET_AFTER_END must be cut and this is long too.\n"
    )
    for fn in (parse_tex_v1, parse_tex):
        texts = " ".join(c.content for c in fn(src).chunks)
        assert "Body paragraph" in texts
        assert "TRAILING_SECRET_AFTER_END" not in texts


def test_w67_regex_tolerates_space() -> None:
    assert BEGIN_DOC_RX.search("\\begin {document}")
    assert END_DOC_RX.search("\\end {document}")
    assert BEGIN_DOC_RX.search("\\begin{document}")
    assert END_DOC_RX.search("\\end{document}")


# ═══════════════════════════════════════════════════════════════
# W110 — flatten _seen 祖先栈断环
# ═══════════════════════════════════════════════════════════════


def test_w110_mutual_input_loop_breaks(tmp_path: Path) -> None:
    """a<->b 互环：返回不挂起，双方内容各内联一次。"""
    (tmp_path / "a.tex").write_text("\\input{b.tex}\nAAA body\n")
    (tmp_path / "b.tex").write_text("\\input{a.tex}\nBBB body\n")
    out = flatten_inputs((tmp_path / "a.tex").read_text(), str(tmp_path))
    assert "AAA body" in out
    assert "BBB body" in out


def test_w110_self_input_loop_breaks(tmp_path: Path) -> None:
    """\\input{self} 自环：断环返回。"""
    (tmp_path / "self.tex").write_text("\\input{self.tex}\nSELF body\n")
    out = flatten_inputs((tmp_path / "self.tex").read_text(), str(tmp_path))
    assert "SELF body" in out


def test_w110_sibling_reinclude_allowed(tmp_path: Path) -> None:
    """兄弟位合法重包含照常内联（_seen 是祖先栈非 once-set）。"""
    (tmp_path / "shared.tex").write_text("SHARED\n")
    (tmp_path / "main.tex").write_text(
        "\\input{shared.tex}\nmid\n\\input{shared.tex}\n"
    )
    out = flatten_inputs((tmp_path / "main.tex").read_text(), str(tmp_path))
    assert out == "SHARED\n\nmid\nSHARED\n\n"


# ═══════════════════════════════════════════════════════════════
# T14 — 裸 \input file 形态
# ═══════════════════════════════════════════════════════════════


def test_t14_bare_input_expands(tmp_path: Path) -> None:
    """``\\input subfile``（无花括号）展开内联。"""
    (tmp_path / "main.tex").write_text("Before\n\\input subfile\nAfter\n")
    (tmp_path / "subfile.tex").write_text("SUBFILE_CONTENT\n")
    out = flatten_inputs((tmp_path / "main.tex").read_text(), str(tmp_path))
    assert "SUBFILE_CONTENT" in out


def test_t14_commented_input_not_expanded(tmp_path: Path) -> None:
    """注释掉的 \\input 不展开（目标文件在场也不读）。"""
    (tmp_path / "main.tex").write_text("% \\input ghost\nBody\n")
    (tmp_path / "ghost.tex").write_text("GHOST_CONTENT\n")
    out = flatten_inputs((tmp_path / "main.tex").read_text(), str(tmp_path))
    assert "GHOST_CONTENT" not in out
    assert "% \\input ghost" in out


# ═══════════════════════════════════════════════════════════════
# W05 — TEX_EXT 含 .ltx/.latex + locate 认非 .tex 主文件
# ═══════════════════════════════════════════════════════════════


def test_w05_tex_ext_covers_ltx_latex() -> None:
    assert ".ltx" in TEX_EXT
    assert ".latex" in TEX_EXT


def test_w05_locate_accepts_latex_ext(tmp_path: Path) -> None:
    """唯一主文件 article.latex → locate 判 latex 主档。"""
    (tmp_path / "article.latex").write_text(
        "\\documentclass{article}\n\\begin{document}\nBody\n\\end{document}\n"
    )
    res = locate(tmp_path)
    assert res.main == "article.latex"


# ═══════════════════════════════════════════════════════════════
# W01 — caption 参数内注释：剥注释先于参数读取
# ═══════════════════════════════════════════════════════════════


def test_w01_caption_arg_comment_masked() -> None:
    """``\\caption{甲 % 注释\\n乙}`` → chunk 得 甲乙，注释成占位符不泄漏字面。"""
    src = (
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{figure}\n\\caption{First part % trailing comment\n"
        "second part}\n\\end{figure}\n\\end{document}\n"
    )
    for fn in (parse_tex_v1, parse_tex):
        texts = " ".join(c.content for c in fn(src).chunks)
        assert "second part" in texts
        assert "trailing comment" not in texts


# ═══════════════════════════════════════════════════════════════
# W02 — multi_doc 多主文件裁决
# ═══════════════════════════════════════════════════════════════


def test_w02_multi_doc_flag(tmp_path: Path) -> None:
    """两独立根 → multi_doc 置位 + main 取自候选。"""
    for name in ("a.tex", "b.tex"):
        (tmp_path / name).write_text(
            "\\documentclass{article}\n\\begin{document}\nBody\n\\end{document}\n"
        )
    res = locate(tmp_path)
    assert res.multi_doc
    assert res.main in {"a.tex", "b.tex"}


def test_w02_single_root_not_multi(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nBody\n\\end{document}\n"
    )
    (tmp_path / "sec.tex").write_text("Section body\n")
    res = locate(tmp_path)
    assert not res.multi_doc
    assert res.main == "main.tex"
