"""refs 路由：引用悬浮卡的文献条目远端元数据代理（L2 机会型增强）。

前端从 dual.json ph 索引出 ``bibkey → {arxivId?, doi?}`` 线索，本路由
批量解成 title/authors/year/venue/citationCount/tldr。设计铁律（引用
UX 调研 §0/§4）：浏览器绝不按 hover 直连 S2/OpenAlex——免 key 池 429
是常态，必须服务端代理 + TTL + 负缓存。主路上游 S2 ``/paper/batch``
（``ARXIV:``/``DOI:`` 前缀一批同解两类 id，≤500/批）；S2 漏网的 DOI
条目走 Crossref ``/works/{doi}`` 补（公共池 5rps，并发闸 4）。

机会型面：任一上游失败 ``degraded=true`` 仍 200 尽力返回——绝不 502
打错误面（卡字段缺位前端静默隐藏）。缓存照抄 ``discover._TtlCache``
双桶：命中 24h、miss 负缓存 10min（429 风暴期不重复鞭尸上游）。
httpx client 按 loop 分桶 + ``_aclose_clients`` lifespan 钩——跨环
复用炸 "attached to a different loop"（discover.py 同款坑）。
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

from texlate.arxiv.fetch import normalize_arxiv_id, valid_id
from texlate.server import bibexport
from texlate.server.http import _ApiError, _read_body
from texlate.server.store import StoreError

if TYPE_CHECKING:
    from pathlib import Path

    import httpx
    from fastapi import FastAPI

    from texlate.server.routers.deps import AppDeps

log = logging.getLogger(__name__)

_S2_BATCH = "https://api.semanticscholar.org/graph/v1/paper/batch"
_S2_FIELDS = "title,authors,year,venue,citationCount,tldr,externalIds"
_S2_BATCH_MAX = 450
_CR_WORKS = "https://api.crossref.org/works/"
_CR_FALLBACK_MAX = 24
_CR_CONCURRENCY = 4

_MAX_REFS = 400
_MAX_KEY = 160
_MAX_DOI = 256
_MAX_ARXIV = 64


class _TtlCache[T]:
    """key → (expires_monotonic, value)，容量有界 LRU 头出（discover.py 同款）。"""

    def __init__(self, ttl: float, max_entries: int) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self._d: OrderedDict[str, tuple[float, T]] = OrderedDict()

    def get(self, key: str) -> T | None:
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
        self._d[key] = (time.monotonic() + self.ttl, val)
        self._d.move_to_end(key)
        while len(self._d) > self.max_entries:
            self._d.popitem(last=False)


#: 上游 id（``ARXIV:x``/``DOI:x``）→ meta 24h；miss 负缓存 10min 挡 429 鞭尸
_meta_cache = _TtlCache[dict[str, Any]](ttl=86400, max_entries=4096)
_neg_cache = _TtlCache[dict[str, Any]](ttl=600, max_entries=2048)

#: loop 分桶 AsyncClient——连接池绑创建时 running loop（discover.py 同坑）
_clients: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}


def _client() -> httpx.AsyncClient:
    """取当前环的共享 client（惰性建，顺带摘除死环条目）。"""
    import httpx  # noqa: PLC0415 -- 重依赖惰性加载

    loop = asyncio.get_running_loop()
    for dead in [lp for lp in _clients if lp.is_closed()]:
        del _clients[dead]
    cli = _clients.get(loop)
    if cli is None:
        cli = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            headers={
                "User-Agent": "texlate-refs (mailto:texlate@localhost)",
            },
        )
        _clients[loop] = cli
    return cli


async def _aclose_clients() -> None:
    """尽力关全部 loop 桶 client——app lifespan 收尾用。"""
    while _clients:
        cli = _clients.pop(next(iter(_clients)))
        try:
            await cli.aclose()
        except Exception as e:  # noqa: BLE001 -- 收尾尽力而为
            log.debug("refs client aclose failed: %s: %s", type(e).__name__, e)


_DOI_RX = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_DOI_PREFIX_RX = re.compile(
    r"^(?:(?:https?://)?(?:dx\.|www\.)?doi\.org/|doi:\s*)", re.IGNORECASE
)


def _norm_doi(raw: str) -> str | None:
    """DOI 归一：剥 doi.org/ 各族前缀与 doi: + ?# 截断 + lowercase；非法形拒收。"""
    d = _DOI_PREFIX_RX.sub("", raw.strip())
    d = d.split("?", 1)[0].split("#", 1)[0].strip().rstrip(".,;)]}")
    return d.lower() if _DOI_RX.match(d) else None


def _s2_to_meta(paper: dict[str, Any]) -> dict[str, Any]:
    """S2 paper 对象 → RefMeta 平面（字段缺位即不出键）。"""
    ext = paper.get("externalIds") or {}
    out: dict[str, Any] = {}
    if isinstance(paper.get("title"), str):
        out["title"] = paper["title"]
    auth = paper.get("authors")
    if isinstance(auth, list):
        names = [
            a["name"]
            for a in auth
            if isinstance(a, dict) and isinstance(a.get("name"), str)
        ]
        if names:
            out["authors"] = names
    if isinstance(paper.get("year"), int):
        out["year"] = paper["year"]
    if isinstance(paper.get("venue"), str) and paper["venue"]:
        out["venue"] = paper["venue"]
    if isinstance(paper.get("citationCount"), int):
        out["citationCount"] = paper["citationCount"]
    tl = paper.get("tldr")
    if isinstance(tl, dict) and isinstance(tl.get("text"), str):
        out["tldr"] = tl["text"]
    if isinstance(ext.get("ArXiv"), str):
        out["arxivId"] = ext["ArXiv"]
    if isinstance(ext.get("DOI"), str):
        out["doi"] = ext["DOI"].lower()
    return out


def _cr_to_meta(msg: dict[str, Any]) -> dict[str, Any]:  # noqa: C901 -- 字段映射阶梯
    """Crossref work.message → RefMeta 平面。"""
    out: dict[str, Any] = {}
    t = msg.get("title")
    if isinstance(t, list) and t and isinstance(t[0], str):
        out["title"] = t[0]
    auth = msg.get("author")
    if isinstance(auth, list):
        names = []
        for a in auth:
            if not isinstance(a, dict):
                continue
            name = " ".join(
                x for x in (a.get("given"), a.get("family")) if isinstance(x, str)
            ).strip()
            if name:
                names.append(name)
        if names:
            out["authors"] = names
    issued = msg.get("issued")
    if isinstance(issued, dict):
        parts = issued.get("date-parts")
        if (
            isinstance(parts, list)
            and parts
            and isinstance(parts[0], list)
            and parts[0]
            and isinstance(parts[0][0], int)
        ):
            out["year"] = parts[0][0]
    cont = msg.get("container-title")
    if isinstance(cont, list) and cont and isinstance(cont[0], str):
        out["venue"] = cont[0]
    if isinstance(msg.get("is-referenced-by-count"), int):
        out["citationCount"] = msg["is-referenced-by-count"]
    if isinstance(msg.get("DOI"), str):
        out["doi"] = msg["DOI"].lower()
    return out


async def _s2_batch(ids: list[str]) -> dict[str, dict[str, Any] | None]:
    """S2 /paper/batch：id → meta|None（None=该 id 未解析）。

    整批失败抛异常——调用方归并 degraded。
    """
    out: dict[str, dict[str, Any] | None] = {}
    resp = await _client().post(
        _S2_BATCH,
        params={"fields": _S2_FIELDS},
        json={"ids": ids},
    )
    # 4xx/5xx（含 429）一律 raise_for_status 上抛——调用方归并 degraded
    resp.raise_for_status()
    arr = resp.json()
    # 200 但非 list（网关层 {"error":…} 等异常体）按整挂处理——否则每个 sid
    # 都被误当 resolved-miss 负缓存 10min 且 degraded 不置位
    if not isinstance(arr, list):
        msg = "s2 batch: non-list body"
        raise TypeError(msg)
    for sid, paper in zip(ids, arr, strict=False):
        out[sid] = _s2_to_meta(paper) if isinstance(paper, dict) else None
    return out


async def _cr_work(doi: str) -> dict[str, Any] | None:
    """Crossref /works/{doi} 单条；miss/失败 → None。"""
    try:
        resp = await _client().get(f"{_CR_WORKS}{doi}")
    except Exception:  # noqa: BLE001 -- InvalidURL 非 HTTPError；关 client RuntimeError 同视同 miss
        return None
    if resp.status_code != HTTPStatus.OK:
        return None
    try:
        msg = resp.json().get("message")
    except Exception:  # noqa: BLE001 -- 上游坏 JSON 视同 miss
        return None
    return _cr_to_meta(msg) if isinstance(msg, dict) else None


def _collect_jobs(refs: list[Any]) -> list[tuple[str, str, str | None]]:
    """请求 refs → (key, s2id, doi) 工作表（ARXIV 优先——S2 同批面一次解）。"""
    jobs: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    for r in refs:
        if not isinstance(r, dict):
            continue
        key = r.get("key")
        if (
            not isinstance(key, str)
            or not key
            or len(key) > _MAX_KEY
            or key in seen
        ):
            continue
        seen.add(key)
        doi = r.get("doi")
        doi = (
            _norm_doi(doi)
            if isinstance(doi, str) and len(doi) <= _MAX_DOI
            else None
        )
        s2id: str | None = None
        raw_ax = r.get("arxivId")
        if isinstance(raw_ax, str) and len(raw_ax) <= _MAX_ARXIV:
            base, _ver = normalize_arxiv_id(raw_ax)
            if base and valid_id(base):
                s2id = f"ARXIV:{base}"
        if s2id is None and doi:
            s2id = f"DOI:{doi}"
        if s2id:
            jobs.append((key, s2id, doi))
    return jobs


async def _s2_resolve(
    todo: list[tuple[str, str, str | None]],
    meta: dict[str, dict[str, Any]],
) -> tuple[list[tuple[str, str]], bool]:
    """S2 批量臂：解 todo → meta（写缓存）；返 DOI 漏网表 + degraded。"""
    s2_miss_doi: list[tuple[str, str]] = []
    degraded = False
    for i in range(0, len(todo), _S2_BATCH_MAX):
        batch = todo[i : i + _S2_BATCH_MAX]
        try:
            got = await _s2_batch([sid for _, sid, _ in batch])
        except Exception as e:  # noqa: BLE001 -- 上游整挂=degraded 不炸端点
            log.info("s2 batch failed: %s: %s", type(e).__name__, e)
            degraded = True
            s2_miss_doi.extend((key, doi) for key, _, doi in batch if doi)
            continue
        for key, sid, doi in batch:
            if sid not in got:
                # 数组截短=该 id 根本没回包（unknown 非 miss）——不 poison
                # 负缓存，DOI 条目照常转 Crossref 兜底
                degraded = True
                if doi:
                    s2_miss_doi.append((key, doi))
                continue
            m = got[sid]
            if m:
                _meta_cache.put(sid, m)
                meta[key] = m
            else:
                _neg_cache.put(sid, {})
                if doi:
                    s2_miss_doi.append((key, doi))
    return s2_miss_doi, degraded


async def _cr_fallback(
    s2_miss_doi: list[tuple[str, str]],
    meta: dict[str, dict[str, Any]],
) -> bool:
    """Crossref DOI 兜底臂：S2 漏网的 DOI 条目逐条补（并发闸 4，上限 24）。"""
    if not s2_miss_doi:
        return False
    sem = asyncio.Semaphore(_CR_CONCURRENCY)

    async def one(key: str, doi: str) -> None:
        async with sem:
            m = await _cr_work(doi)
        sid = f"DOI:{doi}"
        if m:
            _meta_cache.put(sid, m)
            meta[key] = m
        else:
            _neg_cache.put(sid, {})

    await asyncio.gather(
        *(one(k, d) for k, d in s2_miss_doi[:_CR_FALLBACK_MAX]),
        return_exceptions=True,
    )
    return len(s2_miss_doi) > _CR_FALLBACK_MAX


async def _lookup(body: dict[str, Any]) -> dict[str, Any]:
    refs = body.get("refs")
    if not isinstance(refs, list) or len(refs) > _MAX_REFS:
        raise _ApiError(
            400, {"detail": "refs: list required (<=400)", "code": "bad_request"}
        )

    jobs = _collect_jobs(refs)
    meta: dict[str, dict[str, Any]] = {}
    # 1) 缓存命中直出；2) S2 批量解 miss；3) DOI 漏网 Crossref 补
    todo: list[tuple[str, str, str | None]] = []
    for key, s2id, _doi in jobs:
        hit = _meta_cache.get(s2id)
        if hit is not None:
            meta[key] = hit
        elif _neg_cache.get(s2id) is None:
            todo.append((key, s2id, _doi))

    s2_miss_doi, degraded = await _s2_resolve(todo, meta)
    if await _cr_fallback(s2_miss_doi, meta):
        degraded = True
    return {"meta": meta, "degraded": degraded}


def _kept_list(deps: AppDeps, request: Request, task_id: str) -> dict[str, Any]:
    """任务 kept 全集 ``{kept: {key: payload}}``——ReaderView mount 一次取回。"""
    deps.get_task(request, task_id)
    return {"kept": deps.store.kept_list(task_id)}


async def _kept_put(
    deps: AppDeps, request: Request, task_id: str
) -> dict[str, Any]:
    """``{key, payload}`` upsert / ``payload:null`` unkeep（乐观写回滚对端）。"""
    deps.get_task(request, task_id)
    body = await _read_body(request)
    key = body.get("key")
    if not isinstance(key, str) or not key or len(key) > _MAX_KEY:
        raise _ApiError(
            400, {"detail": f"key: str 1..{_MAX_KEY}", "code": "bad_request"}
        )
    payload = body.get("payload")
    if payload is None:
        # unkeep——幂等（未存在也 200，乐观写回滚不区分先态）
        deps.store.kept_delete(task_id, key)
        return {"kept": False}
    if not isinstance(payload, dict):
        raise _ApiError(
            400, {"detail": "payload: object|null", "code": "bad_request"}
        )
    try:
        deps.store.kept_put(task_id, key, payload)
    except StoreError as e:
        raise _ApiError(
            400, {"detail": str(e), "code": "bad_request"}
        ) from e
    return {"kept": True}


def _kept_delete(
    deps: AppDeps, request: Request, task_id: str, key: str
) -> dict[str, Any]:
    """按 key 删 kept（``:path`` 容纳 key 内 ``/``）；未命中 → 404。"""
    deps.get_task(request, task_id)
    if not deps.store.kept_delete(task_id, key):
        raise _ApiError(
            404, {"detail": "kept ref not found", "code": "not_found"}
        )
    return {"kept": False}


def _src_tar_path(deps: AppDeps, task_id: str) -> Path | None:
    """src.tar blob 落盘定位：files 表登记 + resolve/is_relative_to 防逃逸。

    ``file_get`` 同款口径——登记路径可能脏，resolve 后必须仍在 task 目录内。
    """
    rec = deps.store.file_record(task_id, "src_tar")
    if rec is None:
        return None
    task_root = deps.task_dir(task_id).resolve()
    cand = (task_root / str(rec["path"])).resolve()
    if cand.is_relative_to(task_root) and cand.is_file():
        return cand
    return None


def _qint(request: Request, name: str) -> int:
    """Query flag → int；非数字 → 400（与 JSON 端点同闸不静默吞）。"""
    raw = request.query_params.get(name) or "0"
    try:
        return int(raw)
    except ValueError as e:
        raise _ApiError(
            400, {"detail": f"{name}: int flag", "code": "bad_request"}
        ) from e


async def _refs_bib(
    deps: AppDeps, request: Request, task_id: str
) -> Response:
    """``.bib`` 导出体：key 集裁定 → 物料/远端臂 → build_bib → Response。"""
    deps.get_task(request, task_id)
    keys = request.query_params.get("keys") or ""
    all_flag = _qint(request, "all")
    download = _qint(request, "download")
    kept = deps.store.kept_list(task_id)
    idx = await asyncio.to_thread(
        bibexport.load_src_index, _src_tar_path(deps, task_id)
    )

    if keys:
        wanted = [k.strip() for k in keys.split(",") if k.strip()]
    elif all_flag or not kept:
        wanted = idx.universe(kept)
    else:
        wanted = list(kept)
    truncated = len(wanted) > _MAX_REFS
    if truncated:
        wanted = wanted[:_MAX_REFS]

    items = bibexport.plan_items(wanted, idx, kept)
    remote_items = [
        it for it in items if it.verbatim is None and it.remote_worthy
    ]
    remote = (
        await bibexport.resolve_remote(_client(), remote_items)
        if remote_items
        else {}
    )
    body, degraded = bibexport.build_bib(
        items, remote, idx.strings, truncated=truncated
    )
    headers = {"X-Refs-Degraded": str(len(degraded))}
    if truncated:
        headers["X-Refs-Truncated"] = "1"
    if download:
        headers["Content-Disposition"] = (
            f'attachment; filename="texlate-{task_id}-refs.bib"'
        )
    return Response(content=body, media_type="text/x-bibtex", headers=headers)


def register(app: FastAPI, deps: AppDeps) -> None:
    """``POST /api/refs/lookup`` + M4：kept CRUD 与 ``refs.bib`` 导出端点。"""

    @app.post("/api/refs/lookup")
    async def refs_lookup(req: Request) -> dict[str, Any]:
        # _read_body 一口价：4MB 闸 + CT 415 + 坏 JSON/UnicodeDecodeError/
        # RecursionError→400——与其它 JSON 端点同闸，勿手搓 req.json()
        return await _lookup(await _read_body(req))

    # -------------------------------------------------- M4 Phase B：kept refs

    @app.get("/api/task/{task_id}/refs/kept")
    async def refs_kept_list(request: Request, task_id: str) -> dict[str, Any]:
        return _kept_list(deps, request, task_id)

    @app.put("/api/task/{task_id}/refs/kept")
    async def refs_kept_put(request: Request, task_id: str) -> dict[str, Any]:
        return await _kept_put(deps, request, task_id)

    @app.delete("/api/task/{task_id}/refs/kept/{key:path}")
    async def refs_kept_delete(
        request: Request, task_id: str, key: str
    ) -> dict[str, Any]:
        return _kept_delete(deps, request, task_id, key)

    # -------------------------------------------------- M4 Phase A：refs.bib

    @app.get("/api/task/{task_id}/refs.bib")
    async def refs_bib(request: Request, task_id: str) -> Response:
        """``.bib`` 导出：Lane A verbatim + Lane B 远端 + Lane C 合成。

        ``?keys=a,b`` 显式子集；缺省=kept 全集（无 kept 则全可解 key）；
        ``?all=1`` 无视 kept 出全量。超 ``_MAX_REFS`` 截短 +
        ``X-Refs-Truncated``；远端降级数 ``X-Refs-Degraded`` + 文件头注释；
        ``?download=1`` 附 ``Content-Disposition``。绝不 502。
        """
        return await _refs_bib(deps, request, task_id)
