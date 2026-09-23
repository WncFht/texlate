"""reader 路由：dual.json 阅读器装配 + 阅读位置字段级合并落盘（§2.5/§5.4）。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, cast

# FastAPI 注册期 eval_str 解析端点签名注解——Request/Response 须驻运行时
from fastapi import Request, Response  # noqa: TC002
from fastapi.responses import JSONResponse

from texlate.server.http import _json_error, _read_body
from texlate.server.seqpos import seqpos_for_task
from texlate.xlat.state import atomic_json

if TYPE_CHECKING:
    from fastapi import FastAPI

    from texlate.server.routers.deps import AppDeps


def register(app: FastAPI, deps: AppDeps) -> None:  # noqa: C901, PLR0915 -- 端点面平铺
    """挂载 reader 端点。"""

    @app.get("/api/task/{task_id}/reader")
    async def reader_get(  # noqa: C901 -- 序列化装配阶梯平铺
        request: Request, task_id: str
    ) -> Response:
        """``{documents, alignment, reading, view}``（§2.5/§5.4）。"""
        row = deps.get_task(request, task_id)
        # files 表一次取——file_record 每次全量 SELECT，本端点要查 4 个
        # kind（dual_json/zh_html/md_zip/zh_pdf），串发即 mini-N+1
        files = deps.store.files(task_id)
        dual_path = deps.task_dir(task_id) / "dual.json"
        if files.get("dual_json") is None:
            # 以登记行为准——磁盘孤儿件（登记前崩溃/失效清理残留）不服务
            return _json_error(404, "dual.json 未产出", "not_found")

        def _load() -> dict[str, Any]:
            if not dual_path.is_file():
                raise FileNotFoundError(dual_path)
            data: Any = json.loads(dual_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise TypeError  # 非 object 与 corrupt 同归 500——调用方只分 404/500/ok
            return cast("dict[str, Any]", data)

        try:
            # 数 MB 级读+解析——卸出事件循环
            dual = await asyncio.to_thread(_load)
        except FileNotFoundError:
            return _json_error(404, "dual.json 未产出", "not_found")
        except (json.JSONDecodeError, TypeError):
            return _json_error(500, "dual.json 损坏", "internal")
        docs = dual.get("documents") or {}
        if not isinstance(docs, dict):
            return _json_error(500, "dual.json 损坏", "internal")
        # arxiv_html 链的 documents 指向序列化 DOM 产物（dom 视图锚点页）；
        # 其余链恒为 PDF 双栏
        doc_kinds = (
            (("original", "en.html"), ("translated", "zh.html"))
            if str(row["kind"]) == "arxiv_html"
            else (("original", "en.pdf"), ("translated", "zh.pdf"))
        )
        for side, kind in doc_kinds:
            if isinstance(docs.get(side), dict):
                docs[side]["url"] = f"/api/files/{task_id}/{kind}"
        reading: dict[str, Any] = {}
        rpath = deps.task_dir(task_id) / "reading.json"
        if rpath.is_file():
            try:
                raw_reading = json.loads(rpath.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raw_reading = {}
            if isinstance(raw_reading, dict):
                reading = raw_reading
        # seq 级对位——懒算缓存 seqpos.json，注入顶层字段而非 alignment
        # （前端 dual()?.alignment 优先级高于本响应的 alignment，注进
        # 里面会被盖掉；seqpos 独立键前端自行消费）。失败/缺席降级 {}。
        seqpos = await asyncio.to_thread(
            seqpos_for_task, deps.task_dir(task_id), dual
        )
        return JSONResponse(
            {
                "documents": docs,
                "alignment": dual.get("alignment") or {"kind": "pages"},
                "seqpos": seqpos or {},
                "reading": reading,
                # zh_html = arxiv_html 链 DOM 产物 → dom 视图（pages 语义即
                # 锚点数）；md_zip = 无 PDF 路的降级登记物；zh_pdf 在则 pdf
                # 视图优先（fault→retry 救回出 pdf 后残留的 md_zip 不把视图
                # 钉死在 html）
                "view": (
                    "dom"
                    if files.get("zh_html")
                    else (
                        "html"
                        if files.get("md_zip") and not files.get("zh_pdf")
                        else "pdf"
                    )
                ),
            }
        )

    @app.put("/api/task/{task_id}/reader/position")
    async def reader_put(request: Request, task_id: str) -> Response:
        """阅读位置落盘（``tasks/{id}/reading.json``）；版本不符 409。

        字段级合并：body 出现的键更新、缺席的保留——整覆写会让「单栏
        保存」抹掉对侧位置（``positions`` 再按侧键深合并，en/zh 互补）。
        """
        deps.get_task(request, task_id)
        body = await _read_body(request)
        want = str(body.get("document_version") or "")
        if want:
            # files 一次取——串发 file_record 是 mini-N+1；仅版本校验臂需要，
            # 不带 ``document_version`` 的 PUT 不付这趟 SELECT
            files = deps.store.files(task_id)
            # arxiv_html 无 zh_pdf——回落 zh_html（dom 路也吃防旧版位置回灌）
            rec = files.get("zh_pdf") or files.get("zh_html")
            cur = str((rec or {}).get("sha256") or "")
            if cur and want != cur:
                return _json_error(409, "document_version mismatch", "version_mismatch")
        keep = {
            k: body[k]
            for k in ("positions", "active", "mode", "zoom", "sync", "swapped")
            if k in body
        }

        def _persist() -> None:
            tdir = deps.task_dir(task_id)
            tdir.mkdir(parents=True, exist_ok=True)
            path = tdir / "reading.json"
            existing: dict[str, Any] = {}
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = None
            if isinstance(raw, dict):
                existing = raw
            merged = {**existing, **keep}
            old_pos = existing.get("positions")
            new_pos = keep.get("positions")
            if isinstance(old_pos, dict) and isinstance(new_pos, dict):
                merged["positions"] = {**old_pos, **new_pos}
            atomic_json(path, merged)

        await asyncio.to_thread(_persist)
        return JSONResponse({"ok": True})
