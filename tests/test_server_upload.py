"""POST /api/upload 的 docx/epub 接受面（§2.4：export_document 通路入队）。"""

from __future__ import annotations

import io
import zipfile
from http import HTTPStatus
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from conftest import live_app, make_app, task_events, upload, wait_terminal
from starlette.testclient import TestClient

from texlate.server.settings import SettingsStore


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


def _task_kind(client: TestClient, task_id: str) -> str:
    """tasks 列表反查 kind（建行断言——worker 未跑时仍可读）。"""
    rows = client.get("/api/tasks").json()["tasks"]
    row = next(r for r in rows if r["task_id"] == task_id)
    return str(row["kind"])


class TestUploadDocRoute:
    """docx/epub → 202 + kind 建行 + upload blob 落盘（不再 501）。"""

    def test_docx_202_kind(self, client: TestClient) -> None:
        body = upload(client, name="报告.docx", data=_docx())
        assert body["status"] == "queued"
        assert _task_kind(client, body["task_id"]) == "docx"

    def test_epub_202_kind(self, client: TestClient) -> None:
        body = upload(client, name="book.epub", data=_epub())
        assert body["status"] == "queued"
        assert _task_kind(client, body["task_id"]) == "epub"

    def test_blob_persisted(self, client: TestClient) -> None:
        """upload/{safe_name} 落盘：建行前写 blob，worker _run_doc 以此为源。"""
        payload = _epub()
        body = upload(client, name="my book.epub", data=payload)
        updir = client.app.state.data_dir / "tasks" / body["task_id"] / "upload"
        blobs = list(updir.glob("*"))
        assert len(blobs) == 1
        # 与上传载荷逐字节等——zip mtime 2s 粒度下 _epub() 两调用未必同字节
        assert blobs[0].read_bytes() == payload
        # 文件名 sanitize：空格 → _（与 tex 路同纪律）
        assert blobs[0].name == "my_book.epub"

    def test_fields_accepted(self, client: TestClient) -> None:
        """model/target_lang/options 表单字段与 tex 路同面解析。"""
        body = upload(
            client,
            name="a.docx",
            data=_docx(),
            fields={
                "model": "mock-m",
                "target_lang": "zh-TW",
                "options": '{"prefer":"fresh"}',
            },
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

    def test_pdf_no_babeldoc_501(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """501 闸与宿主机 babeldoc 装没装无关——探测钉成未装。"""
        monkeypatch.setattr("texlate.server.routers.upload.find_tool", lambda _n: None)
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

        app = live_app(tmp_path, lambda _ctx: MockTranslator())
        return TestClient(app)

    def test_docx_done(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = self._fake_export(monkeypatch)
        with self._live(tmp_path) as c:
            body = upload(c, name="a.docx", data=_docx())
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
            body = upload(c, name="book", data=_epub())  # 无 .epub 后缀——kind 兜底命名
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
            body = upload(c, name="a.epub", data=_epub())
            snap = wait_terminal(c, body["task_id"])
            assert snap["status"] == "fault"
            assert snap["error"]["code"] == "unsupported_format"
            assert snap["error"]["retryable"] is False

    def test_glossary_kwarg_unconditional(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``_run_doc`` 无条件 ``glossary=_make_glossary(ctx)``——无 options 也

        是 ``Glossary`` 实例（内建 default 层），不是 None。
        """
        from texlate.xlat.glossary import Glossary  # noqa: PLC0415

        calls = self._fake_export(monkeypatch)
        with self._live(tmp_path) as c:
            body = upload(c, name="a.docx", data=_docx())
            snap = wait_terminal(c, body["task_id"])
            assert snap["status"] == "done"
        g = calls[0]["kw"]["glossary"]
        assert isinstance(g, Glossary)
        assert any(e.source == "default" for e in g.terms.values())

    def test_glossary_reaches_prompt_real_path(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """Prompt 直证：``options.glossary`` 经 ``glossary_dir`` confine →

        ``_make_glossary`` → ``export_document`` → system 尾块术语行。
        """
        from docx import Document  # noqa: PLC0415

        from texlate.xlat.pipeline import MockTranslator  # noqa: PLC0415

        gdir = tmp_path / "gdir"
        gdir.mkdir()
        (gdir / "g.yaml").write_text("transformer: 变形金刚\n", encoding="utf-8")
        _settings(tmp_path / "data", glossary_dir=str(gdir))
        buf = io.BytesIO()
        doc = Document()
        doc.add_paragraph("The transformer architecture relies on attention.")
        doc.save(buf)
        mock = MockTranslator()
        app = live_app(tmp_path, lambda _ctx: mock)
        with TestClient(app) as c:
            body = upload(
                c,
                name="a.docx",
                data=buf.getvalue(),
                fields={"options": '{"glossary":"g.yaml"}'},
            )
            snap = wait_terminal(c, body["task_id"])
            assert snap["status"] == "done"
        systems = [str(call["system"]) for call in mock.calls]
        assert systems
        assert any("- transformer: 变形金刚" in s for s in systems)

    def test_on_result_counters_chunk_event_progress(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """on_result 回弹面：counters/tokens 落库 + chunk 事件 + progress 离 25。"""
        self._fake_export(monkeypatch)
        with self._live(tmp_path) as c:
            store = c.app.state.store
            seen: list[int] = []
            orig = store.update_fields

            def _spy(tid: str, **fields: object) -> None:
                if "progress" in fields:
                    seen.append(int(fields["progress"]))  # type: ignore[arg-type]
                orig(tid, **fields)

            monkeypatch.setattr(store, "update_fields", _spy)
            body = upload(c, name="a.docx", data=_docx())
            snap = wait_terminal(c, body["task_id"])
            assert snap["status"] == "done"
            assert snap["counters"]["done"] == 1
            # (len("Hello world") + len("你好世界")) // 4 = 3——无真账时 est 持久化
            assert snap["counters"]["tokens"] == 3  # noqa: PLR2004 -- 上式定值
            assert "usage" not in snap  # MockTranslator 无 client → 不落 usage 行
            chunks = [
                e["data"]
                for e in task_events(c, body["task_id"])
                if e["type"] == "chunk"
            ]
            assert chunks == [
                {
                    "done": 1,
                    "total": 0,
                    "cached": 0,
                    "failed": 0,
                    "items": [{"seq": 1, "status": "ok"}],
                }
            ]
            # translating 区间 (25,85)：逐 unit 自增 25+1=26，不再钉 25
            assert seen == [26]

    def test_mock_fallback_warns(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """无 key 且未显式 mock → ``mock_translator`` warning 事件留痕。"""
        self._fake_export(monkeypatch)
        app = make_app(tmp_path, start_worker=True)  # 无 translator_factory
        with TestClient(app) as c:
            body = upload(c, name="a.docx", data=_docx())
            snap = wait_terminal(c, body["task_id"])
            assert snap["status"] == "done"
            warns = [
                e["data"]["code"]
                for e in task_events(c, body["task_id"])
                if e["type"] == "warning"
            ]
            assert warns == ["mock_translator"]

    def test_explicit_mock_env_no_warning(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``TEXLATE_TRANSLATOR=mock`` 是显式选择——不打 mock_translator 警告。"""
        monkeypatch.setenv("TEXLATE_TRANSLATOR", "mock")
        self._fake_export(monkeypatch)
        app = make_app(tmp_path, start_worker=True)
        with TestClient(app) as c:
            body = upload(c, name="a.docx", data=_docx())
            snap = wait_terminal(c, body["task_id"])
            assert snap["status"] == "done"
            warns = [
                e["data"]["code"]
                for e in task_events(c, body["task_id"])
                if e["type"] == "warning"
            ]
            assert "mock_translator" not in warns
