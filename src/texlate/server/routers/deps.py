"""``AppDeps``：``create_app`` 装配产物 → 路由叶的依赖注入面。

原 ``create_app`` 内的请求级共享闭包（auth 三级决议 / tenant 隔离取行 /
配额闸 / dedup-建行-入队阶梯）收为方法——叶子 ``register(app, deps)``
拿到的同一个实例即当时的装配快照（store/runner/settings_store/salt 皆
同一对象，行为与原闭包捕获逐字等价）。
"""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request

from texlate.pipecore import front_matter_of
from texlate.server.http import _api_error
from texlate.server.settings import (
    TARGET_LANGS,
    AuthContext,
    resolve_auth,
    server_mode,
    validate_model,
)
from texlate.server.store import new_task_id, valid_task_id
from texlate.server.worker import Secrets, artifact_urls, cache_key_for
from texlate.textutil import env_str
from texlate.textutil.osutil import ENV_TRANSLATOR

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
        """BYOK 逐项决议（§4.1）：key 走 header > settings > env，其余 header > env > settings；非法 header 值 → 400。

        头面直传 ``request.headers``——查名按 ``BYOK_FIELDS`` 单源，本层
        不再枚举 ``X-Texlate-*`` 字面量。每请求缓存到 ``request.state``：
        一次请求内 header 与 settings 快照都不变，而 ``load()`` 每次都
        读盘解析——translate 单链决议 3+ 次（model 回落/cache_key/
        create_and_enqueue），缓存只读一次。失败不缓存（重试同路径重炸 400）。
        """
        cached = getattr(request.state, "auth_ctx", None)
        if isinstance(cached, AuthContext):
            return cached
        try:
            auth = resolve_auth(
                self.settings_store.load(),
                headers=request.headers,
                mode=server_mode(),
                salt=self.salt,
            )
        except ValueError as e:
            raise _api_error(400, str(e), "invalid_request") from e
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
        return Secrets.from_auth(auth, model=str(row["model"]))

    def resolve_model_lang(
        self, request: Request, model_raw: str, lang_raw: str
    ) -> tuple[str, str]:
        """``model``/``target_lang`` 入参决议 + 校验 → ``(model, target_lang)``。

        空值回落 ``auth(request)`` 快照（``.model`` /
        ``settings["target_lang"]``）——一次 auth 决议同时供两侧回落；
        违例 → ``_ApiError(400, invalid_request)``。tasks/upload 两域
        共用本闸（原 ``tasks._resolve_model_lang``/``_upload_fields``
        双份实现收编于此）。
        """
        auth = self.auth(request)
        try:
            model = validate_model(model_raw or auth.model)
        except ValueError as e:
            raise _api_error(400, str(e), "invalid_request") from e
        target_lang = lang_raw or str(auth.settings["target_lang"])
        if target_lang not in TARGET_LANGS:
            raise _api_error(
                400, f"target_lang ∈ {sorted(TARGET_LANGS)}", "invalid_request"
            )
        return model, target_lang

    def task_dir(self, task_id: str) -> Path:
        """任务产物目录 ``root/tasks/<task_id>``——单源防各叶手拼漂移。"""
        return self.root / "tasks" / task_id

    async def drop_task_dir(self, task_id: str) -> None:
        """任务目录 rmtree（``ignore_errors``）——GB 级产物树重 I/O 卸出 loop。"""
        await asyncio.to_thread(
            shutil.rmtree, self.task_dir(task_id), ignore_errors=True
        )

    def snapshot(self, task_id: str) -> dict[str, Any]:
        """§2.2 快照 + 产物 URL 映射——``store.snapshot`` 与 ``artifact_urls`` 的固定组合。"""
        return self.store.snapshot(
            task_id, artifacts=artifact_urls(self.store, task_id)
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
            raise _api_error(
                429, f"tenant 任务配额已用尽（{q_tasks}）", "quota_exceeded"
            )
        if q_bytes and usage["bytes"] + incoming_bytes > q_bytes:
            raise _api_error(
                429, f"tenant 字节配额超限（{q_bytes}B）", "quota_exceeded"
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
            raise _api_error(
                429, f"同 IP 任务配额已用尽（{q_tasks}）", "quota_exceeded"
            )
        if q_bytes and bucket[1] + incoming_bytes > q_bytes:
            raise _api_error(
                429, f"同 IP 字节配额超限（{q_bytes}B）", "quota_exceeded"
            )
        # 过闸才累计——被拒请求不占桶；建行失败的多计是保守方向
        bucket[0] += 1
        bucket[1] += incoming_bytes

    def create_and_enqueue(  # noqa: C901, PLR0912, PLR0913 -- dedup/reuse/建行阶梯 + 参数面平铺
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
        # M1 缺 key 硬闸的两块判据（建行前算定，臂内共用）：
        # ``mock_env`` —— ``TEXLATE_TRANSLATOR=mock`` 显式 opt-in 面
        # （bench/e2e 夹具），该形态下建行即写 ``mock_run:1`` 审计键
        # （``_SNAPSHOT_OPTS_DROP`` 同款不透出口径）；
        # ``explicit_mock`` —— mock 可达即豁免缺 key 闸（env mock 或注入
        # ``translator_factory`` 测试桩），否则无 key 请求建行即落
        # ``needs_auth`` 终态不进队列——静默 Mock 译文按 done 交付 +
        # 毒化段缓存/reuse 链是实测事故面（misc-pack §M1）。
        mock_env = env_str(ENV_TRANSLATOR) == "mock"
        explicit_mock = (
            mock_env or self.worker._translator_factory is not None  # noqa: SLF001 -- 装配注入面只读探测（同 _llm_hook_pack 判据）
        )
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
                raise _api_error(
                    409,
                    f"active task {active['id']} exists",
                    "duplicate_active",
                    task_id=active["id"],
                )
            done = store.find_reusable(cache_key)
            if done is not None:
                if server_mode() == "server" and str(done["tenant"]) != auth.tenant:
                    # 跨租户命中——直接回 hit 行的 task_id 对本租户是死链
                    # （get_task tenant 检恒 404）。改走建行+worker
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
                            front_matter=front_matter_of(options),
                        )
                else:
                    return done, 200, {"reused": True}
            # needs_auth 终态行不占 cache_key 唯一槽——同键再撞不产
            # IntegrityError，须显式查收编：缺 key 用户重交同论文回
            # 既有 needs_auth 行（200 + task_id），补 key 走该行 retry
            # 通道，而非再堆一条新死行（misc-pack §M1 风险 1）。
            needs = store.find_needs_auth_by_cache_key(cache_key)
            if needs is not None:
                return needs, 200, {"reused": True}
        self.check_quota(
            auth,
            incoming_bytes,
            request.client.host if request.client is not None else "",
        )
        if mock_env and kind != "share":
            # env mock 形态建行即打 mock_run 审计键——queued 未跑的行
            # 也提前进排除集（worker 侧 ``_flag_mock_run`` 在 resolve 时
            # 对 factory/存量行补同一标记，两处幂等会合）。share 豁免：
            # 共享包译文是真实产物非 mock 占位，误标会把真译文踢出
            # reuse 命中集。
            options = {**options, "mock_run": 1}
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
        kw: dict[str, Any] = {
            "task_id": tid,
            "kind": kind,
            "target_lang": target_lang,
            "model": model,
            "arxiv_id": arxiv_id,
            "source_name": source_name,
            "title": title,
            "config": config,
            "options": options,
            "auth_source": auth.source,
            "tenant": auth.tenant,
            "cache_key": cache_key,
        }
        try:
            row = store.create_task(**kw)
        except sqlite3.IntegrityError:
            if prefer != "fresh":
                # 检查-建行之间并发插入撞 ACTIVE 唯一索引——归 duplicate_active
                # （原来裸 re-raise 出 FastAPI 成无码 500）
                active = store.find_active_by_cache_key(cache_key)
                if active is not None:
                    raise _api_error(
                        409,
                        f"active task {active['id']} exists",
                        "duplicate_active",
                        task_id=active["id"],
                    ) from None
                # 持槽行已迁出 ACTIVE（查-写窗内完成/取消）：needs_auth
                # 撞键行收编 200——缺 key 重交指向可补 key 的既有行，
                # 不发无 task_id 的 409 死信（misc-pack §M1 风险 1）
                needs = store.find_needs_auth_by_cache_key(cache_key)
                if needs is not None:
                    return needs, 200, {"reused": True}
                # 剩余撞键面：持槽行是 mock_run 排除集内行（唯一索引不含
                # mock 谓词，active mock 行仍占槽）或持槽行在查-写窗内
                # 消失——无可指认对象时放弃 dedup 键建行（fresh 同语义，
                # 优于死信 409）
                kw["cache_key"] = None
                row = store.create_task(**kw)
            else:
                # fresh：cache_key 撞活跃行——放弃 dedup 键强行新建（§2.1）
                kw["cache_key"] = None
                row = store.create_task(**kw)
        if auth.source == "none" and not explicit_mock and kind != "share":
            # 缺 key 硬闸（M1）：建行即落 needs_auth 终态，不进队列——
            # Mock 兜底译文按 done 静默交付是事故面；needs_auth 行复用
            # 既有 UX（ResultBody 内联 key + retry 端点带 X-Texlate-Key）。
            # ``kind=="share`` 豁免：share 链全程不 resolve translator
            # （``_run_share`` 无 translating 段，compile 各 LLM 臂被
            # ``_share_sourced`` 闸死）——零 token 消费不需要 key。
            row = store.transition(
                tid, "needs_auth", force=True, message="未配置 API Key"
            )
            return row, 202, {"cache": "miss"}
        self.runner.enqueue(
            tid,
            Secrets.from_auth(auth, model=model),
        )
        return row, 202, {"cache": "miss"}
