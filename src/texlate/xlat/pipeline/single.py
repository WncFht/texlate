"""pipeline 单块路径域（自 ``pipeline`` 出叶）：阶梯调用点 + logfix 回灌重译 + 抄回修复臂。

``_XlatSingle`` 是 ``XlatPipeline`` 的单块臂 mixin——每块经 retry 阶梯
（corrector/slots/repair 全套修复臂）；``retranslate_chunk`` 是 logfix 回灌
单发重译，不走阶梯。``_net_apply_fn`` 经 ``.pipeline`` 门面回取——其
``globals()`` 晚绑定钉在门面命名空间，是 tests ``setattr(pl, _intercept_*)``
补丁守恒的落点（docs/dev/seams.md §5）。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from texlate.xlat import placeholders, prompts
from texlate.xlat.intercept import _INTERCEPT_NETS
from texlate.xlat.pipeline import _net_apply_fn
from texlate.xlat.pipeline.translator import _strip_json_fence
from texlate.xlat.pipeline.types import ChunkResult
from texlate.xlat.retry import (
    assess_answer,
    bare_token_audit,
    translate_with_ladder,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from texlate.chunk import ChunkIn
    from texlate.xlat.pipeline.translator import Translator
    from texlate.xlat.pipeline.types import PipelineConfig

log = logging.getLogger(__name__)


def _slots_user_obj(
    c: ChunkIn,
    slots_map: dict[str, str],
    failures_json: str,
    *,
    cfg: PipelineConfig,
) -> dict[str, Any]:
    """Slots 调用 user JSON：slots + instructions + 可选字段。

    ``placeholder_values``（占位符值参考，截断口径同 user 后缀块）与
    ``slot_validation_failures`` 各自有才挂——字段缺席即"无此信息"，
    比空值少一层解析歧义。
    """
    user_obj: dict[str, Any] = {
        "slots": slots_map,
        "instructions": (
            f"Translate each slot value from {cfg.src_lang} to "
            f"{cfg.tgt_lang}. Return a JSON object mapping each "
            "slot id to its translation. Keep ids unchanged."
        ),
    }
    if c.ph_fragments:
        user_obj["placeholder_values"] = prompts.truncate_value_frags(c.ph_fragments)
    if failures_json:
        user_obj["slot_validation_failures"] = failures_json
    return user_obj


class _XlatSingle:
    """单块阶梯 + logfix 回灌 mixin（实例状态由 ``XlatPipeline.__init__`` 初始化）。"""

    if TYPE_CHECKING:
        # 组合根 ``.orch.XlatPipeline.__init__`` 注入的共享态契约
        cfg: PipelineConfig
        translator: Translator
        validator: Callable[[str, str], str]

    # ------------------------------------------------------------ 单块路径

    def _repair_fn(
        self, c: ChunkIn
    ) -> Callable[[str, str], tuple[str, list[str]]] | None:
        """阶梯修复臂：译文缺 token 且 fragment 唯一命中 → 抄回（placeholders 层）。"""
        frags = c.ph_fragments
        if not frags:
            return None

        def _repair(src_text: str, zh: str) -> tuple[str, list[str]]:
            todo = {
                ph: frags[ph]
                for ph in placeholders.diff(src_text, zh).missing
                if ph in frags
            }
            return placeholders.recover_copied_tokens(zh, todo)

        return _repair

    async def _one_chunk(self, c: ChunkIn, *, batch_id: str = "") -> ChunkResult:
        """单块：缓存命中 → 否则阶梯翻译 → 校验 → 结果。"""
        if hit := self._cache_hit(c, batch_id):
            return hit

        system = self._system_prompt(c.kind)

        async def translate_fn(src_text: str, feedback: str) -> str:
            user = src_text + prompts.render_value_context(c.ph_fragments or {})
            if feedback:
                user = f"{user}\n\n[previous_validation_error]\n{feedback}"
            return await self.translator.translate(
                system=system,
                user=user,
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
            )

        async def corrector_fn(original: str, translation: str, error: str) -> str:
            return await self.translator.translate(
                system=prompts.corrector_system_prompt(
                    self.cfg.src_lang, self.cfg.tgt_lang
                ),
                user=prompts.corrector_user_prompt(original, translation, error),
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
            )

        async def slots_fn(
            slots_map: dict[str, str], failures_json: str
        ) -> dict[str, str]:
            user_obj = _slots_user_obj(c, slots_map, failures_json, cfg=self.cfg)
            # response_format 在 3003 网关被静默忽略（B4a 实测三变体同输出）——
            # 只是 prompt 增强；真正约束在阶梯侧的槽位合法性校验 + 失败重问。
            raw = await self.translator.translate(
                system=self._system_prompt(c.kind, paper_ctx=False),
                user=json.dumps(user_obj, ensure_ascii=False),
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
                response_format={"type": "json_object"},
            )
            try:
                data = json.loads(_strip_json_fence(raw))
            except (json.JSONDecodeError, RecursionError):
                # RecursionError：模型输出超深嵌套同坏 JSON 计——弃本轮 slots
                return {}
            if isinstance(data, dict) and isinstance(data.get("slots"), dict):
                data = data["slots"]
            return data if isinstance(data, dict) else {}

        res = await translate_with_ladder(
            c.content,
            translate_fn=translate_fn,
            corrector_fn=corrector_fn,
            slots_fn=slots_fn,
            validate_fn=self.validator,
            repair_fn=self._repair_fn(c),
        )
        status = (
            "ok"
            if res.status == "ok"
            else "partial"
            if res.status == "recovered"
            else "fault"
        )
        # 坍缩标点清理已收口进阶梯 postlude（``assess_answer``）——fallback_orig
        # 原文在此不再过清洗，保住 ``fell_back`` 的 zh≡src 簿记不变量
        zh = res.translation
        if res.status in ("ok", "recovered"):
            self._cache_store(c, zh)
        return ChunkResult(
            chunk_id=c.chunk_id,
            source=c.content,
            translation=zh,
            kind=c.kind,
            status=status,
            batch_id=batch_id,
            skip_reason=(
                "; ".join(res.warnings) if res.status == "fallback_orig" else ""
            ),
            attempts=res.attempts,
            warnings=res.warnings,
            error_kind="validate" if res.status == "fallback_orig" else "",
        )

    async def retranslate_chunk(
        self, c: ChunkIn, compile_feedback: str
    ) -> ChunkResult | None:
        """Logfix 回灌单发重译：带 ``[compile_error]`` 反馈再要一次，不走阶梯。

        每 chunk 只此一发的配额由调用方（e2e logfix 回灌）记账。返回值：

        - ``None`` —— 传输层异常：保留原译，调用方按"未变"处理；
        - ``status="ok"`` —— rules 过：新译可入 splice（并写段级缓存）；
        - ``status="fault"`` + ``translation=source`` —— rules 仍败：
          调用方应回落原文（spec：再不过 → fallback 原文）。
        """
        system = self._system_prompt(c.kind)
        try:
            raw = await self.translator.translate(
                system=system,
                user=(
                    f"{c.content}"
                    f"{prompts.render_value_context(c.ph_fragments or {})}"
                    f"\n\n[compile_error]\n{compile_feedback}"
                ),
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
            )
        except Exception as e:  # noqa: BLE001 -- 传输崩=保留原译，不算一次有效修复
            log.debug("retranslate %s transport failed: %s", c.chunk_id, e)
            return None
        # 回灌 user 是未编码原文——token 多重集期望基线同为原文形态
        zh, err, warnings = assess_answer(
            c.content,
            placeholders.decode_newlines(raw),
            audit_err=bare_token_audit(c.content, raw),
            repair_fn=self._repair_fn(c),
            validate_fn=self.validator,
        )
        if err:
            return ChunkResult(
                chunk_id=c.chunk_id,
                source=c.content,
                translation=c.content,
                kind=c.kind,
                status="fault",
                attempts=1,
                warnings=[*warnings, f"retranslate still invalid: {err}"],
                error_kind="validate",
            )
        self._cache_store(c, zh)
        r = ChunkResult(
            chunk_id=c.chunk_id,
            source=c.content,
            translation=zh,
            kind=c.kind,
            status="ok",
            attempts=1,
            warnings=warnings,
        )
        # logfix 回灌同受拦截——fault 由调用方回落原文；与账本形同表晚绑定取件，
        # 新增网在本臂不会漏挂。
        for net in _INTERCEPT_NETS:
            _net_apply_fn(net)(r)
        return r
