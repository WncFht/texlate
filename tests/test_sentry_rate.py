"""``_RunawaySentry`` 密度/页洪双臂语义 + ``sentry_reason`` 归因链。

校准对（tmp/lane-pstimeout/report.md 实证）：
- 1003.2165 良性形：逐页 1 条 vbox 告警 × 46 页（46 签名/46 页标）——
  慢性 ~2.7pt 排版溢出，36s 干净编译；旧累计≥30 闸 ~15.6s 误杀。
- gr-qc/0104075 暴走形：~96K 签名 / ~97K 页标 ≈1:1 高密度——页标闸
  10K 截杀（``page_flood``）。
- 纯 ``\\output`` 空转形：签名洪片零页标——vbox 密度闸即杀
  （``vbox_flood``）。

钉：
  a) 逐页良性形任意长度不越阈（含 500 页长文档）；
  b) 空转/页洪越阈且 ``reason`` 臂名正确；
  c) ``sentry_reason`` 链：run_process timed_out 槽 str →
     ``_collect_compile_outputs`` 归位 → judge category=runaway_output →
     fixloop ``_round_cat`` 同优先录因；
  d) 无字段兜底：tail/全文密度判据新语义仍工作。
"""

from __future__ import annotations

import signal
import sys
from typing import TYPE_CHECKING

import pytest

from texlate.compile.engine import CompRes, _collect_compile_outputs
from texlate.compile.fixloop.engine import _round_cat
from texlate.compile.fixloop.logparse import ErrReport, _is_runaway_output
from texlate.compile.fixloop.ruleset import Ruleset
from texlate.compile.judge import judge
from texlate.compile.loginfo import LogInfo
from texlate.compile.sandbox import _RunawaySentry, child_env, run_process

if TYPE_CHECKING:
    from pathlib import Path

_VBOX = "Overfull \\vbox (6.7pt too high) has occurred while \\output is active"
_VBOX_B = _VBOX.encode()

requires_posix = pytest.mark.skipif(
    sys.platform == "win32", reason="排干环活哨仅 POSIX"
)


def _per_page_blob(pages: int) -> bytes:
    """逐页 1 告警 + 1 页标的良性形字节流（1003.2165 形状）。"""
    return b"".join(_VBOX_B + b"\n[%d]\n" % i for i in range(pages))


def _emit_then_sleep(payload: str, sleep_s: int = 60) -> list[str]:
    """``sys.executable -c`` argv：把 payload 写 stdout 后睡到被杀。"""
    prog = (
        f"import sys,time;sys.stdout.write({payload!r});"
        f"sys.stdout.flush();time.sleep({sleep_s})"
    )
    return [sys.executable, "-c", prog]


# ---------------------------------------------------------------- 哨件单元：良性形
def test_1003_shape_no_trip() -> None:
    """pin a-1003.2165：46 签名/46 页标 1:1——旧闸第 30 签名即杀，新语义放行。"""
    s = _RunawaySentry()
    assert s.feed(_per_page_blob(46)) is False
    assert s.reason is None


def test_benign_per_page_never_trips_long() -> None:
    """pin a-长文档：500 页各一告警——密度恒 ~1，任意长度不越阈。"""
    s = _RunawaySentry()
    for chunk in range(5):
        assert s.feed(_per_page_blob(100)) is False, f"chunk {chunk} 误伤"
    assert s.reason is None


def test_benign_split_feed_no_trip() -> None:
    """逐片喂入 1:1 流——行界切分不积累假密度。"""
    s = _RunawaySentry()
    blob = _per_page_blob(60)
    for i in range(0, len(blob), 100):
        assert s.feed(blob[i : i + 100]) is False
    assert s.reason is None


# ---------------------------------------------------------------- 哨件单元：暴走形
def test_vbox_flood_no_pages_trips() -> None:
    """pin b-空转：30+ 签名零页标 → vbox_flood（原死循环最快截杀）。"""
    s = _RunawaySentry()
    assert s.feed((_VBOX_B + b"\n") * 30) is True
    assert s.reason == "vbox_flood"


def test_vbox_density_margin() -> None:
    """密度边界：签名数须 > 4×页标数——30 签名 vs 8 页标放行，vs 7 页标杀。"""
    s8 = _RunawaySentry()
    for i in range(8):
        s8.feed(b"[%d]\n" % i)
    assert s8.feed((_VBOX_B + b"\n") * 30) is False  # 30 ≯ 4×8=32

    s7 = _RunawaySentry()
    for i in range(7):
        s7.feed(b"[%d]\n" % i)
    assert s7.feed((_VBOX_B + b"\n") * 30) is True  # 30 > 4×7=28
    assert s7.reason == "vbox_flood"


def test_grqc_shape_page_flood() -> None:
    """pin b-gr-qc：签名+页标 1:1 同速推进至 10K 页 → page_flood 截杀。"""
    s = _RunawaySentry()
    blob = b"".join(_VBOX_B + b"\n[%d]\n" % i for i in range(11_000))
    assert s.feed(blob) is True
    assert s.reason == "page_flood"


# ---------------------------------------------------------------- 归因链：字段 → judge
def test_collect_outputs_normalizes_reason() -> None:
    """pin c-归位：str 形 timed_out 移入 sentry_reason 并复归 bool。"""
    res = CompRes(engine="xelatex")
    res.timed_out = "vbox_flood"  # 引擎原样拷贝 run_process 的 to 槽
    _collect_compile_outputs(res, ["partial\n"])
    assert res.timed_out is True
    assert res.sentry_reason == "vbox_flood"
    assert res.stdout_tail == "partial\n"


def test_collect_outputs_bool_untouched() -> None:
    """bool 形 timed_out 不受影响——墙钟超时无原因可记。"""
    res = CompRes(engine="xelatex")
    res.timed_out = True
    _collect_compile_outputs(res, ["x\n"])
    assert res.timed_out is True
    assert res.sentry_reason is None


def test_judge_sentry_reason_runaway() -> None:
    """pin c-归因：sentry_reason 置位 → category=runaway_output 免重扫。"""
    res = CompRes(
        engine="xelatex",
        timed_out=True,
        sentry_reason="page_flood",
        log=LogInfo(tail="partial\n"),
    )
    v = judge(res)
    assert v.status == "fail"
    assert v.category == "runaway_output"
    assert "sentry:page_flood" in v.notes
    assert "timeout" in v.reasons


def test_judge_str_timed_out_reason() -> None:
    """未经归位的 str 形 timed_out（手构 CompRes）同样命中记录原因。"""
    res = CompRes(
        engine="xelatex",
        timed_out="vbox_flood",  # type: ignore[arg-type]  # 引擎→res 的途中形态
        log=LogInfo(tail="partial\n"),
    )
    v = judge(res)
    assert v.category == "runaway_output"
    assert "sentry:vbox_flood" in v.notes


# ---------------------------------------------------------------- 归因链：→ fixloop _round_cat
def _mini_ruleset() -> Ruleset:
    """空 taxonomy 的最小 ruleset——``_round_cat`` 只消费 ``rs.taxonomy``。"""
    return Ruleset({"version": 1, "taxonomy": [], "rules": []})


def test_roundcat_sentry_reason_runaway() -> None:
    """pin c-fixloop：sentry_reason 置位 → runaway_output，sentry:<arm> 挂 payload。"""
    res = CompRes(engine="xelatex", timed_out=True, sentry_reason="page_flood")
    rep = ErrReport(raw="partial\n", tail="partial\n")
    cat, pay = _round_cat(_mini_ruleset(), rep, res)
    assert cat == "runaway_output"
    assert pay == "sentry:page_flood"


def test_roundcat_str_timed_out_reason() -> None:
    """未经归位的 str 形 timed_out（引擎→res 途中形态）同样命中记录原因。"""
    res = CompRes(
        engine="xelatex",
        timed_out="vbox_flood",  # type: ignore[arg-type]  # 引擎→res 的途中形态
    )
    cat, pay = _round_cat(_mini_ruleset(), ErrReport(), res)
    assert cat == "runaway_output"
    assert pay == "sentry:vbox_flood"


def test_roundcat_sentry_preempts_error_rep() -> None:
    """录因优先于文本重扫——rep 携真错也直归 runaway_output（与 judge 同语义）。"""
    res = CompRes(engine="xelatex", timed_out=True, sentry_reason="vbox_flood")
    rep = ErrReport(
        first="! Undefined control sequence.",
        n_bang=1,
        raw="! Undefined control sequence.\n",
    )
    cat, pay = _round_cat(_mini_ruleset(), rep, res)
    assert cat == "runaway_output"
    assert pay == "sentry:vbox_flood"


def test_roundcat_no_reason_plain_timeout() -> None:
    """无字段兜底：良性 rep + bool 超时 → 泛 timeout（录因缺席不改旧路）。"""
    benign = "".join(f"{_VBOX}\n[{i}]\n" for i in range(46))
    res = CompRes(engine="xelatex", timed_out=True)
    rep = ErrReport(raw=benign, tail=benign)
    cat, pay = _round_cat(_mini_ruleset(), rep, res)
    assert (cat, pay) == ("timeout", None)


def test_roundcat_no_reason_stdout_tail_runaway() -> None:
    """无字段兜底：rep 良性但 stdout_tail 密签名 → runaway_output（旧补查保留）。"""
    benign = "".join(f"{_VBOX}\n[{i}]\n" for i in range(46))
    res = CompRes(
        engine="xelatex",
        timed_out=True,
        stdout_tail="\n".join([_VBOX] * 40),
    )
    rep = ErrReport(raw=benign, tail=benign)
    cat, pay = _round_cat(_mini_ruleset(), rep, res)
    assert (cat, pay) == ("runaway_output", None)


def test_roundcat_killed_signal_unchanged() -> None:
    """非超时信号死：裸分类 clean → killed（sentry 臂不干扰既有通道）。"""
    res = CompRes(engine="xelatex", killed_signal=13)
    cat, pay = _round_cat(_mini_ruleset(), ErrReport(), res)
    assert (cat, pay) == ("killed", None)


# ---------------------------------------------------------------- 兜底：无字段文本重扫
def test_fallback_benign_shape_timeout() -> None:
    """pin d-良性形：无字段 + 46签名/46页标 tail → 泛 timeout（旧判据误判 runaway）。"""
    benign_tail = "".join(f"{_VBOX}\n[{i}]\n" for i in range(46))
    res = CompRes(
        engine="xelatex",
        timed_out=True,
        log=LogInfo(tail=benign_tail),
    )
    v = judge(res)
    assert v.status == "fail"
    assert v.category == "timeout"


def test_fallback_dense_tail_runaway() -> None:
    """pin d-空转形：无字段 + 尾窗密签名零页标 → 仍 runaway_output。"""
    res = CompRes(
        engine="xelatex",
        timed_out=True,
        log=LogInfo(tail="\n".join([_VBOX] * 40)),
    )
    v = judge(res)
    assert v.category == "runaway_output"


def test_fallback_full_log_page_flood(tmp_path: Path) -> None:
    """pin d-页洪形：tail 窗看不出（1:1 密度）但全文 .log 页标 ≥10K → runaway。"""
    log_file = tmp_path / "main.log"
    log_file.write_text("".join(f"{_VBOX}\n[{i}]\n" for i in range(10_000)))
    res = CompRes(
        engine="xelatex",
        timed_out=True,
        log=LogInfo(tail="partial tail window\n"),
        log_path=log_file,
    )
    v = judge(res)
    assert v.category == "runaway_output"


def test_is_runaway_output_new_semantics() -> None:
    """post-hoc 判据双臂：密度闸 + 页洪闸；良性 1:1 任意长度不判。"""
    assert _is_runaway_output("\n".join([_VBOX] * 40))  # 空转零页标
    assert not _is_runaway_output("\n".join([_VBOX] * 29))
    assert not _is_runaway_output(
        "".join(f"{_VBOX}\n[{i}]\n" for i in range(46))
    )  # 1003.2165 形
    assert not _is_runaway_output(
        "".join(f"{_VBOX}\n[{i}]\n" for i in range(500))
    )  # 长良性文档
    assert _is_runaway_output("".join(f"[{i}]\n" for i in range(10_000)))  # 静默页洪
    assert _is_runaway_output(
        "".join(f"{_VBOX}\n[{i}]\n" for i in range(10_000))
    )  # gr-qc 形


# ---------------------------------------------------------------- 真子进程端到端
@pytest.mark.integration
@requires_posix
def test_run_process_benign_survives(tmp_path: Path) -> None:
    """200 页各一告警 + 正常退出 → 不杀不标（1003.2165 复归路径）。"""
    payload = "".join(f"{_VBOX}\n[{i}]\n" for i in range(200))
    rc, out, _sec, to = run_process(
        [sys.executable, "-c", f"import sys;sys.stdout.write({payload!r})"],
        cwd=tmp_path,
        env=child_env(),
        timeout=30,
    )
    assert to is False
    assert rc == 0
    assert "Overfull" in out


@pytest.mark.integration
@requires_posix
def test_run_process_vbox_flood_reason(tmp_path: Path) -> None:
    """空转签名 + 挂死 → killpg 秒级收树，timed_out 槽回吐 vbox_flood。"""
    rc, out, sec, to = run_process(
        _emit_then_sleep((_VBOX + "\n") * 40),
        cwd=tmp_path,
        env=child_env(),
        timeout=60,
    )
    assert to == "vbox_flood"
    assert rc == -signal.SIGKILL
    assert sec < 30  # noqa: PLR2004 - 越阈即杀，远早于 60s 墙钟
    assert "Overfull" in out


@pytest.mark.integration
@requires_posix
def test_run_process_page_flood_reason(tmp_path: Path) -> None:
    """页标洪片 + 挂死 → timed_out 槽回吐 page_flood。"""
    payload = "".join(f"[{i}]\n" for i in range(11_000))
    rc, _out, sec, to = run_process(
        _emit_then_sleep(payload),
        cwd=tmp_path,
        env=child_env(),
        timeout=60,
    )
    assert to == "page_flood"
    assert rc == -signal.SIGKILL
    assert sec < 30  # noqa: PLR2004 - 越阈即杀，远早于 60s 墙钟


@pytest.mark.integration
@requires_posix
def test_run_process_wallclock_still_bool(tmp_path: Path) -> None:
    """真墙钟超时 timed_out 仍是 bool True——str 槽只载活哨原因。"""
    rc, _out, _sec, to = run_process(
        [sys.executable, "-c", "import time;time.sleep(30)"],
        cwd=tmp_path,
        env=child_env(),
        timeout=2,
    )
    assert to is True
    assert rc == -signal.SIGKILL
