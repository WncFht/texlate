"""server 抛光包：F3 reject→partial 一致性、glossary.local 层、ToUnicode 注入、任务删除端点、跨租户 reuse 语义钉样。"""

from __future__ import annotations

import json
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from conftest import (
    FakeEngine,
    make_app,
    upload_tex,
    wait_terminal,
)
from starlette.testclient import TestClient

from texlate.server.events import EventBus
from texlate.server.store import ERROR_CODES, Store
from texlate.server.worker import (
    PipelineWorker,
    Secrets,
    TaskCtx,
    embed_cjk_mappings,
)
from texlate.xlat.pipeline import MockTranslator

if TYPE_CHECKING:
    from pathlib import Path


class TestF3RejectPartial:
    """F3：策略拒绝归 ``partial`` + ``reject_at`` 审计档（e2e verdict 同形）。"""

    def test_no_main_tex_route_reject(self, live_client: TestClient) -> None:
        """无 ``\\documentclass``/``\\begin{document}`` 的上传 → partial+reject_at=route。"""
        body = upload_tex(live_client, tex="just some prose, no preamble at all\n")
        snap = wait_terminal(live_client, body["task_id"])
        assert snap["status"] == "partial"
        err = snap["error"]
        assert err["code"] == "route_reject"
        assert err["reject_at"] == "route"
        assert err["retryable"] is False
        assert "no main tex" in err["message"]

    def test_route_reject_explicit(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """``route_project.reject`` 置位 → partial+reject_at=route（当前路由恒
        None——monkeypatch 钉住分支语义，防将来真实拒绝回 fault）。"""
        import texlate.server.worker as worker_mod  # noqa: PLC0415
        from texlate.compile.engine import RouteDecision  # noqa: PLC0415

        monkeypatch.setattr(
            worker_mod,
            "route_project",
            lambda _root: RouteDecision(
                engines=[], reject="policy_deny", reasons=["deny"]
            ),
        )
        app = make_app(
            tmp_path,
            start_worker=True,
            translator_factory=lambda _ctx: MockTranslator(),
            engine_factory=lambda _name: FakeEngine(),
        )
        with TestClient(app) as c:
            tid = upload_tex(c)["task_id"]
            snap = wait_terminal(c, tid)
        assert snap["status"] == "partial"
        assert snap["error"]["reject_at"] == "route"
        assert "policy_deny" in snap["error"]["message"]

    def test_inject_reject_partial(self, live_client: TestClient) -> None:
        r"""``\documentstyle``（LaTeX 2.09）：route 降级放行 → inject 兜底拒 →
        partial+reject_at=inject，且 zh-src.zip 已落盘（译文 splice 降级交付）。"""
        tex209 = (
            "\\documentstyle{ias}\n"
            "\\begin{document}\n"
            "A paragraph of English text long enough to form a chunk.\n"
            "\\end{document}\n"
        )
        body = upload_tex(live_client, tex=tex209)
        snap = wait_terminal(live_client, body["task_id"])
        assert snap["status"] == "partial"
        err = snap["error"]
        assert err["code"] == "inject_reject"
        assert err["reject_at"] == "inject"
        assert "zh_src_zip" in snap["artifacts"]

    def test_reject_codes_registered(self) -> None:
        assert "route_reject" in ERROR_CODES
        assert "inject_reject" in ERROR_CODES


# ------------------------------------------------------------ glossary local


def _glossary_ctx(
    tmp_path: Path, options: dict[str, object] | None = None
) -> tuple[TaskCtx, PipelineWorker]:
    """最小 TaskCtx + worker（glossary/cache 装配面单测用）。"""
    store = Store(tmp_path / "t.db")
    store.open()
    bus = EventBus(store)
    worker = PipelineWorker(store, bus, tmp_path)
    ctx = TaskCtx(
        store=store,
        bus=bus,
        task_id="t_ctx",
        row={
            "config_json": "{}",
            "options_json": json.dumps(options or {}),
            "model": "m",
            "target_lang": "zh-CN",
        },
        secrets=Secrets(),
        root=tmp_path / "task",
    )
    return ctx, worker


class TestLocalGlossary:
    """``base/glossary.local.yaml`` → ``Glossary.load`` local 层（§三级表第②档）。"""

    def test_local_layer_merged(self, tmp_path: Path) -> None:
        ctx, worker = _glossary_ctx(tmp_path)
        ctx.base_dir.mkdir(parents=True)
        (ctx.base_dir / "glossary.local.yaml").write_text(
            "transformer: 变形金刚\n", encoding="utf-8"
        )
        g = worker._make_glossary(ctx)  # noqa: SLF001 -- 装配面即被测对象
        assert g is not None
        entry = g.terms.get("transformer")
        assert entry is not None
        assert entry.zh == "变形金刚"
        assert entry.source == "local"

    def test_user_overrides_local(self, tmp_path: Path) -> None:
        """user 层（options.glossary，confine 在 base/ 内）优先于 local 层。"""
        ctx, worker = _glossary_ctx(tmp_path, options={"glossary": "user.yaml"})
        ctx.base_dir.mkdir(parents=True)
        (ctx.base_dir / "glossary.local.yaml").write_text(
            "transformer: 变形金刚\n", encoding="utf-8"
        )
        (ctx.base_dir / "user.yaml").write_text(
            "transformer: 变换器\n", encoding="utf-8"
        )
        g = worker._make_glossary(ctx)  # noqa: SLF001
        assert g is not None
        assert g.terms["transformer"].zh == "变换器"
        assert g.terms["transformer"].source == "user"

    def test_no_base_dir_no_crash(self, tmp_path: Path) -> None:
        """docx/epub/pdf 路无 ``base/`` ——local 层缺省不炸。"""
        ctx, worker = _glossary_ctx(tmp_path)
        g = worker._make_glossary(ctx)  # noqa: SLF001
        assert g is not None
        assert "transformer" not in g.terms

    def test_cache_prefix_tracks_local(self, tmp_path: Path) -> None:
        """local 层有无/内容变更进段缓存指纹——防跨任务译文污染。"""
        ctx, worker = _glossary_ctx(tmp_path)
        ctx.base_dir.mkdir(parents=True)
        cache1 = worker._make_cache(ctx)  # noqa: SLF001
        cache1["s"] = "t"
        key1 = cache1.drain()[0][0]
        (ctx.base_dir / "glossary.local.yaml").write_text(
            "transformer: 变形金刚\n", encoding="utf-8"
        )
        cache2 = worker._make_cache(ctx)  # noqa: SLF001
        cache2["s"] = "t"
        key2 = cache2.drain()[0][0]
        assert key1 != key2
        (ctx.base_dir / "glossary.local.yaml").write_text(
            "transformer: 变换器\n", encoding="utf-8"
        )
        cache3 = worker._make_cache(ctx)  # noqa: SLF001
        cache3["s"] = "t"
        assert cache3.drain()[0][0] not in (key1, key2)

    def test_cache_prefix_tracks_base_url(self, tmp_path: Path) -> None:
        """base_url 进段缓存指纹——同名 model 换后端不混桶（spec-xlat #7）。"""
        ctx_a, worker_a = _glossary_ctx(tmp_path / "a")
        ctx_a.secrets.base_url = "http://100.0.0.1:3003"
        ctx_b, worker_b = _glossary_ctx(tmp_path / "b")
        ctx_b.secrets.base_url = "https://api.example.com"
        ka = worker_a._make_cache(ctx_a)  # noqa: SLF001
        ka["s"] = "t"
        kb = worker_b._make_cache(ctx_b)  # noqa: SLF001
        kb["s"] = "t"
        key_a, key_b = ka.drain()[0][0], kb.drain()[0][0]
        assert key_a != key_b
        ctx_c, worker_c = _glossary_ctx(tmp_path / "c")
        ctx_c.secrets.base_url = ""
        kc = worker_c._make_cache(ctx_c)  # noqa: SLF001
        kc["s"] = "t"
        assert kc.drain()[0][0] != key_b


# ------------------------------------------------------------ ToUnicode 注入


class TestEmbedCjkMappings:
    """embed_cjk_mappings：GB1/Identity-H 无 ToUnicode → 注 Adobe-GB1-UCS2。"""

    def _pdf(self, tmp_path: Path, **kw: object) -> Path:
        from pypdf import PdfWriter  # noqa: PLC0415
        from pypdf.generic import (  # noqa: PLC0415
            ArrayObject,
            DecodedStreamObject,
            DictionaryObject,
            NameObject,
            NumberObject,
            TextStringObject,
        )

        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        page = w.pages[0]
        cid_sys = DictionaryObject(
            {
                NameObject("/Registry"): TextStringObject("Adobe"),
                NameObject("/Ordering"): TextStringObject(str(kw["ordering"])),
                NameObject("/Supplement"): NumberObject(5),
            }
        )
        cid_font = w._add_object(  # noqa: SLF001
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/CIDFontType0"),
                    NameObject("/BaseFont"): NameObject("/FandolSong-Regular"),
                    NameObject("/CIDSystemInfo"): cid_sys,
                }
            )
        )
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type0"),
                NameObject("/BaseFont"): NameObject("/Fandol-Regular-Identity-H"),
                NameObject("/Encoding"): NameObject("/Identity-H"),
                NameObject("/DescendantFonts"): ArrayObject([cid_font]),
            }
        )
        if kw["with_tu"]:
            tu = DecodedStreamObject()
            tu.set_data(b"begincmap\nendcmap\n")
            font[NameObject("/ToUnicode")] = w._add_object(  # noqa: SLF001
                tu.flate_encode()
            )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F5"): font})}
        )
        out = tmp_path / "probe.pdf"
        with out.open("wb") as fh:
            w.write(fh)
        w.close()
        return out

    def test_injects_gb1_font(self, tmp_path: Path) -> None:
        from pypdf import PdfReader  # noqa: PLC0415

        pdf = self._pdf(tmp_path, ordering="GB1", with_tu=False)
        assert embed_cjk_mappings(pdf) == 1
        font = PdfReader(str(pdf)).pages[0]["/Resources"]["/Font"]["/F5"].get_object()
        tu = font["/ToUnicode"].get_object()
        assert b"Adobe-GB1-UCS2" in tu.get_data()

    def test_skips_identity_ordering(self, tmp_path: Path) -> None:
        """Ordering=Identity（CID=GID）字体注 GB1 cmap 反而写错——不碰。"""
        pdf = self._pdf(tmp_path, ordering="Identity", with_tu=False)
        assert embed_cjk_mappings(pdf) == 0
        from pypdf import PdfReader  # noqa: PLC0415

        font = PdfReader(str(pdf)).pages[0]["/Resources"]["/Font"]["/F5"].get_object()
        assert "/ToUnicode" not in font

    def test_skips_existing_tounicode(self, tmp_path: Path) -> None:
        pdf = self._pdf(tmp_path, ordering="GB1", with_tu=True)
        assert embed_cjk_mappings(pdf) == 0


# ------------------------------------------------------------ 任务删除端点


class TestTaskDelete:
    def test_delete_terminal(self, client: TestClient, tmp_path: Path) -> None:
        tid = upload_tex(client)["task_id"]
        client.post(f"/api/task/{tid}/cancel")
        tdir = tmp_path / "data" / "tasks" / tid
        assert tdir.is_dir()  # upload/ blob 落盘于建行时
        r = client.delete(f"/api/task/{tid}")
        assert r.status_code == HTTPStatus.OK
        assert r.json()["status"] == "deleted"
        assert client.get(f"/api/task/{tid}").status_code == HTTPStatus.NOT_FOUND
        assert client.get(f"/api/files/{tid}").status_code == HTTPStatus.NOT_FOUND
        assert client.get("/api/tasks").json()["tasks"] == []
        assert not tdir.exists()

    def test_delete_active_409(self, client: TestClient) -> None:
        tid = upload_tex(client)["task_id"]  # queued = ACTIVE
        r = client.delete(f"/api/task/{tid}")
        assert r.status_code == HTTPStatus.CONFLICT
        assert r.json()["code"] == "invalid_transition"
        assert client.get(f"/api/task/{tid}").status_code == HTTPStatus.OK

    def test_delete_404(self, client: TestClient) -> None:
        assert (
            client.delete("/api/task/t_0000000000000000").status_code
            == HTTPStatus.NOT_FOUND
        )
        assert client.delete("/api/task/garbage").status_code == HTTPStatus.NOT_FOUND

    def test_delete_idempotent_second_404(self, client: TestClient) -> None:
        tid = upload_tex(client)["task_id"]
        client.post(f"/api/task/{tid}/cancel")
        assert client.delete(f"/api/task/{tid}").status_code == HTTPStatus.OK
        assert client.delete(f"/api/task/{tid}").status_code == HTTPStatus.NOT_FOUND

    def test_delete_cascades_children(self, client: TestClient) -> None:
        """chunks/files/task_events 随 tasks 行级联删（FK ON DELETE CASCADE）。"""
        tid = upload_tex(client)["task_id"]
        store = client.app.state.store
        client.portal.call(partial(store.put_file, tid, "src_tar", "upload/main.tex"))
        client.portal.call(
            partial(
                store.insert_chunks,
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
        client.post(f"/api/task/{tid}/cancel")
        assert client.delete(f"/api/task/{tid}").status_code == HTTPStatus.OK
        rows = client.portal.call(
            partial(
                lambda: {
                    "chunks": store.conn.execute(
                        "SELECT COUNT(*) AS c FROM chunks WHERE task_id = ?",
                        (tid,),
                    ).fetchone()["c"],
                    "files": store.conn.execute(
                        "SELECT COUNT(*) AS c FROM files WHERE task_id = ?",
                        (tid,),
                    ).fetchone()["c"],
                    "events": store.conn.execute(
                        "SELECT COUNT(*) AS c FROM task_events WHERE task_id = ?",
                        (tid,),
                    ).fetchone()["c"],
                }
            )
        )
        assert rows == {"chunks": 0, "files": 0, "events": 0}

    def test_delete_tenant_isolated(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """server 模式：租户 B 删不到租户 A 的任务（404 存在性遮蔽）。"""
        monkeypatch.setenv("TEXLATE_MODE", "server")
        r = client.post(
            "/api/arxiv/2401.00009/translate",
            json={"model": "m"},
            headers={"X-Texlate-Key": "k-A"},
        )
        tid = r.json()["task_id"]
        client.post(f"/api/task/{tid}/cancel", headers={"X-Texlate-Key": "k-A"})
        assert (
            client.delete(
                f"/api/task/{tid}", headers={"X-Texlate-Key": "k-B"}
            ).status_code
            == HTTPStatus.NOT_FOUND
        )
        # 本租户可删
        assert (
            client.delete(
                f"/api/task/{tid}", headers={"X-Texlate-Key": "k-A"}
            ).status_code
            == HTTPStatus.OK
        )


# ------------------------------------------------------------ 跨租户 reuse（§4.3 既定特性钉样）


class TestCrossTenantReuse:
    """shared scope 下跨租户 reuse 是产品特性（hjfy 对等共享缓存）——
    存在性 oracle 的消除通道是 ``TEXLATE_CACHE_SCOPE=per_key``，钉两态。"""

    _ARXIV = "2401.00011"

    def test_shared_scope_reuses_across_tenants(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEXLATE_MODE", "server")
        hdr_a = {"X-Texlate-Key": "k-A"}
        hdr_b = {"X-Texlate-Key": "k-B"}
        tid = client.post(
            f"/api/arxiv/{self._ARXIV}/translate",
            json={"model": "m"},
            headers=hdr_a,
        ).json()["task_id"]
        store = client.app.state.store
        client.portal.call(partial(store.transition, tid, "done", force=True))
        r = client.post(
            f"/api/arxiv/{self._ARXIV}/translate",
            json={"model": "m"},
            headers=hdr_b,
        )
        assert r.status_code == HTTPStatus.OK
        assert r.json()["reused"] is True
        assert r.json()["task_id"] == tid  # A 的任务 id 回到 B——oracle 即特性

    def test_per_key_scope_no_cross_reuse(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEXLATE_MODE", "server")
        monkeypatch.setenv("TEXLATE_CACHE_SCOPE", "per_key")
        hdr_a = {"X-Texlate-Key": "k-A"}
        hdr_b = {"X-Texlate-Key": "k-B"}
        tid = client.post(
            f"/api/arxiv/{self._ARXIV}/translate",
            json={"model": "m"},
            headers=hdr_a,
        ).json()["task_id"]
        store = client.app.state.store
        client.portal.call(partial(store.transition, tid, "done", force=True))
        r = client.post(
            f"/api/arxiv/{self._ARXIV}/translate",
            json={"model": "m"},
            headers=hdr_b,
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        assert r.json()["task_id"] != tid
