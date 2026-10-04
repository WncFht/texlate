"""``texlate service`` 子命令簇：锁面 meta × pid 存活 × health 三源状态机。

全 mock：``_pid_alive``/``_health_probe``/``_pid_cmdline``/``_spawn_detached``
桩在 ``texlate.cli.service`` 叶模块面（调用期查名，monkeypatch 生效）；
锁 meta 走 tmp_path 真文件写——只读径与 ``web`` 持有者写径同文件格式。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from texlate.cli import app
from texlate.cli import service as svc

if TYPE_CHECKING:
    from pathlib import Path

_RUNNER = CliRunner()

_URL = "http://127.0.0.1:8765"
_HEALTH = {
    "ok": True,
    "version": "0.1.0",
    "started_at": "2026-10-04T00:00:00Z",
    "data_dir": "",
}


def _meta(root: Path, pid: int = 1234, url: str = _URL) -> None:
    """``<root>/service.lock`` meta 落盘（持有者登记形态）。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "service.lock").write_text(
        json.dumps({"pid": pid, "url": url}), encoding="utf-8"
    )


def _health_ok(root: Path, **over: object) -> dict[str, object]:
    """本家 health 应答体（``data_dir`` 缺省对齐观测根）。"""
    return {**_HEALTH, "data_dir": str(root), **over}


def _stub_health(
    monkeypatch: pytest.MonkeyPatch, body: dict[str, object] | None
) -> None:
    """``_health_probe`` 桩：``body`` None = 不应答。"""
    monkeypatch.setattr(svc, "_health_probe", lambda _url: body or {})


@pytest.fixture(autouse=True)
def _no_real_health(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认「无应答」——防测试机真实例（127.0.0.1:8765）污染未桩用例。

    要应答的用例经 ``_stub_health`` 再 setattr 覆盖（同 monkeypatch 后设胜出）。
    """
    monkeypatch.setattr(svc, "_health_probe", lambda _url: {})


@pytest.fixture
def _alive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "_pid_alive", lambda _pid: True)


@pytest.fixture
def _dead(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "_pid_alive", lambda _pid: False)


@pytest.mark.usefixtures("clean_env")
class TestStatus:
    def test_stopped_no_lock(self, tmp_path: Path) -> None:
        """无锁无应答 → stopped 文案 + exit 1。"""
        r = _RUNNER.invoke(app, ["service", "status", "--data-dir", str(tmp_path)])
        assert r.exit_code == 1
        assert "未在运行" in r.stdout

    def test_stopped_json(self, tmp_path: Path) -> None:
        """``--json`` 出状态机字段；stopped 仍 exit 1。"""
        r = _RUNNER.invoke(
            app, ["service", "status", "--data-dir", str(tmp_path), "--json"]
        )
        assert r.exit_code == 1
        body = json.loads(r.stdout)
        assert body["state"] == "stopped"
        assert body["data_dir"] == str(tmp_path)
        assert body["pid"] is None

    @pytest.mark.usefixtures("_alive")
    def test_running(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """meta+pid 活+health ok → running（版本/pid/url 全在行内）。"""
        _meta(tmp_path)
        _stub_health(monkeypatch, _health_ok(tmp_path))
        r = _RUNNER.invoke(app, ["service", "status", "--data-dir", str(tmp_path)])
        assert r.exit_code == 0, r.output
        assert "运行中" in r.stdout
        assert "pid 1234" in r.stdout
        assert _URL in r.stdout

    def test_running_lockless(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无锁但 health 应答 → running「无锁实例」（server 模式部署形态）。"""
        _stub_health(monkeypatch, _health_ok(tmp_path))
        r = _RUNNER.invoke(app, ["service", "status", "--data-dir", str(tmp_path)])
        assert r.exit_code == 0, r.output
        assert "无锁实例" in r.stdout

    @pytest.mark.usefixtures("_alive")
    def test_degraded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """pid 活但 health 死 → degraded + exit 1。"""
        _meta(tmp_path)
        _stub_health(monkeypatch, None)
        r = _RUNNER.invoke(app, ["service", "status", "--data-dir", str(tmp_path)])
        assert r.exit_code == 1
        assert "pid 1234 存活" in r.stdout

    @pytest.mark.usefixtures("_dead")
    def test_stale_meta_is_stopped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """meta 残留但 pid 死 + health 死 → stopped（常态停机遗迹）。"""
        _meta(tmp_path)
        _stub_health(monkeypatch, None)
        r = _RUNNER.invoke(app, ["service", "status", "--data-dir", str(tmp_path)])
        assert r.exit_code == 1
        assert "未在运行" in r.stdout

    @pytest.mark.usefixtures("_alive")
    def test_foreign(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """health ok 但 data_dir 他属 → 占用提示 + exit 1。"""
        _meta(tmp_path)
        _stub_health(monkeypatch, _health_ok(tmp_path, data_dir="/other/dir"))
        r = _RUNNER.invoke(app, ["service", "status", "--data-dir", str(tmp_path)])
        assert r.exit_code == 1
        assert "别家占用" in r.stdout
        assert "/other/dir" in r.stdout


@pytest.mark.usefixtures("clean_env")
class TestStop:
    def test_stopped_noop(self, tmp_path: Path) -> None:
        """未在运行 → 幂等报出 exit 0。"""
        r = _RUNNER.invoke(app, ["service", "stop", "--data-dir", str(tmp_path)])
        assert r.exit_code == 0
        assert "未在运行" in r.stdout

    def test_sigterm_running(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """running 本家 → SIGTERM 单发即退（evidence 足免身份核验）。"""
        _meta(tmp_path)
        _stub_health(monkeypatch, _health_ok(tmp_path))
        killed: list[int] = []
        alive = {"v": True}
        monkeypatch.setattr(svc, "_pid_alive", lambda _p: alive["v"])

        def _kill(_pid: int, sig: int) -> None:
            killed.append(sig)
            alive["v"] = False

        monkeypatch.setattr(os, "kill", _kill)
        r = _RUNNER.invoke(app, ["service", "stop", "--data-dir", str(tmp_path)])
        assert r.exit_code == 0, r.output
        assert killed == [signal.SIGTERM]
        assert "已停止" in r.stdout

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="nt 无 SIGKILL——Windows 升级路径走 TerminateProcess",
    )
    def test_sigkill_escalation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SIGTERM 超时 → posix 升级 SIGKILL 再退。"""
        _meta(tmp_path)
        _stub_health(monkeypatch, _health_ok(tmp_path))
        killed: list[int] = []
        alive = {"v": True}
        monkeypatch.setattr(svc, "_pid_alive", lambda _p: alive["v"])
        monkeypatch.setattr(svc, "_wait_pid_gone", lambda _p, _t: False)

        def _kill(_pid: int, sig: int) -> None:
            killed.append(sig)
            if sig == signal.SIGKILL:
                alive["v"] = False

        monkeypatch.setattr(os, "kill", _kill)
        r = _RUNNER.invoke(
            app, ["service", "stop", "--data-dir", str(tmp_path), "--timeout", "1"]
        )
        assert r.exit_code == 0, r.output
        assert killed == [signal.SIGTERM, signal.SIGKILL]
        assert "SIGKILL" in r.stderr

    def test_refuse_lockless(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """health 应答但锁面无 pid → 拒杀指认部署形态。"""
        _stub_health(monkeypatch, _health_ok(tmp_path))
        r = _RUNNER.invoke(app, ["service", "stop", "--data-dir", str(tmp_path)])
        assert r.exit_code == 1
        assert "部署方式" in r.stderr

    @pytest.mark.usefixtures("_alive")
    def test_refuse_foreign(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """他目实例占用 + pid 活 → 无条件拒杀（pid 可能撞号到别家）。"""
        _meta(tmp_path)
        _stub_health(monkeypatch, _health_ok(tmp_path, data_dir="/other/dir"))
        killed: list[int] = []
        monkeypatch.setattr(os, "kill", lambda _p, s: killed.append(s))
        r = _RUNNER.invoke(app, ["service", "stop", "--data-dir", str(tmp_path)])
        assert r.exit_code == 1
        assert killed == []
        assert "别家" in r.stderr or "勿动" in r.stderr

    def test_degraded_cmdline_verified(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """degraded 态：pid 命令行含 texlate → 放行 SIGTERM。"""
        _meta(tmp_path)
        _stub_health(monkeypatch, None)
        killed: list[int] = []
        alive = {"v": True}
        monkeypatch.setattr(svc, "_pid_alive", lambda _p: alive["v"])
        monkeypatch.setattr(svc, "_pid_cmdline", lambda _p: "python -m texlate web")

        def _kill(_pid: int, sig: int) -> None:
            killed.append(sig)
            alive["v"] = False

        monkeypatch.setattr(os, "kill", _kill)
        r = _RUNNER.invoke(app, ["service", "stop", "--data-dir", str(tmp_path)])
        assert r.exit_code == 0, r.output
        assert killed == [signal.SIGTERM]

    @pytest.mark.usefixtures("_alive")
    def test_degraded_pid_reuse_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """degraded + pid 命令行查无 texlate → 判撞号拒杀。"""
        _meta(tmp_path)
        _stub_health(monkeypatch, None)
        monkeypatch.setattr(svc, "_pid_cmdline", lambda _p: "vim foo.txt")
        killed: list[int] = []
        monkeypatch.setattr(os, "kill", lambda _p, s: killed.append(s))
        r = _RUNNER.invoke(app, ["service", "stop", "--data-dir", str(tmp_path)])
        assert r.exit_code == 1
        assert killed == []
        assert "撞号" in r.stderr


@pytest.mark.usefixtures("clean_env")
class TestStart:
    def test_already_running(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """目标端口本家已在跑 → 指到实例 + 开浏览器，不 spawn。"""
        _stub_health(monkeypatch, _health_ok(tmp_path))
        opened: list[str] = []
        monkeypatch.setattr("webbrowser.open", opened.append)
        spawned: list[list[str]] = []
        monkeypatch.setattr(
            svc, "_spawn_detached", lambda argv, _log: spawned.append(argv) or 1
        )
        r = _RUNNER.invoke(app, ["service", "start", "--data-dir", str(tmp_path)])
        assert r.exit_code == 0, r.output
        assert "已在运行" in r.stdout
        assert opened == [_URL]
        assert spawned == []

    def test_refuse_foreign_port(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """目标端口被他数据目录实例占用 → 拒 spawn。"""
        _stub_health(monkeypatch, _health_ok(tmp_path, data_dir="/other/dir"))
        r = _RUNNER.invoke(
            app,
            ["service", "start", "--data-dir", str(tmp_path), "--no-open"],
        )
        assert r.exit_code == 1
        assert "占用" in r.stderr

    @pytest.mark.usefixtures("_alive")
    def test_refuse_held_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """锁面 pid 存活但目标未就绪 → 拒 spawn（spawn 也会锁竞争即退）。"""
        _meta(tmp_path, url="http://127.0.0.1:9999")
        _stub_health(monkeypatch, None)
        r = _RUNNER.invoke(
            app,
            ["service", "start", "--data-dir", str(tmp_path), "--no-open"],
        )
        assert r.exit_code == 1
        assert "service.lock" in r.stderr

    @pytest.mark.usefixtures("_alive")
    def test_spawn_happy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """干净拉起：spawn argv 正确 + 轮询就绪 → exit 0。"""
        spawned: list[list[str]] = []

        def _health(_url: str) -> dict[str, object]:
            # spawn 前（target 探测 + _probe_service）未起；spawn 后即就绪
            return _health_ok(tmp_path) if spawned else {}

        def _spawn(argv: list[str], _log: Path) -> int:
            spawned.append(argv)
            return 4242

        monkeypatch.setattr(svc, "_health_probe", _health)
        monkeypatch.setattr(svc, "_spawn_detached", _spawn)
        opened: list[str] = []
        monkeypatch.setattr("webbrowser.open", opened.append)
        r = _RUNNER.invoke(
            app,
            ["service", "start", "--data-dir", str(tmp_path), "--port", "9999"],
        )
        assert r.exit_code == 0, r.output
        assert "已拉起" in r.stdout
        assert "pid 4242" in r.stdout
        argv = spawned[0]
        assert argv[:3] == [sys.executable, "-m", "texlate"]
        assert "web" in argv
        assert "--port" in argv
        assert "9999" in argv
        assert str(tmp_path) in argv
        assert opened == ["http://127.0.0.1:9999"]

    @pytest.mark.usefixtures("_alive")
    def test_spawn_timeout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """spawn 后 wait 上限内未就绪 → exit 1 指日志。"""
        _stub_health(monkeypatch, None)
        monkeypatch.setattr(svc, "_spawn_detached", lambda _a, _l: 4242)
        r = _RUNNER.invoke(
            app,
            [
                "service",
                "start",
                "--data-dir",
                str(tmp_path),
                "--wait",
                "0",
                "--no-open",
            ],
        )
        assert r.exit_code == 1
        assert "未就绪" in r.stderr
        assert "service-launch.log" in r.stderr


@pytest.mark.usefixtures("clean_env")
class TestRestart:
    def test_stopped_goes_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """未在运行 → 跳过 stop 直走 start。"""
        calls: list[str] = []
        monkeypatch.setattr(svc, "service_stop", lambda **_kw: calls.append("stop"))
        monkeypatch.setattr(svc, "service_start", lambda **_kw: calls.append("start"))
        _stub_health(monkeypatch, None)
        r = _RUNNER.invoke(app, ["service", "restart", "--data-dir", str(tmp_path)])
        assert r.exit_code == 0, r.output
        assert calls == ["start"]

    @pytest.mark.usefixtures("_alive")
    def test_running_stop_then_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """running → stop→start 顺序。"""
        _meta(tmp_path)
        _stub_health(monkeypatch, _health_ok(tmp_path))
        calls: list[str] = []
        monkeypatch.setattr(svc, "service_stop", lambda **_kw: calls.append("stop"))
        monkeypatch.setattr(svc, "service_start", lambda **_kw: calls.append("start"))
        r = _RUNNER.invoke(app, ["service", "restart", "--data-dir", str(tmp_path)])
        assert r.exit_code == 0, r.output
        assert calls == ["stop", "start"]


def test_python_dash_m() -> None:
    """``python -m texlate --help`` 冒烟——``service start`` 的 spawn 目标可达。"""
    r = subprocess.run(
        [sys.executable, "-m", "texlate", "--help"],
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 0
    assert b"service" in r.stdout
