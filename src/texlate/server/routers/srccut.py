"""srccut 路由：copy-latex 选区 → LaTeX 源切片端点。

``POST /api/task/{task_id}/latex``（copy-latex 实现文档 §后端改动）：
seqs + 可选 head/tail anchor → ``{latex,chunks,files,mode_used,approx?,
truncated?}``。纯逻辑全在 ``texlate.server.srccut``——本叶只持租户闸/
kind 闸/body 闸与文件 IO 卸载（``asyncio.to_thread``）。

只读端点：chunks 行与 base/ 树在终态后冻结（单块重译不改 span/src_text），
无写无锁；在飞任务（translating 中）chunks 已建同样可服务。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

# FastAPI 注册期 eval_str 解析端点签名注解——Request 须驻运行时
from fastapi import Request  # noqa: TC002

from texlate.server import srccut
from texlate.server.http import _ApiError, _read_body

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

    from texlate.server.routers.deps import AppDeps


def _src_tar_path(deps: AppDeps, task_id: str) -> Path | None:
    """``src_tar`` 登记 blob 落盘定位：files 表 + resolve/is_relative_to 防逃逸。

    ``refs._src_tar_path`` 同款口径（登记路径可能脏，resolve 后必须仍在
    task 目录内）。路由内私有副本——两叶共享挪 deps 是另一笔重构。
    """
    rec = deps.store.file_record(task_id, "src_tar")
    if rec is None:
        return None
    task_root = deps.task_dir(task_id).resolve()
    cand = (task_root / str(rec["path"])).resolve()
    if cand.is_relative_to(task_root) and cand.is_file():
        return cand
    return None


def register(app: FastAPI, deps: AppDeps) -> None:
    """挂 ``POST /api/task/{task_id}/latex``。"""

    @app.post("/api/task/{task_id}/latex")
    async def task_latex(request: Request, task_id: str) -> dict[str, Any]:
        """选区 → 原始 LaTeX 切片（三级回落 + sentclip + gap 回收）。

        400 seqs 非法/超帽；404 task（``get_task`` 租户闸）；
        422 ``arxiv_html``（无 tex 源——DOM 链 ``src/`` 只有 index.html）
        或源全不可得。
        """
        row = deps.get_task(request, task_id)
        if str(row["kind"]) == "arxiv_html":
            raise _ApiError(
                422,
                {
                    "detail": "arxiv_html 链无 LaTeX 源",
                    "code": "no_latex_source",
                },
            )
        # _read_body 一口价：4MB 闸 + CT 415 + 坏 JSON→400——勿手搓 req.json()
        body = await _read_body(request)
        try:
            req = srccut.parse_request(body)
        except srccut.SrcCutError as e:
            raise _ApiError(e.status, {"detail": e.detail, "code": e.code}) from e
        rows = deps.store.spans_by_seqs(task_id, list(req.seqs))
        task_dir = deps.task_dir(task_id)
        try:
            # 文件 IO（base 树读/tar 成员拆/dual.json 解析）卸出事件循环
            return await asyncio.to_thread(
                srccut.cut_latex,
                task_dir=task_dir,
                src_tar=_src_tar_path(deps, task_id),
                dual_path=task_dir / "dual.json",
                rows=rows,
                req=req,
            )
        except srccut.SrcCutError as e:
            raise _ApiError(e.status, {"detail": e.detail, "code": e.code}) from e
