r"""secdispatch (twinhead): 次级错误派发钉 —— logparse ``errs``/
``classify_head``/``classify_errs`` + fixloop miss-path 次级候选再匹配
+ xelatex halt_on_error 探针预算 + 探针结果 salvage 复用。

1206.0291 型: ``Missing \begin{document}`` (syntax) 首错遮蔽
``Option clash for package geometry`` (option_clash)——halt_on_error 下
轮 log 只见首错, 孪生证据只在 nonstop 全量 log; miss 时次级派发让
option_clash 类规则够到真根因。
"""

from pathlib import Path

from _fixloopkit import MockEngine, MockRes, make_proj, mini_rs

from texlate.compile.fixloop import fixloop, load_ruleset
from texlate.compile.fixloop.ruleset import Ruleset
from texlate.compile.logparse import Taxonomy, parse_text
from texlate.texlog import CTX_LINES

_TAX = [
    {
        "id": "option_clash",
        "scope": "head",
        "payload_group": 1,
        "pattern": "Option clash for package ([\\w-]+)",
    },
    {
        "id": "missing_file",
        "scope": "head",
        "payload_group": 1,
        "pattern": "File `([^']+)' not found",
    },
    {"id": "syntax", "scope": "head", "pattern": "Missing|Runaway"},
    {"id": "other", "scope": "head", "pattern": "^."},
]

_HALT_LOG = "! Missing \\begin{document}.\nl.491 \\begin{document}\n"
# 孪生间隔 >CTX_LINES(8)——err1 的 ctx blob 才不会吃进 err2 行
# (1206.0291 实形: 两错 log_line 491/503 相距 12 行)。
_TWIN_LOG = (
    "! Missing \\begin{document}.\nl.491 \\begin{document}\n"
    + "pad line\n" * 10
    + "! LaTeX Error: Option clash for package geometry.\n"
    "l.503 \\usepackage\n[total={17.8cm,24.0cm},centering]{geometry}\n"
)
_CLEAN_LOG = "This is pdfTeX\nOutput written on main.pdf (1 page).\n"
_MAIN = (
    "\\documentclass{article}\n"
    "\\usepackage[total={17.8cm,24.0cm},centering]{geometry}\n"
    "zap-me\n"
    "\\begin{document}\nx\n\\end{document}\n"
)

_FIX_CLASH = {
    "id": "fix_geom_clash",
    "phase": "loop",
    "order": 1,
    "when": {"category": "option_clash", "payload_required": True},
    "condition": {"ctx_suggests": "Option clash for package geometry\\b"},
    "action": {
        "kind": "regex_rewrite",
        "params": {
            "exts": [".tex"],
            "rewrites": [
                {
                    "pattern": "\\\\usepackage\\[[^\\]]+\\]\\{geometry\\}",
                    "repl": "\\\\usepackage{geometry}",
                }
            ],
        },
    },
}


class _HaltEngine(MockEngine):
    """xelatex ``halt_on_error`` 替身: 普通轮吐 ``script``, best_effort
    探针/兜底轮吐 ``be_script`` (各自脚本耗尽后重放末条)。"""

    halt_on_error = True

    def __init__(self, script: list, be_script: list | None = None) -> None:
        super().__init__(script)
        self.be_script = list(be_script or [{"log": ""}])
        self.calls: list[dict] = []

    def compile(
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = 2,
        best_effort: bool = False,
        **_kw: object,
    ) -> MockRes:
        self.calls.append({"passes": passes, "best_effort": best_effort})
        script, i = (
            (self.be_script, sum(1 for c in self.calls if c["best_effort"]) - 1)
            if best_effort
            else (self.script, self.rounds)
        )
        if not best_effort:
            self.rounds += 1
        return MockRes(Path(wdir), main, script[min(i, len(script) - 1)])


def _rs(rules: list[dict], **loop_over: int) -> Ruleset:
    """合成 ruleset (compile_passes=1 → 每轮恰一编译, 探针/兜底另计)。"""
    return mini_rs(
        rules=rules,
        taxonomy=_TAX,
        loop_cfg={"compile_passes": 1, **loop_over},
    )


def _tax() -> Taxonomy:
    return Taxonomy(_TAX)


# ------------------------------------------------------------- logparse 面
def test_errs_collects_each_bang_line() -> None:
    rep = parse_text(
        "! First error here.\nl.1 a\nmid stuff\n"
        "! Second error.\nl.9 b\n"
        "./x.tex:3: LaTeX Warning: ref undefined\n"  # warning 不算错误行
        "! Third.\nl.12 c\n"
    )
    assert rep.n_bang == 3  # noqa: PLR2004 - 3 条 '!' 行钉值
    assert [e[0] for e in rep.errs] == [
        "! First error here.",
        "! Second error.",
        "! Third.",
    ]
    assert rep.errs[0] == (rep.first, rep.ctx)
    assert rep.errs[1][1].startswith("! Second error.\nl.9 b")
    assert all(len(e[1].splitlines()) <= CTX_LINES for e in rep.errs)


def test_errs_file_line_error_form() -> None:
    """``-file-line-error`` 形错误行同样进 errs (Warning/==> 尾行滤除)。"""
    rep = parse_text(
        "./main.tex:5: Undefined control sequence.\nl.5 \\foo\n"
        "./main.tex:9: LaTeX Warning: something\n"
        "==> Fatal error occurred, no output PDF produced!\n"
    )
    assert rep.n_bang == 1
    assert rep.errs[0][0] == "./main.tex:5: Undefined control sequence."


def test_errs_capped_at_32() -> None:
    rep = parse_text("".join(f"! err {i}\nl.{i} x\n" for i in range(40)))
    assert rep.n_bang == 40  # noqa: PLR2004 - 超帽样本量
    assert len(rep.errs) == 32  # noqa: PLR2004 - _ERRS_MAX 钉值


def test_classify_head_per_error() -> None:
    tax = _tax()
    assert tax.classify_head(
        "! LaTeX Error: Option clash for package geometry.", "l.5 \\usepackage"
    ) == ("option_clash", "geometry")
    assert tax.classify_head("! Missing \\begin{document}.", "l.1 x") == (
        "syntax",
        None,
    )
    assert tax.classify_head("! Unrecognized blob", "") == ("other", None)
    assert tax.classify_head(None, None) is None
    # 无 catchall 的 taxonomy: 不识错误 → None (调用方决定兜底)
    tax2 = Taxonomy([{"id": "syntax", "scope": "head", "pattern": "Missing"}])
    assert tax2.classify_head("! Weird", "") is None


def test_classify_head_consistent_with_classify() -> None:
    """抽出前后首错分类零漂移。"""
    tax = _tax()
    rep = parse_text("! LaTeX Error: Option clash for package geometry.\nl.5 x\n")
    assert tax.classify(rep) == ("option_clash", "geometry")
    assert tax.classify(rep) == tax.classify_head(rep.first, rep.ctx)


def test_classify_errs_dedupe_preserves_order() -> None:
    tax = _tax()
    rep = parse_text(
        "! Missing \\begin{document}.\nl.1 x\n"
        + "pad\n" * 10
        + "! LaTeX Error: Option clash for package geometry.\nl.5 y\n"
        + "pad\n" * 10
        + "! Missing $ inserted.\nl.9 z\n"  # 同 syntax → dedupe
    )
    assert tax.classify_errs(rep) == [("syntax", None), ("option_clash", "geometry")]
    rep2 = parse_text(
        "! LaTeX Error: Option clash for package geometry.\nl.5 y\n"
        + "pad\n" * 10
        + "! Missing \\begin{document}.\nl.1 x\n"
    )
    # 输出序跟随错误序, 非 taxonomy 序
    assert tax.classify_errs(rep2) == [
        ("option_clash", "geometry"),
        ("syntax", None),
    ]


def test_err_candidates_carry_source_blob() -> None:
    cands = _tax().err_candidates(parse_text(_TWIN_LOG))
    assert [c[:2] for c in cands] == [
        ("syntax", None),
        ("option_clash", "geometry"),
    ]
    assert cands[1][2] == "! LaTeX Error: Option clash for package geometry."
    assert "Option clash for package geometry" in cands[1][3]


def test_real_taxonomy_12060291_twin_surface() -> None:
    """1206.0291 形 log → 真 taxonomy 全错误面含 (option_clash, geometry)。"""
    rep = parse_text(
        "! Missing \\begin{document}.\n<recently read> \\begin\n"
        "l.491 \\begin{document}\n"
        + "pad\n"
        * 40
        + "! LaTeX Error: Option clash for package geometry.\n"
        "l.503 \\usepackage\n[total={17.8cm,24.0cm},centering]{geometry}\n"
    )
    tax = load_ruleset().taxonomy
    assert ("option_clash", "geometry") in tax.classify_errs(rep)
    cand = next(c for c in tax.err_candidates(rep) if c[0] == "option_clash")
    assert "Option clash for package geometry" in cand[3]


# ------------------------------------------------------------- 引擎 miss 面
def test_secondary_dispatch_free_candidates_no_probe(tmp_path: Path) -> None:
    """nonstop log 自带孪生 (n_bang≥2): 免费候选直派, 零探针编译。"""
    make_proj(tmp_path, _MAIN)
    eng = _HaltEngine([{"log": _TWIN_LOG}, {"log": _CLEAN_LOG, "pdf": True}])
    cell = fixloop(tmp_path, eng, ruleset=_rs([_FIX_CLASH]))
    assert cell["verdict"] == "clean"
    act = next(a for a in cell["actions"] if a["rule"] == "fix_geom_clash")
    assert act["via"] == "secondary:option_clash"
    assert not any(c["best_effort"] for c in eng.calls)
    assert "\\usepackage{geometry}" in (tmp_path / "main.tex").read_text()
    assert any("secondary dispatch -> option_clash:geometry" in e for e in cell["log"])


def test_secondary_dispatch_xelatex_probe(tmp_path: Path) -> None:
    """halt_on_error 单错 log: miss → best_effort 探针见孪生 → 派发命中。"""
    make_proj(tmp_path, _MAIN)
    eng = _HaltEngine(
        [{"log": _HALT_LOG}, {"log": _CLEAN_LOG, "pdf": True}],
        be_script=[{"log": _TWIN_LOG}],
    )
    cell = fixloop(tmp_path, eng, ruleset=_rs([_FIX_CLASH]))
    assert cell["verdict"] == "clean"
    assert [c["best_effort"] for c in eng.calls].count(True) == 1
    act = next(a for a in cell["actions"] if a["rule"] == "fix_geom_clash")
    assert act["via"] == "secondary:option_clash"
    assert any("secondary probe: err=2" in e for e in cell["log"])


def test_probe_result_reused_by_salvage(tmp_path: Path) -> None:
    """候选全灭 → 原裁决; 探针结果兜底复用——全程恰一发 best_effort 编译。"""
    make_proj(tmp_path, _MAIN)
    # 条件要 xcolor 撞名——探针孪生是 geometry → 候选点火失败, 原裁决
    rule = {
        **_FIX_CLASH,
        "id": "fix_xcolor",
        "condition": {"ctx_suggests": "Option clash for package xcolor\\b"},
    }
    eng = _HaltEngine(
        [{"log": _HALT_LOG}],
        be_script=[{"log": _TWIN_LOG, "pdf": True}],
    )
    cell = fixloop(tmp_path, eng, ruleset=_rs([rule]))
    # 探针产出 pdf → 兜底复用 → best_effort_pdf
    assert cell["verdict"] == "best_effort_pdf"
    assert [c["best_effort"] for c in eng.calls].count(True) == 1
    assert cell["rounds"][-1]["salvage"] is True
    assert cell["rounds"][-1]["pdf"] is True


def test_probe_budget_max_two(tmp_path: Path) -> None:
    """探针预算 ≤2/格: 两轮次级修复后再 miss → 预算尽直落原裁决。"""
    make_proj(tmp_path, _MAIN)
    rules = [
        _FIX_CLASH,
        {
            "id": "fix_missing",
            "phase": "loop",
            "order": 2,
            "when": {"category": "missing_file"},
            "action": {
                "kind": "regex_rewrite",
                "params": {
                    "exts": [".tex"],
                    "rewrites": [{"pattern": "zap-me", "repl": ""}],
                },
            },
        },
    ]
    twin2_log = (
        "! Missing \\begin{document}.\nl.1 x\n"
        + "pad\n" * 10
        + "! LaTeX Error: File `zzz.sty' not found.\nl.2 y\n"
    )
    eng = _HaltEngine(
        [{"log": _HALT_LOG}] * 3,
        be_script=[{"log": _TWIN_LOG}, {"log": twin2_log}],
    )
    # stuck_sig_repeat 拉离: 同 sig 三连 miss 在 r3 先触 stuck 而够不到
    # miss-path——本测试面是探针预算, 关掉 stuck 干扰。
    cell = fixloop(tmp_path, eng, ruleset=_rs(rules, stuck_sig_repeat=99))
    assert cell["verdict"] == "unfixable:syntax"
    probes = [e for e in cell["log"] if "secondary probe" in e]
    assert len(probes) == 2  # noqa: PLR2004 - _SEC_PROBE_MAX 钉值
    # 2 探针 + 1 salvage 兜底 = 3 发 best_effort
    assert [c["best_effort"] for c in eng.calls].count(True) == 3  # noqa: PLR2004
    vias = {a["rule"]: a.get("via") for a in cell["actions"] if "via" in a}
    assert vias == {
        "fix_geom_clash": "secondary:option_clash",
        "fix_missing": "secondary:missing_file",
    }


def test_probe_gated_on_no_pdf(tmp_path: Path) -> None:
    """dirty-pdf miss (有产出): 只给免费候选——halt 单错 log 下零派发零探针。"""
    make_proj(tmp_path, _MAIN)
    eng = _HaltEngine(
        [{"log": _HALT_LOG, "pdf": True}],
        be_script=[{"log": _TWIN_LOG, "pdf": True}],
    )
    cell = fixloop(tmp_path, eng, ruleset=_rs([_FIX_CLASH]))
    # halt 截断轮 (pdf+1 错): n_bang 是下界证不了 错≤max → Guard A
    # (adjudication #10) 封 acceptable 升档, 留 dirty_pdf。
    assert cell["verdict"] == "dirty_pdf"
    assert cell["rounds"][-1]["log_truncated"] is True
    assert not any(c["best_effort"] for c in eng.calls)


def test_primary_hit_never_dispatches(tmp_path: Path) -> None:
    """主错命中既有路径: 孪生在场也不派发——零探针, actions 无 via。"""
    make_proj(tmp_path, _MAIN)
    rule = {
        "id": "fix_syntax",
        "phase": "loop",
        "order": 1,
        "when": {"category": "syntax"},
        "action": {
            "kind": "regex_rewrite",
            "params": {
                "exts": [".tex"],
                "rewrites": [{"pattern": "zap-me", "repl": ""}],
            },
        },
    }
    eng = _HaltEngine([{"log": _TWIN_LOG}, {"log": _CLEAN_LOG, "pdf": True}])
    cell = fixloop(tmp_path, eng, ruleset=_rs([rule]))
    assert cell["verdict"] == "clean"
    act = next(a for a in cell["actions"] if a["rule"] == "fix_syntax")
    assert "via" not in act
    assert not any(c["best_effort"] for c in eng.calls)


def test_secondary_apply_dedupes_on_twin_payload(tmp_path: Path) -> None:
    """``applied`` 键用次级 payload: 同规则不同 twin pay 各火一次。"""
    make_proj(
        tmp_path,
        "\\documentclass{article}\nclash-geometry clash-xcolor\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    twin_xcolor = (
        "! Missing \\begin{document}.\nl.1 x\n"
        + "pad\n" * 10
        + "! LaTeX Error: Option clash for package xcolor.\nl.9 y\n"
    )
    # 双包撞名规则 (无 ctx_suggests 绑名); {payload} 置换让每 pay 改不同词元
    rule = {
        "id": "fix_any_clash",
        "phase": "loop",
        "order": 1,
        "when": {"category": "option_clash", "payload_required": True},
        "action": {
            "kind": "regex_rewrite",
            "params": {
                "exts": [".tex"],
                "rewrites": [{"pattern": "clash-{payload}", "repl": ""}],
            },
        },
    }
    eng = _HaltEngine(
        [{"log": _TWIN_LOG}, {"log": twin_xcolor}, {"log": _CLEAN_LOG, "pdf": True}],
        be_script=[],
    )
    cell = fixloop(tmp_path, eng, ruleset=_rs([rule]))
    assert cell["verdict"] == "clean"
    acts = [a for a in cell["actions"] if a["rule"] == "fix_any_clash"]
    assert len(acts) == 2  # noqa: PLR2004 - geometry + xcolor 各应用一次
    assert all(a["via"].startswith("secondary:option_clash") for a in acts)


def test_secondary_reject_route_propagates(tmp_path: Path) -> None:
    """次级派发命中 reject_route 规则 → 同样落 reject verdict。"""
    make_proj(tmp_path, _MAIN)
    rule = {
        "id": "clash_reject",
        "phase": "loop",
        "order": 1,
        "when": {"category": "option_clash"},
        "action": {
            "kind": "reject_route",
            "params": {"route": "manual", "reason": "clash needs human"},
        },
    }
    eng = _HaltEngine([{"log": _TWIN_LOG}])
    cell = fixloop(tmp_path, eng, ruleset=_rs([rule]))
    assert cell["verdict"] == "reject:clash_reject"
    assert cell["reject_route"] == "manual"
