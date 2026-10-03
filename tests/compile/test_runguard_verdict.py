"""runguard verdict 钉 —— 死编译 (超时/信号杀) 否决 clean/acceptable_pdf。

gr-qc/0104075 residdiag 实证
(``git show 5ebc9797^:docs/research/overseer-selfimp.md`` :300):
240s SIGKILL 编译解析 0 错误 → fixloop_verdict=clean → post-verdict 再烧
240s;同档 ``\\end{document}`` 期 ``\\clearpage`` 死循环刷屏 73,595 行
``Overfull \\vbox while \\output is active`` → ``runaway_output`` 与普通
超时分流 (重跑必再暴走，salvage 排除)。

钉：
  a) timed_out/killed + 0 错 + pdf → 不 clean 也不 acceptable_pdf;
  b) overfull-vbox-output 刷屏 log → runaway_output (阈值 30 成串才判);
  c) 正常干净编译仍 clean (回归)。
"""

from pathlib import Path

from _fixloopkit import CLEAN_LOG, MockEngine, make_proj

from texlate.compile.engine import CompRes
from texlate.compile.fixloop import fixloop
from texlate.compile.judge import judge
from texlate.compile.loginfo import LogInfo, classify_error
from texlate.compile.logparse import (
    ErrReport,
    Taxonomy,
    _is_runaway_output,
)

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
    """runaway_output 进 salvage 排除臂——重跑必再暴走，不烧兜底轮。"""
    eng = MockEngine([{"log": RUNAWAY_LOG, "timed_out": True}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "unfixable:runaway_output"
    assert all(not r.get("salvage") for r in cell["rounds"])
    assert eng.rounds == 1


CAP_STACK_LOG = (
    "! TeX capacity exceeded, sorry [input stack size=10000].\n"
    "\\@nomath ->\\if@nomath\n"
    "                  \\else \\expandafter \\@firstofone \\fi \n"
    "l.190 \\section{intro}\n"
    "If you really absolutely need more capacity,\n"
    "you can ask a wizard to enlarge me.\n"
)


def test_input_stack_no_pdf_no_salvage(tmp_path: Path) -> None:
    """unfixable:input_stack 进 salvage 排除臂——上游递归帧定败，不烧兜底轮。

    cat ``input_stack`` 只由 capacity ``input_stack|<cs>`` 重路由产出
    (``_CAP_UPSTREAM_RECURSION_CS`` 名单，``\\@nomath`` 内核守卫帧在
    列), 全属 TeX-exec 宏递归——同输入同炸，nonstopmode 救不回。
    """
    eng = MockEngine([{"log": CAP_STACK_LOG}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "unfixable:input_stack"
    assert all(not r.get("salvage") for r in cell["rounds"])
    assert eng.rounds == 1


def test_killed_signal_pdf_not_clean(tmp_path: Path) -> None:
    """信号杀 (非超时) + pdf + 0 错 → dirty_pdf, cat=killed。"""
    eng = MockEngine([{"log": CLEAN_LOG, "pdf": True, "killed_signal": 9}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "dirty_pdf"
    assert cell["final_cat"] == "killed"
    # 一轮定判 dirty_pdf 即破——无第二轮、无 salvage（eng.rounds 含 pass-1
    # 探测+finalize 两次调用，被杀编译非超时不免 pass-2，故 != 1 属正常）。
    assert len(cell["rounds"]) == 1
    assert all(not r.get("salvage") for r in cell["rounds"])


def test_killed_signal_runaway_log(tmp_path: Path) -> None:
    """信号杀 + vbox 刷屏 → warn_overfull：warnings 税目先于 killed 否决位
    收编 (否决臂只改写 clean/None)；活哨记录值/超时臂才直归
    runaway_output (overfull_vbox → warn_overfull 别名面)。"""
    eng = MockEngine([{"log": RUNAWAY_LOG, "pdf": True, "killed_signal": 9}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["final_cat"] == "warn_overfull"
    assert cell["verdict"] == "dirty_pdf"


def test_killed_signal_no_pdf_salvage_fires(tmp_path: Path) -> None:
    """unfixable:killed 不进排除臂——信号死可非定败，salvage 通道保留。"""
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


# ------------------------------------------------------- driver fatal (1907.00277)
XFATAL_TAIL = (
    "shipout progress\n"
    "xdvipdfmx:fatal: pdf_link_obj(): passed invalid object\n"
    "No output PDF file written.\n"
)


def test_driver_fatal_pdf_not_clean(tmp_path: Path) -> None:
    """1907.00277 形：rc=1 非信号退出 + 残 pdf + fatal 只走 stdout_tail。

    xdvipdfmx fatal 不进 .log——``_report_of`` 把 ``*: fatal:`` 归一成
    ``!`` 行使签名对 dispatch 可见 (category 押 ``other`` 是
    pdf_asset_sanitize ``when: category: other`` 的派发面), 精确归因
    载 ``driver_fatal`` 字段; 驱动死与被杀同属产出未证 → died 置位。
    """
    eng = MockEngine([{"log": CLEAN_LOG, "pdf": True, "tail": XFATAL_TAIL, "rc": 1}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "dirty_pdf"
    assert cell["final_cat"] == "other"
    assert cell["rounds"][0]["category"] == "other"
    assert cell["rounds"][0]["died"] is True
    assert "pdf_link_obj" in cell["rounds"][0]["driver_fatal"]
    assert cell["verdict"] != "acceptable_pdf"  # died 末轮禁升


def test_driver_fatal_no_pdf_unfixable(tmp_path: Path) -> None:
    """驱动 fatal + 无 pdf → unfixable:other + driver_fatal 归因; 定败不烧 salvage 轮。"""
    eng = MockEngine([{"log": CLEAN_LOG, "tail": XFATAL_TAIL, "rc": 1}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "unfixable:other"
    assert cell["final_cat"] == "other"
    assert "pdf_link_obj" in cell["rounds"][0]["driver_fatal"]
    assert eng.rounds == 1
    assert all(not r.get("salvage") for r in cell["rounds"])


def test_driver_fatal_rc0_noise_acceptable(tmp_path: Path) -> None:
    """阴性钉：rc=0 出 pdf 的 ``fatal:`` 字面行——非驱动死，died 不置位。

    bang 化 (_report_of 归一) 保守压 clean → dirty_pdf, 但 died=False
    使 acceptable_pdf 升级不封——孙件噪声不伪报驱动死。
    """
    eng = MockEngine([{"log": CLEAN_LOG, "pdf": True, "tail": XFATAL_TAIL, "rc": 0}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "acceptable_pdf"
    assert cell["rounds"][0]["died"] is False
    assert cell["rounds"][0]["driver_fatal"] is None


def test_driver_warning_not_fatal_still_clean(tmp_path: Path) -> None:
    """``: fatal:`` 字面锚——``xdvipdfmx:warning:`` 非致命行不误否。"""
    eng = MockEngine(
        [{"log": CLEAN_LOG, "pdf": True, "tail": "xdvipdfmx:warning: stray\n", "rc": 0}]
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"


def test_judge_driver_fatal_pdf_partial(tmp_path: Path) -> None:
    """judge 面：rc=1 + fatal tail + 残 pdf → partial (非 clean), cat 归因。"""
    pdf = tmp_path / "main.pdf"
    pdf.write_bytes(b"%PDF-partial")
    res = CompRes(
        engine="xelatex",
        rc=1,
        pdf=pdf,
        pdf_bytes=pdf.stat().st_size,
        log=LogInfo(),
        stdout_tail=XFATAL_TAIL,
    )
    v = judge(res)
    assert v.status == "partial"
    assert v.category == "driver_fatal"
    assert any(r.startswith("driver_fatal:xdvipdfmx") for r in v.reasons)


def test_judge_driver_fatal_no_pdf() -> None:
    """judge 面：fatal + 无 pdf → fail, driver_fatal 为近因类别。"""
    res = CompRes(engine="xelatex", rc=1, log=LogInfo(), stdout_tail=XFATAL_TAIL)
    v = judge(res)
    assert v.status == "fail"
    assert v.category == "driver_fatal"
    assert "no_pdf" in v.reasons


def test_judge_driver_fatal_rc0_clean(tmp_path: Path) -> None:
    """judge 阴性钉：rc=0 + pdf + fatal 字面行 → clean (孙件噪声不采)。"""
    pdf = tmp_path / "main.pdf"
    pdf.write_bytes(b"%PDF-ok")
    res = CompRes(
        engine="xelatex",
        rc=0,
        pdf=pdf,
        pdf_bytes=pdf.stat().st_size,
        log=LogInfo(),
        stdout_tail=XFATAL_TAIL,
    )
    assert judge(res).status == "clean"


# ---------------------------------------------------------------- 单元面
def test_is_runaway_output_threshold() -> None:
    """阈值 30: 健康档偶发告警不判，病态刷屏成串即判。"""
    assert not _is_runaway_output("\n".join([_VBOX] * 29))
    assert _is_runaway_output("\n".join([_VBOX] * 30))
    assert not _is_runaway_output(CLEAN_LOG)


def test_taxonomy_timed_out_split() -> None:
    """Taxonomy.classify timed_out 短路：刷屏 → runaway_output, 否则 timeout。"""
    tax = Taxonomy([])
    run = ErrReport(raw=RUNAWAY_LOG)
    assert tax.classify(run, timed_out=True) == ("runaway_output", None)
    plain = ErrReport(raw="partial output\n")
    assert tax.classify(plain, timed_out=True) == ("timeout", None)
    # tail-only rep (judge/classify_error 面): 尾 30 行全签名同样判暴走
    tail_only = ErrReport(tail="\n".join([_VBOX] * 30))
    assert tax.classify(tail_only, timed_out=True) == ("runaway_output", None)


def test_classify_error_timed_out() -> None:
    """loginfo 适配：真 ruleset 装载下 timed_out 细分同源。"""
    cat, _ = classify_error(None, None, "\n".join([_VBOX] * 35), timed_out=True)
    assert cat == "runaway_output"
    cat, _ = classify_error(None, None, "partial\n", timed_out=True)
    assert cat == "timeout"


def test_judge_timeout_categories() -> None:
    """judge() 超时早退：fail + runaway_output/timeout 细分写 category。"""
    res = CompRes(
        engine="xelatex",
        timed_out=True,
        log=LogInfo(tail="\n".join([_VBOX] * 35)),
    )
    v = judge(res)
    assert v.status == "fail"
    assert v.category == "runaway_output"


def test_judge_livekill_stdout_tail_fallback() -> None:
    """活哨早杀形：.log 截在签名刷屏前，stdout_tail 携签名 → 仍 runaway_output。"""
    res = CompRes(
        engine="xelatex",
        timed_out=True,
        log=LogInfo(tail="partial output\n"),
        stdout_tail="\n".join([_VBOX] * 35),
    )
    v = judge(res)
    assert v.status == "fail"
    assert v.category == "runaway_output"
    # stdout_tail 也无签名 → 泛 timeout 不变
    res2 = CompRes(
        engine="xelatex",
        timed_out=True,
        log=LogInfo(tail="partial output\n"),
        stdout_tail="some normal lines\n",
    )
    v2 = judge(res2)
    assert v2.category == "timeout"
    assert "timeout" in v2.reasons  # res2 的 verdict——非上方 runaway 的 v

    res2 = CompRes(engine="xelatex", timed_out=True, log=LogInfo(tail="partial\n"))
    v2 = judge(res2)
    assert v2.status == "fail"
    assert v2.category == "timeout"
