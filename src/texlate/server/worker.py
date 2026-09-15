"""管线 worker + 任务队列分发器（web-layer §3.1/§3.4）。

- ``TaskRunner``：进程内 ``asyncio.Queue`` + 单 worker 串行（等价
  Semaphore(1) 管线槽——下载/编译重活串行，翻译块级并行由
  ``XlatPipeline`` 内部 ``Semaphore(concurrency)`` 管）；内存 secrets
  注册表（key 绝不入库）；心跳 ticker 维护 ``updated_at``。
- ``PipelineWorker``：驱动产品公共 API 跑真实管线——
  ``acquire_source → route_project → normalize_project → parse_file →
  XlatPipeline → reconstruct → prepare_chinese → engine.compile → judge``。
  阻塞段一律 ``asyncio.to_thread``，DB 写只发生在 loop 线程。
- 断点恢复三级：stage 级磁盘哨兵（``.fetch-done``/``.base-done``/
  ``.splice-done`` + chunks 行）、chunk 级 chunks 表 ``status='pending'``
  续跑、事件级 ``task_events`` 重放。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import secrets as secrets_mod
import shutil
import threading
import time
import zipfile
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, TypeVar

from texlate import __version__
from texlate.arxiv.cache import SourceCache
from texlate.arxiv.fetch import AcquireStatus, Fetcher, acquire_source
from texlate.arxiv.ratelimit import RateLimiter
from texlate.arxiv.sniff import BlobKind, SniffError, sniff
from texlate.arxiv.unpack import (
    MAX_FILE_BYTES,
    UnpackError,
    unpack_sniffed,
)
from texlate.compile.engine import Engine, engine_for, route_project
from texlate.compile.inject import (
    InjectRejectError,
    find_main_tex,
    prepare_chinese,
)
from texlate.compile.judge import judge
from texlate.compile.normalize import normalize_project
from texlate.compile.sandbox import find_tool
from texlate.latex.api import parse_file
from texlate.latex.reconstruct import reconstruct
from texlate.server.settings import cache_scope, scrub
from texlate.server.store import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    Store,
    StoreError,
)
from texlate.validate.l0 import validate_pair
from texlate.xlat.client import (
    AuthError,
    ChatClient,
    ChatError,
    RetryableHTTPError,
)
from texlate.xlat.glossary import Glossary
from texlate.xlat.pipeline import (
    ChunkIn,
    ChunkResult,
    GatewayTranslator,
    MockTranslator,
    PipelineConfig,
    Translator,
    XlatPipeline,
)
from texlate.xlat.prompts import PROMPT_VERSION, normalize_kind
from texlate.xlat.state import ChunkRecord, atomic_json

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.latex.model import ScanResult
    from texlate.server.events import EventBus

log = logging.getLogger(__name__)

_T = TypeVar("_T")

#: 进度刻度（§2.2：fetching 3→9 / parsing 9→25 / translating 25→85 /
#: compiling 90→99 / 终态 100）
PROGRESS = {
    "fetching": (3, 9),
    "parsing": (9, 25),
    "translating": (25, 85),
    "compiling": (90, 99),
}

#: 管线版本（cache_key 成分；prompt 模板或产品版本变即失效）
PIPELINE_VERSION = f"texlate-{__version__}|{PROMPT_VERSION}"

#: chunk 落盘批量 flush 阈值（§3.4.2：每 8 块或 500ms）
_FLUSH_N = 8
_FLUSH_MS = 0.5

#: 编译超时（docs/08 §4.1 默认值）
COMPILE_TIMEOUT = 240.0

#: 心跳间隔（updated_at 供 SSE/列表页判活）
_HEARTBEAT_S = 5.0

#: upload_tex 解包文件数上限（§2.4：4000 文件）
_MAX_UNPACK_FILES = 4000

#: files.kind → URL kind（§2.3 白名单表）
KIND_URL = {
    "src_tar": "src.tar",
    "en_pdf": "en.pdf",
    "zh_pdf": "zh.pdf",
    "dual_pdf": "dual.pdf",
    "dual_json": "dual.json",
    "zh_src_zip": "zh-src.zip",
    "compile_log": "compile.log",
    "md_zip": "md",
}
#: URL kind → files.kind（反查）
URL_KIND = {v: k for k, v in KIND_URL.items()}

#: fetch 失败中重试无意义的终态
_FETCH_NO_RETRY = frozenset(
    {
        AcquireStatus.PDF_ONLY,
        AcquireStatus.UNKNOWN_FORMAT,
        AcquireStatus.TOO_LARGE,
        AcquireStatus.NOT_FOUND,
    }
)

#: zip 成员名拒绝面：绝对路径/盘符
_BAD_ZIP_NAME = re.compile(r"^(?:[a-zA-Z]:|/|\\)")


@dataclass(slots=True)
class Secrets:
    """BYOK 运行时凭证（只在内存里活过任务生命周期，绝不入库）。"""

    api_key: str = ""
    base_url: str = ""
    model: str = ""
    source: str = "none"


@dataclass(slots=True)
class TaskCtx:
    """单次 run 的工作上下文：任务行快照 + 目录布局 + 内存态。"""

    store: Store
    bus: EventBus
    task_id: str
    row: dict[str, Any]
    secrets: Secrets
    root: Path  # tasks/{id}/
    scans: dict[str, ScanResult] = field(default_factory=dict)
    main_rel: str = ""
    engine_name: str = "tectonic"
    tokens_est: int = 0

    @property
    def src_dir(self) -> Path:
        """原始源树（fetching 产物，只读）。"""
        return self.root / "src"

    @property
    def base_dir(self) -> Path:
        """Normalize 后树（parsing/translating 输入）。"""
        return self.root / "base"

    @property
    def zh_dir(self) -> Path:
        """译文工程树（splice + ctex 注入产物）。"""
        return self.root / "zh"

    def options(self) -> dict[str, Any]:
        """任务 options_json 反序列化。"""
        try:
            data = json.loads(self.row.get("options_json") or "{}")
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}


def chunk_db_id(src_file: str, byte_start: int, byte_end: int) -> str:
    """``sha256(src_file+byte_start+byte_end)[:24]``（§3.2 chunks.chunk_id）。"""
    h = hashlib.sha256(f"{src_file}:{byte_start}:{byte_end}".encode())
    return h.hexdigest()[:24]


def cache_key_for(
    *,
    arxiv_id: str,
    version: int | None,
    model: str,
    target_lang: str,
    tenant: str,
) -> str:
    """产物级 dedup 键：``sha256(arxiv_id@ver|model|pipeline_ver|lang)``。

    故意不含 tenant（§4.3：公开论文的确定性函数可跨租户 reuse）；
    ``TEXLATE_CACHE_SCOPE=tenant`` 时把 tenant 拼进材料。
    """
    ver = f"v{version}" if version else ""
    material = f"{arxiv_id}@{ver}|{model}|{PIPELINE_VERSION}|{target_lang}"
    if cache_scope() == "tenant":
        material += f"|{tenant}"
    return hashlib.sha256(material.encode()).hexdigest()


# ---------------------------------------------------------------- 段缓存桥


class SegmentCache:
    """``translation_cache`` 表的 dict 门面（XlatPipeline ``cache`` 参数契约）。

    键 = ``{cfg_hash}:{seg_key}``——``cfg_hash`` 由
    ``sha256(model|prompt_ver|target_lang|glossary)[:16]`` 派生，管线内部
    ``_seg_key`` 再叠 src_text+kind+masked 快照。读穿透 SELECT，写进
    pending 缓冲由 ``drain`` 随 chunk flush 事务落盘。
    """

    def __init__(
        self,
        store: Store,
        *,
        prefix: str,
        model: str,
        target_lang: str,
    ) -> None:
        """Prefix = 配置指纹前缀（含 tenant 若 cache_scope=tenant）。"""
        self._store = store
        self._prefix = prefix
        self._model = model
        self._lang = target_lang
        self._pending: dict[str, str] = {}
        self.hits = 0

    def _full(self, seg_key: str) -> str:
        return f"{self._prefix}:{seg_key}"

    def __contains__(self, seg_key: object) -> bool:
        """存在性探测（不 bump hit_count——命中计数只在 ``__getitem__``）。"""
        if not isinstance(seg_key, str):
            return False
        if seg_key in self._pending:
            return True
        row = self._store.conn.execute(
            "SELECT 1 FROM translation_cache WHERE key = ?",
            (self._full(seg_key),),
        ).fetchone()
        return row is not None

    def __getitem__(self, seg_key: str) -> str:
        """读穿透：pending 优先，然后表（命中记 hit_count）。"""
        if seg_key in self._pending:
            return self._pending[seg_key]
        hit = self._store.cache_get(self._full(seg_key))
        if hit is None:
            raise KeyError(seg_key)
        self.hits += 1
        return hit

    def __setitem__(self, seg_key: str, translation: str) -> None:
        """写进 pending 缓冲（drain 前对同 key 读可见）。"""
        self._pending[seg_key] = translation

    def __len__(self) -> int:
        """待写缓冲长度。"""
        return len(self._pending)

    def drain(self) -> list[tuple[str, str, str, str]]:
        """取走待写缓存项 → ``[(key, translation, model, lang)]``。"""
        out = [
            (self._full(k), v, self._model, self._lang)
            for k, v in self._pending.items()
        ]
        self._pending.clear()
        return out


# ---------------------------------------------------------------- 断点 state 桥

_DB_TO_PIPE = {"ok": "ok", "fallback_orig": "skipped", "failed": "fault"}
_PIPE_TO_DB = {
    "ok": "ok",
    "partial": "ok",
    "skipped": "fallback_orig",
    "fault": "failed",
}


class DBStateBridge:
    """``StateStore`` 鸭子型：chunks 表做断点续跑状态面。

    ``load`` → (completed, recs)——completed 只收 ``ok``（pipeline 语义：
    skipped/fault 续跑必须重试）；``record`` → 待写缓冲由 worker flush。
    """

    def __init__(self, store: Store, task_id: str) -> None:
        """绑定 store 与任务。"""
        self._store = store
        self._task_id = task_id
        self.buffer: list[ChunkRecord] = []

    def load(self) -> tuple[set[str], dict[str, ChunkRecord]]:
        """Chunks 行 → (completed, recs)（``_load_resumed`` 契约）。"""
        completed: set[str] = set()
        recs: dict[str, ChunkRecord] = {}
        for r in self._store.all_chunks(self._task_id):
            status = r["status"]
            if status not in _DB_TO_PIPE:
                continue
            rec = ChunkRecord(
                chunk_id=r["chunk_id"],
                source=r["src_text"],
                translation=r["translation"] or "",
                status=_DB_TO_PIPE[status],
                kind=r["kind"],
                skipped=(status == "fallback_orig"),
                attempts=int(r["attempts"]),
            )
            recs[rec.chunk_id] = rec
            if status == "ok":
                completed.add(rec.chunk_id)
        return completed, recs

    def record(self, rec: ChunkRecord, *, error: dict[str, Any] | None = None) -> None:
        """缓冲一条结果（worker 按批量事务 flush）。"""
        del error
        self.buffer.append(rec)

    def start(self, total_chunks: int) -> None:
        """开跑登记：只记总数（state.json 语义已由 tasks 表覆盖）。"""
        self._store.update_fields(self._task_id, total_chunks=total_chunks)

    def finish(self) -> None:
        """收尾（落盘在 worker flush——这里无操作）。"""


class _StageError(Exception):
    """阶段内携带错误码的异常（→ ``run()`` 统一落 fault）。"""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        """Code 取 §2.2 错误码枚举。"""
        self.code = code
        self.retryable = retryable
        super().__init__(message)


# ---------------------------------------------------------------- 上传解包


def unpack_zip(data: bytes, dest: Path) -> list[str]:
    """Zip 安全解包（upload_tex 路线；tar/gz 走 ``unpack_sniffed``）。

    拒绝：绝对路径/盘符/``..`` 逃逸/超过 4000 文件/单文件或总量超限。
    """
    warnings: list[str] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        msg = f"corrupt zip: {e}"
        raise UnpackError(msg) from e
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > _MAX_UNPACK_FILES:
            msg = f"too_many_files:{len(infos)}"
            raise UnpackError(msg)
        total = 0
        dest.mkdir(parents=True, exist_ok=True)
        for info in infos:
            rel = PurePosixPath(info.filename)
            parts = [p for p in rel.parts if p not in ("", ".")]
            if _BAD_ZIP_NAME.match(info.filename) or any(p == ".." for p in parts):
                warnings.append(f"reject:{info.filename}")
                continue
            if info.file_size > MAX_FILE_BYTES:
                warnings.append(f"reject_size:{info.filename}")
                continue
            total += info.file_size
            if total > 300 * 1024 * 1024:  # 300MB 解压上限（§2.4）
                warnings.append("reject_totalcap")
                break
            target = dest.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
    return warnings


def _zip_kind(data: bytes) -> str:
    """PK 容器细分：docx/epub/upload_tex（坏 zip 交解包处报错）。"""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "word/document.xml" in names:
                return "docx"
            head = b""
            if "mimetype" in names:
                try:
                    head = zf.read("mimetype")[:64].strip()
                except KeyError:
                    head = b""
            if head == b"application/epub+zip" or any(
                n.endswith("content.opf") for n in names
            ):
                return "epub"
    except zipfile.BadZipFile:
        pass  # 坏 zip 交给 upload_tex 路在解包处报错
    return "upload_tex"


def sniff_upload(data: bytes, filename: str) -> str:
    """上传魔数路由（§2.4）→ ``upload_pdf|upload_tex|docx|epub|unknown``。

    判据顺序：``%PDF`` → zip(docx/epub 细分) → gzip/tar → 可解码文本兜底。
    """
    if data[:4] == b"%PDF":
        return "upload_pdf"
    if data[:4] == b"PK\x03\x04":
        return _zip_kind(data)
    try:
        s = sniff(data)
    except SniffError:
        return "unknown"
    if s.kind in (BlobKind.TAR, BlobKind.SINGLE):
        return "upload_tex"
    if filename.lower().endswith((".tex", ".ltx", ".latex", ".txt")):
        return "upload_tex"
    return "upload_tex" if _looks_text(data) else "unknown"


def pdf_pages(pdf: Path) -> int:
    """PDF 页数 best-effort：``/Type /Pages`` 的 ``/Count N``（压流返 0）。"""
    try:
        blob = pdf.read_bytes()
    except OSError:
        return 0
    m = re.search(rb"/Type\s*/Pages[^/>]*?/Count\s+(\d+)", blob)
    return int(m.group(1)) if m else 0


def _looks_text(data: bytes) -> bool:
    """粗糙文本判定：前 64KB 可 UTF-8 解码且无 NUL。"""
    if b"\x00" in data[:4096]:
        return False
    try:
        data[:65536].decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _safe_name(name: str) -> str:
    """上传文件名 → 安全落盘名（剥目录、滤怪字符，空则 main.tex）。"""
    base = PurePosixPath(name.replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9_.+-]", "_", base)
    if not base or not base.lower().endswith((".tex", ".ltx", ".latex", ".txt")):
        base = (base or "main") + ".tex"
    return base


def _translate_progress(done: int, total: int) -> int:
    """按 done/total 线性映射 translating 段进度（25→85）。"""
    lo, hi = PROGRESS["translating"]
    return min(hi, lo + int((hi - lo) * done / max(1, total)))


def _tgt_lang(target_lang: str) -> str:
    """``zh-CN/zh-TW/en`` → prompt 语言名。"""
    return {"zh-TW": "Traditional Chinese", "en": "English"}.get(target_lang, "Chinese")


# ---------------------------------------------------------------- Worker


class PipelineWorker:
    """单任务管线驱动。注入面：translator_factory / fetcher / engine_factory。

    ``translator_factory(ctx) -> Translator``——缺省按凭证有无分流
    GatewayTranslator / MockTranslator（``TEXLATE_TRANSLATOR`` env 可强制）。
    """

    def __init__(  # noqa: PLR0913 -- 依赖注入面集中声明
        self,
        store: Store,
        bus: EventBus,
        data_dir: Path,
        *,
        translator_factory: Callable[[TaskCtx], Translator] | None = None,
        fetcher: Fetcher | None = None,
        source_cache: SourceCache | None = None,
        engine_factory: Callable[[str], Engine] | None = None,
        babeldoc: str | None = None,
        compile_timeout: float = COMPILE_TIMEOUT,
    ) -> None:
        """data_dir = ``TEXLATE_DATA_DIR`` 根；任务工作区 ``tasks/{id}/``。"""
        self.store = store
        self.bus = bus
        self.data_dir = data_dir
        self._translator_factory = translator_factory
        self._fetcher = fetcher
        self._src_cache = source_cache
        self._engine_factory = engine_factory
        self._babeldoc = babeldoc
        self._compile_timeout = compile_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_tid = 0

    # ------------------------------------------------------------ 事件辅助

    def _on_loop(self, fn: Callable[..., _T], *args: object, **kw: object) -> _T:
        """Worker 线程的 DB/事件写弹回 loop 线程执行（§3.2 单写者纪律）。

        ``asyncio.to_thread`` 段内的 ``store``/``bus`` 调用一律走这里；
        loop 只 ``await`` 线程结果、反向等待不构成环，无死锁。
        """
        if self._loop is None or threading.get_ident() == self._loop_tid:
            return fn(*args, **kw)
        fut: Future[_T] = Future()

        def _run() -> None:
            try:
                fut.set_result(fn(*args, **kw))
            except Exception as e:  # noqa: BLE001 -- 透传回 worker 线程
                fut.set_exception(e)

        self._loop.call_soon_threadsafe(_run)
        return fut.result()

    def _stage(self, ctx: TaskCtx, stage: str, message: str, progress: int) -> None:
        """状态迁移 + stage 事件（先写库再发，同序保证）。"""
        self.store.transition(
            ctx.task_id, stage, message=message, progress=progress, force=True
        )
        self.bus.publish(
            ctx.task_id,
            "stage",
            {
                "stage": stage,
                "progress": progress,
                "message": message,
                "at": time.time(),
            },
        )

    def _log(self, ctx: TaskCtx, line: str) -> None:
        self._on_loop(
            self.bus.publish,
            ctx.task_id,
            "log",
            {"line": scrub(line, ctx.secrets.api_key)},
        )

    def _warning(self, ctx: TaskCtx, code: str, message: str) -> None:
        self._on_loop(
            self.bus.publish,
            ctx.task_id,
            "warning",
            {"code": code, "message": scrub(message, ctx.secrets.api_key)},
        )

    def _current_status(self, ctx: TaskCtx) -> str:
        row = self.store.get(ctx.task_id)
        return str(row["status"]) if row else "fault"

    def _check_cancelled(self, ctx: TaskCtx) -> None:
        """段边界 cancel 检查：API 置 cancelled 后由本检查收敛 worker。"""
        if self._current_status(ctx) == "cancelled":
            raise asyncio.CancelledError

    def _fail(
        self,
        ctx: TaskCtx,
        code: str,
        message: str,
        *,
        retryable: bool,
        stage: str | None,
    ) -> None:
        """致命错误：fault 迁移 + error 事件 + done 事件（终态一致性）。

        并发 cancel 竞态守卫：行已入终态则整条跳过（cancel 路径已发 done）。
        """
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return
        clean = scrub(message, ctx.secrets.api_key)
        err = {"code": code, "message": clean, "retryable": retryable}
        row = self.store.get(ctx.task_id)
        progress = int(row["progress"]) if row else 0
        self.store.transition(
            ctx.task_id, "fault", error=err, progress=progress, force=True
        )
        self.bus.publish(
            ctx.task_id, "error", {**err, "stage": stage, "chunk_seq": None}
        )
        self.bus.publish(
            ctx.task_id,
            "done",
            {
                "status": "fault",
                "artifacts": self._artifact_urls(ctx),
                "stats": self._stats(ctx),
            },
        )

    def _artifact_urls(self, ctx: TaskCtx) -> dict[str, str]:
        """Files 行 → ``{db_kind: /api/files/{id}/{url_kind}}``。"""
        return {
            kind: f"/api/files/{ctx.task_id}/{KIND_URL.get(kind, kind)}"
            for kind in self.store.files(ctx.task_id)
        }

    def _stats(self, ctx: TaskCtx) -> dict[str, Any]:
        counts = self.store.chunk_counts(ctx.task_id)
        return {
            "tokens": ctx.tokens_est,
            "seconds": round(time.time() - float(ctx.row["created_at"]), 1),
            "chunks_failed": counts["failed"],
        }

    def _register(self, ctx: TaskCtx, kind: str, rel: str) -> dict[str, Any]:
        """产物登记（bytes/sha256 实测，相对 ``tasks/{id}/``）。"""
        return self._on_loop(
            self.store.put_file, ctx.task_id, kind, rel, data_dir=ctx.root
        )

    # ------------------------------------------------------------ 主入口

    async def run(self, ctx: TaskCtx) -> None:  # noqa: C901 -- 异常阶梯平铺即 §2.2 错误码映射表
        """按 kind 跑全链；异常按错误码映射落 fault/cancelled。"""
        # resume：内存字段从行快照重建（main_tex/engine_resolved 持久化值）
        self._loop = asyncio.get_running_loop()
        self._loop_tid = threading.get_ident()
        ctx.main_rel = str(ctx.row.get("main_tex") or "")
        ctx.engine_name = str(ctx.options().get("engine_resolved") or "tectonic")
        try:
            self._check_cancelled(ctx)
            if ctx.row["kind"] == "upload_pdf":
                await self._run_pdf(ctx)
            else:
                await self._run_tex(ctx)
        except asyncio.CancelledError:
            # cancel 端点已置 cancelled；只在没有终态时补 interrupted
            if self._current_status(ctx) in ACTIVE_STATUSES:
                self.store.transition(
                    ctx.task_id,
                    "interrupted",
                    force=True,
                    message="worker cancelled",
                )
            raise
        except _StageError as e:
            self._fail(
                ctx,
                e.code,
                str(e),
                retryable=e.retryable,
                stage=ctx.row["stage"],
            )
        except AuthError as e:
            self._fail(
                ctx,
                "provider_auth",
                str(e),
                retryable=False,
                stage=ctx.row["stage"],
            )
        except RetryableHTTPError as e:
            code = (
                "provider_rate"
                if e.status == HTTPStatus.TOO_MANY_REQUESTS
                else "provider_timeout"
            )
            self._fail(ctx, code, str(e), retryable=True, stage=ctx.row["stage"])
        except ChatError as e:
            self._fail(
                ctx,
                "provider_error",
                str(e),
                retryable=e.retryable,
                stage=ctx.row["stage"],
            )
        except InjectRejectError as e:
            self._fail(
                ctx,
                "parse",
                f"inject reject: {e.reason}",
                retryable=False,
                stage=ctx.row["stage"],
            )
        except (UnpackError, ValueError, OSError) as e:
            self._fail(ctx, "parse", str(e), retryable=False, stage=ctx.row["stage"])
        except Exception as e:
            log.exception("task %s crashed", ctx.task_id)
            self._fail(
                ctx,
                "internal",
                f"{type(e).__name__}: {e}",
                retryable=True,
                stage=ctx.row["stage"],
            )

    # ------------------------------------------------------------ tex 管线

    async def _run_tex(self, ctx: TaskCtx) -> None:
        """arxiv/upload_tex 共链：fetch → parse → translate → compile。"""
        ctx.root.mkdir(parents=True, exist_ok=True)
        await self._stage_fetch(ctx)
        await self._stage_parse(ctx)
        await self._stage_translate(ctx)
        await self._stage_compile(ctx)

    async def _stage_fetch(self, ctx: TaskCtx) -> None:
        """fetching：源树就绪 + src.tar 登记（哨兵 .fetch-done 幂等）。"""
        if (ctx.src_dir / ".fetch-done").is_file():
            return
        self._stage(ctx, "fetching", "取源", PROGRESS["fetching"][0])
        if ctx.row["kind"] == "arxiv":
            await asyncio.to_thread(self._fetch_arxiv, ctx)
        else:
            await asyncio.to_thread(self._fetch_upload, ctx)
        (ctx.src_dir / ".fetch-done").write_text("", encoding="utf-8")
        self._stage(ctx, "fetching", "取源完成", PROGRESS["fetching"][1])
        self._check_cancelled(ctx)

    def _fetch_arxiv(self, ctx: TaskCtx) -> None:
        """``acquire_source`` → extracted → ``src/``；raw blob → ``src.tar``。"""
        arxiv_id = str(ctx.row["arxiv_id"])
        cache = self._src_cache or SourceCache(self.data_dir / "src-cache")
        fetcher = self._fetcher or Fetcher(RateLimiter(cache.root / "ratelimit.json"))
        res = acquire_source(arxiv_id, fetcher=fetcher, cache=cache)
        if res.status not in (AcquireStatus.OK, AcquireStatus.HIT):
            code = (
                "no_latex_source"
                if res.status in (AcquireStatus.PDF_ONLY, AcquireStatus.UNKNOWN_FORMAT)
                else "arxiv_fetch"
            )
            raise _StageError(
                code,
                res.detail or res.status.value,
                retryable=res.status not in _FETCH_NO_RETRY,
            )
        assert res.entry is not None  # noqa: S101 -- ok/hit 必有 entry
        entry = res.entry
        self._on_loop(
            self.store.update_fields,
            ctx.task_id,
            arxiv_id=f"{entry.arxiv_id}v{entry.resolved_version}",
            title=str(entry.meta.get("title") or ""),
        )
        if ctx.src_dir.exists():
            shutil.rmtree(ctx.src_dir)
        shutil.copytree(entry.extracted_dir, ctx.src_dir)
        raw = entry.raw_path
        if raw is not None and raw.is_file():
            shutil.copyfile(raw, ctx.root / "src.tar")
            self._register(ctx, "src_tar", "src.tar")
        for w in res.warnings:
            self._log(ctx, f"fetch warn: {w}")

    def _fetch_upload(self, ctx: TaskCtx) -> None:
        """upload_tex：解包 ``upload/`` blob → ``src/``；原文登记 src_tar。"""
        uploads = sorted((ctx.root / "upload").glob("*"))
        if not uploads:
            msg = "upload payload missing"
            raise _StageError(code="internal", message=msg)
        blob_path = uploads[0]
        data = blob_path.read_bytes()
        ctx.src_dir.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []
        try:
            s = sniff(data)
        except SniffError:
            s = None
        if s is not None and s.kind in (BlobKind.TAR, BlobKind.SINGLE):
            res = unpack_sniffed(s, ctx.src_dir, stem_hint=blob_path.name)
            warnings = res.warnings
        elif data[:4] == b"PK\x03\x04":
            warnings = unpack_zip(data, ctx.src_dir)
        elif _looks_text(data) or blob_path.suffix.lower() in (
            ".tex",
            ".ltx",
            ".latex",
            ".txt",
        ):
            (ctx.src_dir / _safe_name(blob_path.name)).write_bytes(data)
        else:
            msg = f"unrecognized upload format: {blob_path.name}"
            raise _StageError(code="unsupported_format", message=msg)
        for w in warnings:
            self._log(ctx, f"unpack: {w}")
        self._register(ctx, "src_tar", f"upload/{blob_path.name}")

    # ------------------------------------------------------------ parsing

    async def _stage_parse(self, ctx: TaskCtx) -> None:
        """parsing：normalize → 主文件定位 → 逐文件 parse → chunks 入库。"""
        if self.store.has_chunks(ctx.task_id):
            self._ensure_scans(ctx)
            return
        self._stage(ctx, "parsing", "解析工程", PROGRESS["parsing"][0])
        if not (ctx.base_dir / ".base-done").is_file():
            await asyncio.to_thread(self._build_base, ctx)
        self._check_cancelled(ctx)
        rows, scans = await asyncio.to_thread(self._parse_all, ctx)
        self.store.insert_chunks(ctx.task_id, rows)
        ctx.scans = scans
        self._stage(ctx, "parsing", "解析完成", PROGRESS["parsing"][1])

    def _build_base(self, ctx: TaskCtx) -> None:
        """``src → base``：route（reject → parse fault）→ normalize。"""
        if ctx.base_dir.exists():
            shutil.rmtree(ctx.base_dir)
        shutil.copytree(ctx.src_dir, ctx.base_dir)
        route = route_project(ctx.base_dir)
        for r in route.reasons:
            self._log(ctx, f"route: {r}")
        if route.reject:
            msg = f"route reject: {route.reject}"
            raise _StageError(code="parse", message=msg)
        opt_engine = str(ctx.options().get("engine") or "auto")
        engines = route.engines if opt_engine == "auto" else [opt_engine]
        if not engines:
            raise _StageError(code="parse", message="no engine route")
        ctx.engine_name = engines[0]
        override = str(ctx.options().get("main") or "")
        if override:
            # retry body {main} 或 upload main 字段：显式主文件
            cand = ctx.base_dir / override
            if not cand.is_file():
                raise _StageError(
                    code="parse", message=f"main override 不存在: {override}"
                )
            ctx.main_rel = override
        else:
            main = find_main_tex(ctx.base_dir)
            if main is None:
                raise _StageError(code="parse", message="no main tex")
            ctx.main_rel = main.relative_to(ctx.base_dir).as_posix()
        stats = normalize_project(ctx.base_dir, ctx.engine_name, ctx.main_rel)
        self._log(ctx, f"normalize: {stats}")
        # 引擎路由与主文件持久化——resume 后编译段还要用同一台引擎
        opts = ctx.options()
        opts["engine_resolved"] = ctx.engine_name
        self._on_loop(
            self.store.update_fields,
            ctx.task_id,
            main_tex=ctx.main_rel,
            options_json=json.dumps(opts, ensure_ascii=False),
        )
        (ctx.base_dir / ".base-done").write_text("", encoding="utf-8")

    def _parse_all(
        self, ctx: TaskCtx
    ) -> tuple[list[dict[str, Any]], dict[str, ScanResult]]:
        """逐文件半解析 → (chunk 行, scans)。单文件崩不拖全树。"""
        rows: list[dict[str, Any]] = []
        scans: dict[str, ScanResult] = {}
        seq = 0
        for f in sorted(ctx.base_dir.rglob("*.tex")):
            if f.name.startswith("."):
                continue
            rel = f.relative_to(ctx.base_dir).as_posix()
            try:
                res = parse_file(f, flatten=False)
            except Exception as e:  # noqa: BLE001 -- 单文件解析崩记名跳过
                self._log(ctx, f"parse skip {rel}: {e}")
                continue
            scans[rel] = res
            for c in res.chunks:
                cid = chunk_db_id(rel, c.span.start, c.span.end)
                rows.append(
                    {
                        "seq": seq,
                        "chunk_id": cid,
                        "src_file": rel,
                        "byte_start": c.span.start,
                        "byte_end": c.span.end,
                        "kind": normalize_kind(c.context),
                        "src_text": c.content,
                    }
                )
                seq += 1
        return rows, scans

    def _ensure_scans(self, ctx: TaskCtx) -> None:
        """Resume 场景：chunks 已有但内存 scans 空 → 重解析 base/ 补建。"""
        if not ctx.scans:
            _rows, ctx.scans = self._parse_all(ctx)

    # ------------------------------------------------------------ translating

    async def _stage_translate(self, ctx: TaskCtx) -> None:
        """translating：XlatPipeline 跑 chunks pending 集（批量 flush 落盘）。"""
        rows = self.store.all_chunks(ctx.task_id)
        if not rows:
            self._stage(ctx, "translating", "无可译块", PROGRESS["translating"][1])
            return
        self._ensure_scans(ctx)
        self._stage(ctx, "translating", "翻译中", PROGRESS["translating"][0])

        translator = self._make_translator(ctx)
        client = getattr(translator, "client", None)
        cache = self._make_cache(ctx)
        state = DBStateBridge(self.store, ctx.task_id)
        seq_map = {r["chunk_id"]: int(r["seq"]) for r in rows}
        status_map = {r["chunk_id"]: str(r["status"]) for r in rows}
        sse_items: list[dict[str, Any]] = []
        last_flush = time.monotonic()

        def on_result(r: ChunkResult) -> None:
            item: dict[str, Any] = {
                "seq": seq_map.get(r.chunk_id, -1),
                "status": _PIPE_TO_DB.get(r.status, "failed"),
            }
            if r.skipped:
                item["error_code"] = (
                    "placeholder_mismatch"
                    if "placeholder" in r.skip_reason
                    else "validate"
                )
            elif r.status == "fault":
                item["error_code"] = "provider_error"
            sse_items.append(item)
            ctx.tokens_est += (len(r.source) + len(r.translation)) // 4

        pipe = XlatPipeline(
            translator,
            config=PipelineConfig(
                concurrency=int(ctx.options().get("concurrency") or 3),
                tgt_lang=_tgt_lang(str(ctx.row["target_lang"])),
            ),
            glossary=self._make_glossary(ctx),
            state=state,  # type: ignore[arg-type] -- StateStore 鸭子型
            validator=lambda s, z: validate_pair(s, z).feedback(),
            cache=cache,  # type: ignore[arg-type] -- MutableMapping 鸭子型
            on_result=on_result,
        )
        inputs = [
            ChunkIn(chunk_id=r["chunk_id"], content=r["src_text"], kind=r["kind"])
            for r in rows
        ]

        try:
            run_task = asyncio.create_task(pipe.run(inputs))
            while not run_task.done():
                await asyncio.sleep(0.05)
                self._check_cancelled(ctx)
                if (
                    len(state.buffer) >= _FLUSH_N
                    or time.monotonic() - last_flush >= _FLUSH_MS
                ):
                    await self._flush_translate(
                        ctx, state, cache, status_map, sse_items
                    )
                    last_flush = time.monotonic()
            await run_task  # 传播异常
            await self._flush_translate(ctx, state, cache, status_map, sse_items)
        finally:
            if isinstance(client, ChatClient):
                await client.aclose()
        self._stage(ctx, "translating", "翻译完成", PROGRESS["translating"][1])
        counts = self.store.chunk_counts(ctx.task_id)
        if counts["failed"]:
            self._warning(
                ctx,
                "chunks_failed",
                f"{counts['failed']} 块回退原文（fallback_orig/failed）",
            )
        self._check_cancelled(ctx)

    async def _flush_translate(
        self,
        ctx: TaskCtx,
        state: DBStateBridge,
        cache: SegmentCache,
        status_map: dict[str, str],
        sse_items: list[dict[str, Any]],
    ) -> None:
        """批量事务 flush（§3.4.2）：record 缓冲 → chunks 行 + 段缓存 + 计数器 + chunk 事件。"""
        if not state.buffer and not sse_items:
            return
        updates = []
        for rec in state.buffer:
            db_status = _PIPE_TO_DB.get(rec.status, "failed")
            status_map[rec.chunk_id] = db_status
            updates.append(
                (
                    rec.chunk_id,
                    {
                        "status": db_status,
                        "translation": rec.translation,
                        "error_code": ("placeholder_mismatch" if rec.skipped else None),
                        "attempts": rec.attempts,
                    },
                )
            )
        state.buffer = []
        n_done = sum(
            v in ("ok", "fallback_orig", "failed") for v in status_map.values()
        )
        n_failed = sum(v in ("fallback_orig", "failed") for v in status_map.values())
        counts = {
            "total": len(status_map),
            "done": n_done,
            "cached": cache.hits,
            "failed": n_failed,
            "tokens": ctx.tokens_est,
            "progress": _translate_progress(n_done, len(status_map)),
        }
        self.store.flush_chunk_batch(ctx.task_id, updates, cache.drain(), counts)
        items_now = list(sse_items)
        sse_items.clear()
        self.bus.publish(
            ctx.task_id,
            "chunk",
            {
                "done": counts["done"],
                "total": counts["total"],
                "cached": counts["cached"],
                "failed": counts["failed"],
                "items": items_now,
            },
        )

    # ------------------------------------------------------------ compiling

    async def _stage_compile(self, ctx: TaskCtx) -> None:
        """compiling：en/zh 双侧编译 + zh-src.zip + dual.json + 终态。"""
        self._stage(ctx, "compiling", "编译", PROGRESS["compiling"][0])
        self._ensure_scans(ctx)
        await asyncio.to_thread(self._build_zh, ctx)
        self._check_cancelled(ctx)
        self.store.update_fields(ctx.task_id, progress=PROGRESS["compiling"][0] + 4)
        await asyncio.to_thread(self._compile_en, ctx)
        ok = await asyncio.to_thread(self._compile_zh, ctx)
        self._check_cancelled(ctx)
        self.store.update_fields(ctx.task_id, progress=PROGRESS["compiling"][1])
        self._build_dual(ctx)
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return  # cancel 竞态：终态已写，不再覆盖
        failed = self.store.chunk_counts(ctx.task_id)["failed"]
        if ok and failed == 0:
            status, err = "done", None
        elif ok or self._has_pdf(ctx, "zh_pdf"):
            status = "partial"
            err = {
                "code": "compile",
                "message": "有 pdf 但判据未全绿或块级失败",
                "retryable": True,
            }
        else:
            self._fail(
                ctx,
                "compile",
                "zh compile: no pdf",
                retryable=True,
                stage="compiling",
            )
            return
        self.store.transition(
            ctx.task_id,
            status,
            progress=100,
            error=err,
            force=True,
            message="完成" if status == "done" else "部分完成",
        )
        self.bus.publish(
            ctx.task_id,
            "done",
            {
                "status": status,
                "artifacts": self._artifact_urls(ctx),
                "stats": self._stats(ctx),
            },
        )

    def _has_pdf(self, ctx: TaskCtx, kind: str) -> bool:
        rec = self._on_loop(self.store.file_record, ctx.task_id, kind)
        return rec is not None and bool(rec.get("bytes"))

    def _build_zh(self, ctx: TaskCtx) -> None:
        """回写 zh 工程：按 chunks 表译文 splice + ctex 注入 + zip 登记。"""
        if (ctx.zh_dir / ".splice-done").is_file():
            return
        if ctx.zh_dir.exists():
            shutil.rmtree(ctx.zh_dir)
        shutil.copytree(ctx.base_dir, ctx.zh_dir)
        trans = {
            r["chunk_id"]: r["translation"]
            for r in self._on_loop(self.store.all_chunks, ctx.task_id)
            if r["status"] == "ok" and r["translation"]
        }
        n_files = 0
        for rel, res in ctx.scans.items():
            by_int: dict[int, str] = {}
            for c in res.chunks:
                cid = chunk_db_id(rel, c.span.start, c.span.end)
                zh = trans.get(cid)
                if zh is not None:
                    by_int[c.id] = zh
            if not by_int:
                continue
            out = reconstruct(res, by_int)
            (ctx.zh_dir / rel).write_text(out, encoding="utf-8")
            n_files += 1
        self._log(ctx, f"splice: {n_files} files rewritten")
        info = prepare_chinese(ctx.zh_dir, ctx.main_rel)
        self._log(ctx, f"inject: {info}")
        (ctx.zh_dir / ".splice-done").write_text("", encoding="utf-8")
        zip_path = ctx.root / "zh-src.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(ctx.zh_dir.rglob("*")):
                if f.is_file() and f.name != ".splice-done":
                    zf.write(f, f.relative_to(ctx.zh_dir).as_posix())
        self._register(ctx, "zh_src_zip", "zh-src.zip")

    def _engine(self, ctx: TaskCtx) -> Engine:
        """按注入面/默认构造引擎（xelatex 走 best-effort nonstopmode）。"""
        eng = ctx.engine_name or "tectonic"
        if self._engine_factory is not None:
            return self._engine_factory(eng)
        kw: dict[str, Any] = {"halt_on_error": False} if eng == "xelatex" else {}
        return engine_for(eng, **kw)

    def _compile_en(self, ctx: TaskCtx) -> None:
        """en.pdf：base/ 拷贝编译；失败只记 warning（不阻塞译文链）。"""
        if self._has_pdf(ctx, "en_pdf"):
            return
        work = ctx.root / "build-en"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(ctx.base_dir, work)
        res = self._engine(ctx).compile(
            work, ctx.main_rel, timeout=self._compile_timeout, sandbox=True
        )
        if res.has_pdf and res.pdf is not None:
            shutil.copyfile(res.pdf, ctx.root / "en.pdf")
            self._register(ctx, "en_pdf", "en.pdf")
        else:
            self._warning(
                ctx,
                "en_compile",
                f"原文编译未出 pdf（{res.log.first_error or res.stdout_tail[:120]}）",
            )

    def _compile_zh(self, ctx: TaskCtx) -> bool:
        """zh.pdf：zh/ 拷贝编译 + judge(expect_cjk)。返回「终态不 fault」。"""
        work = ctx.root / "build-zh"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(ctx.zh_dir, work)
        res = self._engine(ctx).compile(
            work, ctx.main_rel, timeout=self._compile_timeout, sandbox=True
        )
        if res.has_pdf and res.pdf is not None:
            shutil.copyfile(res.pdf, ctx.root / "zh.pdf")
            self._register(ctx, "zh_pdf", "zh.pdf")
        log_text = ""
        if res.log_path and res.log_path.exists():
            log_text = res.log_path.read_text(errors="replace")
        elif res.stdout_tail:
            log_text = res.stdout_tail
        (ctx.root / "compile.log").write_text(
            scrub(log_text, ctx.secrets.api_key), encoding="utf-8"
        )
        self._register(ctx, "compile_log", "compile.log")
        v = judge(res, expect_cjk=True, log_text=log_text)
        for r in v.reasons:
            self._log(ctx, f"judge: {r}")
        for n in v.notes:
            self._log(ctx, f"judge note: {n}")
        self._log(ctx, f"verdict: {v.status} cat={v.category} errs={v.n_errors}")
        return v.status in ("clean", "partial") or res.has_pdf

    def _build_dual(self, ctx: TaskCtx) -> None:
        """dual.json（§5.4）：documents 版本/pages + 页级 alignment + chunks。"""
        files = self.store.files(ctx.task_id)
        doc: dict[str, Any] = {"version": 1, "documents": {}, "chunks": []}
        en = files.get("en_pdf")
        zh = files.get("zh_pdf")
        if en:
            doc["documents"]["original"] = {
                "version": en.get("sha256") or "",
                "pages": pdf_pages(ctx.root / en["path"]),
            }
        if zh:
            doc["documents"]["translated"] = {
                "version": zh.get("sha256") or "",
                "pages": pdf_pages(ctx.root / zh["path"]),
            }
        # 无锚退化（§5.3 pairs 缺席路径 → 同页码映射）
        doc["alignment"] = {"kind": "pages"}
        doc["chunks"] = [
            {
                "seq": r["seq"],
                "src_file": r["src_file"],
                "en": r["src_text"],
                "zh": r["translation"] or "",
                "kind": r["kind"],
            }
            for r in self.store.all_chunks(ctx.task_id)
        ]
        atomic_json(ctx.root / "dual.json", doc)
        self._register(ctx, "dual_json", "dual.json")

    # ------------------------------------------------------------ pdf 管线

    async def _run_pdf(self, ctx: TaskCtx) -> None:
        """upload_pdf：BabelDOC sidecar（AGPL 边界=独立进程，§2.4）。"""
        self._stage(ctx, "compiling", "BabelDOC 双语转换", 30)
        uploads = sorted((ctx.root / "upload").glob("*"))
        if not uploads:
            self._fail(
                ctx,
                "internal",
                "upload payload missing",
                retryable=False,
                stage="compiling",
            )
            return
        src = uploads[0]
        en = ctx.root / "en.pdf"
        if not en.exists():
            shutil.copyfile(src, en)
        self._register(ctx, "en_pdf", "en.pdf")
        babeldoc = self._babeldoc or find_tool("babeldoc")
        if babeldoc is None:
            self._fail(
                ctx,
                "internal",
                "babeldoc 未安装（pipx/uv tool install babeldoc）",
                retryable=False,
                stage="compiling",
            )
            return
        outdir = ctx.root / "babeldoc-out"
        outdir.mkdir(exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            babeldoc,
            "--files",
            str(src),
            "--output",
            str(outdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        self._check_cancelled(ctx)
        self._log(
            ctx,
            f"babeldoc rc={proc.returncode}: {out.decode(errors='replace')[-400:]}",
        )
        produced = sorted(outdir.glob("*.pdf"))
        dual = next((p for p in produced if "dual" in p.name.lower()), None)
        mono = next((p for p in produced if p is not dual), None)
        if mono is not None:
            shutil.copyfile(mono, ctx.root / "zh.pdf")
            self._register(ctx, "zh_pdf", "zh.pdf")
        if dual is not None:
            shutil.copyfile(dual, ctx.root / "dual.pdf")
            self._register(ctx, "dual_pdf", "dual.pdf")
        if proc.returncode != 0 or mono is None:
            self._fail(
                ctx,
                "compile",
                "babeldoc 未产出译文 pdf",
                retryable=True,
                stage="compiling",
            )
            return
        self._build_dual(ctx)
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return
        self.store.transition(
            ctx.task_id, "done", progress=100, message="完成", force=True
        )
        self.bus.publish(
            ctx.task_id,
            "done",
            {
                "status": "done",
                "artifacts": self._artifact_urls(ctx),
                "stats": self._stats(ctx),
            },
        )

    # ------------------------------------------------------------ translator

    def _make_translator(self, ctx: TaskCtx) -> Translator:
        """默认工厂：key 或 ``TEXLATE_TRANSLATOR=gateway`` → 网关，否则 Mock。"""
        if self._translator_factory is not None:
            return self._translator_factory(ctx)
        force = os.environ.get("TEXLATE_TRANSLATOR", "").lower()
        if force == "mock":
            return MockTranslator()
        if force == "gateway" or ctx.secrets.api_key:
            client = ChatClient(ctx.secrets.base_url, ctx.secrets.api_key)
            return GatewayTranslator(client, ctx.secrets.model or "swe-2-medium")
        return MockTranslator()

    def _make_glossary(self, ctx: TaskCtx) -> Glossary | None:
        """术语表：config.glossary 路径优先，缺省内置默认层。"""
        try:
            cfg = json.loads(str(ctx.row.get("config_json") or "{}"))
        except json.JSONDecodeError:
            cfg = {}
        gpath = str(cfg.get("glossary") or ctx.options().get("glossary") or "")
        try:
            return Glossary.load(user_path=Path(gpath)) if gpath else Glossary.load()
        except (OSError, ValueError) as e:
            self._log(ctx, f"glossary load failed: {e}")
            return None

    def _make_cache(self, ctx: TaskCtx) -> SegmentCache:
        """段缓存门面（cfg 指纹前缀含 model/prompt_ver/lang[/tenant]）。"""
        glossary = str(ctx.options().get("glossary") or "")
        cfg = hashlib.sha256(
            f"{ctx.row['model']}|{PROMPT_VERSION}|{ctx.row['target_lang']}"
            f"|{glossary}".encode()
        ).hexdigest()[:16]
        if cache_scope() == "tenant":
            cfg = f"{ctx.row['tenant']}:{cfg}"
        return SegmentCache(
            self.store,
            prefix=cfg,
            model=str(ctx.row["model"]),
            target_lang=str(ctx.row["target_lang"]),
        )


# ---------------------------------------------------------------- Runner


class TaskRunner:
    """``asyncio.Queue`` 单消费者 + secrets 注册表 + 心跳 + cancel 路由。

    所有 DB 交互都在 loop 线程。``secrets`` 只挂内存——重启后
    ``auth_source='header'`` 的任务因凭证丢失走 ``needs_auth``。
    """

    def __init__(
        self,
        store: Store,
        bus: EventBus,
        worker: PipelineWorker,
        *,
        worker_id: str | None = None,
    ) -> None:
        """worker_id 缺省 ``w-<rand>``（崩溃恢复认领标记）。"""
        self.store = store
        self.bus = bus
        self.worker = worker
        self.worker_id = worker_id or f"w-{secrets_mod.token_hex(6)}"
        self.secrets: dict[str, Secrets] = {}
        self._queue: asyncio.Queue[str] | None = None
        self._dispatcher: asyncio.Task[None] | None = None
        self._ticker: asyncio.Task[None] | None = None
        self._current: tuple[str, asyncio.Task[None]] | None = None

    # ------------------------------------------------------------ 生命周期

    def start(self) -> None:
        """起 dispatcher + 心跳 ticker（必须在 loop 线程调）。"""
        self._queue = asyncio.Queue()
        self._dispatcher = asyncio.create_task(
            self._dispatch_loop(), name="texlate-dispatch"
        )
        self._ticker = asyncio.create_task(
            self._heartbeat_loop(), name="texlate-heartbeat"
        )

    async def stop(self) -> None:
        """关停：cancel ticker/dispatcher/当前任务，等收尾。"""
        for t in (self._ticker, self._dispatcher):
            if t is not None:
                t.cancel()
        if self._current is not None:
            self._current[1].cancel()
        pending = [t for t in (self._ticker, self._dispatcher) if t]
        if self._current is not None:
            pending.append(self._current[1])
        for t in pending:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001,S112 -- 关停吞全部
                continue

    # ------------------------------------------------------------ 对外

    def enqueue(self, task_id: str, secrets: Secrets | None = None) -> None:
        """入队；``secrets`` 给了就登记（header BYOK 任务的唯一凭证通道）。"""
        if secrets is not None:
            self.secrets[task_id] = secrets
        if self._queue is not None:
            self._queue.put_nowait(task_id)

    def secrets_for(self, task_id: str) -> Secrets | None:
        """读内存凭证（无则 None——API 侧回落 settings/env 决议）。"""
        return self.secrets.get(task_id)

    def cancel_running(self, task_id: str) -> bool:
        """取消正在跑的任务；未在跑（还在队列）返回 False。"""
        if self._current is not None and self._current[0] == task_id:
            self._current[1].cancel()
            return True
        return False

    # ------------------------------------------------------------ 内部

    async def _dispatch_loop(self) -> None:
        """串行消费：dequeue → 状态复核 → 建 ctx → worker.run。"""
        assert self._queue is not None  # noqa: S101 -- start() 后必有
        while True:
            task_id = await self._queue.get()
            try:
                row = self.store.get(task_id)
                if row is None or row["status"] != "queued":
                    self.secrets.pop(task_id, None)
                    continue
                sec = self.secrets.get(task_id) or Secrets(model=str(row["model"]))
                ctx = TaskCtx(
                    store=self.store,
                    bus=self.bus,
                    task_id=task_id,
                    row=row,
                    secrets=sec,
                    root=self.worker.data_dir / "tasks" / task_id,
                )
                self.store.claim(task_id, self.worker_id)
                task = asyncio.create_task(
                    self.worker.run(ctx), name=f"texlate-task-{task_id}"
                )
                self._current = (task_id, task)
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    log.exception("worker escaped for %s", task_id)
                finally:
                    self._current = None
                    self.secrets.pop(task_id, None)
            finally:
                self._queue.task_done()

    async def _heartbeat_loop(self) -> None:
        """每 ``_HEARTBEAT_S`` 秒 bump 当前任务 updated_at。"""
        while True:
            await asyncio.sleep(_HEARTBEAT_S)
            if self._current is not None:
                try:
                    self.store.heartbeat(self._current[0])
                except (StoreError, OSError):
                    continue
