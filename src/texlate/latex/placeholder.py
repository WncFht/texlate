"""占位符方案（docs/07 §6）。

格式 ``[[TYPE_n]]``；``n`` 由单一 :class:`PlaceholderIssuer` 全局单调递增
（跨子扫描器共享——spike ``_ctr`` list-hack 的扶正）。

两个命名空间：``[[CHUNK_n]]``（可译，``chunks[]`` 索引）与 ``[[TYPE_n]]``
（保护，``ph_map``）——同语法不同表，reconstruct 统一按 DAG 展开。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.latex.model import PhType

PH_RX = re.compile(r"\[\[[A-Z_]+_\d+\]\]")  # 无分组：findall 直接出整 token
CHUNK_RX = re.compile(r"\[\[CHUNK_(\d+)\]\]")


class PlaceholderIssuer:
    r"""单一单调计数器（编号冲突教训的扶正）。

    >>> issuer = PlaceholderIssuer()
    >>> m = {}
    >>> issuer.new(PhType.CITE, "\\\\cite{x}", m)
    '[[CITE_1]]'
    """

    __slots__ = ("_n",)

    def __init__(self) -> None:
        """计数器归零。"""
        self._n = 0

    def new(self, typ: PhType, body: str, ph_map: dict[str, str]) -> str:
        """签发 ``[[TYPE_n]]`` 并把本体登记进 ``ph_map``。"""
        self._n += 1
        ph = f"[[{typ.name}_{self._n}]]"
        ph_map[ph] = body
        return ph
