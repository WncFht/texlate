"""csfix8 批 (task #315) —— singles4 triage 六格直改单测。

``_CS_FIX_TABLE`` 默认表新增五键 + 85-shim.yaml 新规则
``provides_date_daypad`` (1511.06717, triage 前提证伪后的真实机理)。
钉死的机制要点：

- ``cref@section`` (2211.04538): crossreftools 1.0 字段层 splitter
  ``\\crt@cref@splitter@<field>#1#2`` 按 cleveref ≤0.21 双组
  ``\\r@<l>@cref`` 形取参; ≥0.21.1 五组形残留 ``{}{}{}`` 落进外层
  ``\\csname cref@<type>{}{}{}@name`` → 名带花括号的 orphan cs (写期
  undefined_cs|cref@section, ``\\def\\cref@section`` 无用 —— orphan 名
  带 ``{}{}{}`` 后缀)。根修 = begindocument/before 钩内把五字段 splitter
  改 ``#1#2#3\\fi`` 定界吞尾组再回吐 ``\\fi`` —— 包装载期 ``\\let``
  快照链 ``firstarg→counter`` 已完成，必须覆写字段名本体。
- ``bar`` (1206.1993): 95-targeted.yaml cs_table 有 ``Bar`` 键但 payload
  是小写 ``bar`` —— 精确大小写查表落空。eulervm ``\\let\\bar\\undefined``
  → AtBeginDocument 复查点 ``\\providecommand`` 补 ``\\overline`` 替身
  (docclass 缝裸 provide 会抢 eulervm ``\\DeclareMathAccent`` 名)。
- ``inputencoding`` (2504.01669): doc 体直调 ``\\inputencoding{latin1}``,
  xelatex 下 inputenc 不载 → 一参 gobble。
- ``red`` (2009.11007): doc 自有 ``{\\red 这是译文}`` 色切宏无定义 →
  xcolor 装载 + 组内色切替身。
- ``+`` (cond-mat/0111246): 2.09 代 tabbing 重音 ``\\+'e`` 裸调
  (tabbing env 外顶层 ``\\+`` 未定义，实证) → 零参 gobble 留 'e 文本。
- ``provides_date_daypad`` (1511.06717): aa.cls ``\\def\\filedate{2014/12/1}``
  单数字日段让 kernel ``\\@parse@version@dash`` 错位，``\\@nil`` 漏进
  ``\\ifnum`` → ``\\@ifl@ter``/``\\usepackage`` 全链 undefined_cs|@nil。
  双臂 regex_rewrite 把 YYYY/M/D 单数字月日段补零 (月臂先跑日臂后跑
  任一序皆收敛，双位数/三位数段不动)。
"""

from pathlib import Path

from _fixloopkit import DOC, rule
from test_fixloop_csfix7 import (
    _fix,
    _proj,
    check_backslash_payload,
    check_refire_idempotent,
    check_unknown_cs_decline,
)

from texlate.compile.fixloop.builtins.csfix import _CS_FIX_TABLE


def test_table_entries_present() -> None:
    """五键在默认表，spec 键面与机理相符。"""
    for cs in ("cref@section", "bar", "inputencoding", "red", "+"):
        assert cs in _CS_FIX_TABLE, cs
    assert set(_CS_FIX_TABLE["cref@section"]) == {"polyfill"}
    assert set(_CS_FIX_TABLE["bar"]) == {"polyfill"}
    assert set(_CS_FIX_TABLE["inputencoding"]) == {"polyfill"}
    assert set(_CS_FIX_TABLE["red"]) == {"usepackage", "polyfill"}
    assert set(_CS_FIX_TABLE["+"]) == {"polyfill"}


def test_cref_section_splitter_patch(tmp_path: Path) -> None:
    """crossreftools 字段层 splitter 补丁：#3\\fi 定界 + begindocument/before 钩。"""
    _proj(tmp_path, DOC)
    ok, note = _fix(tmp_path, "cref@section")
    assert ok, note
    assert "polyfill injected" in note
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\AddToHook{begindocument/before}" in text
    # 五字段臂全覆写 (包装载期 let 快照使 arg 层重绑够不到)。
    for field in ("counter", "number", "result", "reference", "page"):
        assert f"\\crt@cref@splitter@{field}#1#2#3\\fi" in text, field
    # 钩点在 docclass 缝后、begin{document} 前。
    assert text.index("\\AddToHook") > text.index("\\documentclass")
    assert text.index("\\AddToHook") < text.index("\\begin{document}")


def test_cref_payload_backslash_form(tmp_path: Path) -> None:
    """log payload 带反斜杠 (``\\cref@section``) → lstrip 归一同键命中。"""
    check_backslash_payload(tmp_path, "\\cref@section", "\\crt@cref@splitter@counter")


def test_bar_deferred_provide(tmp_path: Path) -> None:
    """eulervm ``\\let\\bar\\undefined`` 格 → AtBeginDocument 复查点 overline 替身。"""
    _proj(tmp_path, DOC)
    ok, _ = _fix(tmp_path, "bar")
    assert ok
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\AtBeginDocument{\\providecommand\\bar[1]{\\overline{#1}}}" in text


def test_inputencoding_gobble(tmp_path: Path) -> None:
    """xelatex 裸 ``\\inputencoding`` 调用 → 一参 gobble。"""
    _proj(tmp_path, DOC)
    ok, _ = _fix(tmp_path, "inputencoding")
    assert ok
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\providecommand\\inputencoding[1]{}" in text
    assert text.index("\\providecommand\\inputencoding") > text.index("\\documentclass")


def test_red_xcolor_and_polyfill(tmp_path: Path) -> None:
    """``\\red`` doc 自有色切 → ``\\RequirePackage{xcolor}`` + provide 替身。"""
    _proj(tmp_path, DOC)
    ok, note = _fix(tmp_path, "red")
    assert ok, note
    assert "xcolor" in note
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\RequirePackage{xcolor}" in text
    assert "\\providecommand{\\red}{\\color{red}}" in text
    assert text.index("\\RequirePackage{xcolor}") < text.index("\\begin{document}")


def test_plus_tabbing_accent_gobble(tmp_path: Path) -> None:
    """``\\+'e`` 裸调 → 零参 gobble (tabbing env 内 ``\\+`` 自重绑不受扰)。"""
    _proj(tmp_path, DOC)
    ok, _ = _fix(tmp_path, "+")
    assert ok
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\providecommand{\\+}{}" in text


def test_refire_applied_nothing(tmp_path: Path) -> None:
    """二轮重火：snippet 已在文 → applied nothing, 不重复注入。"""
    check_refire_idempotent(
        tmp_path, "inputencoding", "\\providecommand\\inputencoding[1]{}"
    )


def test_unknown_cs_still_declines(tmp_path: Path) -> None:
    """非表键 payload → 拆分臂亦不中，诚实 decline 落 guess 链。"""
    check_unknown_cs_decline(tmp_path)


# ──────────────────── provides_date_daypad (1511.06717) ────────────────────
# aa.cls \def\filedate{2014/12/1} 单数字日段 → \@parse@version 错位
# \@nil 入 \ifnum。修复面 = 源级月日段补零双臂 regex_rewrite。

import regex  # noqa: E402

from texlate.compile.fixloop.ruleset import Rule  # noqa: E402


def _daypad_rule() -> Rule:
    return rule("provides_date_daypad")


def _apply_rewrites(text: str) -> str:
    for rw in _daypad_rule().action["params"]["rewrites"]:
        text = regex.sub(rw["pattern"], rw["repl"], text)
    return text


def test_daypad_rule_shape() -> None:
    """undefined_cs+payload 门，双 condition 门，regex_rewrite 双臂。"""
    rule = _daypad_rule()
    assert rule.when == {"category": "undefined_cs", "payload_required": True}
    assert set(rule.condition) == {"payload_pattern", "source_contains"}
    assert rule.action["kind"] == "regex_rewrite"
    assert {".tex", ".sty", ".cls"} == set(rule.action["params"]["exts"])
    arms = rule.action["params"]["rewrites"]
    assert [a["match_surface"] for a in arms] == ["masked", "masked"]


def test_daypad_payload_gate() -> None:
    """``@nil``/``\\@nil`` 双形命中; 别 payload 不中。"""
    pat = _daypad_rule().condition["payload_pattern"]
    assert regex.search(pat, "@nil")
    assert regex.search(pat, "\\@nil")
    assert not regex.search(pat, "@par")
    assert not regex.search(pat, "nil")


def test_daypad_source_gate() -> None:
    """单数字月或日段命中门; 双位数/三位数段不触发。"""
    pat = _daypad_rule().condition["source_contains"]
    assert regex.search(pat, "\\def\\filedate{2014/12/1}")
    assert regex.search(pat, "\\def\\filedate{2014/1/12}")
    assert regex.search(pat, "2014/1/1")
    assert not regex.search(pat, "\\def\\filedate{2014/12/01}")
    assert not regex.search(pat, "2014/12/123")
    assert not regex.search(pat, "12014/1/1")  # 年段须恰四位


def test_daypad_rewrite_arms() -> None:
    """日段/月段补零：单数字段补 0, 双位数与三位数段原样。"""
    assert _apply_rewrites("\\def\\filedate{2014/12/1}") == (
        "\\def\\filedate{2014/12/01}"
    )
    assert _apply_rewrites("2014/1/12") == "2014/01/12"
    # 双单数字段：日臂先 2014/1/01 → 月臂 2014/01/01 —— 序无关收敛。
    assert _apply_rewrites("2014/1/1") == "2014/01/01"
    # 已规范/非日期形不动。
    assert _apply_rewrites("2014/12/01") == "2014/12/01"
    assert _apply_rewrites("2014/10/31") == "2014/10/31"
    assert _apply_rewrites("2014/12/123") == "2014/12/123"
    assert _apply_rewrites("a/b/1") == "a/b/1"
