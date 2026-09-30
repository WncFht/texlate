"""cs_targeted_fix cs_table 扩项单测 —— natbib 引用族 + ``\\kwd``/``\\newblock`` polyfill。

实证背景 (failmine-2026-09-19, loop2 best_effort_pdf 残面): ``\\citet``/
``\\citealt``/``\\kwd`` 的 undefined_cs payload 命中 cs_targeted_fix 但
cs_table 无键 → 落 undefined_cs_guess 未修。本批补 natbib 全家族
(citet/citealt/citealp/citeauthor/citeyearpar/citetext/citenum) 的
``{usepackage: natbib}`` 同式条 (citet×7格 citealt×4格实证) + ``\\kwd``
noop polyfill (imsart 类在而 ``\\kwd`` 缺位面: 1012.2012/1206.1960/
1811.10292, 与 startlocaldefs/endlocaldefs 同格)。均为表内键值条目,
非新规则 —— ruleset 规则数不变。

newblockpf (failmine2): ``LaTeX Error: Command \\newblock undefined.``
是 ``\\renewcommand`` 对未定义 cs 的内核签 (natbib.sty:1070 重定义
thebibliography 内 ``\\renewcommand\\newblock`` 要宿主先定义, 老类/shim
缺位面 ~13 cells)。taxonomy 新签归 ``undefined_cs:newblock`` →
canonical hskip 形 ``\\providecommand`` polyfill。
"""

from pathlib import Path
from typing import Any

import pytest

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx, Rule

_RULE_ID = "cs_targeted_fix"

#: failmine 点名缺键的 natbib 引用族 (citenum 同包同面一并收)。
NATBIB_CS = [
    "citet",
    "citealt",
    "citealp",
    "citeauthor",
    "citeyearpar",
    "citetext",
    "citenum",
]


class _EngStub:
    """``cs_targeted_fix`` 的引擎面替身 —— 只触 probe_file/install_file。"""

    def probe_file(self, fname: str, cwd: Path | None = None) -> str:
        del cwd
        return f"/texmf/{fname}"  # 系统 texmf 恒有件 → "available" 支路

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return True


def _rule() -> Rule:
    return next(r for r in load_ruleset().rules if r.id == _RULE_ID)


def _cs_table() -> dict[str, dict[str, Any]]:
    return _rule().action["params"]["cs_table"]


def _fix(ctx: LoopCtx, payload: str) -> tuple[bool, str]:
    """真表真参直驱 builtin —— 走 ruleset 装载的 cs_table 而非手抄字典。"""
    return TRANSFORM_FNS[_RULE_ID](ctx, _EngStub(), payload, _rule().action["params"])


def _proj(tmp_path: Path, tex: str) -> Path:
    (tmp_path / "main.tex").write_text(tex, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------- 规则接线
def test_ruleset_rule_count_floor() -> None:
    """条目是 cs_table 表内键值非新规则 —— 总数守住 ≥112 地板线。

    (``>=`` 只证「不缩水」证不了「不增量」——dup id 由 ruleset 装载期
    ``_dup_id_problems`` 硬拒, 不在本钉射程。)"""
    assert len(load_ruleset().rules) >= 112  # noqa: PLR2004 - schema 断言值


def test_table_natbib_family_maps_usepackage() -> None:
    """natbib 引用族七键全挂 ``{usepackage: natbib}`` 同式条。"""
    table = _cs_table()
    for cs in NATBIB_CS:
        assert table[cs] == {"usepackage": "natbib"}, cs


def test_table_kwd_polyfill_shape() -> None:
    """``kwd`` 键是 ``\\providecommand{\\kwd}[1]{}`` noop polyfill (\\n 前缀)。"""
    polyfill = _cs_table()["kwd"]["polyfill"]
    assert polyfill.startswith("\n")  # docclass 行尾 % 注释吞注入逃逸前缀
    assert "\\providecommand{\\kwd}[1]{}" in polyfill


# ---------------------------------------------------------------- when 匹配
def test_when_fires_undefined_cs_payload(tmp_path: Path) -> None:
    """undefined_cs + payload → when any 臂命中。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    assert actions._when_ok(_rule().when, "undefined_cs", "citet", ctx)  # noqa: SLF001
    assert actions._when_ok(_rule().when, "undefined_cs", "kwd", ctx)  # noqa: SLF001


def test_when_rejects_no_payload(tmp_path: Path) -> None:
    """payload 缺席 → payload_required 闸拒。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    assert not actions._when_ok(_rule().when, "undefined_cs", None, ctx)  # noqa: SLF001


# ---------------------------------------------------------------- 动作直驱
@pytest.mark.parametrize("cs", NATBIB_CS)
def test_builtin_natbib_cs_injects_usepackage(tmp_path: Path, cs: str) -> None:
    """每个 natbib 键: payload → docclass 后注 ``\\RequirePackage{natbib}``。"""
    _proj(
        tmp_path,
        "\\documentclass{article}\n\\begin{document}\n"
        f"see \\{cs}{{key}}\n\\end{{document}}\n",
    )
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok, note = _fix(ctx, cs)
    assert ok, note
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\RequirePackage{natbib}" in text
    assert text.index("\\RequirePackage{natbib}") < text.index("\\begin{document}")


def test_builtin_payload_leading_backslash(tmp_path: Path) -> None:
    """payload 带反斜杠形 ``\\citet`` 同命中 (builtin lstrip 归一)。"""
    _proj(
        tmp_path,
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok, _ = _fix(ctx, "\\citet")
    assert ok
    assert "\\RequirePackage{natbib}" in (tmp_path / "main.tex").read_text(
        encoding="utf-8"
    )


def test_builtin_natbib_already_loaded_no_dup(tmp_path: Path) -> None:
    """稿已装 natbib → 不重复注入 (masked 源码面查重)。"""
    _proj(
        tmp_path,
        "\\documentclass{article}\n\\usepackage{natbib}\n"
        "\\begin{document}\n\\citet{k}\n\\end{document}\n",
    )
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok, _ = _fix(ctx, "citet")
    assert ok  # probe_file 报 available 即 applied
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert text.count("\\usepackage{natbib}") == 1


def test_builtin_kwd_polyfill_injected(tmp_path: Path) -> None:
    """``kwd`` payload → docclass 后注 noop polyfill (preamble 面)。"""
    _proj(
        tmp_path,
        "\\documentclass{article}\n\\begin{document}\n"
        "\\kwd{keyword}\n\\end{document}\n",
    )
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok, note = _fix(ctx, "kwd")
    assert ok, note
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\providecommand{\\kwd}[1]{}" in text
    assert text.index("\\providecommand{\\kwd}") < text.index("\\begin{document}")


def test_builtin_unknown_cs_misses(tmp_path: Path) -> None:
    """表外 + 非粘连头 payload → 不中 (落 undefined_cs_guess 通道)。"""
    _proj(
        tmp_path,
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok, note = _fix(ctx, "boguscs")
    assert not ok
    assert "not in cs-fix table" in note


# ---------------------------------------------------------------- newblock
def test_table_newblock_polyfill_shape() -> None:
    """``newblock`` 键是 canonical hskip 形 ``\\providecommand`` polyfill。

    ``\\providecommand`` 先于 natbib ``\\renewcommand\\newblock``
    (natbib.sty:1070) 落位 → renew 合法接管; 宿主类已定义时 provide
    静默 no-op (runtime 幂等), 不抢类语义。"""
    polyfill = _cs_table()["newblock"]["polyfill"]
    assert polyfill.startswith("\n")  # docclass 行尾 % 注释逃逸前缀
    assert "\\providecommand{\\newblock}" in polyfill
    assert "\\hskip .11em plus .33em minus .07em" in polyfill


def test_when_fires_newblock_payload(tmp_path: Path) -> None:
    """taxonomy 归 ``undefined_cs:newblock`` 后 when 臂命中。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    assert actions._when_ok(_rule().when, "undefined_cs", "newblock", ctx)  # noqa: SLF001


def test_builtin_newblock_polyfill_injected(tmp_path: Path) -> None:
    """``newblock`` payload → docclass 缝注 providecommand (preamble 面)。"""
    _proj(
        tmp_path,
        "\\documentclass{article}\n\\usepackage{natbib}\n"
        "\\begin{document}\n\\begin{thebibliography}{9}\n"
        "\\bibitem{k} a \\newblock b\n\\end{thebibliography}\n\\end{document}\n",
    )
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok, note = _fix(ctx, "newblock")
    assert ok, note
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\providecommand{\\newblock}" in text
    assert text.index("\\providecommand{\\newblock}") < text.index("\\begin{document}")


def test_builtin_newblock_refire_idempotent(tmp_path: Path) -> None:
    """二次点火: snippet 已在 → applied nothing, 不重复注入。"""
    _proj(
        tmp_path,
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok1, _ = _fix(ctx, "newblock")
    assert ok1
    ok2, note2 = _fix(ctx, "newblock")
    assert not ok2
    assert "applied nothing" in note2
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert text.count("\\providecommand{\\newblock}") == 1
