"""ruleset._ruleset_family — ``_FAMILY_TOKENS`` 占位符展开 (C5 拆叶)。

yaml 模式串占位符 ``@pdftex_prims``/``@pstricks`` → 原语/签名族正则
交替——``_expand_family_tokens`` 递归展开 yaml 全树。
"""

from __future__ import annotations

from typing import Any

from texlate.compile.engine._route import PSTRICKS_SIG_ALTS
from texlate.compile.fixloop import builtins

#: yaml 模式串占位符 → 原语/签名族 (扩表免手同步: 1e0e5c8 手工
#: 13→75 交替即此债)。``@pdftex_prims``/``@pstricks`` 在任何字符串值里
#: 出现即展开成 ``(?:…)`` 非捕获交替——按长度降序排, 防短名前缀截长名。
#: ``@pstricks`` 单源在 compile/engine/_route.py ``PSTRICKS_SIG_ALTS``
#: (route 静态签名与规则条件同口径; 行锚 ``^[ \t]*`` 留在 yaml 侧外置,
#: token 不含锚, 嵌进遮盖视图/raw 源两用)。
_FAMILY_TOKENS: dict[str, frozenset[str] | tuple[str, ...]] = {
    "@pdftex_prims": builtins.PDFTEX_PRIMS,
    "@pstricks": PSTRICKS_SIG_ALTS,
}


def _expand_family_tokens(node: Any) -> Any:  # noqa: ANN401  # yaml 树天然 Any
    """递归展开 ``_FAMILY_TOKENS`` 占位符 → 正则交替片段 (yaml 全树)。"""
    if isinstance(node, str):
        for tok, fam in _FAMILY_TOKENS.items():
            if tok in node:
                alts = "|".join(sorted(fam, key=lambda s: (-len(s), s)))
                node = node.replace(tok, f"(?:{alts})")
        return node
    if isinstance(node, list):
        return [_expand_family_tokens(x) for x in node]
    if isinstance(node, dict):
        return {k: _expand_family_tokens(v) for k, v in node.items()}
    return node
