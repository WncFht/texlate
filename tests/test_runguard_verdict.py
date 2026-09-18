"""runguard verdict 钉 —— 死编译(超时/信号杀)否决 clean/acceptable_pdf。

gr-qc/0104075 residdiag 实证 (docs/research/overseer-selfimp.md:296):
240s SIGKILL 编译解析 0 错误 → fixloop_verdict=clean → post-verdict 再烧
240s;同档 ``\\end{document}`` 期 ``\\clearpage`` 死循环刷屏 73,595 行
``Overfull \\vbox while \\output is active`` → ``runaway_output`` 与普通
超时分流 (重跑必再暴走, salvage 排除)。

钉:
  a) timed_out/killed + 0 错 + pdf → 不 clean 也不 acceptable_pdf;
  b) overfull-vbox-output 刷屏 log → runaway_output (阈值 30 成串才判);
  c) 正常干净编译仍 clean (回归)。
"""

from pathlib import Path

from test_fixloop_loop import CLEAN_LOG, MockEngine, make_proj

from texlate.compile.engine import CompRes
from texlate.compile.fixloop import fixloop
from texlate.compile.fixloop.logparse import (
    ErrReport,
    Taxonomy,
    _is_runaway_output,
)
from texlate.compile.judge import judge
from texlate.compile.loginfo import LogInfo, classify_error

_VBOX = "Overfull \\vbox (400.0pt too high) has occurred while \\output is active"
RUNAWAY_LOG = "This is XeTeX, Version 3.141592653\n" + "\n".join([_VBOX] * 40) + "\n"


# ---------------------------------------------------------------- fixloop 环路
def test_timeout_pdf_zero_errors_not_clean(tmp_path: Path) -> None:
    """pin a: 超时编译产 pdf + 0 错 → dirty_pdf (非 clean/acceptable)。"""
    eng = MockEngine([{"log": CLEAN_LOG, "pdf": True, "timed_out": True}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "dirty_pdf"
    assert cell["final_cat"] == "timeout"
    assert cell["rounds"][0]["died"] is True
    assert eng.rounds == 1  # 无 post-verdict 复跑再烧 240s (gr-qc/0104075)


def test_runaway_output_pdf_not_clean(tmp_path: Path) -> None:
    """pin b: vbox 刷屏 + 超时 + pdf → dirty_pdf, cat=runaway_output。"""
    eng = MockEngine([{"log": RUNAWAY_LOG, "pdf": True, "timed_out": True}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "dirty_pdf"
    assert cell["final_cat"] == "runaway_output"
    assert cell["rounds"][0]["category"] == "runaway_output"


def test_runaway_output_no_pdf_no_salvage(tmp_path: Path) -> None:
    """runaway_output 进 salvage 排除臂——重跑必再暴走, 不烧兜底轮。"""
    eng = MockEngine([{"log": RUNAWAY_LOG, "timed_out": True}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "unfixable:runaway_output"
    assert all(not r.get("salvage") for r in cell["rounds"])
    assert eng.rounds == 1


def test_killed_signal_pdf_not_clean(tmp_path: Path) -> None:
    """信号杀(非超时) + pdf + 0 错 → dirty_pdf, cat=killed。"""
    eng = MockEngine([{"log": CLEAN_LOG, "pdf": True, "killed_signal": 9}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "dirty_pdf"
    assert cell["final_cat"] == "killed"
    # 一轮定判 dirty_pdf 即破——无第二轮、无 salvage（eng.rounds 含 pass-1
    # 探测+finalize 两次调用，被杀编译非超时不免 pass-2，故 != 1 属正常）。
    assert len(cell["rounds"]) == 1
    assert all(not r.get("salvage") for r in cell["rounds"])


def test_killed_signal_runaway_log(tmp_path: Path) -> None:
    """信号杀 + vbox 刷屏 → runaway_output (killed 否决位先查暴走签名)。"""
    eng = MockEngine([{"log": RUNAWAY_LOG, "pdf": True, "killed_signal": 9}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["final_cat"] == "runaway_output"
    assert cell["verdict"] == "dirty_pdf"


def test_killed_signal_no_pdf_salvage_fires(tmp_path: Path) -> None:
    """unfixable:killed 不进排除臂——信号死可非定败, salvage 通道保留。"""
    eng = MockEngine([{"log": "partial\n", "killed_signal": 9}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "unfixable:killed"
    assert cell["rounds"][-1].get("salvage") is True
    assert len(cell["rounds"]) == 2  # noqa: PLR2004 - 正式 1 轮 + salvage 1 轮


def test_killed_with_real_error_keeps_taxonomy(tmp_path: Path) -> None:
    """被杀轮携真错误行 → 分类仍走 taxonomy (killed 只否决 clean)。"""
    eng = MockEngine(
        [{"log": "! LaTeX Error: File `foo.sty' not found.\n", "killed_signal": 13}]
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["rounds"][0]["category"] == "missing_file"
    assert cell["rounds"][0]["payload"] == "foo.sty"
    assert cell["verdict"] != "clean"


def test_normal_clean_still_clean(tmp_path: Path) -> None:
    """pin c: 正常干净编译 → clean, died=False。"""
    eng = MockEngine([{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["died"] is False


# ---------------------------------------------------------------- 单元面
def test_is_runaway_output_threshold() -> None:
    """阈值 30: 健康档偶发告警不判, 病态刷屏成串即判。"""
    assert not _is_runaway_output("\n".join([_VBOX] * 29))
    assert _is_runaway_output("\n".join([_VBOX] * 30))
    assert not _is_runaway_output(CLEAN_LOG)


def test_taxonomy_timed_out_split() -> None:
    """Taxonomy.classify timed_out 短路: 刷屏 → runaway_output, 否则 timeout。"""
    tax = Taxonomy([])
    run = ErrReport(raw=RUNAWAY_LOG)
    assert tax.classify(run, timed_out=True) == ("runaway_output", None)
    plain = ErrReport(raw="partial output\n")
    assert tax.classify(plain, timed_out=True) == ("timeout", None)
    # tail-only rep (judge/classify_error 面): 尾 30 行全签名同样判暴走
    tail_only = ErrReport(tail="\n".join([_VBOX] * 30))
    assert tax.classify(tail_only, timed_out=True) == ("runaway_output", None)


def test_classify_error_timed_out() -> None:
    """loginfo 适配: 真 ruleset 装载下 timed_out 细分同源。"""
    cat, _ = classify_error(None, None, "\n".join([_VBOX] * 35), timed_out=True)
    assert cat == "runaway_output"
    cat, _ = classify_error(None, None, "partial\n", timed_out=True)
    assert cat == "timeout"


def test_judge_timeout_categories() -> None:
    """judge() 超时早退: fail + runaway_output/timeout 细分写 category。"""
    res = CompRes(
        engine="xelatex",
        timed_out=True,
        log=LogInfo(tail="\n".join([_VBOX] * 35)),
    )
    v = judge(res)
    assert v.status == "fail"
    assert v.category == "runaway_output"
    assert "timeout" in v.reasons

    res2 = CompRes(engine="xelatex", timed_out=True, log=LogInfo(tail="partial\n"))
    v2 = judge(res2)
    assert v2.status == "fail"
    assert v2.category == "timeout"
