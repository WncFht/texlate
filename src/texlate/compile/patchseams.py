"""compile 层唯一 monkeypatch 面（patch 缝注册表；``server.worker.seams`` 同款收口）。

compile 层「测试可替换件」一律在调用点 ``patchseams.X`` 查名——
``monkeypatch.setattr("texlate.compile.patchseams.X", …)`` 即拦截全部
经本缝路由的消费点。

全名经 ``__getattr__`` 惰性回指既有锚位模块（不 eager bind）——
patch 打锚位（``toolchain.find_tool``/``repair.fixloop`` 等）与打
``patchseams.X`` 同拦；``setattr`` 落 patchseams 成真 attr 后
``__getattr__`` 不再被调、该名固化（同套件再 patch 锚位不回传——
锚位收敛以 ``patchseams.X`` 为准）。

``engine.X`` 叶侧锚是独立平面：``engine/__init__`` 经
``from texlate.compile.patchseams import`` eager 回引，`_eng.` 回查的
叶文件只认 engine 包 attr——patch ``engine.X`` 拦叶消费点、
``patchseams.X`` 拦 patchseams 路由消费点，两平面不互通（叶文件未改前
``engine.X`` 是唯一确定性叶锚）。``sandbox``/``cli``/``upload``
各模块自带锚位同理——本缝只覆盖经其路由的消费点。

名件辨（刻意异名，跨层不互替）：``texlate.server.worker.seams`` 是
worker 层同款 monkeypatch 面，留用 ``seams`` 本名（机制异——彼件
eager bind + 两名惰性回指，本件全名 ``_SOURCES`` map 惰性回指）；
``texlate.compile._docseams`` 是 docclass 注入缝几何原语，名近义更异。
"""

from __future__ import annotations

import importlib
from typing import Final

#: 缝名 → 锚位模块。惰性回指保锚位 patch 语义（``setattr`` 落锚位模块
#: 即被消费点拿到）；eager bind 既丢这层语义又引 import 环
#: （repair→patchseams→repair、engine→patchseams→toolchain 两路）。
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

# 全名皆 ``__getattr__`` 惰性回指——``__all__`` 由 ``_SOURCES`` 键派生
# （单源零漂移；计算值天然躲过 F822 静态点名）。
__all__ = sorted(_SOURCES)  # noqa: PLE0605 -- ``_SOURCES`` 派生的计算值


def __getattr__(name: str) -> object:
    # 回指锚位模块当前 attr——锚位 patch（setattr 落锚位模块）与缝侧
    # patch（setattr 落本模块成真 attr，遮蔽本函数）均拦 patchseams 消费点。
    source = _SOURCES.get(name)
    if source is None:
        raise AttributeError(name)
    return getattr(importlib.import_module(source), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_SOURCES))
