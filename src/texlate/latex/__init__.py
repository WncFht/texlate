"""LaTeX 半解析管线：pieces / macros / flatten / splice（规格 docs/07）。

典型用法::

    from texlate.latex import parse_file, reconstruct

    res = parse_file("main.tex")            # 展平 + 半解析
    for c in res.chunks:                    # 可译段
        translations[c.id] = translate(c)
    out = reconstruct(res, translations)    # splice 回重建
"""

from texlate.latex.api import parse_file, parse_tex
from texlate.latex.flatten import flatten_inputs
from texlate.latex.reconstruct import (
    reconstruct,
    validate_result,
    validate_translation,
)

__all__ = [
    "flatten_inputs",
    "parse_file",
    "parse_tex",
    "reconstruct",
    "validate_result",
    "validate_translation",
]
