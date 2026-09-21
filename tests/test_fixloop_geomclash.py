r"""geomlane (2026-09-19): ``option_clash_geometry_hoist`` 规则钉。

1206.0291 (stagerun-loop2-2026-09-18 实读): vendored mn2e stub 桥
``\LoadClassWithOptions{mnras}`` → mnras.cls:117 ``\usepackage[a4paper]{geometry}``
先载, doc ``\usepackage[total={17.8cm,24.0cm},centering]{geometry}`` 撞
``Option clash for package geometry``。option_clash 三规够不到:
merge(120) 需同文件双载, loadopt_strip(121) 只收驱动词括号,
passopts(122) 需 ``\n\documentclass`` 锚点而本篇 documentclass 居文件 0
字节。本规把 clashing 装载的括号选项整组挪到载点后 ``\geometry{opts}``
(geometry 自带运行时 keyval 面)——裸载 ⊆ 实载恒静默, documentclass
位置/存在无关。
"""

from pathlib import Path

from _fixloopkit import EngStub, apply, mk_ctx, rule

from texlate.compile.fixloop import actions

_RID = "option_clash_geometry_hoist"


def _apply(tmp_path: Path) -> tuple[bool, str]:
    """钉规则动作直驱——kit ``apply`` 收口 (eng 缺省 ``EngStub``, ErrReport 内置)。"""
    return apply(_RID, mk_ctx(tmp_path), "geometry")


def _cond(tmp_path: Path, err_head: str, pay: str) -> tuple[bool, str]:
    """``actions._cond_ok`` 直驱——SLF001 豁免一处收口。"""
    r = rule(_RID)
    return actions._cond_ok(  # noqa: SLF001 - 钉规则条件直驱
        r.condition, r, mk_ctx(tmp_path, err_head=err_head), EngStub(), pay
    )


_GEOM_ERR = (
    "! LaTeX Error: Option clash for package geometry.\n"
    "l.193 \\usepackage\n[total={17.8cm,24.0cm},centering]{geometry}"
)


def test_geom_rule_registered() -> None:
    r = rule(_RID)
    assert r.order == 186  # noqa: PLR2004 - schema 断言值
    assert r.phase == "loop"
    assert r.when["category"] == "option_clash"
    assert r.action["kind"] == "regex_rewrite"
    rw = r.action["params"]["rewrites"][0]
    assert rw["match_surface"] == "masked"
    assert "geometry" in r.condition["source_contains"]
    assert "geometry" in r.condition["ctx_suggests"]


def test_geomclash_rewrite_real_shape(tmp_path: Path) -> None:
    """1206.0291 形: 括号选项整组挪载点后 \\geometry{} (裸载恒静默)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass[usenatbib,usegraphicx]{mn2e}\n"
        "\\usepackage{times}\n"
        "\\usepackage[total={17.8cm,24.0cm},centering]{geometry}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _apply(tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert (
        "\\usepackage{geometry}\n\\geometry{total={17.8cm,24.0cm},centering}\n"
    ) in t
    assert "[total={17.8cm,24.0cm},centering]{geometry}" not in t


def test_geomclash_requirepackage_kept(tmp_path: Path) -> None:
    """cls/sty 内 \\RequirePackage[opts]{geometry} 同改写, 命令名保留。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    (tmp_path / "pkg.sty").write_text(
        "\\RequirePackage[a4paper,twoside]{geometry}\n", encoding="utf-8"
    )
    ok, note = _apply(tmp_path)
    assert ok, note
    t = (tmp_path / "pkg.sty").read_text()
    assert "\\RequirePackage{geometry}\n\\geometry{a4paper,twoside}" in t


def test_geomclash_unbracketed_and_other_pkg_untouched(tmp_path: Path) -> None:
    """无括号 geometry 载点与他包括号载点都不命中 → applied=False。"""
    src = (
        "\\documentclass{article}\n"
        "\\usepackage{geometry}\n"
        "\\usepackage[draft]{graphicx}\n"
        "\\usepackage{geometry2}\n"
    )
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, _ = _apply(tmp_path)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_geomclash_commented_load_untouched(tmp_path: Path) -> None:
    """masked 面: 注释内假括号载点不改写, 活面载点照改。"""
    (tmp_path / "main.tex").write_text(
        "% \\usepackage[a4paper]{geometry}\n\\usepackage[margin=1in]{geometry}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert t == (
        "% \\usepackage[a4paper]{geometry}\n"
        "\\usepackage{geometry}\n"
        "\\geometry{margin=1in}\n"
    )


def test_geomclash_group_load_hoists_to_geometry_only(tmp_path: Path) -> None:
    """组载 {geometry,graphicx}: 组保留裸载, 共享选项收窄到 \\geometry (known_gap 钉档)。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[dvips,a4paper]{geometry,graphicx}\n", encoding="utf-8"
    )
    ok, _ = _apply(tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{geometry,graphicx}\n\\geometry{dvips,a4paper}" in t


def test_geomclash_multiple_files_all_hoisted(tmp_path: Path) -> None:
    """多文件括号载点统一改写——双侧都剥括号即双侧都不撞。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[total={17.8cm,24.0cm},centering]{geometry}\n", encoding="utf-8"
    )
    (tmp_path / "stub.cls").write_text(
        "\\usepackage[a4paper]{geometry}\n", encoding="utf-8"
    )
    ok, _ = _apply(tmp_path)
    assert ok
    assert (
        "\\geometry{total={17.8cm,24.0cm},centering}"
        in (tmp_path / "main.tex").read_text()
    )
    assert "\\geometry{a4paper}" in (tmp_path / "stub.cls").read_text()


def test_geomclash_condition_geometry_binding(tmp_path: Path) -> None:
    """ctx+source 双闸: 错面须 geometry 撞名, 源面须有括号 geometry 载点。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[a4paper]{geometry}\n", encoding="utf-8"
    )
    ok, _ = _cond(tmp_path, _GEOM_ERR, "geometry")
    assert ok
    # 他包撞名 (payload=xcolor): 源面有括号 geometry 载点也不点火
    xcol_err = "! LaTeX Error: Option clash for package xcolor.\nl.5 \\usepackage"
    ok, why = _cond(tmp_path, xcol_err, "xcolor")
    assert not ok, why


def test_geomclash_commented_gate_passes_masked_skips(tmp_path: Path) -> None:
    """注释内括号载点过 source_contains 闸 (raw 面), 但 masked 重写不动 → applied=False。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage{geometry}\n% \\usepackage[a4paper]{geometry}\n",
        encoding="utf-8",
    )
    ok, _ = _cond(tmp_path, _GEOM_ERR, "geometry")
    assert ok  # 闸过许可 (注释载点计入), masked 重写层才是真判
    ok, _note = _apply(tmp_path)
    assert not ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{geometry}\n% \\usepackage[a4paper]{geometry}" in t


def test_geomclash_condition_no_load_declines(tmp_path: Path) -> None:
    """工程完全无 geometry 载点 → source_contains 拒, 不空转。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    ok, why = _cond(tmp_path, _GEOM_ERR, "geometry")
    assert not ok, why
