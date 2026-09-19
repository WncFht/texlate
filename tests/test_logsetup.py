"""``texlate.logsetup`` 日志底座：级别三来源 / 幂等重入 / 文件落盘 /
scrub 抹 key / caplog 兼容（propagate=True）。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from texlate.logsetup import (
    ENV_LOG,
    ENV_LOG_FILE,
    RedactFilter,
    _file_from_env,
    _resolve_level,
    configure_logging,
    configure_server_logging,
    level_from_flags,
    scrub,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_TEXLATE_LOG = logging.getLogger("texlate")


@pytest.fixture(autouse=True)
def _clean_texlate_logger() -> Iterator[None]:
    """texlate logger 是全局态——用例前后摘掉本模块装的 handler。"""
    yield
    for h in list(_TEXLATE_LOG.handlers):
        _TEXLATE_LOG.removeHandler(h)
        h.close()
    _TEXLATE_LOG.setLevel(logging.NOTSET)


class TestResolveLevel:
    """显式参 > ``TEXLATE_LOG`` env > default；off 全闸。"""

    def test_explicit_arg_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_LOG, "debug")
        assert _resolve_level("error", logging.WARNING) == logging.ERROR
        assert _resolve_level(logging.INFO, logging.WARNING) == logging.INFO

    def test_env_beats_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_LOG, "DEBUG")
        assert _resolve_level(None, logging.WARNING) == logging.DEBUG

    def test_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_LOG, raising=False)
        assert _resolve_level(None, logging.WARNING) == logging.WARNING

    def test_off_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_LOG, "off")
        assert _resolve_level(None, logging.WARNING) > logging.CRITICAL

    def test_bad_env_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_LOG, "bogus")
        assert _resolve_level(None, logging.WARNING) == logging.WARNING


class TestLevelFromFlags:
    """-v/-q count 旗标映射。"""

    def test_mapping(self) -> None:
        assert level_from_flags(0, 0) == logging.WARNING
        assert level_from_flags(1, 0) == logging.INFO
        assert level_from_flags(2, 0) == logging.DEBUG
        assert level_from_flags(0, 1) == logging.ERROR
        assert level_from_flags(0, 2) == logging.CRITICAL
        assert level_from_flags(3, 1) == logging.ERROR  # quiet 优先


class TestConfigureLogging:
    """handler 装配：幂等重入 / off 全闸 / 外部 handler 不动。"""

    def test_installs_stderr_handler(self) -> None:
        lg = configure_logging()
        managed = [h for h in lg.handlers if getattr(h, "_texlate_managed", False)]
        assert len(managed) == 1
        assert lg.level == logging.WARNING

    def test_idempotent_reentry(self) -> None:
        lg = configure_logging()
        first = list(lg.handlers)
        lg2 = configure_logging(level="info")
        assert lg2 is lg
        assert all(h not in lg.handlers for h in first)
        managed = [h for h in lg.handlers if getattr(h, "_texlate_managed", False)]
        assert len(managed) == 1
        assert lg.level == logging.INFO

    def test_foreign_handler_survives_reentry(self) -> None:
        foreign = logging.StreamHandler()
        _TEXLATE_LOG.addHandler(foreign)
        configure_logging()
        configure_logging()
        assert foreign in _TEXLATE_LOG.handlers

    def test_off_installs_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_LOG, "off")
        lg = configure_logging()
        assert not lg.handlers
        assert lg.level > logging.CRITICAL

    def test_propagate_stays_true(self) -> None:
        lg = configure_logging()
        assert lg.propagate


class TestFileHandler:
    """``file=``/``TEXLATE_LOG_FILE`` 三态。"""

    def test_file_writes_records(self, tmp_path: Path) -> None:
        fp = tmp_path / "logs" / "t.log"
        lg = configure_logging(level="debug", file=fp)
        lg.debug("落盘行 sk-should-be-scrubbed-12345")
        for h in lg.handlers:
            h.flush()
        text = fp.read_text(encoding="utf-8")
        assert "落盘行" in text
        assert "sk-should-be-scrubbed-12345" not in text
        assert "***" in text

    def test_env_off_disables_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_LOG_FILE, "off")
        assert _file_from_env(None) is None

    def test_env_path_overrides(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fp = tmp_path / "custom.log"
        monkeypatch.setenv(ENV_LOG_FILE, str(fp))
        assert _file_from_env(None) == fp

    def test_env_unset_returns_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv(ENV_LOG_FILE, raising=False)
        default = tmp_path / "x.log"
        assert _file_from_env(default) == default

    def test_unwritable_dir_degrades(self, tmp_path: Path) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir", encoding="utf-8")
        lg = configure_logging(file=blocker / "sub" / "t.log")
        managed = [h for h in lg.handlers if getattr(h, "_texlate_managed", False)]
        assert len(managed) == 1  # 仅 stderr，文件降级不炸


class TestServerLogging:
    """``configure_server_logging``：data_dir 落盘 + env 关文件。"""

    def test_writes_under_data_dir(self, tmp_path: Path) -> None:
        fp = configure_server_logging(tmp_path)
        assert fp == tmp_path / "logs" / "texlate.log"
        _TEXLATE_LOG.info("server 行")
        for h in _TEXLATE_LOG.handlers:
            h.flush()
        assert "server 行" in fp.read_text(encoding="utf-8")

    def test_env_off_returns_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(ENV_LOG_FILE, "off")
        assert configure_server_logging(tmp_path) is None


class TestScrub:
    """``scrub``/``RedactFilter`` 抹 key 形态。"""

    def test_scrubs_sk_and_bearer(self) -> None:
        out = scrub("key=sk-abcdef12345 Bearer token-xyz")
        assert "sk-abcdef12345" not in out
        assert "Bearer token-xyz" not in out

    def test_scrubs_explicit_key(self) -> None:
        assert "my-secret-key" not in scrub("use my-secret-key ok", "my-secret-key")

    def test_filter_key_provider_dynamic(self) -> None:
        keys = ["k-one"]
        filt = RedactFilter(lambda: keys)
        rec = logging.LogRecord("t", logging.INFO, __file__, 1, "has k-one", (), None)
        filt.filter(rec)
        assert "k-one" not in rec.getMessage()
        keys.append("k-two")
        rec2 = logging.LogRecord("t", logging.INFO, __file__, 1, "has k-two", (), None)
        filt.filter(rec2)
        assert "k-two" not in rec2.getMessage()

    def test_filter_provider_exception_survives(self) -> None:
        def boom() -> list[str]:
            err = "provider boom"
            raise RuntimeError(err)

        filt = RedactFilter(boom)
        rec = logging.LogRecord("t", logging.INFO, __file__, 1, "plain", (), None)
        assert filt.filter(rec)


class TestCaplogCompat:
    """propagate=True → pytest caplog（root handler）照常采集。"""

    def test_caplog_sees_records(self, caplog: pytest.LogCaptureFixture) -> None:
        configure_logging()
        with caplog.at_level(logging.INFO, logger="texlate"):
            _TEXLATE_LOG.info("caplog 可见")
        assert "caplog 可见" in caplog.text
