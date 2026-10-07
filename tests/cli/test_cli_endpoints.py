"""``texlate endpoints`` 命令组：list/test/activate 三动词 + doctor endpoints 项。

档案面全走真 ``tmp_path`` 数据目录（``TEXLATE_DATA_DIR``）——读径投影/
凭据阶梯/``record_probe`` 钉文件要真 JSON 过一遍；``probe_endpoint``
网络面桩在 ``texlate.server.endpoints`` 源点（叶内 ``from X import``
延迟绑定，桩源点即生效）。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from texlate.cli import app

if TYPE_CHECKING:
    from pathlib import Path

_RUNNER = CliRunner()

_P1_URL = "https://api.deepseek.com"


def _write_settings(data: Path, **kw: object) -> None:
    """``<data>/settings.json`` 落盘。"""
    data.mkdir(parents=True, exist_ok=True)
    (data / "settings.json").write_text(json.dumps(kw), encoding="utf-8")


def _write_endpoints(data: Path, profiles: list[dict[str, Any]]) -> None:
    """``<data>/endpoints.json`` 落盘（v1 schema）。"""
    data.mkdir(parents=True, exist_ok=True)
    (data / "endpoints.json").write_text(
        json.dumps({"version": 1, "profiles": profiles}, ensure_ascii=False),
        encoding="utf-8",
    )


def _profile(**over: object) -> dict[str, Any]:
    """单条 profile 夹具——``over`` 逐字段覆盖。"""
    p: dict[str, Any] = {
        "id": "p1",
        "label": "DeepSeek",
        "base_url": _P1_URL,
        "dialect": "auto",
        "models": [{"model": "deepseek-chat", "redirect_model": ""}],
        "enabled": True,
        "api_key": "sk-p1-secret",
        "key_env": "",
        "last_probe": None,
    }
    p.update(over)
    return p


def _probe_report(stage1: str = "ok", model_verdict: str = "usable") -> dict[str, Any]:
    """探针报告夹具——``probe_endpoint`` 出参同形。"""
    return {
        "at": "2026-10-07T01:00:00+00:00",
        "key_fp": "abcd1234",
        "stage1": {"verdict": stage1, "models": ["deepseek-chat"], "detail": ""},
        "models": {
            "deepseek-chat": {
                "verdict": model_verdict,
                "latency_s": 0.4,
                "detail": "",
                "listed": True,
            }
        },
    }


@pytest.fixture
def ep_env(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> Path:
    """``TEXLATE_DATA_DIR`` 落 tmp——各测试自写 settings/endpoints.json。"""
    clean_env.setenv("TEXLATE_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


class TestList:
    def test_bare_help(self, ep_env: Path) -> None:  # noqa: ARG002 -- fixture 副作用
        """裸 ``endpoints`` → 出子命令帮助（click 组 no_args_is_help exit 2 语义）。"""
        r = _RUNNER.invoke(app, ["endpoints"])
        assert r.exit_code == 2  # noqa: PLR2004 -- click 组裸调=用法错 2
        assert "list" in r.output
        assert "activate" in r.output

    def test_no_file_projects_settings(self, ep_env: Path) -> None:
        """无 endpoints.json → 投影合成表：id=default 映活动 settings 行。"""
        _write_settings(ep_env, base_url=_P1_URL, model="deepseek-chat", api_key="sk-x")
        r = _RUNNER.invoke(app, ["endpoints", "list"])
        assert r.exit_code == 0, r.output
        assert "default" in r.stdout
        assert "api.deepseek.com" in r.stdout
        assert "Key 已存" in r.stdout
        assert "sk-x" not in r.stdout  # key 值绝不出输出

    def test_file_lists_profiles(self, ep_env: Path) -> None:
        """文件在 → 活动 ``*``/停用标/env 凭据态/last_probe 摘要。"""
        _write_settings(ep_env, base_url=_P1_URL)
        _write_endpoints(
            ep_env,
            [
                _profile(),
                _profile(
                    id="p2",
                    label="",
                    base_url="https://openrouter.ai/api",
                    models=[
                        {"model": "m-a", "redirect_model": ""},
                        {"model": "m-b", "redirect_model": ""},
                    ],
                    enabled=False,
                    api_key="",
                    key_env="OR_KEY",
                    last_probe={
                        "at": "2026-10-06T00:00:00+00:00",
                        "stage1": {"verdict": "ok"},
                        "models": {"m-a": {"verdict": "usable"}},
                    },
                ),
            ],
        )
        r = _RUNNER.invoke(app, ["endpoints", "list"])
        assert r.exit_code == 0, r.output
        assert "* p1" in r.stdout
        assert "  p2" in r.stdout
        assert "（停用）" in r.stdout
        assert "env:OR_KEY（未设置）" in r.stdout
        assert "stage1=ok" in r.stdout
        assert "m-a=usable" in r.stdout


class TestProbe:
    def test_unknown_id_exit2(self, ep_env: Path) -> None:
        """id 无命中 → 报错 + exit 2（用法错非探针败）。"""
        _write_endpoints(ep_env, [_profile()])
        r = _RUNNER.invoke(app, ["endpoints", "test", "nope"])
        assert r.exit_code == 2  # noqa: PLR2004 -- 用法错退出码
        assert "profile 不存在" in r.output

    def test_usable_pins_last_probe(
        self, ep_env: Path, clean_env: pytest.MonkeyPatch
    ) -> None:
        """usable → exit 0 + verdict 行 + 报告钉回 ``last_probe``；key 走 inline 臂。"""
        _write_endpoints(ep_env, [_profile()])
        seen: dict[str, object] = {}

        async def _probe(
            base_url: str,
            api_key: str,
            dialect: str,
            models: list[dict[str, str]],
        ) -> dict[str, Any]:
            seen.update(
                base_url=base_url, api_key=api_key, dialect=dialect, models=models
            )
            return _probe_report()

        clean_env.setattr("texlate.server.endpoints.probe_endpoint", _probe)
        r = _RUNNER.invoke(app, ["endpoints", "test", "p1"])
        assert r.exit_code == 0, r.output
        assert "stage1: ok" in r.stdout
        assert "deepseek-chat: usable" in r.stdout
        assert seen == {
            "base_url": _P1_URL,
            "api_key": "sk-p1-secret",
            "dialect": "auto",
            "models": [{"model": "deepseek-chat", "redirect_model": ""}],
        }
        assert "sk-p1-secret" not in r.output
        saved = json.loads((ep_env / "endpoints.json").read_text(encoding="utf-8"))
        probe = saved["profiles"][0]["last_probe"]
        assert probe["stage1"]["verdict"] == "ok"
        assert probe["models"]["deepseek-chat"]["verdict"] == "usable"

    def test_env_key_ladder(self, ep_env: Path, clean_env: pytest.MonkeyPatch) -> None:
        """``key_env`` 命中 → 凭据走 env 臂（inline 空时阶梯第二级）。"""
        clean_env.setenv("OR_KEY", "sk-env-secret")
        _write_endpoints(ep_env, [_profile(api_key="", key_env="OR_KEY")])
        seen: dict[str, object] = {}

        async def _probe(
            base_url: str,  # noqa: ARG001 -- 桩签名与 probe_endpoint 齐位
            api_key: str,
            dialect: str,  # noqa: ARG001
            models: list[dict[str, str]],  # noqa: ARG001
        ) -> dict[str, Any]:
            seen["api_key"] = api_key
            return _probe_report()

        clean_env.setattr("texlate.server.endpoints.probe_endpoint", _probe)
        r = _RUNNER.invoke(app, ["endpoints", "test", "p1"])
        assert r.exit_code == 0, r.output
        assert seen["api_key"] == "sk-env-secret"
        assert "env:OR_KEY" in r.output

    def test_all_dead_exit1(self, ep_env: Path, clean_env: pytest.MonkeyPatch) -> None:
        """stage1 auth_failed → 模型整段 skipped + exit 1（端点死=actionable）。"""
        _write_endpoints(ep_env, [_profile()])

        async def _probe(*_a: object, **_kw: object) -> dict[str, Any]:
            rep = _probe_report(stage1="auth_failed")
            rep["models"] = {
                "deepseek-chat": {"verdict": "skipped", "latency_s": 0, "detail": ""}
            }
            return rep

        clean_env.setattr("texlate.server.endpoints.probe_endpoint", _probe)
        r = _RUNNER.invoke(app, ["endpoints", "test", "p1"])
        assert r.exit_code == 1
        assert "stage1: auth_failed" in r.stdout
        assert "skipped" in r.stdout


class TestActivate:
    def test_inline_key_writes_settings(self, ep_env: Path) -> None:
        """inline-key profile → base_url/dialect/model[0]/api_key 全进 settings。"""
        _write_settings(
            ep_env, base_url="https://old.example.com", api_key="sk-old", model="m0"
        )
        _write_endpoints(ep_env, [_profile()])
        r = _RUNNER.invoke(app, ["endpoints", "activate", "p1"])
        assert r.exit_code == 0, r.output
        assert "已切换到 p1" in r.stdout
        s = json.loads((ep_env / "settings.json").read_text(encoding="utf-8"))
        assert s["base_url"] == _P1_URL
        assert s["model"] == "deepseek-chat"
        assert s["api_key"] == "sk-p1-secret"

    def test_env_profile_clears_inline_key(self, ep_env: Path) -> None:
        """非 inline profile → settings 旧 key 清掉（阶梯接管；残留 key 发向新端点是 exfil）。"""
        _write_settings(ep_env, base_url="https://old.example.com", api_key="sk-old")
        _write_endpoints(ep_env, [_profile(api_key="", key_env="OR_KEY", models=[])])
        r = _RUNNER.invoke(app, ["endpoints", "activate", "p1"])
        assert r.exit_code == 0, r.output
        s = json.loads((ep_env / "settings.json").read_text(encoding="utf-8"))
        assert s["base_url"] == _P1_URL
        assert not s.get("api_key")
        assert s.get("model") != "deepseek-chat"  # models 空 → model 承旧/不写

    def test_unknown_id_exit2(self, ep_env: Path) -> None:
        """id 无命中 → exit 2，settings 不动。"""
        _write_settings(ep_env, base_url="https://old.example.com")
        _write_endpoints(ep_env, [_profile()])
        r = _RUNNER.invoke(app, ["endpoints", "activate", "nope"])
        assert r.exit_code == 2  # noqa: PLR2004 -- 用法错退出码
        s = json.loads((ep_env / "settings.json").read_text(encoding="utf-8"))
        assert s["base_url"] == "https://old.example.com"
