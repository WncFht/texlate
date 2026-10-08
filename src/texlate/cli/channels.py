"""``channels`` 子命令簇：BYOK 渠道管理本地命令行面（list/test/route）。

与 ``server/channels.py``（数据层）/``routers/channels.py``（HTTP 面）
同名异义——本叶只是直读 ``<data_dir>/channels.json`` 的薄壳，归一化/
凭据阶梯/探针/路由语义全在数据层（glossary §3 登记）。server 部署形态下
CLI 管的仍是本机数据目录——渠道恰是部署方的管理通道，不做形态闸。

server 层 import 全部调用期延迟（``PLC0415``）——``cli.app`` 冷启动面
不背 httpx/fastapi 链。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, Any

import typer

from texlate.cli._common import app
from texlate.compile import toolchain

if TYPE_CHECKING:
    from texlate.server.channels import ChannelStore
    from texlate.server.settings import SettingsStore

channels_app = typer.Typer(
    help="BYOK 渠道管理（channels.json：渠道 + 路由 + 优先级 + 并发上限）。",
    no_args_is_help=True,
)
app.add_typer(channels_app, name="channels")

#: ``list`` 探测摘要行展示的模型 verdict 上限（超出折叠成 ``…+N``）。
_PROBE_LIST_MAX = 4


def _view() -> tuple[list[dict[str, Any]], dict[str, str], ChannelStore, SettingsStore]:
    """``(channels, route, ChannelStore, SettingsStore)``——三命令同数据面。

    读径投影语义：文件缺席 → settings+connections 合成表（不落盘）。
    """
    from texlate.server.channels import ChannelStore  # noqa: PLC0415 -- 冷启动延迟
    from texlate.server.settings import SettingsStore  # noqa: PLC0415

    root = toolchain.data_root()
    cstore = ChannelStore(root)
    sstore = SettingsStore(root)
    settings = sstore.load()
    channels = cstore.effective_channels(settings, sstore.connections())
    return channels, cstore.load()["route"], cstore, sstore


def _find(channels: list[dict[str, Any]], cid: str) -> dict[str, Any] | None:
    """按 id 精确命中渠道；无 → ``None``。"""
    return next((c for c in channels if c["id"] == cid), None)


def _cred_text(c: dict[str, Any]) -> str:
    """凭据三态展示行：inline > env 名态 > 无。"""
    from texlate.textutil import env_raw  # noqa: PLC0415

    if c.get("api_key"):
        return "Key 已存"
    env = str(c.get("key_env") or "")
    if env:
        return f"env:{env}（{'已设置' if env_raw(env) else '未设置'}）"
    return "无凭据"


def _model_chip(entry: dict[str, Any]) -> str:
    """模型条目 → ``model(redirect)`` 展示名（无 redirect 只显本地名）。"""
    name = str(entry.get("model") or "")
    red = str(entry.get("redirect_model") or "")
    return f"{name}({red})" if red else name


def _probe_line(c: dict[str, Any]) -> str:
    """``last_probe`` 单行摘要；未探 → ``"未探测"``。"""
    rep = c.get("last_probe")
    if not isinstance(rep, dict):
        return "未探测"
    at = str(rep.get("at") or "")[:16].replace("T", " ")
    s1 = rep.get("stage1") or {}
    parts = [f"stage1={s1.get('verdict', '?')}"]
    models = rep.get("models") or {}
    parts.extend(
        f"{uid}={m.get('verdict', '?')}"
        for uid, m in list(models.items())[:_PROBE_LIST_MAX]
    )
    if len(models) > _PROBE_LIST_MAX:
        parts.append(f"…+{len(models) - _PROBE_LIST_MAX}")
    return f"{at} " + " ".join(parts) if at else " ".join(parts)


@channels_app.command("list")
def channels_list() -> None:
    """列渠道表（按 priority 降序；读径投影——文件缺席映 settings/connections）。"""
    channels, route, cstore, _sstore = _view()
    typer.echo(f"{cstore.path}：{len(channels)} 条渠道")
    typer.echo(
        f"route: channel_id={route['channel_id']}  model={route['model'] or '（未选）'}"
    )
    for c in sorted(channels, key=lambda x: -int(x["priority"])):
        routed = "→" if c["id"] == route["channel_id"] else " "
        off = "（停用）" if not c.get("enabled") else ""
        cap = c.get("max_concurrency")
        cap_s = f" cap={cap}" if cap else ""
        typer.echo(
            f"{routed} {c['id']}  p{c['priority']}  {c['name']}  {c['base_url']}{off}{cap_s}"
        )
        models = (
            "、".join(_model_chip(m) for m in c["models"]) if c["models"] else "（无）"
        )
        typer.echo(f"    models: {models} | 凭据: {_cred_text(c)}")
        typer.echo(f"    探测: {_probe_line(c)}")


@channels_app.command("test")
def channels_test(cid: str) -> None:
    """两段行为探针探指定渠道（凭据走四级阶梯，报告钉回 last_probe）。

    退出码：stage1 通且（无模型或至少一模型 usable）→ 0；否则 1——
    渠道活而模型全灭同样是 actionable 信号。
    """
    from texlate.server.channels import (  # noqa: PLC0415
        credential_for,
        probe_channel,
    )

    channels, _route, cstore, sstore = _view()
    c = _find(channels, cid)
    if c is None:
        typer.echo(f"渠道不存在：{cid}", err=True)
        raise typer.Exit(2)
    key, src = credential_for(c, sstore.connections())
    if not key:
        typer.echo(f"凭据：无（{src}）——无 key 渠道按裸探跑", err=True)
    else:
        typer.echo(f"凭据：{src}", err=True)
    report = asyncio.run(
        probe_channel(
            str(c["base_url"]),
            key,
            str(c["protocol"] or "auto"),
            list(c["models"]),
        )
    )
    cstore.record_probe(cid, report)
    s1 = report["stage1"]
    typer.echo(
        f"stage1: {s1['verdict']}" + (f"——{s1['detail']}" if s1.get("detail") else "")
    )
    if s1.get("models"):
        typer.echo(f"  清单 {len(s1['models'])} 条（截断至 50）")
    usable = 0
    for uid, m in (report.get("models") or {}).items():
        line = f"  {uid}: {m['verdict']} {m.get('latency_s', 0)}s"
        if m.get("listed") is False:
            line += "（不在清单）"
        if m.get("detail"):
            line += f"——{m['detail']}"
        typer.echo(line)
        usable += m["verdict"] == "usable"
    ok_stage1 = s1["verdict"] in ("ok", "no_models_dir")
    if ok_stage1 and (not report.get("models") or usable):
        return
    raise typer.Exit(1)


@channels_app.command("route")
def channels_route(
    cid: Annotated[str, typer.Argument(help="渠道 id 或 auto")] = "",
    model: Annotated[str, typer.Argument(help="模型本地名（缺省承旧）")] = "",
) -> None:
    """路由选择：``route auto`` 回自动、``route <channel_id> [model]`` 钉渠道（+模型）。

    不给参数只显示当前 route。渠道表本体不动——只写 ``route`` 小节
    （``ChannelStore.save`` 的 route 校验臂）。
    """
    channels, route, cstore, _sstore = _view()
    if not cid:
        typer.echo(
            f"route: channel_id={route['channel_id']}  model={route['model'] or '（未选）'}"
        )
        return
    if cid != "auto" and _find(channels, cid) is None:
        typer.echo(f"渠道不存在：{cid}", err=True)
        raise typer.Exit(2)
    try:
        saved = cstore.save(
            cstore.load()["channels"],
            {"channel_id": cid, "model": model or route["model"]},
        )
    except (TypeError, ValueError) as e:
        typer.echo(f"路由失败：{e}", err=True)
        raise typer.Exit(1) from None
    r = saved["route"]
    typer.echo(
        f"route → channel_id={r['channel_id']}  model={r['model'] or '（未选）'}"
    )
