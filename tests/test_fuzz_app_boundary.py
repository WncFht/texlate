"""server/app.py HTTP 边界对抗 fuzz——闸后/闸间解析与状态面。

SEC-1..7 入站闸（Host 白名单→Origin/fetch-site→CT→auth）由 test_server_gate.py
与 gate-redteam 覆盖，413 字节闸由 test_app_endpoints.py 覆盖；本文件打的是
**闸后解析面**：``_parse_multipart``/``_read_body`` 下游、``settings`` 并发
churn、share_pack 索引敌意行、SSE 参数形态、task_id/arxiv_id/kind 路径变形、
上传字段 Content-Type×大小组合。全离线 TestClient，枚举输入即确定性。
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import zipfile
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from conftest import MINI_TEX, make_app, mk_api_task
from starlette.testclient import TestClient

from texlate.server.settings import SettingsStore
from texlate.server.worker import Secrets, TaskCtx
from texlate.share import SHARE_FORMAT, share_key

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import httpx

ARXIV = "2401.00041"

#: CPython int↔str 转换上限（4300）之上的整数位——JSON 巨 int 触发 ValueError。
_HUGE_INT_DIGITS = 5000
#: 远超任何 recursionlimit 的 JSON 嵌套深度——触发 RecursionError。
_DEEP_NEST = 50_000
#: starlette 非文件 part 上限（MultiPartParser.max_part_size）。
_TEXT_PART_CAP = 1024 * 1024
#: starlette 表单字段数上限（max_fields）。
_MAX_FIELDS = 1000
#: int64 上限——events_since 绑参天花板。
_INT64_MAX = 2**63 - 1
#: 私有落盘权限钉。
_MODE_PRIVATE = 0o600
_MODE_MASK = 0o777


@pytest.fixture
def raw_client(
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,  # noqa: ARG001 -- fixture 副作用
) -> Iterator[TestClient]:
    """``raise_server_exceptions=False``——探测 5xx 错误面专用。"""
    with TestClient(make_app(tmp_path), raise_server_exceptions=False) as c:
        yield c


def _force(client: TestClient, tid: str, status: str) -> None:
    """store.transition force 通道（portal 线程纪律）。"""
    client.portal.call(
        partial(client.app.state.store.transition, tid, status, force=True)
    )


def _publish_done(client: TestClient, tid: str) -> None:
    """落 stage+done 两条事件——SSE 重放流的终结凭据。"""
    bus = client.app.state.bus
    client.portal.call(partial(bus.publish, tid, "stage", {"stage": "parsing"}))
    client.portal.call(partial(bus.publish, tid, "done", {"status": "done"}))


def _mp(parts: list[bytes], boundary: bytes = b"X") -> bytes:
    """原始 multipart 体：parts 为完整 part 字节（header 段 + 载荷）。"""
    out = b""
    for p in parts:
        out += b"--" + boundary + b"\r\n" + p + b"\r\n"
    return out + b"--" + boundary + b"--\r\n"


def _cd(name: bytes | str, filename: bytes | str | None = None) -> bytes:
    """Content-Disposition part 头；filename=None → 纯文本字段。"""
    if isinstance(name, str):
        name = name.encode()
    disp = b'Content-Disposition: form-data; name="' + name + b'"'
    if filename is not None:
        if isinstance(filename, str):
            filename = filename.encode()
        disp += b'; filename="' + filename + b'"'
    return disp


def _file_part(payload: bytes, filename: str = "a.tex", name: str = "file") -> bytes:
    return _cd(name, filename) + b"\r\n\r\n" + payload


def _text_part(name: str, value: bytes | str) -> bytes:
    if isinstance(value, str):
        value = value.encode()
    return _cd(name) + b"\r\n\r\n" + value


def _post_raw(client: TestClient, body: bytes, content_type: str) -> httpx.Response:
    """``/api/upload`` 原始字节 POST（绕过 httpx 的 multipart 编码器）。"""
    return client.post(
        "/api/upload", content=body, headers={"Content-Type": content_type}
    )


def _share_bundle(path: Path, artifacts: dict[str, bytes]) -> Path:
    """最小合法 .share.zip（sha256 全真值）——够到 options 解析点。"""
    parts = {
        "arxiv_id": ARXIV,
        "version": "v1",
        "model": "m",
        "prompt_ver": "p1",
        "target_lang": "zh-CN",
        "glossary_hash": "",
        "pipeline_ver": "t|p1",
    }
    manifest = {
        "format": SHARE_FORMAT,
        "share_key": share_key(
            parts["arxiv_id"],
            parts["version"],
            parts["model"],
            parts["prompt_ver"],
            parts["target_lang"],
            parts["glossary_hash"],
            parts["pipeline_ver"],
        ),
        "key_parts": parts,
        "artifacts": {
            n: {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)}
            for n, b in artifacts.items()
        },
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for n, b in artifacts.items():
            zf.writestr(n, b)
    return path


# ------------------------------------------------------------ _read_body JSON


class TestReadBodyJsonFuzz:
    """``_read_body``：``json.loads`` 非 JSONDecodeError 失败逃逸成 500。"""

    def test_huge_int_translate_400(self, raw_client: TestClient) -> None:
        body = b'{"options": {"k": ' + b"1" * _HUGE_INT_DIGITS + b"}}"
        r = raw_client.post(
            f"/api/arxiv/{ARXIV}/translate",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_huge_int_settings_put_400(self, raw_client: TestClient) -> None:
        r = raw_client.put(
            "/api/settings",
            content=b'{"concurrency": ' + b"1" * _HUGE_INT_DIGITS + b"}",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_huge_int_reader_position_400(self, raw_client: TestClient) -> None:
        tid = mk_api_task(raw_client, ARXIV)
        r = raw_client.put(
            f"/api/task/{tid}/reader/position",
            content=b'{"zoom": ' + b"1" * _HUGE_INT_DIGITS + b"}",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_deep_nest_translate_400(self, raw_client: TestClient) -> None:
        body = b"[" * _DEEP_NEST + b"]" * _DEEP_NEST
        r = raw_client.post(
            f"/api/arxiv/{ARXIV}/translate",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_huge_int_upload_options_400(self, raw_client: TestClient) -> None:
        r = raw_client.post(
            "/api/upload",
            files={"file": ("a.tex", MINI_TEX.encode(), "text/plain")},
            data={"options": '{"k": ' + "1" * _HUGE_INT_DIGITS + "}"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_huge_int_share_options_400(
        self, raw_client: TestClient, tmp_path: Path
    ) -> None:
        bundle = _share_bundle(
            tmp_path / "b.zip", {"zh-src.zip": b"x", "dual.json": b"{}"}
        )
        r = raw_client.post(
            "/api/share/import",
            files={"file": ("b.share.zip", bundle.read_bytes())},
            data={"options": '{"k": ' + "1" * _HUGE_INT_DIGITS + "}"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST

    # ---------------- 通过钉：JSON Content-Type 与标量体形 ----------------

    @pytest.mark.parametrize(
        ("ctype", "arxiv_id"),
        [
            ("Application/JSON", "2401.00101"),
            ("application/json;charset=utf-8", "2401.00102"),
            (" application/json ", "2401.00103"),
        ],
    )
    def test_json_ct_variants_accepted(
        self, client: TestClient, ctype: str, arxiv_id: str
    ) -> None:
        """CT 判 = 剥 ``;`` 参数 + strip + lower——大小写/参数/空白放行。"""
        r = client.post(
            f"/api/arxiv/{arxiv_id}/translate",
            content=b"{}",
            headers={"Content-Type": ctype},
        )
        assert r.status_code == HTTPStatus.ACCEPTED

    @pytest.mark.parametrize(
        "ctype", ["application/json-patch+json", "text/json", "application/jsonx"]
    )
    def test_json_ct_nonexact_415(self, client: TestClient, ctype: str) -> None:
        """``+json`` 后缀族不放宽——严格等值（CSRF 闸宁可误伤）。"""
        r = client.post(
            "/api/arxiv/2401.00104/translate",
            content=b"{}",
            headers={"Content-Type": ctype},
        )
        assert r.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE

    def test_json_scalar_bodies_lenient(self, client: TestClient) -> None:
        """``5``/``"s"``/``null`` 等非 dict 体 → ``_read_body`` 归一成 {}。"""
        for i, raw in enumerate((b"5", b'"s"', b"null", b"true")):
            r = client.post(
                f"/api/arxiv/2401.0011{i}/translate",
                content=raw,
                headers={"Content-Type": "application/json"},
            )
            assert r.status_code == HTTPStatus.ACCEPTED, raw

    def test_json_bom_and_whitespace(self, raw_client: TestClient) -> None:
        """UTF-8 BOM 体可解析；纯空白体 → 400 bad json。"""
        r = raw_client.post(
            "/api/arxiv/2401.00115/translate",
            content=b"\xef\xbb\xbf{}",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        r = raw_client.post(
            "/api/arxiv/2401.00116/translate",
            content=b"  \n\t ",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert "bad json" in r.json()["detail"]


# ------------------------------------------------------------ multipart 结构


class TestMultipartStructureFuzz:
    """``_parse_multipart`` 上游：python-multipart 引擎错误的 HTTP 归一化。"""

    @pytest.mark.parametrize(
        ("body", "ct"),
        [
            pytest.param(
                _mp([_file_part(MINI_TEX.encode())], boundary=b"Y"),
                "multipart/form-data; boundary=X",
                id="boundary-mismatch",
            ),
            pytest.param(
                b"--X\r\n"
                + _file_part(MINI_TEX.encode())
                + b"\r\n--X\r\nFAKE BOUNDARY SPLIT\r\n--X--\r\n",
                "multipart/form-data; boundary=X",
                id="boundary-inside-content",
            ),
            pytest.param(
                _mp([_file_part(MINI_TEX.encode())]),
                "multipart/form-data; boundary=X; boundary=Y",
                id="duplicate-boundary-param",
            ),
            pytest.param(
                _mp([_file_part(MINI_TEX.encode())]),
                "multipart/form-data; boundary",
                id="bare-boundary-param",
            ),
        ],
    )
    def test_malformed_multipart_400(
        self, raw_client: TestClient, body: bytes, ct: str
    ) -> None:
        r = _post_raw(raw_client, body, ct)
        assert r.status_code == HTTPStatus.BAD_REQUEST

    # ---------------- 通过钉：结构畸形但可干净拒绝 ----------------

    @pytest.mark.parametrize(
        ("body", "ct"),
        [
            pytest.param(
                b"garbage no boundary body",
                "multipart/form-data",
                id="missing-boundary-param",
            ),
            pytest.param(
                b"--X\r\n\r\nhello\r\n--X--\r\n",
                "multipart/form-data; boundary=X",
                id="part-no-content-disposition",
            ),
            pytest.param(
                b"--X\r\nContent-Disposition: form-data\r\n\r\nhi\r\n--X--\r\n",
                "multipart/form-data; boundary=X",
                id="cd-without-name",
            ),
            pytest.param(
                b'--X\r\nContent-Disposition: form-data; filename="a.tex"'
                b"\r\n\r\nx\r\n--X--\r\n",
                "multipart/form-data; boundary=X",
                id="filename-without-name",
            ),
            pytest.param(
                b"--X\r\n" + _file_part(MINI_TEX.encode()),
                "multipart/form-data; boundary=X",
                id="truncated-no-closing",
            ),
            pytest.param(
                b"--X\r\n" + _cd("file", "a.tex") + b"\r\n",
                "multipart/form-data; boundary=X",
                id="truncated-mid-headers",
            ),
            pytest.param(b"", "multipart/form-data; boundary=X", id="empty-body"),
            pytest.param(
                b"--X--\r\n",
                "multipart/form-data; boundary=X",
                id="only-closing",
            ),
        ],
    )
    def test_rejected_multipart_stays_400(
        self, client: TestClient, body: bytes, ct: str
    ) -> None:
        r = _post_raw(client, body, ct)
        assert r.status_code == HTTPStatus.BAD_REQUEST, r.text
        assert r.json()["detail"]

    def test_nested_foreign_boundary_is_content(self, client: TestClient) -> None:
        """体内 ``--Y`` 段不是声明 boundary → 按文件内容收（multipart 语义）。"""
        body = _mp(
            [
                _file_part(
                    MINI_TEX.encode()
                    + b'\r\n--Y\r\nContent-Disposition: form-data; name="z"'
                    b"\r\n\r\nzz\r\n--Y--\r\n"
                )
            ]
        )
        r = _post_raw(client, body, "multipart/form-data; boundary=X")
        assert r.status_code == HTTPStatus.ACCEPTED

    @pytest.mark.parametrize(
        "ct",
        [
            'multipart/form-data; boundary="X"',
            "multipart/form-data; Boundary=X",
        ],
        ids=["quoted-boundary", "uppercase-param-name"],
    )
    def test_boundary_param_forms_ok(self, client: TestClient, ct: str) -> None:
        r = _post_raw(client, _mp([_file_part(MINI_TEX.encode())]), ct)
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_multipart_media_type_case(self, raw_client: TestClient) -> None:
        r = _post_raw(
            raw_client,
            _mp([_file_part(MINI_TEX.encode())]),
            "MULTIPART/FORM-DATA; boundary=X",
        )
        assert r.status_code == HTTPStatus.ACCEPTED

    @pytest.mark.parametrize(
        "ct",
        [
            "application/json",
            "application/x-www-form-urlencoded",
            "multipart/related; boundary=X",
            "text/plain",
        ],
    )
    def test_non_multipart_ct_400(self, client: TestClient, ct: str) -> None:
        """非 multipart CT → 空表单 → 400 file required（不炸）。"""
        r = _post_raw(client, b"file=x&options=%7B%7D", ct)
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert "file" in r.json()["detail"]


class TestMultipartFieldSemantics:
    """字段重名/file 形态怪异的归一语义钉（last-wins / filename 定 file 性）。"""

    def test_file_then_text_same_name_400(self, client: TestClient) -> None:
        """同名 text 尾随后写覆盖 file → ``out["file"]`` 是 str → 400。"""
        body = _mp([_file_part(MINI_TEX.encode()), _text_part("file", "notafile")])
        r = _post_raw(client, body, "multipart/form-data; boundary=X")
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_text_then_file_same_name_202(self, client: TestClient) -> None:
        """file 尾随后写覆盖 text → UploadPart 生效。"""
        body = _mp([_text_part("file", "notafile"), _file_part(MINI_TEX.encode())])
        r = _post_raw(client, body, "multipart/form-data; boundary=X")
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_two_file_parts_last_wins(self, client: TestClient) -> None:
        """双 file part：落盘的是后者（b.tex）。"""
        second = b"SECOND FILE BODY"
        body = _mp(
            [
                _file_part(MINI_TEX.encode(), filename="a.tex"),
                _file_part(second, filename="b.tex"),
            ]
        )
        r = _post_raw(client, body, "multipart/form-data; boundary=X")
        assert r.status_code == HTTPStatus.ACCEPTED
        tid = r.json()["task_id"]
        updir = client.app.state.data_dir / "tasks" / tid / "upload"
        assert (updir / "b.tex").read_bytes() == second

    def test_options_as_file_ignored(self, client: TestClient) -> None:
        """``options`` 给文件 part → ``_form_text`` 按缺省（不炸不进 options）。"""
        body = _mp(
            [
                _cd("options", "o.bin") + b"\r\n\r\n{" + b"{" * 9,
                _file_part(MINI_TEX.encode()),
            ]
        )
        r = _post_raw(client, body, "multipart/form-data; boundary=X")
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_dup_options_last_wins(self, client: TestClient) -> None:
        """双 ``options`` 文本字段 → 后者生效（坏 JSON 400 证明后写覆盖）。"""
        body = _mp(
            [
                _text_part("options", "{}"),
                _text_part("options", "{bad json"),
                _file_part(MINI_TEX.encode()),
            ]
        )
        r = _post_raw(client, body, "multipart/form-data; boundary=X")
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert "JSON" in r.json()["detail"]

    def test_empty_filename_still_file(self, client: TestClient) -> None:
        """``filename=""`` → UploadFile(filename="") → 缺省名 upload.bin。"""
        body = _mp([_cd("file", "") + b"\r\n\r\n" + MINI_TEX.encode()])
        r = _post_raw(client, body, "multipart/form-data; boundary=X")
        assert r.status_code == HTTPStatus.ACCEPTED
        tid = r.json()["task_id"]
        updir = client.app.state.data_dir / "tasks" / tid / "upload"
        assert (updir / "upload.bin").is_file()

    def test_filename_ext_only_not_file(self, client: TestClient) -> None:
        """``filename*=``（RFC 5987 扩展形）不定 file 性 → 当文本字段 → 400。"""
        body = _mp(
            [
                b'Content-Disposition: form-data; name="file"; '
                b"filename*=utf-8''a.tex\r\n\r\n" + MINI_TEX.encode()
            ]
        )
        r = _post_raw(client, body, "multipart/form-data; boundary=X")
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_escaped_quote_filename(self, client: TestClient) -> None:
        """``filename="a\\"b.tex"`` 引号转义 → 净化成 ``a_b.tex`` 落盘。"""
        body = _mp([_cd("file", 'a\\"b.tex') + b"\r\n\r\n" + MINI_TEX.encode()])
        r = _post_raw(client, body, "multipart/form-data; boundary=X")
        assert r.status_code == HTTPStatus.ACCEPTED
        tid = r.json()["task_id"]
        updir = client.app.state.data_dir / "tasks" / tid / "upload"
        assert (updir / "a_b.tex").is_file()

    def test_text_field_over_1mb_400(self, client: TestClient) -> None:
        """starlette 非文件 part 1MB 闸先于产品 CAP 生效 → 400。"""
        body = _mp(
            [
                _text_part("options", b"z" * (_TEXT_PART_CAP + 8)),
                _file_part(MINI_TEX.encode()),
            ]
        )
        r = _post_raw(client, body, "multipart/form-data; boundary=X")
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert "maximum size" in r.json()["detail"]

    def test_field_count_cap_400(self, client: TestClient) -> None:
        """``max_fields=1000``：第 1001 个文本字段 → 400 Too many fields。"""
        parts = [_text_part(f"f{i}", "v") for i in range(_MAX_FIELDS + 1)]
        parts.append(_file_part(MINI_TEX.encode()))
        r = _post_raw(client, _mp(parts), "multipart/form-data; boundary=X")
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert "Too many fields" in r.json()["detail"]

    def test_file_part_over_1mb_ok(self, client: TestClient) -> None:
        """对照组：1MB part 闸只管非文件字段——1.5MB 文件 part 正常 202。"""
        payload = MINI_TEX.encode() + b"x" * (1500 * 1024)
        r = _post_raw(
            client, _mp([_file_part(payload)]), "multipart/form-data; boundary=X"
        )
        assert r.status_code == HTTPStatus.ACCEPTED


class TestContentTypeVsMagic:
    """上传路由看魔数不看声明 CT/filename——CT 撒谎不改变路由。"""

    def test_declared_pdf_ct_but_tex_magic(self, client: TestClient) -> None:
        """filename=a.pdf + CT application/pdf + tex 字节 → upload_tex。"""
        body = _mp(
            [
                _cd("file", "a.pdf")
                + b"\r\nContent-Type: application/pdf\r\n\r\n"
                + MINI_TEX.encode()
            ]
        )
        r = _post_raw(client, body, "multipart/form-data; boundary=X")
        assert r.status_code == HTTPStatus.ACCEPTED
        rows = client.get("/api/tasks").json()["tasks"]
        row = next(t for t in rows if t["task_id"] == r.json()["task_id"])
        assert row["kind"] == "upload_tex"

    def test_tex_ct_but_pdf_magic_501(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """filename=a.tex + tex/plain CT + %PDF 字节 → upload_pdf → 501。"""
        monkeypatch.setattr("texlate.server.app.find_tool", lambda _n: None)
        body = _mp(
            [
                _cd("file", "a.tex")
                + b"\r\nContent-Type: text/plain\r\n\r\n"
                + b"%PDF-1.4 fake"
            ]
        )
        r = _post_raw(client, body, "multipart/form-data; boundary=X")
        assert r.status_code == HTTPStatus.NOT_IMPLEMENTED
        assert r.json()["code"] == "unsupported_format"

    def test_zip_magic_beats_tex_filename(self, client: TestClient) -> None:
        """filename=a.tex 但 PK 魔数 → zip 路由（docx 看 word/ 成员）。"""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", "<doc/>")
        r = client.post(
            "/api/upload",
            files={"file": ("a.tex", buf.getvalue(), "application/octet-stream")},
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        rows = client.get("/api/tasks").json()["tasks"]
        row = next(t for t in rows if t["task_id"] == r.json()["task_id"])
        assert row["kind"] == "docx"


class TestContentLengthLies:
    """``_parse_multipart`` CL 预检只看纯数字；非数字/缺 CL 由流式闸兜底。"""

    @pytest.mark.parametrize("cl", ["abc", "-5", "+10", "0x10", " 5"])
    def test_non_numeric_cl_valid_body_202(self, client: TestClient, cl: str) -> None:
        """非数字 CL → 预检跳过；体仍被流式闸计数，合法体正常 202。"""
        r = client.post(
            "/api/upload",
            content=_mp([_file_part(MINI_TEX.encode())]),
            headers={
                "Content-Type": "multipart/form-data; boundary=X",
                "Content-Length": cl,
            },
        )
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_cl_underestimate_body_over_cap_413(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CL 报小体真大：预检被绕，流式闸仍按实收字节 413。"""
        import texlate.server.app as app_mod  # noqa: PLC0415 -- 测试内补丁对象

        monkeypatch.setattr(app_mod, "UPLOAD_CAP", 16)
        body = _mp([_file_part(b"y" * (128 * 1024), filename="big.bin")])
        r = client.post(
            "/api/upload",
            content=body,
            headers={
                "Content-Type": "multipart/form-data; boundary=X",
                "Content-Length": "10",  # 谎报——真体远超
            },
        )
        assert r.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert r.json()["code"] == "upload_too_large"

    def test_cl_overestimate_body_small_413(self, client: TestClient) -> None:
        """CL 报大体真小：预检信任声明 → 413（不读体）。"""
        r = client.post(
            "/api/upload",
            content=b"x",
            headers={
                "Content-Type": "multipart/form-data; boundary=X",
                "Content-Length": str(90 * 1024 * 1024),
            },
        )
        assert r.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE


# ------------------------------------------------------------ SSE /events 边界


class TestSseBoundary:
    """``GET /api/task/{id}`` 的 Accept/Last-Event-ID 参数形态。"""

    @staticmethod
    def _sse_events(client: TestClient, tid: str, leid: str) -> list[str]:
        with client.stream(
            "GET",
            f"/api/task/{tid}",
            headers={"Accept": "text/event-stream", "Last-Event-ID": leid},
        ) as r:
            return [
                ln.removeprefix("event:").strip()
                for ln in r.iter_lines()
                if ln.startswith("event:")
            ]

    def test_huge_last_event_id_graceful(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        _force(client, tid, "done")
        # 期望：超界 last_id 被夹住/视为空——流干净终结（无已发事件可放）
        events = self._sse_events(client, tid, str(2**80))
        assert events == ["snapshot"]

    def test_int64_max_last_event_id(self, client: TestClient) -> None:
        """int64 上限内：无重放事件（seq 全 ≤id）→ snapshot 帧后即终。"""
        tid = mk_api_task(client, ARXIV)
        _publish_done(client, tid)
        _force(client, tid, "done")
        events = self._sse_events(client, tid, str(_INT64_MAX))
        assert events == ["snapshot"]

    @pytest.mark.parametrize("leid", ["-5", "abc", "1.5", "", "0x10"])
    def test_unparseable_last_event_id_replays_all(
        self, client: TestClient, leid: str
    ) -> None:
        """解析失败/负值 → last_id=0 → 全量重放含 done 帧收尾。"""
        tid = mk_api_task(client, ARXIV)
        _publish_done(client, tid)
        _force(client, tid, "done")
        events = self._sse_events(client, tid, leid)
        assert events == ["snapshot", "stage", "done"]

    def test_accept_media_type_case(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        _publish_done(client, tid)
        _force(client, tid, "done")
        r = client.get(f"/api/task/{tid}", headers={"Accept": "TEXT/EVENT-STREAM"})
        assert r.headers["content-type"].startswith("text/event-stream")

    @pytest.mark.parametrize(
        "accept",
        [
            "text/event-stream;charset=utf-8",
            "application/xhtml+xml, text/event-stream;q=0.9",
            "x-text/event-stream",  # 子串命中——宽松但无害
        ],
    )
    def test_accept_superset_still_sse(self, client: TestClient, accept: str) -> None:
        tid = mk_api_task(client, ARXIV)
        _publish_done(client, tid)
        _force(client, tid, "done")
        r = client.get(f"/api/task/{tid}", headers={"Accept": accept})
        assert r.headers["content-type"].startswith("text/event-stream")

    def test_sse_nonexistent_task_404(self, client: TestClient) -> None:
        r = client.get(
            "/api/task/t_0000000000000000",
            headers={"Accept": "text/event-stream"},
        )
        assert r.status_code == HTTPStatus.NOT_FOUND


# ------------------------------------------------------------ 路径参数变形


class TestPathParamFuzz:
    """task_id/arxiv_id/kind 路径变形——无 5xx、无形态 oracle 分裂。"""

    @pytest.mark.parametrize(
        "tid",
        [
            "t_0000000000000000",  # 合法形态不存在
            "t_g000000000000000",  # 非 hex
            "t_0",  # 短
            "t_000000000000000",  # 15 hex
            "t_00000000000000000",  # 17 hex
            "T_0000000000000000",  # 大写前缀
            "t_FFFFFFFFFFFFFFFF",  # 大写 hex（valid 过闸→不存在）
            "..",
            "%2e%2e",
        ],
    )
    def test_task_id_shapes_404(self, client: TestClient, tid: str) -> None:
        assert client.get(f"/api/task/{tid}").status_code == HTTPStatus.NOT_FOUND
        assert client.get(f"/api/files/{tid}").status_code == HTTPStatus.NOT_FOUND

    def test_task_id_shape_no_oracle(self, client: TestClient) -> None:
        """非法形态与合法不存在同 404 同 body——不泄形态判定面。"""
        r_bad = client.get("/api/task/t_zzz")
        r_none = client.get("/api/task/t_0000000000000000")
        assert r_bad.status_code == r_none.status_code
        assert r_bad.json() == r_none.json()

    @pytest.mark.parametrize(
        ("arxiv_id", "want"),
        [
            ("", HTTPStatus.BAD_REQUEST),  # //translate
            ("%2e%2e", HTTPStatus.BAD_REQUEST),
            ("2401.00031%2fextra", HTTPStatus.BAD_REQUEST),
            ("hep-th%2f9901001", HTTPStatus.ACCEPTED),  # 旧式斜杠 id 经 %2f
            ("9" * 500, HTTPStatus.BAD_REQUEST),
            ("2401.00031v3", HTTPStatus.ACCEPTED),
        ],
    )
    def test_arxiv_id_shapes(
        self, client: TestClient, arxiv_id: str, want: int
    ) -> None:
        r = client.post(f"/api/arxiv/{arxiv_id}/translate", json={})
        assert r.status_code == want

    @pytest.mark.parametrize(
        "kind",
        ["ZH.PDF", "src", "en.pdf/extra", "zh.pdf%00", "%2e%2e"],
    )
    def test_kind_shapes_404_or_400(self, client: TestClient, kind: str) -> None:
        tid = mk_api_task(client, ARXIV)
        r = client.get(f"/api/files/{tid}/{kind}")
        assert r.status_code in (HTTPStatus.NOT_FOUND, HTTPStatus.BAD_REQUEST)


# ------------------------------------------------------------ share_pack 索引敌意行


class TestSharePackIndexHostility:
    """``index.jsonl`` 行 ``url`` 非扁平名 → 按未命中走重打，绝不 stat 越界。"""

    def _done_arxiv_task(self, client: TestClient) -> tuple[str, str]:
        """done 任务 + 真 share_key（manifest 派生与端点同口径）。"""
        tid = mk_api_task(client, ARXIV)
        _force(client, tid, "done")
        store = client.app.state.store
        row = client.portal.call(partial(store.get, tid))
        root = client.app.state.data_dir
        ctx = TaskCtx(
            store=store,
            bus=client.app.state.bus,
            task_id=tid,
            row=row,
            secrets=Secrets(),
            root=root / "tasks" / tid,
        )
        mf = client.app.state.runner.worker.share_pack_manifest(ctx, row)
        assert mf is not None
        key = share_key(
            str(mf["arxiv_id"]),
            str(mf["version"]),
            str(mf["model"]),
            str(mf["prompt_ver"]),
            str(mf["target_lang"]),
            str(mf["glossary_hash"]),
            str(mf["pipeline_ver"]),
        )
        return tid, key

    @pytest.mark.parametrize(
        "url", ["../../etc/passwd", "a\\b.zip", "e\x00vil.zip", "", ".", ".."]
    )
    def test_hostile_url_falls_through_422(self, client: TestClient, url: str) -> None:
        """非扁平 url 跳过 stat → 产物缺 → 422 share_pack_artifacts（非 500）。"""
        tid, key = self._done_arxiv_task(client)
        out = client.app.state.data_dir / "share"
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.jsonl").write_text(
            json.dumps({"share_key": key, "url": url}) + "\n", encoding="utf-8"
        )
        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert r.json()["code"] == "share_pack_artifacts"

    def test_flat_url_hit_200(self, client: TestClient) -> None:
        """扁平名 + 包文件在场 → 幂等 200 不重打（正面对照组）。"""
        tid, key = self._done_arxiv_task(client)
        out = client.app.state.data_dir / "share"
        out.mkdir(parents=True, exist_ok=True)
        blob = b"PK fake bundle"
        (out / "cached.share.zip").write_bytes(blob)
        (out / "index.jsonl").write_text(
            json.dumps({"share_key": key, "url": "cached.share.zip"}) + "\n",
            encoding="utf-8",
        )
        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.OK
        assert r.json() == {
            "share_key": key,
            "url": "cached.share.zip",
            "bytes": len(blob),
        }

    def test_malformed_index_lines_skipped(self, client: TestClient) -> None:
        """坏行不毒死索引——后面的合法命中行照常。"""
        tid, key = self._done_arxiv_task(client)
        out = client.app.state.data_dir / "share"
        out.mkdir(parents=True, exist_ok=True)
        (out / "ok.share.zip").write_bytes(b"PK")
        (out / "index.jsonl").write_text(
            '{broken\n["not", "dict"]\n\n'
            + json.dumps({"share_key": key, "url": "ok.share.zip"})
            + "\n",
            encoding="utf-8",
        )
        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.OK


# ------------------------------------------------------------ settings churn


class TestSettingsChurn:
    """SettingsStore 多线程 save+load：文件永不撕裂、权限不掉、字段不漂。"""

    def test_concurrent_save_load_integrity(self, tmp_path: Path) -> None:
        root = tmp_path / "data"
        root.mkdir(parents=True)
        store = SettingsStore(root)
        errors: list[str] = []
        n_threads, n_iters = 6, 40

        def worker(i: int) -> None:
            try:
                for k in range(n_iters):
                    store.save(
                        {
                            "model": f"m{i}-{k}",
                            "concurrency": (i % 16) + 1,
                            "target_lang": ("zh-CN", "zh-TW", "en")[i % 3],
                            "api_key": f"sk-t{i}-k{k}",
                        }
                    )
                    loaded = store.load()
                    # 读时完整 schema——损坏窗口绝不可见
                    assert set(SettingsStore.FIELDS) <= set(loaded)
                    store.public()
                    conns = store.connections()
                    assert all(isinstance(v, dict) for v in conns.values())
            except Exception as e:  # noqa: BLE001 -- 收集线程失败统一断言
                errors.append(f"t{i}: {type(e).__name__} {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        final = store.load()
        assert set(SettingsStore.FIELDS) <= set(final)
        assert store.path.stat().st_mode & _MODE_MASK == _MODE_PRIVATE
        assert store.connections_path.stat().st_mode & _MODE_MASK == _MODE_PRIVATE
        # api_key 终值属于某次写入（合并竞态可丢整次更新，绝不出现撕值）
        assert str(final["api_key"]).startswith("sk-t")

    def test_http_put_get_concurrent_churn(self, client: TestClient) -> None:
        """HTTP 面同强度：共享 TestClient 跨线程 PUT/GET 全 200。"""
        errors: list[str] = []
        codes: list[int] = []

        def worker(i: int) -> None:
            try:
                for k in range(25):
                    codes.append(
                        client.put(
                            "/api/settings",
                            json={
                                "concurrency": (i % 16) + 1,
                                "model": f"m{i}-{k}",
                            },
                        ).status_code
                    )
                    codes.append(client.get("/api/settings").status_code)
            except Exception as e:  # noqa: BLE001
                errors.append(f"t{i}: {type(e).__name__} {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert set(codes) == {HTTPStatus.OK}
        data_dir = client.app.state.data_dir
        assert isinstance(json.loads((data_dir / "settings.json").read_text()), dict)

    @pytest.mark.parametrize("bad", [None, {"x": 1}, [1]])
    def test_concurrency_non_numeric_400(
        self, raw_client: TestClient, bad: object
    ) -> None:
        r = raw_client.put("/api/settings", json={"concurrency": bad})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_quota_non_numeric_400_contrast(self, raw_client: TestClient) -> None:
        """对照组：quota_* 对同型输入已正确 400——concurrency 独漏。"""
        for bad in (None, {"x": 1}, [1]):
            r = raw_client.put("/api/settings", json={"quota_max_tasks": bad})
            assert r.status_code == HTTPStatus.BAD_REQUEST, bad

    def test_lenient_coercions(self, client: TestClient) -> None:
        """宽容归一钉：float 截断 / int→str 强转（语义钉非缺陷）。"""
        r = client.put("/api/settings", json={"concurrency": 3.9})
        assert r.json()["concurrency"] == 3  # noqa: PLR2004 -- 截断钉
        r = client.put("/api/settings", json={"quota_max_tasks": 3.7})
        assert r.json()["quota_max_tasks"] == 3  # noqa: PLR2004 -- 同上
        r = client.put("/api/settings", json={"model": 42})
        assert r.json()["model"] == "42"


# ------------------------------------------------------------ 方法/其它面


class TestMethodSurface:
    """路由形态之外的方法面——405 而非 5xx。"""

    @pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
    def test_upload_wrong_method_405(self, client: TestClient, method: str) -> None:
        r = client.request(method, "/api/upload")
        assert r.status_code == HTTPStatus.METHOD_NOT_ALLOWED

    def test_reader_position_lenient_values(self, client: TestClient) -> None:
        """白名单键内值不做类型闸——positions 非 dict 也原样落盘（语义钉）。"""
        tid = mk_api_task(client, ARXIV)
        r = client.put(
            f"/api/task/{tid}/reader/position",
            json={"positions": "not-a-dict", "zoom": "high", "sync": 7},
        )
        assert r.status_code == HTTPStatus.OK
        tdir = client.app.state.data_dir / "tasks" / tid
        saved = json.loads((tdir / "reading.json").read_text(encoding="utf-8"))
        assert saved == {"positions": "not-a-dict", "zoom": "high", "sync": 7}
