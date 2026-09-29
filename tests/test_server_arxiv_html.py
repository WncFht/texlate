"""arxiv_html 链 worker e2e：fetch→DOM chunk→translate→emit DOM+dual.json。"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from conftest import (
    FakeEngine,
    FakeFetcher,
    make_app,
    wait_terminal,
)
from starlette.testclient import TestClient
from test_arxiv_html import FIXTURE

from texlate.arxiv.cache import SourceCache
from texlate.xlat.pipeline import MockTranslator

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def html_client(
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """arxiv_html 路 e2e：``seams.fetch_html`` 缝回 FIXTURE，Mock 翻译。"""
    clean_env.setattr(
        "texlate.server.worker.seams.fetch_html", lambda *_a, **_k: FIXTURE
    )
    app = make_app(
        tmp_path,
        start_worker=True,
        translator_factory=lambda _ctx: MockTranslator(),
        engine_factory=lambda _name: FakeEngine(),
        fetcher=FakeFetcher(b""),
        source_cache=SourceCache(tmp_path / "src-cache"),
    )
    with TestClient(app) as c:
        yield c


def _post_html(client: TestClient, arxiv_id: str = "2401.00009") -> str:
    r = client.post(
        f"/api/arxiv/{arxiv_id}/translate",
        json={"options": {"source": "html"}},
    )
    assert r.status_code == HTTPStatus.ACCEPTED, r.text
    return str(r.json()["task_id"])


class TestArxivHtmlE2E:
    def test_done_artifacts(self, html_client: TestClient) -> None:
        tid = _post_html(html_client)
        snap = wait_terminal(html_client, tid)
        assert snap["status"] == "done"
        arts = snap["artifacts"]
        assert "en_html" in arts
        assert "zh_html" in arts
        assert "dual_json" in arts

    def test_en_zh_dom_anchors(self, html_client: TestClient) -> None:
        """双侧 DOM 带同源 ``data-chunk`` 锚（DomPane PageGeom 契约）。"""
        tid = _post_html(html_client)
        wait_terminal(html_client, tid)
        en = html_client.get(f"/api/files/{tid}/en.html")
        zh = html_client.get(f"/api/files/{tid}/zh.html")
        assert en.status_code == HTTPStatus.OK
        assert zh.status_code == HTTPStatus.OK
        assert 'data-chunk="S1.p1"' in en.text
        assert 'data-chunk="S1.p1"' in zh.text
        # support 块（bibitem/figure）两侧同锚——几何序含它们
        assert 'data-chunk="bib.b1"' in en.text
        assert 'data-chunk="bib.b1"' in zh.text

    def test_zh_dom_swapped(self, html_client: TestClient) -> None:
        """zh 侧译文回插：Mock 中文串进块体，原文句子被替换。"""
        tid = _post_html(html_client)
        wait_terminal(html_client, tid)
        zh = html_client.get(f"/api/files/{tid}/zh.html")
        assert "Item text one." not in zh.text  # 译文替换块内文
        en = html_client.get(f"/api/files/{tid}/en.html")
        assert "Item text one." in en.text  # en 侧保持原文
        # footnote 块只换 .ltx_note_content 子树——mark/触发包装留存
        assert 'class="ltx_note_mark"' in zh.text
        assert 'class="ltx_note_outer"' in zh.text
        assert "Note text here." not in zh.text  # note 体已被译文换掉

    def test_dual_json_dom_shape(self, html_client: TestClient) -> None:
        tid = _post_html(html_client)
        wait_terminal(html_client, tid)
        doc = html_client.get(f"/api/files/{tid}/dual.json").json()
        assert doc["version"] == 1
        assert doc["documents"]["translated"]["pages"] >= 1
        assert doc["documents"]["original"]["version"]
        assert doc["alignment"] == {"kind": "pages"}
        assert doc["chunks"]
        chunk0 = doc["chunks"][0]
        assert {"seq", "src_file", "en", "zh", "kind"} <= set(chunk0)

    def test_reader_dom_view(self, html_client: TestClient) -> None:
        tid = _post_html(html_client)
        wait_terminal(html_client, tid)
        r = html_client.get(f"/api/task/{tid}/reader")
        assert r.status_code == HTTPStatus.OK
        doc = r.json()
        assert doc["view"] == "dom"
        assert doc["documents"]["translated"]["url"] == f"/api/files/{tid}/zh.html"

    def test_no_html_source_fault(
        self,
        html_client: TestClient,
        clean_env: pytest.MonkeyPatch,
    ) -> None:
        """``HtmlNotAvailableError`` → ``no_html_source`` fault + retryable=False。"""
        from texlate.arxiv.html import HtmlNotAvailableError  # noqa: PLC0415

        def _na(*_a: object, **_k: object) -> str:
            aid = "2401.00010"
            raise HtmlNotAvailableError(aid, status=HTTPStatus.NOT_FOUND)

        clean_env.setattr("texlate.server.worker.seams.fetch_html", _na)
        tid = _post_html(html_client, "2401.00010")
        snap = wait_terminal(html_client, tid)
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "no_html_source"
        assert snap["error"]["retryable"] is False
