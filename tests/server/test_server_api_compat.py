"""api-compat 批：retry 换引擎清废 + hjfy 兼容端点 + share.zip 登记 + 单块重译。

- ``POST /api/task/{id}/retry`` body ``options.engine`` ≠ 上轮持久化的
  ``engine_resolved`` → 与换 main 同档清废（chunks/base/zh/build-*/
  派生产物行全抹，src/ 与 src_tar 保留）；同值/未带 engine 不动现场。
- ``GET /api/arxivStatus/{id}`` / ``GET /api/arxivFiles/{id}``：hjfy
  轮询兼容面——状态词汇映射、``{status,msg,data}`` 产物信封、404。
- ``POST /api/task/{id}/share/pack`` 成功后 ``tasks/{id}/share.zip``
  落盘 + files 登记 ``share_zip`` → manifest/下载路由可达。
- ``POST /api/task/{id}/chunk/{seq}/retranslate``：202 入队 + 守卫
  矩阵（非 done/partial 409、未知任务/seq 404、header 源缺 key 401）。
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING

from conftest import make_zip, mk_api_task, mk_chunk_row

from texlate.server.store import new_task_id

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from starlette.testclient import TestClient

    from texlate.server.store import Store

ARXIV = "2401.00001"
#: M1 缺 key 硬闸后，无 key 建行即 ``needs_auth`` 终态——需要 ``queued``/ACTIVE
#: 语义承载的用例统一带此头走 keyed 路径（local 形态 tenant 恒 "local"）。
KEY = {"X-Texlate-Key": "sk-test"}


class TestRetryEngineWipe:
    """``options.engine`` ≠ ``engine_resolved`` → 换 main 同档清废。"""

    def _seed(
        self,
        client: TestClient,
        store: Store,
        tmp_path: Path,
        *,
        engine_resolved: str | None = "tectonic",
    ) -> tuple[str, Path]:
        """fault 任务 + engine_resolved + chunks + 目录 + 产物行/磁盘件。"""
        tid = new_task_id()
        options = {"engine_resolved": engine_resolved} if engine_resolved else {}

        async def setup() -> None:
            store.create_task(
                task_id=tid,
                kind="arxiv",
                target_lang="zh-CN",
                model="m",
                arxiv_id=ARXIV,
                options=options,
            )
            store.update_fields(tid, main_tex="main.tex")
            store.insert_chunks(tid, [mk_chunk_row(0), mk_chunk_row(1)])
            store.transition(tid, "fault", force=True, error={"code": "compile"})

        client.portal.call(setup)
        tdir = tmp_path / "data" / "tasks" / tid
        for d in ("src", "base", "zh", "build-en", "build-zh"):
            (tdir / d).mkdir(parents=True)

        async def register() -> None:
            for kind, name in (
                ("src_tar", "src.tar"),
                ("en_pdf", "en.pdf"),
                ("zh_pdf", "zh.pdf"),
            ):
                (tdir / name).write_bytes(b"old")
                store.put_file(tid, kind, name, data_dir=tdir)

        client.portal.call(register)
        return tid, tdir

    def test_engine_change_wipes(self, client: TestClient, tmp_path: Path) -> None:
        """tectonic → xelatex：chunks/目录/派生产物与换 main 同档抹除。"""
        store = client.app.state.store
        tid, tdir = self._seed(client, store, tmp_path)
        r = client.post(
            f"/api/task/{tid}/retry", json={"options": {"engine": "xelatex"}}
        )
        assert r.status_code == HTTPStatus.ACCEPTED, r.text

        async def inspect() -> None:
            assert store.all_chunks(tid) == []
            for kind in ("en_pdf", "zh_pdf"):
                assert store.file_record(tid, kind) is None, kind
            assert store.file_record(tid, "src_tar") is not None
            assert store.get(tid)["status"] == "queued"
            opts = json.loads(str(store.get(tid)["options_json"]))
            assert opts["engine"] == "xelatex"

        client.portal.call(inspect)
        for d in ("base", "zh", "build-en", "build-zh"):
            assert not (tdir / d).exists(), d
        for name in ("en.pdf", "zh.pdf"):
            assert not (tdir / name).exists(), name
        assert (tdir / "src.tar").is_file()
        assert (tdir / "src").is_dir()

    def test_same_engine_keeps(self, client: TestClient, tmp_path: Path) -> None:
        """显式带与 resolved 同值的 engine → 一切保留。"""
        store = client.app.state.store
        tid, tdir = self._seed(client, store, tmp_path)
        r = client.post(
            f"/api/task/{tid}/retry", json={"options": {"engine": "tectonic"}}
        )
        assert r.status_code == HTTPStatus.ACCEPTED, r.text

        async def inspect() -> None:
            assert len(store.all_chunks(tid)) == 2  # noqa: PLR2004 -- 两块种子
            assert store.file_record(tid, "zh_pdf") is not None

        client.portal.call(inspect)
        assert (tdir / "zh.pdf").is_file()
        assert (tdir / "base").is_dir()

    def test_no_engine_keeps(self, client: TestClient, tmp_path: Path) -> None:
        """body 不带 engine → 一切保留。"""
        store = client.app.state.store
        tid, tdir = self._seed(client, store, tmp_path)
        r = client.post(f"/api/task/{tid}/retry", json={})
        assert r.status_code == HTTPStatus.ACCEPTED, r.text

        async def inspect() -> None:
            assert len(store.all_chunks(tid)) == 2  # noqa: PLR2004 -- 两块种子
            assert store.file_record(tid, "zh_pdf") is not None

        client.portal.call(inspect)
        assert (tdir / "base").is_dir()

    def test_engine_without_resolved_wipes(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """上轮未落 ``engine_resolved``（从未跑到编译）→ 显式 engine 即换档。"""
        store = client.app.state.store
        tid, tdir = self._seed(client, store, tmp_path, engine_resolved=None)
        r = client.post(
            f"/api/task/{tid}/retry", json={"options": {"engine": "xelatex"}}
        )
        assert r.status_code == HTTPStatus.ACCEPTED, r.text

        async def inspect() -> None:
            assert store.all_chunks(tid) == []
            assert store.file_record(tid, "zh_pdf") is None

        client.portal.call(inspect)
        assert not (tdir / "base").exists()


class TestArxivStatusCompat:
    """``GET /api/arxivStatus/{id}`` → hjfy ``{status, info}`` 词汇面。"""

    def test_active_maps_start(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV, headers=KEY)
        r = client.get(f"/api/arxivStatus/{ARXIV}")
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        assert body["status"] == "start"
        assert body["task_id"] == tid
        assert "info" in body
        assert "progress" in body

    def test_done_maps_finished(self, client: TestClient) -> None:
        store = client.app.state.store
        tid = mk_api_task(client, ARXIV)

        async def done() -> None:
            store.transition(tid, "done", force=True)

        client.portal.call(done)
        assert client.get(f"/api/arxivStatus/{ARXIV}").json()["status"] == ("finished")

    def test_fault_maps_fault(self, client: TestClient) -> None:
        store = client.app.state.store
        tid = mk_api_task(client, ARXIV)

        async def fault() -> None:
            store.transition(tid, "fault", force=True)

        client.portal.call(fault)
        assert client.get(f"/api/arxivStatus/{ARXIV}").json()["status"] == "fault"

    def test_versioned_lookup(self, client: TestClient) -> None:
        """钉版查询精确行；裸 id 经 GLOB 罩住 ``{base}vN`` 行。"""
        store = client.app.state.store
        tid = new_task_id()

        async def setup() -> None:
            store.create_task(
                task_id=tid,
                kind="share",
                target_lang="zh-CN",
                model="m",
                arxiv_id="2401.00002v2",
            )

        client.portal.call(setup)
        r = client.get("/api/arxivStatus/2401.00002v2")
        assert r.status_code == HTTPStatus.OK
        assert r.json()["task_id"] == tid
        r2 = client.get("/api/arxivStatus/2401.00002")
        assert r2.status_code == HTTPStatus.OK
        assert r2.json()["task_id"] == tid

    def test_latest_wins(self, client: TestClient) -> None:
        """同 arxiv_id 多行取 ``created_at`` 最新。"""
        store = client.app.state.store
        t1, t2 = new_task_id(), new_task_id()

        async def setup() -> None:
            for tid, ts in ((t1, 1000.0), (t2, 2000.0)):
                store.create_task(
                    task_id=tid,
                    kind="arxiv",
                    target_lang="zh-CN",
                    model="m",
                    arxiv_id="2401.00003",
                )
                store.update_fields(tid, created_at=ts)

        client.portal.call(setup)
        assert client.get("/api/arxivStatus/2401.00003").json()["task_id"] == t2

    def test_not_found(self, client: TestClient) -> None:
        r = client.get("/api/arxivStatus/2401.99999")
        assert r.status_code == HTTPStatus.NOT_FOUND
        assert r.json() == {"error": "not_found"}

    def test_invalid_id(self, client: TestClient) -> None:
        r = client.get("/api/arxivStatus/bad%20id%21")
        assert r.status_code == HTTPStatus.BAD_REQUEST


class TestArxivFilesCompat:
    """``GET /api/arxivFiles/{id}`` → hjfy ``{status, msg, data}`` 产物面。"""

    def _seed_done(self, client: TestClient) -> str:
        """done 任务 + en/zh pdf + zh-src.zip 产物行。"""
        store = client.app.state.store
        tid = new_task_id()

        async def setup() -> None:
            store.create_task(
                task_id=tid,
                kind="arxiv",
                target_lang="zh-CN",
                model="m",
                arxiv_id=ARXIV,
                title="T",
            )
            store.transition(tid, "done", force=True)
            store.put_file(tid, "en_pdf", "en.pdf", size=1, sha256="e")
            store.put_file(tid, "zh_pdf", "zh.pdf", size=1, sha256="z")
            store.put_file(tid, "zh_src_zip", "zh-src.zip", size=1, sha256="s")

        client.portal.call(setup)
        return tid

    def test_done_shape(self, client: TestClient) -> None:
        tid = self._seed_done(client)
        r = client.get(f"/api/arxivFiles/{ARXIV}")
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        assert body["status"] == 0
        data = body["data"]
        assert data["id"] == ARXIV
        assert data["title"] == "T"
        assert data["origin"] == f"/api/files/{tid}/en.pdf"
        assert data["zhCN"] == f"/api/files/{tid}/zh.pdf"
        assert data["zhCNTar"] == f"/api/files/{tid}/zh-src.zip"
        assert data["isDeepSeek"] is False

    def test_active_pending(self, client: TestClient) -> None:
        """进行中：status 0 + 「正在处理中」，产物 URL 空串。"""
        mk_api_task(client, ARXIV, headers=KEY)
        body = client.get(f"/api/arxivFiles/{ARXIV}").json()
        assert body["status"] == 0
        assert body["msg"] == "正在处理中"
        assert body["data"]["zhCN"] == ""
        assert body["data"]["origin"] == ""

    def test_needs_auth_101(self, client: TestClient) -> None:
        """needs_auth → status 101 + 「请登录」（hjfy 认证态词汇）。"""
        store = client.app.state.store
        tid = new_task_id()

        async def setup() -> None:
            store.create_task(
                task_id=tid,
                kind="arxiv",
                target_lang="zh-CN",
                model="m",
                arxiv_id=ARXIV,
                auth_source="header",
            )
            store.transition(tid, "needs_auth", force=True)

        client.portal.call(setup)
        body = client.get(f"/api/arxivFiles/{ARXIV}").json()
        assert body["status"] == 101  # noqa: PLR2004 -- hjfy 协议认证态码
        assert body["msg"] == "请登录"

    def test_fault_msg(self, client: TestClient) -> None:
        """终态无 zh_pdf → status 0 + message（hjfy dead 判定驱动文案）。"""
        store = client.app.state.store
        tid = new_task_id()

        async def setup() -> None:
            store.create_task(
                task_id=tid,
                kind="arxiv",
                target_lang="zh-CN",
                model="m",
                arxiv_id=ARXIV,
            )
            store.transition(tid, "fault", force=True, message="编译失败")

        client.portal.call(setup)
        body = client.get(f"/api/arxivFiles/{ARXIV}").json()
        assert body["status"] == 0
        assert body["msg"] == "编译失败"
        assert body["data"]["zhCN"] == ""

    def test_not_found(self, client: TestClient) -> None:
        r = client.get("/api/arxivFiles/2401.99999")
        assert r.status_code == HTTPStatus.NOT_FOUND
        assert r.json() == {"error": "not_found"}

    def test_invalid_id(self, client: TestClient) -> None:
        r = client.get("/api/arxivFiles/bad%20id%21")
        assert r.status_code == HTTPStatus.BAD_REQUEST


class TestShareZipArtifact:
    """``POST share/pack`` → ``tasks/{id}/share.zip`` 镜像 + ``share_zip`` 登记。"""

    def _seed_done(self, client: TestClient, tmp_path: Path) -> tuple[str, Path]:
        """done 任务 + ``REQUIRED_ARTIFACTS``（zh-src.zip + dual.json）。"""
        store = client.app.state.store
        tid = new_task_id()

        async def setup() -> None:
            store.create_task(
                task_id=tid,
                kind="arxiv",
                target_lang="zh-CN",
                model="m",
                arxiv_id=ARXIV,
            )
            store.transition(tid, "done", force=True)

        client.portal.call(setup)
        tdir = tmp_path / "data" / "tasks" / tid
        tdir.mkdir(parents=True)
        (tdir / "zh-src.zip").write_bytes(
            make_zip({"main.tex": "\\documentclass{article}"})
        )
        (tdir / "dual.json").write_text('{"chunks": []}', encoding="utf-8")
        return tid, tdir

    def test_pack_registers_share_zip(self, client: TestClient, tmp_path: Path) -> None:
        store = client.app.state.store
        tid, tdir = self._seed_done(client, tmp_path)
        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.OK, r.text
        body = r.json()
        assert body["share_key"]
        assert body["url"].endswith(".share.zip")

        assert (tdir / "share.zip").is_file()

        async def inspect() -> None:
            rec = store.file_record(tid, "share_zip")
            assert rec is not None
            assert rec["path"] == "share.zip"
            assert rec["bytes"] == (tdir / "share.zip").stat().st_size

        client.portal.call(inspect)

        manifest = client.get(f"/api/files/{tid}").json()["artifacts"]
        assert manifest["share_zip"]["url"] == f"/api/files/{tid}/share.zip"

        dl = client.get(f"/api/files/{tid}/share.zip")
        assert dl.status_code == HTTPStatus.OK
        assert dl.headers["content-type"] == "application/zip"

    def test_repack_recovers_registration(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """index 命中臂（二次 pack 不重打）同样补登记——手工摘行后重发自愈。"""
        store = client.app.state.store
        tid, tdir = self._seed_done(client, tmp_path)
        assert client.post(f"/api/task/{tid}/share/pack").status_code == (HTTPStatus.OK)

        async def wipe() -> None:
            store.delete_file(tid, "share_zip")
            (tdir / "share.zip").unlink()

        client.portal.call(wipe)

        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.OK, r.text
        assert (tdir / "share.zip").is_file()

        async def inspect() -> None:
            assert store.file_record(tid, "share_zip") is not None

        client.portal.call(inspect)


class TestRetranslate:
    """``POST /task/{id}/chunk/{seq}/retranslate`` 202 + 守卫矩阵。"""

    def _seed(self, client: TestClient, *, status: str = "done", **kw: object) -> str:
        store = client.app.state.store
        tid = new_task_id()

        async def setup() -> None:
            store.create_task(
                task_id=tid, kind="arxiv", target_lang="zh-CN", model="m", **kw
            )
            store.insert_chunks(tid, [mk_chunk_row(0), mk_chunk_row(1)])
            store.transition(tid, status, force=True)

        client.portal.call(setup)
        return tid

    def _spy(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> list:
        """``runner.enqueue_retranslate`` 桩 → 调用记录（不入队真 job）。"""
        calls: list[tuple] = []

        def fake(task_id: str, seq: int, secrets: object) -> None:
            calls.append((task_id, seq, secrets))

        monkeypatch.setattr(client.app.state.runner, "enqueue_retranslate", fake)
        return calls

    def test_202_enqueues(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._spy(client, monkeypatch)
        tid = self._seed(client)
        r = client.post(f"/api/task/{tid}/chunk/0/retranslate")
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        assert r.json() == {"task_id": tid, "seq": 0, "status": "queued"}
        assert len(calls) == 1
        assert calls[0][0] == tid
        assert calls[0][1] == 0

    def test_partial_ok(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._spy(client, monkeypatch)
        tid = self._seed(client, status="partial")
        r = client.post(f"/api/task/{tid}/chunk/1/retranslate")
        assert r.status_code == HTTPStatus.ACCEPTED, r.text

    def test_active_409(self, client: TestClient) -> None:
        """translating (ACTIVE)→ 409 invalid_state."""
        tid = self._seed(client, status="translating")
        r = client.post(f"/api/task/{tid}/chunk/0/retranslate")
        assert r.status_code == HTTPStatus.CONFLICT

    def test_fault_409(self, client: TestClient) -> None:
        """fault 终态也不可重译（仅 done/partial）→ 409。"""
        tid = self._seed(client, status="fault")
        r = client.post(f"/api/task/{tid}/chunk/0/retranslate")
        assert r.status_code == HTTPStatus.CONFLICT

    def test_unknown_task_404(self, client: TestClient) -> None:
        r = client.post(f"/api/task/{new_task_id()}/chunk/0/retranslate")
        assert r.status_code == HTTPStatus.NOT_FOUND

    def test_bad_seq_404(self, client: TestClient) -> None:
        tid = self._seed(client)
        r = client.post(f"/api/task/{tid}/chunk/99/retranslate")
        assert r.status_code == HTTPStatus.NOT_FOUND
        r2 = client.post(f"/api/task/{tid}/chunk/-1/retranslate")
        assert r2.status_code == HTTPStatus.NOT_FOUND

    def test_header_auth_missing_key_401(self, client: TestClient) -> None:
        """``auth_source=header`` 缺 X-Texlate-Key → 401（retry 同口径）。"""
        tid = self._seed(client, auth_source="header")
        r = client.post(f"/api/task/{tid}/chunk/0/retranslate")
        assert r.status_code == HTTPStatus.UNAUTHORIZED

    def test_header_auth_with_key_202(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """重带 key → 正常入队（secrets 走 header 决议）。"""
        calls = self._spy(client, monkeypatch)
        tid = self._seed(client, auth_source="header")
        r = client.post(
            f"/api/task/{tid}/chunk/0/retranslate",
            headers={"X-Texlate-Key": "sk-test"},
        )
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        assert len(calls) == 1
        assert calls[0][2].api_key == "sk-test"
