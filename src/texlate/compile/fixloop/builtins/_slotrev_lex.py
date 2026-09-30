r"""builtins._slotrev_lex — 机位实参词法件 (slotrev 拆分)。

``_ARG``/``_OPT*``/``_GAP``/``_NBC``/``_ARGNL``/``_BGM``/``_ARGB``/``_OPTB``
—— ``_SLOTREV_EXTRA_RXS`` 表与 ``_holder_rxs`` 动态行共用的正则片段
单源 (平衡组/跨行/空行截断口径)。
"""

from __future__ import annotations

__all__ = [
    "_ARG",
    "_ARGB",
    "_ARGNL",
    "_BGM",
    "_GAP",
    "_NBC",
    "_OPT",
    "_OPTB",
    "_OPTC",
]

#: 同命令相邻实参间空白 (跨行随意); 仅 envarg 尾随参用受限 _GAP。
_ARG = r"\{([^{}\n]*)\}"
_OPT = r"\[[^\]\n]*\]"  # opt 位只吃不捕 (非 revert 面)
_OPTC = r"\[([^\]\n]*)\]"  # opt 位捕获 (revert 面: 计数/包选项/label)
#: envarg 尾随参 gap: 同行空白 + 至多一个换行 —— 空行=\par 截断 arg
#: 扫描 (TeX 无 \long 参扫描语义), 防 ``\begin{env}`` 后散文 ``{word}``
#: 误收。
_GAP = r"[^\S\n]*(?:\n[^\S\n]*)?"
#: 平衡组扫描单元 —— 非 ``{}`` 字符且非空行首 ``\n``: 空行=\par 截断 arg
#: 扫描 (同 _GAP 口径), 单 ``\n`` 是合法 arg token (2609.19556
#: ``{General\ninstructions}`` 实证: src 参带字面换行 ``_ARG`` 捕不进 →
#: 计数分歧整 kind 跳)。``\r`` 入空白列护 CRLF 空行判。
_NBC = r"(?:(?!\n[ \t\r]*\n)[^{}])"
#: 换行容忍实参 —— envarg 尾随参跨行组; 嵌套 ``{}`` 仍不收 (由 _ARGB 面盖)。
_ARGNL = r"\{(" + _NBC + r"*)\}"
#: 平衡组体 (非捕获, ≤1 层嵌套) —— 中置参/组内嵌套单元。
_BGM = r"\{(?:" + _NBC + r"|\{" + _NBC + r"*\})*\}"
#: 平衡组实参 (捕获, ≤2 层嵌套 + 跨行) —— tcb kv 选项组
#: (``listing options={...}`` 值自带 ``{}`` 组)。
_ARGB = r"\{((?:" + _NBC + r"|" + _BGM + r")*)\}"
#: 平衡方括 opt 实参 (捕获, ≤1 层嵌套 + 跨行) —— tcolorbox ``[kv]`` 头。
_OPTB = r"\[((?:(?!\n[ \t\r]*\n)[^\[\]]|\[[^\[\]\n]*\])*)\]"
