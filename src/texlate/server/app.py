"""FastAPI app factory（web-layer §2 全部端点 + §4 BYOK 接线）。

``create_app()`` 组装：``Store``(SQLite 单写者) + ``EventBus``(SSE 扇出)
+ ``TaskRunner``/``PipelineWorker``（``start_worker=False`` 供测试按住
dispatcher）。横切：``/api`` 一律 ``Cache-Control: no-store``；local 模式
对 mutating 请求做 ``Origin``/``Sec-Fetch-Site`` CSRF 检查（texglot 同款）。

key 纪律：``X-Texlate-*`` 头只进内存 ``Secrets`` 随任务活，绝不写库/日志；
``GET /api/settings`` 出参只给 ``has_api_key``。

注意：本模块只在 server extra（fastapi/sse-starlette）存在时才会被导入——
``texlate.server`` 包本体保持轻依赖（``__init__`` 走 PEP 562 延迟加载）。
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

from texlate import __version__
from texlate.arxiv.fetch import normalize_arxiv_id
from texlate.compile.sandbox import find_tool
from texlate.server.events import EventBus, sse_frame
from texlate.server.settings import (
    TARGET_LANGS,
    UPLOAD_CAP,
    AuthContext,
    SettingsStore,
    provider_presets,
    resolve_auth,
    scrub,
    server_mode,
    server_salt,
    validate_base_url,
    validate_model,
)
from texlate.server.settings import data_dir as default_data_dir
from texlate.server.store import (
    Store,
    StoreError,
    TransitionError,
    new_task_id,
    valid_task_id,
)
from texlate.server.worker import (
    KIND_URL,
    URL_KIND,
    PipelineWorker,
    Secrets,
    TaskRunner,
    cache_key_for,
    sniff_upload,
)
from texlate.xlat.client import ChatClient, ChatError
from texlate.xlat.state import atomic_json

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from texlate.arxiv.cache import SourceCache
    from texlate.arxiv.fetch import Fetcher
    from texlate.compile.engine import Engine
    from texlate.server.worker import TaskCtx
    from texlate.xlat.pipeline import Translator

log = logging.getLogger(__name__)

#: arXiv id 白名单正则（fetch._valid_id 同款口径，§2.1 fullmatch）
_NEW_ID_RE = re.compile(r"^\d{4}\.\d{4,5}$")
_OLD_ID_RE = re.compile(r"^[a-zA-Z-]+(?:\.[A-Z][a-zA-Z]+)?/\d{7}$")

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

#: URL kind → media_type（§2.3 表）
_MEDIA = {
    "en.pdf": "application/pdf",
    "zh.pdf": "application/pdf",
    "dual.pdf": "application/pdf",
    "dual.json": "application/json",
    "src.tar": "application/gzip",
    "zh-src.zip": "application/zip",
    "compile.log": "text/plain; charset=utf-8",
    "md": "application/zip",
}


class _ApiError(Exception):
    """携带完整 JSON body 的 API 错误（409 需带 task_id 等附加字段）。"""

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        """Body 直出为响应体。"""
        self.status = status
        self.body = body
        super().__init__(str(body.get("detail", status)))


@dataclass(frozen=True, slots=True)
class UploadPart:
    """multipart 文件字段（``request.form()`` 产出归一到本形态）。"""

    filename: str
    data: bytes


_MULTIPART_OVERHEAD = 65536


async def _parse_multipart(request: Request) -> dict[str, str | UploadPart]:
    """``multipart/form-data`` → ``{name: str | UploadPart}``。

    走 starlette ``request.form()``（python-multipart 在 server extra 内）；
    ``Content-Length`` 超 ``UPLOAD_CAP + overhead`` 先 413 不读体，文件字段
    的精细上限在 upload handler 里按 payload 判。
    """
    clen = request.headers.get("content-length", "")
    if clen.isdigit() and int(clen) > UPLOAD_CAP + _MULTIPART_OVERHEAD:
        raise _ApiError(
            413, {"detail": f"upload > {UPLOAD_CAP}B", "code": "upload_too_large"}
        )
    form = await request.form()
    out: dict[str, str | UploadPart] = {}
    for name, val in form.multi_items():
        if isinstance(val, StarletteUploadFile):
            out[name] = UploadPart(filename=val.filename or "", data=await val.read())
        elif isinstance(val, str):
            out[name] = val
    return out


def _form_text(form: dict[str, str | UploadPart], name: str) -> str:
    """表单文本字段（文件字段同名时按缺省处理）。"""
    val = form.get(name)
    return val if isinstance(val, str) else ""


def _is_valid_arxiv(base: str) -> bool:
    return bool(_NEW_ID_RE.fullmatch(base) or _OLD_ID_RE.fullmatch(base))


def _json_error(status: int, detail: str, code: str | None = None) -> JSONResponse:
    """``{"detail": str, "code"?}`` 统一错误面。"""
    body: dict[str, Any] = {"detail": detail}
    if code:
        body["code"] = code
    return JSONResponse(body, status_code=status)


def _artifacts(store: Store, task_id: str) -> dict[str, str]:
    """``{db_kind: /api/files/{id}/{url_kind}}``（done 事件/快照共用）。"""
    return {
        kind: f"/api/files/{task_id}/{KIND_URL.get(kind, kind)}"
        for kind in store.files(task_id)
    }


def _accepted(row: dict[str, Any], status: int, extra: dict[str, Any]) -> JSONResponse:
    """202/200 任务响应统一形状（§2.1）。"""
    tid = str(row["id"])
    body = {
        "task_id": tid,
        "status": row["status"],
        "events_url": f"/api/task/{tid}",
        "reader_url": f"/api/task/{tid}/reader",
        **extra,
    }
    return JSONResponse(body, status_code=status)


def create_app(  # noqa: C901, PLR0913, PLR0915 -- 端点面即规格表，平铺即清单
    *,
    data_dir: Path | None = None,
    start_worker: bool = True,
    translator_factory: Callable[[TaskCtx], Translator] | None = None,
    fetcher: Fetcher | None = None,
    source_cache: SourceCache | None = None,
    engine_factory: Callable[[str], Engine] | None = None,
    babeldoc: str | None = None,
) -> FastAPI:
    """装配 app。``data_dir`` 缺省 ``TEXLATE_DATA_DIR``/``~/.texlate``。"""
    root = data_dir or default_data_dir()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings_store = SettingsStore(root)
    salt = server_salt(root)
    store = Store(root / "texlate.db")
    bus = EventBus(store)
    worker = PipelineWorker(
        store,
        bus,
        root,
        translator_factory=translator_factory,
        fetcher=fetcher,
        source_cache=source_cache,
        engine_factory=engine_factory,
        babeldoc=babeldoc,
    )
    runner = TaskRunner(store, bus, worker)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        store.open()
        recovered = store.recover_startup()
        if recovered["interrupted"] or recovered["needs_auth"]:
            log.info("startup recovery: %s", recovered)
        if start_worker:
            runner.start()
        yield
        await runner.stop()
        bus.close_all()
        store.close()

    app = FastAPI(title="texlate-server", version=__version__, lifespan=lifespan)
    app.state.data_dir = root
    app.state.store = store
    app.state.bus = bus
    app.state.runner = runner
    app.state.settings_store = settings_store
    app.state.babeldoc = babeldoc

    # ------------------------------------------------------------ 横切

    @app.middleware("http")
    async def local_only_mw(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Local 模式 CSRF：mutating /api 拒跨站（texglot 同款）。"""
        if server_mode() == "server":
            return await call_next(request)
        if request.method in ("POST", "PUT", "DELETE", "PATCH") and (
            request.url.path.startswith("/api")
        ):
            if request.headers.get("sec-fetch-site") == "cross-site":
                return _json_error(403, "cross-site request rejected")
            origin = request.headers.get("origin")
            if origin:
                host = (urlsplit(origin).hostname or "").lower()
                if host not in _LOCAL_HOSTS:
                    return _json_error(403, f"origin {host} not allowed")
        return await call_next(request)

    @app.middleware("http")
    async def no_store_mw(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        resp = await call_next(request)
        if request.url.path.startswith("/api"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.exception_handler(_ApiError)
    async def _api_error(_req: Request, exc: _ApiError) -> JSONResponse:
        return JSONResponse(exc.body, status_code=exc.status)

    @app.exception_handler(TransitionError)
    async def _transition_409(_req: Request, exc: TransitionError) -> JSONResponse:
        return _json_error(409, str(exc), "invalid_transition")

    @app.exception_handler(StoreError)
    async def _store_500(_req: Request, exc: StoreError) -> JSONResponse:
        return _json_error(500, str(exc), "internal")

    @app.exception_handler(RequestValidationError)
    async def _validation_400(
        _req: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _json_error(400, str(exc.errors()[:3]), "invalid_request")

    # ------------------------------------------------------------ 辅助

    def _auth(request: Request) -> AuthContext:
        """Header > settings > env 三级决议（§4.1）。"""
        return resolve_auth(
            settings_store.load(),
            header_key=request.headers.get("x-texlate-key", ""),
            header_base_url=request.headers.get("x-texlate-base-url", ""),
            header_model=request.headers.get("x-texlate-model", ""),
            mode=server_mode(),
            salt=salt,
        )

    def _get_task(request: Request, task_id: str) -> dict[str, Any]:
        """Id 形态 + 存在 + tenant 隔离三检；不过 → 404。"""
        row = store.get(task_id) if valid_task_id(task_id) else None
        if row is None or row["tenant"] != _auth(request).tenant:
            raise HTTPException(404, "task not found")
        return row

    def _secrets_for(request: Request, row: dict[str, Any]) -> Secrets:
        """重决议凭证 → 内存 ``Secrets``（retry/enqueue 用）。"""
        auth = _auth(request)
        return Secrets(
            api_key=auth.api_key,
            base_url=auth.base_url,
            model=str(row["model"]),
            source=auth.source,
        )

    async def _read_body(request: Request) -> dict[str, Any]:
        """可选 JSON body；坏 JSON → 400。"""
        raw = await request.body()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise _ApiError(400, {"detail": f"bad json: {e}"}) from e
        return data if isinstance(data, dict) else {}

    def _create_and_enqueue(  # noqa: PLR0913 -- 建行参数面
        request: Request,
        *,
        kind: str,
        arxiv_id: str | None,
        source_name: str,
        title: str,
        model: str,
        target_lang: str,
        options: dict[str, Any],
        prefer: str,
        cache_key: str | None,
        task_id: str | None = None,
    ) -> tuple[dict[str, Any], int, dict[str, Any]]:
        """dedup/reuse/idempotency 判别 + 建行 + 入队。

        返回 ``(row, http_status, extra_body)``——reuse/idempotent 命中时
        status 200/202 且不新建。
        """
        auth = _auth(request)
        idem = request.headers.get("idempotency-key") or options.get("idempotency_key")
        if idem:
            hit = store.find_by_idempotency(auth.tenant, str(idem))
            if hit is not None:
                return hit, 202, {"cache": "idempotent"}
            options = {**options, "idempotency_key": str(idem)}
        if cache_key and prefer == "reuse":
            active = store.find_active_by_cache_key(cache_key)
            if active is not None:
                raise _ApiError(
                    409,
                    {
                        "detail": f"active task {active['id']} exists",
                        "task_id": active["id"],
                        "code": "duplicate_active",
                    },
                )
            done = store.find_reusable(cache_key)
            if done is not None:
                return done, 200, {"reused": True}
        tid = task_id or new_task_id()
        config = {
            "base_url": auth.base_url,
            "model": model,
            "glossary": str(options.get("glossary") or ""),
            "engine": str(options.get("engine") or "auto"),
            "concurrency": int(options.get("concurrency") or 3),
        }
        try:
            row = store.create_task(
                task_id=tid,
                kind=kind,
                target_lang=target_lang,
                model=model,
                arxiv_id=arxiv_id,
                source_name=source_name,
                title=title,
                config=config,
                options=options,
                auth_source=auth.source,
                tenant=auth.tenant,
                cache_key=cache_key,
            )
        except sqlite3.IntegrityError:
            if prefer != "fresh":
                raise
            # fresh：cache_key 撞活跃行——放弃 dedup 键强行新建（§2.1）
            row = store.create_task(
                task_id=tid,
                kind=kind,
                target_lang=target_lang,
                model=model,
                arxiv_id=arxiv_id,
                source_name=source_name,
                title=title,
                config=config,
                options=options,
                auth_source=auth.source,
                tenant=auth.tenant,
                cache_key=None,
            )
        runner.enqueue(
            tid,
            Secrets(
                api_key=auth.api_key,
                base_url=auth.base_url,
                model=model,
                source=auth.source,
            ),
        )
        return row, 202, {"cache": "miss"}

    # ------------------------------------------------------------ §2.1 arxiv

    @app.post("/api/arxiv/{arxiv_id:path}/translate")
    async def arxiv_translate(request: Request, arxiv_id: str) -> Response:
        """建 arxiv 任务：202 + cache_key dedup/reuse（§2.1）。"""
        base, ver = normalize_arxiv_id(arxiv_id)
        if not _is_valid_arxiv(base):
            return _json_error(400, f"invalid arxiv id: {arxiv_id!r}")
        body = await _read_body(request)
        options = dict(body.get("options") or {})
        try:
            model = validate_model(str(body.get("model") or _auth(request).model))
        except ValueError as e:
            return _json_error(400, str(e))
        target_lang = str(
            body.get("target_lang") or settings_store.load()["target_lang"]
        )
        if target_lang not in TARGET_LANGS:
            return _json_error(400, f"target_lang ∈ {sorted(TARGET_LANGS)}")
        if body.get("glossary"):
            options["glossary"] = str(body["glossary"])
        prefer = str(options.get("prefer") or "reuse")
        if prefer not in ("reuse", "fresh"):
            return _json_error(400, "options.prefer ∈ reuse|fresh")
        cache_key = cache_key_for(
            arxiv_id=base,
            version=ver,
            model=model,
            target_lang=target_lang,
            tenant=_auth(request).tenant,
        )
        row, status, extra = _create_and_enqueue(
            request,
            kind="arxiv",
            arxiv_id=base,
            source_name=arxiv_id,
            title="",
            model=model,
            target_lang=target_lang,
            options=options,
            prefer=prefer,
            cache_key=cache_key,
        )
        return _accepted(row, status, extra)

    # ------------------------------------------------------------ §2.2 task/SSE

    @app.get("/api/task/{task_id}")
    async def task_get(request: Request, task_id: str) -> Response:
        """快照 or SSE 流（Accept: text/event-stream；Last-Event-ID 重放）。"""
        _get_task(request, task_id)
        accept = request.headers.get("accept", "")
        if "text/event-stream" not in accept:
            return JSONResponse(
                store.snapshot(task_id, artifacts=_artifacts(store, task_id))
            )
        try:
            last_id = int(request.headers.get("last-event-id", "0") or 0)
        except ValueError:
            last_id = 0

        async def gen() -> AsyncIterator[dict[str, Any]]:
            snap = store.snapshot(task_id, artifacts=_artifacts(store, task_id))
            yield sse_frame({"seq": 0, "type": "snapshot", "data": snap})
            async for ev in bus.stream(task_id, last_event_id=last_id):
                yield sse_frame(ev)

        return EventSourceResponse(gen(), ping=15)

    # ------------------------------------------------------------ §2.3 files

    @app.get("/api/files/{task_id}")
    async def files_list(request: Request, task_id: str) -> Response:
        """产物清单（db kind → bytes/sha256/created_at/url）。"""
        _get_task(request, task_id)
        out = {
            kind: {
                "bytes": rec["bytes"],
                "sha256": rec["sha256"],
                "created_at": rec["created_at"],
                "url": f"/api/files/{task_id}/{KIND_URL.get(kind, kind)}",
            }
            for kind, rec in store.files(task_id).items()
        }
        return JSONResponse({"artifacts": out})

    @app.get("/api/files/{task_id}/{kind}")
    async def file_get(
        request: Request,
        task_id: str,
        kind: str,
        download: int = 0,
        version: str = "",
    ) -> Response:
        """产物下载：kind 白名单 + ``?version=`` sha256 校验 + download=1。"""
        row = _get_task(request, task_id)
        db_kind = URL_KIND.get(kind)
        if db_kind is None:
            return _json_error(404, f"unknown kind {kind!r}")
        rec = store.file_record(task_id, db_kind)
        if rec is None:
            return _json_error(404, f"no artifact {kind}")
        if version and rec.get("sha256") and version != rec["sha256"]:
            return _json_error(
                409,
                f"version mismatch: have {rec['sha256'][:12]}",
                "version_mismatch",
            )
        task_root = (root / "tasks" / task_id).resolve()
        path = (task_root / rec["path"]).resolve()
        if not path.is_file() or not path.is_relative_to(task_root):
            return _json_error(404, "artifact file missing")
        headers = None
        if download:
            stem = row.get("arxiv_id") or task_id
            headers = {
                "Content-Disposition": (f'attachment; filename="texlate-{stem}-{kind}"')
            }
        return FileResponse(
            path,
            media_type=_MEDIA.get(kind, "application/octet-stream"),
            headers=headers,
        )

    # ------------------------------------------------------------ §2.4 upload

    def _check_upload_route(route: str, babeldoc: str | None, filename: str) -> None:
        """魔数路由 → 错误面：docx/epub 501、unknown 400、pdf 无 babeldoc 501。"""
        if route in ("docx", "epub"):
            raise _ApiError(
                501,
                {
                    "detail": f"{route} 支持在 M2 之前不可用",
                    "code": "unsupported_format",
                },
            )
        if route == "unknown":
            raise _ApiError(
                400,
                {
                    "detail": f"无法识别上传格式: {filename}",
                    "code": "unsupported_format",
                },
            )
        if route == "upload_pdf" and babeldoc is None:
            raise _ApiError(
                501,
                {
                    "detail": (
                        "babeldoc 未安装：pipx install babeldoc / uv tool install"
                        " babeldoc"
                    ),
                    "code": "unsupported_format",
                },
            )

    def _upload_fields(
        request: Request, form: dict[str, str | UploadPart]
    ) -> tuple[str, str, dict[str, Any]]:
        """表单字段 → ``(model, target_lang, options)``；非法 → ``_ApiError``。"""
        options_raw = _form_text(form, "options")
        try:
            options = json.loads(options_raw) if options_raw else {}
        except json.JSONDecodeError:
            raise _ApiError(400, {"detail": "options 字段不是合法 JSON"}) from None
        if not isinstance(options, dict):
            options = {}
        try:
            model = validate_model(_form_text(form, "model") or _auth(request).model)
        except ValueError as e:
            raise _ApiError(400, {"detail": str(e)}) from e
        target_lang = _form_text(form, "target_lang") or str(
            settings_store.load()["target_lang"]
        )
        if target_lang not in TARGET_LANGS:
            raise _ApiError(400, {"detail": f"target_lang ∈ {sorted(TARGET_LANGS)}"})
        if _form_text(form, "main"):
            options["main"] = _form_text(form, "main")
        return model, target_lang, options

    @app.post("/api/upload")
    async def upload(request: Request) -> Response:
        """Multipart 上传：魔数路由 upload_tex/upload_pdf（§2.4）。"""
        form = await _parse_multipart(request)
        file = form.get("file")
        if not isinstance(file, UploadPart):
            raise _ApiError(400, {"detail": "multipart field 'file' required"})
        data = file.data
        if not data:
            raise _ApiError(400, {"detail": "empty upload"})
        if len(data) > UPLOAD_CAP:
            raise _ApiError(
                413,
                {"detail": f"upload > {UPLOAD_CAP}B", "code": "upload_too_large"},
            )
        filename = file.filename or "upload.bin"
        route = sniff_upload(data, filename)
        _check_upload_route(
            route, app.state.babeldoc or find_tool("babeldoc"), filename
        )
        model, target_lang, options = _upload_fields(request, form)
        # 先落 blob（建行前），再建行+入队——task_id 两侧共用
        task_id = new_task_id()
        updir = root / "tasks" / task_id / "upload"
        updir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.+-]", "_", Path(filename).name)
        (updir / (safe or "upload.bin")).write_bytes(data)
        row, status, extra = _create_and_enqueue(
            request,
            kind=route,
            arxiv_id=None,
            source_name=filename,
            title=filename,
            model=model,
            target_lang=target_lang,
            options=options,
            prefer="fresh",
            cache_key=None,
            task_id=task_id,
        )
        return _accepted(row, status, extra)

    # ------------------------------------------------------------ §2.5 helpers

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        """``{ok, version, compilers, data_dir}``。"""
        return {
            "ok": True,
            "version": __version__,
            "compilers": {
                "tectonic": find_tool("tectonic") is not None,
                "xelatex": find_tool("xelatex") is not None,
                "babeldoc": (app.state.babeldoc or find_tool("babeldoc")) is not None,
            },
            "data_dir": str(root),
        }

    @app.get("/api/tasks")
    async def tasks_list(request: Request, status: str = "") -> Response:
        """Tenant 过滤任务列表（``?status=`` 再过滤）。"""
        rows = store.list_tasks(_auth(request).tenant, status or None)
        return JSONResponse(
            {
                "tasks": [
                    {
                        "task_id": r["id"],
                        "kind": r["kind"],
                        "status": r["status"],
                        "stage": r["stage"],
                        "progress": r["progress"],
                        "message": r["message"],
                        "title": r["title"],
                        "arxiv_id": r["arxiv_id"],
                        "source_name": r["source_name"],
                        "target_lang": r["target_lang"],
                        "model": r["model"],
                        "created_at": r["created_at"],
                        "updated_at": r["updated_at"],
                        "counters": {
                            "total": r["total_chunks"],
                            "done": r["done_chunks"],
                            "cached": r["cached_chunks"],
                            "failed": r["failed_chunks"],
                            "tokens": r["tokens"],
                        },
                        "error": (
                            json.loads(r["error_json"]) if r["error_json"] else None
                        ),
                    }
                    for r in rows
                ]
            }
        )

    @app.post("/api/task/{task_id}/cancel")
    async def task_cancel(request: Request, task_id: str) -> Response:
        """ACTIVE → cancelled；跑中任务 cancel asyncio task + done 事件。"""
        _get_task(request, task_id)
        try:
            store.transition(task_id, "cancelled", message="已取消")
        except TransitionError as e:
            return _json_error(409, str(e), "invalid_transition")
        runner.cancel_running(task_id)
        row = store.get(task_id) or {}
        bus.publish(
            task_id,
            "done",
            {
                "status": "cancelled",
                "artifacts": _artifacts(store, task_id),
                "stats": {
                    "tokens": row.get("tokens", 0),
                    "seconds": round(
                        time.time() - float(row.get("created_at") or 0), 1
                    ),
                    "chunks_failed": row.get("failed_chunks", 0),
                },
            },
        )
        return JSONResponse({"task_id": task_id, "status": "cancelled"})

    @app.post("/api/task/{task_id}/retry")
    async def task_retry(request: Request, task_id: str) -> Response:
        """终态/needs_auth → queued 重入队；body 可带 ``{main, options}``。"""
        row = _get_task(request, task_id)
        body = await _read_body(request)
        header_key = request.headers.get("x-texlate-key", "")
        if row["status"] == "needs_auth" and not header_key:
            return _json_error(
                401,
                "auth_source=header：重试必须重带 X-Texlate-Key",
                "auth_required",
            )
        try:
            opts = json.loads(row.get("options_json") or "{}")
        except json.JSONDecodeError:
            opts = {}
        if not isinstance(opts, dict):
            opts = {}
        if isinstance(body.get("options"), dict):
            opts.update(body["options"])
        if body.get("main"):
            opts["main"] = str(body["main"])
            if str(body["main"]) != row.get("main_tex"):
                # 换主文件 → 解析产物作废（chunks/base/zh 重建，src/ 保留）
                store.conn.execute("DELETE FROM chunks WHERE task_id = ?", (task_id,))
                store.conn.commit()
                for d in ("base", "zh", "build-en", "build-zh"):
                    shutil.rmtree(root / "tasks" / task_id / d, ignore_errors=True)
        store.update_fields(task_id, options_json=json.dumps(opts))
        try:
            store.transition(task_id, "queued", message="重试入队")
        except TransitionError as e:
            return _json_error(409, str(e), "invalid_transition")
        runner.enqueue(task_id, _secrets_for(request, row))
        return _accepted(store.get(task_id) or row, 202, {"cache": "retry"})

    # ------------------------------------------------------------ reader

    @app.get("/api/task/{task_id}/reader")
    async def reader_get(request: Request, task_id: str) -> Response:
        """``{documents, alignment, reading, view}``（§2.5/§5.4）。"""
        _get_task(request, task_id)
        dual_path = root / "tasks" / task_id / "dual.json"
        if not dual_path.is_file():
            return _json_error(404, "dual.json 未产出")
        try:
            dual = json.loads(dual_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return _json_error(500, "dual.json 损坏", "internal")
        docs = dual.get("documents") or {}
        for side, kind in (("original", "en.pdf"), ("translated", "zh.pdf")):
            if isinstance(docs.get(side), dict):
                docs[side]["url"] = f"/api/files/{task_id}/{kind}"
        reading: dict[str, Any] = {}
        rpath = root / "tasks" / task_id / "reading.json"
        if rpath.is_file():
            try:
                reading = json.loads(rpath.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                reading = {}
        return JSONResponse(
            {
                "documents": docs,
                "alignment": dual.get("alignment") or {"kind": "pages"},
                "reading": reading,
                "view": ("html" if store.file_record(task_id, "md_zip") else "pdf"),
            }
        )

    @app.put("/api/task/{task_id}/reader/position")
    async def reader_put(request: Request, task_id: str) -> Response:
        """阅读位置落盘（``tasks/{id}/reading.json``）；版本不符 409。"""
        _get_task(request, task_id)
        body = await _read_body(request)
        want = str(body.get("document_version") or "")
        if want:
            rec = store.file_record(task_id, "zh_pdf")
            cur = str((rec or {}).get("sha256") or "")
            if cur and want != cur:
                return _json_error(409, "document_version mismatch", "version_mismatch")
        keep = {
            k: body[k]
            for k in ("positions", "active", "mode", "zoom", "sync")
            if k in body
        }
        tdir = root / "tasks" / task_id
        tdir.mkdir(parents=True, exist_ok=True)
        atomic_json(tdir / "reading.json", keep)
        return JSONResponse({"ok": True})

    # ------------------------------------------------------------ §4 settings

    @app.get("/api/settings")
    async def settings_get() -> dict[str, Any]:
        """public_settings：key 剥壳只给 ``has_api_key``。"""
        return settings_store.public()

    @app.put("/api/settings")
    async def settings_put(request: Request) -> Response:
        """合并更新（0600 原子写 + connections 分槽）。"""
        body = await _read_body(request)
        try:
            settings_store.save(body)
        except ValueError as e:
            return _json_error(400, str(e))
        return JSONResponse(settings_store.public())

    @app.post("/api/settings/test")
    async def settings_test(request: Request) -> Response:
        """探活配置端点：body 可带覆盖值；错误信息先过 scrub。"""
        body = await _read_body(request)
        cur = settings_store.load()
        base_url = str(body.get("base_url") or cur["base_url"])
        api_key = str(body.get("api_key") or cur["api_key"])
        model = str(body.get("model") or cur["model"])
        try:
            base_url = validate_base_url(base_url)
        except ValueError as e:
            return _json_error(400, str(e))
        client = ChatClient(base_url, api_key)
        try:
            models = await client.list_models()
        except ChatError as e:
            detail = scrub(str(e), api_key)
            return JSONResponse({"ok": False, "detail": detail})
        except Exception as e:  # noqa: BLE001 -- 探活失败面收敛为 ok:false
            detail = scrub(str(e), api_key)
            return JSONResponse({"ok": False, "detail": detail})
        finally:
            await client.aclose()
        return JSONResponse({"ok": True, "models": models[:50], "model": model})

    @app.get("/api/providers")
    async def providers() -> dict[str, Any]:
        """列 provider 预设清单（key 只给 has_api_key/has_env_key）。"""
        return {"providers": provider_presets(settings_store.load())}

    # ------------------------------------------------------------ SPA 静态

    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        from fastapi.staticfiles import StaticFiles  # noqa: PLC0415 -- 可选挂载

        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
