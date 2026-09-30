r"""compile.normalize_blocks — 兼容前导块与早期定义注入叶 (compile.normalize 域缝叶)。

文件顶前置的 XeTeX/tectonic 兼容块（PIXEL/XETEX/TECTONIC_FONT）+
``\documentclass`` 缝后注入的 preamble 消费仿真定义（``XETEX_EARLY_DEFS``
经 ``_splice_early_defs`` 逐缝注入）。
"""

from __future__ import annotations

from texlate.textutil import SUBDOC_CHILD_RX, iter_depth0

from ._docseams import _splice_after_seams, find_docclass_ends
from .mask import visible_tex

# ---------------------------------------------------------------- 兼容前导块
# 注入缝三档（docs/spec/compile.md）：包钩/类选项/字体 shim → 文件顶前置
# （``\documentclass`` 之前——``\PassOptionsTo*`` 必须抢在类装载前）；
# preamble 消费的仿真定义 → ``\documentclass`` 缝后（XETEX_EARLY_DEFS，
# 经 inject 缝原语）；bd 锚块（CJK_MATH_FALLBACK 等）→ ``\begin{document}``
# 之前，归 inject/layout。

PIXEL_COMPATIBILITY = r"""% texlate: pdfTeX pixel dimensions for XeTeX
\ifdefined\pdfpxdimen\else\newdimen\pdfpxdimen\pdfpxdimen=65782sp\fi
"""

XETEX_COMPATIBILITY = r"""% texlate: native XeTeX font and PDF-driver capabilities
\AddToHook{package/microtype/after}{%
\DeclareMicrotypeSet{texlate-native}{encoding={TU,EU1,EU2}}%
\UseMicrotypeSet[protrusion]{texlate-native}%
}
% breakurl already has a native-PDF branch; limit its PDF-mode override to loading.
\AddToHook{package/breakurl/before}{%
\RequirePackage{xkeyval,ifpdf}%
\let\TeXlateSavedIfpdf\ifpdf\let\ifpdf\iftrue
}
\AddToHook{package/breakurl/after}{\let\ifpdf\TeXlateSavedIfpdf}
% This class's optional arXiv check assumes every non-pdfTeX engine writes DVI.
\PassOptionsToClass{nopdfoutputerror,allowfontchangeintitle}{quantumarticle}
% Embedded PostScript can silently disappear with restricted XeTeX drivers.
% Record actual drawing operations; merely loading an unused package is harmless.
\AddToHook{package/pstricks/after}{%
\ifcsname pst@object\endcsname
\expandafter\let\expandafter\TeXlatePstObject\csname pst@object\endcsname
\expandafter\def\csname pst@object\endcsname#1{%
\typeout{TeXlate-PostScript-object: #1}\TeXlatePstObject{#1}}%
\fi
}
"""

#: preamble 消费的仿真定义——用户 preamble 代码会调用的 cs，落
#: ``\documentclass`` 缝后逐缝注入（``_splice_early_defs``），抢在全部
#: 用户 preamble 代码之前。
XETEX_EARLY_DEFS = r"""% texlate: emulation defs consumed by user preamble code
% \DeclareUnicodeCharacter is pdfTeX/inputenc-only and undefined under XeTeX,
% but e-print preambles still call it (2501.14787). Emulate via the lccode
% idiom: make the code point an active char expanding to the replacement.
\providecommand{\DeclareUnicodeCharacter}[2]{%
\begingroup\lccode`\~="#1\relax
\lowercase{\endgroup\catcode`~\active\protected\def~}{#2}}
"""

TECTONIC_FONT_COMPATIBILITY = r"""% texlate: vector double-stroke fonts; Tectonic cannot generate PK fonts
\AddToHook{package/bbm/after}{%
\SetMathAlphabet{\mathbbm}{normal}{U}{dsrom}{m}{n}%
\SetMathAlphabet{\mathbbm}{bold}{U}{dsrom}{m}{n}%
\SetMathAlphabet{\mathbbmss}{normal}{U}{dsss}{m}{n}%
\SetMathAlphabet{\mathbbmss}{bold}{U}{dsss}{m}{n}%
\SetMathAlphabet{\mathbbmtt}{normal}{U}{dsrom}{m}{n}%
\SetMathAlphabet{\mathbbmtt}{bold}{U}{dsrom}{m}{n}%
}
"""


def _splice_early_defs(text: str) -> str:
    r"""``\documentclass`` 缝后逐缝注入 preamble 消费的仿真定义块。

    刻意不挂 preamble_ok/bd 闸：bd 藏进 ``\input`` 子件时 main 零 bd
    （2609.19376），旧闸把定义整段关在 main 外、落进子件顶=组合
    preamble 中段，``\input`` 点之前的调用仍 undefined_cs。
    ``\providecommand`` 幂等，多缝逐点重放安全；``\documentstyle``
    缝滤除（209 无该 cs）。subdoc 子档（subfiles/standalone 类）同
    preamble_ok 口径放行——其 docclass→bd 区段在母档 ``\subfile``/
    ``\includestandalone`` 语境被整体吞没，preamble 调用永不执行。
    """
    if XETEX_EARLY_DEFS in text:
        return text
    if any(iter_depth0(SUBDOC_CHILD_RX, visible_tex(text))):
        return text
    seams = [hit for hit in find_docclass_ends(text) if hit[2] == "documentclass"]
    return _splice_after_seams(text, seams, XETEX_EARLY_DEFS) if seams else text
