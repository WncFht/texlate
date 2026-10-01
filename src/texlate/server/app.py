"""FastAPI app factory（web-layer §2 全部端点 + §4 BYOK 接线）。

``create_app()`` 组装：``Store``(SQLite 单写者) + ``EventBus``(SSE 扇出)
+ ``TaskRunner``/``PipelineWorker``（``start_worker=False`` 供测试按住
dispatcher）→ ``AppDeps`` 注入 ``server/routers/`` 各域路由叶（端点面
按域分叶：tasks/compat/files/upload/share/meta/reader/settings/discover）。
横切：``/api`` 一律 ``Cache-Control: no-store``；入站闸
（``request_gate_mw``）做 local Host 白名单 + mutating 请求
``Origin``/``Sec-Fetch-Site`` 同源检查 + server 形态匿名写 401。
请求层纯件（multipart 流式落盘/body 闸/同源判定/统一错误面）在
``server/http.py``；后台清扫簇（孤儿目录启动清扫 + retention
瘦身/淘汰 sweep）在 ``server/sweep.py``。

key 纪律：``X-Texlate-*`` 头只进内存 ``Secrets`` 随任务活，绝不写库/日志；
``GET /api/settings`` 出参只给 ``has_api_key``。

注意：本模块只在 server extra（fastapi/sse-starlette）存在时才会被导入——
``texlate.server`` 包本体保持轻依赖（``__init__`` 走 PEP 562 延迟加载）。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from texlate import __version__
from texlate.server.events import EventBus
from texlate.server.http import (
    _BUILD_COMMIT,
    _OPTIONS_JSON_CAP,
    _STARTED_AT,
    _ApiError,
    _clean_task_options,
    _exposed_bind_warning,
    _host_only,
    _json_error,
    _loopback_bind,
    _loopback_peer,
    _probe_git_commit,
    _route_path,
    _same_origin,
)
from texlate.server.routers import AppDeps, discover, refs, register_routers
from texlate.server.settings import (
    BYOK_FIELDS,
    SettingsStore,
    install_log_scrub,
    server_mode,
    server_salt,
)
from texlate.server.settings import data_dir as default_data_dir
from texlate.server.staticfiles import mount_spa
from texlate.server.store import (
    Store,
    StoreError,
    TransitionError,
)
from texlate.server.sweep import (
    _sweep_orphan_task_dirs,
    retention_loop,
    sweep_once,
)
from texlate.server.worker import (
    URL_KIND,
    PipelineWorker,
    TaskRunner,
    _env_timeout,
)
from texlate.textutil.osutil import ENV_COMPILE_TIMEOUT
from texlate.xlat.client import LOOPBACK_HOSTS

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable
    from pathlib import Path

    from texlate.arxiv.cache import SourceCache
    from texlate.arxiv.fetch import Fetcher
    from texlate.compile.engine import Engine
    from texlate.server.worker import TaskCtx
    from texlate.xlat.pipeline import Translator

#: ``texlate.server.app.X`` 可达性契约——测试 patch/读面与 cli/``__main__``
#: 转口的公共面。写面 patch 目标（``UPLOAD_CAP``/``_JSON_BODY_CAP``/
#: ``find_tool``）已随消费代码迁出本模块，不收编——留着会是沉默失效的
#: 假缝，让旧 patch 点 AttributeError 显形。
__all__ = [
    "URL_KIND",
    "_BUILD_COMMIT",
    "_OPTIONS_JSON_CAP",
    "_STARTED_AT",
    "_ApiError",
    "_clean_task_options",
    "_exposed_bind_warning",
    "_loopback_bind",
    "_probe_git_commit",
    "create_app",
    "retention_loop",
    "sweep_once",
]

log = logging.getLogger(__name__)


def create_app(  # noqa: C901, PLR0913, PLR0915 -- 装配阶梯 + 闭包面平铺
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
        # env ``TEXLATE_COMPILE_TIMEOUT`` > settings.json compile_timeout > 240
        compile_timeout=_env_timeout(
            ENV_COMPILE_TIMEOUT, settings_store.load()["compile_timeout"]
        ),
    )
    runner = TaskRunner(store, bus, worker)
    #: multipart 文件字段流式落盘目录（``_parse_multipart`` 写入面）；
    #: 残骸由 lifespan 启动段清扫。
    spool_dir = root / "tmp" / "upload-spool"
    deps = AppDeps(
        root=root,
        store=store,
        bus=bus,
        runner=runner,
        worker=worker,
        settings_store=settings_store,
        salt=salt,
        spool_dir=spool_dir,
        babeldoc=babeldoc,
    )

    def _key_provider() -> list[str]:
        """当前该抹的 key 集合：settings key + 运行中 header key（RedactFilter 动态取）。"""
        keys = [str(settings_store.load().get("api_key") or "")]
        keys.extend(s.api_key for s in runner.secrets.values())
        return [k for k in keys if k]

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # §4.2 第二道防线：uvicorn log config 此时已就绪，filter 落到
        # root+uvicorn 全部 handler（传播链上各 handler 独立判定）。
        install_log_scrub(_key_provider)
        store.open()
        recovered = store.recover_startup()
        orphans = _sweep_orphan_task_dirs(store, root)
        # 上传 spool 目录只收流式落盘的临时件——进程被杀留的残骸启动即清
        spool_dir.mkdir(parents=True, exist_ok=True)
        for stale in spool_dir.iterdir():
            with suppress(OSError):
                stale.unlink()
        if recovered["interrupted"] or recovered["needs_auth"]:
            log.info("startup recovery: %s", recovered)
        if orphans:
            log.info("swept %d orphan task dir(s)", orphans)
        retention = asyncio.create_task(
            retention_loop(store, settings_store, runner, root / "tasks")
        )
        if start_worker:
            runner.start()
        try:
            yield
        finally:
            retention.cancel()
            with suppress(asyncio.CancelledError):
                await retention
            await runner.stop()
            bus.close_all()
            await discover._aclose_clients()  # noqa: SLF001 -- lifespan 收尾钩
            await refs._aclose_clients()  # noqa: SLF001 -- 同上 loop 桶收尾
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
    async def request_gate_mw(  # noqa: PLR0911 -- 闸序列每层一个早退 return
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """入站闸：local 回环对端+Host 白名单 + mutating /api 跨站检查 + server 匿名写 401。

        - local 形态双闸：TCP 对端须回环（伪造 ``Host: localhost`` 的外网
          直连在这层死）；``Host`` 剥端口须 loopback 且不可缺席——
          Host 缺席无法证明浏览器来源合法性（HTTP/1.1 恒有 Host，
          HTTP/1.0 裸连场景事实上不存在），fail closed。
        - mutating /api：``Sec-Fetch-Site: cross-site`` 一律拒；``Origin``
          在时须与请求 scheme+Host（含端口）同源，或命中 server 形态
          ``cors_origins`` allowlist（部署方显式跨域面）；两头皆无的
          非浏览器客户端（curl/脚本）放行。
        - server 形态无 ``X-Texlate-Key`` 的 mutation 一律 401——settings/env
          的部署方 key 不外借（``resolve_auth`` 同侧不再回落）。

        ``/api`` 前缀判定走 ``_route_path``（剥 ``root_path``）而非
        ``request.url.path``——后者含 ``root_path``，``--root-path``/反代
        子路径部署下 ``/tex/api/…`` 会骗过前缀闸而路由照样命中。
        """
        if server_mode() != "server":
            peer = request.client.host if request.client is not None else ""
            if not _loopback_peer(request):
                return _json_error(403, f"peer {peer} not allowed", "forbidden")
            host = request.headers.get("host", "")
            if not host or _host_only(host) not in LOOPBACK_HOSTS:
                return _json_error(
                    403, f"host {host or '<absent>'} not allowed", "forbidden"
                )
        mutating = request.method in (
            "POST",
            "PUT",
            "DELETE",
            "PATCH",
        ) and _route_path(request.scope).startswith("/api")
        if not mutating:
            return await call_next(request)
        origin = request.headers.get("origin")
        if origin and origin in getattr(app.state, "cors_origins", ()):
            pass  # 部署方 CORS allowlist 显式放行的跨域源
        elif request.headers.get("sec-fetch-site") == "cross-site":
            return _json_error(403, "cross-site request rejected", "forbidden")
        elif origin and not _same_origin(request, origin):
            return _json_error(403, f"origin {origin} not allowed", "forbidden")
        if server_mode() == "server" and not request.headers.get("x-texlate-key"):
            return _json_error(
                401,
                "server 形态 mutation 要求 X-Texlate-Key",
                "auth_required",
            )
        return await call_next(request)

    @app.middleware("http")
    async def no_store_mw(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        resp = await call_next(request)
        if _route_path(request.scope).startswith("/api"):
            # 端点可经 request.state.cache_control 覆盖——内容寻址产物
            # （/api/files ?version=sha 匹配）放 private,immutable
            resp.headers["Cache-Control"] = (
                getattr(request.state, "cache_control", None) or "no-store"
            )
        return resp

    # server 形态 CORS allowlist（web-layer §6）：settings.cors_origins 显式配，
    # 空 = 不挂中间件 = 禁跨域（浏览器同源策略天然拒）。local 形态不读此项——
    # 跨站防护由 request_gate_mw 的同源检查承担；allowlist 同时喂给该闸作
    # mutation 的跨域放行面。
    _origins: list[str] = []
    if server_mode() == "server":
        _origins = list(settings_store.load().get("cors_origins") or [])
        if _origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=_origins,
                allow_methods=["GET", "POST", "PUT", "DELETE"],
                allow_headers=[
                    "content-type",
                    "idempotency-key",
                    "last-event-id",
                    # BYOK 头面与 ``BYOK_FIELDS`` 单源——加字段自动进 CORS
                    *(spec.header for spec in BYOK_FIELDS),
                ],
            )
    app.state.cors_origins = _origins

    # gzip 出站压缩：最后挂即最外层（starlette 后加先跑），CORS/闸响应也
    # 过它。server 形态远程访问 JSON 端点省 3-10x 流量；local 回环无感。
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.exception_handler(_ApiError)
    async def _api_error(_req: Request, exc: _ApiError) -> JSONResponse:
        return JSONResponse(exc.body, status_code=exc.status)

    @app.exception_handler(TransitionError)
    async def _transition_409(_req: Request, exc: TransitionError) -> JSONResponse:
        return _json_error(409, str(exc), "invalid_transition")

    @app.exception_handler(StoreError)
    async def _store_500(_req: Request, exc: StoreError) -> JSONResponse:
        return _json_error(500, str(exc), "internal")

    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        """裸 ``HTTPException`` 归一到统一错误面（404/405 带 code）。"""
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code)
        resp = _json_error(exc.status_code, str(exc.detail), code)
        for k, v in (exc.headers or {}).items():
            resp.headers[k] = v
        return resp

    @app.exception_handler(RequestValidationError)
    async def _validation_400(
        _req: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Pydantic 错误列表转可读 detail（``loc: msg``；截前 3 条）。"""
        msgs = "; ".join(
            f"{'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg', '')}"
            for e in exc.errors()[:3]
        )
        return _json_error(400, msgs or "请求参数校验失败", "invalid_request")

    # ------------------------------------------------------------ 路由 + SPA

    register_routers(app, deps)
    mount_spa(app)

    return app
