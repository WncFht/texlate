"""settings 路由（§4 BYOK）：public 读面 + 合并写 + 探活 + provider 预设。

server 形态写路径由 ``_settings_write_gate`` 关闭（settings.json/env 管理）。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

# FastAPI 注册期 eval_str 解析端点签名注解——Request/Response 须驻运行时
from fastapi import Request, Response  # noqa: TC002
from fastapi.responses import JSONResponse

from texlate.server.http import _api_error, _json_error, _read_body
from texlate.server.settings import (
    SettingsStore,
    provider_presets,
    scrub,
    server_mode,
    validate_base_url,
    validate_dialect,
)
from texlate.xlat.client import ChatClient

if TYPE_CHECKING:
    from fastapi import FastAPI

    from texlate.server.routers.deps import AppDeps

#: server 模式 ``GET /api/settings`` 摘键：前端不消费且泄漏部署拓扑
#: （``glossary_dir`` 宿主文件系统路径、``cors_origins`` 部署方跨域策略）。
#: ``quota_*`` 保留——多租户下配额上限是租户自身策略面，非拓扑。
_SERVER_SETTINGS_HIDDEN = frozenset({"cors_origins", "glossary_dir"})


def _settings_write_gate() -> None:
    """Server 模式 settings 写路径关闭（§4.1：PUT settings 是本地单机默认形态）。

    多租户形态下 settings.json 是部署方全局配置——租户可写即可改
    ``base_url`` 截获他租户 header key、改配额/CORS/glossary_dir；
    ``settings/test`` 是同级别的出站探活 oracle。server 形态的写管理
    走 settings.json 文件 / env / CLI ``--configure``。
    """
    if server_mode() == "server":
        raise _api_error(
            403,
            "server 模式下 settings 由部署方管理（settings.json/env），API 写关闭",
            "forbidden",
        )


def register(app: FastAPI, deps: AppDeps) -> None:  # noqa: C901 -- 端点面平铺
    """挂载 settings/provider 端点（§4）。"""

    @app.get("/api/settings")
    async def settings_get() -> dict[str, Any]:
        """public_settings：key 剥壳只给 ``has_api_key``；server 摘部署拓扑键。"""
        data = deps.settings_store.public()
        if server_mode() == "server":
            for k in _SERVER_SETTINGS_HIDDEN:
                data.pop(k, None)
        return data

    @app.put("/api/settings")
    async def settings_put(request: Request) -> Response:
        """合并更新（0600 原子写 + connections 分槽）。

        键白名单 = ``SettingsStore.FIELDS`` + ``clear_api_key``/``has_api_key``
        两个伪字段（出参回显/显式控制）。未识别键不落盘——在响应
        ``ignored`` 字段原样回显：静默丢弃的 200 会让调用方以为写入
        生效（前端可凭 ``ignored`` 出告警）。
        """
        _settings_write_gate()
        body = await _read_body(request)
        allowed = set(SettingsStore.FIELDS) | {"clear_api_key", "has_api_key"}
        ignored = sorted(set(body) - allowed)
        for k in ignored:
            body.pop(k)
        try:
            # save 内含同步 httpx 探活（timeout 不盖 DNS getaddrinfo，
            # 死 DNS 网络可卡数十秒）——to_thread 卸载防冻结事件循环；
            # merge 串行语义由 SettingsStore._save_lock 接管
            await asyncio.to_thread(deps.settings_store.save, body)
        except (TypeError, ValueError) as e:
            # 字段值类型错（concurrency 收 None/dict/list 时 int() TypeError）
            # 与校验错同归 400——非数值输入是客户端错误非服务端故障
            return _json_error(400, str(e), "invalid_request")
        resp = deps.settings_store.public()
        if ignored:
            resp["ignored"] = ignored
        return JSONResponse(resp)

    @app.post("/api/settings/test")
    async def settings_test(request: Request) -> Response:
        """探活配置端点：body 可带覆盖值；错误信息先过 scrub。"""
        _settings_write_gate()
        body = await _read_body(request)
        if body.get("base_url") and not body.get("api_key"):
            # 跨槽组合即已存 key 被打向任意出站地址的 exfil oracle——
            # 与 settings.save 的「新槽按新 base_url 查 key」同设计。
            return _json_error(400, "覆盖 base_url 须同给 api_key", "invalid_request")
        cur = deps.settings_store.load()
        base_url = str(body.get("base_url") or cur["base_url"])
        api_key = str(body.get("api_key") or cur["api_key"])
        model = str(body.get("model") or cur["model"])
        dialect = str(body.get("dialect") or cur.get("dialect") or "auto")
        try:
            base_url = validate_base_url(base_url)
            dialect = validate_dialect(dialect)
        except ValueError as e:
            return _json_error(400, str(e), "invalid_request")
        client = ChatClient(base_url, api_key, dialect=dialect)
        try:
            models = await client.list_models()
        except Exception as e:  # noqa: BLE001 -- 探活失败面收敛为 ok:false
            # ``GET /v1/models`` 缺席（responses-only 反代等异形端点）≠ 配置坏
            # ——按生效方言做一次最小 chat 探活兜底，探活也败才报失败
            fm = await client.probe_model(model)
            if not fm.probe_ok:
                detail = scrub(fm.probe_error or str(e), api_key)
                return JSONResponse({"ok": False, "detail": detail})
            return JSONResponse(
                {"ok": True, "models": [], "model": model, "probe": True}
            )
        finally:
            await client.aclose()
        return JSONResponse({"ok": True, "models": models[:50], "model": model})

    @app.get("/api/providers")
    async def providers() -> dict[str, Any]:
        """列 provider 预设清单；server 摘 ``has_env_key``（部署方 env 凭据面）。"""
        presets = provider_presets(deps.settings_store.load())
        if server_mode() == "server":
            for p in presets:
                p.pop("has_env_key", None)
        return {"providers": presets}
