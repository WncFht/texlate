"""路由叶包：``register_routers`` 把各域 ``/api`` 端点挂上 app。

原 ``create_app`` ~25 端点按真实域聚类成叶：``tasks``（建任务 + 生命周期+
SSE）、``compat``（hjfy 轮询协议面）、``files``、``upload``、``share``、
``meta``（health）、``reader``、``settings``、``discover``（alphaXiv
公共面只读代理）。共享装配经 ``deps.AppDeps`` 注入；请求层纯件
（multipart/同源/错误面）在 ``texlate.server.http``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.server.routers import (
    compat,
    discover,
    endpoints,
    files,
    meta,
    reader,
    refs,
    settings,
    share,
    srccut,
    tasks,
    upload,
)
from texlate.server.routers.deps import AppDeps

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = ["AppDeps", "register_routers"]


def register_routers(app: FastAPI, deps: AppDeps) -> None:
    """按域注册全部 ``/api`` 端点。

    各叶路由模式互不重叠（literal 前缀 + 段数互斥），注册顺序与匹配
    语义无关；排序沿用原 ``create_app`` 内端点出现序便于对读。
    """
    tasks.register(app, deps)
    compat.register(app, deps)
    files.register(app, deps)
    upload.register(app, deps)
    share.register(app, deps)
    meta.register(app, deps)
    reader.register(app, deps)
    settings.register(app, deps)
    endpoints.register(app, deps)
    discover.register(app, deps)
    refs.register(app, deps)
    srccut.register(app, deps)
