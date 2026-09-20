"""``run_process`` 内嵌 ``_RunawaySentry`` 活哨——病态 ``\\output`` 暴走的
活杀测试。

签名/阈值与 ``compile.logparse`` 事后判据单源（``_RUNAWAY_VBOX_RX`` ×
30；``[N]`` shipout 页标 10K 第二闸）。越阈排干环抛 ``TimeoutExpired``
→ ``run_process`` 既有 killpg 收树臂 → ``timed_out`` 槽回吐截杀臂名
（``vbox_flood``/``page_flood`` str）+ SIGKILL——``_res_died``/
``runaway_output`` 归因凭记录臂名命中，病态编译不再烧满墙钟
（gr-qc/0104075：96K+ 签名行 / ~97K 页烧 240s 实证）；逐页一条的慢性
vbox 告警（1003.2165：46签名/46页）密度判据放行不杀，密度语义钉见
``test_sentry_rate.py``。
哨件只活在 POSIX 排干环——win32 分片 communicate 与无 stdout 替身
（测试注入面）不装哨，runner 注入缝原样。
"""

from __future__ import annotations

import signal
import sys
from typing import TYPE_CHECKING

import pytest

import texlate.compile.sandbox as sb
from texlate.compile.sandbox import _RunawaySentry, child_env, run_process

if TYPE_CHECKING:
    from pathlib import Path

_SIG = "Overfull \\vbox (6.7pt too high) has occurred while \\output is active []"
_SIG_B = _SIG.encode()

requires_posix = pytest.mark.skipif(
    sys.platform == "win32", reason="排干环活哨仅 POSIX"
)


def _emit_then_sleep(payload: str, sleep_s: int = 60) -> list[str]:
    """``sys.executable -c`` argv：把 payload 写 stdout 后睡到被杀。"""
    prog = (
        f"import sys,time;sys.stdout.write({payload!r});"
        f"sys.stdout.flush();time.sleep({sleep_s})"
    )
    return [sys.executable, "-c", prog]


# ---------------------------------------------------------------- 哨件单元
def test_sentry_vbox_threshold() -> None:
    """29 行不误伤、第 30 行越阈——与 logparse 事后判据同阈值。"""
    s = _RunawaySentry()
    for _ in range(29):
        assert s.feed(_SIG_B + b"\n") is False
    assert s.feed(_SIG_B + b"\n") is True


def test_sentry_split_line_counted() -> None:
    """签名被读片劈开仍计数——留尾拼回未完行，不漏半边命中。"""
    s = _RunawaySentry()
    head, rest = _SIG_B[:40], _SIG_B[40:] + b"\n"
    for _ in range(29):
        assert s.feed(head) is False
        assert s.feed(rest) is False
    assert s.feed(head) is False
    assert s.feed(rest) is True


def test_sentry_page_ceiling() -> None:
    """``[N]`` 页标计数 10K 越阈——vbox 缺席的静默死循环第二闸。"""
    s = _RunawaySentry()
    assert s.feed(b"".join(b"[%d]\n" % i for i in range(9_999))) is False
    assert s.feed(b"[10000]\n") is True


def test_sentry_noise_brackets_no_trip() -> None:
    """偶发大数值括号（``[12345]`` 引用/编号）不积累计数误伤。"""
    s = _RunawaySentry()
    assert s.feed(b"see ref [12345] and [99999] ok\n") is False


def test_sentry_tail_bounded() -> None:
    """无换行洪片留尾有界——长行截断扫头留尾，驻留不随输入膨胀。"""
    s = _RunawaySentry()
    assert s.feed(b"x" * 200_000) is False
    assert len(s._tail) <= sb._SENTRY_KEEP  # noqa: SLF001


def test_sentry_tripped_is_sticky() -> None:
    """越阈后持续报 True——排干环首轮即抛，重复 feed 不翻转。"""
    s = _RunawaySentry()
    assert s.feed((_SIG_B + b"\n") * 40) is True
    assert s.feed(b"quiet\n") is True


# ---------------------------------------------------------------- 真子进程端到端
@pytest.mark.integration
@requires_posix
def test_run_process_livekill_vbox_flood(tmp_path: Path) -> None:
    """40 行 vbox 签名 + 挂死 → 秒级 killpg（非等满 timeout）+ 输出留证。

    输出须仍含签名——事后 ``_is_runaway_output``/``runaway_output`` 归因
    靠它命中（``timed_out`` + 签名文本 → ``runaway_output`` 而非 ``timeout``）。
    """
    from texlate.compile.logparse import (  # noqa: PLC0415  # 与哨件同源
        _is_runaway_output,
    )

    payload = (_SIG + "\n") * 40
    rc, out, sec, to = run_process(
        _emit_then_sleep(payload), cwd=tmp_path, env=child_env(), timeout=60
    )
    assert to == "vbox_flood"  # timed_out 槽回吐截杀臂名 → sentry_reason 归因
    assert rc == -signal.SIGKILL
    assert sec < 30  # noqa: PLR2004 - 越阈即杀；慢机余量下仍远早于 60s 墙钟
    assert _is_runaway_output(out)  # 签名随已读片带出 → runaway_output 归因可命中


@pytest.mark.integration
@requires_posix
def test_run_process_livekill_page_flood(tmp_path: Path) -> None:
    """11K ``[N]`` 页标洪片 → 页标闸提前收树。"""
    payload = "".join(f"[{i}]\n" for i in range(11_000))
    rc, _out, sec, to = run_process(
        _emit_then_sleep(payload), cwd=tmp_path, env=child_env(), timeout=60
    )
    assert to == "page_flood"  # 页洪臂名回吐
    assert rc == -signal.SIGKILL
    assert sec < 30  # noqa: PLR2004 - 越阈即杀，远早于 60s 墙钟


@pytest.mark.integration
@requires_posix
def test_run_process_under_threshold_unaffected(tmp_path: Path) -> None:
    """阈值内签名/页标 + 正常退出 → 不误杀（健康编译的偶发告警档）。"""
    payload = (_SIG + "\n") * 5 + "".join(f"[{i}]" for i in range(100))
    rc, out, _sec, to = run_process(
        [sys.executable, "-c", f"import sys;sys.stdout.write({payload!r})"],
        cwd=tmp_path,
        env=child_env(),
        timeout=30,
    )
    assert to is False
    assert rc == 0
    assert "Overfull" in out


# ---------------------------------------------------------------- 注入面/非 POSIX 路径
def test_run_process_stub_communicate_unguarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无 stdout 替身走 communicate 臂——活哨不装，签名刷屏也不闸。

    runner/替身注入缝原样（哨件只挂 POSIX 排干环）：替身形态下旧
    ``communicate`` 语义逐字节保留，测试注入与 win32 路径不受影响。
    """

    class FakeProc:
        pid = 0xFA19
        returncode = 0

        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def communicate(self, timeout: float | None = None) -> tuple[bytes, None]:
            del timeout
            return (_SIG_B + b"\n") * 40, None

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

        def kill(self) -> None:
            pass

    monkeypatch.setattr(sb.subprocess, "Popen", FakeProc)
    rc, out, _sec, to = run_process(["fake"], cwd=tmp_path, env={}, timeout=5)
    assert to is False  # communicate 臂无哨——签名刷屏不误伤替身
    assert rc == 0
    assert "Overfull" in out
