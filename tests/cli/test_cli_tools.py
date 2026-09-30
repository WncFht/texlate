"""``texlate tools install-tectonic``：三态探测 + 安装分支（全 mock 不触网）。

探测面 ``resolve_tool``/``find_managed`` 与安装面 ``install_tectonic`` 全部
monkeypatch——本文件不下载、不写托管目录。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from texlate.cli import app
from texlate.compile import toolchain

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_RUNNER = CliRunner()


def _probe(
    monkeypatch: pytest.MonkeyPatch, resolved: str | None, managed: str | None
) -> None:
    """钉住探测面：resolve_tool/find_managed 返回值。"""
    monkeypatch.setattr(toolchain, "resolve_tool", lambda _name: resolved)
    monkeypatch.setattr(toolchain, "find_managed", lambda: managed)


class TestInstallTectonic:
    def test_system_hit_no_install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PATH 命中 → 报系统件 exit 0，不触发下载。"""
        _probe(monkeypatch, "/usr/bin/tectonic", None)
        called: list[bool] = []
        monkeypatch.setattr(toolchain, "install_tectonic", lambda: called.append(True))
        result = _RUNNER.invoke(app, ["tools", "install-tectonic"])
        assert result.exit_code == 0, result.output
        assert "系统件 /usr/bin/tectonic" in result.stdout
        assert not called

    def test_managed_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """托管目录命中 → 报托管件。"""
        managed = "/data/tools/tectonic"
        _probe(monkeypatch, managed, managed)
        result = _RUNNER.invoke(app, ["tools", "install-tectonic"])
        assert result.exit_code == 0, result.output
        assert f"托管件 {managed}" in result.stdout

    def test_missing_download_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """缺失 + 下载关 → 指明开关 + exit 1。"""
        _probe(monkeypatch, None, None)
        monkeypatch.setattr(toolchain, "download_allowed", lambda: False)
        result = _RUNNER.invoke(app, ["tools", "install-tectonic"])
        assert result.exit_code == 1
        assert "缺失" in result.stdout
        assert "TEXLATE_NO_DOWNLOAD" in result.stderr

    def test_missing_installs_managed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """缺失 + 允许 → install_tectonic 落点 + 版本上 stdout。"""
        _probe(monkeypatch, None, None)
        monkeypatch.setattr(toolchain, "download_allowed", lambda: True)
        target = tmp_path / "tools" / "tectonic"
        monkeypatch.setattr(toolchain, "install_tectonic", lambda: target)
        result = _RUNNER.invoke(app, ["tools", "install-tectonic"])
        assert result.exit_code == 0, result.output
        assert str(target) in result.stdout
        assert toolchain.TECTONIC_VERSION in result.stdout

    def test_missing_install_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """下载/校验失败 → 错误落 stderr + exit 1。"""
        _probe(monkeypatch, None, None)
        monkeypatch.setattr(toolchain, "download_allowed", lambda: True)

        def _boom() -> Path:
            msg = "sha256 校验失败"
            raise RuntimeError(msg)

        monkeypatch.setattr(toolchain, "install_tectonic", _boom)
        result = _RUNNER.invoke(app, ["tools", "install-tectonic"])
        assert result.exit_code == 1
        assert "sha256 校验失败" in result.stderr
