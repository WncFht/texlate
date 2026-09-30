"""``server.worker`` 包共享低层件——TaskCtx/常量/桥/译器包装（原 worker.py 顶层段）。

拆分：实现体按职域下沉同包八叶——``_common_ctx``（``Secrets``/``TaskCtx``
运行上下文 dataclass）、``_common_const``（进度刻度/kind 双向映射/哨兵面/
probe·fixloop 常量表 + ``_row_status_snap`` 行快照）、``_common_util``
（env/开关/``COMPILE_TIMEOUT`` 读入 + ``_scrub_deep``/进度/语言/术语小件）、
``_common_state``（``chunk_db_id``/``zh_slot``/``FAILED_DB``/
``chunk_error_code``/``DBStateBridge`` chunks 行面与断点桥 + pipecore
状态图转口）、``_common_segcache``（``SegmentCache`` 段缓存桥 +
``_repend_puts`` 回挂）、``_common_client``（usage meter/ChatClient
接线小件/``_Sink`` 适配）、``_common_xlator``（``_FallbackTranslator``/
``_PerCallTranslator``/``_AbortingTranslator`` 译器包装）、
``_common_errors``（阶段/路由/share/段内取消四类控制流信号）。本文件是
PEP 562 惰性门面（同 ``xlat.pipeline``/``kernel.index`` 形制）——平名经
``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``from ._common import X`` 读面与拆分前逐名等价。叶子间互引走全路径
直跨（``texlate.server.worker._common_*``），不经本门面。
"""

from __future__ import annotations

import importlib
import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # __all__ 名单静态落地——F822 要名可解，F401 以 __all__ re-export 豁免；
    # 私有惰性名不在此列（不在 __all__，无 F822 需，导入反吃 F401）。
    import hashlib
    import json
    import threading
    from dataclasses import dataclass, field
    from typing import Any

    from texlate.arxiv.fetch import AcquireStatus
    from texlate.pipecore import delivered_db
    from texlate.server._ttlcache import LoopClientPool
    from texlate.server.settings import (
        COMPILE_TIMEOUT_MAX_S,
        DEFAULT_COMPILE_TIMEOUT_S,
        scrub,
    )
    from texlate.server.store import row_json
    from texlate.server.worker._common_const import (
        KIND_URL,
        PROGRESS,
        URL_KIND,
        artifact_urls,
    )
    from texlate.server.worker._common_ctx import Secrets, TaskCtx
    from texlate.server.worker._common_segcache import SegmentCache
    from texlate.server.worker._common_state import (
        FAILED_DB,
        DBStateBridge,
        chunk_db_id,
        chunk_error_code,
        zh_slot,
    )
    from texlate.server.worker._common_util import COMPILE_TIMEOUT, opt_bool
    from texlate.share import PIPELINE_VERSION, cache_key_for
    from texlate.textutil import env_float
    from texlate.textutil.osutil import ENV_COMPILE_TIMEOUT, opt_switch
    from texlate.xlat.client import ChatClient, ChatError, UsageRecord
    from texlate.xlat.pipeline import ChunkResult, GatewayTranslator
    from texlate.xlat.state import ChunkRecord, StateStore, atomic_json

log = logging.getLogger(__name__)

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_common_client": (
        "_Sink",
        "_aclose_clients",
        "_new_usage_meter",
        "_translator_clients",
    ),
    "_common_const": (
        "KIND_URL",
        "PROGRESS",
        "URL_KIND",
        "_COMPILE_VERDICTS",
        "_FETCH_NO_RETRY",
        "_FIXLOOP_SRC_EXTS",
        "_FLUSH_MS",
        "_FLUSH_N",
        "_PROBE_LIST_CAP",
        "_PROBE_SEEN_TAG",
        "_SENTINELS",
        "_SPLICE_STALE_KINDS",
        "_compile_done_verdict",
        "_row_status_snap",
        "_write_compile_done",
        "artifact_urls",
    ),
    "_common_ctx": (
        "Secrets",
        "TaskCtx",
    ),
    "_common_errors": (
        "_RouteRejectError",
        "_SectionAbort",
        "_ShareRejectError",
        "_StageError",
    ),
    "_common_segcache": (
        "SegmentCache",
        "_repend_puts",
    ),
    "_common_state": (
        "DBStateBridge",
        "FAILED_DB",
        "_DB_TO_PIPE",
        "_PIPE_TO_DB",
        "chunk_db_id",
        "chunk_error_code",
        "zh_slot",
    ),
    "_common_util": (
        "COMPILE_TIMEOUT",
        "_ENV_TIMEOUT_MAX_S",
        "_env_timeout",
        "_glossary_option",
        "_scrub_deep",
        "_tgt_lang",
        "_translate_progress",
        "opt_bool",
    ),
    "_common_xlator": (
        "_AbortingTranslator",
        "_FallbackTranslator",
        "_PerCallTranslator",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# HEAD 单件期模块属性面——stdlib 模块名与 texlate 顶层绑定也按名惰性解析，
# 读面（含 ``import *``/``from _common import`` 两形）与拆分前逐名等价。
_STDLIB_MODS = ("hashlib", "json", "threading")
_EXTRA_BINDINGS = {
    "Any": "typing",
    "dataclass": "dataclasses",
    "field": "dataclasses",
}
_TEXLATE_EXPORTS = {
    "AcquireStatus": "texlate.arxiv.fetch",
    "COMPILE_TIMEOUT_MAX_S": "texlate.server.settings",
    "ChatClient": "texlate.xlat.client",
    "ChatError": "texlate.xlat.client",
    "ChunkRecord": "texlate.xlat.state",
    "ChunkResult": "texlate.xlat.pipeline",
    "DEFAULT_COMPILE_TIMEOUT_S": "texlate.server.settings",
    "ENV_COMPILE_TIMEOUT": "texlate.textutil.osutil",
    "GatewayTranslator": "texlate.xlat.pipeline",
    "LoopClientPool": "texlate.server._ttlcache",
    "PIPELINE_VERSION": "texlate.share",
    "StateStore": "texlate.xlat.state",
    "UsageRecord": "texlate.xlat.client",
    "atomic_json": "texlate.xlat.state",
    "cache_key_for": "texlate.share",
    "delivered_db": "texlate.pipecore",
    "env_float": "texlate.textutil",
    "opt_switch": "texlate.textutil.osutil",
    "row_json": "texlate.server.store",
    "scrub": "texlate.server.settings",
}

# 字面列表——拆分前 ``import *`` 面（无 __all__ 期全量非下划线名）逐名保留；
# 私有名经 _LAZY 进属性读面不进 __all__。ruff F401 re-export 判定要静态
# __all__；``_export_drift`` 是三表同步闸。
__all__ = [
    "COMPILE_TIMEOUT",
    "COMPILE_TIMEOUT_MAX_S",
    "DEFAULT_COMPILE_TIMEOUT_S",
    "ENV_COMPILE_TIMEOUT",
    "FAILED_DB",
    "KIND_URL",
    "PIPELINE_VERSION",
    "PROGRESS",
    "TYPE_CHECKING",
    "URL_KIND",
    "AcquireStatus",
    "Any",
    "ChatClient",
    "ChatError",
    "ChunkRecord",
    "ChunkResult",
    "DBStateBridge",
    "GatewayTranslator",
    "LoopClientPool",
    "Secrets",
    "SegmentCache",
    "StateStore",
    "TaskCtx",
    "UsageRecord",
    "annotations",
    "artifact_urls",
    "atomic_json",
    "cache_key_for",
    "chunk_db_id",
    "chunk_error_code",
    "dataclass",
    "delivered_db",
    "env_float",
    "field",
    "hashlib",
    "json",
    "log",
    "logging",
    "opt_bool",
    "opt_switch",
    "row_json",
    "scrub",
    "threading",
    "zh_slot",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性 / stdlib 绑定 / texlate 顶层名。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"texlate.server.worker.{leaf}"), name)
        globals()[name] = value
        return value
    if name in _STDLIB_MODS:
        value = importlib.import_module(name)
        globals()[name] = value
        return value
    extra = _EXTRA_BINDINGS.get(name)
    if extra is not None:
        value = getattr(importlib.import_module(extra), name)
        globals()[name] = value
        return value
    texmod = _TEXLATE_EXPORTS.get(name)
    if texmod is not None:
        value = getattr(importlib.import_module(texmod), name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return sorted(
        set(globals())
        | set(__all__)
        | set(_LAZY)
        | set(_STDLIB_MODS)
        | set(_EXTRA_BINDINGS)
        | set(_TEXLATE_EXPORTS)
    )


def _export_drift() -> list[str]:
    """``_LAZY``/``__all__``/叶子实体三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。逐名 ``getattr`` 实解：叶子断链
    （``_LEAF_EXPORTS`` 配名叶子不提供）与幽灵条（解析不到任何叶子或绑
    定）在此曝，是首访 ``AttributeError`` 唯一的提前闸。审计实载全部
    叶子，只供测试调用，装载期不自检。
    """
    mod = sys.modules[__name__]
    drift = []
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    for name in _LAZY:
        try:
            getattr(mod, name)
        except Exception as exc:  # noqa: BLE001 -- 审计兜全漂移，非首错即死
            drift.append(f"_LEAF_EXPORTS entry {name} does not resolve: {exc}")
    for name in __all__:
        if name in _LAZY:
            continue  # 已解
        try:
            getattr(mod, name)
        except Exception as exc:  # noqa: BLE001 -- 审计兜全漂移，非首错即死
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and name not in _STDLIB_MODS
        and name not in _EXTRA_BINDINGS
        and name not in _TEXLATE_EXPORTS
        and callable(v)
        and getattr(v, "__module__", None) == __name__
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
