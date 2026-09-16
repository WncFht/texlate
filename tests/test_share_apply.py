"""POST /api/share/import + worker share 重验链（shared-cache.md §5 消费侧）。

包由真管线产出（FakeFetcher 供源 + MockTranslator 译 + FakeEngine 编 →
``pack_share`` 打包）；生产/导入双 app 实例模拟跨实例共享。断言面：

- 任务行 ``kind=share``/``arxiv_id`` 钉版/model 取 manifest 值、产物
  六件登记、reader 可达、dual.json 本地重建含包译文；
- 导入产物经 ``cache_key`` 钉版公式对后来的 ``id@vN`` 请求真命中；
- 篡改产物/篡改 manifest/坏 zip/缺字段 → 4xx ``share_invalid``；
- 对账零命中与本地重编失败 → ``partial`` + ``reject_at=share_verify``；
- 命中但 L0 校验不过的 zh → 块级 ``fallback_orig``（``validate``），
  本地无包块 → ``share_miss``——导入全程零 token。
"""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from conftest import (
    MINI_TEX,
    FakeEngine,
    FakeFetcher,
    RecordingEngine,
    make_app,
    make_targz,
    wait_terminal,
)
from starlette.testclient import TestClient

from texlate.arxiv.cache import SourceCache
from texlate.server.worker import PIPELINE_VERSION
from texlate.share import MANIFEST_NAME, pack_share
from texlate.xlat.pipeline import MockTranslator
from texlate.xlat.prompts import PROMPT_VERSION

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path
    from typing import Any

    import httpx
    from fastapi import FastAPI

_ARXIV = "2401.00003"


def _apps(
    tmp_path: Path, *, imp_engine: object | None = None
) -> tuple[FastAPI, FastAPI, Path]:
    """生产/导入双 app——独立 data_dir + SourceCache，同一 FakeFetcher 载荷。"""
    prod_engine = FakeEngine()
    prod = make_app(
        tmp_path / "pa",
        start_worker=True,
        translator_factory=lambda _ctx: MockTranslator(),
        engine_factory=lambda _name: prod_engine,
        fetcher=FakeFetcher(make_targz({"main.tex": MINI_TEX})),
        source_cache=SourceCache(tmp_path / "pa" / "src-cache"),
    )
    ie = imp_engine or FakeEngine()
    imp = make_app(
        tmp_path / "pb",
        start_worker=True,
        translator_factory=lambda _ctx: MockTranslator(),
        engine_factory=lambda _name: ie,
        fetcher=FakeFetcher(make_targz({"main.tex": MINI_TEX})),
        source_cache=SourceCache(tmp_path / "pb" / "src-cache"),
    )
    return prod, imp, tmp_path / "pa" / "data"


@pytest.fixture
def pair(
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,  # noqa: ARG001 -- fixture 副作用（env 清洗）
) -> Iterator[tuple[TestClient, TestClient, Path]]:
    """(生产端 client, 导入端 client, 生产端 data_dir)。"""
    prod, imp, ddir = _apps(tmp_path)
    with TestClient(prod) as pa, TestClient(imp) as pb:
        yield pa, pb, ddir


def _produce_pack(pa: TestClient, data_dir: Path, **kp_over: str) -> tuple[bytes, dict]:
    """生产端真跑 arxiv 任务 → 任务目录三件套 ``pack_share`` → (包字节, 快照)。"""
    r = pa.post(f"/api/arxiv/{_ARXIV}/translate", json={})
    assert r.status_code == HTTPStatus.ACCEPTED, r.text
    tid = r.json()["task_id"]
    snap = wait_terminal(pa, tid)
    assert snap["status"] == "done", snap
    parts = {
        "arxiv_id": _ARXIV,
        "version": "v1",
        "model": snap["model"],
        "prompt_ver": PROMPT_VERSION,
        "target_lang": snap["target_lang"],
        "glossary_hash": "",
        "pipeline_ver": PIPELINE_VERSION,
    }
    parts.update(kp_over)
    tdir = data_dir / "tasks" / tid
    return pack_share(tdir, parts, out_dir=tdir).read_bytes(), snap


def _synth_bundle(tmp_path: Path, chunks: list[dict], **kp_over: str) -> bytes:
    """手合成包（不过真管线）——dual.json chunks 内容完全可控。"""
    work = tmp_path / "synth"
    work.mkdir(exist_ok=True)
    (work / "zh.pdf").write_bytes(b"%PDF-1.4 synth")
    (work / "dual.json").write_text(
        json.dumps(
            {"version": 1, "documents": {}, "chunks": chunks}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    with zipfile.ZipFile(work / "zh-src.zip", "w") as zf:
        zf.writestr("main.tex", "\\documentclass{article}x")
    parts = {
        "arxiv_id": _ARXIV,
        "version": "v1",
        "model": "synth-model",
        "prompt_ver": PROMPT_VERSION,
        "target_lang": "zh-CN",
        "glossary_hash": "",
        "pipeline_ver": PIPELINE_VERSION,
    }
    parts.update(kp_over)
    return pack_share(work, parts, out_dir=tmp_path).read_bytes()


def _import(pb: TestClient, blob: bytes) -> httpx.Response:
    return pb.post(
        "/api/share/import",
        files={"file": ("community.share.zip", blob, "application/zip")},
    )


def _rezip(blob: bytes, **members: bytes) -> bytes:
    """重写 zip 指定成员（其余原样）——产物篡改构造。"""
    src = zipfile.ZipFile(io.BytesIO(blob))
    items = {n: src.read(n) for n in src.namelist()}
    src.close()
    items.update(members)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n, b in items.items():
            zf.writestr(n, b)
    return buf.getvalue()


def _repack_dual(
    blob: bytes, tmp_path: Path, edit: Callable[[dict[str, Any]], None]
) -> bytes:
    """解开包 → 改 dual.json → ``pack_share`` 重打（manifest 重新对账）。"""
    src = zipfile.ZipFile(io.BytesIO(blob))
    doc = json.loads(src.read(MANIFEST_NAME))
    work = tmp_path / "repack"
    work.mkdir(exist_ok=True)
    for name in doc["artifacts"]:
        (work / name).write_bytes(src.read(name))
    src.close()
    dual = json.loads((work / "dual.json").read_text(encoding="utf-8"))
    edit(dual)
    (work / "dual.json").write_text(
        json.dumps(dual, ensure_ascii=False), encoding="utf-8"
    )
    return pack_share(work, doc["key_parts"], out_dir=tmp_path).read_bytes()


class TestShareImport:
    def test_import_done(self, pair: tuple[TestClient, TestClient, Path]) -> None:
        """全链：导入 → done + 产物六件 + reader 200 + dual.json 含包译文。"""
        pa, pb, ddir = pair
        blob, prod_snap = _produce_pack(pa, ddir)
        r = _import(pb, blob)
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        tid = r.json()["task_id"]
        snap = wait_terminal(pb, tid)
        assert snap["status"] == "done", snap
        assert snap["kind"] == "share"
        assert snap["arxiv_id"] == f"{_ARXIV}v1"
        assert snap["model"] == prod_snap["model"]
        assert snap["target_lang"] == prod_snap["target_lang"]
        for kind in (
            "src_tar",
            "en_pdf",
            "zh_pdf",
            "zh_src_zip",
            "dual_json",
            "compile_log",
        ):
            assert kind in snap["artifacts"], snap["artifacts"]
        cnt = snap["counters"]
        assert cnt["total"] > 0
        assert cnt["done"] == cnt["total"]
        assert cnt["failed"] == 0
        r = pb.get(f"/api/task/{tid}/reader")
        assert r.status_code == HTTPStatus.OK
        doc = r.json()
        assert doc["documents"]["translated"]["url"] == f"/api/files/{tid}/zh.pdf"
        assert doc["documents"]["original"]["url"] == f"/api/files/{tid}/en.pdf"
        assert doc["view"] == "pdf"
        dual = pb.get(f"/api/files/{tid}/dual.json").json()
        assert dual["chunks"]
        assert all(c["zh"] for c in dual["chunks"])

    def test_import_reuse_and_later_request_hit(
        self, pair: tuple[TestClient, TestClient, Path]
    ) -> None:
        """钉版 cache_key：同包再导入 200 reuse；后来的 id@vN 请求也命中。"""
        pa, pb, ddir = pair
        blob, prod_snap = _produce_pack(pa, ddir)
        tid = _import(pb, blob).json()["task_id"]
        wait_terminal(pb, tid)
        r2 = _import(pb, blob)
        assert r2.status_code == HTTPStatus.OK, r2.text
        assert r2.json()["task_id"] == tid
        assert r2.json().get("reused") is True
        # 后来的普通请求：钉版形态 id@v1 + 同 model/lang → find_reusable 命中
        r3 = pb.post(
            f"/api/arxiv/{_ARXIV}v1/translate",
            json={"model": prod_snap["model"]},
        )
        assert r3.status_code == HTTPStatus.OK, r3.text
        assert r3.json()["task_id"] == tid
        assert r3.json().get("reused") is True

    def test_import_manifest_provenance(
        self, pair: tuple[TestClient, TestClient, Path]
    ) -> None:
        """manifest model 与上传者设置不同不拒——任务行记内容生产者真值。"""
        pa, pb, ddir = pair
        blob, _ = _produce_pack(pa, ddir, model="contributor-model-x")
        r = _import(pb, blob)
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        snap = wait_terminal(pb, r.json()["task_id"])
        assert snap["status"] == "done", snap
        assert snap["model"] == "contributor-model-x"

    def test_import_validate_fail_falls_back(
        self, pair: tuple[TestClient, TestClient, Path], tmp_path: Path
    ) -> None:
        """命中但 zh 过不过 L0（brace 失衡）→ fallback_orig + partial。"""
        pa, pb, ddir = pair
        blob, _ = _produce_pack(pa, ddir)

        def corrupt(dual: dict) -> None:
            dual["chunks"][0]["zh"] = "坏译文 }"

        evil = _repack_dual(blob, tmp_path, corrupt)
        r = _import(pb, evil)
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        snap = wait_terminal(pb, r.json()["task_id"])
        assert snap["status"] == "partial", snap
        assert snap["counters"]["failed"] == 1
        assert snap["error"]["code"] == "compile"
        assert snap["error"]["share"]["dropped"] == 1

    def test_import_zero_match_reject(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """包与本源全不对应（chunks 零命中）→ partial + share_verify。"""
        _prod, imp, _ddir = _apps(tmp_path)
        with TestClient(imp) as pb:
            blob = _synth_bundle(
                tmp_path,
                [
                    {
                        "seq": 0,
                        "src_file": "main.tex",
                        "en": "source text that does not exist locally",
                        "zh": "与本源无关的译文",
                        "kind": "text",
                    }
                ],
            )
            r = _import(pb, blob)
            assert r.status_code == HTTPStatus.ACCEPTED, r.text
            snap = wait_terminal(pb, r.json()["task_id"])
            assert snap["status"] == "partial"
            err = snap["error"]
            assert err["code"] == "share_verify"
            assert err["reject_at"] == "share_verify"
            assert "零命中" in err["message"]

    def test_import_compile_fail_reject(
        self, tmp_path: Path, clean_env: pytest.MonkeyPatch
    ) -> None:
        """本地重编不出 pdf → partial + share_verify（不信包内 zh.pdf）。"""
        clean_env.setenv("TEXLATE_NO_FIXLOOP", "1")
        clean_env.setenv("TEXLATE_NO_L2", "1")
        eng = RecordingEngine("fake")
        eng.produce_pdf = False
        prod, imp, ddir = _apps(tmp_path, imp_engine=eng)
        with TestClient(prod) as pa, TestClient(imp) as pb:
            blob, _ = _produce_pack(pa, ddir)
            r = _import(pb, blob)
            assert r.status_code == HTTPStatus.ACCEPTED, r.text
            snap = wait_terminal(pb, r.json()["task_id"])
            assert snap["status"] == "partial"
            err = snap["error"]
            assert err["code"] == "share_verify"
            assert err["reject_at"] == "share_verify"
            # 译文在库 → md.zip 降级产物照发
            assert "md_zip" in snap["artifacts"]


class TestShareImportBadBundle:
    """包级校验面——全是端点 4xx，不建行不入队。"""

    def test_import_tampered_artifact(
        self, pair: tuple[TestClient, TestClient, Path]
    ) -> None:
        """zh.pdf 成员被改 → sha256 对账不过 → 400 share_invalid。"""
        pa, pb, ddir = pair
        blob, _ = _produce_pack(pa, ddir)
        evil = _rezip(blob, **{"zh.pdf": b"%PDF-1.4 tampered"})
        r = _import(pb, evil)
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "share_invalid"

    def test_import_tampered_manifest(
        self, pair: tuple[TestClient, TestClient, Path]
    ) -> None:
        """key_parts 与 share_key 不自洽 → 400。"""
        pa, pb, ddir = pair
        blob, _ = _produce_pack(pa, ddir)
        src = zipfile.ZipFile(io.BytesIO(blob))
        doc = json.loads(src.read(MANIFEST_NAME))
        doc["key_parts"]["model"] = "tampered-model"
        src.close()
        evil = _rezip(blob, **{MANIFEST_NAME: json.dumps(doc).encode()})
        r = _import(pb, evil)
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "share_invalid"

    def test_import_not_zip(self, client: TestClient) -> None:
        r = client.post(
            "/api/share/import",
            files={"file": ("x.share.zip", b"not a zip", "application/zip")},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "share_invalid"

    def test_import_missing_file(self, client: TestClient) -> None:
        r = client.post("/api/share/import", data={"options": "{}"})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_import_bad_lang(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """key_parts.target_lang 不在 TARGET_LANGS → 400。"""
        _prod, imp, _ddir = _apps(tmp_path)
        with TestClient(imp) as pb:
            blob = _synth_bundle(tmp_path, [], target_lang="fr")
            r = _import(pb, blob)
            assert r.status_code == HTTPStatus.BAD_REQUEST
            assert r.json()["code"] == "share_invalid"

    def test_import_bad_version_form(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """key_parts.version 非 vN 钉版形（"vlatest"）→ 400。"""
        _prod, imp, _ddir = _apps(tmp_path)
        with TestClient(imp) as pb:
            blob = _synth_bundle(tmp_path, [], version="vlatest")
            r = _import(pb, blob)
            assert r.status_code == HTTPStatus.BAD_REQUEST
            assert r.json()["code"] == "share_invalid"


class TestShareImportCleanup:
    """解包后非预期异常（非 ShareError/_ApiError）→ 500 + 不留孤儿现场。"""

    def test_import_mid_error_no_orphan_dir(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,
    ) -> None:
        """``store.create_task`` 抛 ``sqlite3.OperationalError`` → 500，
        已建 ``tasks/{tid}``（bundle + 解包产物）一并收掉——upload B4 同口径。"""
        app = make_app(tmp_path)
        with TestClient(app, raise_server_exceptions=False) as c:

            def boom(*_a: object, **_kw: object) -> None:
                raise sqlite3.OperationalError

            clean_env.setattr(app.state.store, "create_task", boom)
            blob = _synth_bundle(tmp_path, [])
            r = c.post(
                "/api/share/import",
                files={"file": ("x.share.zip", blob, "application/zip")},
            )
            assert r.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            tasks_dir = app.state.data_dir / "tasks"
            assert not tasks_dir.exists() or list(tasks_dir.iterdir()) == []
