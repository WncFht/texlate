"""w13b 钉 —— w13spec Part-A 五捆落地 (2026-09-20)。

B1 whenany-taxrow: ``bxcjkjatype_engine_retire`` (70-pkgopt.yaml order 201)
when.any += pkg_engine/unknown_option; ``xy_option_load`` (order 198)
when.any += xypic_err —— taxrow 新类目行签名回收 (2609.20764/2607.14648)。
B2 microtype-xetex: ``microtype_expansion_off`` (50-font.yaml order 72)
``when: {other}`` → ``any: [{other},{microtype_pdftex}]`` (microtype_lig_off
同式兼容对; 2310.02541)。
B3 gfx-macro-indirect: ``_has_live_graphic_ref`` 加一级宏间接臂 ——
``\\newcommand``/``\\def`` 包装体内 ``\\includegraphics{..#N..}`` 形参回填
调用位实参 (2505.06480 ``\\fig`` 实证)。
B4 ``optlist_cond_hoist`` (70-pkgopt.yaml order 204): 选项括号内嵌
``\\if..\\else..\\fi`` 块 → ``\\PassOptionsToPackage`` 外提 + 装载行重开括号
(2609.20135 webofc.cls); 同形条目别名×6 串行剥 ≤6 块/趟。
B7 svjour-clo: ``_SVJOUR_CLO_BODY`` 补 svepj.clo PACS 面四件
(``\\pacsstart``/``\\and``/``\\PACS``/``\\@@PACS``, 嵌套位 ## 归一顶层 #)。
ichep residual: ``legacy_pkg_shim`` shim_map ``ichep.cls`` 内联体补
``\\fl``/``\\Table``/``\\mpl``/``\\Bibliography``/``leqnarray`` 五件
(hep-ph/9412258)。
"""

from pathlib import Path

import regex

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop._builtins_graphics import _has_live_graphic_ref
from texlate.compile.fixloop._builtins_shim import _SVJOUR_CLO_BODY
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.fixloop.ruleset import Rule

_RS = load_ruleset()
_BXC = next(r for r in _RS.rules if r.id == "bxcjkjatype_engine_retire")
_XY = next(r for r in _RS.rules if r.id == "xy_option_load")
_MTEXP = next(r for r in _RS.rules if r.id == "microtype_expansion_off")
_OPTCOND = next(r for r in _RS.rules if r.id == "optlist_cond_hoist")
_SHIM = next(r for r in _RS.rules if r.id == "legacy_pkg_shim")


def _sub_all(rule: Rule, text: str) -> str:
    """rewrite 列表全条目依序过真管线 (B4 同形条目逐条剥一块)。"""
    for pat, repl, masked in actions._compile_rewrites(  # noqa: SLF001
        rule.action["params"]["rewrites"]
    ):
        if masked:
            text = actions._masked_sub(pat, repl, text)  # noqa: SLF001
        else:
            text = actions._bounded_sub(pat, repl, text)  # noqa: SLF001
    return text


def _ctx(tmp_path: Path, files: dict[str, str]) -> LoopCtx:
    for name, body in files.items():
        (tmp_path / name).write_text(body)
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


def test_ruleset_loads_with_w13b_rules() -> None:
    """新臂在册且位次钉死 (共仓兄弟 lane 并发加规则, 只钉下界)。"""
    assert len(_RS.rules) >= 200  # noqa: PLR2004 - 落地时已逾 200
    assert _OPTCOND.order == 204  # noqa: PLR2004 - cite_natbib_clash_retire(203) 后
    assert _OPTCOND.action["kind"] == "regex_rewrite"
    assert len(_OPTCOND.action["params"]["rewrites"]) == 6  # noqa: PLR2004
    assert _OPTCOND.action["params"]["exts"] == [".tex", ".sty", ".cls"]


def test_b1_whenany_taxrow() -> None:
    """B1 门: 两臂 when.any 各收新 taxrow 类目 (原类目全留)。"""
    cats = {w["category"] for w in _BXC.when["any"]}
    assert {"other", "early_eof", "syntax", "pkg_engine", "unknown_option"} <= cats
    cats = {w["category"] for w in _XY.when["any"]}
    assert {"other", "syntax", "xypic_err"} <= cats
    assert _BXC.condition["ctx_suggests"] == "bxcjkjatype"


def test_b2_microtype_expansion_when_widened() -> None:
    """B2 门: expansion_off when 收成 microtype_lig_off 同式兼容对。"""
    cats = {w["category"] for w in _MTEXP.when["any"]}
    assert cats == {"other", "microtype_pdftex"}
    assert _MTEXP.condition["ctx_suggests"] == "expansion does not work"


def test_b4_arm_gate() -> None:
    """B4 门: 雪崩面类目 + ctx 多签 + 括号内 \\if 源签 (括号外 \\if 不开闸)。"""
    cats = {w["category"] for w in _OPTCOND.when["any"]}
    assert {
        "syntax",
        "other",
        "unknown_option",
        "key_unknown",
        "keyval_undef",
        "undefined_cs",
        "hyperref_driver",
    } <= cats
    ctx_pat = _OPTCOND.condition["ctx_suggests"]
    for sig in (
        "Extra \\fi",
        "Extra \\else",
        "Unknown option `x' for package `p'",
        "keyval Error",
        "Undefined control sequence",
        "Wrong DVI mode driver option `dvips'",
    ):
        assert regex.search(ctx_pat, sig), sig
    sc = _OPTCOND.condition["source_contains"]
    assert regex.search(
        sc, "\\RequirePackage[\n\\ifnum\\pdfoutput=\\z@\n dvips,\\fi\n]{hyperref}"
    )
    assert regex.search(sc, "\\usepackage{plain}\n\\ifnum\\pdfoutput=\\z@\\fi") is None


def test_b4_hoist_two_blocks() -> None:
    """B4 改写: 两块括号内 \\if 全外提为守卫 PassOptions 行, 重开括号留静态残件。"""
    src = (
        "\\RequirePackage[\n"
        "  \\ifnum\\pdfoutput=\\z@\n"
        "    dvips,\n"
        "  \\else\n"
        "    pdftex,\n"
        "  \\fi\n"
        "  unicode=true,\n"
        "  \\if@online\n"
        "    bookmarks=true,\n"
        "  \\fi\n"
        "  pdfstartview={FitH 1000},\n"
        "]\n"
        "{hyperref}\n"
    )
    out = _sub_all(_OPTCOND, src)
    assert "\\ifnum\\pdfoutput=\\z@\n\\PassOptionsToPackage{dvips,}{hyperref}" in out
    assert "\\else\n\\PassOptionsToPackage{pdftex,}{hyperref}\n\\fi" in out
    assert "\\if@online\n\\PassOptionsToPackage{bookmarks=true,}{hyperref}" in out
    assert "\\PassOptionsToPackage{}{hyperref}" in out  # \\else 缺省空载 no-op
    brk = out[out.index("\\RequirePackage[") :]
    assert "\\if" not in brk  # 重开括号内 \\if 清零
    assert "unicode=true" in brk
    assert "pdfstartview={FitH 1000}" in brk
    assert _sub_all(_OPTCOND, out) == out  # 幂等


def test_b4_declines() -> None:
    """B4 拒解面: 条件与 then 部同行 / 括号外 \\if / then 部内嵌套 \\if。"""
    same_line = "\\usepackage[\n  \\ifnum\\pdfoutput=\\z@ dvips,\\fi\n]{hyperref}"
    assert _sub_all(_OPTCOND, same_line) == same_line
    out_of = "\\ifnum\\pdfoutput=\\z@\n\\RequirePackage[hyphenbreaks]{breakurl}\n\\fi"
    assert _sub_all(_OPTCOND, out_of) == out_of
    nested = "\\usepackage[\n\\ifx\\a\\b\n  \\ifinner x\\fi y,\\fi\n]{p}"
    assert _sub_all(_OPTCOND, nested) == nested


def test_b4_masked_comment_block() -> None:
    """B4 masked 面: 注释内 \\if 块不可见 —— 无可剥块即不动。"""
    src = "\\usepackage[a,\n% \\ifx\\b\\c\n% d,\n% \\fi\nb]{p}"
    assert _sub_all(_OPTCOND, src) == src


def test_b3_macro_indirect_hit(tmp_path: Path) -> None:
    """B3: ``\\newcommand`` 包装宏 #N 回填 —— def 在 main.tex 调用在 sub.tex。"""
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": (
                "\\newcommand{\\fig}[6]\n"
                "{\\begin{#1}[#2]\n"
                "    \\includegraphics[width=#3\\linewidth]{#4}\\caption{#5}\\label{#6}\n"
                "\\end{#1}}\n"
                "\\input{sub}\n"
            ),
            "sub.tex": (
                "\\fig{figure*}{htb}{1}{01-abstract}\n{\\textbf{cap}}{fig:x}\n"
            ),
        },
    )
    assert _has_live_graphic_ref(ctx, "01-abstract")
    assert _has_live_graphic_ref(ctx, "01-abstract.pdf")  # stem 双侧口径
    assert not _has_live_graphic_ref(ctx, "zzz-nope")


def test_b3_macro_indirect_prim_and_masked(tmp_path: Path) -> None:
    """B3: ``\\def`` 形参记号形同收; 注释内 def 不算。"""
    ctx = _ctx(
        tmp_path,
        {
            "main.tex": (
                "\\def\\pic#1#2{\\fbox{\\includegraphics{#2}}}\n"
                "% \\newcommand{\\ghost}[1]{\\includegraphics{#1}}\n"
                "\\begin{document}\n\\pic{cap}{figs/real}\n"
            ),
        },
    )
    assert _has_live_graphic_ref(ctx, "real.png")  # basename/stem 口径
    assert not _has_live_graphic_ref(ctx, "ghost-target")


def test_b3_literal_still_first(tmp_path: Path) -> None:
    """B3 退化: 字面 \\includegraphics 引用点照常 (间接臂纯增量)。"""
    ctx = _ctx(tmp_path, {"main.tex": "\\includegraphics{direct}\n"})
    assert _has_live_graphic_ref(ctx, "direct")


def test_b7_svjour_clo_pacs_surface() -> None:
    """B7: svepj.clo PACS 面四件入体 (顶层单 #), \\endinput 收尾。"""
    body = _SVJOUR_CLO_BODY
    for frag in (
        "\\def\\pacsstart#1#2{#1\\hskip5pt plus2ptminus2pt#2}%",
        "\\def\\and#1#2{\\unskip\\ -- #1\\hskip5pt plus2ptminus2pt#2}%",
        "\\def\\PACS#1{\\gdef\\@PACS{#1}}",
        "\\def\\@@PACS{\\par\\addvspace\\baselineskip",
        "\\expandafter\\pacsstart\\@PACS\\par}",
    ):
        assert frag in body, frag
    assert "##" not in body
    assert body.endswith("\\endinput\n")


def test_ichep_shim_body_residual() -> None:
    """ichep 残留: shim_map 内联体补 \\fl/\\Table/\\mpl/\\Bibliography/leqnarray。"""
    body = _SHIM.action["params"]["shim_map"]["ichep.cls"]["body"]
    for frag in (
        "\\providecommand{\\fl}{}",
        "\\newcommand{\\Table}[2]{\\begin{tabular}{#1}#2\\end{tabular}}",
        "\\newcommand{\\mpl}[3]{Mod.~Phys.~Lett. {\\bf A#1} (19#2) #3}",
        "\\providecommand{\\Bibliography}[1]{\\begin{thebibliography}{#1}}",
        "\\newenvironment{leqnarray}{\\begin{eqnarray}}{\\end{eqnarray}}",
    ):
        assert frag in body, frag
