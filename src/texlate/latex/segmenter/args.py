r"""``latex/segmenter`` 子模块——god-class 机械拆分（行为零变）。

``Segmenter`` 参数读取/保护调用/各 handler/argspec 发射的 ``_Args``
mixin 实现体按域拆五兄弟叶（链式继承，``_Pending(_GrpScan)`` 同款）：
``args_read`` 拉取/回放契约 → ``args_protect`` 保护调用/keyval 尾参 →
``args_prose`` 散文参挖掘+子扫渲染 → ``args_chunk`` chunk-arg 族+argspec
分派 → ``args_handlers`` 各行 handler。本文件是组合位薄门面——
``from .args import _Args`` 消费面与 ``Segmenter`` mixin 链位不变。
"""

from .args_handlers import _ArgsHandlers


class _Args(_ArgsHandlers):
    """``_Args`` mixin 组合位——实现体分居五叶（链式继承，行为零变）。"""
