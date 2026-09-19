"""app.py 端点覆盖补洞：错误码路径 / 边界参数 / 状态机守卫 / 租户遮蔽。

对照 ``bench/results/api-cover-2026-09-16/report.md`` 的端点×覆盖矩阵——
本文件只补既有 test_server_* 未覆盖的面（不重测 happy path）。
历史 xfail 钉（400/500 分裂等）已全部修复拆钉，现存断言即防回归常态。
"""

from __future__ import annotations

import io
import json
import zipfile
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from conftest import MINI_TEX, make_app, make_targz, mk_api_task, upload_tex
from starlette.testclient import TestClient

import texlate.server.app as app_mod
from texlate.server.settings import SettingsStore
from texlate.server.store import new_task_id

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import ClassVar

ARXIV = "2401.00021"


@pytest.fixture
def raw_client(
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,  # noqa: ARG001 -- fixture 副作用
) -> Iterator[TestClient]:
    """``raise_server_exceptions=False``——探测 5xx 错误面专用。"""
    with TestClient(make_app(tmp_path), raise_server_exceptions=False) as c:
        yield c


def _docx() -> bytes:
    """最小 docx 魔数载荷。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<doc/>")
    return buf.getvalue()


def _epub() -> bytes:
    """最小 epub 魔数载荷（mimetype 段即判定依据）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("OEBPS/content.opf", "<package/>")
    return buf.getvalue()


def _reg_file(
    client: TestClient, tid: str, kind: str, name: str, blob: bytes = b"%PDF-1.4 fake"
) -> dict:
    """tasks/{tid}/{name} 落盘 + files 表登记 → rec（含 sha256）。"""
    tdir = client.app.state.data_dir / "tasks" / tid
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / name).write_bytes(blob)
    return client.portal.call(
        partial(client.app.state.store.put_file, tid, kind, name, data_dir=tdir)
    )


def _force(client: TestClient, tid: str, status: str) -> None:
    """store.transition force 通道——把任务钉到指定终态。"""
    client.portal.call(
        partial(client.app.state.store.transition, tid, status, force=True)
    )


def _chunks(client: TestClient, tid: str) -> int:
    store = client.app.state.store
    return client.portal.call(
        partial(
            lambda: store.conn.execute(
                "SELECT COUNT(*) AS c FROM chunks WHERE task_id = ?", (tid,)
            ).fetchone()["c"]
        )
    )


def _insert_chunk(client: TestClient, tid: str) -> None:
    client.portal.call(
        partial(
            client.app.state.store.insert_chunks,
            tid,
            [
                {
                    "seq": 0,
                    "chunk_id": "c0",
                    "src_file": "main.tex",
                    "byte_start": 0,
                    "byte_end": 5,
                    "kind": "text",
                    "src_text": "hello",
                }
            ],
        )
    )


def _mk_kind_task(client: TestClient, kind: str, arxiv_id: str | None = ARXIV) -> str:
    """store 直建行（不跑 translate 端点/worker）——任意 kind 的任务 fixture。"""
    tid = new_task_id()
    client.portal.call(
        partial(
            client.app.state.store.create_task,
            task_id=tid,
            kind=kind,
            target_lang="zh-CN",
            model="m",
            arxiv_id=arxiv_id,
        )
    )
    return tid


# ------------------------------------------------------------ §2.1 translate


class TestTranslateEdges:
    def test_bad_json_400(self, client: TestClient) -> None:
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            content=b"{not json",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert "bad json" in r.json()["detail"]

    def test_non_dict_body_400(self, client: TestClient) -> None:
        """非 dict JSON body → 400（静默归 {} 会让 PUT settings 200 无操作）。"""
        r = client.post(f"/api/arxiv/{ARXIV}/translate", json=[1, 2])
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "invalid_request"

    def test_options_str_400(self, raw_client: TestClient) -> None:
        r = raw_client.post(f"/api/arxiv/{ARXIV}/translate", json={"options": "xx"})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_options_int_400(self, raw_client: TestClient) -> None:
        r = raw_client.post(f"/api/arxiv/{ARXIV}/translate", json={"options": 5})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_options_pairs_lenient(self, client: TestClient) -> None:
        """``options`` 为 KV 对列表时 dict() 可转——宽松接收，不 500。"""
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate", json={"options": [["prefer", "fresh"]]}
        )
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_model_too_long_400(self, client: TestClient) -> None:
        r = client.post(f"/api/arxiv/{ARXIV}/translate", json={"model": "x" * 201})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_model_blank_400(self, client: TestClient) -> None:
        """纯空白 model strip 后为空 → 400。"""
        r = client.post(f"/api/arxiv/{ARXIV}/translate", json={"model": "   "})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_model_empty_falls_back(self, client: TestClient) -> None:
        """``model: ""`` 是 falsy → 回落 settings/auth 默认，不报错。"""
        r = client.post(f"/api/arxiv/{ARXIV}/translate", json={"model": ""})
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_bad_header_base_url_no_body_model_400(
        self, raw_client: TestClient
    ) -> None:
        """body 不带 model 时 _auth 在 try 内 → ValueError 收敛成 400。

        （原「400/500 分裂」xfail 对照组——分裂已修，本断言为留存回归。）
        """
        r = raw_client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={},
            headers={"X-Texlate-Base-Url": "ftp://x"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_bad_header_base_url_with_body_model_400(
        self, raw_client: TestClient
    ) -> None:
        r = raw_client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={"model": "m"},
            headers={"X-Texlate-Base-Url": "ftp://x"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_idempotency_in_options(self, client: TestClient) -> None:
        """options.idempotency_key 与 header 同效（_create_and_enqueue 双通道）。"""
        kw = {"options": {"idempotency_key": "body-idem-1"}}
        r1 = client.post(f"/api/arxiv/{ARXIV}/translate", json=kw)
        r2 = client.post(f"/api/arxiv/{ARXIV}/translate", json=kw)
        assert r1.status_code == HTTPStatus.ACCEPTED
        assert r2.status_code == HTTPStatus.ACCEPTED
        assert r2.json()["task_id"] == r1.json()["task_id"]
        assert r2.json()["cache"] == "idempotent"

    def test_glossary_field(self, client: TestClient) -> None:
        """body.glossary 落 options_json（worker glossary confine 的入口）。"""
        tid = mk_api_task(client, ARXIV, glossary="terms.yaml")
        row = client.portal.call(partial(client.app.state.store.get, tid))
        assert json.loads(row["options_json"])["glossary"] == "terms.yaml"

    def test_idempotent_replay_skips_quota(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """配额满后 idempotent 命中不建行 → 仍 202（_check_quota 在 dedup 后）。"""
        data_root = tmp_path / "data"
        data_root.mkdir(parents=True)
        SettingsStore(data_root).save({"quota_max_tasks": 1})
        with TestClient(make_app(tmp_path)) as c:
            hdr = {"Idempotency-Key": "q1"}
            assert (
                c.post(
                    f"/api/arxiv/{ARXIV}/translate", json={}, headers=hdr
                ).status_code
                == HTTPStatus.ACCEPTED
            )
            r = c.post(f"/api/arxiv/{ARXIV}/translate", json={}, headers=hdr)
            assert r.status_code == HTTPStatus.ACCEPTED
            assert r.json()["cache"] == "idempotent"
            # 无 idem 的新任务 → 429
            r = c.post("/api/arxiv/2401.00022/translate", json={})
            assert r.status_code == HTTPStatus.TOO_MANY_REQUESTS


# ------------------------------------------------------------ §2.2 task get


class TestTaskGetEdges:
    def test_last_event_id_garbage_replays_all(self, client: TestClient) -> None:
        """Last-Event-ID 非整数 → last_id=0 → 全量重放（不 4xx）。"""
        tid = mk_api_task(client, ARXIV)
        bus = client.app.state.bus
        _force(client, tid, "done")  # done 帧只对真终态任务终结重放
        client.portal.call(partial(bus.publish, tid, "stage", {"stage": "parsing"}))
        client.portal.call(partial(bus.publish, tid, "done", {"status": "done"}))
        with client.stream(
            "GET",
            f"/api/task/{tid}",
            headers={"Accept": "text/event-stream", "Last-Event-ID": "abc"},
        ) as r:
            events = [ln[7:] for ln in r.iter_lines() if ln.startswith("event:")]
        assert events == ["snapshot", "stage", "done"]

    def test_snapshot_artifacts_url_kind(self, client: TestClient) -> None:
        """snapshot.artifacts 键是 db kind、URL 用 KIND_URL 映射（md_zip→md）。"""
        tid = mk_api_task(client, ARXIV)
        _reg_file(client, tid, "md_zip", "md.zip", b"PKfake")
        snap = client.get(f"/api/task/{tid}").json()
        assert snap["artifacts"]["md_zip"].endswith(f"/api/files/{tid}/md")

    def test_error_responses_no_store(self, client: TestClient) -> None:
        """no-store 横切对错误响应同样生效。"""
        r = client.get("/api/task/t_0000000000000000")
        assert r.status_code == HTTPStatus.NOT_FOUND
        assert r.headers["Cache-Control"] == "no-store"

    def test_bad_header_base_url_400(self, raw_client: TestClient) -> None:
        tid = mk_api_task(raw_client, ARXIV)
        r = raw_client.get(
            f"/api/task/{tid}", headers={"X-Texlate-Base-Url": "ftp://x"}
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_bad_header_model_400(self, raw_client: TestClient) -> None:
        tid = mk_api_task(raw_client, ARXIV)
        r = raw_client.get(f"/api/task/{tid}", headers={"X-Texlate-Model": "x" * 300})
        assert r.status_code == HTTPStatus.BAD_REQUEST


# ------------------------------------------------------------ §2.3 files


class TestFilesList:
    def test_shape(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        rec = _reg_file(client, tid, "zh_pdf", "zh.pdf")
        r = client.get(f"/api/files/{tid}")
        assert r.status_code == HTTPStatus.OK
        art = r.json()["artifacts"]["zh_pdf"]
        assert art["bytes"] == len(b"%PDF-1.4 fake")
        assert art["sha256"] == rec["sha256"]
        assert art["url"].endswith(f"/api/files/{tid}/zh.pdf")
        assert "created_at" in art


class TestFileGet:
    def test_version_match_200(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        rec = _reg_file(client, tid, "zh_pdf", "zh.pdf")
        r = client.get(f"/api/files/{tid}/zh.pdf", params={"version": rec["sha256"]})
        assert r.status_code == HTTPStatus.OK
        assert r.content == b"%PDF-1.4 fake"

    def test_version_mismatch_409(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        _reg_file(client, tid, "zh_pdf", "zh.pdf")
        r = client.get(f"/api/files/{tid}/zh.pdf", params={"version": "deadbeef"})
        assert r.status_code == HTTPStatus.CONFLICT
        assert r.json()["code"] == "version_mismatch"

    def test_record_without_disk_file_404(self, client: TestClient) -> None:
        """files 行在、磁盘文件不在 → 404 artifact file missing。"""
        tid = mk_api_task(client, ARXIV)
        client.portal.call(
            partial(client.app.state.store.put_file, tid, "zh_pdf", "zh.pdf")
        )
        r = client.get(f"/api/files/{tid}/zh.pdf")
        assert r.status_code == HTTPStatus.NOT_FOUND
        assert "missing" in r.json()["detail"]

    def test_db_path_escape_confined_404(self, client: TestClient) -> None:
        """files.path 越出 tasks/{tid}/ → 404（resolve+is_relative_to 闸）。"""
        tid = mk_api_task(client, ARXIV)
        root = client.app.state.data_dir
        (root / "evil.pdf").write_bytes(b"%PDF-1.4 outside")
        client.portal.call(
            partial(client.app.state.store.put_file, tid, "zh_pdf", "../../evil.pdf")
        )
        r = client.get(f"/api/files/{tid}/zh.pdf")
        assert r.status_code == HTTPStatus.NOT_FOUND

    def test_download_filename_upload(self, client: TestClient) -> None:
        """upload 任务无 arxiv_id → Content-Disposition 用 task_id 做 stem。"""
        tid = upload_tex(client)["task_id"]
        _reg_file(client, tid, "zh_pdf", "zh.pdf")
        r = client.get(f"/api/files/{tid}/zh.pdf", params={"download": 1})
        assert f'filename="texlate-{tid}-zh.pdf"' in r.headers["Content-Disposition"]

    def test_download_filename_arxiv(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        _reg_file(client, tid, "zh_pdf", "zh.pdf")
        r = client.get(f"/api/files/{tid}/zh.pdf", params={"download": 1})
        assert f'filename="texlate-{ARXIV}-zh.pdf"' in r.headers["Content-Disposition"]

    def test_media_types(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        _reg_file(client, tid, "compile_log", "compile.log", b"log line\n")
        r = client.get(f"/api/files/{tid}/compile.log")
        assert r.status_code == HTTPStatus.OK
        assert r.headers["content-type"].startswith("text/plain")
        _reg_file(client, tid, "dual_json", "dual.json", b"{}")
        r = client.get(f"/api/files/{tid}/dual.json")
        assert r.headers["content-type"].startswith("application/json")

    def test_html_media_csp_sandbox(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """text/html 产物 → ``Content-Security-Policy: sandbox``（直接导航时
        文档内脚本全灭的同源兜底闸）；非 html 产物不带头。

        ``URL_KIND`` 的 ``en.html``/``zh.html`` 反查项由 worker 侧
        ``KIND_URL`` 注册（并行 lane）——setitem 同键值 shim，落地后等价。
        """
        monkeypatch.setitem(app_mod.URL_KIND, "zh.html", "zh_html")
        tid = _mk_kind_task(client, "arxiv_html")
        _reg_file(client, tid, "zh_html", "zh.html", b"<html/>")
        r = client.get(f"/api/files/{tid}/zh.html")
        assert r.status_code == HTTPStatus.OK
        assert r.headers["content-type"].startswith("text/html")
        assert r.headers["content-security-policy"] == "sandbox"
        _reg_file(client, tid, "dual_json", "dual.json", b"{}")
        r = client.get(f"/api/files/{tid}/dual.json")
        assert "content-security-policy" not in r.headers

    def test_src_tar_media_arxiv_gzip(self, client: TestClient) -> None:
        """arxiv 任务的 src.tar 是 e-print tar.gz → application/gzip。"""
        tid = mk_api_task(client, ARXIV)
        _reg_file(client, tid, "src_tar", "src.tar", make_targz({"a.tex": "x"}))
        r = client.get(f"/api/files/{tid}/src.tar")
        assert r.headers["content-type"].startswith("application/gzip")

    def test_src_tar_media_upload_kinds(self, client: TestClient) -> None:
        """上传任务 src.tar = 原始字节回读——mime 按任务 kind/魔数给真值。"""
        r = client.post(
            "/api/upload",
            files={"file": ("a.docx", _docx(), "application/octet-stream")},
        )
        did = r.json()["task_id"]
        _reg_file(client, did, "src_tar", "upload/a.docx", _docx())
        r = client.get(f"/api/files/{did}/src.tar")
        assert r.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument"
        )

        r = client.post(
            "/api/upload",
            files={"file": ("a.epub", _epub(), "application/octet-stream")},
        )
        eid = r.json()["task_id"]
        _reg_file(client, eid, "src_tar", "upload/a.epub", _epub())
        r = client.get(f"/api/files/{eid}/src.tar")
        assert r.headers["content-type"].startswith("application/epub+zip")

    def test_src_tar_media_upload_tex_sniffed(self, client: TestClient) -> None:
        """upload_tex 的 blob 按魔数：gzip→gzip、裸 .tex→octet-stream。"""
        tid = upload_tex(client)["task_id"]
        _reg_file(client, tid, "src_tar", "upload/p.tar.gz", make_targz({"a.tex": "x"}))
        r = client.get(f"/api/files/{tid}/src.tar")
        assert r.headers["content-type"].startswith("application/gzip")
        _reg_file(client, tid, "src_tar", "upload/main.tex", MINI_TEX.encode())
        r = client.get(f"/api/files/{tid}/src.tar")
        assert r.headers["content-type"].startswith("application/octet-stream")

    def test_download_filename_old_arxiv_sanitized(self, client: TestClient) -> None:
        """旧式 arxiv id 含 '/'（hep-th/9901001）——filename 消毒防畸形 header。"""
        tid = mk_api_task(client, "hep-th/9901001")
        _reg_file(client, tid, "zh_pdf", "zh.pdf")
        r = client.get(f"/api/files/{tid}/zh.pdf", params={"download": 1})
        cd = r.headers["Content-Disposition"]
        assert 'filename="texlate-hep-th_9901001-zh.pdf"' in cd
        assert "/" not in cd.split("filename=")[1]

    def test_download_bad_int_400(self, client: TestClient) -> None:
        """?download=abc → RequestValidationError → 400 invalid_request。"""
        tid = mk_api_task(client, ARXIV)
        r = client.get(f"/api/files/{tid}/zh.pdf", params={"download": "abc"})
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "invalid_request"


# ------------------------------------------------------------ §2.4 upload


class TestUploadEdges:
    def test_empty_file_400(self, client: TestClient) -> None:
        r = client.post(
            "/api/upload",
            files={"file": ("a.tex", b"", "application/octet-stream")},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert "empty" in r.json()["detail"]

    def test_file_text_field_400(self, client: TestClient) -> None:
        """file 字段给文本而非文件 → 400 file required。"""
        r = client.post("/api/upload", data={"file": "just text"})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_options_bad_json_400(self, client: TestClient) -> None:
        r = client.post(
            "/api/upload",
            files={"file": ("main.tex", MINI_TEX.encode(), "text/plain")},
            data={"options": "{broken"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_options_non_dict_lenient(self, client: TestClient) -> None:
        """options 字段是合法 JSON 但非 dict → 按空 options 收（与 tex 路同）。"""
        r = client.post(
            "/api/upload",
            files={"file": ("main.tex", MINI_TEX.encode(), "text/plain")},
            data={"options": "[1, 2]"},
        )
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_model_too_long_400(self, client: TestClient) -> None:
        r = client.post(
            "/api/upload",
            files={"file": ("main.tex", MINI_TEX.encode(), "text/plain")},
            data={"model": "x" * 201},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_bad_target_lang_400(self, client: TestClient) -> None:
        r = client.post(
            "/api/upload",
            files={"file": ("main.tex", MINI_TEX.encode(), "text/plain")},
            data={"target_lang": "fr"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_content_length_precheck_413(self, client: TestClient) -> None:
        """声明 Content-Length 超 CAP+overhead → 不读体直接 413。"""
        r = client.post(
            "/api/upload",
            content=b"x",
            headers={
                "Content-Type": "multipart/form-data; boundary=x",
                "Content-Length": str(90 * 1024 * 1024),
            },
        )
        assert r.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert r.json()["code"] == "upload_too_large"

    @pytest.mark.parametrize("path", ["/api/upload", "/api/share/import"])
    def test_chunked_no_content_length_oversize_413(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
    ) -> None:
        """无 Content-Length（chunked 流式体）绕预检——文件字段有界读，
        累计超 CAP 同语义 413，全量不进 RAM。"""
        monkeypatch.setattr("texlate.server.http.UPLOAD_CAP", 16)
        body = (
            b"--X\r\n"
            b'Content-Disposition: form-data; name="file"; filename="big.bin"\r\n'
            b"Content-Type: application/octet-stream\r\n\r\n"
            + b"y" * 256
            + b"\r\n--X--\r\n"
        )
        r = client.post(
            path,
            content=iter([body]),  # httpx 迭代体 → chunked，无 Content-Length
            headers={"Content-Type": "multipart/form-data; boundary=X"},
        )
        assert r.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert r.json()["code"] == "upload_too_large"

    def test_chunked_small_upload_accepted(self, client: TestClient) -> None:
        """chunked 限额内小体不受影响——multipart 解析与 CL 路径同语义。"""
        body = (
            b"--X\r\n"
            b'Content-Disposition: form-data; name="file"; filename="main.tex"\r\n'
            b"Content-Type: text/plain\r\n\r\n" + MINI_TEX.encode() + b"\r\n--X--\r\n"
        )
        r = client.post(
            "/api/upload",
            content=iter([body]),
            headers={"Content-Type": "multipart/form-data; boundary=X"},
        )
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_chunked_text_field_bounded_413(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """chunked 体 + 巨型 str 字段：receive 字节闸解析中途 413——str 字段
        不再随 ``request.form()`` 无界进 RAM（修前此例体全吞后按缺 file 400）。
        """
        monkeypatch.setattr("texlate.server.http.UPLOAD_CAP", 16)
        body = (
            b"--X\r\n"
            b'Content-Disposition: form-data; name="options"\r\n\r\n'
            + b"z" * 80000
            + b"\r\n--X--\r\n"
        )
        r = client.post(
            "/api/upload",
            content=iter([body]),
            headers={"Content-Type": "multipart/form-data; boundary=X"},
        )
        assert r.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert r.json()["code"] == "upload_too_large"

    def test_chunked_json_body_bounded_413(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``_cap_request_body`` 的 JSON 闸：无 CL 的 JSON 体超 ``_JSON_BODY_CAP``
        → 413 ``body_too_large``（修前 ``request.body()`` 无界读进 RAM 后正常 202；
        JSON 端点与 upload 的 ``UPLOAD_CAP`` 已分闸）。"""
        monkeypatch.setattr("texlate.server.http._JSON_BODY_CAP", 16)
        big = b'{"options": {"k": "' + b"v" * 80000 + b'"}}'
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            content=iter([big]),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert r.json()["code"] == "body_too_large"

    def test_filename_traversal_sanitized(self, client: TestClient) -> None:
        """``../../etc/evil.tex`` → ``Path().name`` 剥目录 + 字符白名单。"""
        r = client.post(
            "/api/upload",
            files={"file": ("../../etc/evil.tex", MINI_TEX.encode(), "text/plain")},
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        tid = r.json()["task_id"]
        updir = client.app.state.data_dir / "tasks" / tid / "upload"
        assert (updir / "evil.tex").is_file()
        assert len(list(updir.iterdir())) == 1

    def test_idempotent_no_orphan_dir(self, client: TestClient) -> None:
        hdr = {"Idempotency-Key": "up-idem-1"}
        files = {"file": ("main.tex", MINI_TEX.encode(), "text/plain")}
        r1 = client.post("/api/upload", files=files, headers=hdr)
        r2 = client.post("/api/upload", files=files, headers=hdr)
        assert r2.status_code == HTTPStatus.ACCEPTED
        assert r2.json()["task_id"] == r1.json()["task_id"]
        assert r2.json()["cache"] == "idempotent"
        dirs = list((client.app.state.data_dir / "tasks").iterdir())
        assert len(dirs) == 1  # 重放不该多写一个孤儿任务目录

    def test_quota_reject_no_orphan_dir(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """建行失败（quota 429）也要收掉已落盘的 tasks/{new}/upload 现场（B4）。"""
        data_root = tmp_path / "data"
        data_root.mkdir(parents=True)
        SettingsStore(data_root).save({"quota_max_tasks": 1})
        with TestClient(make_app(tmp_path)) as c:
            assert (
                c.post(f"/api/arxiv/{ARXIV}/translate", json={}).status_code
                == HTTPStatus.ACCEPTED
            )
            r = c.post(
                "/api/upload",
                files={"file": ("main.tex", MINI_TEX.encode(), "text/plain")},
            )
            assert r.status_code == HTTPStatus.TOO_MANY_REQUESTS
            tasks_dir = data_root / "tasks"
            assert not tasks_dir.exists() or list(tasks_dir.iterdir()) == []

    def test_docx_no_reader_url(self, client: TestClient) -> None:
        """docx 管线不产 dual.json → 202 不发 reader_url（空诺闸）。"""
        r = client.post(
            "/api/upload",
            files={"file": ("a.docx", _docx(), "application/octet-stream")},
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        body = r.json()
        row = client.portal.call(partial(client.app.state.store.get, body["task_id"]))
        assert row["kind"] == "docx"
        assert "reader_url" not in body
        assert "events_url" in body

    def test_epub_no_reader_url(self, client: TestClient) -> None:
        r = client.post(
            "/api/upload",
            files={"file": ("a.epub", _epub(), "application/octet-stream")},
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        assert "reader_url" not in r.json()

    def test_tex_upload_has_reader_url(self, client: TestClient) -> None:
        """upload_tex 会产 dual.json → reader_url 照发。"""
        body = upload_tex(client)
        assert body["reader_url"].endswith("/reader")


# ------------------------------------------------------------ §2.5 tasks list


class TestTasksListEdges:
    def test_status_bogus_400(self, client: TestClient) -> None:
        """未识别 status 值 → 400 枚举校验——静默返空会让调用方分不清
        「无匹配」与「参数打错」。"""
        mk_api_task(client, ARXIV)
        r = client.get("/api/tasks", params={"status": "bogus'"})
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "invalid_request"

    def test_error_field_shape(self, client: TestClient) -> None:
        """error_json 反序列化成 dict 进列表项；counters 五键齐。"""
        tid = mk_api_task(client, ARXIV)
        client.portal.call(
            partial(
                client.app.state.store.transition,
                tid,
                "fault",
                force=True,
                error={"code": "compile", "message": "x", "retryable": True},
            )
        )
        rows = client.get("/api/tasks", params={"status": "fault"}).json()["tasks"]
        assert rows[0]["task_id"] == tid
        assert rows[0]["error"]["code"] == "compile"
        assert {"total", "done", "cached", "failed", "tokens"} == set(
            rows[0]["counters"]
        )


# ------------------------------------------------------------ cancel / retry


class TestCancelEdges:
    def test_cancel_404(self, client: TestClient) -> None:
        assert client.post("/api/task/t_0000000000000000/cancel").status_code == (
            HTTPStatus.NOT_FOUND
        )
        assert client.post("/api/task/garbage/cancel").status_code == (
            HTTPStatus.NOT_FOUND
        )

    def test_cancel_publishes_done_event(self, client: TestClient) -> None:
        """cancel 同步补 done{cancelled} 事件——SSE 订阅者正常收尾。"""
        tid = mk_api_task(client, ARXIV)
        client.post(f"/api/task/{tid}/cancel")
        evs = client.portal.call(partial(client.app.state.store.events_since, tid, 0))
        done = [e for e in evs if e["type"] == "done"]
        assert done
        assert done[-1]["data"]["status"] == "cancelled"


class TestRetryEdges:
    def test_retry_404(self, client: TestClient) -> None:
        assert client.post(
            "/api/task/t_0000000000000000/retry", json={}
        ).status_code == (HTTPStatus.NOT_FOUND)

    def test_retry_done_409(self, client: TestClient) -> None:
        """done ∉ RETRYABLE_FROM → 409 invalid_transition。"""
        tid = mk_api_task(client, ARXIV)
        _force(client, tid, "done")
        r = client.post(f"/api/task/{tid}/retry", json={})
        assert r.status_code == HTTPStatus.CONFLICT
        assert r.json()["code"] == "invalid_transition"

    def test_retry_fault_202(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        _force(client, tid, "fault")
        r = client.post(f"/api/task/{tid}/retry", json={})
        assert r.status_code == HTTPStatus.ACCEPTED
        assert client.get(f"/api/task/{tid}").json()["status"] == "queued"

    def test_retry_bad_json_400(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        client.post(f"/api/task/{tid}/cancel")
        r = client.post(
            f"/api/task/{tid}/retry",
            content=b"{broken",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert client.get(f"/api/task/{tid}").json()["status"] == "cancelled"

    def test_retry_options_merge(self, client: TestClient) -> None:
        """body.options 深并入 options_json（不覆盖未提键）。"""
        tid = mk_api_task(client, ARXIV, options={"glossary": "a.yaml"})
        client.post(f"/api/task/{tid}/cancel")
        r = client.post(
            f"/api/task/{tid}/retry", json={"options": {"retry_model": "alt"}}
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        row = client.portal.call(partial(client.app.state.store.get, tid))
        opts = json.loads(row["options_json"])
        assert opts["glossary"] == "a.yaml"
        assert opts["retry_model"] == "alt"

    def test_retry_main_switch_wipes(
        self,
        client: TestClient,
        tmp_path: Path,  # noqa: ARG002
    ) -> None:
        """换主文件 retry → chunks 清 + base/zh/build-* 目录删（src 保留）。"""
        tid = mk_api_task(client, ARXIV)
        tdir = client.app.state.data_dir / "tasks" / tid
        for d in ("base", "zh", "build-en", "build-zh"):
            (tdir / d).mkdir(parents=True)
        _insert_chunk(client, tid)
        client.portal.call(
            partial(client.app.state.store.update_fields, tid, main_tex="main.tex")
        )
        client.post(f"/api/task/{tid}/cancel")
        r = client.post(f"/api/task/{tid}/retry", json={"main": "other.tex"})
        assert r.status_code == HTTPStatus.ACCEPTED
        assert _chunks(client, tid) == 0
        for d in ("base", "zh", "build-en", "build-zh"):
            assert not (tdir / d).exists()
        row = client.portal.call(partial(client.app.state.store.get, tid))
        assert json.loads(row["options_json"])["main"] == "other.tex"

    def test_retry_same_main_preserves(self, client: TestClient) -> None:
        """main 未变 → chunks 不清（断点续跑）。"""
        tid = mk_api_task(client, ARXIV)
        _insert_chunk(client, tid)
        client.portal.call(
            partial(client.app.state.store.update_fields, tid, main_tex="main.tex")
        )
        client.post(f"/api/task/{tid}/cancel")
        r = client.post(f"/api/task/{tid}/retry", json={"main": "main.tex"})
        assert r.status_code == HTTPStatus.ACCEPTED
        assert _chunks(client, tid) == 1

    def test_retry_terminal_no_side_effects(self, raw_client: TestClient) -> None:
        """done 任务 retry 应纯 409——chunks/options/目录一概不动。"""
        tid = mk_api_task(raw_client, ARXIV)
        tdir = raw_client.app.state.data_dir / "tasks" / tid
        (tdir / "base").mkdir(parents=True)
        _insert_chunk(raw_client, tid)
        raw_client.portal.call(
            partial(raw_client.app.state.store.update_fields, tid, main_tex="main.tex")
        )
        _force(raw_client, tid, "done")
        before = raw_client.portal.call(partial(raw_client.app.state.store.get, tid))[
            "options_json"
        ]
        r = raw_client.post(
            f"/api/task/{tid}/retry",
            json={"main": "other.tex", "options": {"zap": "1"}},
        )
        assert r.status_code == HTTPStatus.CONFLICT
        assert _chunks(raw_client, tid) == 1
        assert (tdir / "base").exists()
        after = raw_client.portal.call(partial(raw_client.app.state.store.get, tid))[
            "options_json"
        ]
        assert after == before

    def test_retry_unknown_keys_400(self, client: TestClient) -> None:
        """body.model/target_lang 曾是静默丢弃（空诺）——白名单外键一律 400。"""
        tid = mk_api_task(client, ARXIV)
        client.post(f"/api/task/{tid}/cancel")
        r = client.post(f"/api/task/{tid}/retry", json={"model": "other-m"})
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert "model" in r.json()["detail"]
        assert client.get(f"/api/task/{tid}").json()["status"] == "cancelled"
        r = client.post(f"/api/task/{tid}/retry", json={"target_lang": "en"})
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert client.get(f"/api/task/{tid}").json()["status"] == "cancelled"
        # options 非 object 也是静默丢弃——同族闸
        r = client.post(f"/api/task/{tid}/retry", json={"options": "x"})
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert client.get(f"/api/task/{tid}").json()["status"] == "cancelled"

    def test_retry_known_keys_still_202(self, client: TestClient) -> None:
        """main/options 白名单内——不误伤。"""
        tid = mk_api_task(client, ARXIV)
        client.post(f"/api/task/{tid}/cancel")
        r = client.post(
            f"/api/task/{tid}/retry",
            json={"main": "main.tex", "options": {"k": "v"}},
        )
        assert r.status_code == HTTPStatus.ACCEPTED


# ------------------------------------------------------------ reader


def _write_dual(client: TestClient, tid: str, doc: dict) -> Path:
    """tasks/{tid}/dual.json 直写 + files 登记（不跑 worker 的 reader 侧 fixture）。

    reader_get 以 ``dual_json`` 登记行为准——只落盘不登记即孤儿件 404。
    """
    tdir = client.app.state.data_dir / "tasks" / tid
    tdir.mkdir(parents=True, exist_ok=True)
    p = tdir / "dual.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    client.portal.call(
        partial(
            client.app.state.store.put_file,
            tid,
            "dual_json",
            "dual.json",
            data_dir=tdir,
        )
    )
    return p


class TestReaderGet:
    def test_corrupted_dual_500(self, client: TestClient) -> None:
        """已登记但磁盘件损坏 → 解析 500（未登记孤儿件 404 由 test_server_persist 钉）。"""
        tid = mk_api_task(client, ARXIV)
        _reg_file(client, tid, "dual_json", "dual.json", b"{{{not json")
        r = client.get(f"/api/task/{tid}/reader")
        assert r.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert r.json()["code"] == "internal"

    def test_dual_non_dict_500(self, client: TestClient) -> None:
        """dual.json 是合法 JSON 但顶层非 object → 结构化 500（非裸 AttributeError）。"""
        tid = mk_api_task(client, ARXIV)
        _reg_file(client, tid, "dual_json", "dual.json", b'["not", "a", "dict"]')
        r = client.get(f"/api/task/{tid}/reader")
        assert r.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert r.json()["code"] == "internal"

    def test_documents_non_dict_500(self, client: TestClient) -> None:
        """documents 段非 dict 同属损坏——不静默吞成空 documents。"""
        tid = mk_api_task(client, ARXIV)
        _write_dual(client, tid, {"documents": ["x"], "chunks": []})
        r = client.get(f"/api/task/{tid}/reader")
        assert r.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert r.json()["code"] == "internal"

    def test_reading_non_dict_degrades(self, client: TestClient) -> None:
        """reading.json 非 dict → 降级 {}（辅助状态文件不炸 reader）。"""
        tid = mk_api_task(client, ARXIV)
        _write_dual(client, tid, {"documents": {}, "chunks": []})
        tdir = client.app.state.data_dir / "tasks" / tid
        (tdir / "reading.json").write_text('["junk"]', encoding="utf-8")
        r = client.get(f"/api/task/{tid}/reader")
        assert r.status_code == HTTPStatus.OK
        assert r.json()["reading"] == {}

    def test_documents_urls_both_sides(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        _write_dual(
            client,
            tid,
            {
                "documents": {
                    "original": {"pages": 3},
                    "translated": {"pages": 3},
                },
                "chunks": [],
            },
        )
        doc = client.get(f"/api/task/{tid}/reader").json()
        assert doc["documents"]["original"]["url"] == f"/api/files/{tid}/en.pdf"
        assert doc["documents"]["translated"]["url"] == f"/api/files/{tid}/zh.pdf"
        assert doc["alignment"] == {"kind": "pages"}  # 缺省回填
        assert doc["view"] == "pdf"

    def test_view_md_zip_only_html(self, client: TestClient) -> None:
        """md_zip 在而 zh_pdf 不在 → view=html；zh_pdf 补上 → pdf。"""
        tid = mk_api_task(client, ARXIV)
        _write_dual(client, tid, {"documents": {}, "chunks": []})
        _reg_file(client, tid, "md_zip", "md.zip", b"PKfake")
        assert client.get(f"/api/task/{tid}/reader").json()["view"] == "html"
        _reg_file(client, tid, "zh_pdf", "zh.pdf")
        assert client.get(f"/api/task/{tid}/reader").json()["view"] == "pdf"

    def test_view_dom_zh_html(self, client: TestClient) -> None:
        """``zh_html`` 登记 → ``view=dom``（dom 视图 pages 即锚点数）——
        优先级高于 md_zip/pdf 判定。"""
        tid = _mk_kind_task(client, "arxiv_html")
        _write_dual(client, tid, {"documents": {}, "chunks": []})
        _reg_file(client, tid, "zh_html", "zh.html", b"<html/>")
        assert client.get(f"/api/task/{tid}/reader").json()["view"] == "dom"

    def test_dom_documents_urls(self, client: TestClient) -> None:
        """``kind=arxiv_html`` 的 documents url → en.html/zh.html（非 PDF 对）。"""
        tid = _mk_kind_task(client, "arxiv_html")
        _write_dual(
            client,
            tid,
            {
                "documents": {
                    "original": {"pages": 5},
                    "translated": {"pages": 5},
                },
                "chunks": [],
            },
        )
        _reg_file(client, tid, "zh_html", "zh.html", b"<html/>")
        doc = client.get(f"/api/task/{tid}/reader").json()
        assert doc["documents"]["original"]["url"] == f"/api/files/{tid}/en.html"
        assert doc["documents"]["translated"]["url"] == f"/api/files/{tid}/zh.html"
        assert doc["view"] == "dom"
        # 对照：kind=arxiv 仍发 PDF 对
        tid2 = _mk_kind_task(client, "arxiv")
        _write_dual(
            client,
            tid2,
            {"documents": {"original": {}, "translated": {}}, "chunks": []},
        )
        doc2 = client.get(f"/api/task/{tid2}/reader").json()
        assert doc2["documents"]["original"]["url"] == f"/api/files/{tid2}/en.pdf"
        assert doc2["view"] == "pdf"

    def test_reading_roundtrip(self, client: TestClient) -> None:
        """PUT position 写 reading.json → GET reader 原样读回。"""
        tid = mk_api_task(client, ARXIV)
        _write_dual(client, tid, {"documents": {}, "chunks": []})
        r = client.put(
            f"/api/task/{tid}/reader/position",
            json={"positions": {"original": 5, "translated": 7}, "active": "original"},
        )
        assert r.status_code == HTTPStatus.OK
        doc = client.get(f"/api/task/{tid}/reader").json()
        assert doc["reading"]["positions"] == {"original": 5, "translated": 7}
        assert doc["reading"]["active"] == "original"


class TestReaderPut:
    def test_document_version_mismatch_409(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        rec = _reg_file(client, tid, "zh_pdf", "zh.pdf")
        r = client.put(
            f"/api/task/{tid}/reader/position",
            json={"positions": {"original": 1}, "document_version": "stale"},
        )
        assert r.status_code == HTTPStatus.CONFLICT
        assert r.json()["code"] == "version_mismatch"
        r = client.put(
            f"/api/task/{tid}/reader/position",
            json={
                "positions": {"original": 1},
                "document_version": rec["sha256"],
            },
        )
        assert r.status_code == HTTPStatus.OK

    def test_document_version_zh_html_fallback(self, client: TestClient) -> None:
        """无 zh_pdf 的 arxiv_html → 版本闸回落 ``zh_html`` sha256。"""
        tid = _mk_kind_task(client, "arxiv_html")
        rec = _reg_file(client, tid, "zh_html", "zh.html", b"<html/>")
        r = client.put(
            f"/api/task/{tid}/reader/position",
            json={"positions": {"original": 1}, "document_version": "stale"},
        )
        assert r.status_code == HTTPStatus.CONFLICT
        assert r.json()["code"] == "version_mismatch"
        r = client.put(
            f"/api/task/{tid}/reader/position",
            json={
                "positions": {"original": 1},
                "document_version": rec["sha256"],
            },
        )
        assert r.status_code == HTTPStatus.OK

    def test_whitelist_keys(self, client: TestClient) -> None:
        """positions/active/mode/zoom/sync 白名单外键不落盘。"""
        tid = mk_api_task(client, ARXIV)
        r = client.put(
            f"/api/task/{tid}/reader/position",
            json={
                "positions": {"original": 2},
                "active": "original",
                "mode": "dual",
                "zoom": 1.5,
                "sync": True,
                "evil_key": "payload",
                "document_version": "",
            },
        )
        assert r.status_code == HTTPStatus.OK
        tdir = client.app.state.data_dir / "tasks" / tid
        saved = json.loads((tdir / "reading.json").read_text(encoding="utf-8"))
        assert "evil_key" not in saved
        assert "document_version" not in saved
        assert saved["zoom"] == 1.5  # noqa: PLR2004 -- 直写值回读

    def test_put_404(self, client: TestClient) -> None:
        r = client.put(
            "/api/task/t_0000000000000000/reader/position", json={"positions": {}}
        )
        assert r.status_code == HTTPStatus.NOT_FOUND

    def test_put_bad_json_400(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        r = client.put(
            f"/api/task/{tid}/reader/position",
            content=b"{broken",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST


# ------------------------------------------------------------ settings


class TestSettingsPut:
    def test_bad_json_400(self, client: TestClient) -> None:
        r = client.put(
            "/api/settings",
            content=b"{broken",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_bad_target_lang_400(self, client: TestClient) -> None:
        r = client.put("/api/settings", json={"target_lang": "fr"})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_bad_engine_400(self, client: TestClient) -> None:
        r = client.put("/api/settings", json={"engine": "pdflatex"})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_bad_quota_400(self, client: TestClient) -> None:
        assert (
            client.put("/api/settings", json={"quota_max_tasks": -1}).status_code
            == HTTPStatus.BAD_REQUEST
        )
        assert (
            client.put("/api/settings", json={"quota_max_bytes": "abc"}).status_code
            == HTTPStatus.BAD_REQUEST
        )

    def test_concurrency_clamp(self, client: TestClient) -> None:
        r = client.put("/api/settings", json={"concurrency": 99})
        assert r.status_code == HTTPStatus.OK
        assert r.json()["concurrency"] == 16  # noqa: PLR2004 -- 上限
        r = client.put("/api/settings", json={"concurrency": 0})
        assert r.json()["concurrency"] == 1

    def test_clear_api_key(self, client: TestClient) -> None:
        client.put("/api/settings", json={"api_key": "sk-x"})
        assert client.get("/api/settings").json()["has_api_key"] is True
        # 空串不清（合并语义）——须显式 clear_api_key
        client.put("/api/settings", json={"api_key": ""})
        assert client.get("/api/settings").json()["has_api_key"] is True
        client.put("/api/settings", json={"clear_api_key": True})
        assert client.get("/api/settings").json()["has_api_key"] is False

    def test_unknown_field_ignored(self, client: TestClient) -> None:
        """未知键不落盘、响应 ``ignored`` 回显——静默丢弃的 200 会让调用方
        以为写入生效（旧行为是静默写进 settings.json 攒垃圾键）。"""
        r = client.put("/api/settings", json={"bogus_field": 1})
        assert r.status_code == HTTPStatus.OK
        assert r.json()["ignored"] == ["bogus_field"]
        # 未知键被摘除后才进 save——落盘文件里没有它
        stored = client.get("/api/settings").json()
        assert "bogus_field" not in stored

    def test_pseudo_keys_pass(self, client: TestClient) -> None:
        """has_api_key（出参回显）/clear_api_key（控制键）不算未知键。"""
        r = client.put("/api/settings", json={"has_api_key": True})
        assert r.status_code == HTTPStatus.OK
        r = client.put("/api/settings", json={"api_key": "sk-x", "clear_api_key": True})
        assert r.status_code == HTTPStatus.OK
        assert r.json()["has_api_key"] is False


class TestSettingsTestEdge:
    def test_invalid_base_url_400(self, client: TestClient) -> None:
        assert (
            client.post("/api/settings/test", json={"base_url": "ftp://x"}).status_code
            == HTTPStatus.BAD_REQUEST
        )
        # 非 localhost/tailnet 的 http → 400（强制 HTTPS）
        assert (
            client.post(
                "/api/settings/test", json={"base_url": "http://remote.example.com"}
            ).status_code
            == HTTPStatus.BAD_REQUEST
        )

    def test_body_key_scrubbed(self, client: TestClient) -> None:
        """body.api_key 探活失败回显必须脱敏。"""
        import socket  # noqa: PLC0415 -- 仅此用例要占即释端口

        # bind 但不 listen：占住端口防外部抢占，入站连接仍必 ECONNREFUSED。
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            r = client.post(
                "/api/settings/test",
                json={
                    "base_url": f"http://127.0.0.1:{port}",
                    "api_key": "sk-body-secret-9",
                },
            )
        assert r.status_code == HTTPStatus.OK
        assert r.json()["ok"] is False
        assert "sk-body-secret-9" not in json.dumps(r.json())


# ------------------------------------------------------------ CSRF 补面


class TestCsrfEdges:
    def test_delete_cross_site_403(self, client: TestClient) -> None:
        r = client.delete(
            "/api/task/t_0000000000000000",
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        assert r.status_code == HTTPStatus.FORBIDDEN

    def test_patch_cross_site_403(self, client: TestClient) -> None:
        """PATCH 也在 mutating 方法集——路由不存在也得先过 CSRF 闸。"""
        r = client.patch(
            "/api/task/t_0000000000000000",
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        assert r.status_code == HTTPStatus.FORBIDDEN

    def test_origin_null_403(self, client: TestClient) -> None:
        """sandbox/null origin → hostname 缺失 → 拒。"""
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={},
            headers={"Origin": "null"},
        )
        assert r.status_code == HTTPStatus.FORBIDDEN

    def test_origin_subdomain_evil_403(self, client: TestClient) -> None:
        """``localhost.evil.com`` 后缀碰瓷——hostname 全等比对不过。"""
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={},
            headers={"Origin": "http://localhost.evil.com"},
        )
        assert r.status_code == HTTPStatus.FORBIDDEN

    def test_origin_ipv6_localhost_403(self, client: TestClient) -> None:
        """[::1] 与 localhost 是不同 origin（主机形+端口全等比对）——拒。"""
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={},
            headers={"Origin": "http://[::1]:8765"},
        )
        assert r.status_code == HTTPStatus.FORBIDDEN

    def test_origin_case_insensitive_host(self, client: TestClient) -> None:
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={},
            headers={"Origin": "HTTP://LOCALHOST"},
        )
        assert r.status_code == HTTPStatus.ACCEPTED


# ------------------------------------------------------------ 租户遮蔽矩阵


class TestTenantShadowing:
    """server 模式：`_get_task` 三检不过 → 全端点 404（存在性遮蔽）。

    test_server_byok/polish 已钉 GET task / GET tasks / DELETE——本类补齐
    files / files{kind} / cancel / retry / reader / reader/position。
    """

    @pytest.fixture
    def alien(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> str:
        """k-A 租户名下的任务 id；探测方持 k-B。"""
        monkeypatch.setenv("TEXLATE_MODE", "server")
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={"model": "m"},
            headers={"X-Texlate-Key": "k-A"},
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        return r.json()["task_id"]

    _HDR_B: ClassVar[dict[str, str]] = {"X-Texlate-Key": "k-B"}

    def test_files_list(self, client: TestClient, alien: str) -> None:
        r = client.get(f"/api/files/{alien}", headers=self._HDR_B)
        assert r.status_code == HTTPStatus.NOT_FOUND

    def test_file_get(self, client: TestClient, alien: str) -> None:
        r = client.get(f"/api/files/{alien}/zh.pdf", headers=self._HDR_B)
        assert r.status_code == HTTPStatus.NOT_FOUND

    def test_cancel(self, client: TestClient, alien: str) -> None:
        r = client.post(f"/api/task/{alien}/cancel", headers=self._HDR_B)
        assert r.status_code == HTTPStatus.NOT_FOUND

    def test_retry(self, client: TestClient, alien: str) -> None:
        r = client.post(f"/api/task/{alien}/retry", json={}, headers=self._HDR_B)
        assert r.status_code == HTTPStatus.NOT_FOUND

    def test_reader(self, client: TestClient, alien: str) -> None:
        r = client.get(f"/api/task/{alien}/reader", headers=self._HDR_B)
        assert r.status_code == HTTPStatus.NOT_FOUND

    def test_reader_position(self, client: TestClient, alien: str) -> None:
        r = client.put(
            f"/api/task/{alien}/reader/position",
            json={"positions": {}},
            headers=self._HDR_B,
        )
        assert r.status_code == HTTPStatus.NOT_FOUND

    def test_sse_stream(self, client: TestClient, alien: str) -> None:
        """SSE 通道同检——跨租户订不到事件流。"""
        r = client.get(
            f"/api/task/{alien}",
            headers={**self._HDR_B, "Accept": "text/event-stream"},
        )
        assert r.status_code == HTTPStatus.NOT_FOUND


# ------------------------------------------------------------ SPA 挂载


class TestSpaMount:
    def test_env_dir_mounted(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,
    ) -> None:
        """``TEXLATE_SPA_DIR`` 指向含 index.html 的目录 → ``/`` 挂该 SPA。"""
        spa = tmp_path / "spa"
        spa.mkdir()
        (spa / "index.html").write_text(
            "<html><title>spa-ok</title></html>", encoding="utf-8"
        )
        clean_env.setenv("TEXLATE_SPA_DIR", str(spa))
        with TestClient(make_app(tmp_path / "d")) as c:
            r = c.get("/")
            assert r.status_code == HTTPStatus.OK
            assert "spa-ok" in r.text

    def test_no_artifacts_no_mount(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """产物缺席（spa_dir→None）→ 不挂载：``/`` 404 但 API 照常。"""
        monkeypatch.setattr("texlate.server.staticfiles.spa_dir", lambda: None)
        with TestClient(make_app(tmp_path)) as c:
            assert c.get("/").status_code == HTTPStatus.NOT_FOUND
            assert c.get("/api/health").status_code == HTTPStatus.OK

    def test_spa_dir_index_gate(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,
    ) -> None:
        """``spa_dir`` 的 index.html 闸：env 目录无 index.html 不采信（回退包内）。"""
        import texlate.server.staticfiles as sf  # noqa: PLC0415 -- 测试内延迟导入

        spa = tmp_path / "spa"
        spa.mkdir()
        clean_env.setenv("TEXLATE_SPA_DIR", str(spa))
        assert sf.spa_dir() != spa  # 无 index.html → 回退包内（有/无皆可能）
        (spa / "index.html").write_text("<html/>", encoding="utf-8")
        assert sf.spa_dir() == spa


# ------------------------------------------------------------ options 入参闸


class TestOptionsGate:
    """``_clean_task_options``：engine/concurrency 白名单 + 系统保留键摘除。

    此前 options_json 无入参闸——``engine`` 非法值跑到编译段才 fault、
    ``concurrency`` 非数值直接 500、``reuse_hit`` 可伪造让 share_pack 永 422。
    """

    def test_engine_invalid_400(self, client: TestClient) -> None:
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={"options": {"engine": "pdflatex"}},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "invalid_request"

    def test_engine_valid_202(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV, options={"engine": "xelatex"})
        row = client.portal.call(partial(client.app.state.store.get, tid))
        assert json.loads(row["options_json"])["engine"] == "xelatex"

    def test_source_invalid_400(self, client: TestClient) -> None:
        """``options.source ∈ eprint|html``——非法取源值入参即 400。"""
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={"options": {"source": "ftp"}},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "invalid_request"

    def test_source_html_kind_arxiv_html(self, client: TestClient) -> None:
        """``source=html`` → ``kind=arxiv_html`` + reader_url 签发（产 dual.json）。"""
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={"options": {"source": "html"}},
        )
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        assert "reader_url" in r.json()
        row = client.portal.call(
            partial(client.app.state.store.get, r.json()["task_id"])
        )
        assert row["kind"] == "arxiv_html"
        assert json.loads(row["options_json"])["source"] == "html"

    def test_source_default_eprint(self, client: TestClient) -> None:
        """缺省 source → kind=arxiv 原链 + ``"eprint"`` 规范回写 options。"""
        tid = mk_api_task(client, ARXIV)
        row = client.portal.call(partial(client.app.state.store.get, tid))
        assert row["kind"] == "arxiv"
        assert json.loads(row["options_json"])["source"] == "eprint"

    def test_concurrency_garbage_400(self, raw_client: TestClient) -> None:
        """``int("abc")`` 裸炸曾是 500——入参闸收敛成 400 invalid_request。"""
        for bad in ("abc", {"x": 1}, [2]):
            r = raw_client.post(
                f"/api/arxiv/{ARXIV}/translate",
                json={"options": {"concurrency": bad}},
            )
            assert r.status_code == HTTPStatus.BAD_REQUEST, bad
            assert r.json()["code"] == "invalid_request"

    def test_concurrency_clamped(self, client: TestClient) -> None:
        """settings 同口径 1–16 clamp（0→1、99→16）。"""
        tid = mk_api_task(client, ARXIV, options={"concurrency": 99})
        row = client.portal.call(partial(client.app.state.store.get, tid))
        assert json.loads(row["options_json"])["concurrency"] == 16  # noqa: PLR2004
        assert json.loads(row["config_json"])["concurrency"] == 16  # noqa: PLR2004

    def test_reserved_keys_stripped(self, client: TestClient) -> None:
        """reuse_hit 等系统键入参即摘——options_json 审计面不可伪造。"""
        tid = mk_api_task(
            client,
            ARXIV,
            options={
                "reuse_hit": "t_deadbeefdeadbeef",
                "share": {"contributor": "fake"},
                "engine_resolved": "xelatex",
                "route_engines": ["xelatex"],
                "arxiv_categories": ["cs.FAKE"],
                "prefer": "fresh",
            },
        )
        row = client.portal.call(partial(client.app.state.store.get, tid))
        opts = json.loads(row["options_json"])
        for k in (
            "reuse_hit",
            "share",
            "engine_resolved",
            "route_engines",
            "arxiv_categories",
        ):
            assert k not in opts
        assert opts["prefer"] == "fresh"  # 用户合法键不误伤

    def test_stripped_reuse_hit_no_pack_422(self, client: TestClient) -> None:
        """注入 reuse_hit 被摘 → share_pack 走到产物检查（artifacts 码区分分支）。"""
        tid = mk_api_task(client, ARXIV, options={"reuse_hit": "t_deadbeefdeadbeef"})
        _force(client, tid, "done")
        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        # reuse_hit 分支是 share_pack_rejected；摘除后是缺产物分支
        assert r.json()["code"] == "share_pack_artifacts"

    def test_upload_options_gate(self, client: TestClient) -> None:
        """upload 同闸：engine 白名单 + 保留键摘除。"""
        r = client.post(
            "/api/upload",
            files={"file": ("main.tex", MINI_TEX.encode(), "text/plain")},
            data={"options": '{"engine":"pdflatex"}'},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST
        r = client.post(
            "/api/upload",
            files={"file": ("main.tex", MINI_TEX.encode(), "text/plain")},
            data={"options": '{"reuse_hit":"t_x","concurrency":99}'},
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        row = client.portal.call(
            partial(client.app.state.store.get, r.json()["task_id"])
        )
        opts = json.loads(row["options_json"])
        assert "reuse_hit" not in opts
        assert opts["concurrency"] == 16  # noqa: PLR2004

    def test_retry_options_gate(self, client: TestClient) -> None:
        """retry 并入增量同闸：非法 engine 400、保留键摘、合法键 clamp 并入。"""
        tid = mk_api_task(client, ARXIV)
        client.post(f"/api/task/{tid}/cancel")
        r = client.post(
            f"/api/task/{tid}/retry", json={"options": {"engine": "pdflatex"}}
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert client.get(f"/api/task/{tid}").json()["status"] == "cancelled"
        r = client.post(
            f"/api/task/{tid}/retry",
            json={"options": {"reuse_hit": "t_x", "concurrency": 99}},
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        row = client.portal.call(partial(client.app.state.store.get, tid))
        opts = json.loads(row["options_json"])
        assert "reuse_hit" not in opts
        assert opts["concurrency"] == 16  # noqa: PLR2004


# ------------------------------------------------------------ server 模式 settings 闸


class TestServerModeSettingsGate:
    """§4.1：PUT settings 是本地单机默认形态——server 模式写路径 403。

    多租户下 settings.json 是部署方全局配置：租户可写即可改 base_url
    截获他租户 header key / 改配额/CORS；``settings/test`` 是同级
    出站探活 oracle。读面（GET settings/providers/health）保持开放
    但裁部署拓扑字段（glossary_dir/cors_origins/data_dir/has_env_key）。
    """

    def test_put_settings_403(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEXLATE_MODE", "server")
        # 带 key 才过匿名 401 闸、够到 write gate 的 403
        r = client.put(
            "/api/settings",
            json={"base_url": "https://evil.example"},
            headers={"X-Texlate-Key": "k-A"},
        )
        assert r.status_code == HTTPStatus.FORBIDDEN
        # 未落盘——settings.json 根本没被写
        assert not (client.app.state.data_dir / "settings.json").exists()

    def test_settings_test_403(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEXLATE_MODE", "server")
        r = client.post("/api/settings/test", json={}, headers={"X-Texlate-Key": "k-A"})
        assert r.status_code == HTTPStatus.FORBIDDEN

    def test_read_paths_open(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GET settings/providers/health 是公共读面——server 模式不闸。"""
        monkeypatch.setenv("TEXLATE_MODE", "server")
        assert client.get("/api/settings").status_code == HTTPStatus.OK
        assert client.get("/api/providers").status_code == HTTPStatus.OK
        assert client.get("/api/health").status_code == HTTPStatus.OK

    def test_health_minimal(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """server 模式 health = 探活 + 深度集 ``{ok, db, queue_depth}``——
        version/compilers/data_dir 属部署拓扑仍不外露。"""
        monkeypatch.setenv("TEXLATE_MODE", "server")
        assert client.get("/api/health").json() == {
            "ok": True,
            "db": True,
            "queue_depth": 0,
        }

    def test_settings_topology_hidden(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """server 模式 settings 摘 glossary_dir/cors_origins；租户可见面保留。"""
        monkeypatch.setenv("TEXLATE_MODE", "server")
        body = client.get("/api/settings").json()
        assert "glossary_dir" not in body
        assert "cors_origins" not in body
        assert "api_key" not in body
        # 租户自身策略面不裁：配额/当前网关/key 存在位
        assert "quota_max_tasks" in body
        assert "base_url" in body
        assert "has_api_key" in body

    def test_providers_env_key_hidden(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """server 模式 providers 摘 has_env_key——部署方 env 凭据配置面。"""
        monkeypatch.setenv("TEXLATE_MODE", "server")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-x")
        body = client.get("/api/providers").json()
        assert all("has_env_key" not in p for p in body["providers"])

    def test_local_mode_full_read_surface(self, client: TestClient) -> None:
        """local 形态读面不裁——三端点全量字段照回。"""
        body = client.get("/api/settings").json()
        assert "glossary_dir" in body
        assert "cors_origins" in body
        health = client.get("/api/health").json()
        assert {"version", "compilers", "data_dir"} <= health.keys()
        presets = client.get("/api/providers").json()["providers"]
        assert all("has_env_key" in p for p in presets)

    def test_local_mode_still_writes(self, client: TestClient) -> None:
        """local 形态不受影响——PUT settings 正常合并。"""
        r = client.put("/api/settings", json={"concurrency": 4})
        assert r.status_code == HTTPStatus.OK


class TestTasksSlim:
    """POST /api/tasks/slim：终态任务 workdir 清未登记字节，产物/记录全留。"""

    @staticmethod
    def _seed(client: TestClient, tid: str) -> Path:
        """造一个典型 workdir：登记产物 + zh/base 活树 + build 中间件。"""
        tdir = client.app.state.data_dir / "tasks" / tid
        for d in ("zh", "base", "build-zh"):
            (tdir / d).mkdir(parents=True, exist_ok=True)
        (tdir / "zh" / "main.tex").write_bytes(b"x" * 40)
        (tdir / "base" / "main.tex").write_bytes(b"x" * 20)
        (tdir / "build-zh" / "a.aux").write_bytes(b"x" * 50)
        (tdir / "orphan.bin").write_bytes(b"x" * 10)
        return tdir

    def test_done_task_keeps_artifacts_and_live_trees(
        self, client: TestClient
    ) -> None:
        tid = _mk_kind_task(client, "arxiv")
        _force(client, tid, "done")
        _reg_file(client, tid, "zh_pdf", "zh.pdf")
        tdir = self._seed(client, tid)
        r = client.post("/api/tasks/slim")
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        assert body["slimmed"] == 1
        assert body["freed_bytes"] == 60  # noqa: PLR2004 -- a.aux 50 + orphan.bin 10
        # 登记产物 + zh/base 活树（单块重译依赖）保留；build 中间件清空
        assert (tdir / "zh.pdf").is_file()
        assert (tdir / "zh" / "main.tex").is_file()
        assert (tdir / "base" / "main.tex").is_file()
        assert not (tdir / "build-zh").exists()
        assert not (tdir / "orphan.bin").exists()
        # 幂等：二刷零释放
        r2 = client.post("/api/tasks/slim")
        assert r2.json() == {"slimmed": 0, "freed_bytes": 0}

    def test_non_done_terminal_drops_live_trees(
        self, client: TestClient
    ) -> None:
        """fault 终态不可重译——zh/base 同中间件一并清，只留登记件。"""
        tid = _mk_kind_task(client, "arxiv")
        _force(client, tid, "fault")
        _reg_file(client, tid, "compile_log", "compile.log")
        tdir = self._seed(client, tid)
        r = client.post("/api/tasks/slim")
        assert r.status_code == HTTPStatus.OK
        assert (tdir / "compile.log").is_file()
        for d in ("zh", "base", "build-zh"):
            assert not (tdir / d).exists()

    def test_active_task_untouched(self, client: TestClient) -> None:
        tid = _mk_kind_task(client, "arxiv")
        _force(client, tid, "translating")
        tdir = self._seed(client, tid)
        r = client.post("/api/tasks/slim")
        assert r.status_code == HTTPStatus.OK
        assert r.json() == {"slimmed": 0, "freed_bytes": 0}
        assert (tdir / "orphan.bin").is_file()

    def test_dry_run_reports_without_deleting(
        self, client: TestClient
    ) -> None:
        """``?dry=1``：同口径只算不删——UI 清理菜单的「约可释放 X」预估。"""
        tid = _mk_kind_task(client, "arxiv")
        _force(client, tid, "done")
        _reg_file(client, tid, "zh_pdf", "zh.pdf")
        tdir = self._seed(client, tid)
        r = client.post("/api/tasks/slim?dry=1")
        assert r.status_code == HTTPStatus.OK
        assert r.json() == {"slimmed": 1, "freed_bytes": 60}
        # 一个 bit 都没动——含空目录与孤儿文件
        assert (tdir / "build-zh" / "a.aux").is_file()
        assert (tdir / "orphan.bin").is_file()
        # 再 dry 同值；真跑后 dry 归零——预估口径与执行口径一致
        assert client.post("/api/tasks/slim?dry=1").json()["freed_bytes"] == 60
        client.post("/api/tasks/slim")
        assert client.post("/api/tasks/slim?dry=1").json() == {
            "slimmed": 0,
            "freed_bytes": 0,
        }
