"""``endpoints`` 子命令簇：BYOK 端点档案本地命令行面（list/test/activate）。

与 ``server/endpoints.py``（数据层）/``routers/endpoints.py``（HTTP 面）
同名异义——本叶只是直读 ``<data_dir>/endpoints.json`` 的薄壳，归一化/
凭据阶梯/探针语义全在数据层（glossary §3 登记）。server 部署形态下
CLI 管的仍是本机数据目录——端点档案恰是部署方的管理通道，不做形态闸。

server 层 import 全部调用期延迟（``PLC0415``）——``cli.app`` 冷启动面
不背 httpx/fastapi 链。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import typer

from texlate.cli._common import app
from texlate.compile import toolchain

if TYPE_CHECKING:
    from texlate.server.endpoints import EndpointStore
    from texlate.server.settings import SettingsStore

endpoints_app = typer.Typer(
    help="BYOK 端点档案管理（endpoints.json：多端点回退档案库）。",
    no_args_is_help=True,
)
app.add_typer(endpoints_app, name="endpoints")

#: ``list`` 探测摘要行展示的模型 verdict 上限（超出折叠成 ``…+N``）。
_PROBE_LIST_MAX = 4


def _view() -> tuple[list[dict[str, Any]], str, EndpointStore, SettingsStore]:
    """``(profiles, active_id, EndpointStore, SettingsStore)``——三命令同数据面。

    读径投影语义：文件缺席 → settings+connections 合成表（不落盘）。
    """
    from texlate.server.endpoints import (  # noqa: PLC0415 -- 冷启动延迟
        EndpointStore,
        active_id,
    )
    from texlate.server.settings import SettingsStore  # noqa: PLC0415

    root = toolchain.data_root()
    estore = EndpointStore(root)
    sstore = SettingsStore(root)
    settings = sstore.load()
    profiles = estore.effective_profiles(settings, sstore.connections())
    return profiles, active_id(profiles, settings), estore, sstore


def _find(profiles: list[dict[str, Any]], pid: str) -> dict[str, Any] | None:
    """按 id 精确命中 profile；无 → ``None``。"""
    return next((p for p in profiles if p["id"] == pid), None)


def _cred_text(p: dict[str, Any]) -> str:
    """凭据三态展示行（与 web credText 同口径）：inline > env 名态 > 无。"""
    from texlate.textutil import env_raw  # noqa: PLC0415

    if p.get("api_key"):
        return "Key 已存"
    env = str(p.get("key_env") or "")
    if env:
        return f"env:{env}（{'已设置' if env_raw(env) else '未设置'}）"
    return "无凭据"


def _model_chip(entry: dict[str, Any]) -> str:
    """模型条目 → ``model(redirect)`` 展示名（无 redirect 只显本地名）。"""
    name = str(entry.get("model") or "")
    red = str(entry.get("redirect_model") or "")
    return f"{name}({red})" if red else name


def _probe_line(p: dict[str, Any]) -> str:
    """``last_probe`` 单行摘要；未探 → ``"未探测"``。"""
    rep = p.get("last_probe")
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


@endpoints_app.command("list")
def endpoints_list() -> None:
    """列端点档案（* = 当前活动；读径投影——文件缺席映 settings/connections）。"""
    profiles, act, estore, _sstore = _view()
    typer.echo(f"{estore.path}：{len(profiles)} 条档案")
    for p in profiles:
        mark = "*" if p["id"] == act else " "
        off = "（停用）" if not p.get("enabled") else ""
        typer.echo(f"{mark} {p['id']}  {p['label']}  {p['base_url']}{off}")
        models = (
            "、".join(_model_chip(m) for m in p["models"]) if p["models"] else "（无）"
        )
        typer.echo(f"    models: {models} | 凭据: {_cred_text(p)}")
        typer.echo(f"    探测: {_probe_line(p)}")


@endpoints_app.command("test")
def endpoints_test(pid: str) -> None:
    """两段行为探针探指定档案（凭据走四级阶梯，报告钉回 last_probe）。

    退出码：stage1 通且（无模型或至少一模型 usable）→ 0；否则 1——
    端点活而模型全灭同样是 actionable 信号。
    """
    from texlate.server.endpoints import (  # noqa: PLC0415
        credential_for,
        probe_endpoint,
    )

    profiles, _act, estore, sstore = _view()
    p = _find(profiles, pid)
    if p is None:
        typer.echo(f"profile 不存在：{pid}", err=True)
        raise typer.Exit(2)
    key, src = credential_for(p, sstore.connections())
    if not key:
        typer.echo(f"凭据：无（{src}）——无 key 端点按裸探跑", err=True)
    else:
        typer.echo(f"凭据：{src}", err=True)
    report = asyncio.run(
        probe_endpoint(
            str(p["base_url"]),
            key,
            str(p["dialect"] or "auto"),
            list(p["models"]),
        )
    )
    estore.record_probe(pid, report)
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


@endpoints_app.command("activate")
def endpoints_activate(pid: str) -> None:
    """激活 profile → settings（base_url/dialect/model[0] + 凭据面归位）。

    inline key 直写 settings；非 inline（key_env/连接槽/provider env）
    清掉 settings 里旧端点 key 让凭据阶梯接管——残留 key 发向新端点是
    exfil 事故（路由面同口径）。
    """
    profiles, _act, _estore, sstore = _view()
    p = _find(profiles, pid)
    if p is None:
        typer.echo(f"profile 不存在：{pid}", err=True)
        raise typer.Exit(2)
    updates: dict[str, Any] = {
        "base_url": p["base_url"],
        "dialect": p["dialect"],
    }
    if p["models"]:
        # 写线名（redirect 优先）——主翻译径按线名直发
        from texlate.server.endpoints import wire_model  # noqa: PLC0415

        updates["model"] = wire_model(p["models"][0])
    if p["api_key"]:
        updates["api_key"] = p["api_key"]
    else:
        updates["clear_api_key"] = True
    try:
        sstore.save(updates)
    except (TypeError, ValueError) as e:
        typer.echo(f"激活失败：{e}", err=True)
        raise typer.Exit(1) from None
    typer.echo(
        f"已切换到 {p['id']}（{p['base_url']}，model={updates.get('model', '承旧')}）"
    )
