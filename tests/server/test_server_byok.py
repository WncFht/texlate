"""§4 BYOK：header > 渠道 > env 回落、租户指纹、needs_auth 重试、key 不落库。"""

from __future__ import annotations

import json
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

from conftest import get_row, mk_api_task, refused_base_url

if TYPE_CHECKING:
    import pytest
    from starlette.testclient import TestClient

ARXIV = "2401.00004"
HDR = {"X-Texlate-Key": "sk-header-secret-1"}


def _put_channel(client: TestClient, api_key: str) -> None:
    """写单条 inline-key 渠道（路由 auto 下即唯一候选）。"""
    r = client.put(
        "/api/channels",
        json={
            "channels": [
                {
                    "id": "ch-a",
                    "base_url": "https://api.deepseek.com",
                    "api_key": api_key,
                    "models": [{"model": "m1"}],
                }
            ],
        },
    )
    assert r.status_code == HTTPStatus.OK, r.text


class TestPriorityChain:
    def test_header_over_channel(self, client: TestClient) -> None:
        _put_channel(client, "sk-channel-key")
        tid = mk_api_task(client, ARXIV, model="m", headers=HDR)
        sec = client.app.state.runner.secrets[tid]
        assert sec.api_key == "sk-header-secret-1"
        row = get_row(client, tid)
        assert row["auth_source"] == "header"

    def test_channel_fallback(self, client: TestClient) -> None:
        """无 header → 渠道路由决议：凭据取渠道档，auth_source=channel。"""
        _put_channel(client, "sk-channel-key")
        tid = mk_api_task(client, ARXIV, model="m")
        assert client.app.state.runner.secrets[tid].api_key == "sk-channel-key"
        row = get_row(client, tid)
        assert row["auth_source"] == "channel"

    def test_env_fallback(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # env key 经路由渠道的凭据阶梯（key_env/provider env 层）送达
        monkeypatch.setenv("TEXLATE_API_KEY", "sk-env-key")
        tid = mk_api_task(client, ARXIV, model="m")
        assert client.app.state.runner.secrets[tid].api_key == "sk-env-key"

    def test_none_source(self, client: TestClient) -> None:
        """无 key 源（M1 后语义）：建行即 ``needs_auth`` 终态——不登记
        secrets、不入队（空 key 任务不再有可跑的 mock 面）。

        bootstrap 播种的缺省渠道无凭据可决议 → 路由源 ``none``。
        """
        tid = mk_api_task(client, ARXIV, model="m")
        row = get_row(client, tid)
        assert row["status"] == "needs_auth"
        assert row["auth_source"] == "none"
        assert tid not in client.app.state.runner.secrets


class TestTenant:
    def test_local_tenant(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV, model="m", headers=HDR)
        row = get_row(client, tid)
        assert row["tenant"] == "local"

    def test_server_mode_key_fingerprint(self, server_client: TestClient) -> None:
        tid = mk_api_task(
            server_client, ARXIV, model="m", headers={"X-Texlate-Key": "k-A"}
        )
        row = get_row(server_client, tid)
        assert row["tenant"].startswith("k_")
        assert "k-A" not in row["tenant"]

    def test_server_mode_isolation(self, server_client: TestClient) -> None:
        """server 模式下别的租户看不到本任务（404）。"""
        tid = mk_api_task(
            server_client, ARXIV, model="m", headers={"X-Texlate-Key": "k-A"}
        )
        r = server_client.get(f"/api/task/{tid}", headers={"X-Texlate-Key": "k-B"})
        assert r.status_code == HTTPStatus.NOT_FOUND
        r = server_client.get("/api/tasks", headers={"X-Texlate-Key": "k-B"})
        assert r.json()["tasks"] == []


class TestNeedsAuth:
    def test_retry_without_header_401(self, client: TestClient) -> None:
        """auth_source=header 的任务重试必须重带 key（凭证只活内存）。"""
        tid = mk_api_task(client, ARXIV, model="m", headers=HDR)
        store = client.app.state.store
        client.portal.call(partial(store.transition, tid, "needs_auth", force=True))
        r = client.post(f"/api/task/{tid}/retry", json={})
        assert r.status_code == HTTPStatus.UNAUTHORIZED
        assert r.json()["code"] == "auth_required"

    def test_retry_with_header_202(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV, model="m", headers=HDR)
        store = client.app.state.store
        client.portal.call(partial(store.transition, tid, "needs_auth", force=True))
        r = client.post(f"/api/task/{tid}/retry", json={}, headers=HDR)
        assert r.status_code == HTTPStatus.ACCEPTED


class TestNoKeyLeak:
    def test_key_not_in_db(self, client: TestClient) -> None:
        """header key 不进任何库表/事件。"""
        tid = mk_api_task(client, ARXIV, model="m", headers=HDR)
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

    def test_channels_mask_key(self, client: TestClient) -> None:
        """渠道 inline key 绝不出 API 面——只报 has_api_key。"""
        _put_channel(client, "sk-very-secret")
        body = client.get("/api/channels").json()
        assert body["channels"][0]["has_api_key"] is True
        assert "sk-very-secret" not in json.dumps(body)

    def test_scrub_filter(self) -> None:
        """settings.scrub 抹显式 key 值。"""
        from texlate.server.settings import scrub  # noqa: PLC0415 -- 轻依赖但聚类

        out = scrub("Authorization: Bearer sk-abc123 key=sk-abc123", "sk-abc123")
        assert "sk-abc123" not in out


class TestChannelProbe:
    def test_unreachable_endpoint(self, client: TestClient) -> None:
        """裸端点探活打不通 → stage1 非 ok，detail 已脱敏、不含 key。"""
        # bind 但不 listen：用例期间一直占住端口（免疫外部抢占窗口），
        # 入站 SYN 仍必吃 RST → 探活确定 ECONNREFUSED，不依赖本机端口状态。
        with refused_base_url() as base_url:
            r = client.post(
                "/api/channels/probe",
                json={"base_url": base_url, "api_key": "sk-probe-key"},
            )
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        assert body["stage1"]["verdict"] != "ok"
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
