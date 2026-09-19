r"""cite/bib 键面词法叶——``\cite`` 族/``\bibitem``/aux 陈旧键的键表抽取单源。

跨层共享件（architecture-review-2026-09-19 C3 归位预置）：``CITE_FAMILY_RE``
原居 ``fixloop/_builtins_bib.py`` 私有表，compile ``judge`` 与 fixloop
``_builtins_slotrev`` 私有名点名借调（分层倒置——compile 层消费 fixloop
私名）。键表是文本词法知识，归 textutil 底叶；旧私有名面待消费 lane
解冻后并指本叶（``_builtins_bib``/``judge``/``_builtins_slotrev``）。
"""

import re

__all__ = ["AUX_CITEKEY_RE", "BIBITEM_KEY_RE", "CITE_FAMILY_RE"]

#: ``\cite`` 族命令（\cite/\citet/\citep/\nocite/\citeauthor…）可选参后键表组。
CITE_FAMILY_RE = re.compile(
    r"\\[a-zA-Z@]*cite[a-zA-Z@]*\*?\s*(?:\[[^\]\n]*\]\s*)*\{([^}]*)\}"
)
#: ``\bibitem[<opt>]{key}`` —— .bbl 键定义点。
BIBITEM_KEY_RE = re.compile(r"\\bibitem\s*(?:\[[^\]]*\]\s*)?\{([^}]*)\}")
#: .aux 残留 ``\bibcite{key}{..}``/``\citation{keys}`` —— 陈旧键同源改写。
AUX_CITEKEY_RE = re.compile(r"\\(?:bibcite|citation)\s*\{([^}]*)\}")
