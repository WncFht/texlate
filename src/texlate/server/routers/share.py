"""share 域路由：``.share.zip`` 导入（校验解包→建行）与终态任务事后打包发布。

原 ``create_app`` share 导入/导出两端点 + manifest key_parts 白名单闸
+ share.zip 任务目录镜像登记（产物面 ``share.zip`` kind）。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import sqlite3
from typing import TYPE_CHECKING

# FastAPI 注册期 eval_str 解析端点签名注解——Request/Response 须驻运行时
from fastapi import Request, Response  # noqa: TC002
from fastapi.responses import JSONResponse

from texlate.arxiv.fetch import normalize_arxiv_id, valid_id
from texlate.pipecore import FRONT_MATTER_NAMES
from texlate.server.http import (
    _accepted,
    _ApiError,
    _discard_part,
    _form_options,
    _json_error,
    _options_json_checked,
    _parse_multipart,
    _require_file_part,
)
from texlate.server.settings import (
    TARGET_LANGS,
    share_dir,
    validate_model,
)
from texlate.server.store import new_task_id, row_json
from texlate.server.worker import (
    Secrets,
    TaskCtx,
    cache_key_for,
    share_pack_publish,
)
from texlate.share import (
    REQUIRED_ARTIFACTS,
    ShareError,
    index_lookup,
    share_key,
    unpack_share,
)

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

    from texlate.server.routers.deps import AppDeps
    from texlate.share import ShareManifest

log = logging.getLogger(__name__)


def _share_parts_checked(
    parts: dict[str, str],
) -> tuple[str, str, str, str, int | None]:
    """Manifest key_parts → ``(base, ver_s, model, lang, ver)`` 白名单校验。

    ``arxiv_id`` 必须裸 id（版本只走 ``version`` 键，嵌 ``vN`` 后缀即
    400）；``target_lang`` ∈ TARGET_LANGS；``model`` 过 ``validate_model``；
    ``version`` 只收 ``vN`` 钉版形或空串（``_norm_version`` 可能的
    非数字形在此闸死，``int()`` 不会炸）。全数违例 → ``share_invalid``。
    """
    base, embedded = normalize_arxiv_id(parts["arxiv_id"])
    if embedded is not None or not valid_id(base):
        raise _ApiError(
            400,
            {
                "detail": f"key_parts.arxiv_id 非法: {parts['arxiv_id']!r}",
                "code": "share_invalid",
            },
        )
    lang = parts["target_lang"]
    if lang not in TARGET_LANGS:
        raise _ApiError(
            400,
            {
                "detail": f"key_parts.target_lang ∈ {sorted(TARGET_LANGS)}",
                "code": "share_invalid",
            },
        )
    try:
        model = validate_model(parts["model"])
    except ValueError as e:
        raise _ApiError(
            400, {"detail": f"key_parts.model: {e}", "code": "share_invalid"}
        ) from e
    ver_s = parts["version"]  # "v5" 钉版 / "" latest 别名
    if ver_s and not re.fullmatch(r"v\d{1,3}", ver_s):
        raise _ApiError(
            400,
            {
                "detail": f"key_parts.version 须为 vN 钉版形: {ver_s!r}",
                "code": "share_invalid",
            },
        )
    return base, ver_s, model, lang, (int(ver_s[1:]) if ver_s else None)


def _mirror_share_zip(deps: AppDeps, task_id: str, bundle: Path) -> tuple[int, str]:
    """发布包流式拷进 ``tasks/{id}/share.zip`` → ``(bytes, sha256)``。

    ``file_get`` 只服 ``tasks/{id}/`` 相对路径（confine 闸）——share_dir
    的包对 files manifest 不可达，拷一份任务目录内镜像上产物面。
    重 I/O——调用方 ``to_thread`` 卸载。
    """
    dst = deps.task_dir(task_id) / "share.zip"
    digest = hashlib.sha256()
    size = 0
    with bundle.open("rb") as src, dst.open("wb") as out:
        while chunk := src.read(1 << 20):
            out.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


async def _register_share_zip(deps: AppDeps, task_id: str, bundle: Path) -> None:
    """share.zip 镜像落盘 + files 登记 ``share_zip``（前端产物面）。

    best-effort：镜像拷贝失败只留 warning——共享包发布（包文件 +
    index.jsonl 行）已成功，产物面缺项由重发 pack 自愈，不把 200
    打成 500。
    """
    try:
        size, sha = await asyncio.to_thread(_mirror_share_zip, deps, task_id, bundle)
    except OSError as e:
        log.warning("share.zip 镜像登记失败 %s: %s", task_id, e)
        return
    deps.store.put_file(task_id, "share_zip", "share.zip", size=size, sha256=sha)


def register(app: FastAPI, deps: AppDeps) -> None:  # noqa: C901, PLR0915 -- 端点面平铺
    """挂载 share 域端点（导入 + 事后打包）。"""

    @app.post("/api/share/import")
    async def share_import(request: Request) -> Response:
        """``.share.zip`` → 校验解包 → ``kind="share"`` 任务入队。

        端点只做机械校验（``unpack_share``：format/share_key 自洽/逐产物
        sha256 对账）+ key_parts 白名单（arxiv_id 形态、target_lang ∈
        TARGET_LANGS、model 合法性、version 钉版形 ``vN``）；译文可信度
        由 worker ``_run_share`` 全链重跑承担（2026-09-16-shared-cache.md §5）。
        model/lang/arxiv_id/version 一律取 manifest key_parts（内容生产
        者口径）——与上传者自身 model 设置不同**不拒**：包自描述，任务行
        记 manifest 真值，上传者配置不进寻址。``cache_key`` 按钉版形态
        重算——后来的 ``id@vN`` 请求经 ``find_reusable`` 真命中本产物。
        """
        form = await _parse_multipart(request, deps.spool_dir)
        file = _require_file_part(form)
        try:
            tid = new_task_id()
            tdir = deps.task_dir(tid)

            def _stage() -> ShareManifest:
                bundle_dir = tdir / "upload"
                bundle_dir.mkdir(parents=True, exist_ok=True)
                bundle = bundle_dir / "bundle.share.zip"
                file.path.replace(bundle)  # spool → 任务目录同 fs rename
                return unpack_share(bundle, tdir / "share")

            try:
                # 逐成员 sha256+解压跑满 CPU 秒级——卸出事件循环（share_pack 同口径）
                mf = await asyncio.to_thread(_stage)
                parts = mf.key_parts
                base, ver_s, model, lang, ver = _share_parts_checked(parts)
                options = _form_options(form)
                # 审计载荷强制覆盖——调用方 options 不得伪造 share 来源字段。
                # 注入在 64KB 闸之后发生（manifest 字段已经
                # ``_manifest_field_max`` 收敛），注入后重跑尺寸闸兜底。
                options["share"] = {
                    "share_key": mf.share_key,
                    "contributor": mf.contributor,
                    "created_at": mf.created_at,
                    "key_parts": dict(parts),
                }
                # 任务 fm 锁定为包内容集——对账面要求本地扫描集与生产者
                # 同料（多扫必 miss、少扫留 extra）；同时让 cache_key/
                # 扫描/manifest 三面对同一显式 dict 自洽。调用方自带
                # front_matter 在此被覆盖（∩NAMES 挡包内脏串）
                bundle_fm = (
                    frozenset(
                        x.strip()
                        for x in str(parts.get("front_matter") or "").split(",")
                        if x.strip()
                    )
                    & FRONT_MATTER_NAMES
                )
                options["front_matter"] = {
                    k: k in bundle_fm for k in ("abstract", "title", "author")
                }
                _options_json_checked(options)
                row, status, extra = deps.create_and_enqueue(
                    request,
                    kind="share",
                    arxiv_id=f"{base}{ver_s}",
                    source_name=file.filename or "bundle.share.zip",
                    title="",
                    model=model,
                    target_lang=lang,
                    options=options,
                    prefer="reuse",
                    cache_key=cache_key_for(
                        arxiv_id=base,
                        version=ver,
                        model=model,
                        target_lang=lang,
                        api_key=deps.auth(request).api_key,
                        # 包内容随生产者 fm 定形——导入任务须与后续同 fm
                        # 请求同桶（key_parts 缺键 = 前置全盖过的历史包）
                        front_matter=bundle_fm,
                    ),
                    task_id=tid,
                    incoming_bytes=file.size,
                )
            except ShareError as e:
                await deps.drop_task_dir(tid)
                raise _ApiError(
                    400,
                    {
                        "detail": f"share bundle invalid: {e}",
                        "code": "share_invalid",
                    },
                ) from e
            except sqlite3.IntegrityError:
                # reuse 语义下并发同键撞 ACTIVE 唯一索引——归 duplicate_active
                await deps.drop_task_dir(tid)
                raise _ApiError(
                    409,
                    {"detail": "active task exists", "code": "duplicate_active"},
                ) from None
            except Exception:
                # 落盘/解包/校验/建行/入队任何失败（含 _ApiError 与非预期异常）
                # ——task 目录一并收掉，不留孤儿（upload 端点 B4 同口径）
                await deps.drop_task_dir(tid)
                raise
            if str(row["id"]) != tid:
                # reuse/idempotent 命中旧行——本次解包现场作废（行从未建）
                await deps.drop_task_dir(tid)
            return _accepted(row, status, extra)
        finally:
            _discard_part(file)

    @app.post("/api/task/{task_id}/share/pack")
    async def share_pack(request: Request, task_id: str) -> Response:  # noqa: C901, PLR0911 -- 守卫阶梯平铺
        """终态任务事后打 ``.share.zip``（2026-09-16-shared-cache.md §6「完成后提示分享」服务端面）。

        与 worker ``_maybe_share_pack`` 完成钩同口径：key_parts 由
        ``worker.share_pack_manifest`` 从任务行现值派生，产物取
        ``tasks/{id}/`` 下 ``REQUIRED_ARTIFACTS``（zh.pdf 缺席落 partial
        包）。幂等：share_key 已入 ``index.jsonl`` 且包文件在场 → 直接
        200 不重打。``kind=share``（导入产物不自包）/``arxiv_html``
        （html 链产不出 zh-src.zip，且 HTML chunk 与 share 包 TeX chunk
        不对版不可比对）与 reuse 命中任务（产物物化自他任务、生效术语表
        不可知）→ 422；非 done/partial → 409；缺必需产物 → 422。
        响应 ``{share_key, url, bytes}``——``url`` 与 index 行同口径
        （包文件名）。
        """
        row = deps.get_task(request, task_id)
        if str(row["kind"]) in ("share", "arxiv_html"):
            return _json_error(
                422,
                f"kind={row['kind']} 任务不打共享包（产物形态不参与共享寻址）",
                "share_pack_rejected",
            )
        opts = row_json(row, "options_json")
        if opts.get("reuse_hit"):
            return _json_error(
                422,
                f"reuse 命中任务（产物物化自 {opts['reuse_hit']}）不打共享包",
                "share_pack_rejected",
            )
        if row["status"] not in ("done", "partial"):
            return _json_error(
                409,
                f"任务状态 {row['status']}：仅 done/partial 终态可打包",
                "invalid_state",
            )
        task_root = deps.task_dir(task_id)
        ctx = TaskCtx(
            store=deps.store,
            bus=deps.bus,
            task_id=task_id,
            row=row,
            secrets=Secrets(),
            root=task_root,
        )
        # manifest 派生会读生效术语表文件算 hash（重 I/O）——卸出 loop；
        # 与 worker 侧 ``_share_pack_try`` 的 ``_to_thread`` 口径对齐
        manifest = await asyncio.to_thread(deps.worker.share_pack_manifest, ctx, row)
        if manifest is None:
            return _json_error(
                422,
                "任务无 arxiv_id（不参与共享寻址）",
                "share_pack_rejected",
            )
        key = share_key(
            str(manifest["arxiv_id"]),
            str(manifest["version"]),
            str(manifest["model"]),
            str(manifest["prompt_ver"]),
            str(manifest["target_lang"]),
            str(manifest["glossary_hash"]),
            str(manifest["pipeline_ver"]),
            front_matter=str(manifest.get("front_matter") or ""),
        )
        out_dir = share_dir(deps.root)
        try:
            # index.jsonl 整读全扫——append-only 索引随时间增长，卸出 loop
            hit = await asyncio.to_thread(index_lookup, out_dir / "index.jsonl", key)
        except (OSError, UnicodeDecodeError) as e:
            # 索引读挂不挡重打——index_lookup 实抛面即此二类（坏行内部跳过，
            # 不抛 ShareError）；append-only last-wins 读出侧自愈
            log.warning("share index unreadable for %s, repacking: %s", task_id, e)
            hit = None
        if hit is not None:
            # index 行 url 按约定是扁平包文件名——只认扁平名防越界探测；
            # NUL 漏检会让 stat() 抛 ValueError（不属 OSError）炸 500
            name = str(hit.get("url") or "")
            flat = (
                "/" not in name
                and "\\" not in name
                and "\x00" not in name
                and name not in ("", ".", "..")
            )
            if flat:
                try:
                    size = (out_dir / name).stat().st_size
                except OSError:
                    size = -1  # 行在包不在（或竞态消失）——按未命中走重打
                if size >= 0:
                    await _register_share_zip(deps, task_id, out_dir / name)
                    return JSONResponse({"share_key": key, "url": name, "bytes": size})
        missing = [n for n in REQUIRED_ARTIFACTS if not (task_root / n).is_file()]
        if missing:
            return _json_error(
                422,
                f"缺必需产物: {missing}",
                "share_pack_artifacts",
            )
        try:
            bundle, mf = await asyncio.to_thread(
                share_pack_publish, task_root, manifest, out_dir
            )
        except ShareError as e:
            return _json_error(422, f"share 打包失败: {e}", "share_pack_failed")
        await _register_share_zip(deps, task_id, bundle)
        return JSONResponse(
            {
                "share_key": mf.share_key,
                "url": bundle.name,
                "bytes": bundle.stat().st_size,
            }
        )
