r"""killsem 车道 (2026-09-20): runaway_output 修复面双臂钉。

``sentry:page_flood`` 谱 (unbreakable box > ``\textheight`` → ``\output``
永空页 SIGKILL) 的 ``tcolorbox_breakable_inject``/``float_h_demote`` 两规
(95-targeted.yaml)。sentry-killed 轮 ``err_head`` 为空 →
``ctx_suggests`` 不可用, 门全走 ``source_contains`` 粗筛 + builtin 内
``mask_tex``/``_live_matches`` 实判。实证: 2311.04163 zh +breakable →
57p rc=0; 2504.11741 zh → 47p; 2608.09867 [H]-demote 未实测 (同机理族)。
"""

from pathlib import Path

from conftest import _write

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport


class _Eng:
    """builtin_transform/condition 路径的最小引擎替身 (不触 probe/install)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _ctx(tmp_path: Path) -> LoopCtx:
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ctx.err_head = ""  # sentry-killed 轮截断 log → 空 ctx 面
    return ctx


def _rule(rid: str) -> Rule:
    return next(r for r in load_ruleset().rules if r.id == rid)


def _apply(rid: str, tmp_path: Path) -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        _rule(rid), _ctx(tmp_path), _Eng(), "sentry:page_flood", ErrReport()
    )


def _cond(rid: str, tmp_path: Path) -> tuple[bool, str]:
    rule = _rule(rid)
    return actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, _ctx(tmp_path), _Eng(), "sentry:page_flood"
    )


def test_runaway_rules_registered() -> None:
    tcb = _rule("tcolorbox_breakable_inject")
    assert tcb.order == 199.7  # noqa: PLR2004 - schema 断言值
    assert tcb.phase == "loop"
    assert tcb.when == {"category": "runaway_output"}
    assert tcb.action["kind"] == "builtin_transform"
    assert tcb.action["function"] == "tcolorbox_breakable_inject"
    fh = _rule("float_h_demote")
    assert fh.order == 199.8  # noqa: PLR2004 - schema 断言值
    assert fh.when == {"category": "runaway_output"}
    assert fh.action["function"] == "float_h_demote"


def test_runaway_when_matches_sentry_and_none_payload(tmp_path: Path) -> None:
    """runaway_output 类目过 when 闸; sentry 外 killed/timeout 路 pay=None 亦过
    (不设 payload_required —— log-scan 检出形 payload 缺席)。"""
    for rid in ("tcolorbox_breakable_inject", "float_h_demote"):
        rule = _rule(rid)
        assert actions._when_ok(  # noqa: SLF001
            rule.when, "runaway_output", "sentry:page_flood", _ctx(tmp_path)
        )
        assert actions._when_ok(rule.when, "runaway_output", None, _ctx(tmp_path))  # noqa: SLF001
        assert not actions._when_ok(  # noqa: SLF001
            rule.when, "undefined_cs", "x", _ctx(tmp_path)
        )


def test_tcb_fires_lib_loaded_opts_prepended(tmp_path: Path) -> None:
    """2311.04163 形: ``[most]`` bundle 已含 breakable 库 → 纯 per-env 键补。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n"
        "\\usepackage[most]{tcolorbox}\n"
        "\\begin{document}\n"
        "\\begin{tcolorbox}[width=\\textwidth,colback=gray!10]\nx\n\\end{tcolorbox}\n"
        "\\begin{tcolorbox}\ny\n\\end{tcolorbox}\n"
        "\\end{document}\n",
    )
    ok, note = _apply("tcolorbox_breakable_inject", tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\begin{tcolorbox}[breakable,width=\\textwidth,colback=gray!10]" in t
    assert "\\begin{tcolorbox}[breakable]\n" in t
    assert "\\tcbuselibrary" not in t  # 库已载不补


def test_tcb_fires_injects_lib_when_absent(tmp_path: Path) -> None:
    """库未载但有 ``\\usepackage{tcolorbox}`` 装载点 → 先补 ``\\tcbuselibrary``。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n"
        "\\usepackage{tcolorbox}\n"
        "\\begin{document}\n\\begin{tcolorbox}[enhanced]\nx\n\\end{tcolorbox}\n\\end{document}\n",
    )
    ok, note = _apply("tcolorbox_breakable_inject", tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{tcolorbox}\n\\tcbuselibrary{breakable} % fixloop\n" in t
    assert "\\begin{tcolorbox}[breakable,enhanced]" in t


def test_tcb_tcbuselibrary_site_also_anchors(tmp_path: Path) -> None:
    """``\\tcbuselibrary{skins}`` 站点算装载点 (breakable 不在列 → 补载)。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n"
        "\\usepackage{tcolorbox}\n\\tcbuselibrary{skins}\n"
        "\\begin{document}\n\\begin{tcolorbox}\nx\n\\end{tcolorbox}\n\\end{document}\n",
    )
    ok, note = _apply("tcolorbox_breakable_inject", tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\tcbuselibrary{breakable} % fixloop" in t


def test_tcb_bundle_lib_tokens_count_loaded(tmp_path: Path) -> None:
    """many/most/all bundle token 均判 breakable 库已载 (tcolorbox.sty bundle 展开)。"""
    for lib in ("breakable", "many", "most", "all"):
        _write(
            tmp_path,
            "main.tex",
            "\\documentclass{article}\n"
            f"\\tcbuselibrary{{{lib}}}\n"
            "\\begin{document}\n\\begin{tcolorbox}[x=1]\nx\n\\end{tcolorbox}\n\\end{document}\n",
        )
        ok, _ = _apply("tcolorbox_breakable_inject", tmp_path)
        assert ok, lib
        t = (tmp_path / "main.tex").read_text()
        assert "breakable,x=1" in t, lib
        assert "% fixloop" not in t, lib  # 不补载


def test_tcb_declines_no_load_site(tmp_path: Path) -> None:
    """env 在但全文无 tcolorbox 装载点 (cls 内载等) → 补键产 unknown-key 新错, 让位。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n"
        "\\begin{document}\n\\begin{tcolorbox}\nx\n\\end{tcolorbox}\n\\end{document}\n",
    )
    ok, note = _apply("tcolorbox_breakable_inject", tmp_path)
    assert not ok
    assert "load site" in note
    assert "[breakable]" not in (tmp_path / "main.tex").read_text()


def test_tcb_declines_no_sites(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply("tcolorbox_breakable_inject", tmp_path)
    assert not ok
    assert "no unbreakable" in note


def test_tcb_newtcolorbox_def_patched(tmp_path: Path) -> None:
    """2504.11741 形: ``\\newtcolorbox`` def 的末位 options 组补键。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n"
        "\\usepackage[many,breakable]{tcolorbox}\n"
        "\\newtcolorbox{notebox}{colback=yellow!10}\n"
        "\\newtcolorbox[auto counter]{warnbox}[1]{title=#1}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply("tcolorbox_breakable_inject", tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\newtcolorbox{notebox}{breakable,colback=yellow!10}" in t
    assert "\\newtcolorbox[auto counter]{warnbox}[1]{breakable,title=#1}" in t


def test_tcb_neg_key_flipped(tmp_path: Path) -> None:
    """``unbreakable``/``breakable=false`` 否定形即肇事者 → 翻正为 ``breakable``。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\usepackage{tcolorbox}\n\\tcbuselibrary{breakable}\n"
        "\\begin{document}\n"
        "\\begin{tcolorbox}[unbreakable,colback=red]\nx\n\\end{tcolorbox}\n"
        "\\begin{tcolorbox}[breakable=false]\ny\n\\end{tcolorbox}\n"
        "\\end{document}\n",
    )
    ok, _ = _apply("tcolorbox_breakable_inject", tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "[breakable,colback=red]" in t
    assert "[breakable]" in t
    assert "breakable=false" not in t


def test_tcb_idempotent_second_round(tmp_path: Path) -> None:
    """补键后再无 unbreakable 站 → 重放 decline (与 dedup 键双保险)。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\usepackage[most]{tcolorbox}\n"
        "\\begin{document}\n\\begin{tcolorbox}[a=1]\nx\n\\end{tcolorbox}\n\\end{document}\n",
    )
    ok, _ = _apply("tcolorbox_breakable_inject", tmp_path)
    assert ok
    ok, note = _apply("tcolorbox_breakable_inject", tmp_path)
    assert not ok
    assert "no unbreakable" in note


def test_tcb_commented_site_masked(tmp_path: Path) -> None:
    """注释内 ``\\begin{tcolorbox}`` 不算站 → 仅注释站时 decline, 文件不动。"""
    src = (
        "\\documentclass{article}\n\\usepackage[most]{tcolorbox}\n"
        "% \\begin{tcolorbox}[unbreakable]\n\\begin{document}\nx\n\\end{document}\n"
    )
    _write(tmp_path, "main.tex", src)
    ok, _ = _apply("tcolorbox_breakable_inject", tmp_path)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_tcb_cond_gate(tmp_path: Path) -> None:
    """source_contains 粗筛: 无 tcolorbox env/def 字面 → condition 拒。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ok, _ = _cond("tcolorbox_breakable_inject", tmp_path)
    assert not ok
    _write(
        tmp_path,
        "main.tex",
        "\\usepackage{tcolorbox}\n\\begin{document}\n\\begin{tcolorbox}\nx\n\\end{tcolorbox}\n",
    )
    ok, _ = _cond("tcolorbox_breakable_inject", tmp_path)
    assert ok


def test_float_demote_fires(tmp_path: Path) -> None:
    """2608.09867 形: ``[H]`` 系混排 → ``!``+placement (``p`` 保底, 无 h/t/b 补 ``ht``)。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\usepackage{float}\n\\begin{document}\n"
        "\\begin{figure}[H]\na\n\\end{figure}\n"
        "\\begin{table}[H!tbp]\nb\n\\end{table}\n"
        "\\begin{figure*}[Hb]\nc\n\\end{figure*}\n"
        "\\end{document}\n",
    )
    ok, note = _apply("float_h_demote", tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\begin{figure}[!htp]" in t
    assert "\\begin{table}[!tbp]" in t
    assert "\\begin{figure*}[!bp]" in t


def test_float_demote_declines(tmp_path: Path) -> None:
    """无 H / 无浮体括号组 / 仅注释内 [H] → decline。"""
    for body in (
        "\\begin{figure}[htbp]\nx\n\\end{figure}\n",  # 无 H 幂等面
        "\\begin{figure}\nx\n\\end{figure}\n",  # 无选项组
        "% \\begin{figure}[H]\nx\n",  # masked 注释站
        "\\begin{table}[H,name=x]\ny\n\\end{table}\n",  # 非 placement 白名单
    ):
        _write(tmp_path, "main.tex", "\\documentclass{article}\n" + body)
        ok, _ = _apply("float_h_demote", tmp_path)
        assert not ok, body


def test_float_demote_mixed_keeps_nonplacement(tmp_path: Path) -> None:
    """同文件 ``[H,name=x]`` 非白名单组不动, ``[H]`` 组照降。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n"
        "\\begin{table}[H,name=x]\na\n\\end{table}\n"
        "\\begin{table}[H]\nb\n\\end{table}\n",
    )
    ok, _ = _apply("float_h_demote", tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\begin{table}[H,name=x]" in t
    assert "\\begin{table}[!htp]" in t


def test_float_demote_idempotent(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\n\\begin{figure}[H]\nx\n\\end{figure}\n\\end{document}\n",
    )
    ok, _ = _apply("float_h_demote", tmp_path)
    assert ok
    ok, _ = _apply("float_h_demote", tmp_path)
    assert not ok
    assert "[!htp]" in (tmp_path / "main.tex").read_text()


def test_float_demote_cond_gate(tmp_path: Path) -> None:
    """source_contains 粗筛钉字面 ``[`` 内 ``H`` —— ``[h]``/无浮体 → 拒。"""
    _write(tmp_path, "main.tex", "\\begin{figure}[h]\nx\n\\end{figure}\n")
    ok, _ = _cond("float_h_demote", tmp_path)
    assert not ok
    _write(tmp_path, "main.tex", "\\begin{algorithm}[H]\nx\n\\end{algorithm}\n")
    ok, _ = _cond("float_h_demote", tmp_path)
    assert ok


def test_arms_no_crossfire(tmp_path: Path) -> None:
    """签名互斥: tcolorbox 格 float 臂让位, [H] 格 tcb 臂让位。"""
    _write(
        tmp_path,
        "main.tex",
        "\\usepackage[most]{tcolorbox}\n\\begin{tcolorbox}\nx\n\\end{tcolorbox}\n",
    )
    ok, _ = _apply("float_h_demote", tmp_path)
    assert not ok
    _write(tmp_path, "main.tex", "\\begin{figure}[H]\nx\n\\end{figure}\n")
    ok, _ = _apply("tcolorbox_breakable_inject", tmp_path)
    assert not ok
