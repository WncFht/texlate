"""``PipelineWorker._Translate``——translating 段 + 译器/词表/用量接线。

god-split: 实现体按域拆进同包 6 叶——``translate.stage``（translating
段编排 + ``_Translate`` 组合根）、``translate.cache``（``_NullCache``
段缓存全哑面 + ``_make_cache`` 防毒围栅）、``translate.xlator``
（Translator 构造决策链 + mock_run 审计键）、``translate.glossary``
（术语表层解析/装配/自动抽取接线）、``translate.envjudge``（env_judge
判定过滤）、``translate.usage``（usage 记账 + 旁路臂收尾）。本文件是
PEP 562 惰性门面（同 ``compile``/``_common`` 形制）——平名经
``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``translate.X`` 公共面与 ``from texlate.server.worker.translate import X`` 不变；拆分前
单件期 import 期名面（stdlib 模块名/typing 绑定/``_common`` 转口/
texlate 顶层名）同样逐名惰性解析。
monkeypatch 锚点注意：patch 叶子不 patch 门面（docs/dev/seams.md §1）。
叶子间互引走全路径直跨（``texlate.server.worker.translate_<叶>``），
不经本门面。
"""

from __future__ import annotations

import importlib
import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # __all__ 名单静态落地——F822 要名可解，F401 以 __all__ re-export 豁免;
    # 私有惰性名不在此列 (不在 __all__, 无 F822 需，导入反吃 F401)。
    import asyncio
    import contextlib
    import hashlib
    import json
    import time
    from pathlib import Path
    from typing import Any, TypeVar

    from texlate.pipecore import auto_glossary_fn
    from texlate.repair import (
        ENV_ENV_JUDGE,
        env_judge_all,
        resolve_glossary_path,
        unknown_env_of,
    )
    from texlate.server.settings import cache_scope, validate_model
    from texlate.server.worker import seams
    from texlate.server.worker._common import (
        FAILED_DB,
        PROGRESS,
        DBStateBridge,
        SegmentCache,
        TaskCtx,
        chunk_db_id,
        chunk_error_code,
        opt_bool,
    )
    from texlate.textutil import env_flag
    from texlate.textutil.osutil import translator_mode
    from texlate.validate.l0 import pair_feedback
    from texlate.xlat.client import (
        DEFAULT_MODEL,
        AuthError,
        ChatClient,
        UsageRecord,
    )
    from texlate.xlat.glossary import (
        LOCAL_GLOSSARY_NAME,
        Glossary,
    )
    from texlate.xlat.pipeline import (
        ChunkIn,
        ChunkResult,
        GatewayTranslator,
        MockTranslator,
        PipelineConfig,
        Translator,
        XlatPipeline,
    )
    from texlate.xlat.prompts import PROMPT_VERSION

log = logging.getLogger(__name__)

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "cache": (
        "_NullCache",
        "_TranslateCache",
    ),
    "envjudge": ("_TranslateEnvJudge",),
    "glossary": ("_TranslateGlossary",),
    "stage": (
        "_Translate",
        "_TranslateStage",
    ),
    "usage": ("_T", "_TranslateUsage"),
    "xlator": ("_TranslateXlator",),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 拆分前单件期模块属性面——stdlib 模块名、typing/pathlib 绑定、
# ``._common``/``.share``/``seams`` 兄弟件转口与 texlate.* 顶层名全部按名
# 惰性解析 (setattr 型 monkeypatch 落在共享 module 对象上照旧触达真身)。
_STDLIB_MODS = (
    "asyncio",
    "contextlib",
    "hashlib",
    "json",
    "logging",
    "sys",
    "time",
)
_EXTRA_BINDINGS = {
    "Any": "typing",
    "Path": "pathlib",
    "TYPE_CHECKING": "typing",
    "TypeVar": "typing",
    "annotations": "__future__",
}
_MODULE_ATTRS = {
    "seams": "texlate.server.worker.seams",
}
_TEXLATE_EXPORTS = {
    "AuthError": "texlate.xlat.client",
    "ChatClient": "texlate.xlat.client",
    "ChunkIn": "texlate.xlat.pipeline",
    "ChunkResult": "texlate.xlat.pipeline",
    "DBStateBridge": "texlate.server.worker._common",
    "DEFAULT_MODEL": "texlate.xlat.client",
    "ENV_ENV_JUDGE": "texlate.repair",
    "FAILED_DB": "texlate.server.worker._common",
    "GatewayTranslator": "texlate.xlat.pipeline",
    "Glossary": "texlate.xlat.glossary",
    "LOCAL_GLOSSARY_NAME": "texlate.xlat.glossary",
    "MockTranslator": "texlate.xlat.pipeline",
    "PROGRESS": "texlate.server.worker._common",
    "PROMPT_VERSION": "texlate.xlat.prompts",
    "PipelineConfig": "texlate.xlat.pipeline",
    "SegmentCache": "texlate.server.worker._common",
    "TaskCtx": "texlate.server.worker._common",
    "Translator": "texlate.xlat.pipeline",
    "UsageRecord": "texlate.xlat.client",
    "XlatPipeline": "texlate.xlat.pipeline",
    "_DB_TO_PIPE": "texlate.server.worker._common",
    "_FLUSH_MS": "texlate.server.worker._common",
    "_FLUSH_N": "texlate.server.worker._common",
    "_FallbackTranslator": "texlate.server.worker._common",
    "_PIPE_TO_DB": "texlate.server.worker._common",
    "_PerCallTranslator": "texlate.server.worker._common",
    "_SPLICE_STALE_KINDS": "texlate.server.worker._common",
    "_glossary_option": "texlate.server.worker._common",
    "_new_usage_meter": "texlate.server.worker._common",
    "_repend_puts": "texlate.server.worker._common",
    "_row_status_snap": "texlate.server.worker._common",
    "_share_sourced": "texlate.server.worker.share",
    "_tgt_lang": "texlate.server.worker._common",
    "_translate_progress": "texlate.server.worker._common",
    "_translator_clients": "texlate.server.worker._common",
    "auto_glossary_fn": "texlate.pipecore",
    "cache_scope": "texlate.server.settings",
    "chunk_db_id": "texlate.server.worker._common",
    "chunk_error_code": "texlate.server.worker._common",
    "env_flag": "texlate.textutil",
    "env_judge_all": "texlate.repair",
    "opt_bool": "texlate.server.worker._common",
    "pair_feedback": "texlate.validate.l0",
    "resolve_glossary_path": "texlate.repair",
    "translator_mode": "texlate.textutil.osutil",
    "unknown_env_of": "texlate.repair",
    "validate_model": "texlate.server.settings",
}

# 字面列表 = 拆分前 ``import *`` 面 (原件无 __all__, 非下划线全局名逐名
# 保留); 私有名经 _LAZY/_TEXLATE_EXPORTS 进属性读面不进 __all__。
__all__ = [
    "DEFAULT_MODEL",
    "ENV_ENV_JUDGE",
    "FAILED_DB",
    "LOCAL_GLOSSARY_NAME",
    "PROGRESS",
    "PROMPT_VERSION",
    "TYPE_CHECKING",
    "Any",
    "AuthError",
    "ChatClient",
    "ChunkIn",
    "ChunkResult",
    "DBStateBridge",
    "GatewayTranslator",
    "Glossary",
    "MockTranslator",
    "Path",
    "PipelineConfig",
    "SegmentCache",
    "TaskCtx",
    "Translator",
    "TypeVar",
    "UsageRecord",
    "XlatPipeline",
    "annotations",
    "asyncio",
    "auto_glossary_fn",
    "cache_scope",
    "chunk_db_id",
    "chunk_error_code",
    "contextlib",
    "env_flag",
    "env_judge_all",
    "hashlib",
    "json",
    "log",
    "logging",
    "opt_bool",
    "pair_feedback",
    "resolve_glossary_path",
    "seams",
    "sys",
    "time",
    "translator_mode",
    "unknown_env_of",
    "validate_model",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性 / stdlib 绑定 / 兄弟件·texlate 顶层名。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"{__package__}.{leaf}"), name)
        globals()[name] = value
        return value
    if name in _STDLIB_MODS:
        value = importlib.import_module(name)
        globals()[name] = value
        return value
    extra = _EXTRA_BINDINGS.get(name)
    if extra is not None:
        value = getattr(importlib.import_module(extra), name)
        globals()[name] = value
        return value
    mod_path = _MODULE_ATTRS.get(name)
    if mod_path is not None:
        value = importlib.import_module(mod_path)
        globals()[name] = value
        return value
    texmod = _TEXLATE_EXPORTS.get(name)
    if texmod is not None:
        value = getattr(importlib.import_module(texmod), name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return sorted(
        set(globals())
        | set(__all__)
        | set(_LAZY)
        | set(_STDLIB_MODS)
        | set(_MODULE_ATTRS)
        | set(_EXTRA_BINDINGS)
        | set(_TEXLATE_EXPORTS)
    )


def _export_drift() -> list[str]:
    """``_LAZY``/``__all__``/叶子实体三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。逐名 ``getattr`` 实解：叶子断链
    (``_LEAF_EXPORTS`` 配名叶子不提供) 与幽灵条 (解析不到任何叶子或绑
    定) 在此曝，是首访 ``AttributeError`` 唯一的提前闸。审计实载全部
    叶子，只供测试调用，装载期不自检。
    """
    mod = sys.modules[__name__]
    drift = []
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    drift += [
        f"leaf stem {stem!r} shadows an exported name (rename the leaf)"
        for stem in _LEAF_EXPORTS
        if stem in _LAZY
    ]
    for name in _LAZY:
        try:
            getattr(mod, name)
        except Exception as exc:  # noqa: BLE001 -- 审计兜全漂移，非首错即死
            drift.append(f"_LEAF_EXPORTS entry {name} does not resolve: {exc}")
    for name in __all__:
        if name in _LAZY:
            continue  # 已解
        try:
            getattr(mod, name)
        except Exception as exc:  # noqa: BLE001 -- 同上
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and name not in _STDLIB_MODS
        and name not in _EXTRA_BINDINGS
        and name not in _MODULE_ATTRS
        and name not in _TEXLATE_EXPORTS
        and callable(v)
        and getattr(v, "__module__", None) == __name__
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
