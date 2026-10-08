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
    """channels.json 渠道表 + 路由小节 + 路由决议 → API 出参（public 面）。

    ``active_id``/``active_model`` 是 ``resolve_route()`` 决议结果
    （冷却过滤后的实际生效臂），与 ``route`` 小节的期望选择分开报。
    ``cooling`` 是渠道级冷却中的 id 列表——前端据此解释决议与钉选
    不一致（pin 的渠道冷却时顺位跳过/无路由）。
    """
    # 函数级导入：取的是模块当前属性，测试 monkeypatch 模块级
    # ``cooldowns`` 换空表后本处读到的是新表
    from texlate.server.channels import cooldowns  # noqa: PLC0415

    data = deps.channels_store.load()
    resolved = deps.channels_store.resolve_route()
    return {
        "channels": [public_channel(c) for c in data["channels"]],
        "route": data["route"],
        "active_id": resolved["channel"]["id"] if resolved else "",
        "active_model": resolved["wire_model"] if resolved else "",
        "cooling": [
            c["id"] for c in data["channels"] if cooldowns.is_cooled(str(c["id"]), "")
        ],
    }


def register(app: FastAPI, deps: AppDeps) -> None:  # noqa: C901 -- 渠道面平铺
    """挂载 ``/api/channels*`` 渠道面。"""

    @app.get("/api/channels")
    async def channels_get() -> dict[str, Any]:
        """渠道表 + 路由小节 + 决议（channels.json 缺席时 ``bootstrap`` 已物化）。"""
        _channels_gate()
        return _view(deps)

    @app.put("/api/channels")
    async def channels_put(request: Request) -> Response:
        """整表替换写（``{"channels": [...], "route": {...}}``）——``ChannelStore.save`` 归一化语义。"""
        _channels_gate()
        body = await _read_body(request)
        try:
            await asyncio.to_thread(
                deps.channels_store.save,
                body.get("channels"),
                body.get("route"),
            )
        except (TypeError, ValueError) as e:
            return _json_error(400, str(e), "invalid_request")
        return JSONResponse(_view(deps))

    @app.post("/api/channels/route")
    async def channels_route(request: Request) -> Response:
        """路由选择写（``{channel_id, model}``）——渠道表本体不动，只改 route 小节。"""
        _channels_gate()
        body = await _read_body(request)
        try:
            await asyncio.to_thread(
                deps.channels_store.save,
                deps.channels_store.load()["channels"],
                {"channel_id": body.get("channel_id"), "model": body.get("model")},
            )
        except (TypeError, ValueError) as e:
            return _json_error(400, str(e), "invalid_request")
        return JSONResponse(_view(deps))

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

        id 路径凭据走渠道三级阶梯；裸端点必须自带 ``api_key``——否则
        env 里部署方凭据可被引到任意出站地址（exfil 闸）。
        探测完把报告钉回 ``last_probe``。
        """
        _channels_gate()
        body = await _read_body(request)
        cid = str(body.get("id") or "")
        try:
            if cid:
                channels = deps.channels_store.load()["channels"]
                c = next((x for x in channels if x["id"] == cid), None)
                if c is None:
                    return _json_error(404, f"渠道不存在：{cid}", "not_found")
                key, _src = credential_for(c)
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
                    # 裸端点探测必须自带 key——否则 env 里部署方
                    # 凭据可被引到任意出站地址（exfil 闸）
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
