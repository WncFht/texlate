"""``texlate web`` 单实例锁（web-layer §6）：flock service.lock 语义。

锁被持有 = 已有实例在跑 → 第二实例浏览器打开其地址并 exit 0，
而非端口冲突/静默双开。锁文件元数据（url）优先于请求端口。
"""

from __future__ import annotations

import contextlib
import json
import webbrowser
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from texlate.cli import app

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

fcntl = pytest.importorskip("fcntl", reason="无 fcntl 平台锁语义不适用")

_RUNNER = CliRunner()


@contextlib.contextmanager
def _held_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, meta: bytes = b""
) -> Iterator[list[str]]:
    """持 ``service.lock`` + ``webbrowser.open`` 捕获——contended 测试的占用侧脚手架。

    ``meta`` 非空则先写入锁文件（持有者登记的 {pid,url} 元数据）。"""
    holder = (tmp_path / "service.lock").open("a+b")
    if meta:
        holder.write(meta)
        holder.flush()
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    try:
        yield opened
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()


@pytest.fixture
def _local_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEXLATE_MODE=server 会按设计跳过锁——钉回 local。"""
    monkeypatch.delenv("TEXLATE_MODE", raising=False)


@pytest.mark.usefixtures("_local_mode")
class TestServiceLock:
    def test_contended_opens_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """锁被持有 → 读锁文件 url → webbrowser.open + exit 0（不起服）。"""
        with _held_lock(
            tmp_path, monkeypatch, b'{"pid": 1, "url": "http://127.0.0.1:8765"}'
        ) as opened:
            result = _RUNNER.invoke(
                app, ["web", "--data-dir", str(tmp_path), "--port", "9999"]
            )
        assert result.exit_code == 0, result.output
        assert "已在运行" in result.stderr
        # 锁文件里的 url（8765）优先于本次请求的 --port 9999
        assert opened == ["http://127.0.0.1:8765"]

    def test_contended_no_meta_falls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """锁文件无元数据 → 回退按 host/port 推断已运行实例地址。"""
        with _held_lock(tmp_path, monkeypatch) as opened:
            result = _RUNNER.invoke(
                app, ["web", "--data-dir", str(tmp_path), "--port", "9999"]
            )
        assert result.exit_code == 0, result.output
        assert opened == ["http://127.0.0.1:9999"]

    def test_acquire_writes_meta_and_releases(self, tmp_path: Path) -> None:
        """拿锁写 {pid,url}；fd 关闭后锁可重获取（进程死亡释放语义）。"""
        from texlate.cli import _service_lock  # noqa: PLC0415

        fh, existing = _service_lock(tmp_path, "127.0.0.1", 8765)
        assert existing is None
        assert fh is not None
        meta = json.loads((tmp_path / "service.lock").read_text())
        assert meta["url"] == "http://127.0.0.1:8765"
        fh.close()
        fh2, existing2 = _service_lock(tmp_path, "127.0.0.1", 8765)
        assert existing2 is None
        assert fh2 is not None
        fh2.close()

    def test_server_mode_skips_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``TEXLATE_MODE=server`` 多副本部署形态跳过锁（§6）。"""
        from texlate.cli import _service_lock  # noqa: PLC0415

        monkeypatch.setenv("TEXLATE_MODE", "server")
        fh, existing = _service_lock(
            tmp_path,
            "0.0.0.0",  # noqa: S104 -- 参数非绑定
            8765,
        )
        assert (fh, existing) == (None, None)
