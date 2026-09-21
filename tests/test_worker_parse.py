"""worker parse 段钉样：``_parse_all`` 大写 .TEX / rtx 转储排除 / 散文门 /
重段出 loop / parse 尾检查点收敛 cancel。

自 test_worker_audit_fixes.py 切出（parse 题域五类）。
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from _drivekit import drive
from _workerkit import mk_ctx, scan_base

if TYPE_CHECKING:
    from pathlib import Path

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


class TestParseEndCheckpoint:
    """#148：``_stage_parse`` 尾检查点——parse 期 cancel 当场收敛不漂进 translate。"""

    def test_cancel_during_parse_converges(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        ctx.base_dir.mkdir(parents=True, exist_ok=True)
        (ctx.base_dir / ".base-done").write_text("", encoding="utf-8")

        def fake_parse(_ctx: TaskCtx) -> tuple[list, dict]:
            worker._on_loop(store.transition, ctx.task_id, "cancelled")  # noqa: SLF001
            return [], {}

        monkeypatch.setattr(worker, "_parse_all", fake_parse)

        with pytest.raises(asyncio.CancelledError):
            drive(worker, worker.run_stage(ctx, "stage_parse"))
        assert store.get(ctx.task_id)["status"] == "cancelled"


class TestOffLoopHeavySegments:
    """#148：重 FS/解析段一律 ``asyncio.to_thread`` 出 loop；store 读弹回 loop。"""

    def test_ensure_scans_parses_off_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """resume 形态（chunks 在库 + scans 空）：``_parse_all`` 必须在 worker 线程。"""
        ctx, worker, store = mk_ctx(tmp_path)
        scan_base(ctx, worker, store, _MATH_TEX)
        ctx.scans = {}
        seen: list[int] = []
        real = worker._parse_all  # noqa: SLF001

        def spy(_ctx: TaskCtx) -> tuple[list, dict]:
            seen.append(threading.get_ident())
            return real(_ctx)

        monkeypatch.setattr(worker, "_parse_all", spy)

        drive(worker, worker.run_stage(ctx, "ensure_scans"))
        loop_tid = worker._loop_tid  # noqa: SLF001
        assert seen, "_parse_all 应被调用"
        assert seen[0] != loop_tid, "_parse_all 必须跑在 worker 线程"
        assert ctx.scans, "scans 应被补建"

    def test_build_md_zip_store_read_on_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``_build_md_zip`` 跑 worker 线程时 ``all_chunks`` 弹回 loop 线程。"""
        ctx, worker, store = mk_ctx(tmp_path)
        scan_base(ctx, worker, store, _MATH_TEX)
        row = store.all_chunks(ctx.task_id)[0]
        store.update_chunk(
            ctx.task_id, row["chunk_id"], {"status": "ok", "translation": "译文"}
        )
        seen: list[int] = []
        real = store.all_chunks

        def spy(task_id: str) -> list[dict]:
            seen.append(threading.get_ident())
            return real(task_id)

        monkeypatch.setattr(store, "all_chunks", spy)

        drive(worker, asyncio.to_thread(worker._build_md_zip, ctx))  # noqa: SLF001
        loop_tid = worker._loop_tid  # noqa: SLF001
        assert seen, "all_chunks 应被调用"
        assert all(t == loop_tid for t in seen), "store 读必须弹回 loop 线程"
        assert store.file_record(ctx.task_id, "md_zip") is not None


class TestParseAllUpperTex:
    """#148 追加：``_parse_all`` rglob 大小写盲区——``.TEX`` 主文件不再零块。"""

    def test_uppercase_tex_parsed(self, tmp_path: Path) -> None:
        ctx, worker, _store = mk_ctx(tmp_path)
        ctx.base_dir.mkdir(parents=True, exist_ok=True)
        (ctx.base_dir / "MAIN.TEX").write_text(_MATH_TEX, encoding="utf-8")
        rows, scans = worker.run_stage(ctx, "parse_all")
        assert "MAIN.TEX" in scans
        assert rows, "大写 .TEX 应产出 chunk"


class TestParseAllRtxSkip:
    """REVTeX 运行时转储 ``*.rtx.tex`` 不进翻译集——与 e2e/stagerun 同口径。

    实测案例 1206.0660 ``aps.rtx.tex`` 曾被翻出 +24 CJK。
    """

    def test_rtx_dump_excluded(self, tmp_path: Path) -> None:
        ctx, worker, _store = mk_ctx(tmp_path)
        ctx.base_dir.mkdir(parents=True, exist_ok=True)
        (ctx.base_dir / "main.tex").write_text(_MATH_TEX, encoding="utf-8")
        (ctx.base_dir / "aps.rtx.tex").write_text(_MATH_TEX, encoding="utf-8")
        (ctx.base_dir / "UP.RTX.TEX").write_text(_MATH_TEX, encoding="utf-8")
        rows, scans = worker.run_stage(ctx, "parse_all")
        assert set(scans) == {"main.tex"}
        assert all(r["src_file"] == "main.tex" for r in rows)


class TestParseAllProseGate:
    """散文门：``.code.tex`` 机制件与无散文件分流 support 不送译（同 e2e 口径）。"""

    def test_code_tex_and_nonprose_to_support(self, tmp_path: Path) -> None:
        ctx, worker, _store = mk_ctx(tmp_path)
        ctx.base_dir.mkdir(parents=True, exist_ok=True)
        (ctx.base_dir / "main.tex").write_text(_MATH_TEX, encoding="utf-8")
        (ctx.base_dir / "tikzlibraryfoo.code.tex").write_text(
            "\\def\\psunit{1cm}\\def\\plot{\\psline}", encoding="utf-8"
        )
        (ctx.base_dir / "macros.tex").write_text(
            "\\newcommand{\\foo}[1]{#1}\\def\\bar{baz}", encoding="utf-8"
        )
        rows, scans = worker.run_stage(ctx, "parse_all")
        assert set(scans) == {"main.tex"}
        assert all(r["src_file"] == "main.tex" for r in rows)
        assert set(ctx.support_files) == {
            "tikzlibraryfoo.code.tex",
            "macros.tex",
        }

    def test_support_files_reset_on_rerun(self, tmp_path: Path) -> None:
        """``_ensure_scans`` 会二次调 ``_parse_all``——support 清单须幂等。"""
        ctx, worker, _store = mk_ctx(tmp_path)
        ctx.base_dir.mkdir(parents=True, exist_ok=True)
        (ctx.base_dir / "main.tex").write_text(_MATH_TEX, encoding="utf-8")
        (ctx.base_dir / "x.code.tex").write_text("\\def\\a{1}", encoding="utf-8")
        worker.run_stage(ctx, "parse_all")
        worker.run_stage(ctx, "parse_all")
        assert ctx.support_files == ["x.code.tex"]
