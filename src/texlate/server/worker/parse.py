"""``PipelineWorker._Parse``——parsing 段：base 树 + 解析 + ph 快照。"""

from __future__ import annotations

import asyncio
import json
import shutil
from typing import TYPE_CHECKING, Any

from texlate.compile.inject import (
    classify_no_main,
    find_main_tex,
)
from texlate.compile.normalize import normalize_project
from texlate.latex.api import parse_file
from texlate.latex.prose import file_has_prose
from texlate.xlat.pipeline import chunk_to_in
from texlate.xlat.prompts import normalize_kind

from ._common import (
    PROGRESS,
    TaskCtx,
    _RouteRejectError,
    _StageError,
    chunk_db_id,
)

if TYPE_CHECKING:
    from texlate.latex.model import ScanResult

import texlate.server.worker as _w


class _Parse:
    """parsing 段 mixin：base 树 + 解析 + ph 快照。"""

    # ------------------------------------------------------------ parsing

    async def _stage_parse(self, ctx: TaskCtx) -> None:
        """parsing：normalize → 主文件定位 → 逐文件 parse → chunks 入库。"""
        if self.store.has_chunks(ctx.task_id):
            await self._ensure_scans(ctx)
            return
        self._stage(ctx, "parsing", "解析工程", PROGRESS["parsing"][0])
        if ctx.row["kind"] == "arxiv_html":
            # DOM 链：无 normalize/主文件——src/index.html 直接出 chunk 行
            rows = await asyncio.to_thread(self._parse_html, ctx)
            self.store.insert_chunks(ctx.task_id, rows)
            self._stage(ctx, "parsing", "解析完成", PROGRESS["parsing"][1])
            self._check_cancelled(ctx)
            return
        if not (ctx.base_dir / ".base-done").is_file():
            await asyncio.to_thread(self._build_base, ctx)
        self._check_cancelled(ctx)
        rows, scans = await asyncio.to_thread(self._parse_all, ctx)
        self.store.insert_chunks(ctx.task_id, rows)
        ctx.scans = scans
        self._stage(ctx, "parsing", "解析完成", PROGRESS["parsing"][1])
        self._check_cancelled(ctx)

    def _build_base(self, ctx: TaskCtx) -> None:
        """``src → base``：route（reject → partial+``reject_at``，F3）→ normalize。"""
        if ctx.base_dir.exists():
            shutil.rmtree(ctx.base_dir)
        shutil.copytree(ctx.src_dir, ctx.base_dir)
        route = _w.route_project(ctx.base_dir)
        for r in route.reasons:
            self._log(ctx, f"route: {r}")
        if route.reject:
            raise _RouteRejectError(route.reject)
        opt_engine = str(ctx.options().get("engine") or "auto")
        engines = route.engines if opt_engine == "auto" else [opt_engine]
        if not engines:
            raise _StageError(code="parse", message="no engine route")
        ctx.engine_name = engines[0]
        override = str(ctx.options().get("main") or "")
        if override:
            # retry body {main} 或 upload main 字段：显式主文件——
            # 必须 confine 在 base/ 内（绝对路径与 ``..`` 逃逸一律拒，
            # resolve 后判——symlink 逃逸同挡），main_tex/编译产物
            # 不许落任务目录外。
            base = ctx.base_dir.resolve()
            cand = (ctx.base_dir / override).resolve()
            if not cand.is_relative_to(base):
                msg = f"main override 越出工程目录: {override}"
                raise _StageError(code="parse", message=msg)
            if not cand.is_file():
                raise _StageError(
                    code="parse", message=f"main override 不存在: {override}"
                )
            ctx.main_rel = cand.relative_to(base).as_posix()
        else:
            main = find_main_tex(ctx.base_dir)
            if main is None:
                # e2e 同位：no main tex 归 route 档策略拒绝（F3）；
                # classify_no_main 子码细分上游形态（P-D）
                sub = classify_no_main(ctx.base_dir)
                msg = f"no main tex:{sub}" if sub else "no main tex"
                raise _RouteRejectError(msg)
            ctx.main_rel = main.relative_to(ctx.base_dir).as_posix()
        stats = normalize_project(ctx.base_dir, ctx.engine_name, ctx.main_rel)
        self._log(ctx, f"normalize: {stats}")
        # 引擎路由与主文件持久化——resume 后编译段还要用同一台引擎；
        # route_engines 供 fixloop 跨引擎臂（tectonic 丢 flag → xelatex
        # 重编）判定——显式 engine 覆盖时只剩用户指定那台，跨臂自熄
        opts = ctx.options()
        opts["engine_resolved"] = ctx.engine_name
        opts["route_engines"] = list(engines)
        ctx.row["options_json"] = json.dumps(opts, ensure_ascii=False)
        self._on_loop(
            self.store.update_fields,
            ctx.task_id,
            main_tex=ctx.main_rel,
            options_json=ctx.row["options_json"],
        )
        (ctx.base_dir / ".base-done").write_text("", encoding="utf-8")

    def _parse_all(
        self, ctx: TaskCtx
    ) -> tuple[list[dict[str, Any]], dict[str, ScanResult]]:
        """逐文件半解析 → (chunk 行, scans)。单文件崩不拖全树。"""
        rows: list[dict[str, Any]] = []
        scans: dict[str, ScanResult] = {}
        ctx.support_files = []
        seq = 0
        for f in sorted(
            p
            for p in ctx.base_dir.rglob("*")
            if p.is_file() and p.suffix.lower() == ".tex"
        ):
            name = f.name.lower()
            if f.name.startswith(".") or name.endswith(".rtx.tex"):
                continue  # 隐文件 + REVTeX 运行时转储不进翻译集（同 e2e/stagerun）
            rel = f.relative_to(ctx.base_dir).as_posix()
            if name.endswith(".code.tex"):
                ctx.support_files.append(rel)  # tikzlibrary 机制件按原文保留
                continue
            try:
                res = parse_file(f, flatten=False)
            except Exception as e:  # noqa: BLE001 -- 单文件解析崩记名跳过
                self._log(ctx, f"parse skip {rel}: {e}")
                continue
            if not file_has_prose(res.chunks):
                # 无散文（pstricks/epsf/宏件/gnuplot 转储）——送译即腐蚀，
                # 按原文保留；与 parse skip 分流：这里是有意跳过而非失败
                ctx.support_files.append(rel)
                continue
            scans[rel] = res
            for c in res.chunks:
                cid = chunk_db_id(rel, c.span.start, c.span.end)
                rows.append(
                    {
                        "seq": seq,
                        "chunk_id": cid,
                        "src_file": rel,
                        "byte_start": c.span.start,
                        "byte_end": c.span.end,
                        "kind": normalize_kind(c.context),
                        "src_text": c.content,
                    }
                )
                seq += 1
        return rows, scans

    async def _ensure_scans(self, ctx: TaskCtx) -> None:
        """Resume 场景：chunks 已有但内存 scans 空 → 重解析 base/ 补建。"""
        if not ctx.scans:
            _rows, ctx.scans = await asyncio.to_thread(self._parse_all, ctx)

    def _ph_frag_map(self, ctx: TaskCtx) -> dict[str, dict[str, str]]:
        """``chunk_db_id → ph_fragments``：scans × ph_map 全量映射。

        DB 行与 ``ScanResult.chunks`` 按 byte span 对账（``chunk_db_id``
        同式）；无占位符的块不进表——``ph_fragments=None`` 才不武装。
        """
        frag_of: dict[str, dict[str, str]] = {}
        for rel, res in ctx.scans.items():
            for c in res.chunks:
                cid = chunk_db_id(rel, c.span.start, c.span.end)
                ci = chunk_to_in(c, chunk_id=cid, ph_map=res.ph_map)
                if ci.ph_fragments:
                    frag_of[cid] = ci.ph_fragments
        return frag_of
