"""``POST /api/task/{task_id}/share/pack`` 事后打包端点（task #120）：

终态任务 200 ``{share_key, url, bytes}`` + index 落行 + 幂等重放；
partial 包（无 zh.pdf）；404/409/422 守卫面（不存在/非终态/缺产物/
kind=share/reuse_hit/无 arxiv_id）。与完成钩 ``_share_pack_try`` 同口径。
"""

from __future__ import annotations

import asyncio
import json
import threading
import zipfile
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from conftest import MINI_TEX

from texlate.server.events import EventBus
from texlate.server.store import Store, new_task_id
from texlate.server.worker import PipelineWorker, Secrets, TaskCtx
from texlate.share import REQUIRED_ARTIFACTS, index_lookup, unpack_share
from texlate.xlat.prompts import PROMPT_VERSION

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.testclient import TestClient


def _mk_task(
    client: TestClient,
    *,
    kind: str = "arxiv",
    arxiv_id: str | None = "2401.00001v2",
    status: str = "done",
    options: dict[str, object] | None = None,
) -> str:
    """直建行 + force 迁终态（不跑 worker——产物由 ``_seed_artifacts`` 预置）。

    store conn 绑 portal 线程——一切 store 调用经 ``client.portal.call``。
    """
    store = client.app.state.store
    tid = new_task_id()
    client.portal.call(
        partial(
            store.create_task,
            task_id=tid,
            kind=kind,
            target_lang="zh-CN",
            model="m",
            arxiv_id=arxiv_id,
            options=options or {},
        )
    )
    client.portal.call(partial(store.transition, tid, status, force=True))
    return tid


def _seed_artifacts(client: TestClient, task_id: str, *, zh_pdf: bool = True) -> Path:
    """``tasks/{id}/`` 下落 zh-src.zip + dual.json（+ 可选 zh.pdf）。"""
    root = client.app.state.data_dir / "tasks" / task_id
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(root / "zh-src.zip", "w") as zf:
        zf.writestr("main.tex", MINI_TEX)
    (root / "dual.json").write_text(
        json.dumps({"documents": {}, "chunks": []}), encoding="utf-8"
    )
    if zh_pdf:
        (root / "zh.pdf").write_bytes(b"%PDF-1.4 fake")
    return root


def _share_root(client: TestClient) -> Path:
    """默认发布目录 ``<data_dir>/share``。"""
    return client.app.state.data_dir / "share"


class TestPostPack:
    """done 任务 → 包 + index 行；幂等重放不重复打包。"""

    def test_done_packs_and_indexes(self, client: TestClient, tmp_path: Path) -> None:
        tid = _mk_task(client)
        _seed_artifacts(client, tid)
        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        share_root = _share_root(client)
        bundle = share_root / body["url"]
        assert bundle.is_file()
        assert bundle.stat().st_size == body["bytes"]
        mf = unpack_share(bundle, tmp_path / "verify")
        assert mf.share_key == body["share_key"]
        assert mf.key_parts == {
            "arxiv_id": "2401.00001",
            "version": "v2",
            "model": "m",
            "prompt_ver": PROMPT_VERSION,
            "target_lang": "zh-CN",
            "glossary_hash": "",
            "pipeline_ver": mf.key_parts["pipeline_ver"],
        }
        assert set(mf.artifacts) == {"zh-src.zip", "dual.json", "zh.pdf"}
        row = index_lookup(share_root / "index.jsonl", mf.share_key)
        assert row is not None
        assert row["url"] == body["url"]
        assert row["bytes"] == body["bytes"]

    def test_idempotent_replay(self, client: TestClient) -> None:
        tid = _mk_task(client)
        _seed_artifacts(client, tid)
        r1 = client.post(f"/api/task/{tid}/share/pack")
        r2 = client.post(f"/api/task/{tid}/share/pack")
        assert r1.status_code == HTTPStatus.OK
        assert r2.status_code == HTTPStatus.OK
        assert r1.json() == r2.json()
        share_root = _share_root(client)
        # 单包 + 单 index 行——二次调用没重打没追加
        assert len(list(share_root.glob("*.share.zip"))) == 1
        lines = [
            ln
            for ln in (share_root / "index.jsonl").read_text().splitlines()
            if ln.strip()
        ]
        assert len(lines) == 1

    def test_partial_pack_without_pdf(self, client: TestClient) -> None:
        tid = _mk_task(client, status="partial")
        _seed_artifacts(client, tid, zh_pdf=False)
        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.OK
        share_root = _share_root(client)
        bundles = list(share_root.glob("*.share.zip"))
        assert len(bundles) == 1
        mf = unpack_share(bundles[0], client.app.state.data_dir / "verify")
        assert set(mf.artifacts) == set(REQUIRED_ARTIFACTS)  # 无 zh.pdf 成员

    def test_done_pack_opt_out_irrelevant(self, client: TestClient) -> None:
        """事后打包是显式用户动作——``options.share_pack`` opt-in 不参与判定。"""
        tid = _mk_task(client, options={"share_pack": False})
        _seed_artifacts(client, tid)
        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.OK


class TestIndexDegraded:
    """index.jsonl 降级面：读挂不挡重打、坏行按未命中处理——
    原 ``except ShareError`` 是死面（index_lookup 实抛
    OSError/UnicodeDecodeError），NUL url 让 stat() 抛 ValueError。"""

    def test_index_non_utf8_repacks(self, client: TestClient) -> None:
        """index 整体非 UTF-8 → 捕获降级重打 200（修前 UnicodeDecodeError → 500）。"""
        tid = _mk_task(client)
        _seed_artifacts(client, tid)
        share_root = _share_root(client)
        share_root.mkdir(parents=True)
        (share_root / "index.jsonl").write_bytes(b"\xff\xfe\x00not-utf8\n")
        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.OK
        url = r.json()["url"]
        assert (share_root / url).is_file()

    def test_index_nul_url_repacks(self, client: TestClient) -> None:
        """index 行 url 含 ``\\x00`` → 非扁平名落 miss 路径重打
        （修前过 flat 检查后 ``stat()`` 抛 ValueError → 500）。"""
        tid = _mk_task(client)
        _seed_artifacts(client, tid)
        r1 = client.post(f"/api/task/{tid}/share/pack")
        assert r1.status_code == HTTPStatus.OK
        key = r1.json()["share_key"]
        share_root = _share_root(client)
        with (share_root / "index.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps({"share_key": key, "url": "evil\x00name.share.zip"}) + "\n"
            )
        r2 = client.post(f"/api/task/{tid}/share/pack")
        assert r2.status_code == HTTPStatus.OK
        url = r2.json()["url"]
        assert "\x00" not in url
        assert "/" not in url
        assert (share_root / url).is_file()


class TestGuards:
    """404/409/422 守卫面——每种拒绝各一例。"""

    def test_404_missing(self, client: TestClient) -> None:
        r = client.post("/api/task/t_0000000000000000/share/pack")
        assert r.status_code == HTTPStatus.NOT_FOUND

    def test_409_non_terminal(self, client: TestClient) -> None:
        tid = _mk_task(client, status="queued")
        _seed_artifacts(client, tid)
        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.CONFLICT
        assert "detail" in r.json()
        # web 侧按 status 分支 + mock 钉死本码——与 invalid_transition 同义
        # 但属 share_pack 词表，改名须前后端同改（app-contracts 审计钉约）
        assert r.json()["code"] == "invalid_state"

    def test_422_missing_artifacts(self, client: TestClient) -> None:
        tid = _mk_task(client)
        (client.app.state.data_dir / "tasks" / tid).mkdir(parents=True)
        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert "zh-src.zip" in r.json()["detail"]

    def test_422_share_kind(self, client: TestClient) -> None:
        tid = _mk_task(client, kind="share")
        _seed_artifacts(client, tid)
        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert r.json()["code"] == "share_pack_rejected"

    def test_422_arxiv_html_kind(self, client: TestClient) -> None:
        """``kind=arxiv_html`` 按 kind 拒——产物齐也打不了：html 链产不出
        zh-src.zip，且 HTML chunk 与包内 TeX chunk 不对版不可比对。"""
        tid = _mk_task(client, kind="arxiv_html")
        _seed_artifacts(client, tid)
        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert r.json()["code"] == "share_pack_rejected"

    def test_422_reuse_hit(self, client: TestClient) -> None:
        tid = _mk_task(client, options={"reuse_hit": "t_deadbeefdeadbeef"})
        _seed_artifacts(client, tid)
        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert r.json()["code"] == "share_pack_rejected"

    def test_422_no_arxiv_id(self, client: TestClient) -> None:
        tid = _mk_task(client, kind="upload_tex", arxiv_id=None)
        _seed_artifacts(client, tid)
        r = client.post(f"/api/task/{tid}/share/pack")
        assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert r.json()["code"] == "share_pack_rejected"


def _mk_worker(tmp_path: Path) -> tuple[TaskCtx, PipelineWorker, Store]:
    """test_share_hook 同款直调面：真实任务行 + TaskCtx + worker。"""
    store = Store(tmp_path / "t.db")
    store.open()
    bus = EventBus(store)
    worker = PipelineWorker(store, bus, tmp_path)
    task_id = new_task_id()
    row = store.create_task(
        task_id=task_id,
        kind="upload_tex",
        target_lang="zh-CN",
        model="m",
        arxiv_id=None,
    )
    ctx = TaskCtx(
        store=store,
        bus=bus,
        task_id=task_id,
        row=row,
        secrets=Secrets(),
        root=tmp_path / "tasks" / task_id,
    )
    return ctx, worker, store


def _drive_fetch(ctx: TaskCtx, worker: PipelineWorker) -> None:
    async def drive() -> None:
        worker._loop = asyncio.get_running_loop()  # noqa: SLF001
        worker._loop_tid = threading.get_ident()  # noqa: SLF001
        await worker._stage_fetch(ctx)  # noqa: SLF001 -- 单测直驱

    asyncio.run(drive())


class TestReuseMarker:
    """``reuse_hit`` 行级标记：``_finish_reuse`` 写入、真跑取源摘除——
    端点 422 判定只读 options_json，标记生命周期由 worker 保证。"""

    def test_finish_reuse_writes_marker(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk_worker(tmp_path)
        hit = store.create_task(
            task_id=new_task_id(),
            kind="arxiv",
            target_lang="zh-CN",
            model="m",
            arxiv_id="2401.00001v1",
        )
        store.transition(str(hit["id"]), "done", force=True)
        worker._finish_reuse(ctx, store.get(str(hit["id"])) or {})  # noqa: SLF001
        opts = json.loads(str(store.get(ctx.task_id)["options_json"]))
        assert opts["reuse_hit"] == hit["id"]
        # ctx.row 内存面同步（与 arxiv_categories 写回同纪律）
        assert ctx.options()["reuse_hit"] == hit["id"]

    def test_real_fetch_clears_marker(self, tmp_path: Path) -> None:
        """reuse_hit 任务重试后真跑——.fetch-done 落盘即摘标记。"""
        ctx, worker, store = _mk_worker(tmp_path)
        opts = {"reuse_hit": "t_deadbeefdeadbeef"}
        store.update_fields(ctx.task_id, options_json=json.dumps(opts))
        ctx.row["options_json"] = json.dumps(opts)
        updir = ctx.root / "upload"
        updir.mkdir(parents=True)
        (updir / "main.tex").write_text(MINI_TEX, encoding="utf-8")
        _drive_fetch(ctx, worker)
        assert (ctx.src_dir / ".fetch-done").is_file()
        got = json.loads(str(store.get(ctx.task_id)["options_json"]))
        assert "reuse_hit" not in got
