"""worker share 道钉样：llm_hook 零 token 结构闸 / index 解码+except 面 /
zh 位污染对账池闸 / share_apply UTF-8 拒 / share_pack 终态闸。

自 test_worker_audit_fixes.py 切出（share 题域六类）。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from _workerkit import mk_ctx, scan_base
from conftest import MINI_TEX

import texlate.server.worker as worker_mod
from texlate.server.settings import share_dir
from texlate.server.worker import (
    PipelineWorker,
    Secrets,
    _PerCallTranslator,
    _ShareRejectError,
)
from texlate.share import ShareError

if TYPE_CHECKING:
    from typing import Any

    from texlate.server.worker import TaskCtx

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


class TestLlmHookShareGates:
    """Item C：llm_hook BYOK 接线 + share 零 token 结构闸。"""

    def test_share_no_llm_hook_with_key(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """kind=share 有真 api_key 也不给 llm_hook——零 token 是结构承诺。"""
        ctx, worker, _store = mk_ctx(tmp_path)
        ctx.row["kind"] = "share"
        ctx.secrets = Secrets(api_key="k", base_url="http://b", model="m")
        hook, usage, clients = worker._llm_hook_pack(ctx)  # noqa: SLF001
        assert hook is None
        assert usage is None
        assert clients == []

    def test_share_l2_env_judge_off(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """share 任务 options/env 全开也压不住——三处 LLM 面结构关。"""
        ctx, worker, _store = mk_ctx(
            tmp_path, options={"l2": True, "env_judge": True, "llm_hook": True}
        )
        ctx.row["kind"] = "share"
        assert worker._l2_enabled(ctx) is False  # noqa: SLF001
        assert worker._env_judge_enabled(ctx) is False  # noqa: SLF001
        hook, _u, _c = worker._llm_hook_pack(ctx)  # noqa: SLF001
        assert hook is None

    def test_llm_hook_byok_default_on(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """arxiv 任务带真 key → hook 建，translator 是 per-call BYOK 面。"""
        ctx, worker, _store = mk_ctx(tmp_path)
        ctx.secrets = Secrets(api_key="k", base_url="http://b", model="m9")
        hook, usage, clients = worker._llm_hook_pack(ctx)  # noqa: SLF001
        assert hook is not None
        assert isinstance(hook.translator, _PerCallTranslator)  # type: ignore[attr-defined]
        assert usage is not None
        assert usage["calls"] == 0
        assert clients == [], "per-call client 即弃，无长存连接要关"

    def test_llm_hook_off_without_key(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """无 BYOK key → None（裸 env-key client 会绕开计费面）。"""
        ctx, worker, _store = mk_ctx(tmp_path)
        hook, usage, _c = worker._llm_hook_pack(ctx)  # noqa: SLF001
        assert hook is None
        assert usage is None

    def test_llm_hook_opt_out(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """``options.llm_hook=False`` / ``TEXLATE_FIXLOOP_LLM=0`` 显式关。"""
        ctx, worker, _store = mk_ctx(tmp_path, options={"llm_hook": False})
        ctx.secrets = Secrets(api_key="k", base_url="http://b", model="m")
        assert worker._llm_hook_pack(ctx)[0] is None  # noqa: SLF001


class TestShareLookupIndexDecode:
    """#148：index.jsonl 非 UTF-8 → miss 回退（``index_lookup`` 漏 UnicodeDecodeError）。"""

    def test_bad_index_bytes_falls_back(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        scan_base(ctx, worker, store, _MATH_TEX)
        out_dir = share_dir(tmp_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.jsonl").write_bytes(b"\xff\xfe\x00bad")
        assert worker.run_stage(ctx, "share_lookup") is False


class TestSharePoolZhGuard:
    """worker-share-fix：包内 dual ``zh`` 位污染条目不进对账池。

    源任务 ``fallback_orig``/``failed`` 行的 dual.json zh 位装的是
    src_text 回写或空串——``validate_pair`` 对无占位符 src 放行这两形态
    （CJK 占比仅 WARN），收进池会让英文原文/空译文以 ``ok`` 落库续传、
    matched 计数造假甚至绕过零命中拒绝。``zh == en`` 含 CJK 是合法恒等
    译文（原文即中文段），照常放行。
    """

    @staticmethod
    def _row(src: str) -> dict[str, Any]:
        return {
            "status": "pending",
            "src_file": "main.tex",
            "src_text": src,
            "chunk_id": "c1",
        }

    def test_echo_src_counts_as_miss(self) -> None:
        """``zh == en`` 无 CJK = 原文回写 → 不进池 → missed/share_miss。"""
        src = "English prose that fell back to original on the origin side."
        pool = worker_mod._share_pool(  # noqa: SLF001
            [{"src_file": "main.tex", "en": src, "zh": src}]
        )
        assert ("main.tex", src) not in pool
        outcome, upd = worker_mod._share_row(self._row(src), pool)  # noqa: SLF001
        assert outcome == "missed"
        assert upd == {
            "status": "fallback_orig",
            "translation": src,
            "error_code": "share_miss",
        }

    def test_empty_blank_and_nonstr_zh_not_pooled(self) -> None:
        """``zh == ""``/空白串/非 str → 不进池 → missed。"""
        src = "A paragraph whose translation never landed upstream."
        pool = worker_mod._share_pool(  # noqa: SLF001
            [
                {"src_file": "main.tex", "en": src, "zh": ""},
                {"src_file": "main.tex", "en": "blank", "zh": "   \n "},
                {"src_file": "main.tex", "en": "nonstr", "zh": 123},
                {"src_file": "main.tex", "en": "missing"},
            ]
        )
        assert pool == {}
        outcome, upd = worker_mod._share_row(self._row(src), pool)  # noqa: SLF001
        assert outcome == "missed"
        assert upd is not None
        assert upd["error_code"] == "share_miss"

    def test_cjk_identity_and_real_zh_pass(self) -> None:
        """``zh == en`` 含 CJK（原文即中文段）与真译文照常入池对账。"""
        cjk_src = "本节给出全文总结与后续工作展望。"
        en_src = "Experiments show our approach outperforms strong baselines."
        zh = "实验表明我们的方法优于强基线。"
        pool = worker_mod._share_pool(  # noqa: SLF001
            [
                {"src_file": "main.tex", "en": cjk_src, "zh": cjk_src},
                {"src_file": "main.tex", "en": en_src, "zh": zh},
            ]
        )
        outcome, upd = worker_mod._share_row(self._row(cjk_src), pool)  # noqa: SLF001
        assert outcome == "ok"
        assert upd is not None
        assert upd["translation"] == cjk_src
        outcome, upd = worker_mod._share_row(self._row(en_src), pool)  # noqa: SLF001
        assert outcome == "ok"
        assert upd is not None
        assert upd["translation"] == zh


class TestShareLookupExceptSurface:
    """worker-share-fix：``_share_lookup`` 的 ``index_lookup`` except 面钉死。

    ``index_lookup`` 真实异常面只有 OSError/UnicodeDecodeError
    （FileNotFoundError 归 None、坏行内吞记 warning）——原
    ``except (ShareError, ...)`` 是死代码；删掉后 ShareError 冒出来即
    实现漂移信号，宁可 fault 暴露也不当 miss 静默。
    """

    def test_index_oserror_degrades_to_miss(self, tmp_path: Path) -> None:
        """index.jsonl 是目录（IsADirectoryError ⊂ OSError）→ 仍按 miss 降级。"""
        ctx, worker, store = mk_ctx(tmp_path)
        scan_base(ctx, worker, store, MINI_TEX)  # has_chunks → 才走到 index_lookup
        idx = share_dir(worker.data_dir) / "index.jsonl"
        idx.mkdir(parents=True)
        assert worker.run_stage(ctx, "share_lookup") is False

    def test_share_error_propagates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """index_lookup 抛 ShareError → 传播（钉死 except 不含 ShareError）。"""
        ctx, worker, store = mk_ctx(tmp_path)
        scan_base(ctx, worker, store, MINI_TEX)

        def boom(*_a: object, **_kw: object) -> None:
            raise ShareError

        monkeypatch.setattr(worker_mod.seams, "index_lookup", boom)
        with pytest.raises(ShareError):
            worker.run_stage(ctx, "share_lookup")


class TestResidAuditShareApply:
    """#278：``dual.json`` 非 UTF-8 → ``_ShareRejectError`` 而非逃逸。

    UnicodeDecodeError 是 ValueError 但非 ``json.JSONDecodeError``——漏捕
    时隐式命中路走 ``run()`` 的 parse 臂把任务 fault 掉（违反「隐式命中
    是优化不是承诺」）；kind=share 应归 partial+share_verify 而非 fault。
    """

    def test_bad_utf8_dual_rejects(self, tmp_path: Path) -> None:
        ctx, worker, _store = mk_ctx(tmp_path, options={})
        ctx.row["kind"] = "share"
        (ctx.root / "share").mkdir(parents=True)
        (ctx.root / "share" / "dual.json").write_bytes(b'{"chunks": [\xff\xfe]}')
        with pytest.raises(_ShareRejectError):
            worker.run_stage(ctx, "share_apply")


class TestResidAuditSharePackGate:
    """#278：``_share_pack_try`` 终态闸——弃单系终态（cancelled/
    interrupted/needs_auth）不进公共 index；fault/partial/done 照旧
    （§9 fixloop_exhausted 型放行语义不变）。"""

    @staticmethod
    def _drive(ctx: TaskCtx, worker: PipelineWorker) -> int:
        calls = 0

        def fake_publish(_root: Path, manifest: object, _out: Path) -> object:
            nonlocal calls
            calls += 1
            return Path("fake.share.zip"), manifest

        orig_publish = worker_mod.seams.share_pack_publish
        orig_manifest = PipelineWorker.share_pack_manifest
        worker_mod.seams.share_pack_publish = fake_publish
        PipelineWorker.share_pack_manifest = lambda _s, _c, _r: object()  # type: ignore[method-assign]
        try:
            worker._share_pack_try(ctx)  # noqa: SLF001 -- 主线程直调（_loop 未钉）
        finally:
            worker_mod.seams.share_pack_publish = orig_publish
            PipelineWorker.share_pack_manifest = orig_manifest  # type: ignore[method-assign]
        return calls

    def test_cancelled_not_published(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path, options={"share_pack": True})
        store.transition(ctx.task_id, "cancelled")
        assert self._drive(ctx, worker) == 0

    def test_interrupted_not_published(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path, options={"share_pack": True})
        store.transition(ctx.task_id, "interrupted", force=True)
        assert self._drive(ctx, worker) == 0

    def test_fault_still_published(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path, options={"share_pack": True})
        store.transition(ctx.task_id, "fault", force=True)
        assert self._drive(ctx, worker) == 1
