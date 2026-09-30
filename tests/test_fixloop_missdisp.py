"""missdisp #189 — 缺字族再派发 (per-round cp delta + warn-preempt 勤勉闸)。

misschar3 车道普查双缺陷对账:

- family_not_dispatched (77 cells, 60/77 臂覆盖): error cat 把轮
  次烧完、裁决落 acceptable_pdf/best_effort_pdf 时 warn 族从未拿到
  派发轮 → ``_warn_preempt`` 在派发耗尽点 (site a) 与 loop 退出点
  (site b) 补发一轮 ``warn_missing_char`` 派发。
- fired_late_surface (34 cells): 缺字臂起火**之后**才浮面的新码位
  (``\\bibitem`` 细空格/.bbl 字形/cs_rebind 重音) 被 ``applied`` 键
  死挡 → 起火轮码位记 ``mc_seen`` 消费账, 后浪码位经 ``_mc_delta``
  增量豁免 dedup 再派发; 增量空 → 照常 dedup (终止性)。

全部走实装 ruleset (test_fixloop_missing_char.py 同型)。
"""

from pathlib import Path

from test_fixloop_loop import CLEAN_LOG, MockEngine, SalvageMockEngine, make_proj

from texlate.compile.fixloop import fixloop

MAIN_NEQ = (
    "\\documentclass{article}\n\\usepackage{ctex}\n"
    "\\begin{document}\na ≠ b\n\\end{document}\n"
)

MC_NEQ = "Missing character: There is no ≠ (U+2260) in font cmr7!\n"

UNDEF_LOG = "! Undefined control sequence.\nl.5 \\zzNoSuchCs\n"


def _actions(cell: dict, rule: str) -> list[dict]:
    return [a for a in cell["actions"] if a.get("rule") == rule]


# ---------------------------------------------------------------- warn-preempt
def test_warn_preempt_error_cat_exhaustion(tmp_path: Path) -> None:
    """error-cat 轮烧尽派发 → 裁决前补发 warn 轮 → mcf 落地 ≠ (60/77 覆盖格形)。"""
    log = UNDEF_LOG + MC_NEQ + "Output written on main.pdf (1 page).\n"
    eng = MockEngine([{"log": log, "pdf": True}, {"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path, MAIN_NEQ), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["category"] == "undefined_cs"
    mcf = _actions(cell, "missing_char_fix")
    assert len(mcf) == 1
    assert mcf[0]["via"] == "warn_preempt"
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "a \\ensuremath{\\neq} b" in t


def test_warn_preempt_declines_uncoverable(tmp_path: Path) -> None:
    """残存码位全族不可修 (U+0016 控制符) → preempt 空转留痕, 原裁决照走。"""
    log = (
        UNDEF_LOG
        + "Missing character: There is no ^^V (U+0016) in font cmr10!\n"
        + "Output written on main.pdf (1 page).\n"
    )
    eng = MockEngine([{"log": log, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "acceptable_pdf"  # pdf 在 + err≤3 → 降级照走
    assert not _actions(cell, "missing_char_fix")
    assert any("warn-preempt" in e for e in cell["log"])  # 勤勉闸确跑过


def test_warn_preempt_no_missing_chars_noop(tmp_path: Path) -> None:
    """无缺字轮的 error 耗尽路径 —— 闸不启动, 无 warn-preempt 事件。"""
    eng = MockEngine([{"log": UNDEF_LOG}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "unfixable:undefined_cs"
    assert not any("warn-preempt" in e for e in cell["log"])


def test_warn_preempt_before_salvage(tmp_path: Path) -> None:
    """无 pdf 定败格: preempt 先于 salvage 兜底给族一轮, 修复落源。"""
    log = UNDEF_LOG + MC_NEQ
    eng = SalvageMockEngine([{"log": log}])
    cell = fixloop(make_proj(tmp_path, MAIN_NEQ), eng)
    assert cell["verdict"] == "best_effort_pdf"  # 兜底仍救残页
    mcf = _actions(cell, "missing_char_fix")
    assert len(mcf) == 1
    assert mcf[0]["via"] == "warn_preempt"
    assert mcf[0]["round"] == 1  # 首个耗尽轮即补发, 不等退出点
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ensuremath{\\neq}" in t


# ---------------------------------------------------------------- cp-delta 再派发
def test_misschar_redispatch_on_cp_delta(tmp_path: Path) -> None:
    """起火后浮面的新码位 (fired_late_surface) → 同臂增量豁免 dedup 再火。"""
    main = (
        "\\documentclass{article}\n\\usepackage{ctex}\n"
        "\\begin{document}\na ≠ b 且 a − b\n\\end{document}\n"
    )
    eng = MockEngine(
        [
            {"log": MC_NEQ + "Output written on main.pdf (1 page).\n", "pdf": True},
            {
                "log": "Missing character: There is no − (U+2212) in font "
                "cmr10!\nOutput written on main.pdf (1 page).\n",
                "pdf": True,
            },
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(make_proj(tmp_path, main), eng)
    assert cell["verdict"] == "clean"
    assert len(_actions(cell, "missing_char_fix")) == 2  # noqa: PLR2004 - 两波各火一次
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "a \\ensuremath{\\neq} b 且 a \\ensuremath{-} b" in t


def test_no_redispatch_same_cp_set(tmp_path: Path) -> None:
    """同码位集重现 → 增量空 → dedup 拦截不重火 (终止性钉死)。"""
    log = MC_NEQ + "Output written on main.pdf (1 page).\n"
    eng = MockEngine([{"log": log, "pdf": True}])
    cell = fixloop(make_proj(tmp_path, MAIN_NEQ), eng)
    # r1 warn 轮 mcf 起火; r2 同 log → mcf 码位已消费 → 全族 dedup/decline
    # → dirty_pdf → 退出点 preempt 同判 → acceptable 降级
    assert cell["verdict"] == "acceptable_pdf"
    assert len(cell["rounds"]) == 2  # noqa: PLR2004 - 不再续轮
    assert len(_actions(cell, "missing_char_fix")) == 1


def test_redispatch_reaches_sibling_arm(tmp_path: Path) -> None:
    """新码位越出已火臂覆盖面 → 派发穿透到同族未火臂 (font_fallback)。"""
    main = (
        "\\documentclass{article}\n\\usepackage{ctex}\n"
        "\\begin{document}\na ≠ b Ж\n\\end{document}\n"
    )
    eng = MockEngine(
        [
            {"log": MC_NEQ + "Output written on main.pdf (1 page).\n", "pdf": True},
            {
                "log": "Missing character: There is no Ж (U+0416) in font "
                "[lmroman10-regular]:mapping=tex-text;!\n"
                "Output written on main.pdf (1 page).\n",
                "pdf": True,
            },
            {"log": CLEAN_LOG, "pdf": True},
        ],
        available={"newunicodechar.sty"},
    )
    cell = fixloop(make_proj(tmp_path, main), eng)
    assert cell["verdict"] == "clean"
    # r2: mcf 增量豁免放行评估但 Ж 不在 char_table → decline 穿透;
    # font_fallback (未火) 带 [0x400,0x4FF] 覆盖 0x416 → 起火
    assert len(_actions(cell, "missing_char_fix")) == 1
    assert len(_actions(cell, "font_fallback")) == 1
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\newunicodechar{Ж}" in t
