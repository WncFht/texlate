"""``cli/`` 包共享底座：``app`` Typer 实例、``_CliPath`` 参数型与宽判小件。"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Annotated

import typer
from typer.models import TyperPath

from texlate.textutil import safe_is_dir, safe_is_file
from texlate.textutil.osutil import cache_root

if TYPE_CHECKING:
    from pathlib import Path

    import click

app = typer.Typer(
    help="arXiv LaTeX 源码 → LLM 段落级翻译 → ctex 重编译中文 PDF。",
    no_args_is_help=True,
)


_DEFAULT_CACHE = cache_root() / "src"

#: 路径串控制字符（C0/C1——NUL 为代表）。
_CTRL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class _CliPath(TyperPath):
    """Path 参数型：``os.stat`` 探针前置拒控制字符（NUL 一族）。

    ``TyperPath.convert`` 的 ``os.stat`` 只吞 ``OSError``——NUL 字节抛
    ``ValueError: stat: embedded null character`` 逃逸成 traceback
    （typer 上游缺陷）。控制字符在 POSIX 文件名里合法但 CLI 输入必是
    脏数据——统一按 usage 错拒收（exit 2），其余语义照走父类。
    """

    def convert(
        self,
        value: str | os.PathLike[str],
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> str | bytes | os.PathLike[str]:
        """先查控制字符再走父类 ``os.stat`` 探针。"""
        if isinstance(value, (str, bytes, os.PathLike)):
            raw = os.fsdecode(value)
            if _CTRL_CHARS_RE.search(raw):
                self.fail(f"路径含控制字符: {raw!r}", param, ctx)
        return super().convert(value, param, ctx)


#: ``ParamType`` 无参数态——两类形态各一个单例全 CLI 复用；``click_type``
#: 注入后 typer 的 exists/dir_okay/readable 声明失效，语义由构造参数承载。
_CLI_PATH = _CliPath()
_CLI_FILE = _CliPath(exists=True, dir_okay=False, readable=True)


def _is_dir(p: Path) -> bool:
    """``is_dir`` 宽判：ENAMETOOLONG/EACCES/NUL 等非缺席型异常归一 False。"""
    return safe_is_dir(p)


def _is_file(p: Path) -> bool:
    """``is_file`` 宽判：同 ``_is_dir``。"""
    return safe_is_file(p)


@app.callback()
def _main(
    verbose: Annotated[
        int,
        typer.Option(
            "--verbose",
            "-v",
            count=True,
            help="日志加噪：-v=INFO -vv=DEBUG（子命令前；TEXLATE_LOG 等效）",
        ),
    ] = 0,
    quiet: Annotated[
        int,
        typer.Option(
            "--quiet",
            "-q",
            count=True,
            help="日志降噪：-q=ERROR -qq=CRITICAL（覆盖 -v）",
        ),
    ] = 0,
) -> None:
    """texlate。

    ``-v/-q`` 只调 ``texlate.*`` 日志级别（stderr 实况/JSON stdout 契约
    不受影响）；``run`` 另有子命令位同名旗标（写子命令后）覆盖本层。
    """
    from texlate.cli._output import console as _cli_console  # noqa: PLC0415
    from texlate.logsetup import configure_logging, level_from_flags  # noqa: PLC0415

    # 级别决议序「旗标 > ``TEXLATE_LOG`` env > 缺省」：无旗标必须传
    # ``None`` 让 ``_resolve_level`` 落到 env——恒传 int 会把 env 判死
    # （``run`` 子命令位同名旗标 ``if verbose or quiet`` 同口径覆盖）。
    configure_logging(
        level=level_from_flags(verbose, quiet) if (verbose or quiet) else None,
        console=_cli_console,
    )
