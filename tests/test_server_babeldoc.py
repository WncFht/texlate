"""upload_pdf → BabelDOC sidecar 通路（pdf-path §4 契约的假 CLI + 模块单测）。"""

from __future__ import annotations

import csv
import json
import stat
import sys
import time
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from _serverkit import sse_frames
from conftest import make_app, upload, wait_terminal
from starlette.testclient import TestClient

from texlate.server import babeldoc as bd

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

#: 假 babeldoc CLI：认 --files/--output/--working-dir/--lang-out/-c，
#: 按 ``FAKE_BABELDOC_MODE`` 出产物/报错；argv 落 ``workdir/argv.json``
#: 供「key 不进 argv」断言。
_FAKE = """\
import json
import os
import sys
import time
from pathlib import Path

argv = sys.argv[1:]


def opt(name):
    return argv[argv.index(name) + 1]


src = Path(opt("--files"))
outdir = Path(opt("--output"))
workdir = Path(opt("--working-dir"))
lang = opt("--lang-out")
outdir.mkdir(parents=True, exist_ok=True)
workdir.mkdir(parents=True, exist_ok=True)
stem = src.stem
(workdir / "argv.json").write_text(json.dumps(argv), encoding="utf-8")
mode = os.environ.get("FAKE_BABELDOC_MODE", "ok")


def tracking(tracker):
    d = workdir / stem
    d.mkdir(parents=True, exist_ok=True)
    (d / "translate_tracking.json").write_text(
        json.dumps({"page": [{"paragraph": [{"llm_translate_trackers": [tracker]}]}]}),
        encoding="utf-8",
    )


def emit():
    (outdir / f"{stem}.no_watermark.{lang}.mono.pdf").write_bytes(b"%PDF-1.4 mono")
    (outdir / f"{stem}.no_watermark.{lang}.dual.pdf").write_bytes(b"%PDF-1.4 dual")


if mode == "hang":
    time.sleep(60)
elif mode == "scanned":
    print("ScannedPDFError: scanned document", file=sys.stderr)
    sys.exit(2)
elif mode == "zero":
    emit()
    print("Total tokens: 0", file=sys.stderr)
    sys.exit(0)
elif mode == "degraded":
    tracking({"has_error": False, "fallback_to_translate": True})
    emit()
    print("Total tokens: 55", file=sys.stderr)
    sys.exit(0)
elif mode == "fail":
    print("translate error: boom", file=sys.stderr)
    sys.exit(3)
else:
    print("Parse PDF (1/5) 10/10", file=sys.stderr)
    print("translate 40/100", file=sys.stderr)
    print("translate 100/100", file=sys.stderr)
    tracking({"has_error": False, "fallback_to_translate": False})
    emit()
    print("Total tokens: 120", file=sys.stderr)
    sys.exit(0)
"""

_PDF_BYTES = b"%PDF-1.4 fake bytes for upload"


def _upload_pdf(client: TestClient, **kw: object) -> str:
    # M1：无 key 建行即 needs_auth 终态、worker 永不到达——默认带 key
    # （test_key_only_in_toml 自带 headers 时 setdefault 不覆盖）
    kw.setdefault("headers", {"X-Texlate-Key": "sk-test"})
    body = upload(
        client,
        name="paper.pdf",
        data=_PDF_BYTES,
        content_type="application/pdf",
        **kw,
    )
    return str(body["task_id"])


def _sse_events(client: TestClient, tid: str) -> list[tuple[str, dict]]:
    """终态后重放 SSE：``[(event, data)]``（done 帧自然终流）。"""
    return [(ev, d) for _i, ev, d in sse_frames(client, tid)]


def _job(tmp_path: Path, **kw: object) -> bd.BabeldocJob:
    """``BabeldocJob`` 小工厂——默认面与 ``test_server_m3_fixes._job`` 同体。"""
    base = {
        "src": tmp_path / "a.pdf",
        "outdir": tmp_path / "o",
        "workdir": tmp_path / "w",
        "model": "m1",
        "base_url": "http://gw.local:3003",
    }
    base.update(kw)
    return bd.BabeldocJob(**base)  # type: ignore[arg-type]


@pytest.fixture
def pdf_client(
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """worker 真跑 + 假 babeldoc CLI 的 TestClient。"""
    clean_env.delenv("FAKE_BABELDOC_MODE", raising=False)
    clean_env.delenv("TEXLATE_BABELDOC_TIMEOUT", raising=False)
    script = tmp_path / "fake_babeldoc.py"
    script.write_text(f"#!{sys.executable}\n" + _FAKE, encoding="utf-8")
    script.chmod(0o755)
    app = make_app(tmp_path, start_worker=True, babeldoc=str(script))
    with TestClient(app) as c:
        yield c


class TestRunPdf:
    """worker ``_run_pdf`` → sidecar 全链（dispatch + 终态映射 + 产物登记）。"""

    def test_ok_done(self, pdf_client: TestClient, tmp_path: Path) -> None:
        tid = _upload_pdf(pdf_client)
        snap = wait_terminal(pdf_client, tid)
        assert snap["status"] == "done"
        assert snap["progress"] == 100  # noqa: PLR2004 -- 终态刻度
        artifacts = pdf_client.get(f"/api/files/{tid}").json()["artifacts"]
        for kind in ("en_pdf", "zh_pdf", "dual_pdf", "dual_json"):
            assert kind in artifacts
        # sidecar 产物真落盘且名字对得上 harvest 规则
        root = tmp_path / "data" / "tasks" / tid
        assert (root / "zh.pdf").read_bytes() == b"%PDF-1.4 mono"
        assert (root / "dual.pdf").read_bytes() == b"%PDF-1.4 dual"
        # tracking json 被写进 workdir（assess 的输入面）
        assert (root / "babeldoc-work" / "paper" / "translate_tracking.json").is_file()

    def test_done_event_stats_and_logs(self, pdf_client: TestClient) -> None:
        tid = _upload_pdf(pdf_client)
        wait_terminal(pdf_client, tid)
        events = _sse_events(pdf_client, tid)
        done = next(d for t, d in events if t == "done")
        assert done["status"] == "done"
        assert done["stats"]["babeldoc"]["total_tokens"] == 120  # noqa: PLR2004
        log_lines = [d["line"] for t, d in events if t == "log"]
        assert any("Total tokens: 120" in ln for ln in log_lines)
        assert any("babeldoc stage: Parse PDF" in ln for ln in log_lines)
        # 进度帧走 on_progress 不进 log 流（rich 重绘噪声隔离）
        assert not any("40/100" in ln for ln in log_lines)

    def test_fail_maps_compile(
        self, pdf_client: TestClient, clean_env: pytest.MonkeyPatch
    ) -> None:
        clean_env.setenv("FAKE_BABELDOC_MODE", "fail")
        tid = _upload_pdf(pdf_client)
        snap = wait_terminal(pdf_client, tid)
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "compile"
        assert snap["error"]["retryable"] is True
        assert "boom" in snap["error"]["message"]

    def test_scanned_pdf_terminal(
        self, pdf_client: TestClient, clean_env: pytest.MonkeyPatch
    ) -> None:
        clean_env.setenv("FAKE_BABELDOC_MODE", "scanned")
        tid = _upload_pdf(pdf_client)
        snap = wait_terminal(pdf_client, tid)
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "scanned_pdf"
        assert snap["error"]["retryable"] is False

    def test_zero_tokens(
        self, pdf_client: TestClient, clean_env: pytest.MonkeyPatch
    ) -> None:
        clean_env.setenv("FAKE_BABELDOC_MODE", "zero")
        tid = _upload_pdf(pdf_client)
        snap = wait_terminal(pdf_client, tid)
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "zero_tokens"

    def test_degraded_partial(
        self, pdf_client: TestClient, clean_env: pytest.MonkeyPatch
    ) -> None:
        clean_env.setenv("FAKE_BABELDOC_MODE", "degraded")
        tid = _upload_pdf(pdf_client)
        snap = wait_terminal(pdf_client, tid)
        assert snap["status"] == "partial"
        assert snap["error"]["code"] == "degraded"
        # 降级单仍交付产物
        artifacts = pdf_client.get(f"/api/files/{tid}").json()["artifacts"]
        assert "zh_pdf" in artifacts

    def test_cancel_kills_sidecar(
        self, pdf_client: TestClient, clean_env: pytest.MonkeyPatch
    ) -> None:
        clean_env.setenv("FAKE_BABELDOC_MODE", "hang")
        tid = _upload_pdf(pdf_client)
        for _ in range(200):  # 等进 compiling（sidecar 已 spawn）
            snap = pdf_client.get(f"/api/task/{tid}").json()
            if snap.get("stage") == "compiling":
                break
            time.sleep(0.05)
        r = pdf_client.post(f"/api/task/{tid}/cancel")
        assert r.status_code == HTTPStatus.OK
        snap = wait_terminal(pdf_client, tid, timeout=15)
        assert snap["status"] == "cancelled"

    def test_timeout_maps_timeout(
        self, pdf_client: TestClient, clean_env: pytest.MonkeyPatch
    ) -> None:
        clean_env.setenv("FAKE_BABELDOC_MODE", "hang")
        clean_env.setenv("TEXLATE_BABELDOC_TIMEOUT", "1")
        tid = _upload_pdf(pdf_client)
        snap = wait_terminal(pdf_client, tid, timeout=20)
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "timeout"
        assert snap["error"]["retryable"] is True

    def test_key_only_in_toml(self, pdf_client: TestClient, tmp_path: Path) -> None:
        key = "sk-babeldoc-test-12345"
        tid = _upload_pdf(pdf_client, headers={"x-texlate-key": key})
        snap = wait_terminal(pdf_client, tid)
        assert snap["status"] == "done"
        work = tmp_path / "data" / "tasks" / tid / "babeldoc-work"
        argv = json.loads((work / "argv.json").read_text(encoding="utf-8"))
        assert "--openai-api-key" not in argv
        assert (
            "--max-pages-per-part" not in argv
        )  # split 模式禁用（tracking 会被 rmtree）
        assert all(key not in a for a in argv)  # key 绝不进 argv/ps
        toml = work / "babeldoc.toml"
        assert stat.S_IMODE(toml.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR
        assert key in toml.read_text(encoding="utf-8")


class TestUnit:
    """sidecar 模块纯函数：argv 契约 / tracking 统计 / 帧分类。"""

    def test_lang_out_for(self) -> None:
        assert bd.lang_out_for("zh-CN") == "zh-CN"
        assert bd.lang_out_for("zh-TW") == "zh-TW"
        assert bd.lang_out_for("en") == "en"
        assert bd.lang_out_for("fr") == "zh-CN"  # 未知 → 默认

    def test_default_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEXLATE_BABELDOC_TIMEOUT", raising=False)
        assert bd.default_timeout() == bd.DEFAULT_TIMEOUT_S
        monkeypatch.setenv("TEXLATE_BABELDOC_TIMEOUT", "30")
        assert bd.default_timeout() == pytest.approx(30.0)
        monkeypatch.setenv("TEXLATE_BABELDOC_TIMEOUT", "junk")
        assert bd.default_timeout() == bd.DEFAULT_TIMEOUT_S

    def test_build_argv_contract(self, tmp_path: Path) -> None:
        job = _job(tmp_path, api_key="sk-secret")
        argv = bd.build_argv(job, "/bin/babeldoc")
        assert "--working-dir" in argv
        assert "-c" in argv
        assert "--no-send-temperature" in argv  # 冒烟坑①默认关
        assert "--max-pages-per-part" not in argv
        assert "sk-secret" not in argv
        i = argv.index("--lang-out")
        assert argv[i + 1] == "zh-CN"
        j = argv.index("--openai-base-url")
        assert argv[j + 1] == "http://gw.local:3003/v1"  # openai SDK 根要 /v1

    def test_openai_base_url_v1_suffix(self, tmp_path: Path) -> None:
        job = _job(tmp_path, base_url="http://gw.local:3003/v1")
        argv = bd.build_argv(job, "/bin/babeldoc")
        j = argv.index("--openai-base-url")
        assert argv[j + 1] == "http://gw.local:3003/v1"  # 已带 /v1 不重复
        job.base_url = "http://gw.local:3003/v1/chat/completions/"
        argv = bd.build_argv(job, "/bin/babeldoc")
        assert argv[argv.index("--openai-base-url") + 1] == "http://gw.local:3003/v1"

    def test_write_config_0600(self, tmp_path: Path) -> None:
        job = _job(tmp_path, base_url="", api_key="k-secret")
        p = bd.write_config(job)
        assert stat.S_IMODE(p.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR
        body = p.read_text(encoding="utf-8")
        assert 'openai-api-key = "k-secret"' in body

    def test_glossary_csv(self, tmp_path: Path) -> None:
        p = tmp_path / "w" / "g.csv"
        assert bd.write_glossary_csv(p, []) is None
        out = bd.write_glossary_csv(p, [("alpha", "甲"), ("beta", "乙")])
        assert out == p
        with p.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        assert rows[0] == ["source", "target", "tgt_lng"]
        assert rows[1] == ["alpha", "甲", ""]

    def test_assess_tracking(self, tmp_path: Path) -> None:
        w = tmp_path / "w"
        d = w / "paper"
        d.mkdir(parents=True)
        (d / "translate_tracking.json").write_text(
            json.dumps(
                {
                    "page": [
                        {
                            "paragraph": [
                                {
                                    "llm_translate_trackers": [
                                        {
                                            "has_error": True,
                                            "error_message": "boom",
                                            "fallback_to_translate": True,
                                        },
                                        {"has_error": False},
                                    ]
                                }
                            ]
                        }
                    ],
                    "cross_column": [
                        {
                            "paragraph": [
                                {
                                    "llm_translate_trackers": [
                                        {"has_error": True, "error_message": "b2"}
                                    ]
                                }
                            ]
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        res = bd.assess_tracking(w, "paper")
        assert res["total"] == 3  # noqa: PLR2004 -- tracker 计数
        assert res["errors"] == 2  # noqa: PLR2004
        assert res["fallbacks"] == 1
        assert res["tracking_found"] is True
        assert res["error_samples"] == ["boom", "b2"]

    def test_tracking_paths_part_fallback(self, tmp_path: Path) -> None:
        w = tmp_path / "w"
        d = w / "doc" / "part_0"
        d.mkdir(parents=True)
        p = d / "translate_tracking.json"
        p.write_text("{}", encoding="utf-8")
        assert bd.tracking_paths(w, "doc") == [p]
        assert bd.tracking_paths(w, "nope") == []

    def test_feed_gates_progress_frames(self) -> None:
        logs: list[str] = []
        progs: list[tuple[float, str]] = []
        feed = bd._Feed(  # noqa: SLF001 -- 帧分类行为直测
            on_progress=lambda p, s: progs.append((p, s)),
            on_log=logs.append,
        )
        feed.feed(b"Parse PDF (1/5) 10/10\r\n")
        feed.feed(b"translate 40/100\r\nsome real log\n")
        feed.feed(b"Total tokens: 7\n")
        feed.flush()
        assert feed.stage == "Parse PDF"
        assert (40.0, "Parse PDF") in progs
        assert feed.stats["total_tokens"] == 7  # noqa: PLR2004
        assert "some real log" in logs
        assert any("Total tokens" in ln for ln in logs)
        assert not any("40/100" in ln for ln in logs)  # 进度帧不进 on_log
        assert not any("Parse PDF" in ln for ln in logs)  # stage 表行同帧
