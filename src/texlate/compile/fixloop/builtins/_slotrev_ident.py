r"""builtins._slotrev_ident — 机位 ident 白名单族 + ``_is_ident`` 谓词 (slotrev 拆分)。

严格/宽松/spec/kvnl 四档字符域 + per-kind 分派: ``colspec*`` 前缀族与
inferkv/primgap/pgtable 走 spec 域 (可打印 ASCII+``\t\n\r``), font 走
宽松 (含空格/'/()/&), tcbopt 走 kvnl (另须 ``=``,``#`` kv 形), 其余严格。
``_BROADCAST_KINDS``/``_NOTE_CAP`` 是 revert 引擎的配套常量。
"""

from __future__ import annotations

import re

__all__ = [
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
]

#: 严格 ident 白名单 —— 机位实参 (键/名/路径/kv 串/csv) 的字符域。
_IDENT_STRICT_RX = re.compile(r"[A-Za-z0-9@._/:+*!,=~-]+")
#: 宽松 ident —— 仅 font kind: 字体名含空格/'/()/& ("Times New Roman")。
_IDENT_LOOSE_RX = re.compile(r"[A-Za-z0-9@._/:+*!,=~ '()&-]+")
_IDENT_LOOSE_KINDS = frozenset({"font"})
#: spec ident —— 列 spec/dimen/数据表参的字符域: 可打印 ASCII +
#: ``\t\n\r`` (| 空格 @ < > ! * 反斜杠换行全收; {} 由 ``_ARGB``
#: 平衡组结构上承载)。spec 位自带机位断言，不复用严格白名单
#: (1502.01845 实证：真 spec 恒被它拒); 空白容忍为跨行 spec
#: (2609.20179 xltabular ``>{...}`` 嵌组多行参) 与 pgf 内联数
#: 值表 (2609.19828) 所需 —— ``_ARGB`` 捕获可含 ``\n\t``。
_IDENT_SPEC_RX = re.compile(r"[\t\n\r -~]+")
#: spec 系 kind 前缀 —— colspec/colspec_mc/colspec_nt/colspec_holder:*。
_IDENT_SPEC_PREFIX = "colspec"
#: spec 同域 (可打印 ASCII+ 空白) 的散 kind —— inferkv: opt kv 值含 cs 调用
#: (``\rlabel{Rec}``) 与空格，严格/宽松 ident 均拒; 该位恒为
#: mathpartir kv 键表机位，CJK 即译污。primgap: 原语 pre-``{`` gap
#: 含空格/反斜杠 (``to .55em``/``\hbox to .55em``/``spread 2pt``)。
#: pgtable: pgfplots 数据参位 (内联表/csname/文件名/kv 全机器引用，
#: CJK 即译污) —— 纯数值表无 ``=``,``/``#``, kvnl 形断言会拒收，
#: 故用无门控 spec 域 (2609.19828 实证，勿并入 _IDENT_KVNL_KINDS)。
_IDENT_SPEC_KINDS = frozenset({"inferkv", "primgap", "pgtable"})
#: kvnl ident —— tcb kv 选项组字符域：可打印 ASCII + ``\t\n\r`` (跨行
#: kv 串含嵌组/``#n`` 形参); 须同时含 ``=``/``,``/``#`` kv 形，防
#: ``\begin{tcolorbox}`` 后散文 ``{multi\nline prose}`` 组误收 —
#: kvnl 白名单放得太宽，纯散文 ASCII 组也能 fullmatch, 靠 kv 形断言
#: 兜底 (错位 revert 比不复原更糟; ``{listing only}`` 裸键站宁可漏)。
_IDENT_KVNL_RX = re.compile(r"[\t\n\r -~]+")
_KVNL_SHAPE_RX = re.compile(r"[=,#]")
_IDENT_KVNL_KINDS = frozenset({"tcbopt"})

#: unique-src 广播适用 kind —— 计数分歧时若 src 侧该 kind 全部 gap 值
#: 唯一且过 ident, 广播至 zh 侧全部含 CJK gap 站 (宏展开把单一 def 站
#: 机位倍增到调用站：2609.20633 ``\tocdots`` def 1 站 ``\hbox to .55em``
#: vs zh ``\leaders\hbox`` 字面量调用站 ×14 实证)。仅 gap 恒为 TeX
#: keyword/dimen 机料的 primgap 启用 —— 其余 kind 计数分歧仍整跳
#: (错位 revert 比不复原更糟); src 多值/空集 → 同样整跳。
_BROADCAST_KINDS = frozenset({"primgap"})

#: note 面站点/分歧条目封顶 (与 judge._MACHINE_SLOT_MAX 同量级)。
_NOTE_CAP = 20


def _is_ident(arg: str, kind: str) -> bool:
    r"""机位标识符谓词。

    font 类用宽松名单 (字体名含空格), colspec 系与 inferkv/
    primgap/pgtable 用可打印 ASCII+``\t\n\r`` (spec/dimen/数据
    表形), tcbopt 用 kvnl (可打印 ASCII+空白 ∧ kv 形), 其余严格。
    """
    if kind in _IDENT_KVNL_KINDS:
        return (
            _IDENT_KVNL_RX.fullmatch(arg) is not None
            and _KVNL_SHAPE_RX.search(arg) is not None
        )
    if kind.startswith(_IDENT_SPEC_PREFIX) or kind in _IDENT_SPEC_KINDS:
        return _IDENT_SPEC_RX.fullmatch(arg) is not None
    rx = _IDENT_LOOSE_RX if kind in _IDENT_LOOSE_KINDS else _IDENT_STRICT_RX
    return rx.fullmatch(arg) is not None
