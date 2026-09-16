"""§2 端点契约：translate 202/409/reuse、snapshot、files、upload、settings。"""

from __future__ import annotations

import io
import zipfile
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")

from conftest import MINI_TEX

import texlate.server.app as app_mod

if TYPE_CHECKING:
    from starlette.testclient import TestClient

ARXIV = "2401.00001"
_TASKS_LEN = 1


def _docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<doc/>")
    return buf.getvalue()


def _mk_task(client: TestClient) -> str:
    r = client.post(f"/api/arxiv/{ARXIV}/translate", json={"model": "mock-m"})
    assert r.status_code == HTTPStatus.ACCEPTED
    return r.json()["task_id"]


class TestHealth:
    def test_health(self, client: TestClient) -> None:
        r = client.get("/api/health")
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        assert body["ok"] is True
        assert "version" in body
        assert "compilers" in body

    def test_no_store_header(self, client: TestClient) -> None:
        r = client.get("/api/health")
        assert r.headers["Cache-Control"] == "no-store"


class TestArxivTranslate:
    def test_202_shape(self, client: TestClient) -> None:
        r = client.post(f"/api/arxiv/{ARXIV}/translate", json={"model": "mock-m"})
        assert r.status_code == HTTPStatus.ACCEPTED
        body = r.json()
        tid = body["task_id"]
        assert body["status"] == "queued"
        assert body["events_url"] == f"/api/task/{tid}"
        assert body["reader_url"] == f"/api/task/{tid}/reader"
        assert body["cache"] == "miss"

    def test_invalid_id(self, client: TestClient) -> None:
        r = client.post("/api/arxiv/not-an-id!!/translate", json={})
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert "detail" in r.json()

    def test_old_style_id(self, client: TestClient) -> None:
        r = client.post("/api/arxiv/hep-th/9901001/translate", json={})
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_version_pin(self, client: TestClient) -> None:
        r = client.post(f"/api/arxiv/{ARXIV}v2/translate", json={})
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_bad_target_lang(self, client: TestClient) -> None:
        r = client.post(f"/api/arxiv/{ARXIV}/translate", json={"target_lang": "fr"})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_bad_prefer(self, client: TestClient) -> None:
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={"options": {"prefer": "bogus"}},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_duplicate_active_409(self, client: TestClient) -> None:
        tid = _mk_task(client)
        r = client.post(f"/api/arxiv/{ARXIV}/translate", json={"model": "mock-m"})
        assert r.status_code == HTTPStatus.CONFLICT
        body = r.json()
        assert body["task_id"] == tid
        assert body["code"] == "duplicate_active"

    def test_different_model_new_task(self, client: TestClient) -> None:
        tid1 = _mk_task(client)
        r = client.post(f"/api/arxiv/{ARXIV}/translate", json={"model": "other"})
        assert r.status_code == HTTPStatus.ACCEPTED
        assert r.json()["task_id"] != tid1

    def test_idempotency_key(self, client: TestClient) -> None:
        hdr = {"Idempotency-Key": "abc123"}
        r1 = client.post(f"/api/arxiv/{ARXIV}/translate", json={}, headers=hdr)
        r2 = client.post(f"/api/arxiv/{ARXIV}/translate", json={}, headers=hdr)
        assert r1.status_code == HTTPStatus.ACCEPTED
        assert r2.status_code == HTTPStatus.ACCEPTED
        assert r2.json()["task_id"] == r1.json()["task_id"]
        assert r2.json()["cache"] == "idempotent"


class TestCacheReuse:
    def test_reuse_after_done(self, client: TestClient) -> None:
        tid = _mk_task(client)
        store = client.app.state.store
        client.portal.call(partial(store.transition, tid, "done", force=True))
        r = client.post(f"/api/arxiv/{ARXIV}/translate", json={"model": "mock-m"})
        assert r.status_code == HTTPStatus.OK
        assert r.json()["reused"] is True
        assert r.json()["task_id"] == tid

    def test_fresh_bypasses(self, client: TestClient) -> None:
        tid = _mk_task(client)
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={"model": "mock-m", "options": {"prefer": "fresh"}},
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        assert r.json()["task_id"] != tid


class TestTaskGet:
    def test_snapshot(self, client: TestClient) -> None:
        tid = _mk_task(client)
        r = client.get(f"/api/task/{tid}")
        assert r.status_code == HTTPStatus.OK
        snap = r.json()
        assert snap["task_id"] == tid
        assert snap["status"] == "queued"
        assert snap["counters"]["total"] == 0
        assert snap["artifacts"] == {}
        assert snap["last_seq"] == 0

    def test_404(self, client: TestClient) -> None:
        r = client.get("/api/task/t_0000000000000000")
        assert r.status_code == HTTPStatus.NOT_FOUND
        r = client.get("/api/task/garbage")
        assert r.status_code == HTTPStatus.NOT_FOUND


class TestCancelRetry:
    def test_cancel_queued(self, client: TestClient) -> None:
        tid = _mk_task(client)
        r = client.post(f"/api/task/{tid}/cancel")
        assert r.status_code == HTTPStatus.OK
        assert r.json()["status"] == "cancelled"
        snap = client.get(f"/api/task/{tid}").json()
        assert snap["status"] == "cancelled"

    def test_cancel_terminal_409(self, client: TestClient) -> None:
        tid = _mk_task(client)
        client.post(f"/api/task/{tid}/cancel")
        r = client.post(f"/api/task/{tid}/cancel")
        assert r.status_code == HTTPStatus.CONFLICT

    def test_retry_cancelled(self, client: TestClient) -> None:
        tid = _mk_task(client)
        client.post(f"/api/task/{tid}/cancel")
        r = client.post(f"/api/task/{tid}/retry", json={})
        assert r.status_code == HTTPStatus.ACCEPTED
        assert client.get(f"/api/task/{tid}").json()["status"] == "queued"

    def test_retry_active_409(self, client: TestClient) -> None:
        tid = _mk_task(client)
        r = client.post(f"/api/task/{tid}/retry", json={})
        assert r.status_code == HTTPStatus.CONFLICT


class TestFiles:
    def test_files_list_empty(self, client: TestClient) -> None:
        tid = _mk_task(client)
        r = client.get(f"/api/files/{tid}")
        assert r.status_code == HTTPStatus.OK
        assert r.json()["artifacts"] == {}

    def test_unknown_kind_404(self, client: TestClient) -> None:
        tid = _mk_task(client)
        r = client.get(f"/api/files/{tid}/evil.exe")
        assert r.status_code == HTTPStatus.NOT_FOUND

    def test_missing_artifact_404(self, client: TestClient) -> None:
        tid = _mk_task(client)
        r = client.get(f"/api/files/{tid}/zh.pdf")
        assert r.status_code == HTTPStatus.NOT_FOUND


class TestUpload:
    def test_tex_202(self, client: TestClient) -> None:
        r = client.post(
            "/api/upload",
            files={"file": ("main.tex", MINI_TEX.encode(), "text/plain")},
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        assert r.json()["status"] == "queued"

    def test_pdf_no_babeldoc_501(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """501 闸与宿主机 babeldoc 装没装无关——探测钉成未装。"""
        monkeypatch.setattr("texlate.server.app.find_tool", lambda _n: None)
        r = client.post(
            "/api/upload",
            files={"file": ("a.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert r.status_code == HTTPStatus.NOT_IMPLEMENTED
        assert r.json()["code"] == "unsupported_format"

    def test_docx_202(self, client: TestClient) -> None:
        r = client.post(
            "/api/upload",
            files={"file": ("a.docx", _docx(), "application/octet-stream")},
        )
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_unknown_400(self, client: TestClient) -> None:
        r = client.post(
            "/api/upload",
            files={"file": ("a.bin", b"\x00\x01\x02\x03", "application/octet-stream")},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_no_file_400(self, client: TestClient) -> None:
        r = client.post("/api/upload", data={})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_oversize_413(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(app_mod, "UPLOAD_CAP", 16)
        r = client.post(
            "/api/upload",
            files={"file": ("main.tex", MINI_TEX.encode(), "text/plain")},
        )
        assert r.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert r.json()["code"] == "upload_too_large"


class TestCsrf:
    def test_cross_site_rejected(self, client: TestClient) -> None:
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={},
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        assert r.status_code == HTTPStatus.FORBIDDEN

    def test_foreign_origin_rejected(self, client: TestClient) -> None:
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={},
            headers={"Origin": "https://evil.example.com"},
        )
        assert r.status_code == HTTPStatus.FORBIDDEN

    def test_same_origin_ok(self, client: TestClient) -> None:
        """Origin 与请求 scheme+Host 全等（含端口）→ 放行。"""
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={},
            headers={"Origin": "http://localhost"},
        )
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_other_loopback_origin_403(self, client: TestClient) -> None:
        """127.0.0.1:8765 ≠ localhost——loopback 族内跨 origin 也拒。"""
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={},
            headers={"Origin": "http://127.0.0.1:8765"},
        )
        assert r.status_code == HTTPStatus.FORBIDDEN

    def test_get_not_checked(self, client: TestClient) -> None:
        r = client.get("/api/health", headers={"Origin": "https://evil.com"})
        assert r.status_code == HTTPStatus.OK


class TestSettings:
    def test_public_shape(self, client: TestClient) -> None:
        r = client.get("/api/settings")
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        assert "has_api_key" in body
        assert "api_key" not in body

    def test_put_merge(self, client: TestClient) -> None:
        r = client.put("/api/settings", json={"model": "other-m", "api_key": "k1"})
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        assert body["model"] == "other-m"
        assert body["has_api_key"] is True
        assert "api_key" not in body

    def test_put_bad_url_400(self, client: TestClient) -> None:
        r = client.put("/api/settings", json={"base_url": "http://remote.example.com"})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_providers(self, client: TestClient) -> None:
        r = client.get("/api/providers")
        assert r.status_code == HTTPStatus.OK
        ids = [p["id"] for p in r.json()["providers"]]
        assert "gateway" in ids
        assert "openai" in ids


class TestReader:
    def test_position_roundtrip(self, client: TestClient) -> None:
        tid = _mk_task(client)
        r = client.put(
            f"/api/task/{tid}/reader/position",
            json={"positions": {"original": 3}, "active": "original"},
        )
        assert r.status_code == HTTPStatus.OK
        assert r.json()["ok"] is True

    def test_reader_404_without_dual(self, client: TestClient) -> None:
        tid = _mk_task(client)
        r = client.get(f"/api/task/{tid}/reader")
        assert r.status_code == HTTPStatus.NOT_FOUND


class TestTasksList:
    def test_list(self, client: TestClient) -> None:
        _mk_task(client)
        r = client.get("/api/tasks")
        assert r.status_code == HTTPStatus.OK
        tasks = r.json()["tasks"]
        assert len(tasks) == _TASKS_LEN
        assert tasks[0]["status"] == "queued"
        assert tasks[0]["arxiv_id"] == ARXIV

    def test_status_filter(self, client: TestClient) -> None:
        tid = _mk_task(client)
        client.post(f"/api/task/{tid}/cancel")
        r = client.get("/api/tasks?status=cancelled")
        assert [t["task_id"] for t in r.json()["tasks"]] == [tid]
        r = client.get("/api/tasks?status=queued")
        assert r.json()["tasks"] == []
