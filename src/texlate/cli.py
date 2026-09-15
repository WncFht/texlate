"""texlate 命令行入口。"""

import typer

from texlate import __version__

app = typer.Typer(
    help="arXiv LaTeX 源码 → LLM 段落级翻译 → ctex 重编译中文 PDF。",
    no_args_is_help=True,
)


@app.callback()
def _main() -> None:
    """texlate。"""


@app.command()
def version() -> None:
    """打印版本号。"""
    typer.echo(f"texlate {__version__}")
