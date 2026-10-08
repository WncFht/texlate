"""``server.channels`` 数据层单测：store 读写径 + 迁移 + 冷却 + 路由决议 + 探针。

探针侧 ``ChatClient`` 整类打桩（``channels_mod.ChatClient``）——``probe_channel``
自造 client，不走 MockTransport 注入面；verdict 断言全在报告 dict 上。
冷却测试一律用本地 ``Cooldowns()`` 实例或 monkeypatch 模块单例——不污染
跨用例的进程级 ``cooldowns``。
"""

from __future__ import annotations

import asyncio
import json
import stat
from typing import TYPE_CHECKING, Any, ClassVar

import pytest

from texlate.server import channels as ch
from texlate.xlat._dialects import ChatResult, Usage
from texlate.xlat._errors import (
    AuthError,
    BillingError,
    ChatError,
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
    """``probe_channel`` 内造 client 的桩：类级编程表驱动 list/chat 应答。"""

    instances: ClassVar[list[_StubClient]] = []
    list_error: ClassVar[BaseException | None] = None
    list_ids: ClassVar[list[str]] = ["m1", "m2"]
    chat_results: ClassVar[dict[str, ChatResult | BaseException]] = {}
    seen_uids: ClassVar[list[str]] = []

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
        type(self).seen_uids.append(uid)
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
    _StubClient.seen_uids = []
    monkeypatch.setattr(ch, "ChatClient", _StubClient)
    return _StubClient


@pytest.fixture
def store(tmp_path: Path) -> ch.ChannelStore:
    return ch.ChannelStore(tmp_path)


@pytest.fixture
def fresh_cooldowns(monkeypatch: pytest.MonkeyPatch) -> ch.Cooldowns:
    """模块级 ``cooldowns`` 换成空表——冷却断言不被跨用例落戳污染。"""
    cd = ch.Cooldowns()
    monkeypatch.setattr(ch, "cooldowns", cd)
    return cd


def _m(model: str, redirect: str = "") -> dict[str, str]:
    """模型条目夹具——写径输入形（``enabled``/``max_concurrency`` 归一补默认）。"""
    return {"model": model, "redirect_model": redirect}


def _norm_m(model: str, redirect: str = "") -> dict[str, Any]:
    """归一后模型条目形态（断言读径出参用）。"""
    return {
        "model": model,
        "redirect_model": redirect,
        "enabled": True,
        "max_concurrency": None,
    }


def _channel(cid: str = "ch-p1", **over: object) -> dict[str, Any]:
    c: dict[str, Any] = {
        "id": cid,
        "name": "",
        "preset": "custom",
        "base_url": "https://api.deepseek.com",
        "protocol": "auto",
        "models": [_m("m1")],
        "priority": 0,
        "max_concurrency": None,
        "enabled": True,
        "api_key": "sk-test-key",
        "key_env": "",
        "last_probe": None,
    }
    c.update(over)
    return c


def _saved_channels(out: dict[str, Any]) -> list[dict[str, Any]]:
    """``save()`` 出参 → 渠道表。"""
    return out["channels"]


# ---------------------------------------------------------------- load/save


class TestLoadSave:
    def test_absent_empty(self, store: ch.ChannelStore) -> None:
        data = store.load()
        assert data == {
            "version": 2,
            "channels": [],
            "route": {"channel_id": "auto", "model": ""},
        }

    def test_roundtrip_0600(self, store: ch.ChannelStore) -> None:
        out = store.save([_channel()])
        assert out["channels"][0]["id"] == "ch-p1"
        assert out["channels"][0]["name"] == "deepseek"  # 空 name → provider 兜底名
        mode = stat.S_IMODE(store.path.stat().st_mode)
        assert mode == (stat.S_IRUSR | stat.S_IWUSR)
        loaded = store.load()
        assert loaded["channels"][0]["api_key"] == "sk-test-key"
        assert loaded["route"] == {"channel_id": "auto", "model": ""}

    def test_generated_id(self, store: ch.ChannelStore) -> None:
        """id 缺席/空串 → 服务端生成 ``ch-<8hex>`` 稳定键。"""
        out = store.save([_channel(id=""), _channel(id=None)])
        ids = [c["id"] for c in out["channels"]]
        assert all(i.startswith("ch-") and len(i) == 11 for i in ids)  # noqa: PLR2004 -- "ch-"+8hex
        assert ids[0] != ids[1]
        assert store.load()["channels"][0]["id"] == ids[0]  # 钉死不再变

    def test_corrupt_quarantine(self, store: ch.ChannelStore) -> None:
        store.path.write_text("{bad json", encoding="utf-8")
        assert store.load()["channels"] == []
        siblings = [p.name for p in store.path.parent.glob("channels-invalid-*.json")]
        assert len(siblings) == 1
        assert not store.path.exists()

    def test_version_mismatch_kept(self, store: ch.ChannelStore) -> None:
        store.path.write_text(
            json.dumps({"version": 99, "channels": [_channel()]}), encoding="utf-8"
        )
        assert store.load()["channels"] == []
        assert store.path.exists()  # 高版本文件不隔离——留给新进程

    def test_malformed_member_dropped(self, store: ch.ChannelStore) -> None:
        store.path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "channels": [
                        _channel("good"),
                        _channel("BAD ID"),  # 非法 slug → 整条丢
                        _channel(
                            "good2", base_url="http://8.8.8.8/x"
                        ),  # 公网 http → 丢
                        "not-a-dict",
                        42,
                    ],
                }
            ),
            encoding="utf-8",
        )
        ids = [c["id"] for c in store.load()["channels"]]
        assert ids == ["good"]

    def test_str_models_member_dropped(self, store: ch.ChannelStore) -> None:
        """裸 str-models 渠道无兼容——整档按坏成员读径丢弃（不升级、不改写）。"""
        store.path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "channels": [
                        _channel("legacy", models=["m1"]),
                        _channel("fresh", models=[_m("m1")]),
                    ],
                }
            ),
            encoding="utf-8",
        )
        assert [c["id"] for c in store.load()["channels"]] == ["fresh"]

    def test_handmade_mutex_conflict_env_wins(self, store: ch.ChannelStore) -> None:
        """手改文件 api_key+key_env 双非空 → 读径 env 引用优先（不落盘更安全）。"""
        store.path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "channels": [_channel(api_key="sk-x", key_env="MY_KEY")],
                }
            ),
            encoding="utf-8",
        )
        c = store.load()["channels"][0]
        assert c["api_key"] == ""
        assert c["key_env"] == "MY_KEY"


class TestSaveRules:
    def test_id_slug(self, store: ch.ChannelStore) -> None:
        for bad in ("BAD", "-lead", "a" * 33, "has_underscore", 42):
            with pytest.raises(ValueError, match="id"):
                store.save([_channel(id=bad)])  # type: ignore[arg-type]

    def test_mutex_explicit(self, store: ch.ChannelStore) -> None:
        with pytest.raises(ValueError, match="互斥"):
            store.save([_channel(api_key="sk-x", key_env="MY_ENV")])

    def test_empty_api_key_keeps_old(self, store: ch.ChannelStore) -> None:
        store.save([_channel(api_key="sk-old")])
        out = store.save([_channel(api_key="", name="renamed")])
        assert _saved_channels(out)[0]["api_key"] == "sk-old"

    def test_explicit_switch_clears_other(self, store: ch.ChannelStore) -> None:
        store.save([_channel(api_key="sk-old")])
        out = store.save([_channel(api_key="", key_env="MY_ENV")])
        assert _saved_channels(out)[0]["api_key"] == ""
        assert _saved_channels(out)[0]["key_env"] == "MY_ENV"
        out = store.save([_channel(api_key="sk-new")])
        assert _saved_channels(out)[0]["api_key"] == "sk-new"
        assert _saved_channels(out)[0]["key_env"] == ""

    def test_models_cap_and_type(self, store: ch.ChannelStore) -> None:
        with pytest.raises(ValueError, match="至多"):
            store.save([_channel(models=[_m(f"m{i}") for i in range(9)])])
        with pytest.raises(TypeError, match="对象"):
            store.save([_channel(models=["m1"])])  # 裸 str 不收
        with pytest.raises(TypeError, match="对象"):
            store.save([_channel(models=[42])])
        with pytest.raises(TypeError, match="model"):
            store.save([_channel(models=[{"redirect_model": "m"}])])  # 缺 model
        with pytest.raises(TypeError, match="redirect_model"):
            store.save([_channel(models=[{"model": "m", "redirect_model": 1}])])

    def test_models_normalize_dict(self, store: ch.ChannelStore) -> None:
        """dict 条目归一：redirect==model 清成空、按本地名去重保序、补默认键。"""
        out = store.save(
            [
                _channel(
                    models=[
                        _m("m1"),
                        {"model": "alias", "redirect_model": "wire-x"},
                        {"model": "m2", "redirect_model": "m2"},
                        {"model": "m1", "redirect_model": "dup"},  # 本地名撞 → 丢
                        {
                            "model": "m3",
                            "redirect_model": "",
                            "enabled": False,
                            "max_concurrency": 3,
                        },
                    ]
                )
            ]
        )
        assert _saved_channels(out)[0]["models"] == [
            _norm_m("m1"),
            _norm_m("alias", "wire-x"),
            _norm_m("m2"),
            {
                "model": "m3",
                "redirect_model": "",
                "enabled": False,
                "max_concurrency": 3,
            },
        ]
        # 重载读径 dict 形态自持
        assert (
            store.load()["channels"][0]["models"] == _saved_channels(out)[0]["models"]
        )

    def test_wire_model_helper(self) -> None:
        assert ch.wire_model({"model": "a", "redirect_model": ""}) == "a"
        assert ch.wire_model({"model": "a", "redirect_model": "r"}) == "r"
        assert ch.local_model_name({"model": "a", "redirect_model": "r"}) == "a"

    def test_max_concurrency_clamp(self, store: ch.ChannelStore) -> None:
        """渠道/模型并发上限：null/0 → None（不限）；正 int clamp ≤64；非法 → ValueError。"""
        out = store.save([_channel(max_concurrency=0)])
        assert _saved_channels(out)[0]["max_concurrency"] is None
        out = store.save([_channel(max_concurrency=999)])
        assert _saved_channels(out)[0]["max_concurrency"] == ch.MAX_CONCURRENCY_CAP
        out = store.save([_channel(models=[{"model": "m1", "max_concurrency": 999}])])
        assert (
            _saved_channels(out)[0]["models"][0]["max_concurrency"]
            == ch.MAX_CONCURRENCY_CAP
        )
        with pytest.raises(ValueError, match="max_concurrency"):
            store.save([_channel(max_concurrency="high")])

    def test_preset_membership(self, store: ch.ChannelStore) -> None:
        out = store.save([_channel(preset="deepseek")])
        assert _saved_channels(out)[0]["preset"] == "deepseek"
        with pytest.raises(ValueError, match="preset"):
            store.save([_channel(preset="no-such-preset")])

    def test_dup_id_rejected(self, store: ch.ChannelStore) -> None:
        with pytest.raises(ValueError, match="重复"):
            store.save([_channel("ch-a"), _channel("ch-a")])

    def test_count_cap(self, store: ch.ChannelStore) -> None:
        with pytest.raises(ValueError, match="16"):
            store.save([_channel(f"ch-{i}") for i in range(17)])

    def test_put_last_probe_ignored(self, store: ch.ChannelStore) -> None:
        """客户端自带 last_probe 一律丢弃——探针报告服务端独占。"""
        out = store.save([_channel(last_probe={"at": "fake", "key_fp": "x"})])
        assert _saved_channels(out)[0]["last_probe"] is None

    def test_last_probe_preserved_when_unchanged(self, store: ch.ChannelStore) -> None:
        store.save([_channel()])
        store.record_probe("ch-p1", _probe_report(key="sk-test-key"))
        out = store.save([_channel(name="still same")])  # 渠道面+key 未变
        assert _saved_channels(out)[0]["last_probe"]["stage1"]["verdict"] == "ok"

    def test_last_probe_dropped_on_channel_change(self, store: ch.ChannelStore) -> None:
        store.save([_channel()])
        store.record_probe("ch-p1", _probe_report(key="sk-test-key"))
        out = store.save([_channel(models=[_m("m1"), _m("m2")])])
        assert _saved_channels(out)[0]["last_probe"] is None
        store.save([_channel()])
        store.record_probe("ch-p1", _probe_report(key="sk-test-key"))
        out = store.save([_channel(api_key="sk-rotated")])
        assert _saved_channels(out)[0]["last_probe"] is None


class TestRoute:
    def test_save_route_roundtrip(self, store: ch.ChannelStore) -> None:
        out = store.save(
            [_channel("ch-a"), _channel("ch-b")],
            {"channel_id": "ch-b", "model": "m1"},
        )
        assert out["route"] == {"channel_id": "ch-b", "model": "m1"}
        assert store.load()["route"]["channel_id"] == "ch-b"

    def test_route_none_keeps_old(self, store: ch.ChannelStore) -> None:
        store.save([_channel("ch-a")], {"channel_id": "ch-a", "model": "m1"})
        out = store.save([_channel("ch-a")])  # route=None 承旧
        assert out["route"] == {"channel_id": "ch-a", "model": "m1"}

    def test_route_pin_ghost_rejected(self, store: ch.ChannelStore) -> None:
        with pytest.raises(ValueError, match="不存在"):
            store.save([_channel("ch-a")], {"channel_id": "ch-ghost"})

    def test_route_survives_channel_delete(self, store: ch.ChannelStore) -> None:
        """读径容错：route 指向已删渠道 → 落 auto 不丢 model。"""
        store.save([_channel("ch-a")], {"channel_id": "ch-a", "model": "m1"})
        store.save([])  # 渠道清空——route=None 臂走读径校验归 auto
        assert store.load()["route"] == {"channel_id": "auto", "model": "m1"}

    def test_route_bad_model_rejected(self, store: ch.ChannelStore) -> None:
        # 控制字符是非 printable——validate_model 唯一会拒的形态
        with pytest.raises(ValueError, match="invalid model"):
            store.save(
                [_channel("ch-a")], {"channel_id": "auto", "model": "bad\nmodel"}
            )
        # 读径容错面：手改烂 model → 空串
        store.path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "channels": [_channel()],
                    "route": {"channel_id": "auto", "model": "bad\nmodel"},
                }
            ),
            encoding="utf-8",
        )
        assert store.load()["route"]["model"] == ""


class TestRecordProbe:
    def test_stamp_and_noop(self, store: ch.ChannelStore) -> None:
        store.save([_channel()])
        store.record_probe("ch-p1", _probe_report())
        assert store.load()["channels"][0]["last_probe"]["key_fp"] == _fp("k")
        store.record_probe("ghost", _probe_report())  # no-op 不炸
        assert store.load()["channels"][0]["last_probe"]["key_fp"] == _fp("k")

    def test_noop_absent_file(self, store: ch.ChannelStore) -> None:
        store.record_probe("ch-p1", _probe_report())
        assert not store.path.exists()

    def test_merge_same_key_partial_probe(self, store: ch.ChannelStore) -> None:
        """同凭据子集探测：被探模型 verdict 更新，未探模型保留旧值。"""
        store.save([_channel()])
        store.record_probe("ch-p1", _probe_report(key="k"))
        partial = {
            "at": "2026-10-07T01:00:00+00:00",
            "key_fp": _fp("k"),
            "stage1": {"verdict": "ok", "models": ["m1", "m2"], "detail": ""},
            "models": {
                "m2": {
                    "verdict": "usable",
                    "latency_s": 0.7,
                    "detail": "",
                    "listed": True,
                }
            },
        }
        store.record_probe("ch-p1", partial)
        models = store.load()["channels"][0]["last_probe"]["models"]
        # 未探的 m1 整条保留旧 verdict；m2 是新探测结果
        assert models["m1"] == {
            "verdict": "usable",
            "latency_s": 0.5,
            "detail": "",
            "listed": True,
        }
        assert models["m2"]["verdict"] == "usable"

    def test_merge_stage1_only_keeps_models(self, store: ch.ChannelStore) -> None:
        """stage1-only 报告（获取模型径）不清空既有 stage2 verdict。"""
        store.save([_channel()])
        store.record_probe("ch-p1", _probe_report(key="k"))
        stage1_only = {
            "at": "2026-10-07T01:00:00+00:00",
            "key_fp": _fp("k"),
            "stage1": {"verdict": "ok", "models": ["x", "y"], "detail": ""},
            "models": {},
        }
        store.record_probe("ch-p1", stage1_only)
        last = store.load()["channels"][0]["last_probe"]
        assert last["stage1"]["models"] == ["x", "y"]  # stage1 更新
        assert last["models"]["m1"]["verdict"] == "usable"  # stage2 保留

    def test_key_fp_change_replaces_wholesale(self, store: ch.ChannelStore) -> None:
        """换凭据 → 旧 verdict 对新 key 无效，整报告覆盖不 merge。"""
        store.save([_channel()])
        old = _probe_report(key="k")
        old["models"]["m-gone"] = {
            "verdict": "usable",
            "latency_s": 0.1,
            "detail": "",
            "listed": True,
        }
        store.record_probe("ch-p1", old)
        store.record_probe("ch-p1", _probe_report(key="rotated"))
        models = store.load()["channels"][0]["last_probe"]["models"]
        assert set(models) == {"m1"}  # 旧 key 的 m-gone 不残留


def _fp(key: str) -> str:
    return ch._key_fp(key)  # noqa: SLF001 -- 测本叶私有件同文件直取


def _probe_report(key: str = "k") -> dict[str, Any]:
    return {
        "at": "2026-10-07T00:00:00+00:00",
        "key_fp": _fp(key),
        "stage1": {"verdict": "ok", "models": ["m1"], "detail": ""},
        "models": {
            "m1": {"verdict": "usable", "latency_s": 0.5, "detail": "", "listed": True}
        },
    }


# ---------------------------------------------------------------- 迁移


class TestLegacyMigration:
    """v1 ``endpoints.json`` → v2 读径转形 + save 收尾改名。"""

    def _v1(self, tmp_path: Path, profiles: list[dict[str, Any]]) -> None:
        (tmp_path / "endpoints.json").write_text(
            json.dumps({"version": 1, "profiles": profiles}, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_legacy_reads_as_channels(
        self, store: ch.ChannelStore, tmp_path: Path
    ) -> None:
        """label→name、dialect→protocol、档案序→priority 差 10 递减、不落盘。"""
        self._v1(
            tmp_path,
            [
                {
                    "id": "p1",
                    "label": "DeepSeek 主",
                    "base_url": "https://api.deepseek.com",
                    "dialect": "openai",
                    "models": [{"model": "m1", "redirect_model": "wire-m1"}],
                    "enabled": True,
                    "api_key": "sk-ds",
                    "key_env": "",
                },
                {
                    "id": "p2",
                    "label": "",
                    "base_url": "https://api.anthropic.com",
                    "dialect": "auto",
                    "models": [],
                    "enabled": False,
                    "api_key": "",
                    "key_env": "ANT_KEY",
                },
            ],
        )
        data = store.load()
        assert data["version"] == ch.SCHEMA_VERSION
        assert [c["id"] for c in data["channels"]] == ["p1", "p2"]
        c0 = data["channels"][0]
        assert c0["name"] == "DeepSeek 主"
        assert c0["protocol"] == "openai"
        assert c0["models"][0]["redirect_model"] == "wire-m1"
        assert c0["models"][0]["enabled"] is True  # 缺省键归一补齐
        assert c0["priority"] == 2 * ch.PRIORITY_STEP  # 序 0 → (2-0)*step
        assert data["channels"][1]["priority"] == ch.PRIORITY_STEP
        assert data["route"] == {"channel_id": "auto", "model": ""}
        assert not store.path.exists()  # 读径转形不落盘

    def test_save_materializes_and_renames_legacy(
        self, store: ch.ChannelStore, tmp_path: Path
    ) -> None:
        """首个 save 落 channels.json + 旧件改名 ``endpoints-migrated-*`` 留档。"""
        self._v1(
            tmp_path,
            [
                {
                    "id": "p1",
                    "label": "x",
                    "base_url": "https://api.deepseek.com",
                    "dialect": "auto",
                    "models": [],
                    "enabled": True,
                    "api_key": "sk-ds",
                    "key_env": "",
                }
            ],
        )
        out = store.save(store.load()["channels"])
        assert store.path.exists()
        assert _saved_channels(out)[0]["id"] == "p1"
        migrated = list(tmp_path.glob("endpoints-migrated-*.json"))
        assert len(migrated) == 1
        assert not (tmp_path / "endpoints.json").exists()

    def test_legacy_corrupt_or_wrong_version_ignored(
        self, store: ch.ChannelStore, tmp_path: Path
    ) -> None:
        (tmp_path / "endpoints.json").write_text("{bad", encoding="utf-8")
        assert store.load()["channels"] == []
        (tmp_path / "endpoints.json").write_text(
            json.dumps({"version": 9, "profiles": []}), encoding="utf-8"
        )
        assert store.load()["channels"] == []


# ---------------------------------------------------------------- 投影/出参


class TestProjection:
    def test_absent_file_projects(
        self, store: ch.ChannelStore, monkeypatch: pytest.MonkeyPatch
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
        channels = store.effective_channels(settings, connections)
        assert [c["id"] for c in channels] == [
            "default",
            ch._stable_id(  # noqa: SLF001
                "https://openrouter.ai/api"
            ),
        ]
        assert channels[0]["models"] == [
            {
                "model": "deepseek-chat",
                "redirect_model": "",
                "enabled": True,
                "max_concurrency": None,
            }
        ]
        assert channels[0]["api_key"] == "sk-ds"
        assert channels[1]["api_key"] == "sk-or"
        assert not store.path.exists()  # 投影不落盘

    def test_file_wins_over_projection(self, store: ch.ChannelStore) -> None:
        store.save([_channel("ch-mine", base_url="https://api.anthropic.com")])
        channels = store.effective_channels(
            {"base_url": "https://api.deepseek.com"}, {}
        )
        assert [c["id"] for c in channels] == ["ch-mine"]

    def test_active_channel_id(self) -> None:
        channels = [
            _channel("ch-a", base_url="https://api.deepseek.com", enabled=False),
            _channel("ch-b", base_url="https://api.anthropic.com"),
        ]
        # enabled=False 仍是活动定位（身份≠参与）;尾斜杠归一命中
        assert (
            ch.active_channel_id(channels, {"base_url": "https://api.deepseek.com/"})
            == "ch-a"
        )
        assert (
            ch.active_channel_id(channels, {"base_url": "https://api.openai.com"}) == ""
        )

    def test_public_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TEST_KEY", "sk-hidden")
        # api_key/key_env 互斥只在写径——构造面直接给双键 dict 验出参剥离
        pub = ch.public_channel(
            _channel(api_key="sk-secret") | {"key_env": "MY_TEST_KEY"}
        )
        assert "api_key" not in pub
        blob = json.dumps(pub)
        assert "sk-secret" not in blob
        assert pub["has_api_key"] is True
        assert pub["key_env"] == "MY_TEST_KEY"
        assert pub["has_env_key"] is True
        monkeypatch.delenv("MY_TEST_KEY")
        assert (
            ch.public_channel(_channel(api_key="", key_env="MY_TEST_KEY"))[
                "has_env_key"
            ]
            is False
        )


class TestCredentialLadder:
    def test_inline_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_KEY", "sk-env")
        key, src = ch.credential_for(
            _channel(api_key="sk-inline", key_env=""),
            {"https://api.deepseek.com": {"api_key": "sk-conn"}},
        )
        assert (key, src) == ("sk-inline", "channel")

    def test_key_env_second(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_KEY", "sk-env")
        key, src = ch.credential_for(
            _channel(api_key="", key_env="MY_KEY"),
            {"https://api.deepseek.com": {"api_key": "sk-conn"}},
        )
        assert (key, src) == ("sk-env", "env:MY_KEY")

    def test_connections_third(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEXLATE_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        key, src = ch.credential_for(
            _channel(api_key=""),
            {"https://api.deepseek.com": {"api_key": "sk-conn"}},
        )
        assert (key, src) == ("sk-conn", "connection")

    def test_provider_env_last(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-penv")
        monkeypatch.delenv("TEXLATE_API_KEY", raising=False)
        key, src = ch.credential_for(_channel(api_key=""), {})
        assert (key, src) == ("sk-penv", "provider_env")

    def test_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("TEXLATE_API_KEY", "DEEPSEEK_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        key, src = ch.credential_for(_channel(api_key=""), {})
        assert (key, src) == ("", "none")

    def test_key_env_for(self, store: ch.ChannelStore) -> None:
        store.save(
            [
                _channel(
                    "ch-a",
                    base_url="https://api.deepseek.com",
                    api_key="",
                    key_env="DS_KEY",
                    enabled=False,
                ),
                _channel("ch-b", base_url="https://api.anthropic.com"),
            ]
        )
        assert (
            store.key_env_for("https://api.deepseek.com") == "DS_KEY"
        )  # disabled 也查
        assert store.key_env_for("https://api.anthropic.com") == ""
        assert store.key_env_for("https://example.com/x") == ""


# ---------------------------------------------------------------- 冷却


class TestCooldowns:
    """``Cooldowns.mark_error`` 错误分级 → 渠道级/模型级 TTL 归属。"""

    def test_auth_billing_channel_scope(self) -> None:
        cd = ch.Cooldowns()
        assert cd.mark_error("c1", "m", AuthError("401", status=401)) == 300.0  # noqa: PLR2004 -- auth→渠道级 300s
        assert cd.is_cooled("c1", "")
        assert cd.is_cooled("c1", "other-model")  # 渠道级冷却罩住全模型
        cd2 = ch.Cooldowns()
        assert cd2.mark_error("c1", "m", BillingError("402", status=402)) == 300.0  # noqa: PLR2004 -- billing→渠道级 300s
        assert cd2.is_cooled("c1", "m")

    def test_transport_death_channel_scope(self) -> None:
        cd = ch.Cooldowns()
        e = RetryableHTTPError("conn refused", status=-1, retryable=True)
        assert cd.mark_error("c1", "m", e) == 60.0  # noqa: PLR2004 -- 传输死亡→渠道级 60s
        assert cd.is_cooled("c1", "")  # 渠道级——端点不可达换模同死

    def test_content_filter_not_marked(self) -> None:
        cd = ch.Cooldowns()
        e = ContentFilterError("filtered", status=400)
        assert cd.mark_error("c1", "m", e) == 0.0
        assert not cd.is_cooled("c1", "m")
        assert not cd.is_cooled("c1", "")

    def test_model_scopes(self) -> None:
        cd = ch.Cooldowns()
        assert (
            cd.mark_error("c1", "m", EndpointNotFoundError("404", status=404)) == 600.0  # noqa: PLR2004 -- 404→模型级 600s
        )
        assert cd.is_cooled("c1", "m")
        assert not cd.is_cooled("c1", "m2")  # 模型级不殃及同渠道他模
        assert not cd.is_cooled("c1", "")
        cd2 = ch.Cooldowns()
        e = RetryableHTTPError("429", status=429, retryable=True)
        assert cd2.mark_error("c1", "m", e) == 60.0  # noqa: PLR2004 -- retryable→模型级 60s
        assert cd2.is_cooled("c1", "m")
        assert not cd2.is_cooled("c1", "")
        cd3 = ch.Cooldowns()
        assert cd3.mark_error("c1", "m", ChatError("x", status=400)) == 600.0  # noqa: PLR2004 -- 其余→模型级 600s
        assert cd3.is_cooled("c1", "m")

    def test_empty_channel_id_noop(self) -> None:
        cd = ch.Cooldowns()
        assert cd.mark_error("", "m", AuthError("401", status=401)) == 0.0
        assert not cd.is_cooled("", "")


# ---------------------------------------------------------------- 路由决议


class TestResolveRoute:
    def _settings(self, model: str = "m1") -> dict[str, Any]:
        return {
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-ds",
            "model": model,
        }

    def test_no_files_none(
        self,
        store: ch.ChannelStore,
        fresh_cooldowns: ch.Cooldowns,  # noqa: ARG002
    ) -> None:
        assert store.resolve_route(self._settings(), {}) is None

    def test_auto_picks_priority_and_model(
        self,
        store: ch.ChannelStore,
        fresh_cooldowns: ch.Cooldowns,  # noqa: ARG002
    ) -> None:
        """auto：route.model 非空 → 显式含该名的最高 priority 渠道 + redirect 反解。"""
        store.save(
            [
                _channel(
                    "ch-lo",
                    priority=10,
                    api_key="sk-lo",
                    models=[{"model": "deepseek-chat", "redirect_model": "wire-ds"}],
                ),
                _channel(
                    "ch-hi",
                    priority=20,
                    base_url="https://api.anthropic.com",
                    api_key="sk-hi",
                    models=[_m("other")],
                ),
            ]
        )
        # want=deepseek-chat：ch-hi 无此名 → 落到 ch-lo，wire 名取 redirect
        r = store.resolve_route(self._settings("deepseek-chat"), {})
        assert r is not None
        assert r["channel"]["id"] == "ch-lo"
        assert r["wire_model"] == "wire-ds"
        assert r["api_key"] == "sk-lo"

    def test_auto_fallback_first_enabled_model(
        self,
        store: ch.ChannelStore,
        fresh_cooldowns: ch.Cooldowns,  # noqa: ARG002
    ) -> None:
        """want 全不命中 → 最高 priority 渠道的首个 enabled 模型。"""
        store.save(
            [
                _channel("ch-lo", priority=10, models=[_m("a")]),
                _channel(
                    "ch-hi",
                    priority=20,
                    base_url="https://api.anthropic.com",
                    models=[_m("x", "wire-x"), _m("y")],
                ),
            ]
        )
        r = store.resolve_route(self._settings("nonexistent"), {})
        assert r is not None
        assert r["channel"]["id"] == "ch-hi"
        assert r["wire_model"] == "wire-x"

    def test_pinned_channel(
        self,
        store: ch.ChannelStore,
        fresh_cooldowns: ch.Cooldowns,  # noqa: ARG002
    ) -> None:
        """route.channel_id 钉死 → 只用该渠道（priority 低也命中）。"""
        store.save(
            [
                _channel("ch-lo", priority=10, api_key="sk-lo"),
                _channel(
                    "ch-hi",
                    priority=20,
                    base_url="https://api.anthropic.com",
                    api_key="sk-hi",
                ),
            ],
            {"channel_id": "ch-lo", "model": ""},
        )
        r = store.resolve_route(self._settings("ghost-model"), {})
        assert r is not None
        assert r["channel"]["id"] == "ch-lo"
        assert r["api_key"] == "sk-lo"

    def test_disabled_skipped(
        self,
        store: ch.ChannelStore,
        fresh_cooldowns: ch.Cooldowns,  # noqa: ARG002
    ) -> None:
        store.save(
            [
                _channel("ch-off", priority=30, enabled=False),
                _channel("ch-on", priority=10, base_url="https://api.anthropic.com"),
            ]
        )
        r = store.resolve_route(self._settings("m1"), {})
        assert r is not None
        assert r["channel"]["id"] == "ch-on"

    def test_cooled_channel_filtered(
        self, store: ch.ChannelStore, fresh_cooldowns: ch.Cooldowns
    ) -> None:
        """渠道级冷却 → 路由跳过该渠道落次优。"""
        store.save(
            [
                _channel("ch-dead", priority=30),
                _channel("ch-live", priority=10, base_url="https://api.anthropic.com"),
            ]
        )
        fresh_cooldowns.mark("ch-dead", "", 300.0)
        r = store.resolve_route(self._settings("m1"), {})
        assert r is not None
        assert r["channel"]["id"] == "ch-live"

    def test_cooled_model_filtered(
        self, store: ch.ChannelStore, fresh_cooldowns: ch.Cooldowns
    ) -> None:
        """模型级冷却 → 该 (渠道,模型) 滤掉，渠道级不冷却。"""
        store.save([_channel("ch-a", priority=10, models=[_m("m1"), _m("m2")])])
        fresh_cooldowns.mark("ch-a", "m1", 60.0)
        r = store.resolve_route(self._settings("m1"), {})
        # m1 冷却 → 第一遍不命中；第二遍首 enabled 模是 m1 仍冷却 → 跳 m1
        # 同渠道无可选 → channels 耗尽 → None？ 不——第一遍按 want=m1 找
        # entry 命中但 cooled → continue；第二遍首个 enabled 模 m1 cooled
        # → continue → None
        assert r is None

    def test_key_ladder_env(
        self,
        store: ch.ChannelStore,
        fresh_cooldowns: ch.Cooldowns,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MY_CH_KEY", "sk-from-env")
        store.save([_channel("ch-a", api_key="", key_env="MY_CH_KEY")])
        r = store.resolve_route(self._settings(), {})
        assert r is not None
        assert r["api_key"] == "sk-from-env"
        assert r["key_source"] == "env:MY_CH_KEY"


# ---------------------------------------------------------------- 探针


class TestProbeChannel:
    def test_ok_two_stage(self) -> None:
        _StubClient.list_ids = ["m1", "ghost"]
        report = asyncio.run(
            ch.probe_channel("https://x.test", "sk-k", "openai", [_m("m1"), _m("m9")])
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
        report = asyncio.run(ch.probe_channel("https://x.test", "", "auto", [_m("m1")]))
        assert report["models"]["m1"]["verdict"] == "placeholder_lost"

    def test_no_cjk(self) -> None:
        _StubClient.chat_results = {
            "m1": _result("The [[MATH_1]] norm satisfies [[MATH_2]]; see [[CITE_1]].")
        }
        report = asyncio.run(ch.probe_channel("https://x.test", "", "auto", [_m("m1")]))
        assert report["models"]["m1"]["verdict"] == "no_cjk"

    def test_empty_and_refused(self) -> None:
        _StubClient.chat_results = {
            "m1": _result("   "),
            "m2": ContentFilterError("filtered", status=400),
        }
        report = asyncio.run(
            ch.probe_channel("https://x.test", "", "auto", [_m("m1"), _m("m2")])
        )
        assert report["models"]["m1"]["verdict"] == "empty"
        assert report["models"]["m2"]["verdict"] == "refused"

    def test_stage1_auth_skips_stage2(self) -> None:
        _StubClient.list_error = AuthError("HTTP 401: bad key", status=401)
        report = asyncio.run(
            ch.probe_channel("https://x.test", "sk-bad", "auto", [_m("m1"), _m("m2")])
        )
        assert report["stage1"]["verdict"] == "auth_failed"
        assert all(m["verdict"] == "skipped" for m in report["models"].values())

    def test_no_models_dir_still_probes(self) -> None:
        _StubClient.list_error = EndpointNotFoundError("HTTP 404", status=404)
        report = asyncio.run(ch.probe_channel("https://x.test", "", "auto", [_m("m1")]))
        assert report["stage1"]["verdict"] == "no_models_dir"
        assert report["models"]["m1"]["verdict"] == "usable"
        assert report["models"]["m1"]["listed"] is None

    def test_unreachable_skips(self) -> None:
        _StubClient.list_error = RetryableHTTPError(
            "transport error: timed out", status=-1
        )
        report = asyncio.run(ch.probe_channel("https://x.test", "", "auto", [_m("m1")]))
        assert report["stage1"]["verdict"] == "timeout"
        assert report["models"]["m1"]["verdict"] == "skipped"

    def test_stage2_transport_and_http(self) -> None:
        _StubClient.chat_results = {
            "m1": RetryableHTTPError("transport error: connection refused", status=-1),
            "m2": RetryableHTTPError("HTTP 500: boom", status=500),
        }
        report = asyncio.run(
            ch.probe_channel("https://x.test", "", "auto", [_m("m1"), _m("m2")])
        )
        assert report["models"]["m1"]["verdict"] == "unreachable"
        assert report["models"]["m2"]["verdict"] == "http_error"

    def test_models_capped_at_8(self) -> None:
        report = asyncio.run(
            ch.probe_channel(
                "https://x.test", "", "auto", [_m(f"m{i}") for i in range(12)]
            )
        )
        assert len(report["models"]) == ch.MAX_MODELS_PER_CHANNEL

    def test_redirect_sends_wire_reports_local(self) -> None:
        """redirect 条目：上游收 wire 名，报告键是本地名，listed 对线名判。"""
        _StubClient.list_ids = ["wire-x", "m2"]
        report = asyncio.run(
            ch.probe_channel(
                "https://x.test",
                "",
                "auto",
                [{"model": "alias", "redirect_model": "wire-x"}, _m("m2")],
            )
        )
        # 并发 gather 顺序不定——集合断言即可，键在上游见的是线名
        assert set(_StubClient.seen_uids) == {"wire-x", "m2"}
        assert set(report["models"]) == {"alias", "m2"}  # 报告键本地名
        assert report["models"]["alias"]["listed"] is True  # wire-x 在清单
        assert report["models"]["alias"]["verdict"] == "usable"

    def test_detail_scrubs_key(self) -> None:
        _StubClient.chat_results = {
            "m1": AuthError("HTTP 401: bad key sk-SECRET123", status=401),
        }
        report = asyncio.run(
            ch.probe_channel("https://x.test", "sk-SECRET123", "auto", [_m("m1")])
        )
        assert "sk-SECRET123" not in json.dumps(report)
        assert report["models"]["m1"]["verdict"] == "auth_failed"
