"""FastAPI app factory（web-layer §2 全部端点 + §4 BYOK 接线）。

``create_app()`` 组装：``Store``(SQLite 单写者) + ``EventBus``(SSE 扇出)
+ ``TaskRunner``/``PipelineWorker``（``start_worker=False`` 供测试按住
dispatcher）→ ``AppDeps`` 注入 ``server/routers/`` 各域路由叶（端点面
按域分叶：tasks/compat/files/upload/share/meta/reader/settings）。
横切：``/api`` 一律 ``Cache-Control: no-store``；入站闸
（``request_gate_mw``）做 local Host 白名单 + mutating 请求
``Origin``/``Sec-Fetch-Site`` 同源检查 + server 形态匿名写 401。
请求层纯件（multipart 流式落盘/body 闸/同源判定/统一错误面）在
``server/http.py``。

key 纪律：``X-Texlate-*`` 头只进内存 ``Secrets`` 随任务活，绝不写库/日志；
``GET /api/settings`` 出参只给 ``has_api_key``。

注意：本模块只在 server extra（fastapi/sse-starlette）存在时才会被导入——
``texlate.server`` 包本体保持轻依赖（``__init__`` 走 PEP 562 延迟加载）。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette._utils import get_route_path  # 路由匹配同一条路径视图（剥 root_path）
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
    _host_only,
    _json_error,
    _loopback_bind,
    _loopback_peer,
    _probe_git_commit,
    _same_origin,
)
from texlate.server.routers import AppDeps, register_routers
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
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    Store,
    StoreError,
    TransitionError,
    slim_task_dir,
    valid_task_id,
)
from texlate.server.store._common import _dir_size
from texlate.server.worker import (
    URL_KIND,
    PipelineWorker,
    TaskRunner,
    _env_timeout,
)
from texlate.xlat.client import _LOOPBACK_HOSTS

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
    "_loopback_bind",
    "_probe_git_commit",
    "create_app",
]

log = logging.getLogger(__name__)


def create_app(  # noqa: C901, PLR0913, PLR0915 -- 装配阶梯+闭包面平铺
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
            "TEXLATE_COMPILE_TIMEOUT", settings_store.load()["compile_timeout"]
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

    def _sweep_orphan_task_dirs() -> int:
        """启动清扫：``tasks/{id}`` 无对应 DB 行的孤儿目录 → 清扫数。

        upload/share_import 在建行前落盘 blob——进程在写盘与 INSERT 之间
        被杀会留孤儿目录。只在启动窗口跑（尚无并发建行）；名字非法或不
        是 task-id 形态的条目不碰。
        """
        tasks_root = root / "tasks"
        if not tasks_root.is_dir():
            return 0
        known = set(store.task_ids())
        n = 0
        for d in tasks_root.iterdir():
            if not (valid_task_id(d.name) and d.name not in known):
                continue
            if d.is_dir() and not d.is_symlink():
                shutil.rmtree(d, ignore_errors=True)
            else:
                with suppress(OSError):
                    d.unlink()
            n += 1
        return n

    tasks_dir = root / "tasks"

    async def _slim_terminal() -> None:
        """瘦身段（无条件）：终态任务 ``tasks/{id}/`` 清未登记字节。

        产物/记录全留；done/partial 追加 ``zh``/``base`` 整树——单块重
        译（``_ensure_scans`` 重解析 base/ + resplice 写 zh/）与 share
        打包的 glossary 指纹都读活树。DB 留 loop 线程，dir walk 逐任务
        ``to_thread`` 卸载；retry 竞窗靠 runner 在飞集 + 逐任务状态复
        核收窄（复核→walk 间翻活只丢一拍窗口，下拍再瘦）。
        """
        skip = runner.inflight_task_ids()
        slim_freed = 0
        slimmed = 0
        for tid in store.terminal_task_ids():
            if tid in skip:
                continue
            row = store.get(tid)
            if row is None or str(row["status"]) not in TERMINAL_STATUSES:
                continue
            keep = {str(rec["path"]) for rec in store.files(tid).values()}
            keep_dirs = (
                ("zh", "base") if str(row["status"]) in ("done", "partial") else ()
            )
            freed = await asyncio.to_thread(
                slim_task_dir, tasks_dir / tid, keep, keep_dirs
            )
            if freed:
                slimmed += 1
                slim_freed += freed
        if slimmed:
            log.info("slim sweep: %d task(s), freed %d B", slimmed, slim_freed)

    async def _sweep_delete() -> None:  # noqa: C901 -- 两阶段淘汰阶梯平铺
        """删除段：``retention_days``/``retention_max_gb`` 淘汰整任务（全 0 = 关）。

        ``sweep_retention`` 的 loop-native 版——决策查询（``TaskRepo``
        单侧化）+ ``delete_task_guard`` 条件写留在 loop，``_dir_size``/
        ``rmtree`` 重 I/O 逐段 ``to_thread``。settings 每拍重读（PUT 即
        生效，不用重启）。
        """
        st = settings_store.load()
        days = int(st.get("retention_days") or 0)
        max_gb = int(st.get("retention_max_gb") or 0)
        if days <= 0 and max_gb <= 0:
            return
        removed: list[str] = []
        freed_bytes = 0

        async def _drop(tid: str) -> int:
            """条件删行（loop）+ rmtree（thread）→ 目录字节数。"""
            if not store.delete_task_guard(tid, blocked=ACTIVE_STATUSES):
                return 0
            sz = await asyncio.to_thread(_dir_size, tasks_dir / tid)
            await asyncio.to_thread(shutil.rmtree, tasks_dir / tid, ignore_errors=True)
            removed.append(tid)
            return sz

        if days > 0:
            cutoff = time.time() - days * 86400
            for tid in store.retention_candidates(cutoff):
                freed_bytes += await _drop(tid)
        if max_gb > 0:
            cap = max_gb * (1 << 30)
            total = await asyncio.to_thread(_dir_size, tasks_dir)
            if total > cap:
                for tid in store.terminal_oldest_first():
                    if total <= cap:
                        break
                    sz = await _drop(tid)
                    freed_bytes += sz
                    total -= sz
        if removed:
            log.info(
                "retention sweep: %s",
                {"removed": removed, "freed_bytes": freed_bytes},
            )

    async def _retention_loop() -> None:
        """产物保留策略周期 sweep（每 10min 一拍：瘦身 + retention 删除）。

        失败只 log——保留策略是后台清扫面，故障绝不拖垮服务。
        """
        while True:
            await asyncio.sleep(600)
            try:
                await _slim_terminal()
                await _sweep_delete()
            except Exception as e:  # noqa: BLE001 -- 后台清扫失败只留 warning
                log.warning("retention sweep failed: %s", e)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # §4.2 第二道防线：uvicorn log config 此时已就绪，filter 落到
        # root+uvicorn 全部 handler（传播链上各 handler 独立判定）。
        install_log_scrub(_key_provider)
        store.open()
        recovered = store.recover_startup()
        orphans = _sweep_orphan_task_dirs()
        # 上传 spool 目录只收流式落盘的临时件——进程被杀留的残骸启动即清
        spool_dir.mkdir(parents=True, exist_ok=True)
        for stale in spool_dir.iterdir():
            with suppress(OSError):
                stale.unlink()
        if recovered["interrupted"] or recovered["needs_auth"]:
            log.info("startup recovery: %s", recovered)
        if orphans:
            log.info("swept %d orphan task dir(s)", orphans)
        retention = asyncio.create_task(_retention_loop())
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

        ``/api`` 前缀判定走 ``get_route_path``（剥 ``root_path``）而非
        ``request.url.path``——后者含 ``root_path``，``--root-path``/反代
        子路径部署下 ``/tex/api/…`` 会骗过前缀闸而路由照样命中。
        """
        if server_mode() != "server":
            peer = request.client.host if request.client is not None else ""
            if not _loopback_peer(request):
                return _json_error(403, f"peer {peer} not allowed", "forbidden")
            host = request.headers.get("host", "")
            if not host or _host_only(host) not in _LOOPBACK_HOSTS:
                return _json_error(
                    403, f"host {host or '<absent>'} not allowed", "forbidden"
                )
        mutating = request.method in (
            "POST",
            "PUT",
            "DELETE",
            "PATCH",
        ) and get_route_path(request.scope).startswith("/api")
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
        if get_route_path(request.scope).startswith("/api"):
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
