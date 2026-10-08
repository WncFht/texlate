"""channels 路由：渠道读/写面 + 路由选择 + 两段探针 + 预设目录。

与 ``server/channels.py``（数据层）/``cli/channels.py``（命令行面）同名异义
——本叶只是 HTTP 薄壳，schema/合并/探针/路由语义全在数据层
（glossary §3 登记）。

server 形态整面 403：渠道枚举本身就是部署拓扑（base_url 集 +
key_env 名 + 探活历史），比 settings GET 的摘键口径更严——读写全关。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

# FastAPI 注册期 eval_str 解析端点签名注解——Request/Response 须驻运行时
from fastapi import Request, Response  # noqa: TC002
from fastapi.responses import JSONResponse

from texlate.server.channels import (
    CHANNEL_PRESETS,
    _check_model_names,
    _check_models,
    active_channel_id,
    credential_for,
    local_model_name,
    probe_channel,
    public_channel,
)
from texlate.server.http import _api_error, _json_error, _read_body
from texlate.server.settings import (
    server_mode,
    validate_base_url,
    validate_dialect,
)
from texlate.textutil import env_raw

if TYPE_CHECKING:
    from fastapi import FastAPI

    from texlate.server.routers.deps import AppDeps


def _channels_gate() -> None:
    """Server 模式渠道面全关（channels.json/env 由部署方管理）。

    比 ``_settings_write_gate`` 更严——settings GET 本地可读（摘两键），
    渠道连读也关：渠道枚举泄漏部署方后端拓扑与 env 凭据名。
    """
    if server_mode() == "server":
        raise _api_error(
            403,
            "server 模式下渠道由部署方管理（channels.json/env），API 关闭",
            "forbidden",
        )


def _view(deps: AppDeps) -> dict[str, Any]:
    """当前有效渠道表 + 路由小节 → API 出参（public 面 + active_id 兼容位）。"""
    settings = deps.settings_store.load()
    channels = deps.channels_store.effective_channels(
        settings, deps.settings_store.connections()
    )
    data = deps.channels_store.load()
    return {
        "channels": [public_channel(c) for c in channels],
        "route": data["route"],
        "active_id": active_channel_id(channels, settings),
    }


def register(app: FastAPI, deps: AppDeps) -> None:  # noqa: C901, PLR0915 -- 渠道面平铺
    """挂载 ``/api/channels*`` 渠道面。"""

    @app.get("/api/channels")
    async def channels_get() -> dict[str, Any]:
        """有效渠道表（channels.json 在 → 文件表；缺席 → settings+connections 投影）。"""
        _channels_gate()
        return _view(deps)

    @app.put("/api/channels")
    async def channels_put(request: Request) -> Response:
        """整表替换写（``{"channels": [...], "route": {...}}``）——``ChannelStore.save`` 归一化语义。"""
        _channels_gate()
        body = await _read_body(request)
        try:
            saved = await asyncio.to_thread(
                deps.channels_store.save,
                body.get("channels"),
                body.get("route"),
            )
        except (TypeError, ValueError) as e:
            return _json_error(400, str(e), "invalid_request")
        settings = deps.settings_store.load()
        return JSONResponse(
            {
                "channels": [public_channel(c) for c in saved["channels"]],
                "route": saved["route"],
                "active_id": active_channel_id(saved["channels"], settings),
            }
        )

    @app.post("/api/channels/route")
    async def channels_route(request: Request) -> Response:
        """路由选择写（``{channel_id, model}``）——渠道表本体不动，只改 route 小节。"""
        _channels_gate()
        body = await _read_body(request)
        try:
            saved = await asyncio.to_thread(
                deps.channels_store.save,
                deps.channels_store.load()["channels"],
                {"channel_id": body.get("channel_id"), "model": body.get("model")},
            )
        except (TypeError, ValueError) as e:
            return _json_error(400, str(e), "invalid_request")
        settings = deps.settings_store.load()
        return JSONResponse(
            {
                "channels": [public_channel(c) for c in saved["channels"]],
                "route": saved["route"],
                "active_id": active_channel_id(saved["channels"], settings),
            }
        )

    @app.get("/api/channels/presets")
    async def channels_presets() -> dict[str, Any]:
        """服务商预设目录：新建渠道表单预填面（key 只报 env 是否已设置）。"""
        _channels_gate()
        return {
            "presets": [
                {**p, "has_env_key": bool(env_raw(str(p.get("key_env") or "")))}
                for p in CHANNEL_PRESETS
            ]
        }

    @app.post("/api/channels/probe")
    async def channels_probe(request: Request) -> Response:
        """两段探针：``{id}`` 探渠道条目，或裸 ``{base_url, api_key, …}`` 直探。

        id 路径凭据走渠道四级阶梯；裸端点必须自带 ``api_key``——否则
        settings/env 里部署方凭据可被引到任意出站地址（exfil 闸）。
        探测完把报告钉回 ``last_probe``（文件驻留渠道才落；投影条目
        ``record_probe`` 自然 no-op）。
        """
        _channels_gate()
        body = await _read_body(request)
        cid = str(body.get("id") or "")
        settings = deps.settings_store.load()
        try:
            if cid:
                channels = deps.channels_store.effective_channels(
                    settings, deps.settings_store.connections()
                )
                c = next((x for x in channels if x["id"] == cid), None)
                if c is None:
                    return _json_error(404, f"渠道不存在：{cid}", "not_found")
                key, _src = credential_for(c, deps.settings_store.connections())
                base_url = c["base_url"]
                protocol = c["protocol"]
                if body.get("models") is not None:
                    # 子集探测按模型名匹配渠道条目（redirect 随档）；档外
                    # 名字按无 redirect 直探——测未入档模型也合法
                    by_local = {local_model_name(m): m for m in c["models"]}
                    models = [
                        by_local.get(
                            n,
                            {
                                "model": n,
                                "redirect_model": "",
                                "enabled": True,
                                "max_concurrency": None,
                            },
                        )
                        for n in _check_model_names(body.get("models"))
                    ]
                else:
                    models = list(c["models"])
            else:
                base_url = validate_base_url(str(body.get("base_url") or ""))
                key = str(body.get("api_key") or "")
                if not key:
                    # 裸端点探测必须自带 key——否则 settings/env 里部署方
                    # 凭据可被引到任意出站地址（settings_test 同 exfil 闸）
                    return _json_error(
                        400, "裸端点探测须显式 api_key", "invalid_request"
                    )
                protocol = validate_dialect(str(body.get("protocol") or "auto"))
                models = _check_models(body.get("models"))
        except (TypeError, ValueError) as e:
            return _json_error(400, str(e), "invalid_request")
        report = await probe_channel(base_url, key, protocol, models)
        if cid:
            await asyncio.to_thread(deps.channels_store.record_probe, cid, report)
        return JSONResponse(report)
