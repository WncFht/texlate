"""arXiv 源获取层：fetch / sniff / unpack / cache / locate / ratelimit（规格 docs/06）。

典型用法::

    from texlate.arxiv import Fetcher, RateLimiter, SourceCache, acquire_source

    cache = SourceCache("cache/src")
    fetcher = Fetcher(RateLimiter(cache.root / "ratelimit.json"))
    res = acquire_source("1412.6980", fetcher=fetcher, cache=cache)
"""

from texlate.arxiv.cache import CacheEntry, CacheError, SourceCache
from texlate.arxiv.fetch import (
    AcquireResult,
    AcquireStatus,
    Fetcher,
    FetchStatus,
    HeadInfo,
    SrcResult,
    acquire_source,
    normalize_arxiv_id,
)
from texlate.arxiv.locate import DocKind, InputRef, LocateResult, locate
from texlate.arxiv.meta import (
    DegradeReason,
    DegradeResult,
    DegradeTier,
    PaperMeta,
    VersionInfo,
    degrade,
    fetch_metadata,
    resolve_version,
)
from texlate.arxiv.ratelimit import (
    BudgetExhaustedError,
    ParkedError,
    RateLimiter,
    path_class,
)
from texlate.arxiv.sniff import (
    BlobKind,
    SniffError,
    SniffResult,
    WrapperVerdict,
    check_pdf_wrapper,
    sniff,
)
from texlate.arxiv.unpack import (
    MemberEntry,
    UnpackError,
    UnpackResult,
    unpack_single,
    unpack_sniffed,
    unpack_tar,
    write_manifest,
)

__all__ = [
    "AcquireResult",
    "AcquireStatus",
    "BlobKind",
    "BudgetExhaustedError",
    "CacheEntry",
    "CacheError",
    "DegradeReason",
    "DegradeResult",
    "DegradeTier",
    "DocKind",
    "FetchStatus",
    "Fetcher",
    "HeadInfo",
    "InputRef",
    "LocateResult",
    "MemberEntry",
    "PaperMeta",
    "ParkedError",
    "RateLimiter",
    "SniffError",
    "SniffResult",
    "SourceCache",
    "SrcResult",
    "UnpackError",
    "UnpackResult",
    "VersionInfo",
    "WrapperVerdict",
    "acquire_source",
    "check_pdf_wrapper",
    "degrade",
    "fetch_metadata",
    "locate",
    "normalize_arxiv_id",
    "path_class",
    "resolve_version",
    "sniff",
    "unpack_single",
    "unpack_sniffed",
    "unpack_tar",
    "write_manifest",
]
