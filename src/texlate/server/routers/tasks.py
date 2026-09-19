"""任务生命周期路由：arxiv 建任务 + 快照/SSE + chunks 分页 + 列表 + cancel/retry/delete。

原 ``create_app`` §2.1/§2.2/§2.5 任务域端点（+ 单块重译）。共享闭包经
``AppDeps`` 方法化：``deps.auth``/``deps.get_task``/``deps.secrets_for``/
``deps.create_and_enqueue``。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from contextlib import suppress
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from texlate.arxiv.fetch import normalize_arxiv_id, valid_id
from texlate.pipecore import front_matter_of
from texlate.server.events import sse_frame
from texlate.server.http import (
    _accepted,
    _artifacts,
    _clean_task_options,
    _json_error,
    _options_json_checked,
    _read_body,
)
from texlate.server.settings import TARGET_LANGS, validate_model
from texlate.server.store import (
    ACTIVE_STATUSES,
    CHUNKS_PAGE_MAX,
    RETRYABLE_FROM,
    TERMINAL_STATUSES,
    StoreError,
    TransitionError,
    row_json,
    slim_task_dir,
)
from texlate.server.worker import cache_key_for

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from texlate.server.routers.deps import AppDeps

#: ``/api/tasks?status=`` 过滤的合法值域——11 态机全集（ACTIVE+TERMINAL）。
_ALL_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES


def register(app: FastAPI, deps: AppDeps) -> None:  # noqa: C901, PLR0915 -- 端点面平铺
    """挂载任务域端点（§2.1/§2.2/§2.5 + retranslate）。"""
    # ------------------------------------------------------------ §2.1 arxiv

    @app.post("/api/arxiv/{arxiv_id:path}/translate")
    async def arxiv_translate(request: Request, arxiv_id: str) -> Response:
        """建 arxiv 任务：202 + cache_key dedup/reuse（§2.1）。"""
        base, ver = normalize_arxiv_id(arxiv_id)
        if not valid_id(base):
            return _json_error(
                400, f"invalid arxiv id: {arxiv_id!r}", "invalid_request"
            )
        body = await _read_body(request)
        try:
            options = dict(body.get("options") or {})
        except (TypeError, ValueError):
            return _json_error(
                400, "options 须为 object 或 KV 对列表", "invalid_request"
            )
        options = _clean_task_options(options)
        try:
            model = validate_model(str(body.get("model") or deps.auth(request).model))
        except ValueError as e:
            return _json_error(400, str(e), "invalid_request")
        target_lang = str(
            body.get("target_lang") or deps.auth(request).settings["target_lang"]
        )
        if target_lang not in TARGET_LANGS:
            return _json_error(
                400, f"target_lang ∈ {sorted(TARGET_LANGS)}", "invalid_request"
            )
        if body.get("glossary"):
            options["glossary"] = str(body["glossary"])
        prefer = str(options.get("prefer") or "reuse")
        if prefer not in ("reuse", "fresh"):
            return _json_error(400, "options.prefer ∈ reuse|fresh", "invalid_request")
        # source 已经 _clean_task_options 白名单规范化（eprint|html）。
        # eprint 是历史默认、键材料不动（存量缓存续命）——仅非默认源追加
        # ``source=`` 成分（与 worker cache_key_for 的 no-op 默认同语义，
        # 也让本调用点对未带 source 形参的旧签名兼容）
        source = str(options.get("source") or "eprint")
        kind = "arxiv_html" if source == "html" else "arxiv"
        # front_matter 改变扫描块集 → 进 dedup 材料分桶（∅ 不配成分，
        # 与前置全盖过的存量缓存同桶——见 cache_key_for 文档）
        cache_key = cache_key_for(
            arxiv_id=base,
            version=ver,
            model=model,
            target_lang=target_lang,
            api_key=deps.auth(request).api_key,
            source=source,
            front_matter=front_matter_of(options),
        )
        row, status, extra = deps.create_and_enqueue(
            request,
            kind=kind,
            arxiv_id=base,
            source_name=arxiv_id,
            title="",
            model=model,
            target_lang=target_lang,
            options=options,
            prefer=prefer,
            cache_key=cache_key,
        )
        return _accepted(row, status, extra)

    # ------------------------------------------------------------ §2.2 task/SSE

    @app.get("/api/task/{task_id}")
    async def task_get(request: Request, task_id: str) -> Response:
        """快照 or SSE 流（Accept: text/event-stream；Last-Event-ID 重放）。"""
        deps.get_task(request, task_id)
        accept = request.headers.get("accept", "")
        # RFC 9110：媒体类型大小写不敏感——TEXT/EVENT-STREAM 也应进 SSE
        if "text/event-stream" not in accept.lower():
            return JSONResponse(
                deps.store.snapshot(task_id, artifacts=_artifacts(deps.store, task_id))
            )
        try:
            last_id = int(request.headers.get("last-event-id", "0") or 0)
        except ValueError:
            last_id = 0
        # SQLite 绑参 int64 界——超界声明夹到界值（语义=客户端已见至该 seq，
        # 大值→无重放，负值→全量重放）；不夹则 events_since OverflowError
        # 在 snapshot 帧发出后炸断流。
        last_id = max(-(2**63), min(last_id, 2**63 - 1))

        async def gen() -> AsyncIterator[dict[str, Any]]:
            snap = deps.store.snapshot(
                task_id, artifacts=_artifacts(deps.store, task_id)
            )
            yield sse_frame({"seq": 0, "type": "snapshot", "data": snap})
            async for ev in deps.bus.stream(task_id, last_event_id=last_id):
                yield sse_frame(ev)

        return EventSourceResponse(gen(), ping=15)

    @app.get("/api/task/{task_id}/chunks")
    async def task_chunks(
        request: Request,
        task_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        # 声明上限必须与 store 钳位同值——高于 CHUNKS_PAGE_MAX 的 limit
        # 会拿 200 却静默丢尾页（clamp 不回告）
        limit: Annotated[int, Query(ge=1, le=CHUNKS_PAGE_MAX)] = 200,
        # 增量轮询：逗号分隔 seq 集定点取（web 端按 SSE 已知状态只拉脏 seq，
        # 省掉每 2.5s 全窗几 MB 的重拉）；与 offset/limit 互斥，优先此参数
        seqs: str = "",
    ) -> Response:
        """Chunk 窄列分页（翻译中流式预览面，fe-U1 配套）。

        返回 ``{chunks: [{seq, kind, status, en, zh}], total}``——pending
        块 ``zh`` 为空串；``total`` 是全集大小供前端翻页/进度条。
        ``?seqs=1,2,3`` 定点模式：只回命中 seq 的行（个数 ≤CHUNKS_PAGE_MAX，
        非整数/超限 400），total 语义不变。
        """
        deps.get_task(request, task_id)
        if seqs:
            try:
                wanted = {int(s) for s in seqs.split(",") if s.strip()}
            except ValueError:
                return _json_error(400, "seqs 须为逗号分隔整数", "invalid_request")
            if len(wanted) > CHUNKS_PAGE_MAX:
                return _json_error(
                    400,
                    f"seqs 个数 ≤{CHUNKS_PAGE_MAX}",
                    "invalid_request",
                )
            rows, total = deps.store.chunks_by_seqs(task_id, sorted(wanted))
        else:
            rows, total = deps.store.chunks_page(task_id, offset=offset, limit=limit)
        return JSONResponse(
            {
                "chunks": [
                    {
                        "seq": r["seq"],
                        "kind": r["kind"],
                        "status": r["status"],
                        "en": r.get("src_text") or "",
                        "zh": r.get("translation") or "",
                    }
                    for r in rows
                ],
                "total": total,
            }
        )

    # ------------------------------------------------------------ §2.5 helpers

    @app.get("/api/tasks")
    async def tasks_list(
        request: Request,
        status: str = "",
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> Response:
        """Tenant 过滤任务列表（``?status=`` 枚举校验再过滤；``limit``/``offset`` 分页）。

        ``total`` = 过滤后全集大小（非本页行数），前端分页条用。
        非法 ``status`` 值 400——不校验会静默返空 200，调用方无从分辨
        「无匹配」与「参数打错」。
        """
        if status and status not in _ALL_STATUSES:
            return _json_error(
                400,
                f"status ∈ {sorted(_ALL_STATUSES)}",
                "invalid_request",
            )
        rows, total = deps.store.list_tasks_page(
            deps.auth(request).tenant,
            status=status or None,
            limit=limit,
            offset=offset,
        )
        return JSONResponse(
            {
                "tasks": [
                    {
                        "task_id": r["id"],
                        "kind": r["kind"],
                        "status": r["status"],
                        "stage": r["stage"],
                        "progress": r["progress"],
                        "message": r["message"],
                        "title": r["title"],
                        "arxiv_id": r["arxiv_id"],
                        "source_name": r["source_name"],
                        "target_lang": r["target_lang"],
                        "model": r["model"],
                        "created_at": r["created_at"],
                        "updated_at": r["updated_at"],
                        "counters": {
                            "total": r["total_chunks"],
                            "done": r["done_chunks"],
                            "cached": r["cached_chunks"],
                            "failed": r["failed_chunks"],
                            "tokens": r["tokens"],
                        },
                        "error": (
                            json.loads(r["error_json"]) if r["error_json"] else None
                        ),
                        # 行快照水位——前端 refresh reconcile 据以拒旧读回退
                        "last_seq": r["last_seq"],
                    }
                    for r in rows
                ],
                "total": total,
            }
        )

    @app.post("/api/task/{task_id}/cancel")
    async def task_cancel(request: Request, task_id: str) -> Response:
        """ACTIVE → cancelled；跑中任务 cancel asyncio task + done 事件。"""
        deps.get_task(request, task_id)
        try:
            deps.store.transition(task_id, "cancelled", message="已取消")
        except TransitionError as e:
            return _json_error(409, str(e), "invalid_transition")
        deps.runner.cancel_running(task_id)
        row = deps.store.get(task_id) or {}
        deps.bus.publish(
            task_id,
            "done",
            {
                "status": "cancelled",
                "artifacts": _artifacts(deps.store, task_id),
                "stats": {
                    "tokens": row.get("tokens", 0),
                    "seconds": round(
                        time.time() - float(row.get("created_at") or 0), 1
                    ),
                    "chunks_failed": row.get("failed_chunks", 0),
                },
            },
        )
        return JSONResponse({"task_id": task_id, "status": "cancelled"})

    @app.post("/api/task/{task_id}/retry")
    async def task_retry(request: Request, task_id: str) -> Response:  # noqa: C901 -- 校验阶梯平铺
        """终态/needs_auth → queued 重入队；body 只收 ``{main, options}``。

        ``model``/``target_lang`` 是 cache_key 口径成员——换值得新建任务，
        静默丢弃比报错糟，故 body 白名单外的键一律 400。
        """
        row = deps.get_task(request, task_id)
        # 状态守卫必须在一切 mutation 之前——done 任务 retry 只许纯 409，
        # 不得先清 chunks/删目录/写 options（B3）
        if row["status"] not in RETRYABLE_FROM:
            raise TransitionError(task_id, row["status"], "queued")
        body = await _read_body(request)
        header_key = request.headers.get("x-texlate-key", "")
        if row["status"] == "needs_auth" and not header_key:
            return _json_error(
                401,
                "auth_source=header：重试必须重带 X-Texlate-Key",
                "auth_required",
            )
        bad_keys = sorted(set(body) - {"main", "options"})
        if bad_keys:
            return _json_error(
                400,
                f"retry body 仅支持 main/options，不识别: {bad_keys}",
                "invalid_request",
            )
        if "options" in body and not isinstance(body["options"], dict):
            return _json_error(400, "retry options 须为 object", "invalid_request")
        opts = row_json(row, "options_json")
        if isinstance(body.get("options"), dict):
            # 合并臂不注默认——``inject_defaults=False`` 只校验 body 真实
            # 出现的键，缺席的 ``source`` 不会被改回 ``eprint``（html 任务
            # 的存量 source 原样保留）
            opts.update(_clean_task_options(body["options"], inject_defaults=False))
        if body.get("main"):
            opts["main"] = str(body["main"])
        # 合并结果重跑帽闸——_clean_task_options 只闸 body 增量，存量+增量
        # 可越 _OPTIONS_JSON_CAP（与 share 导入臂 post-merge 重闸同口径）。
        # 必须先于 transition——超帽 400 拒在抢 queued 前，任务行不动
        options_json = _options_json_checked(opts)
        main_req = str(opts.get("main") or "")
        # body 显式带 engine 且 ≠ 上轮持久化的 ``engine_resolved`` → 换引擎
        # 与换 main 同档清废：base/ 树是旧引擎 ``normalize_project`` 产物，
        # ``.base-done`` 哨兵不抹则 ``_build_base`` 整段跳过、engine_resolved
        # 原地复活旧引擎（``_clean_task_options`` 已摘 body 内保留键，
        # 合并后 opts 里读到的 engine_resolved 恒是上轮真值）
        body_opts = body.get("options")
        engine_req = (
            str(body_opts.get("engine") or "") if isinstance(body_opts, dict) else ""
        )
        engine_stale = bool(engine_req) and engine_req != str(
            opts.get("engine_resolved") or ""
        )
        # 原子守卫先行——抢到 queued 前不做任何破坏清理。双发 retry 时后者
        # 在此 409 出局，不再抹掉 worker 已重插的 chunks / 覆盖 options（B3）
        try:
            deps.store.transition(task_id, "queued", message="重试入队")
        except TransitionError as e:
            return _json_error(409, str(e), "invalid_transition")
        try:
            if (
                main_req and main_req != str(row.get("main_tex") or "")
            ) or engine_stale:
                # 换主文件（body.main 与 options.main 同口径）或显式换引擎 →
                # 解析产物作废（chunks/base/zh 重建，src/ 保留）；派生产物行
                # 与磁盘件并删——残行会让 files/reader 照发上一轮产物
                # （en.pdf 也随 base/ 同死：换 main/引擎后它编译自另一棵树）
                deps.store.delete_chunks(task_id)
                task_root = deps.root / "tasks" / task_id
                recs = [
                    (kind, rec)
                    for kind, rec in deps.store.files(task_id).items()
                    if kind != "src_tar"  # 取源产物不受影响——e-print/上传件仍有效
                ]

                def _wipe() -> None:
                    """FS 侧清理（rmtree×4 + 失效产物 unlink）——重 I/O 离 loop。"""
                    for d in ("base", "zh", "build-en", "build-zh"):
                        shutil.rmtree(task_root / d, ignore_errors=True)
                    resolved_root = task_root.resolve()
                    for _kind, rec in recs:
                        stale = (task_root / str(rec["path"])).resolve()
                        if stale.is_relative_to(resolved_root):
                            with suppress(OSError):
                                stale.unlink(missing_ok=True)

                await asyncio.to_thread(_wipe)
                for kind, _rec in recs:
                    deps.store.delete_file(task_id, kind)
            deps.store.update_fields(task_id, options_json=options_json)
        except Exception:
            # 已抢 queued 但清理/写 options 折了——不留 queued 半成品给
            # dispatcher 捡，转 fault 把责任落回行状态
            with suppress(StoreError):
                deps.store.transition(
                    task_id, "fault", force=True, message="retry 清理失败"
                )
            raise
        deps.runner.enqueue(task_id, deps.secrets_for(request, row))
        return _accepted(deps.store.get(task_id) or row, 202, {"cache": "retry"})

    @app.post("/api/task/{task_id}/chunk/{seq}/retranslate")
    async def chunk_retranslate(request: Request, task_id: str, seq: int) -> Response:
        """终态任务单块重译入队——202 ``{task_id, seq, status:"queued"}``。

        守卫阶梯：任务存在 + tenant 隔离（``_get_task`` 404）→ 状态须
        done/partial（reader 消费面——ACTIVE 与其余终态 409）→ seq 须
        命中 chunks 表（404）→ ``auth_source=header`` 重带 key（401，
        retry 同口径：内存 secrets 随终态已摘）。``enqueue_retranslate``
        的 KeyError/ValueError 归一 404/409——检查到入队之间行被并发
        删/改态的竞态兜底。
        """
        row = deps.get_task(request, task_id)
        if str(row["status"]) not in ("done", "partial"):
            return _json_error(
                409,
                f"任务状态 {row['status']}：仅 done/partial 终态可单块重译",
                "invalid_state",
            )
        if seq < 0 or not deps.store.chunk_exists(task_id, seq):
            return _json_error(404, f"no chunk seq {seq}", "not_found")
        if row["auth_source"] == "header" and not request.headers.get("x-texlate-key"):
            return _json_error(
                401,
                "auth_source=header：重译必须重带 X-Texlate-Key",
                "auth_required",
            )
        try:
            deps.runner.enqueue_retranslate(
                task_id, seq, deps.secrets_for(request, row)
            )
        except KeyError:
            return _json_error(404, "task not found", "not_found")
        except ValueError as e:
            return _json_error(409, str(e), "invalid_state")
        return JSONResponse(
            {"task_id": task_id, "seq": seq, "status": "queued"},
            status_code=202,
        )

    @app.delete("/api/task/{task_id}")
    async def task_delete(request: Request, task_id: str) -> Response:
        """终态任务删除：DB 行（FK 级联子表）+ ``tasks/{id}/`` 工作目录。

        ACTIVE 态 409——进行中任务先 ``POST cancel`` 收敛再删；删前补一条
        ``done{status:"deleted"}`` 事件让在听的 SSE 流正常收尾（事件随
        行级联删，只服务实时订阅者）。内存 ``secrets`` 一并摘。
        """
        row = deps.get_task(request, task_id)
        if row["status"] in ACTIVE_STATUSES:
            return _json_error(
                409,
                f"task {task_id} is {row['status']}: cancel first",
                "invalid_transition",
            )
        # 先发终帧再删行——task_events FK 挂 tasks(id)，删后 publish 即
        # 约束违例；publish→delete 间无 await，对并发 retry/cancel 原子
        deps.bus.publish(
            task_id,
            "done",
            {"status": "deleted", "artifacts": {}, "stats": {}},
        )
        if not deps.store.delete_task_guard(task_id, blocked=ACTIVE_STATUSES):
            # 读时终态、删前被并发 retry 激活（跨进程/极端时序）——条件写兜底
            return _json_error(
                409,
                f"task {task_id} is active: cancel first",
                "invalid_transition",
            )
        deps.runner.secrets.pop(task_id, None)
        # 任务目录可能是 GB 级产物树——rmtree 重 I/O 卸出 loop
        await asyncio.to_thread(
            shutil.rmtree, deps.root / "tasks" / task_id, ignore_errors=True
        )
        return JSONResponse({"task_id": task_id, "status": "deleted"})

    @app.post("/api/tasks/slim")
    async def tasks_slim(request: Request) -> Response:
        """批量瘦身：终态任务 ``tasks/{id}/`` 清未登记字节，产物/记录全留。

        白名单 = files 表登记路径（``file_get`` 可服务面）；done/partial
        追加 ``zh``/``base`` 整树——单块重译（``_ensure_scans`` 重解析
        base/ + resplice 写 zh/）与 share 打包的 glossary 指纹都读活树。
        rmtree 级重 I/O 逐任务卸出 loop；retry 竞窗靠 runner 在飞集 +
        逐任务状态复核收窄（复核→walk 间翻活只丢一拍窗口，下拍再瘦）。

        ``?dry=1`` 同口径只算不删——给 UI 出「约可释放 X」预估。
        """
        tenant = deps.auth(request).tenant
        dry = request.query_params.get("dry") in ("1", "true")
        skip = deps.runner.inflight_task_ids()
        freed = 0
        slimmed = 0
        for tid in deps.store.terminal_task_ids(tenant):
            if tid in skip:
                continue
            row = deps.store.get(tid)
            if row is None or str(row["status"]) not in TERMINAL_STATUSES:
                continue
            keep = {str(rec["path"]) for rec in deps.store.files(tid).values()}
            keep_dirs = (
                ("zh", "base") if str(row["status"]) in ("done", "partial") else ()
            )
            n = await asyncio.to_thread(
                slim_task_dir, deps.root / "tasks" / tid, keep, keep_dirs, dry=dry
            )
            if n:
                slimmed += 1
                freed += n
        return JSONResponse({"slimmed": slimmed, "freed_bytes": freed})
