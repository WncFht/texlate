"""early_eof 分类语义钉 —— W126 根修 (10-taxonomy.yaml `other` 兜底 `^!`→`^.`)。

缺陷: file-line-error 形 (`f.tex:N: msg`) 首错无 head 签命中时,
`other` 兜底 `^!` 锚不住 → 裸评估落 tail 段被 "No pages of output"
吞成 early_eof, 真签名类规则收不到 (0806.2594 TUletters /
astro-ph/0408240 natbib-aux 实证, \begin{document} 期 aux 读/字体声明错)。

钉:
  - file-line 形签名错 + 零页尾 → other (非 early_eof)
  - 真零错误行早夭 (无 '!'/file-line 行) → 仍 early_eof
  - tail 抢占面 (missing_file/latex209) 对签名错日志依旧可达
"""

from texlate.compile.engine import classify_error
from texlate.compile.fixloop.engine import Ruleset
from texlate.compile.fixloop.logparse import parse_text

# ── 实证形态 (stagerun-loop1-2026-09-16 cases.jsonl log_excerpt 节录) ──

_TULETTERS_LOG = (
    "/w/splice/main.tex:225: LaTeX Error: Symbol font `TUletters' is not "
    "defined.\n\nSee the LaTeX manual or LaTeX Companion for explanation.\n"
    "Type  H <return>  for immediate help.\n ...\n"
    "l.225 \\begin{document}\nYour command was ignored.\n"
    "No pages of output.\n"
)

_NATBIB_AUX_LOG = (
    "(./main.aux\n./main.aux:146: Package natbib Error: Bibliography not "
    "compatible with author-year citations.\nl.146 \\NAT@force@numbers\n)\n"
    "No pages of output.\n"
)


def _classify_log(text: str) -> tuple[str | None, str | None]:
    """全链: 真 log 文本 → parse_text → ruleset taxonomy.classify。"""
    rs = Ruleset.load()
    return rs.taxonomy.classify(parse_text(text, rs.warn_patterns))


# ---------------------------------------------------------------- W126 缺陷面
def test_fileline_signed_error_not_early_eof() -> None:
    """file-line 形签名错 + 零页尾 → taxrow 专属行 (非 early_eof, 非 other 兜底)。"""
    assert _classify_log(_TULETTERS_LOG) == ("symbol_font", "TUletters")
    assert _classify_log(_NATBIB_AUX_LOG) == ("bib_compat", "author-year")


def test_fileline_signed_error_via_classify_error() -> None:
    """薄包装同语义: file-line err + No-pages tail → symbol_font。"""
    err = "./main.tex:63: LaTeX Error: Symbol font `TUletters' is not defined."
    tail = "l.63 \\begin{document}\nNo pages of output.\n"
    cat, _ = classify_error(err, None, tail, timed_out=False)
    assert cat == "symbol_font"


def test_bang_signed_error_still_other() -> None:
    """'!' 形无签错行为不变: `other` 兜底 (原有 `^!` 语义的 `^.` 延拓)。"""
    cat, _ = classify_error(
        "! Weird unclassified failure.",
        None,
        "No pages of output.\n",
        timed_out=False,
    )
    assert cat == "other"


# ---------------------------------------------------------------- 真 early_eof 面
def test_clean_death_incomplete_still_early_eof() -> None:
    """零错误行 + \\end occurred incomplete + 零页 → early_eof 保留。"""
    cat, pay = classify_error(
        None,
        None,
        "(\\end occurred when \\ifx on line 27 was incomplete)\nNo pages of output.\n",
        timed_out=False,
    )
    assert cat == "early_eof"
    assert pay == "\\ifx"


def test_clean_death_bare_no_pages_still_early_eof() -> None:
    """零错误行 + 裸 No pages of output → early_eof 保留。"""
    cat, _ = classify_error(None, None, "...\nNo pages of output.\n", timed_out=False)
    assert cat == "early_eof"


def test_incomplete_with_output_not_early_eof() -> None:
    """guard: 有页输出仅带 \\end occurred 警告 → 不归 early_eof。"""
    cat, _ = classify_error(
        None,
        None,
        "(\\end occurred when \\ifx on line 27 was incomplete)\n"
        "Output written on main.pdf (3 pages).\n",
        timed_out=False,
    )
    assert cat == "clean"


def test_early_eof_cannot_preempt_other() -> None:
    """early_eof 无 preempts: 签名错 + \\end incomplete 同尾 → other。"""
    cat, _ = classify_error(
        "./main.tex:5: LaTeX Error: Some unclassified thing.",
        None,
        "(\\end occurred when \\ifx on line 5 was incomplete)\nNo pages of output.\n",
        timed_out=False,
    )
    assert cat == "other"


# ---------------------------------------------------------------- tail 抢占面保留
def test_tail_missing_file_still_preempts_other() -> None:
    """file-line 错 + 尾段缺档+Emergency → missing_file (preempts∋other)。"""
    cat, pay = _classify_log(
        "./main.tex:9: LaTeX Error: Some unclassified thing.\nl.9 \\x\n"
        "! File `chemgreek.sty' not found.\n! Emergency stop.\n"
        "No pages of output.\n"
    )
    assert cat == "missing_file"
    assert pay == "chemgreek.sty"


def test_tail_plea_still_preempts_other() -> None:
    """file-line 错 + cls 求档文尾 (+No pages guard) → missing_file。"""
    cat, pay = _classify_log(
        "Document Class: aastex61 2016/04/16 Version 6.1\n"
        "./main.tex:9: LaTeX Error: Some unclassified thing.\nl.9 \\x\n"
        " Please update your system to include revtex4-1.cls\n"
        "No pages of output.\n"
    )
    assert cat == "missing_file"
    assert pay == "revtex4-1.cls"


def test_tail_latex209_preempts_other() -> None:
    """compat 横幅落尾时夺回签名错路由 —— `^.` 后 latex209 tail 条挂
    preempts:[other] 保住旧可达面 (file-line 错 + 2.09 尾 → latex209)。"""
    cat, _ = _classify_log(
        "Entering LaTeX 2.09 COMPATIBILITY MODE\n"
        "./main.tex:5: LaTeX Error: Some unclassified thing.\nl.5 \\x\n"
        "No pages of output.\n"
    )
    assert cat == "latex209"


def test_tail_latex209_real_signature_not_stolen() -> None:
    """preempts:[other] 只夺未分类错: 真 head 签 (missing_file) 不被抢。"""
    cat, pay = _classify_log(
        "! LaTeX Error: File `revtex4.cls' not found.\nl.3 \\usepackage\n"
        "Entering LaTeX 2.09 COMPATIBILITY MODE\n"
        "No pages of output.\n"
    )
    assert cat == "missing_file"
    assert pay == "revtex4.cls"


# ---------------------------------------------------------------- 95-targeted 回改
def test_targeted_rules_when_no_early_eof() -> None:
    """symbolfont_tuletters / natbib_numbers_pass when 面无 early_eof 臂。"""
    rs = Ruleset.load()
    expected = {
        "symbolfont_tuletters": {"other", "symbol_font"},
        "natbib_numbers_pass": {"other"},
    }
    for rid, want in expected.items():
        rule = next(r for r in rs.rules if r.id == rid)
        cats = {
            c.get("category")
            for c in (rule.when.get("any") or [rule.when])
            if isinstance(c, dict)
        }
        assert cats == want, f"{rid} when 面应为 {want}: {cats}"
