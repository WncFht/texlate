"""worker.translate.xlator — Translator 构造决策链叶 (worker.translate 域缝叶)。

``_resolve_translator`` 统一构造决策链（``translator_factory`` 注入 →
``TEXLATE_TRANSLATOR=mock`` → 网关臂 → 无 key 硬失败）、``_retry_model_of``
``options.retry_model`` 备选模型解析、``_flag_mock_run`` ``mock_run``
审计键幂等写/清、``_make_translator``/``_doc_translator`` 消费面（默认
工厂 / doc 路 per-call 臂）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from texlate.server.channels import (
    ChannelStore,
    cooldowns,
    credential_for,
    local_model_name,
    wire_model,
)
from texlate.server.settings import (
    SettingsStore,
    server_mode,
    validate_model,
)
from texlate.server.worker._common import _FallbackTranslator, _PerCallTranslator
from texlate.textutil.osutil import translator_mode
from texlate.xlat.client import (
    DEFAULT_MODEL,
    AuthError,
    ChatClient,
    normalize_base_url,
    provider_for_url,
)
from texlate.xlat.pipeline import GatewayTranslator, MockTranslator

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from texlate.server.store import Store
    from texlate.server.worker._common import TaskCtx
    from texlate.xlat.client import ChatError, UsageRecord
    from texlate.xlat.pipeline import Translator

#: ``_FallbackTranslator`` 备选臂上限（retry_model + 端点臂合计）——
#: 每臂一次完整调用，封顶防回退链把单块放大成跨端点扫射。
FALLBACK_ARM_MAX = 4


class _TranslateXlator:
    """译器构造/审计 mixin（``_resolve``/``_make``/``_doc``/``_retry``/``_flag``）。"""

    if TYPE_CHECKING:
        # 组合根 ``worker._Core.__init__`` 注入的共享态契约
        store: Store
        data_dir: Path
        _translator_factory: Callable[[TaskCtx], Translator] | None

    def _retry_model_of(self, ctx: TaskCtx, model: str) -> str:
        """``options.retry_model`` → 备选模型名；缺省/同 primary/非法 → ``""``。

        非法值记 ``retry_model`` warning 后按无备选处理——不挡主链翻译。
        """
        retry_model = str(ctx.options().get("retry_model") or "").strip()
        if retry_model and retry_model != model:
            try:
                return validate_model(retry_model)
            except ValueError:
                self._warning(
                    ctx,
                    "retry_model",
                    f"options.retry_model {retry_model!r} 非法，忽略",
                )
        return ""

    def _flag_mock_run(self, ctx: TaskCtx, tr: Translator) -> None:
        """``mock_run`` 审计键幂等写/清——resolve 出的真实形态是标记唯一真源。

        ``isinstance(MockTranslator)`` 命中 → 置 ``1`` + 按任务去重发
        ``mock_translator`` warning（建行臂的 env-mock 预标记幂等会合）；
        非 mock resolve 而行上有陈旧标记（env flip / needs_auth 补 key
        重跑成真）→ 摘除。``ctx.set_option`` 先同步 ``ctx.row`` 内存快照
        （同 run 下游 ``_make_cache`` 即刻可见），库写经 ``_on_loop``
        回弹——本方法在 loop（``_stage_translate``）与工作线程
        （``_logfix_run_state``/``_llm_hook_pack`` 的 to_thread 段）两侧都会
        被调到，写面必须走单写者通道。
        """
        is_mock = isinstance(tr, MockTranslator)
        if is_mock:
            if ctx.task_id not in self._mock_warned:
                self._mock_warned.add(ctx.task_id)
                self._warning(
                    ctx,
                    "mock_translator",
                    "本任务译文由 MockTranslator 产出——占位译文而非真实翻译",
                )
            if not ctx.options().get("mock_run"):
                options_json = ctx.set_option("mock_run", 1)
                self._on_loop(
                    self.store.update_fields,
                    ctx.task_id,
                    options_json=options_json,
                )
        elif ctx.options().get("mock_run"):
            options_json = ctx.update_options(lambda opts: opts.pop("mock_run", None))
            self._on_loop(
                self.store.update_fields,
                ctx.task_id,
                options_json=options_json,
            )

    def _global_cap(self) -> int:
        """服务级并发上限 = ``settings.concurrency``——全进程在飞翻译调用总闸。"""
        return int(SettingsStore(self.data_dir).load().get("concurrency") or 0)

    def _scope_limits(
        self,
        ch: dict[str, Any] | None,
        entry: dict[str, Any] | None,
        wire: str,
        gcap: int,
    ) -> tuple[tuple[str, int | None], ...]:
        """``(global, channel, model)`` 三层并发作用域元组——缺省层略去。

        取序固定 global → channel → model：``_ScopePool.acquire`` 按序
        取锁，全进程同序即无多信号量死锁面。``ch=None`` 时只有 global
        层（非渠道路径/无档投影期）。
        """
        scopes: list[tuple[str, int | None]] = []
        if gcap > 0:
            scopes.append(("global", gcap))
        if ch is not None:
            cap = ch.get("max_concurrency")
            if cap:
                scopes.append((f"ch:{ch['id']}", int(cap)))
            if entry is not None and entry.get("max_concurrency"):
                scopes.append((f"ch:{ch['id']}:{wire}", int(entry["max_concurrency"])))
        return tuple(scopes)

    def _channel_of(
        self, ctx: TaskCtx
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """当前 secrets → ``(渠道档, 模型条目)``；无档/无命中 → ``(None, None)``。

        定位序：``secrets.channel_id``（deps 路由决议落的 id）→
        ``secrets.base_url`` 归一匹配（env 逃生舱/手工配置路径照样吃
        渠道层上限）。条目按 ``secrets.model`` 先 wire 名再本地名反查。
        """
        store = ChannelStore(self.data_dir)
        if not (store.path.is_file() or store.legacy_path.is_file()):
            return None, None
        channels = store.load()["channels"]
        cid = str(ctx.secrets.channel_id or "")
        ch = next((c for c in channels if c["id"] == cid), None) if cid else None
        if ch is None:
            url = normalize_base_url(ctx.secrets.base_url)
            ch = next(
                (c for c in channels if normalize_base_url(str(c["base_url"])) == url),
                None,
            )
        if ch is None:
            return None, None
        model = str(ctx.secrets.model or "")
        entry = next((e for e in ch["models"] if wire_model(e) == model), None) or next(
            (e for e in ch["models"] if local_model_name(e) == model), None
        )
        return ch, entry

    def _channel_arms(  # noqa: C901 -- 闸 + 同渠道/异渠道两遍建档阶梯平铺
        self, ctx: TaskCtx, client: ChatClient, exclude: set[str], gcap: int
    ) -> list[GatewayTranslator]:
        """channels.json → 渠道回退臂（活动渠道余模同 client + 异渠道各带自家 client）。

        闸（任一命中 → 空链）：``secrets.source == "header"``（用户单发
        key 绝不被扇到第二渠道）、非 local 形态（server 部署拓扑不自助
        回退）、渠道文件缺席（投影条目只映 settings/connections 本体，
        无异质臂可挂）。

        臂序 = ``priority`` 降序：第一遍活动渠道的余下 enabled 模型
        （同 client 同凭据零成本换模），第二遍其余 enabled 渠道的首个
        enabled 模型（各带 ``credential_for`` 阶梯决议的凭据 client——
        ``ctx.secrets.api_key`` 绝不发向异 base_url，exfil 墙）。冷却
        中的（渠道,模型）组合建档期即滤——半死渠道不再每块先烧一跳。
        无凭据的远程渠道跳过（必 AuthError 白烧一跳），回环端点无 key
        合法（``provider_for_url → "gateway"``）。
        """
        if ctx.secrets.source == "header" or server_mode() != "local":
            return []
        root = self.data_dir
        store = ChannelStore(root)
        if not (store.path.is_file() or store.legacy_path.is_file()):
            return []
        channels = sorted(
            (c for c in store.load()["channels"] if c.get("enabled")),
            key=lambda c: -int(c["priority"]),
        )
        connections = SettingsStore(root).connections()
        active_id = str(ctx.secrets.channel_id or "")
        active_url = normalize_base_url(ctx.secrets.base_url)

        def _is_active(ch: dict[str, Any]) -> bool:
            if active_id:
                return str(ch["id"]) == active_id
            return normalize_base_url(str(ch["base_url"])) == active_url

        arms: list[GatewayTranslator] = []
        for ch in channels:  # 第一遍：活动渠道余模（同 client 换模臂）
            if not _is_active(ch) or cooldowns.is_cooled(ch["id"], ""):
                continue
            for entry in ch["models"]:
                if not entry.get("enabled"):
                    continue
                wire = wire_model(entry)
                if wire in exclude or cooldowns.is_cooled(ch["id"], wire):
                    continue
                exclude.add(wire)
                arms.append(
                    GatewayTranslator(
                        client,
                        wire,
                        channel_id=str(ch["id"]),
                        limits=self._scope_limits(ch, entry, wire, gcap),
                    )
                )
        for ch in channels:  # 第二遍：异渠道首模（各带自家凭据 client）
            if _is_active(ch) or cooldowns.is_cooled(ch["id"], ""):
                continue
            entry = next((e for e in ch["models"] if e.get("enabled")), None)
            if entry is None:
                continue
            wire = wire_model(entry)
            if cooldowns.is_cooled(ch["id"], wire):
                continue
            base_url = str(ch["base_url"])
            key, _src = credential_for(ch, connections)
            if not key and provider_for_url(base_url) != "gateway":
                continue
            arm_client = ChatClient(
                base_url,
                key,
                dialect=str(ch["protocol"] or "auto"),
            )
            arms.append(
                GatewayTranslator(
                    arm_client,
                    wire,
                    channel_id=str(ch["id"]),
                    limits=self._scope_limits(ch, entry, wire, gcap),
                )
            )
        return arms

    def _arm_served(self, ctx: TaskCtx, tr: GatewayTranslator) -> None:
        """备选臂成功服务 → ``ctx.memo["served_by"]`` 计数（段收尾落 options 审计键）。"""
        client = getattr(tr, "client", None)
        label = f"{tr.model}@{getattr(client, 'base_url', '?')}"
        served = ctx.memo.setdefault("served_by", {})
        served[label] = served.get(label, 0) + 1

    def _arm_switch_warn(
        self,
        ctx: TaskCtx,
        frm: GatewayTranslator,
        to: GatewayTranslator,
        e: ChatError,
    ) -> None:
        """切臂事件 → ``channel_fallback`` warning（每任务每目标渠道去重）。

        链上每块都可能切臂——不 dedupe 会按 chunk 数刷屏；dedupe 键是
        目标臂 ``base_url``（``ctx.memo`` 按 run 存活，自然随任务回收）。
        """
        to_client = getattr(to, "client", None)
        to_url = str(getattr(to_client, "base_url", "") or "")
        key = f"channel_fallback:{to_url}"
        seen = ctx.memo.setdefault("channel_fallback_seen", set())
        if key in seen:
            return
        seen.add(key)
        frm_url = str(getattr(getattr(frm, "client", None), "base_url", "") or "")
        self._warning(
            ctx,
            "channel_fallback",
            f"翻译回退：{frm.model}@{frm_url} 失败"
            f"（{type(e).__name__} status={e.status}）→ {to.model}@{to_url}",
        )

    def _resolve_translator(
        self,
        ctx: TaskCtx,
        *,
        sink: Callable[[UsageRecord], None] | None = None,
        retry: bool = True,
    ) -> Translator:
        """统一 ``Translator`` 构造决策链（``_make/_doc/_llm_hook_pack`` 同源）。

        序即优先级：``translator_factory`` 注入 → ``TEXLATE_TRANSLATOR=mock``
        → 网关臂（``force=gateway`` 或有 ``api_key``）→ 无 key 硬失败。

        网关臂两形态：``sink`` 给定 = ephemeral-loop 消费面（doc 路/llm_hook
        的 ``asyncio.run`` 临时 loop——共享 client 跨 loop 复用会炸、aclose
        回不去已关 loop）→ ``_PerCallTranslator`` 即开即关；``sink=None`` =
        主链共享 client ``GatewayTranslator``，``retry_model`` 与
        channels.json 渠道臂经 ``_FallbackTranslator`` 链式接备选
        （``_channel_arms`` 闸内：header 凭据/非 local/无渠道档 → 空链；
        臂恒包装——``on_error`` 冷却落戳在零备选时也生效）。
        ``retry=False`` 给不接
        ``retry_model`` 的旁路臂（llm_hook——备选模型烧 token 的语义不擅自
        加）用。

        无 key 且未显式 mock/gateway 时静默假译文是生产事故面（M1）——
        建行闸拦常规入口后本臂兜底 replay/直拉残留：留 ``mock_translator``
        warning 痕后抛 ``AuthError``（``core.run`` 归 ``provider_auth``
        fault，``retryable=False``）。Mock 自此只对显式 opt-in 可达。

        每条成功返回路径先过 ``_flag_mock_run``——mock 形态落
        ``options_json.mock_run`` 审计键（reuse/dedup 排除 + retry 放行
        的消费面），非 mock resolve 顺带摘陈旧标记。
        """
        tr: Translator
        if self._translator_factory is not None:
            tr = self._translator_factory(ctx)
        else:
            force = translator_mode()
            if force == "mock":
                tr = MockTranslator()
            elif force == "gateway" or ctx.secrets.api_key:
                model = ctx.secrets.model or DEFAULT_MODEL
                retry_model = self._retry_model_of(ctx, model) if retry else ""
                ch, ch_entry = self._channel_of(ctx)
                cid = str(ch["id"]) if ch is not None else ""
                gcap = self._global_cap()
                limits = self._scope_limits(ch, ch_entry, model, gcap)
                if sink is not None:
                    tr = _PerCallTranslator(
                        ctx.secrets.base_url,
                        ctx.secrets.api_key,
                        model,
                        sink,
                        retry_model=retry_model,
                        dialect=ctx.secrets.dialect,
                        channel_id=cid,
                        limits=limits,
                    )
                else:
                    client = ChatClient(
                        ctx.secrets.base_url,
                        ctx.secrets.api_key,
                        dialect=ctx.secrets.dialect,
                    )
                    primary = GatewayTranslator(
                        client, model, channel_id=cid, limits=limits
                    )
                    arms: list[GatewayTranslator] = []
                    if retry:
                        # retry=False 旁路臂（splice/fixloop sink 面、llm_hook
                        # 自承语义）不接任何回退臂
                        if retry_model:
                            rentry = (
                                next(
                                    (
                                        e
                                        for e in ch["models"]
                                        if wire_model(e) == retry_model
                                    ),
                                    None,
                                )
                                if ch is not None
                                else None
                            )
                            arms.append(
                                GatewayTranslator(
                                    client,
                                    retry_model,
                                    channel_id=cid,
                                    limits=self._scope_limits(
                                        ch, rentry, retry_model, gcap
                                    ),
                                )
                            )
                        arms.extend(
                            self._channel_arms(
                                ctx, client, exclude={model, retry_model}, gcap=gcap
                            )
                        )
                    # 恒包 _FallbackTranslator（空臂也包）——on_error 是
                    # 冷却落戳唯一通道：裸 primary 时渠道主臂 terminal
                    # 失败不落戳，下块/下任务路由照选半死渠道
                    tr = _FallbackTranslator(
                        primary,
                        arms[:FALLBACK_ARM_MAX],
                        on_switch=lambda frm, to, e: self._arm_switch_warn(
                            ctx, frm, to, e
                        ),
                        on_error=lambda arm, e: cooldowns.mark_error(
                            arm.channel_id, arm.model, e
                        ),
                        on_served=lambda arm: self._arm_served(ctx, arm),
                    )
            else:
                if ctx.task_id not in self._mock_warned:
                    self._mock_warned.add(ctx.task_id)
                    self._warning(
                        ctx,
                        "mock_translator",
                        "未配置 API key——翻译中止（请配置 key 后重试）",
                    )
                msg = "未配置 API key——请在设置页或 X-Texlate-Key 头提供"
                raise AuthError(msg)
        self._flag_mock_run(ctx, tr)
        return tr

    def _make_translator(self, ctx: TaskCtx) -> Translator:
        """默认工厂：key 或 ``TEXLATE_TRANSLATOR=gateway`` → 网关，否则 Mock。

        ``options.retry_model`` 仅在默认网关路径生效——备选模型与 primary
        同 client（同 endpoint+key），``translator_factory``/Mock 注入路径
        由调用方自担语义不包。决策链本体在 ``_resolve_translator``。
        """
        return self._resolve_translator(ctx)

    def _doc_translator(
        self, ctx: TaskCtx, sink: Callable[[UsageRecord], None]
    ) -> Translator:
        """``_run_doc`` 专用 translator——``_resolve_translator`` 的 per-call 臂。

        ``export_document`` 内嵌管线在 to_thread 的 ephemeral ``asyncio.run``
        loop 里消费 client——共享 client 的 aclose 回不去该 loop（已关），
        跨 loop 关连接炸 RuntimeError 被吞成 FD 泄漏。``sink`` 给定即开
        ``_PerCallTranslator``；``retry_model`` 经其内建备选臂保持 option
        面等价。factory/Mock 注入路径原样（测试桩语义调用方担）。
        """
        return self._resolve_translator(ctx, sink=sink)
