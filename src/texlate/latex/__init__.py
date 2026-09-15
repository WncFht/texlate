"""LaTeX 半解析管线：scanner / pieces / macros / flatten / splice（规格 docs/07）。

典型用法::

    from texlate.latex import parse_file, reconstruct

    res = parse_file("main.tex")            # 展平 + 半解析
    for c in res.chunks:                    # 可译段
        translations[c.id] = translate(c)
    out = reconstruct(res, translations)    # splice 回重建
"""

from texlate.latex.api import parse_file, parse_tex
from texlate.latex.flatten import flatten_inputs, strip_doc_shell
from texlate.latex.macro_table import MacroTable, parse_argspec
from texlate.latex.model import (
    ArgSpan,
    ArgSpec,
    Chunk,
    EnvEntry,
    MacroEntry,
    MacroKind,
    PhType,
    Piece,
    PieceKind,
    ScanMode,
    ScanResult,
    ScanState,
    ScanWarning,
    Span,
)
from texlate.latex.placeholder import CHUNK_RX, PH_RX, PlaceholderIssuer
from texlate.latex.reconstruct import (
    TranslationVerdict,
    cjk_glue_fix,
    reconstruct,
    validate_result,
    validate_translation,
)
from texlate.latex.scanner import Scanner

__all__ = [
    "CHUNK_RX",
    "PH_RX",
    "ArgSpan",
    "ArgSpec",
    "Chunk",
    "EnvEntry",
    "MacroEntry",
    "MacroKind",
    "MacroTable",
    "PhType",
    "Piece",
    "PieceKind",
    "PlaceholderIssuer",
    "ScanMode",
    "ScanResult",
    "ScanState",
    "ScanWarning",
    "Scanner",
    "Span",
    "TranslationVerdict",
    "cjk_glue_fix",
    "flatten_inputs",
    "parse_argspec",
    "parse_file",
    "parse_tex",
    "reconstruct",
    "strip_doc_shell",
    "validate_result",
    "validate_translation",
]
