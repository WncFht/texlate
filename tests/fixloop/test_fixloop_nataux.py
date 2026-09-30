r"""``natbib_aux_force_purge`` 规则钉 (80-bib.yaml, failmine item 2, 4 格)。

机制: ``natbib_numbers_pass`` (95-targeted order 186) preamble 末翻
``\NAT@numberstrue``, 使 natbib ``\AtEndDocument`` 向 aux 写
``\NAT@force@numbers`` 空转——只挡 FUTURE 写; 先前编译遗留的 .aux 已含
``\providecommand\NAT@force@numbers{}\NAT@force@numbers`` 行
(natbib.sty:967-968 写面, pipe-fix 工作区多格实证单行形), 次遍
``\begin{document}`` 期 aux 读仍炸 "Bibliography not compatible with
author-year citations" 而 numbers_pass 已 applied 不再点火。本规则
整行剥除标记——aux 可再生件, 再写源已被上游规则断掉, 剥一次即净。
"""

from functools import lru_cache
from pathlib import Path

import regex
from _fixloopkit import MAIN_TEX, XETEX_CLEAN_LOG, EngStub, ScriptEng

from texlate.compile.fixloop import Ruleset, actions, fixloop, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport, parse_text


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    """ruleset 首用时加载——收集期不 IO (坏 yaml 报 test fail 而非 collection error)。"""
    return load_ruleset()


def _rule() -> Rule:
    return next(r for r in _rs().rules if r.id == "natbib_aux_force_purge")


# natbib.sty:967-968 \AtEndDocument 真实写面: provide+invoke 同一行。
_AUX_MARKED = (
    "\\relax\n"
    "\\newlabel{a}{{1}{1}{ok}}\n"
    "\\providecommand\\NAT@force@numbers{}\\NAT@force@numbers\n"
    "\\bibcite{x}{{1}{}{a}{b}}\n"
)
# file-line-error 形首错 (xelatex -file-line-error; .aux 内读炸的实证形态)。
_COMPAT_LOG = (
    "This is XeTeX\n(./main.aux\n"
    "./main.aux:32: Package natbib Error: Bibliography not compatible "
    "with author-year citations.\nl.32 \\NAT@force@numbers\n"
)


def _pat() -> regex.Pattern[str]:
    rw = _rule().raw["action"]["params"]["rewrites"][0]
    flags = 0
    for fl in rw.get("flags") or []:
        flags |= getattr(regex, fl)
    return regex.compile(rw["pattern"], flags)


def _sub(src: str) -> str:
    rw = _rule().raw["action"]["params"]["rewrites"][0]
    return _pat().sub(rw["repl"], src)


def _ctx(wdir: Path, err_head: str = "") -> LoopCtx:
    ctx = LoopCtx(wdir=wdir, engine_name="xelatex", main_rel="main.tex")
    ctx.err_head = err_head
    return ctx


def _apply(wdir: Path) -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        _rule(), _ctx(wdir), EngStub(), None, ErrReport()
    )


# ---------------------------------------------------------------- taxonomy
def test_compat_signature_classifies_other() -> None:
    r"""``.aux:NN:`` file-line 签名 taxrow 归 ``bib_compat``。"""
    rep = parse_text(_COMPAT_LOG)
    cat, _pay = _rs().taxonomy.classify(rep)
    assert cat == "bib_compat"


def test_rule_shape() -> None:
    r"""loop 相 order 195 (begindoc_tail_recomment 194 同签族殿后) + other 猫 +
    ctx_suggests 签名 + fileset .aux 预筛 + exts [.aux] 直改。"""
    r = _rule()
    assert r.raw["phase"] == "loop"
    assert r.raw["order"] == 195  # noqa: PLR2004
    assert r.raw["when"] == {"any": [{"category": "other"}, {"category": "bib_compat"}]}
    assert r.raw["action"]["kind"] == "regex_rewrite"
    assert r.raw["action"]["params"]["exts"] == [".aux"]
    cond = r.raw["condition"]
    assert "Bibliography not compatible" in cond["ctx_suggests"]
    assert ".aux" in cond["fileset"]["has_ext"]
    assert r.raw["engines"]["xelatex"]["mode"] == "native"
    assert r.raw["engines"]["tectonic"]["mode"] == "same"


# ---------------------------------------------------------------- rewrite 单测
def test_rewrite_strips_marker_real_shape() -> None:
    """真实写面行整删, 其余 aux 行逐字节不动。"""
    out = _sub(_AUX_MARKED)
    assert "\\NAT@force@numbers" not in out
    assert out == "\\relax\n\\newlabel{a}{{1}{1}{ok}}\n\\bibcite{x}{{1}{}{a}{b}}\n"


def test_rewrite_strips_lone_invoke() -> None:
    r"""裸 ``\NAT@force@numbers`` 调用行 (旧写面变体) 同收。"""
    src = "\\relax\n\\NAT@force@numbers\n\\bibcite{x}{{1}{}{a}{b}}\n"
    out = _sub(src)
    assert out == "\\relax\n\\bibcite{x}{{1}{}{a}{b}}\n"


def test_rewrite_marker_last_line_no_newline() -> None:
    """标记居末行且无尾换行 → 仍整行剥除。"""
    src = "\\relax\n\\NAT@force@numbers"
    assert _sub(src) == "\\relax\n"


def test_rewrite_lookahead_guards_longer_cs() -> None:
    r"""``\NAT@force@numbersx`` 型更长 cs 名不误伤 (名字界 lookahead)。"""
    src = "\\relax\n\\providecommand\\NAT@force@numbersx{}\\NAT@force@numbersx\n"
    assert _sub(src) == src


def test_rewrite_no_marker_noop() -> None:
    """健康 aux → 零命中原文不动。"""
    src = "\\relax\n\\newlabel{a}{{1}{1}{ok}}\n\\bibcite{x}{{1}{}{a}{b}}\n"
    assert _sub(src) == src


def test_rewrite_idempotent() -> None:
    """二入幂等: 剥后再 sub 文本不变。"""
    once = _sub(_AUX_MARKED)
    assert _sub(once) == once


# ---------------------------------------------------------------- _apply 直驱
def test_apply_fires_and_strips_only_marker(tmp_path: Path) -> None:
    """点火: marker 行剥除, 其余 aux 字节不动, .tex 零改动。"""
    (tmp_path / "main.aux").write_text(_AUX_MARKED, encoding="utf-8")
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    ok, note = _apply(tmp_path)
    assert ok
    assert "rewrite in 1 files" in note
    out = (tmp_path / "main.aux").read_text(encoding="utf-8")
    assert "\\NAT@force@numbers" not in out
    assert out == "\\relax\n\\newlabel{a}{{1}{1}{ok}}\n\\bibcite{x}{{1}{}{a}{b}}\n"
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == MAIN_TEX


def test_apply_fires_each_aux(tmp_path: Path) -> None:
    """多 .aux 含标记 → 全剥 (rewrite in N files)。"""
    (tmp_path / "main.aux").write_text(_AUX_MARKED, encoding="utf-8")
    sub = tmp_path / "chapters"
    sub.mkdir()
    (sub / "part.aux").write_text("\\relax\n\\NAT@force@numbers\n", encoding="utf-8")
    ok, note = _apply(tmp_path)
    assert ok
    assert "rewrite in 2 files" in note
    assert "\\NAT@force@numbers" not in (tmp_path / "main.aux").read_text()
    assert "\\NAT@force@numbers" not in (sub / "part.aux").read_text()


def test_apply_declines_without_marker(tmp_path: Path) -> None:
    """aux 在场但无标记 → 0 命中不点火 (留给同签后续规则)。"""
    (tmp_path / "main.aux").write_text(
        "\\relax\n\\newlabel{a}{{1}{1}{ok}}\n", encoding="utf-8"
    )
    ok, _ = _apply(tmp_path)
    assert not ok


def test_apply_declines_without_aux(tmp_path: Path) -> None:
    """无 .aux → 0 命中不点火 (fileset 闸之外 rewrite 自兜)。"""
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    ok, _ = _apply(tmp_path)
    assert not ok


# ---------------------------------------------------------------- condition 闸
def test_cond_requires_signature(tmp_path: Path) -> None:
    """err_head 无 compat 签名 → cond 拒。"""
    (tmp_path / "main.aux").write_text(_AUX_MARKED, encoding="utf-8")
    ok, why = actions._cond_ok(  # noqa: SLF001 - 闸行为直驱
        _rule().condition, _rule(), _ctx(tmp_path), EngStub(), None
    )
    assert not ok
    assert "err ctx" in why


def test_cond_requires_aux_fileset(tmp_path: Path) -> None:
    """签名在场但无 .aux → cond 拒。"""
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    ok, why = actions._cond_ok(  # noqa: SLF001
        _rule().condition,
        _rule(),
        _ctx(tmp_path, err_head="x:32: Bibliography not compatible with author-year"),
        EngStub(),
        None,
    )
    assert not ok
    assert "fileset" in why


def test_cond_passes_on_signature_plus_aux(tmp_path: Path) -> None:
    """签名 + .aux 双备 → cond 放行。"""
    (tmp_path / "main.aux").write_text(_AUX_MARKED, encoding="utf-8")
    ok, _why = actions._cond_ok(  # noqa: SLF001
        _rule().condition,
        _rule(),
        _ctx(tmp_path, err_head=_COMPAT_LOG),
        EngStub(),
        None,
    )
    assert ok


# ---------------------------------------------------------------- 端到端
def test_fixloop_e2e_stale_aux_purged(tmp_path: Path) -> None:
    """同签接力: numbers_pass(r1) 注入防再写 → 本规则(r2) 剥陈旧标记 → r3 净。"""
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (tmp_path / "main.aux").write_text(_AUX_MARKED, encoding="utf-8")
    eng = ScriptEng(
        [
            {"log": _COMPAT_LOG, "pdf": False},
            {"log": _COMPAT_LOG, "pdf": False},
            {"log": XETEX_CLEAN_LOG, "pdf": True},
        ],
        probe_cwd=False,
    )
    cell = fixloop(tmp_path, eng, ruleset=_rs())
    assert cell["verdict"] == "clean"
    fired = [a["rule"] for a in cell["actions"]]
    assert "natbib_numbers_pass" in fired  # r1 先收: 挡 FUTURE aux 写
    assert "natbib_aux_force_purge" in fired  # r2 接力: 剥存量标记
    assert "\\NAT@force@numbers" not in (tmp_path / "main.aux").read_text(
        encoding="utf-8"
    )


def test_fixloop_e2e_no_marker_falls_through(tmp_path: Path) -> None:
    """签名命中但 aux 无标记 → 本规则不点火, 不误伤健康 aux。"""
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (tmp_path / "main.aux").write_text(
        "\\relax\n\\newlabel{a}{{1}{1}{ok}}\n", encoding="utf-8"
    )
    eng = ScriptEng([{"log": _COMPAT_LOG, "pdf": False}] * 4, probe_cwd=False)
    cell = fixloop(tmp_path, eng, ruleset=_rs())
    assert all(a["rule"] != "natbib_aux_force_purge" for a in cell["actions"])
    assert "\\newlabel{a}" in (tmp_path / "main.aux").read_text(encoding="utf-8")
