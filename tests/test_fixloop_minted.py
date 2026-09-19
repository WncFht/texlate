r"""mintedstyle lane (2026-09-19): minted v3×v2 缓存错配钉。

chronic347 普查 5 格 (1803.00188/2111.00110/2112.00004/2112.00114 style
``default``, 2105.11390 ``emacs``): doc 全挂 ``frozencache`` 且自带 v2
``*.pygstyle``/``listingN.pygtex`` 缓存, 系统 minted v3.8 要
``<style>.style.minted`` → styledef 落空 + frozencache 禁再生 →
``Missing definition for highlighting style`` 每 ``\end{minted}`` 一错。
机制钉: 签名归 ``minted_froz`` 桶 (旧仅 frozencache/Cannot highlight code
两签不收此句 → 落 syntax 永不派发); ``minted_frozencache`` 规则剥
``frozencache`` 选项 + ``-shell-escape`` 放 latexminted 再生 v3 缓存
(1803.00188/2105.11390 splice 实证 rc=0 零 minted 错)。剥选项三式序贯:
``[a,frozencache,b]`` 双逗不可并吞 (粘连成 ``[ab]``), ``=true`` 值随删。
"""

import shutil
from functools import lru_cache
from pathlib import Path

import pytest

from texlate.compile.fixloop import Ruleset, actions, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.fixloop.logparse import ErrReport, parse_text


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    return load_ruleset()


def _rule(rid: str) -> Rule:
    return next(r for r in _rs().rules if r.id == rid)


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


def _classify(text: str) -> tuple[str | None, str | None]:
    return _rs().taxonomy.classify(parse_text(text, _rs().warn_patterns))


class _Eng:
    """condition/action 直驱的最小引擎替身 (不触 probe/install)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None


def _apply(rule: Rule, ctx: LoopCtx, pay: str = "") -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        rule, ctx, _Eng(), pay, ErrReport()
    )


def _write_main(tmp_path: Path, opts: str) -> LoopCtx:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage"
        + opts
        + "{minted}\n\\begin{document}\n\\begin{minted}{python}x\\end{minted}\n\\end{document}\n",
        encoding="utf-8",
    )
    return _ctx(tmp_path)


# ──────────────────────────── taxonomy: minted_froz ────────────────────────────
def test_taxonomy_missing_styledef_signature() -> None:
    """v3 "Missing definition for highlighting style" → minted_froz (此前落 syntax)。"""
    cat, _pay = _classify(
        '! Package minted Error: Missing definition for highlighting style "default" '
        "(minted executable is unavailable or disabled); attempting to substitute "
        "fallback style.\nl.461 \\end{minted}\n"
    )
    assert cat == "minted_froz"


def test_taxonomy_minted_froz_family_intact() -> None:
    """老签 (frozencache/Cannot highlight code) 与 v2 错 (Cannot find Pygments style) 同桶。"""
    cat, _ = _classify("! Package minted Error: frozencache option requires ...")
    assert cat == "minted_froz"
    cat, _ = _classify("! Package minted Error: Cannot find Pygments style default")
    assert cat == "minted_froz"


# ─────────────────────── minted_frozencache: 规则形状 ─────────────────────────
def test_rule_registered_and_condition() -> None:
    """order 130 minted_froz 触发; condition 收 latexminted/pygmentize 任一。"""
    rule = _rule("minted_frozencache")
    assert rule.order == 130  # noqa: PLR2004 - schema 断言值
    assert rule.when["category"] == "minted_froz"
    cond = rule.condition
    tools = {sub.get("tool_available") for sub in cond["any"]}
    assert tools == {"latexminted", "pygmentize"}


@pytest.mark.parametrize(
    ("opts", "want"),
    [
        ("[frozencache]", "[]"),
        ("[frozencache=true,cachedir=minted-cache]", "[cachedir=minted-cache]"),
        ("[cachedir=minted-cache,frozencache]", "[cachedir=minted-cache]"),
        ("[a,frozencache,b]", "[a,b]"),
        ("[frozencache = true]", "[]"),
        ("[nofrozencache]", "[nofrozencache]"),
    ],
)
def test_frozencache_strip_variants(tmp_path: Path, opts: str, want: str) -> None:
    """frozencache 剥除: 逗号邻位三式覆盖首/中/末位 + ``=true`` 值, 不串名。"""
    ctx = _write_main(tmp_path, opts)
    ok, note = _apply(_rule("minted_frozencache"), ctx)
    main = (tmp_path / "main.tex").read_text(encoding="utf-8")
    if want == opts:
        assert not ok
        assert f"\\usepackage{opts}{{minted}}" in main
    else:
        assert ok, note
        assert f"\\usepackage{want}{{minted}}" in main
        assert "-shell-escape" in ctx.engine_flags


def test_no_hit_no_engine_flag(tmp_path: Path) -> None:
    """无 frozencache 命中 → applied=False 且不落 -shell-escape (空转不注 flag)。"""
    ctx = _write_main(tmp_path, "[cachedir=minted-cache]")
    ok, _note = _apply(_rule("minted_frozencache"), ctx)
    assert not ok
    assert "-shell-escape" not in ctx.engine_flags


def test_condition_declines_without_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """latexminted/pygmentize 双缺 → condition fail-closed (不剥选项不注 flag)。"""
    monkeypatch.setattr(shutil, "which", lambda _cmd: None)
    rule = _rule("minted_frozencache")
    ok, _reason = actions._cond_ok(  # noqa: SLF001 - 条件原语直驱
        rule.condition, rule, _ctx(tmp_path), _Eng(), None
    )
    assert not ok
