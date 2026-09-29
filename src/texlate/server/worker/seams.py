"""worker 包唯一 monkeypatch 面（原 ``__init__`` noqa-F401 缝 + ``_w`` 包回查的收口）。

worker 子模块对一切「测试可替换件」一律在调用点 ``seams.X`` 查名——
``monkeypatch.setattr("texlate.server.worker.seams.X", …)`` 即拦截全部消费点。
``__init__.py`` 再出口同名供直读面（``texlate.server.worker.X`` 仍解析，
但 patch 必须打到本模块）。

同名件辨：``texlate.compile.seams`` 是 compile 层同款 monkeypatch 面
（机制异——彼件全名经 ``_SOURCES`` map 惰性 ``__getattr__`` 回指，
本件 eager bind + 两名惰性回指）；``texlate.compile._docseams`` 是
docclass 注入缝几何原语，名近义更异。三者跨包/跨域不互替。
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from texlate.align import build_alignment
from texlate.arxiv.fetch import Fetcher, acquire_source
from texlate.arxiv.html import fetch_html, marked_html, parse_arxiv_html
from texlate.arxiv.meta import fetch_metadata
from texlate.compile.engine import engine_for, route_project
from texlate.compile.probe import target_probe
from texlate.share import index_lookup
from texlate.xlat.glossary import user_glossary_path as _user_glossary_path

from ._common import _aclose_clients

if TYPE_CHECKING:
    from pathlib import Path

#: 心跳间隔（updated_at 供 SSE/列表页判活）
_HEARTBEAT_S = 5.0

__all__ = [
    "USER_GLOSSARY_PATH",  # noqa: F822 -- __getattr__ 惰性回指 canonical
    "_HEARTBEAT_S",
    "Fetcher",
    "_aclose_clients",
    "acquire_source",
    "build_alignment",
    "engine_for",
    "fetch_html",
    "fetch_metadata",
    "index_lookup",
    "marked_html",
    "parse_arxiv_html",
    "route_project",
    "share_pack_publish",  # noqa: F822 -- __getattr__ 惰性回指 .share
    "target_probe",
    "user_glossary_path",
]


def user_glossary_path() -> Path:
    """``xlat.glossary.user_glossary_path`` 的 seams 补丁面（canonical 名单源）。

    读的是本模块 ``USER_GLOSSARY_PATH`` 属性——``seams.USER_GLOSSARY_PATH``
    setattr 补丁（conftest 钉缺席 / 用例钉指定文件）逐调用生效；未补丁时
    经下方 ``__getattr__`` 兼容名回落 canonical 的 env 现算路径（与
    ``xlat.glossary._default_user_path`` 同式，``Glossary.load`` 缺省口径）。
    """
    return sys.modules[__name__].USER_GLOSSARY_PATH


def __getattr__(name: str) -> object:
    # share.py 定义的发布函数惰性回指——eager import 会成 seams↔share 循环；
    # setattr 落为真 attr 后本函数不再被调用，patch 语义不变。
    if name == "share_pack_publish":
        from .share import share_pack_publish  # noqa: PLC0415

        return share_pack_publish
    # USER_GLOSSARY_PATH 兼容名惰性回指 canonical——常量形冻结在 import 期
    # 会错过 ``set_data_dir`` 的运行期 env 写入；setattr 补丁落真 attr 后
    # 本分支不再被调，补丁语义同 glossary 模块自身的 __getattr__。
    if name == "USER_GLOSSARY_PATH":
        return _user_glossary_path()
    raise AttributeError(name)
