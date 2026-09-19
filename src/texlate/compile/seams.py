"""compile 层唯一 monkeypatch 面（``server.worker.seams`` 同款收口）。

compile 层「测试可替换件」一律在调用点 ``seams.X`` 查名——
``monkeypatch.setattr("texlate.compile.seams.X", …)`` 即拦截全部
经本缝路由的消费点。

全名经 ``__getattr__`` 惰性回指既有锚位模块（不 eager bind）——
patch 打旧锚（``toolchain.find_tool``/``repair.fixloop`` 等）与打
``seams.X`` 同拦；``setattr`` 落 seams 成真 attr 后 ``__getattr__``
不再被调、该名固化（同套件再 patch 旧锚不回传——锚位收敛以
``seams.X`` 为准）。

``engine.X`` 叶侧锚是独立平面：``engine/__init__`` 经
``from texlate.compile.seams import`` eager 回引，`_eng.` 回查的
叶文件只认 engine 包 attr——patch ``engine.X`` 拦叶消费点、
``seams.X`` 拦 seams 路由消费点，两平面不互通（叶文件未改前
``engine.X`` 是唯一确定性叶锚）。``sandbox``/``cli``/``upload``
各模块自带锚位同理——本缝只覆盖经其路由的消费点。
"""

from __future__ import annotations

import importlib
from typing import Final

#: 缝名 → 锚位模块。惰性回指保旧锚 patch 语义（``setattr`` 落锚位模块
#: 即被消费点拿到）；eager bind 既丢这层语义又引 import 环
#: （repair→seams→repair、engine→seams→toolchain 两路）。
_SOURCES: Final = {
    "download_allowed": "texlate.compile.toolchain",
    "ensure_tectonic": "texlate.compile.toolchain",
    "find_managed": "texlate.compile.toolchain",
    "find_tool": "texlate.compile.toolchain",
    "fixloop": "texlate.repair",
    "install_tectonic": "texlate.compile.toolchain",
    "precheck_pass": "texlate.repair",
    "resolve_tool": "texlate.compile.toolchain",
    "run_process": "texlate.compile.proc",
    "tectonic_version": "texlate.compile.toolchain",
}

# 全名皆 ``__getattr__`` 惰性回指（``_SOURCES`` 单源）——F822 一律误报。
__all__ = [
    "download_allowed",  # noqa: F822
    "ensure_tectonic",  # noqa: F822
    "find_managed",  # noqa: F822
    "find_tool",  # noqa: F822
    "fixloop",  # noqa: F822
    "install_tectonic",  # noqa: F822
    "precheck_pass",  # noqa: F822
    "resolve_tool",  # noqa: F822
    "run_process",  # noqa: F822
    "tectonic_version",  # noqa: F822
]


def __getattr__(name: str) -> object:
    # 回指锚位模块当前 attr——旧锚 patch（setattr 落锚位模块）与新锚
    # patch（setattr 落本模块成真 attr，遮蔽本函数）均拦 seams 消费点。
    source = _SOURCES.get(name)
    if source is None:
        raise AttributeError(name)
    return getattr(importlib.import_module(source), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_SOURCES))
