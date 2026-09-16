"""worker.py 审计修复批（task #52）逐条钉样：ph 武装 / glossary 五层 /
cancel 孤儿 / 旁路 usage+术语 / fixloop reject+跨引擎 / _build_dual 出
loop / queued 重放 / _stage 终态守卫 / zip 前缀冲突 / IndirectObject 字体。"""

from __future__ import annotations

import asyncio
import io
import json
import threading
import zipfile
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from conftest import MINI_TEX, FakeFetcher, RecordingEngine, make_targz

from texlate.arxiv.cache import SourceCache
from texlate.arxiv.meta import PaperMeta
from texlate.compile.engine import CompRes, LogInfo
from texlate.server.events import EventBus
from texlate.server.store import ERROR_CODES, Store, new_task_id
from texlate.server.worker import (
    DBStateBridge,
    PipelineWorker,
    Secrets,
    SegmentCache,
    TaskCtx,
    TaskRunner,
    chunk_db_id,
    embed_cjk_mappings,
    unpack_zip,
)
from texlate.xlat.client import ChatClient
from texlate.xlat.pipeline import ChunkIn, MockTranslator, XlatPipeline

if TYPE_CHECKING:
    from pathlib import Path

_MATH_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "A paragraph with inline math $x+y$ and a command \\alpha inside prose.\n"
    "\n"
    "Second paragraph to pad the document body out a little.\n"
    "\\end{document}\n"
)

_ENV_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "First paragraph of English prose long enough to be a real chunk.\n"
    "\n"
    "\\begin{weirdbox}\n"
    "Some content inside a weird environment.\n"
    "\\end{weirdbox}\n"
    "\n"
    "Trailing paragraph.\n"
    "\\end{document}\n"
)


def _mk(
    tmp_path: Path,
    *,
    options: dict[str, object] | None = None,
    worker_kw: dict[str, object] | None = None,
) -> tuple[TaskCtx, PipelineWorker, Store]:
    """真实任务行 + TaskCtx + worker（stage 级直调面；conn 在主线程）。"""
    store = Store(tmp_path / "t.db")
    store.open()
    bus = EventBus(store)
    worker = PipelineWorker(store, bus, tmp_path, **(worker_kw or {}))  # type: ignore[arg-type]
    task_id = new_task_id()
    row = store.create_task(
        task_id=task_id,
        kind="arxiv",
        target_lang="zh-CN",
        model="m",
        arxiv_id="2401.00001",
        options=options or {},
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


def _scan(ctx: TaskCtx, worker: PipelineWorker, store: Store, tex: str) -> None:
    """main.tex 落 ``base/`` + 真解析 + chunks 入库。"""
    ctx.base_dir.mkdir(parents=True, exist_ok=True)
    (ctx.base_dir / "main.tex").write_text(tex, encoding="utf-8")
    rows, ctx.scans = worker._parse_all(ctx)  # noqa: SLF001 -- 单测直驱
    store.insert_chunks(ctx.task_id, rows)


class TestPhFragments:
    """Fix1：主链 ChunkIn 带 ph_fragments——``_repair_fn``/``recover_copied_tokens`` 得武装。"""

    def test_frag_map_and_pipe_inputs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        ctx, worker, store = _mk(tmp_path)
        _scan(ctx, worker, store, _MATH_TEX)
        frag_of = worker._ph_frag_map(ctx)  # noqa: SLF001
        math_cid = next(cid for cid, m in frag_of.items() if "$x+y$" in m.values())

        captured: list[ChunkIn] = []

        async def fake_run(_self: XlatPipeline, chunks: list[ChunkIn]) -> list:
            captured.extend(chunks)
            return []

        monkeypatch.setattr(XlatPipeline, "run", fake_run)
        asyncio.run(worker._stage_translate(ctx))  # noqa: SLF001
        math_in = next(c for c in captured if c.chunk_id == math_cid)
        assert math_in.ph_fragments == frag_of[math_cid]
        assert math_in.ph_fragments is not None
        assert "$x+y$" in math_in.ph_fragments.values()


class TestGlossaryLayers:
    """Fix2：``_make_glossary`` 五层——categories（arxiv 分类）+ placeholders 恒等注入。"""

    def test_categories_layer(self, tmp_path: Path) -> None:
        ctx, worker, _store = _mk(tmp_path, options={"arxiv_categories": ["cs.LG"]})
        g = worker._make_glossary(ctx)  # noqa: SLF001
        assert g is not None
        cat_terms = {en for en, t in g.terms.items() if t.source == "category:cs.LG"}
        assert "Abstractive Summarization" in cat_terms

    def test_placeholders_layer(self, tmp_path: Path) -> None:
        ctx, worker, _store = _mk(tmp_path)
        g = worker._make_glossary(  # noqa: SLF001
            ctx, placeholders=["[[MATH_2]]"]
        )
        assert g is not None
        entry = g.terms["[[MATH_2]]"]
        assert entry.zh == "[[MATH_2]]"  # 恒等注入：逼模型原样回抄
        assert entry.source == "placeholder"

    def test_fetch_arxiv_persists_categories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """fetch_metadata → ``options.arxiv_categories`` 落库 + ctx.row 同步（resume 路径）。"""
        ctx, worker, store = _mk(
            tmp_path,
            worker_kw={
                "fetcher": FakeFetcher(make_targz({"main.tex": MINI_TEX})),
                "source_cache": SourceCache(tmp_path / "src-cache"),
            },
        )
        monkeypatch.setattr(
            "texlate.server.worker.fetch_metadata",
            lambda arxiv_id, *, fetcher: PaperMeta(  # noqa: ARG005
                arxiv_id=arxiv_id,
                resolved_version=1,
                primary_category="cs.LG",
                categories=("cs.LG", "stat.ML"),
            ),
        )
        ctx.root.mkdir(parents=True, exist_ok=True)
        worker._fetch_arxiv(ctx)  # noqa: SLF001
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
        ctx, worker, _store = _mk(
            tmp_path,
            worker_kw={
                "fetcher": FakeFetcher(make_targz({"main.tex": MINI_TEX})),
                "source_cache": SourceCache(tmp_path / "src-cache"),
            },
        )
        monkeypatch.setattr(
            "texlate.server.worker.fetch_metadata",
            lambda _id, *, fetcher: None,  # noqa: ARG005
        )
        ctx.root.mkdir(parents=True, exist_ok=True)
        worker._fetch_arxiv(ctx)  # noqa: SLF001
        assert "arxiv_categories" not in ctx.options()
        assert (ctx.src_dir / "main.tex").is_file()


class TestCancelOrphan:
    """Fix3：cancel 竞态后 run_task 不再孤儿化。"""

    def test_teardown_cancels_pending_run_task(self, tmp_path: Path) -> None:
        ctx, worker, store = _mk(tmp_path)

        async def drive() -> asyncio.Task[list]:
            async def never() -> list:
                await asyncio.sleep(3600)
                return []  # pragma: no cover

            t = asyncio.create_task(never())
            await asyncio.sleep(0)  # 让它先跑起来
            await worker._teardown_translate(  # noqa: SLF001
                ctx=ctx,
                run_task=t,
                state=DBStateBridge(store, ctx.task_id),
                cache=SegmentCache(store, prefix="t", model="m", target_lang="zh-CN"),
                status_map={},
                sse_items=[],
                usage={"calls": 0},
                clients=[],
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
        ctx, worker, store = _mk(
            tmp_path,
            options={"env_judge": True},
            worker_kw={"translator_factory": lambda _ctx: fake},
        )
        _scan(ctx, worker, store, _ENV_TEX)
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
        ctx, worker, store = _mk(
            tmp_path,
            worker_kw={"translator_factory": lambda _c: MockTranslator()},
        )
        _scan(ctx, worker, store, _MATH_TEX)
        ph = next(
            t
            for res in ctx.scans.values()
            for t, frag in res.ph_map.items()
            if "x+y" in frag
        )
        run, _db = worker._l2_run_state(ctx, ctx.root / "build-zh")  # noqa: SLF001
        assert run.pipe.glossary is not None
        assert run.pipe._doc_glossary.get(ph) == ph  # noqa: SLF001
        assert run.pipe.cache is None


class TestFixloopFix:
    """Fix5：``reject:*`` verdict → partial+reject_at；engine_flags 跨引擎臂。"""

    def test_fixloop_reject_maps_partial(self, tmp_path: Path) -> None:
        assert "fixloop_reject" in ERROR_CODES
        ctx, worker, store = _mk(tmp_path)
        ctx.main_rel = "main.tex"
        ctx.engine_name = "tectonic"
        ctx.base_dir.mkdir(parents=True, exist_ok=True)
        ctx.zh_dir.mkdir(parents=True, exist_ok=True)
        # 哨兵旁路：splice/compile 产物预置，直抵终态分派
        (ctx.zh_dir / ".splice-done").write_text("", encoding="utf-8")
        (ctx.zh_dir / ".compile-done").write_text("", encoding="utf-8")
        (ctx.root / "zh.pdf").write_bytes(b"%PDF-1.4 fake")
        (ctx.root / "en.pdf").write_bytes(b"%PDF-1.4 fake")
        store.put_file(ctx.task_id, "zh_pdf", "zh.pdf", data_dir=ctx.root)
        store.put_file(ctx.task_id, "en_pdf", "en.pdf", data_dir=ctx.root)
        ctx.fixloop = {"verdict": "reject:r42", "trace": []}

        async def drive() -> None:
            worker._loop = asyncio.get_running_loop()  # noqa: SLF001
            worker._loop_tid = threading.get_ident()  # noqa: SLF001
            await worker._stage_compile(ctx)  # noqa: SLF001

        asyncio.run(drive())
        row = store.get(ctx.task_id)
        assert row["status"] == "partial"
        err = json.loads(str(row["error_json"]))
        assert err["code"] == "fixloop_reject"
        assert err["reject_at"] == "fixloop"
        assert err["fixloop"]["verdict"] == "reject:r42"

    def test_fixloop_cross_engine_arm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """dropped flags + tectonic + xelatex 候选 + verdict<clean → xelatex 重编取优。"""
        xeng = RecordingEngine("xelatex")
        teng = RecordingEngine("tectonic")

        def factory(name: str, **_kw: object) -> RecordingEngine:
            return {"xelatex": xeng, "tectonic": teng}[name]

        ctx, worker, _store = _mk(
            tmp_path,
            options={
                "engine_resolved": "tectonic",
                "route_engines": ["tectonic", "xelatex"],
            },
            worker_kw={"engine_factory": factory},
        )
        ctx.main_rel = "main.tex"
        ctx.engine_name = "tectonic"
        work = ctx.root / "build-zh"
        work.mkdir(parents=True)
        ctx.zh_dir.mkdir(parents=True)
        (work / "main.tex").write_text(MINI_TEX, encoding="utf-8")
        (ctx.zh_dir / "main.tex").write_text(MINI_TEX, encoding="utf-8")
        cell = {
            "verdict": "fail",
            "engine_flags": ["-shell-escape"],
            "engine_flags_dropped": ["-shell-escape"],
            "rounds": [],
            "actions": [],
        }
        monkeypatch.setattr("texlate.server.worker.fixloop", lambda *_a, **_kw: cell)
        first = CompRes(engine="tectonic", ok=True, pdf=None, log=LogInfo(n_errors=2))
        res = worker._run_fixloop(ctx, work, teng, first)  # noqa: SLF001
        assert xeng.calls, "xelatex 跨引擎臂应被触发"
        assert xeng.calls[0]["flags"] == ["-shell-escape"]
        assert res.engine == "xelatex"  # clean/partial > fail → 取优换臂
        assert ctx.fixloop is not None
        assert ctx.fixloop["engine_flags_dropped"] == ["-shell-escape"]
        assert ctx.fixloop["cross_engine"]["engine"] == "xelatex"


class TestBuildDualThread:
    """Fix6：``_build_dual`` 在 worker 线程跑（store 读经 ``_on_loop`` 回弹）。"""

    def test_build_dual_off_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import texlate.server.worker as worker_mod  # noqa: PLC0415

        ctx, worker, store = _mk(tmp_path)
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

        monkeypatch.setattr(worker_mod, "build_alignment", spy_align)

        async def drive() -> int:
            worker._loop = asyncio.get_running_loop()  # noqa: SLF001
            worker._loop_tid = threading.get_ident()  # noqa: SLF001
            await asyncio.to_thread(worker._build_dual, ctx)  # noqa: SLF001
            return threading.get_ident()

        loop_tid = asyncio.run(drive())
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
        ctx, worker, store = _mk(tmp_path)
        store.transition(ctx.task_id, "cancelled")
        seq0 = store.last_seq(ctx.task_id)
        worker._stage(ctx, "translating", "翻译中", 25)  # noqa: SLF001
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
