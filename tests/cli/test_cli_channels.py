"""``texlate channels`` 命令组：list/test/route 三动词。

渠道面全走真 ``tmp_path`` 数据目录（``TEXLATE_DATA_DIR``）——读径投影/
凭据阶梯/``record_probe`` 钉文件要真 JSON 过一遍；``probe_channel``
网络面桩在 ``texlate.server.channels`` 源点（CLI 叶内 ``from X import``
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


def _channel(**over: object) -> dict[str, Any]:
    """单条渠道夹具——``over`` 逐字段覆盖。"""
    c: dict[str, Any] = {
        "id": "ch-p1",
        "name": "DeepSeek",
        "preset": "deepseek",
        "base_url": _P1_URL,
        "protocol": "openai",
        "models": [{"model": "deepseek-chat", "redirect_model": ""}],
        "priority": 10,
        "max_concurrency": None,
        "enabled": True,
        "api_key": "sk-p1-secret",
        "key_env": "",
        "last_probe": None,
    }
    c.update(over)
    return c


def _write_channels(
    data: Path,
    channels: list[dict[str, Any]],
    route: dict[str, str] | None = None,
) -> None:
    """``<data>/channels.json`` 落盘（v2 schema）。"""
    data.mkdir(parents=True, exist_ok=True)
    (data / "channels.json").write_text(
        json.dumps(
            {
                "version": 2,
                "channels": channels,
                "route": route or {"channel_id": "auto", "model": ""},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _probe_report(stage1: str = "ok", model_verdict: str = "usable") -> dict[str, Any]:
    """探针报告夹具——``probe_channel`` 出参同形。"""
    return {
        "at": "2026-10-07T00:00:00+00:00",
        "key_fp": "fp00",
        "stage1": {"verdict": stage1, "models": ["deepseek-chat"], "detail": ""},
        "models": {
            "deepseek-chat": {
                "verdict": model_verdict,
                "latency_s": 0.5,
                "detail": "",
                "listed": True,
            }
        },
    }


@pytest.fixture
def ch_env(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """``TEXLATE_DATA_DIR`` 落 tmp——各测试自写 channels.json。"""
    clean_env.setenv("TEXLATE_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def _stub_probe(
    monkeypatch: pytest.MonkeyPatch, report: dict[str, Any]
) -> list[dict[str, Any]]:
    """桩 ``texlate.server.channels.probe_channel``；返回调用记录。"""
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
        return report

    monkeypatch.setattr("texlate.server.channels.probe_channel", fake)
    return calls


class TestList:
    def test_empty_projects_default(
        self,
        ch_env: Path,  # noqa: ARG002 -- fixture 副作用（TEXLATE_DATA_DIR）
    ) -> None:
        """无 channels.json：list 走投影面——settings 行映成 default 渠道。"""
        r = _RUNNER.invoke(app, ["channels", "list"])
        assert r.exit_code == 0, r.output
        assert "1 条渠道" in r.output
        assert "default" in r.output
        assert "channel_id=auto" in r.output

    def test_list_shows_route_and_channels(self, ch_env: Path) -> None:
        """钉死路由的渠道带 → 标记；priority 降序排；停用/上限/redirect 进展示。"""
        _write_channels(
            ch_env,
            [
                _channel(
                    id="ch-lo",
                    name="低速",
                    priority=10,
                    max_concurrency=4,
                    enabled=False,
                ),
                _channel(
                    id="ch-hi",
                    name="主力",
                    priority=20,
                    base_url="https://api.anthropic.com",
                    models=[{"model": "claude", "redirect_model": "wire-claude"}],
                ),
            ],
            route={"channel_id": "ch-hi", "model": "claude"},
        )
        r = _RUNNER.invoke(app, ["channels", "list"])
        assert r.exit_code == 0, r.output
        assert "2 条渠道" in r.output
        assert "channel_id=ch-hi" in r.output
        out = r.output
        assert "→ ch-hi" in out
        assert "（停用）" in out
        assert "cap=4" in out
        assert "claude(wire-claude)" in out
        assert out.index("ch-hi") < out.index("ch-lo")  # priority 20 排前

    def test_list_credential_line(self, ch_env: Path) -> None:
        _write_channels(
            ch_env,
            [
                _channel(id="ch-inline", api_key="sk-x"),
                _channel(id="ch-env", api_key="", key_env="MY_UNSET_KEY"),
            ],
        )
        r = _RUNNER.invoke(app, ["channels", "list"])
        assert r.exit_code == 0, r.output
        assert "Key 已存" in r.output
        assert "env:MY_UNSET_KEY（未设置）" in r.output


class TestTest:
    def test_missing_id_exit2(self, ch_env: Path) -> None:
        _write_channels(ch_env, [_channel()])
        r = _RUNNER.invoke(app, ["channels", "test", "nope"])
        assert r.exit_code == 2  # noqa: PLR2004 -- 用法错 Exit(2)
        assert "渠道不存在" in r.output

    def test_ok_exit0_and_pins_probe(
        self, ch_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _stub_probe(monkeypatch, _probe_report())
        _write_channels(ch_env, [_channel()])
        r = _RUNNER.invoke(app, ["channels", "test", "ch-p1"])
        assert r.exit_code == 0, r.output
        assert "stage1: ok" in r.output
        assert calls[0]["api_key"] == "sk-p1-secret"  # inline 凭据层
        assert calls[0]["base_url"] == _P1_URL
        # 报告钉回 channels.json
        data = json.loads((ch_env / "channels.json").read_text(encoding="utf-8"))
        assert data["channels"][0]["last_probe"]["key_fp"] == "fp00"

    def test_all_models_dead_exit1(
        self, ch_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """stage1 通但模型全灭 → exit 1（渠道活而模型不可用同样 actionable）。"""
        _stub_probe(monkeypatch, _probe_report(model_verdict="auth_failed"))
        _write_channels(ch_env, [_channel()])
        r = _RUNNER.invoke(app, ["channels", "test", "ch-p1"])
        assert r.exit_code == 1

    def test_stage1_failed_exit1(
        self, ch_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_probe(monkeypatch, _probe_report(stage1="auth_failed"))
        _write_channels(ch_env, [_channel()])
        r = _RUNNER.invoke(app, ["channels", "test", "ch-p1"])
        assert r.exit_code == 1

    def test_keyless_channel_bare_probe(
        self, ch_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无凭据渠道照探（裸探）——stderr 报「无」，probe 拿到空 key。"""
        calls = _stub_probe(monkeypatch, _probe_report())
        _write_channels(ch_env, [_channel(api_key="", key_env="")])
        r = _RUNNER.invoke(app, ["channels", "test", "ch-p1"])
        assert "凭据：无" in (r.stderr or r.output)
        assert calls[0]["api_key"] == ""

    def test_env_credential(
        self, ch_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _stub_probe(monkeypatch, _probe_report())
        monkeypatch.setenv("CH_KEY_X", "sk-from-env")
        _write_channels(ch_env, [_channel(api_key="", key_env="CH_KEY_X")])
        r = _RUNNER.invoke(app, ["channels", "test", "ch-p1"])
        assert r.exit_code == 0, r.output
        assert calls[0]["api_key"] == "sk-from-env"
        assert "env:CH_KEY_X" in (r.stderr or r.output)


class TestRoute:
    def test_bare_shows_current(self, ch_env: Path) -> None:
        _write_channels(ch_env, [_channel()])
        r = _RUNNER.invoke(app, ["channels", "route"])
        assert r.exit_code == 0, r.output
        assert "channel_id=auto" in r.output

    def test_pin_and_show(self, ch_env: Path) -> None:
        _write_channels(ch_env, [_channel(id="ch-a"), _channel(id="ch-b")])
        r = _RUNNER.invoke(app, ["channels", "route", "ch-b", "deepseek-chat"])
        assert r.exit_code == 0, r.output
        assert "channel_id=ch-b" in r.output
        assert "model=deepseek-chat" in r.output
        data = json.loads((ch_env / "channels.json").read_text(encoding="utf-8"))
        assert data["route"] == {"channel_id": "ch-b", "model": "deepseek-chat"}

    def test_auto_resets(self, ch_env: Path) -> None:
        _write_channels(
            ch_env, [_channel()], route={"channel_id": "ch-p1", "model": ""}
        )
        r = _RUNNER.invoke(app, ["channels", "route", "auto"])
        assert r.exit_code == 0, r.output
        assert "channel_id=auto" in r.output

    def test_ghost_channel_exit2(self, ch_env: Path) -> None:
        _write_channels(ch_env, [_channel()])
        r = _RUNNER.invoke(app, ["channels", "route", "ch-ghost"])
        assert r.exit_code == 2  # noqa: PLR2004 -- 用法错 Exit(2)
        assert "渠道不存在" in (r.stderr or r.output)

    def test_pin_keeps_model_when_omitted(self, ch_env: Path) -> None:
        """``route <id>`` 不给 model → 承旧 model 不清空。"""
        _write_channels(
            ch_env,
            [_channel(id="ch-a"), _channel(id="ch-b")],
            route={"channel_id": "auto", "model": "deepseek-chat"},
        )
        r = _RUNNER.invoke(app, ["channels", "route", "ch-b"])
        assert r.exit_code == 0, r.output
        data = json.loads((ch_env / "channels.json").read_text(encoding="utf-8"))
        assert data["route"] == {"channel_id": "ch-b", "model": "deepseek-chat"}


class TestLegacyCliView:
    def test_endpoints_v1_serves_list(self, ch_env: Path) -> None:
        """只写旧 endpoints.json：CLI list 直接读径转形，渠道照常列出。"""
        ch_env.mkdir(parents=True, exist_ok=True)
        (ch_env / "endpoints.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "profiles": [
                        {
                            "id": "p1",
                            "label": "旧档",
                            "base_url": _P1_URL,
                            "dialect": "auto",
                            "models": [{"model": "m1", "redirect_model": ""}],
                            "enabled": True,
                            "api_key": "sk-x",
                            "key_env": "",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        r = _RUNNER.invoke(app, ["channels", "list"])
        assert r.exit_code == 0, r.output
        assert "p1" in r.output
        assert "旧档" in r.output
