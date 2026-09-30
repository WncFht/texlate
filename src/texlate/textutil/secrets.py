r"""secret 形态表单源 —— 日志/错误面脱敏正则的跨层宿主叶。

两档刻意分层、共享行字面单源：

- ``SECRET_PATTERNS``（严档，``xlat._errors.redact`` 错误文本道）：
  ``sk-`` 分两档（``{8,}`` 通用 + ``sk-ant-{4,}`` 窄形）。错误消息
  要回显给用户，``sk-`` 收太宽会把 ``task-1234`` 类日常词误抹成
  ``ta***``，故保严口径。
- ``SECRET_LOG_PATTERNS``（宽档，``logsetup.scrub``/``RedactFilter``
  日志道）：``sk-`` 放宽为 ``[A-Za-z0-9._-]{4,}`` 单宽行——``.`` 入类
  收编严档两档与旧 ``sk-ant-.`` 冗行（窄形先跑会把 ``sk-…….`` 截成
  ``***.尾`` 留残，单宽行无此坑）；``key-`` 宽松形为日志面独有。

``Bearer``/``AIza``/``api_key=`` 三行两表同形，字面只定义一次。
覆盖不变量由 ``tests/xlat/test_secret_patterns.py`` 钉住（基表新形态无
日志表覆盖即红）。宿本叶而非任一消费层：logsetup 是日志底座不能
反引 ``xlat``（拖 httpx/asyncio/ssl 全栈），``xlat._errors`` 同理
不引 logsetup——textutil 底叶是双方可达的最低点。
"""

from __future__ import annotations

import re
from typing import Final

_BEARER_RX: Final = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_AIZA_RX: Final = re.compile(r"AIza[0-9A-Za-z_-]{10,}")
_API_KEY_RX: Final = re.compile(
    r"(?:api[_-]?key|x-api-key|token)[=:]\s*[\"']?\S+", re.IGNORECASE
)

_SK_STRICT_RX: Final = re.compile(r"sk-[A-Za-z0-9_-]{8,}")
_SK_ANT_RX: Final = re.compile(r"sk-ant-[A-Za-z0-9_-]{4,}")
_SK_WIDE_RX: Final = re.compile(r"sk-[A-Za-z0-9._-]{4,}")
_KEY_WIDE_RX: Final = re.compile(r"key-[A-Za-z0-9._-]{4,}")

#: 严档——错误文本脱敏（``xlat._errors.redact`` 经 ``xlat.client`` 转口）。
SECRET_PATTERNS: Final = [
    _BEARER_RX,
    _SK_STRICT_RX,
    _SK_ANT_RX,
    _AIZA_RX,
    _API_KEY_RX,
]

#: 宽档——日志脱敏（``logsetup.scrub``/``RedactFilter``/``server.logredact``）。
SECRET_LOG_PATTERNS: Final = [
    _BEARER_RX,
    _SK_WIDE_RX,
    _KEY_WIDE_RX,
    _AIZA_RX,
    _API_KEY_RX,
]
