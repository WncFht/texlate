"""app.py 端点覆盖补洞：错误码路径 / 边界参数 / 状态机守卫 / 租户遮蔽。

对照 ``bench/results/api-cover-2026-09-16/report.md`` 的端点×覆盖矩阵——
本文件只补既有 test_server_* 未覆盖的面（不重测 happy path）。
已确认的产品 bug 用 ``xfail(strict=True)`` 钉期望行为：修好即 XPASS 报警。
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

from conftest import MINI_TEX, make_app, upload_tex
from starlette.testclient import TestClient

from texlate.server.settings import SettingsStore

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


def _mk(client: TestClient, arxiv_id: str = ARXIV, **kw: object) -> str:
    """POST translate → task_id（缺省 202 断言）。"""
    r = client.post(f"/api/arxiv/{arxiv_id}/translate", json=dict(kw))
    assert r.status_code == HTTPStatus.ACCEPTED, r.text
    return r.json()["task_id"]


def _docx() -> bytes:
    """最小 docx 魔数载荷。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<doc/>")
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

    def test_non_dict_body_empty(self, client: TestClient) -> None:
        """JSON 数组 body 按空 body 处理（_read_body 只收 dict）。"""
        r = client.post(f"/api/arxiv/{ARXIV}/translate", json=[1, 2])
        assert r.status_code == HTTPStatus.ACCEPTED

    @pytest.mark.xfail(
        strict=True, reason="dict(options) 非标量 → 500（report.md B2）"
    )
    def test_options_str_400(self, raw_client: TestClient) -> None:
        r = raw_client.post(
            f"/api/arxiv/{ARXIV}/translate", json={"options": "xx"}
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.xfail(
        strict=True, reason="dict(options) 非标量 → 500（report.md B2）"
    )
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
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate", json={"model": "x" * 201}
        )
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

        与下条 xfail 对照：同一路径因 body.model 有无而 400/500 分裂。
        """
        r = raw_client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={},
            headers={"X-Texlate-Base-Url": "ftp://x"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.xfail(
        strict=True,
        reason="_auth 的 ValueError 只在 translate try 内被接住（report.md B1）",
    )
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
        tid = _mk(client, glossary="terms.yaml")
        row = client.portal.call(partial(client.app.state.store.get, tid))
        assert json.loads(row["options_json"])["glossary"] == "terms.yaml"

    def test_idempotent_replay_skips_quota(
        self, tmp_path: Path, clean_env: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        """配额满后 idempotent 命中不建行 → 仍 202（_check_quota 在 dedup 后）。"""
        data_root = tmp_path / "data"
        data_root.mkdir(parents=True)
        SettingsStore(data_root).save({"quota_max_tasks": 1})
        with TestClient(make_app(tmp_path)) as c:
            hdr = {"Idempotency-Key": "q1"}
            assert c.post(
                f"/api/arxiv/{ARXIV}/translate", json={}, headers=hdr
            ).status_code == HTTPStatus.ACCEPTED
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
        tid = _mk(client)
        bus = client.app.state.bus
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
        tid = _mk(client)
        _reg_file(client, tid, "md_zip", "md.zip", b"PKfake")
        snap = client.get(f"/api/task/{tid}").json()
        assert snap["artifacts"]["md_zip"].endswith(f"/api/files/{tid}/md")

    def test_error_responses_no_store(self, client: TestClient) -> None:
        """no-store 横切对错误响应同样生效。"""
        r = client.get("/api/task/t_0000000000000000")
        assert r.status_code == HTTPStatus.NOT_FOUND
        assert r.headers["Cache-Control"] == "no-store"

    @pytest.mark.xfail(
        strict=True, reason="_auth ValueError 无 400 收敛（report.md B1）"
    )
    def test_bad_header_base_url_400(self, raw_client: TestClient) -> None:
        tid = _mk(raw_client)
        r = raw_client.get(
            f"/api/task/{tid}", headers={"X-Texlate-Base-Url": "ftp://x"}
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.xfail(
        strict=True, reason="_auth ValueError 无 400 收敛（report.md B1）"
    )
    def test_bad_header_model_400(self, raw_client: TestClient) -> None:
        tid = _mk(raw_client)
        r = raw_client.get(f"/api/task/{tid}", headers={"X-Texlate-Model": "x" * 300})
        assert r.status_code == HTTPStatus.BAD_REQUEST


# ------------------------------------------------------------ §2.3 files


class TestFilesList:
    def test_shape(self, client: TestClient) -> None:
        tid = _mk(client)
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
        tid = _mk(client)
        rec = _reg_file(client, tid, "zh_pdf", "zh.pdf")
        r = client.get(f"/api/files/{tid}/zh.pdf", params={"version": rec["sha256"]})
        assert r.status_code == HTTPStatus.OK
        assert r.content == b"%PDF-1.4 fake"

    def test_version_mismatch_409(self, client: TestClient) -> None:
        tid = _mk(client)
        _reg_file(client, tid, "zh_pdf", "zh.pdf")
        r = client.get(f"/api/files/{tid}/zh.pdf", params={"version": "deadbeef"})
        assert r.status_code == HTTPStatus.CONFLICT
        assert r.json()["code"] == "version_mismatch"

    def test_record_without_disk_file_404(self, client: TestClient) -> None:
        """files 行在、磁盘文件不在 → 404 artifact file missing。"""
        tid = _mk(client)
        client.portal.call(
            partial(client.app.state.store.put_file, tid, "zh_pdf", "zh.pdf")
        )
        r = client.get(f"/api/files/{tid}/zh.pdf")
        assert r.status_code == HTTPStatus.NOT_FOUND
        assert "missing" in r.json()["detail"]

    def test_db_path_escape_confined_404(self, client: TestClient) -> None:
        """files.path 越出 tasks/{tid}/ → 404（resolve+is_relative_to 闸）。"""
        tid = _mk(client)
        root = client.app.state.data_dir
        (root / "evil.pdf").write_bytes(b"%PDF-1.4 outside")
        client.portal.call(
            partial(
                client.app.state.store.put_file, tid, "zh_pdf", "../../evil.pdf"
            )
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
        tid = _mk(client)
        _reg_file(client, tid, "zh_pdf", "zh.pdf")
        r = client.get(f"/api/files/{tid}/zh.pdf", params={"download": 1})
        assert f'filename="texlate-{ARXIV}-zh.pdf"' in r.headers[
            "Content-Disposition"
        ]

    def test_media_types(self, client: TestClient) -> None:
        tid = _mk(client)
        _reg_file(client, tid, "compile_log", "compile.log", b"log line\n")
        r = client.get(f"/api/files/{tid}/compile.log")
        assert r.status_code == HTTPStatus.OK
        assert r.headers["content-type"].startswith("text/plain")
        _reg_file(client, tid, "dual_json", "dual.json", b"{}")
        r = client.get(f"/api/files/{tid}/dual.json")
        assert r.headers["content-type"].startswith("application/json")

    def test_download_bad_int_400(self, client: TestClient) -> None:
        """?download=abc → RequestValidationError → 400 invalid_request。"""
        tid = _mk(client)
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

    def test_filename_traversal_sanitized(self, client: TestClient) -> None:
        """``../../etc/evil.tex`` → ``Path().name`` 剥目录 + 字符白名单。"""
        r = client.post(
            "/api/upload",
            files={
                "file": ("../../etc/evil.tex", MINI_TEX.encode(), "text/plain")
            },
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        tid = r.json()["task_id"]
        updir = client.app.state.data_dir / "tasks" / tid / "upload"
        assert (updir / "evil.tex").is_file()
        assert len(list(updir.iterdir())) == 1

    @pytest.mark.xfail(
        strict=True,
        reason="idempotent 命中前 blob 已写 orphan tasks/{新id}/（report.md B4）",
    )
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


# ------------------------------------------------------------ §2.5 tasks list


class TestTasksListEdges:
    def test_status_bogus_empty(self, client: TestClient) -> None:
        """未识别 status 值不校验 → 空列表（参数化查询，无注入面）。"""
        _mk(client)
        r = client.get("/api/tasks", params={"status": "bogus'"})
        assert r.status_code == HTTPStatus.OK
        assert r.json()["tasks"] == []

    def test_error_field_shape(self, client: TestClient) -> None:
        """error_json 反序列化成 dict 进列表项；counters 五键齐。"""
        tid = _mk(client)
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
        tid = _mk(client)
        client.post(f"/api/task/{tid}/cancel")
        evs = client.portal.call(
            partial(client.app.state.store.events_since, tid, 0)
        )
        done = [e for e in evs if e["type"] == "done"]
        assert done
        assert done[-1]["data"]["status"] == "cancelled"


class TestRetryEdges:
    def test_retry_404(self, client: TestClient) -> None:
        assert client.post("/api/task/t_0000000000000000/retry", json={}).status_code == (
            HTTPStatus.NOT_FOUND
        )

    def test_retry_done_409(self, client: TestClient) -> None:
        """done ∉ RETRYABLE_FROM → 409 invalid_transition。"""
        tid = _mk(client)
        _force(client, tid, "done")
        r = client.post(f"/api/task/{tid}/retry", json={})
        assert r.status_code == HTTPStatus.CONFLICT
        assert r.json()["code"] == "invalid_transition"

    def test_retry_fault_202(self, client: TestClient) -> None:
        tid = _mk(client)
        _force(client, tid, "fault")
        r = client.post(f"/api/task/{tid}/retry", json={})
        assert r.status_code == HTTPStatus.ACCEPTED
        assert client.get(f"/api/task/{tid}").json()["status"] == "queued"

    def test_retry_bad_json_400(self, client: TestClient) -> None:
        tid = _mk(client)
        client.post(f"/api/task/{tid}/cancel")
        r = client.post(f"/api/task/{tid}/retry", content=b"{broken")
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert client.get(f"/api/task/{tid}").json()["status"] == "cancelled"

    def test_retry_options_merge(self, client: TestClient) -> None:
        """body.options 深并入 options_json（不覆盖未提键）。"""
        tid = _mk(client, options={"glossary": "a.yaml"})
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
        self, client: TestClient, tmp_path: Path  # noqa: ARG002
    ) -> None:
        """换主文件 retry → chunks 清 + base/zh/build-* 目录删（src 保留）。"""
        tid = _mk(client)
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
        tid = _mk(client)
        _insert_chunk(client, tid)
        client.portal.call(
            partial(client.app.state.store.update_fields, tid, main_tex="main.tex")
        )
        client.post(f"/api/task/{tid}/cancel")
        r = client.post(f"/api/task/{tid}/retry", json={"main": "main.tex"})
        assert r.status_code == HTTPStatus.ACCEPTED
        assert _chunks(client, tid) == 1

    @pytest.mark.xfail(
        strict=True,
        reason="retry 在 transition 守卫前先写库/删目录（report.md B3）",
    )
    def test_retry_terminal_no_side_effects(
        self, raw_client: TestClient
    ) -> None:
        """done 任务 retry 应纯 409——chunks/options/目录一概不动。"""
        tid = _mk(raw_client)
        tdir = raw_client.app.state.data_dir / "tasks" / tid
        (tdir / "base").mkdir(parents=True)
        _insert_chunk(raw_client, tid)
        raw_client.portal.call(
            partial(raw_client.app.state.store.update_fields, tid, main_tex="main.tex")
        )
        _force(raw_client, tid, "done")
        before = raw_client.portal.call(
            partial(raw_client.app.state.store.get, tid)
        )["options_json"]
        r = raw_client.post(
            f"/api/task/{tid}/retry",
            json={"main": "other.tex", "options": {"zap": "1"}},
        )
        assert r.status_code == HTTPStatus.CONFLICT
        assert _chunks(raw_client, tid) == 1
        assert (tdir / "base").exists()
        after = raw_client.portal.call(
            partial(raw_client.app.state.store.get, tid)
        )["options_json"]
        assert after == before


# ------------------------------------------------------------ reader


def _write_dual(client: TestClient, tid: str, doc: dict) -> Path:
    """tasks/{tid}/dual.json 直写（不跑 worker 的 reader 侧 fixture）。"""
    tdir = client.app.state.data_dir / "tasks" / tid
    tdir.mkdir(parents=True, exist_ok=True)
    p = tdir / "dual.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


class TestReaderGet:
    def test_corrupted_dual_500(self, client: TestClient) -> None:
        tid = _mk(client)
        tdir = client.app.state.data_dir / "tasks" / tid
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "dual.json").write_bytes(b"{{{not json")
        r = client.get(f"/api/task/{tid}/reader")
        assert r.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert r.json()["code"] == "internal"

    def test_documents_urls_both_sides(self, client: TestClient) -> None:
        tid = _mk(client)
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
        tid = _mk(client)
        _write_dual(client, tid, {"documents": {}, "chunks": []})
        _reg_file(client, tid, "md_zip", "md.zip", b"PKfake")
        assert client.get(f"/api/task/{tid}/reader").json()["view"] == "html"
        _reg_file(client, tid, "zh_pdf", "zh.pdf")
        assert client.get(f"/api/task/{tid}/reader").json()["view"] == "pdf"

    def test_reading_roundtrip(self, client: TestClient) -> None:
        """PUT position 写 reading.json → GET reader 原样读回。"""
        tid = _mk(client)
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
        tid = _mk(client)
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

    def test_whitelist_keys(self, client: TestClient) -> None:
        """positions/active/mode/zoom/sync 白名单外键不落盘。"""
        tid = _mk(client)
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
        tid = _mk(client)
        r = client.put(f"/api/task/{tid}/reader/position", content=b"{broken")
        assert r.status_code == HTTPStatus.BAD_REQUEST


# ------------------------------------------------------------ settings


class TestSettingsPut:
    def test_bad_json_400(self, client: TestClient) -> None:
        r = client.put("/api/settings", content=b"{broken")
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_bad_target_lang_400(self, client: TestClient) -> None:
        r = client.put("/api/settings", json={"target_lang": "fr"})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_bad_engine_400(self, client: TestClient) -> None:
        r = client.put("/api/settings", json={"engine": "pdflatex"})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_bad_quota_400(self, client: TestClient) -> None:
        assert client.put(
            "/api/settings", json={"quota_max_tasks": -1}
        ).status_code == HTTPStatus.BAD_REQUEST
        assert client.put(
            "/api/settings", json={"quota_max_bytes": "abc"}
        ).status_code == HTTPStatus.BAD_REQUEST

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

    def test_unknown_field_not_returned(self, client: TestClient) -> None:
        """未知键不报错也不回读（load FIELDS 白名单过滤）。"""
        r = client.put("/api/settings", json={"bogus_field": 1})
        assert r.status_code == HTTPStatus.OK
        assert "bogus_field" not in r.json()


class TestSettingsTestEdge:
    def test_invalid_base_url_400(self, client: TestClient) -> None:
        assert client.post(
            "/api/settings/test", json={"base_url": "ftp://x"}
        ).status_code == HTTPStatus.BAD_REQUEST
        # 非 localhost/tailnet 的 http → 400（强制 HTTPS）
        assert client.post(
            "/api/settings/test", json={"base_url": "http://remote.example.com"}
        ).status_code == HTTPStatus.BAD_REQUEST

    def test_body_key_scrubbed(self, client: TestClient) -> None:
        """body.api_key 探活失败回显必须脱敏。"""
        import socket  # noqa: PLC0415 -- 仅此用例要占即释端口

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
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

    def test_origin_ipv6_localhost_ok(self, client: TestClient) -> None:
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={},
            headers={"Origin": "http://[::1]:8765"},
        )
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_origin_case_insensitive_host(self, client: TestClient) -> None:
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={},
            headers={"Origin": "HTTP://LOCALHOST:8765"},
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
