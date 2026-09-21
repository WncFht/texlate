r"""取源编排：HEAD → 缓存命中/重验证 → GET → sniff → unpack → locate → 钉版落盘。

``fetch.py`` 是线缆层（``Fetcher``/HEAD/GET/退避/id 归一/``_body_result``）；
本叶是 ``acquire_source`` 的 phase 编排——``_head_phase``/``_get_phase``/
``_commit_phase``/``_offline_phase`` 与缓存命中终态映射。
``fetch.acquire_source`` 经模块 ``__getattr__`` 惰性回指本叶——
``from texlate.arxiv.fetch import acquire_source`` 引用面不变。

规格：docs/spec/arxiv-source.md 状态机（失败终态对齐 ``AcquireStatus``）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, replace
from typing import Final

import httpx

from texlate.arxiv.cache import CacheEntry, CacheError, SourceCache
from texlate.arxiv.fetch import (
    AcquireResult,
    AcquireStatus,
    Fetcher,
    FetchStatus,
    HeadInfo,
    SrcResult,
    _head_gate,
    normalize_arxiv_id,
    req_base_ver,
    valid_id,
)
from texlate.arxiv.locate import LocateResult, locate
from texlate.arxiv.ratelimit import BudgetExhaustedError, ParkedError
from texlate.arxiv.sniff import BlobKind
from texlate.arxiv.unpack import (
    UnpackError,
    UnpackResult,
    unpack_sniffed,
    write_manifest,
)
from texlate.textutil import utc_now

log = logging.getLogger(__name__)


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
    # 保持延迟导入：meta 拉 defusedxml 依赖，本函数是唯一消费点
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


#: ``FetchStatus`` → ``AcquireStatus`` 终态映射（head-gate/get 两臂共用；
#: head-gate 产不出 PARKED，超集带一键无害、免两表各自发散）
_FETCH_TO_ACQ: Final = {
    FetchStatus.NOT_FOUND: AcquireStatus.NOT_FOUND,
    FetchStatus.TOO_LARGE: AcquireStatus.TOO_LARGE,
    FetchStatus.PARKED: AcquireStatus.PARKED,
}


def _head_phase(
    base: str, ver_req: int | None, fetcher: Fetcher, cache: SourceCache
) -> tuple[HeadInfo | AcquireResult, CacheEntry | None]:
    """HEAD + 缓存 etag 比对。返回 (head, cached) 或短路 AcquireResult。"""
    err: AcquireResult | None = None
    head: HeadInfo | None = None
    log.info("head %s", base)
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
        status = _FETCH_TO_ACQ.get(gate.status, AcquireStatus.ERROR)
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
    log.info("get %sv%s", ids.base, ids.ver)
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
    st = _FETCH_TO_ACQ.get(res.status, AcquireStatus.ERROR)
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
    log.info("commit %sv%s", ids.base, ids.ver)
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
        "fetched_at": utc_now(),
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
    try:
        base, ver_req = req_base_ver(arxiv_id, version)
    except ValueError:
        # 同判据不抛版——错细节分 bad_id/bad_version 两档
        base, pin = normalize_arxiv_id(arxiv_id)
        ver_req = version if version is not None else pin
        bad = f"bad_id:{base!r}" if not valid_id(base) else f"bad_version:{ver_req}"
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
