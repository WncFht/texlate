r"""元数据层：Atom API 主源 + OAI-PMH 兜底 + §5 降级链（docs/06 §3/§5）。

- ``fetch_metadata``：``export.arxiv.org/api/query?id_list=…`` Atom feed →
  ``PaperMeta``（§3.2 schema：title/authors/categories/published/updated/
  resolved_version/comment/doi/journal_ref/links）。Atom 无 ``license`` 与
  版本史——Atom 不可用/无条目时降级 OAI-PMH ``GetRecord``，
  ``metadataPrefix=arXivRaw``（独占 ``<version>`` 版本史 + license 唯一
  机读源；OAI 已迁 ``oaipmh.arxiv.org``，独立第三限流桶，见 §1.1）。
- ``resolve_version``：裸 id → 最新 ``vN``；带 ``want``（或 id 自带 vN 钉）
  → 存在性校验。版本天然连续 ``1..latest``，一次拉取够两种判断。
- ``degrade``：L1 e-print 失败后的降级裁决（§5）——解析/编译失败走 L2
  ``/html/{id}``（最新版 → 逐版本回退）；%PDF/404/stub 走 L3 ``/pdf/{id}``
  sidecar；首选层不可得时落到另一层兜底（三层叠加覆盖语义）。

纪律：全部请求过 ``Fetcher``（per-host 限速桶 + (host,path) 断路器 +
日预算）。无网/超时/park/预算/解析失败一律 ``None`` 或
``DegradeResult(NONE)``，不抛——调用方判空。id 形非法仍 ``ValueError``
（与 ``head_src`` 一致的调用方错误语义）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC
from email.utils import parsedate_to_datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Final
from urllib.parse import urlsplit

import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from texlate.arxiv.fetch import Fetcher, _valid_id, normalize_arxiv_id
from texlate.arxiv.ratelimit import BudgetExhaustedError, ParkedError

#: Atom API 端点（export 桶；arxiv.org/api 302 到此，直接打 canonical）
ATOM_API: Final = "https://export.arxiv.org/api/query"
#: OAI-PMH baseURL（已迁出 export——/oai2 全动词 301 到此；独立第三限流桶）
OAI_BASE: Final = "https://oaipmh.arxiv.org/oai"
#: OAI 元数据前缀：arXivRaw 独占版本史 + license（docs/research/arxiv/oai-pmh.md §2）
OAI_PREFIX: Final = "arXivRaw"

_ATOM_NS: Final = "http://www.w3.org/2005/Atom"
_ARXIV_NS: Final = "http://arxiv.org/schemas/atom"
_OAI_NS: Final = "http://www.openarchives.org/OAI/2.0/"
_RAW_NS: Final = "http://arxiv.org/OAI/arXivRaw/"

_VER_TAIL_RE: Final = re.compile(r"[vV](\d+)(?:\.pdf)?$")


def _text(parent: ElementTree.Element, tag: str) -> str:
    """取子元素文本并折叠空白（Atom summary/title 常带换行缩进）。"""
    el = parent.find(tag)
    if el is None or el.text is None:
        return ""
    return " ".join(el.text.split())


def _rfc822_to_iso(s: str) -> str:
    """OAI arXivRaw 版本日期（RFC822 GMT）→ ISO Z；解析不动原样返回。"""
    if not s:
        return ""
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        return s
    if dt.tzinfo is None:
        return s
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class VersionInfo:
    """单版本记录（OAI arXivRaw ``<version>``；date 已转 ISO Z）。"""

    version: int
    date: str = ""
    size: str = ""
    source_type: str = ""


@dataclass(slots=True)
class PaperMeta:
    """§3.2 meta schema + ``versions``（仅 OAI 源有真值）+ ``source`` 留痕。

    Atom 钉版查询（``id_list=id vN``）时 feed 只描述该版——
    ``resolved_version`` = 钉版号；``latest_version`` 此时是「已见最新」
    而非论文真 latest。裸 id 查询 / OAI 源时 ``latest_version`` 即真 latest。
    """

    arxiv_id: str
    resolved_version: int | None
    title: str = ""
    authors: tuple[str, ...] = ()
    abstract: str = ""
    primary_category: str = ""
    categories: tuple[str, ...] = ()
    published: str = ""
    updated: str = ""
    doi: str = ""
    journal_ref: str = ""
    comment: str = ""
    license: str = ""
    submitter: str = ""
    links: dict[str, str] = field(default_factory=dict)
    versions: tuple[VersionInfo, ...] = ()
    source: str = "atom"

    @property
    def latest_version(self) -> int | None:
        """已知最新版本号（OAI 版本史取 max；否则 = resolved_version）。"""
        if self.versions:
            return max(v.version for v in self.versions)
        return self.resolved_version

    def has_version(self, want: int) -> bool:
        """``want`` 版存在性：有真版本史查表，否则按连续 ``1..latest`` 判。"""
        if self.versions:
            return any(v.version == want for v in self.versions)
        latest = self.resolved_version
        return latest is not None and 1 <= want <= latest


def _get(fetcher: Fetcher, url: str) -> httpx.Response | None:
    """GET + 失败归一：park/预算/传输错误/非 200 → None。"""
    try:
        resp = fetcher.get_url(url)
    except (ParkedError, BudgetExhaustedError, httpx.TransportError, OSError):
        return None
    return resp if resp.status_code == HTTPStatus.OK else None


def _parse_atom(body: bytes) -> PaperMeta | None:
    """Atom feed → PaperMeta；错误 entry / 无有效 entry → None。

    坏 id 时 API 回 ``<title>Error</title>`` 形态的错误 entry——其 ``<id>``
    不是 abs URL，``normalize_arxiv_id`` + id 校验即滤除。
    """
    root = ElementTree.fromstring(body)
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        eid, ver = normalize_arxiv_id(_text(entry, f"{{{_ATOM_NS}}}id"))
        if not _valid_id(eid):
            continue
        if _text(entry, f"{{{_ATOM_NS}}}title").lower() == "error":
            continue
        links: dict[str, str] = {}
        for link in entry.findall(f"{{{_ATOM_NS}}}link"):
            href = link.get("href", "")
            if not href:
                continue
            if link.get("rel") == "alternate":
                links.setdefault("abs", href)
            elif link.get("title"):
                links.setdefault(link.get("title", ""), href)
        cats = tuple(
            t
            for c in entry.findall(f"{{{_ATOM_NS}}}category")
            if (t := c.get("term", ""))
        )
        pri = entry.find(f"{{{_ARXIV_NS}}}primary_category")
        return PaperMeta(
            arxiv_id=eid,
            resolved_version=ver,
            title=_text(entry, f"{{{_ATOM_NS}}}title"),
            authors=tuple(
                t
                for a in entry.findall(f"{{{_ATOM_NS}}}author")
                if (t := _text(a, f"{{{_ATOM_NS}}}name"))
            ),
            abstract=_text(entry, f"{{{_ATOM_NS}}}summary"),
            primary_category="" if pri is None else pri.get("term", ""),
            categories=cats,
            published=_text(entry, f"{{{_ATOM_NS}}}published"),
            updated=_text(entry, f"{{{_ATOM_NS}}}updated"),
            doi=_text(entry, f"{{{_ARXIV_NS}}}doi"),
            journal_ref=_text(entry, f"{{{_ARXIV_NS}}}journal_ref"),
            comment=_text(entry, f"{{{_ARXIV_NS}}}comment"),
            links=links,
            source="atom",
        )
    return None


def _parse_oai(body: bytes, pin: int | None) -> PaperMeta | None:
    """OAI-PMH GetRecord(arXivRaw) → PaperMeta。

    OAI 错误即 200 + ``<error code='…'>``（idDoesNotExist 等）→ None；
    墓碑记录（``status="deleted"``）无 metadata → 同样 None。
    ``pin`` 在版本史内 → resolved_version 记钉版，否则记最新版。
    """
    root = ElementTree.fromstring(body)
    if root.find(f"{{{_OAI_NS}}}error") is not None:
        return None
    rec = root.find(
        f"{{{_OAI_NS}}}GetRecord/{{{_OAI_NS}}}record/"
        f"{{{_OAI_NS}}}metadata/{{{_RAW_NS}}}arXivRaw"
    )
    if rec is None:
        return None
    versions = tuple(
        VersionInfo(
            version=int(v.get("version", "").removeprefix("v")),
            date=_rfc822_to_iso(_text(v, f"{{{_RAW_NS}}}date")),
            size=_text(v, f"{{{_RAW_NS}}}size"),
            source_type=_text(v, f"{{{_RAW_NS}}}source_type"),
        )
        for v in rec.findall(f"{{{_RAW_NS}}}version")
        if v.get("version", "").removeprefix("v").isdigit()
    )
    cats = tuple(_text(rec, f"{{{_RAW_NS}}}categories").split())
    latest = max((v.version for v in versions), default=None)
    resolved = (
        pin if pin is not None and any(v.version == pin for v in versions) else latest
    )
    base = _text(rec, f"{{{_RAW_NS}}}id")
    suffix = f"v{resolved}" if resolved else ""
    return PaperMeta(
        arxiv_id=base,
        resolved_version=resolved,
        title=_text(rec, f"{{{_RAW_NS}}}title"),
        authors=tuple(
            a.strip()
            for a in _text(rec, f"{{{_RAW_NS}}}authors").split(" and ")
            if a.strip()
        ),
        abstract=_text(rec, f"{{{_RAW_NS}}}abstract"),
        primary_category=cats[0] if cats else "",
        categories=cats,
        published=versions[0].date if versions else "",
        updated=versions[-1].date if versions else "",
        doi=_text(rec, f"{{{_RAW_NS}}}doi"),
        journal_ref=_text(rec, f"{{{_RAW_NS}}}journal-ref"),
        comment=_text(rec, f"{{{_RAW_NS}}}comments"),
        license=_text(rec, f"{{{_RAW_NS}}}license"),
        submitter=_text(rec, f"{{{_RAW_NS}}}submitter"),
        links={
            "abs": f"https://arxiv.org/abs/{base}{suffix}",
            "pdf": f"https://arxiv.org/pdf/{base}{suffix}",
        },
        versions=versions,
        source="oai-raw",
    )


def _atom_meta(fetcher: Fetcher, base: str, pin: int | None) -> PaperMeta | None:
    """Atom ``id_list`` 单篇查询；钉版透传（``id_list=id vN`` → 该版 entry）。"""
    suffix = f"v{pin}" if pin else ""
    resp = _get(fetcher, f"{ATOM_API}?id_list={base}{suffix}")
    if resp is None:
        return None
    try:
        return _parse_atom(resp.content)
    except (ElementTree.ParseError, DefusedXmlException):
        return None


def _oai_meta(fetcher: Fetcher, base: str, pin: int | None) -> PaperMeta | None:
    """OAI-PMH GetRecord 兜底（版本史 + license 的唯一机读源）。"""
    url = (
        f"{OAI_BASE}?verb=GetRecord&identifier=oai:arXiv.org:{base}"
        f"&metadataPrefix={OAI_PREFIX}"
    )
    resp = _get(fetcher, url)
    if resp is None:
        return None
    try:
        return _parse_oai(resp.content, pin)
    except (ElementTree.ParseError, DefusedXmlException, ValueError):
        return None


def fetch_metadata(arxiv_id: str, *, fetcher: Fetcher) -> PaperMeta | None:
    """Atom 主源 → OAI-PMH 兜底。无网/超时/park/无条目 → ``None``。"""
    base, pin = normalize_arxiv_id(arxiv_id)
    if not _valid_id(base):
        msg = f"bad arxiv id: {arxiv_id!r}"
        raise ValueError(msg)
    return _atom_meta(fetcher, base, pin) or _oai_meta(fetcher, base, pin)


def resolve_version(
    arxiv_id: str, want: int | None = None, *, fetcher: Fetcher
) -> int | None:
    """裸 id → 最新版本号；``want``/id 自带 vN 钉 → 存在则返回该号否则 None。

    一次裸 id 元数据拉取同时覆盖两种判断（版本连续 ``1..latest``）；
    主源 Atom、兜底 OAI arXivRaw 版本史，全挂 → None。
    """
    base, pin = normalize_arxiv_id(arxiv_id)
    if not _valid_id(base):
        msg = f"bad arxiv id: {arxiv_id!r}"
        raise ValueError(msg)
    want = want if want is not None else pin
    meta = fetch_metadata(base, fetcher=fetcher)
    latest = meta.latest_version if meta is not None else None
    if latest is None:
        return None
    if want is None:
        return latest
    return want if meta.has_version(want) else None


class DegradeReason(StrEnum):
    """L1 e-print 失败因（§5 降级链路由键，对齐 §4.2 失败终态）。"""

    PARSE_FAILED = "parse_failed"
    COMPILE_FAILED = "compile_failed"
    PDF_ONLY = "pdf_only"
    NOT_FOUND = "not_found"
    STUB = "stub"


class DegradeTier(StrEnum):
    """降级层。"""

    HTML = "html"  # L2 LaTeXML DOM
    PDF = "pdf"  # L3 PDF sidecar
    NONE = "none"  # 三层皆不可得


@dataclass(frozen=True, slots=True)
class DegradeResult:
    """降级裁决：命中层 + 可用资源 URL + 探测轨迹。"""

    arxiv_id: str
    tier: DegradeTier
    url: str = ""
    version: int | None = None
    probed: tuple[str, ...] = ()
    detail: str = ""


#: §5 路由：解析/编译失败 → L2 优先；%PDF/404/stub → L3 优先
_L2_FIRST: Final = frozenset({DegradeReason.PARSE_FAILED, DegradeReason.COMPILE_FAILED})


def _head(
    fetcher: Fetcher, base: str, kind: str, ver: int | None, probed: list[str]
) -> tuple[str, int | None] | None:
    """``HEAD /{kind}/{id}[vN]`` 跨镜像探测；200 → (final_url, version)。

    裸 id 经 301 跳到 ``{id}v{N}``——从 final URL 回收版本号。
    park/传输错误向上抛（让 degrade 切下一层，不再空耗版本回退）。
    """
    path = f"/{kind}/{base}{f'v{ver}' if ver else ''}"
    try:
        resp = fetcher.head_path(path)
    except (ParkedError, BudgetExhaustedError, httpx.TransportError, OSError) as e:
        probed.append(f"error {path}: {e}")
        raise
    probed.append(f"{resp.status_code} {resp.url}")
    if resp.status_code != HTTPStatus.OK:
        return None
    m = _VER_TAIL_RE.search(urlsplit(str(resp.url)).path)
    return str(resp.url), int(m.group(1)) if m else ver


def _probe_html(
    fetcher: Fetcher, base: str, ver_req: int | None, probed: list[str]
) -> tuple[str, int | None] | None:
    """L2：钉版 → 裸 id（最新版）→ 逐版本回退 v(latest-1)..v1（§5 探测序）。"""
    tried: set[int] = set()
    order: list[int | None] = ([ver_req] if ver_req else []) + [None]
    for v in order:
        hit = _head(fetcher, base, "html", v, probed)
        if hit is not None:
            return hit
    latest = resolve_version(base, fetcher=fetcher)
    if latest is None:
        return None
    tried.add(latest)  # 裸 id 探的就是最新版
    if ver_req:
        tried.add(ver_req)
    for v in range(latest - 1, 0, -1):
        if v in tried:
            continue
        hit = _head(fetcher, base, "html", v, probed)
        if hit is not None:
            return hit
    return None


def _probe_pdf(
    fetcher: Fetcher, base: str, ver_req: int | None, probed: list[str]
) -> tuple[str, int | None] | None:
    """L3：钉版 → 裸 id（PDF 全版本都有，两次足够）。"""
    order: list[int | None] = ([ver_req] if ver_req else []) + [None]
    for v in order:
        hit = _head(fetcher, base, "pdf", v, probed)
        if hit is not None:
            return hit
    return None


def degrade(
    arxiv_id: str,
    *,
    fetcher: Fetcher,
    reason: DegradeReason | str,
    version: int | None = None,
) -> DegradeResult:
    """§5 降级裁决：按失败因路由首选层，不可得时落到另一层兜底。

    ``parse_failed``/``compile_failed`` → L2 ``/html/{id}``（钉版 → 最新版
    → 逐版本回退）→ L3；``pdf_only``/``not_found``/``stub`` → L3
    ``/pdf/{id}``（钉版 → 最新版）→ L2。全不可得 → ``tier=NONE``。
    """
    base, pin = normalize_arxiv_id(arxiv_id)
    if not _valid_id(base):
        msg = f"bad arxiv id: {arxiv_id!r}"
        raise ValueError(msg)
    ver_req = version if version is not None else pin
    first, second = (
        (_probe_html, _probe_pdf)
        if DegradeReason(reason) in _L2_FIRST
        else (_probe_pdf, _probe_html)
    )
    probed: list[str] = []
    for probe in (first, second):
        try:
            hit = probe(fetcher, base, ver_req, probed)
        except (ParkedError, BudgetExhaustedError, httpx.TransportError, OSError) as e:
            probed.append(f"abort: {e}")
            continue
        if hit is not None:
            url, ver = hit
            tier = DegradeTier.HTML if probe is _probe_html else DegradeTier.PDF
            return DegradeResult(base, tier, url, ver, tuple(probed))
    return DegradeResult(
        base,
        DegradeTier.NONE,
        version=ver_req,
        probed=tuple(probed),
        detail="all_tiers_unavailable",
    )
