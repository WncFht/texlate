"""``server.endpoints`` 数据层单测：store 读写径 + 投影 + 凭据阶梯 + 两段探针。

探针侧 ``ChatClient`` 整类打桩（``endpoints_mod.ChatClient``）——``probe_endpoint``
自造 client，不走 MockTransport 注入面；verdict 断言全在报告 dict 上。
"""

from __future__ import annotations

import asyncio
import json
import stat
from typing import TYPE_CHECKING, Any, ClassVar

import pytest

from texlate.server import endpoints as ep
from texlate.xlat._dialects import ChatResult, Usage
from texlate.xlat._errors import (
    AuthError,
    ContentFilterError,
    EndpointNotFoundError,
    RetryableHTTPError,
)

if TYPE_CHECKING:
    from pathlib import Path


def _result(content: str, finish: str = "stop") -> ChatResult:
    return ChatResult(
        content=content,
        reasoning="",
        finish_reason=finish,
        usage=Usage(),
        model="m",
        latency_s=0.1,
    )


_OK_ZH = "[[MATH_1]] 范数满足 [[MATH_2]] ≤ 1；见 [[CITE_1]]。"


class _StubClient:
    """``probe_endpoint`` 内造 client 的桩：类级编程表驱动 list/chat 应答。"""

    instances: ClassVar[list[_StubClient]] = []
    list_error: ClassVar[BaseException | None] = None
    list_ids: ClassVar[list[str]] = ["m1", "m2"]
    chat_results: ClassVar[dict[str, ChatResult | BaseException]] = {}

    def __init__(
        self, base_url: str, api_key: str = "", *, dialect: str = "auto", **_kw: object
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.dialect = dialect
        self.closed = False
        type(self).instances.append(self)

    async def list_models(self) -> list[str]:
        if type(self).list_error is not None:
            raise type(self).list_error
        return list(type(self).list_ids)

    async def probe_chat(self, uid: str, *_a: object, **_kw: object) -> ChatResult:
        r = type(self).chat_results.get(uid)
        if isinstance(r, BaseException):
            raise r
        if r is None:
            return _result(_OK_ZH)
        return r

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _stub_client(monkeypatch: pytest.MonkeyPatch) -> type[_StubClient]:
    _StubClient.instances = []
    _StubClient.list_error = None
    _StubClient.list_ids = ["m1", "m2"]
    _StubClient.chat_results = {}
    monkeypatch.setattr(ep, "ChatClient", _StubClient)
    return _StubClient


@pytest.fixture
def store(tmp_path: Path) -> ep.EndpointStore:
    return ep.EndpointStore(tmp_path)


def _profile(pid: str = "p1", **over: object) -> dict[str, Any]:
    p: dict[str, Any] = {
        "id": pid,
        "label": "",
        "base_url": "https://api.deepseek.com",
        "dialect": "auto",
        "models": ["m1"],
        "enabled": True,
        "api_key": "sk-test-key",
        "key_env": "",
        "last_probe": None,
    }
    p.update(over)
    return p


# ---------------------------------------------------------------- load/save


class TestLoadSave:
    def test_absent_empty(self, store: ep.EndpointStore) -> None:
        data = store.load()
        assert data == {"version": 1, "profiles": []}

    def test_roundtrip_0600(self, store: ep.EndpointStore) -> None:
        out = store.save([_profile()])
        assert out[0]["id"] == "p1"
        assert out[0]["label"] == "deepseek"  # 空 label → provider 兜底名
        mode = stat.S_IMODE(store.path.stat().st_mode)
        assert mode == (stat.S_IRUSR | stat.S_IWUSR)
        loaded = store.load()
        assert loaded["profiles"][0]["api_key"] == "sk-test-key"

    def test_corrupt_quarantine(self, store: ep.EndpointStore) -> None:
        store.path.write_text("{bad json", encoding="utf-8")
        assert store.load()["profiles"] == []
        siblings = [p.name for p in store.path.parent.glob("endpoints-invalid-*.json")]
        assert len(siblings) == 1
        assert not store.path.exists()

    def test_version_mismatch_kept(self, store: ep.EndpointStore) -> None:
        store.path.write_text(
            json.dumps({"version": 99, "profiles": [_profile()]}), encoding="utf-8"
        )
        assert store.load()["profiles"] == []
        assert store.path.exists()  # 高版本文件不隔离——留给新进程

    def test_malformed_member_dropped(self, store: ep.EndpointStore) -> None:
        store.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "profiles": [
                        _profile("good"),
                        _profile("BAD ID"),  # 非法 slug → 整条丢
                        _profile(
                            "good2", base_url="http://8.8.8.8/x"
                        ),  # 公网 http → 丢
                        "not-a-dict",
                        42,
                    ],
                }
            ),
            encoding="utf-8",
        )
        ids = [p["id"] for p in store.load()["profiles"]]
        assert ids == ["good"]

    def test_handmade_mutex_conflict_env_wins(self, store: ep.EndpointStore) -> None:
        """手改文件 api_key+key_env 双非空 → 读径 env 引用优先（不落盘更安全）。"""
        store.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "profiles": [_profile(api_key="sk-x", key_env="MY_KEY")],
                }
            ),
            encoding="utf-8",
        )
        p = store.load()["profiles"][0]
        assert p["api_key"] == ""
        assert p["key_env"] == "MY_KEY"


class TestSaveRules:
    def test_id_slug(self, store: ep.EndpointStore) -> None:
        for bad in ("BAD", "-lead", "", "a" * 33, "has_underscore", 42):
            with pytest.raises(ValueError, match="id"):
                store.save([_profile(id=bad)])  # type: ignore[arg-type]

    def test_mutex_explicit(self, store: ep.EndpointStore) -> None:
        with pytest.raises(ValueError, match="互斥"):
            store.save([_profile(api_key="sk-x", key_env="MY_ENV")])

    def test_empty_api_key_keeps_old(self, store: ep.EndpointStore) -> None:
        store.save([_profile(api_key="sk-old")])
        out = store.save([_profile(api_key="", label="renamed")])
        assert out[0]["api_key"] == "sk-old"

    def test_explicit_switch_clears_other(self, store: ep.EndpointStore) -> None:
        store.save([_profile(api_key="sk-old")])
        out = store.save([_profile(api_key="", key_env="MY_ENV")])
        assert out[0]["api_key"] == ""
        assert out[0]["key_env"] == "MY_ENV"
        out = store.save([_profile(api_key="sk-new")])
        assert out[0]["api_key"] == "sk-new"
        assert out[0]["key_env"] == ""

    def test_models_cap_and_type(self, store: ep.EndpointStore) -> None:
        with pytest.raises(ValueError, match="至多"):
            store.save([_profile(models=[f"m{i}" for i in range(9)])])
        with pytest.raises(TypeError, match="string"):
            store.save([_profile(models=["m1", 42])])

    def test_dup_id_rejected(self, store: ep.EndpointStore) -> None:
        with pytest.raises(ValueError, match="重复"):
            store.save([_profile("a"), _profile("a")])

    def test_count_cap(self, store: ep.EndpointStore) -> None:
        with pytest.raises(ValueError, match="16"):
            store.save([_profile(f"p{i}") for i in range(17)])

    def test_put_last_probe_ignored(self, store: ep.EndpointStore) -> None:
        """客户端自带 last_probe 一律丢弃——探针报告服务端独占。"""
        out = store.save([_profile(last_probe={"at": "fake", "key_fp": "x"})])
        assert out[0]["last_probe"] is None

    def test_last_probe_preserved_when_unchanged(self, store: ep.EndpointStore) -> None:
        store.save([_profile()])
        store.record_probe("p1", _probe_report(key="sk-test-key"))
        out = store.save([_profile(label="still same")])  # 端点面+key 未变
        assert out[0]["last_probe"]["stage1"]["verdict"] == "ok"

    def test_last_probe_dropped_on_endpoint_change(
        self, store: ep.EndpointStore
    ) -> None:
        store.save([_profile()])
        store.record_probe("p1", _probe_report(key="sk-test-key"))
        out = store.save([_profile(models=["m1", "m2"])])
        assert out[0]["last_probe"] is None
        store.save([_profile()])
        store.record_probe("p1", _probe_report(key="sk-test-key"))
        out = store.save([_profile(api_key="sk-rotated")])
        assert out[0]["last_probe"] is None


class TestRecordProbe:
    def test_stamp_and_noop(self, store: ep.EndpointStore) -> None:
        store.save([_profile()])
        store.record_probe("p1", _probe_report())
        assert store.load()["profiles"][0]["last_probe"]["key_fp"] == _fp("k")
        store.record_probe("ghost", _probe_report())  # no-op 不炸
        assert store.load()["profiles"][0]["last_probe"]["key_fp"] == _fp("k")

    def test_noop_absent_file(self, store: ep.EndpointStore) -> None:
        store.record_probe("p1", _probe_report())
        assert not store.path.exists()


def _fp(key: str) -> str:
    return ep._key_fp(key)  # noqa: SLF001 -- 测本叶私有件同文件直取


def _probe_report(key: str = "k") -> dict[str, Any]:
    return {
        "at": "2026-10-07T00:00:00+00:00",
        "key_fp": _fp(key),
        "stage1": {"verdict": "ok", "models": ["m1"], "detail": ""},
        "models": {
            "m1": {"verdict": "usable", "latency_s": 0.5, "detail": "", "listed": True}
        },
    }


# ---------------------------------------------------------------- 投影/出参


class TestProjection:
    def test_absent_file_projects(
        self, store: ep.EndpointStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TEXLATE_API_KEY", raising=False)
        settings = {
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-ds",
            "model": "deepseek-chat",
            "dialect": "openai",
        }
        connections = {
            "https://api.deepseek.com": {
                "api_key": "sk-ds",
                "model": "deepseek-chat",
                "dialect": "openai",
            },
            "https://openrouter.ai/api": {
                "api_key": "sk-or",
                "model": "some/free",
                "dialect": "openai",
            },
        }
        profiles = store.effective_profiles(settings, connections)
        assert [p["id"] for p in profiles] == ["default", "openrouter-ai"]
        assert profiles[0]["models"] == ["deepseek-chat"]
        assert profiles[0]["api_key"] == "sk-ds"
        assert profiles[1]["api_key"] == "sk-or"
        assert not store.path.exists()  # 投影不落盘

    def test_file_wins_over_projection(self, store: ep.EndpointStore) -> None:
        store.save([_profile("mine", base_url="https://api.anthropic.com")])
        profiles = store.effective_profiles(
            {"base_url": "https://api.deepseek.com"}, {}
        )
        assert [p["id"] for p in profiles] == ["mine"]

    def test_active_id(self) -> None:
        profiles = [
            _profile("a", base_url="https://api.deepseek.com", enabled=False),
            _profile("b", base_url="https://api.anthropic.com"),
        ]
        # enabled=False 仍是活动定位（身份≠参与）;尾斜杠归一命中
        assert ep.active_id(profiles, {"base_url": "https://api.deepseek.com/"}) == "a"
        assert ep.active_id(profiles, {"base_url": "https://api.openai.com"}) == ""

    def test_public_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TEST_KEY", "sk-hidden")
        pub = ep.public_profile(_profile(api_key="sk-secret", key_env="MY_TEST_KEY"))
        assert "api_key" not in pub
        blob = json.dumps(pub)
        assert "sk-secret" not in blob
        assert pub["has_api_key"] is True
        assert pub["key_env"] == "MY_TEST_KEY"
        assert pub["has_env_key"] is True
        monkeypatch.delenv("MY_TEST_KEY")
        assert (
            ep.public_profile(_profile(key_env="MY_TEST_KEY"))["has_env_key"] is False
        )


class TestCredentialLadder:
    def test_inline_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_KEY", "sk-env")
        key, src = ep.credential_for(
            _profile(api_key="sk-inline", key_env=""),
            {"https://api.deepseek.com": {"api_key": "sk-conn"}},
        )
        assert (key, src) == ("sk-inline", "profile")

    def test_key_env_second(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_KEY", "sk-env")
        key, src = ep.credential_for(
            _profile(api_key="", key_env="MY_KEY"),
            {"https://api.deepseek.com": {"api_key": "sk-conn"}},
        )
        assert (key, src) == ("sk-env", "env:MY_KEY")

    def test_connections_third(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEXLATE_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        key, src = ep.credential_for(
            _profile(api_key=""),
            {"https://api.deepseek.com": {"api_key": "sk-conn"}},
        )
        assert (key, src) == ("sk-conn", "connection")

    def test_provider_env_last(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-penv")
        monkeypatch.delenv("TEXLATE_API_KEY", raising=False)
        key, src = ep.credential_for(_profile(api_key=""), {})
        assert (key, src) == ("sk-penv", "provider_env")

    def test_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("TEXLATE_API_KEY", "DEEPSEEK_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        key, src = ep.credential_for(_profile(api_key=""), {})
        assert (key, src) == ("", "none")

    def test_key_env_for(self, store: ep.EndpointStore) -> None:
        store.save(
            [
                _profile(
                    "a",
                    base_url="https://api.deepseek.com",
                    api_key="",
                    key_env="DS_KEY",
                    enabled=False,
                ),
                _profile("b", base_url="https://api.anthropic.com"),
            ]
        )
        assert (
            store.key_env_for("https://api.deepseek.com") == "DS_KEY"
        )  # disabled 也查
        assert store.key_env_for("https://api.anthropic.com") == ""
        assert store.key_env_for("https://example.com/x") == ""


# ---------------------------------------------------------------- 探针


class TestProbeEndpoint:
    def test_ok_two_stage(self) -> None:
        _StubClient.list_ids = ["m1", "ghost"]
        report = asyncio.run(
            ep.probe_endpoint("https://x.test", "sk-k", "openai", ["m1", "m9"])
        )
        assert report["stage1"]["verdict"] == "ok"
        assert report["stage1"]["models"] == ["m1", "ghost"]
        assert report["models"]["m1"]["verdict"] == "usable"
        assert report["models"]["m1"]["listed"] is True
        assert report["models"]["m9"]["listed"] is False
        assert report["key_fp"] == _fp("sk-k")
        assert _StubClient.instances[0].closed  # aclose 到位

    def test_placeholder_lost(self) -> None:
        _StubClient.chat_results = {"m1": _result("范数满足 ≤ 1；见引用。")}
        report = asyncio.run(ep.probe_endpoint("https://x.test", "", "auto", ["m1"]))
        assert report["models"]["m1"]["verdict"] == "placeholder_lost"

    def test_no_cjk(self) -> None:
        _StubClient.chat_results = {
            "m1": _result("The [[MATH_1]] norm satisfies [[MATH_2]]; see [[CITE_1]].")
        }
        report = asyncio.run(ep.probe_endpoint("https://x.test", "", "auto", ["m1"]))
        assert report["models"]["m1"]["verdict"] == "no_cjk"

    def test_empty_and_refused(self) -> None:
        _StubClient.chat_results = {
            "m1": _result("   "),
            "m2": ContentFilterError("filtered", status=400),
        }
        report = asyncio.run(
            ep.probe_endpoint("https://x.test", "", "auto", ["m1", "m2"])
        )
        assert report["models"]["m1"]["verdict"] == "empty"
        assert report["models"]["m2"]["verdict"] == "refused"

    def test_stage1_auth_skips_stage2(self) -> None:
        _StubClient.list_error = AuthError("HTTP 401: bad key", status=401)
        report = asyncio.run(
            ep.probe_endpoint("https://x.test", "sk-bad", "auto", ["m1", "m2"])
        )
        assert report["stage1"]["verdict"] == "auth_failed"
        assert all(m["verdict"] == "skipped" for m in report["models"].values())

    def test_no_models_dir_still_probes(self) -> None:
        _StubClient.list_error = EndpointNotFoundError("HTTP 404", status=404)
        report = asyncio.run(ep.probe_endpoint("https://x.test", "", "auto", ["m1"]))
        assert report["stage1"]["verdict"] == "no_models_dir"
        assert report["models"]["m1"]["verdict"] == "usable"
        assert report["models"]["m1"]["listed"] is None

    def test_unreachable_skips(self) -> None:
        _StubClient.list_error = RetryableHTTPError(
            "transport error: timed out", status=-1
        )
        report = asyncio.run(ep.probe_endpoint("https://x.test", "", "auto", ["m1"]))
        assert report["stage1"]["verdict"] == "timeout"
        assert report["models"]["m1"]["verdict"] == "skipped"

    def test_stage2_transport_and_http(self) -> None:
        _StubClient.chat_results = {
            "m1": RetryableHTTPError("transport error: connection refused", status=-1),
            "m2": RetryableHTTPError("HTTP 500: boom", status=500),
        }
        report = asyncio.run(
            ep.probe_endpoint("https://x.test", "", "auto", ["m1", "m2"])
        )
        assert report["models"]["m1"]["verdict"] == "unreachable"
        assert report["models"]["m2"]["verdict"] == "http_error"

    def test_models_capped_at_8(self) -> None:
        report = asyncio.run(
            ep.probe_endpoint(
                "https://x.test", "", "auto", [f"m{i}" for i in range(12)]
            )
        )
        assert len(report["models"]) == ep.MAX_MODELS_PER_PROFILE

    def test_detail_scrubs_key(self) -> None:
        _StubClient.chat_results = {
            "m1": AuthError("HTTP 401: bad key sk-SECRET123", status=401),
        }
        report = asyncio.run(
            ep.probe_endpoint("https://x.test", "sk-SECRET123", "auto", ["m1"])
        )
        assert "sk-SECRET123" not in json.dumps(report)
        assert report["models"]["m1"]["verdict"] == "auth_failed"
