"""endpoints 路由：端点档案读/写面 + 激活 + 两段探针。

与 ``server/endpoints.py``（数据层）/``cli/endpoints.py``（命令行面）同名异义
——本叶只是 HTTP 薄壳，schema/合并/探针语义全在数据层（glossary §3 登记）。

server 形态整面 403：端点档案枚举本身就是部署拓扑（base_url 集 +
key_env 名 + 探活历史），比 settings GET 的摘键口径更严——读写全关。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

# FastAPI 注册期 eval_str 解析端点签名注解——Request/Response 须驻运行时
from fastapi import Request, Response  # noqa: TC002
from fastapi.responses import JSONResponse

from texlate.server.endpoints import (
    MAX_MODELS_PER_PROFILE,
    active_id,
    credential_for,
    probe_endpoint,
    public_profile,
)
from texlate.server.http import _api_error, _json_error, _read_body
from texlate.server.settings import (
    server_mode,
    validate_base_url,
    validate_dialect,
    validate_model,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from texlate.server.routers.deps import AppDeps


def _endpoints_gate() -> None:
    """Server 模式端点档案面全关（settings.json/endpoints.json/env 管理）。

    比 ``_settings_write_gate`` 更严——settings GET 本地可读（摘两键），
    端点档案连读也关：profile 枚举泄漏部署方后端拓扑与 env 凭据名。
    """
    if server_mode() == "server":
        raise _api_error(
            403,
            "server 模式下端点档案由部署方管理（endpoints.json/env），API 关闭",
            "forbidden",
        )


def _view(deps: AppDeps) -> dict[str, Any]:
    """当前有效 profile 表 → API 出参（public 面 + active_id）。"""
    settings = deps.settings_store.load()
    profiles = deps.endpoints_store.effective_profiles(
        settings, deps.settings_store.connections()
    )
    return {
        "profiles": [public_profile(p) for p in profiles],
        "active_id": active_id(profiles, settings),
    }


def _validate_models(raw: object) -> list[str]:
    """请求面 models 校验：string list + 逐条 ``validate_model`` + ≤8 去重。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        msg = "models 须为 string list"
        raise TypeError(msg)
    seen: set[str] = set()
    out: list[str] = []
    for m in raw:
        if not isinstance(m, str):
            msg = "models 成员须为 string"
            raise TypeError(msg)
        uid = validate_model(m)
        if uid not in seen:
            seen.add(uid)
            out.append(uid)
    if len(out) > MAX_MODELS_PER_PROFILE:
        msg = f"models 至多 {MAX_MODELS_PER_PROFILE} 条"
        raise ValueError(msg)
    return out


def register(app: FastAPI, deps: AppDeps) -> None:  # noqa: C901, PLR0915 -- 端点面平铺
    """挂载 ``/api/endpoints*`` 端点面。"""

    @app.get("/api/endpoints")
    async def endpoints_get() -> dict[str, Any]:
        """有效 profile 表（文件在 → 文件表；缺席 → settings+connections 投影）。"""
        _endpoints_gate()
        return _view(deps)

    @app.put("/api/endpoints")
    async def endpoints_put(request: Request) -> Response:
        """整表替换写（``{"profiles": [...]}``）——``EndpointStore.save`` 归一化语义。"""
        _endpoints_gate()
        body = await _read_body(request)
        try:
            saved = await asyncio.to_thread(
                deps.endpoints_store.save, body.get("profiles")
            )
        except (TypeError, ValueError) as e:
            return _json_error(400, str(e), "invalid_request")
        settings = deps.settings_store.load()
        return JSONResponse(
            {
                "profiles": [public_profile(p) for p in saved],
                "active_id": active_id(saved, settings),
            }
        )

    @app.post("/api/endpoints/activate")
    async def endpoints_activate(request: Request) -> Response:
        """激活 profile → settings（base_url/dialect/model[0] + 凭据面归位）。

        inline key 直写 settings；非 inline（key_env/连接槽/provider env）
        带 ``clear_api_key`` 清掉旧端点 key——否则残留 key 会遮蔽
        ``resolve_auth`` 的 key_env 阶梯把旧 key 发向新端点。
        """
        _endpoints_gate()
        body = await _read_body(request)
        pid = str(body.get("id") or "")
        settings = deps.settings_store.load()
        profiles = deps.endpoints_store.effective_profiles(
            settings, deps.settings_store.connections()
        )
        p = next((x for x in profiles if x["id"] == pid), None)
        if p is None:
            return _json_error(404, f"profile 不存在：{pid}", "not_found")
        updates: dict[str, Any] = {
            "base_url": p["base_url"],
            "dialect": p["dialect"],
        }
        if p["models"]:
            updates["model"] = p["models"][0]
        if p["api_key"]:
            updates["api_key"] = p["api_key"]
        else:
            updates["clear_api_key"] = True
        try:
            await asyncio.to_thread(deps.settings_store.save, updates)
        except (TypeError, ValueError) as e:
            return _json_error(400, str(e), "invalid_request")
        return JSONResponse(deps.settings_store.public())

    @app.post("/api/endpoints/probe")
    async def endpoints_probe(request: Request) -> Response:
        """两段探针：``{id}`` 探档案条目，或裸 ``{base_url, api_key, …}`` 直探。

        id 路径凭据走 profile 四级阶梯；裸端点必须自带 ``api_key``——否则
        settings/env 里部署方凭据可被引到任意出站地址（``settings/test``
        同口径 exfil 闸）。探测完把报告钉回 ``last_probe``（文件驻留
        profile 才落；投影条目 ``record_probe`` 自然 no-op）。
        """
        _endpoints_gate()
        body = await _read_body(request)
        pid = str(body.get("id") or "")
        settings = deps.settings_store.load()
        try:
            if pid:
                profiles = deps.endpoints_store.effective_profiles(
                    settings, deps.settings_store.connections()
                )
                p = next((x for x in profiles if x["id"] == pid), None)
                if p is None:
                    return _json_error(404, f"profile 不存在：{pid}", "not_found")
                key, _src = credential_for(p, deps.settings_store.connections())
                base_url = p["base_url"]
                dialect = p["dialect"]
                models = (
                    _validate_models(body.get("models"))
                    if body.get("models") is not None
                    else list(p["models"])
                )
            else:
                base_url = validate_base_url(str(body.get("base_url") or ""))
                key = str(body.get("api_key") or "")
                if not key:
                    # 裸端点探测必须自带 key——否则 settings/env 里部署方
                    # 凭据可被引到任意出站地址（settings_test 同 exfil 闸）
                    return _json_error(
                        400, "裸端点探测须显式 api_key", "invalid_request"
                    )
                dialect = validate_dialect(str(body.get("dialect") or "auto"))
                models = _validate_models(body.get("models"))
        except (TypeError, ValueError) as e:
            return _json_error(400, str(e), "invalid_request")
        report = await probe_endpoint(base_url, key, dialect, models)
        if pid:
            await asyncio.to_thread(deps.endpoints_store.record_probe, pid, report)
        return JSONResponse(report)
