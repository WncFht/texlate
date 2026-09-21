import json
import math
import os
import time
from http import HTTPStatus
from pathlib import Path

import httpx
import pytest
from conftest import FakeClock, make_targz, mk_fetcher

from texlate.arxiv import fetch as fetch_mod
from texlate.arxiv.cache import SourceCache
from texlate.arxiv.fetch import (
    AcquireStatus,
    Fetcher,
    FetchStatus,
    acquire_source,
    normalize_arxiv_id,
)
from texlate.arxiv.ratelimit import RateLimiter

TINY_TEX = b"\\documentclass{article}\n\\begin{document}hi\\end{document}\n"
TINY_TAR_GZ = make_targz({"main.tex": TINY_TEX, "figs/x.eps": b"EPS"})
VER_2 = 2

#: Atom feed：entry id 带 ``v2``——裸 id 查询时 resolved_version=2 即 feed
#: 宣告的最新版（Atom 无版本史，仅这一字段可取最新版号）。
_ATOM_LATEST_V2 = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2001.00001v2</id>
    <title>Mock</title>
  </entry>
</feed>"""


def _head_headers(arxiv_id: str, ver: int, ext: str, etag: str) -> dict[str, str]:
    return {
        "content-disposition": f'attachment; filename="arXiv-{arxiv_id}v{ver}{ext}"',
        "etag": etag,
        "content-length": "1234",
    }


def test_normalize_arxiv_id() -> None:
    assert normalize_arxiv_id("1412.6980") == ("1412.6980", None)
    assert normalize_arxiv_id("1412.6980v3") == ("1412.6980", 3)
    assert normalize_arxiv_id("arXiv:hep-th/9901001") == ("hep-th/9901001", None)
    assert normalize_arxiv_id("hep-th/9901001v2") == ("hep-th/9901001", 2)
    assert normalize_arxiv_id("https://arxiv.org/abs/1412.6980v3") == ("1412.6980", 3)
    assert normalize_arxiv_id("https://arxiv.org/pdf/1412.6980") == ("1412.6980", None)


def test_fetcher_close_idempotent() -> None:
    """``close()`` 委托内建 client 关池——幂等，重复调用安全。"""
    f = Fetcher()
    assert not f.client.is_closed
    f.close()
    assert f.client.is_closed
    f.close()


def test_fetcher_context_manager() -> None:
    """``with Fetcher()`` 出块自动关连接池。"""
    with Fetcher() as f:
        assert not f.client.is_closed
    assert f.client.is_closed


def test_head_src_parses_version_format() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "HEAD"
        return httpx.Response(
            HTTPStatus.OK,
            headers=_head_headers("2001.00001", 2, ".tar.gz", '"E1"'),
        )

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    head = f.head_src("2001.00001")
    assert head.resolved_version == VER_2
    assert head.kind_hint == "tar.gz"
    assert head.etag == '"E1"'


def test_get_src_ok_sniffs_tar() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTPStatus.OK, headers=_head_headers("2001.00001", 1, ".tar.gz", '"E1"')
            )
        return httpx.Response(HTTPStatus.OK, content=TINY_TAR_GZ)

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    res = f.get_src("2001.00001")
    assert res.status is FetchStatus.OK
    assert res.sniffed is not None
    assert res.sniffed.kind.value == "tar"


def test_get_src_304_and_404() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            if "missing" in req.url.path:
                return httpx.Response(HTTPStatus.NOT_FOUND)
            return httpx.Response(
                HTTPStatus.OK, headers=_head_headers("2001.00001", 1, ".tar.gz", '"E1"')
            )
        if req.headers.get("if-none-match") == '"E1"':
            return httpx.Response(HTTPStatus.NOT_MODIFIED)
        return httpx.Response(HTTPStatus.OK, content=TINY_TAR_GZ)

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
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
            HTTPStatus.OK, headers=_head_headers("2001.00001", 1, ".gz", '"E1"')
        )

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    head = f.head_src("2001.00001")
    assert head.kind_hint == "gz"
    assert "arxiv.org" in calls
    assert "export.arxiv.org" in calls


def test_env_proxy_transport_failure_falls_back_direct(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """env 代理全 host 传输失败 → ``trust_env=False`` 直连臂兜底并粘住。"""
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")
    proxied: list[str] = []
    direct: list[str] = []

    def dead(request: httpx.Request) -> httpx.Response:
        proxied.append(request.url.host)
        msg = "conn refused"
        raise httpx.ConnectError(msg, request=request)

    def live(request: httpx.Request) -> httpx.Response:
        direct.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(
                HTTPStatus.OK, headers=_head_headers("2001.00001", 1, ".tar.gz", '"E1"')
            )
        return httpx.Response(HTTPStatus.OK, content=TINY_TAR_GZ)

    def fake_make(*, trust_env: bool) -> httpx.Client:
        handler = dead if trust_env else live
        return httpx.Client(
            transport=httpx.MockTransport(handler), follow_redirects=True
        )

    monkeypatch.setattr(fetch_mod, "_make_client", fake_make)
    clk = FakeClock()
    f = Fetcher(
        RateLimiter(clock=clk.now, sleep=clk.sleep),
        hosts=("arxiv.org", "export.arxiv.org"),
        sleep=clk.sleep,
    )
    try:
        res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
        assert res.status is AcquireStatus.OK
        assert len(proxied) == (len(fetch_mod.RETRY_DELAYS) + 1) * len(f.hosts)
        assert direct == ["HEAD", "GET"]  # GET 走粘住的直连臂
    finally:
        f.close()


def test_no_env_proxy_no_direct_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """无 env 代理：传输全灭直接报错，不开直连臂。"""
    for k in ("https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(k, raising=False)

    def dead(request: httpx.Request) -> httpx.Response:
        msg = "conn refused"
        raise httpx.ConnectError(msg, request=request)

    monkeypatch.setattr(
        fetch_mod,
        "_make_client",
        lambda **_: httpx.Client(
            transport=httpx.MockTransport(dead), follow_redirects=True
        ),
    )
    clk = FakeClock()
    f = Fetcher(
        RateLimiter(clock=clk.now, sleep=clk.sleep),
        hosts=("arxiv.org",),
        sleep=clk.sleep,
    )
    try:
        res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
        assert res.status is AcquireStatus.ERROR
        assert f._direct_client is None  # noqa: SLF001 -- 断言兜底臂未建
    finally:
        f.close()


def test_acquire_end_to_end_and_cache_hit(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTPStatus.OK, headers=_head_headers("2001.00001", 1, ".tar.gz", '"E1"')
            )
        return httpx.Response(HTTPStatus.OK, content=TINY_TAR_GZ)

    clk = FakeClock()
    f = mk_fetcher(httpx.MockTransport(handler), clk)
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
                HTTPStatus.OK, headers=_head_headers("2001.00002", 1, ".pdf", '"P1"')
            )
        return httpx.Response(HTTPStatus.OK, content=b"%PDF-1.4 fake")

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    res = acquire_source("2001.00002", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.PDF_ONLY


def test_normalize_pdf_suffix_and_bare_host() -> None:
    assert normalize_arxiv_id("https://arxiv.org/pdf/1412.6980.pdf") == (
        "1412.6980",
        None,
    )
    assert normalize_arxiv_id("arxiv.org/abs/1412.6980v2") == ("1412.6980", 2)


def test_normalize_version_zero_is_bad_id() -> None:
    """``v0``/``v00`` 非合法版本——不算钉版，落到非法 id 统一拒。"""
    assert normalize_arxiv_id("1412.6980v0") == ("1412.6980v0", None)
    assert normalize_arxiv_id("1412.6980v00") == ("1412.6980v00", None)
    assert normalize_arxiv_id("1412.6980v01") == ("1412.6980", 1)


def test_version_zero_kwarg_rejected(tmp_path: Path) -> None:
    """显式 ``version=0``：`_src_url` 的 ``if version`` 会把 0 当未钉版发——
    静默按最新版取还把 requested_version=0 写进 meta，按调用方错误拒。"""
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(HTTPStatus.OK)

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    res = acquire_source(
        "2001.00001", fetcher=f, cache=SourceCache(tmp_path), version=0
    )
    assert res.status is AcquireStatus.ERROR
    assert "bad_version" in res.detail
    assert not calls
    with pytest.raises(ValueError, match="bad arxiv id"):
        f.head_src("2001.00001", version=0)
    with pytest.raises(ValueError, match="bad arxiv id"):
        f.get_src("2001.00001", version=0)


def test_decode_error_classified_not_crash(tmp_path: Path) -> None:
    """``content-encoding: gzip`` + 坏 body → DecodingError（RequestError 而非
    TransportError）——必须归 ERROR 而不是崩出 acquire_source。"""
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTPStatus.OK, headers=_head_headers("2001.00001", 1, ".tar.gz", '"E1"')
            )
        calls.append(req.url.host)
        return httpx.Response(
            HTTPStatus.OK,
            content=b"not-a-gzip-body",
            headers={"content-encoding": "gzip"},
        )

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.ERROR
    # 确定性解码失败不原地重试（白烧预算）；每 host 恰一次 = 纯 failover
    assert sorted(calls) == ["arxiv.org", "export.arxiv.org"]


def test_redirect_loop_classified_not_crash(tmp_path: Path) -> None:
    """重定向环 → TooManyRedirects（RequestError）——归类 ERROR 不崩。"""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"location": str(req.url)})

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    clk = FakeClock()
    f = Fetcher(
        RateLimiter(clock=clk.now, sleep=clk.sleep),
        client=client,
        hosts=("arxiv.org",),
        sleep=clk.sleep,
    )
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.ERROR


def test_cd_filename_case_insensitive(tmp_path: Path) -> None:
    """cd 文件名大写扩展名 ``arXiv-xV2.TAR.GZ``——版本号与格式提示仍解出。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTPStatus.OK,
                headers={
                    "content-disposition": (
                        'attachment; filename="arXiv-2001.00001V2.TAR.GZ"'
                    ),
                    "etag": '"E1"',
                },
            )
        return httpx.Response(HTTPStatus.OK, content=TINY_TAR_GZ)

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    head = f.head_src("2001.00001")
    assert head.resolved_version == VER_2
    assert head.kind_hint == "tar.gz"

    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.OK
    assert res.resolved_version == VER_2


def test_bad_id_rejected_before_network(tmp_path: Path) -> None:
    """``a/../b`` 形 id：URL 归一化后能拿 200，但缓存键会被污染/逃逸——取源前拒。"""
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(HTTPStatus.OK)

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    res = acquire_source("a/../b", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.ERROR
    assert "bad_id" in res.detail
    assert not calls  # 一次请求都不发
    with pytest.raises(ValueError, match="bad arxiv id"):
        f.head_src("../x")
    with pytest.raises(ValueError, match="bad arxiv id"):
        f.get_src("..")


def test_hit_passthrough_terminal_status(tmp_path: Path) -> None:
    """pdf_only 条目 etag 命中 → 透传 pdf_only（不伪装成 cache_hit）。

    伪装 hit 的下游代价：cli/e2e 把 HIT 当 OK，对着不存在的 extracted/ 跑。
    """

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTPStatus.OK, headers=_head_headers("2001.00002", 1, ".pdf", '"P1"')
            )
        return httpx.Response(HTTPStatus.OK, content=b"%PDF-1.4 fake")

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
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
                HTTPStatus.OK,
                headers=_head_headers("2001.00002", 1, ".pdf", state["etag"]),
            )
        if not state["got"]:
            state["got"] = True
            return httpx.Response(HTTPStatus.OK, content=b"%PDF-1.4 fake")
        return httpx.Response(HTTPStatus.NOT_MODIFIED)

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    cache = SourceCache(tmp_path)
    acquire_source("2001.00002", fetcher=f, cache=cache)
    state["etag"] = '"P2"'
    res = acquire_source("2001.00002", fetcher=f, cache=cache)
    assert res.status is AcquireStatus.PDF_ONLY


def test_hit_stale_hint_when_feed_newer(tmp_path: Path) -> None:
    """§1.4：钉 v1 命中、feed 宣告 v2 → hit 带 ``stale:v2`` 提示（不自动升级）。

    etag-hit 与 304-hit 两条命中臂共用同一 stale 探测，都覆盖到。
    """
    state = {"etag": '"E1"'}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTPStatus.OK,
                headers=_head_headers("2001.00001", 1, ".tar.gz", state["etag"]),
            )
        if "/api/query" in req.url.path:
            return httpx.Response(HTTPStatus.OK, content=_ATOM_LATEST_V2.encode())
        if req.headers.get("if-none-match") == '"E1"':
            return httpx.Response(HTTPStatus.NOT_MODIFIED)
        return httpx.Response(HTTPStatus.OK, content=TINY_TAR_GZ)

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    cache = SourceCache(tmp_path)
    seeded = acquire_source("2001.00001v1", fetcher=f, cache=cache)
    assert seeded.status is AcquireStatus.OK

    hit = acquire_source("2001.00001v1", fetcher=f, cache=cache)
    assert hit.status is AcquireStatus.HIT
    assert hit.warnings == ["stale:v2 available"]

    # HEAD etag 变了但 GET 仍 304 → 304-hit 臂同样报 stale
    state["etag"] = '"E2"'
    hit304 = acquire_source("2001.00001v1", fetcher=f, cache=cache)
    assert hit304.status is AcquireStatus.HIT
    assert hit304.warnings == ["stale:v2 available"]


def test_hit_no_stale_when_pinned_is_latest(tmp_path: Path) -> None:
    """钉的就是 feed 最新版 → hit 干净（不误报 stale）。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTPStatus.OK, headers=_head_headers("2001.00001", 2, ".tar.gz", '"E1"')
            )
        if "/api/query" in req.url.path:
            return httpx.Response(HTTPStatus.OK, content=_ATOM_LATEST_V2.encode())
        return httpx.Response(HTTPStatus.OK, content=TINY_TAR_GZ)

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    cache = SourceCache(tmp_path)
    acquire_source("2001.00001v2", fetcher=f, cache=cache)
    hit = acquire_source("2001.00001v2", fetcher=f, cache=cache)
    assert hit.status is AcquireStatus.HIT
    assert hit.warnings == []


def test_hit_stale_unpinned_feed_ahead(tmp_path: Path) -> None:
    """未钉版：HEAD 解到已缓存旧版（src CDN 滞后）、feed 已宣告新版 → stale。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTPStatus.OK, headers=_head_headers("2001.00001", 1, ".tar.gz", '"E1"')
            )
        if "/api/query" in req.url.path:
            return httpx.Response(HTTPStatus.OK, content=_ATOM_LATEST_V2.encode())
        return httpx.Response(HTTPStatus.OK, content=TINY_TAR_GZ)

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    cache = SourceCache(tmp_path)
    acquire_source("2001.00001", fetcher=f, cache=cache)
    hit = acquire_source("2001.00001", fetcher=f, cache=cache)
    assert hit.status is AcquireStatus.HIT
    assert hit.resolved_version == 1
    assert hit.warnings == ["stale:v2 available"]


def test_hit_stale_check_survives_meta_outage(tmp_path: Path) -> None:
    """stale 探测 best-effort：Atom/OAI 全挂 → warnings 空，hit 不受影响。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTPStatus.OK, headers=_head_headers("2001.00001", 1, ".tar.gz", '"E1"')
            )
        if "/api/query" in req.url.path or req.url.path == "/oai":
            msg = "meta down"
            raise httpx.ConnectError(msg, request=req)
        return httpx.Response(HTTPStatus.OK, content=TINY_TAR_GZ)

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    cache = SourceCache(tmp_path)
    acquire_source("2001.00001v1", fetcher=f, cache=cache)
    hit = acquire_source("2001.00001v1", fetcher=f, cache=cache)
    assert hit.status is AcquireStatus.HIT
    assert hit.warnings == []


def test_get_newer_version_commits_resolved(tmp_path: Path) -> None:
    """HEAD 解 v1、GET 已发 v2 → 按 GET 的 cd 钉 v2（版本漂移不错位缓存键）。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTPStatus.OK, headers=_head_headers("2001.00003", 1, ".tar.gz", '"E1"')
            )
        return httpx.Response(
            HTTPStatus.OK,
            content=TINY_TAR_GZ,
            headers={
                "content-disposition": "attachment; "
                'filename="arXiv-2001.00003v2.tar.gz"',
                "etag": '"E2"',
            },
        )

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    cache = SourceCache(tmp_path)
    res = acquire_source("2001.00003", fetcher=f, cache=cache)
    assert res.status is AcquireStatus.OK
    assert res.resolved_version == VER_2
    assert res.entry is not None
    assert res.entry.dir.name == "2001.00003v2"
    meta = json.loads((res.entry.dir / "meta.json").read_text())
    assert meta["etag"] == '"E2"'


def _online_seed(handler: httpx.MockTransport, tmp_path: Path) -> Fetcher:
    """先在线取一遍铺缓存，返回同一个 fetcher 供离线臂复用。"""
    f = mk_fetcher(handler, FakeClock())
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
                HTTPStatus.OK, headers=_head_headers("2001.00001", 1, ".tar.gz", '"E1"')
            )
        return httpx.Response(HTTPStatus.OK, content=TINY_TAR_GZ)

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
                HTTPStatus.OK, headers=_head_headers("2001.00001", 1, ".tar.gz", '"E1"')
            )
        return httpx.Response(HTTPStatus.OK, content=TINY_TAR_GZ)

    transport = httpx.MockTransport(handler)
    cache = SourceCache(tmp_path)
    f = mk_fetcher(transport, FakeClock())
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
                HTTPStatus.OK, headers=_head_headers("2001.00002", 1, ".pdf", '"P1"')
            )
        return httpx.Response(HTTPStatus.OK, content=b"%PDF-1.4 fake")

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    cache = SourceCache(tmp_path)
    seeded = acquire_source("2001.00002", fetcher=f, cache=cache)
    assert seeded.status is AcquireStatus.PDF_ONLY
    res = acquire_source("2001.00002", fetcher=f, cache=cache, offline=True)
    assert res.status is AcquireStatus.PDF_ONLY
    assert res.detail == "offline"


# ---- 小流量实测（默认跳过，TEXLATE_LIVE=1 打开） ----
LIVE = pytest.mark.skipif(
    not os.environ.get("TEXLATE_LIVE"),
    reason="live arXiv traffic gated on TEXLATE_LIVE=1",
)


@pytest.mark.integration
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


# ----------------------------------------------------- Retry-After 上限


def test_retry_delay_huge_finite_retry_after_terminal() -> None:
    """``Retry-After: 1000000``（≈11.5 天）视同不可兑现 → 归 inf 终态不真睡。

    ≤``MAX_RETRY_AFTER_S`` 仍从其值；nan 沿用 ``max(delay, nan)=delay`` 回落。
    """
    huge = httpx.Response(429, headers={"retry-after": "1000000"})
    assert math.isinf(fetch_mod._retry_delay("https://arxiv.org/src/x", 1, huge))  # noqa: SLF001
    ok = httpx.Response(429, headers={"retry-after": "60"})
    d_ok = fetch_mod._retry_delay("https://arxiv.org/src/x", 1, ok)  # noqa: SLF001
    assert d_ok == pytest.approx(60.0)
    nan = httpx.Response(429, headers={"retry-after": "nan"})
    d = fetch_mod._retry_delay("https://arxiv.org/src/x", 1, nan)  # noqa: SLF001
    assert d == pytest.approx(10.0, rel=0.2)  # 回落 10s±20% jitter 区间


def test_request_huge_retry_after_sleeps_nothing() -> None:
    """端面实证：429+``Retry-After: 1e6`` → 不睡巨值、429 原样上交终态。"""
    clk = FakeClock()

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "1000000"})

    f = Fetcher(
        RateLimiter(clock=clk.now, sleep=clk.sleep),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        hosts=("arxiv.org",),
        sleep=clk.sleep,
    )
    resp = f._request("GET", "https://arxiv.org/src/x", {})  # noqa: SLF001
    assert resp.status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert clk.slept == []  # 首请求无 pacing 等待、inf 退避 break——零睡眠
