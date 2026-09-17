"""FastAPI app factory（web-layer §2 全部端点 + §4 BYOK 接线）。

``create_app()`` 组装：``Store``(SQLite 单写者) + ``EventBus``(SSE 扇出)
+ ``TaskRunner``/``PipelineWorker``（``start_worker=False`` 供测试按住
dispatcher）。横切：``/api`` 一律 ``Cache-Control: no-store``；入站闸
（``request_gate_mw``）做 local Host 白名单 + mutating 请求
``Origin``/``Sec-Fetch-Site`` 同源检查 + server 形态匿名写 401。

key 纪律：``X-Texlate-*`` 头只进内存 ``Secrets`` 随任务活，绝不写库/日志；
``GET /api/settings`` 出参只给 ``has_api_key``。

注意：本模块只在 server extra（fastapi/sse-starlette）存在时才会被导入——
``texlate.server`` 包本体保持轻依赖（``__init__`` 走 PEP 562 延迟加载）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import sqlite3
import subprocess
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse
from starlette._utils import get_route_path  # 路由匹配同一条路径视图（剥 root_path）
from starlette.datastructures import UploadFile as StarletteUploadFile

try:
    import python_multipart as _pymp
except ModuleNotFoundError:  # pragma: no cover -- 旧式包名回落（同 starlette）
    import multipart as _pymp  # type: ignore[no-redef]

from texlate import __version__
from texlate.arxiv.fetch import _valid_id, normalize_arxiv_id
from texlate.compile.sandbox import find_tool
from texlate.compile.toolchain import resolve_tool
from texlate.server.events import EventBus, sse_frame
from texlate.server.settings import (
    TARGET_LANGS,
    UPLOAD_CAP,
    AuthContext,
    SettingsStore,
    install_log_scrub,
    provider_presets,
    resolve_auth,
    scrub,
    server_mode,
    server_salt,
    share_dir,
    validate_base_url,
    validate_model,
)
from texlate.server.settings import data_dir as default_data_dir
from texlate.server.staticfiles import mount_spa
from texlate.server.store import (
    ACTIVE_STATUSES,
    RETRYABLE_FROM,
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
    TaskCtx,
    TaskRunner,
    _env_timeout,
    cache_key_for,
    share_pack_publish,
    sniff_upload,
)
from texlate.share import (
    REQUIRED_ARTIFACTS,
    ShareError,
    index_lookup,
    share_key,
    unpack_share,
)
from texlate.xlat.client import _LOOPBACK_HOSTS, ChatClient, ChatError
from texlate.xlat.state import atomic_json

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from starlette.types import Message

    from texlate.arxiv.cache import SourceCache
    from texlate.arxiv.fetch import Fetcher
    from texlate.compile.engine import Engine
    from texlate.xlat.pipeline import Translator

log = logging.getLogger(__name__)

#: URL kind → media_type（§2.3 表）。``src.tar`` 不在表内——它的物理类型
#: 随任务 kind 变化（e-print tar.gz / 上传原文件回读），走 ``_src_tar_media``。
_MEDIA = {
    "en.pdf": "application/pdf",
    "zh.pdf": "application/pdf",
    "dual.pdf": "application/pdf",
    "dual.json": "application/json",
    "zh-src.zip": "application/zip",
    "compile.log": "text/plain; charset=utf-8",
    "md": "application/zip",
    "zh.docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    "zh.epub": "application/epub+zip",
    # arxiv_html 链的序列化 DOM 产物（file_get 对 text/html 补 CSP sandbox 闸）
    "en.html": "text/html; charset=utf-8",
    "zh.html": "text/html; charset=utf-8",
}

#: 会产出 ``dual.json``（→ reader 可用）的任务 kind。docx/epub 走
#: export 双语插译没有 dual.json——``_accepted`` 对它们不发 reader_url。
_DUAL_JSON_KINDS = frozenset(
    {"arxiv", "share", "upload_tex", "upload_pdf", "arxiv_html"}
)


def _probe_git_commit() -> str:
    """``git rev-parse --short HEAD``（包路径定位仓根）；非 git 安装/无 git → ``""``。

    import 期一次性探测——build 戳语义是「加载的代码」而非「现在磁盘上的
    代码」，模块常量恰好钉住进程起跑时的构建。
    """
    git = shutil.which("git")
    if git is None:
        return ""
    try:
        out = subprocess.run(  # noqa: S603 -- argv[0] 是 which 定位的绝对路径
            [git, "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


#: ``/api/health`` 构建面：进程加载的代码 commit + 进程启动时刻
#: （长驻 ``texlate web`` 服旧码的 stale-实例识别——M3 smoke B3）
_BUILD_COMMIT = _probe_git_commit()
_STARTED_AT = datetime.now(UTC).isoformat(timespec="seconds")

#: 上传任务 ``src.tar``（原始上传字节回读）按任务 kind 钉死的 mime
_SRC_TAR_KIND_MEDIA = {
    "upload_pdf": "application/pdf",
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "epub": "application/epub+zip",
}


def _src_tar_media(task_kind: str, path: Path) -> str:
    """``src.tar`` 的物理 mime：arxiv/share=e-print tar.gz；上传任务=原文件回读。

    ``upload_tex`` 的 blob 可能是 .tex/.zip/.tar/.tar.gz——按魔数给真值，
    认不出的按 octet-stream（不谎报 gzip）。
    """
    if task_kind in ("arxiv", "share"):
        return "application/gzip"
    fixed = _SRC_TAR_KIND_MEDIA.get(task_kind)
    if fixed is not None:
        return fixed
    if task_kind == "upload_tex":
        with path.open("rb") as fh:
            head = fh.read(263)
        if head[:2] == b"\x1f\x8b":
            return "application/gzip"
        if head[:4] == b"PK\x03\x04":
            return "application/zip"
        if head[257:262] == b"ustar":
            return "application/x-tar"
    return "application/octet-stream"


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
_FILENAME_MAX = 255  # POSIX NAME_MAX（字节）——净化名全 ASCII，len 即字节数


def _cap_request_body(request: Request) -> None:
    """给 ``request`` 的 receive 通道装字节闸：累计体超 ``UPLOAD_CAP + overhead`` → 413。

    ``stream()``/``body()``/``form()`` 全经 ``self._receive``——此处包一层
    计数即覆盖一切体消费方，且保持流式语义（文件字段仍走 spool，不整读
    进 RAM）。``Content-Length`` 缺席（chunked/HTTP2）时头部预检失效，
    本闸是唯一兜底；无 ``body`` 键的消息（disconnect 等）计 0 透传。
    """
    inner = request._receive  # noqa: SLF001 -- starlette 无公开 receive 包装口
    seen = 0

    async def capped() -> Message:
        nonlocal seen
        msg = await inner()
        seen += len(msg.get("body", b""))
        if seen > UPLOAD_CAP + _MULTIPART_OVERHEAD:
            raise _ApiError(
                413,
                {
                    "detail": f"upload > {UPLOAD_CAP}B",
                    "code": "upload_too_large",
                },
            )
        return msg

    request._receive = capped  # noqa: SLF001 -- 同上：替换实例 receive 通道


async def _parse_multipart(request: Request) -> dict[str, str | UploadPart]:
    """``multipart/form-data`` → ``{name: str | UploadPart}``。

    走 starlette ``request.form()``（python-multipart 在 server extra 内）；
    ``Content-Length`` 超 ``UPLOAD_CAP + overhead`` 先 413 不读体。
    ``Content-Length`` 缺席（chunked/HTTP2）预检失效——``_cap_request_body``
    的流式字节闸对 str/文件全部字段合计上界，超界即 413；文件字段再按
    剩余额度有界读，累计文件字节超 ``UPLOAD_CAP`` 即 413。
    """
    clen = request.headers.get("content-length", "")
    if clen.isdigit() and int(clen) > UPLOAD_CAP + _MULTIPART_OVERHEAD:
        raise _ApiError(
            413, {"detail": f"upload > {UPLOAD_CAP}B", "code": "upload_too_large"}
        )
    _cap_request_body(request)
    # starlette 的 multipart 判定是 media-type token byte-equal——带参数时
    # ``MULTIPART/FORM-DATA; boundary=X``（RFC 9110 大小写不敏感）被当非
    # multipart 清空表单。就地归一媒体 token（参数原样保留）：
    # ``scope["headers"]`` 与缓存 ``request._headers`` 共享同一 list 对象，
    # 原地改写才能让随后 ``request.form()`` 的判定看到（``MutableHeaders``/
    # ``Headers.raw`` 在 starlette 1.6 都是防御性复制，改了不生效）。
    ctype = request.headers.get("content-type", "")
    media, sep, params = ctype.partition(";")
    if media.strip().lower() == "multipart/form-data" and (
        media.strip() != "multipart/form-data"
    ):
        normalized = f"multipart/form-data{sep}{params}".encode("latin-1")
        raw_headers = request.scope["headers"]
        for i, (k, _v) in enumerate(raw_headers):
            if k == b"content-type":
                raw_headers[i] = (k, normalized)
                break
    try:
        form = await request.form()
    except _pymp.exceptions.ParseError as e:
        # python-multipart 引擎错（boundary 不符/伪 boundary 行/参数畸形）——
        # starlette 只包自家回调侧 MultiPartException，引擎错直穿成 500
        raise _ApiError(400, {"detail": f"malformed multipart: {e}"}) from e
    out: dict[str, str | UploadPart] = {}
    file_bytes = 0
    for name, val in form.multi_items():
        if isinstance(val, StarletteUploadFile):
            data = await val.read(UPLOAD_CAP + 1 - file_bytes)
            file_bytes += len(data)
            if file_bytes > UPLOAD_CAP:
                raise _ApiError(
                    413,
                    {"detail": f"upload > {UPLOAD_CAP}B", "code": "upload_too_large"},
                )
            out[name] = UploadPart(filename=val.filename or "", data=data)
        elif isinstance(val, str):
            out[name] = val
    return out


def _form_text(form: dict[str, str | UploadPart], name: str) -> str:
    """表单文本字段（文件字段同名时按缺省处理）。"""
    val = form.get(name)
    return val if isinstance(val, str) else ""


def _share_parts_checked(
    parts: dict[str, str],
) -> tuple[str, str, str, str, int | None]:
    """Manifest key_parts → ``(base, ver_s, model, lang, ver)`` 白名单校验。

    ``arxiv_id`` 必须裸 id（版本只走 ``version`` 键，嵌 ``vN`` 后缀即
    400）；``target_lang`` ∈ TARGET_LANGS；``model`` 过 ``validate_model``；
    ``version`` 只收 ``vN`` 钉版形或空串（``_norm_version`` 可能的
    非数字形在此闸死，``int()`` 不会炸）。全数违例 → ``share_invalid``。
    """
    base, embedded = normalize_arxiv_id(parts["arxiv_id"])
    if embedded is not None or not _valid_id(base):
        raise _ApiError(
            400,
            {
                "detail": f"key_parts.arxiv_id 非法: {parts['arxiv_id']!r}",
                "code": "share_invalid",
            },
        )
    lang = parts["target_lang"]
    if lang not in TARGET_LANGS:
        raise _ApiError(
            400,
            {
                "detail": f"key_parts.target_lang ∈ {sorted(TARGET_LANGS)}",
                "code": "share_invalid",
            },
        )
    try:
        model = validate_model(parts["model"])
    except ValueError as e:
        raise _ApiError(
            400, {"detail": f"key_parts.model: {e}", "code": "share_invalid"}
        ) from e
    ver_s = parts["version"]  # "v5" 钉版 / "" latest 别名
    if ver_s and not re.fullmatch(r"v\d{1,3}", ver_s):
        raise _ApiError(
            400,
            {
                "detail": f"key_parts.version 须为 vN 钉版形: {ver_s!r}",
                "code": "share_invalid",
            },
        )
    return base, ver_s, model, lang, (int(ver_s[1:]) if ver_s else None)


#: 任务 options 的系统保留键——worker/app 自写字段（provenance/审计/持久化）。
#: options_json 无 schema、用户可写任意键进库：伪造 ``reuse_hit`` 让 share_pack
#: 永 422（自伤方向，但脏审计行）；``engine_resolved``/``route_engines``/
#: ``arxiv_categories`` 是 worker 运行期持久化值；``share`` 是 share_import
#: 的强制覆盖审计载荷。入参侧一律摘除（idempotency_key/prefer/main/glossary
#: 等用户合法键不在列）。
_RESERVED_OPTION_KEYS = frozenset(
    {"reuse_hit", "arxiv_categories", "engine_resolved", "route_engines", "share"}
)

#: options.engine 白名单（settings ``_normalize_updates`` 同口径——
#: ``engine_for`` 只认两台真机 + auto 路由）。
_ENGINE_NAMES = frozenset({"auto", "xelatex", "tectonic"})

#: server 模式 ``GET /api/settings`` 摘键：前端不消费且泄漏部署拓扑
#: （``glossary_dir`` 宿主文件系统路径、``cors_origins`` 部署方跨域策略）。
#: ``quota_*`` 保留——多租户下配额上限是租户自身策略面，非拓扑。
_SERVER_SETTINGS_HIDDEN = frozenset({"cors_origins", "glossary_dir"})


def _settings_write_gate() -> None:
    """Server 模式 settings 写路径关闭（§4.1：PUT settings 是本地单机默认形态）。

    多租户形态下 settings.json 是部署方全局配置——租户可写即可改
    ``base_url`` 截获他租户 header key、改配额/CORS/glossary_dir；
    ``settings/test`` 是同级别的出站探活 oracle。server 形态的写管理
    走 settings.json 文件 / env / CLI ``--configure``。
    """
    if server_mode() == "server":
        raise _ApiError(
            403,
            {
                "detail": (
                    "server 模式下 settings 由部署方管理（settings.json/env），"
                    "API 写关闭"
                )
            },
        )


def _clean_task_options(options: dict[str, Any]) -> dict[str, Any]:
    """任务 options 入参闸（就地改写 + 返回）：摘保留键 + 白名单校验。

    ``engine`` 此前无入参校验——非法值要跑到编译段 ``engine_for`` 才炸成
    fault；``concurrency`` 裸 ``int()`` 对非数值输入直接 500。两闸与
    settings 同口径：engine ∈ ``_ENGINE_NAMES``；concurrency 须可转
    int 并 clamp 1–16。
    """
    for k in _RESERVED_OPTION_KEYS:
        options.pop(k, None)
    engine = str(options.get("engine") or "auto")
    if engine not in _ENGINE_NAMES:
        raise _ApiError(
            400,
            {
                "detail": f"options.engine ∈ {sorted(_ENGINE_NAMES)}",
                "code": "invalid_request",
            },
        )
    # 取源闸：eprint（默认，e-print tar 链）| html（ar5iv DOM 链）——
    # 与 arxiv 获取层「取源」同词；值规范化回写，worker 侧恒可读
    source = str(options.get("source") or "eprint")
    if source not in ("eprint", "html"):
        raise _ApiError(
            400,
            {
                "detail": "options.source ∈ eprint|html",
                "code": "invalid_request",
            },
        )
    options["source"] = source
    if "concurrency" in options:
        try:
            options["concurrency"] = max(1, min(16, int(options["concurrency"])))
        except (TypeError, ValueError):
            raise _ApiError(
                400,
                {
                    "detail": "options.concurrency 须为整数（clamp 1–16）",
                    "code": "invalid_request",
                },
            ) from None
    return options


def _json_error(status: int, detail: str, code: str | None = None) -> JSONResponse:
    """``{"detail": str, "code"?}`` 统一错误面。"""
    body: dict[str, Any] = {"detail": detail}
    if code:
        body["code"] = code
    return JSONResponse(body, status_code=status)


def _host_only(host: str) -> str:
    """``Host`` 头剥端口 → 小写主机名（``[::1]:p`` 与裸 ``::1`` 都收）。"""
    h = host.strip().lower()
    if h.startswith("["):
        return h[1:].split("]", 1)[0]
    if h.count(":") > 1:
        return h  # 裸 IPv6（无括号写法）
    return h.split(":", 1)[0]


def _same_origin(request: Request, origin: str) -> bool:
    """``Origin`` 与请求 scheme+Host（含端口）严格一致——同源判定。"""
    o = urlsplit(origin)
    return (
        o.scheme == request.url.scheme
        and o.netloc.lower() == request.headers.get("host", "").lower()
    )


def _artifacts(store: Store, task_id: str) -> dict[str, str]:
    """``{db_kind: /api/files/{id}/{url_kind}}``（done 事件/快照共用）。"""
    return {
        kind: f"/api/files/{task_id}/{KIND_URL.get(kind, kind)}"
        for kind in store.files(task_id)
    }


def _accepted(row: dict[str, Any], status: int, extra: dict[str, Any]) -> JSONResponse:
    """202/200 任务响应统一形状（§2.1）。

    ``reader_url`` 只发给会产 ``dual.json`` 的 kind（``_DUAL_JSON_KINDS``）——
    docx/epub 的 reader 端点恒 404，发链接是空诺。
    """
    tid = str(row["id"])
    body = {
        "task_id": tid,
        "status": row["status"],
        "events_url": f"/api/task/{tid}",
        **extra,
    }
    if str(row["kind"]) in _DUAL_JSON_KINDS:
        body["reader_url"] = f"/api/task/{tid}/reader"
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
        # env ``TEXLATE_COMPILE_TIMEOUT`` > settings.json compile_timeout > 240
        compile_timeout=_env_timeout(
            "TEXLATE_COMPILE_TIMEOUT", settings_store.load()["compile_timeout"]
        ),
    )
    runner = TaskRunner(store, bus, worker)

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
    async def request_gate_mw(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """入站闸：local Host 白名单 + mutating /api 跨站检查 + server 匿名写 401。

        - local 形态 ``Host`` 剥端口须 loopback——DNS rebinding 读面收口。
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
            host = request.headers.get("host", "")
            if host and _host_only(host) not in _LOOPBACK_HOSTS:
                return _json_error(403, f"host {host} not allowed")
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
            return _json_error(403, "cross-site request rejected")
        elif origin and not _same_origin(request, origin):
            return _json_error(403, f"origin {origin} not allowed")
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
            resp.headers["Cache-Control"] = "no-store"
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
                    "x-texlate-key",
                    "x-texlate-base-url",
                    "x-texlate-model",
                ],
            )
    app.state.cors_origins = _origins

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
        """Header > settings > env 三级决议（§4.1）；非法 header 值 → 400。

        每请求缓存到 ``request.state``：一次请求内 header 与 settings
        快照都不变，而 ``load()`` 每次都读盘解析——translate 单链决议
        3+ 次（model 回落/cache_key/_create_and_enqueue），缓存只读
        一次。失败不缓存（重试同路径重炸 400）。
        """
        cached = getattr(request.state, "auth_ctx", None)
        if isinstance(cached, AuthContext):
            return cached
        try:
            auth = resolve_auth(
                settings_store.load(),
                header_key=request.headers.get("x-texlate-key", ""),
                header_base_url=request.headers.get("x-texlate-base-url", ""),
                header_model=request.headers.get("x-texlate-model", ""),
                mode=server_mode(),
                salt=salt,
            )
        except ValueError as e:
            raise _ApiError(400, {"detail": str(e)}) from e
        request.state.auth_ctx = auth
        return auth

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
        """可选 JSON body；坏 JSON → 400；非空 body 须 ``application/json``。

        Content-Type 闸是 CSRF 面的另一半：浏览器 simple-request 只能发
        ``text/plain``/``application/x-www-form-urlencoded``/``multipart``——
        闸死后跨站表单构造不了有效 JSON mutation。空 body（无 CT 的
        curl 式 POST）照旧放行。
        """
        _cap_request_body(request)  # 与 multipart 同闸——无 CL 时 body() 原无界读
        raw = await request.body()
        if not raw:
            return {}
        ctype = request.headers.get("content-type", "").split(";", 1)[0].strip()
        if ctype.lower() != "application/json":
            raise _ApiError(
                415,
                {
                    "detail": "Content-Type 须为 application/json",
                    "code": "unsupported_media_type",
                },
            )
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError) as e:
            # ValueError 含 JSONDecodeError 与巨 int 字面量（int↔str 上限）；
            # RecursionError 是超深嵌套——不入网即 500
            raise _ApiError(400, {"detail": f"bad json: {e}"}) from e
        return data if isinstance(data, dict) else {}

    def _check_quota(auth: AuthContext, incoming_bytes: int) -> None:
        """Tenant 配额闸（settings.quota_max_*，0=不限）——超限 429。

        任务数按 ``tasks`` 行全量计（含终态行）；字节按已登记产物
        ``files.bytes`` 合计 + 本次入队载荷。reuse/idempotent 命中不建行，
        在调用方此处之前就返回，不占配额。
        """
        st = auth.settings  # 与 _auth 同一份请求快照——不再读一次盘
        q_tasks = int(st.get("quota_max_tasks") or 0)
        q_bytes = int(st.get("quota_max_bytes") or 0)
        if not (q_tasks or q_bytes):
            return
        usage = store.tenant_usage(auth.tenant)
        if q_tasks and usage["tasks"] >= q_tasks:
            raise _ApiError(
                429,
                {
                    "detail": f"tenant 任务配额已用尽（{q_tasks}）",
                    "code": "quota_exceeded",
                },
            )
        if q_bytes and usage["bytes"] + incoming_bytes > q_bytes:
            raise _ApiError(
                429,
                {
                    "detail": f"tenant 字节配额超限（{q_bytes}B）",
                    "code": "quota_exceeded",
                },
            )

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
        incoming_bytes: int = 0,
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
            # oracle 权衡：shared 模式下 dedup 命中可被他租户探测
            # （「这篇论文是否译过」存在性侧信道）——hjfy 对等共享缓存是
            # 既定产品特性，须消除时 TEXLATE_CACHE_SCOPE=per_key 按
            # 凭证指纹分桶（见 settings.cache_scope）。
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
        _check_quota(auth, incoming_bytes)
        tid = task_id or new_task_id()
        config = {
            "base_url": auth.base_url,
            "model": model,
            "glossary": str(
                options.get("glossary") or auth.settings.get("glossary") or ""
            ),
            # settings 侧受信术语表根（worker 的 glossary 相对路径解析根之一；
            # 不透传请求面，防调用方自选根绕 confine）
            "glossary_dir": str(auth.settings.get("glossary_dir") or ""),
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
        if not _valid_id(base):
            return _json_error(400, f"invalid arxiv id: {arxiv_id!r}")
        body = await _read_body(request)
        try:
            options = dict(body.get("options") or {})
        except (TypeError, ValueError):
            return _json_error(400, "options 须为 object 或 KV 对列表")
        options = _clean_task_options(options)
        try:
            model = validate_model(str(body.get("model") or _auth(request).model))
        except ValueError as e:
            return _json_error(400, str(e))
        target_lang = str(
            body.get("target_lang") or _auth(request).settings["target_lang"]
        )
        if target_lang not in TARGET_LANGS:
            return _json_error(400, f"target_lang ∈ {sorted(TARGET_LANGS)}")
        if body.get("glossary"):
            options["glossary"] = str(body["glossary"])
        prefer = str(options.get("prefer") or "reuse")
        if prefer not in ("reuse", "fresh"):
            return _json_error(400, "options.prefer ∈ reuse|fresh")
        # source 已经 _clean_task_options 白名单规范化（eprint|html）。
        # eprint 是历史默认、键材料不动（存量缓存续命）——仅非默认源追加
        # ``source=`` 成分（与 worker cache_key_for 的 no-op 默认同语义，
        # 也让本调用点对未带 source 形参的旧签名兼容）
        source = str(options.get("source") or "eprint")
        kind = "arxiv_html" if source == "html" else "arxiv"
        ck_extra: dict[str, str] = {}
        if source != "eprint":
            ck_extra["source"] = source
        cache_key = cache_key_for(
            arxiv_id=base,
            version=ver,
            model=model,
            target_lang=target_lang,
            api_key=_auth(request).api_key,
            **ck_extra,
        )
        row, status, extra = _create_and_enqueue(
            request,
            kind=kind,
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
        # RFC 9110：媒体类型大小写不敏感——TEXT/EVENT-STREAM 也应进 SSE
        if "text/event-stream" not in accept.lower():
            return JSONResponse(
                store.snapshot(task_id, artifacts=_artifacts(store, task_id))
            )
        try:
            last_id = int(request.headers.get("last-event-id", "0") or 0)
        except ValueError:
            last_id = 0
        # SQLite 绑参 int64 界——超界声明夹到界值（语义=客户端已见至该 seq，
        # 大值→无重放，负值→全量重放）；不夹则 events_since OverflowError
        # 在 snapshot 帧发出后炸断流。
        last_id = max(-(2**63), min(last_id, 2**63 - 1))

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
            # 旧式 arxiv_id 含 '/'（hep-th/9901001）——filename 白名单化防畸形 header
            stem = re.sub(r"[^A-Za-z0-9_.+-]", "_", str(row.get("arxiv_id") or task_id))
            headers = {
                "Content-Disposition": (f'attachment; filename="texlate-{stem}-{kind}"')
            }
        media = (
            _src_tar_media(str(row["kind"]), path)
            if kind == "src.tar"
            else _MEDIA.get(kind, "application/octet-stream")
        )
        if media.startswith("text/html"):
            # html 产物同源伺服——直接导航时文档内幸存脚本可在同源上下文
            # 打 mutating /api；CSP sandbox（无 allow-*）整文档脚本全灭。
            # 纵深防御：worker _sanitize_dom 主防线 + 前端 DOMPurify 之外的
            # 服务端兜底；不挡 img-src（sandbox 只禁脚本）
            headers = {**(headers or {}), "Content-Security-Policy": "sandbox"}
        return FileResponse(path, media_type=media, headers=headers)

    # ------------------------------------------------------------ §2.4 upload

    def _check_upload_route(route: str, babeldoc: str | None, filename: str) -> None:
        """魔数路由 → 错误面：unknown 400、pdf 无 babeldoc 501。

        docx/epub 经 ``export_document`` 双语插译通路（worker ``_run_doc``），
        转换器是进程内 export 包（bs4/lxml/python-docx 均为硬依赖），无外部
        工具探测面。
        """
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
        except (ValueError, RecursionError):
            raise _ApiError(400, {"detail": "options 字段不是合法 JSON"}) from None
        if not isinstance(options, dict):
            options = {}
        options = _clean_task_options(options)
        try:
            model = validate_model(_form_text(form, "model") or _auth(request).model)
        except ValueError as e:
            raise _ApiError(400, {"detail": str(e)}) from e
        target_lang = _form_text(form, "target_lang") or str(
            _auth(request).settings["target_lang"]
        )
        if target_lang not in TARGET_LANGS:
            raise _ApiError(400, {"detail": f"target_lang ∈ {sorted(TARGET_LANGS)}"})
        if _form_text(form, "main"):
            options["main"] = _form_text(form, "main")
        return model, target_lang, options

    @app.post("/api/upload")
    async def upload(request: Request) -> Response:
        """Multipart 上传：魔数路由 upload_tex/upload_pdf/docx/epub（§2.4）。"""
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
        # re.sub 白名单放行 ``.``——``..`` 原样幸存会打成目录写（500+孤儿
        # task 目录），建行前先拒。>255B 名（NAME_MAX）会让 write_bytes
        # 抛 ENAMETOOLONG 成 500——同闸先拒。
        safe = re.sub(r"[^A-Za-z0-9_.+-]", "_", Path(filename).name)
        if safe in (".", "..") or len(safe) > _FILENAME_MAX:
            raise _ApiError(400, {"detail": f"unsafe filename: {filename!r}"})
        # 先落 blob（建行前），再建行+入队——task_id 两侧共用
        task_id = new_task_id()
        updir = root / "tasks" / task_id / "upload"
        try:
            updir.mkdir(parents=True, exist_ok=True)
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
                incoming_bytes=len(data),
            )
        except Exception:
            # 建行/入队任何失败——upload blob 目录一并收掉，不留孤儿（B4）
            shutil.rmtree(root / "tasks" / task_id, ignore_errors=True)
            raise
        if str(row["id"]) != task_id:
            # idempotent 命中旧行——本次落盘 blob 成孤儿，连带目录清掉（B4）
            shutil.rmtree(root / "tasks" / task_id, ignore_errors=True)
        return _accepted(row, status, extra)

    # ------------------------------------------------------------ share 导入

    @app.post("/api/share/import")
    async def share_import(request: Request) -> Response:
        """``.share.zip`` → 校验解包 → ``kind="share"`` 任务入队。

        端点只做机械校验（``unpack_share``：format/share_key 自洽/逐产物
        sha256 对账）+ key_parts 白名单（arxiv_id 形态、target_lang ∈
        TARGET_LANGS、model 合法性、version 钉版形 ``vN``）；译文可信度
        由 worker ``_run_share`` 全链重跑承担（shared-cache.md §5）。
        model/lang/arxiv_id/version 一律取 manifest key_parts（内容生产
        者口径）——与上传者自身 model 设置不同**不拒**：包自描述，任务行
        记 manifest 真值，上传者配置不进寻址。``cache_key`` 按钉版形态
        重算——后来的 ``id@vN`` 请求经 ``find_reusable`` 真命中本产物。
        """
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
        tid = new_task_id()
        tdir = root / "tasks" / tid
        try:
            bundle_dir = tdir / "upload"
            bundle_dir.mkdir(parents=True, exist_ok=True)
            bundle = bundle_dir / "bundle.share.zip"
            bundle.write_bytes(data)
            mf = unpack_share(bundle, tdir / "share")
            parts = mf.key_parts
            base, ver_s, model, lang, ver = _share_parts_checked(parts)
            options_raw = _form_text(form, "options")
            try:
                options = json.loads(options_raw) if options_raw else {}
            except (ValueError, RecursionError):
                raise _ApiError(400, {"detail": "options 字段不是合法 JSON"}) from None
            if not isinstance(options, dict):
                options = {}
            options = _clean_task_options(options)
            # 审计载荷强制覆盖——调用方 options 不得伪造 share 来源字段
            options["share"] = {
                "share_key": mf.share_key,
                "contributor": mf.contributor,
                "created_at": mf.created_at,
                "key_parts": dict(parts),
            }
            row, status, extra = _create_and_enqueue(
                request,
                kind="share",
                arxiv_id=f"{base}{ver_s}",
                source_name=file.filename or "bundle.share.zip",
                title="",
                model=model,
                target_lang=lang,
                options=options,
                prefer="reuse",
                cache_key=cache_key_for(
                    arxiv_id=base,
                    version=ver,
                    model=model,
                    target_lang=lang,
                    api_key=_auth(request).api_key,
                ),
                task_id=tid,
                incoming_bytes=len(data),
            )
        except ShareError as e:
            shutil.rmtree(tdir, ignore_errors=True)
            raise _ApiError(
                400,
                {"detail": f"share bundle invalid: {e}", "code": "share_invalid"},
            ) from e
        except sqlite3.IntegrityError:
            # reuse 语义下并发同键撞 ACTIVE 唯一索引——归 duplicate_active
            shutil.rmtree(tdir, ignore_errors=True)
            raise _ApiError(
                409,
                {"detail": "active task exists", "code": "duplicate_active"},
            ) from None
        except Exception:
            # 落盘/解包/校验/建行/入队任何失败（含 _ApiError 与非预期异常）
            # ——task 目录一并收掉，不留孤儿（upload 端点 B4 同口径）
            shutil.rmtree(tdir, ignore_errors=True)
            raise
        if str(row["id"]) != tid:
            # reuse/idempotent 命中旧行——本次解包现场作废（行从未建）
            shutil.rmtree(tdir, ignore_errors=True)
        return _accepted(row, status, extra)

    # ------------------------------------------------------------ share 导出

    @app.post("/api/task/{task_id}/share/pack")
    async def share_pack(request: Request, task_id: str) -> Response:  # noqa: C901, PLR0911 -- 守卫阶梯平铺
        """终态任务事后打 ``.share.zip``（shared-cache.md §6「完成后提示分享」服务端面）。

        与 worker ``_maybe_share_pack`` 完成钩同口径：key_parts 由
        ``worker.share_pack_manifest`` 从任务行现值派生，产物取
        ``tasks/{id}/`` 下 ``REQUIRED_ARTIFACTS``（zh.pdf 缺席落 partial
        包）。幂等：share_key 已入 ``index.jsonl`` 且包文件在场 → 直接
        200 不重打。``kind=share``（导入产物不自包）/``arxiv_html``
        （html 链产不出 zh-src.zip，且 HTML chunk 与 share 包 TeX chunk
        不对版不可比对）与 reuse 命中任务（产物物化自他任务、生效术语表
        不可知）→ 422；非 done/partial → 409；缺必需产物 → 422。
        响应 ``{share_key, url, bytes}``——``url`` 与 index 行同口径
        （包文件名）。
        """
        row = _get_task(request, task_id)
        if str(row["kind"]) in ("share", "arxiv_html"):
            return _json_error(
                422,
                f"kind={row['kind']} 任务不打共享包（产物形态不参与共享寻址）",
                "share_pack_rejected",
            )
        try:
            opts = json.loads(str(row.get("options_json") or "{}"))
        except json.JSONDecodeError:
            opts = {}
        if isinstance(opts, dict) and opts.get("reuse_hit"):
            return _json_error(
                422,
                f"reuse 命中任务（产物物化自 {opts['reuse_hit']}）不打共享包",
                "share_pack_rejected",
            )
        if row["status"] not in ("done", "partial"):
            return _json_error(
                409,
                f"任务状态 {row['status']}：仅 done/partial 终态可打包",
                "invalid_state",
            )
        task_root = root / "tasks" / task_id
        ctx = TaskCtx(
            store=store,
            bus=bus,
            task_id=task_id,
            row=row,
            secrets=Secrets(),
            root=task_root,
        )
        manifest = worker.share_pack_manifest(ctx, row)
        if manifest is None:
            return _json_error(
                422,
                "任务无 arxiv_id（不参与共享寻址）",
                "share_pack_rejected",
            )
        key = share_key(
            str(manifest["arxiv_id"]),
            str(manifest["version"]),
            str(manifest["model"]),
            str(manifest["prompt_ver"]),
            str(manifest["target_lang"]),
            str(manifest["glossary_hash"]),
            str(manifest["pipeline_ver"]),
        )
        out_dir = share_dir(root)
        try:
            hit = index_lookup(out_dir / "index.jsonl", key)
        except (OSError, UnicodeDecodeError) as e:
            # 索引读挂不挡重打——index_lookup 实抛面即此二类（坏行内部跳过，
            # 不抛 ShareError）；append-only last-wins 读出侧自愈
            log.warning("share index unreadable for %s, repacking: %s", task_id, e)
            hit = None
        if hit is not None:
            # index 行 url 按约定是扁平包文件名——只认扁平名防越界探测；
            # NUL 漏检会让 stat() 抛 ValueError（不属 OSError）炸 500
            name = str(hit.get("url") or "")
            flat = (
                "/" not in name
                and "\\" not in name
                and "\x00" not in name
                and name not in ("", ".", "..")
            )
            if flat:
                try:
                    size = (out_dir / name).stat().st_size
                except OSError:
                    size = -1  # 行在包不在（或竞态消失）——按未命中走重打
                if size >= 0:
                    return JSONResponse({"share_key": key, "url": name, "bytes": size})
        missing = [n for n in REQUIRED_ARTIFACTS if not (task_root / n).is_file()]
        if missing:
            return _json_error(
                422,
                f"缺必需产物: {missing}",
                "share_pack_artifacts",
            )
        try:
            bundle, mf = await asyncio.to_thread(
                share_pack_publish, task_root, manifest, out_dir
            )
        except ShareError as e:
            return _json_error(422, f"share 打包失败: {e}", "share_pack_failed")
        return JSONResponse(
            {
                "share_key": mf.share_key,
                "url": bundle.name,
                "bytes": bundle.stat().st_size,
            }
        )

    # ------------------------------------------------------------ §2.5 helpers

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        """``{ok}`` 探活最小集；local 形态附加 ``version/commit/started_at/compilers/data_dir``。"""
        if server_mode() == "server":
            return {"ok": True}
        return {
            "ok": True,
            "version": __version__,
            "commit": _BUILD_COMMIT,
            "started_at": _STARTED_AT,
            "compilers": {
                "tectonic": resolve_tool("tectonic") is not None,
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
    async def task_retry(request: Request, task_id: str) -> Response:  # noqa: C901, PLR0912 -- 校验阶梯平铺
        """终态/needs_auth → queued 重入队；body 只收 ``{main, options}``。

        ``model``/``target_lang`` 是 cache_key 口径成员——换值得新建任务，
        静默丢弃比报错糟，故 body 白名单外的键一律 400。
        """
        row = _get_task(request, task_id)
        # 状态守卫必须在一切 mutation 之前——done 任务 retry 只许纯 409，
        # 不得先清 chunks/删目录/写 options（B3）
        if row["status"] not in RETRYABLE_FROM:
            raise TransitionError(task_id, row["status"], "queued")
        body = await _read_body(request)
        header_key = request.headers.get("x-texlate-key", "")
        if row["status"] == "needs_auth" and not header_key:
            return _json_error(
                401,
                "auth_source=header：重试必须重带 X-Texlate-Key",
                "auth_required",
            )
        bad_keys = sorted(set(body) - {"main", "options"})
        if bad_keys:
            return _json_error(
                400,
                f"retry body 仅支持 main/options，不识别: {bad_keys}",
                "invalid_request",
            )
        if "options" in body and not isinstance(body["options"], dict):
            return _json_error(400, "retry options 须为 object", "invalid_request")
        try:
            opts = json.loads(row.get("options_json") or "{}")
        except json.JSONDecodeError:
            opts = {}
        if not isinstance(opts, dict):
            opts = {}
        if isinstance(body.get("options"), dict):
            opts.update(_clean_task_options(body["options"]))
        if body.get("main"):
            opts["main"] = str(body["main"])
        main_req = str(opts.get("main") or "")
        if main_req and main_req != str(row.get("main_tex") or ""):
            # 换主文件（body.main 与 options.main 同口径）→ 解析产物作废
            # （chunks/base/zh 重建，src/ 保留）；派生产物行与磁盘件并删——
            # 残行会让 files/reader 照发上一轮产物（en.pdf 也随 base/ 同死：
            # 换 main 后它编译自另一棵树）
            store.conn.execute("DELETE FROM chunks WHERE task_id = ?", (task_id,))
            store.conn.commit()
            task_root = root / "tasks" / task_id
            for d in ("base", "zh", "build-en", "build-zh"):
                shutil.rmtree(task_root / d, ignore_errors=True)
            resolved_root = task_root.resolve()
            for kind, rec in store.files(task_id).items():
                if kind == "src_tar":
                    continue  # 取源产物不受影响——e-print/上传件仍有效
                store.delete_file(task_id, kind)
                stale = (task_root / str(rec["path"])).resolve()
                if stale.is_relative_to(resolved_root):
                    with suppress(OSError):
                        stale.unlink(missing_ok=True)
        store.update_fields(task_id, options_json=json.dumps(opts))
        try:
            store.transition(task_id, "queued", message="重试入队")
        except TransitionError as e:
            return _json_error(409, str(e), "invalid_transition")
        runner.enqueue(task_id, _secrets_for(request, row))
        return _accepted(store.get(task_id) or row, 202, {"cache": "retry"})

    @app.delete("/api/task/{task_id}")
    async def task_delete(request: Request, task_id: str) -> Response:
        """终态任务删除：DB 行（FK 级联子表）+ ``tasks/{id}/`` 工作目录。

        ACTIVE 态 409——进行中任务先 ``POST cancel`` 收敛再删；删前补一条
        ``done{status:"deleted"}`` 事件让在听的 SSE 流正常收尾（事件随
        行级联删，只服务实时订阅者）。内存 ``secrets`` 一并摘。
        """
        row = _get_task(request, task_id)
        if row["status"] in ACTIVE_STATUSES:
            return _json_error(
                409,
                f"task {task_id} is {row['status']}: cancel first",
                "invalid_transition",
            )
        bus.publish(
            task_id,
            "done",
            {"status": "deleted", "artifacts": {}, "stats": {}},
        )
        store.delete_task(task_id)
        runner.secrets.pop(task_id, None)
        shutil.rmtree(root / "tasks" / task_id, ignore_errors=True)
        return JSONResponse({"task_id": task_id, "status": "deleted"})

    # ------------------------------------------------------------ reader

    @app.get("/api/task/{task_id}/reader")
    async def reader_get(request: Request, task_id: str) -> Response:
        """``{documents, alignment, reading, view}``（§2.5/§5.4）。"""
        row = _get_task(request, task_id)
        dual_path = root / "tasks" / task_id / "dual.json"
        if store.file_record(task_id, "dual_json") is None or not dual_path.is_file():
            # 以登记行为准——磁盘孤儿件（登记前崩溃/失效清理残留）不服务
            return _json_error(404, "dual.json 未产出")
        try:
            dual = json.loads(dual_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return _json_error(500, "dual.json 损坏", "internal")
        if not isinstance(dual, dict):
            return _json_error(500, "dual.json 损坏", "internal")
        docs = dual.get("documents") or {}
        if not isinstance(docs, dict):
            return _json_error(500, "dual.json 损坏", "internal")
        # arxiv_html 链的 documents 指向序列化 DOM 产物（dom 视图锚点页）；
        # 其余链恒为 PDF 双栏
        doc_kinds = (
            (("original", "en.html"), ("translated", "zh.html"))
            if str(row["kind"]) == "arxiv_html"
            else (("original", "en.pdf"), ("translated", "zh.pdf"))
        )
        for side, kind in doc_kinds:
            if isinstance(docs.get(side), dict):
                docs[side]["url"] = f"/api/files/{task_id}/{kind}"
        reading: dict[str, Any] = {}
        rpath = root / "tasks" / task_id / "reading.json"
        if rpath.is_file():
            try:
                raw_reading = json.loads(rpath.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raw_reading = {}
            if isinstance(raw_reading, dict):
                reading = raw_reading
        return JSONResponse(
            {
                "documents": docs,
                "alignment": dual.get("alignment") or {"kind": "pages"},
                "reading": reading,
                # zh_html = arxiv_html 链 DOM 产物 → dom 视图（pages 语义即
                # 锚点数）；md_zip = 无 PDF 路的降级登记物；zh_pdf 在则 pdf
                # 视图优先（fault→retry 救回出 pdf 后残留的 md_zip 不把视图
                # 钉死在 html）
                "view": (
                    "dom"
                    if store.file_record(task_id, "zh_html")
                    else (
                        "html"
                        if store.file_record(task_id, "md_zip")
                        and not store.file_record(task_id, "zh_pdf")
                        else "pdf"
                    )
                ),
            }
        )

    @app.put("/api/task/{task_id}/reader/position")
    async def reader_put(request: Request, task_id: str) -> Response:
        """阅读位置落盘（``tasks/{id}/reading.json``）；版本不符 409。"""
        _get_task(request, task_id)
        body = await _read_body(request)
        want = str(body.get("document_version") or "")
        if want:
            # arxiv_html 无 zh_pdf——回落 zh_html（dom 路也吃防旧版位置回灌）
            rec = store.file_record(task_id, "zh_pdf") or store.file_record(
                task_id, "zh_html"
            )
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
        """public_settings：key 剥壳只给 ``has_api_key``；server 摘部署拓扑键。"""
        data = settings_store.public()
        if server_mode() == "server":
            for k in _SERVER_SETTINGS_HIDDEN:
                data.pop(k, None)
        return data

    @app.put("/api/settings")
    async def settings_put(request: Request) -> Response:
        """合并更新（0600 原子写 + connections 分槽）。

        键白名单 = ``SettingsStore.FIELDS`` + ``clear_api_key``/``has_api_key``
        两个伪字段——未知键直接 400，否则 save 会原样写进 settings.json
        攒垃圾键（load 侧 FIELDS 过滤只是读时兜底）。
        """
        _settings_write_gate()
        body = await _read_body(request)
        allowed = set(SettingsStore.FIELDS) | {"clear_api_key", "has_api_key"}
        bad_keys = sorted(set(body) - allowed)
        if bad_keys:
            return _json_error(400, f"settings 未知字段: {bad_keys}")
        try:
            # save 内含同步 httpx 探活（timeout 不盖 DNS getaddrinfo，
            # 死 DNS 网络可卡数十秒）——to_thread 卸载防冻结事件循环；
            # merge 串行语义由 SettingsStore._save_lock 接管
            await asyncio.to_thread(settings_store.save, body)
        except (TypeError, ValueError) as e:
            # 字段值类型错（concurrency 收 None/dict/list 时 int() TypeError）
            # 与校验错同归 400——非数值输入是客户端错误非服务端故障
            return _json_error(400, str(e))
        return JSONResponse(settings_store.public())

    @app.post("/api/settings/test")
    async def settings_test(request: Request) -> Response:
        """探活配置端点：body 可带覆盖值；错误信息先过 scrub。"""
        _settings_write_gate()
        body = await _read_body(request)
        if body.get("base_url") and not body.get("api_key"):
            # 跨槽组合即已存 key 被打向任意出站地址的 exfil oracle——
            # 与 settings.save 的「新槽按新 base_url 查 key」同设计。
            return _json_error(400, "覆盖 base_url 须同给 api_key")
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
        """列 provider 预设清单；server 摘 ``has_env_key``（部署方 env 凭据面）。"""
        presets = provider_presets(settings_store.load())
        if server_mode() == "server":
            for p in presets:
                p.pop("has_env_key", None)
        return {"providers": presets}

    # ------------------------------------------------------------ SPA 静态

    mount_spa(app)

    return app
