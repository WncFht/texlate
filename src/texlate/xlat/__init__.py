"""翻译编排层：prompt 套件 / 批量 / 重试阶梯 / 术语表 / 断点续跑（规格 docs/08）。

惰性门面（PEP 562）：``__all__`` 平名经 ``__getattr__`` 映射回子模块惰性
解析——``import texlate.xlat.placeholders`` 不再经包 init 拉入 httpx 等
重依赖（audit: 全仓消费者均为子模块级 import，平名零消费者）。
"""

from __future__ import annotations

import importlib

_SUBMODULE_EXPORTS: dict[str, tuple[str, ...]] = {
    "batch": (
        "BATCH_MAX_CHARS",
        "BATCH_MAX_ITEMS",
        "BATCH_MIN_CHARS",
        "CHUNK_HARD_LIMIT",
        "encode_batch",
        "pack_batches",
        "parse_batch_response",
        "split_long_chunk",
    ),
    "client": (
        "ChatClient",
        "ChatError",
        "ChatOptions",
        "ChatResult",
        "FreeModel",
        "Usage",
        "pick_model",
        "provider_for_url",
        "redact",
    ),
    "glossary": ("Glossary", "TermEntry"),
    "pipeline": (
        "ChunkIn",
        "ChunkResult",
        "GatewayTranslator",
        "MockTranslator",
        "PipelineConfig",
        "Translator",
        "XlatPipeline",
    ),
    "placeholders": (
        "ANY_PH_RX",
        "BARE_PH_RX",
        "PH_FUZZY_RX",
        "TYPED_PH_RX",
        "PhDiff",
        "collect_doc_placeholders",
        "decode_newlines",
        "diff",
        "encode_newlines",
        "is_placeholder_only",
        "recover_copied_tokens",
        "sort_key",
    ),
    "prompts": (
        "ENV_JUDGE_MAX_TOKENS",
        "ENV_JUDGE_RETRIES",
        "ENV_JUDGE_TEMPERATURE",
        "NAME_CLAUSE",
        "PLACEHOLDER_CLAUSE",
        "PROMPT_VERSION",
        "build_system_prompt",
        "corrector_system_prompt",
        "corrector_user_prompt",
        "env_judge_system_prompt",
        "normalize_kind",
        "parse_env_judge_answer",
        "render_glossary_block",
    ),
    "retry": ("RetryPolicy", "call_with_backoff", "translate_with_ladder"),
    "state": (
        "ChunkRecord",
        "StateStore",
        "atomic_json",
        "file_cache_key",
        "load_cache",
        "segment_key",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _SUBMODULE_EXPORTS.items() for name in names
}

# 由映射表生成——单一事实源，避免两份清单漂移
__all__ = sorted(_LAZY)  # noqa: PLE0605


def __getattr__(name: str) -> object:
    """平名惰性解析 → 子模块属性；子模块名本身也走惰性 import。"""
    mod = _LAZY.get(name)
    if mod is not None:
        value = getattr(importlib.import_module(f".{mod}", __name__), name)
        globals()[name] = value
        return value
    if name in _SUBMODULE_EXPORTS:
        return importlib.import_module(f".{name}", __name__)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return __all__
