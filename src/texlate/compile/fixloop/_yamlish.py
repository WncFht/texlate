"""re-export shim —— 实现已上提 ``texlate.compile._yamlish``（compile 层共享件）。

C3 地基归位：yaml 装载器有 compile 层非 fixloop 消费面（``loginfo``），
不再寄居依赖 compile 的 fixloop 子包。旧路径
``texlate.compile.fixloop._yamlish`` 名面转口守恒（``ruleset``/tests 等
旧 import 不动）；新代码一律直引 ``texlate.compile._yamlish``。
"""

from texlate.compile._yamlish import (  # noqa: F401
    YamlishError,
    _merge_into,
    _merge_maps,
    load_yaml,
    loads,
)
