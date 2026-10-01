"""M3 smoke 三修（bench/results/m3smoke-2026-09-17/report.md B1–B3）：

- B1：babeldoc fault message 吞根因——rc 与 stderr 尾摘要必须进 message，
  且 api_key 绝不泄漏进 message/stderr_tail。
- B2：settings 存了 provider 不广告的 model → ``model_warning`` 随
  ``public()``/PUT 响应透出；探活失败面不阻断保存。
- B3：``/api/health`` 带 ``commit``/``started_at`` 构建戳。
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

import texlate.server.app as app_mod
import texlate.server.http as http_mod
import texlate.server.settings as settings_mod
from texlate.server import babeldoc as bd
from texlate.server.settings import SettingsStore

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import Any

    from starlette.testclient import TestClient


def _job(tmp_path: Path, **kw: object) -> bd.BabeldocJob:
    base = {
        "src": tmp_path / "a.pdf",
        "outdir": tmp_path / "o",
        "workdir": tmp_path / "w",
        "model": "m1",
        "base_url": "http://gw.local:3003",
    }
    base.update(kw)
    return bd.BabeldocJob(**base)  # type: ignore[arg-type]


def _feed(*lines: str) -> bd._Feed:
    feed = bd._Feed()  # noqa: SLF001
    feed.feed(("\n".join(lines) + "\n").encode())
    feed.flush()
    return feed


_TRACK_EMPTY = {
    "total": 0,
    "errors": 0,
    "fallbacks": 0,
    "error_samples": [],
    "tracking_found": False,
}


class TestB1FaultRootCause:
    """fault message 必带 rc + stderr 尾摘要；key 脱敏。"""

    def test_rc0_no_outputs_carries_tail(self, tmp_path: Path) -> None:
        """rc=0 静默无产物——旧面恒「未产出」，新面带 rc + stderr 尾。"""
        feed = _feed(
            "Loading pipeline",
            "Error: the following arguments are required: --openai/--bing",
        )
        status, code, msg, retryable = bd._judge_run(  # noqa: SLF001
            _job(tmp_path),
            rc=0,
            timed_out=False,
            feed=feed,
            outputs={},
            track=_TRACK_EMPTY,
            stats={},
        )
        assert status == "failed"
        assert code == "compile"
        assert retryable
        assert "未产出译文 pdf" in msg
        assert "rc=0" in msg
        assert "--openai" in msg  # 真根因透到 fault 面

    def test_rc0_no_outputs_empty_tail(self, tmp_path: Path) -> None:
        """stderr 全空 → 裸消息 + rc，不编内容。"""
        status, code, msg, _r = bd._judge_run(  # noqa: SLF001
            _job(tmp_path),
            rc=0,
            timed_out=False,
            feed=bd._Feed(),  # noqa: SLF001
            outputs={},
            track=_TRACK_EMPTY,
            stats={},
        )
        assert status == "failed"
        assert code == "compile"
        assert msg == "babeldoc 未产出译文 pdf（rc=0）"

    def test_rc_nonzero_suffix_and_pick(self) -> None:
        """rc!=0 → 末条错误行 + rc 后缀（argparse rc=2 vs SIGKILL 可分）。"""
        feed = _feed("some noise", "Error: config parse failed")
        code, msg, retryable = bd._classify_rc(  # noqa: SLF001
            feed, api_key="", rc=2
        )
        assert (code, retryable) == ("compile", True)
        assert "config parse failed" in msg
        assert "rc=2" in msg

    def test_rc_suffix_via_judge(self, tmp_path: Path) -> None:
        feed = _feed("translate error: boom")
        _s, code, msg, _r = bd._judge_run(  # noqa: SLF001
            _job(tmp_path),
            rc=3,
            timed_out=False,
            feed=feed,
            outputs={},
            track=_TRACK_EMPTY,
            stats={},
        )
        assert code == "compile"
        assert "boom" in msg
        assert "rc=3" in msg

    @pytest.mark.parametrize(
        "key",
        [
            # 不命中任何 _SECRET_PATTERNS 的短数字 key——只有 job.api_key
            # 显式抹除通道能拦住，该通道断则本臂红（通用短数字形态）
            pytest.param("012345", id="explicit-only"),
            # sk- 形态命中通用正则——显式通道断掉也照过，保通用通道覆盖
            pytest.param("sk-super-secret-b123", id="generic-pattern"),
        ],
    )
    def test_api_key_scrubbed_from_message(self, tmp_path: Path, key: str) -> None:
        """stderr 回显 key → message 只见 ``***``（key 原位被替换）。"""
        feed = _feed(f"Error: upstream rejected key {key} at line 1")
        _s, _c, msg, _r = bd._judge_run(  # noqa: SLF001
            _job(tmp_path, api_key=key),
            rc=0,
            timed_out=False,
            feed=feed,
            outputs={},
            track=_TRACK_EMPTY,
            stats={},
        )
        assert key not in msg
        assert "rejected key ***" in msg

    def test_tail_excerpt_bounded(self) -> None:
        """尾摘要有界——长 traceback 不塞满 message（`` | `` 折行微扩容）。"""
        feed = _feed(*[f"line {i} " + "x" * 200 for i in range(30)])
        excerpt = bd._err_tail(feed, "")  # noqa: SLF001
        assert len(excerpt) < 600  # noqa: PLR2004 -- 500 截尾 + 折行符膨胀上界
        assert "\n" not in excerpt

    def test_zero_tokens_carries_tail(self, tmp_path: Path) -> None:
        """zero_tokens（疑似未配 key 空跑）同带 stderr 尾摘要。"""
        feed = _feed("openai error: api key missing", "Total tokens: 0")
        _s, code, msg, _r = bd._judge_run(  # noqa: SLF001
            _job(tmp_path),
            rc=0,
            timed_out=False,
            feed=feed,
            outputs={"mono": tmp_path / "m.pdf"},
            track=_TRACK_EMPTY,
            stats={},
        )
        assert code == "zero_tokens"
        assert "api key missing" in msg


class TestB2ModelWarning:
    """``save`` 探活 → ``model_warning`` 透出；失败面不阻断。"""

    @pytest.fixture(autouse=True)
    def _clear_models_cache(self) -> Iterator[None]:
        settings_mod._MODELS_CACHE.clear()  # noqa: SLF001 -- TTL 缓存跨用例污染
        yield
        settings_mod._MODELS_CACHE.clear()  # noqa: SLF001

    def test_unlisted_model_warns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            settings_mod, "list_provider_models", lambda *_a, **_k: ["real-m"]
        )
        store = SettingsStore(tmp_path)
        store.save({"model": "typo-m", "api_key": "sk-x"})
        body = store.public()
        assert "model_warning" in body
        assert "typo-m" in body["model_warning"]
        # 保存本身不被警告阻断
        assert body["model"] == "typo-m"

    def test_listed_model_no_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            settings_mod, "list_provider_models", lambda *_a, **_k: ["real-m", "m2"]
        )
        store = SettingsStore(tmp_path)
        store.save({"model": "real-m"})
        assert "model_warning" not in store.public()

    def test_unreachable_never_bricks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """探活失败（None）→ 无警告、save 照成——离线不砖 settings UX。"""
        monkeypatch.setattr(
            settings_mod, "list_provider_models", lambda *_a, **_k: None
        )
        store = SettingsStore(tmp_path)
        store.save({"model": "anything", "base_url": "https://api.example.com"})
        assert "model_warning" not in store.public()

    def test_unrelated_save_skips_probe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(
            settings_mod,
            "list_provider_models",
            lambda *_a, **_k: calls.append("hit") or [],
        )
        store = SettingsStore(tmp_path)
        store.save({"concurrency": 4})
        assert calls == []

    def test_probe_env_kill_switch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(
            settings_mod,
            "list_provider_models",
            lambda *_a, **_k: calls.append("hit") or [],
        )
        monkeypatch.setenv("TEXLATE_MODEL_PROBE", "0")
        store = SettingsStore(tmp_path)
        store.save({"model": "typo-m"})
        assert calls == []
        assert "model_warning" not in store.public()

    def test_put_response_carries_warning(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            settings_mod, "list_provider_models", lambda *_a, **_k: ["real-m"]
        )
        r = client.put("/api/settings", json={"model": "typo-m"})
        assert r.status_code == HTTPStatus.OK
        assert "typo-m" in r.json()["model_warning"]
        # GET 复现同一警告（进程瞬态口径）
        assert "model_warning" in client.get("/api/settings").json()

    def test_put_probe_off_event_loop(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """探活须在 worker 线程跑——若回退为 loop 内同步调用，3s+（DNS
        getaddrinfo 盲区可达数十秒）的同步 httpx 会冻结 SSE 与全部请求。"""
        on_loop: list[bool] = []

        def spy(*_a: object, **_k: object) -> list[str]:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                on_loop.append(False)
            else:
                on_loop.append(True)
            return ["real-m"]

        monkeypatch.setattr(settings_mod, "list_provider_models", spy)
        r = client.put("/api/settings", json={"model": "typo-m"})
        assert r.status_code == HTTPStatus.OK
        assert on_loop == [False]
        # 语义保持：警告仍随 PUT 响应透出
        assert "typo-m" in r.json()["model_warning"]

    def test_save_serializes_under_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``save`` 全程持 ``_save_lock``——to_thread 卸载后并发 PUT 的
        load→merge→write 不能再靠事件循环单线程隐式串行。"""
        monkeypatch.setattr(
            settings_mod, "list_provider_models", lambda *_a, **_k: ["m2"]
        )
        store = SettingsStore(tmp_path)
        entered = threading.Event()
        orig = store._save  # noqa: SLF001

        def spy(updates: dict[str, Any]) -> dict[str, Any]:
            entered.set()
            return orig(updates)

        monkeypatch.setattr(store, "_save", spy)
        store._save_lock.acquire()  # noqa: SLF001
        t = threading.Thread(target=store.save, args=({"model": "m2"},))
        t.start()
        try:
            # 锁被占时 save 进不了临界区（反向等待——永不置位才算过）
            assert not entered.wait(1.0)
        finally:
            store._save_lock.release()  # noqa: SLF001
        t.join(10)
        assert entered.is_set()
        assert store.load()["model"] == "m2"

    def test_list_provider_models_parse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """同步探活解析形：``data[*].id`` 抽取；非 2xx/坏 JSON → None。"""

        class _Resp:
            def __init__(self, payload: object, *, ok: bool = True) -> None:
                self._payload = payload
                self.is_success = ok

            def json(self) -> object:
                if isinstance(self._payload, Exception):
                    raise self._payload
                return self._payload

        seen: dict[str, object] = {}

        def fake_get(url: str, **kw: object) -> _Resp:
            seen["url"] = url
            seen["headers"] = kw.get("headers")
            return _Resp({"data": [{"id": "m1"}, {"id": "m2"}, {"noid": 1}]})

        monkeypatch.setattr("httpx.get", fake_get)
        got = settings_mod.list_provider_models("https://api.example.com/", "sk-k")
        assert got == ["m1", "m2"]
        assert seen["url"] == "https://api.example.com/v1/models"
        assert seen["headers"] == {"Authorization": "Bearer sk-k"}
        monkeypatch.setattr("httpx.get", lambda *_a, **_k: _Resp("boom", ok=False))
        assert settings_mod.list_provider_models("https://api.example.com") is None
        monkeypatch.setattr(
            "httpx.get",
            lambda *_a, **_k: _Resp(json.JSONDecodeError("x", "y", 0)),
        )
        assert settings_mod.list_provider_models("https://api.example.com") is None


class TestB3HealthBuildStamp:
    """``/api/health`` local 形态带构建戳；server 形态仍最小集。"""

    def test_health_stamp_keys(self, client: TestClient) -> None:
        body = client.get("/api/health").json()
        assert body["ok"] is True
        # 仓内测试必得非空短哈希——非 git 部署面由
        # test_probe_git_commit_tolerates_non_git 钉 ``""``
        assert body["commit"]
        assert body["commit"] == app_mod._BUILD_COMMIT  # noqa: SLF001
        assert body["started_at"] == app_mod._STARTED_AT  # noqa: SLF001
        # ISO 可解析 + 时区已钉（astimezone 不炸即 aware）
        dt = datetime.fromisoformat(body["started_at"])
        assert dt.tzinfo is not None
        assert body["version"] == app_mod.__version__

    def test_probe_git_commit_tolerates_non_git(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无 git/非仓路径 → ``""``（源码树外安装不炸）。"""
        monkeypatch.setattr(http_mod.shutil, "which", lambda _n: None)
        assert app_mod._probe_git_commit() == ""  # noqa: SLF001

    def test_server_mode_health_minimal(self, server_client: TestClient) -> None:
        """server 模式 health = ``{ok, db, queue_depth}`` 深度探活——部署拓扑键仍摘。"""
        assert server_client.get("/api/health").json() == {
            "ok": True,
            "db": True,
            "queue_depth": 0,
        }
