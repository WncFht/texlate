"""ruleset —— rules/ 规则库的校验装载 + phase 查询 (C2 自 engine.py 拆出).

``Rule``/``Ruleset``/``load_ruleset``/``RULES_PATH``/``RulesetError`` +
装载期校验助手 (``_when_problems``/``_cond_problems``/``_dup_id_problems``)
+ when/condition/action 词表常量簇 + ``_FAMILY_TOKENS`` 展开 +
``_RULESET_CACHE`` 分片指纹缓存。不依赖 engine——动作解释器在
``actions.py``, 主循环在 ``engine.py`` (两侧均门面回引本叶公共名)。

C5 拆叶：实现体按域拆进四个 ``_ruleset_*`` 私有兄弟叶，本文件化纯
PEP 562 惰性门面 (同 ``fixloop/engine`` 形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``ruleset.X`` 公共面与 ``from ... import X``/``M._x`` 属性读面不变。
monkeypatch 锚点注意：patch 叶子不 patch 门面 (docs/dev/seams.md §1)
——``ruleset.name`` 读到的恒是叶子对象，但 ``setattr(ruleset, ...)``
只遮蔽门面不改叶子内部互引。叶子间互引走全路径直跨
(``texlate.compile.fixloop._ruleset_<叶>``), 不经本门面。

叶谱：``_ruleset_vocab`` 词表常量簇+RULES_PATH (纯数据，无 builtins
链) / ``_ruleset_family`` _FAMILY_TOKENS 占位展开 /
``_ruleset_validate`` 装载期校验助手簇 / ``_ruleset_core``
Rule+Ruleset+ 缓存装载+phase 查询。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.compile.fixloop._ruleset_core import (
        _RULESET_CACHE,
        _RULESET_CACHE_MAX,
        Rule,
        Ruleset,
        RulesetError,
        _ruleset_fingerprint,
        load_ruleset,
    )
    from texlate.compile.fixloop._ruleset_family import (
        _FAMILY_TOKENS,
        _expand_family_tokens,
    )
    from texlate.compile.fixloop._ruleset_validate import (
        _action_params_problems,
        _cond_problems,
        _cond_value_problems,
        _dup_id_problems,
        _producible_categories,
        _re_compilable,
        _rewrite_flag_bit,
        _rewrite_item_problems,
        _rx_problems,
        _scan_pattern_problems,
        _str_list,
        _taxonomy_problems,
        _warnings_problems,
        _when_item_problems,
        _when_problems,
    )
    from texlate.compile.fixloop._ruleset_vocab import (
        _ACTION_KEYS,
        _ACTION_KINDS,
        _ACTION_PARAM_KEYS,
        _BUILTIN_CATS,
        _COND_KEYS,
        _COND_REGEX_KEYS,
        _COND_STR_KEYS,
        _DEGRADE_VALUES,
        _ENGINE_NAMES,
        _ENGINE_SPEC_KEYS,
        _FALLBACK_VALUES,
        _FILESET_KEYS,
        _MATCH_SURFACES,
        _MECH_ID_RX,
        _MODES,
        _PHASES,
        _REWRITE_KEYS,
        _SCAN_PATTERN_KEYS,
        _TAXONOMY_SCOPES,
        _WHEN_ITEM_KEYS,
        _WHEN_KEYS,
        RULES_PATH,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_ruleset_core": (
        "Rule",
        "Ruleset",
        "RulesetError",
        "load_ruleset",
        "_ruleset_fingerprint",
        "_RULESET_CACHE",
        "_RULESET_CACHE_MAX",
    ),
    "_ruleset_family": (
        "_expand_family_tokens",
        "_FAMILY_TOKENS",
    ),
    "_ruleset_validate": (
        "_action_params_problems",
        "_cond_problems",
        "_cond_value_problems",
        "_dup_id_problems",
        "_producible_categories",
        "_re_compilable",
        "_rewrite_flag_bit",
        "_rewrite_item_problems",
        "_rx_problems",
        "_scan_pattern_problems",
        "_str_list",
        "_taxonomy_problems",
        "_warnings_problems",
        "_when_item_problems",
        "_when_problems",
    ),
    "_ruleset_vocab": (
        "RULES_PATH",
        "_ACTION_KEYS",
        "_ACTION_KINDS",
        "_ACTION_PARAM_KEYS",
        "_BUILTIN_CATS",
        "_COND_KEYS",
        "_COND_REGEX_KEYS",
        "_COND_STR_KEYS",
        "_DEGRADE_VALUES",
        "_ENGINE_NAMES",
        "_ENGINE_SPEC_KEYS",
        "_FALLBACK_VALUES",
        "_FILESET_KEYS",
        "_MATCH_SURFACES",
        "_MECH_ID_RX",
        "_MODES",
        "_PHASES",
        "_REWRITE_KEYS",
        "_SCAN_PATTERN_KEYS",
        "_TAXONOMY_SCOPES",
        "_WHEN_ITEM_KEYS",
        "_WHEN_KEYS",
    ),
}

_LAZY: dict[str, str] = {
    name: leaf for leaf, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集，
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "RULES_PATH",
    "_ACTION_KEYS",
    "_ACTION_KINDS",
    "_ACTION_PARAM_KEYS",
    "_BUILTIN_CATS",
    "_COND_KEYS",
    "_COND_REGEX_KEYS",
    "_COND_STR_KEYS",
    "_DEGRADE_VALUES",
    "_ENGINE_NAMES",
    "_ENGINE_SPEC_KEYS",
    "_FALLBACK_VALUES",
    "_FAMILY_TOKENS",
    "_FILESET_KEYS",
    "_MATCH_SURFACES",
    "_MECH_ID_RX",
    "_MODES",
    "_PHASES",
    "_REWRITE_KEYS",
    "_RULESET_CACHE",
    "_RULESET_CACHE_MAX",
    "_SCAN_PATTERN_KEYS",
    "_TAXONOMY_SCOPES",
    "_WHEN_ITEM_KEYS",
    "_WHEN_KEYS",
    "Rule",
    "Ruleset",
    "RulesetError",
    "_action_params_problems",
    "_cond_problems",
    "_cond_value_problems",
    "_dup_id_problems",
    "_expand_family_tokens",
    "_producible_categories",
    "_re_compilable",
    "_rewrite_flag_bit",
    "_rewrite_item_problems",
    "_ruleset_fingerprint",
    "_rx_problems",
    "_scan_pattern_problems",
    "_str_list",
    "_taxonomy_problems",
    "_warnings_problems",
    "_when_item_problems",
    "_when_problems",
    "load_ruleset",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"{__package__}.{leaf}"), name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return __all__


def _export_drift() -> list[str]:
    """``__all__``/``_LEAF_EXPORTS``/本地公共名三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。三向覆盖：

    - ``_LAZY`` 键全进 ``__all__``;
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链 (``_LEAF_EXPORTS``
      配名叶子不提供) 与幽灵条 (既非叶子名也非本地名) 在此曝，是首访
      ``AttributeError`` 唯一的提前闸;
    - 本地公共名 (本模块定义的函数/类) 全进 ``__all__``。

    审计实载全部叶子，只供测试调用，装载期不自检。
    """
    mod = sys.modules[__name__]
    drift = [
        f"{name} in _LEAF_EXPORTS but missing from __all__"
        for name in _LAZY
        if name not in __all__
    ]
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    for name in __all__:
        try:
            getattr(mod, name)
        except Exception as exc:  # noqa: BLE001 -- 审计兜全漂移，非首错即死
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and (
            isinstance(v, dict)
            or (callable(v) and getattr(v, "__module__", None) == __name__)
        )
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
