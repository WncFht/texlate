r"""jsonl 追加件——flock 串行化单行 append 的跨层单源。

POSIX 侧 ``flock`` 串行化写临界区——append 账被 ``asyncio.to_thread``
工作线程/多进程共享时防行交错（每次调用新开 fd，flock 同时覆盖跨线程
与跨进程写者，无需 ``threading.Lock``）；无 fcntl 平台退化为无锁
（``cli.web._service_lock``/``_xelatex._install_lock`` 同平台门）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

try:
    import fcntl
except ImportError:  # 无 fcntl 平台（win 等）→ 追加写退化为无锁
    fcntl = None  # type: ignore[assignment]


def append_jsonl(path: Path, obj: Mapping[str, Any]) -> None:
    r"""``jsonl`` 追加一行（UTF-8 单行 JSON + ``\n`` 结尾）；父目录缺席自建。

    写临界区经 ``flock`` 串行化（模块顶平台门）——``share.index_append``
    与 ``fixloop.cases.CaseSink.record`` 共用本件。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.write(line)
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
