"""``AppDeps``：``create_app`` 装配产物 → 路由叶的依赖注入面。

原 ``create_app`` 内的请求级共享闭包（auth 三级决议 / tenant 隔离取行 /
配额闸 / dedup-建行-入队阶梯）收为方法——叶子 ``register(app, deps)``
拿到的同一个实例即当时的装配快照（store/runner/settings_store/salt 皆
同一对象，行为与原闭包捕获逐字等价）。
"""

from __future__ import annotations

import sqlite3
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request

from texlate.server.http import _ApiError
from texlate.server.settings import AuthContext, resolve_auth, server_mode
from texlate.server.store import new_task_id, valid_task_id
from texlate.server.worker import Secrets, cache_key_for

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.server.events import EventBus
    from texlate.server.settings import SettingsStore
    from texlate.server.store import Store
    from texlate.server.worker import PipelineWorker, TaskRunner

#: per-IP 配额兜底桶表界（``check_quota``）——distinct peer 数有界防洪泛，
#: LRU 头出。4096 个 IPv6 字面量键 ≈ 数百 KB，量级无害。
_IP_QUOTA_MAX_PEERS = 4096


@dataclass(slots=True)
class AppDeps:
    """路由叶共享的装配依赖。

    ``ip_quota``：per-IP 配额兜底桶（进程内累计，peer → ``[tasks, bytes]``）
    ——tenant=sha256(key) 换 key 即新桶，本桶按网络对端记账封轮转。
    """

    root: Path
    store: Store
    bus: EventBus
    runner: TaskRunner
    worker: PipelineWorker
    settings_store: SettingsStore
    salt: str
    spool_dir: Path
    babeldoc: str | None
    ip_quota: OrderedDict[str, list[int]] = field(default_factory=OrderedDict)

    def auth(self, request: Request) -> AuthContext:
        """Header > settings > env 三级决议（§4.1）；非法 header 值 → 400。

        每请求缓存到 ``request.state``：一次请求内 header 与 settings
        快照都不变，而 ``load()`` 每次都读盘解析——translate 单链决议
        3+ 次（model 回落/cache_key/_create_and_enqueue），缓存只读
        一次。失败不缓存（重试同路径重炸 400）。
        """
        cached = getattr(request.state, "auth_ctx", None)
        if isinstance(cached, AuthContext):
            return cached
        try:
            auth = resolve_auth(
                self.settings_store.load(),
                header_key=request.headers.get("x-texlate-key", ""),
                header_base_url=request.headers.get("x-texlate-base-url", ""),
                header_model=request.headers.get("x-texlate-model", ""),
                mode=server_mode(),
                salt=self.salt,
            )
        except ValueError as e:
            raise _ApiError(400, {"detail": str(e), "code": "invalid_request"}) from e
        request.state.auth_ctx = auth
        return auth

    def get_task(self, request: Request, task_id: str) -> dict[str, Any]:
        """Id 形态 + 存在 + tenant 隔离三检；不过 → 404。"""
        row = self.store.get(task_id) if valid_task_id(task_id) else None
        if row is None or row["tenant"] != self.auth(request).tenant:
            raise HTTPException(404, "task not found")
        return row

    def secrets_for(self, request: Request, row: dict[str, Any]) -> Secrets:
        """重决议凭证 → 内存 ``Secrets``（retry/enqueue 用）。"""
        auth = self.auth(request)
        return Secrets(
            api_key=auth.api_key,
            base_url=auth.base_url,
            model=str(row["model"]),
            source=auth.source,
        )

    def check_quota(
        self, auth: AuthContext, incoming_bytes: int, peer: str = ""
    ) -> None:
        """Tenant 配额闸（settings.quota_max_*，0=不限）——超限 429。

        任务数按 ``tasks`` 行全量计（含终态行）；字节按已登记产物
        ``files.bytes`` 合计 + 本次入队载荷。reuse/idempotent 命中不建行，
        在调用方此处之前就返回，不占配额。

        ``peer`` 非空时再叠加进程内 per-IP 兜底桶（同字节口径累计）：
        tenant=sha256(key) 的锅——换 key 即新桶，轮转 key 刷 upload 把
        tenant 配额打成筛子。IP 桶按对端地址记进程内累计，key 轮转不改
        对端事实。局限（记注释不瞒）：进程重启清零、NAT 后多用户共 IP
        会互占额度、local 形态全量请求共享回环桶（同机用户配额同桶，
        语义上可接受——local 本就是单机面）。
        """
        st = auth.settings  # 与 auth() 同一份请求快照——不再读一次盘
        q_tasks = int(st.get("quota_max_tasks") or 0)
        q_bytes = int(st.get("quota_max_bytes") or 0)
        if not (q_tasks or q_bytes):
            return
        usage = self.store.tenant_usage(auth.tenant)
        if q_tasks and usage["tasks"] >= q_tasks:
            raise _ApiError(
                429,
                {
                    "detail": f"tenant 任务配额已用尽（{q_tasks}）",
                    "code": "quota_exceeded",
                },
            )
        if q_bytes and usage["bytes"] + incoming_bytes > q_bytes:
            raise _ApiError(
                429,
                {
                    "detail": f"tenant 字节配额超限（{q_bytes}B）",
                    "code": "quota_exceeded",
                },
            )
        if not peer:
            return
        bucket = self.ip_quota.get(peer)
        if bucket is None:
            if len(self.ip_quota) >= _IP_QUOTA_MAX_PEERS:
                self.ip_quota.popitem(last=False)  # LRU 头出——有界表防 IP 洪泛
            bucket = [0, 0]
            self.ip_quota[peer] = bucket
        else:
            self.ip_quota.move_to_end(peer)
        if q_tasks and bucket[0] >= q_tasks:
            raise _ApiError(
                429,
                {
                    "detail": f"同 IP 任务配额已用尽（{q_tasks}）",
                    "code": "quota_exceeded",
                },
            )
        if q_bytes and bucket[1] + incoming_bytes > q_bytes:
            raise _ApiError(
                429,
                {
                    "detail": f"同 IP 字节配额超限（{q_bytes}B）",
                    "code": "quota_exceeded",
                },
            )
        # 过闸才累计——被拒请求不占桶；建行失败的多计是保守方向
        bucket[0] += 1
        bucket[1] += incoming_bytes

    def create_and_enqueue(  # noqa: C901, PLR0913 -- dedup/reuse/建行阶梯 + 参数面平铺
        self,
        request: Request,
        *,
        kind: str,
        arxiv_id: str | None,
        source_name: str,
        title: str,
        model: str,
        target_lang: str,
        options: dict[str, Any],
        prefer: str,
        cache_key: str | None,
        task_id: str | None = None,
        incoming_bytes: int = 0,
    ) -> tuple[dict[str, Any], int, dict[str, Any]]:
        """dedup/reuse/idempotency 判别 + 建行 + 入队。

        返回 ``(row, http_status, extra_body)``——reuse/idempotent 命中时
        status 200/202 且不新建。
        """
        auth = self.auth(request)
        store = self.store
        idem = request.headers.get("idempotency-key") or options.get("idempotency_key")
        if idem:
            hit = store.find_by_idempotency(auth.tenant, str(idem))
            if hit is not None:
                return hit, 202, {"cache": "idempotent"}
            options = {**options, "idempotency_key": str(idem)}
        if cache_key and prefer == "reuse":
            # oracle 权衡：shared 模式下 dedup 命中可被他租户探测
            # （「这篇论文是否译过」存在性侧信道）——hjfy 对等共享缓存是
            # 既定产品特性，须消除时 TEXLATE_CACHE_SCOPE=per_key 按
            # 凭证指纹分桶（见 settings.cache_scope）。
            active = store.find_active_by_cache_key(cache_key)
            if active is not None:
                raise _ApiError(
                    409,
                    {
                        "detail": f"active task {active['id']} exists",
                        "task_id": active["id"],
                        "code": "duplicate_active",
                    },
                )
            done = store.find_reusable(cache_key)
            if done is not None:
                if server_mode() == "server" and str(done["tenant"]) != auth.tenant:
                    # 跨租户命中——直接回 hit 行的 task_id 对本租户是死链
                    # （_get_task tenant 检恒 404）。改走建行+worker
                    # post-resolve dedup：_materialize_reuse 把产物真拷进
                    # 本任务目录，租户拿到自己的可读任务句柄。
                    # 存 alias（无版本）键使 stored≠resolved——钉版请求
                    # 也能命中物化臂；share/upload 等不走 post_resolve 的
                    # kind 保留原键（真跑语义不变，dedup 槽位照占）。
                    if kind in ("arxiv", "arxiv_html") and arxiv_id:
                        cache_key = cache_key_for(
                            arxiv_id=arxiv_id,
                            version=None,
                            model=model,
                            target_lang=target_lang,
                            api_key=auth.api_key,
                            source=str(options.get("source") or "eprint"),
                        )
                else:
                    return done, 200, {"reused": True}
        self.check_quota(
            auth,
            incoming_bytes,
            request.client.host if request.client is not None else "",
        )
        tid = task_id or new_task_id()
        config = {
            "base_url": auth.base_url,
            "model": model,
            "glossary": str(
                options.get("glossary") or auth.settings.get("glossary") or ""
            ),
            # settings 侧受信术语表根（worker 的 glossary 相对路径解析根之一；
            # 不透传请求面，防调用方自选根绕 confine）
            "glossary_dir": str(auth.settings.get("glossary_dir") or ""),
            "engine": str(options.get("engine") or "auto"),
            "concurrency": int(options.get("concurrency") or 3),
        }
        try:
            row = store.create_task(
                task_id=tid,
                kind=kind,
                target_lang=target_lang,
                model=model,
                arxiv_id=arxiv_id,
                source_name=source_name,
                title=title,
                config=config,
                options=options,
                auth_source=auth.source,
                tenant=auth.tenant,
                cache_key=cache_key,
            )
        except sqlite3.IntegrityError:
            if prefer != "fresh":
                # 检查-建行之间并发插入撞 ACTIVE 唯一索引——归 duplicate_active
                # （原来裸 re-raise 出 FastAPI 成无码 500）
                active = store.find_active_by_cache_key(cache_key)
                body: dict[str, Any] = {
                    "detail": "active task exists",
                    "code": "duplicate_active",
                }
                if active is not None:
                    body["detail"] = f"active task {active['id']} exists"
                    body["task_id"] = active["id"]
                raise _ApiError(409, body) from None
            # fresh：cache_key 撞活跃行——放弃 dedup 键强行新建（§2.1）
            row = store.create_task(
                task_id=tid,
                kind=kind,
                target_lang=target_lang,
                model=model,
                arxiv_id=arxiv_id,
                source_name=source_name,
                title=title,
                config=config,
                options=options,
                auth_source=auth.source,
                tenant=auth.tenant,
                cache_key=None,
            )
        self.runner.enqueue(
            tid,
            Secrets(
                api_key=auth.api_key,
                base_url=auth.base_url,
                model=model,
                source=auth.source,
            ),
        )
        return row, 202, {"cache": "miss"}
