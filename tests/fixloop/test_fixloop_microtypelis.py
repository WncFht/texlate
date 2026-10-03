r"""microtypelis 车道 (2026-09-20): microtype ``\DisableLigatures`` 修复钉。

格面: soak-2026-09-18 五格 (2609.19356/19911/20511/20581/20804) ICLR-2027 系
doc-shipped cls 模板段 ``\DisableLigatures[f]{family=sf*}`` —— 该 cs 仅
pdfTeX≥1.30/LuaTeX 可达, XeTeX 族下 microtype 抛可恢复 ``\PackageError``
("...only possible with pdftex version 1.30 or newer. Ignoring
\DisableLigatures.") → error 计数使 verdict 落 best_effort_pdf。file-line 形
签名 taxrow 归 ``microtype_pdftex`` (other 闸保兼容); ``microtype_lig_off``
行注释中和 (本引擎下该调用恒被 Ignoring, 注释即其自身语义, shipped-cls
保真不动其他行)。
"""

from pathlib import Path

from _fixloopkit import EngStub, apply, mk_ctx, rs, rule

from texlate.compile.fixloop import actions
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport, parse_text


def _rule(rid: str) -> Rule:
    return rule(rid)


def _ctx(tmp_path: Path, err_head: str = "") -> LoopCtx:
    return mk_ctx(tmp_path, err_head=err_head)


def _classify(text: str) -> tuple[str | None, str | None]:
    """kit ``classify`` 尚未透传 ``warn_patterns`` —— 本地保真版留本文件。"""
    return rs().taxonomy.classify(parse_text(text, rs().warn_patterns))


def _apply(r: Rule, tmp_path: Path, pay: str) -> tuple[bool, str]:
    return apply(r, mk_ctx(tmp_path), pay)


_ERR_HEAD = (
    "/x/splice/applemlr.cls:19: Package microtype Error: Disabling ligatures "
    "of a font is only possible\n"
    "(microtype)                with pdftex version 1.30 or newer.\n"
    "(microtype)                Ignoring \\DisableLigatures.\n"
)


# ──────────────────────────── 类目：file-line 形归 other ────────────────────────
def test_taxonomy_signature_falls_to_other() -> None:
    """真实 file-line 错行 taxrow 归 microtype_pdftex, payload=None。"""
    cat, pay = _classify(
        "./applemlr.cls:19: Package microtype Error: Disabling ligatures of a "
        "font is only possible\n(microtype)                with pdftex version "
        "1.30 or newer.\n(microtype)                Ignoring \\DisableLigatures."
        "\n\nl.19 \\DisableLigatures[f]{family=sf*}\n"
    )
    assert (cat, pay) == ("microtype_pdftex", None)


def test_rule_registered() -> None:
    """规则面：other+microtype_pdftex 双臂 + ctx_suggests, loop order 71, cls 在 exts。"""
    rule = _rule("microtype_lig_off")
    assert rule.order == 71  # noqa: PLR2004 - schema 断言值
    cats = {c.get("category") for c in rule.when["any"]}
    assert {"other", "microtype_pdftex"} <= cats
    assert "Disabling ligatures" in rule.condition["ctx_suggests"]
    assert ".cls" in rule.action["params"]["exts"]


def test_condition_gate_needs_signature(tmp_path: Path) -> None:
    """ctx_suggests 闸：err_head 无签名 → condition 拒 (other 桶不盲点火)。"""
    rule = _rule("microtype_lig_off")
    ok, why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, _ctx(tmp_path, "! some other error"), EngStub(), None
    )
    assert not ok, why


def test_condition_gate_accepts_signature(tmp_path: Path) -> None:
    """err_head 含 Disabling ligatures → condition 放行。"""
    rule = _rule("microtype_lig_off")
    ok, why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, _ctx(tmp_path, _ERR_HEAD), EngStub(), None
    )
    assert ok, why


# ──────────────────────────── 动作：行注释中和 ────────────────────────────
def test_disable_ligatures_commented_in_cls(tmp_path: Path) -> None:
    """ICLR-2027 系 cls 实形：\\DisableLigatures[f]{family=sf*} → 行注释。"""
    cls = tmp_path / "applemlr.cls"
    cls.write_text(
        "\\RequirePackage[expansion=false]{microtype}\n"
        "\\RequirePackage{etoolbox}\n"
        "\n"
        "\\DisableLigatures[f]{family=sf*}\n"
        "\n"
        "\\RequirePackage{graphicx}\n",
        encoding="utf-8",
    )
    ok, note = _apply(_rule("microtype_lig_off"), tmp_path, "")
    assert ok, note
    t = cls.read_text()
    assert "%\\DisableLigatures[f]{family=sf*}" in t
    assert "\n\\DisableLigatures" not in t
    # microtype usepackage 行不动 (microtype_off 的改写面不属于本臂)
    assert "\\RequirePackage[expansion=false]{microtype}" in t


def test_disable_ligatures_bare_and_multi(tmp_path: Path) -> None:
    """裸形 \\DisableLigatures{...} 与 .tex/.sty 面同盖; 多处调用全注释。"""
    (tmp_path / "a.sty").write_text(
        "\\RequirePackage{microtype}\n\\DisableLigatures{family=tt*}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\DisableLigatures[f]{family=sf*}\n",
        encoding="utf-8",
    )
    ok, note = _apply(_rule("microtype_lig_off"), tmp_path, "")
    assert ok, note
    assert "%\\DisableLigatures{family=tt*}" in (tmp_path / "a.sty").read_text()
    assert "%\\DisableLigatures[f]{family=sf*}" in (tmp_path / "main.tex").read_text()


def test_already_commented_no_refire(tmp_path: Path) -> None:
    """masked 面：已注释 \\DisableLigatures 行不可见 → applied=False 不再叠 %。"""
    src = "% \\DisableLigatures[f]{family=sf*}\n\\RequirePackage{microtype}\n"
    (tmp_path / "x.cls").write_text(src, encoding="utf-8")
    ok, _ = _apply(_rule("microtype_lig_off"), tmp_path, "")
    assert not ok
    assert (tmp_path / "x.cls").read_text() == src


def test_nested_cls_copies_all_rewritten(tmp_path: Path) -> None:
    """2609.19664 实形：wrapper-promote 残留的双层嵌套 fairmeta.cls 副本同愈。

    ``templates/arxiv/fairmeta.cls`` 与 ``templates/arxiv/templates/arxiv/
    fairmeta.cls`` 各携同签行 —— exts glob 按 rglob 全深度收集，两处皆注释。
    """
    for sub in ["templates/arxiv", "templates/arxiv/templates/arxiv"]:
        d = tmp_path / sub
        d.mkdir(parents=True)
        (d / "fairmeta.cls").write_text(
            "\\RequirePackage{microtype}\n\\DisableLigatures[f]{family=sf*} \n",
            encoding="utf-8",
        )
    ok, note = _apply(_rule("microtype_lig_off"), tmp_path, "")
    assert ok, note
    for p in tmp_path.rglob("fairmeta.cls"):
        assert "%\\DisableLigatures[f]{family=sf*}" in p.read_text()


def test_unrelated_cs_untouched(tmp_path: Path) -> None:
    """\\b 词界：\\DisableLigaturesX 等非目标 cs 不命中; 无命中 → applied=False。"""
    src = "\\newcommand{\\DisableLigaturesX}{}\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, _ = _apply(_rule("microtype_lig_off"), tmp_path, "")
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_match_apply_routes(tmp_path: Path) -> None:
    """整链：microtype_pdftex → 本臂；other → neutralize(47) 序位先中。

    ``microtype_disableligatures_neutralize`` (55-prim order47, other+
    emergency 面) 后加件序位在本臂 (71) 前——``other`` 签由 ``\\relax``
    中和臂收；``microtype_pdftex`` 不在其 when 面，仍归本臂注释中和。
    """
    for cat, want in (
        ("microtype_pdftex", "microtype_lig_off"),
        ("other", "microtype_disableligatures_neutralize"),
    ):
        sub = tmp_path / cat
        sub.mkdir()
        (sub / "applemlr.cls").write_text(
            "\\RequirePackage{microtype}\n\\DisableLigatures[f]{family=sf*}\n",
            encoding="utf-8",
        )
        ctx = _ctx(sub, _ERR_HEAD)
        rule, note = actions._match_apply(  # noqa: SLF001
            rs(), ctx, EngStub(), cat, None, ErrReport()
        )
        assert rule is not None, f"{cat}: {note}"
        assert rule.id == want
        body = (sub / "applemlr.cls").read_text()
        if want == "microtype_lig_off":
            assert "%\\DisableLigatures[f]{family=sf*}" in body
        else:
            assert "\\DisableLigatures" not in body


def test_xetexglyph_arm_unaffected(tmp_path: Path) -> None:
    """microtype_off 主场不回退：xetexglyph_tfm 签名不命中本臂 ctx 闸。"""
    rule = _rule("microtype_lig_off")
    ok, _why = actions._cond_ok(  # noqa: SLF001
        rule.condition,
        rule,
        _ctx(tmp_path, "! Cannot use XeTeXglyph with ptmr8c"),
        EngStub(),
        "ptmr8c",
    )
    assert not ok
