"""产物文件路由：清单 + kind 白名单下载（``?version=sha256`` 内容寻址）。

§2.3 端点 + URL kind → media_type 表与 ``src.tar`` 物理 mime 嗅探——
媒体表只服务本域，随叶内聚。
"""

from __future__ import annotations

import re
import stat as stat_mod
from typing import TYPE_CHECKING

# FastAPI 注册期 eval_str 解析端点签名注解——Request/Response 须驻运行时
from fastapi import Request, Response  # noqa: TC002
from fastapi.responses import FileResponse, JSONResponse

from texlate.server.http import _json_error
from texlate.server.worker import KIND_URL, URL_KIND

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

    from texlate.server.routers.deps import AppDeps

#: URL kind → media_type（§2.3 表）。``src.tar`` 不在表内——它的物理类型
#: 随任务 kind 变化（e-print tar.gz / 上传原文件回读），走 ``_src_tar_media``。
_MEDIA = {
    "en.pdf": "application/pdf",
    "zh.pdf": "application/pdf",
    "dual.pdf": "application/pdf",
    "dual.json": "application/json",
    "zh-src.zip": "application/zip",
    "compile.log": "text/plain; charset=utf-8",
    "md": "application/zip",
    "zh.docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    "zh.epub": "application/epub+zip",
    # arxiv_html 链的序列化 DOM 产物（file_get 对 text/html 补 CSP sandbox 闸）
    "en.html": "text/html; charset=utf-8",
    "zh.html": "text/html; charset=utf-8",
    "share.zip": "application/zip",
}

#: 上传任务 ``src.tar``（原始上传字节回读）按任务 kind 钉死的 mime
_SRC_TAR_KIND_MEDIA = {
    "upload_pdf": "application/pdf",
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "epub": "application/epub+zip",
}


def _src_tar_media(task_kind: str, path: Path) -> str:
    """``src.tar`` 的物理 mime：arxiv/share=e-print tar.gz；上传任务=原文件回读。

    ``upload_tex`` 的 blob 可能是 .tex/.zip/.tar/.tar.gz——按魔数给真值，
    认不出的按 octet-stream（不谎报 gzip）。
    """
    if task_kind in ("arxiv", "share"):
        return "application/gzip"
    fixed = _SRC_TAR_KIND_MEDIA.get(task_kind)
    if fixed is not None:
        return fixed
    if task_kind == "upload_tex":
        with path.open("rb") as fh:
            head = fh.read(263)
        if head[:2] == b"\x1f\x8b":
            return "application/gzip"
        if head[:4] == b"PK\x03\x04":
            return "application/zip"
        if head[257:262] == b"ustar":
            return "application/x-tar"
    return "application/octet-stream"


def register(app: FastAPI, deps: AppDeps) -> None:  # noqa: C901 -- 嵌套端点分支计入
    """挂载产物文件端点（§2.3）。"""

    @app.get("/api/files/{task_id}")
    async def files_list(request: Request, task_id: str) -> Response:
        """产物清单（db kind → bytes/sha256/created_at/url）。"""
        deps.get_task(request, task_id)
        out = {
            kind: {
                "bytes": rec["bytes"],
                "sha256": rec["sha256"],
                "created_at": rec["created_at"],
                "url": f"/api/files/{task_id}/{KIND_URL.get(kind, kind)}",
            }
            for kind, rec in deps.store.files(task_id).items()
        }
        return JSONResponse({"artifacts": out})

    @app.get("/api/files/{task_id}/{kind}")
    async def file_get(  # noqa: C901, PLR0911 -- 校验阶梯每层一个早退 return
        request: Request,
        task_id: str,
        kind: str,
        download: int = 0,
        version: str = "",
    ) -> Response:
        """产物下载：kind 白名单 + ``?version=`` sha256 校验 + download=1。"""
        row = deps.get_task(request, task_id)
        db_kind = URL_KIND.get(kind)
        if db_kind is None:
            return _json_error(404, f"unknown kind {kind!r}", "not_found")
        rec = deps.store.file_record(task_id, db_kind)
        if rec is None:
            return _json_error(404, f"no artifact {kind}", "not_found")
        if version and rec.get("sha256") and version != rec["sha256"]:
            return _json_error(
                409,
                f"version mismatch: have {rec['sha256'][:12]}",
                "version_mismatch",
            )
        if version and rec.get("sha256"):
            # ``?version=<sha256>`` 内容寻址命中——响应随 sha 不变而异变，
            # 私有缓存可钉死。no_store_mw 认 request.state 标记。
            request.state.cache_control = "private, immutable"
        task_root = (deps.root / "tasks" / task_id).resolve()
        path = (task_root / rec["path"]).resolve()
        if not path.is_relative_to(task_root):
            return _json_error(404, "artifact file missing", "not_found")
        try:
            stat_res = path.stat()
        except OSError:
            return _json_error(404, "artifact file missing", "not_found")
        if not stat_mod.S_ISREG(stat_res.st_mode):
            return _json_error(404, "artifact file missing", "not_found")
        headers = None
        if download:
            # 旧式 arxiv_id 含 '/'（hep-th/9901001）——filename 白名单化防畸形 header
            stem = re.sub(r"[^A-Za-z0-9_.+-]", "_", str(row.get("arxiv_id") or task_id))
            headers = {
                "Content-Disposition": (f'attachment; filename="texlate-{stem}-{kind}"')
            }
        try:
            media = (
                _src_tar_media(str(row["kind"]), path)
                if kind == "src.tar"
                else _MEDIA.get(kind, "application/octet-stream")
            )
        except OSError:
            # src.tar 魔数嗅探 open() 竞删——与 stat 同归 404
            return _json_error(404, "artifact file missing", "not_found")
        if media.startswith("text/html"):
            # html 产物同源伺服——直接导航时文档内幸存脚本可在同源上下文
            # 打 mutating /api；CSP sandbox（无 allow-*）整文档脚本全灭。
            # 纵深防御：worker _sanitize_dom 主防线 + 前端 DOMPurify 之外的
            # 服务端兜底；不挡 img-src（sandbox 只禁脚本）
            headers = {**(headers or {}), "Content-Security-Policy": "sandbox"}
        # stat_result 直传：__call__ 跳过惰性 stat——不给 is_file→serve 留
        # TOCTOU 窗（starlette 惰性 stat 缺文件抛 RuntimeError 裸 500）
        return FileResponse(
            path, media_type=media, headers=headers, stat_result=stat_res
        )
