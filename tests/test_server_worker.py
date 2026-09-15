"""§3.1/§3.4 worker e2e：upload_tex/arxiv 全链 → done + 产物登记 + 终态守卫。"""

from __future__ import annotations

import asyncio
import time
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from conftest import (
    MINI_TEX,
    FakeEngine,
    FakeFetcher,
    make_app,
    make_targz,
    upload_tex,
    wait_terminal,
)
from starlette.testclient import TestClient

from texlate.arxiv.cache import SourceCache
from texlate.server.worker import chunk_db_id
from texlate.xlat.client import AuthError, ChatError
from texlate.xlat.pipeline import MockTranslator

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from texlate.server.worker import TaskCtx

_CHUNK_ID_LEN = 24  # sha256[:24]


@pytest.fixture
def arxiv_client(
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,  # noqa: ARG001 -- fixture 副作用
) -> Iterator[TestClient]:
    """arxiv 路 e2e：FakeFetcher 供 tar.gz、Mock 翻译、Fake 引擎。"""
    engine = FakeEngine()
    app = make_app(
        tmp_path,
        start_worker=True,
        translator_factory=lambda _ctx: MockTranslator(),
        engine_factory=lambda _name: engine,
        fetcher=FakeFetcher(make_targz({"main.tex": MINI_TEX})),
        source_cache=SourceCache(tmp_path / "src-cache"),
    )
    with TestClient(app) as c:
        yield c


class TestUploadTexE2E:
    def test_full_pipeline_done(self, live_client: TestClient) -> None:
        body = upload_tex(live_client)
        snap = wait_terminal(live_client, body["task_id"])
        assert snap["status"] == "done"
        assert snap["progress"] == 100  # noqa: PLR2004 - 终态进度 100
        arts = snap["artifacts"]
        assert "zh_pdf" in arts
        assert "dual_json" in arts
        assert "zh_src_zip" in arts

    def test_chunk_counters(self, live_client: TestClient) -> None:
        body = upload_tex(live_client)
        snap = wait_terminal(live_client, body["task_id"])
        assert snap["counters"]["total"] >= 1
        assert snap["counters"]["done"] == snap["counters"]["total"]
        assert snap["counters"]["failed"] == 0

    def test_dual_json_schema(self, live_client: TestClient) -> None:
        body = upload_tex(live_client)
        tid = body["task_id"]
        wait_terminal(live_client, tid)
        r = live_client.get(f"/api/files/{tid}/dual.json")
        assert r.status_code == HTTPStatus.OK
        doc = r.json()
        assert doc["version"] == 1
        assert doc["documents"]["translated"]["pages"] >= 0
        assert doc["alignment"]["kind"] == "pages"
        chunk0 = doc["chunks"][0]
        assert {"seq", "src_file", "en", "zh", "kind"} <= set(chunk0)

    def test_file_download(self, live_client: TestClient) -> None:
        body = upload_tex(live_client)
        tid = body["task_id"]
        wait_terminal(live_client, tid)
        r = live_client.get(f"/api/files/{tid}/zh.pdf")
        assert r.status_code == HTTPStatus.OK
        assert r.content.startswith(b"%PDF")
        r2 = live_client.get(f"/api/files/{tid}/zh.pdf", params={"download": 1})
        assert "attachment" in r2.headers["Content-Disposition"]

    def test_reader_after_done(self, live_client: TestClient) -> None:
        body = upload_tex(live_client)
        tid = body["task_id"]
        wait_terminal(live_client, tid)
        r = live_client.get(f"/api/task/{tid}/reader")
        assert r.status_code == HTTPStatus.OK
        doc = r.json()
        assert doc["documents"]["translated"]["url"] == f"/api/files/{tid}/zh.pdf"
        assert doc["view"] == "pdf"


class TestArxivE2E:
    def test_arxiv_done(self, arxiv_client: TestClient) -> None:
        r = arxiv_client.post("/api/arxiv/2401.00003/translate", json={})
        assert r.status_code == HTTPStatus.ACCEPTED
        snap = wait_terminal(arxiv_client, r.json()["task_id"])
        assert snap["status"] == "done"
        # src.tar 应已登记（raw blob 回放产物）
        assert "src_tar" in snap["artifacts"]


class TestFaultPaths:
    def test_translate_fault(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """translator 构造期 AuthError → fault + provider_auth（§3.3 ACTIVE 异常）。"""

        def boom_factory(_ctx: TaskCtx) -> object:
            msg = "bad key"
            raise AuthError(msg, status=401)

        app = make_app(
            tmp_path,
            start_worker=True,
            translator_factory=boom_factory,
            engine_factory=lambda _name: FakeEngine(),
        )
        with TestClient(app) as c:
            tid = upload_tex(c)["task_id"]
            snap = wait_terminal(c, tid)
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "provider_auth"
        assert snap["error"]["retryable"] is False

    def test_all_chunks_failed_partial(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """块级 ChatError 被管线吸收 → failed chunks，仍出 pdf → partial（§3.4）。"""

        class Boom:
            async def translate(self, **_kw: object) -> object:
                msg = "provider down"
                raise ChatError(msg, status=500, retryable=False)

        app = make_app(
            tmp_path,
            start_worker=True,
            translator_factory=lambda _ctx: Boom(),
            engine_factory=lambda _name: FakeEngine(),
        )
        with TestClient(app) as c:
            tid = upload_tex(c)["task_id"]
            snap = wait_terminal(c, tid)
        assert snap["status"] == "partial"
        assert snap["counters"]["failed"] == snap["counters"]["total"]
        assert snap["counters"]["total"] >= 1

    def test_cancel_during_run(self, live_client: TestClient) -> None:
        """排队中的任务 cancel → cancelled（不进入 running 态也成立）。"""
        tid = upload_tex(live_client)["task_id"]
        # 跑得飞快——cancel 可能赶在终态前（ACTIVE→cancelled）或后（409）
        r = live_client.post(f"/api/task/{tid}/cancel")
        assert r.status_code in (HTTPStatus.OK, HTTPStatus.CONFLICT)
        snap = wait_terminal(live_client, tid)
        assert snap["status"] in ("cancelled", "done")


class TestResume:
    def test_interrupted_chunks_resume(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """translating 中崩 → cancelled 后 chunks 表保留断点（total≥1）。"""

        class HangTranslator:
            def __init__(self) -> None:
                self.n = 0

            async def translate(self, **_kw: object) -> object:
                self.n += 1
                await asyncio.sleep(30)  # 永不返回 → 测试靠 cancel 杀
                return None

        engine = FakeEngine()
        app = make_app(
            tmp_path,
            start_worker=True,
            translator_factory=lambda _ctx: HangTranslator(),
            engine_factory=lambda _name: engine,
        )
        with TestClient(app) as c:
            tid = upload_tex(c)["task_id"]
            # 等到 chunks 已入库（parsing 完成）
            deadline = time.time() + 10
            while time.time() < deadline:
                snap = c.get(f"/api/task/{tid}").json()
                if snap["counters"]["total"] >= 1 or snap["status"] in (
                    "translating",
                    "compiling",
                ):
                    break
                time.sleep(0.05)
            c.post(f"/api/task/{tid}/cancel")
            snap = wait_terminal(c, tid)
            assert snap["status"] == "cancelled"
            assert snap["counters"]["total"] >= 1


def test_chunk_db_id_stable() -> None:
    """chunk_id = sha256(src_file:byte_start:byte_end)[:24]——splice 重建靠它稳定。"""
    a = chunk_db_id("a.tex", 0, 5)
    b = chunk_db_id("a.tex", 0, 5)
    assert a == b
    assert len(a) == _CHUNK_ID_LEN
    assert chunk_db_id("a.tex", 0, 6) != a
