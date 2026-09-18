r"""子进程 runner：Popen 管线 + 单调钟排干环 + 超时 killpg + rlimits + 暴走活哨。

自 ``sandbox.py`` 出叶——本叶只管执行件；OS 沙箱策略面（env 白名单 /
sandbox-exec / bwrap 挂载与能力探测）留 ``sandbox.py``，runner 名经其
``from .proc import`` 再出口，旧 ``sandbox.X`` 路径原样可 import。

- 进程组隔离（`start_new_session`）+ `killpg` 杀整棵进程树；非 POSIX 降级
  为 `proc.kill()`。子进程输出封顶 8MB 防内存炸。
- POSIX 主流排干环（``_drain_bounded``）：单调钟 deadline + 子进程死透即
  收——孙进程握管/死锁（xelatex↔xdvipdfmx 形）、墙钟拨回都不再挂死；
  win32 selectors 看不了管道 fd，退回 ``_communicate_cancellable`` 分片
  ``communicate``。``should_cancel`` 旗标依 ``_CANCEL_POLL_S`` 分片响应。
- POSIX rlimits 纵深：exec 前经 preexec_fn 装 AS/NOFILE/CPU 软帽——失控
  TeX 吃不光宿主内存与 fd，自旋进程墙钟之外还有 SIGXCPU 第二闸。
- ``\output`` 暴走活哨（``_RunawaySentry``）：排干环逐片喂签名计数
  （logparse 事后判据同 regex 同阈值 + ``[N]`` 页标计数闸），越阈抛
  ``TimeoutExpired`` 走既有 killpg 收树臂——病态编译不再烧满墙钟
  （gr-qc/0104075：96K+ 签名行 / ~97K 页烧 240s 实证），``timed_out``
  置位让 ``runaway_output``/``timeout`` 归因原样命中。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Final

if sys.platform != "win32":
    import resource
else:
    resource = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

#: 子进程地址空间软帽（字节）——TeX 正常编译峰值 <1GiB，4GiB 只拦失控
#: 分配；macOS 不强制 RLIMIT_AS，设之无害。
_RLIMIT_AS_BYTES = 4 * 1024**3
#: 文件描述符软帽——kpathsea 正常并发 fd 峰值远低于 1024。
_RLIMIT_NOFILE = 1024
#: CPU 秒软帽下限：cap = max(2×墙钟, 本下限)——timeout/killpg 仍是主杀器，
#: CPU 帽兜「100% 自旋但墙钟面失守」的逃逸（SIGXCPU → engine 信号归因
#: 照常吃）；短 timeout 探针调用也拿 600s 地板，永不误杀。
_RLIMIT_CPU_FLOOR = 600


def _cap_rlimit(what: int, cap: int) -> None:
    """把 *what* 软帽降到 ``cap``（已低于 cap 则不动）；hard 保持原值。

    TeX 系进程从不自行 setrlimit——降 hard 是永久自残且无收益。单件失败
    （平台缺该 limit / 容器拒设）静默跳过：rlimits 是纵深兜底不是主闸。
    """
    try:
        soft, hard = resource.getrlimit(what)
    except (OSError, ValueError):
        return
    if soft == resource.RLIM_INFINITY or soft > cap:
        with contextlib.suppress(OSError, ValueError):
            resource.setrlimit(what, (cap, hard))


def _rlimit_preexec(timeout: float) -> Callable[[], None] | None:
    """返回 Popen ``preexec_fn``：exec 前装 AS/NOFILE/CPU 软帽；非 POSIX → None。"""
    if resource is None:
        return None
    caps = {resource.RLIMIT_CPU: max(2 * int(timeout), _RLIMIT_CPU_FLOOR)}
    if hasattr(resource, "RLIMIT_AS"):
        caps[resource.RLIMIT_AS] = _RLIMIT_AS_BYTES
    if hasattr(resource, "RLIMIT_NOFILE"):
        caps[resource.RLIMIT_NOFILE] = _RLIMIT_NOFILE

    def _install() -> None:
        for what, cap in caps.items():
            _cap_rlimit(what, cap)

    return _install


#: ``should_cancel`` 轮询步长（server.babeldoc ``_POLL_S`` 同口径）——
#: cancel 置位到进程树死透收敛在亚秒级
_CANCEL_POLL_S = 0.5

#: ``_drain_bounded`` 的读片大小与驻留上界倍率——输出封顶 headroom 之外
#: 不再放大驻留（runaway xelatex 日志 GB 级也只留尾部窗口）。
_READ_CHUNK = 65536

#: 活哨行界扫描的留尾上限——签名永不跨 ``\n``（regex 的 ``[^\n]*`` 界），
#: 只留最后一个未完行；max_print_line=10000 保真行有界，更长的无换行
#: 洪片按病态截断（签名海量重复，切断处漏一个不计）。
_SENTRY_TAIL_CAP: Final = 65536
#: 洪片截断的留尾——长过任一签名（vbox 行 ~85B、``[N]`` 页标数 B），
#: 切断点的签名续段仍能拼回计数。
_SENTRY_KEEP: Final = 4096
#: 页标记闸（``[N]`` shipout 计数）——健康论文页数百级以下；gr-qc/0104075
#: 暴走 ~240s 产 ~97K 页（~400 页/秒），10K 闸约 25s 截杀、距正常档两个
#: 数量级。vbox 签名缺席的静默死循环由本闸兜住；计数制（非 max 值）免
#: 被文本偶发的大数值括号（``[12345]`` 引用/编号）单发误伤。
_RUNAWAY_PAGE_MAX: Final = 10_000
_PAGE_MARK_RX: Final = re.compile(rb"\[\d+\]")


class _RunawaySentry:
    r"""``\output`` 暴走活哨：drain 流片喂入、行界扫描，签名越阈即报。

    与 ``fixloop.logparse`` 事后判据同 regex 同阈值——``_RUNAWAY_VBOX_RX``
    × ``_RUNAWAY_VBOX_MIN``（str 模式源 ``encode`` 成 bytes 编译形，定义
    仍单源）；越阈由排干环抛 ``TimeoutExpired`` 走 ``run_process`` 既有
    killpg 收树臂，``timed_out=True`` 让 ``runaway_output``/``timeout``
    归因原样命中——病态编译烧满墙钟前即收。
    """

    def __init__(self) -> None:
        from texlate.compile.fixloop.logparse import (  # noqa: PLC0415  # 延迟: fixloop/__init__ 链重(cases→fcntl 平台门)，运行期首用才拉
            _RUNAWAY_VBOX_MIN,
            _RUNAWAY_VBOX_RX,
        )

        self._vbox_rx = re.compile(_RUNAWAY_VBOX_RX.pattern.encode())
        self._vbox_min = _RUNAWAY_VBOX_MIN
        self._vbox_hits = 0
        self._page_marks = 0
        self._tail = b""
        self.tripped = False

    def feed(self, data: bytes) -> bool:
        """喂一片 stdout；vbox 签名/``[N]`` 页标任一越阈返 True。"""
        if self.tripped:
            return True
        buf = self._tail + data
        cut = buf.rfind(b"\n")
        if cut >= 0:
            seg, tail = buf[:cut], buf[cut + 1 :]
        else:
            seg, tail = b"", buf
        if len(tail) > _SENTRY_TAIL_CAP:
            seg += tail[:-_SENTRY_KEEP]
            tail = tail[-_SENTRY_KEEP:]
        self._tail = tail
        if seg:
            self._scan(seg)
        return self.tripped

    def _scan(self, seg: bytes) -> None:
        if self._vbox_hits < self._vbox_min:
            self._vbox_hits += len(self._vbox_rx.findall(seg))
        self._page_marks += len(_PAGE_MARK_RX.findall(seg))
        if self._vbox_hits >= self._vbox_min or self._page_marks >= _RUNAWAY_PAGE_MAX:
            self.tripped = True


def _drain_nonblocking(fd: int, chunks: list[bytes]) -> None:
    """子进程死透后非阻塞排干管道余量——孙进程握写端也不会再阻塞。"""
    try:
        os.set_blocking(fd, False)
    except OSError:
        return
    while True:
        try:
            data = os.read(fd, _READ_CHUNK)
        except (BlockingIOError, OSError):
            return
        if not data:
            return
        chunks.append(data)


def _pump_once(
    sel: selectors.BaseSelector, fd: int, wait_s: float
) -> tuple[bytes, bool]:
    """一轮 select+read：返回 ``(本轮数据, 是否 EOF)``；EOF 顺手 unregister。"""
    buf = bytearray()
    eof = False
    for _key, _mask in sel.select(wait_s):
        try:
            data = os.read(fd, _READ_CHUNK)
        except OSError:
            data = b""
        if data:
            buf += data
        else:
            eof = True
            with contextlib.suppress(KeyError, ValueError, OSError):
                sel.unregister(fd)
    return bytes(buf), eof


def _drain_bounded(  # noqa: PLR0913, PLR0917 -- 排干环参数面集中声明
    proc: subprocess.Popen[bytes],
    cmd: list[str],
    timeout: float,
    out_cap: int,
    should_cancel: Callable[[], bool] | None = None,
    sentry: _RunawaySentry | None = None,
) -> bytes:
    r"""POSIX 主流排干环：单调钟 deadline + 子进程死透即收——替 ``communicate``。

    ``communicate`` 把「读完」定义为管道 EOF——孙进程继承写端不死则 EOF
    永不到（xelatex→xdvipdfmx 死锁对、setsid 逃逸孙都实证过整格挂死）。
    本环以 ``proc.poll()`` 为终态：子进程死透即非阻塞排干余量返回，孙
    进程握管/死锁不再挂死本层；deadline 走 ``time.monotonic``——墙钟
    拨回不再无限延时（旧实现 ``time.time()`` 实证过小时级假死）。
    ``should_cancel`` 依旧 ``_CANCEL_POLL_S`` 分片响应。
    ``sentry`` 非 None 时逐片喂活签名——越阈视同超时抛
    ``TimeoutExpired``（语义同 deadline 臂：调用方收树+续收），病态
    ``\output`` 暴走不再烧满墙钟。
    ``TimeoutExpired`` 携带已读部分输出，``run_process`` 超时臂续收。
    """
    deadline = time.monotonic() + timeout
    if proc.stdout is None:  # use_drain 闸住外防御——替身形态不炸 AttributeError
        return b""
    fd = proc.stdout.fileno()
    sel = selectors.DefaultSelector()
    chunks: list[bytes] = []
    total = 0
    headroom = max(4 * out_cap, _READ_CHUNK)
    eof = False
    try:
        sel.register(fd, selectors.EVENT_READ)
        while True:
            if should_cancel is not None and should_cancel():
                raise asyncio.CancelledError
            left = deadline - time.monotonic()
            if left <= 0:
                raise subprocess.TimeoutExpired(cmd, timeout, output=b"".join(chunks))
            if eof:
                # 写端全关而子未死（子关 stdout 续跑的罕见形）——只轮询等死。
                time.sleep(min(_CANCEL_POLL_S, left))
            else:
                data, eof = _pump_once(sel, fd, min(_CANCEL_POLL_S, left))
                if data:
                    chunks.append(data)
                    total += len(data)
                    if sentry is not None and sentry.feed(data):
                        # 病态输出签名已坐实——视同超时收树：已读片随异常
                        # 带出（超时臂续收），runaway_output 归因同口径。
                        raise subprocess.TimeoutExpired(
                            cmd, timeout, output=b"".join(chunks)
                        )
                    if total > headroom:
                        tail = b"".join(chunks)[-2 * out_cap :]
                        chunks = [tail]
                        total = len(tail)
            if proc.poll() is not None:
                break
    finally:
        sel.close()
    _drain_nonblocking(fd, chunks)
    return b"".join(chunks)


def _communicate_cancellable(
    proc: subprocess.Popen[bytes],
    cmd: list[str],
    timeout: float,
    should_cancel: Callable[[], bool] | None,
) -> bytes | None:
    """win32 退化臂：``_CANCEL_POLL_S`` 分片 communicate——单调钟 deadline。

    selectors 在 win32 看不了管道 fd，``_drain_bounded`` 不可用；退回分片
    ``communicate``（``TimeoutExpired`` 后可合法重入续读不丢输出）。旗标
    置位抛 ``CancelledError``；真超时/取消都抛给 ``run_process`` 外层臂
    收树——kill 语义单点不散。``should_cancel`` 为 None 时纯跑 deadline。
    """
    deadline = time.monotonic() + timeout
    while True:
        if should_cancel is not None and should_cancel():
            raise asyncio.CancelledError
        left = deadline - time.monotonic()
        if left <= 0:
            raise subprocess.TimeoutExpired(cmd, timeout)
        try:
            out, _ = proc.communicate(timeout=min(_CANCEL_POLL_S, left))
        except subprocess.TimeoutExpired:
            continue
        return out


def run_process(  # noqa: PLR0913 -- 子进程参数面集中声明，kwarg 各承一职
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    out_cap: int = 8 * 1024 * 1024,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[int | None, str, float, bool]:
    r"""同步跑子进程：进程组隔离 + 超时 killpg + 输出封顶 + POSIX rlimits。

    返回 `(rc, output, seconds, timed_out)`；timeout 后 SIGKILL 整组
    （latex→dvips/mktextfm 子进程一并带走），非 POSIX 平台降级 proc.kill。
    子进程 exec 前装资源软帽（仅降不升），硬顶之外的纵深兜底。

    POSIX 走 ``_drain_bounded``：单调钟 deadline + 子进程死透即收——
    孙进程握管/死锁（xelatex↔xdvipdfmx 形）、墙钟拨回都不再挂死。
    win32 selectors 看不了管道 fd，退回 ``_communicate_cancellable``
    分片 ``communicate``（单调钟同款）。``should_cancel`` 旗标置位即抛
    ``asyncio.CancelledError``（``except BaseException`` 臂照常
    ``_kill_tree`` 收树，编译段孤儿不再等满 timeout 才死）。
    drain 臂内嵌 ``_RunawaySentry`` 活哨——``\output`` 暴走签名/``[N]``
    页标越阈视同超时收树，``timed_out=True`` 让事后归因原样命中。
    """
    t0 = time.time()
    try:
        proc = subprocess.Popen(  # noqa: S603 — 编译器子进程即本模块职责，输入已由
            cmd,  # --untrusted/-no-shell-escape/env 白名单/sandbox-exec 约束
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,  # 缺文件时 TeX 仍 \read stdin 问替代名——
            # 不钉死则吃 harness 继承的 stdin，行为随父进程飘（e2e-real 2308.12712
            # r1 出 4.4MB pdf / r2 emergency stop 即此不确定性）；钉 DEVNULL =
            # 确定性 EOF → emergency stop → missing_file 归因稳定。
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=(sys.platform != "win32"),
            # PLW1509: rlimits 只能 fork 后 exec 前装——回调只碰
            # resource.setrlimit（纯 syscall 封套，不取锁不分配）。
            preexec_fn=_rlimit_preexec(timeout),  # noqa: PLW1509
        )
    except OSError as e:
        # 二进制缺席/cwd 失效等 exec 失败——返回 rc=None 而非炸掉调用方
        # （fixloop 轮内 FileNotFoundError 会整格崩）。
        return None, f"exec failed: {e}", time.time() - t0, False
    timed_out = False
    # 有 stdout 管的 POSIX 真子进程走 drain 环；win32/测试替身（无 stdout
    # 面）退回 communicate 系——原 ``communicate(timeout)`` 语义原样。
    use_drain = sys.platform != "win32" and getattr(proc, "stdout", None) is not None
    try:
        if use_drain:
            out = _drain_bounded(
                proc, cmd, timeout, out_cap, should_cancel, _RunawaySentry()
            )
        elif should_cancel is None:
            out, _ = proc.communicate(timeout=timeout)
        else:
            out = _communicate_cancellable(proc, cmd, timeout, should_cancel)
    except subprocess.TimeoutExpired as e1:
        timed_out = True
        # 超时前已读部分输出随异常带出——先收进口袋再收树。
        prior = e1.output
        out = b"".join(prior) if isinstance(prior, list) else (prior or b"")
        _kill_tree(proc)
        try:
            if use_drain:
                # 子已死/将死：poll 即返 + 非阻塞排干——setsid/双 fork 逃逸
                # 的孙进程仍握 stdout 写端也不再等 EOF，30s 硬顶兜住。
                out += _drain_bounded(proc, cmd, 30, out_cap)
            else:
                rest, _ = proc.communicate(timeout=30)
                out += rest or b""
        except subprocess.TimeoutExpired as e2:
            # setsid/双 fork 逃逸的孙进程仍握 stdout 写端——killpg 只带走
            # 本组，无限 communicate 会等孙进程退格才返 → 弃读防整格挂死。
            partial = e2.output
            out += b"".join(partial) if isinstance(partial, list) else (partial or b"")
    except BaseException:
        # KeyboardInterrupt/GeneratorExit 等——不杀树会把编译进程连同
        # mktex*/dvips 子孙一起孤儿化（sleep 30 探针实证幸存）。
        _kill_tree(proc)
        proc.wait()
        raise
    if out is None:
        out = b""
    # 封顶保留**尾部**——消费端是 stdout_tail（tectonic 不写 .log 时的错误
    # 兜底），fatal error 恒在末尾；截头会把诊断现场丢掉。
    return (
        proc.returncode,
        out[-out_cap:].decode("utf-8", errors="replace"),
        time.time() - t0,
        timed_out,
    )


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """SIGKILL 整进程组；组杀失败退化为单进程 kill。"""
    try:
        if sys.platform != "win32":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()
