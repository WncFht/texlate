"""``version`` 命令：打印版本号。"""

from __future__ import annotations

import typer

from texlate import __version__
from texlate.cli._common import app


@app.command()
def version() -> None:
    """打印版本号。"""
    typer.echo(f"texlate {__version__}")
