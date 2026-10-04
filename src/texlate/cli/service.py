"""``service`` 子命令簇：本地 web 服务的后台生命周期管理。

``web`` 动词的常驻包装——同一 ``service.lock`` 语义（flock=真值、meta
``{pid,url}`` = 提示）：``status``/``stop`` 靠锁面 meta × pid 存活 ×
``/api/health`` 三源合成定位在跑实例；``start`` 脱离会话 spawn
``python -m texlate web``
（父进程退出服务照活，与 zotero 插件 bootstrap 同语义不同实现）。
``TEXLATE_MODE=server`` 部署不持锁——status 经 health 应答侧认，
stop 拒杀非锁面实例。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 -- typer eval_str 解析 Annotated 实参
from typing import TYPE_CHECKING, Annotated, Any

import httpx
import typer

from texlate.cli._common import _CLI_PATH, app
from texlate.cli.web import _connect_url
from texlate.textutil import DEFAULT_BIND_HOST, DEFAULT_BIND_PORT, data_root

if TYPE_CHECKING:
    from collections.abc import Callable

service_app = typer.Typer(
    help="本地 web 服务管理（后台拉起/停止/查看状态）。",
    no_args_is_help=True,
)
app.add_typer(service_app, name="service")

#: ``/api/health`` 单次探活上限——回环地址，挂死即降级（不等 TCP 超时）。
_HEALTH_TIMEOUT_S = 3.0
#: ``_pid_cmdline`` 系统工具上限（powershell CIM 冷启慢于 ps，留余量）。
_CMDLINE_TIMEOUT_S = 5.0
#: 轮询节拍（stop 等退场 / start 等就绪共用）。
_POLL_S = 0.4
#: SIGTERM 后的体面退场宽限；超时 posix 升级 SIGKILL。
_STOP_TIMEOUT_S = 15.0
#: ``_fmt_age`` 秒→分钟/时/天进位阈。
_MIN_S = 60
_HOUR_S = 3600
_DAY_S = 86400


@dataclass(frozen=True, slots=True)
class _ServiceStatus:
    """``service.lock`` 观测面：``state`` ∈ ``running|degraded|stopped``。

    ``running`` = 探活 ``/api/health`` 应答 ok——``pid`` 为锁面登记持有者，
    缺席 = 无锁拉起（``TEXLATE_MODE=server`` 或 ``python -m texlate.server``
    直连）；``foreign`` 非空 = 应答实例 ``data_dir`` 与本观测根不符（端口
    被别家实例占用）。``degraded`` = 锁面 pid 存活但 health 无应答（起服中/
    卡死/pid 撞号）。``stopped`` = 无存活迹象——锁文件残留 meta 是常态停机
    遗迹（flock 随进程退出释放但文件不删），不算异常。
    """

    state: str
    pid: int | None
    pid_alive: bool
    url: str
    root: Path
    version: str
    started_at: str
    uptime: str
    foreign: str


def _read_lock_meta(root: Path) -> dict[str, Any]:
    """``<root>/service.lock`` meta（缺席/损坏/非 dict → ``{}``）——只读不写。

    与 ``web._service_lock`` 的拿锁路径刻意分家：探测绝不 flock/truncate，
    否则 status 自己就成锁持有者还会覆写 meta。
    """
    try:
        meta = json.loads((root / "service.lock").read_bytes() or b"{}")
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _pid_alive(pid: int) -> bool:
    """Pid 存活探针：posix ``kill(pid, 0)``；nt 走 ``OpenProcess`` 可开即活。

    Windows 的 ``os.kill`` 不支持 signal 0 语义（非 CTRL 族信号一律
    TerminateProcess——0 也会真杀），故分平台实现。
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        return _pid_alive_nt(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 存在但无权 signal——活着
    except OSError:
        return False
    return True


def _pid_alive_nt(pid: int) -> bool:
    """Windows 侧 pid 存活：``OpenProcess(QUERY_LIMITED_INFORMATION)`` 可开即活。"""
    import ctypes  # noqa: PLC0415 -- nt 专属，posix 永远不触

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined] -- win32 API
    handle = kernel32.OpenProcess(
        0x1000,  # PROCESS_QUERY_LIMITED_INFORMATION
        False,  # noqa: FBT003 -- win32 API 定参序
        pid,
    )
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def _pid_cmdline(pid: int) -> str:
    """Pid 命令行（进程身份核验）；取不到 → ``""``。

    stop 的防撞号闸：``service.lock`` meta pid 死后被复用，kill 前须确认
    对象真是 texlate 系进程。posix 走 ``ps``；nt 走 powershell CIM 查询
    （``Get-CimInstance Win32_Process``——``wmic`` 已被微软弃用）。
    """
    argv = (
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
        ]
        if os.name == "nt"
        else ["ps", "-o", "args=", "-p", str(pid)]
    )
    try:
        r = subprocess.run(  # noqa: S603 -- 固定系统工具 argv
            argv,
            capture_output=True,
            timeout=_CMDLINE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if r.returncode != 0:
        return ""
    return r.stdout.decode("utf-8", "replace").strip()


def _health_probe(url: str) -> dict[str, Any]:
    """``GET {url}/api/health`` → body dict；不应答/非 2xx/坏 body → ``{}``。

    与 doctor 网关探活同手法——health 应答是「有 texlate 在服务」的
    唯一硬证据（pid 可撞号、锁 meta 可残留）。
    """
    try:
        r = httpx.get(f"{url}/api/health", timeout=_HEALTH_TIMEOUT_S)
    except (httpx.HTTPError, httpx.InvalidURL):
        return {}
    if not r.is_success:
        return {}
    try:
        data = r.json()
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict) or data.get("ok") is not True:
        return {}
    return data


def _fmt_age(started_at: str) -> str:
    """``utc_now()`` 的 Z 戳 → ``45s``/``37m``/``2h5m``/``3d`` 龄串；坏戳 → ``""``。"""
    try:
        t0 = datetime.fromisoformat(started_at)
    except ValueError:
        return ""
    if t0.tzinfo is None:
        return ""  # 朴素戳与 aware now 相减会 TypeError——无 tz 不判龄
    secs = max(0, int((datetime.now(UTC) - t0).total_seconds()))
    if secs < _MIN_S:
        return f"{secs}s"
    if secs < _HOUR_S:
        return f"{secs // _MIN_S}m"
    if secs < _DAY_S:
        return f"{secs // _HOUR_S}h{secs % _HOUR_S // _MIN_S}m"
    return f"{secs // _DAY_S}d{secs % _DAY_S // _HOUR_S}h"


def _probe_service(root: Path, url_hint: str = "") -> _ServiceStatus:
    """``service.lock`` meta × pid 存活 × ``/api/health`` 三源合成观测态。

    url 决议序：meta.url > ``url_hint`` > 缺省绑定面（无锁实例只能按
    绑定面猜）。
    """
    meta = _read_lock_meta(root)
    pid_raw = meta.get("pid")
    pid = pid_raw if isinstance(pid_raw, int) else None
    url = (
        str(meta.get("url") or "")
        or url_hint
        or _connect_url(DEFAULT_BIND_HOST, DEFAULT_BIND_PORT)
    )
    alive = pid is not None and _pid_alive(pid)
    health = _health_probe(url)
    if health:
        foreign = ""
        other_dir = health.get("data_dir")
        # server 形态 health 不带 data_dir——无据可判视同本家
        if (
            isinstance(other_dir, str)
            and other_dir
            and os.path.normpath(other_dir) != os.path.normpath(str(root))
        ):
            foreign = other_dir
        return _ServiceStatus(
            state="running",
            pid=pid,
            pid_alive=alive,
            url=url,
            root=root,
            version=str(health.get("version") or ""),
            started_at=str(health.get("started_at") or ""),
            uptime=_fmt_age(str(health.get("started_at") or "")),
            foreign=foreign,
        )
    if alive:
        return _ServiceStatus(
            state="degraded",
            pid=pid,
            pid_alive=True,
            url=url,
            root=root,
            version="",
            started_at="",
            uptime="",
            foreign="",
        )
    return _ServiceStatus(
        state="stopped",
        pid=pid,
        pid_alive=False,
        url=url,
        root=root,
        version="",
        started_at="",
        uptime="",
        foreign="",
    )


def _service_log(root: Path) -> Path:
    """Spawn stdout/stderr 落点（``logs/`` 与服务自身日志同层）。"""
    return root / "logs" / "service-launch.log"


def _spawn_detached(argv: list[str], log_path: Path) -> int:
    """脱离会话 spawn → 返回子进程 pid。

    posix ``start_new_session`` 脱离会话 + std 三流重定向（父进程退出
    服务照活）；nt 走 ``DETACHED_PROCESS|CREATE_NO_WINDOW``。
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log_fh:
        if os.name == "nt":
            proc = subprocess.Popen(  # noqa: S603 -- argv[0] 是 sys.executable 绝对路径
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                creationflags=(
                    subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
                ),
                close_fds=True,
            )
        else:
            proc = subprocess.Popen(  # noqa: S603 -- argv[0] 是 sys.executable 绝对路径
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
    return proc.pid


def _wait_health(
    url: str, timeout: float, extra_gone: Callable[[], bool] | None = None
) -> bool:
    """轮询 ``_health_probe`` 至 ok 或超时；``extra_gone`` 供「子进程早夭」早退。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _health_probe(url):
            return True
        if extra_gone is not None and extra_gone():
            return False
        time.sleep(_POLL_S)
    return bool(_health_probe(url))


def _wait_pid_gone(pid: int, timeout: float) -> bool:
    """轮询 ``_pid_alive`` 至退场或超时。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(_POLL_S)
    return not _pid_alive(pid)


def _resolve_root(data_dir: Path | None) -> Path:
    """``--data-dir`` > ``TEXLATE_DATA_DIR`` > ``~/.texlate``——只定位不 mkdir。"""
    return data_dir.expanduser() if data_dir is not None else data_root()


def _status_line(st: _ServiceStatus) -> str:
    """Status 单行呈现。"""
    if st.state == "running":
        pid = f"pid {st.pid}" if st.pid is not None else "无锁实例"
        age = f" · 已运行 {st.uptime}" if st.uptime else ""
        line = f"运行中 — v{st.version or '?'} · {pid} · {st.url}{age}"
        if st.foreign:
            line += (
                f"\n  注意：应答实例数据目录 {st.foreign} ≠ {st.root}（端口被别家占用）"
            )
        return line
    if st.state == "degraded":
        return (
            f"pid {st.pid} 存活但 {st.url} 不应答——起服中/卡死/pid 撞号"
            f"（日志 {st.root / 'logs' / 'texlate.log'}）"
        )
    return (
        f"未在运行（{st.root}/service.lock 无存活实例——`texlate service start` 拉起）"
    )


@service_app.command("status")
def service_status(
    *,
    data_dir: Annotated[
        Path | None,
        typer.Option(
            "--data-dir",
            help="数据目录（缺省 TEXLATE_DATA_DIR 或 ~/.texlate）",
            click_type=_CLI_PATH,
        ),
    ] = None,
    url_hint: Annotated[
        str, typer.Option("--url", help="锁面无 meta 时的探活地址兜底")
    ] = "",
    as_json: Annotated[
        bool, typer.Option("--json", help="机器可读输出（供脚本/插件）")
    ] = False,
) -> None:
    """查看本地服务状态：锁面 meta × pid 存活 × ``/api/health`` 三源合成。

    退出码：``running`` 且非他目占用 → 0；``degraded``/``stopped``/``foreign`` → 1。
    """
    st = _probe_service(_resolve_root(data_dir), url_hint)
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "state": st.state,
                    "pid": st.pid,
                    "pid_alive": st.pid_alive,
                    "url": st.url,
                    "data_dir": str(st.root),
                    "version": st.version,
                    "started_at": st.started_at,
                    "foreign": st.foreign,
                },
                ensure_ascii=False,
            )
        )
    else:
        typer.echo(_status_line(st))
    if st.state != "running" or st.foreign:
        raise typer.Exit(1)


@service_app.command("start")
def service_start(
    *,
    host: Annotated[str, typer.Option("--host", help="绑定地址")] = DEFAULT_BIND_HOST,
    port: Annotated[
        int, typer.Option("--port", "-p", help="端口", min=1, max=65535)
    ] = DEFAULT_BIND_PORT,
    data_dir: Annotated[
        Path | None,
        typer.Option(
            "--data-dir",
            help="数据目录（缺省 TEXLATE_DATA_DIR 或 ~/.texlate）",
            click_type=_CLI_PATH,
        ),
    ] = None,
    wait: Annotated[
        float,
        typer.Option("--wait", help="等就绪上限秒数", min=0),
    ] = 30.0,
    open_browser: Annotated[
        bool,
        typer.Option("--open/--no-open", help="就绪后打开浏览器（缺省开）"),
    ] = True,
) -> None:
    """后台拉起服务：脱离会话 spawn ``python -m texlate web`` 后轮询就绪。

    已运行 → 指到实例并退出（同 ``web`` 的锁竞争语义）；目标端口被别家
    texlate（数据目录不符）或锁面 pid 卡占 → 拒 spawn 并指认。spawn 早期
    输出落 ``<data_dir>/logs/service-launch.log``。
    """
    root = _resolve_root(data_dir)
    target = _connect_url(host, port)
    target_health = _health_probe(target)
    if target_health:
        foreign_dir = str(target_health.get("data_dir") or "")
        if foreign_dir and os.path.normpath(foreign_dir) != os.path.normpath(str(root)):
            typer.echo(
                f"{target} 已被另一数据目录的 texlate 占用（{foreign_dir}）"
                "——换 --port 或先停那边",
                err=True,
            )
            raise typer.Exit(1)
        typer.echo(f"已在运行 → {target}")
        if open_browser:
            webbrowser.open(target)
        return
    st = _probe_service(root, target)
    if st.pid is not None and st.pid_alive:
        typer.echo(
            f"service.lock 持有者 pid {st.pid} 存活但 {target} 未就绪"
            "——先 `texlate service stop`，或确认它跑在其它端口",
            err=True,
        )
        raise typer.Exit(1)
    argv = [
        sys.executable,
        "-m",
        "texlate",
        "web",
        "--host",
        host,
        "--port",
        str(port),
        "--data-dir",
        str(root),
    ]
    try:
        pid = _spawn_detached(argv, _service_log(root))
    except OSError as e:
        typer.echo(f"spawn 失败：{e}", err=True)
        raise typer.Exit(1) from None
    if not _wait_health(target, wait, extra_gone=lambda: not _pid_alive(pid)):
        typer.echo(
            f"已 spawn（pid {pid}）但 {wait:.0f}s 内未就绪——"
            f"见 {_service_log(root)} 与 {root / 'logs' / 'texlate.log'}",
            err=True,
        )
        raise typer.Exit(1)
    typer.echo(f"已拉起 → {target}（pid {pid}；数据目录 {root}）")
    if open_browser:
        webbrowser.open(target)


@service_app.command("stop")
def service_stop(
    *,
    data_dir: Annotated[
        Path | None,
        typer.Option(
            "--data-dir",
            help="数据目录（缺省 TEXLATE_DATA_DIR 或 ~/.texlate）",
            click_type=_CLI_PATH,
        ),
    ] = None,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="SIGTERM 后等退场秒数", min=1),
    ] = _STOP_TIMEOUT_S,
) -> None:
    """停止服务：锁面 meta pid → SIGTERM → 超时升级 SIGKILL（posix）。

    只杀「锁面登记 + 身份可核验」的实例：health 应答但锁面无存活 pid
    （server 模式/外部拉起）、应答实例属别家数据目录、或 pid 命令核验
    不到 texlate（撞号）→ 拒杀指认人工处置。
    """
    st = _probe_service(_resolve_root(data_dir))
    if st.state == "stopped":
        typer.echo("未在运行")
        return
    pid = st.pid
    if st.foreign:
        typer.echo(
            f"{st.url} 应答实例属 {st.foreign}（≠ 本数据目录）——不是本目录服务，勿动",
            err=True,
        )
        raise typer.Exit(1)
    if pid is None or not st.pid_alive:
        typer.echo(
            f"{st.url} 有 texlate 应答但锁面无存活 pid"
            "（TEXLATE_MODE=server 或外部拉起）——请按部署方式停",
            err=True,
        )
        raise typer.Exit(1)
    if st.state == "degraded" and "texlate" not in _pid_cmdline(pid):
        typer.echo(
            f"pid {pid} 存活但 health 不应答且进程身份核验不到 texlate"
            "（pid 撞号？）——请人工确认",
            err=True,
        )
        raise typer.Exit(1)
    os.kill(pid, signal.SIGTERM)
    if not _wait_pid_gone(pid, timeout):
        sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
        if sigkill != signal.SIGTERM:
            typer.echo(f"SIGTERM {timeout:.0f}s 未退场——升级 SIGKILL", err=True)
            os.kill(pid, sigkill)
            _wait_pid_gone(pid, 5.0)
    if _pid_alive(pid):
        typer.echo(f"pid {pid} 仍未退场——请人工处置", err=True)
        raise typer.Exit(1)
    typer.echo(f"已停止（pid {pid}）")


@service_app.command("restart")
def service_restart(
    *,
    host: Annotated[str, typer.Option("--host", help="绑定地址")] = DEFAULT_BIND_HOST,
    port: Annotated[
        int, typer.Option("--port", "-p", help="端口", min=1, max=65535)
    ] = DEFAULT_BIND_PORT,
    data_dir: Annotated[
        Path | None,
        typer.Option(
            "--data-dir",
            help="数据目录（缺省 TEXLATE_DATA_DIR 或 ~/.texlate）",
            click_type=_CLI_PATH,
        ),
    ] = None,
    wait: Annotated[
        float,
        typer.Option("--wait", help="等就绪上限秒数", min=0),
    ] = 30.0,
) -> None:
    """重启 = ``stop``（在跑才停）+ ``start``；未在运行则直接拉起。

    锁面无存活 pid 的实例（无锁拉起）stop 拒杀——restart 随之落到
    start 的「已在运行/他占」分支如实报出。
    """
    st = _probe_service(_resolve_root(data_dir))
    if st.state != "stopped" and st.pid is not None and st.pid_alive:
        service_stop(data_dir=data_dir)
    service_start(
        host=host,
        port=port,
        data_dir=data_dir,
        wait=wait,
        open_browser=False,
    )
