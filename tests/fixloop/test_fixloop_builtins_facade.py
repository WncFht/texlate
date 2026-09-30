"""fixloop builtins 惰性门面的导出面对拍。

``builtins.py`` 三表：``__all__``（公共面）/ ``_LEAF_EXPORTS``（叶→名
映射，``__getattr__`` 惰性解析的唯一路由表）/ TYPE_CHECKING 块（类型
期同形 import——IDE/mypy 的影面）。``_export_drift`` 审计（见
``test_fixloop_export_drift.py``）盖运行时同步面；本文件补它不盖的
静态缝与独立直白断言：

- TYPE_CHECKING import 块 ↔ ``_LEAF_EXPORTS`` 逐叶逐名全等——影面漂移
  不炸运行时，但 IDE 跳转到错叶/旧名，重构时即误导源；
- ``__all__`` 逐名 ``getattr`` 可解（不借 ``_export_drift`` 机件——
  首访 ``AttributeError`` 的直接钉）；
- ``_LEAF_EXPORTS`` 配名叶子真提供（叶断链＝叶子改名没回改门面）；
- 注册表键集（``REWRITE_FNS``/``TRANSFORM_FNS``）全在 ``__all__``——
  rules.yaml ``function:`` 名经门面可达。
"""

import ast
import importlib
from pathlib import Path

from texlate.compile.fixloop import builtins


def _type_checking_map() -> dict[str, tuple[str, ...]]:
    """builtins.py ``TYPE_CHECKING`` 块 → {叶模块名: import 名集（排序）}。"""
    src = Path(builtins.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    out: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
        ):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.ImportFrom):
                continue
            leaf = (stmt.module or "").rsplit(".", 1)[-1]
            if not leaf.startswith("_builtins"):
                continue  # collections.abc.Callable 等非叶影件不比对
            out[leaf] = tuple(sorted(a.name for a in stmt.names))
    return out


def test_type_checking_block_matches_leaf_exports() -> None:
    """TYPE_CHECKING 影面 ↔ ``_LEAF_EXPORTS`` 逐叶逐名全等。"""
    expected = {
        leaf: tuple(sorted(names))
        for leaf, names in builtins._LEAF_EXPORTS.items()  # noqa: SLF001 -- 钉路由表
    }
    assert _type_checking_map() == expected


def test_all_entries_resolve() -> None:
    """``__all__`` 逐名 ``getattr`` 可解——惰性解析首访不炸。"""
    missing = [name for name in builtins.__all__ if not hasattr(builtins, name)]
    assert missing == []


def test_no_stale_leaf_names() -> None:
    """``_LEAF_EXPORTS`` 配名叶子真提供（叶断链在此曝）。"""
    stale = []
    for leaf, names in builtins._LEAF_EXPORTS.items():  # noqa: SLF001 -- 同上
        mod = importlib.import_module(f"texlate.compile.fixloop.{leaf}")
        stale += [f"{leaf}.{n}" for n in names if not hasattr(mod, n)]
    assert stale == []


def test_registry_keys_exported() -> None:
    """``REWRITE_FNS``/``TRANSFORM_FNS`` 键集 ⊆ ``__all__``——rules.yaml 名可达。"""
    unexported = [
        key
        for key in set(builtins.REWRITE_FNS) | set(builtins.TRANSFORM_FNS)
        if key not in builtins.__all__
    ]
    assert unexported == []
