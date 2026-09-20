"""上传路由：``/api/upload`` multipart → 魔数分发 upload_tex/upload_pdf/docx/epub。

§2.4 端点 + 表单字段闸与魔数路由错误面——本域私有，随叶内聚。
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

# FastAPI 注册期 eval_str 解析端点签名注解——Request/Response 须驻运行时
from fastapi import Request, Response  # noqa: TC002

from texlate.compile.toolchain import find_tool
from texlate.server.http import (
    _FILENAME_MAX,
    UploadPart,
    _accepted,
    _ApiError,
    _clean_task_options,
    _form_text,
    _parse_multipart,
)
from texlate.server.settings import TARGET_LANGS, validate_model
from texlate.server.store import new_task_id
from texlate.server.worker import sniff_upload

if TYPE_CHECKING:
    from fastapi import FastAPI

    from texlate.server.routers.deps import AppDeps


def _check_upload_route(route: str, babeldoc: str | None, filename: str) -> None:
    """魔数路由 → 错误面：unknown 400、pdf 无 babeldoc 501。

    docx/epub 经 ``export_document`` 双语插译通路（worker ``_run_doc``），
    转换器是进程内 export 包（bs4/lxml/python-docx 均为硬依赖），无外部
    工具探测面。
    """
    if route == "unknown":
        raise _ApiError(
            400,
            {
                "detail": f"无法识别上传格式: {filename}",
                "code": "unsupported_format",
            },
        )
    if route == "upload_pdf" and babeldoc is None:
        raise _ApiError(
            501,
            {
                "detail": (
                    "babeldoc 未安装：pipx install babeldoc / uv tool install babeldoc"
                ),
                "code": "unsupported_format",
            },
        )


def _discard_part(file: UploadPart) -> None:
    """spool 件兜底清理——已 rename 走则 ``unlink`` no-op，仍躺 spool 收掉。

    ``UploadPart.discard()`` 的本地件（share.py 同款 finally 幂等清理）——
    待 hoist 至 ``server/http.py`` 两域共吃。
    """
    with suppress(OSError):
        file.path.unlink(missing_ok=True)


def _require_file_part(form: dict[str, str | UploadPart]) -> UploadPart:
    """``file`` 字段闸：缺席/非文件字段 → 400；空文件收掉 spool 件后 → 400。"""
    file = form.get("file")
    if not isinstance(file, UploadPart):
        raise _ApiError(
            400,
            {
                "detail": "multipart field 'file' required",
                "code": "invalid_request",
            },
        )
    if file.size == 0:
        _discard_part(file)
        raise _ApiError(
            400, {"detail": "empty upload", "code": "invalid_request"}
        )
    return file


def _form_options(form: dict[str, str | UploadPart]) -> dict[str, Any]:
    """``options`` 字段 → 清洗后 dict：坏 JSON → 400；非 object → ``{}``。"""
    options_raw = _form_text(form, "options")
    try:
        options = json.loads(options_raw) if options_raw else {}
    except (ValueError, RecursionError):
        raise _ApiError(
            400,
            {"detail": "options 字段不是合法 JSON", "code": "invalid_request"},
        ) from None
    if not isinstance(options, dict):
        options = {}
    return _clean_task_options(options)


def _upload_fields(
    request: Request, form: dict[str, str | UploadPart], deps: AppDeps
) -> tuple[str, str, dict[str, Any]]:
    """表单字段 → ``(model, target_lang, options)``；非法 → ``_ApiError``。"""
    options = _form_options(form)
    try:
        model = validate_model(_form_text(form, "model") or deps.auth(request).model)
    except ValueError as e:
        raise _ApiError(400, {"detail": str(e), "code": "invalid_request"}) from e
    target_lang = _form_text(form, "target_lang") or str(
        deps.auth(request).settings["target_lang"]
    )
    if target_lang not in TARGET_LANGS:
        raise _ApiError(
            400,
            {
                "detail": f"target_lang ∈ {sorted(TARGET_LANGS)}",
                "code": "invalid_request",
            },
        )
    if _form_text(form, "main"):
        options["main"] = _form_text(form, "main")
    return model, target_lang, options


def register(app: FastAPI, deps: AppDeps) -> None:
    """挂载上传端点（§2.4）。"""

    @app.post("/api/upload")
    async def upload(request: Request) -> Response:
        """Multipart 上传：魔数路由 upload_tex/upload_pdf/docx/epub（§2.4）。"""
        form = await _parse_multipart(request, deps.spool_dir)
        file = _require_file_part(form)
        try:
            filename = file.filename or "upload.bin"
            # 魔数路由读全 blob（gzip/zip 容器判定非头字节可定）——CPU+读盘
            # 秒级，卸出事件循环；临时 bytes 不出本函数域
            route = await asyncio.to_thread(
                sniff_upload, file.path.read_bytes(), filename
            )
            _check_upload_route(route, deps.babeldoc or find_tool("babeldoc"), filename)
            model, target_lang, options = _upload_fields(request, form, deps)
            # re.sub 白名单放行 ``.``——``..`` 原样幸存会打成目录写（500+
            # 孤儿 task 目录），建行前先拒。>255B 名（NAME_MAX）会让落盘
            # 抛 ENAMETOOLONG 成 500——同闸先拒。
            safe = re.sub(r"[^A-Za-z0-9_.+-]", "_", Path(filename).name)
            if safe in (".", "..") or len(safe) > _FILENAME_MAX:
                raise _ApiError(
                    400,
                    {
                        "detail": f"unsafe filename: {filename!r}",
                        "code": "invalid_request",
                    },
                )
            # 先落 blob（建行前），再建行+入队——task_id 两侧共用
            task_id = new_task_id()
            updir = deps.root / "tasks" / task_id / "upload"

            def _stage() -> None:
                updir.mkdir(parents=True, exist_ok=True)
                # spool → 任务目录同文件系统 rename——零拷贝交接
                file.path.replace(updir / (safe or "upload.bin"))

            try:
                await asyncio.to_thread(_stage)
                row, status, extra = deps.create_and_enqueue(
                    request,
                    kind=route,
                    arxiv_id=None,
                    source_name=filename,
                    title=filename,
                    model=model,
                    target_lang=target_lang,
                    options=options,
                    prefer="fresh",
                    cache_key=None,
                    task_id=task_id,
                    incoming_bytes=file.size,
                )
            except Exception:
                # 建行/入队任何失败——upload blob 目录一并收掉，不留孤儿（B4）；
                # rmtree 是重 I/O，卸出事件循环
                await asyncio.to_thread(
                    shutil.rmtree, deps.root / "tasks" / task_id, ignore_errors=True
                )
                raise
            if str(row["id"]) != task_id:
                # idempotent 命中旧行——本次落盘 blob 成孤儿，连带目录清掉（B4）
                await asyncio.to_thread(
                    shutil.rmtree, deps.root / "tasks" / task_id, ignore_errors=True
                )
            return _accepted(row, status, extra)
        finally:
            # 仍躺 spool 即本次未消费——收掉（已 rename 走则 no-op）
            _discard_part(file)
