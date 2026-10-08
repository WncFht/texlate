"""``/api/channels*`` HTTP 面测试：读写往返 + 路由小节 + 探针 + 预设 + server 禁。

探针一律打桩 ``texlate.server.routers.channels.probe_channel``（模块级
from-import 名）——不真发网络；断言点是凭据阶梯出口 key、子集 selector
的条目解析、``record_probe`` 钉档行为与 exfil 闸。
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from starlette.testclient import TestClient


def _m(model: str, redirect: str = "") -> dict[str, str]:
    return {"model": model, "redirect_model": redirect}


def _channel(cid: str, **over: object) -> dict[str, Any]:
    c: dict[str, Any] = {
        "id": cid,
        "name": "",
        "preset": "custom",
        "base_url": "https://api.deepseek.com",
        "protocol": "openai",
        "models": [_m("m1")],
        "priority": 0,
        "max_concurrency": None,
        "enabled": True,
        "api_key": "sk-test",
        "key_env": "",
    }
    c.update(over)
    return c


def _report() -> dict[str, Any]:
    return {
        "at": "2026-10-07T00:00:00+00:00",
        "key_fp": "fp00",
        "stage1": {"verdict": "ok", "models": ["m1"], "detail": ""},
        "models": {
            "m1": {"verdict": "usable", "latency_s": 0.1, "detail": "", "listed": True}
        },
    }


def _put_channels(client: TestClient, channels: list[dict[str, Any]]) -> dict[str, Any]:
    r = client.put("/api/channels", json={"channels": channels})
    assert r.status_code == HTTPStatus.OK, r.text
    return r.json()


class TestGetPut:
    def test_get_projection_when_absent(self, client: TestClient) -> None:
        """零旧料：bootstrap 一次性物化缺省网关渠道，GET 回播种表。"""
        r = client.get("/api/channels")
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        assert [c["id"] for c in body["channels"]] == ["default"]
        assert body["route"] == {"channel_id": "auto", "model": ""}
        assert body["active_id"] == "default"

    def test_put_roundtrip_public_view(self, client: TestClient) -> None:
        """PUT 整表 → GET 回 public 面：api_key 绝不出参，has_api_key 报位。"""
        out = _put_channels(
            client,
            [
                _channel("ch-a", name="主力", api_key="sk-secret-a"),
                _channel(
                    "ch-b",
                    base_url="https://api.anthropic.com",
                    api_key="",
                    key_env="ANTHROPIC_API_KEY",
                ),
            ],
        )
        assert [c["id"] for c in out["channels"]] == ["ch-a", "ch-b"]
        blob = json.dumps(out)
        assert "sk-secret-a" not in blob
        assert "api_key" not in out["channels"][0]
        assert out["channels"][0]["has_api_key"] is True
        assert out["channels"][0]["name"] == "主力"
        assert out["channels"][1]["key_env"] == "ANTHROPIC_API_KEY"
        assert out["channels"][0]["models"][0] == {
            "model": "m1",
            "redirect_model": "",
            "enabled": True,
            "max_concurrency": None,
        }
        got = client.get("/api/channels").json()
        assert [c["id"] for c in got["channels"]] == ["ch-a", "ch-b"]
        # auto 路由：priority 同分按表序——ch-a 居首 → active 定位到它
        assert got["active_id"] == "ch-a"

    def test_put_invalid_400(self, client: TestClient) -> None:
        r = client.put(
            "/api/channels",
            json={"channels": [_channel("ch-a", base_url="http://8.8.8.8/x")]},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST
        r = client.put("/api/channels", json={"channels": "notalist"})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_put_rewrites_idempotent(self, client: TestClient) -> None:
        """整表替换语义：第二次 PUT 的缺席渠道真删（不做 merge）。"""
        _put_channels(client, [_channel("ch-a"), _channel("ch-b")])
        out = _put_channels(client, [_channel("ch-b")])
        assert [c["id"] for c in out["channels"]] == ["ch-b"]

    def test_get_after_put_strips_key(self, client: TestClient) -> None:
        _put_channels(client, [_channel("ch-a", api_key="sk-do-not-leak")])
        blob = client.get("/api/channels").text
        assert "sk-do-not-leak" not in blob

    def test_legacy_file_serves_migrated_view(self, tmp_path: Path) -> None:
        """endpoints.json v1 在场：bootstrap 物化为渠道表（app 创建前落盘）。"""
        from conftest import make_app  # noqa: PLC0415
        from starlette.testclient import TestClient  # noqa: PLC0415

        (tmp_path / "data").mkdir(parents=True)
        (tmp_path / "data" / "endpoints.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "profiles": [
                        {
                            "id": "p1",
                            "label": "DeepSeek",
                            "base_url": "https://api.deepseek.com",
                            "dialect": "openai",
                            "models": [{"model": "m1", "redirect_model": ""}],
                            "enabled": True,
                            "api_key": "sk-ds",
                            "key_env": "",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with TestClient(make_app(tmp_path)) as client:
            body = client.get("/api/channels").json()
        assert [c["id"] for c in body["channels"]] == ["p1"]
        assert body["channels"][0]["has_api_key"] is True
        assert "sk-ds" not in json.dumps(body)


class TestRouteEndpoint:
    def test_route_pin_roundtrip(self, client: TestClient) -> None:
        _put_channels(client, [_channel("ch-a"), _channel("ch-b")])
        r = client.post(
            "/api/channels/route", json={"channel_id": "ch-b", "model": "m1"}
        )
        assert r.status_code == HTTPStatus.OK
        assert r.json()["route"] == {"channel_id": "ch-b", "model": "m1"}
        got = client.get("/api/channels").json()
        assert got["route"]["channel_id"] == "ch-b"

    def test_route_auto_and_default(self, client: TestClient) -> None:
        _put_channels(client, [_channel("ch-a")])
        r = client.post("/api/channels/route", json={"channel_id": "auto"})
        assert r.status_code == HTTPStatus.OK
        assert r.json()["route"] == {"channel_id": "auto", "model": ""}

    def test_route_ghost_400(self, client: TestClient) -> None:
        _put_channels(client, [_channel("ch-a")])
        r = client.post("/api/channels/route", json={"channel_id": "ch-ghost"})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_route_keeps_channels_untouched(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """route 写只动 route 小节——渠道表与凭据原样。"""
        _put_channels(client, [_channel("ch-a", api_key="sk-keep")])
        client.post("/api/channels/route", json={"channel_id": "ch-a"})
        data = json.loads(
            (tmp_path / "data" / "channels.json").read_text(encoding="utf-8")
        )
        assert data["channels"][0]["api_key"] == "sk-keep"
        assert data["route"] == {"channel_id": "ch-a", "model": ""}


class TestPresets:
    def test_presets_listed(self, client: TestClient) -> None:
        r = client.get("/api/channels/presets")
        assert r.status_code == HTTPStatus.OK
        presets = r.json()["presets"]
        ids = [p["id"] for p in presets]
        assert "deepseek" in ids
        assert "custom" in ids
        deepseek = next(p for p in presets if p["id"] == "deepseek")
        assert deepseek["base_url"] == "https://api.deepseek.com"
        assert "has_env_key" in deepseek


class TestProbe:
    def _stub(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        """打桩路由面 probe_channel；返回调用记录表。"""
        calls: list[dict[str, Any]] = []

        async def fake(
            base_url: str, api_key: str, protocol: str, models: list[dict[str, Any]]
        ) -> dict[str, Any]:
            calls.append(
                {
                    "base_url": base_url,
                    "api_key": api_key,
                    "protocol": protocol,
                    "models": models,
                }
            )
            return _report()

        monkeypatch.setattr("texlate.server.routers.channels.probe_channel", fake)
        return calls

    def test_probe_by_id_uses_channel_credential(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._stub(monkeypatch)
        _put_channels(
            client,
            [
                _channel(
                    "ch-a",
                    api_key="",
                    key_env="MY_PROBE_KEY",
                    models=[{"model": "m1", "redirect_model": "wire-m1"}, _m("m2")],
                )
            ],
        )
        monkeypatch.setenv("MY_PROBE_KEY", "sk-env-resolved")
        r = client.post("/api/channels/probe", json={"id": "ch-a"})
        assert r.status_code == HTTPStatus.OK
        assert r.json()["models"]["m1"]["verdict"] == "usable"
        assert calls[0]["base_url"] == "https://api.deepseek.com"
        assert calls[0]["api_key"] == "sk-env-resolved"  # 阶梯 env 层命中
        assert calls[0]["protocol"] == "openai"
        # 无 models 选择器 → 全档条目（wire 名交给探针解析）
        assert [m["redirect_model"] for m in calls[0]["models"]] == ["wire-m1", ""]
        # 报告钉回渠道档
        got = client.get("/api/channels").json()
        assert got["channels"][0]["last_probe"]["key_fp"] == "fp00"

    def test_probe_subset_by_local_name(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``models`` 选择器按本地名取档内条目；档外名按无 redirect 直探。"""
        calls = self._stub(monkeypatch)
        _put_channels(
            client,
            [
                _channel(
                    "ch-a",
                    models=[{"model": "m1", "redirect_model": "wire-m1"}, _m("m2")],
                )
            ],
        )
        r = client.post(
            "/api/channels/probe",
            json={"id": "ch-a", "models": ["m1", "m9"]},
        )
        assert r.status_code == HTTPStatus.OK
        models = calls[0]["models"]
        assert models[0]["model"] == "m1"
        assert models[0]["redirect_model"] == "wire-m1"  # 档内 redirect 随档
        assert models[1] == {
            "model": "m9",
            "redirect_model": "",
            "enabled": True,
            "max_concurrency": None,
        }

    def test_probe_ghost_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub(monkeypatch)
        _put_channels(client, [_channel("ch-a")])
        r = client.post("/api/channels/probe", json={"id": "ch-ghost"})
        assert r.status_code == HTTPStatus.NOT_FOUND

    def test_probe_bare_requires_key(self, client: TestClient) -> None:
        """裸端点探测缺 api_key → 400（不把服务端凭据扇到任任地址）。"""
        r = client.post(
            "/api/channels/probe",
            json={"base_url": "https://api.deepseek.com", "models": [_m("m1")]},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_probe_bare_explicit_key(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._stub(monkeypatch)
        r = client.post(
            "/api/channels/probe",
            json={
                "base_url": "https://api.deepseek.com",
                "api_key": "sk-explicit",
                "protocol": "openai",
                "models": [_m("m1")],
            },
        )
        assert r.status_code == HTTPStatus.OK
        assert calls[0]["api_key"] == "sk-explicit"
        assert calls[0]["base_url"] == "https://api.deepseek.com"
        # 裸探不落 last_probe——无渠道档可钉
        got = client.get("/api/channels").json()
        assert all(c.get("last_probe") is None for c in got["channels"])

    def test_probe_bare_invalid_url(self, client: TestClient) -> None:
        r = client.post(
            "/api/channels/probe",
            json={"base_url": "http://8.8.8.8/x", "api_key": "sk-x"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST


class TestServerModeGate:
    """server 形态全面 403——渠道枚举本身是部署拓扑。

    mutation 须带 ``X-Texlate-Key`` 才能穿过匿名 401 中间件抵达 gate；
    GET 读面匿名放行，403 直接由 gate 给。
    """

    _KEY: ClassVar[dict[str, str]] = {"X-Texlate-Key": "k-A"}

    def test_get_403(self, server_client: TestClient) -> None:
        assert server_client.get("/api/channels").status_code == HTTPStatus.FORBIDDEN

    def test_put_403(self, server_client: TestClient) -> None:
        r = server_client.put(
            "/api/channels",
            json={"channels": [_channel("ch-a")]},
            headers=self._KEY,
        )
        assert r.status_code == HTTPStatus.FORBIDDEN

    def test_route_403(self, server_client: TestClient) -> None:
        r = server_client.post(
            "/api/channels/route",
            json={"channel_id": "auto"},
            headers=self._KEY,
        )
        assert r.status_code == HTTPStatus.FORBIDDEN

    def test_presets_403(self, server_client: TestClient) -> None:
        assert (
            server_client.get("/api/channels/presets").status_code
            == HTTPStatus.FORBIDDEN
        )

    def test_probe_403(self, server_client: TestClient) -> None:
        r = server_client.post(
            "/api/channels/probe", json={"id": "x"}, headers=self._KEY
        )
        assert r.status_code == HTTPStatus.FORBIDDEN

    def test_put_anonymous_401(self, server_client: TestClient) -> None:
        """无 key 的 mutation 在 gate 之前被 401 挡死——gate 永远摸不到。"""
        r = server_client.put("/api/channels", json={"channels": []})
        assert r.status_code == HTTPStatus.UNAUTHORIZED
