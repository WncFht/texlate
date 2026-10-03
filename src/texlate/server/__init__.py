"""Web 服务层：FastAPI + SSE + SQLite 任务队列（M3，2026-09-15-web-layer.md §2-§4）。

``import texlate.server`` 保持轻依赖——``create_app``/``main`` 走 PEP 562
``__getattr__`` 延迟导入（fastapi 等大件只在真用时进场，保 CLI 冷启动）；
store/events/settings/worker 子模块本体不依赖 fastapi，可直接 import。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.server.__main__ import main
    from texlate.server.app import create_app

__all__ = ["create_app", "main"]


def __getattr__(name: str) -> object:
    """``create_app``/``main`` 首用时才 import fastapi 链（§M3 轻依赖纪律）。"""
    if name == "create_app":
        from texlate.server.app import create_app  # noqa: PLC0415 -- 延迟导入即本意

        return create_app
    if name == "main":
        from texlate.server.__main__ import main  # noqa: PLC0415 -- 同上

        return main
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
