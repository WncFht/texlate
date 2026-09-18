"""``tools`` 子命令簇：外部工具链管理（编译引擎探测/安装）。"""

from __future__ import annotations

import tarfile
import zipfile

import httpx
import typer

from texlate.cli._common import app
from texlate.compile import toolchain

tools_app = typer.Typer(
    help="外部工具链管理（编译引擎探测/安装）。",
    no_args_is_help=True,
)
app.add_typer(tools_app, name="tools")


@tools_app.command("install-tectonic")
def tools_install_tectonic() -> None:
    """探测 tectonic（系统件/托管件/缺失）；缺失时下载安装到托管目录。

    走 ``compile.toolchain``：sha256 钉值校验 → 单文件提取 → 原子落位，
    托管落点 ``<data>/tools/``（``TEXLATE_DATA_DIR`` > ``~/.texlate``）。
    已可用即报落点退出；``TEXLATE_NO_DOWNLOAD``/CI 默认关自动下载——
    显式 ``TEXLATE_NO_DOWNLOAD=0`` 可在 CI 强制开。
    """
    resolved = toolchain.resolve_tool("tectonic")
    if resolved is not None:
        kind = "托管件" if resolved == toolchain.find_managed() else "系统件"
        typer.echo(f"tectonic: {kind} {resolved} —— 无需安装")
        return
    typer.echo("tectonic: 缺失（PATH 与托管目录均未命中）")
    if not toolchain.download_allowed():
        typer.echo(
            "自动下载已关闭（TEXLATE_NO_DOWNLOAD / CI）；"
            "显式 TEXLATE_NO_DOWNLOAD=0 可强制开启",
            err=True,
        )
        raise typer.Exit(1)
    try:
        path = toolchain.install_tectonic()
    except (
        OSError,
        RuntimeError,
        tarfile.TarError,
        zipfile.BadZipFile,
        httpx.HTTPError,
    ) as e:
        typer.echo(f"tectonic 安装失败：{e}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"tectonic: 已安装 {toolchain.TECTONIC_VERSION} → {path}")
