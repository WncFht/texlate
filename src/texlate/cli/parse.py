"""``parse`` 命令：单 .tex 半解析分块 → chunks.jsonl。"""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 -- typer eval_str 解析 Annotated 实参
from typing import Annotated

import typer

from texlate.cli._common import _CLI_FILE, _CLI_PATH, app
from texlate.latex.api import parse_file


@app.command()
def parse(
    path: Annotated[
        Path,
        typer.Argument(help=".tex 文件路径", click_type=_CLI_FILE),
    ],
    *,
    flatten: Annotated[
        bool, typer.Option("--flatten/--no-flatten", help="展开 \\input 图")
    ] = True,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="chunks.jsonl 输出路径", click_type=_CLI_PATH),
    ] = None,
) -> None:
    """半解析单个 .tex：分块/占位符/警告统计，``--out`` 落逐块明细。"""
    if out is not None:
        out = out.expanduser()
        try:
            same_path = out.resolve() == path.resolve()
        except (OSError, RuntimeError, ValueError):
            # 解不开的 out（symlink loop/NUL）与源必不同径；真写不了由
            # 下方 --out 不可写 OSError 兜底报错。
            same_path = False
        if same_path:
            typer.echo("--out 与输入同路径——拒绝覆写源文件", err=True)
            raise typer.Exit(2)
    try:
        res = parse_file(path, flatten=flatten)
    except OSError as e:  # 检查后消失/变不可读/fifo —— typer 断言与读间有 TOCTOU 窗
        typer.echo(f"不可读 {path}: {e}", err=True)
        raise typer.Exit(2) from None
    typer.echo(
        json.dumps(
            {
                "path": str(path),
                "chunks": len(res.chunks),
                "pieces": len(res.pieces),
                "placeholders": len(res.ph_map),
                "warnings": [f"{w.kind}@{w.pos}: {w.detail}" for w in res.warnings],
            },
            ensure_ascii=False,
        )
    )
    if out is not None:
        try:
            with out.open("w", encoding="utf-8") as fh:
                for c in res.chunks:
                    fh.write(
                        json.dumps(
                            {
                                "id": c.id,
                                "context": c.context,
                                "env": c.env,
                                "placeholders": c.placeholders,
                                "content": c.content,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
        except OSError as e:
            typer.echo(f"--out 不可写 {out}: {e}", err=True)
            raise typer.Exit(1) from None
        typer.echo(f"chunks -> {out}", err=True)
