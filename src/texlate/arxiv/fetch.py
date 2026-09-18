r"""在线获取：HEAD 预检 → GET e-print → 钉版缓存编排（docs/06 §1/§4）。

- ``HEAD /src/{id}[vN]``：``content-disposition`` 文件名给出
  resolved_version + 打包格式（``arXiv-{id}v{N}.tar.gz|.gz|.pdf``），
  ``content-length`` 上限检查（拒 >150MB），``etag`` 供重验证。
- GET 带 ``If-None-Match``/``If-Modified-Since`` → 304 免下载。
- 退避：429/406/5xx 重试 3 次 +10s/+30s/+90s（±20% jitter）；
  ``Retry-After`` 有则从其值；404 不重试记 ``not_found``。
- 故障转移：export.arxiv.org 是全站镜像、第二下载桶——某 host 被 park
  时自动切另一桶。

WAF 备注（build_corpus.py 实测）：``Accept-Encoding: identity`` 会触发
arXiv WAF → 406；httpx 默认 ``gzip, deflate[, br]`` 安全，不要改回
identity。本地代理出口 IP 偶发被 WAF → /src/ 分钟级 406 窗，属瞬时。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Self

import httpx

from texlate import __version__
from texlate.arxiv.cache import CacheEntry, CacheError, SourceCache
from texlate.arxiv.locate import LocateResult, locate
from texlate.arxiv.ratelimit import (
    BudgetExhaustedError,
    ParkedError,
    RateLimiter,
    jitter,
)
from texlate.arxiv.sniff import BlobKind, SniffError, SniffResult, sniff
from texlate.arxiv.unpack import (
    UnpackError,
    UnpackResult,
    unpack_sniffed,
    write_manifest,
)

if TYPE_CHECKING:
    from collections.abc import Callable

ARXIV_HOST: Final = "arxiv.org"
EXPORT_HOST: Final = "export.arxiv.org"
DEFAULT_HOSTS: Final = (ARXIV_HOST, EXPORT_HOST)
DEFAULT_UA: Final = (
    f"texlate/{__version__} (+https://github.com/wncfht/texlate; "
    "mailto:research@texlate.dev)"
)
#: 包体上限（docs/06 §1.2：拒 >150MB）
DL_CAP: Final = 150 * 1024 * 1024
#: 重试间隔表（docs/06 §1.3：+10s → +30s → +90s，±20% jitter）
RETRY_DELAYS: Final = (10.0, 30.0, 90.0)
#: Retry-After 可兑现上限（5min）：高于退避表上限 90s×jitter、远低于断路器
#: park 档（30min 起）。超出视同不可兑现与 inf 同归终态——不钳短硬等，
#: 免得真去 sleep 数天级的有限巨值（1e6s ≈ 11.5 天）。
MAX_RETRY_AFTER_S: Final = 300.0
#: 命中瞬时类的状态码（429 限流 / 406 IP 配额窗 / 5xx）
TRANSIENT_STATUS: Final = frozenset(
    {
        HTTPStatus.NOT_ACCEPTABLE,  # 406 IP 配额窗
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    }
)


class FetchStatus(StrEnum):
    """单次 GET 的线缆结果。"""

    OK = "ok"
    NOT_MODIFIED = "not_modified"
    NOT_FOUND = "not_found"
    TOO_LARGE = "too_large"
    PARKED = "parked"
    ERROR = "error"


class AcquireStatus(StrEnum):
    """端到端取源结果（对齐 docs/06 §4.2 状态机失败终态）。"""

    OK = "ok"
    HIT = "cache_hit"
    NOT_FOUND = "not_found"
    PDF_ONLY = "pdf_only"
    UNKNOWN_FORMAT = "unknown_format"
    UNPACK_ERROR = "unpack_error"
    TOO_LARGE = "too_large"
    PARKED = "parked"
    BUDGET = "budget_exhausted"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class HeadInfo:
    """``HEAD /src/{id}`` 预检结果：resolved 版本 + 格式提示 + etag + 大小。"""

    http_status: int
    url: str
    cd_filename: str = ""
    resolved_version: int | None = None
    kind_hint: str = ""  # "tar.gz" | "gz" | "pdf" | ""
    etag: str = ""
    last_modified: str = ""
    content_length: int | None = None
    too_large: bool = False


@dataclass(slots=True)
class SrcResult:
    """GET e-print 结果。"""

    status: FetchStatus
    head: HeadInfo
    body: bytes | None = None
    sniffed: SniffResult | None = None
    attempts: int = 1
    detail: str = ""


@dataclass(slots=True)
class AcquireResult:
    """acquire_source 结果：缓存条目 + 过程信息。"""

    status: AcquireStatus
    arxiv_id: str
    resolved_version: int | None = None
    entry: CacheEntry | None = None
    head: HeadInfo | None = None
    warnings: list[str] = field(default_factory=list)
    detail: str = ""


_ID_URL_RE: Final = re.compile(
    r"^(?:(?:https?://)?(?:[\w.-]+\.)?arxiv\.org/(?:abs|pdf|src|e-print|html|format)/+|"
    r"arxiv\s*:\s*)",
    re.IGNORECASE,
)
_VER_RE: Final = re.compile(r"^(?P<base>.+?)[vV](?P<ver>\d{1,3})$", re.ASCII)
_NEW_ID_RE: Final = re.compile(r"^\d{4}\.\d{4,5}$", re.ASCII)
_OLD_ID_RE: Final = re.compile(r"^[a-zA-Z-]+(?:\.[A-Z][a-zA-Z]+)?/\d{7}$", re.ASCII)
_CD_FN_RE: Final = re.compile(r'filename="?([^";]+)')
_CD_VER_RE: Final = re.compile(
    r"[vV](\d+)\.(tar\.gz|gz|pdf)$", re.IGNORECASE | re.ASCII
)


def normalize_arxiv_id(raw: str) -> tuple[str, int | None]:
    """``1412.6980``/``1412.6980v3``/``arXiv:hep-th/9901001``/abs URL → (id, ver)。

    返回的 base id 不带版本后缀；ver 为 None 表示未钉版。
    """
    s = _ID_URL_RE.sub("", raw.strip())
    s = s.split("?")[0].split("#")[0].strip("/")
    s = re.sub(r"\.pdf$", "", s, flags=re.IGNORECASE)
    m = _VER_RE.match(s)
    if (
        m
        and int(m.group("ver")) >= 1  # v0/v00 非合法版本——落非法 id 统一拒
        and (_NEW_ID_RE.match(m.group("base")) or _OLD_ID_RE.match(m.group("base")))
    ):
        return m.group("base"), int(m.group("ver"))
    return s, None


def valid_id(base: str) -> bool:
    """校验 base 为合法 arXiv id 形（新 ``YYMM.NNNNN`` / 旧 ``archive/NNNNNNN``）。

    ``a/../b`` 之类经 URL 归一化仍能拿到远端 200，但会把另一篇的内容写进
    错误的缓存键（碰撞污染），甚至借 ``..`` 逃逸出缓存根——取源前必须拒。
    """
    return bool(_NEW_ID_RE.match(base) or _OLD_ID_RE.match(base))


# TODO(refactor-sweep): drop alias after cli/app split lands——cli.py/cli.thin/  # noqa: TD003, FIX002
# worker.html 仍 import 私名旧称。
_valid_id = valid_id


def _cd_filename(headers: httpx.Headers) -> str:
    m = _CD_FN_RE.search(headers.get("content-disposition", ""))
    return m.group(1) if m else ""


def _safe_int(digits: str) -> int | None:
    """数字串 → int；``int()`` 不可解析的 wire 异常（位数超限/unicode 数字）归 None。"""
    try:
        return int(digits)
    except ValueError:
        return None


def _parse_head(resp: httpx.Response, url: str, pinned: int | None) -> HeadInfo:
    cd = _cd_filename(resp.headers)
    ver: int | None = pinned
    hint = ""
    m = _CD_VER_RE.search(cd)
    if m:
        parsed = _safe_int(m.group(1))
        ver = parsed if parsed is not None else pinned
        hint = m.group(2).lower()
    elif cd.lower().endswith(".pdf"):
        hint = "pdf"
    cl = resp.headers.get("content-length")
    content_length = _safe_int(cl) if cl and cl.isdigit() else None
    return HeadInfo(
        http_status=resp.status_code,
        url=url,
        cd_filename=cd,
        resolved_version=ver,
        kind_hint=hint,
        etag=resp.headers.get("etag", ""),
        last_modified=resp.headers.get("last-modified", ""),
        content_length=content_length,
        too_large=content_length is not None and content_length > DL_CAP,
    )


def _src_url(host: str, arxiv_id: str, version: int | None) -> str:
    suffix = f"v{version}" if version else ""
    return f"https://{host}/src/{arxiv_id}{suffix}"


def _retry_delay(url: str, attempt: int, resp: httpx.Response | None) -> float:
    delay = RETRY_DELAYS[attempt - 1] * jitter(f"{url}#{attempt}")
    ra = resp.headers.get("retry-after") if resp is not None else None
    if ra:
        with contextlib.suppress(ValueError):
            secs = float(ra)
            if secs > MAX_RETRY_AFTER_S:
                # 有限但不可兑现（sleep 会真等）——与 inf 同归终态；
                # nan 比较恒 False → 仍走 max(delay, nan)=delay 回落语义
                return math.inf
            delay = max(delay, secs)
    return delay


class Fetcher:
    """带限速纪律的 arXiv 客户端。所有请求过 limiter（pacing+断路器+预算）。"""

    def __init__(
        self,
        limiter: RateLimiter | None = None,
        *,
        client: httpx.Client | None = None,
        hosts: tuple[str, ...] = DEFAULT_HOSTS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """注入 limiter/client（测试用 MockTransport）与重试 sleep。"""
        self.limiter = limiter or RateLimiter()
        self.hosts = hosts
        self._sleep = sleep
        self.client = client or httpx.Client(
            headers={"User-Agent": DEFAULT_UA, "Accept": "*/*"},
            timeout=httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=10.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        )

    def close(self) -> None:
        """关内建 ``httpx.Client`` 连接池（幂等——重复调用安全）。"""
        self.client.close()

    def __enter__(self) -> Self:
        """进上下文返回自身——``with Fetcher() as f`` 出块自动 ``close()``。"""
        return self

    def __exit__(self, *_exc: object) -> None:
        """出上下文关连接池。"""
        self.close()

    # ---- 底层 ----

    def _request_once(
        self, method: str, url: str, headers: dict[str, str]
    ) -> httpx.Response:
        self.limiter.acquire(url)
        resp = self.client.request(method, url, headers=headers)
        self.limiter.report(url, resp.status_code)
        return resp

    def _request(
        self, method: str, url: str, headers: dict[str, str]
    ) -> httpx.Response:
        """单 URL 请求 + 退避重试。Parked/Budget 直接上抛（交上层切 host）。

        只重试传输层瞬时失败（TransportError/OSError）；DecodingError/
        TooManyRedirects 等确定性 RequestError 立即上抛——重试无意义且
        白烧日预算与退避时间。
        """
        last_exc: Exception | None = None
        last_resp: httpx.Response | None = None
        for attempt in range(len(RETRY_DELAYS) + 1):
            if attempt:
                delay = _retry_delay(url, attempt, last_resp)
                if not math.isfinite(delay):
                    # Retry-After 要求不可兑现的等待（inf）——重试无意义，
                    # 归最后响应为终态（429 → 上层 ERROR/PARKED 分类）
                    break
                self._sleep(delay)
            try:
                resp = self._request_once(method, url, headers)
            except (httpx.TransportError, OSError) as e:
                last_exc = e
                last_resp = None
                continue
            if resp.status_code not in TRANSIENT_STATUS:
                return resp
            last_resp = resp
            last_exc = None
        if last_resp is not None:
            return last_resp
        msg = f"transport failed after retries: {last_exc}"
        raise httpx.TransportError(msg) from last_exc

    def _request_get_body(
        self, url: str, headers: dict[str, str]
    ) -> tuple[httpx.Response, bytes]:
        """流式 GET + 收 body（``DL_CAP``+1B 即断）。退避/限速纪律同 ``_request``。

        ``client.stream`` 只收 header 后逐 chunk 累计——恶意超大响应不再
        ``resp.content`` 全量进内存后才查闸。返回的 ``resp`` 已出 stream
        上下文（流已关），status/headers/url 仍可读，body 不再可读；
        ``body`` 截断在 ``DL_CAP+1`` 处由上层判 ``TOO_LARGE``。非 200 或
        瞬时重试耗尽的 body 归 ``b""``（上层只按 status 裁决）。
        """
        last_exc: Exception | None = None
        last_resp: httpx.Response | None = None
        for attempt in range(len(RETRY_DELAYS) + 1):
            if attempt:
                delay = _retry_delay(url, attempt, last_resp)
                if not math.isfinite(delay):
                    break
                self._sleep(delay)
            try:
                self.limiter.acquire(url)
                with self.client.stream("GET", url, headers=headers) as resp:
                    self.limiter.report(url, resp.status_code)
                    if resp.status_code in TRANSIENT_STATUS:
                        last_exc, last_resp = None, resp
                        continue
                    if resp.status_code != HTTPStatus.OK:
                        return resp, b""
                    return resp, _read_capped(resp)
            except (httpx.TransportError, OSError) as e:
                last_exc, last_resp = e, None
        if last_resp is not None:
            return last_resp, b""
        msg = f"transport failed after retries: {last_exc}"
        raise httpx.TransportError(msg) from last_exc

    def _across_hosts[T](self, fn: Callable[[str], T]) -> T:
        """按 hosts 序尝试，跳过被 park 的 host；全 park 抛首个 ParkedError。"""
        first_park: ParkedError | None = None
        last_err: Exception | None = None
        for host in self.hosts:
            try:
                return fn(host)
            except ParkedError as e:
                if first_park is None:
                    first_park = e
            except (httpx.RequestError, OSError) as e:
                last_err = e
        if last_err is not None and first_park is None:
            raise last_err
        if first_park is not None:
            raise first_park
        msg = f"all hosts failed: {last_err}"
        raise httpx.TransportError(msg)

    # ---- 对外 ----

    def head_src(self, arxiv_id: str, version: int | None = None) -> HeadInfo:
        """HEAD 预检（一次请求 = hasSrc + 版本 + 三态格式预检）。"""
        base, pin = normalize_arxiv_id(arxiv_id)
        ver = version if version is not None else pin
        if not valid_id(base) or (ver is not None and ver < 1):
            msg = f"bad arxiv id: {arxiv_id!r}"
            raise ValueError(msg)
        resp = self._across_hosts(
            lambda host: self._request("HEAD", _src_url(host, base, ver), {})
        )
        return _parse_head(resp, str(resp.url), ver)

    def get_url(
        self, url: str, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        """GET 绝对 URL（同一限速/退避纪律）——export api / oai 元数据端点用。"""
        return self._request("GET", url, headers or {})

    def head_path(self, path: str) -> httpx.Response:
        """HEAD 同 path 按 ``hosts`` 序跨镜像尝试——/html/、/pdf/ 降级探测用。"""
        return self._across_hosts(
            lambda host: self._request("HEAD", f"https://{host}{path}", {})
        )

    def get_path(self, path: str) -> httpx.Response:
        """GET 同 path 按 ``hosts`` 序跨镜像尝试——/html/ 降级链取页用。"""
        return self._across_hosts(
            lambda host: self._request("GET", f"https://{host}{path}", {})
        )

    def get_src(
        self,
        arxiv_id: str,
        version: int | None = None,
        *,
        head: HeadInfo | None = None,
        etag: str = "",
        last_modified: str = "",
    ) -> SrcResult:
        """GET e-print：先 HEAD（可复用传入的），再带条件头 GET，魔数判别。"""
        base, pin = normalize_arxiv_id(arxiv_id)
        ver = version if version is not None else pin
        if not valid_id(base) or (ver is not None and ver < 1):
            msg = f"bad arxiv id: {arxiv_id!r}"
            raise ValueError(msg)
        if head is None:
            head = self.head_src(base, ver)
        early = _head_gate(head)
        if early is not None:
            return early
        cond: dict[str, str] = {}
        if etag:
            cond["If-None-Match"] = etag
        if last_modified:
            cond["If-Modified-Since"] = last_modified
        try:
            resp, body = self._across_hosts(
                lambda host: self._request_get_body(_src_url(host, base, ver), cond)
            )
        except ParkedError as e:
            return SrcResult(FetchStatus.PARKED, head, detail=str(e))
        except (httpx.RequestError, OSError) as e:
            return SrcResult(FetchStatus.ERROR, head, detail=str(e))
        return _body_result(resp, head, body)


def _head_gate(head: HeadInfo) -> SrcResult | None:
    """HEAD 裁决：404/异常/超限 → 提前结束；None = 放行 GET。"""
    if head.http_status == HTTPStatus.NOT_FOUND:
        return SrcResult(FetchStatus.NOT_FOUND, head)
    if head.http_status >= HTTPStatus.BAD_REQUEST:
        return SrcResult(FetchStatus.ERROR, head, detail=f"head:{head.http_status}")
    if head.too_large:
        return SrcResult(FetchStatus.TOO_LARGE, head)
    return None


def _read_capped(resp: httpx.Response) -> bytes:
    """流式收 body，``DL_CAP``+1B 即断——恶意超大响应不整量进内存。"""
    buf = bytearray()
    for chunk in resp.iter_bytes(chunk_size=65536):
        buf += chunk
        if len(buf) > DL_CAP:
            return bytes(buf[: DL_CAP + 1])
    return bytes(buf)


def _body_result(resp: httpx.Response, head: HeadInfo, body: bytes) -> SrcResult:
    """GET 响应 → SrcResult（304/404/200 + 魔数判别）。body 已截到 cap+1。"""
    early = {
        HTTPStatus.NOT_MODIFIED: FetchStatus.NOT_MODIFIED,
        HTTPStatus.NOT_FOUND: FetchStatus.NOT_FOUND,
    }.get(resp.status_code)
    if early is not None:
        return SrcResult(early, head)
    if resp.status_code != HTTPStatus.OK:
        return SrcResult(FetchStatus.ERROR, head, detail=f"get:{resp.status_code}")
    if len(body) > DL_CAP:
        return SrcResult(FetchStatus.TOO_LARGE, head)
    refreshed = _refresh_head(resp, head)
    if refreshed is None:
        return SrcResult(
            FetchStatus.ERROR, head, body=body, detail="malformed_cd_version"
        )
    head = refreshed
    try:
        sniffed = sniff(body)
    except SniffError as e:
        return SrcResult(FetchStatus.ERROR, head, body=body, detail=str(e))
    return SrcResult(FetchStatus.OK, head, body=body, sniffed=sniffed)


def _refresh_head(resp: httpx.Response, head: HeadInfo) -> HeadInfo | None:
    """GET 的 cd/etag 比 HEAD 新（两请求间可能发了新版）——以 GET 为准。

    cd 文件名带版本标记但版本不可解析 → None（malformed wire 数据，不可
    盲目沿用 HEAD 版本钉入缓存，上层归 ERROR）。
    """
    cd = _cd_filename(resp.headers)
    m = _CD_VER_RE.search(cd)
    new_ver = head.resolved_version
    if m:
        new_ver = _safe_int(m.group(1))
        if new_ver is None:
            return None
    return replace(
        head,
        cd_filename=cd or head.cd_filename,
        resolved_version=new_ver,
        etag=resp.headers.get("etag", head.etag),
        last_modified=resp.headers.get("last-modified", head.last_modified),
    )


def _raw_filename(kind: BlobKind) -> str:
    return {
        BlobKind.TAR: "raw.tar.gz",
        BlobKind.SINGLE: "raw.gz",
        BlobKind.PDF: "raw.pdf",
        BlobKind.UNKNOWN: "raw.bin",
    }[kind]


def _locate_meta(res: LocateResult | None) -> dict | None:
    if res is None:
        return None
    return {
        "main": res.main,
        "kind": str(res.kind),
        "candidates": res.candidates,
        "independent_roots": res.independent_roots,
        "multi_doc": res.multi_doc,
        "pdf_wrapper": res.pdf_wrapper,
        "order": res.order,
        "edges": res.edges,  # input 解析图——locate/flatten 对拍调试要用
        "bibliographies": res.bibliographies,
        "dead_files": res.dead_files,
        "unresolved": [
            {"command": r.command, "arg": r.arg, "source": r.source}
            for r in res.unresolved
        ],
        "warnings": res.warnings,
    }


#: 缓存终态透传集——这些条目命中 etag 时不伪装成 cache_hit（无 extracted/）
_HIT_PASSTHROUGH: Final = frozenset(
    {AcquireStatus.PDF_ONLY.value, AcquireStatus.UNKNOWN_FORMAT.value}
)


def _hit_status(cached: CacheEntry) -> AcquireStatus:
    """命中时的状态映射：pdf_only/unknown 条目如实透传，否则 cache_hit。"""
    stored = str(cached.meta.get("status") or "")
    return AcquireStatus(stored) if stored in _HIT_PASSTHROUGH else AcquireStatus.HIT


def _stale_warnings(fetcher: Fetcher, base: str, hit_ver: int) -> list[str]:
    """§1.4 stale 探测：feed 宣告最新版 > 命中版 → 提示新版（不自动升级）。

    best-effort——``resolve_version``（Atom→OAI 链）把一切失败归一成
    None，不挡命中；离线臂零网络不走这里。
    """
    # 鸭子型 fetcher（测试 fake）无 get_url → 无 feed 臂可探，静默跳过
    if not hasattr(fetcher, "get_url"):
        return []
    # meta 反向依赖本模块（Fetcher/normalize_arxiv_id）——延迟导入破环
    from texlate.arxiv.meta import resolve_version  # noqa: PLC0415

    latest = resolve_version(base, fetcher=fetcher)
    if latest is not None and latest > hit_ver:
        return [f"stale:v{latest} available"]
    return []


def _hit_result(
    fetcher: Fetcher, base: str, ver: int, cached: CacheEntry, head: HeadInfo
) -> AcquireResult:
    """缓存命中结果：终态透传（``_hit_status``）+ stale 新版提示。"""
    return AcquireResult(
        _hit_status(cached),
        base,
        ver,
        cached,
        head,
        warnings=_stale_warnings(fetcher, base, ver),
    )


def _head_phase(
    base: str, ver_req: int | None, fetcher: Fetcher, cache: SourceCache
) -> tuple[HeadInfo | AcquireResult, CacheEntry | None]:
    """HEAD + 缓存 etag 比对。返回 (head, cached) 或短路 AcquireResult。"""
    err: AcquireResult | None = None
    head: HeadInfo | None = None
    try:
        head = fetcher.head_src(base, ver_req)
    except ParkedError as e:
        err = AcquireResult(AcquireStatus.PARKED, base, detail=str(e))
    except BudgetExhaustedError as e:
        err = AcquireResult(AcquireStatus.BUDGET, base, detail=str(e))
    except (httpx.RequestError, OSError) as e:
        err = AcquireResult(AcquireStatus.ERROR, base, detail=f"head:{e}")
    if err is not None or head is None:
        return (err or AcquireResult(AcquireStatus.ERROR, base, detail="head")), None
    gate = _head_gate(head)
    if gate is not None:
        status = {
            FetchStatus.NOT_FOUND: AcquireStatus.NOT_FOUND,
            FetchStatus.TOO_LARGE: AcquireStatus.TOO_LARGE,
        }.get(gate.status, AcquireStatus.ERROR)
        return AcquireResult(status, base, head=head, detail=gate.detail), None
    ver = head.resolved_version or ver_req
    if ver is None:
        return (
            AcquireResult(
                AcquireStatus.ERROR, base, head=head, detail="unresolved_version"
            ),
            None,
        )
    cached = cache.get(base, ver)
    if cached is None and cache.entry_dir(base, ver).exists():
        # 条目目录在但 meta 不可读——缓存损坏不静默重下（烧日预算），归 error 待清理
        return (
            AcquireResult(AcquireStatus.ERROR, base, head=head, detail="corrupt_cache"),
            None,
        )
    if cached is not None and head.etag and cached.etag == head.etag:
        return _hit_result(fetcher, base, ver, cached, head), cached
    return head, cached


@dataclass(frozen=True, slots=True)
class _Ids:
    """一次取源的标识集合（base id + 请求原文 + 钉版 + resolved）。"""

    base: str
    requested: str
    ver_req: int | None
    ver: int


def _get_phase(
    ids: _Ids, head: HeadInfo, cached: CacheEntry | None, fetcher: Fetcher
) -> SrcResult | AcquireResult:
    """GET e-print；非 OK 映射成 AcquireResult 短路。"""
    try:
        res = fetcher.get_src(
            ids.base,
            ids.ver,
            head=head,
            etag=cached.etag if cached else "",
            last_modified=str(cached.meta.get("last_modified") or "") if cached else "",
        )
    except (ParkedError, BudgetExhaustedError) as e:
        st = (
            AcquireStatus.PARKED if isinstance(e, ParkedError) else AcquireStatus.BUDGET
        )
        return AcquireResult(st, ids.base, ids.ver, head=head, detail=str(e))
    if res.status is FetchStatus.NOT_MODIFIED and cached is not None:
        return _hit_result(fetcher, ids.base, ids.ver, cached, head)
    if res.status is FetchStatus.OK:
        return res
    st = {
        FetchStatus.NOT_FOUND: AcquireStatus.NOT_FOUND,
        FetchStatus.TOO_LARGE: AcquireStatus.TOO_LARGE,
        FetchStatus.PARKED: AcquireStatus.PARKED,
    }.get(res.status, AcquireStatus.ERROR)
    return AcquireResult(st, ids.base, ids.ver, head=head, detail=res.detail)


_STATUS_MAP: Final = {
    BlobKind.TAR: AcquireStatus.OK,
    BlobKind.SINGLE: AcquireStatus.OK,
    BlobKind.PDF: AcquireStatus.PDF_ONLY,
    BlobKind.UNKNOWN: AcquireStatus.UNKNOWN_FORMAT,
}


def _commit_phase(
    ids: _Ids, res: SrcResult, head: HeadInfo, cache: SourceCache
) -> AcquireResult:
    """Staging 落盘：raw + unpack + manifest + locate + meta.json + 原子换入。"""
    s = res.sniffed
    if s is None or res.body is None:
        return AcquireResult(
            AcquireStatus.ERROR, ids.base, ids.ver, head=head, detail="missing sniff"
        )
    if s.oversized:
        return AcquireResult(
            AcquireStatus.TOO_LARGE,
            ids.base,
            ids.ver,
            head=head,
            detail=f"inflated_too_large:{s.inflated_size}",
        )
    staging = cache.stage()
    warnings: list[str] = []
    loc_res: LocateResult | None = None
    up: UnpackResult | None = None
    try:
        raw_name = _raw_filename(s.kind)
        (staging / raw_name).write_bytes(res.body)
        if s.kind in (BlobKind.TAR, BlobKind.SINGLE):
            ext_dir = staging / "extracted"
            ext_dir.mkdir(parents=True, exist_ok=True)
            stem = head.cd_filename or ids.base.replace("/", "")
            up = unpack_sniffed(s, ext_dir, stem_hint=stem)
            write_manifest(up, staging)
            warnings.extend(up.warnings)
            loc_res = locate(ext_dir, arxiv_id=ids.base)
            warnings.extend(loc_res.warnings)
    except (UnpackError, OSError, ValueError) as e:
        SourceCache.cleanup(staging)
        return AcquireResult(
            AcquireStatus.UNPACK_ERROR, ids.base, ids.ver, head=head, detail=str(e)
        )
    acq_status = _STATUS_MAP[s.kind]
    meta = {
        "arxiv_id": ids.base,
        "requested_id": ids.requested,
        "requested_version": ids.ver_req,
        "resolved_version": ids.ver,
        "status": acq_status.value,
        "cd_filename": head.cd_filename,
        "etag": head.etag,
        "last_modified": head.last_modified,
        "format": s.kind.value,
        "raw_file": raw_name,
        "raw_sha256": hashlib.sha256(res.body).hexdigest(),
        "raw_size": s.raw_size,
        "n_files": up.n_files if up else 0,
        "tex_files": up.tex_files if up else 0,
        "extracted_bytes": up.extracted_bytes if up else 0,
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "warnings": warnings,
        "locate": _locate_meta(loc_res),
    }
    try:
        (staging / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        entry = cache.commit(staging, ids.base, ids.ver)
    except (OSError, KeyError, TypeError, ValueError, CacheError) as e:
        SourceCache.cleanup(staging)
        return AcquireResult(
            AcquireStatus.ERROR, ids.base, ids.ver, head=head, detail=f"commit:{e}"
        )
    return AcquireResult(acq_status, ids.base, ids.ver, entry, head, warnings)


def _offline_phase(base: str, ver_req: int | None, cache: SourceCache) -> AcquireResult:
    """离线旁路：零网络——钉版精确查 ``{id}v{ver}``、未钉版取最高缓存版。

    缓存终态透传同在线路径（pdf_only/unknown 不伪装 hit）；无缓存或钉的
    版本未缓存 → ``error/offline_no_cache``，不静默换版本、不降级上网。
    """
    entry = cache.get(base, ver_req) if ver_req is not None else cache.get_latest(base)
    if entry is None:
        want = f"{base}v{ver_req}" if ver_req is not None else base
        return AcquireResult(
            AcquireStatus.ERROR, base, detail=f"offline_no_cache:{want}"
        )
    return AcquireResult(
        _hit_status(entry), base, entry.resolved_version, entry, detail="offline"
    )


def acquire_source(
    arxiv_id: str,
    *,
    fetcher: Fetcher,
    cache: SourceCache,
    version: int | None = None,
    offline: bool = False,
) -> AcquireResult:
    """端到端取源：HEAD → 缓存命中/重验证 → GET → sniff → unpack → locate → 钉版落盘。

    ``offline=True`` 时完全不触碰 fetcher（HEAD/GET 都不发）：命中本地
    钉版缓存直接返回，无缓存报 ``offline_no_cache``。
    """
    base, pin = normalize_arxiv_id(arxiv_id)
    ver_req = version if version is not None else pin
    bad = (
        f"bad_id:{base!r}"
        if not valid_id(base)
        else f"bad_version:{ver_req}"
        if ver_req is not None and ver_req < 1
        else None
    )
    if bad is not None:
        return AcquireResult(AcquireStatus.ERROR, base, detail=bad)
    if offline:
        return _offline_phase(base, ver_req, cache)
    phased = _head_phase(base, ver_req, fetcher, cache)
    if isinstance(phased[0], AcquireResult):
        return phased[0]
    head: HeadInfo = phased[0]
    ver = head.resolved_version or ver_req
    if ver is None:  # _head_phase 已拒；静态收窄用
        return AcquireResult(
            AcquireStatus.ERROR, base, head=head, detail="unresolved_version"
        )
    ids = _Ids(base=base, requested=arxiv_id, ver_req=ver_req, ver=ver)
    res = _get_phase(ids, head, phased[1], fetcher)
    if isinstance(res, AcquireResult):
        return res
    get_ver = res.head.resolved_version
    if get_ver is not None and get_ver != ids.ver:
        ids = replace(ids, ver=get_ver)
    return _commit_phase(ids, res, res.head, cache)
