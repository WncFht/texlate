r"""unkopt 车道 (2026-09-20): ``ucs_mathletters_opt_strip`` 规则钉。

stagerun-overnite-2026-09-20 failmine5 两格 (2508.04292/2603.08693) 同形:
``\usepackage[mathletters]{ucs}`` —— ucs v2.4 utf8 引擎下自弃 (sty:19-23
``\ifx\Umathchar`` 分支 ``\endinput``, \DeclareOption*/\ProcessOptions* 永不执行),
任何选项无消费者 → ``Unknown option `mathletters' for package `ucs'`` 落 other
桶。根修 = 成员级剥除 (逗号位精确, ``mathlettersx``/``xmathletters`` 不沾), 覆盖
usepackage/RequirePackage 括号与 ``\PassOptionsToPackage`` 首参三位置; ucs 组外
同名键不剥。
"""

from pathlib import Path

from _fixloopkit import EngStub, apply, mk_ctx, rule

from texlate.compile.fixloop import actions
from texlate.compile.fixloop.ruleset import Rule

_RID_UCS = "ucs_mathletters_opt_strip"
_RID_BXC = "bxcjkjatype_engine_retire"

_OPT_ERR = (
    "! LaTeX Error: Unknown option `mathletters' for package `ucs'.\n"
    "l.166 \\usepackage[mathletters]{ucs}"
)


def _rule(rid: str) -> Rule:
    return rule(rid)


def _apply(tmp_path: Path, rid: str, err_head: str) -> tuple[bool, str]:
    return apply(rid, mk_ctx(tmp_path, err_head=err_head), None)


def _cond(tmp_path: Path, rid: str, err_head: str) -> tuple[bool, str]:
    r = rule(rid)
    return actions._cond_ok(  # noqa: SLF001
        r.condition, r, mk_ctx(tmp_path, err_head=err_head), EngStub(), None
    )


def test_ucs_rule_registered() -> None:
    rule = _rule(_RID_UCS)
    assert rule.order == 200  # noqa: PLR2004 - schema 断言值
    assert rule.phase == "loop"
    cats = {w.get("category") for w in rule.when["any"]}
    assert {"other", "unknown_option"} <= cats
    assert rule.action["kind"] == "regex_rewrite"
    rws = rule.action["params"]["rewrites"]
    assert all(rw["match_surface"] == "masked" for rw in rws)
    assert "mathletters" in rule.condition["ctx_suggests"]
    assert "mathletters" in rule.condition["source_contains"]


def test_ucs_solo_bracket_stripped(tmp_path: Path) -> None:
    """两格实读形：\\usepackage[mathletters]{ucs} → 整括号摘除。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage[mathletters]{ucs}\n"
        "\\usepackage[utf8x]{inputenc}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _apply(tmp_path, _RID_UCS, _OPT_ERR)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{ucs}\n" in t
    assert "mathletters" not in t
    assert "\\usepackage[utf8x]{inputenc}" in t


def test_ucs_bracket_positions(tmp_path: Path) -> None:
    """括号三位置：头 [mathletters,rest] / 中 [a,mathletters,b] / 末 [a,mathletters]。"""
    cases = (
        ("[mathletters,postscript]", "[postscript]"),
        ("[postscript,mathletters,autoload]", "[postscript,autoload]"),
        ("[postscript,mathletters]", "[postscript]"),
        ("[postscript, mathletters , autoload]", "[postscript, autoload]"),
    )
    for before, after in cases:
        (tmp_path / "main.tex").write_text(
            f"\\usepackage{before}{{ucs}}\n", encoding="utf-8"
        )
        ok, note = _apply(tmp_path, _RID_UCS, _OPT_ERR)
        assert ok, f"{before}: {note}"
        t = (tmp_path / "main.tex").read_text()
        assert f"\\usepackage{after}{{ucs}}" in t, (before, t)


def test_ucs_requirepackage_in_sty(tmp_path: Path) -> None:
    """cls/sty 内 \\RequirePackage[mathletters]{ucs} 同剥 (exts 面)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{foo}\n", encoding="utf-8"
    )
    (tmp_path / "foo.sty").write_text(
        "\\RequirePackage[mathletters]{ucs}\n", encoding="utf-8"
    )
    ok, note = _apply(tmp_path, _RID_UCS, _OPT_ERR)
    assert ok, note
    t = (tmp_path / "foo.sty").read_text()
    assert t == "\\RequirePackage{ucs}\n"


def test_ucs_passoptions_forms(tmp_path: Path) -> None:
    """\\PassOptionsToPackage 首参三位置; solo 剥净留 {}{ucs} no-op。"""
    cases = (
        ("{mathletters,postscript}", "{postscript}"),
        ("{postscript,mathletters,autoload}", "{postscript,autoload}"),
        ("{postscript,mathletters}", "{postscript}"),
        ("{mathletters}", "{}"),
    )
    for before, after in cases:
        (tmp_path / "main.tex").write_text(
            f"\\PassOptionsToPackage{before}{{ucs}}\n\\usepackage{{ucs}}\n",
            encoding="utf-8",
        )
        ok, note = _apply(tmp_path, _RID_UCS, _OPT_ERR)
        assert ok, f"{before}: {note}"
        t = (tmp_path / "main.tex").read_text()
        assert f"\\PassOptionsToPackage{after}{{ucs}}" in t, (before, t)


def test_ucs_group_load_bracket_stripped(tmp_path: Path) -> None:
    """组载 {ucs,other} 共享括号内 mathletters 同剥 (选项分发全组)。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[mathletters,postscript]{ucs,other}\n", encoding="utf-8"
    )
    ok, note = _apply(tmp_path, _RID_UCS, _OPT_ERR)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage[postscript]{ucs,other}" in t


def test_ucs_near_names_untouched(tmp_path: Path) -> None:
    """成员级匹配：xmathletters/mathlettersx/嵌套值不剥。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[mathletters]{ucs}\n"
        "\\usepackage[xmathletters]{foo}\n"
        "\\usepackage[mathlettersx]{bar}\n"
        "\\PassOptionsToPackage{mathlettersx}{ucs}\n",
        encoding="utf-8",
    )
    ok, note = _apply(tmp_path, _RID_UCS, _OPT_ERR)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{ucs}\n" in t
    assert "\\usepackage[xmathletters]{foo}" in t
    assert "\\usepackage[mathlettersx]{bar}" in t
    assert "\\PassOptionsToPackage{mathlettersx}{ucs}" in t


def test_ucs_other_pkg_same_name_kept(tmp_path: Path) -> None:
    """非 ucs 载点的 mathletters 键不剥 (ucs 组外保守)。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[mathletters]{ucs}\n\\usepackage[mathletters]{other}\n",
        encoding="utf-8",
    )
    ok, note = _apply(tmp_path, _RID_UCS, _OPT_ERR)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{ucs}\n" in t
    assert "\\usepackage[mathletters]{other}" in t


def test_ucs_cond_declines_wrong_err(tmp_path: Path) -> None:
    """err 面非 mathletters/ucs 标记 → ctx_suggests 拒。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[mathletters]{ucs}\n", encoding="utf-8"
    )
    ok, _ = _cond(tmp_path, _RID_UCS, "! LaTeX Error: Unknown option `override'.")
    assert not ok


def test_ucs_cond_declines_no_source(tmp_path: Path) -> None:
    """源面无 mathletters → source_contains 拒 (err/source 双闸 AND)。"""
    (tmp_path / "main.tex").write_text("\\usepackage{ucs}\n", encoding="utf-8")
    ok, _ = _cond(tmp_path, _RID_UCS, _OPT_ERR)
    assert not ok


def test_ucs_commented_load_masked(tmp_path: Path) -> None:
    """masked 面：注释掉的 \\usepackage 不动 → 活面无改 applied=False。"""
    (tmp_path / "main.tex").write_text(
        "% \\usepackage[mathletters]{ucs}\n\\usepackage{ucs}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(tmp_path, _RID_UCS, _OPT_ERR)
    assert not ok
    t = (tmp_path / "main.tex").read_text()
    assert "% \\usepackage[mathletters]{ucs}" in t


def test_ucs_idempotent_second_round(tmp_path: Path) -> None:
    """剥除后 source_contains 自锁：下一轮 condition 拒 → 幂等。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[mathletters]{ucs}\n", encoding="utf-8"
    )
    ok, _ = _apply(tmp_path, _RID_UCS, _OPT_ERR)
    assert ok
    ok, _ = _cond(tmp_path, _RID_UCS, _OPT_ERR)
    assert not ok


_BXC_ERR = (
    "Package bxcjkjatype Error: The engine in use is not supported.\n"
    "! LaTeX Error: Unknown option `whole' for package `bxcjkjatype'.\n"
    "l.43 \\usepackage[whole]{bxcjkjatype}"
)


def test_bxc_rule_registered() -> None:
    rule = _rule(_RID_BXC)
    assert rule.order == 201  # noqa: PLR2004 - schema 断言值
    assert rule.phase == "loop"
    cats = {w.get("category") for w in rule.when["any"]}
    assert "other" in cats
    rws = rule.action["params"]["rewrites"]
    assert all(rw["match_surface"] == "masked" for rw in rws)
    assert "bxcjkjatype" in rule.condition["ctx_suggests"]
    assert "bxcjkjatype" in rule.condition["source_contains"]


def test_bxc_usepackage_commented(tmp_path: Path) -> None:
    """实格形：\\usepackage[whole]{bxcjkjatype} → 行首注释中和。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage[whole]{bxcjkjatype}\n"
        "\\usepackage{xeCJK}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _apply(tmp_path, _RID_BXC, _BXC_ERR)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "%\\usepackage[whole]{bxcjkjatype}\n" in t
    assert "\\usepackage{xeCJK}" in t


def test_bxc_no_option_form(tmp_path: Path) -> None:
    """无括号形 \\usepackage{bxcjkjatype} 同收 (引擎自爆与选项无关)。"""
    (tmp_path / "main.tex").write_text("\\usepackage{bxcjkjatype}\n", encoding="utf-8")
    ok, note = _apply(tmp_path, _RID_BXC, _BXC_ERR)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert t == "%\\usepackage{bxcjkjatype}\n"


def test_bxc_requirepackage_in_sty(tmp_path: Path) -> None:
    """sty 内 \\RequirePackage[whole]{bxcjkjatype} 同注释 (exts 面)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{foo}\n", encoding="utf-8"
    )
    (tmp_path / "foo.sty").write_text(
        "\\RequirePackage[whole]{bxcjkjatype}\n", encoding="utf-8"
    )
    ok, note = _apply(tmp_path, _RID_BXC, _BXC_ERR)
    assert ok, note
    t = (tmp_path / "foo.sty").read_text()
    assert t == "%\\RequirePackage[whole]{bxcjkjatype}\n"


def test_bxc_neighbors_untouched(tmp_path: Path) -> None:
    """花括号精确匹配：bxcjkjatypex 近名与组载他员不动。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[whole]{bxcjkjatype}\n"
        "\\usepackage{bxcjkjatypex}\n"
        "\\usepackage{bxcjkjatype,xother}\n",
        encoding="utf-8",
    )
    ok, note = _apply(tmp_path, _RID_BXC, _BXC_ERR)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "%\\usepackage[whole]{bxcjkjatype}\n" in t
    assert "\\usepackage{bxcjkjatypex}\n" in t
    # 组载 {bxcjkjatype,xother} 未收 (known_gap 明记)
    assert "\\usepackage{bxcjkjatype,xother}\n" in t


def test_bxc_cond_declines_wrong_err(tmp_path: Path) -> None:
    """err 面无 bxcjkjatype 标记 → ctx_suggests 拒。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[whole]{bxcjkjatype}\n", encoding="utf-8"
    )
    ok, _ = _cond(tmp_path, _RID_BXC, "! LaTeX Error: Unknown option `utf8'.")
    assert not ok


def test_bxc_cond_declines_no_source(tmp_path: Path) -> None:
    """源面无 bxcjkjatype → source_contains 拒 (err/source 双闸 AND)。"""
    (tmp_path / "main.tex").write_text("\\usepackage{xeCJK}\n", encoding="utf-8")
    ok, _ = _cond(tmp_path, _RID_BXC, _BXC_ERR)
    assert not ok


def test_bxc_commented_load_masked(tmp_path: Path) -> None:
    """masked 面：已注释装载行不重注释 → 活面无改 applied=False。"""
    (tmp_path / "main.tex").write_text(
        "% \\usepackage[whole]{bxcjkjatype}\n", encoding="utf-8"
    )
    ok, _ = _apply(tmp_path, _RID_BXC, _BXC_ERR)
    assert not ok
    t = (tmp_path / "main.tex").read_text()
    assert "% \\usepackage[whole]{bxcjkjatype}" in t
    assert "%%" not in t


def test_bxc_idempotent_second_round(tmp_path: Path) -> None:
    """注释后装载行落 masked 盲区：第二轮 applied=False → 幂等。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[whole]{bxcjkjatype}\n", encoding="utf-8"
    )
    ok, _ = _apply(tmp_path, _RID_BXC, _BXC_ERR)
    assert ok
    ok, _ = _apply(tmp_path, _RID_BXC, _BXC_ERR)
    assert not ok
    t = (tmp_path / "main.tex").read_text()
    assert t.count("%\\usepackage[whole]{bxcjkjatype}") == 1
