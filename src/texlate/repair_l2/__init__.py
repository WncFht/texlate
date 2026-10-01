"""repair_l2 — L2 回灌 / env judge 簇（自 ``repair`` 拆出的编译失败归因修复机械）.

C4 拆分（reaudit-2026-09-18）：``repair.py`` 收敛为 fixloop 包装/跨引擎
重试/glossary confine 纯低层件，本包承载 L2 阶梯全实现——
``TreeRun``/``split_cid`` 运行态、env judge 可译性判定
（``_env_judge_one``/``env_judge_all`` + 目标谓词 ``unknown_env_of``）、
L2 回灌机械（``_l2_parse``/``chunk_spans``/``_resolve_fidx``/``L2Attr``/
``_l2_localize``/``retranslate_hits``/``_resplice_and_diffs``/
``l2_repair_round``）与配套开关/上限常量。

本文件是 PEP 562 惰性门面（同 ``fixloop/ruleset`` 形制）——平名经
``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``repair_l2.X`` 公共面与 ``from ... import X``/``M._x`` 属性读面不变。
``ENV_*`` 开关名是字面量常量、零成本，直接 eager 回引钉点面。
monkeypatch 锚点注意：patch 叶子不 patch 门面（docs/dev/seams.md §1）
——``repair_l2.name`` 读到的恒是叶子对象，但 ``setattr(repair_l2, ...)``
只遮蔽门面不改叶子内部互引。叶子间互引走全路径直跨
（``texlate.repair_l2.<叶>``），不经本门面。

叶谱：``runstate`` TreeRun+split_cid 运行态 / ``envjudge`` env 可译性
判定簇 / ``attr`` 错误签名+归因桶+L2Attr+_l2_localize 归因面 /
``rounds`` retranslate_hits+resplice 簇+l2_repair_round 阶梯。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

from texlate.textutil.osutil import (
    ENV_ENV_JUDGE,
    ENV_NO_L2,
    ENV_NO_SEQ_MARKS,
)

if TYPE_CHECKING:
    from texlate.repair_l2.attr import (
        _ARM_FLAG_RX,
        _BUCKET_RX_CACHE,
        _BUCKETS,
        _FILELEVEL_CATS,
        _FILELEVEL_EXTRA,
        _INFRA_CATS,
        _INFRA_EXTRA,
        _L2_ATTR_WINDOW,
        _L2_MAX_ERRORS,
        _STRUCT_CATS,
        _STRUCT_EXTRA,
        _UNDEF_CS_CULPRIT_RXS,
        _UNDEF_CS_HEAD_RX,
        L2_MAX_CHUNKS,
        L2Attr,
        _bucket_rx,
        _l2_localize,
        _l2_parse,
        _resolve_fidx,
        _sig_head,
        _sig_set,
        _undef_cs_culprit,
        chunk_spans,
        err_signature,
        err_signatures,
        err_signatures_text,
    )
    from texlate.repair_l2.envjudge import (
        _ENV_JUDGE_MAX_CHARS,
        _KNOWN_ENVS,
        _env_judge_one,
        env_judge_all,
        unknown_env_of,
    )
    from texlate.repair_l2.rounds import (
        _resplice,
        _resplice_and_diffs,
        _slot_diffs,
        l2_repair_round,
        retranslate_hits,
    )
    from texlate.repair_l2.runstate import TreeRun, split_cid

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "runstate": (
        "TreeRun",
        "split_cid",
    ),
    "envjudge": (
        "env_judge_all",
        "unknown_env_of",
        "_env_judge_one",
        "_ENV_JUDGE_MAX_CHARS",
        "_KNOWN_ENVS",
    ),
    "attr": (
        "L2Attr",
        "L2_MAX_CHUNKS",
        "chunk_spans",
        "err_signature",
        "err_signatures",
        "err_signatures_text",
        "_bucket_rx",
        "_l2_localize",
        "_l2_parse",
        "_resolve_fidx",
        "_sig_head",
        "_sig_set",
        "_undef_cs_culprit",
        "_ARM_FLAG_RX",
        "_BUCKETS",
        "_BUCKET_RX_CACHE",
        "_FILELEVEL_CATS",
        "_FILELEVEL_EXTRA",
        "_INFRA_CATS",
        "_INFRA_EXTRA",
        "_L2_ATTR_WINDOW",
        "_L2_MAX_ERRORS",
        "_STRUCT_CATS",
        "_STRUCT_EXTRA",
        "_UNDEF_CS_CULPRIT_RXS",
        "_UNDEF_CS_HEAD_RX",
    ),
    "rounds": (
        "l2_repair_round",
        "retranslate_hits",
        "_resplice",
        "_resplice_and_diffs",
        "_slot_diffs",
    ),
}

_LAZY: dict[str, str] = {
    name: leaf for leaf, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集 +
# eager ENV_* 钉点面，新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "ENV_ENV_JUDGE",
    "ENV_NO_L2",
    "ENV_NO_SEQ_MARKS",
    "L2_MAX_CHUNKS",
    "_ARM_FLAG_RX",
    "_BUCKETS",
    "_BUCKET_RX_CACHE",
    "_ENV_JUDGE_MAX_CHARS",
    "_FILELEVEL_CATS",
    "_FILELEVEL_EXTRA",
    "_INFRA_CATS",
    "_INFRA_EXTRA",
    "_KNOWN_ENVS",
    "_L2_ATTR_WINDOW",
    "_L2_MAX_ERRORS",
    "_STRUCT_CATS",
    "_STRUCT_EXTRA",
    "_UNDEF_CS_CULPRIT_RXS",
    "_UNDEF_CS_HEAD_RX",
    "L2Attr",
    "TreeRun",
    "_bucket_rx",
    "_env_judge_one",
    "_l2_localize",
    "_l2_parse",
    "_resolve_fidx",
    "_resplice",
    "_resplice_and_diffs",
    "_sig_head",
    "_sig_set",
    "_slot_diffs",
    "_undef_cs_culprit",
    "chunk_spans",
    "env_judge_all",
    "err_signature",
    "err_signatures",
    "err_signatures_text",
    "l2_repair_round",
    "retranslate_hits",
    "split_cid",
    "unknown_env_of",
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
    drift += [
        f"leaf stem {stem!r} shadows an exported name (rename the leaf)"
        for stem in _LEAF_EXPORTS
        if stem in _LAZY
    ]
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
