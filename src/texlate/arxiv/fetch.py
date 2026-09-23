r"""在线获取线缆层：HEAD 预检 → GET e-print（端到端编排在 ``acquire.py``）。

规格 docs/spec/arxiv-source.md：

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
import logging
import math
import os
import re
import time
from dataclasses import dataclass, field, replace
from enum import StrEnum
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Self

import httpx

from texlate import __version__
from texlate.arxiv.ratelimit import ParkedError, RateLimiter, jitter
from texlate.arxiv.sniff import SniffError, SniffResult, sniff

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.arxiv.cache import CacheEntry

log = logging.getLogger(__name__)

ARXIV_HOST: Final = "arxiv.org"
EXPORT_HOST: Final = "export.arxiv.org"
DEFAULT_HOSTS: Final = (ARXIV_HOST, EXPORT_HOST)
DEFAULT_UA: Final = (
    f"texlate/{__version__} (+https://github.com/wncfht/texlate; "
    "mailto:research@texlate.dev)"
)
#: 包体上限（docs/spec/arxiv-source.md：拒 >150MB）
DL_CAP: Final = 150 * 1024 * 1024
#: 重试间隔表（docs/spec/arxiv-source.md：+10s → +30s → +90s，±20% jitter）
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
    """端到端取源结果（对齐 docs/spec/arxiv-source.md 状态机失败终态）。"""

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


#: ``get_src`` 内置 HEAD 臂失败时的占位 HeadInfo——无线缆响应可记，status=0 哨兵
_NO_HEAD: Final = HeadInfo(http_status=0, url="")


# ---------------------------------------------------------------- canon
# 单源归一化（规格 docs 对应 tmp/ux-research-20260922/arxiv-id-canon-spec.md）：
# 剥离序管线化——锚定正则前缀剥（不 urlparse 任意 host，端口/双斜杠/怪
# scheme 结构性拒收），``ar5iv.org``/``alphaxiv.org`` 走显式 host 白名单臂
# （动词限 abs|pdf|html，须带 scheme），LANL 镜像/ADS bibcode/散文形不收。

_VER_RE: Final = re.compile(r"^(?P<base>.+?)[vV](?P<ver>\d{1,3})$", re.ASCII)
_NEW_ID_RE: Final = re.compile(r"^(\d{4})\.(\d{4,5})$", re.ASCII)
_OLD_ID_RE: Final = re.compile(
    r"^([A-Za-z-]+)(?:\.[A-Za-z][A-Za-z-]*)?/(\d{7})$", re.ASCII
)
_CD_FN_RE: Final = re.compile(r'filename="?([^";]+)')
_CD_VER_RE: Final = re.compile(
    r"[vV](\d+)\.(tar\.gz|gz|pdf)$", re.IGNORECASE | re.ASCII
)

#: canon 前缀剥壳表（循环至不动点——``doi.org/`` 后再落 ``10.48550/arXiv.``）。
#: 子域组要求显式 ``.`` 边界（``(?:[\w.-]+\.)?``）——``notarxiv.org`` 寄生域
#: 不得命中；scheme 只认 ``http(s)``，缺 scheme 只放行裸 ``*.arxiv.org``。
_PREFIX_RES: Final = (
    re.compile(
        r"^(?:https?://)?(?:[\w.-]+\.)?arxiv\.org/"
        r"(?:abs|pdf|src|e-print|html|format)/+",
        re.IGNORECASE,
    ),
    re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE),
    re.compile(r"^doi:\s*", re.IGNORECASE),
    re.compile(r"^10\.48550/arXiv\.", re.IGNORECASE),
    re.compile(r"^oai\s*:\s*arxiv\.org\s*:\s*", re.IGNORECASE),
    re.compile(r"^arxiv\s*[:.]\s*", re.IGNORECASE),
)
#: ar5iv/alphaXiv 显式 host 白名单臂：须带 http(s) scheme，动词白名单收窄。
_MIRROR_PREFIX_RE: Final = re.compile(
    r"^https?://(?:[\w.-]+\.)?(?:ar5iv|alphaxiv)\.org/(?:abs|pdf|html)/+",
    re.IGNORECASE,
)
_EXT_RE: Final = re.compile(
    r"\.(?:pdf|ps|eps|dvi|gz|tgz|tar\.gz)$", re.IGNORECASE
)
_TAILNOTE_RE: Final = re.compile(r"\s*\[[^\]]{1,20}\]\s*$", re.ASCII)


class CanonError(ValueError):
    """canon 拒收——``reason`` ∈ bad_shape|bad_month|bad_era|bad_version|unsafe。"""

    def __init__(self, reason: str, raw: str) -> None:
        """原因码入 ``reason`` 属性（服务端 400 detail 派生源）；raw 留原始输入。"""
        self.reason = reason
        super().__init__(f"{reason}: {raw!r}")


@dataclass(frozen=True, slots=True)
class CanonId:
    """canon 规范形：``base``（新 ``YYMM.NNNNN``/旧 ``archive/YYMMNNN`` 裸形）。

    旧形 class 已剥（``math.GT/0309136`` → ``math/0309136``）、archive 已小写化；
    ``version`` 仅用户钉版时非 None（≥1、无导零）。
    """

    base: str
    version: int | None = None
    scheme: str = "new"  # "new" | "old"

    def __str__(self) -> str:
        """渲染 ``base`` 或 ``{base}v{version}``——幂等回喂 canon 得自身。"""
        return f"{self.base}v{self.version}" if self.version else self.base

    def safe(self) -> str:
        """单层存储拼写（``/``→``--``）——``benchlib.safe_id`` 同形。"""
        return self.base.replace("/", "--")


def _old_era(yymm: str) -> bool:
    """YYMM ∈ 旧形时代窗（9107–9912 ∪ 0000–0703，世纪回绕）。"""
    return yymm >= "9107" or yymm <= "0703"


def _canon_strip(raw: str) -> str:
    """剥离管线（绝不抛）。

    空白 → ``--``→``/`` → 前缀循环 → ``?#`` 截断 → 尾 ``/`` → ``[class]``
    尾注/扩展名不动点循环。返回值即「剩件」——版本钉与形校验在 ``canon``
    本体；失败路径把剩件回给 ``normalize_arxiv_id`` 作旧口径 fallback
    （调用方 ``valid_id`` 复核）。
    """
    s = raw.strip()
    # ``--`` 永不可能出现在合法 id（旧 archive 只带单 ``-``）——safe_id
    # 存储拼写回流并进前置步，raw/safe 两形同键。
    s = s.replace("--", "/")
    prev = None
    while prev != s:  # 前缀循环至不动点
        prev = s
        for rx in _PREFIX_RES:
            s = rx.sub("", s)
        s = _MIRROR_PREFIX_RE.sub("", s)
        s = s.strip()
    s = s.split("?", 1)[0].split("#", 1)[0].strip("/").strip()
    prev = None
    while prev != s:  # 尾注/扩展名循环至不动点——``id [cs.CL].pdf`` 两序皆收
        prev = s
        s = _TAILNOTE_RE.sub("", s)  # ``[cs.CL]`` 引用尾注
        s = _EXT_RE.sub("", s)
    return s


def _peel_ver(s: str, orig: str) -> tuple[str, int | None]:
    """``vN`` 钉版剥离——``v0``/``v00`` 判非法不静默去钉（保留旧语义）。"""
    m = _VER_RE.match(s)
    if m is None:
        return s, None
    v = int(m.group("ver"))
    if v < 1:
        raise CanonError(reason="bad_version", raw=orig)
    return m.group("base"), v


def _canon_semantic_gate(yymm: str, orig: str, *, old: bool, strict_era: bool) -> None:
    """MM∈[01,12] + strict_era 时代窗闸（新形须旧时代窗外、旧形反之）。"""
    if not 1 <= int(yymm[2:4]) <= 12:  # noqa: PLR2004 -- 月份上下界自明
        raise CanonError(reason="bad_month", raw=orig)
    if strict_era and old != _old_era(yymm):
        raise CanonError(reason="bad_era", raw=orig)


def canon(raw: str, *, strict_era: bool = True) -> CanonId:
    """任意常见 arXiv 形态 → ``CanonId``；不可识别抛 ``CanonError``。

    ``strict_era``（默认开）：新形 YYMM 须落在旧形时代窗之外
    （``0704``–``9106``），旧形反之——``9912.00001``/``hep-th/0801001``
    这类不可能 id 本地即拒（省一轮远端 404）。
    """
    orig = raw
    s = _canon_strip(raw)
    if ".." in s:
        raise CanonError(reason="unsafe", raw=orig)
    if not s:
        raise CanonError(reason="bad_shape", raw=orig)
    s, version = _peel_ver(s, orig)
    m = _OLD_ID_RE.match(s)
    if m:
        _canon_semantic_gate(m.group(2), orig, old=True, strict_era=strict_era)
        base = f"{m.group(1).lower()}/{m.group(2)}"
        return CanonId(base=base, version=version, scheme="old")
    m = _NEW_ID_RE.match(s)
    if m:
        _canon_semantic_gate(m.group(1), orig, old=False, strict_era=strict_era)
        return CanonId(base=s, version=version, scheme="new")
    raise CanonError(reason="bad_shape", raw=orig)


def try_canon(raw: str, **kw: object) -> CanonId | None:
    """``canon`` 不抛变体——不可识别归 ``None``。"""
    try:
        return canon(raw, **kw)  # type: ignore[arg-type]
    except CanonError:
        return None


def normalize_arxiv_id(raw: str) -> tuple[str, int | None]:
    """``1412.6980``/``1412.6980v3``/``arXiv:hep-th/9901001``/abs URL → (id, ver)。

    薄壳转发 ``canon``：成功 → ``(canon.base, canon.version)``；拒收 →
    ``(剥离剩件, None)``——旧契约「任意输入不抛」保留，剩件恒过不了
    ``valid_id``/下游闸（``canon`` 已拒的串再 canon 必仍拒）。
    """
    try:
        c = canon(raw)
    except CanonError:
        return _canon_strip(raw), None
    return c.base, c.version


def valid_id(base: str) -> bool:
    """校验 base 为 canon 规范形 id（新 ``YYMM.NNNNN`` / 旧 ``archive/NNNNNNN``）。

    语义收窄为「已是规范形」：classful 旧形/``vN`` 钉版串/``--`` 安全拼写
    都是 canon 可收输入但不是合法 base——``canon(x)`` 必须成立且输出
    ``str()`` 回读等于输入。``a/../b`` 之类经 URL 归一化仍能拿到远端 200，
    但会把另一篇的内容写进错误的缓存键（碰撞污染），甚至借 ``..`` 逃逸
    出缓存根——取源前必须拒。
    """
    c = try_canon(base)
    return c is not None and c.version is None and c.base == base


def req_base_ver(arxiv_id: str, version: int | None = None) -> tuple[str, int | None]:
    """归一化 + 钉版合并 + 校验 → ``(base, ver)``；非法 id/版本抛 ``ValueError``。

    ``version`` 实参优先于 id 串内 ``vN`` 钉版；返回 ``ver=None`` 表示未钉版。
    取源/降级各入口共用的 id 前置闸。
    """
    try:
        c = canon(arxiv_id)
    except CanonError as e:
        msg = f"bad arxiv id: {arxiv_id!r} ({e.reason})"
        raise ValueError(msg) from e
    ver = version if version is not None else c.version
    if ver is not None and ver < 1:
        msg = f"bad arxiv id: {arxiv_id!r} (bad_version)"
        raise ValueError(msg)
    return c.base, ver


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


def _make_client(*, trust_env: bool) -> httpx.Client:
    """Fetcher 默认 client 构型；``trust_env=False`` 即绕 env 代理的直连臂。"""
    return httpx.Client(
        headers={"User-Agent": DEFAULT_UA, "Accept": "*/*"},
        timeout=httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=10.0),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        trust_env=trust_env,
    )


def _env_proxy_set() -> bool:
    """Env 有正向代理（https/all 任一）且未被 ``no_proxy=*`` 全豁免。

    粗判——只为「传输层全灭时值得直连兜底」提供开关；host 级 no_proxy
    豁免不精确展开（那种情况直连臂只是白探一次单发，代价有界）。
    """
    if not any(
        os.environ.get(k)
        for k in ("https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY")
    ):
        return False
    noproxy = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
    return "*" not in {p.strip() for p in noproxy.split(",")}


class Fetcher:
    """带限速纪律的 arXiv 客户端。所有请求过 limiter（pacing+ 断路器 + 预算）。"""

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
        self._owns_client = client is None
        self.client = client or _make_client(trust_env=True)
        self._direct_client: httpx.Client | None = None
        self._attempts = len(RETRY_DELAYS) + 1

    def close(self) -> None:
        """关连接池（幂等——重复调用安全）。

        当前安装的 ``self.client`` 一律关——含注入件：注入方即把连接池
        生命周期交给 ``with Fetcher()``/显式 ``close()`` 管；惰性直连臂
        （若开过）同关。
        """
        self.client.close()
        if self._direct_client is not None:
            self._direct_client.close()

    def _open_direct(self) -> httpx.Client | None:
        """惰性直连臂：env 有代理且 client 是内建（注入件不参与）才开。"""
        if self._direct_client is None and self._owns_client and _env_proxy_set():
            self._direct_client = _make_client(trust_env=False)
        return self._direct_client

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

    def _retry[T](
        self,
        url: str,
        label: str,
        fn: Callable[[], tuple[httpx.Response, T | None]],
    ) -> tuple[httpx.Response, T | None]:
        """退避重试驱动：``fn`` 打一发返 ``(resp, 结果)``——结果 ``None``=瞬时续重试。

        只重试传输层瞬时失败（TransportError/OSError）与 ``TRANSIENT_STATUS``
        响应；DecodingError/TooManyRedirects 等确定性 RequestError 立即上抛——
        重试无意义且白烧日预算与退避时间。Parked/Budget 直接上抛（交上层
        切 host）。瞬时耗尽归 ``(last_resp, None)`` 由调用方裁决；纯传输
        失败耗尽抛 ``httpx.TransportError``。``label`` 仅用于重试告警日志。
        """
        last_exc: Exception | None = None
        last_resp: httpx.Response | None = None
        for attempt in range(self._attempts):
            if attempt:
                delay = _retry_delay(url, attempt, last_resp)
                if not math.isfinite(delay):
                    # Retry-After 要求不可兑现的等待（inf）——重试无意义，
                    # 归最后响应为终态（429 → 上层 ERROR/PARKED 分类）
                    break
                why = (
                    f"HTTP {last_resp.status_code}"
                    if last_resp is not None
                    else (str(last_exc) or type(last_exc).__name__)
                )
                log.warning(
                    "%s %s failed (%s) → retry %d/%d in %.0fs",
                    label,
                    url,
                    why,
                    attempt,
                    len(RETRY_DELAYS),
                    delay,
                )
                self._sleep(delay)
            try:
                resp, result = fn()
            except (httpx.TransportError, OSError) as e:
                last_exc = e
                last_resp = None
                continue
            if result is not None:
                return resp, result
            last_resp = resp
            last_exc = None
        if last_resp is not None:
            return last_resp, None
        msg = f"transport failed after retries: {last_exc}"
        raise httpx.TransportError(msg) from last_exc

    def _request(
        self, method: str, url: str, headers: dict[str, str]
    ) -> httpx.Response:
        """单 URL 请求 + 退避重试。Parked/Budget 直接上抛（交上层切 host）。

        只重试传输层瞬时失败（TransportError/OSError）；DecodingError/
        TooManyRedirects 等确定性 RequestError 立即上抛——重试无意义且
        白烧日预算与退避时间。
        """

        def once() -> tuple[httpx.Response, httpx.Response | None]:
            resp = self._request_once(method, url, headers)
            if resp.status_code in TRANSIENT_STATUS:
                return resp, None
            return resp, resp

        resp, _done = self._retry(url, method, once)
        return resp

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

        def once() -> tuple[httpx.Response, bytes | None]:
            self.limiter.acquire(url)
            with self.client.stream("GET", url, headers=headers) as resp:
                self.limiter.report(url, resp.status_code)
                if resp.status_code in TRANSIENT_STATUS:
                    return resp, None
                if resp.status_code != HTTPStatus.OK:
                    return resp, b""
                return resp, _read_capped(resp)

        resp, body = self._retry(url, "GET", once)
        return resp, b"" if body is None else body

    def _across_hosts[T](self, fn: Callable[[str], T]) -> T:
        """按 hosts 序尝试，跳过被 park 的 host；全 park 抛首个 ParkedError。

        全 host 传输层失败且 env 代理在链 → 切 ``trust_env=False`` 直连臂
        单发重探一轮（代理抽风/断流自救；``self.client is direct`` 防重入，
        必走代理的环境最坏损失每 host 一次 connect 超时）。
        """
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
        if (
            last_err is not None
            and first_park is None
            and (direct := self._open_direct()) is not None
            and self.client is not direct
        ):
            log.warning("all hosts transport-failed → direct retry (bypass env proxy)")
            prev_client, prev_attempts = self.client, self._attempts
            self.client, self._attempts = direct, 1
            try:
                result = self._across_hosts(fn)
            except Exception:
                # 直连也不通 → 恢复代理臂，原异常继续上抛
                self.client, self._attempts = prev_client, prev_attempts
                raise
            # 直连探通 → client 粘住余下生命周期（代理臂已证死，head+get 不再各
            # 挨一轮代理重试）；attempts 恢复正常退避
            self._attempts = prev_attempts
            return result
        if last_err is not None and first_park is None:
            raise last_err
        if first_park is not None:
            raise first_park
        msg = f"all hosts failed: {last_err}"
        raise httpx.TransportError(msg)

    # ---- 对外 ----

    def head_src(self, arxiv_id: str, version: int | None = None) -> HeadInfo:
        """HEAD 预检（一次请求 = hasSrc + 版本 + 三态格式预检）。"""
        base, ver = req_base_ver(arxiv_id, version)
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
        """GET e-print：先 HEAD（可复用传入的），再带条件头 GET，魔数判别。

        ``head=None`` 时内置 HEAD 预检——其 park/传输失败与 GET 臂同归
        ``PARKED``/``ERROR``；``BudgetExhaustedError`` 同 GET 臂原样上抛。
        """
        base, ver = req_base_ver(arxiv_id, version)
        if head is None:
            try:
                head = self.head_src(base, ver)
            except ParkedError as e:
                return SrcResult(FetchStatus.PARKED, _NO_HEAD, detail=str(e))
            except (httpx.RequestError, OSError) as e:
                return SrcResult(FetchStatus.ERROR, _NO_HEAD, detail=str(e))
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


def __getattr__(name: str) -> object:
    """``acquire_source`` 惰性回指 ``acquire.py``——本模块引用面不变。

    端到端编排（``_head_phase``/``_get_phase``/``_commit_phase``/缓存命中
    映射）已迁 ``texlate.arxiv.acquire`` 叶；``from texlate.arxiv.fetch
    import acquire_source`` 与各 ``fetch.acquire_source`` 消费点照旧。
    """
    if name == "acquire_source":
        from texlate.arxiv.acquire import acquire_source  # noqa: PLC0415

        return acquire_source
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
