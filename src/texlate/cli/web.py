"""``web`` 命令：起 FastAPI+SSE 服务 + ``service.lock`` 单实例锁。"""

from __future__ import annotations

import errno
import json
import os
import webbrowser
from pathlib import Path  # noqa: TC003 -- typer eval_str 解析 Annotated 实参
from typing import IO, Annotated

import typer

from texlate.cli._common import _CLI_PATH, app
from texlate.textutil import DEFAULT_BIND_HOST, DEFAULT_BIND_PORT, set_data_dir


def _connect_url(host: str, port: int) -> str:
    """浏览器可点地址：通配/空绑定回环化；IPv6 字面量加方括号。"""
    if host in ("0.0.0.0", "::", ""):  # noqa: S104 -- 比较非绑定：通配回环化
        return f"http://127.0.0.1:{port}"
    if ":" in host:  # IPv6 字面量——不 bracket 则 host:port 拼出非法 URL
        return f"http://[{host}]:{port}"
    return f"http://{host}:{port}"


def _service_lock(
    root: Path, host: str, port: int
) -> tuple[IO[bytes] | None, str | None]:
    """``<data_dir>/service.lock`` 单实例锁（web-layer §6 本地形态）。

    返回 ``(fh, None)`` = 拿到锁——**fh 必须活到进程终止**（flock 随 fd
    关闭/进程退出自动释放）；``(None, url)`` = 锁被持有即已有实例在跑，
    url 取自锁文件元数据（缺席按 host/port 推）；``(None, None)`` = 退化
    放行（``TEXLATE_MODE=server`` 多副本部署 / 无 fcntl 平台 / 锁文件
    不可写——不加锁也不拦起服）。
    """
    from texlate.server.settings import server_mode  # noqa: PLC0415

    if server_mode() == "server":
        return None, None
    try:
        import fcntl  # noqa: PLC0415 -- 平台门：win/无 fcntl 退化为无锁
    except ImportError:
        return None, None
    try:
        fh = (root / "service.lock").open("a+b")
    except OSError:
        return None, None
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        # 只有「锁被持有」族 errno 走已运行实例路径——其余（如 ENOLCK/
        # 文件系统错）按退化契约放行，不误报「已在运行」
        if e.errno not in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
            fh.close()
            return None, None
        url = ""
        try:
            fh.seek(0)
            meta = json.loads(fh.read().decode() or "{}")
            url = str(meta.get("url") or "")
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            pass
        fh.close()
        return None, url or _connect_url(host, port)
    # "a+b" 写恒落 EOF——truncate(0) 显式清零再写，免得上任持有者的
    # 元数据残留拼出非法 JSON（读侧解析失败会回退 host/port 推断）。
    try:
        fh.truncate(0)
        fh.write(
            json.dumps({"pid": os.getpid(), "url": _connect_url(host, port)}).encode()
        )
        fh.flush()
    except OSError:
        # meta 写失败但 flock 有效——无 meta 放行优于崩（读侧会回退推断）
        pass
    return fh, None


@app.command()
def web(
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
) -> None:
    """起 web 服务：FastAPI + SSE + 任务队列（需 ``server`` extra）。

    local 形态单实例（web-layer §6）：``<data_dir>/service.lock`` flock
    被持有 → 浏览器打开已运行实例并退出，而不是端口冲突或静默双开。
    ``python -m texlate.server`` 是低层入口、不经此锁（瘦客户端自动
    拉起/容器内的预期通路）。
    """
    if data_dir is not None:
        set_data_dir(data_dir)
    try:
        import uvicorn  # noqa: PLC0415 -- server extra 延迟导入

        from texlate.server.app import (  # noqa: PLC0415
            _exposed_bind_warning,
            create_app,
        )
        from texlate.server.settings import data_dir as _data_dir  # noqa: PLC0415
    except ImportError:
        typer.echo(
            "web 需要 server extra：uv sync --extra server"
            "（或 pip install 'texlate[server]'）",
            err=True,
        )
        raise typer.Exit(1) from None
    try:
        root = _data_dir()
    except OSError as e:
        typer.echo(f"数据目录不可用: {e}", err=True)
        raise typer.Exit(1) from None
    _lock_fh, existing = _service_lock(root, host, port)
    if existing is not None:
        typer.echo(
            f"texlate web 已在运行 → {existing}（service.lock 被持有）",
            err=True,
        )
        webbrowser.open(existing)
        return
    typer.echo(f"texlate web → {_connect_url(host, port)}", err=True)
    warning = _exposed_bind_warning(host)
    if warning is not None:
        typer.echo(warning, err=True)
    from texlate.logsetup import configure_server_logging  # noqa: PLC0415

    # try 只罩日志装/建 app——uvicorn 起服 bind 失败是自打日志 +
    # ``SystemExit(1)`` 自退路径，不抛 OSError（原 except 永远捕不到）
    try:
        configure_server_logging(root)
        asgi = create_app()
    except OSError as e:
        typer.echo(f"web 起服失败（{host}:{port}）: {e}", err=True)
        raise typer.Exit(1) from None
    uvicorn.run(asgi, host=host, port=port)
