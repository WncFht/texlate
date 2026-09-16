import httpx
import pytest

from texlate.arxiv.fetch import Fetcher
from texlate.arxiv.meta import (
    DegradeReason,
    DegradeTier,
    degrade,
    fetch_metadata,
    resolve_version,
)
from texlate.arxiv.ratelimit import RateLimiter

HTTP_OK = 200
HTTP_NOT_FOUND = 404
HTTP_TOO_MANY = 429
HTTP_REDIRECT = 301
LATEST = 9
V2 = 2
V3 = 3
MISSING_VER = 99

ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1412.6980v9</id>
    <updated>2017-01-30T17:27:54Z</updated>
    <published>2014-12-22T13:54:29Z</published>
    <title>Adam: A Method for Stochastic Optimization</title>
    <summary>We introduce Adam,
      an algorithm.</summary>
    <author><name>Diederik P. Kingma</name></author>
    <author><name>Jimmy Ba</name></author>
    <arxiv:comment>ICLR 2015</arxiv:comment>
    <arxiv:journal_ref>ICLR 2015</arxiv:journal_ref>
    <arxiv:doi>10.48550/arXiv.1412.6980</arxiv:doi>
    <arxiv:primary_category term="cs.LG"/>
    <category term="cs.LG"/>
    <category term="stat.ML"/>
    <link rel="alternate" type="text/html" href="http://arxiv.org/abs/1412.6980v9"/>
    <link title="pdf" rel="related" type="application/pdf" href="http://arxiv.org/pdf/1412.6980v9"/>
  </entry>
</feed>"""

ATOM_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/api/errors</id>
    <title>Error</title>
    <summary>incorrect id format for 9999.99999</summary>
  </entry>
</feed>"""

OAI_RAW = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <responseDate>2026-09-14T13:32:46Z</responseDate>
  <request verb="GetRecord" identifier="oai:arXiv.org:1412.6980"
           metadataPrefix="arXivRaw">http://oaipmh.arxiv.org/oai</request>
  <GetRecord>
    <record>
      <header>
        <identifier>oai:arXiv.org:1412.6980</identifier>
        <datestamp>2017-01-31</datestamp>
        <setSpec>cs:cs:LG</setSpec>
      </header>
      <metadata>
        <arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/">
          <id>1412.6980</id>
          <submitter>Diederik P Kingma M.Sc.</submitter>
          <version version="v1">
            <date>Mon, 22 Dec 2014 13:54:29 GMT</date>
            <size>280kb</size>
            <source_type>D</source_type>
          </version>
          <version version="v2">
            <date>Sat, 17 Jan 2015 20:26:06 GMT</date>
            <size>283kb</size>
            <source_type>D</source_type>
          </version>
          <version version="v9">
            <date>Mon, 30 Jan 2017 01:27:54 GMT</date>
            <size>489kb</size>
            <source_type>D</source_type>
          </version>
          <title>Adam: A Method for Stochastic Optimization</title>
          <authors>Diederik P. Kingma and Jimmy Ba</authors>
          <categories>cs.LG stat.ML</categories>
          <comments>Published at ICLR 2015</comments>
          <license>http://arxiv.org/licenses/nonexclusive-distrib/1.0/</license>
          <abstract>We introduce Adam.</abstract>
        </arXivRaw>
      </metadata>
    </record>
  </GetRecord>
</OAI-PMH>"""

OAI_ERROR = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <responseDate>2026-09-14T13:32:46Z</responseDate>
  <error code="idDoesNotExist">No matching identifier</error>
</OAI-PMH>"""


class _Clock:
    """注入限速器的假时钟：sleep 即前进。"""

    def __init__(self) -> None:
        self.t = 1_700_000_000.0

    def now(self) -> float:
        return self.t

    def sleep(self, d: float) -> None:
        self.t += d


def _fetcher(
    handler: httpx.MockTransport, clk: _Clock, *, redirects: bool = False
) -> Fetcher:
    client = httpx.Client(transport=handler, follow_redirects=redirects)
    return Fetcher(
        RateLimiter(clock=clk.now, sleep=clk.sleep),
        client=client,
        hosts=("arxiv.org", "export.arxiv.org"),
        sleep=clk.sleep,
    )


def test_fetch_metadata_atom_parses_schema() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(HTTP_OK, content=ATOM_FEED.encode())

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    meta = fetch_metadata("1412.6980", fetcher=f)
    assert meta is not None
    assert meta.source == "atom"
    assert meta.arxiv_id == "1412.6980"
    assert meta.resolved_version == LATEST
    assert meta.title == "Adam: A Method for Stochastic Optimization"
    assert meta.authors == ("Diederik P. Kingma", "Jimmy Ba")
    assert meta.abstract == "We introduce Adam, an algorithm."
    assert meta.primary_category == "cs.LG"
    assert meta.categories == ("cs.LG", "stat.ML")
    assert meta.published == "2014-12-22T13:54:29Z"
    assert meta.updated == "2017-01-30T17:27:54Z"
    assert meta.doi == "10.48550/arXiv.1412.6980"
    assert meta.journal_ref == "ICLR 2015"
    assert meta.comment == "ICLR 2015"
    assert meta.links["abs"].endswith("/abs/1412.6980v9")
    assert meta.links["pdf"].endswith("/pdf/1412.6980v9")
    assert "id_list=1412.6980" in seen[0]


def test_fetch_metadata_pin_passthrough() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(HTTP_OK, content=ATOM_FEED.encode())

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    meta = fetch_metadata("1412.6980v3", fetcher=f)
    assert "id_list=1412.6980v3" in seen[0]
    assert meta is not None


def test_fetch_metadata_oai_fallback_on_error_entry() -> None:
    """Atom 错误 entry（坏 id 形态）→ OAI arXivRaw 兜底，版本史+license 到手。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if "/api/query" in req.url.path:
            return httpx.Response(HTTP_OK, content=ATOM_EMPTY.encode())
        return httpx.Response(HTTP_OK, content=OAI_RAW.encode())

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    meta = fetch_metadata("1412.6980", fetcher=f)
    assert meta is not None
    assert meta.source == "oai-raw"
    assert meta.resolved_version == LATEST
    assert meta.license == "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"
    assert [v.version for v in meta.versions] == [1, V2, LATEST]
    assert meta.versions[0].date == "2014-12-22T13:54:29Z"
    assert meta.published == "2014-12-22T13:54:29Z"
    assert meta.updated == "2017-01-30T01:27:54Z"
    assert meta.authors == ("Diederik P. Kingma", "Jimmy Ba")
    assert meta.submitter == "Diederik P Kingma M.Sc."
    assert meta.primary_category == "cs.LG"
    assert meta.categories == ("cs.LG", "stat.ML")


def test_fetch_metadata_oai_fallback_on_transport_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/api/query" in req.url.path:
            msg = "export down"
            raise httpx.ConnectError(msg, request=req)
        return httpx.Response(HTTP_OK, content=OAI_RAW.encode())

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    meta = fetch_metadata("1412.6980", fetcher=f)
    assert meta is not None
    assert meta.source == "oai-raw"


def test_fetch_metadata_none_when_both_fail() -> None:
    """Atom 传输挂 + OAI 错误 body（200+error 形态）→ None，不抛。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if "/api/query" in req.url.path:
            msg = "down"
            raise httpx.ConnectError(msg, request=req)
        return httpx.Response(HTTP_OK, content=OAI_ERROR.encode())

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    assert fetch_metadata("1412.6980", fetcher=f) is None


def test_fetch_metadata_bad_id_raises() -> None:
    f = _fetcher(httpx.MockTransport(lambda _req: httpx.Response(HTTP_OK)), _Clock())
    with pytest.raises(ValueError, match="bad arxiv id"):
        fetch_metadata("a/../b", fetcher=f)
    with pytest.raises(ValueError, match="bad arxiv id"):
        resolve_version("../x", fetcher=f)


def test_fetch_metadata_decode_error_none() -> None:
    """响应体解码失败（DecodingError）——归一成 None，不炸穿契约。"""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            HTTP_OK,
            content=b"not-a-gzip",
            headers={"content-encoding": "gzip"},
        )

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    assert fetch_metadata("1412.6980", fetcher=f) is None


def test_degrade_request_error_falls_through() -> None:
    """首选层 TooManyRedirects → 落次选层探测，不炸出 degrade。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.startswith("/pdf/"):
            return httpx.Response(HTTP_REDIRECT, headers={"location": str(req.url)})
        if req.url.path == "/html/1412.6980v1":
            return httpx.Response(HTTP_OK)
        return httpx.Response(HTTP_NOT_FOUND)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    clk = _Clock()
    f = Fetcher(
        RateLimiter(clock=clk.now, sleep=clk.sleep),
        client=client,
        hosts=("arxiv.org",),
        sleep=clk.sleep,
    )
    res = degrade("1412.6980v1", fetcher=f, reason=DegradeReason.STUB)
    assert res.tier is DegradeTier.HTML
    assert res.version == 1


def test_degrade_version_zero_raises() -> None:
    """``version=0`` 与 ``idv0`` 钉版一样按调用方错误拒。"""
    f = _fetcher(httpx.MockTransport(lambda _req: httpx.Response(HTTP_OK)), _Clock())
    with pytest.raises(ValueError, match="bad arxiv id"):
        degrade("1412.6980", fetcher=f, reason=DegradeReason.STUB, version=0)
    with pytest.raises(ValueError, match="bad arxiv id"):
        degrade("1412.6980v0", fetcher=f, reason=DegradeReason.STUB)


def test_resolve_version_via_atom() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(HTTP_OK, content=ATOM_FEED.encode())

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    assert resolve_version("1412.6980", fetcher=f) == LATEST
    assert resolve_version("1412.6980v3", fetcher=f) == V3
    assert resolve_version("1412.6980", want=V3, fetcher=f) == V3
    assert resolve_version("1412.6980", want=MISSING_VER, fetcher=f) is None
    assert resolve_version("1412.6980v99", fetcher=f) is None


def test_oai_version_history_sorted_and_v0_dropped() -> None:
    """乱序版本史 + v0 边界：published/updated 按版本号取真值，v0 不算版本。

    修复前 ``versions[0]``/``[-1]`` 信文档序（乱序源 published/updated 颠倒），
    ``v0`` 成立 has_version(0)/pin=0——版本从 v1 起，v<1 滤除。
    """
    body = b"""<?xml version="1.0"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <GetRecord><record><metadata>
    <arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/">
      <id>1234.5678</id>
      <version version="v3"><date>Wed, 01 Jan 2020 00:00:00 GMT</date></version>
      <version version="v0"><date>Sun, 01 Jan 1989 00:00:00 GMT</date></version>
      <version version="v1"><date>Tue, 02 Jan 1990 00:00:00 GMT</date></version>
      <title>t</title><authors>a</authors><categories>cs.LG</categories>
    </arXivRaw>
  </metadata></record></GetRecord>
</OAI-PMH>"""

    def handler(req: httpx.Request) -> httpx.Response:
        if "/api/query" in req.url.path:
            msg = "atom down"
            raise httpx.ConnectError(msg, request=req)
        return httpx.Response(HTTP_OK, content=body)

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    meta = fetch_metadata("1234.5678", fetcher=f)
    assert meta is not None
    assert [v.version for v in meta.versions] == [1, V3]  # v0 滤除 + 升序
    assert meta.published == "1990-01-02T00:00:00Z"  # v1 date，不是 v3
    assert meta.updated == "2020-01-01T00:00:00Z"  # v3 date
    assert not meta.has_version(0)
    assert resolve_version("1234.5678", want=0, fetcher=f) is None


def test_resolve_version_via_oai_when_atom_down() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/api/query" in req.url.path:
            return httpx.Response(HTTP_TOO_MANY)
        return httpx.Response(HTTP_OK, content=OAI_RAW.encode())

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    # 429×2 后 (export,api) 断路器 park → Atom 放弃 → OAI 版本史兜底
    assert resolve_version("1412.6980", fetcher=f) == LATEST
    assert resolve_version("1412.6980", want=V2, fetcher=f) == V2
    assert resolve_version("1412.6980", want=10, fetcher=f) is None


def test_resolve_version_none_when_nothing() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/api/query" in req.url.path:
            return httpx.Response(HTTP_OK, content=ATOM_EMPTY.encode())
        return httpx.Response(HTTP_OK, content=OAI_ERROR.encode())

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    assert resolve_version("9999.99999", fetcher=f) is None


def test_degrade_parse_failed_html_latest() -> None:
    """解析失败 → L2：裸 id 301 到最新版 → 命中 html 层，版本从 final URL 回收。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/html/1412.6980":
            return httpx.Response(
                HTTP_REDIRECT,
                headers={"location": "https://arxiv.org/html/1412.6980v9"},
            )
        if req.url.path == "/html/1412.6980v9":
            return httpx.Response(HTTP_OK)
        return httpx.Response(HTTP_NOT_FOUND)

    f = _fetcher(httpx.MockTransport(handler), _Clock(), redirects=True)
    res = degrade("1412.6980", fetcher=f, reason=DegradeReason.PARSE_FAILED)
    assert res.tier is DegradeTier.HTML
    assert res.url.endswith("/html/1412.6980v9")
    assert res.version == LATEST


def test_degrade_html_version_fallback() -> None:
    """最新版 HTML 404 → resolve_version 拿版本清单 → 逐版本回退命中 v2。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if "/api/query" in req.url.path:
            return httpx.Response(HTTP_OK, content=ATOM_FEED.encode())
        if req.url.path == "/html/1412.6980v2":
            return httpx.Response(HTTP_OK)
        return httpx.Response(HTTP_NOT_FOUND)

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    res = degrade("1412.6980", fetcher=f, reason="compile_failed")
    assert res.tier is DegradeTier.HTML
    assert res.version == V2
    assert res.url.endswith("/html/1412.6980v2")
    assert res.probed[0].startswith(f"{HTTP_NOT_FOUND}")


def test_degrade_pdf_only_goes_pdf_first() -> None:
    """%PDF 直投 → L3 优先：首个探测就是 /pdf/，且命中。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/pdf/1412.6980":
            return httpx.Response(
                HTTP_REDIRECT,
                headers={"location": "https://arxiv.org/pdf/1412.6980v9"},
            )
        if req.url.path == "/pdf/1412.6980v9":
            return httpx.Response(HTTP_OK)
        msg = f"unexpected {req.url.path}"
        raise AssertionError(msg)

    f = _fetcher(httpx.MockTransport(handler), _Clock(), redirects=True)
    res = degrade("1412.6980", fetcher=f, reason=DegradeReason.PDF_ONLY)
    assert res.tier is DegradeTier.PDF
    assert res.version == LATEST
    assert len(res.probed) == 1


def test_degrade_stub_pdf_then_html_fallthrough() -> None:
    """stub → L3 先探；pdf 404 时落到 L2 兜底（三层叠加语义）。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.startswith("/pdf/"):
            return httpx.Response(HTTP_NOT_FOUND)
        if req.url.path == "/html/1412.6980v1":
            return httpx.Response(HTTP_OK)
        return httpx.Response(HTTP_NOT_FOUND)

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    res = degrade("1412.6980v1", fetcher=f, reason=DegradeReason.STUB)
    assert res.tier is DegradeTier.HTML
    assert res.version == 1


def test_degrade_all_tiers_fail_none() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(HTTP_NOT_FOUND)

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    res = degrade("1412.6980", fetcher=f, reason=DegradeReason.NOT_FOUND)
    assert res.tier is DegradeTier.NONE
    assert res.probed
    assert res.detail == "all_tiers_unavailable"


def test_degrade_mirror_failover() -> None:
    """主 host 传输挂 → head_path 自动切 export 镜像桶。"""
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.host)
        if req.url.host == "arxiv.org":
            msg = "down"
            raise httpx.ConnectError(msg, request=req)
        return httpx.Response(HTTP_OK)

    f = _fetcher(httpx.MockTransport(handler), _Clock())
    res = degrade("1412.6980v2", fetcher=f, reason=DegradeReason.PDF_ONLY)
    assert res.tier is DegradeTier.PDF
    assert "arxiv.org" in calls
    assert "export.arxiv.org" in calls
