"""SPA 静态产物定位与挂载（``web/dist`` → 包内 ``server/static/``）。

产物由 ``scripts/build-web.sh`` 拷入（gitignored 构建产物，wheel 经
pyproject ``[tool.hatch.build] artifacts`` 携带）。前端走 hash 路由
（``#/``、``#/reader/:id``、``#/settings``），``StaticFiles(html=True)``
即够，不需要 index.html fallback 路由。

开发期 ``vite build --watch`` 可设 ``TEXLATE_SPA_DIR=web/dist`` 直挂
产物目录，免拷贝。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger(__name__)

#: SPA 产物目录环境变量覆盖（dev 可直挂 ``web/dist``）
SPA_DIR_ENV = "TEXLATE_SPA_DIR"


def spa_dir() -> Path | None:
    """定位 SPA 产物目录：``TEXLATE_SPA_DIR`` > 包内 ``static/``。

    目录下无 ``index.html`` 视为未构建，返回 ``None``。
    """
    override = os.environ.get(SPA_DIR_ENV)
    if override:
        cand = Path(override).expanduser()
        if (cand / "index.html").is_file():
            return cand
        log.warning("%s=%s 下无 index.html，回退包内 static/", SPA_DIR_ENV, override)
    pkg = Path(__file__).parent / "static"
    if (pkg / "index.html").is_file():
        return pkg
    return None


def mount_spa(app: FastAPI) -> bool:
    """SPA 产物挂到 ``/``（须在全部 ``/api`` 路由注册之后调用）。

    产物缺席则不挂、返回 ``False``——API 照常可用，``/`` 保持 404。
    """
    static = spa_dir()
    if static is None:
        log.warning(
            "SPA 产物缺失：先跑 scripts/build-web.sh（或设 %s 指向产物目录）",
            SPA_DIR_ENV,
        )
        return False
    from fastapi.staticfiles import StaticFiles  # noqa: PLC0415 -- 延迟导入

    app.mount("/", StaticFiles(directory=static, html=True), name="spa")
    log.info("SPA mounted: %s", static)
    return True
