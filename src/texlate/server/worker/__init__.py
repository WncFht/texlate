"""管线 worker + 任务队列分发器（web-layer §3.1/§3.4）。

- ``TaskRunner``：进程内 ``asyncio.Queue`` + 单 worker 串行（等价
  Semaphore(1) 管线槽——下载/编译重活串行，翻译块级并行由
  ``XlatPipeline`` 内部 ``Semaphore(concurrency)`` 管）；内存 secrets
  注册表（key 绝不入库）；心跳 ticker 维护 ``updated_at``。
- ``PipelineWorker``：驱动产品公共 API 跑真实管线——
  ``acquire_source → route_project → normalize_project → parse_file →
  XlatPipeline → reconstruct → prepare_chinese → engine.compile → judge``.
  阻塞段一律 ``asyncio.to_thread``，DB 写只发生在 loop 线程。
- 断点恢复三级：stage 级磁盘哨兵（``.fetch-done``/``.base-done``/
  ``.splice-done`` + chunks 行）、chunk 级 chunks 表 ``status='pending'``
  续跑、事件级 ``task_events`` 重放。

``PipelineWorker`` 在本模块装配——方法集按 stage 拆在同包 mixin 模块里
（``_Fetch``/``_Parse``/``_Translate``/``_Share``/``_Compile``/``_Pdf``
等），多继承保持单类语义与 ``type(self)`` spawn 不变。monkeypatch 缝
集中在 ``seams`` 子模块——子模块调用点 ``seams.X`` 查名；本模块
``__getattr__`` 把缝名转指 seams，``worker.X`` 直读解析到同一对象
（patch 打 ``worker.seams.X`` 即拦截全部消费点）。
"""

from __future__ import annotations

from texlate.repair import resolve_glossary_path, ruleset_with_baseline
from texlate.server.upload import (
    _md_member,
    pdf_pages,
    sniff_upload,
    unpack_zip,
)

from . import seams
from ._common import (
    _DB_TO_PIPE,
    _ENV_TIMEOUT_MAX_S,
    _FETCH_NO_RETRY,
    _FIXLOOP_SRC_EXTS,
    _FLUSH_MS,
    _FLUSH_N,
    _PIPE_TO_DB,
    _PROBE_LIST_CAP,
    _PROBE_SEEN_TAG,
    _SENTINELS,
    _SPLICE_STALE_KINDS,
    COMPILE_TIMEOUT,
    KIND_URL,
    PIPELINE_VERSION,
    PROGRESS,
    URL_KIND,
    DBStateBridge,
    Secrets,
    SegmentCache,
    TaskCtx,
    _AbortingTranslator,
    _aclose_clients,
    _env_timeout,
    _FallbackTranslator,
    _new_usage_meter,
    _PerCallTranslator,
    _RouteRejectError,
    _scrub_deep,
    _SectionAbort,
    _ShareRejectError,
    _StageError,
    _tgt_lang,
    _translate_progress,
    _translator_clients,
    artifact_urls,
    cache_key_for,
    chunk_db_id,
    chunk_error_code,
)
from .compile import (
    _Compile,
    _fixloop_summary,
    _sync_fixed_sources,
)
from .core import _Core
from .emit import _Events
from .fetch import _Fetch
from .html import _Html
from .parse import _Parse
from .pdf import _Pdf
from .retranslate import _Retranslate
from .runner import TaskRunner
from .share import (
    _Share,
    _share_pool,
    _share_row,
    _share_sourced,
    share_pack_publish,
)
from .translate import _Translate


class PipelineWorker(
    _Core,
    _Events,
    _Fetch,
    _Html,
    _Parse,
    _Translate,
    _Share,
    _Compile,
    _Pdf,
    _Retranslate,
):
    """单任务管线驱动。注入面：translator_factory / fetcher / engine_factory。

    ``translator_factory(ctx) -> Translator``——缺省按凭证有无分流
    GatewayTranslator / MockTranslator（``TEXLATE_TRANSLATOR`` env 可强制）。
    """


def __getattr__(name: str) -> object:
    # 缝名转指 seams 子模块——patch 打 seams 后 `worker.X` 直读拿到同一替身
    if name in seams.__all__:
        return getattr(seams, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(seams.__all__))


__all__ = [
    "COMPILE_TIMEOUT",
    "KIND_URL",
    "PIPELINE_VERSION",
    "PROGRESS",
    "URL_KIND",
    "_DB_TO_PIPE",
    "_ENV_TIMEOUT_MAX_S",
    "_FETCH_NO_RETRY",
    "_FIXLOOP_SRC_EXTS",
    "_FLUSH_MS",
    "_FLUSH_N",
    "_HEARTBEAT_S",
    "_PIPE_TO_DB",
    "_PROBE_LIST_CAP",
    "_PROBE_SEEN_TAG",
    "_SENTINELS",
    "_SPLICE_STALE_KINDS",
    "DBStateBridge",
    "PipelineWorker",
    "Secrets",
    "SegmentCache",
    "TaskCtx",
    "TaskRunner",
    "_AbortingTranslator",
    "_FallbackTranslator",
    "_PerCallTranslator",
    "_RouteRejectError",
    "_SectionAbort",
    "_ShareRejectError",
    "_StageError",
    "_aclose_clients",
    "_env_timeout",
    "_fixloop_summary",
    "_md_member",
    "_new_usage_meter",
    "_scrub_deep",
    "_share_pool",
    "_share_row",
    "_share_sourced",
    "_sync_fixed_sources",
    "_tgt_lang",
    "_translate_progress",
    "_translator_clients",
    "artifact_urls",
    "cache_key_for",
    "chunk_db_id",
    "chunk_error_code",
    "pdf_pages",
    "resolve_glossary_path",
    "ruleset_with_baseline",
    "share_pack_publish",
    "sniff_upload",
    "unpack_zip",
]
