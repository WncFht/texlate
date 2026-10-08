"""server settings/salt 面钉样：``_auth`` 每请求单读 /
settings load 字段级容错 / server_salt 空文件重生成。

自 test_worker_audit_fixes.py 切出（server-residual 波的四类）。
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from texlate.server.settings import SettingsStore, server_salt

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from starlette.testclient import TestClient


class TestAuthOncePerRequest:
    """``_auth`` 每请求缓存：translate 单链决议 3+ 次，settings.json 只读一次。"""

    def test_translate_loads_settings_once(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = client.app.state.settings_store
        calls = 0
        orig = store.load

        def spy() -> dict:
            nonlocal calls
            calls += 1
            return orig()

        monkeypatch.setattr(store, "load", spy)
        r = client.post("/api/arxiv/2401.00022/translate", json={})
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        assert calls == 1, (
            f"一次 translate 请求读了 {calls} 次 settings.json"
            "（_auth/model/target_lang/quota 应共享同一快照）"
        )


class TestSettingsLoadTolerant:
    """``load()`` 字段级容错——文件级损坏已有兜底，手改字段留垃圾不能炸 500。"""

    def test_corrupt_concurrency_falls_back(self, tmp_path: Path) -> None:
        (tmp_path / "settings.json").write_text(
            '{"concurrency": "abc"}', encoding="utf-8"
        )
        assert SettingsStore(tmp_path).load()["concurrency"] == 10  # noqa: PLR2004 -- 缺省值钉样

    def test_zero_and_negative_concurrency(self, tmp_path: Path) -> None:
        (tmp_path / "settings.json").write_text('{"concurrency": 0}', encoding="utf-8")
        assert SettingsStore(tmp_path).load()["concurrency"] == 10  # noqa: PLR2004 -- 0 → 缺省
        (tmp_path / "settings.json").write_text('{"concurrency": -2}', encoding="utf-8")
        assert SettingsStore(tmp_path).load()["concurrency"] == 1  # 负 → clamp


class TestServerSaltEmpty:
    """空/全空白 salt 文件重生成——空盐下租户指纹退成裸 sha256(key)。"""

    def test_empty_file_regenerated(self, tmp_path: Path) -> None:
        (tmp_path / "server_salt").write_text("", encoding="utf-8")
        salt = server_salt(tmp_path)
        assert salt
        assert (tmp_path / "server_salt").read_text(encoding="utf-8") == salt

    def test_valid_file_kept(self, tmp_path: Path) -> None:
        (tmp_path / "server_salt").write_text("deadcafe", encoding="utf-8")
        assert server_salt(tmp_path) == "deadcafe"
