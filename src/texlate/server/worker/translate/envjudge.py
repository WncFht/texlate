"""worker.translate.envjudge — env_judge 判定过滤叶 (worker.translate 域缝叶)。

``_env_judge_enabled`` 开关仲裁（options 显式优先、``TEXLATE_ENV_JUDGE``
缺省、共享译文任务恒关）、``_env_judge_filter`` 静态表外 env 块 LLM
可译性判定——判 false 移出 splice 映射 + 落库 ``fallback_orig``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from texlate.repair_l2 import ENV_ENV_JUDGE, env_judge_all, unknown_env_of
from texlate.server.worker._common import (
    _tgt_lang,
    _translator_clients,
    chunk_db_id,
    opt_bool,
)
from texlate.server.worker.share import _share_sourced
from texlate.textutil import env_flag
from texlate.xlat.pipeline import PipelineConfig, XlatPipeline

if TYPE_CHECKING:
    from texlate.latex.model import Chunk
    from texlate.server.worker._common import TaskCtx


class _TranslateEnvJudge:
    """env_judge mixin（开关仲裁 + splice 映射过滤）。"""

    def _env_judge_enabled(self, ctx: TaskCtx) -> bool:
        """env_judge 开关：``options.env_judge`` 显式优先，缺省读 ``TEXLATE_ENV_JUDGE``（默认关）。

        共享译文任务（kind=share 导入 / arxiv 隐式命中）恒关——零 token
        结构承诺，options/env 无权打开。
        """
        if _share_sourced(ctx):
            return False
        return opt_bool(
            ctx.options(),
            "env_judge",
            lambda: env_flag(ENV_ENV_JUDGE, default=False),
        )

    def _env_judge_filter(  # 守卫/回退阶梯平铺即 spec 的跳过面
        self,
        ctx: TaskCtx,
        trans: dict[str, str],
        rows: list[dict[str, Any]],
    ) -> dict[str, str]:
        """静态表外 env 块问 LLM 可译性（e2e ``_env_judge_pass`` 同语义）。

        判 false 的块移出 splice 映射（回写时保留原文）并落库
        ``fallback_orig``/``env_judge``。
        """
        if not self._env_judge_enabled(ctx) or not trans:
            return trans
        targets: list[tuple[str, Chunk, str]] = []
        for rel, res in ctx.scans.items():
            for c in res.chunks:
                env_name = unknown_env_of(c)
                if env_name is None:
                    continue
                cid = chunk_db_id(rel, c.span.start, c.span.end)
                if cid in trans:
                    targets.append((cid, c, env_name))
        if not targets:
            return trans
        translator = self._make_translator(ctx)
        clients = _translator_clients(translator)
        usage = self._meter_usage(clients)
        pipe = XlatPipeline(
            translator,
            config=PipelineConfig(tgt_lang=_tgt_lang(str(ctx.row["target_lang"]))),
            glossary=self._make_glossary(ctx),
        )

        try:
            verdicts = self._run_ephemeral(
                clients, lambda: env_judge_all(pipe, targets)
            )
        finally:
            # judge 调用也烧 token——不入账就从 task_usage 里蒸发
            self._teardown_bypass(ctx, usage, clients, label="env_judge")
        reverted = sorted(cid for cid, keep in verdicts.items() if not keep)
        self._log(
            ctx,
            f"env_judge: {len(targets)} 块待判，{len(reverted)} 块回落原文",
        )
        if not reverted:
            return trans
        by_id = {r["chunk_id"]: r for r in rows}
        updates = [
            (
                cid,
                {
                    "status": "fallback_orig",
                    "translation": str(by_id[cid]["src_text"] or ""),
                    "error_code": "env_judge",
                },
            )
            for cid in reverted
            if cid in by_id
        ]
        self._flush_chunk_updates(ctx, updates, [])
        out = dict(trans)
        for cid in reverted:
            out.pop(cid, None)
        return out
