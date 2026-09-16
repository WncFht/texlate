"""§4 BYOK：header > settings > env 三级回落、租户指纹、needs_auth 重试、key 不落库。"""

from __future__ import annotations

import json
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")

if TYPE_CHECKING:
    from starlette.testclient import TestClient

ARXIV = "2401.00004"
HDR = {"X-Texlate-Key": "sk-header-secret-1"}


def _mk(client: TestClient, headers: dict | None = None) -> str:
    r = client.post(
        f"/api/arxiv/{ARXIV}/translate", json={"model": "m"}, headers=headers or {}
    )
    assert r.status_code == HTTPStatus.ACCEPTED
    return r.json()["task_id"]


class TestPriorityChain:
    def test_header_over_settings(self, client: TestClient) -> None:
        client.put("/api/settings", json={"api_key": "sk-settings-key"})
        tid = _mk(client, headers=HDR)
        sec = client.app.state.runner.secrets[tid]
        assert sec.api_key == "sk-header-secret-1"
        row = client.portal.call(partial(client.app.state.store.get, tid))
        assert row["auth_source"] == "header"

    def test_settings_fallback(self, client: TestClient) -> None:
        client.put("/api/settings", json={"api_key": "sk-settings-key"})
        tid = _mk(client)
        assert client.app.state.runner.secrets[tid].api_key == "sk-settings-key"
        row = client.portal.call(partial(client.app.state.store.get, tid))
        assert row["auth_source"] == "settings"

    def test_env_fallback(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEXLATE_API_KEY", "sk-env-key")
        tid = _mk(client)
        assert client.app.state.runner.secrets[tid].api_key == "sk-env-key"

    def test_none_source(self, client: TestClient) -> None:
        tid = _mk(client)
        assert client.app.state.runner.secrets[tid].api_key == ""


class TestTenant:
    def test_local_tenant(self, client: TestClient) -> None:
        tid = _mk(client, headers=HDR)
        row = client.portal.call(partial(client.app.state.store.get, tid))
        assert row["tenant"] == "local"

    def test_server_mode_key_fingerprint(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEXLATE_MODE", "server")
        tid = _mk(client, headers={"X-Texlate-Key": "k-A"})
        row = client.portal.call(partial(client.app.state.store.get, tid))
        assert row["tenant"].startswith("k_")
        assert "k-A" not in row["tenant"]

    def test_server_mode_isolation(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """server 模式下别的租户看不到本任务（404）。"""
        monkeypatch.setenv("TEXLATE_MODE", "server")
        tid = _mk(client, headers={"X-Texlate-Key": "k-A"})
        r = client.get(f"/api/task/{tid}", headers={"X-Texlate-Key": "k-B"})
        assert r.status_code == HTTPStatus.NOT_FOUND
        r = client.get("/api/tasks", headers={"X-Texlate-Key": "k-B"})
        assert r.json()["tasks"] == []


class TestNeedsAuth:
    def test_retry_without_header_401(self, client: TestClient) -> None:
        """auth_source=header 的任务重试必须重带 key（凭证只活内存）。"""
        tid = _mk(client, headers=HDR)
        store = client.app.state.store
        client.portal.call(partial(store.transition, tid, "needs_auth", force=True))
        r = client.post(f"/api/task/{tid}/retry", json={})
        assert r.status_code == HTTPStatus.UNAUTHORIZED
        assert r.json()["code"] == "auth_required"

    def test_retry_with_header_202(self, client: TestClient) -> None:
        tid = _mk(client, headers=HDR)
        store = client.app.state.store
        client.portal.call(partial(store.transition, tid, "needs_auth", force=True))
        r = client.post(f"/api/task/{tid}/retry", json={}, headers=HDR)
        assert r.status_code == HTTPStatus.ACCEPTED


class TestNoKeyLeak:
    def test_key_not_in_db(self, client: TestClient) -> None:
        """header key 不进任何库表/事件。"""
        tid = _mk(client, headers=HDR)
        store = client.app.state.store
        rows = client.portal.call(
            partial(
                lambda: {
                    "task": store.get(tid),
                    "events": store.events_since(tid, 0),
                }
            )
        )
        blob = json.dumps(rows, ensure_ascii=False, default=str)
        assert "sk-header-secret-1" not in blob

    def test_settings_masks_key(self, client: TestClient) -> None:
        client.put("/api/settings", json={"api_key": "sk-very-secret"})
        body = client.get("/api/settings").json()
        assert body["has_api_key"] is True
        assert "sk-very-secret" not in json.dumps(body)

    def test_scrub_filter(self) -> None:
        """settings.scrub 抹显式 key 值。"""
        from texlate.server.settings import scrub  # noqa: PLC0415 -- 轻依赖但聚类

        out = scrub("Authorization: Bearer sk-abc123 key=sk-abc123", "sk-abc123")
        assert "sk-abc123" not in out


class TestSettingsTest:
    def test_unreachable_endpoint(self, client: TestClient) -> None:
        """探活打不通 → ok:false，detail 已脱敏、不含 key。"""
        import socket  # noqa: PLC0415 -- 仅此用例要占即释端口

        # bind 但不 listen：用例期间一直占住端口（免疫外部抢占窗口），
        # 入站 SYN 仍必吃 RST → 探活确定 ECONNREFUSED，不依赖本机 :3003 状态。
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            client.put("/api/settings", json={"api_key": "sk-probe-key"})
            r = client.post(
                "/api/settings/test", json={"base_url": f"http://127.0.0.1:{port}"}
            )
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        assert body["ok"] is False
        assert "sk-probe-key" not in json.dumps(body)


class TestUploadByok:
    def test_upload_with_header(self, client: TestClient) -> None:
        """upload 路同吃 header 凭证。"""
        tex = b"\\documentclass{article}\n\\begin{document}\nHi.\n\\end{document}\n"
        r = client.post(
            "/api/upload",
            files={"file": ("main.tex", tex, "text/plain")},
            headers=HDR,
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        tid = r.json()["task_id"]
        assert client.app.state.runner.secrets[tid].api_key == "sk-header-secret-1"
