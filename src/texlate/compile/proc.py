r"""子进程 runner：Popen 管线 + 单调钟排干环 + 超时 killpg + rlimits + 暴走活哨。

自 ``sandbox.py`` 出叶——本叶只管执行件；OS 沙箱策略面（env 白名单 /
sandbox-exec / bwrap 挂载与能力探测）留 ``sandbox.py``，runner 名经其
``from .proc import`` 再出口，旧 ``sandbox.X`` 路径原样可 import。
``run_process`` 亦入 ``compile.seams`` 缝面（惰性回指本模块——patch
``seams.X`` 或 ``proc.X`` 同拦 seams 路由消费点；``engine``/``sandbox``
回引锚各归其包，详见 seams docstring）。

- 进程组隔离（`start_new_session`）+ `killpg` 杀整棵进程树；非 POSIX 降级
  为 `proc.kill()`。子进程输出封顶 8MB 防内存炸。
- POSIX 主流排干环（``_drain_bounded``）：单调钟 deadline + 子进程死透即
  收——孙进程握管/死锁（xelatex↔xdvipdfmx 形）、墙钟拨回都不再挂死；
  win32 selectors 看不了管道 fd，退回 ``_communicate_cancellable`` 分片
  ``communicate``。``should_cancel`` 旗标依 ``_CANCEL_POLL_S`` 分片响应。
- POSIX rlimits 纵深：exec 前经 preexec_fn 装 AS/NOFILE/CPU 软帽——失控
  TeX 吃不光宿主内存与 fd，自旋进程墙钟之外还有 SIGXCPU 第二闸。
- ``\output`` 暴走活哨（``_RunawaySentry``）：排干环逐片喂签名计数
  （logparse 事后判据同 regex 同阈值）——``[N]`` 页标单调包络计数
  ≥10K 页洪闸 + vbox 签名密度闸（签名 ≫ 页产才判暴走，逐页慢性告
  警不杀），
  越阈抛 ``TimeoutExpired`` 走既有 killpg 收树臂——病态编译不再烧满
  墙钟（gr-qc/0104075：96K+ 签名行 / ~97K 页烧 240s 实证）。截杀原因
  （``vbox_flood``/``page_flood``）经 ``timed_out`` 槽以 str 回吐——
  引擎原样落 ``res.timed_out``，``_collect_compile_outputs`` 归位
  ``CompRes.sentry_reason``，事后归因不再凭 4KB 尾窗重数累计签名。
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

from texlate.compile.logparse import (
    _RUNAWAY_PAGE_MAX,
    _RUNAWAY_PAGE_RX,
    _RUNAWAY_VBOX_DENSITY,
    _RUNAWAY_VBOX_MIN,
    _RUNAWAY_VBOX_RX,
)

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
#: 数量级。vbox 签名缺席的静默死循环由本闸兜住。计数走**单调包络**——
#: 真 shipout 序号只增不减（2609.19748 实测 9623 标记全序），仅
#: ``n >= 已计最大值`` 入计；收敛文档万级非序方括数字（索引/引用阵
#: 列）只贡献 ~ln(n) 个左向右极大值，不再假触（killsem2 census 开放缺
#: 口——旧纯计数把任意 ``[\d+]`` 当页标）。
#: 页标 ``[N]`` 的 bytes 编译形——权威 str 源与阈值单源在 ``compile.logparse``
#: （顶层 import 转口），按同一 ``str.pattern.encode()`` 变换派生；
#: ``logparse`` 的事后判据与本哨的流片判据同词素两介质（logparse:71 注记）。
#: 活哨逐实例直用本编译形，免 ``__init__`` 重编译。
_PAGE_MARK_RX: Final = re.compile(_RUNAWAY_PAGE_RX.pattern.encode())


class _RunawaySentry:
    r"""``\output`` 暴走活哨：drain 流片喂入、行界扫描，双臂越阈即报。

    与 ``compile.logparse`` 事后判据同 regex 同阈值（str 模式源 ``encode``
    成 bytes 编译形，定义仍单源）：

    - ``page_flood``：``[N]`` 页标**单调包络计数** ≥ ``_RUNAWAY_PAGE_MAX``
      ——病态页产率（gr-qc/0104075 ~97K 页实证），vbox 签名缺席的静默
      死循环也兜住；非序方括数字不入计，万级良性 ``[\d+]`` 文本不误杀；
    - ``vbox_flood``：vbox 签名 ≥ ``_RUNAWAY_VBOX_MIN`` ∧ 签名数 >
      ``_RUNAWAY_VBOX_DENSITY`` × 页标**原始计数**——无 shipout 空转
      签名。「逐页一条」的慢性告警是良性排版溢出（1003.2165：46 签名
      /46 页、36s 干净编译，旧累计≥30 闸 ~15.6s 误杀），密度语义后不
      杀；分母不走包络——非序噪声撑大分母是豁免方向（保守），复位
      档页标也不漏计。

    越阈由排干环抛 ``TimeoutExpired`` 走 ``run_process`` 既有 killpg 收
    树臂；``reason`` 记截杀臂名，经 ``timed_out`` 槽回吐让
    ``runaway_output`` 归因不依赖截断尾窗重数签名。
    """

    def __init__(self) -> None:
        self._vbox_rx = re.compile(_RUNAWAY_VBOX_RX.pattern.encode())
        self._page_rx = _PAGE_MARK_RX
        self._vbox_min = _RUNAWAY_VBOX_MIN
        self._vbox_density = _RUNAWAY_VBOX_DENSITY
        self._page_max = _RUNAWAY_PAGE_MAX
        self._vbox_hits = 0
        #: 页标原始总数——vbox 密度分母。分母走原始计数是保守方向：噪声
        #: 只会撑大分母豁免 vbox 臂（签名 ≫ 页产才杀），永不反向假触；
        #: pagenumbering 复位档的真 shipout 也全数入计，密度不失真。
        self._page_marks = 0
        #: 单调包络计数——page_flood 闸专用：真 shipout 序号只增不减，
        #: 仅 ``n >= _page_last`` 入计；非序方括噪声只贡献 ~ln(n) 个
        #: 左向右极大值，万级良性 ``[\d+]`` 文本不再假触（killsem2）。
        self._page_env = 0
        self._page_last = -1
        self._tail = b""
        self.tripped = False
        #: 截杀臂名（``vbox_flood``/``page_flood``）；未越阈为 None。
        self.reason: str | None = None

    def feed(self, data: bytes) -> bool:
        """喂一片 stdout；vbox 密度/``[N]`` 页洪任一越阈返 True。"""
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
        self._vbox_hits += len(self._vbox_rx.findall(seg))
        for m in self._page_rx.finditer(seg):
            self._page_marks += 1
            n = int(m.group(0)[1:-1])
            if n >= self._page_last:
                self._page_env += 1
                self._page_last = n
                if self._page_env >= self._page_max:
                    break
        if self._page_env >= self._page_max:
            self.tripped = True
            self.reason = "page_flood"
        elif (
            self._vbox_hits >= self._vbox_min
            and self._vbox_hits > self._vbox_density * self._page_marks
        ):
            self.tripped = True
            self.reason = "vbox_flood"


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
    merge_stderr: bool = True,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[int | None, str, float, bool | str]:
    r"""同步跑子进程：进程组隔离 + 超时 killpg + 输出封顶 + POSIX rlimits。

    返回 `(rc, output, seconds, timed_out)`；timeout 后 SIGKILL 整组
    （latex→dvips/mktextfm 子进程一并带走），非 POSIX 平台降级 proc.kill。
    子进程 exec 前装资源软帽（仅降不升），硬顶之外的纵深兜底。

    ``timed_out`` 槽语义：``False`` 正常 / ``True`` 墙钟或取消超时 /
    非空 str（``vbox_flood``/``page_flood``）= 活哨截杀原因——哨件越阈
    视同超时收树，原因字符串随槽位回吐（调用方 truthiness 用法不变，
    ``res.timed_out`` 短暂携 str 后由 ``_collect_compile_outputs`` 归位
    ``CompRes.sentry_reason``）。
    ``merge_stderr=False`` 把 stderr 丢 DEVNULL 而非并入 stdout——文本
    计量型调用面（``judge.pdf_text_stats``）要它：外来告警行插进管道
    会劈断多字节 UTF-8 序列，decode 面产出假 U+FFFD 污染计数（poppler
    ``Syntax Warning`` 劈 CJK 实详见该函数注释）。

    POSIX 走 ``_drain_bounded``：单调钟 deadline + 子进程死透即收——
    孙进程握管/死锁（xelatex↔xdvipdfmx 形）、墙钟拨回都不再挂死。
    win32 selectors 看不了管道 fd，退回 ``_communicate_cancellable``
    分片 ``communicate``（单调钟同款）。``should_cancel`` 旗标置位即抛
    ``asyncio.CancelledError``（``except BaseException`` 臂照常
    ``_kill_tree`` 收树，编译段孤儿不再等满 timeout 才死）。
    drain 臂内嵌 ``_RunawaySentry`` 活哨——``\output`` 暴走签名密度/
    ``[N]`` 页标越阈视同超时收树。
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
            stderr=subprocess.STDOUT if merge_stderr else subprocess.DEVNULL,
            start_new_session=(sys.platform != "win32"),
            # PLW1509: rlimits 只能 fork 后 exec 前装——回调只碰
            # resource.setrlimit（纯 syscall 封套，不取锁不分配）。
            preexec_fn=_rlimit_preexec(timeout),  # noqa: PLW1509
        )
    except OSError as e:
        # 二进制缺席/cwd 失效等 exec 失败——返回 rc=None 而非炸掉调用方
        # （fixloop 轮内 FileNotFoundError 会整格崩）。
        return None, f"exec failed: {e}", time.time() - t0, False
    timed_out: bool | str = False
    # 有 stdout 管的 POSIX 真子进程走 drain 环；win32/测试替身（无 stdout
    # 面）退回 communicate 系——原 ``communicate(timeout)`` 语义原样。
    use_drain = sys.platform != "win32" and getattr(proc, "stdout", None) is not None
    sentry = _RunawaySentry() if use_drain else None
    try:
        if use_drain:
            out = _drain_bounded(proc, cmd, timeout, out_cap, should_cancel, sentry)
        elif should_cancel is None:
            out, _ = proc.communicate(timeout=timeout)
        else:
            out = _communicate_cancellable(proc, cmd, timeout, should_cancel)
    except subprocess.TimeoutExpired as e1:
        # 活哨截杀把臂名（vbox_flood/page_flood）写进 timed_out 槽回吐——
        # 截断的 4KB 尾窗数不出全程签名密度，事后归因凭记录值（1003.2165
        # 实证旧判据误归泛 timeout）。
        timed_out = sentry.reason if sentry is not None and sentry.reason else True
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
