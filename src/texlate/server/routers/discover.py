"""discover 路由：alphaXiv 公共面只读代理（feed/搜索/导读/OG 卡）。

alphaXiv 的 CORS 固定回 ``allow-origin: https://www.alphaxiv.org``——
浏览器侧第三方直连被挡，发现层数据只能由服务端代取（逆向报告
``docs/research/product/2026-09-19-alphaxiv-reverse.md``，端点形状
均实测过）。全部是机会型增强、不进核心管线：feed/search/og 上游失败
归一 502 ``discover_upstream``，前端整块隐藏；overview 链上任一环
404 或目标语言未生成回 ``{"available": false}``，网络/5xx 才 502。
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from fastapi import Request, Response

from texlate.arxiv.fetch import normalize_arxiv_id, valid_id
from texlate.server._ttlcache import LoopClientPool, _TtlCache
from texlate.server.http import _api_error

if TYPE_CHECKING:
    import httpx
    from fastapi import FastAPI

    from texlate.server.routers.deps import AppDeps

log = logging.getLogger(__name__)

_AX_API = "https://api.alphaxiv.org"

#: feed 参数白名单（上游 zod 枚举实测）；ForYou 需登录恒 401 不收
_FEED_SORTS = frozenset({"Hot", "Comments", "Views", "Likes", "GitHub", "Recent"})
_FEED_INTERVALS = frozenset({"3 Days", "7 Days", "30 Days", "90 Days", "All time"})

_SEARCH_Q_MAX = 200


#: 进程内 TTL 缓存——feed 10min、搜索 2min、导读 30min、OG 字节 24h。
#: 都是只读公共数据的弱新鲜度面；容量上界防内存账失控。
#: （``_TtlCache``/loop 分桶池单源在 ``texlate.server._ttlcache``）
_feed_cache = _TtlCache[dict[str, Any]](ttl=600, max_entries=64)
_search_cache = _TtlCache[list[dict[str, Any]]](ttl=120, max_entries=256)
_overview_cache = _TtlCache[dict[str, Any]](ttl=1800, max_entries=256)
_og_cache = _TtlCache[bytes](ttl=86400, max_entries=64)


def _new_client() -> httpx.AsyncClient:
    """本环懒建 alphaXiv client（连接池绑创建时 running loop）。"""
    import httpx  # noqa: PLC0415 -- 重依赖惰性加载

    return httpx.AsyncClient(
        base_url=_AX_API,
        timeout=httpx.Timeout(10.0),
        follow_redirects=True,
        headers={"User-Agent": "texlate-discover"},
    )


#: 按事件环分桶的 AsyncClient——httpx 连接池绑创建时的 running loop，
#: 跨环复用炸 "attached to a different loop"（worker ``_PerCallTranslator``
#: 同款坑，桶管理/死环摘除/尽力收尾单源在 ``LoopClientPool``）。
_clients = LoopClientPool(_new_client, label="discover")


def _client() -> httpx.AsyncClient:
    """取当前环的共享 client（池懒建 + 死环摘除）。"""
    return _clients.get()


async def _aclose_clients() -> None:
    """尽力关全部 loop 桶 client——app lifespan 收尾用（``bus.close_all()`` 旁）。

    异环/死环绑定的 client aclose 抛 ``RuntimeError`` 在预期内（死环条目
    本就关不掉，FD 归 GC）——逐条尽力而为在 ``aclose_all`` 内。
    """
    await _clients.aclose_all()


async def _ax_get(path: str, params: dict[str, Any] | None = None) -> httpx.Response:
    """上游 GET：网络层失败一律 502 ``discover_upstream``；HTTP 状态留给调用方判定。"""
    import httpx  # noqa: PLC0415 -- 重依赖惰性加载

    try:
        return await _client().get(path, params=params)
    except httpx.HTTPError as e:
        raise _api_error(502, f"alphaxiv upstream: {e}", "discover_upstream") from e


def _check_2xx(resp: httpx.Response, what: str) -> None:
    """上游非 200 → 502（404 语义由调用方在调本函数前自行拦截）。"""
    if resp.status_code != HTTPStatus.OK:
        raise _api_error(
            502, f"alphaxiv {what}: {resp.status_code}", "discover_upstream"
        )


def _ax_json[T](resp: httpx.Response, what: str, expect: type[T]) -> T:
    """上游 ``.json()`` + 顶层形状闸：坏 JSON/非 ``expect`` 型 → 502 ``discover_upstream``。

    裸 ``resp.json()`` 的 ``JSONDecodeError``、以及下游 ``.get``/下标撞上
    非标量形状的 ``AttributeError``/``TypeError`` 都会漏成无码 500——
    上游数据病归一到本口径（端点 ``-> dict`` 注解同理救不了运行时形状）。
    """
    try:
        data = resp.json()
    except (TypeError, ValueError) as e:
        raise _api_error(
            502, f"alphaxiv {what}: bad json: {e}", "discover_upstream"
        ) from e
    if not isinstance(data, expect):
        raise _api_error(
            502,
            (f"alphaxiv {what}: expect {expect.__name__}, got {type(data).__name__}"),
            "discover_upstream",
        )
    return data


def _checked_arxiv_id(raw: str) -> str:
    """校验 arXiv id 形态。

    ``normalize_arxiv_id``+``valid_id`` 单源口径（compat/tasks 同套，
    容忍 ``arXiv:``/URL/``.pdf`` 等装饰形）；``vN`` 钉版形原样拼回
    转发上游。
    """
    base, ver = normalize_arxiv_id(raw)
    if not valid_id(base):
        raise _api_error(400, f"bad arxiv id {raw!r}", "invalid_request")
    return f"{base}v{ver}" if ver is not None else base


async def _fetch_overview(aid: str) -> dict[str, Any] | None:
    """legacy→pvid→status→zh 优先/en 兜底三步链；任一 404/未生成 → ``None``。"""
    resp = await _ax_get(f"/papers/v3/legacy/{aid}")
    if resp.status_code == HTTPStatus.NOT_FOUND:
        return None
    _check_2xx(resp, "legacy")
    try:
        pvid = _ax_json(resp, "legacy", dict)["paper"]["paper_version"]["id"]
    except (KeyError, TypeError) as e:
        raise _api_error(
            502, f"alphaxiv legacy 形状异常: {e}", "discover_upstream"
        ) from e
    resp = await _ax_get(f"/papers/v3/{pvid}/overview/status")
    if resp.status_code == HTTPStatus.NOT_FOUND:
        return None
    _check_2xx(resp, "overview/status")
    status = _ax_json(resp, "overview/status", dict)
    translations = status.get("translations") or {}
    if not isinstance(translations, dict):
        translations = {}
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
    ov = _ax_json(resp, "overview", dict)
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
            raise _api_error(400, f"sort ∈ {sorted(_FEED_SORTS)}", "invalid_request")
        if interval not in _FEED_INTERVALS:
            raise _api_error(
                400, f"interval ∈ {sorted(_FEED_INTERVALS)}", "invalid_request"
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
        body: dict[str, Any] = _ax_json(resp, "feed", dict)
        _feed_cache.put(key, body)
        return body

    @app.get("/api/discover/search")
    async def discover_search(q: str = "") -> list[dict[str, Any]]:
        """快搜建议代理（``search/v2/paper/fast``，``{paperId,title,snippet,link}`` 列表）。"""
        q = q.strip()
        if not q or len(q) > _SEARCH_Q_MAX:
            raise _api_error(400, f"q 须为 1–{_SEARCH_Q_MAX} 字符", "invalid_request")
        cached = _search_cache.get(q)
        if cached is not None:
            return cached
        resp = await _ax_get(
            "/search/v2/paper/fast",
            params={"q": q, "includePrivate": "false"},
        )
        _check_2xx(resp, "search")
        body: list[dict[str, Any]] = _ax_json(resp, "search", list)
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
            body = {"available": False}
        # 负结果同进 30min 缓存——否则未收录论文每次首页加载都打穿三步上游链
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
                raise _api_error(404, "og not available", "not_found")
            _check_2xx(resp, "open-graph")
            cached = resp.content
            _og_cache.put(aid, cached)
        # 渲染图按 id 稳定——私有缓存一天（no_store_mw 认 request.state 标记）
        request.state.cache_control = "private, max-age=86400"
        return Response(content=cached, media_type="image/png")
