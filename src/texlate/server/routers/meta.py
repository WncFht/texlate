"""meta 路由：``/api/health`` 探活（local 深检编译器面 + server db/队列深度）。"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from texlate import __version__
from texlate.compile.toolchain import find_tool, resolve_tool
from texlate.server.http import _BUILD_COMMIT, _STARTED_AT
from texlate.server.settings import server_mode
from texlate.server.store import StoreError

if TYPE_CHECKING:
    from fastapi import FastAPI

    from texlate.server.routers.deps import AppDeps

log = logging.getLogger(__name__)


def register(app: FastAPI, deps: AppDeps) -> None:
    """挂载 meta 端点。"""

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        """``{ok}`` 探活最小集；server 附加 ``db``/``queue_depth``；local 附加 ``version/commit/started_at/compilers/data_dir``。"""
        if server_mode() == "server":
            # 深度探活：db=真实 SELECT 探测（queued_rows 顺带产出队列深度），
            # 探挂只降 db=False 不 503——健康面只报不掩
            db_ok = True
            queue_depth: int | None = None
            try:
                queue_depth = len(deps.store.queued_rows())
            except (StoreError, sqlite3.Error) as e:
                log.warning("health db probe failed: %s", e)
                db_ok = False
            return {"ok": True, "db": db_ok, "queue_depth": queue_depth}
        return {
            "ok": True,
            "version": __version__,
            "commit": _BUILD_COMMIT,
            "started_at": _STARTED_AT,
            "compilers": {
                "tectonic": resolve_tool("tectonic") is not None,
                "xelatex": find_tool("xelatex") is not None,
                "babeldoc": (deps.babeldoc or find_tool("babeldoc")) is not None,
            },
            "data_dir": str(deps.root),
        }
