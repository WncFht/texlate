"""POST /api/upload 的 docx/epub 接受面（§2.4：export_document 通路入队）。

worker ``_run_doc`` 补丁应用前（tmp/upload501-worker.patch 未落）：
TestDocPipeline 整类 skip——路由层契约（202/kind/落盘/配额）先行锁定。
"""

from __future__ import annotations

import io
import zipfile
from http import HTTPStatus
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from conftest import make_app, wait_terminal
from starlette.testclient import TestClient

from texlate.server.settings import SettingsStore
from texlate.server.worker import PipelineWorker


def _settings(data_root: Path, **updates: object) -> None:
    """create_app 之前预写 settings.json（quota 等 create 期读取的项用）。"""
    data_root.mkdir(parents=True, exist_ok=True)
    SettingsStore(data_root).save(updates)


def _docx() -> bytes:
    """最小 docx 魔数载荷（``word/document.xml`` 触发 _zip_kind→docx）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<doc/>")
    return buf.getvalue()


def _epub() -> bytes:
    """最小 epub 魔数载荷（mimetype=application/epub+zip → _zip_kind→epub）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("OEBPS/content.opf", "<package/>")
    return buf.getvalue()


def _post(client: TestClient, name: str, data: bytes, **fields: str) -> dict:
    """上传辅助：``fields`` 走 multipart 文本槽（model/target_lang/options）。"""
    r = client.post(
        "/api/upload",
        files={"file": (name, data, "application/octet-stream")},
        data=fields,
    )
    assert r.status_code == HTTPStatus.ACCEPTED, r.text
    return r.json()


def _task_kind(client: TestClient, task_id: str) -> str:
    """tasks 列表反查 kind（建行断言——worker 未跑时仍可读）。"""
    rows = client.get("/api/tasks").json()["tasks"]
    row = next(r for r in rows if r["task_id"] == task_id)
    return str(row["kind"])


class TestUploadDocRoute:
    """docx/epub → 202 + kind 建行 + upload blob 落盘（不再 501）。"""

    def test_docx_202_kind(self, client: TestClient) -> None:
        body = _post(client, "报告.docx", _docx())
        assert body["status"] == "queued"
        assert _task_kind(client, body["task_id"]) == "docx"

    def test_epub_202_kind(self, client: TestClient) -> None:
        body = _post(client, "book.epub", _epub())
        assert body["status"] == "queued"
        assert _task_kind(client, body["task_id"]) == "epub"

    def test_blob_persisted(self, client: TestClient) -> None:
        """upload/{safe_name} 落盘：建行前写 blob，worker _run_doc 以此为源。"""
        body = _post(client, "my book.epub", _epub())
        updir = client.app.state.data_dir / "tasks" / body["task_id"] / "upload"
        blobs = list(updir.glob("*"))
        assert len(blobs) == 1
        assert blobs[0].read_bytes() == _epub()
        # 文件名 sanitize：空格 → _（与 tex 路同纪律）
        assert blobs[0].name == "my_book.epub"

    def test_fields_accepted(self, client: TestClient) -> None:
        """model/target_lang/options 表单字段与 tex 路同面解析。"""
        body = _post(
            client,
            "a.docx",
            _docx(),
            model="mock-m",
            target_lang="zh-TW",
            options='{"prefer":"fresh"}',
        )
        snap = client.get(f"/api/task/{body['task_id']}").json()
        assert snap["model"] == "mock-m"
        assert snap["target_lang"] == "zh-TW"


class TestUploadDocGuards:
    """既有闸不退化：unknown 400 / pdf 无 babeldoc 501 / 配额 429。"""

    def test_unknown_still_400(self, client: TestClient) -> None:
        r = client.post(
            "/api/upload",
            files={"file": ("a.bin", b"\x00\x01\x02\x03", "application/octet-stream")},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "unsupported_format"

    def test_pdf_no_babeldoc_501(self, client: TestClient) -> None:
        r = client.post(
            "/api/upload",
            files={"file": ("a.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert r.status_code == HTTPStatus.NOT_IMPLEMENTED
        assert r.json()["code"] == "unsupported_format"

    def test_docx_quota_429(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """quota_max_bytes 对 docx 载荷同样生效（incoming_bytes=len(data)）。"""
        _settings(tmp_path / "data", quota_max_bytes=10)
        with TestClient(make_app(tmp_path)) as c:
            r = c.post(
                "/api/upload",
                files={"file": ("a.docx", _docx(), "application/octet-stream")},
            )
            assert r.status_code == HTTPStatus.TOO_MANY_REQUESTS
            assert r.json()["code"] == "quota_exceeded"


_HAS_RUN_DOC = hasattr(PipelineWorker, "_run_doc")


@pytest.mark.skipif(
    not _HAS_RUN_DOC,
    reason="worker _run_doc 未接线（tmp/upload501-worker.patch 待应用）",
)
class TestDocPipeline:
    """worker _run_doc 端到端：fake export_document 替身（不触网/不真插译）。"""

    def _fake_export(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        raise_exc: Exception | None = None,
    ) -> list[dict[str, object]]:
        """``texlate.export.export_document`` 替换件：写假 dst + 放一炮 on_result。"""
        import texlate.export  # noqa: PLC0415
        from texlate.export.common import ExportReport  # noqa: PLC0415
        from texlate.xlat.pipeline import ChunkResult  # noqa: PLC0415

        calls: list[dict[str, object]] = []

        def fake(
            src: Path, dst: Path, translator: object, **kw: object
        ) -> ExportReport:
            calls.append({"src": src, "dst": dst, "translator": translator, "kw": kw})
            if raise_exc is not None:
                raise raise_exc
            cb = kw.get("on_result")
            if callable(cb):
                cb(
                    ChunkResult(
                        chunk_id="u1",
                        source="Hello world",
                        translation="你好世界",
                        kind="para",
                        status="ok",
                    )
                )
            Path(dst).write_bytes(b"%FAKE bilingual doc")
            return ExportReport(
                src=src,
                dst=dst,
                format=str(src.suffix).lstrip("."),
                units=1,
                translated=1,
                unchanged=0,
                skipped=0,
                fault=0,
                documents=1,
            )

        monkeypatch.setattr(texlate.export, "export_document", fake)
        return calls

    def _live(self, tmp_path: Path) -> TestClient:
        """worker 起跑的 client（MockTranslator——export 侧实际被 fake 短路）。"""
        from texlate.xlat.pipeline import MockTranslator  # noqa: PLC0415

        app = make_app(
            tmp_path,
            start_worker=True,
            translator_factory=lambda _ctx: MockTranslator(),
        )
        return TestClient(app)

    def test_docx_done(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = self._fake_export(monkeypatch)
        with self._live(tmp_path) as c:
            body = _post(c, "a.docx", _docx())
            snap = wait_terminal(c, body["task_id"])
            assert snap["status"] == "done"
            assert calls
            assert calls[0]["dst"].name.endswith("_bilingual.docx")
            assert snap["artifacts"]["zh_docx"].endswith("/zh.docx")
            r = c.get(f"/api/files/{body['task_id']}/zh.docx")
            assert r.status_code == HTTPStatus.OK
            assert r.content == b"%FAKE bilingual doc"

    def test_epub_done(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = self._fake_export(monkeypatch)
        with self._live(tmp_path) as c:
            body = _post(c, "book", _epub())  # 无 .epub 后缀——kind 兜底命名
            snap = wait_terminal(c, body["task_id"])
            assert snap["status"] == "done"
            assert calls[0]["dst"].name.endswith("_bilingual.epub")
            assert snap["artifacts"]["zh_epub"].endswith("/zh.epub")

    def test_drm_fault(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """DrmError → fault(unsupported_format, 非 retryable)——拒翻不爆炸。"""
        from texlate.export.common import DrmError  # noqa: PLC0415

        self._fake_export(monkeypatch, raise_exc=DrmError("drm protected"))
        with self._live(tmp_path) as c:
            body = _post(c, "a.epub", _epub())
            snap = wait_terminal(c, body["task_id"])
            assert snap["status"] == "fault"
            assert snap["error"]["code"] == "unsupported_format"
            assert snap["error"]["retryable"] is False
