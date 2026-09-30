"""``PipelineWorker._Compile`` + fixloop 模块件——compiling 段全链。

god-split: 实现体按域拆进同包 7 叶——``compile_splice``（zh 工程物化：
splice/zip/源码回灌同步）、``compile_engine``（引擎构造/任务 texmf 树/
依赖探针/修复实况帧）、``compile_en``（en.pdf 臂）、``compile_fixloop``
（fixloop/precheck/llm_hook 救援链）、``compile_l2``（L2 回灌 + 块级
回写事务）、``compile_artifacts``（dual.json/md.zip/ToUnicode 交付产物）、
``compile_stage``（终态阶梯编排 + zh 编译链驱动 + ``_Compile`` 组合根）。
本文件是 PEP 562 惰性门面（同 ``seqpos/__init__``/``fixloop/builtins``
形制）——平名经 ``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访
解析并缓存，``compile.X`` 公共面与 ``from .compile import X`` 不变。
monkeypatch 锚点注意：patch 叶子不 patch 门面（docs/dev/seams.md §1）
——``compile.X`` 读到的恒是叶子对象，但 ``setattr(compile, ...)``
只遮蔽门面不改叶子内部互引。叶子间互引走全路径直跨
（``texlate.server.worker.compile_<叶>``），不经本门面。
"""

from __future__ import annotations

import importlib
import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.server.worker.compile_artifacts import (
        _CompileArtifacts,
    )
    from texlate.server.worker.compile_en import (
        _CompileEn,
    )
    from texlate.server.worker.compile_engine import (
        _CompileEngine,
    )
    from texlate.server.worker.compile_fixloop import (
        _CompileFixloop,
        _fixloop_summary,
    )
    from texlate.server.worker.compile_l2 import (
        _CompileL2,
    )
    from texlate.server.worker.compile_splice import (
        _CompileSplice,
        _delivered_map,
        _seq_mark_scrub,
        _seq_marks_on,
        _sync_fixed_sources,
    )
    from texlate.server.worker.compile_stage import (
        _Compile,
        _CompileStage,
        _repair_detail,
    )

log = logging.getLogger(__name__)

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "compile_artifacts": ("_CompileArtifacts",),
    "compile_en": ("_CompileEn",),
    "compile_engine": ("_CompileEngine",),
    "compile_fixloop": (
        "_CompileFixloop",
        "_fixloop_summary",
    ),
    "compile_l2": ("_CompileL2",),
    "compile_splice": (
        "_CompileSplice",
        "_delivered_map",
        "_seq_mark_scrub",
        "_seq_marks_on",
        "_sync_fixed_sources",
    ),
    "compile_stage": (
        "_Compile",
        "_CompileStage",
        "_repair_detail",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集，
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "_Compile",
    "_CompileArtifacts",
    "_CompileEn",
    "_CompileEngine",
    "_CompileFixloop",
    "_CompileL2",
    "_CompileSplice",
    "_CompileStage",
    "_delivered_map",
    "_fixloop_summary",
    "_repair_detail",
    "_seq_mark_scrub",
    "_seq_marks_on",
    "_sync_fixed_sources",
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
