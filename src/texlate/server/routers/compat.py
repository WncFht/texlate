"""hjfy 轮询协议兼容面：``/api/arxivStatus`` + ``/api/arxivFiles``（competitors.md §4）。

状态词汇按 hjfy 插件轮询协议映射（``_HJFY_STATUS``）；查源是 tenant 内
arxiv_id 最新任务行（``store.find_latest_by_arxiv``）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# FastAPI 注册期 eval_str 解析端点签名注解——Request/Response 须驻运行时
from fastapi import Request, Response  # noqa: TC002
from fastapi.responses import JSONResponse

from texlate.arxiv.fetch import normalize_arxiv_id, valid_id
from texlate.server.http import _ApiError
from texlate.server.store import TERMINAL_STATUSES
from texlate.server.worker import KIND_URL

if TYPE_CHECKING:
    from fastapi import FastAPI

    from texlate.server.routers.deps import AppDeps

#: 任务状态 → hjfy ``arxivStatus`` 词汇（compat 端点映射表）。hjfy 侧
#: ``start``/``finished`` 都被客户端当中间态（finished 仅表管线跑完、
#: zhCN 未落地还会再 prime）；本侧终态里 done/partial 有产物出才算
#: finished，弃单系归 failed、needs_auth 归 error、fault 同名直译。
_HJFY_STATUS = {
    "queued": "start",
    "fetching": "start",
    "parsing": "start",
    "translating": "start",
    "compiling": "start",
    "done": "finished",
    "partial": "finished",
    "cancelled": "failed",
    "interrupted": "failed",
    "needs_auth": "error",
    "fault": "fault",
}


def register(app: FastAPI, deps: AppDeps) -> None:  # noqa: C901 -- 端点面平铺
    """挂载 hjfy 兼容端点。"""

    def _hjfy_row(request: Request, arxiv_id: str) -> dict[str, Any]:
        """``hjfy`` 轮询端点共用解析：id 归一校验 + tenant 内最新任务行（无 → 404）。"""
        base, ver = normalize_arxiv_id(arxiv_id)
        if not valid_id(base):
            raise _ApiError(
                400,
                {
                    "detail": f"invalid arxiv id: {arxiv_id!r}",
                    "code": "invalid_request",
                },
            )
        row = deps.store.find_latest_by_arxiv(deps.auth(request).tenant, base, ver)
        if row is None:
            # 刻意不走统一 ``{"detail","code"}`` 错误面：hjfy 轮询客户端
            # 按字面 ``{"error":"not_found"}`` 判定 404，tests/
            # test_server_api_compat.py 以全等断言钉死该协议契约。
            raise _ApiError(404, {"error": "not_found"})
        return row

    @app.get("/api/arxivStatus/{arxiv_id:path}")
    async def arxiv_status(request: Request, arxiv_id: str) -> Response:
        """``hjfy`` 轮询面（competitors.md §4）：``{status, info}`` + 扩展键。

        状态词汇按 hjfy 插件轮询协议映射（``_HJFY_STATUS``）；
        ``progress``/``task_id`` 是附加信息——只读 status/info 的客户端
        不受影响。
        """
        row = _hjfy_row(request, arxiv_id)
        return JSONResponse(
            {
                "status": _HJFY_STATUS.get(str(row["status"]), "error"),
                "info": str(row.get("message") or ""),
                "progress": int(row["progress"]),
                "task_id": str(row["id"]),
            }
        )

    @app.get("/api/arxivFiles/{arxiv_id:path}")
    async def arxiv_files(request: Request, arxiv_id: str) -> Response:
        """``hjfy`` 产物面：``{status, msg, data:{id,title,origin,zhCN,zhCNTar,isDeepSeek}}``。

        ``status:0`` + ``data.zhCN`` 非空是客户端的「译好」判据；
        ``101`` + 「请登录」= 需认证；其余态 ``msg`` 载任务行 message
        （进行中/失败文案驱动 pending/dead 判定）。产物 URL 指到
        ``/api/files/{id}/{kind}`` 下载路由——en.pdf→origin、
        zh.pdf→zhCN、zh-src.zip→zhCNTar；未产出的 kind 给空串。
        """
        row = _hjfy_row(request, arxiv_id)
        tid = str(row["id"])
        recs = deps.store.files(tid)

        def _url(kind: str) -> str:
            if kind not in recs:
                return ""
            return f"/api/files/{tid}/{KIND_URL[kind]}"

        if str(row["status"]) == "needs_auth":
            code, msg = 101, "请登录"
        elif recs.get("zh_pdf"):
            code, msg = 0, ""
        elif str(row["status"]) in TERMINAL_STATUSES:
            code, msg = 0, str(row.get("message") or "翻译失败")
        else:
            code, msg = 0, "正在处理中"
        return JSONResponse(
            {
                "status": code,
                "msg": msg,
                "data": {
                    "id": str(row.get("arxiv_id") or ""),
                    "title": str(row.get("title") or ""),
                    "origin": _url("en_pdf"),
                    "zhCN": _url("zh_pdf"),
                    "zhCNTar": _url("zh_src_zip"),
                    "isDeepSeek": False,
                },
            }
        )
