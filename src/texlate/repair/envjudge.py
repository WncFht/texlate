"""repair.envjudge — env judge 可译性判定叶 (repair 拆分叶).

静态表外 env 的目标选择谓词 ``unknown_env_of`` + 逐条 LLM 判定
``_env_judge_one``/``env_judge_all``（0 温/16 tok/3 试/解析失败
fail-open——宁翻勿漏）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from texlate.latex.tables import (
    ARG_TRANSPARENT_ENVS,
    MATH_ENVS,
    PROTECTED_ENVS,
    VERBATIM_ENVS,
)
from texlate.xlat import prompts as xlat_prompts

if TYPE_CHECKING:
    from texlate.latex.model import Chunk
    from texlate.xlat.pipeline import XlatPipeline

log = logging.getLogger(__name__)

#: env judge 输入截断（长 env 体只喂前 N 字符）
_ENV_JUDGE_MAX_CHARS = 2000

#: 静态环境表（已知语义的 env 不问 judge——体是否可译已由表决定）
_KNOWN_ENVS = MATH_ENVS | VERBATIM_ENVS | PROTECTED_ENVS | ARG_TRANSPARENT_ENVS


def unknown_env_of(chunk: Chunk) -> str | None:
    """静态表外 env 名——体可译性未定的 env 返名，已知/无 env 返 None。

    ``env_judge_all`` 目标选择谓词（e2e ``_env_judge_pass`` 与 worker
    ``_env_judge_filter`` 同一闸）。
    """
    env_name = (chunk.env or "").strip()
    return env_name if env_name and env_name not in _KNOWN_ENVS else None


async def _env_judge_one(pipe: XlatPipeline, chunk: Chunk, env_name: str) -> bool:
    """单 env 可译性判定（docs/spec/translate.md）：0 温/16 tok/3 试/解析失败 fail-open。"""
    system = xlat_prompts.env_judge_system_prompt(pipe.cfg.src_lang, pipe.cfg.tgt_lang)
    user = (
        f"\\begin{{{env_name}}}\n"
        f"{chunk.content[:_ENV_JUDGE_MAX_CHARS]}\n\\end{{{env_name}}}"
    )
    for _ in range(xlat_prompts.ENV_JUDGE_RETRIES):
        try:
            raw = await pipe.translator.translate(
                system=system,
                user=user,
                temperature=xlat_prompts.ENV_JUDGE_TEMPERATURE,
                max_tokens=xlat_prompts.ENV_JUDGE_MAX_TOKENS,
            )
            return xlat_prompts.parse_env_judge_answer(raw)
        except Exception as e:  # noqa: BLE001 -- judge 是旁路臂，异常→宁翻勿漏
            log.debug("env judge call failed (%s) → retry", e)
            continue
    return True


async def env_judge_all(
    pipe: XlatPipeline, targets: list[tuple[str, Chunk, str]]
) -> dict[str, bool]:
    """逐条判定未知 env 块（顺序跑——mock/单文件路径，量小）。"""
    out: dict[str, bool] = {}
    for cid, chunk, env_name in targets:
        out[cid] = await _env_judge_one(pipe, chunk, env_name)
    return out
