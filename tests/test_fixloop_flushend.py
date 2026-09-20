r"""flushend lane (2026-09-19): ``flushend_keeplastbox_opt_strip`` 规则钉。

stagerun-loop2-2026-09-18 failmine2 五格 (1706.02725/1803.09012/2105.00097/
2105.03814/2111.00082, zh+base 双臂) 同形: ``\usepackage[keeplastbox]{flushend}``
——sttools 3.x flushend.sty 已删 keeplastbox 选项 (1.x ``\lastbox`` 冲刷保留
开关), 炸 ``Unknown option `keeplastbox' for package `flushend'`` @flushend.sty:83,
err 落 other 桶。根修 = 成员级剥除 (逗号位精确, ``keeplastboxfoo`` 不沾;
``{a={x,keeplastbox}}`` 嵌套值不动), 覆盖 usepackage/RequirePackage 括号与
``\PassOptionsToPackage`` 首参三位置; 非 flushend 载点的同名键不剥。
"""

from pathlib import Path

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport


class _Eng:
    """regex_rewrite/condition 路径的最小引擎替身 (不触 probe/install)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


_OPT_ERR = (
    "! LaTeX Error: Unknown option `keeplastbox' for package `flushend'.\n"
    "l.83 \\ProcessOptions"
)


def _ctx(tmp_path: Path, err_head: str = _OPT_ERR) -> LoopCtx:
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ctx.err_head = err_head
    return ctx


def _rule() -> Rule:
    return next(
        r for r in load_ruleset().rules if r.id == "flushend_keeplastbox_opt_strip"
    )


def _apply(tmp_path: Path) -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        _rule(), _ctx(tmp_path), _Eng(), None, ErrReport()
    )


def _cond(tmp_path: Path, err_head: str = _OPT_ERR) -> tuple[bool, str]:
    rule = _rule()
    return actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, _ctx(tmp_path, err_head), _Eng(), None
    )


def test_flushend_rule_registered() -> None:
    rule = _rule()
    assert rule.order == 197  # noqa: PLR2004 - schema 断言值
    assert rule.phase == "loop"
    cats = {w.get("category") for w in rule.when["any"]}
    assert {"other", "unknown_option"} <= cats
    assert rule.action["kind"] == "regex_rewrite"
    rws = rule.action["params"]["rewrites"]
    assert all(rw["match_surface"] == "masked" for rw in rws)
    assert "keeplastbox" in rule.condition["ctx_suggests"]
    assert "keeplastbox" in rule.condition["source_contains"]


def test_flushend_solo_bracket_stripped(tmp_path: Path) -> None:
    """五格实读形: \\usepackage[keeplastbox]{flushend} → 整括号摘除。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{IEEEtran}\n"
        "\\usepackage{amsmath}\n"
        "\\usepackage[keeplastbox]{flushend}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _apply(tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{flushend}\n" in t
    assert "keeplastbox" not in t


def test_flushend_bracket_positions(tmp_path: Path) -> None:
    """括号三位置: 头 [keeplastbox,spread] / 中 [a,keeplastbox,b] / 末 [a,keeplastbox]。"""
    cases = (
        ("[keeplastbox,spread]", "[spread]"),
        ("[spread,keeplastbox,debug]", "[spread,debug]"),
        ("[spread,keeplastbox]", "[spread]"),
        ("[spread, keeplastbox , debug]", "[spread, debug]"),
    )
    for before, after in cases:
        (tmp_path / "main.tex").write_text(
            f"\\usepackage{before}{{flushend}}\n", encoding="utf-8"
        )
        ok, note = _apply(tmp_path)
        assert ok, f"{before}: {note}"
        t = (tmp_path / "main.tex").read_text()
        assert f"\\usepackage{after}{{flushend}}" in t, (before, t)


def test_flushend_requirepackage_in_sty(tmp_path: Path) -> None:
    """cls/sty 内 \\RequirePackage[keeplastbox]{flushend} 同剥 (exts 面)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{foo}\n", encoding="utf-8"
    )
    (tmp_path / "foo.sty").write_text(
        "\\RequirePackage[keeplastbox]{flushend}\n", encoding="utf-8"
    )
    ok, note = _apply(tmp_path)
    assert ok, note
    t = (tmp_path / "foo.sty").read_text()
    assert t == "\\RequirePackage{flushend}\n"


def test_flushend_passoptions_forms(tmp_path: Path) -> None:
    """\\PassOptionsToPackage 首参三位置; solo 剥净留 {}{flushend} no-op。"""
    cases = (
        ("{keeplastbox,spread}", "{spread}"),
        ("{spread,keeplastbox,debug}", "{spread,debug}"),
        ("{spread,keeplastbox}", "{spread}"),
        ("{keeplastbox}", "{}"),
    )
    for before, after in cases:
        (tmp_path / "main.tex").write_text(
            f"\\PassOptionsToPackage{before}{{flushend}}\n\\usepackage{{flushend}}\n",
            encoding="utf-8",
        )
        ok, note = _apply(tmp_path)
        assert ok, f"{before}: {note}"
        t = (tmp_path / "main.tex").read_text()
        assert f"\\PassOptionsToPackage{after}{{flushend}}" in t, (before, t)


def test_flushend_group_load_bracket_stripped(tmp_path: Path) -> None:
    """组载 {flushend,other} 共享括号内 keeplastbox 同剥 (选项分发全组)。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[keeplastbox,spread]{flushend,other}\n", encoding="utf-8"
    )
    ok, note = _apply(tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage[spread]{flushend,other}" in t


def test_flushend_near_names_untouched(tmp_path: Path) -> None:
    """成员级匹配: xkeeplastbox/keeplastboxfoo/嵌套值 {a={x,keeplastbox}} 不剥。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[keeplastbox]{flushend}\n"
        "\\usepackage[xkeeplastbox]{foo}\n"
        "\\usepackage[keeplastboxfoo]{bar}\n"
        "\\PassOptionsToPackage{keeplastboxx}{flushend}\n",
        encoding="utf-8",
    )
    ok, note = _apply(tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{flushend}\n" in t
    assert "\\usepackage[xkeeplastbox]{foo}" in t
    assert "\\usepackage[keeplastboxfoo]{bar}" in t
    assert "\\PassOptionsToPackage{keeplastboxx}{flushend}" in t


def test_flushend_other_pkg_same_name_kept(tmp_path: Path) -> None:
    """非 flushend 载点的 keeplastbox 键不剥 (flushend 组外保守)。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[keeplastbox]{flushend}\n\\usepackage[keeplastbox]{other}\n",
        encoding="utf-8",
    )
    ok, note = _apply(tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{flushend}\n" in t
    assert "\\usepackage[keeplastbox]{other}" in t


def test_flushend_cond_declines_wrong_err(tmp_path: Path) -> None:
    """err 面非 keeplastbox/flushend 签名 → ctx_suggests 拒。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[keeplastbox]{flushend}\n", encoding="utf-8"
    )
    ok, _ = _cond(tmp_path, "! LaTeX Error: Unknown option `override'.")
    assert not ok


def test_flushend_cond_declines_no_source(tmp_path: Path) -> None:
    """源面无 keeplastbox → source_contains 拒 (err/source 双闸 AND)。"""
    (tmp_path / "main.tex").write_text("\\usepackage{flushend}\n", encoding="utf-8")
    ok, _ = _cond(tmp_path)
    assert not ok


def test_flushend_commented_load_masked(tmp_path: Path) -> None:
    """masked 面: 注释掉的 \\usepackage 不动 → 活面无改 applied=False。"""
    (tmp_path / "main.tex").write_text(
        "% \\usepackage[keeplastbox]{flushend}\n\\usepackage{flushend}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(tmp_path)
    assert not ok
    t = (tmp_path / "main.tex").read_text()
    assert "% \\usepackage[keeplastbox]{flushend}" in t


def test_flushend_idempotent_second_round(tmp_path: Path) -> None:
    """剥除后 source_contains 自锁: 下一轮 condition 拒 → 幂等。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[keeplastbox]{flushend}\n", encoding="utf-8"
    )
    ok, _ = _apply(tmp_path)
    assert ok
    ok, _ = _cond(tmp_path)
    assert not ok


def test_flushend_ruleset_loads() -> None:
    rs = load_ruleset()
    ids = [r.id for r in rs.rules]
    assert len(ids) == len(set(ids))
