"""``texlate.redlines`` 单源注册表 pin：四层发射名/pattern 冻结 + 镜像断言。

★2 收敛（同概念四层三拼写 missing_chars/missing_char/missing_glyph）的
零行为变契约：本文件钉死各层**对外可观测面**——发射名、pattern、
序位、l2 红线集、judge 门控/探针行为、rules.yaml ``warnings:`` 镜像。
改 registry 引致任何一层对外面漂移即红。
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import texlate.redlines
from texlate.compile import engine as eng
from texlate.compile.fixloop import Ruleset, load_ruleset
from texlate.compile.judge import _MISSCHAR_GATE_RX, _MISSCHAR_NULLFONT_RX
from texlate.redlines import (
    ENGINE_RED_LINES,
    L2_REDLINE_CLASSES,
    REDLINES_BY_ID,
    RULES_WARNINGS,
    name_pattern,
)
from texlate.validate import l2
from texlate.validate.l2 import _REDLINE_CLASSES, _WARNING_RULES

#: engine 层发射名序（→ ``LogInfo.warnings_hit`` → judge ``warn:*`` reasons）。
_ENGINE_EMIT = [
    "invalid_utf8",
    "fffd_glyph",
    "missing_chars",
    "missing_graphic",
    "degraded_file",
]
#: rules.yaml ``warnings:`` 镜像发射名序（→ ``rep.warnings`` → warn_id 门）。
_RULES_EMIT = [
    "invalid_utf8",
    "missing_char",
    "missing_graphic",
    "tectonic_degrade",
]
#: l2 ``_WARNING_RULES`` 全类序（含非红线观察类——序变即归类优先级变）。
_L2_ALL_CLASSES = [
    "invalid_utf8",
    "missing_glyph_nullfont",
    "missing_glyph",
    "citation",
    "reference",
    "rerun",
    "font_subst",
    "file_not_found",
    "overfull",
]
#: l2 红线类集（→ ``WarningSummary.redlines``）。
_L2_RED = {
    "invalid_utf8",
    "missing_glyph",
    "missing_glyph_cjk",
    "fffd_glyph",
    "file_not_found",
}


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    """ruleset 首用时加载（test_fixloop_rules 同式——收集期不 IO）。"""
    return load_ruleset()


def test_engine_slice_matches_consumption() -> None:
    """engine.WARNING_RED_LINES == registry engine 切片（序+名+pattern）。"""
    assert list(ENGINE_RED_LINES) == eng.WARNING_RED_LINES
    assert [n for n, _ in eng.WARNING_RED_LINES] == _ENGINE_EMIT


def test_rules_yaml_warnings_mirror() -> None:
    """rules.yaml warnings: 段逐条 == registry rules 切片（镜像不漂）。"""
    assert _rs().warn_patterns == [{"id": n, "pattern": p} for n, p in RULES_WARNINGS]
    assert [n for n, _ in RULES_WARNINGS] == _RULES_EMIT


def test_l2_surfaces_match_registry() -> None:
    """l2 红线集 == registry l2 切片；_WARNING_RULES 类序+托管 pattern 冻结。"""
    assert _REDLINE_CLASSES == L2_REDLINE_CLASSES
    assert frozenset(_L2_RED) == L2_REDLINE_CLASSES
    assert [name for name, _ in _WARNING_RULES] == _L2_ALL_CLASSES
    managed = {r.l2.name: r.l2.pattern for r in REDLINES_BY_ID.values() if r.l2}
    for name, rx in _WARNING_RULES:
        if managed.get(name) is not None:
            assert rx.pattern == managed[name]


def test_misschar_three_layers_share_pattern() -> None:
    """missing_char 概念三层 pattern 同一——tempered 窗单源的字面承诺。"""
    r = REDLINES_BY_ID["missing_char"]
    assert r.engine is not None
    assert r.rules is not None
    assert r.judge is not None
    assert r.engine.pattern == r.rules.pattern
    assert r.rules.pattern == r.judge.pattern
    # engine fffd_glyph = 同一 gate 窗 + FFFD 码点段（窗漂移则 fffd 行跟着漂）
    fffd = REDLINES_BY_ID["fffd_glyph"].engine
    assert fffd is not None
    assert fffd.pattern is not None
    assert r.engine.pattern is not None
    assert fffd.pattern.startswith(r.engine.pattern)


def test_judge_gate_behavior() -> None:
    """judge 门控/探针行为冻结：nullfont 行豁免、真字体行命中。"""
    real = "Missing character: There is no 中 (U+4E2D) in font cmr10"
    nullfont = "Missing character: There is no 中 (U+4E2D) in font nullfont"
    assert _MISSCHAR_GATE_RX.search(real)
    assert not _MISSCHAR_GATE_RX.search(nullfont)
    assert _MISSCHAR_NULLFONT_RX.search(nullfont)
    assert not _MISSCHAR_NULLFONT_RX.search(real)
    # judge 层 reason 词干 = registry judge 发射名
    assert name_pattern(REDLINES_BY_ID["missing_char"].judge)[0] == (
        "missing_character"
    )
    assert name_pattern(REDLINES_BY_ID["missing_char_nullfont"].judge)[0] == (
        "missing_character_nullfont"
    )


def test_engine_scan_end_to_end() -> None:
    """engine.parse_log 抽查：graphic 缺档中 missing_graphic；nullfont
    misschar 不中 missing_chars；``!`` not-found 中 degraded_file。"""
    log = (
        "This is XeTeX, Version 3\n"
        "File `fig.png' not found\n"
        "Missing character: There is no x (U+0078) in font nullfont\n"
    )
    info = eng.parse_log(log)
    assert "missing_graphic" in info.warnings_hit
    assert "missing_chars" not in info.warnings_hit
    bang = "This is XeTeX\n! File `foo.sty' not found.\n"
    assert "degraded_file" in eng.parse_log(bang).warnings_hit


def test_l2_classify_end_to_end() -> None:
    """l2 行级归类抽查：nullfont 行归观察类、CJK 真字体行归红线派生类。"""
    v = l2.parse_log_text(
        "This is XeTeX\n"
        "Missing character: There is no 中 (U+4E2D) in font nullfont\n"
        "Missing character: There is no 中 (U+4E2D) in font cmr10\n"
    )
    assert v.warnings.by_class["missing_glyph_nullfont"] == 1
    assert v.warnings.by_class["missing_glyph_cjk"] == 1
    assert any("missing_glyph_cjk" in r for r in v.warnings.redlines)
    assert not any("nullfont" in r for r in v.warnings.redlines)


def test_no_orphan_misschar_literal() -> None:
    """反漂移哨兵：消费层不再持有脱离 registry 的 tempered misschar 字面量。"""
    src = Path(texlate.redlines.__file__).parent
    pat = re.compile(r"Missing character\(\?!")
    offenders = [
        f"{rel}:{i}"
        for rel in ("compile/engine.py", "compile/judge.py", "validate/l2.py")
        for i, line in enumerate((src / rel).read_text().splitlines(), start=1)
        if pat.search(line)
    ]
    assert offenders == [], f"registry 外残留 misschar 红线字面量: {offenders}"
