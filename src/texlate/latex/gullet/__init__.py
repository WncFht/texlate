r"""Gullet：回压式不动点展开（plasTeX ``TeX.__iter__`` TeX.py:281-340 的移植）。

宏展开的**唯一**发生地：拉取 Mouth 原始 token → 命中宏表/原语则按预编译
spec 读参 → 代入 → 推回流前端（不动点，不 return）。移植位逐条对
``docs/research/latex/expansion-design.md`` §12 表；行为规格 docs/07 §8。

与 plasTeX 的刻意分歧（规格内留档项）：

- ``\def`` 参数文本**定义时**编译为 ``spec``（§5.2）——plasTeX 每次调用重走
  参数文本（``Definition.invoke __init__.py:1177`` 起）；语义等价，省每调用解析。
- 定界参数支持**多 token** 定界序列（``#1 abc`` 的 ``abc`` 整体是 delim）；
  plasTeX 只逐单 token 匹配（``__init__.py:1214``）——多 token 更贴 TeX。
- ``\if`` 两档（§8.6）：可求值 → ``process_if`` 只推回选中支；不可求值 →
  条件按语法消费 + ``\ifX`` 界标 token 直交分段器，**两分支都进**（召回优先）。
  ``\ifhmode/\ifvmode`` 常量取 plasTeX 真值 True/False（``tables.py``
  ``IF_CONST`` 已同值修正，v1 scanner 消费它）。
- 参数不匹配 → ``raise ArgMismatch`` + 全部已读 token 回吐（§3.5）；
  plasTeX 只 log.info 然后 break 继续（``__init__.py:1226``）——"继续"会
  默吞参数字节，对 splice 模型更危险。
- 三级限制（plasTeX 无任何限制）：``gen>MAX_GEN`` 不再展开 / ``steps>BUDGET``
  全停 / ``inputs>MAX_INPUTS`` 拒压栈。
"""

from __future__ import annotations

# ------------------------------------------------------------------ 兼容面
# 旧单文件模块属性面的在役子集：``BUDGET``（core._can_expand 经 ``_g.BUDGET``
# 取包属性——tests monkeypatch 面）、``export_flat_macros``（scanner v1 臂
# 消费）、``_tok_eq``（bench gullet_bench 消费）。其余泄漏导入名零消费
# 已修剪；``__all__`` 即公共面。
from texlate.latex.tables import (
    BUDGET as BUDGET,
)

from .args import (
    _Args,
)
from .classify import (
    _Classify,
)
from .cond import (
    _Cond,
)
from .core import (
    _Core,
)
from .decls import (
    _Decls,
)
from .defcmd import (
    _DefCmd,
)
from .entries import (
    Alias,
    Arg,
    ArgMismatch,
    EnvDef,
    IfCond,
    IfSetter,
    MacroDef,
    ScopeMacroTable,
)
from .entries import (
    export_flat_macros as export_flat_macros,
)
from .expand import (
    _Expand,
)
from .input import (
    _Input,
)
from .tokutil import (
    _tok_eq as _tok_eq,
)
from .tokutil import (
    expand_def,
)

__all__ = [
    "Alias",
    "Arg",
    "ArgMismatch",
    "EnvDef",
    "Gullet",
    "IfCond",
    "IfSetter",
    "MacroDef",
    "ScopeMacroTable",
    "expand_def",
]


class Gullet(_Core, _Args, _DefCmd, _Decls, _Input, _Expand, _Cond, _Classify):
    r"""回压式不动点展开器（``TeX.__iter__`` 移植）。

    用法：``Gullet(tex, root_dir=dir)`` 或 ``Gullet()`` + ``push_source``；
    ``next_expanded()`` 逐枚取展开后 token 直到 ``None``。
    """
