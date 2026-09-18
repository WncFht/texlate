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
import hashlib
import ipaddress
import json
import logging
import re
import secrets
import shutil
import sqlite3
import stat as stat_mod
import subprocess
import time
from collections import OrderedDict
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse
from starlette._utils import get_route_path  # 路由匹配同一条路径视图（剥 root_path）
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

try:
    import python_multipart as _pymp
except ModuleNotFoundError:  # pragma: no cover -- 旧式包名回落（同 starlette）
    import multipart as _pymp  # type: ignore[no-redef]

from texlate import __version__
from texlate.arxiv.fetch import _valid_id, normalize_arxiv_id
from texlate.compile.toolchain import find_tool, resolve_tool
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
    CHUNKS_PAGE_MAX,
    RETRYABLE_FROM,
    TERMINAL_STATUSES,
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
    from typing import BinaryIO

    from starlette.types import Message

    from texlate.arxiv.cache import SourceCache
    from texlate.arxiv.fetch import Fetcher
    from texlate.compile.engine import Engine
    from texlate.share import ShareManifest
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
    "share.zip": "application/zip",
}

#: 任务状态 → hjfy ``arxivStatus`` 词汇（compat 端点映射表）。hjfy 侧
#: ``start``/``finished`` 都被客户端当中间态（finished 仅表管线跑完、
#: zhCN 未落地还会再 prime）；本侧终态里 done/partial 有产物出才算
#: finished，弃单系归 failed、needs_auth 归 error、fault 同名直译。
_HJFY_STATUS = {
    "queued": "start",
    "fetching": "start",
    "parsing": "start",
    "translating": "start",
    "compiling": "start",
    "done": "finished",
    "partial": "finished",
    "cancelled": "failed",
    "interrupted": "failed",
    "needs_auth": "error",
    "fault": "fault",
}

#: 会产出 ``dual.json``（→ reader 可用）的任务 kind。docx/epub 走
#: export 双语插译没有 dual.json——``_accepted`` 对它们不发 reader_url。
_DUAL_JSON_KINDS = frozenset(
    {"arxiv", "share", "upload_tex", "upload_pdf", "arxiv_html"}
)

#: ``/api/tasks?status=`` 过滤的合法值域——11 态机全集（ACTIVE+TERMINAL）。
_ALL_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES


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
    """multipart 文件字段——流式落盘后的 spool 引用（不进 RAM）。

    ``path`` 是 ``_parse_multipart`` 在 data_dir spool 目录落的临时文件；
    消费端 ``Path.replace`` 走改名（同文件系统零拷贝），处理完毕或异常
    由调用方兜底 ``unlink(missing_ok=True)``——已 rename 走的 no-op。
    """

    filename: str
    path: Path
    size: int


def _spool_part(src: BinaryIO, dst: Path, budget: int) -> int:
    """``src`` fileobj → ``dst`` 流式拷贝（64KB 块），返回写入字节数。

    超 ``budget`` 即中断抛 413（文件字段合计额度在 ``_parse_multipart``
    累计）；任何失败清掉半成品 dst——TOCTOU 无所谓，dst 名是本调用独占
    的随机串。
    """
    written = 0
    try:
        with dst.open("wb") as out:
            while True:
                # max(1, …)：budget 耗尽后再读 1B 探溢出——read(≤0) 会
                # 全量回拉剩余流，把有界读打成无界
                chunk = src.read(min(1 << 16, max(1, budget - written + 1)))
                if not chunk:
                    break
                written += len(chunk)
                out.write(chunk)
                if written > budget:
                    break
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
    if written > budget:
        dst.unlink(missing_ok=True)
        raise _ApiError(
            413,
            {
                "detail": f"upload > {UPLOAD_CAP}B",
                "code": "upload_too_large",
            },
        )
    return written


_MULTIPART_OVERHEAD = 65536
_FILENAME_MAX = 255  # POSIX NAME_MAX（字节）——净化名全 ASCII，len 即字节数

#: JSON 端点 body 上限——``_read_body`` 消费面（translate/retry/reader PUT/
#: settings PUT/settings test）。与 upload 的 ``UPLOAD_CAP`` 分开：JSON
#: 端点无文件载荷，合法体远小于 4MB（options 本身再受 ``_OPTIONS_JSON_CAP``
#: 64KB 约束），共享 80MB 闸只放大解析面内存账。
_JSON_BODY_CAP = 4 << 20


def _cap_request_body(request: Request, cap: int, code: str, label: str) -> None:
    """给 ``request`` 的 receive 通道装字节闸：累计体超 ``cap`` → 413。

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
        if seen > cap:
            raise _ApiError(
                413,
                {"detail": f"{label} > {cap}B", "code": code},
            )
        return msg

    request._receive = capped  # noqa: SLF001 -- 同上：替换实例 receive 通道


async def _parse_multipart(
    request: Request, spool_dir: Path
) -> dict[str, str | UploadPart]:
    """``multipart/form-data`` → ``{name: str | UploadPart}``。

    走 starlette ``request.form()``（python-multipart 在 server extra 内）；
    ``Content-Length`` 超 ``UPLOAD_CAP + overhead`` 先 413 不读体。
    ``Content-Length`` 缺席（chunked/HTTP2）预检失效——``_cap_request_body``
    的流式字节闸对 str/文件全部字段合计上界，超界即 413。文件字段流式
    落 ``spool_dir`` 临时文件（``_spool_part`` 64KB 块拷贝，剩余额度有界，
    累计超 ``UPLOAD_CAP`` 即 413）——``val.read()`` 全量回拉 RAM 的旧面
    取消，峰值内存随并发数不再按整文件翻倍。
    """
    clen = request.headers.get("content-length", "")
    if clen.isdigit() and int(clen) > UPLOAD_CAP + _MULTIPART_OVERHEAD:
        raise _ApiError(
            413, {"detail": f"upload > {UPLOAD_CAP}B", "code": "upload_too_large"}
        )
    _cap_request_body(
        request, UPLOAD_CAP + _MULTIPART_OVERHEAD, "upload_too_large", "upload"
    )
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
        raise _ApiError(
            400,
            {"detail": f"malformed multipart: {e}", "code": "invalid_request"},
        ) from e
    out: dict[str, str | UploadPart] = {}
    file_bytes = 0
    for name, val in form.multi_items():
        if isinstance(val, StarletteUploadFile):
            await val.seek(0)
            tmp = spool_dir / f".part-{secrets.token_hex(8)}"
            size = await asyncio.to_thread(
                _spool_part, val.file, tmp, UPLOAD_CAP - file_bytes
            )
            file_bytes += size
            out[name] = UploadPart(filename=val.filename or "", path=tmp, size=size)
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

#: ``options`` 落库序列化上限——body 闸放到 UPLOAD_CAP 级，options_json
#: 是无 schema 自由 KV，巨型 blob 会原样进 ``tasks.options_json``
#: （每行拖 KB→MB 级垃圾且 ``options()`` 每读全解析）。64KB 远超合法
#: 键集（glossary/main/source/engine/concurrency/idempotency_key…）。
_OPTIONS_JSON_CAP = 65536

#: per-IP 配额兜底桶表界（``_check_quota``）——distinct peer 数有界防洪泛，
#: LRU 头出。4096 个 IPv6 字面量键 ≈ 数百 KB，量级无害。
_IP_QUOTA_MAX_PEERS = 4096


def _options_json_checked(options: dict[str, Any]) -> str:
    """``options`` → JSON 串：不可序列化或超 ``_OPTIONS_JSON_CAP`` → 400。"""
    try:
        raw = json.dumps(options, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise _ApiError(
            400,
            {"detail": f"options 须可 JSON 序列化: {e}", "code": "invalid_request"},
        ) from e
    if len(raw.encode()) > _OPTIONS_JSON_CAP:
        raise _ApiError(
            400,
            {
                "detail": f"options 序列化超 {_OPTIONS_JSON_CAP}B",
                "code": "invalid_request",
            },
        )
    return raw


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
                ),
                "code": "forbidden",
            },
        )


def _clean_task_options(
    options: dict[str, Any], *, inject_defaults: bool = True
) -> dict[str, Any]:
    """任务 options 入参闸（就地改写 + 返回）：摘保留键 + 白名单校验。

    ``engine`` 此前无入参校验——非法值要跑到编译段 ``engine_for`` 才炸成
    fault；``concurrency`` 裸 ``int()`` 对非数值输入直接 500。两闸与
    settings 同口径：engine ∈ ``_ENGINE_NAMES``；concurrency 须可转
    int 并 clamp 1–16。

    ``inject_defaults=False`` 是 retry 合并臂：只对 body 真实出现的键
    校验+归一，不注 ``source`` 默认——创建侧把 ``source`` 规范化回写
    无妨，retry 往存量 options 合并时注默认会把 ``html`` 任务的
    ``source`` 静默改回 ``eprint``。
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
    if inject_defaults or "source" in options:
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
    if inject_defaults:
        options.setdefault("auto_glossary", True)
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
    _options_json_checked(options)
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


def _loopback_peer(request: Request) -> bool:
    """TCP 对端回环判定——网络层事实，伪造 ``Host`` 绕不过。

    非 IP 字面量/缺席（UDS、in-process testclient）视为本机：真 TCP
    ``getpeername`` 恒返回 IP，非 IP 值只能来自非网络传输。IPv4-mapped
    IPv6（``::ffff:127.0.0.1``，``::`` 双栈监听下的 IPv4 对端）归一再判。
    """
    peer = request.client.host if request.client is not None else ""
    if not peer:
        return True
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return True
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    return addr.is_loopback


def _loopback_bind(host: str) -> bool:
    """``--host`` 绑定地址回环判定（cli/``__main__`` 启动警告用）。

    可解析 IP 看 ``is_loopback``；主机名形态查白名单——``0.0.0.0``/``::``
    与无法定性的主机名一律按非回环论。
    """
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        h = _host_only(host)
        return h in _LOOPBACK_HOSTS or h.endswith(".localhost")


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
    #: multipart 文件字段流式落盘目录（``_parse_multipart`` 写入面）；
    #: 残骸由 lifespan 启动段清扫。
    spool_dir = root / "tmp" / "upload-spool"
    #: per-IP 配额兜底桶（进程内累计，peer → ``[tasks, bytes]``）——
    #: tenant=sha256(key) 换 key 即新桶，本桶按网络对端记账封轮转。
    _ip_quota: OrderedDict[str, list[int]] = OrderedDict()

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

    async def _retention_loop() -> None:
        """产物保留策略周期 sweep（每 10min 一拍；``retention_*`` 全 0 = 关）。

        ``Store.sweep_retention`` 按 tasks/ 目录占用 + 行龄做淘汰；失败只
        log——保留策略是后台清扫面，故障绝不拖垮服务。settings 每拍重读
        （PUT 即生效，不用重启）。
        """
        while True:
            await asyncio.sleep(600)
            try:
                st = settings_store.load()
                days = int(st.get("retention_days") or 0)
                max_gb = int(st.get("retention_max_gb") or 0)
                if days <= 0 and max_gb <= 0:
                    continue
                report = await asyncio.to_thread(
                    store.sweep_retention,
                    root / "tasks",
                    max_age_s=float(days * 86400) if days > 0 else 0.0,
                    max_total_bytes=max_gb * (1 << 30) if max_gb > 0 else 0,
                )
                if report.get("removed"):
                    log.info("retention sweep: %s", report)
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
            raise _ApiError(400, {"detail": str(e), "code": "invalid_request"}) from e
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
        # JSON 端点独立小闸（_JSON_BODY_CAP）——无 CL 时 body() 原是无界读
        _cap_request_body(request, _JSON_BODY_CAP, "body_too_large", "body")
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
            raise _ApiError(
                400, {"detail": f"bad json: {e}", "code": "invalid_request"}
            ) from e
        if not isinstance(data, dict):
            # 非 object JSON（[1]/"x"/null）——静默当 {} 会让 PUT settings 等
            # 端点 200 无操作，调用方无从察觉体被整个丢弃
            raise _ApiError(
                400,
                {"detail": "json body 须为 object", "code": "invalid_request"},
            )
        return data

    def _check_quota(auth: AuthContext, incoming_bytes: int, peer: str = "") -> None:
        """Tenant 配额闸（settings.quota_max_*，0=不限）——超限 429。

        任务数按 ``tasks`` 行全量计（含终态行）；字节按已登记产物
        ``files.bytes`` 合计 + 本次入队载荷。reuse/idempotent 命中不建行，
        在调用方此处之前就返回，不占配额。

        ``peer`` 非空时再叠加进程内 per-IP 兜底桶（同字节口径累计）：
        tenant=sha256(key) 的锅——换 key 即新桶，轮转 key 刷 upload 把
        tenant 配额打成筛子。IP 桶按对端地址记进程内累计，key 轮转不改
        对端事实。局限（记注释不瞒）：进程重启清零、NAT 后多用户共 IP
        会互占额度、local 形态全量请求共享回环桶（同机用户配额同桶，
        语义上可接受——local 本就是单机面）。
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
        if not peer:
            return
        bucket = _ip_quota.get(peer)
        if bucket is None:
            if len(_ip_quota) >= _IP_QUOTA_MAX_PEERS:
                _ip_quota.popitem(last=False)  # LRU 头出——有界表防 IP 洪泛
            bucket = [0, 0]
            _ip_quota[peer] = bucket
        else:
            _ip_quota.move_to_end(peer)
        if q_tasks and bucket[0] >= q_tasks:
            raise _ApiError(
                429,
                {
                    "detail": f"同 IP 任务配额已用尽（{q_tasks}）",
                    "code": "quota_exceeded",
                },
            )
        if q_bytes and bucket[1] + incoming_bytes > q_bytes:
            raise _ApiError(
                429,
                {
                    "detail": f"同 IP 字节配额超限（{q_bytes}B）",
                    "code": "quota_exceeded",
                },
            )
        # 过闸才累计——被拒请求不占桶；建行失败的多计是保守方向
        bucket[0] += 1
        bucket[1] += incoming_bytes

    def _create_and_enqueue(  # noqa: C901, PLR0913 -- dedup/reuse/建行阶梯 + 参数面平铺
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
                if server_mode() == "server" and str(done["tenant"]) != auth.tenant:
                    # 跨租户命中——直接回 hit 行的 task_id 对本租户是死链
                    # （_get_task tenant 检恒 404）。改走建行+worker
                    # post-resolve dedup：_materialize_reuse 把产物真拷进
                    # 本任务目录，租户拿到自己的可读任务句柄。
                    # 存 alias（无版本）键使 stored≠resolved——钉版请求
                    # 也能命中物化臂；share/upload 等不走 post_resolve 的
                    # kind 保留原键（真跑语义不变，dedup 槽位照占）。
                    if kind in ("arxiv", "arxiv_html") and arxiv_id:
                        cache_key = cache_key_for(
                            arxiv_id=arxiv_id,
                            version=None,
                            model=model,
                            target_lang=target_lang,
                            api_key=auth.api_key,
                            source=str(options.get("source") or "eprint"),
                        )
                else:
                    return done, 200, {"reused": True}
        _check_quota(
            auth,
            incoming_bytes,
            request.client.host if request.client is not None else "",
        )
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
                # 检查-建行之间并发插入撞 ACTIVE 唯一索引——归 duplicate_active
                # （原来裸 re-raise 出 FastAPI 成无码 500）
                active = store.find_active_by_cache_key(cache_key)
                body: dict[str, Any] = {
                    "detail": "active task exists",
                    "code": "duplicate_active",
                }
                if active is not None:
                    body["detail"] = f"active task {active['id']} exists"
                    body["task_id"] = active["id"]
                raise _ApiError(409, body) from None
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
            return _json_error(
                400, f"invalid arxiv id: {arxiv_id!r}", "invalid_request"
            )
        body = await _read_body(request)
        try:
            options = dict(body.get("options") or {})
        except (TypeError, ValueError):
            return _json_error(
                400, "options 须为 object 或 KV 对列表", "invalid_request"
            )
        options = _clean_task_options(options)
        try:
            model = validate_model(str(body.get("model") or _auth(request).model))
        except ValueError as e:
            return _json_error(400, str(e), "invalid_request")
        target_lang = str(
            body.get("target_lang") or _auth(request).settings["target_lang"]
        )
        if target_lang not in TARGET_LANGS:
            return _json_error(
                400, f"target_lang ∈ {sorted(TARGET_LANGS)}", "invalid_request"
            )
        if body.get("glossary"):
            options["glossary"] = str(body["glossary"])
        prefer = str(options.get("prefer") or "reuse")
        if prefer not in ("reuse", "fresh"):
            return _json_error(400, "options.prefer ∈ reuse|fresh", "invalid_request")
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

    # ------------------------------------------------------------ hjfy 兼容面

    def _hjfy_row(request: Request, arxiv_id: str) -> dict[str, Any]:
        """``hjfy`` 轮询端点共用解析：id 归一校验 + tenant 内最新任务行（无 → 404）。"""
        base, ver = normalize_arxiv_id(arxiv_id)
        if not _valid_id(base):
            raise _ApiError(
                400,
                {
                    "detail": f"invalid arxiv id: {arxiv_id!r}",
                    "code": "invalid_request",
                },
            )
        row = store.find_latest_by_arxiv(_auth(request).tenant, base, ver)
        if row is None:
            raise _ApiError(404, {"error": "not_found"})
        return row

    @app.get("/api/arxivStatus/{arxiv_id:path}")
    async def arxiv_status(request: Request, arxiv_id: str) -> Response:
        """``hjfy`` 轮询面（competitors.md §4）：``{status, info}`` + 扩展键。

        状态词汇按 hjfy 插件轮询协议映射（``_HJFY_STATUS``）；
        ``progress``/``task_id`` 是附加信息——只读 status/info 的客户端
        不受影响。
        """
        row = _hjfy_row(request, arxiv_id)
        return JSONResponse(
            {
                "status": _HJFY_STATUS.get(str(row["status"]), "error"),
                "info": str(row.get("message") or ""),
                "progress": int(row["progress"]),
                "task_id": str(row["id"]),
            }
        )

    @app.get("/api/arxivFiles/{arxiv_id:path}")
    async def arxiv_files(request: Request, arxiv_id: str) -> Response:
        """``hjfy`` 产物面：``{status, msg, data:{id,title,origin,zhCN,zhCNTar,isDeepSeek}}``。

        ``status:0`` + ``data.zhCN`` 非空是客户端的「译好」判据；
        ``101`` + 「请登录」= 需认证；其余态 ``msg`` 载任务行 message
        （进行中/失败文案驱动 pending/dead 判定）。产物 URL 指到
        ``/api/files/{id}/{kind}`` 下载路由——en.pdf→origin、
        zh.pdf→zhCN、zh-src.zip→zhCNTar；未产出的 kind 给空串。
        """
        row = _hjfy_row(request, arxiv_id)
        tid = str(row["id"])
        recs = store.files(tid)

        def _url(kind: str) -> str:
            if kind not in recs:
                return ""
            return f"/api/files/{tid}/{KIND_URL[kind]}"

        if str(row["status"]) == "needs_auth":
            code, msg = 101, "请登录"
        elif recs.get("zh_pdf"):
            code, msg = 0, ""
        elif str(row["status"]) in TERMINAL_STATUSES:
            code, msg = 0, str(row.get("message") or "翻译失败")
        else:
            code, msg = 0, "正在处理中"
        return JSONResponse(
            {
                "status": code,
                "msg": msg,
                "data": {
                    "id": str(row.get("arxiv_id") or ""),
                    "title": str(row.get("title") or ""),
                    "origin": _url("en_pdf"),
                    "zhCN": _url("zh_pdf"),
                    "zhCNTar": _url("zh_src_zip"),
                    "isDeepSeek": False,
                },
            }
        )

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

    @app.get("/api/task/{task_id}/chunks")
    async def task_chunks(
        request: Request,
        task_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        # 声明上限必须与 store 钳位同值——高于 CHUNKS_PAGE_MAX 的 limit
        # 会拿 200 却静默丢尾页（clamp 不回告）
        limit: Annotated[int, Query(ge=1, le=CHUNKS_PAGE_MAX)] = 200,
    ) -> Response:
        """Chunk 窄列分页（翻译中流式预览面，fe-U1 配套）。

        返回 ``{chunks: [{seq, kind, status, en, zh}], total}``——pending
        块 ``zh`` 为空串；``total`` 是全集大小供前端翻页/进度条。
        """
        _get_task(request, task_id)
        rows, total = store.chunks_page(task_id, offset=offset, limit=limit)
        return JSONResponse(
            {
                "chunks": [
                    {
                        "seq": r["seq"],
                        "kind": r["kind"],
                        "status": r["status"],
                        "en": r.get("src_text") or "",
                        "zh": r.get("translation") or "",
                    }
                    for r in rows
                ],
                "total": total,
            }
        )

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
    async def file_get(  # noqa: C901, PLR0911 -- 校验阶梯每层一个早退 return
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
            return _json_error(404, f"unknown kind {kind!r}", "not_found")
        rec = store.file_record(task_id, db_kind)
        if rec is None:
            return _json_error(404, f"no artifact {kind}", "not_found")
        if version and rec.get("sha256") and version != rec["sha256"]:
            return _json_error(
                409,
                f"version mismatch: have {rec['sha256'][:12]}",
                "version_mismatch",
            )
        if version and rec.get("sha256"):
            # ``?version=<sha256>`` 内容寻址命中——响应随 sha 不变而异变，
            # 私有缓存可钉死。no_store_mw 认 request.state 标记。
            request.state.cache_control = "private, immutable"
        task_root = (root / "tasks" / task_id).resolve()
        path = (task_root / rec["path"]).resolve()
        if not path.is_relative_to(task_root):
            return _json_error(404, "artifact file missing", "not_found")
        try:
            stat_res = path.stat()
        except OSError:
            return _json_error(404, "artifact file missing", "not_found")
        if not stat_mod.S_ISREG(stat_res.st_mode):
            return _json_error(404, "artifact file missing", "not_found")
        headers = None
        if download:
            # 旧式 arxiv_id 含 '/'（hep-th/9901001）——filename 白名单化防畸形 header
            stem = re.sub(r"[^A-Za-z0-9_.+-]", "_", str(row.get("arxiv_id") or task_id))
            headers = {
                "Content-Disposition": (f'attachment; filename="texlate-{stem}-{kind}"')
            }
        try:
            media = (
                _src_tar_media(str(row["kind"]), path)
                if kind == "src.tar"
                else _MEDIA.get(kind, "application/octet-stream")
            )
        except OSError:
            # src.tar 魔数嗅探 open() 竞删——与 stat 同归 404
            return _json_error(404, "artifact file missing", "not_found")
        if media.startswith("text/html"):
            # html 产物同源伺服——直接导航时文档内幸存脚本可在同源上下文
            # 打 mutating /api；CSP sandbox（无 allow-*）整文档脚本全灭。
            # 纵深防御：worker _sanitize_dom 主防线 + 前端 DOMPurify 之外的
            # 服务端兜底；不挡 img-src（sandbox 只禁脚本）
            headers = {**(headers or {}), "Content-Security-Policy": "sandbox"}
        # stat_result 直传：__call__ 跳过惰性 stat——不给 is_file→serve 留
        # TOCTOU 窗（starlette 惰性 stat 缺文件抛 RuntimeError 裸 500）
        return FileResponse(
            path, media_type=media, headers=headers, stat_result=stat_res
        )

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
            raise _ApiError(
                400,
                {"detail": "options 字段不是合法 JSON", "code": "invalid_request"},
            ) from None
        if not isinstance(options, dict):
            options = {}
        options = _clean_task_options(options)
        try:
            model = validate_model(_form_text(form, "model") or _auth(request).model)
        except ValueError as e:
            raise _ApiError(400, {"detail": str(e), "code": "invalid_request"}) from e
        target_lang = _form_text(form, "target_lang") or str(
            _auth(request).settings["target_lang"]
        )
        if target_lang not in TARGET_LANGS:
            raise _ApiError(
                400,
                {
                    "detail": f"target_lang ∈ {sorted(TARGET_LANGS)}",
                    "code": "invalid_request",
                },
            )
        if _form_text(form, "main"):
            options["main"] = _form_text(form, "main")
        return model, target_lang, options

    @app.post("/api/upload")
    async def upload(request: Request) -> Response:
        """Multipart 上传：魔数路由 upload_tex/upload_pdf/docx/epub（§2.4）。"""
        form = await _parse_multipart(request, spool_dir)
        file = form.get("file")
        if not isinstance(file, UploadPart):
            raise _ApiError(
                400,
                {
                    "detail": "multipart field 'file' required",
                    "code": "invalid_request",
                },
            )
        try:
            if file.size == 0:
                raise _ApiError(
                    400, {"detail": "empty upload", "code": "invalid_request"}
                )
            filename = file.filename or "upload.bin"
            # 魔数路由读全 blob（gzip/zip 容器判定非头字节可定）——CPU+读盘
            # 秒级，卸出事件循环；临时 bytes 不出本函数域
            route = await asyncio.to_thread(
                sniff_upload, file.path.read_bytes(), filename
            )
            _check_upload_route(
                route, app.state.babeldoc or find_tool("babeldoc"), filename
            )
            model, target_lang, options = _upload_fields(request, form)
            # re.sub 白名单放行 ``.``——``..`` 原样幸存会打成目录写（500+
            # 孤儿 task 目录），建行前先拒。>255B 名（NAME_MAX）会让落盘
            # 抛 ENAMETOOLONG 成 500——同闸先拒。
            safe = re.sub(r"[^A-Za-z0-9_.+-]", "_", Path(filename).name)
            if safe in (".", "..") or len(safe) > _FILENAME_MAX:
                raise _ApiError(
                    400,
                    {
                        "detail": f"unsafe filename: {filename!r}",
                        "code": "invalid_request",
                    },
                )
            # 先落 blob（建行前），再建行+入队——task_id 两侧共用
            task_id = new_task_id()
            updir = root / "tasks" / task_id / "upload"

            def _stage() -> None:
                updir.mkdir(parents=True, exist_ok=True)
                # spool → 任务目录同文件系统 rename——零拷贝交接
                file.path.replace(updir / (safe or "upload.bin"))

            try:
                await asyncio.to_thread(_stage)
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
                    incoming_bytes=file.size,
                )
            except Exception:
                # 建行/入队任何失败——upload blob 目录一并收掉，不留孤儿（B4）；
                # rmtree 是重 I/O，卸出事件循环
                await asyncio.to_thread(
                    shutil.rmtree, root / "tasks" / task_id, ignore_errors=True
                )
                raise
            if str(row["id"]) != task_id:
                # idempotent 命中旧行——本次落盘 blob 成孤儿，连带目录清掉（B4）
                await asyncio.to_thread(
                    shutil.rmtree, root / "tasks" / task_id, ignore_errors=True
                )
            return _accepted(row, status, extra)
        finally:
            # spool 件已 rename 走则 no-op；仍躺 spool 即本次未消费——收掉
            with suppress(OSError):
                file.path.unlink(missing_ok=True)

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
        form = await _parse_multipart(request, spool_dir)
        file = form.get("file")
        if not isinstance(file, UploadPart):
            raise _ApiError(
                400,
                {
                    "detail": "multipart field 'file' required",
                    "code": "invalid_request",
                },
            )
        try:
            if file.size == 0:
                raise _ApiError(
                    400, {"detail": "empty upload", "code": "invalid_request"}
                )
            tid = new_task_id()
            tdir = root / "tasks" / tid

            def _stage() -> ShareManifest:
                bundle_dir = tdir / "upload"
                bundle_dir.mkdir(parents=True, exist_ok=True)
                bundle = bundle_dir / "bundle.share.zip"
                file.path.replace(bundle)  # spool → 任务目录同 fs rename
                return unpack_share(bundle, tdir / "share")

            try:
                # 逐成员 sha256+解压跑满 CPU 秒级——卸出事件循环（share_pack 同口径）
                mf = await asyncio.to_thread(_stage)
                parts = mf.key_parts
                base, ver_s, model, lang, ver = _share_parts_checked(parts)
                options_raw = _form_text(form, "options")
                try:
                    options = json.loads(options_raw) if options_raw else {}
                except (ValueError, RecursionError):
                    raise _ApiError(
                        400,
                        {
                            "detail": "options 字段不是合法 JSON",
                            "code": "invalid_request",
                        },
                    ) from None
                if not isinstance(options, dict):
                    options = {}
                options = _clean_task_options(options)
                # 审计载荷强制覆盖——调用方 options 不得伪造 share 来源字段。
                # 注入在 64KB 闸之后发生（manifest 字段已经
                # ``_manifest_field_max`` 收敛），注入后重跑尺寸闸兜底。
                options["share"] = {
                    "share_key": mf.share_key,
                    "contributor": mf.contributor,
                    "created_at": mf.created_at,
                    "key_parts": dict(parts),
                }
                _options_json_checked(options)
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
                    incoming_bytes=file.size,
                )
            except ShareError as e:
                await asyncio.to_thread(shutil.rmtree, tdir, ignore_errors=True)
                raise _ApiError(
                    400,
                    {
                        "detail": f"share bundle invalid: {e}",
                        "code": "share_invalid",
                    },
                ) from e
            except sqlite3.IntegrityError:
                # reuse 语义下并发同键撞 ACTIVE 唯一索引——归 duplicate_active
                await asyncio.to_thread(shutil.rmtree, tdir, ignore_errors=True)
                raise _ApiError(
                    409,
                    {"detail": "active task exists", "code": "duplicate_active"},
                ) from None
            except Exception:
                # 落盘/解包/校验/建行/入队任何失败（含 _ApiError 与非预期异常）
                # ——task 目录一并收掉，不留孤儿（upload 端点 B4 同口径）
                await asyncio.to_thread(shutil.rmtree, tdir, ignore_errors=True)
                raise
            if str(row["id"]) != tid:
                # reuse/idempotent 命中旧行——本次解包现场作废（行从未建）
                await asyncio.to_thread(shutil.rmtree, tdir, ignore_errors=True)
            return _accepted(row, status, extra)
        finally:
            with suppress(OSError):
                file.path.unlink(missing_ok=True)

    # ------------------------------------------------------------ share 导出

    def _mirror_share_zip(task_id: str, bundle: Path) -> tuple[int, str]:
        """发布包流式拷进 ``tasks/{id}/share.zip`` → ``(bytes, sha256)``。

        ``file_get`` 只服 ``tasks/{id}/`` 相对路径（confine 闸）——share_dir
        的包对 files manifest 不可达，拷一份任务目录内镜像上产物面。
        重 I/O——调用方 ``to_thread`` 卸载。
        """
        dst = root / "tasks" / task_id / "share.zip"
        digest = hashlib.sha256()
        size = 0
        with bundle.open("rb") as src, dst.open("wb") as out:
            while chunk := src.read(1 << 20):
                out.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        return size, digest.hexdigest()

    async def _register_share_zip(task_id: str, bundle: Path) -> None:
        """share.zip 镜像落盘 + files 登记 ``share_zip``（前端产物面）。

        best-effort：镜像拷贝失败只留 warning——共享包发布（包文件 +
        index.jsonl 行）已成功，产物面缺项由重发 pack 自愈，不把 200
        打成 500。
        """
        try:
            size, sha = await asyncio.to_thread(_mirror_share_zip, task_id, bundle)
        except OSError as e:
            log.warning("share.zip 镜像登记失败 %s: %s", task_id, e)
            return
        store.put_file(task_id, "share_zip", "share.zip", size=size, sha256=sha)

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
        # manifest 派生会读生效术语表文件算 hash（重 I/O）——卸出 loop；
        # 与 worker 侧 ``_share_pack_try`` 的 ``_to_thread`` 口径对齐
        manifest = await asyncio.to_thread(worker.share_pack_manifest, ctx, row)
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
            # index.jsonl 整读全扫——append-only 索引随时间增长，卸出 loop
            hit = await asyncio.to_thread(index_lookup, out_dir / "index.jsonl", key)
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
                    await _register_share_zip(task_id, out_dir / name)
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
        await _register_share_zip(task_id, bundle)
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
        """``{ok}`` 探活最小集；server 附加 ``db``/``queue_depth``；local 附加 ``version/commit/started_at/compilers/data_dir``。"""
        if server_mode() == "server":
            # 深度探活：db=真实 SELECT 探测（queued_rows 顺带产出队列深度），
            # 探挂只降 db=False 不 503——健康面只报不掩
            db_ok = True
            queue_depth: int | None = None
            try:
                queue_depth = len(store.queued_rows())
            except (StoreError, sqlite3.Error) as e:
                log.warning("health db probe failed: %s", e)
                db_ok = False
            return {"ok": True, "db": db_ok, "queue_depth": queue_depth}
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
    async def tasks_list(
        request: Request,
        status: str = "",
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> Response:
        """Tenant 过滤任务列表（``?status=`` 枚举校验再过滤；``limit``/``offset`` 分页）。

        ``total`` = 过滤后全集大小（非本页行数），前端分页条用。
        非法 ``status`` 值 400——不校验会静默返空 200，调用方无从分辨
        「无匹配」与「参数打错」。
        """
        if status and status not in _ALL_STATUSES:
            return _json_error(
                400,
                f"status ∈ {sorted(_ALL_STATUSES)}",
                "invalid_request",
            )
        rows, total = store.list_tasks_page(
            _auth(request).tenant,
            status=status or None,
            limit=limit,
            offset=offset,
        )
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
                        # 行快照水位——前端 refresh reconcile 据以拒旧读回退
                        "last_seq": r["last_seq"],
                    }
                    for r in rows
                ],
                "total": total,
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
    async def task_retry(request: Request, task_id: str) -> Response:  # noqa: C901 -- 校验阶梯平铺
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
            # 合并臂不注默认——``inject_defaults=False`` 只校验 body 真实
            # 出现的键，缺席的 ``source`` 不会被改回 ``eprint``（html 任务
            # 的存量 source 原样保留）
            opts.update(_clean_task_options(body["options"], inject_defaults=False))
        if body.get("main"):
            opts["main"] = str(body["main"])
        # 合并结果重跑帽闸——_clean_task_options 只闸 body 增量，存量+增量
        # 可越 _OPTIONS_JSON_CAP（与 share 导入臂 post-merge 重闸同口径）。
        # 必须先于 transition——超帽 400 拒在抢 queued 前，任务行不动
        options_json = _options_json_checked(opts)
        main_req = str(opts.get("main") or "")
        # body 显式带 engine 且 ≠ 上轮持久化的 ``engine_resolved`` → 换引擎
        # 与换 main 同档清废：base/ 树是旧引擎 ``normalize_project`` 产物，
        # ``.base-done`` 哨兵不抹则 ``_build_base`` 整段跳过、engine_resolved
        # 原地复活旧引擎（``_clean_task_options`` 已摘 body 内保留键，
        # 合并后 opts 里读到的 engine_resolved 恒是上轮真值）
        body_opts = body.get("options")
        engine_req = (
            str(body_opts.get("engine") or "") if isinstance(body_opts, dict) else ""
        )
        engine_stale = bool(engine_req) and engine_req != str(
            opts.get("engine_resolved") or ""
        )
        # 原子守卫先行——抢到 queued 前不做任何破坏清理。双发 retry 时后者
        # 在此 409 出局，不再抹掉 worker 已重插的 chunks / 覆盖 options（B3）
        try:
            store.transition(task_id, "queued", message="重试入队")
        except TransitionError as e:
            return _json_error(409, str(e), "invalid_transition")
        try:
            if (
                main_req and main_req != str(row.get("main_tex") or "")
            ) or engine_stale:
                # 换主文件（body.main 与 options.main 同口径）或显式换引擎 →
                # 解析产物作废（chunks/base/zh 重建，src/ 保留）；派生产物行
                # 与磁盘件并删——残行会让 files/reader 照发上一轮产物
                # （en.pdf 也随 base/ 同死：换 main/引擎后它编译自另一棵树）
                store.delete_chunks(task_id)
                task_root = root / "tasks" / task_id
                recs = [
                    (kind, rec)
                    for kind, rec in store.files(task_id).items()
                    if kind != "src_tar"  # 取源产物不受影响——e-print/上传件仍有效
                ]

                def _wipe() -> None:
                    """FS 侧清理（rmtree×4 + 失效产物 unlink）——重 I/O 离 loop。"""
                    for d in ("base", "zh", "build-en", "build-zh"):
                        shutil.rmtree(task_root / d, ignore_errors=True)
                    resolved_root = task_root.resolve()
                    for _kind, rec in recs:
                        stale = (task_root / str(rec["path"])).resolve()
                        if stale.is_relative_to(resolved_root):
                            with suppress(OSError):
                                stale.unlink(missing_ok=True)

                await asyncio.to_thread(_wipe)
                for kind, _rec in recs:
                    store.delete_file(task_id, kind)
            store.update_fields(task_id, options_json=options_json)
        except Exception:
            # 已抢 queued 但清理/写 options 折了——不留 queued 半成品给
            # dispatcher 捡，转 fault 把责任落回行状态
            with suppress(StoreError):
                store.transition(task_id, "fault", force=True, message="retry 清理失败")
            raise
        runner.enqueue(task_id, _secrets_for(request, row))
        return _accepted(store.get(task_id) or row, 202, {"cache": "retry"})

    @app.post("/api/task/{task_id}/chunk/{seq}/retranslate")
    async def chunk_retranslate(request: Request, task_id: str, seq: int) -> Response:
        """终态任务单块重译入队——202 ``{task_id, seq, status:"queued"}``。

        守卫阶梯：任务存在 + tenant 隔离（``_get_task`` 404）→ 状态须
        done/partial（reader 消费面——ACTIVE 与其余终态 409）→ seq 须
        命中 chunks 表（404）→ ``auth_source=header`` 重带 key（401，
        retry 同口径：内存 secrets 随终态已摘）。``enqueue_retranslate``
        的 KeyError/ValueError 归一 404/409——检查到入队之间行被并发
        删/改态的竞态兜底。
        """
        row = _get_task(request, task_id)
        if str(row["status"]) not in ("done", "partial"):
            return _json_error(
                409,
                f"任务状态 {row['status']}：仅 done/partial 终态可单块重译",
                "invalid_state",
            )
        if seq < 0 or not store.chunk_exists(task_id, seq):
            return _json_error(404, f"no chunk seq {seq}", "not_found")
        if row["auth_source"] == "header" and not request.headers.get("x-texlate-key"):
            return _json_error(
                401,
                "auth_source=header：重译必须重带 X-Texlate-Key",
                "auth_required",
            )
        try:
            runner.enqueue_retranslate(task_id, seq, _secrets_for(request, row))
        except KeyError:
            return _json_error(404, "task not found", "not_found")
        except ValueError as e:
            return _json_error(409, str(e), "invalid_state")
        return JSONResponse(
            {"task_id": task_id, "seq": seq, "status": "queued"},
            status_code=202,
        )

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
        # 先发终帧再删行——task_events FK 挂 tasks(id)，删后 publish 即
        # 约束违例；publish→delete 间无 await，对并发 retry/cancel 原子
        bus.publish(
            task_id,
            "done",
            {"status": "deleted", "artifacts": {}, "stats": {}},
        )
        if not store.delete_task_guard(task_id, blocked=ACTIVE_STATUSES):
            # 读时终态、删前被并发 retry 激活（跨进程/极端时序）——条件写兜底
            return _json_error(
                409,
                f"task {task_id} is active: cancel first",
                "invalid_transition",
            )
        runner.secrets.pop(task_id, None)
        # 任务目录可能是 GB 级产物树——rmtree 重 I/O 卸出 loop
        await asyncio.to_thread(
            shutil.rmtree, root / "tasks" / task_id, ignore_errors=True
        )
        return JSONResponse({"task_id": task_id, "status": "deleted"})

    # ------------------------------------------------------------ reader

    @app.get("/api/task/{task_id}/reader")
    async def reader_get(  # noqa: C901 -- 序列化装配阶梯平铺
        request: Request, task_id: str
    ) -> Response:
        """``{documents, alignment, reading, view}``（§2.5/§5.4）。"""
        row = _get_task(request, task_id)
        # files 表一次取——file_record 每次全量 SELECT，本端点要查 4 个
        # kind（dual_json/zh_html/md_zip/zh_pdf），串发即 mini-N+1
        files = store.files(task_id)
        dual_path = root / "tasks" / task_id / "dual.json"
        if files.get("dual_json") is None:
            # 以登记行为准——磁盘孤儿件（登记前崩溃/失效清理残留）不服务
            return _json_error(404, "dual.json 未产出", "not_found")

        def _load() -> dict[str, Any]:
            if not dual_path.is_file():
                raise FileNotFoundError(dual_path)
            data: Any = json.loads(dual_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise TypeError  # 非 object 与 corrupt 同归 500——调用方只分 404/500/ok
            return cast("dict[str, Any]", data)

        try:
            # 数 MB 级读+解析——卸出事件循环
            dual = await asyncio.to_thread(_load)
        except FileNotFoundError:
            return _json_error(404, "dual.json 未产出", "not_found")
        except (json.JSONDecodeError, TypeError):
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
                    if files.get("zh_html")
                    else (
                        "html"
                        if files.get("md_zip") and not files.get("zh_pdf")
                        else "pdf"
                    )
                ),
            }
        )

    @app.put("/api/task/{task_id}/reader/position")
    async def reader_put(request: Request, task_id: str) -> Response:
        """阅读位置落盘（``tasks/{id}/reading.json``）；版本不符 409。

        字段级合并：body 出现的键更新、缺席的保留——整覆写会让「单栏
        保存」抹掉对侧位置（``positions`` 再按侧键深合并，en/zh 互补）。
        """
        _get_task(request, task_id)
        files = store.files(task_id)  # 一次取——串发 file_record 是 mini-N+1
        body = await _read_body(request)
        want = str(body.get("document_version") or "")
        if want:
            # arxiv_html 无 zh_pdf——回落 zh_html（dom 路也吃防旧版位置回灌）
            rec = files.get("zh_pdf") or files.get("zh_html")
            cur = str((rec or {}).get("sha256") or "")
            if cur and want != cur:
                return _json_error(409, "document_version mismatch", "version_mismatch")
        keep = {
            k: body[k]
            for k in ("positions", "active", "mode", "zoom", "sync", "swapped")
            if k in body
        }

        def _persist() -> None:
            tdir = root / "tasks" / task_id
            tdir.mkdir(parents=True, exist_ok=True)
            path = tdir / "reading.json"
            existing: dict[str, Any] = {}
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = None
            if isinstance(raw, dict):
                existing = raw
            merged = {**existing, **keep}
            old_pos = existing.get("positions")
            new_pos = keep.get("positions")
            if isinstance(old_pos, dict) and isinstance(new_pos, dict):
                merged["positions"] = {**old_pos, **new_pos}
            atomic_json(path, merged)

        await asyncio.to_thread(_persist)
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
        两个伪字段（出参回显/显式控制）。未识别键不落盘——在响应
        ``ignored`` 字段原样回显：静默丢弃的 200 会让调用方以为写入
        生效（前端可凭 ``ignored`` 出告警）。
        """
        _settings_write_gate()
        body = await _read_body(request)
        allowed = set(SettingsStore.FIELDS) | {"clear_api_key", "has_api_key"}
        ignored = sorted(set(body) - allowed)
        for k in ignored:
            body.pop(k)
        try:
            # save 内含同步 httpx 探活（timeout 不盖 DNS getaddrinfo，
            # 死 DNS 网络可卡数十秒）——to_thread 卸载防冻结事件循环；
            # merge 串行语义由 SettingsStore._save_lock 接管
            await asyncio.to_thread(settings_store.save, body)
        except (TypeError, ValueError) as e:
            # 字段值类型错（concurrency 收 None/dict/list 时 int() TypeError）
            # 与校验错同归 400——非数值输入是客户端错误非服务端故障
            return _json_error(400, str(e), "invalid_request")
        resp = settings_store.public()
        if ignored:
            resp["ignored"] = ignored
        return JSONResponse(resp)

    @app.post("/api/settings/test")
    async def settings_test(request: Request) -> Response:
        """探活配置端点：body 可带覆盖值；错误信息先过 scrub。"""
        _settings_write_gate()
        body = await _read_body(request)
        if body.get("base_url") and not body.get("api_key"):
            # 跨槽组合即已存 key 被打向任意出站地址的 exfil oracle——
            # 与 settings.save 的「新槽按新 base_url 查 key」同设计。
            return _json_error(400, "覆盖 base_url 须同给 api_key", "invalid_request")
        cur = settings_store.load()
        base_url = str(body.get("base_url") or cur["base_url"])
        api_key = str(body.get("api_key") or cur["api_key"])
        model = str(body.get("model") or cur["model"])
        try:
            base_url = validate_base_url(base_url)
        except ValueError as e:
            return _json_error(400, str(e), "invalid_request")
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
