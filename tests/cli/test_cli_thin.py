"""``run --server`` 瘦客户端：MockTransport 全离线——提交/轮询/下载/退出码。

由 ``test_cli`` 拆出（瘦客户端块自包含、与 run/parse/fetch/web/share 面零共享）：
``httpx.MockTransport`` 背板驱动提交/409 attach/快照终态/产物 sha256 对账/
lost·needs_auth 短路 + SSE 实况帧（重连 Last-Event-ID/resync 快照重置/
quiet 轮询/fixloop 紧凑行）。typer CliRunner 三流分离：JSON 报告在
``result.stdout``、诊断在 ``result.stderr``（``output`` 是混合流，不做解析面）。
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import httpx
import pytest
from typer.testing import CliRunner, Result

from texlate.cli import app
from texlate.cli._output import console

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_RUNNER = CliRunner()


@pytest.fixture(autouse=True)
def _plain_terminal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉无色彩端——纯文本 stderr 断言前提。

    ``FORCE_COLOR``/``TTY_COMPATIBLE`` 会把 rich ``is_terminal`` 顶成 True
    （CliRunner 捕获非 tty 也开 Live 进度条与转义序列），须摘除；
    ``console._color_system`` 又在 import 时已按当时环境冻结，运行期摘 env
    不改已缓存的色域——须置 None 让 ``style.render`` 走无色路径。
    """
    for key in ("FORCE_COLOR", "TTY_COMPATIBLE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(console, "_color_system", None)


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[str]:
    """``httpx.Client`` 换 ``MockTransport`` 背板——返回请求路径流水供断言。"""
    calls: list[str] = []

    def _h(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        return handler(request)

    real = httpx.Client

    def _factory(*a: object, **kw: object) -> httpx.Client:
        kw["transport"] = httpx.MockTransport(_h)
        return real(*a, **kw)

    monkeypatch.setattr(httpx, "Client", _factory)
    return calls


class TestThinRun:
    """``run --server`` 瘦客户端：MockTransport 全离线——提交/轮询/下载/退出码。"""

    _TASK = "t_thin01"

    def _handler_ok(self, blob: bytes, sha: str) -> Callable:
        def handler(req: httpx.Request) -> httpx.Response:
            p = req.url.path
            if p.endswith("/translate"):
                return httpx.Response(
                    200, json={"task_id": self._TASK, "status": "queued"}
                )
            if p == f"/api/task/{self._TASK}":
                return httpx.Response(
                    200,
                    json={
                        "status": "done",
                        "stage": "compile",
                        "progress": 100,
                        "counters": {"done": 5, "total": 5, "failed": 0},
                    },
                )
            if p == f"/api/files/{self._TASK}":
                return httpx.Response(
                    200,
                    json={
                        "artifacts": {
                            "zh.pdf": {
                                "url": f"/api/files/{self._TASK}/zh.pdf",
                                "sha256": sha,
                            }
                        }
                    },
                )
            if p == f"/api/files/{self._TASK}/zh.pdf":
                return httpx.Response(200, content=blob)
            return httpx.Response(404)

        return handler

    def _invoke(self, *args: str) -> Result:
        return _RUNNER.invoke(
            app, ["run", "2001.00001v2", "--server", "http://s", *args]
        )

    def test_done_downloads_artifacts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """终态 done → 产物逐件流式下载 + sha256 对账 → exit 0。"""
        blob = b"%PDF-zh fake"
        sha = hashlib.sha256(blob).hexdigest()
        _patch_httpx(monkeypatch, self._handler_ok(blob, sha))
        out = tmp_path / "o"
        result = self._invoke("--out", str(out))
        assert result.exit_code == 0, result.output
        rep = json.loads(result.stdout)
        assert rep["task_id"] == self._TASK
        assert rep["status"] == "done"
        assert rep["artifacts"]["zh.pdf"] == str(out / "zh.pdf")
        assert (out / "zh.pdf").read_bytes() == blob
        assert not list(out.glob("*.part"))  # 临时件不残留

    def test_conflict_attach_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """409 duplicate_active → 复用其 task_id attach → 正常等终态。"""
        blob = b"%PDF-zh"
        sha = hashlib.sha256(blob).hexdigest()
        ok = self._handler_ok(blob, sha)

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path.endswith("/translate"):
                return httpx.Response(
                    409, json={"detail": "duplicate_active", "task_id": self._TASK}
                )
            return ok(req)

        _patch_httpx(monkeypatch, handler)
        result = self._invoke("--out", str(tmp_path / "o"))
        assert result.exit_code == 0, result.output
        assert "attach 进行中任务 t_thin01" in result.stderr

    def test_lost_skips_download(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """快照非 200 → lost → exit 1，且不再请求产物清单（端点已失联）。"""
        calls = _patch_httpx(
            monkeypatch,
            lambda req: (
                httpx.Response(200, json={"task_id": self._TASK, "status": "queued"})
                if req.url.path.endswith("/translate")
                else httpx.Response(404, json={"detail": "gone"})
            ),
        )
        result = self._invoke()
        assert result.exit_code == 1
        assert json.loads(result.stdout)["status"] == "lost"
        assert not any("/api/files/" in c for c in calls)

    def test_needs_auth_skips_download(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """终态 needs_auth → exit 2；任务未产出 → 不打产物清单。"""
        calls = _patch_httpx(
            monkeypatch,
            lambda req: (
                httpx.Response(200, json={"task_id": self._TASK, "status": "queued"})
                if req.url.path.endswith("/translate")
                else httpx.Response(200, json={"status": "needs_auth"})
            ),
        )
        result = self._invoke()
        assert result.exit_code == 2  # noqa: PLR2004
        assert not any("/api/files/" in c for c in calls)

    def test_non_dict_snapshot_is_lost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """快照 200 但非对象 JSON → 不当崩溃（AttributeError）而是 lost exit 1。"""
        _patch_httpx(
            monkeypatch,
            lambda req: (
                httpx.Response(200, json={"task_id": self._TASK, "status": "queued"})
                if req.url.path.endswith("/translate")
                else httpx.Response(200, json=["not", "a", "dict"])
            ),
        )
        result = self._invoke()
        assert result.exit_code == 1
        assert "快照非法" in result.stderr
        assert "Traceback" not in result.output

    def test_wait_zero_times_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--wait 0 + 非终态快照 → 立即超时 exit 1 + attach 提示。"""
        _patch_httpx(
            monkeypatch,
            lambda req: (
                httpx.Response(200, json={"task_id": self._TASK, "status": "queued"})
                if req.url.path.endswith("/translate")
                else httpx.Response(
                    200,
                    json={
                        "status": "running",
                        "stage": "xlat",
                        "progress": 40,
                        "counters": {"done": 2, "total": 5, "failed": 0},
                    },
                )
            ),
        )
        result = self._invoke("--wait", "0")
        assert result.exit_code == 1
        assert "等待超时" in result.stderr
        assert "attach" in result.stderr

    def test_submit_rejected_exit_2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """提交被拒（422）→ exit 2 干净报错。"""
        _patch_httpx(
            monkeypatch,
            lambda _req: httpx.Response(422, json={"detail": "bad id"}),
        )
        result = self._invoke()
        assert result.exit_code == 2  # noqa: PLR2004
        assert "translate 422" in result.stderr

    def test_sha256_mismatch_skips_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """产物 sha256 不符 → 跳过该件不留盘，任务本身 done → exit 0。"""
        _patch_httpx(monkeypatch, self._handler_ok(b"%PDF-real", "f" * 64))
        out = tmp_path / "o"
        result = self._invoke("--out", str(out))
        assert result.exit_code == 0, result.output
        assert "sha256 不符" in result.stderr
        rep = json.loads(result.stdout)
        assert rep["artifacts"] == {}
        assert not (out / "zh.pdf").exists()
        assert not list(out.glob("*.part"))

    def test_traversal_artifact_name_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """产物 url 末段 ``..`` → 跳过且不发请求（防 dest 外逃逸）。"""
        blob = b"%PDF-zh"
        sha = hashlib.sha256(blob).hexdigest()
        ok = self._handler_ok(blob, sha)

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == f"/api/files/{self._TASK}":
                return httpx.Response(
                    200,
                    json={
                        "artifacts": {
                            "evil": {
                                "url": f"/api/files/{self._TASK}/..",
                                "sha256": sha,
                            },
                            "zh.pdf": {
                                "url": f"/api/files/{self._TASK}/zh.pdf",
                                "sha256": sha,
                            },
                        }
                    },
                )
            return ok(req)

        calls = _patch_httpx(monkeypatch, handler)
        out = tmp_path / "o"
        result = self._invoke("--out", str(out))
        assert result.exit_code == 0, result.output
        assert "产物名非法" in result.stderr
        rep = json.loads(result.stdout)
        assert set(rep["artifacts"]) == {"zh.pdf"}
        assert (out / "zh.pdf").is_file()
        assert not any(c.endswith((" /..", "/..")) for c in calls)

    def test_empty_artifacts_no_dir_residue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """产物清单为空 → 不建默认 ``texlate-{id}-{task}`` 目录（cwd 零残渣）。"""
        ok = self._handler_ok(b"%PDF-zh", "f" * 64)

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == f"/api/files/{self._TASK}":
                return httpx.Response(200, json={"artifacts": {}})
            return ok(req)

        _patch_httpx(monkeypatch, handler)
        monkeypatch.chdir(tmp_path)
        result = self._invoke()
        assert result.exit_code == 0, result.output
        assert not list(tmp_path.iterdir())

    def test_all_fetches_fail_removes_new_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """产物全下载失败 → 本调用新建的空壳目录回收，不留空 dir。"""
        _patch_httpx(monkeypatch, self._handler_ok(b"%PDF-zh", "f" * 64))
        monkeypatch.chdir(tmp_path)
        result = self._invoke()
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["artifacts"] == {}
        assert not list(tmp_path.iterdir())

    # ---------------------------------------------------------------- SSE 实况

    @staticmethod
    def _sse_bytes(frames: list[tuple[int, str, dict[str, object]]]) -> bytes:
        """``(seq, event, data)`` 帧组 → SSE wire bytes。"""
        return "".join(
            f"id: {seq}\nevent: {ev}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            for seq, ev, data in frames
        ).encode()

    def _sse_handler(
        self, frames: list[tuple[int, str, dict[str, object]]]
    ) -> Callable[[httpx.Request], httpx.Response]:
        """Accept 分流背板：SSE 请求吃帧流，普通 GET 走 ``_handler_ok`` JSON 面。"""
        ok = self._handler_ok(b"%PDF-zh", "f" * 64)

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == f"/api/task/{self._TASK}" and (
                "text/event-stream" in req.headers.get("accept", "")
            ):
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=self._sse_bytes(frames),
                )
            return ok(req)

        return handler

    def test_sse_renders_frames_to_done(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SSE 流：snapshot/stage/chunk/warning/done 逐型渲 stderr，终态取自 done 帧。"""
        frames = [
            (
                0,
                "snapshot",
                {
                    "status": "running",
                    "stage": "translating",
                    "progress": 30,
                    "counters": {"done": 0, "total": 4, "failed": 0},
                },
            ),
            (
                1,
                "stage",
                {"stage": "translating", "progress": 30, "message": "翻译"},
            ),
            (2, "chunk", {"done": 2, "total": 4, "failed": 0, "items": []}),
            (3, "chunk", {"done": 4, "total": 4, "failed": 1, "items": []}),
            (4, "warning", {"code": "mock_engine", "message": "mock 引擎在跑"}),
            (5, "done", {"status": "done", "artifacts": {}, "stats": {}}),
        ]
        _patch_httpx(monkeypatch, self._sse_handler(frames))
        result = self._invoke()
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["status"] == "done"
        err = result.stderr
        assert "running/translating 30% chunks=0/4" in err
        assert "translating 30% 翻译" in err
        assert "chunks 4/4" in err
        assert "warning mock_engine: mock 引擎在跑" in err
        assert "回退" not in err

    def test_sse_json_response_falls_back_to_poll(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``/api/task`` 回 JSON（无 SSE 面）→ 回退提示 + 轮询通道到终态。"""
        _patch_httpx(monkeypatch, self._handler_ok(b"%PDF", "f" * 64))
        result = self._invoke()
        assert result.exit_code == 0, result.output
        assert "回退快照轮询" in result.stderr

    def test_sse_early_eof_reconnects_with_last_event_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """流早夭（无 done 帧）→ ``Last-Event-ID`` 续放×2 → 尽后回退轮询。"""
        sse_lei: list[str | None] = []
        ok = self._handler_ok(b"%PDF", "f" * 64)

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == f"/api/task/{self._TASK}" and (
                "text/event-stream" in req.headers.get("accept", "")
            ):
                sse_lei.append(req.headers.get("last-event-id"))
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=self._sse_bytes(
                        [(5, "snapshot", {"status": "running", "progress": 10})]
                    ),
                )
            return ok(req)

        _patch_httpx(monkeypatch, handler)
        result = self._invoke()
        assert result.exit_code == 0, result.output
        # 首开无水位 → 两次重连均带 Last-Event-ID:5，尽后回退轮询
        assert sse_lei == [None, "5", "5"]
        assert "回退快照轮询" in result.stderr

    def test_sse_resync_refetches_snapshot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``resync`` 缺口帧 → 拉新快照重置水位（普通 JSON GET）→ 续流到 done。"""
        frames = [
            (
                1,
                "stage",
                {"stage": "translating", "progress": 30, "message": "翻译"},
            ),
            (9, "resync", {"gap_after": 0, "resume_from": 5}),
            (10, "done", {"status": "done", "artifacts": {}, "stats": {}}),
        ]
        _patch_httpx(monkeypatch, self._sse_handler(frames))
        result = self._invoke()
        assert result.exit_code == 0, result.output
        # resync 拉到的快照是 _handler_ok 的 done 行（非 SSE GET 通道）
        assert "done/compile 100% chunks=5/5 failed=0" in result.stderr

    def test_sse_quiet_uses_polling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``-q`` → 静默轮询通道：快照状态行不渲，SSE 面在场也不消费。"""
        frames = [(1, "done", {"status": "done", "artifacts": {}, "stats": {}})]
        _patch_httpx(monkeypatch, self._sse_handler(frames))
        result = self._invoke("-q")
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["status"] == "done"
        assert "chunks=" not in result.stderr  # 快照状态行全抑
        assert "回退快照轮询" not in result.stderr

    def test_sse_fixloop_compact_round_and_log_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``fixloop`` round dict → 紧凑行；``log`` trace 噪音缺省滤、叙事行透传。"""
        import logging  # noqa: PLC0415

        from texlate.cli import _output  # noqa: PLC0415

        monkeypatch.setattr(_output.log, "level", logging.WARNING)  # 钉缺省过滤态
        _output.log.manager._clear_cache()  # noqa: SLF001 -- isEnabledFor 有缓存
        frames = [
            (
                1,
                "fixloop",
                {
                    "phase": "round",
                    "round": {
                        "round": 1,
                        "pdf": True,
                        "n_errors": 68,
                        "category": "missing_file",
                        "payload": "plex-sans.sty",
                        "warnings": ["missing_char"],
                        "line_no": 94,
                        "file_stack": ["main.tex", "phai.cls"],
                        "sec": 15.7,
                    },
                },
            ),
            (2, "log", {"line": "fixloop: rule x: cond skip (y)"}),
            (
                3,
                "log",
                {"line": "fixloop: apply install_file: already-present a.sty"},
            ),
            (
                4,
                "fixloop",
                {"phase": "done", "cell": {"verdict": "dirty_pdf", "rounds": [{}]}},
            ),
            (5, "done", {"status": "done", "artifacts": {}, "stats": {}}),
        ]
        _patch_httpx(monkeypatch, self._sse_handler(frames))
        result = self._invoke()
        assert result.exit_code == 0, result.output
        err = result.stderr
        assert "fixloop r1 missing_file:plex-sans.sty err=68" in err
        assert "at=phai.cls:94" in err
        assert "'pdf_bytes'" not in err  # 整 dict repr 不再泄漏
        assert "cond skip" not in err
        assert "apply install_file" in err
        assert "fixloop done verdict=dirty_pdf rounds=1" in err
