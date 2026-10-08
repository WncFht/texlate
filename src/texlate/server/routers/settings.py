"""settings 路由：public 读面 + 合并写（任务策略/外观/配额键）。

端点面全部归 ``routers/channels.py``（渠道表/路由/探针/预设）——
``/api/settings/test`` 探活与 ``/api/providers`` 预设目录已撤。
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
    server_mode,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from texlate.server.routers.deps import AppDeps

#: server 形态 ``GET /api/settings`` 摘键：前端不消费且泄漏部署拓扑
#: （``glossary_dir`` 宿主文件系统路径、``cors_origins`` 部署方跨域策略）。
#: ``quota_*`` 保留——多租户下配额上限是租户自身策略面，非拓扑。
_SERVER_SETTINGS_HIDDEN = frozenset({"cors_origins", "glossary_dir"})


def _settings_write_gate() -> None:
    """Server 模式 settings 写路径关闭（§4.1：PUT settings 是本地单机默认形态）。

    多租户形态下 settings.json 是部署方全局配置——租户可写即可改
    配额/CORS/glossary_dir 越部署方管理面。server 形态的写管理走
    settings.json 文件 / env / CLI。
    """
    if server_mode() == "server":
        raise _api_error(
            403,
            "server 模式下 settings 由部署方管理（settings.json/env），API 写关闭",
            "forbidden",
        )


def register(app: FastAPI, deps: AppDeps) -> None:
    """挂载 settings 端点。"""

    @app.get("/api/settings")
    async def settings_get() -> dict[str, Any]:
        """public_settings：server 摘部署拓扑键。"""
        data = deps.settings_store.public()
        if server_mode() == "server":
            for k in _SERVER_SETTINGS_HIDDEN:
                data.pop(k, None)
        return data

    @app.put("/api/settings")
    async def settings_put(request: Request) -> Response:
        """合并更新（0600 原子写）。

        键白名单 = ``SettingsStore.FIELDS``；未识别键不落盘——在响应
        ``ignored`` 字段原样回显：静默丢弃的 200 会让调用方以为写入
        生效（前端可凭 ``ignored`` 出告警）。
        """
        _settings_write_gate()
        body = await _read_body(request)
        allowed = set(SettingsStore.FIELDS)
        ignored = sorted(set(body) - allowed)
        for k in ignored:
            body.pop(k)
        try:
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
