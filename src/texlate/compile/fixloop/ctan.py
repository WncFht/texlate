"""re-export shim —— 实现已上提 ``texlate.compile.ctan``（compile 层共享件）。

F2 地基归位：CTAN 拉包/tlpdb 索引是 compile 层共享件（``probe``/
``engine._xelatex``/``pipecore``/``worker`` 同层消费），不再寄居依赖
compile 的 fixloop 子包。旧路径 ``texlate.compile.fixloop.ctan`` 名面
转口守恒（``__init__``/``probe``/``_xelatex``/``worker``/tests 等旧
import 不动，含私名面——``fixloop.ctan._X`` monkeypatch 锚点续用）；
新代码一律直引 ``texlate.compile.ctan``。
"""

from texlate.compile.ctan import (  # noqa: F401
    _MEMBER_DRIVE_RE,
    _NEEDFMT_RE,
    _PKGLATER_RE,
    _RUNFILES_ONLY_EXTS,
    _TAR_PREFIXES,
    _TLPDB_FILE_SECTIONS,
    DEFAULT_CAPS,
    DEFAULT_DOWNLOAD_CAP,
    DEFAULT_INFLATED_CAP,
    DEFAULT_MEMBER_CAP,
    DEFAULT_MEMBERS_CAP,
    DEFAULT_TOTAL_CAP,
    INDEX_EXTS,
    MIRROR,
    OVERLAY_EXTS,
    TLPDB_RELPATH,
    CtanFetcher,
    CtanFetchError,
    FetchCaps,
    Fetcher,
    FetchResult,
    TlpdbIndex,
    _check_member_caps,
    _decompress_xz,
    _fetch_capped,
    _http_get,
    _member_relpath,
    _norm_member_name,
    _overlay_gate,
    _overlay_members,
    check_version_compat,
    ctan_fetch,
    default_cache_dir,
    fetch_package,
    fetch_tlpdb,
)

__all__ = [
    "CtanFetchError",
    "CtanFetcher",
    "FetchCaps",
    "FetchResult",
    "TlpdbIndex",
    "check_version_compat",
    "ctan_fetch",
    "default_cache_dir",
    "fetch_package",
    "fetch_tlpdb",
]
