"""``export`` 命令：EPUB/DOCX → 双语插译文档 + ``_export_translator`` 构造件。

``_export_translator`` 经 ``_cli.`` 调用期解析——测试 monkeypatch
``cli._export_translator`` 面守恒。
"""

from __future__ import annotations

import asyncio
from pathlib import Path  # noqa: TC003 -- typer eval_str 解析 Annotated 实参
from typing import TYPE_CHECKING, Annotated

import typer

import texlate.cli as _cli
from texlate.cli._common import _CLI_PATH, app
from texlate.textutil import env_str

if TYPE_CHECKING:
    from texlate.xlat.pipeline import Translator


@app.command()
def export(
    path: Annotated[
        Path,
        typer.Argument(
            help="EPUB/DOCX 文档（zip 内容嗅探，不看后缀）", click_type=_CLI_PATH
        ),
    ],
    *,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            "-o",
            help="输出路径（缺省 {stem}_bilingual{ext}）",
            click_type=_CLI_PATH,
        ),
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="模型名（缺省 TEXLATE_MODEL）")
    ] = None,
    glossary: Annotated[
        Path | None,
        typer.Option(
            "--glossary",
            help="术语表 .yaml/.csv（user 层，叠内建默认表）",
            click_type=_CLI_PATH,
        ),
    ] = None,
    mock: Annotated[
        bool, typer.Option("--mock", help="MockTranslator 干跑（不触网）")
    ] = False,
) -> None:
    """EPUB/DOCX → 双语插译文档（原文段落后跟译文）。

    DRM 声明/fixed-layout/畸形包落翻译前拒开；中断留 ``{dst}.state/`` 自动续跑。
    """
    from texlate.export import export_document  # noqa: PLC0415 -- 重依赖延迟导入
    from texlate.export.common import ExportError  # noqa: PLC0415

    translator = _cli._export_translator(model, mock=mock)  # noqa: SLF001 -- monkeypatch 缝
    path = path.expanduser()
    if out is not None:
        out = out.expanduser()
    try:
        report = export_document(path, out, translator, glossary=glossary)
    except (ExportError, OSError) as e:
        typer.echo(f"export: {e}", err=True)
        raise typer.Exit(1) from None
    finally:
        # GatewayTranslator 自持 ChatClient——不关则 httpx 连接池随进程泄漏
        client = getattr(translator, "client", None)
        if client is not None:
            asyncio.run(client.aclose())
    typer.echo(
        f"{report.dst} — 插译 {report.translated}/{report.units}"
        f"（unchanged {report.unchanged} / skipped {report.skipped}"
        f" / fault {report.fault}）",
        err=True,
    )


def _export_translator(model: str | None, *, mock: bool) -> Translator:
    """worker._make_translator 的无 ctx 版：env/key → 网关，否则 Mock。

    ``TEXLATE_TRANSLATOR`` 白名单 ``mock|gateway``——其他非空值（typo 形）
    exit 2 显式拒，不静默按 auto 回落；``gateway`` 无 key 同样 exit 2
    （缺 key 的网关调用必败，不静默回落 Mock 产占位译文）；无 key 隐式
    回落 Mock 时打 stderr 提示——占位译文当真译文是真实踩坑面。凭证
    四件套走 ``env_credentials``（``TEXLATE_API_KEY`` 优先 + provider
    专名 env 兜底，与 server ``env_key_for`` 同口径）。
    """
    from texlate.xlat.client import (  # noqa: PLC0415 -- 重依赖延迟导入
        DEFAULT_BASE_URL,
        DEFAULT_MODEL,
        ChatClient,
        env_credentials,
    )
    from texlate.xlat.pipeline import (  # noqa: PLC0415
        GatewayTranslator,
        MockTranslator,
    )

    force = env_str("TEXLATE_TRANSLATOR")
    env_url, api_key, env_model, env_dialect = env_credentials()
    if mock or force == "mock":
        return MockTranslator()  # 显式干跑优先于 env 矛盾检查
    if force not in ("", "gateway"):
        typer.echo(
            f"未知 TEXLATE_TRANSLATOR={force!r}——接受 mock|gateway（缺省自动）",
            err=True,
        )
        raise typer.Exit(2)
    if force == "gateway" and not api_key:
        typer.echo(
            "TEXLATE_TRANSLATOR=gateway 需要 TEXLATE_API_KEY（缺 key 的网关翻译必败）",
            err=True,
        )
        raise typer.Exit(2)
    if not api_key:
        typer.echo(
            "未配置 TEXLATE_API_KEY——按 MockTranslator 干跑（占位译文、不触网）",
            err=True,
        )
        return MockTranslator()
    return GatewayTranslator(
        ChatClient(
            env_url or DEFAULT_BASE_URL,
            api_key,
            dialect=env_dialect,
        ),
        model or env_model or DEFAULT_MODEL,
    )
