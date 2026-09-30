"""占位符方案（docs/spec/latex-pipeline.md）。

格式 ``[[TYPE_n]]``；``n`` 由单一 :class:`PlaceholderIssuer` 全局单调递增
（跨子扫描器共享——原型 ``_ctr`` list-hack 的扶正）。

两个命名空间：``[[CHUNK_n]]``（可译，``chunks[]`` 索引）与 ``[[TYPE_n]]``
（保护，``ph_map``）——同语法不同表，reconstruct 统一按 DAG 展开。
"""

from __future__ import annotations

import re

# 签发侧词法/签发器单源下沉 textutil（arxiv 降级链同消费——跨层宿主件），
# 本模块保持 ``latex.placeholder.PH_RX``/``PlaceholderIssuer`` canonical 面。
# model 是零反向依赖数据层（eager 仅 chars），placeholder→model 单向无环。
from texlate.latex.model import PhType
from texlate.textutil import PH_RX, PhIssuer  # noqa: F401

CHUNK_RX = re.compile(r"\[\[CHUNK_(\d+)\]\]")


class PlaceholderIssuer(PhIssuer):
    r"""单一单调计数器（编号冲突教训的扶正）——``PhType`` 强类型面。

    签发计数/避让逻辑单源在 :class:`texlate.textutil.PhIssuer`；本类只把
    ``typ`` 接成 ``PhType`` 枚举（裸名 ``str`` 亦兼容——枚举外 TYPE 经
    textutil 面直签）。

    >>> issuer = PlaceholderIssuer()
    >>> m = {}
    >>> issuer.new(PhType.CITE, "\\\\cite{x}", m)
    '[[CITE_1]]'
    """

    def new(
        self,
        typ: PhType | str,
        body: str,
        ph_map: dict[str, str],
        reserved: set[str] | frozenset[str] | None = None,
    ) -> str:
        """签发 ``[[TYPE_n]]`` 并把本体登记进 ``ph_map``。

        ``reserved`` = 源文自带的 ``[[X_n]]`` 形字面集合——签发撞上会让
        reconstruct 把原文当占位符展开（identity 破），遇撞顺延编号。
        """
        return super().new(
            typ.name if isinstance(typ, PhType) else typ, body, ph_map, reserved
        )
