r"""``latex/segmenter`` 共享表常量——scanner(v1)/segmenter(v2) 双臂单源。

原 ``scanner.py`` 与 ``segmenter/_common.py`` 的逐字双份常量收编于此：
可译性/保护口径双臂必须逐字一致——任何微差（如 ``+`` 折叠）会把临界
run 压过 ``CHUNK_MIN`` 阈值 → chunk 召回降（验收门不许）。
"""

from __future__ import annotations

import re

from texlate.latex.macro_table import (
    parse_argspec,
)
from texlate.latex.model import (
    ArgSpec,
    PhType,
)

_CLEAN_CMD_RX = re.compile(r"\\[a-zA-Z@]+\*?|\\[^a-zA-Z]")
_CLEAN_NONALPHA_RX = re.compile(r"[^a-zA-Z]")
_LEAD_WS_RX = re.compile(r"\s*")
_TRAIL_WS_RX = re.compile(r"\s*$")

# 尾字符必须真字母：孤 ``\@`` 是控制符号而非控制词尾——``\@x`` 的 ``@``
# 不吞后继空格，``_rappend``/``_seg_join`` 若按 ``\\[@]+`` 收它会补伪
# ``" "`` 破 identity（S1）；``\ds@list`` 族中位 ``@`` 不受影响。
# ``\Z`` 严格串尾（体尾 ``\n`` 已阻断 token 合并，放宽会收过头）。
_LETTER_TAIL_RX = re.compile(r"\\[a-zA-Z@]*[a-zA-Z]\Z")

_PROTECT_TYP = {
    "includegraphics": PhType.GRAPHICS,
    "url": PhType.URL,
    "path": PhType.URL,
    "label": PhType.LABEL,
    "bibliography": PhType.BIB,
    "bibliographystyle": PhType.BIB,
    "bibitem": PhType.BIB,
}

_CHUNK_SPEC_CACHE: dict[str, list[ArgSpec]] = {}


def _chunk_spec_cached(spec_str: str) -> list[ArgSpec]:
    """``CHUNK_ARG_SPEC`` 签名串 → ``list[ArgSpec]``（解析一次缓存）。"""
    if spec_str not in _CHUNK_SPEC_CACHE:
        _CHUNK_SPEC_CACHE[spec_str] = parse_argspec(spec_str)
    return _CHUNK_SPEC_CACHE[spec_str]
