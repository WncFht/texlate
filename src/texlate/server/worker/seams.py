"""worker 包唯一 monkeypatch 面（原 ``__init__`` noqa-F401 缝 + ``_w`` 包回查的收口）。

worker 子模块对一切「测试可替换件」一律在调用点 ``seams.X`` 查名——
``monkeypatch.setattr("texlate.server.worker.seams.X", …)`` 即拦截全部消费点。
``__init__.py`` 再出口同名供直读面（``texlate.server.worker.X`` 仍解析，
但 patch 必须打到本模块）。
"""

from __future__ import annotations

from texlate.align import build_alignment
from texlate.arxiv.fetch import Fetcher, acquire_source
from texlate.arxiv.html import fetch_html, marked_html, parse_arxiv_html
from texlate.arxiv.meta import fetch_metadata
from texlate.compile.engine import engine_for, route_project
from texlate.compile.probe import target_probe
from texlate.share import index_lookup
from texlate.xlat.glossary import USER_GLOSSARY_PATH

from ._common import _aclose_clients

#: 心跳间隔（updated_at 供 SSE/列表页判活）
_HEARTBEAT_S = 5.0

__all__ = [
    "USER_GLOSSARY_PATH",
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
]


def __getattr__(name: str) -> object:
    # share.py 定义的发布函数惰性回指——eager import 会成 seams↔share 循环；
    # setattr 落为真 attr 后本函数不再被调用，patch 语义不变。
    if name == "share_pack_publish":
        from .share import share_pack_publish  # noqa: PLC0415

        return share_pack_publish
    raise AttributeError(name)
