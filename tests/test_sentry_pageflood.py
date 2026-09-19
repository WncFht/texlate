"""``page_flood`` 单调包络语义钉——非序 ``[N]`` 噪声不误杀，真 shipout 洪仍截杀。

killsem2 census 开放缺口（tmp/lane-killsem2/census.md）：
``_RUNAWAY_PAGE_RX = r"\\[\\d+\\]"`` 旧纯计数——收敛文档打印 >10K 非
shipout 方括数字（索引/引用/``\\typeout`` 阵列）会假触哨件 SIGKILL。
真 shipout 序号只增不减（2609.19748 实测 9623 标记全序、2608.09867
19084 标记全序），故计数改**单调包络**：仅 ``n >= 已计最大值`` 的
页标入计；非序噪声至多贡献 ~ln(n) 个左向右极大值。

钉：
  a) >10K 非序方括数字流不触 page_flood（假触场景复归，双侧面）；
  b) 序贯 ``[0]..[N]`` shipout 洪仍越阈截杀（含分片喂入、行内多标记
     ——TeX ``max_print_line`` 折行把页标嵌行内，2609.19748 实测
     ``] [2] [3]`` 形，行锚语义会漏计故不取）；
  c) 冻结计数器暴走 ``[1][1]…``（同页号无限 shipout）非减包络仍计；
  d) 洪中夹小值游离括号：包络跳过不遮洪（相对 run-reset 语义的
     优势——run 语义下单个 stray 会截断连贯段）；
  e) 良性 pagenumbering 复位 ``[1..400][1..600]`` 不超阈；
  f) vbox 密度分母**不走**包络仍用原始计数——噪声撑分母是豁免
     方向（杀开关保守），复位档真 shipout 不漏计（vbox 臂零行为变
     化）；
  g) 洪前已分类首错随归因落记录：judge ``error_cats``/``error_pay``
     + fixloop ``_round_cat`` payload 追加 ``|<cat>``。
"""

from __future__ import annotations

import signal
import sys
from typing import TYPE_CHECKING

import pytest

from texlate.compile.engine import CompRes
from texlate.compile.fixloop.engine import _round_cat
from texlate.compile.fixloop.ruleset import Ruleset
from texlate.compile.judge import judge
from texlate.compile.loginfo import LogInfo
from texlate.compile.logparse import ErrReport, _is_runaway_output
from texlate.compile.sandbox import _RunawaySentry, child_env, run_process

if TYPE_CHECKING:
    from pathlib import Path

_VBOX = "Overfull \\vbox (6.7pt too high) has occurred while \\output is active"
_VBOX_B = _VBOX.encode()

requires_posix = pytest.mark.skipif(
    sys.platform == "win32", reason="排干环活哨仅 POSIX"
)


def _descending_blob(blocks: int = 2) -> bytes:
    """非序方括数字流：``[9999]..[0]`` 降序块 ×N——包络每块只计 1。"""
    ramp = b" ".join(b"[%d]" % (9999 - j) for j in range(10_000))
    return b"\n".join([ramp] * blocks) + b"\n"


# ---------------------------------------------------------------- 哨件单元：假触场景
def test_nonsequential_brackets_no_trip() -> None:
    """pin a：20K 降序方括数字（非 shipout）——包络计数=2，不触 page_flood。"""
    s = _RunawaySentry()
    assert s.feed(_descending_blob(2)) is False
    assert s.reason is None


def test_nonsequential_split_feed_no_trip() -> None:
    """分片喂入的乱序流——行界拼回后包络语义不变，不误杀。"""
    s = _RunawaySentry()
    blob = _descending_blob(2)
    for i in range(0, len(blob), 997):
        assert s.feed(blob[i : i + 997]) is False
    assert s.reason is None


def test_descending_ramp_posthoc_clean() -> None:
    """pin a-事后：``_is_runaway_output`` 同包络语义——降序流不判暴走。"""
    assert not _is_runaway_output(_descending_blob(2).decode())


# ---------------------------------------------------------------- 哨件单元：真洪仍杀
def test_sequential_flood_still_trips() -> None:
    """pin b：序贯 ``[0]..[10999]`` → page_flood（旧语义主路径守恒）。"""
    s = _RunawaySentry()
    blob = b"".join(b"[%d]\n" % i for i in range(11_000))
    assert s.feed(blob) is True
    assert s.reason == "page_flood"


def test_inline_marks_flood_trips() -> None:
    """pin b-真形：页标嵌行内一行多个（``] [2] [3]`` 折行形）仍截杀。"""
    s = _RunawaySentry()
    blob = b""
    for i in range(0, 11_000, 7):
        grp = b" ".join(b"[%d]" % j for j in range(i, min(i + 7, 11_000)))
        blob += b"typeset " + grp + b"\n"
    for i in range(0, len(blob), 4096):
        s.feed(blob[i : i + 4096])
    assert s.tripped is True
    assert s.reason == "page_flood"


def test_frozen_counter_flood_trips() -> None:
    """pin c：同页号无限 shipout ``[1][1]…``——非减包络入计仍杀。"""
    s = _RunawaySentry()
    assert s.feed(b"[1] " * 10_500 + b"\n") is True
    assert s.reason == "page_flood"
    assert _is_runaway_output("[1] " * 10_500)


def test_stray_small_mark_mid_flood_still_trips() -> None:
    """pin d：洪中夹小值游离 ``[3]``——包络跳过且不遮后续页标。"""
    s = _RunawaySentry()
    blob = b"".join(b"[%d]\n" % i for i in range(6_000))
    blob += b"see [3] stray\n"
    blob += b"".join(b"[%d]\n" % i for i in range(6_000, 11_000))
    assert s.feed(blob) is True
    assert s.reason == "page_flood"


# ---------------------------------------------------------------- 哨件单元：良性/密度
def test_pagenumbering_reset_benign() -> None:
    """pin e：``\\pagenumbering`` 复位两段序贯 ``[1..400][1..600]``——
    包络计 ~600（复位段 1..399 跳计），远低于 10K 闸；叠加逐页慢性
    vbox 告警时密度分母走原始计数 1000，30≯4×1000 也不误杀。"""
    s = _RunawaySentry()
    blob = b"".join(b"[%d]\n" % i for i in range(1, 401))
    blob += b"".join(b"[%d]\n" % i for i in range(1, 601))
    assert s.feed(blob) is False
    s2 = _RunawaySentry()
    blob2 = b"".join(_VBOX_B + b"\n[%d]\n" % i for i in range(1, 401)) + b"".join(
        _VBOX_B + b"\n[%d]\n" % i for i in range(1, 601)
    )
    assert s2.feed(blob2) is False
    text = blob.decode()
    assert not _is_runaway_output(text)
    assert not _is_runaway_output(blob2.decode())


def test_vbox_noise_inflates_denominator_safe() -> None:
    """pin f：30 vbox 签名 + 20K 非序噪声——密度分母走原始计数。

    非序噪声撑大分母是**豁免方向**（保守）：杀开关宁漏边际流不误伤；
    真 ``\\output`` 空转暴走签名数以千计（gr-qc ~96K），30 签名级边
    际流本非 vbox 臂目标——包络只收紧 page_flood 闸，密度臂原语义
    零变化。
    """
    s = _RunawaySentry()
    assert s.feed(_descending_blob(2) + (_VBOX_B + b"\n") * 30) is False
    assert s.reason is None


def test_vbox_benign_with_noise_still_safe() -> None:
    """阴性钉：30 签名 + 40 真序贯页标 + 非序噪声——密度 30≤4×40 放行。"""
    s = _RunawaySentry()
    blob = b"".join(b"[%d]\n" % i for i in range(40))
    blob += _descending_blob(2)
    blob += (_VBOX_B + b"\n") * 30
    assert s.feed(blob) is False


# ---------------------------------------------------------------- 洪前错误归因（payload carry）
def test_judge_sentry_preflood_error_cats() -> None:
    """pin g-judge：截杀轮携洪前错误 → ``error_cats``/``error_pay`` 记真凶。

    ``runaway_output`` 是检测态标签——底层可修机理（killsem2 实例：
    2311.04163 洪上游是 undefined_cs）经错误构成字段随 verdict 可查。
    """
    res = CompRes(
        engine="xelatex",
        timed_out=True,
        sentry_reason="page_flood",
        log=LogInfo(
            n_errors=1,
            errors=["! Undefined control sequence."],
            first_error="! Undefined control sequence.",
            error_ctx="! Undefined control sequence.\nl.31 \\arxiv\n",
        ),
    )
    v = judge(res)
    assert v.status == "fail"
    assert v.category == "runaway_output"
    assert "sentry:page_flood" in v.notes
    assert v.error_cats == {"undefined_cs": 1}
    assert v.error_pay == {"undefined_cs": "arxiv"}


def test_judge_sentry_no_errors_cats_empty() -> None:
    """阴性钉：无洪前错误 → ``error_cats`` 保持空，语义不变。"""
    res = CompRes(
        engine="xelatex",
        timed_out=True,
        sentry_reason="page_flood",
        log=LogInfo(tail="partial\n"),
    )
    v = judge(res)
    assert v.category == "runaway_output"
    assert v.error_cats == {}


def test_roundcat_sentry_preflood_cat_appended() -> None:
    """pin g-fixloop：洪前可分类首错 → payload ``sentry:<arm>|<cat>``。"""
    rs = Ruleset.load()
    rep = ErrReport(
        first="! LaTeX Error: File `foo.sty' not found.",
        ctx="l.5 \\usepackage{foo}",
    )
    res = CompRes(engine="xelatex", timed_out=True, sentry_reason="page_flood")
    cat, pay = _round_cat(rs, rep, res)
    assert cat == "runaway_output"
    assert pay == "sentry:page_flood|missing_file"


def test_roundcat_sentry_no_first_unchanged() -> None:
    """阴性钉：无首错/不可分类 → payload 仍裸 ``sentry:<arm>``。"""
    rs = Ruleset.load()
    res = CompRes(engine="xelatex", timed_out=True, sentry_reason="vbox_flood")
    cat, pay = _round_cat(rs, ErrReport(), res)
    assert (cat, pay) == ("runaway_output", "sentry:vbox_flood")


# ---------------------------------------------------------------- 真子进程端到端
@pytest.mark.integration
@requires_posix
def test_run_process_nonsequential_spam_survives(tmp_path: Path) -> None:
    """20K 非序方括数字 + 正常退出 → rc=0 不截杀（假触场景端到端复归）。

    旧纯计数在此输入必越阈 SIGKILL——包络语义下健康输出流不再误伤。
    """
    prog = (
        "import sys;"
        "ramp=' '.join('[%d]' % (9999-j) for j in range(10_000));"
        "sys.stdout.write(ramp+'\\n'+ramp+'\\n')"
    )
    rc, _out, _sec, to = run_process(
        [sys.executable, "-c", prog],
        cwd=tmp_path,
        env=child_env(),
        timeout=30,
    )
    assert to is False
    assert rc == 0


@pytest.mark.integration
@requires_posix
def test_run_process_frozen_counter_killed(tmp_path: Path) -> None:
    """同页号 shipout 洪 + 挂死 → killpg 收树 + ``page_flood`` 回吐。"""
    rc, _out, sec, to = run_process(
        [
            sys.executable,
            "-c",
            (
                "import sys,time;sys.stdout.write('[1]\\n' * 10500);"
                "sys.stdout.flush();time.sleep(60)"
            ),
        ],
        cwd=tmp_path,
        env=child_env(),
        timeout=60,
    )
    assert to == "page_flood"
    assert rc == -signal.SIGKILL
    assert sec < 30  # noqa: PLR2004 - 越阈即杀，远早于 60s 墙钟
