"""占位符方案（docs/spec/latex-pipeline.md）。

格式 ``[[TYPE_n]]``；``n`` 由单一 :class:`PlaceholderIssuer` 全局单调递增
（跨子扫描器共享——spike ``_ctr`` list-hack 的扶正）。

两个命名空间：``[[CHUNK_n]]``（可译，``chunks[]`` 索引）与 ``[[TYPE_n]]``
（保护，``ph_map``）——同语法不同表，reconstruct 统一按 DAG 展开。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

# 签发侧词法单源下沉 textutil（arxiv 降级链同消费——跨层宿主件），本模块
# 保持 ``latex.placeholder.PH_RX`` canonical 转口面。
from texlate.textutil import PH_RX  # noqa: F401

if TYPE_CHECKING:
    from texlate.latex.model import PhType

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

    def new(
        self,
        typ: PhType,
        body: str,
        ph_map: dict[str, str],
        reserved: set[str] | None = None,
    ) -> str:
        """签发 ``[[TYPE_n]]`` 并把本体登记进 ``ph_map``。

        ``reserved`` = 源文自带的 ``[[X_n]]`` 形字面集合——签发撞上会让
        reconstruct 把原文当占位符展开（identity 破），遇撞顺延编号。
        """
        while True:
            self._n += 1
            ph = f"[[{typ.name}_{self._n}]]"
            if ph not in ph_map and (reserved is None or ph not in reserved):
                break
        ph_map[ph] = body
        return ph
