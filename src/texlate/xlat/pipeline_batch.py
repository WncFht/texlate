"""pipeline 批量路径域（自 ``pipeline`` 出叶）：编号批协议 + 解析失败整批退单翻。

``_XlatBatch`` 是 ``XlatPipeline`` 的批量臂 mixin——成员先过段级缓存短路，
实发子集走编号批量协议；批解析失败/批调用可重试失败 → 成员逐个回炉
单翻（复用并发额度），非可重试错误整块 skip。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from . import placeholders, prompts
from .authgate import _kind_of
from .batch import encode_batch_members, parse_batch_response
from .client import ChatError
from .pipeline_types import ChunkResult
from .retry import assess_answer, bare_token_audit

if TYPE_CHECKING:
    from texlate.chunk import ChunkIn

log = logging.getLogger(__name__)


def _merged_value_frags(members: list[ChunkIn]) -> dict[str, str]:
    """批成员 ``ph_fragments`` 合并——token 文档内唯一，同 key 后写赢。

    同 token 跨成员指向同实体，冲突本不该出现；合并块随批 user 尾挂，
    给模型读着消歧（texglot ``value_tokens`` 同族）。
    """
    merged: dict[str, str] = {}
    for c in members:
        if c.ph_fragments:
            merged.update(c.ph_fragments)
    return merged


class _XlatBatch:
    """编号批量协议 mixin（实例状态由 ``XlatPipeline.__init__`` 初始化）。"""

    # ------------------------------------------------------------ 批量路径

    async def _one_batch(
        self, members: list[ChunkIn], batch_id: str
    ) -> list[ChunkResult]:
        """一批：成员先过段级缓存短路，实发子集走编号批量协议。

        逐成员 ``_cache_hit`` 前置（D4）：命中块不进批载荷——省 token、防新应答
        经 ``_cache_store`` 覆盖原条目、批级失败（非可重试 skip/退单翻）也不再
        连坐有缓存的成员。批序号按实发子集编排，``send`` 记原序位回填，返回
        列表与 ``members`` 同序。
        """
        out: dict[int, ChunkResult] = {}
        send: list[tuple[int, ChunkIn]] = []
        for i, c in enumerate(members):
            if hit := self._cache_hit(c, batch_id):
                out[i] = hit
            else:
                send.append((i, c))
        if send:
            out.update(await self._batch_call(send, batch_id))
        return [out[i] for i in range(len(members))]

    async def _batch_call(
        self, send: list[tuple[int, ChunkIn]], batch_id: str
    ) -> dict[int, ChunkResult]:
        """实发子集的批量往返：编号请求 → 解析失败整批退单翻（成员走完整阶梯）。

        ``send`` = ``(members 内原序位，ChunkIn)`` 对；返回 ``{原序位：结果}``。
        """
        members = [c for _i, c in send]
        system = self._system_prompt(members[0].kind, batch=True)
        # 各成员 ph_fragments 合并成批级 value-context 随 user 尾挂；成员编码
        # 只跑一次——``enc_members[k]`` 直作下方 ``bare_token_audit`` 基线
        # （与线发字节结构性同源，免逐成员二次 ``encode_newlines`` 重推导）
        payload, enc_members = encode_batch_members([c.content for c in members])
        user = payload + (prompts.render_value_context(_merged_value_frags(members)))

        raw: str | None = None
        try:
            raw = await self.translator.translate(
                system=system,
                user=user,
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
            )
        except ChatError as e:
            if not e.retryable:
                # 认证/余额/地址类错误重试无意义——直接整块 skip
                return {
                    i: self._skip(c, str(e), batch_id, kind=_kind_of(e))
                    for i, c in send
                }
            log.debug("batch %s call failed (%s) → degrade to singles", batch_id, e)
        except Exception as e:  # noqa: BLE001 -- 批量调用崩→退单翻，绝不丢成员
            log.debug("batch %s crashed (%s) → degrade to singles", batch_id, e)

        parts = parse_batch_response(raw, len(members)) if raw is not None else None
        out: dict[int, ChunkResult] = {}
        if parts is None:
            for i, c in send:
                out[i] = await self._degrade_one(c, batch_id)
            return out

        for k, ((i, c), part) in enumerate(zip(send, parts, strict=True)):
            # 批成员按 ``encode_batch_members`` 同款编码形态对账锻造 token（D3）——
            # ``enc_members[k]`` 即 ``encode_newlines(c.content)[0]`` 的同源基线
            zh, err, warnings = assess_answer(
                c.content,
                placeholders.decode_newlines(part),
                audit_err=bare_token_audit(enc_members[k], part),
                repair_fn=self._repair_fn(c),
                validate_fn=self.validator,
            )
            if err:
                # 批成功但该块校验败 → 单块回炉走完整阶梯
                out[i] = await self._degrade_one(c, batch_id)
                continue
            self._cache_store(c, zh)
            out[i] = ChunkResult(
                chunk_id=c.chunk_id,
                source=c.content,
                translation=zh,
                kind=c.kind,
                status="ok",
                batched=True,
                batch_id=batch_id,
                attempts=1,
                warnings=warnings,
            )
        return out

    async def _degrade_one(self, c: ChunkIn, batch_id: str) -> ChunkResult:
        """批量退路：单块走阶梯；阶梯/传输失败 → 回退原文 skipped。"""
        try:
            return await self._one_chunk(c, batch_id=batch_id)
        except ChatError as e:
            return self._skip(c, f"degraded single: {e}", batch_id, kind=_kind_of(e))
        except Exception as e:  # noqa: BLE001 -- 单块崩不拖全批
            return self._skip(c, f"degraded single crash: {e}", batch_id, kind="crash")
