r"""builtins.slotrev — zh 机位实参 revert (slotrevert 车道, task#188)。

机制 (zhleak 车道普查): segmenter 把未注册机位实参 (csname 体 /
未注册 env 尾随参等) 放上 chunk 翻译字面量面 → zh 化后 splice 写回
机位 → ``Undefined color '这是译文'``/``No counter``/``can't find file``
族。本叶做决定性 revert: ``judge.py`` ``_MACHINE_SLOT_RXS`` + 本叶扩展
表在 ``mask_tex`` 等长遮盖视图 (``DEAD_TAIL_RX`` 死尾截断同口径) 上
定位机位实参, 对 ``params.baseline_dir`` pristine 树逐文件做 per-kind
序号对齐配对 —— baseline 参纯 ASCII 标识符 ∧ zh 参含 CJK ∧ 两侧
相异 → zh 参位字节换回 baseline 参。``\section{标题}`` 等文位结构上
不在机位表内永不被碰; 某 kind 双侧命中数分歧 → 该 kind 整跳防错位
回写 (LLM 臆造/丢参时错位 revert 比不复原更糟), 唯 ``primgap`` kind
(原语 cs 与 ``{``-组之间 gap —— ``\vadjust 这是译文{``/``\leaders\hbox
这是译文{`` 面) 分歧时先判 unique-src 广播: src 全 gap 值唯一 ∧ 过
ident → 写进 zh 全部 CJK gap 站 (宏展开把 def 站机位倍增到调用站);
``baseline_dir`` 缺席/非目录 → False 空转 (standalone precheck 挂点
不注入 baseline)。

w8 拆叶: 实现体按件域拆进五个 ``_slotrev_*`` 私有兄弟叶, 本文件化纯
PEP 562 惰性门面 (同 ``csfix``/``gfx_missing`` 形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子, ``__getattr__`` 首访解析并缓存,
``slotrev.X`` 公共面与 ``from ... import X``/``M._x`` 属性读面不变。
monkeypatch 锚点注意: patch 叶子不 patch 门面 —— ``slotrev.name``
读到的恒是叶子对象, 但 ``setattr(slotrev, ...)`` 只遮蔽门面不改
叶子内部互引。叶子间互引走全路径直跨
(``texlate.compile.fixloop.builtins._slotrev_<叶>``), 不经本门面。

叶谱: ``_slotrev_lex`` 实参词法件 (``_ARG``/``_OPT*``/``_GAP``/
``_ARGB`` 系正则片段) / ``_slotrev_table`` ``_SLOTREV_EXTRA_RXS``
扩展机位表 / ``_slotrev_ident`` ident 白名单+``_is_ident`` /
``_slotrev_holder`` doc 内 spec-holder 宏探测 / ``_slotrev_engine``
配对 revert 引擎+``slot_arg_revert`` 入口。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.compile.fixloop.builtins._slotrev_engine import (
        CITE_FAMILY_RE,
        CJK_RX,
        Any,
        Path,
        _broadcast_value,
        _by_kind,
        _full_rxs,
        _revert_file,
        _revert_tree,
        _slot_spans,
        slot_arg_revert,
    )
    from texlate.compile.fixloop.builtins._slotrev_holder import (
        _HOLDER_CAP,
        _HOLDER_DEF_RX,
        _HOLDER_TAIL_RX,
        _holder_rxs,
        live_tex,
    )
    from texlate.compile.fixloop.builtins._slotrev_ident import (
        _BROADCAST_KINDS,
        _IDENT_KVNL_KINDS,
        _IDENT_KVNL_RX,
        _IDENT_LOOSE_KINDS,
        _IDENT_LOOSE_RX,
        _IDENT_SPEC_KINDS,
        _IDENT_SPEC_PREFIX,
        _IDENT_SPEC_RX,
        _IDENT_STRICT_RX,
        _KVNL_SHAPE_RX,
        _NOTE_CAP,
        _is_ident,
    )
    from texlate.compile.fixloop.builtins._slotrev_lex import (
        _ARG,
        _ARGB,
        _ARGNL,
        _BGM,
        _GAP,
        _NBC,
        _OPT,
        _OPTB,
        _OPTC,
    )
    from texlate.compile.fixloop.builtins._slotrev_table import (
        _SLOTREV_EXTRA_RXS,
        CMD_BOUNDARY,
        re,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_slotrev_engine": (
        "CITE_FAMILY_RE",
        "CJK_RX",
        "Any",
        "Path",
        "_broadcast_value",
        "_by_kind",
        "_full_rxs",
        "_revert_file",
        "_revert_tree",
        "_slot_spans",
        "slot_arg_revert",
    ),
    "_slotrev_holder": (
        "_HOLDER_CAP",
        "_HOLDER_DEF_RX",
        "_HOLDER_TAIL_RX",
        "_holder_rxs",
        "live_tex",
    ),
    "_slotrev_ident": (
        "_BROADCAST_KINDS",
        "_IDENT_KVNL_KINDS",
        "_IDENT_KVNL_RX",
        "_IDENT_LOOSE_KINDS",
        "_IDENT_LOOSE_RX",
        "_IDENT_SPEC_KINDS",
        "_IDENT_SPEC_PREFIX",
        "_IDENT_SPEC_RX",
        "_IDENT_STRICT_RX",
        "_KVNL_SHAPE_RX",
        "_NOTE_CAP",
        "_is_ident",
    ),
    "_slotrev_lex": (
        "_ARG",
        "_ARGB",
        "_ARGNL",
        "_BGM",
        "_GAP",
        "_NBC",
        "_OPT",
        "_OPTB",
        "_OPTC",
    ),
    "_slotrev_table": (
        "CMD_BOUNDARY",
        "_SLOTREV_EXTRA_RXS",
        "re",
    ),
}

_LAZY: dict[str, str] = {
    name: leaf for leaf, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集,
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "CITE_FAMILY_RE",
    "CJK_RX",
    "CMD_BOUNDARY",
    "_ARG",
    "_ARGB",
    "_ARGNL",
    "_BGM",
    "_BROADCAST_KINDS",
    "_GAP",
    "_HOLDER_CAP",
    "_HOLDER_DEF_RX",
    "_HOLDER_TAIL_RX",
    "_IDENT_KVNL_KINDS",
    "_IDENT_KVNL_RX",
    "_IDENT_LOOSE_KINDS",
    "_IDENT_LOOSE_RX",
    "_IDENT_SPEC_KINDS",
    "_IDENT_SPEC_PREFIX",
    "_IDENT_SPEC_RX",
    "_IDENT_STRICT_RX",
    "_KVNL_SHAPE_RX",
    "_NBC",
    "_NOTE_CAP",
    "_OPT",
    "_OPTB",
    "_OPTC",
    "_SLOTREV_EXTRA_RXS",
    "Any",
    "Path",
    "_broadcast_value",
    "_by_kind",
    "_full_rxs",
    "_holder_rxs",
    "_is_ident",
    "_revert_file",
    "_revert_tree",
    "_slot_spans",
    "live_tex",
    "re",
    "slot_arg_revert",
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

    空表 = 同步, 测试断言 ``== []`` 即可。三向覆盖:

    - ``_LAZY`` 键全进 ``__all__``;
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链 (``_LEAF_EXPORTS``
      配名叶子不提供) 与幽灵条 (既非叶子名也非本地名) 在此曝, 是首访
      ``AttributeError`` 唯一的提前闸;
    - 本地公共名 (本模块定义的函数/类) 全进 ``__all__``。

    审计实载全部叶子, 只供测试调用, 装载期不自检。
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
        except Exception as exc:  # noqa: BLE001 -- 审计兜全漂移, 非首错即死
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
