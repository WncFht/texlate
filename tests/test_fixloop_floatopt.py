r"""floatopt lane (2026-09-19): ``float_opt_h_pkgload`` 规则钉。

stagerun-loop1-2026-09-16 failmine 五格 (0806.4088/1003.5014/1608.02624/
astro-ph/0307059/cond-mat/0408234) 同形: ``\begin{figure|table}[H]`` 系
锚 (含 ``[!Ht]``/``[Hb]``/``[H!]``/``[H!tbp]`` 混排) 是 float 宏包专属
specifier——kernel ``\@xfloat`` 只认 h/t/b/p/!, 未载 float 即炸
``Unknown float option `H'``。根修 = ``\begin{document}`` 前注入
``\usepackage{float}`` (零语义改写), 非 [H]→[htbp] 降级。与
float_opt_comma_strip(184, 逗号分隔 [t,b] 形) 零重叠。
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


_H_ERR = "! LaTeX Error: Unknown float option `H'.\nl.197 \\begin{figure}[H]"


def _ctx(tmp_path: Path, err_head: str = _H_ERR) -> LoopCtx:
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ctx.err_head = err_head
    return ctx


def _rule() -> Rule:
    return next(r for r in load_ruleset().rules if r.id == "float_opt_h_pkgload")


def _apply(tmp_path: Path) -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        _rule(), _ctx(tmp_path), _Eng(), "H", ErrReport()
    )


def _cond(tmp_path: Path, err_head: str = _H_ERR) -> tuple[bool, str]:
    rule = _rule()
    return actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, _ctx(tmp_path, err_head), _Eng(), "H"
    )


def test_floatopt_rule_registered() -> None:
    rule = _rule()
    assert rule.order == 187  # noqa: PLR2004 - schema 断言值
    assert rule.phase == "loop"
    assert rule.when["category"] == "float_opt"
    assert rule.when["payload_required"] is True
    assert rule.action["kind"] == "regex_rewrite"
    rw = rule.action["params"]["rewrites"][0]
    assert rw["match_surface"] == "masked"
    assert "H" in rule.condition["ctx_suggests"]
    assert "float" in rule.condition["source_contains"]


def test_floatopt_fires_injects_before_begindoc(tmp_path: Path) -> None:
    """cond-mat/0408234 形: [H] 无 float → \\usepackage{float} 落 preamble。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass[12pt]{iopart}\n"
        "\\usepackage{graphicx}\n"
        "\\begin{document}\n"
        "\\begin{figure}[H]\nx\\end{figure}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _apply(tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert t == (
        "\\documentclass[12pt]{iopart}\n"
        "\\usepackage{graphicx}\n"
        "% fixloop: float_opt H specifier needs float pkg\n"
        "\\usepackage{float}\n"
        "\\begin{document}\n"
        "\\begin{figure}[H]\nx\\end{figure}\n"
        "\\end{document}\n"
    )


def test_floatopt_cond_mixed_specifier_shapes(tmp_path: Path) -> None:
    """0806.4088 [!Ht] / 1608.02624 [Hb] / astro-ph/0307059 [H!tbp] 混排形过闸。"""
    for bracket in ("!Ht", "Hb", "H!", "H!tbp", "H"):
        (tmp_path / "main.tex").write_text(
            "\\documentclass{article}\n"
            f"\\begin{{figure}}[{bracket}]\nx\\end{{figure}}\n",
            encoding="utf-8",
        )
        ok, why = _cond(tmp_path)
        assert ok, f"{bracket}: {why}"


def test_floatopt_cond_declines_when_float_loaded(tmp_path: Path) -> None:
    """float 已载 (名单元素/[opts]/RequirePackage/\\input 形) → LOAD 断言拒。"""
    for load in (
        "\\usepackage{float}\n",
        "\\usepackage{graphicx,float,amsmath}\n",
        "\\usepackage[draft]{float}\n",
        "\\RequirePackage{float}\n",
        "\\input float.sty\n",
        "\\input{float.sty}\n",
    ):
        (tmp_path / "main.tex").write_text(
            "\\documentclass{article}\n"
            f"{load}\\begin{{figure}}[H]\nx\\end{{figure}}\n",
            encoding="utf-8",
        )
        ok, _ = _cond(tmp_path)
        assert not ok, load


def test_floatopt_cond_lookalike_pkgs_not_float(tmp_path: Path) -> None:
    """subfloat/floatrow/floatflt 非 float 本体 → 不算已载, 闸放行。"""
    for load in ("subfloat", "floatrow", "floatflt"):
        (tmp_path / "main.tex").write_text(
            "\\documentclass{article}\n"
            f"\\usepackage{{{load}}}\n"
            "\\begin{figure}[H]\nx\\end{figure}\n",
            encoding="utf-8",
        )
        ok, why = _cond(tmp_path)
        assert ok, f"{load}: {why}"


def test_floatopt_cond_declines_no_h_usage(tmp_path: Path) -> None:
    """float_opt 签名下源面无括号 H → USAGE 断言拒 (signature/source 双闸)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{figure}[htbp]\nx\\end{figure}\n",
        encoding="utf-8",
    )
    ok, _ = _cond(tmp_path)
    assert not ok


def test_floatopt_cond_declines_comma_payload(tmp_path: Path) -> None:
    """float_opt|, (0806.2574 逗号形) 归 comma_strip——ctx_suggests 钉 H 拒。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{figure}[t,b]\nx\\end{figure}\n",
        encoding="utf-8",
    )
    ok, _ = _cond(tmp_path, "! LaTeX Error: Unknown float option `,'.\nl.5 x")
    assert not ok


def test_floatopt_cond_declines_209_documentstyle(tmp_path: Path) -> None:
    """\\documentstyle 稿无 \\usepackage——source_contains docclass 断言拒。"""
    (tmp_path / "main.tex").write_text(
        "\\documentstyle[12pt]{article}\n\\begin{figure}[H]\nx\\end{figure}\n",
        encoding="utf-8",
    )
    ok, _ = _cond(tmp_path)
    assert not ok


def test_floatopt_idempotent_second_round(tmp_path: Path) -> None:
    """注入后 LOAD 断言自锁: 下一轮 condition 拒 → 不重复注入。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n\\begin{figure}[H]\nx\\end{figure}\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(tmp_path)
    assert ok
    ok, _ = _cond(tmp_path)
    assert not ok


def test_floatopt_commented_begindoc_masked(tmp_path: Path) -> None:
    """masked 面: 注释掉的 \\begin{document} 不命中 → applied=False。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "% \\begin{document}\n\\begin{figure}[H]\nx\\end{figure}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(tmp_path)
    assert not ok


def test_floatopt_multi_doc_each_injected(tmp_path: Path) -> None:
    """多 \\begin{document} 文件各自 preamble 获注入 (W02 多主件形)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\na\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "other.tex").write_text(
        "\\documentclass{report}\n\\begin{document}\nb\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _apply(tmp_path)
    assert ok, note
    for f in ("main.tex", "other.tex"):
        t = (tmp_path / f).read_text()
        assert "\\usepackage{float}\n\\begin{document}" in t


def test_floatopt_ruleset_loads() -> None:
    rs = load_ruleset()
    assert len(rs.rules) >= 113  # noqa: PLR2004 - 库规模断言
    ids = [r.id for r in rs.rules]
    assert len(ids) == len(set(ids))
