"""fixer-bblwall 2026-09-17 wave 审计测试.

- W2 bbl_regen stale-drop: biber rc≠0 后 (a) bbl 被自删 → invalidate 计
  progress; (b) 头标 ``bbl format version X.Y`` <3.0 → unlink+invalidate
  计 progress (1706.00240 wall-2, fixer-apjbbx spec)。
- W3 physics_stub_detach: bundled 2012 physics.sty stub 撞 siunitx v3
  ``\\@ifpackageloaded{physics}`` 硬报错 → 剥 usepackage 项 + ``\\input``
  续载 + ``\\ProvidesPackage`` 中和 + 双载守卫 (1706.00240 wall-3)。
- A3 glyphtounicode_shadow: cls ``\\IfFileExists`` 守卫 input 真
  glyphtounicode.tex (pdfTeX 原语件) → wdir 空 stub, order 46 先于
  pdftex_prim guard(50)/polyfill(51) 截 payload (2105.03753)。
- A5 undefine_for_redef: already_def_undefine 升级 builtin —— 寄存器/盒型
  分配名 (``\\newbox\\splitbox`` 族) abstain, ``\\newcommand``/``\\def``
  维持 ``\\let\\X\\@undefined`` (2211.04482 aastex62 实证)。
- A6 TEXT_8BIT_FALLBACK: inject_cjk 块追加 CMU Serif ``\\XeTeXinterchartoks``
  全谱回退 (ec-lmr/aer10 8-bit TFM 域西里尔/希腊/拉丁扩展漏字)。
"""

from pathlib import Path

from test_fixloop_loop import CLEAN_LOG, MockEngine, mini_rs

from texlate.compile.fixloop import fixloop
from texlate.compile.fixloop.builtins import (
    TRANSFORM_FNS,
    _allocated_cs_names,
    _detach_physics_loads,
    bbl_regen,
    bundled_class_shadow,
    physics_stub_detach,
    undefine_for_redef,
)
from texlate.compile.fixloop.engine import LoopCtx, Ruleset, RunFn, _cond_ok
from texlate.compile.inject import TEXT_8BIT_FALLBACK, inject_cjk


def _ctx(tmp_path: Path, runner: RunFn | None = None) -> LoopCtx:
    return LoopCtx(
        wdir=tmp_path, engine_name="xelatex", main_rel="main.tex", runner=runner
    )


def _write_main(tmp_path: Path, head: str, body: str = "hi") -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        + head
        + "\n\\begin{document}\n"
        + body
        + "\n\\end{document}\n",
        encoding="utf-8",
    )


_STUB = (
    "\\ProvidesPackage{physics}[2012/12/31 mini physics stub]\n"
    "\\def\\abs#1{|#1|}\n\\def\\norm#1{\\|#1\\|}\n\\def\\bra{\\langle}\n"
)


# ---------------------------------------------------------------- W2 stale-drop
def test_bbl_regen_stale_format_dropped(tmp_path: Path) -> None:
    """rc=2 + 头标 ``bbl format version 2.8`` → unlink + True + stale-dropped。"""
    (tmp_path / "ms.bcf").write_text("<bcf/>", encoding="utf-8")
    bbl = tmp_path / "ms.bbl"
    bbl.write_text(
        "% $ biblatex control file $ bbl format version 2.8 $\\n\\entry{a}\n",
        encoding="utf-8",
    )

    def _fail(_a: list[str], _t: int, _w: Path) -> tuple:
        return 2, "ERROR - Data file is malformed", 0.4, False

    ok, note = bbl_regen(_ctx(tmp_path, runner=_fail), None, "\\sortlist", {})
    assert ok, note
    assert not bbl.exists()
    assert "stale-dropped" in note
    assert "fmt 2.8" in note


def test_bbl_regen_biber_selfdelete_counts(tmp_path: Path) -> None:
    """rc=2 且 biber 自删 poison bbl → 清场计 progress → True。"""
    (tmp_path / "ms.bcf").write_text("<bcf/>", encoding="utf-8")
    (tmp_path / "ms.bbl").write_text("stale", encoding="utf-8")

    def _selfrm(argv: list[str], _t: int, w: Path) -> tuple:
        (w / f"{argv[1]}.bbl").unlink(missing_ok=True)
        return 2, "ERROR - malformed; Deleted ms.bbl", 0.4, False

    ok, note = bbl_regen(_ctx(tmp_path, runner=_selfrm), None, None, {})
    assert ok, note
    assert "biber-rm" in note


def test_bbl_regen_fresh_format_survives(tmp_path: Path) -> None:
    """头标 3.2 (现行) 的 bbl 不是 poison → rc=1 时保留 + False。"""
    (tmp_path / "ms.bcf").write_text("<bcf/>", encoding="utf-8")
    bbl = tmp_path / "ms.bbl"
    bbl.write_text(
        "% $ biblatex control file $ bbl format version 3.2 $\n", encoding="utf-8"
    )

    def _fail(_a: list[str], _t: int, _w: Path) -> tuple:
        return 1, "boom", 0.2, False

    ok, note = bbl_regen(_ctx(tmp_path, runner=_fail), None, None, {})
    assert not ok
    assert bbl.is_file()
    assert "rc=1" in note


def test_bbl_regen_no_marker_survives(tmp_path: Path) -> None:
    """无版本头标的 bbl (手写/旧形) → 不删, False。"""
    (tmp_path / "ms.bcf").write_text("<bcf/>", encoding="utf-8")
    bbl = tmp_path / "ms.bbl"
    bbl.write_text("\\begin{thebibliography}{9}\n", encoding="utf-8")

    def _fail(_a: list[str], _t: int, _w: Path) -> tuple:
        return 2, "boom", 0.2, False

    ok, _note = bbl_regen(_ctx(tmp_path, runner=_fail), None, None, {})
    assert not ok
    assert bbl.is_file()


def test_bbl_regen_never_existed_fails(tmp_path: Path) -> None:
    """bbl 从不存在 (had_bbl=False) → 自删分支不触发, False。"""
    (tmp_path / "ms.bcf").write_text("<bcf/>", encoding="utf-8")

    def _fail(_a: list[str], _t: int, _w: Path) -> tuple:
        return 2, "boom", 0.2, False

    ok, note = bbl_regen(_ctx(tmp_path, runner=_fail), None, None, {})
    assert not ok
    assert "rc=2" in note


def test_bbl_regen_mixed_regen_and_drop(tmp_path: Path) -> None:
    """a.bcf 重生成功 + b.bcf 陈旧 drop → True, note 双段齐。"""
    (tmp_path / "a.bcf").write_text("<bcf/>", encoding="utf-8")
    (tmp_path / "b.bcf").write_text("<bcf/>", encoding="utf-8")
    (tmp_path / "b.bbl").write_text("bbl format version 2.7\n", encoding="utf-8")

    def _mixed(argv: list[str], _t: int, w: Path) -> tuple:
        if argv[1] == "a":
            (w / "a.bbl").write_text("% regen", encoding="utf-8")
            return 0, "", 0.1, False
        return 2, "boom", 0.1, False

    ok, note = bbl_regen(_ctx(tmp_path, runner=_mixed), None, None, {})
    assert ok, note
    assert "regen: a.bcf" in note
    assert "stale-dropped" in note
    assert not (tmp_path / "b.bbl").exists()
    assert (tmp_path / "a.bbl").is_file()


# ------------------------------------------------------------ W3 physics detach
def test_physics_detach_list_member(tmp_path: Path) -> None:
    """``\\usepackage{amsmath,physics,siunitx}`` → 名单摘 physics + ``\\input`` 续载。"""
    _write_main(tmp_path, "\\usepackage{amsmath,physics,siunitx}", "$\\abs{x}$")
    (tmp_path / "physics.sty").write_text(_STUB, encoding="utf-8")
    ok, note = physics_stub_detach(_ctx(tmp_path), None, "begin", {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\usepackage{amsmath,siunitx}" in t
    assert "\\input{physics.sty}" in t
    st = (tmp_path / "physics.sty").read_text(encoding="utf-8")
    assert "\\ProvidesPackage{physics-stub}" in st
    assert "txlatephysstub" in st


def test_physics_detach_solo_load(tmp_path: Path) -> None:
    """独载 ``\\usepackage{physics}`` → 整命令换成 ``\\input`` 行。"""
    _write_main(tmp_path, "\\usepackage{physics}")
    (tmp_path / "physics.sty").write_text(_STUB, encoding="utf-8")
    ok, _note = physics_stub_detach(_ctx(tmp_path), None, None, {})
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\usepackage{physics}" not in t
    assert "\\input{physics.sty}" in t


def test_physics_detach_real_pkg_abstains(tmp_path: Path) -> None:
    """stub 内含 ``\\DeclareDocumentCommand`` (真 CTAN xparse 形) → 弃权。"""
    _write_main(tmp_path, "\\usepackage{physics}")
    (tmp_path / "physics.sty").write_text(
        "\\ProvidesPackage{physics}\n\\DeclareDocumentCommand\\abs{m}{#1}\n",
        encoding="utf-8",
    )
    ok, note = physics_stub_detach(_ctx(tmp_path), None, None, {})
    assert not ok
    assert "xparse" in note
    assert "\\usepackage{physics}" in (tmp_path / "main.tex").read_text(
        encoding="utf-8"
    )


def test_physics_detach_no_stub_abstains(tmp_path: Path) -> None:
    """wdir 无 physics.sty → 弃权 (系统 physics 由 siunitx 自行处理)。"""
    _write_main(tmp_path, "\\usepackage{physics}")
    ok, note = physics_stub_detach(_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no bundled" in note


def test_physics_detach_existing_input_no_dup(tmp_path: Path) -> None:
    """源已有 ``\\input{physics.sty}`` → 剥 usepackage 但不重复补 ``\\input``。"""
    _write_main(tmp_path, "\\input{physics.sty}\n\\usepackage{amsmath,physics}")
    (tmp_path / "physics.sty").write_text(_STUB, encoding="utf-8")
    ok, _note = physics_stub_detach(_ctx(tmp_path), None, None, {})
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert t.count("\\input{physics.sty}") == 1
    assert "\\usepackage{amsmath}" in t


def test_physics_detach_commented_usepackage_untouched(tmp_path: Path) -> None:
    """``% \\usepackage{physics}`` 注释假装载点 → 不动 (mask 遮盖位过滤)。"""
    line = "% \\usepackage{physics}  % kept commented"
    _write_main(tmp_path, "\\usepackage{siunitx}\n" + line)
    (tmp_path / "physics.sty").write_text(_STUB, encoding="utf-8")
    physics_stub_detach(_ctx(tmp_path), None, None, {})
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert line in t  # 注释原样保留, \\input 未冲进注释域
    assert "\\input{physics.sty}" not in t


def test_physics_detach_idempotent(tmp_path: Path) -> None:
    """二轮重入 → False (无装载点 + stub 已中和 + 守卫在场)。"""
    _write_main(tmp_path, "\\usepackage{physics}")
    (tmp_path / "physics.sty").write_text(_STUB, encoding="utf-8")
    ctx = _ctx(tmp_path)
    ok, _ = physics_stub_detach(ctx, None, None, {})
    assert ok
    ok2, _ = physics_stub_detach(ctx, None, None, {})
    assert not ok2


def test_physics_detach_rule_e2e(tmp_path: Path) -> None:
    """端到端: siunitx 硬错签名 → 规则点火 → 下一轮 clean。"""
    _write_main(tmp_path, "\\usepackage{amsmath,physics,siunitx}", "$\\abs{x}$")
    (tmp_path / "physics.sty").write_text(_STUB, encoding="utf-8")
    rs = mini_rs(
        rules=[
            {
                "id": "physics_stub_detach",
                "phase": "loop",
                "order": 163,
                "when": {"any": [{"category": "undefined_cs"}, {"category": "other"}]},
                "condition": {
                    "cache_dir_glob": "physics.sty",
                    "source_contains": (
                        "\\\\(?:usepackage|RequirePackage)\\s*"
                        "(\\[[^\\]]*\\])?\\s*\\{[^}]*\\bphysics\\b"
                    ),
                },
                "action": {
                    "kind": "builtin_transform",
                    "function": "physics_stub_detach",
                },
            }
        ],
        taxonomy=[
            {
                "id": "undefined_cs",
                "scope": "head",
                "payload_group": 1,
                "pattern": (
                    "Undefined control sequence"
                    "(?:[\\s\\S]*?l\\.\\d+[^\\n]*\\\\([a-zA-Z@]+))?"
                ),
            }
        ],
    )
    err = "! Undefined control sequence.\nl.209 \\begin{document}\n"
    eng = MockEngine([{"log": err}, {"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(tmp_path, eng, ruleset=rs)
    assert cell["verdict"] == "clean", cell
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\input{physics.sty}" in t


def test_detach_loads_helper_unit() -> None:
    """``_detach_physics_loads`` 单测: 列表/独载/伪名过滤。"""
    nt, n = _detach_physics_loads(
        "\\usepackage{physics-tools,physics}\n", add_input=True
    )
    assert n == 1
    assert "\\usepackage{physics-tools}" in nt
    assert "\\input{physics.sty}" in nt
    nt2, n2 = _detach_physics_loads("\\usepackage{physics-tools}\n", add_input=True)
    assert n2 == 0
    assert nt2 == "\\usepackage{physics-tools}\n"


# ---------------------------------------------------------- A5 undefine_for_redef
def test_undefine_newbox_abstains(tmp_path: Path) -> None:
    """``\\newbox\\splitbox`` 分配名 → abstain (2211.04482 aastex62 实证)。"""
    (tmp_path / "aastex62.cls").write_text("\\newbox\\splitbox\n", encoding="utf-8")
    _write_main(tmp_path, "")
    ok, note = undefine_for_redef(_ctx(tmp_path), None, "splitbox", {})
    assert not ok
    assert "allocated" in note
    assert "\\@undefined" not in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_undefine_newcommand_injects(tmp_path: Path) -> None:
    """``\\newcommand`` 形撞名 → docclass 后 ``\\let\\X\\@undefined``。"""
    _write_main(tmp_path, "\\newcommand{\\liningnums}{x}")
    ok, note = undefine_for_redef(_ctx(tmp_path), None, "liningnums", {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\let\\liningnums\\@undefined" in t
    assert t.index("\\let\\liningnums\\@undefined") < t.index("\\newcommand")


def test_undefine_newif_companion_abstains(tmp_path: Path) -> None:
    """``\\newif\\ifflag`` 伴生 ``\\flagtrue``/``\\flagfalse`` → abstain。"""
    _write_main(tmp_path, "\\newif\\ifflag\n\\flagtrue")
    ok, _note = undefine_for_redef(_ctx(tmp_path), None, "flagtrue", {})
    assert not ok
    ok2, _note2 = undefine_for_redef(_ctx(tmp_path), None, "ifflag", {})
    assert not ok2


def test_undefine_newcounter_c_at_abstains(tmp_path: Path) -> None:
    """``\\newcounter{ctr}`` 分配 ``\\c@ctr`` → abstain; ``\\newboolean`` 同。"""
    _write_main(tmp_path, "\\newcounter{sect}\n\\newboolean{draft}")
    ok, _ = undefine_for_redef(_ctx(tmp_path), None, "c@sect", {})
    assert not ok
    ok2, _ = undefine_for_redef(_ctx(tmp_path), None, "drafttrue", {})
    assert not ok2


def test_undefine_commented_alloc_ignored(tmp_path: Path) -> None:
    """注释掉的 ``% \\newbox\\splitbox`` 不构成护栏 → 照常注入。"""
    _write_main(tmp_path, "% \\newbox\\splitbox\n\\usepackage{adjustbox}")
    ok, _note = undefine_for_redef(_ctx(tmp_path), None, "splitbox", {})
    assert ok


def test_undefine_docclass_comment_eol_seam(tmp_path: Path) -> None:
    """docclass 行尾 ``%`` 注释 → 注入落下一行 (A1 eol+1 缝交互)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article} %!TEX program=xelatex\n"
        "\\begin{document}\nhi\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _note = undefine_for_redef(_ctx(tmp_path), None, "foo", {})
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    lines = t.splitlines()
    assert lines[0].endswith("%!TEX program=xelatex")
    assert "\\@undefined" not in lines[0]
    let_ln = next(i for i, ln in enumerate(lines) if "\\let\\foo\\@undefined" in ln)
    assert 0 < let_ln < lines.index("\\begin{document}")


def test_allocated_cs_names_prims() -> None:
    """``_allocated_cs_names`` 覆盖 *def primitive 与花括号形。"""
    blob = "\\countdef\\mycnt=5\n\\chardef\\pct=`\\%\n\\newlength{\\mylen}\n"
    names = _allocated_cs_names(blob)
    assert {"mycnt", "pct", "mylen"} <= names


# ------------------------------------------------------------- A3 glyphtounicode
def _glyphtounicode_rule() -> tuple:
    rs = Ruleset.load()
    rule = next(r for r in rs.rules if r.id == "glyphtounicode_shadow")
    return rs, rule


def test_glyphtounicode_shadow_rule_order() -> None:
    """order 46 先于 pdftex_prim guard(50)/polyfill(51) —— payload 同格先截。"""
    rs, rule = _glyphtounicode_rule()
    assert rule.order < next(r.order for r in rs.rules if r.id == "pdftex_prim_guard")
    assert rule.order < next(
        r.order for r in rs.rules if r.id == "pdftex_prim_polyfill"
    )
    assert rule.action["function"] == "bundled_class_shadow"


def test_glyphtounicode_shadow_drops_stub(tmp_path: Path) -> None:
    """cls 守卫链在场 + payload ``\\pdfglyphtounicode`` → wdir 空 stub。"""
    (tmp_path / "lipics-v2021.cls").write_text(
        "\\IfFileExists{glyphtounicode.tex}{\\input glyphtounicode}{}\n",
        encoding="utf-8",
    )
    _write_main(tmp_path, "")
    _rs, rule = _glyphtounicode_rule()
    ctx = _ctx(tmp_path)
    ok, why = _cond_ok(rule.condition, rule, ctx, MockEngine([]), "pdfglyphtounicode")
    assert ok, why
    applied, note = TRANSFORM_FNS[rule.action["function"]](
        ctx, MockEngine([]), "\\pdfglyphtounicode", rule.action["params"]
    )
    assert applied, note
    stub = (tmp_path / "glyphtounicode.tex").read_text(encoding="utf-8")
    assert "\\newcount\\pdfgentounicode" in stub
    assert "\\endinput" in stub


def test_glyphtounicode_no_source_ref_abstains(tmp_path: Path) -> None:
    """源无 glyphtounicode 引用 → condition 拒 → guard/polyfill 顺位接管。"""
    _write_main(tmp_path, "")
    _rs, rule = _glyphtounicode_rule()
    ok, _why = _cond_ok(
        rule.condition, rule, _ctx(tmp_path), MockEngine([]), "pdfglyphtounicode"
    )
    assert not ok


def test_glyphtounicode_payload_gate() -> None:
    """cs_set 外 payload (如 ``\\pdfobj``) → builtin 弃权, 不抢别格。"""
    applied, _note = bundled_class_shadow(
        LoopCtx(wdir=Path("/nonexistent"), engine_name="xelatex"),
        None,
        "pdfobj",
        {
            "target": "glyphtounicode.tex",
            "cs_set": ["pdfglyphtounicode", "pdfgentounicode"],
            "body": "\\endinput\n",
        },
    )
    assert not applied


# ------------------------------------------------------------------- A6 8-bit fb
def test_text_8bit_fallback_injected(tmp_path: Path) -> None:
    """inject_cjk 块含 CMU Serif interchartoks 回退段。"""
    _write_main(tmp_path, "")
    main = (tmp_path / "main.tex").read_text(encoding="utf-8")
    out, info = inject_cjk(main)
    assert info["status"] == "injected"
    assert "texlatecmu" in out
    assert "\\XeTeXinterchartoks" in out
    assert "cmunrm.otf" in out


def test_text_8bit_fallback_ranges() -> None:
    """回退带覆盖西里尔/希腊/拉丁扩展/组合符, 不含 CJK 段 (xeCJK 领地)。"""
    for rng in ("0400-0530", "0370-0400", "1E00-1F00", "0300-0370"):
        assert rng in TEXT_8BIT_FALLBACK
    assert "4E00" not in TEXT_8BIT_FALLBACK  # CJK Unified 不派 class
    assert "\\ifdefined\\XeTeXversion" in TEXT_8BIT_FALLBACK
    assert "\\IfFileExists{cmunrm.otf}" in TEXT_8BIT_FALLBACK


def test_transform_fns_registered() -> None:
    """新 builtin 全数注册进 TRANSFORM_FNS (rules.yaml function: 面)。"""
    assert TRANSFORM_FNS["physics_stub_detach"] is physics_stub_detach
    assert TRANSFORM_FNS["undefine_for_redef"] is undefine_for_redef
