"""worker.translate_xlator — Translator 构造决策链叶 (worker.translate 域缝叶)。

``_resolve_translator`` 统一构造决策链（``translator_factory`` 注入 →
``TEXLATE_TRANSLATOR=mock`` → 网关臂 → 无 key 硬失败）、``_retry_model_of``
``options.retry_model`` 备选模型解析、``_flag_mock_run`` ``mock_run``
审计键幂等写/清、``_make_translator``/``_doc_translator`` 消费面（默认
工厂 / doc 路 per-call 臂）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.server.settings import validate_model
from texlate.textutil.osutil import translator_mode
from texlate.xlat.client import DEFAULT_MODEL, AuthError, ChatClient
from texlate.xlat.pipeline import GatewayTranslator, MockTranslator

from ._common import _FallbackTranslator, _PerCallTranslator

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.xlat.client import UsageRecord
    from texlate.xlat.pipeline import Translator

    from ._common import TaskCtx


class _TranslateXlator:
    """译器构造/审计 mixin（``_resolve``/``_make``/``_doc``/``_retry``/``_flag``）。"""

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
        （``_l2_run_state``/``_llm_hook_pack`` 的 to_thread 段）两侧都会
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
        主链共享 client ``GatewayTranslator``，``retry_model`` 经
        ``_FallbackTranslator`` 接备选。``retry=False`` 给不接
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
                if sink is not None:
                    tr = _PerCallTranslator(
                        ctx.secrets.base_url,
                        ctx.secrets.api_key,
                        model,
                        sink,
                        retry_model=retry_model,
                        dialect=ctx.secrets.dialect,
                    )
                else:
                    client = ChatClient(
                        ctx.secrets.base_url,
                        ctx.secrets.api_key,
                        dialect=ctx.secrets.dialect,
                    )
                    primary = GatewayTranslator(client, model)
                    tr = (
                        _FallbackTranslator(
                            primary, GatewayTranslator(client, retry_model)
                        )
                        if retry_model
                        else primary
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
