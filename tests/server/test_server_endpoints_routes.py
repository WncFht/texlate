"""``/api/endpoints*`` 路由面单测：读/写/激活/探针 + server 形态 403 闸。

probe 经 ``routers.endpoints.probe_endpoint`` 打桩（模块面 patch——路由叶
直引数据层函数，patch 点名面即缝）；activate 走真 ``settings_store.save``
（``TEXLATE_MODEL_PROBE=0`` 关 save 期模型清单探活，防离线炸网）。
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import pytest

from texlate.server import endpoints as ep

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def _no_model_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXLATE_MODEL_PROBE", "0")


def _put_profile(pid: str = "p1", **over: object) -> dict[str, Any]:
    p: dict[str, Any] = {
        "id": pid,
        "label": "",
        "base_url": "https://api.deepseek.com",
        "dialect": "auto",
        "models": ["deepseek-chat"],
        "enabled": True,
        "api_key": "sk-ds",
        "key_env": "",
    }
    p.update(over)
    return p


# ---------------------------------------------------------------- GET / PUT


class TestGetPut:
    def test_get_projects_default(self, client: TestClient) -> None:
        """文件缺席 → settings 行投影成 default profile。"""
        r = client.get("/api/endpoints")
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        assert body["active_id"] == "default"
        assert body["profiles"][0]["id"] == "default"
        assert all("api_key" not in p for p in body["profiles"])

    def test_put_get_roundtrip(self, client: TestClient) -> None:
        r = client.put(
            "/api/endpoints",
            json={
                "profiles": [
                    _put_profile("p1"),
                    _put_profile(
                        "p2",
                        base_url="https://api.anthropic.com",
                        api_key="sk-ant",
                        models=["claude-x"],
                    ),
                ]
            },
        )
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        assert [p["id"] for p in body["profiles"]] == ["p1", "p2"]
        assert body["profiles"][0]["has_api_key"] is True
        assert "sk-ds" not in json.dumps(body)  # key 值不出参
        assert not body["active_id"]  # 默认网关不在档案里
        g = client.get("/api/endpoints").json()
        assert [p["id"] for p in g["profiles"]] == ["p1", "p2"]

    def test_put_invalid(self, client: TestClient) -> None:
        assert (
            client.put("/api/endpoints", json={}).status_code == HTTPStatus.BAD_REQUEST
        )
        assert (
            client.put("/api/endpoints", json={"profiles": [{"id": "BAD"}]}).status_code
            == HTTPStatus.BAD_REQUEST
        )
        assert (
            client.put(
                "/api/endpoints",
                json={"profiles": [_put_profile(api_key="k", key_env="E")]},
            ).status_code
            == HTTPStatus.BAD_REQUEST
        )


# ---------------------------------------------------------------- activate


class TestActivate:
    def test_activate_inline_key(self, client: TestClient, tmp_path: Path) -> None:
        client.put("/api/endpoints", json={"profiles": [_put_profile()]})
        r = client.post("/api/endpoints/activate", json={"id": "p1"})
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        assert body["base_url"] == "https://api.deepseek.com"
        assert body["model"] == "deepseek-chat"
        assert body["has_api_key"] is True
        # settings.json 落的是真 key（connections 槽同步）
        raw = json.loads(
            (tmp_path / "data" / "settings.json").read_text(encoding="utf-8")
        )
        assert raw["api_key"] == "sk-ds"
        # 激活后 active_id 指向该 profile
        assert client.get("/api/endpoints").json()["active_id"] == "p1"

    def test_activate_key_env_clears_settings_key(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """key_env profile 激活：settings key 清空让 key_env 阶梯接管。"""
        monkeypatch.setenv("MY_DS_KEY", "sk-from-env")
        client.put(
            "/api/settings",
            json={"api_key": "sk-old-gateway"},
        )
        client.put(
            "/api/endpoints",
            json={
                "profiles": [
                    _put_profile(api_key="", key_env="MY_DS_KEY"),
                ]
            },
        )
        r = client.post("/api/endpoints/activate", json={"id": "p1"})
        assert r.status_code == HTTPStatus.OK
        raw = json.loads(
            (tmp_path / "data" / "settings.json").read_text(encoding="utf-8")
        )
        assert raw["base_url"] == "https://api.deepseek.com"
        assert raw["api_key"] == ""  # 清掉——旧 key 发向新端点是 exfil
        # resolve_auth 同径：key_env 命中 → env 凭据接管
        from texlate.server.auth import resolve_auth  # noqa: PLC0415
        from texlate.server.settings import SettingsStore  # noqa: PLC0415

        store = SettingsStore(tmp_path / "data")
        auth = resolve_auth(
            store.load(),
            key_env_lookup=ep.EndpointStore(tmp_path / "data").key_env_for,
        )
        assert auth.api_key == "sk-from-env"
        assert auth.source == "env"

    def test_activate_unknown_404(self, client: TestClient) -> None:
        assert (
            client.post("/api/endpoints/activate", json={"id": "ghost"}).status_code
            == HTTPStatus.NOT_FOUND
        )


# ---------------------------------------------------------------- probe


class TestProbe:
    def test_probe_by_id_records_last(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client.put("/api/endpoints", json={"profiles": [_put_profile()]})
        report = {
            "at": "2026-10-07T00:00:00+00:00",
            "key_fp": "abcd1234",
            "stage1": {"verdict": "ok", "models": ["deepseek-chat"], "detail": ""},
            "models": {
                "deepseek-chat": {
                    "verdict": "usable",
                    "latency_s": 0.4,
                    "detail": "",
                    "listed": True,
                }
            },
        }
        seen: list[tuple[str, str, str, list[str]]] = []

        async def fake_probe(
            base_url: str, key: str, dialect: str, models: list[str]
        ) -> dict[str, Any]:
            seen.append((base_url, key, dialect, models))
            return report

        monkeypatch.setattr(
            "texlate.server.routers.endpoints.probe_endpoint", fake_probe
        )
        r = client.post("/api/endpoints/probe", json={"id": "p1"})
        assert r.status_code == HTTPStatus.OK
        assert r.json()["models"]["deepseek-chat"]["verdict"] == "usable"
        assert seen == [
            ("https://api.deepseek.com", "sk-ds", "auto", ["deepseek-chat"])
        ]
        # last_probe 钉回档案
        g = client.get("/api/endpoints").json()
        assert g["profiles"][0]["last_probe"]["key_fp"] == "abcd1234"

    def test_probe_bare_requires_key(self, client: TestClient) -> None:
        r = client.post(
            "/api/endpoints/probe",
            json={"base_url": "https://api.deepseek.com", "models": ["m"]},
        )
        # 裸端点不带 key → exfil 闸
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_probe_bare_with_key(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_probe(
            _base_url: str, _key: str, _dialect: str, _models: list[str]
        ) -> dict[str, Any]:
            return {"stage1": {"verdict": "ok"}, "models": {}, "key_fp": "", "at": ""}

        monkeypatch.setattr(
            "texlate.server.routers.endpoints.probe_endpoint", fake_probe
        )
        r = client.post(
            "/api/endpoints/probe",
            json={
                "base_url": "https://api.deepseek.com",
                "api_key": "sk-x",
                "models": ["m1"],
            },
        )
        assert r.status_code == HTTPStatus.OK

    def test_probe_unknown_id_404(self, client: TestClient) -> None:
        assert (
            client.post("/api/endpoints/probe", json={"id": "ghost"}).status_code
            == HTTPStatus.NOT_FOUND
        )


# ---------------------------------------------------------------- server 形态


class TestServerModeGate:
    """server 形态整面关闭：匿名写中间件 401，带 key 撞到叶级 403 闸。"""

    def test_all_403(self, server_client: TestClient) -> None:
        key = {"headers": {"X-Texlate-Key": "k"}}
        # 匿名写请求被 app 中间件 401（server 匿名 mutation 闸）——到不了叶闸
        assert (
            server_client.put("/api/endpoints", json={"profiles": []}).status_code
            == HTTPStatus.UNAUTHORIZED
        )
        # 读面带 key 也 403（拓扑面比 settings GET 更严）
        assert server_client.get("/api/endpoints", **key).status_code == (
            HTTPStatus.FORBIDDEN
        )
        assert (
            server_client.put(
                "/api/endpoints", json={"profiles": []}, **key
            ).status_code
            == HTTPStatus.FORBIDDEN
        )
        assert (
            server_client.post(
                "/api/endpoints/activate", json={"id": "x"}, **key
            ).status_code
            == HTTPStatus.FORBIDDEN
        )
        assert (
            server_client.post(
                "/api/endpoints/probe", json={"id": "x"}, **key
            ).status_code
            == HTTPStatus.FORBIDDEN
        )
