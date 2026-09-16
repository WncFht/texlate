import gzip
import io
import json
import os
import tarfile
import time
from pathlib import Path

import httpx
import pytest

from texlate.arxiv.cache import CacheError, SourceCache
from texlate.arxiv.fetch import (
    AcquireStatus,
    Fetcher,
    FetchStatus,
    acquire_source,
    normalize_arxiv_id,
)
from texlate.arxiv.ratelimit import RateLimiter


class _Clock:
    """注入限速器的假时钟：sleep 即前进。"""

    def __init__(self) -> None:
        self.t = 1_700_000_000.0

    def now(self) -> float:
        return self.t

    def sleep(self, d: float) -> None:
        self.t += d


def _tar_gz(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return gzip.compress(buf.getvalue())


TINY_TEX = b"\\documentclass{article}\n\\begin{document}hi\\end{document}\n"
TINY_TAR_GZ = _tar_gz({"main.tex": TINY_TEX, "figs/x.eps": b"EPS"})
VER_2 = 2


def _head_headers(arxiv_id: str, ver: int, ext: str, etag: str) -> dict[str, str]:
    return {
        "content-disposition": f'attachment; filename="arXiv-{arxiv_id}v{ver}{ext}"',
        "etag": etag,
        "content-length": "1234",
    }


def _fetcher(handler: httpx.MockTransport, clk: _Clock) -> Fetcher:
    client = httpx.Client(transport=handler)
    return Fetcher(
        RateLimiter(clock=clk.now, sleep=clk.sleep),
        client=client,
        hosts=("arxiv.org", "export.arxiv.org"),
        sleep=clk.sleep,
    )


def test_normalize_arxiv_id() -> None:
    assert normalize_arxiv_id("1412.6980") == ("1412.6980", None)
    assert normalize_arxiv_id("1412.6980v3") == ("1412.6980", 3)
    assert normalize_arxiv_id("arXiv:hep-th/9901001") == ("hep-th/9901001", None)
    assert normalize_arxiv_id("hep-th/9901001v2") == ("hep-th/9901001", 2)
    assert normalize_arxiv_id("https://arxiv.org/abs/1412.6980v3") == ("1412.6980", 3)
    assert normalize_arxiv_id("https://arxiv.org/pdf/1412.6980") == ("1412.6980", None)


def test_head_src_parses_version_format() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "HEAD"
        return httpx.Response(
            HTTP_OK,
            headers=_head_headers("2001.00001", 2, ".tar.gz", '"E1"'),
        )

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    head = f.head_src("2001.00001")
    assert head.resolved_version == VER_2
    assert head.kind_hint == "tar.gz"
    assert head.etag == '"E1"'


def test_get_src_ok_sniffs_tar() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTP_OK, headers=_head_headers("2001.00001", 1, ".tar.gz", '"E1"')
            )
        return httpx.Response(HTTP_OK, content=TINY_TAR_GZ)

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    res = f.get_src("2001.00001")
    assert res.status is FetchStatus.OK
    assert res.sniffed is not None
    assert res.sniffed.kind.value == "tar"


def test_get_src_304_and_404() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            if "missing" in req.url.path:
                return httpx.Response(HTTP_NOT_FOUND)
            return httpx.Response(
                HTTP_OK, headers=_head_headers("2001.00001", 1, ".tar.gz", '"E1"')
            )
        if req.headers.get("if-none-match") == '"E1"':
            return httpx.Response(HTTP_NOT_MODIFIED)
        return httpx.Response(HTTP_OK, content=TINY_TAR_GZ)

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    res = f.get_src("2001.00001", etag='"E1"')
    assert res.status is FetchStatus.NOT_MODIFIED
    res404 = f.get_src("missing/9999999")
    assert res404.status is FetchStatus.NOT_FOUND


def test_failover_to_export_host() -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.host)
        if req.url.host == "arxiv.org":
            msg = "down"
            raise httpx.ConnectError(msg, request=req)
        return httpx.Response(
            HTTP_OK, headers=_head_headers("2001.00001", 1, ".gz", '"E1"')
        )

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    head = f.head_src("2001.00001")
    assert head.kind_hint == "gz"
    assert "arxiv.org" in calls
    assert "export.arxiv.org" in calls


def test_acquire_end_to_end_and_cache_hit(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTP_OK, headers=_head_headers("2001.00001", 1, ".tar.gz", '"E1"')
            )
        return httpx.Response(HTTP_OK, content=TINY_TAR_GZ)

    clk = _Clock()
    f = _fetcher(httpx.MockTransport(handler), clk)
    cache = SourceCache(tmp_path / "cache")
    res = acquire_source("2001.00001", fetcher=f, cache=cache)
    assert res.status is AcquireStatus.OK
    assert res.resolved_version == 1
    assert res.entry is not None
    entry_dir = res.entry.dir
    assert (entry_dir / "raw.tar.gz").exists()
    assert (entry_dir / "extracted" / "main.tex").read_bytes() == TINY_TEX
    meta = json.loads((entry_dir / "meta.json").read_text())
    assert meta["arxiv_id"] == "2001.00001"
    assert meta["locate"]["main"] == "main.tex"

    res2 = acquire_source("2001.00001", fetcher=f, cache=cache)
    assert res2.status is AcquireStatus.HIT


def test_acquire_pdf_only(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTP_OK, headers=_head_headers("2001.00002", 1, ".pdf", '"P1"')
            )
        return httpx.Response(HTTP_OK, content=b"%PDF-1.4 fake")

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    res = acquire_source("2001.00002", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.PDF_ONLY


def test_normalize_pdf_suffix_and_bare_host() -> None:
    assert normalize_arxiv_id("https://arxiv.org/pdf/1412.6980.pdf") == (
        "1412.6980",
        None,
    )
    assert normalize_arxiv_id("arxiv.org/abs/1412.6980v2") == ("1412.6980", 2)


def test_bad_id_rejected_before_network(tmp_path: Path) -> None:
    """``a/../b`` 形 id：URL 归一化后能拿 200，但缓存键会被污染/逃逸——取源前拒。"""
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(HTTP_OK)

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    res = acquire_source("a/../b", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.ERROR
    assert "bad_id" in res.detail
    assert not calls  # 一次请求都不发
    with pytest.raises(ValueError, match="bad arxiv id"):
        f.head_src("../x")
    with pytest.raises(ValueError, match="bad arxiv id"):
        f.get_src("..")


def test_cache_key_traversal_defense(tmp_path: Path) -> None:
    """缓存层兜底：entry_dir 逃逸拒、find_versions glob 元字符空集。"""
    cache = SourceCache(tmp_path)
    with pytest.raises(CacheError, match="escapes"):
        cache.entry_dir("../x", 1)
    assert cache.find_versions("*") == []
    assert cache.find_versions("../x") == []


def test_hit_passthrough_terminal_status(tmp_path: Path) -> None:
    """pdf_only 条目 etag 命中 → 透传 pdf_only（不伪装成 cache_hit）。

    伪装 hit 的下游代价：cli/e2e 把 HIT 当 OK，对着不存在的 extracted/ 跑。
    """

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTP_OK, headers=_head_headers("2001.00002", 1, ".pdf", '"P1"')
            )
        return httpx.Response(HTTP_OK, content=b"%PDF-1.4 fake")

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    cache = SourceCache(tmp_path)
    res1 = acquire_source("2001.00002", fetcher=f, cache=cache)
    assert res1.status is AcquireStatus.PDF_ONLY
    res2 = acquire_source("2001.00002", fetcher=f, cache=cache)
    assert res2.status is AcquireStatus.PDF_ONLY


def test_304_passthrough_terminal_status(tmp_path: Path) -> None:
    """etag 变了但 GET 回 304 → 同样透传缓存终态。"""
    state = {"etag": '"P1"', "got": False}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTP_OK,
                headers=_head_headers("2001.00002", 1, ".pdf", state["etag"]),
            )
        if not state["got"]:
            state["got"] = True
            return httpx.Response(HTTP_OK, content=b"%PDF-1.4 fake")
        return httpx.Response(HTTP_NOT_MODIFIED)

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    cache = SourceCache(tmp_path)
    acquire_source("2001.00002", fetcher=f, cache=cache)
    state["etag"] = '"P2"'
    res = acquire_source("2001.00002", fetcher=f, cache=cache)
    assert res.status is AcquireStatus.PDF_ONLY


def test_get_newer_version_commits_resolved(tmp_path: Path) -> None:
    """HEAD 解 v1、GET 已发 v2 → 按 GET 的 cd 钉 v2（版本漂移不错位缓存键）。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTP_OK, headers=_head_headers("2001.00003", 1, ".tar.gz", '"E1"')
            )
        return httpx.Response(
            HTTP_OK,
            content=TINY_TAR_GZ,
            headers={
                "content-disposition": "attachment; "
                'filename="arXiv-2001.00003v2.tar.gz"',
                "etag": '"E2"',
            },
        )

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    cache = SourceCache(tmp_path)
    res = acquire_source("2001.00003", fetcher=f, cache=cache)
    assert res.status is AcquireStatus.OK
    assert res.resolved_version == VER_2
    assert res.entry is not None
    assert res.entry.dir.name == "2001.00003v2"
    meta = json.loads((res.entry.dir / "meta.json").read_text())
    assert meta["etag"] == '"E2"'


def test_commit_old_style_id_on_fresh_cache(tmp_path: Path) -> None:
    """旧式 id（cond-mat/…）的 dest 嵌在子目录——commit 需自建父目录。"""
    cache = SourceCache(tmp_path / "cache")
    staging = cache.stage()
    (staging / "meta.json").write_text('{"etag": "\\"E1\\""}', encoding="utf-8")
    entry = cache.commit(staging, "cond-mat/0408438", 1)
    assert entry.dir == tmp_path / "cache" / "cond-mat" / "0408438v1"
    assert (entry.dir / "meta.json").is_file()
    assert cache.get("cond-mat/0408438", 1) is not None


def _online_seed(handler: httpx.MockTransport, tmp_path: Path) -> Fetcher:
    """先在线取一遍铺缓存，返回同一个 fetcher 供离线臂复用。"""
    f = _fetcher(handler, _Clock())
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.OK
    return f


def test_offline_hit_zero_network(tmp_path: Path) -> None:
    """offline=True：钉版/未钉版命中都零请求；未钉版取已缓存版。"""
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if req.method == "HEAD":
            return httpx.Response(
                HTTP_OK, headers=_head_headers("2001.00001", 1, ".tar.gz", '"E1"')
            )
        return httpx.Response(HTTP_OK, content=TINY_TAR_GZ)

    f = _online_seed(httpx.MockTransport(handler), tmp_path)
    cache = SourceCache(tmp_path)
    calls.clear()

    hit = acquire_source("2001.00001", fetcher=f, cache=cache, offline=True)
    assert hit.status is AcquireStatus.HIT
    assert hit.resolved_version == 1
    assert hit.entry is not None
    assert hit.detail == "offline"

    hit_pin = acquire_source("2001.00001v1", fetcher=f, cache=cache, offline=True)
    assert hit_pin.status is AcquireStatus.HIT
    hit_kw = acquire_source(
        "2001.00001", fetcher=f, cache=cache, version=1, offline=True
    )
    assert hit_kw.status is AcquireStatus.HIT
    assert not calls  # 一次请求都不发


def test_offline_miss_no_silent_fallback(tmp_path: Path) -> None:
    """offline 无缓存/钉错版 → error/offline_no_cache，不静默换版也不上网。"""
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if req.method == "HEAD":
            return httpx.Response(
                HTTP_OK, headers=_head_headers("2001.00001", 1, ".tar.gz", '"E1"')
            )
        return httpx.Response(HTTP_OK, content=TINY_TAR_GZ)

    transport = httpx.MockTransport(handler)
    cache = SourceCache(tmp_path)
    f = _fetcher(transport, _Clock())
    res = acquire_source("2001.00001", fetcher=f, cache=cache, offline=True)
    assert res.status is AcquireStatus.ERROR
    assert "offline_no_cache" in res.detail
    assert not calls

    f = _online_seed(transport, tmp_path)
    calls.clear()
    miss = acquire_source("2001.00001v9", fetcher=f, cache=cache, offline=True)
    assert miss.status is AcquireStatus.ERROR
    assert "offline_no_cache:2001.00001v9" in miss.detail
    other = acquire_source("2001.00002", fetcher=f, cache=cache, offline=True)
    assert other.status is AcquireStatus.ERROR
    assert not calls


def test_offline_hit_passthrough_terminal_status(tmp_path: Path) -> None:
    """pdf_only 条目离线命中同样透传终态（不伪装 cache_hit）。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTP_OK, headers=_head_headers("2001.00002", 1, ".pdf", '"P1"')
            )
        return httpx.Response(HTTP_OK, content=b"%PDF-1.4 fake")

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    cache = SourceCache(tmp_path)
    seeded = acquire_source("2001.00002", fetcher=f, cache=cache)
    assert seeded.status is AcquireStatus.PDF_ONLY
    res = acquire_source("2001.00002", fetcher=f, cache=cache, offline=True)
    assert res.status is AcquireStatus.PDF_ONLY
    assert res.detail == "offline"


HTTP_OK = 200
HTTP_NOT_MODIFIED = 304
HTTP_NOT_FOUND = 404


# ---- 小流量实测（默认跳过，TEXLATE_LIVE=1 打开） ----
LIVE = pytest.mark.skipif(
    not os.environ.get("TEXLATE_LIVE"),
    reason="live arXiv traffic gated on TEXLATE_LIVE=1",
)


@LIVE
def test_live_fetch_diverse(tmp_path: Path) -> None:
    """3 个真实 ID（tar / 单文件 gz / pdf-wrapper），真限速真 pacing。"""
    fetcher = Fetcher(
        RateLimiter(tmp_path / "rl.json"),
        sleep=time.sleep,
    )
    cache = SourceCache(tmp_path / "cache")
    cases = {
        "2203.02155": AcquireStatus.OK,  # 多文件 tar
        "math/0404188": AcquireStatus.OK,  # 旧式 id 单文件 .gz
        "1412.6980": AcquireStatus.OK,  # includepdf wrapper（v9+ 有 .tex 源）
    }
    for arxiv_id, want in cases.items():
        res = acquire_source(arxiv_id, fetcher=fetcher, cache=cache)
        assert res.status is want, f"{arxiv_id}: {res.status} {res.detail}"
        assert res.entry is not None
        assert (res.entry.dir / "meta.json").exists()
    wrapper = cache.get_latest("1412.6980")
    assert wrapper is not None
    assert wrapper.meta.get("locate", {}).get("pdf_wrapper") is True
