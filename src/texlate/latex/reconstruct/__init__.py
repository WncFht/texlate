r"""splice 重建 + DAG 递归展开 + validate（docs/spec/latex-pipeline.md）。

- **identity**：``translations=None`` → 平铺 pieces + ph 体逐字 → 逐字节 = 原文。
- O(总规模)+memo；相对 spike ``str.replace`` 不动点语义等价
  （同一替换表迭代至不动点 ≡ DAG 递归展开；构造上无环，assert 兜底）。
- **译文侧契约**：译文必须保留 ``chunk.placeholders`` 全列；
  :func:`validate_translation` 校验缺失/幻觉占位符（由 translate 层消费）。
- ``cjk_glue_fix``（``\\cmd这是`` → 插空格）是 post-reconstruct 全局修正一步，
  只在有译文时启用（identity 路径保持逐字节）。
- ``cjk_punct_close_guard``（CJK 标点 + ``\end{``/``\)``/``\]`` → 标点后插
  ``{}``）同位同门——xeCJK CheckFullRight 前瞻断链护栏。
- ``seg_join`` 接缝守卫（``\cs`` 尾 + 字母头 → 接缝插空格）在 expand/平铺
  两级生效，同样只随译文启用——latin 版不能用平铺正则（``\itemsep``/
  ``\parindent``/``\partial``/用户 camelCase 宏全是前缀撞名，语料万级
  存量），只能打接缝（cs token 永不跨段，``\cs|letter`` 接缝必是分隔被吞）。
- ``unicode_math_fix``（译文里游离的 ``β``/``∂`` → ``$\beta$``/``$\partial$``）
  是 pre-splice 的逐条译文修正——文本字体没有这些字形，缺字判据见 judge。

C3 拆分：实现体按域拆进 ``latex/`` 下 ``reconstruct_<域>.py`` 五兄弟叶，
本文件是 PEP 562 惰性门面（同 ``fixloop/builtins/__init__`` 形制）——
平名经 ``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``reconstruct.X`` 公共面与 ``from  import X`` 测试面不变。叶子私名
同样经映射回引（``_Expander``/``_mark_open`` 等原门面名面全守恒），
新代码请直引叶子模块。monkeypatch 锚点注意：setattr 只遮蔽门面不改
叶子——patch 须指向叶子模块同名。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.latex.reconstruct.core import _Expander, reconstruct
    from texlate.latex.reconstruct.emit import (
        _C1_CTRL_RX,
        _ENV_TOKEN_COUNT_RX,
        _SEG_HIT_MIN_CHARS,
        splice_emit_issues,
    )
    from texlate.latex.reconstruct.fix import (
        _CJK_PUNCT_CLOSE_RX,
        _CJK_PUNCT_RIGHT,
        _CJK_RX,
        _DBL_BRACE_ARG_RX,
        _LINESTART_CS_RX,
        _TEXT_TO_MATH,
        _TRANS_PH_RX,
        _UNICODE_MATH_RX,
        LATIN_ITEM_RX,
        PAR_RUN_RX,
        _insert_masked,
        _restore_linestarts,
        cjk_glue_fix,
        cjk_punct_close_guard,
        dblbrace_arg_fix,
        seg_join,
        translation_tokens,
        unicode_math_fix,
    )
    from texlate.latex.reconstruct.mark import (
        _ARG_TOK_RX,
        _BRACE_TOK_RX,
        _MARK_ALIGN_ENVS,
        _MARK_ARG_CS,
        _MARK_BEGIN_RX,
        _MARK_CLOSE,
        _MARK_CS_TAIL_RX,
        _MARK_ENV_ARG_RX,
        _MARK_MOVING_CTX,
        _MARK_NONTEXT_CS,
        _MARK_ROW_HEAD_RX,
        _MARK_ROW_TAIL_RX,
        _MARK_RULE_HEAD_RX,
        _MARK_RULE_TAIL_RX,
        _MARK_SKIP_CTX,
        _MARK_SOUL_CS,
        _MARK_SPECIAL_TAIL_RX,
        _PH_EDGE_HEAD_RX,
        _PH_EDGE_TAIL_RX,
        _SEQ_MARK_EMC_RX,
        SEQ_MARK_BASE,
        SEQ_MARK_OPEN_RX,
        SEQ_MARK_RX,
        SEQ_MARK_TAG,
        _brace_events,
        _in_align_preamble,
        _mark_open,
        _open_cs,
        _pending_arg,
        _piece_site_map,
        _split_arg_head,
        _wrap_seq_mark,
        in_env_args,
        seq_mark_issues,
        strip_seq_marks,
    )
    from texlate.latex.reconstruct.validate import (
        TranslationVerdict,
        validate_result,
        validate_translation,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "core": (
        "_Expander",
        "reconstruct",
    ),
    "emit": (
        "_C1_CTRL_RX",
        "_ENV_TOKEN_COUNT_RX",
        "_SEG_HIT_MIN_CHARS",
        "splice_emit_issues",
    ),
    "fix": (
        "_CJK_PUNCT_CLOSE_RX",
        "_CJK_PUNCT_RIGHT",
        "_CJK_RX",
        "_DBL_BRACE_ARG_RX",
        "_LINESTART_CS_RX",
        "_TEXT_TO_MATH",
        "_TRANS_PH_RX",
        "_UNICODE_MATH_RX",
        "LATIN_ITEM_RX",
        "PAR_RUN_RX",
        "_insert_masked",
        "_restore_linestarts",
        "cjk_glue_fix",
        "cjk_punct_close_guard",
        "dblbrace_arg_fix",
        "seg_join",
        "translation_tokens",
        "unicode_math_fix",
    ),
    "mark": (
        "_ARG_TOK_RX",
        "_BRACE_TOK_RX",
        "_MARK_ALIGN_ENVS",
        "_MARK_ARG_CS",
        "_MARK_BEGIN_RX",
        "_MARK_CLOSE",
        "_MARK_CS_TAIL_RX",
        "_MARK_ENV_ARG_RX",
        "_MARK_MOVING_CTX",
        "_MARK_NONTEXT_CS",
        "_MARK_ROW_HEAD_RX",
        "_MARK_ROW_TAIL_RX",
        "_MARK_RULE_HEAD_RX",
        "_MARK_RULE_TAIL_RX",
        "_MARK_SKIP_CTX",
        "_MARK_SOUL_CS",
        "_MARK_SPECIAL_TAIL_RX",
        "_PH_EDGE_HEAD_RX",
        "_PH_EDGE_TAIL_RX",
        "_SEQ_MARK_EMC_RX",
        "SEQ_MARK_BASE",
        "SEQ_MARK_OPEN_RX",
        "SEQ_MARK_RX",
        "SEQ_MARK_TAG",
        "_brace_events",
        "_in_align_preamble",
        "_mark_open",
        "_open_cs",
        "_pending_arg",
        "_piece_site_map",
        "_split_arg_head",
        "_wrap_seq_mark",
        "in_env_args",
        "seq_mark_issues",
        "strip_seq_marks",
    ),
    "validate": (
        "TranslationVerdict",
        "validate_result",
        "validate_translation",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__；键集 = _LAZY 键集，
# 新增导出两侧同步（``_export_drift`` 是三表同步闸）。
__all__ = [
    "LATIN_ITEM_RX",
    "PAR_RUN_RX",
    "SEQ_MARK_BASE",
    "SEQ_MARK_OPEN_RX",
    "SEQ_MARK_RX",
    "SEQ_MARK_TAG",
    "_ARG_TOK_RX",
    "_BRACE_TOK_RX",
    "_C1_CTRL_RX",
    "_CJK_PUNCT_CLOSE_RX",
    "_CJK_PUNCT_RIGHT",
    "_CJK_RX",
    "_DBL_BRACE_ARG_RX",
    "_ENV_TOKEN_COUNT_RX",
    "_LINESTART_CS_RX",
    "_MARK_ALIGN_ENVS",
    "_MARK_ARG_CS",
    "_MARK_BEGIN_RX",
    "_MARK_CLOSE",
    "_MARK_CS_TAIL_RX",
    "_MARK_ENV_ARG_RX",
    "_MARK_MOVING_CTX",
    "_MARK_NONTEXT_CS",
    "_MARK_ROW_HEAD_RX",
    "_MARK_ROW_TAIL_RX",
    "_MARK_RULE_HEAD_RX",
    "_MARK_RULE_TAIL_RX",
    "_MARK_SKIP_CTX",
    "_MARK_SOUL_CS",
    "_MARK_SPECIAL_TAIL_RX",
    "_PH_EDGE_HEAD_RX",
    "_PH_EDGE_TAIL_RX",
    "_SEG_HIT_MIN_CHARS",
    "_SEQ_MARK_EMC_RX",
    "_TEXT_TO_MATH",
    "_TRANS_PH_RX",
    "_UNICODE_MATH_RX",
    "TranslationVerdict",
    "_Expander",
    "_brace_events",
    "_in_align_preamble",
    "_insert_masked",
    "_mark_open",
    "_open_cs",
    "_pending_arg",
    "_piece_site_map",
    "_restore_linestarts",
    "_split_arg_head",
    "_wrap_seq_mark",
    "cjk_glue_fix",
    "cjk_punct_close_guard",
    "dblbrace_arg_fix",
    "in_env_args",
    "reconstruct",
    "seg_join",
    "seq_mark_issues",
    "splice_emit_issues",
    "strip_seq_marks",
    "translation_tokens",
    "unicode_math_fix",
    "validate_result",
    "validate_translation",
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

    - ``_LAZY`` 键全进 ``__all__``；
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链（``_LEAF_EXPORTS``
      配名叶子不提供）与幽灵条在此曝，是首访 ``AttributeError`` 唯一
      的提前闸；
    - 本地公共名（本模块定义的函数/类/dict）全进 ``__all__``。

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
