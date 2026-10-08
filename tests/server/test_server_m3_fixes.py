"""M3 smoke 三修（bench/results/m3smoke-2026-09-17/report.md B1–B3）：

- B1：babeldoc fault message 吞根因——rc 与 stderr 尾摘要必须进 message，
  且 api_key 绝不泄漏进 message/stderr_tail。
- B3：``/api/health`` 带 ``commit``/``started_at`` 构建戳。

（原 B2 ``model_warning``/``list_provider_models`` 随 BYOK 全面切除下线——
模型归属校验归渠道探针 ``probe_channel``/``record_probe``。）
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

import texlate.server.app as app_mod
import texlate.server.http as http_mod
from texlate.server import babeldoc as bd
from texlate.server.settings import SettingsStore

if TYPE_CHECKING:
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


class TestSettingsSaveLock:
    """``save`` 序列化：``_save_lock`` 接管原事件循环隐式串行。"""

    def test_save_serializes_under_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``save`` 全程持 ``_save_lock``——to_thread 卸载后并发 PUT 的
        load→merge→write 不能再靠事件循环单线程隐式串行。"""
        store = SettingsStore(tmp_path)
        entered = threading.Event()
        orig = store._save  # noqa: SLF001

        def spy(updates: dict[str, Any]) -> dict[str, Any]:
            entered.set()
            return orig(updates)

        monkeypatch.setattr(store, "_save", spy)
        store._save_lock.acquire()  # noqa: SLF001
        t = threading.Thread(target=store.save, args=({"glossary": "g2.yaml"},))
        t.start()
        try:
            # 锁被占时 save 进不了临界区（反向等待——永不置位才算过）
            assert not entered.wait(1.0)
        finally:
            store._save_lock.release()  # noqa: SLF001
        t.join(10)
        assert entered.is_set()
        assert store.load()["glossary"] == "g2.yaml"


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
