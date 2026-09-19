"""discover 路由：alphaXiv 公共面只读代理（feed/搜索/导读/OG 卡）。

alphaXiv 的 CORS 固定回 ``allow-origin: https://www.alphaxiv.org``——
浏览器侧第三方直连被挡，发现层数据只能由服务端代取（逆向报告
``docs/research/product/2026-09-19-alphaxiv-reverse.md``，端点形状
均实测过）。全部是机会型增强、不进核心管线：feed/search/og 上游失败
归一 502 ``discover_upstream``，前端整块隐藏；overview 链上任一环
404 或目标语言未生成回 ``{"available": false}``，网络/5xx 才 502。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from fastapi import Request, Response

from texlate.server.http import _ApiError

if TYPE_CHECKING:
    import httpx
    from fastapi import FastAPI

    from texlate.server.routers.deps import AppDeps

log = logging.getLogger(__name__)

_AX_API = "https://api.alphaxiv.org"

#: feed 参数白名单（上游 zod 枚举实测）；ForYou 需登录恒 401 不收
_FEED_SORTS = frozenset({"Hot", "Comments", "Views", "Likes", "GitHub", "Recent"})
_FEED_INTERVALS = frozenset({"3 Days", "7 Days", "30 Days", "90 Days", "All time"})

#: arXiv id 形态：新 ``YYMM.NNNNN(vN)``、旧 ``archive(.XX)?/YYMMNNN(vN)``
_ARXIV_ID_RE = re.compile(
    r"(?:\d{4}\.\d{4,6}|[a-zA-Z-]+(?:\.[a-zA-Z]{2})?/\d{7})(?:v\d+)?"
)

_SEARCH_Q_MAX = 200


class _TtlCache[T]:
    """key → (expires_monotonic, value)，容量有界 LRU 头出。"""

    def __init__(self, ttl: float, max_entries: int) -> None:
        """``ttl`` 秒；超 ``max_entries`` 逐最旧键。"""
        self.ttl = ttl
        self.max_entries = max_entries
        self._d: OrderedDict[str, tuple[float, T]] = OrderedDict()

    def get(self, key: str) -> T | None:
        """过期当缺席（顺手摘除）。"""
        hit = self._d.get(key)
        if hit is None:
            return None
        exp, val = hit
        if exp < time.monotonic():
            self._d.pop(key, None)
            return None
        self._d.move_to_end(key)
        return val

    def put(self, key: str, val: T) -> None:
        """写入 + LRU 排序 + 容量逐出。"""
        self._d[key] = (time.monotonic() + self.ttl, val)
        self._d.move_to_end(key)
        while len(self._d) > self.max_entries:
            self._d.popitem(last=False)


#: 进程内 TTL 缓存——feed 10min、搜索 2min、导读 30min、OG 字节 24h。
#: 都是只读公共数据的弱新鲜度面；容量上界防内存账失控。
_feed_cache = _TtlCache[dict[str, Any]](ttl=600, max_entries=64)
_search_cache = _TtlCache[list[dict[str, Any]]](ttl=120, max_entries=256)
_overview_cache = _TtlCache[dict[str, Any]](ttl=1800, max_entries=256)
_og_cache = _TtlCache[bytes](ttl=86400, max_entries=64)

#: 按事件环分桶的 AsyncClient——httpx 连接池绑创建时的 running loop，
#: 跨环复用炸 "attached to a different loop"（worker/_common.py 同款坑）
_clients: dict[int, httpx.AsyncClient] = {}


def _client() -> httpx.AsyncClient:
    """取当前环的共享 client（惰性建）。"""
    import httpx  # noqa: PLC0415 -- 重依赖惰性加载

    key = id(asyncio.get_running_loop())
    cli = _clients.get(key)
    if cli is None:
        cli = httpx.AsyncClient(
            base_url=_AX_API,
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
            headers={"User-Agent": "texlate-discover"},
        )
        _clients[key] = cli
    return cli


async def _ax_get(path: str, params: dict[str, Any] | None = None) -> httpx.Response:
    """上游 GET：网络层失败一律 502 ``discover_upstream``；HTTP 状态留给调用方判定。"""
    import httpx  # noqa: PLC0415 -- 重依赖惰性加载

    try:
        return await _client().get(path, params=params)
    except httpx.HTTPError as e:
        raise _ApiError(
            502,
            {"detail": f"alphaxiv upstream: {e}", "code": "discover_upstream"},
        ) from e


def _check_2xx(resp: httpx.Response, what: str) -> None:
    """上游非 200 → 502（404 语义由调用方在调本函数前自行拦截）。"""
    if resp.status_code != HTTPStatus.OK:
        raise _ApiError(
            502,
            {
                "detail": f"alphaxiv {what}: {resp.status_code}",
                "code": "discover_upstream",
            },
        )


def _checked_arxiv_id(raw: str) -> str:
    """校验 arXiv id 形态：``YYMM.NNNNN(vN)`` 或 ``archive/YYMMNNN(vN)``。"""
    aid = raw.strip().strip("/")
    if not _ARXIV_ID_RE.fullmatch(aid):
        raise _ApiError(
            400,
            {"detail": f"bad arxiv id {raw!r}", "code": "invalid_request"},
        )
    return aid


async def _fetch_overview(aid: str) -> dict[str, Any] | None:
    """legacy→pvid→status→zh 优先/en 兜底三步链；任一 404/未生成 → ``None``。"""
    resp = await _ax_get(f"/papers/v3/legacy/{aid}")
    if resp.status_code == HTTPStatus.NOT_FOUND:
        return None
    _check_2xx(resp, "legacy")
    try:
        pvid = resp.json()["paper"]["paper_version"]["id"]
    except (KeyError, TypeError, ValueError) as e:
        raise _ApiError(
            502,
            {
                "detail": f"alphaxiv legacy 形状异常: {e}",
                "code": "discover_upstream",
            },
        ) from e
    resp = await _ax_get(f"/papers/v3/{pvid}/overview/status")
    if resp.status_code == HTTPStatus.NOT_FOUND:
        return None
    _check_2xx(resp, "overview/status")
    status = resp.json()
    translations = status.get("translations") or {}
    zh_done = (translations.get("zh") or {}).get("state") == "done"
    en_done = (translations.get("en") or {}).get("state") == "done" or status.get(
        "state"
    ) == "done"
    lang = "zh" if zh_done else "en" if en_done else ""
    if not lang:
        return None
    resp = await _ax_get(f"/papers/v3/{pvid}/overview/{lang}")
    if resp.status_code == HTTPStatus.NOT_FOUND:
        return None
    _check_2xx(resp, "overview")
    ov = resp.json()
    return {
        "available": True,
        "lang": lang,
        "arxiv_id": aid,
        "alphaxiv_url": f"https://www.alphaxiv.org/abs/{aid}",
        "title": ov.get("title"),
        "abstract": ov.get("abstract"),
        "summary": ov.get("summary"),
        "overview": ov.get("overview"),
        "citations": ov.get("citations"),
    }


def register(app: FastAPI, _deps: AppDeps) -> None:  # noqa: C901 -- 嵌套端点分支计入
    """挂载 discover 端点（全是只读 GET，不占配额/租户面）。"""

    @app.get("/api/discover/feed")
    async def discover_feed(
        sort: str = "Hot",
        interval: str = "7 Days",
        page: int = 1,
        page_size: int = 12,
    ) -> dict[str, Any]:
        """首页 feed 透传（sort/interval 白名单 + 分页 clamp）。"""
        if sort not in _FEED_SORTS:
            raise _ApiError(
                400,
                {
                    "detail": f"sort ∈ {sorted(_FEED_SORTS)}",
                    "code": "invalid_request",
                },
            )
        if interval not in _FEED_INTERVALS:
            raise _ApiError(
                400,
                {
                    "detail": f"interval ∈ {sorted(_FEED_INTERVALS)}",
                    "code": "invalid_request",
                },
            )
        page = max(1, min(100, page))
        page_size = max(1, min(30, page_size))
        key = f"{sort}|{interval}|{page}|{page_size}"
        cached = _feed_cache.get(key)
        if cached is not None:
            return cached
        resp = await _ax_get(
            "/papers/v3/feed",
            params={
                "sort": sort,
                "interval": interval,
                "pageNum": str(page),
                "pageSize": str(page_size),
            },
        )
        _check_2xx(resp, "feed")
        body: dict[str, Any] = resp.json()
        _feed_cache.put(key, body)
        return body

    @app.get("/api/discover/search")
    async def discover_search(q: str = "") -> list[dict[str, Any]]:
        """快搜建议代理（``search/v2/paper/fast``，``{paperId,title,snippet,link}`` 列表）。"""
        q = q.strip()
        if not q or len(q) > _SEARCH_Q_MAX:
            raise _ApiError(
                400,
                {"detail": f"q 须为 1–{_SEARCH_Q_MAX} 字符", "code": "invalid_request"},
            )
        cached = _search_cache.get(q)
        if cached is not None:
            return cached
        resp = await _ax_get(
            "/search/v2/paper/fast",
            params={"q": q, "includePrivate": "false"},
        )
        _check_2xx(resp, "search")
        body: list[dict[str, Any]] = resp.json()
        _search_cache.put(q, body)
        return body

    @app.get("/api/discover/overview/{arxiv_id:path}")
    async def discover_overview(arxiv_id: str) -> dict[str, Any]:
        """机会型 AI 导读（zh 优先/en 兜底）。

        未收录或未生成 → ``{"available": false}``（非错误，前端静默隐藏）。
        回包裁掉 ``intermediateReport``（25KB 纯英文中间件，非用户内容）。
        """
        aid = _checked_arxiv_id(arxiv_id)
        cached = _overview_cache.get(aid)
        if cached is not None:
            return cached
        body = await _fetch_overview(aid)
        if body is None:
            return {"available": False}
        _overview_cache.put(aid, body)
        return body

    @app.get("/api/discover/og/{arxiv_id:path}")
    async def discover_og(request: Request, arxiv_id: str) -> Response:
        """OG 分享卡 PNG 代理（``open-graph/v1/paper/{id}``，任意 id 实时渲染）。"""
        aid = _checked_arxiv_id(arxiv_id)
        cached = _og_cache.get(aid)
        if cached is None:
            resp = await _ax_get(f"/open-graph/v1/paper/{aid}")
            if resp.status_code == HTTPStatus.NOT_FOUND:
                raise _ApiError(
                    404, {"detail": "og not available", "code": "not_found"}
                )
            _check_2xx(resp, "open-graph")
            cached = resp.content
            _og_cache.put(aid, cached)
        # 渲染图按 id 稳定——私有缓存一天（no_store_mw 认 request.state 标记）
        request.state.cache_control = "private, max-age=86400"
        return Response(content=cached, media_type="image/png")
