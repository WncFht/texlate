"""discover 路由契约：白名单 400、分页 clamp、id 闸、TTL 缓存、上游故障面。

``_ax_get`` 全程打桩——不触真 alphaXiv；端点侧只验「桩回包 → HTTP 面」
的映射（404→``available:false`` 链、非 200/坏 JSON/错形状 → 502
``discover_upstream``、正/负结果同入 TTL 缓存）。
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from texlate.server.http import _ApiError
from texlate.server.routers import discover as discover_mod

if TYPE_CHECKING:
    from collections.abc import Iterator

    from starlette.testclient import TestClient


class _Resp:
    """``_ax_get`` 回包桩——``status_code``/``json()``/``content`` 三面。"""

    def __init__(
        self,
        status: int = 200,
        json_data: object = None,
        content: bytes = b"",
        json_exc: Exception | None = None,
    ) -> None:
        self.status_code = status
        self._json = json_data
        self.content = content
        self._json_exc = json_exc

    def json(self) -> object:
        if self._json_exc is not None:
            raise self._json_exc
        return self._json


def _stub_ax(
    monkeypatch: pytest.MonkeyPatch,
    routes: dict[str, _Resp | Exception],
) -> list[tuple[str, dict[str, Any] | None]]:
    """``discover._ax_get`` 打桩成 path→回包/异常 路由表；返回调用日志。"""
    calls: list[tuple[str, dict[str, Any] | None]] = []

    async def fake(path: str, params: dict[str, Any] | None = None) -> _Resp:
        calls.append((path, params))
        out = routes.get(path, _Resp(404))
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(discover_mod, "_ax_get", fake)
    return calls


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    """模块级 TTL 缓存前后清场——同键残留会让上游桩漏调/串用例。"""
    caches = (
        discover_mod._feed_cache,  # noqa: SLF001
        discover_mod._search_cache,  # noqa: SLF001
        discover_mod._overview_cache,  # noqa: SLF001
        discover_mod._og_cache,  # noqa: SLF001
    )
    for c in caches:
        c._d.clear()  # noqa: SLF001
    yield
    for c in caches:
        c._d.clear()  # noqa: SLF001


class TestTtlCache:
    def test_hit_and_miss(self) -> None:
        c = discover_mod._TtlCache[int](ttl=60, max_entries=4)  # noqa: SLF001
        assert c.get("a") is None
        c.put("a", 1)
        assert c.get("a") == 1

    def test_expiry(self) -> None:
        c = discover_mod._TtlCache[int](ttl=-1.0, max_entries=4)  # noqa: SLF001
        c.put("a", 1)
        assert c.get("a") is None  # 过期即缺席
        assert "a" not in c._d  # noqa: SLF001 -- 顺手摘除是契约的一部分

    def test_lru_evict(self) -> None:
        c = discover_mod._TtlCache[int](ttl=60, max_entries=2)  # noqa: SLF001
        c.put("a", 1)
        c.put("b", 2)
        assert c.get("a") == 1  # touch → b 沉底成逐出候选
        third = 3
        c.put("c", third)
        assert c.get("b") is None
        assert c.get("a") == 1
        assert c.get("c") == third


class TestCheckedArxivId:
    @pytest.mark.parametrize(
        ("raw", "expect"),
        [
            ("2401.00001", "2401.00001"),
            ("2401.00001v2", "2401.00001v2"),
            ("hep-th/9901001", "hep-th/9901001"),
            ("math.GT/0309136", "math/0309136"),  # canon 剥旧形 class
            ("hep-th/9901001v11", "hep-th/9901001v11"),
            ("  2401.00001/\n", "2401.00001"),
            ("arXiv:2401.00001", "2401.00001"),
        ],
    )
    def test_accept(self, raw: str, expect: str) -> None:
        assert discover_mod._checked_arxiv_id(raw) == expect  # noqa: SLF001

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "not-an-id!!",
            "2401.0000123",  # 新形小数点后 4–5 位
            "1234.123456",  # 6 位——旧私有正则的漂移放行面
            "2401.00001v0",  # v0 非合法版本
            "../etc/passwd",
        ],
    )
    def test_reject(self, raw: str) -> None:
        with pytest.raises(_ApiError) as exc_info:
            discover_mod._checked_arxiv_id(raw)  # noqa: SLF001
        assert exc_info.value.status == HTTPStatus.BAD_REQUEST
        assert exc_info.value.body["code"] == "invalid_request"


class TestFeed:
    def test_sort_whitelist(self, client: TestClient) -> None:
        r = client.get("/api/discover/feed", params={"sort": "Bogus"})
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "invalid_request"

    def test_interval_whitelist(self, client: TestClient) -> None:
        r = client.get("/api/discover/feed", params={"interval": "Bogus"})
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "invalid_request"

    def test_page_clamp_and_cache(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _stub_ax(monkeypatch, {"/papers/v3/feed": _Resp(200, {"items": []})})
        r = client.get("/api/discover/feed", params={"page": 0, "page_size": 999})
        assert r.status_code == HTTPStatus.OK
        assert r.json() == {"items": []}
        assert calls[0][1] == {
            "sort": "Hot",
            "interval": "7 Days",
            "pageNum": "1",
            "pageSize": "30",
        }
        # 同键二次命中缓存——不再打上游
        r2 = client.get("/api/discover/feed", params={"page": 0, "page_size": 999})
        assert r2.status_code == HTTPStatus.OK
        assert len(calls) == 1

    def test_page_clamp_high(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _stub_ax(monkeypatch, {"/papers/v3/feed": _Resp(200, {"items": []})})
        client.get("/api/discover/feed", params={"page": 500})
        assert calls[0][1]["pageNum"] == "100"

    def test_upstream_5xx(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_ax(monkeypatch, {"/papers/v3/feed": _Resp(503)})
        r = client.get("/api/discover/feed")
        assert r.status_code == HTTPStatus.BAD_GATEWAY
        assert r.json()["code"] == "discover_upstream"

    def test_upstream_net_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_ax(
            monkeypatch,
            {
                "/papers/v3/feed": _ApiError(
                    502, {"detail": "boom", "code": "discover_upstream"}
                )
            },
        )
        r = client.get("/api/discover/feed")
        assert r.status_code == HTTPStatus.BAD_GATEWAY
        assert r.json()["code"] == "discover_upstream"

    def test_bad_json(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_ax(
            monkeypatch,
            {"/papers/v3/feed": _Resp(200, json_exc=ValueError("junk"))},
        )
        r = client.get("/api/discover/feed")
        assert r.status_code == HTTPStatus.BAD_GATEWAY
        assert r.json()["code"] == "discover_upstream"

    def test_wrong_shape(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_ax(monkeypatch, {"/papers/v3/feed": _Resp(200, json_data=[1, 2])})
        r = client.get("/api/discover/feed")
        assert r.status_code == HTTPStatus.BAD_GATEWAY
        assert r.json()["code"] == "discover_upstream"


class TestSearch:
    def test_empty_q(self, client: TestClient) -> None:
        r = client.get("/api/discover/search", params={"q": "   "})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_long_q(self, client: TestClient) -> None:
        r = client.get(
            "/api/discover/search",
            params={"q": "x" * (discover_mod._SEARCH_Q_MAX + 1)},  # noqa: SLF001
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_ok_and_cache(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _stub_ax(
            monkeypatch,
            {"/search/v2/paper/fast": _Resp(200, [{"paperId": "p1"}])},
        )
        r = client.get("/api/discover/search", params={"q": "kv cache"})
        assert r.status_code == HTTPStatus.OK
        assert r.json() == [{"paperId": "p1"}]
        assert calls[0][1]["includePrivate"] == "false"
        client.get("/api/discover/search", params={"q": "kv cache"})
        assert len(calls) == 1

    def test_wrong_shape(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_ax(
            monkeypatch,
            {"/search/v2/paper/fast": _Resp(200, {"oops": 1})},
        )
        r = client.get("/api/discover/search", params={"q": "x"})
        assert r.status_code == HTTPStatus.BAD_GATEWAY


class TestOverview:
    _AID = "2401.00001"
    _URL = f"/api/discover/overview/{_AID}"

    def test_bad_id(self, client: TestClient) -> None:
        r = client.get("/api/discover/overview/not-an-id!!")
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "invalid_request"

    def test_legacy_404_negative_cached(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _stub_ax(monkeypatch, {})
        r = client.get(self._URL)
        assert r.status_code == HTTPStatus.OK
        assert r.json() == {"available": False}
        # 负结果也进缓存——第二次不再打穿上游链
        r2 = client.get(self._URL)
        assert r2.json() == {"available": False}
        assert len(calls) == 1

    def test_happy_zh(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _stub_ax(
            monkeypatch,
            {
                f"/papers/v3/legacy/{self._AID}": _Resp(
                    200, {"paper": {"paper_version": {"id": "pv1"}}}
                ),
                "/papers/v3/pv1/overview/status": _Resp(
                    200, {"translations": {"zh": {"state": "done"}}}
                ),
                "/papers/v3/pv1/overview/zh": _Resp(
                    200, {"title": "T", "overview": {"x": 1}}
                ),
            },
        )
        r = client.get(self._URL)
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        assert body["available"] is True
        assert body["lang"] == "zh"
        assert body["title"] == "T"
        assert body["arxiv_id"] == self._AID
        assert body["alphaxiv_url"].endswith(self._AID)
        client.get(self._URL)
        # 三步链只走一遍——正结果入缓存，第二次请求不再打上游
        assert [p for p, _params in calls] == [
            f"/papers/v3/legacy/{self._AID}",
            "/papers/v3/pv1/overview/status",
            "/papers/v3/pv1/overview/zh",
        ]

    def test_en_fallback(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_ax(
            monkeypatch,
            {
                f"/papers/v3/legacy/{self._AID}": _Resp(
                    200, {"paper": {"paper_version": {"id": "pv2"}}}
                ),
                "/papers/v3/pv2/overview/status": _Resp(
                    200, {"state": "done", "translations": {}}
                ),
                "/papers/v3/pv2/overview/en": _Resp(200, {"title": "E"}),
            },
        )
        body = client.get(self._URL).json()
        assert body["available"] is True
        assert body["lang"] == "en"
        assert body["title"] == "E"

    def test_not_generated(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_ax(
            monkeypatch,
            {
                f"/papers/v3/legacy/{self._AID}": _Resp(
                    200, {"paper": {"paper_version": {"id": "pv3"}}}
                ),
                "/papers/v3/pv3/overview/status": _Resp(200, {"translations": {}}),
            },
        )
        assert client.get(self._URL).json() == {"available": False}

    def test_upstream_5xx(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_ax(monkeypatch, {f"/papers/v3/legacy/{self._AID}": _Resp(500)})
        r = client.get(self._URL)
        assert r.status_code == HTTPStatus.BAD_GATEWAY
        assert r.json()["code"] == "discover_upstream"

    def test_bad_legacy_shape(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_ax(
            monkeypatch,
            {f"/papers/v3/legacy/{self._AID}": _Resp(200, {"paper": {}})},
        )
        r = client.get(self._URL)
        assert r.status_code == HTTPStatus.BAD_GATEWAY
        assert r.json()["code"] == "discover_upstream"


class TestOg:
    def test_ok_cached(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _stub_ax(
            monkeypatch,
            {"/open-graph/v1/paper/2401.00001": _Resp(200, content=b"PNG")},
        )
        r = client.get("/api/discover/og/2401.00001")
        assert r.status_code == HTTPStatus.OK
        assert r.content == b"PNG"
        assert r.headers["content-type"] == "image/png"
        assert r.headers["cache-control"] == "private, max-age=86400"
        client.get("/api/discover/og/2401.00001")
        assert len(calls) == 1

    def test_404(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_ax(monkeypatch, {})
        r = client.get("/api/discover/og/2401.00002")
        assert r.status_code == HTTPStatus.NOT_FOUND

    def test_bad_id(self, client: TestClient) -> None:
        r = client.get("/api/discover/og/bogus!!")
        assert r.status_code == HTTPStatus.BAD_REQUEST
