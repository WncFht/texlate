"""日志脱敏簇 —— server 侧装配点（2026-09-15-web-layer.md §4.2）。

四层不落日志防线的两道：异常边界 ``scrub()`` 先过（已知 secret 形态 +
显式 key 值），logger/handler 挂 :class:`RedactFilter` 同款正则
scrub——防三方库把请求体打进 traceback。

正则表/``scrub``/``RedactFilter`` 类体已下沉 :mod:`texlate.logsetup`
（CLI 与 server 共用同一脱敏层——core 侧 ``configure_logging`` 装的
handler 挂的是同一个类对象，本叶 ``install_log_scrub`` 的卸旧判型对
其天然生效）；本叶只保留 server 专属的 ``install_log_scrub`` 装配与
re-export 名字面（``_KEY_PATTERNS``/``scrub``/``RedactFilter`` 原样）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from texlate.logsetup import (
    SECRET_LOG_PATTERNS as _KEY_PATTERNS,  # noqa: F401 -- 名字面原样保留
)
from texlate.logsetup import RedactFilter, scrub

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

__all__ = [
    "RedactFilter",
    "install_log_scrub",
    "scrub",
]

#: ``install_log_scrub`` 额外覆盖的具名 logger（uvicorn 系自带 handler，
#: propagate 链上各自独立判定；texlate 根包 logger 本身无 handler，
#: 挂上挡本源直写）。
_LOG_NAMES = ("texlate", "uvicorn", "uvicorn.error", "uvicorn.access")


def install_log_scrub(
    key_provider: Callable[[], Iterable[str]] | None = None,
) -> RedactFilter:
    """把 :class:`RedactFilter` 挂到 root logger 与其全部现有 handler。

    语义坑：logger 级 filter 只在记录「本源」logger 上判定，传播链上
    每个 handler 独立判定——所以 root logger 本体（拦直接
    ``logging.warning(...)`` 的本源记录）+ root handlers（拦
    ``texlate.*``/三方传播上来的记录）+ uvicorn 系私有 handler 都要挂。
    重复调用先卸旧 filter 再挂新的（key_provider 轮换/多次装配幂等）。
    须在 uvicorn log config 就绪后调用（app lifespan 起点）。
    """
    filt = RedactFilter(key_provider)
    loggers = [logging.getLogger(), *(logging.getLogger(n) for n in _LOG_NAMES)]
    for lg in loggers:
        # 快照后再卸——removeFilter 原地改 filters，边遍历边删会跳过后邻旧件
        for old in [f for f in lg.filters if isinstance(f, RedactFilter)]:
            lg.removeFilter(old)
        lg.addFilter(filt)
        for h in lg.handlers:
            for old in [f for f in h.filters if isinstance(f, RedactFilter)]:
                h.removeFilter(old)
            h.addFilter(filt)
    return filt
