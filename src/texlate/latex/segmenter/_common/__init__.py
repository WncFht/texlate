r"""``latex/segmenter`` 共享层——常量/helper/数据类（原模块级原样搬移）。

拆分：实现体按域拆进同包七叶——``_common.tail``（非文本尾参扫：操作数
正则机 + ``_OPERAND_SCAN_STOP`` 终止符集 + ``_TAIL_RX`` 六别尾扫）、
``_common.slots``（待绑参槽字母表 ↔ ``_WSpec`` 归一投影 +
``_COND_GROUP_ARGS``）、``_common.fams``（``_FAM_BIND`` 分派族表单源 +
``_fams`` 行投影 + cite-ref/accent/inline-literal 谓词 +
``_MATH_TEXTARG``）、``_common.prose``（散文参门控：keyval/名单形状门 +
词链判据 + 吞块/死文本名闸）、``_common.tok``（``TokenSource`` 契约 +
``_ListSource`` 回放源 + ``_pull_cursor`` 游标对）、``_common.rec``
（``_Vtex`` + ``_RunItem``/``_EnvDeadTok``/``_ArgTok`` 记录型 + env 族
helper 三件 + ``_verb_delim_tok``/``_doc_begin_of``）、``_common.util``
（清洗/注释小表 + ``_chunk_spec_cached`` + ``_pick_cut`` 切点链）。
本文件是 PEP 562 惰性门面（同 ``server.worker._common`` 形制）——平名经
``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``from texlate.latex.segmenter._common import X`` 读面与拆分前逐名等价。叶子间互引走全路径
直跨（``texlate.latex.segmenter._common.<叶>``），不经本门面。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # __all__ 名单静态落地——F822 要名可解，F401 以 __all__ re-export 豁免；
    # 私有惰性名不在此列（不在 __all__，无 F822 需，导入反吃 F401）。
    import re
    from bisect import bisect_left
    from collections import deque
    from dataclasses import dataclass, field
    from typing import NamedTuple, Protocol

    from texlate.latex.macro_table import parse_argspec
    from texlate.latex.model import ArgSpec, PhType, Span
    from texlate.latex.placeholder import PH_RX
    from texlate.latex.segmenter._common.tok import TokenSource
    from texlate.latex.tables import (
        ACCENT_CHARS,
        BOUNDARY_NAMES,
        BOX_TAIL_NAMES,
        CHUNK_ARG_NAMES,
        CHUNK_MAX,
        CITE_NAMES,
        COND_RX,
        DEF_NAMES,
        DIMEN_TAIL_KIND,
        ENV_MANDATORY_ARG,
        FONT_SWITCHES,
        INLINE_LITERAL_CMDS,
        INPUT_CMDS,
        INPUT_SCAN_CMDS,
        MATH_ENVS,
        PAIR_BLOCK_ALL,
        PROTECT_BLOCK_NAMES,
        PROTECT_NAMES,
        PROTECTED_ENVS,
        REF_NAMES,
        TRANSPARENT_HEAD_SPEC,
        TRANSPARENT_NAMES,
        VERBATIM_ENVS,
    )
    from texlate.textutil import BEGIN_DOC_RX, DOCCLASS_RX, mask_tex

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "fams": (
        "_ENV_CS",
        "_FAM_BIND",
        "_MATH_CLOSE_CS",
        "_MATH_DELIM_CS",
        "_MATH_OPEN_CS",
        "_MATH_TEXTARG",
        "_MATH_TEXTARG_OPT_CAP",
        "_VERB_LIKE",
        "_accent_cs",
        "_cite_ref_type",
        "_fams",
        "_inline_lit_cs",
    ),
    "prose": (
        "_COMMA_LIST_RX",
        "_DEAD_ARG_NAMES",
        "_DEAD_TAIL_NAMES",
        "_KEYVAL_GROUP_RX",
        "_KEYVAL_ITEM_RX",
        "_KEY_TOKEN_RX",
        "_KV_COMMENT_RX",
        "_OPAQUE_ARG_PROSE_RX",
        "_OPAQUE_ARG_STRIP_RX",
        "_OPAQUE_ARG_WORD_RX",
        "_SWALLOW_ARG_NAMES",
        "_ZERO_WIDTH_ARG_RX",
        "_kv_list_shaped",
        "_prose_arg_hit",
        "_prose_text_hit",
        "_prose_word_hit",
    ),
    "rec": (
        "_ArgTok",
        "_EnvDeadTok",
        "_RunItem",
        "_Vtex",
        "_doc_begin_of",
        "_env_mand_count",
        "_env_ph_type",
        "_scan_envtag",
        "_verb_delim_tok",
    ),
    "slots": (
        "_ACCENT_SLOTS",
        "_BSBS_SLOTS",
        "_COND_GROUP_ARGS",
        "_HYPERREF_SLOTS",
        "_KEYARG_TAIL_DEPTH",
        "_KEYARG_TAIL_RX",
        "_PEND_CALL1",
        "_PEND_CALL2",
        "_PEND_PROBE",
        "_SLOT_ELEMS",
        "_SLOT_PAIR_LEN",
        "_SLOT_TEST_LEN",
        "_WSpec",
        "_WalkRes",
        "_aspec_elem",
        "_call_slots",
        "_cond_slots",
        "_gspec_elem",
        "_pend_call_slots",
        "_pend_slot_of",
        "_slot_elem",
    ),
    "tail": (
        "_BSBS_OPT_RX",
        "_DIMEN_NUM",
        "_DIMEN_UNIT",
        "_GRP_BSBS_CONTENT_RX",
        "_GRP_TAIL_CAP",
        "_OPERAND_BASE",
        "_OPERAND_CS",
        "_OPERAND_FACTOR",
        "_OPERAND_SCAN_STOP",
        "_TAIL_CAP",
        "_TAIL_OPERAND",
        "_TAIL_RELAX",
        "_TAIL_RX",
        "_WS_NOPAR",
    ),
    "tok": (
        "_ListSource",
        "_TEXT_RUN_HEADS",
        "_Unpull",
        "TokenSource",
        "_pull_cursor",
    ),
    "util": (
        "_ARG_COMMENT_RX",
        "_CHUNK_SPEC_CACHE",
        "_CLEAN_CMD_RX",
        "_CLEAN_NONALPHA_RX",
        "_COMMENT_GAP_RX",
        "_GRP_FLOW_TAGS",
        "_GRP_SCAN_CAP",
        "_LEAD_WS_RX",
        "_PROTECT_TYP",
        "_TRAIL_WS_RX",
        "_chunk_spec_cached",
        "_pick_cut",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 拆分前单件期模块属性面——stdlib 模块名与 texlate 顶层绑定也按名惰性解析，
# 读面（``from texlate.latex.segmenter._common import X``/属性访问两形）与拆分前逐名等价。
_STDLIB_MODS = ("re",)
_EXTRA_BINDINGS = {
    "NamedTuple": "typing",
    "Protocol": "typing",
    "bisect_left": "bisect",
    "dataclass": "dataclasses",
    "deque": "collections",
    "field": "dataclasses",
}
_TEXLATE_EXPORTS = {
    "ACCENT_CHARS": "texlate.latex.tables",
    "ArgSpec": "texlate.latex.model",
    "BEGIN_DOC_RX": "texlate.textutil",
    "BOUNDARY_NAMES": "texlate.latex.tables",
    "BOX_TAIL_NAMES": "texlate.latex.tables",
    "CHUNK_ARG_NAMES": "texlate.latex.tables",
    "CHUNK_MAX": "texlate.latex.tables",
    "CITE_NAMES": "texlate.latex.tables",
    "COND_RX": "texlate.latex.tables",
    "DEF_NAMES": "texlate.latex.tables",
    "DIMEN_TAIL_KIND": "texlate.latex.tables",
    "DOCCLASS_RX": "texlate.textutil",
    "ENV_MANDATORY_ARG": "texlate.latex.tables",
    "FONT_SWITCHES": "texlate.latex.tables",
    "INLINE_LITERAL_CMDS": "texlate.latex.tables",
    "INPUT_CMDS": "texlate.latex.tables",
    "INPUT_SCAN_CMDS": "texlate.latex.tables",
    "MATH_ENVS": "texlate.latex.tables",
    "PAIR_BLOCK_ALL": "texlate.latex.tables",
    "PH_RX": "texlate.latex.placeholder",
    "PROTECTED_ENVS": "texlate.latex.tables",
    "PROTECT_BLOCK_NAMES": "texlate.latex.tables",
    "PROTECT_NAMES": "texlate.latex.tables",
    "PhType": "texlate.latex.model",
    "REF_NAMES": "texlate.latex.tables",
    "Span": "texlate.latex.model",
    "TRANSPARENT_HEAD_SPEC": "texlate.latex.tables",
    "TRANSPARENT_NAMES": "texlate.latex.tables",
    "VERBATIM_ENVS": "texlate.latex.tables",
    "mask_tex": "texlate.textutil",
    "parse_argspec": "texlate.latex.macro_table",
}

# 字面列表——拆分前 ``import *`` 面（无 __all__ 期全量非下划线名）逐名保留；
# 私有名经 _LAZY 进属性读面不进 __all__。ruff F401 re-export 判定要静态
# __all__；``_export_drift`` 是三表同步闸。
__all__ = [
    "ACCENT_CHARS",
    "BEGIN_DOC_RX",
    "BOUNDARY_NAMES",
    "BOX_TAIL_NAMES",
    "CHUNK_ARG_NAMES",
    "CHUNK_MAX",
    "CITE_NAMES",
    "COND_RX",
    "DEF_NAMES",
    "DIMEN_TAIL_KIND",
    "DOCCLASS_RX",
    "ENV_MANDATORY_ARG",
    "FONT_SWITCHES",
    "INLINE_LITERAL_CMDS",
    "INPUT_CMDS",
    "INPUT_SCAN_CMDS",
    "MATH_ENVS",
    "PAIR_BLOCK_ALL",
    "PH_RX",
    "PROTECTED_ENVS",
    "PROTECT_BLOCK_NAMES",
    "PROTECT_NAMES",
    "REF_NAMES",
    "TRANSPARENT_HEAD_SPEC",
    "TRANSPARENT_NAMES",
    "TYPE_CHECKING",
    "VERBATIM_ENVS",
    "ArgSpec",
    "NamedTuple",
    "PhType",
    "Protocol",
    "Span",
    "TokenSource",
    "annotations",
    "bisect_left",
    "dataclass",
    "deque",
    "field",
    "mask_tex",
    "parse_argspec",
    "re",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性 / stdlib 绑定 / texlate 顶层名。"""
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
        | set(_EXTRA_BINDINGS)
        | set(_TEXLATE_EXPORTS)
    )


def _export_drift() -> list[str]:
    """``_LAZY``/``__all__``/绑定面三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。逐名 ``getattr`` 实解：叶子断链
    （``_LEAF_EXPORTS`` 配名叶子不提供）与幽灵条（解析不到任何叶子或绑
    定）在此曝，是首访 ``AttributeError`` 唯一的提前闸。审计实载全部
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
        except Exception as exc:  # noqa: BLE001 -- 审计兜全漂移，非首错即死
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and name not in _STDLIB_MODS
        and name not in _EXTRA_BINDINGS
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
