"""worker share 完成钩（task #92）：``options.share_pack`` opt-in →
``pack_share`` → ``index.jsonl`` 落行；错误纪律（打包失败不动任务终态）、
``kind=="share"`` 永不自包、无 arxiv_id 跳过、partial 包（无 zh.pdf）。
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from _drivekit import drive
from _workerkit import mk_ctx
from conftest import MINI_TEX, RecordingEngine

from texlate.compile.ctan import TlpdbIndex
from texlate.server.settings import share_dir
from texlate.server.worker import PIPELINE_VERSION
from texlate.share import REQUIRED_ARTIFACTS, index_lookup, unpack_share
from texlate.xlat.prompts import PROMPT_VERSION

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.server.store import Store
    from texlate.server.worker import PipelineWorker, TaskCtx


def _mk(
    tmp_path: Path,
    *,
    kind: str = "arxiv",
    arxiv_id: str | None = "2401.00001v2",
    options: dict[str, object] | None = None,
    worker_kw: dict[str, object] | None = None,
) -> tuple[TaskCtx, PipelineWorker, Store]:
    """真实任务行 + TaskCtx + worker（``_stage_compile`` 级直调面）。"""
    return mk_ctx(
        tmp_path,
        options=options,
        worker_kw={"deps_index": TlpdbIndex({}), **(worker_kw or {})},
        task_kw={"kind": kind, "arxiv_id": arxiv_id},
    )


def _seed_done(ctx: TaskCtx, store: Store, *, zh_src: bool = True) -> None:
    """预置 splice/compile 哨兵 + 产物——``_stage_compile`` 直抵 done 终态。"""
    ctx.main_rel = "main.tex"
    ctx.engine_name = "tectonic"
    ctx.base_dir.mkdir(parents=True, exist_ok=True)
    ctx.zh_dir.mkdir(parents=True, exist_ok=True)
    (ctx.zh_dir / ".splice-done").write_text("", encoding="utf-8")
    (ctx.zh_dir / ".compile-done").write_text("", encoding="utf-8")
    (ctx.root / "zh.pdf").write_bytes(b"%PDF-1.4 fake")
    (ctx.root / "en.pdf").write_bytes(b"%PDF-1.4 fake")
    store.put_file(ctx.task_id, "zh_pdf", "zh.pdf", data_dir=ctx.root)
    store.put_file(ctx.task_id, "en_pdf", "en.pdf", data_dir=ctx.root)
    if zh_src:
        with zipfile.ZipFile(ctx.root / "zh-src.zip", "w") as zf:
            zf.writestr("main.tex", MINI_TEX)
        store.put_file(ctx.task_id, "zh_src_zip", "zh-src.zip", data_dir=ctx.root)


def _events(store: Store, task_id: str, etype: str) -> list[dict[str, object]]:
    rows = store.conn.execute(
        "SELECT data FROM task_events WHERE task_id = ? AND type = ?",
        (task_id, etype),
    ).fetchall()
    return [json.loads(r["data"]) for r in rows]


class TestOptInPack:
    """opt-in 任务完成 → 包 + index 行；key_parts 七组分按库内现值派生。"""

    def test_done_packs_and_indexes(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path, options={"share_pack": True})
        _seed_done(ctx, store)
        drive(worker, worker._stage_compile(ctx))  # noqa: SLF001 -- 单测直驱
        assert store.get(ctx.task_id)["status"] == "done"
        share_root = share_dir(worker.data_dir)
        bundles = list(share_root.glob("*.share.zip"))
        assert len(bundles) == 1
        mf = unpack_share(bundles[0], tmp_path / "verify")
        assert mf.key_parts == {
            "arxiv_id": "2401.00001",
            "version": "v2",
            "model": "m",
            "prompt_ver": PROMPT_VERSION,
            "target_lang": "zh-CN",
            "glossary_hash": "",
            # parse 写回后实跑集入键——默认 fm={abstract,title}
            "front_matter": "abstract,title",
            "pipeline_ver": PIPELINE_VERSION,
        }
        # 全产物包：zh-src.zip + dual.json + zh.pdf 三件套在 manifest
        assert set(mf.artifacts) == {"zh-src.zip", "dual.json", "zh.pdf"}
        row = index_lookup(share_root / "index.jsonl", mf.share_key)
        assert row is not None
        assert row["url"] == bundles[0].name
        assert row["bytes"] == bundles[0].stat().st_size
        assert row["key_parts"] == mf.key_parts
        assert row["contributor"].startswith("c-")

    def test_opt_out_no_pack(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path)
        _seed_done(ctx, store)
        drive(worker, worker._stage_compile(ctx))  # noqa: SLF001 -- 单测直驱
        assert store.get(ctx.task_id)["status"] == "done"
        assert not share_dir(worker.data_dir).exists()

    def test_falsey_string_no_pack(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path, options={"share_pack": "off"})
        _seed_done(ctx, store)
        drive(worker, worker._stage_compile(ctx))  # noqa: SLF001 -- 单测直驱
        assert not share_dir(worker.data_dir).exists()


class TestGuards:
    """kind=share 永不自包；无 arxiv_id 跳过；reuse_hit 到不了本段。"""

    def test_share_kind_never_packs(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path, kind="share", options={"share_pack": True})
        _seed_done(ctx, store)
        drive(worker, worker._stage_compile(ctx))  # noqa: SLF001 -- 单测直驱
        assert not share_dir(worker.data_dir).exists()

    def test_no_arxiv_id_skips(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(
            tmp_path, kind="upload_tex", arxiv_id=None, options={"share_pack": True}
        )
        _seed_done(ctx, store)
        drive(worker, worker._stage_compile(ctx))  # noqa: SLF001 -- 单测直驱
        assert store.get(ctx.task_id)["status"] == "done"
        assert not share_dir(worker.data_dir).exists()
        logs = _events(store, ctx.task_id, "log")
        assert any("不参与共享寻址" in str(e.get("line")) for e in logs)


class TestErrorDiscipline:
    """打包失败只留 warning——任务终态与 done 事件不受牵连。"""

    def test_missing_artifact_keeps_done(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path, options={"share_pack": True})
        _seed_done(ctx, store, zh_src=False)  # zh-src.zip 缺席 → ShareError
        drive(worker, worker._stage_compile(ctx))  # noqa: SLF001 -- 单测直驱
        assert store.get(ctx.task_id)["status"] == "done"
        assert not share_dir(worker.data_dir).exists()
        warns = _events(store, ctx.task_id, "warning")
        assert any(e.get("code") == "share_pack" for e in warns)

    def test_direct_call_missing_artifacts(self, tmp_path: Path) -> None:
        """直调 ``_share_pack_try``：必需产物缺席 → ShareError 抛出（由钩壳吞）。"""
        from texlate.share import ShareError  # noqa: PLC0415

        ctx, worker, store = _mk(tmp_path, options={"share_pack": True})
        ctx.root.mkdir(parents=True, exist_ok=True)
        store.transition(ctx.task_id, "done", force=True)  # 本钩只在终态后被调
        with pytest.raises(ShareError, match="artifact missing"):
            worker._share_pack_try(ctx)  # noqa: SLF001


class TestPartialPack:
    """无 zh.pdf 的终态（fault/partial）仍打 partial 包（§9 已放行）。"""

    def test_fault_no_pdf_packs_partial(self, tmp_path: Path) -> None:
        eng = RecordingEngine("tectonic")
        eng.produce_pdf = False
        ctx, worker, store = _mk(
            tmp_path,
            options={"share_pack": True, "fixloop": False, "l2": False},
            worker_kw={"engine_factory": lambda _name: eng},
        )
        ctx.main_rel = "main.tex"
        ctx.engine_name = "tectonic"
        ctx.base_dir.mkdir(parents=True, exist_ok=True)
        ctx.zh_dir.mkdir(parents=True, exist_ok=True)
        (ctx.zh_dir / "main.tex").write_text(MINI_TEX, encoding="utf-8")
        (ctx.zh_dir / ".splice-done").write_text("", encoding="utf-8")
        with zipfile.ZipFile(ctx.root / "zh-src.zip", "w") as zf:
            zf.writestr("main.tex", MINI_TEX)
        store.put_file(ctx.task_id, "zh_src_zip", "zh-src.zip", data_dir=ctx.root)

        drive(worker, worker._stage_compile(ctx))  # noqa: SLF001 -- 单测直驱
        assert store.get(ctx.task_id)["status"] == "fault"
        share_root = share_dir(worker.data_dir)
        bundles = list(share_root.glob("*.share.zip"))
        assert len(bundles) == 1
        mf = unpack_share(bundles[0], tmp_path / "verify")
        assert set(mf.artifacts) == set(REQUIRED_ARTIFACTS)  # 无 zh.pdf 成员
        row = index_lookup(share_root / "index.jsonl", mf.share_key)
        assert row is not None


class TestGlossaryHash:
    """``glossary_hash`` 组分：local 层内容进指纹；无层 → ``""``。"""

    def test_local_layer_hashes(self, tmp_path: Path) -> None:
        ctx, worker, _store = _mk(tmp_path, options={"share_pack": True})
        ctx.base_dir.mkdir(parents=True, exist_ok=True)
        (ctx.base_dir / "glossary.local.yaml").write_text(
            "term: 术语\n", encoding="utf-8"
        )
        got = worker._share_glossary_hash(ctx, {})  # noqa: SLF001
        expect = hashlib.sha256(
            hashlib.sha256(b"term: \xe6\x9c\xaf\xe8\xaf\xad\n").digest()
        ).hexdigest()
        assert got == expect

    def test_no_layer_empty(self, tmp_path: Path) -> None:
        """无配置层且 USER_GLOSSARY_PATH 缺席（conftest 钉死）→ 空串。"""
        ctx, worker, _store = _mk(tmp_path)
        ctx.base_dir.mkdir(parents=True, exist_ok=True)
        assert worker._share_glossary_hash(ctx, {}) == ""  # noqa: SLF001

    def test_configured_glossary_hashes(self, tmp_path: Path) -> None:
        """配置 glossary 相对路径（confine 到 base/）→ 文件内容进指纹。"""
        ctx, worker, _store = _mk(tmp_path)
        ctx.base_dir.mkdir(parents=True, exist_ok=True)
        (ctx.base_dir / "g.yaml").write_text("a: b\n", encoding="utf-8")
        got = worker._share_glossary_hash(ctx, {"glossary": "g.yaml"})  # noqa: SLF001
        expect = hashlib.sha256(hashlib.sha256(b"a: b\n").digest()).hexdigest()
        assert got == expect
