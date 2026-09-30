"""pipeline 物化域（自 ``pipeline`` 出叶）：system prompt memo + 文档级术语/锚定/点名册 + 段级缓存。

``_XlatMaterialize`` 是 ``XlatPipeline`` 的物化臂 mixin——文档级过滤
一次、跑批期间 system prompt 逐字节恒定；段级缓存读写含毒译拒写与
命中旧毒清除。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from texlate.xlat import placeholders, prompts
from texlate.xlat.intercept import _interceptable
from texlate.xlat.pipeline.types import PAPER_CTX_MAX_CHARS, ChunkResult
from texlate.xlat.state import segment_key

if TYPE_CHECKING:
    from texlate.chunk import ChunkIn

log = logging.getLogger(__name__)


class _XlatMaterialize:
    """文档级物化 + 段级缓存 mixin（实例状态由 ``XlatPipeline.__init__`` 初始化）。"""

    # ------------------------------------------------------------ 物化

    def _system_prompt(
        self, kind: str, *, batch: bool = False, paper_ctx: bool = True
    ) -> str:
        key = (kind, batch, paper_ctx)
        if key not in self._prompts:
            self._prompts[key] = prompts.build_system_prompt(
                kind,
                src_lang=self.cfg.src_lang,
                tgt_lang=self.cfg.tgt_lang,
                glossary_terms=self._doc_glossary,
                batch=batch,
                paper_context=self._paper_ctx if paper_ctx else None,
                placeholder_manifest=self._ph_manifest or None,
            )
        return self._prompts[key]

    async def _auto_glossary(
        self, chunks: list[ChunkIn], pending: list[ChunkIn]
    ) -> dict[str, str]:
        """``auto_glossary_fn`` 抽取层——空 pending 不抽；失败降级 {} 不炸主链。

        术语是增强件：抽取调用炸（网关/JSON/超时）只损失一层术语注入，
        不该让论文 fault。输入=全量 chunks 的 masked 文本（与
        ``_materialize`` 文档级过滤同口径，``[[X_n]]`` 占位符由抽取
        prompt 按不透明 token 跳过）。
        """
        fn = self.cfg.auto_glossary_fn
        if fn is None or not pending:
            return {}
        try:
            terms = await fn([c.content for c in chunks])
        except Exception as e:  # noqa: BLE001 -- 增强件失败只告警不致死
            log.warning("auto-glossary extraction failed → 无 auto 层续跑: %s", e)
            return {}
        return terms or {}

    def _materialize(
        self, chunks: list[ChunkIn], auto_terms: dict[str, str] | None = None
    ) -> None:
        """文档级术语表过滤一次——整个跑批期间 system prompt 逐字节恒定。

        ``chunks`` 是全量输入块（含 state 已完成块）而非 pending 子集——
        ``doc_filter`` 与 ``_paper_ctx`` 锚定须见已完成块，续跑口径才与
        全新跑逐字节一致（前缀缓存身份 + abstract 锚不漂）。
        """
        self._doc_glossary = dict(auto_terms or {})
        if self.glossary is not None:
            # curated 四层表 update 在后赢同 key——auto 抽取层是底座
            self._doc_glossary.update(
                self.glossary.doc_filter(c.content for c in chunks)
            )
        # 首个 abstract 块 masked 原文截断做 paper-context 锚定块（texglot
        # ``paper_context`` 同族）；[[X_n]] 保留无妨——值由 user 侧
        # placeholder_values 块供读。全量 chunks 扫描（含已完成块）——
        # 续跑口径与全新跑逐字节一致。
        self._paper_ctx = next(
            (c.content[:PAPER_CTX_MAX_CHARS] for c in chunks if c.kind == "abstract"),
            "",
        )
        # 文档级占位符点名册（v5 恒等注入替代件）——与 doc_filter 同口径
        # 全量集（含已完成块，续跑逐字节一致）。单行压 <Glossary> 块末行，
        # 占位符多的文档也只是 O(类型 + 连续段) 而非 O(占位符) 重发。
        self._ph_manifest = placeholders.render_placeholder_manifest(
            placeholders.collect_doc_placeholders(c.content for c in chunks)
        )
        # 同实例二次 run 换了文档 → 术语块变了，prompt memo 必须失效重渲染
        self._prompts.clear()

    def _seg_key(self, c: ChunkIn) -> str:
        """段级缓存键：source + role + masked 快照（占位符布局变则 key 变）。"""
        ph_types = [
            placeholders.ph_type(p) for p in placeholders.ANY_PH_RX.findall(c.content)
        ]
        return segment_key(c.content, c.kind, masked_snapshot=repr(ph_types))

    def _cache_store(self, c: ChunkIn, zh: str) -> None:
        """段级缓存写入；过不了升格拦截网注册表的译文不入缓存——防毒化续跑。

        缓存命中旁路校验：同一份污染译文若落缓存，每轮续跑反复命中、永远修不正。
        判定口径 = ``_INTERCEPT_NETS`` 各 ``detect``（``_collect`` 升格拦截同源）。
        """
        if self.cache is None or _interceptable(c.content, zh):
            return
        self.cache[self._seg_key(c)] = zh

    def _cache_hit(self, c: ChunkIn, batch_id: str) -> ChunkResult | None:
        """缓存命中解析 → ok 结果；命中旧毒条目则清除并返回 None（落回重翻自愈）。

        旧版写入侧放行过 ``_interceptable`` 译文——不清则缓存命中旁路校验，
        毒译每轮续跑都被 intercept 降 fault、永不修复。
        """
        if self.cache is None:
            return None
        key = self._seg_key(c)
        if key not in self.cache:
            return None
        zh = self.cache[key]
        if _interceptable(c.content, zh):
            del self.cache[key]
            log.warning("evicted poisoned cache entry for %s", c.chunk_id)
            return None
        return ChunkResult(
            chunk_id=c.chunk_id,
            source=c.content,
            translation=zh,
            kind=c.kind,
            status="ok",
            batch_id=batch_id,
        )
