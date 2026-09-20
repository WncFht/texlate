"""HTTP 请求层：multipart 流式落盘、body 闸、同源/host 判定、统一错误面。

``server/app.py`` 拆出的横切辅助件——不持 app 状态（Store/runner 经
``routers/deps.py`` 的 ``AppDeps`` 注入），常量与纯函数供 ``create_app``
中间件与 ``server/routers/`` 各域叶共用。

注意：本模块只在 server extra（fastapi）存在时才会被导入——
``texlate.server`` 包本体保持轻依赖。
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

try:
    import python_multipart as _pymp
except ModuleNotFoundError:  # pragma: no cover -- 旧式包名回落（同 starlette）
    import multipart as _pymp  # type: ignore[no-redef]

from texlate.compile.engine import ENGINE_NAMES
from texlate.server.settings import UPLOAD_CAP, server_mode
from texlate.textutil import utc_now
from texlate.xlat.client import _LOOPBACK_HOSTS

if TYPE_CHECKING:
    from typing import BinaryIO

    from fastapi import Request
    from starlette.types import Message


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
_STARTED_AT = utc_now()


class _ApiError(Exception):
    """携带完整 JSON body 的 API 错误（409 需带 task_id 等附加字段）。"""

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        """Body 直出为响应体。"""
        self.status = status
        self.body = body
        super().__init__(str(body.get("detail", status)))


def _api_error(
    status: int, detail: str, code: str | None = None, **fields: Any
) -> _ApiError:
    """``raise`` 侧统一错误面——``_json_error`` 的 raise 孪生。

    body 形状同 ``_json_error``：``{"detail": …, "code"?}``；``**fields``
    并入 body 承载附加字段（409 带 ``task_id`` 之类）。
    """
    body: dict[str, Any] = {"detail": detail}
    if code:
        body["code"] = code
    body.update(fields)
    return _ApiError(status, body)


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
        raise _api_error(413, f"upload > {UPLOAD_CAP}B", "upload_too_large")
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
            raise _api_error(413, f"{label} > {cap}B", code)
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
        raise _api_error(413, f"upload > {UPLOAD_CAP}B", "upload_too_large")
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
        raise _api_error(
            400, f"malformed multipart: {e}", "invalid_request"
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
        raise _api_error(
            415, "Content-Type 须为 application/json", "unsupported_media_type"
        )
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError) as e:
        # ValueError 含 JSONDecodeError 与巨 int 字面量（int↔str 上限）；
        # RecursionError 是超深嵌套——不入网即 500
        raise _api_error(400, f"bad json: {e}", "invalid_request") from e
    if not isinstance(data, dict):
        # 非 object JSON（[1]/"x"/null）——静默当 {} 会让 PUT settings 等
        # 端点 200 无操作，调用方无从察觉体被整个丢弃
        raise _api_error(400, "json body 须为 object", "invalid_request")
    return data


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
#: ``engine_for`` 只认两台真机 + auto 路由；单源 ``compile.engine.ENGINE_NAMES``）。
_ENGINE_NAMES = ENGINE_NAMES

#: ``options`` 落库序列化上限——body 闸放到 UPLOAD_CAP 级，options_json
#: 是无 schema 自由 KV，巨型 blob 会原样进 ``tasks.options_json``
#: （每行拖 KB→MB 级垃圾且 ``options()`` 每读全解析）。64KB 远超合法
#: 键集（glossary/main/source/engine/concurrency/idempotency_key…）。
_OPTIONS_JSON_CAP = 65536


def _options_json_checked(options: dict[str, Any]) -> str:
    """``options`` → JSON 串：不可序列化或超 ``_OPTIONS_JSON_CAP`` → 400。"""
    try:
        raw = json.dumps(options, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise _api_error(
            400, f"options 须可 JSON 序列化: {e}", "invalid_request"
        ) from e
    if len(raw.encode()) > _OPTIONS_JSON_CAP:
        raise _api_error(
            400, f"options 序列化超 {_OPTIONS_JSON_CAP}B", "invalid_request"
        )
    return raw


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
        raise _api_error(
            400, f"options.engine ∈ {sorted(_ENGINE_NAMES)}", "invalid_request"
        )
    # 取源闸：eprint（默认，e-print tar 链）| html（ar5iv DOM 链）——
    # 与 arxiv 获取层「取源」同词；值规范化回写，worker 侧恒可读
    if inject_defaults or "source" in options:
        source = str(options.get("source") or "eprint")
        if source not in ("eprint", "html"):
            raise _api_error(400, "options.source ∈ eprint|html", "invalid_request")
        options["source"] = source
    if inject_defaults:
        options.setdefault("auto_glossary", True)
    if "concurrency" in options:
        try:
            options["concurrency"] = max(1, min(16, int(options["concurrency"])))
        except (TypeError, ValueError):
            raise _api_error(
                400, "options.concurrency 须为整数（clamp 1–16）", "invalid_request"
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


def _exposed_bind_warning(host: str) -> str | None:
    """非回环绑定 + local 形态 → 警告文案；否则 ``None``。

    local 形态 API 无鉴权（Host 闸只防 DNS rebinding）——非回环绑定把
    建任务/PUT settings/读产物暴露给整个可达网段。返文案不自带输出：
    两入口各走自己的 stderr 通道（``cli.web`` 用 ``typer.echo``；
    ``__main__`` 无 typer 依赖用 ``print``）。
    """
    if server_mode() == "server" or _loopback_bind(host):
        return None
    return (
        f"警告：--host {host} 非回环绑定，local 形态 API 无鉴权——"
        "可达网段内任何人可建任务/改 settings；多租户部署请用"
        " TEXLATE_MODE=server（X-Texlate-Key 鉴权）"
    )


def _same_origin(request: Request, origin: str) -> bool:
    """``Origin`` 与请求 scheme+Host（含端口）严格一致——同源判定。"""
    o = urlsplit(origin)
    return (
        o.scheme == request.url.scheme
        and o.netloc.lower() == request.headers.get("host", "").lower()
    )


#: 会产出 ``dual.json``（→ reader 可用）的任务 kind。docx/epub 走
#: export 双语插译没有 dual.json——``_accepted`` 对它们不发 reader_url。
_DUAL_JSON_KINDS = frozenset(
    {"arxiv", "share", "upload_tex", "upload_pdf", "arxiv_html"}
)


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
