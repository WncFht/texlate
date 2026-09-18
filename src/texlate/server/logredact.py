"""日志脱敏簇 —— secret 形态正则 + :class:`RedactFilter`（web-layer.md §4.2）。

四层不落日志防线的两道：异常边界 ``scrub()`` 先过（已知 secret 形态 +
显式 key 值），根 logger 挂 :class:`RedactFilter` 同款正则 scrub——防
三方库把请求体打进 traceback。
"""

from __future__ import annotations

import contextlib
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

from texlate.xlat.client import redact

_KEY_PATTERNS = [
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9._-]{4,}"),
    re.compile(r"sk-ant-[A-Za-z0-9._-]{4,}"),
    re.compile(r"key-[A-Za-z0-9._-]{4,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{10,}"),
    re.compile(r"(?:api[_-]?key|x-api-key|token)[=:]\s*[\"']?\S+", re.IGNORECASE),
]


def scrub(text: str, api_key: str = "") -> str:
    """redact() 同族：已知 secret 形态 + 显式 key 值（§4.2 第一道防线）。"""
    out = redact(text, api_key)
    for rx in _KEY_PATTERNS:
        out = rx.sub("***", out)
    return out


#: ``install_log_scrub`` 额外覆盖的具名 logger（uvicorn 系自带 handler，
#: propagate 链上各自独立判定；texlate 根包 logger 本身无 handler，
#: 挂上挡本源直写）。
_LOG_NAMES = ("texlate", "uvicorn", "uvicorn.error", "uvicorn.access")


class RedactFilter(logging.Filter):
    """根 logger 脱敏（§4.2 第二道防线，防三方库把请求体打进 traceback）。

    ``key_provider`` 返回当前该抹掉的 key 值集合（settings key +
    运行中的 header key）——动态取，key 轮换即生效。
    """

    def __init__(self, key_provider: object = None) -> None:
        """key_provider: ``() -> Iterable[str]``，None 时只抹正则形态。"""
        super().__init__()
        self._key_provider = key_provider

    def _keys(self) -> list[str]:
        if callable(self._key_provider):
            try:
                return [k for k in self._key_provider() if k]
            except Exception:  # noqa: BLE001 -- 过滤器绝不能炸掉日志调用
                return []
        return []

    def _scrub(self, text: str) -> str:
        for key in self._keys():
            text = text.replace(key, "***")
        for rx in _KEY_PATTERNS:
            text = rx.sub("***", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        """命中 secret 形态时改写 msg 并清空 args（避免二次格式化还原）。

        ``exc_info``/``stack_info`` 不走 ``msg``——Formatter 另路渲染；
        含 key 的异常文本（三方库把请求体打进异常）须先行 format 再
        洗，写回 ``record.exc_text`` 供 Formatter 直接用缓存值。
        """
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 -- 同上，filter 不炸
            return True
        clean = self._scrub(msg)
        if clean != msg:
            record.msg = clean
            record.args = ()
        if record.exc_info:
            with contextlib.suppress(Exception):
                record.exc_text = self._scrub(
                    logging.Formatter().formatException(record.exc_info)
                )
        if record.stack_info:
            record.stack_info = self._scrub(record.stack_info)
        return True


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
        for old in (f for f in lg.filters if isinstance(f, RedactFilter)):
            lg.removeFilter(old)
        lg.addFilter(filt)
        for h in lg.handlers:
            for old in (f for f in h.filters if isinstance(f, RedactFilter)):
                h.removeFilter(old)
            h.addFilter(filt)
    return filt
