"""worker.py 审计修复批（task #52）逐条钉样：ph 武装 / glossary 五层 /
cancel 孤儿 / 旁路 usage+ 术语 / _build_dual 出 loop / queued 重放 /
_stage 终态守卫 / zip 前缀冲突 / IndirectObject 字体 / _spawn pty fd 清理。

题域切出：fixloop → test_worker_fixloop.py；share → test_worker_share.py；
parse 段 → test_worker_parse.py；server settings/salt → test_server_settings.py。"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import sqlite3
import threading
import zipfile
from pathlib import Path

import pytest
from _drivekit import drive
from _workerkit import mk_ctx, scan_base
from conftest import MINI_TEX, FakeFetcher, make_targz

import texlate.server.babeldoc as babeldoc_mod
import texlate.server.worker as worker_mod
from texlate.arxiv.cache import SourceCache
from texlate.arxiv.meta import PaperMeta
from texlate.arxiv.unpack import UnpackError
from texlate.compile.cjkmap import embed_cjk_mappings
from texlate.compile.engine import CompRes, LogInfo
from texlate.pipecore import front_matter_of
from texlate.server.events import EventBus
from texlate.server.store import Store, StoreError, new_task_id
from texlate.server.worker import (
    DBStateBridge,
    PipelineWorker,
    Secrets,
    SegmentCache,
    TaskCtx,
    TaskRunner,
    cache_key_for,
    chunk_db_id,
    unpack_zip,
)
from texlate.xlat.client import ChatClient
from texlate.xlat.pipeline import (
    ChunkIn,
    MockTranslator,
    PipelineConfig,
    XlatPipeline,
)
from texlate.xlat.state import ChunkRecord

_MATH_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "A paragraph that has inline math $x+y$ and a command \\alpha that "
    "sits inside the prose.\n"
    "\n"
    "Second paragraph that pads the document body and fills it with the "
    "text that was written for this purpose.\n"
    "\\end{document}\n"
)

_ENV_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "First paragraph of English prose that is long enough, with the words "
    "and the phrases that make it a real chunk.\n"
    "\n"
    "\\begin{weirdbox}\n"
    "Some content inside a weird environment.\n"
    "\\end{weirdbox}\n"
    "\n"
    "Trailing paragraph.\n"
    "\\end{document}\n"
)


class TestPhFragments:
    """Fix1：主链 ChunkIn 带 ph_fragments——``_repair_fn``/``recover_copied_tokens`` 得武装。"""

    def test_frag_map_and_pipe_inputs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        ctx, worker, store = mk_ctx(
            tmp_path,
            # M1 后无 key 直调 translate 段撞 AuthError——注入 factory 桩显式 mock 臂
            worker_kw={"translator_factory": lambda _ctx: MockTranslator()},
        )
        scan_base(ctx, worker, store, _MATH_TEX)
        frag_of = worker._ph_frag_map(ctx)  # noqa: SLF001
        math_cid = next(cid for cid, m in frag_of.items() if "$x+y$" in m.values())

        captured: list[ChunkIn] = []

        async def fake_run(_self: XlatPipeline, chunks: list[ChunkIn]) -> list:
            captured.extend(chunks)
            return []

        monkeypatch.setattr(XlatPipeline, "run", fake_run)
        asyncio.run(worker.run_stage(ctx, "stage_translate"))
        math_in = next(c for c in captured if c.chunk_id == math_cid)
        assert math_in.ph_fragments == frag_of[math_cid]
        assert math_in.ph_fragments is not None
        assert "$x+y$" in math_in.ph_fragments.values()


class TestGlossaryLayers:
    """Fix2：``_make_glossary`` 四层——categories（arxiv 分类）等真术语层。

    v5：⑤层 ph→ph 恒等注入已删——占位符点名册改走
    ``pipeline._materialize`` → ``render_placeholder_manifest`` 单行压
    ``<Glossary>`` 块末行（TestBypassArms 的 L2 面有实证）。
    """

    def test_categories_layer(self, tmp_path: Path) -> None:
        ctx, worker, _store = mk_ctx(tmp_path, options={"arxiv_categories": ["cs.LG"]})
        g = worker._make_glossary(ctx)  # noqa: SLF001
        assert g is not None
        cat_terms = {en for en, t in g.terms.items() if t.source == "category:cs.LG"}
        assert "Abstractive Summarization" in cat_terms

    def test_no_placeholder_identity_rows(self, tmp_path: Path) -> None:
        """v5：恒等注入层已删——术语表里无 ``[[X_n]]: [[X_n]]`` 行。"""
        ctx, worker, _store = mk_ctx(tmp_path)
        g = worker._make_glossary(ctx)  # noqa: SLF001
        assert g is not None
        assert not any(en.startswith("[[") and t.zh == en for en, t in g.terms.items())

    def test_fetch_arxiv_persists_categories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """fetch_metadata → ``options.arxiv_categories`` 落库 + ctx.row 同步（resume 路径）。"""
        ctx, worker, store = mk_ctx(
            tmp_path,
            worker_kw={
                "fetcher": FakeFetcher(make_targz({"main.tex": MINI_TEX})),
                "source_cache": SourceCache(tmp_path / "src-cache"),
            },
        )
        monkeypatch.setattr(
            "texlate.server.worker.seams.fetch_metadata",
            lambda arxiv_id, *, fetcher: PaperMeta(  # noqa: ARG005
                arxiv_id=arxiv_id,
                resolved_version=1,
                primary_category="cs.LG",
                categories=("cs.LG", "stat.ML"),
            ),
        )
        ctx.root.mkdir(parents=True, exist_ok=True)
        worker.run_stage(ctx, "fetch_arxiv")
        assert ctx.options()["arxiv_categories"] == ["cs.LG", "stat.ML"]
        db_opts = json.loads(str(store.get(ctx.task_id)["options_json"]))
        assert db_opts["arxiv_categories"] == ["cs.LG", "stat.ML"]
        g = worker._make_glossary(ctx)  # noqa: SLF001
        assert g is not None
        assert any(t.source == "category:cs.LG" for t in g.terms.values())

    def test_fetch_arxiv_meta_failure_tolerated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """fetch_metadata 返回 None → 主链照样走（无 categories 键）。"""
        ctx, worker, _store = mk_ctx(
            tmp_path,
            worker_kw={
                "fetcher": FakeFetcher(make_targz({"main.tex": MINI_TEX})),
                "source_cache": SourceCache(tmp_path / "src-cache"),
            },
        )
        monkeypatch.setattr(
            "texlate.server.worker.seams.fetch_metadata",
            lambda _id, *, fetcher: None,  # noqa: ARG005
        )
        ctx.root.mkdir(parents=True, exist_ok=True)
        worker.run_stage(ctx, "fetch_arxiv")
        assert "arxiv_categories" not in ctx.options()
        assert (ctx.src_dir / "main.tex").is_file()


class TestCancelOrphan:
    """Fix3：cancel 竞态后 run_task 不再孤儿化。"""

    def test_teardown_cancels_pending_run_task(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)

        async def drive() -> asyncio.Task[list]:
            async def never() -> list:
                await asyncio.sleep(3600)
                return []  # pragma: no cover

            t = asyncio.create_task(never())
            await asyncio.sleep(0)  # 让它先跑起来
            await worker.run_stage(  # run_stage 直驱
                ctx,
                "teardown_translate",
                run_task=t,
                state=DBStateBridge(store, ctx.task_id),
                cache=SegmentCache(store, prefix="t", model="m", target_lang="zh-CN"),
                status_map={},
                sse_items=[],
                usage={"calls": 0},
                clients=[],
                pre_rows={},
            )
            return t

        t = asyncio.run(drive())
        assert t.cancelled()


class _JudgeFake:
    """env_judge 旁路假翻译：``.client`` 挂真 ChatClient 当 usage_sink 接线面。"""

    def __init__(self, answer: str = "false") -> None:
        self.client = ChatClient("http://127.0.0.1:9", "k")
        self._answer = answer

    async def translate(self, **_kw: object) -> str:
        if self.client.usage_sink is not None:
            self.client.usage_sink(
                {
                    "model": "m",
                    "prompt_tokens": 5,
                    "completion_tokens": 3,
                    "latency_s": 0.1,
                }
            )
        return self._answer


class TestBypassArms:
    """Fix4：env_judge/L2 旁路 pipe 的 glossary 物化 + usage 记账。"""

    def test_env_judge_usage_recorded(self, tmp_path: Path) -> None:
        fake = _JudgeFake()
        ctx, worker, store = mk_ctx(
            tmp_path,
            options={"env_judge": True},
            worker_kw={"translator_factory": lambda _ctx: fake},
        )
        scan_base(ctx, worker, store, _ENV_TEX)
        env_cid = next(
            chunk_db_id(rel, c.span.start, c.span.end)
            for rel, res in ctx.scans.items()
            for c in res.chunks
            if c.env == "weirdbox"
        )
        out = worker._env_judge_filter(  # noqa: SLF001
            ctx, {env_cid: "假译文"}, store.all_chunks(ctx.task_id)
        )
        assert env_cid not in out, "判 false 的块应回落原文"
        u = store.usage_for(ctx.task_id)
        assert u is not None
        assert u["prompt_tokens"] == 5  # noqa: PLR2004 -- judge 一次调用的真账
        ch = {c["chunk_id"]: c for c in store.all_chunks(ctx.task_id)}[env_cid]
        assert ch["status"] == "fallback_orig"
        assert ch["error_code"] == "env_judge"

    def test_l2_pipe_glossary_materialized(self, tmp_path: Path) -> None:
        """L2 旁路 pipe：glossary 挂上 + ``_materialize`` 跑过 + 不共享主链段缓存。"""
        ctx, worker, store = mk_ctx(
            tmp_path,
            worker_kw={"translator_factory": lambda _c: MockTranslator()},
        )
        scan_base(ctx, worker, store, _MATH_TEX)
        ph = next(
            t
            for res in ctx.scans.values()
            for t, frag in res.ph_map.items()
            if "x+y" in frag
        )
        run, _db = worker._l2_run_state(ctx, ctx.root / "build-zh")  # noqa: SLF001
        assert run.pipe.glossary is not None
        # v5：ph 不进 _doc_glossary（恒等行已删）——改在 manifest 点名
        assert run.pipe._doc_glossary.get(ph) != ph  # noqa: SLF001
        assert ph in run.pipe._ph_manifest  # noqa: SLF001
        assert run.pipe.cache is None


class TestBuildDualThread:
    """Fix6：``_build_dual`` 在 worker 线程跑（store 读经 ``_on_loop`` 回弹）。"""

    def test_build_dual_off_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        ctx.root.mkdir(parents=True, exist_ok=True)
        (ctx.root / "en.pdf").write_bytes(b"%PDF-1.4 fake")
        (ctx.root / "zh.pdf").write_bytes(b"%PDF-1.4 fake")
        store.put_file(ctx.task_id, "en_pdf", "en.pdf", data_dir=ctx.root)
        store.put_file(ctx.task_id, "zh_pdf", "zh.pdf", data_dir=ctx.root)

        real_align = worker_mod.build_alignment
        seen_tid: list[int] = []

        def spy_align(en: Path, zh: Path) -> dict:
            seen_tid.append(threading.get_ident())
            return real_align(en, zh)

        monkeypatch.setattr(worker_mod.seams, "build_alignment", spy_align)

        drive(worker, asyncio.to_thread(worker._build_dual, ctx))  # noqa: SLF001
        loop_tid = worker._loop_tid  # noqa: SLF001
        assert seen_tid, "build_alignment 应被调用"
        assert seen_tid[0] != loop_tid, "pypdf 对齐扫描必须跑在非 loop 线程"
        doc = json.loads((ctx.root / "dual.json").read_text(encoding="utf-8"))
        assert doc["documents"]["translated"]["pages"] == 0  # 假 pdf 页数兜底
        assert store.file_record(ctx.task_id, "dual_json") is not None


class TestRecoverStartupQueued:
    """Fix7：queued 行启动分流——header→needs_auth，其余 TaskRunner 重放。"""

    def test_queued_header_to_needs_auth(self, tmp_path: Path) -> None:
        store = Store(tmp_path / "t.db")
        store.open()
        try:
            hdr = store.create_task(
                task_id=new_task_id(),
                kind="arxiv",
                target_lang="zh-CN",
                model="m",
                auth_source="header",
            )
            keep = store.create_task(
                task_id=new_task_id(),
                kind="arxiv",
                target_lang="zh-CN",
                model="m",
                auth_source="settings",
            )
            out = store.recover_startup()
            assert out["needs_auth"] == 1
            assert store.get(hdr["id"])["status"] == "needs_auth"
            assert store.get(keep["id"])["status"] == "queued"
        finally:
            store.close()

    def test_replay_queued_skips_header(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        store = Store(tmp_path / "t.db")
        store.open()
        try:
            bus = EventBus(store)
            worker = PipelineWorker(store, bus, tmp_path)
            runner = TaskRunner(store, bus, worker)
            keep = store.create_task(
                task_id=new_task_id(),
                kind="arxiv",
                target_lang="zh-CN",
                model="m9",
            )
            store.create_task(
                task_id=new_task_id(),
                kind="arxiv",
                target_lang="zh-CN",
                model="m",
                auth_source="header",
            )

            async def drive() -> int:
                runner._queue = asyncio.Queue()  # noqa: SLF001
                runner._replay_queued()  # noqa: SLF001
                return runner._queue.qsize()  # noqa: SLF001

            assert asyncio.run(drive()) == 1, (
                "header 源 queued 行防御性排除（recover_startup 已分流）"
            )
            sec = runner.secrets.get(keep["id"])
            assert sec is not None
            assert sec.model == "m9"
        finally:
            store.close()


class TestStageTerminalGuard:
    """Fix8：cancel TOCTOU——``_stage`` 不再覆写终态。"""

    def test_stage_noop_after_terminal(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        store.transition(ctx.task_id, "cancelled")
        seq0 = store.last_seq(ctx.task_id)
        worker.run_stage(ctx, "stage", "translating", "翻译中", 25)
        row = store.get(ctx.task_id)
        assert row["status"] == "cancelled"
        assert store.last_seq(ctx.task_id) == seq0, "终态后不许再发 stage 事件"


class TestUnpackZipClash:
    """Fix9：成员路径段撞已落文件——前缀逐级检测而非只查直接 parent。"""

    def _zip(self, members: list[tuple[str, bytes]]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, data in members:
                zf.writestr(name, data)
        return buf.getvalue()

    def test_file_then_nested_member(self, tmp_path: Path) -> None:
        """``a``（文件）先于 ``a/b/c.txt``——深层成员前缀撞文件须拒。"""
        data = self._zip([("a", b"x"), ("a/b/c.txt", b"y")])
        warnings = unpack_zip(data, tmp_path)
        assert "reject_dir_clash:a/b/c.txt" in warnings
        assert (tmp_path / "a").read_bytes() == b"x"
        assert not (tmp_path / "a" / "b" / "c.txt").exists()

    def test_nested_then_file_member(self, tmp_path: Path) -> None:
        """``a/b/c.txt`` 先于 ``a``——后者 target 撞已建目录须拒。"""
        data = self._zip([("a/b/c.txt", b"y"), ("a", b"x")])
        warnings = unpack_zip(data, tmp_path)
        assert "reject_dir_clash:a" in warnings
        assert (tmp_path / "a" / "b" / "c.txt").read_bytes() == b"y"


class TestIndirectFontDict:
    """Fix10：``/Font`` 值为 IndirectObject 时不再 AttributeError 静默丢 ToUnicode。"""

    def test_indirect_font_resources(self, tmp_path: Path) -> None:
        from pypdf import PdfReader, PdfWriter  # noqa: PLC0415
        from pypdf.generic import (  # noqa: PLC0415
            ArrayObject,
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
                NameObject("/Ordering"): TextStringObject("GB1"),
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
        # 关键差异：/Font 整体作为间接对象挂进 Resources（真实生成器常态）；
        # /F5 值也走间接引用——两层 deref 都得走
        f5_ref = w._add_object(font)  # noqa: SLF001
        fonts_ref = w._add_object(  # noqa: SLF001
            DictionaryObject({NameObject("/F5"): f5_ref})
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): fonts_ref}
        )
        pdf = tmp_path / "indirect.pdf"
        with pdf.open("wb") as fh:
            w.write(fh)
        w.close()
        assert embed_cjk_mappings(pdf) == 1
        got = PdfReader(str(pdf)).pages[0]["/Resources"]["/Font"]["/F5"].get_object()
        assert "/ToUnicode" in got


class TestPostResolveDedup:
    """#74：latest-alias 任务 fetch 定版后按钉版键二次 dedup + re-key。"""

    def _mk_alias(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        kind: str = "arxiv",
    ) -> tuple[TaskCtx, PipelineWorker, Store]:
        ctx, worker, store = mk_ctx(
            tmp_path,
            worker_kw={
                "fetcher": FakeFetcher(make_targz({"main.tex": MINI_TEX})),
                "source_cache": SourceCache(tmp_path / "src-cache"),
            },
        )
        monkeypatch.setattr(
            "texlate.server.worker.seams.fetch_metadata",
            lambda _id, *, fetcher: None,  # noqa: ARG005
        )
        if kind != "arxiv":
            ctx.row["kind"] = kind
        # FakeFetcher 恒解析 v1——alias 键（ver=None）≠ 钉版键（ver=1）。
        # enqueue 对缺省 options 也进 fm 成分（front_matter_of 解析缺省
        # {abstract,title}）——fixture 与 enqueue 同料
        alias_key = cache_key_for(
            arxiv_id="2401.00001",
            version=None,
            model="m",
            target_lang="zh-CN",
            front_matter=front_matter_of({}),
        )
        store.update_fields(ctx.task_id, cache_key=alias_key)
        ctx.row["cache_key"] = alias_key
        return ctx, worker, store

    def _resolved_key(self) -> str:
        return cache_key_for(
            arxiv_id="2401.00001",
            version=1,
            model="m",
            target_lang="zh-CN",
            front_matter=front_matter_of({}),
        )

    def _hit_task(self, tmp_path: Path, store: Store) -> str:
        """钉版键已完成任务 + zh.pdf 产物（reuse 命中源）。"""
        hit_id = new_task_id()
        store.create_task(
            task_id=hit_id,
            kind="arxiv",
            target_lang="zh-CN",
            model="m",
            arxiv_id="2401.00001v1",
            cache_key=self._resolved_key(),
        )
        hit_root = tmp_path / "tasks" / hit_id
        hit_root.mkdir(parents=True)
        (hit_root / "zh.pdf").write_bytes(b"%PDF-1.4 hit")
        store.put_file(hit_id, "zh_pdf", "zh.pdf", data_dir=hit_root)
        store.transition(hit_id, "done", force=True)
        return hit_id

    def test_second_dedup_hit(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """钉版键有完成行 → 产物物化 + 终态 done，parse/translate 不跑。"""
        ctx, worker, store = self._mk_alias(tmp_path, monkeypatch)
        self._hit_task(tmp_path, store)
        drive(worker, worker.run_stage(ctx, "run_tex"))
        row = store.get(ctx.task_id)
        assert row["status"] == "done"
        assert (ctx.root / "zh.pdf").read_bytes() == b"%PDF-1.4 hit"
        assert store.file_record(ctx.task_id, "zh_pdf") is not None
        assert not (ctx.src_dir / ".fetch-done").exists(), "reuse 短路不落哨兵"
        assert not ctx.src_dir.exists(), "reuse 短路不拷源树"
        assert not store.has_chunks(ctx.task_id), "翻译/解析段未跑"

    def test_rekey_when_no_hit(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """无命中 → 行 re-key 成钉版形（后来的 id@vN 请求 enqueue 即中）。"""
        ctx, worker, store = self._mk_alias(tmp_path, monkeypatch)
        ctx.root.mkdir(parents=True, exist_ok=True)
        worker.run_stage(ctx, "fetch_arxiv")
        assert store.get(ctx.task_id)["cache_key"] == self._resolved_key()
        assert ctx.reuse_hit is None
        assert (ctx.src_dir / "main.tex").is_file(), "未命中照常落源树"

    def test_fresh_skips_dedup(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """``prefer=fresh`` 不查 reuse 也不 re-key。"""
        ctx, worker, store = self._mk_alias(tmp_path, monkeypatch)
        store.update_fields(ctx.task_id, options_json=json.dumps({"prefer": "fresh"}))
        ctx.row["options_json"] = json.dumps({"prefer": "fresh"})
        self._hit_task(tmp_path, store)
        ctx.root.mkdir(parents=True, exist_ok=True)
        worker.run_stage(ctx, "fetch_arxiv")
        assert ctx.reuse_hit is None
        assert store.get(ctx.task_id)["cache_key"] == ctx.row["cache_key"]
        assert (ctx.src_dir / "main.tex").is_file()

    def test_cancelled_not_resurrected(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """fetch 期间用户 cancel → reuse 命中也只得保持 cancelled。"""
        ctx, worker, store = self._mk_alias(tmp_path, monkeypatch)
        self._hit_task(tmp_path, store)
        store.transition(ctx.task_id, "cancelled")
        drive(worker, worker.run_stage(ctx, "run_tex"))
        row = store.get(ctx.task_id)
        assert row["status"] == "cancelled"
        assert not (ctx.root / "zh.pdf").exists()


_EOF_LOG = """This is XeTeX, Version 3.14159
(./main.tex
(./lib/blob.tex
! Paragraph ended before \\pgffor@var@add was complete.
<to be read again>
l.30 \\foreach\\i
)
./preprint.cls:163: File ended while scanning use of \\pgffor@var@add
l.163 \\input{lib/blob.tex}
"""

_ATTR_MAIN_TEX = (
    "\\documentclass{article}\n"
    "\\usepackage{xcolor}\n"
    "\\definecolor{brand}{RGB}{1,2,3}\n"
    "\\begin{document}\n"
    "A paragraph of English prose long enough to be a real chunk here.\n"
    "\\end{document}\n"
)

_ATTR_BLOB_TEX = (
    "First blob paragraph with enough English prose to be a real chunk.\n"
    "\n"
    "Second blob paragraph, also long enough to be a real chunk here.\n"
)


class TestL2EofAttribution:
    """#78：runaway/EOF 错报父文件续行位——``)`` 弹出的文件才是真肇事者。"""

    def test_eof_file_recorded(self) -> None:
        """``parse_log_text``：File-ended 错回填最近弹出的文件 token。"""
        from texlate.validate.l2 import parse_log_text  # noqa: PLC0415

        v = parse_log_text(_EOF_LOG)
        assert v.n_errors == 2  # noqa: PLR2004 -- fixture 形态断言
        bang, fileline = v.errors
        assert bang.eof_file is None, "行中 Paragraph-ended 错不走 eof 改派"
        assert fileline.tex_file == "./preprint.cls"
        assert fileline.eof_file == "./lib/blob.tex"

    def test_attr_eof_remap(self, tmp_path: Path) -> None:
        """``L2Attr.attr_error``：eof_file 改派肇事文件，行号丢弃。"""
        from texlate.latex.api import parse_file  # noqa: PLC0415
        from texlate.repair_l2 import L2Attr, TreeRun  # noqa: PLC0415
        from texlate.validate.l2 import LogError  # noqa: PLC0415

        work = tmp_path / "work"
        (work / "lib").mkdir(parents=True)
        (work / "main.tex").write_text(_ATTR_MAIN_TEX, encoding="utf-8")
        (work / "lib" / "blob.tex").write_text(_ATTR_BLOB_TEX, encoding="utf-8")
        run = TreeRun(
            scans=[
                (work / "main.tex", parse_file(work / "main.tex", flatten=False)),
                (
                    work / "lib" / "blob.tex",
                    parse_file(work / "lib" / "blob.tex", flatten=False),
                ),
            ],
            trans={},
            chunk_ins={},
            pipe=XlatPipeline(MockTranslator(), config=PipelineConfig()),
        )
        st = L2Attr(run, work)
        blob_cids = [c.id for c in run.scans[1][1].chunks]
        assert blob_cids, "fixture 应产出 blob chunk"

        err = LogError(
            line_no=7,
            head="./preprint.cls:163: File ended while scanning use of \\pgffor@var@add",
            tex_file="./preprint.cls",
            tex_line=163,
            file_stack=("./main.tex", "./preprint.cls"),
            eof_file="./lib/blob.tex",
        )
        fidx, cids = st.attr_error(err)  # type: ignore[misc]
        assert fidx == 1
        assert sorted(cids) == sorted(blob_cids), "归肇事文件整体而非父文件续行"

    def test_attr_forward_exclusion(self, tmp_path: Path) -> None:
        """起点越过错误行行尾的块被顺序读取不变量排除（repro-2501 形态）。"""
        from texlate.latex.api import parse_file  # noqa: PLC0415
        from texlate.repair_l2 import L2Attr, TreeRun  # noqa: PLC0415
        from texlate.validate.l2 import LogError  # noqa: PLC0415

        work = tmp_path / "work"
        work.mkdir(parents=True)
        (work / "main.tex").write_text(_ATTR_MAIN_TEX, encoding="utf-8")
        res = parse_file(work / "main.tex", flatten=False)
        assert res.chunks, "fixture 应产出 chunk"
        run = TreeRun(
            scans=[(work / "main.tex", res)],
            trans={},
            chunk_ins={},
            pipe=XlatPipeline(MockTranslator(), config=PipelineConfig()),
        )
        st = L2Attr(run, work)
        # preamble 错（l.3 \\definecolor）——首个 chunk 在 \\begin{document} 之后
        got = st.attr_error(
            LogError(
                line_no=1,
                head="./main.tex:3: Undefined control sequence.",
                tex_file="./main.tex",
                tex_line=3,
            )
        )
        assert got == (0, []), "错误行之后才开始的块不该被 forward-fallback 错归"
        # 对照：chunk 所在行的错误照常命中
        para_line = (
            _ATTR_MAIN_TEX[: _ATTR_MAIN_TEX.index("A paragraph")].count("\n") + 1
        )
        got2 = st.attr_error(
            LogError(
                line_no=2,
                head="./main.tex:5: Undefined control sequence.",
                tex_file="./main.tex",
                tex_line=para_line,
            )
        )
        assert got2 == (0, [res.chunks[0].id])


class TestChunkSpansMirror:
    """``chunk_spans`` 镜像 ``reconstruct`` 落盘字节：译文侧变换逐项复刻。

    ``LATIN_ITEM_RX`` 保险丝与 ``seg_join`` 接缝守卫缺一则 ``find`` 失配、
    块归 ``None``，L2 归因静默丢块（``4ce255e`` short_arg 同款漂移）。
    """

    def test_translated_transforms_mirrored(self) -> None:
        from texlate.latex import parse_tex  # noqa: PLC0415
        from texlate.latex.reconstruct import reconstruct  # noqa: PLC0415
        from texlate.repair_l2 import chunk_spans  # noqa: PLC0415

        tex = (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "First paragraph text here with enough words to chunk.\n"
            "\n"
            "Second paragraph text here with enough words to chunk.\n"
            "\\end{document}\n"
        )
        res = parse_tex(tex)
        c0, c1 = res.chunks[:2]
        trans = {
            c0.id: "Vector \\itemFSU 内容",
            c1.id: f"前缀 \\foo[[CHUNK_{c0.id}]] 后缀",
        }
        disk = reconstruct(res, trans)
        assert "\\item FSU 内容" in disk  # LATIN_ITEM_RX 保险丝生效
        assert "\\foo Vector \\item FSU 内容" in disk  # seg_join 接缝插空格
        spans = chunk_spans(disk, res, trans)
        assert spans[c0.id] is not None
        assert spans[c1.id] is not None


class TestHeartbeatLoop:
    """``_heartbeat_loop``：store 故障只留 debug 痕，ticker 不死（sweep 钉样）。"""

    def test_survives_store_error_and_current_clear(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = Store(tmp_path / "t.db")
        store.open()
        try:
            bus = EventBus(store)
            worker = PipelineWorker(store, bus, tmp_path)
            runner = TaskRunner(store, bus, worker)
            calls = 0

            def _boom(_task_id: str) -> None:
                nonlocal calls
                calls += 1
                msg = "disk gone"
                raise StoreError(msg)

            monkeypatch.setattr(store, "heartbeat", _boom)
            monkeypatch.setattr("texlate.server.worker.seams._HEARTBEAT_S", 0.01)

            ctx = TaskCtx(
                store=store,
                bus=bus,
                task_id="t1",
                row={},
                secrets=Secrets(),
                root=tmp_path,
            )

            async def drive() -> None:
                dummy = asyncio.create_task(asyncio.sleep(60))
                runner._current = (ctx.task_id, ctx, dummy)  # noqa: SLF001
                ticker = asyncio.create_task(runner._heartbeat_loop())  # noqa: SLF001
                await asyncio.sleep(0.05)
                runner._current = None  # noqa: SLF001 -- 中途清当前任务不得崩 ticker
                await asyncio.sleep(0.03)
                assert not ticker.done(), "heartbeat 失败/_current 清空不得杀 ticker"
                ticker.cancel()
                dummy.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ticker
                with contextlib.suppress(asyncio.CancelledError):
                    await dummy

            asyncio.run(drive())
            assert calls, "heartbeat 必须真打过拍"
        finally:
            store.close()


class TestDocEmitTerminalGuard:
    """#148：``_doc_emit`` 终态守卫——cancel 后孤儿 export thread 的迟到 emit 不落盘/扇出。"""

    def test_emit_noop_after_terminal(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        payload = {"done": 1, "total": 0, "cached": 0, "failed": 0, "items": []}
        worker._doc_emit(ctx, 1, 0, 10, payload)  # noqa: SLF001
        assert store.get(ctx.task_id)["done_chunks"] == 1
        store.transition(ctx.task_id, "cancelled")
        seq0 = store.last_seq(ctx.task_id)
        worker._doc_emit(ctx, 9, 9, 99, payload)  # noqa: SLF001
        row = store.get(ctx.task_id)
        assert row["done_chunks"] == 1, "终态后 emit 不许覆写"
        assert row["tokens"] != 99  # noqa: PLR2004 -- 迟到 tokens 不落库
        assert store.last_seq(ctx.task_id) == seq0, "终态后不许再发 chunk 事件"


class TestPersistUsageReplace:
    """#148：doc 路唯一记账臂用真账**替换**字符估算（``_teardown_translate`` 同口径）。"""

    def _usage(self) -> dict[str, object]:
        return {
            "calls": 1,
            "prompt_tokens": 5,
            "completion_tokens": 3,
            "latency_s": 0.1,
            "model": "m",
        }

    def test_replace_est(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        ctx.tokens_est = 100  # on_result 累积的字符估算钉样
        worker.run_stage(ctx, "persist_usage", self._usage(), replace_est=True)
        assert ctx.tokens_est == 8  # noqa: PLR2004 -- 5+3 真账，est 被替换不叠加
        assert store.get(ctx.task_id)["tokens"] == 8  # noqa: PLR2004

    def test_default_accumulates(self, tmp_path: Path) -> None:
        """旁路臂（env_judge/L2/llm_hook）保持累加——不抹主链真账。"""
        ctx, worker, _store = mk_ctx(tmp_path)
        ctx.tokens_est = 100  # 主链真账钉样
        worker.run_stage(ctx, "persist_usage", self._usage())
        assert ctx.tokens_est == 108  # noqa: PLR2004 -- 100+5+3


class TestPrepHarvestDirs:
    """#148：``_prep_pdf_dirs``/``_harvest_pdf_outputs`` 物化语义钉样。"""

    def test_prep_pdf_dirs(self, tmp_path: Path) -> None:
        """en.pdf 回登记 + 旧产物清理；en.pdf 在场不覆盖（retry 幂等）。"""
        ctx, worker, store = mk_ctx(tmp_path)
        src = ctx.root / "upload" / "paper.pdf"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"%PDF-1.4 up")
        outdir = ctx.root / "babeldoc-out"
        workdir = ctx.root / "babeldoc-work"
        outdir.mkdir(parents=True)
        (outdir / "stale").write_text("x", encoding="utf-8")
        workdir.mkdir()
        worker._prep_pdf_dirs(ctx, src, outdir, workdir)  # noqa: SLF001
        assert (ctx.root / "en.pdf").read_bytes() == b"%PDF-1.4 up"
        assert store.file_record(ctx.task_id, "en_pdf") is not None
        assert not outdir.exists()
        assert not workdir.exists()
        src.write_bytes(b"%PDF-1.4 new")
        worker._prep_pdf_dirs(ctx, src, outdir, workdir)  # noqa: SLF001
        assert (ctx.root / "en.pdf").read_bytes() == b"%PDF-1.4 up"

    def test_harvest_pdf_outputs(self, tmp_path: Path) -> None:
        """mono/dual → zh.pdf/dual.pdf + 登记；tounicode 失败 best-effort。"""
        from texlate.server.babeldoc import BabeldocRun  # noqa: PLC0415

        ctx, worker, store = mk_ctx(tmp_path)
        ctx.root.mkdir(parents=True, exist_ok=True)
        mono = ctx.root / "out" / "mono.pdf"
        dual = ctx.root / "out" / "dual.pdf"
        mono.parent.mkdir(parents=True)
        mono.write_bytes(b"%PDF-1.4 mono")
        dual.write_bytes(b"%PDF-1.4 dual")
        run = BabeldocRun(
            rc=0,
            seconds=1.0,
            status="ok",
            outputs={"mono": mono, "dual": dual},
        )
        worker._harvest_pdf_outputs(ctx, run)  # noqa: SLF001
        assert (ctx.root / "zh.pdf").read_bytes() == b"%PDF-1.4 mono"
        assert (ctx.root / "dual.pdf").read_bytes() == b"%PDF-1.4 dual"
        assert store.file_record(ctx.task_id, "zh_pdf") is not None
        assert store.file_record(ctx.task_id, "dual_pdf") is not None


class TestAcloseTolerated:
    """#148：旁路 client aclose 崩溃 → debug 留痕不拖垮段收尾（``_run_doc`` 同款）。"""

    def test_teardown_llm_hook_aclose_boom(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx, worker, _store = mk_ctx(tmp_path)

        async def boom(_clients: list) -> None:
            msg = "aclose boom"
            raise RuntimeError(msg)

        monkeypatch.setattr(worker_mod.seams, "_aclose_clients", boom)
        client = ChatClient("http://127.0.0.1:9", "k")
        worker._teardown_llm_hook(ctx, None, [client])  # noqa: SLF001 -- 不抛即过


class TestOptIntTolerant:
    """#148 追加：存量 options_json 残留非数值 → 默认 + warning，不裸 int() 崩。"""

    def test_opt_int_values(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        assert worker._opt_int(ctx, {}, "qps", 4) == 4  # noqa: SLF001, PLR2004
        assert worker._opt_int(ctx, {"qps": "8"}, "qps", 4) == 8  # noqa: SLF001, PLR2004
        seq0 = store.last_seq(ctx.task_id)
        assert worker._opt_int(ctx, {"qps": "abc"}, "qps", 4) == 4  # noqa: SLF001, PLR2004
        evs = store.events_since(ctx.task_id, seq0)
        assert any(
            e["type"] == "warning" and e["data"]["code"] == "bad_option" for e in evs
        )

    def test_babeldoc_job_bad_qps(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """存量行 ``options.qps="abc"`` → job 落默认不 500。"""
        ctx, worker, _store = mk_ctx(tmp_path, options={"qps": "abc"})
        ctx.secrets = Secrets(api_key="k")
        workdir = ctx.root / "bw"
        workdir.mkdir(parents=True, exist_ok=True)
        job = worker._babeldoc_job(  # noqa: SLF001
            ctx, ctx.root / "up.pdf", ctx.root / "out", workdir
        )
        assert job.qps == 4  # noqa: PLR2004 -- 默认钉样


class TestRegisterPrecomputed:
    """#148 追加：``_register`` 在调用线程实测 size/sha256——put_file 只做 DB 写。"""

    def test_put_file_precomputed_skips_disk(self, tmp_path: Path) -> None:
        store = Store(tmp_path / "t.db")
        store.open()
        try:
            row = store.create_task(
                task_id=new_task_id(),
                kind="arxiv",
                target_lang="zh-CN",
                model="m",
            )
            rec = store.put_file(
                row["id"], "zh_pdf", "ghost.pdf", size=7, sha256="deadbeef"
            )
            assert rec["bytes"] == 7  # noqa: PLR2004 -- 预算值钉样
            assert rec["sha256"] == "deadbeef"
            got = store.file_record(row["id"], "zh_pdf")
            assert got is not None
            assert got["sha256"] == "deadbeef"
        finally:
            store.close()

    def test_register_hashes_on_caller_thread(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """worker 线程调 ``_register``：读盘+sha256 在调用线程，put_file 仍在 loop。"""
        import hashlib  # noqa: PLC0415

        ctx, worker, store = mk_ctx(tmp_path)
        ctx.root.mkdir(parents=True, exist_ok=True)
        (ctx.root / "big.bin").write_bytes(b"x" * 64)
        sha_tids: list[int] = []
        put_tids: list[int] = []
        real_sha = hashlib.sha256
        real_put = store.put_file

        def spy_sha(data: bytes = b"", **kw: object) -> object:
            sha_tids.append(threading.get_ident())
            return real_sha(data, **kw)

        def spy_put(*a: object, **kw: object) -> object:
            put_tids.append(threading.get_ident())
            return real_put(*a, **kw)

        monkeypatch.setattr(hashlib, "sha256", spy_sha)
        monkeypatch.setattr(store, "put_file", spy_put)

        drive(
            worker,
            asyncio.to_thread(
                worker._register,  # noqa: SLF001
                ctx,
                "blob",
                "big.bin",
            ),
        )
        loop_tid = worker._loop_tid  # noqa: SLF001
        assert sha_tids, "sha256 应被调用"
        assert sha_tids[0] != loop_tid, "sha256 必须在调用线程算"
        assert put_tids, "put_file 应被调用"
        assert put_tids[0] == loop_tid, "put_file 仍在 loop 线程（DB 写单写者）"
        rec = store.file_record(ctx.task_id, "blob")
        assert rec is not None
        assert rec["bytes"] == 64  # noqa: PLR2004 -- fixture 大小钉样
        assert rec["sha256"] == hashlib.sha256(b"x" * 64).hexdigest()


def _pty_dev_fds() -> list[str]:
    """扫 /proc/self/fd 里指向 pty 设备的 readlink 目标（同步阻塞——调用方走 to_thread）。

    fd 号会被兜底 pipe 复用，只能按 readlink 目标数 pty 残留；瞬逝 fd
    （iterdir 目录自身/子继承句柄）readlink 落空即跳过。
    """
    pts: list[str] = []
    for ent in Path("/proc/self/fd").iterdir():
        if int(ent.name) <= 2:  # noqa: PLR2004 -- 0/1/2 标准流不算
            continue
        try:
            t = str(ent.readlink())
        except OSError:
            continue
        if "/dev/pt" in t:  # ptmx/ptsN 设备——pipe/eventfd 不含
            pts.append(t)
    return pts


@pytest.mark.integration
@pytest.mark.skipif(babeldoc_mod.pty is None, reason="POSIX pty only")
class TestSpawnPtyFdCleanup:
    """``_spawn`` openpty 成功后 ioctl 翻车：master/slave 两 fd 必须显式关。"""

    @pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="fd 枚举依赖 /proc")
    def test_ioctl_failure_closes_fds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import fcntl  # noqa: PLC0415 -- POSIX-only（skipif 已闸 Windows）
        import pty  # noqa: PLC0415

        master, slave = pty.openpty()
        monkeypatch.setattr(pty, "openpty", lambda: (master, slave))

        def boom(*_a: object, **_kw: object) -> None:
            msg = "winsize fail"
            raise OSError(msg)

        monkeypatch.setattr(fcntl, "ioctl", boom)

        async def run() -> None:
            proc, feed_fd = await babeldoc_mod._spawn(["/bin/true"])  # noqa: SLF001
            try:
                pts = await asyncio.to_thread(_pty_dev_fds)
                assert pts == [], f"pty fd 泄漏（master/slave 未关）: {pts}"
            finally:
                os.close(feed_fd)  # 测里没有泵——读端手动收
                await proc.wait()

        asyncio.run(run())

    def test_pipe_fallback_carries_both_streams(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """pty 整体缺席 → 匿名 pipe 合并流：stdout/stderr 同进读端（历史 STDOUT 非法形已修）。"""
        monkeypatch.setattr(babeldoc_mod, "pty", None)

        async def run() -> str:
            proc, feed_fd = await babeldoc_mod._spawn(  # noqa: SLF001
                ["/bin/sh", "-c", "echo out-line; echo err-line >&2"]
            )
            try:
                data = b""
                while chunk := os.read(feed_fd, 65536):
                    data += chunk
            finally:
                os.close(feed_fd)
                await proc.wait()
            return data.decode()

        out = asyncio.run(run())
        assert "out-line" in out
        assert "err-line" in out


class TestSyncFixedSourcesUnderscore:
    """``_sync_fixed_sources`` 删除侧与 copy 侧同口径排除 ``_*`` 顶层项。"""

    def test_underscore_dir_survives(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        zh = tmp_path / "zh"
        (work / "_minted-main").mkdir(parents=True)
        (work / "_minted-main" / "x.tex").write_text("minted", encoding="utf-8")
        (work / "main.tex").write_text("new", encoding="utf-8")
        (zh / "_minted-main").mkdir(parents=True)
        keep_file = zh / "_minted-main" / "x.tex"
        keep_file.write_text("minted", encoding="utf-8")
        stale = zh / "stale.tex"
        stale.write_text("old", encoding="utf-8")
        (zh / "main.tex").write_text("old", encoding="utf-8")
        (zh / ".splice-done").write_text("", encoding="utf-8")

        n = worker_mod._sync_fixed_sources(work, zh)  # noqa: SLF001
        assert keep_file.is_file(), "_ 前缀目录内源文件不得被删除"
        assert not stale.exists()
        assert (zh / ".splice-done").is_file()
        assert (zh / "main.tex").read_text(encoding="utf-8") == "new"
        assert n == 2  # noqa: PLR2004 -- main.tex 覆盖 + stale.tex 删除


class TestUnpackZipMemberCorruption:
    """成员级损坏归 ``UnpackError``——漏 BadZipFile 会成 internal 可重试 fault。"""

    def test_bad_crc_member(self, tmp_path: Path) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("a.tex", "hello latex")
        data = bytearray(buf.getvalue())
        idx = data.find(b"hello latex")
        assert idx > 0
        data[idx] ^= 0xFF  # 翻 payload → read 时 CRC 校验必炸
        with pytest.raises(UnpackError, match="bad member"):
            unpack_zip(bytes(data), tmp_path / "out")


class _FailClient:
    """aclose 可炸的 duck-type client（``_aclose_clients`` 韧性钉）。"""

    def __init__(self, name: str, *, boom: bool = False) -> None:
        self.name = name
        self.boom = boom
        self.closed = False

    async def aclose(self) -> None:
        if self.boom:
            msg = "dead conn"
            raise RuntimeError(msg)
        self.closed = True


class TestAcloseClientsResilience:
    """单个 aclose 抛错不挡其余、不上浮。"""

    def test_one_failure_does_not_block_rest(self) -> None:
        bad = _FailClient("a", boom=True)
        good = _FailClient("b")

        async def drive() -> None:
            await worker_mod._aclose_clients([bad, good])  # noqa: SLF001

        asyncio.run(drive())  # 不抛
        assert good.closed


class TestSpliceSentinelInvalidation:
    """重进翻译段改了 chunks 行 → ``.splice-done`` 摘除，逼编译段重 splice。"""

    def _pre_rows(self, store: Store, task_id: str) -> dict[str, tuple[str, str]]:
        return {
            r["chunk_id"]: (str(r["status"]), str(r["translation"] or ""))
            for r in store.all_chunks(task_id)
        }

    def _teardown(
        self,
        worker: PipelineWorker,
        ctx: TaskCtx,
        store: Store,
        pre_rows: dict[str, tuple[str, str]],
    ) -> None:
        asyncio.run(
            worker.run_stage(  # run_stage 直驱
                ctx,
                "teardown_translate",
                run_task=None,
                state=DBStateBridge(store, ctx.task_id),
                cache=SegmentCache(store, prefix="t", model="m", target_lang="zh-CN"),
                status_map={},
                sse_items=[],
                usage={"calls": 0},
                clients=[],
                pre_rows=pre_rows,
            )
        )

    def test_changed_rows_drop_sentinel(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        scan_base(ctx, worker, store, MINI_TEX)
        ctx.zh_dir.mkdir(parents=True)
        sent = ctx.zh_dir / ".splice-done"
        sent.write_text("", encoding="utf-8")
        pre = self._pre_rows(store, ctx.task_id)
        # 模拟本段翻译落盘：首块 pending→ok+ 译文
        cid = str(store.all_chunks(ctx.task_id)[0]["chunk_id"])
        store.update_chunk(
            ctx.task_id,
            cid,
            {"status": "ok", "translation": "译文", "attempts": 1},
        )
        self._teardown(worker, ctx, store, pre)
        assert not sent.exists(), "译文变更后 .splice-done 必须摘除"

    def test_unchanged_rows_keep_sentinel(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        scan_base(ctx, worker, store, MINI_TEX)
        ctx.zh_dir.mkdir(parents=True)
        sent = ctx.zh_dir / ".splice-done"
        sent.write_text("", encoding="utf-8")
        pre = self._pre_rows(store, ctx.task_id)
        self._teardown(worker, ctx, store, pre)
        assert sent.is_file(), "无变化不动哨兵——resume 才能直进编译臂"


class TestCacheUserGlossarySig:
    """``_make_cache`` user 层按内容进指纹：同径换内容分桶、异径同内容合桶。"""

    def test_same_path_content_change_rekeys(self, tmp_path: Path) -> None:
        ctx, worker, _store = mk_ctx(tmp_path, options={"glossary": "g.yaml"})
        ctx.secrets = Secrets(api_key="k")  # M1：无 key → _NullCache 无 _prefix
        ctx.base_dir.mkdir(parents=True, exist_ok=True)
        g = ctx.base_dir / "g.yaml"
        g.write_text("a: 甲\n", encoding="utf-8")
        p1 = worker._make_cache(ctx)._prefix  # noqa: SLF001
        g.write_text("a: 乙\n", encoding="utf-8")
        p2 = worker._make_cache(ctx)._prefix  # noqa: SLF001
        assert p1 != p2

    def test_diff_path_same_content_shares(self, tmp_path: Path) -> None:
        ctx, worker, _store = mk_ctx(tmp_path, options={"glossary": "g.yaml"})
        ctx.secrets = Secrets(api_key="k")  # M1：无 key → _NullCache 无 _prefix
        ctx.base_dir.mkdir(parents=True, exist_ok=True)
        (ctx.base_dir / "g.yaml").write_text("a: 甲\n", encoding="utf-8")
        p1 = worker._make_cache(ctx)._prefix  # noqa: SLF001
        (ctx.base_dir / "h.yaml").write_text("a: 甲\n", encoding="utf-8")
        ctx.row["options_json"] = json.dumps({"glossary": "h.yaml"})
        p2 = worker._make_cache(ctx)._prefix  # noqa: SLF001
        assert p1 == p2

    def test_user_glossary_default_layer_sig(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """缺省 ``USER_GLOSSARY_PATH`` 层内容也进指纹（与 _make_glossary 缺省口径一致）。"""
        udir = tmp_path / "user-g"
        udir.mkdir()
        ufile = udir / "glossary.yaml"
        ufile.write_text("x: 一\n", encoding="utf-8")
        monkeypatch.setattr(worker_mod.seams, "USER_GLOSSARY_PATH", ufile)
        ctx, worker, _store = mk_ctx(tmp_path)
        ctx.secrets = Secrets(api_key="k")  # M1：无 key → _NullCache 无 _prefix
        p1 = worker._make_cache(ctx)._prefix  # noqa: SLF001
        ufile.write_text("x: 二\n", encoding="utf-8")
        p2 = worker._make_cache(ctx)._prefix  # noqa: SLF001
        assert p1 != p2


class TestFetcherOwnership:
    """``_fetch_arxiv`` 连接池纪律：自建 Fetcher 随任务关闭；注入实例归调用方。"""

    def test_injected_fetcher_not_closed(self, tmp_path: Path) -> None:
        closed: list[bool] = []
        fake = FakeFetcher(make_targz({"main.tex": MINI_TEX}))
        fake.close = lambda: closed.append(True)  # type: ignore[attr-defined]
        ctx, worker, _store = mk_ctx(
            tmp_path,
            worker_kw={
                "fetcher": fake,
                "source_cache": SourceCache(tmp_path / "src-cache"),
            },
        )
        worker.run_stage(ctx, "fetch_arxiv")
        assert closed == []

    def test_self_built_fetcher_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        closed: list[bool] = []

        class _RecFetcher(FakeFetcher):
            def close(self) -> None:
                closed.append(True)

        monkeypatch.setattr(
            worker_mod.seams,
            "Fetcher",
            lambda *_a, **_kw: _RecFetcher(make_targz({"main.tex": MINI_TEX})),
        )
        monkeypatch.setattr(
            worker_mod.seams,
            "fetch_metadata",
            lambda _id, *, fetcher: None,  # noqa: ARG005
        )
        ctx, worker, _store = mk_ctx(
            tmp_path, worker_kw={"source_cache": SourceCache(tmp_path / "src-cache")}
        )
        worker.run_stage(ctx, "fetch_arxiv")
        assert closed == [True]

    def test_self_built_fetcher_closed_on_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """acquire_source 抛错路径同样收口——泄漏点正在异常臂。"""
        closed: list[bool] = []

        class _RecFetcher(FakeFetcher):
            def close(self) -> None:
                closed.append(True)

        monkeypatch.setattr(
            worker_mod.seams,
            "Fetcher",
            lambda *_a, **_kw: _RecFetcher(make_targz({"main.tex": MINI_TEX})),
        )
        monkeypatch.setattr(
            worker_mod.seams,
            "acquire_source",
            lambda *_a, **_kw: (_ for _ in ()).throw(OSError("boom")),
        )
        ctx, worker, _store = mk_ctx(
            tmp_path, worker_kw={"source_cache": SourceCache(tmp_path / "src-cache")}
        )
        with pytest.raises(OSError, match="boom"):
            worker.run_stage(ctx, "fetch_arxiv")
        assert closed == [True]


class TestLogTextOfFallback:
    """worker-share-fix：``_log_text_of`` 空/缺席/读失败的 .log 一律退 ``stdout_tail``。

    与 ``engine.parse_log`` 同口径——空 .log 直返空串会把 missing-char
    等只存在于 stdout 的升级信号静默丢掉（judge 拿不到 log_text 即
    missing_chars=0，升级逃逸）。
    """

    @staticmethod
    def _res(log_path: Path | None, tail: str) -> CompRes:
        return CompRes(
            engine="xelatex",
            ok=False,
            pdf=None,
            log=LogInfo(),
            log_path=log_path,
            stdout_tail=tail,
        )

    def test_empty_log_falls_back_to_tail(self, tmp_path: Path) -> None:
        _ctx, worker, _store = mk_ctx(tmp_path)
        log = tmp_path / "empty.log"
        log.write_text("", encoding="utf-8")
        tail = "Missing character: There is no 中 in font cmr10!"
        assert worker._log_text_of(self._res(log, tail)) == tail  # noqa: SLF001

    def test_missing_and_unreadable_log_fall_back(self, tmp_path: Path) -> None:
        _ctx, worker, _store = mk_ctx(tmp_path)
        tail = "tail-signal"
        assert (
            worker._log_text_of(self._res(tmp_path / "nonexistent.log", tail))  # noqa: SLF001
            == tail
        )
        asdir = tmp_path / "asdir.log"
        asdir.mkdir()  # read_text → IsADirectoryError(OSError)
        assert worker._log_text_of(self._res(asdir, tail)) == tail  # noqa: SLF001

    def test_log_content_wins_and_no_logpath_uses_tail(self, tmp_path: Path) -> None:
        _ctx, worker, _store = mk_ctx(tmp_path)
        log = tmp_path / "real.log"
        log.write_text("! real log line", encoding="utf-8")
        assert (
            worker._log_text_of(self._res(log, "tail")) == "! real log line"  # noqa: SLF001
        )
        assert worker._log_text_of(self._res(None, "tail!")) == "tail!"  # noqa: SLF001
        assert worker._log_text_of(self._res(None, "")) == ""  # noqa: SLF001


class TestFlushTranslateSync:
    """worker-share-fix：``_flush_translate`` 同步体钉——cancel 面结构性消除。

    ``_teardown_translate`` 的 buffer flush 原先由 ``suppress(CancelledError)``
    包裹 ``await`` 异步体：体一旦引入悬置点，pending-cancel 会投递进去
    截断写盘再被吞。改同步 ``def`` 后 cancel 只能投递在悬置点，同步体
    原子跑完不被截断。
    """

    def test_flush_is_plain_sync_function(self) -> None:
        """钉死契约：``_flush_translate`` 不得退回 coroutine（防未来 await 混入）。"""
        assert not asyncio.iscoroutinefunction(
            PipelineWorker._flush_translate  # noqa: SLF001
        )

    def test_teardown_flushes_buffer_after_cancel(self, tmp_path: Path) -> None:
        """cancel 已投递后进 teardown：缓冲已完块仍落库（status/translation 真值）。"""
        ctx, worker, store = mk_ctx(tmp_path)
        src = "A finished chunk buffered when cancellation landed."
        store.insert_chunks(
            ctx.task_id,
            [
                {
                    "chunk_id": "c1",
                    "seq": 0,
                    "src_file": "main.tex",
                    "src_text": src,
                    "kind": "para",
                    "byte_start": 0,
                    "byte_end": len(src),
                }
            ],
        )
        state = DBStateBridge(store, ctx.task_id)
        state.buffer.append(
            ChunkRecord(chunk_id="c1", source=src, translation="译文落盘", status="ok")
        )

        async def drive() -> None:
            me = asyncio.current_task()
            assert me is not None
            me.get_loop().call_soon(me.cancel)  # 复刻 poll 循环 _check_cancelled 抛出点
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.sleep(0)
            await worker.run_stage(  # run_stage 直驱
                ctx,
                "teardown_translate",
                run_task=None,
                state=state,
                cache=SegmentCache(store, prefix="t", model="m", target_lang="zh-CN"),
                status_map={},
                sse_items=[],
                usage={"calls": 0},
                clients=[],
                pre_rows={},
            )

        asyncio.run(drive())
        row = store.all_chunks(ctx.task_id)[0]
        assert row["status"] == "ok"
        assert row["translation"] == "译文落盘"


class TestResidAuditLoops:
    """#278：dispatcher/heartbeat 对 sqlite3 异常面存活钉样。

    ``sqlite3.OperationalError`` 不是 OSError/StoreError 子类——原捕获面
    漏它，一次 DB 错即打死 dispatcher（后续任务静默饿死 + secrets 残留）
    或 ticker（全实例 updated_at 停摆）。
    """

    def test_dispatcher_survives_sqlite_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = Store(tmp_path / "t.db")
        store.open()
        try:
            bus = EventBus(store)
            worker = PipelineWorker(store, bus, tmp_path)
            runner = TaskRunner(store, bus, worker)
            tid_a = new_task_id()
            store.create_task(
                task_id=tid_a,
                kind="arxiv",
                target_lang="zh-CN",
                model="m",
                arxiv_id="2401.00001",
                options={},
            )
            tid_b = new_task_id()
            store.create_task(
                task_id=tid_b,
                kind="arxiv",
                target_lang="zh-CN",
                model="m",
                arxiv_id="2401.00002",
                options={},
            )
            # replay 只灌 queued——先挪走，start() 后再挪回
            store.update_fields(tid_a, status="interrupted")
            store.update_fields(tid_b, status="interrupted")

            ran: list[str] = []

            async def fake_run(_self: PipelineWorker, c: TaskCtx) -> None:
                ran.append(c.task_id)

            monkeypatch.setattr(PipelineWorker, "run", fake_run)
            real_get = store.get

            def flaky_get(task_id: str) -> dict[str, object] | None:
                if task_id == tid_a:
                    msg = "database is locked"
                    raise sqlite3.OperationalError(msg)
                return real_get(task_id)

            monkeypatch.setattr(store, "get", flaky_get)

            async def drive() -> None:
                runner.start()
                store.update_fields(tid_a, status="queued")
                store.update_fields(tid_b, status="queued")
                runner.enqueue(tid_a, Secrets())
                runner.enqueue(tid_b, Secrets())
                await asyncio.sleep(0.3)
                assert runner._dispatcher is not None  # noqa: SLF001
                assert not runner._dispatcher.done(), (  # noqa: SLF001
                    "前置段 DB 异常不得打死 dispatcher"
                )
                assert ran == [tid_b], "A 失败后 B 仍须被分发"
                assert tid_a not in runner.secrets, "失败条目的 secrets 必须清"
                await runner.stop()

            asyncio.run(drive())
        finally:
            store.close()

    def test_heartbeat_survives_sqlite_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        store.update_fields(ctx.task_id, status="interrupted")  # 避开 replay
        runner = TaskRunner(store, EventBus(store), worker)
        calls = {"n": 0}

        def flaky(_task_id: str) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                msg = "disk I/O error"
                raise sqlite3.OperationalError(msg)

        monkeypatch.setattr(store, "heartbeat", flaky)
        monkeypatch.setattr("texlate.server.worker.seams._HEARTBEAT_S", 0.01)

        async def drive() -> None:
            runner.start()
            loop = asyncio.get_running_loop()
            runner._current = (ctx.task_id, ctx, loop.create_future())  # noqa: SLF001
            await asyncio.sleep(0.15)
            assert runner._ticker is not None  # noqa: SLF001
            assert not runner._ticker.done(), "sqlite3 面异常不得杀 ticker"  # noqa: SLF001
            await runner.stop()

        asyncio.run(drive())
        assert calls["n"] >= 2, "首拍炸后 ticker 必须续拍"  # noqa: PLR2004


class TestResidAuditGlossary:
    """#278：``_make_glossary`` 降级面——Glossary.load 的 TypeError
    （顶层非 mapping）与 yaml.YAMLError 皆回落 None，不许 fault 任务。"""

    def test_list_yaml_degrades_to_none(self, tmp_path: Path) -> None:
        ctx, worker, _store = mk_ctx(tmp_path)
        ctx.base_dir.mkdir(parents=True)
        (ctx.base_dir / "glossary.local.yaml").write_text(
            "- term_a\n- term_b\n", encoding="utf-8"
        )
        assert worker._make_glossary(ctx) is None  # noqa: SLF001

    def test_bad_yaml_degrades_to_none(self, tmp_path: Path) -> None:
        ctx, worker, _store = mk_ctx(tmp_path)
        ctx.base_dir.mkdir(parents=True)
        (ctx.base_dir / "glossary.local.yaml").write_text(
            "key: [unclosed\n  bad: : :\n", encoding="utf-8"
        )
        assert worker._make_glossary(ctx) is None  # noqa: SLF001


class TestSetOption:
    """review2 worker#11：``set_option``/``update_options``——options 读 - 改 - 写
    + row 快照同步的单点封装（落库键 ``options_json`` 由调用点回写）。"""

    def test_set_and_update_sync_row(self, tmp_path: Path) -> None:
        ctx, _worker, store = mk_ctx(tmp_path, options={"a": 1})
        out = ctx.set_option("b", "x")
        assert json.loads(out) == {"a": 1, "b": "x"}
        assert ctx.row["options_json"] == out, "row 快照必须同步"
        assert ctx.options()["b"] == "x"
        out2 = ctx.update_options(lambda o: o.update({"c": 2, "a": 9}))
        assert json.loads(out2) == {"a": 9, "b": "x", "c": 2}
        assert ctx.options()["a"] == 9  # noqa: PLR2004
        store.update_fields(ctx.task_id, options_json=out2)
        db = json.loads(str(store.get(ctx.task_id)["options_json"]))
        assert db["c"] == 2  # noqa: PLR2004
        assert db["a"] == 9  # noqa: PLR2004

    def test_update_options_pop(self, tmp_path: Path) -> None:
        """删键形态也走同一封装（``reuse_hit`` 摘除臂同款）。"""
        ctx, _worker, _store = mk_ctx(tmp_path, options={"reuse_hit": "t1", "k": 1})
        out = ctx.update_options(lambda o: o.pop("reuse_hit", None))
        assert "reuse_hit" not in json.loads(out)
        assert json.loads(out)["k"] == 1
        assert ctx.row["options_json"] == out


class TestDBStateBridgeRows:
    """review2 worker#2：构造传 ``rows``（段头已读快照）时 ``load()`` 不再全扫。"""

    def test_rows_param_skips_scan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ctx, _worker, store = mk_ctx(tmp_path)

        def boom(_tid: str) -> list:
            pytest.fail("构造给了 rows——load 不许再 all_chunks")

        monkeypatch.setattr(store, "all_chunks", boom)
        rows = [
            {
                "chunk_id": "c1",
                "status": "ok",
                "src_text": "src-one",
                "translation": "译文一",
                "kind": "para",
                "attempts": 1,
                "warnings": "[]",
            },
            {
                "chunk_id": "c2",
                "status": "fallback_orig",
                "src_text": "src-two",
                "translation": "src-two",
                "kind": "para",
                "attempts": 0,
                "warnings": "",
            },
        ]
        completed, recs = DBStateBridge(store, "t1", rows=rows).load()
        assert completed == {"c1"}, "completed 只收 ok"
        assert recs["c1"].translation == "译文一"
        assert recs["c2"].status == "skipped"

    def test_none_rows_falls_back_to_store(self, tmp_path: Path) -> None:
        """不传 rows 走既有 ``all_chunks`` 全扫（旧路径不回退）。"""
        ctx, _worker, store = mk_ctx(tmp_path)
        store.insert_chunks(
            ctx.task_id,
            [
                {
                    "chunk_id": "c1",
                    "seq": 0,
                    "src_file": "main.tex",
                    "src_text": "src",
                    "kind": "para",
                    "byte_start": 0,
                    "byte_end": 3,
                }
            ],
        )
        completed, recs = DBStateBridge(store, ctx.task_id).load()
        assert completed == set()
        assert recs == {}, "pending 不在 _DB_TO_PIPE 映射面"
