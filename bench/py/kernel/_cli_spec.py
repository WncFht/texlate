"""kernel._cli_spec — spec 创作辅助叶 (kernel.cli 拆分叶).

``bench spec list`` — 列 ``bench/py/specs/*.py`` (跳 ``_`` 前缀私有件):
每条给 kind (``kernel.spec.load_spec`` 可用时走真装载, 否则源码正则
``kind = '...'`` 兜底) 与首行 docstring (ast 解析, 永不执行 spec 文件)。

门面回引名单见 ``kernel.cli._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

from kernel._cli_common import EXIT_OK, _lazy, _specs_dir

if TYPE_CHECKING:
    from pathlib import Path


def _spec_doc(path: Path) -> str:
    """First docstring line via ast — never executes the spec file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return ""
    doc = ast.get_docstring(tree) or ""
    return doc.strip().splitlines()[0] if doc.strip() else ""


def _spec_kind(path: Path):
    """kind via kernel.spec.load_spec when available, else a source regex."""
    mod, _load_err = _lazy("spec")
    loader = getattr(mod, "load_spec", None) if mod is not None else None
    kind = None
    if loader is not None:
        try:
            kind = getattr(loader(str(path)), "kind", None)
        except Exception:
            kind = None
    if kind:
        return str(kind)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "?"
    m = re.search(r"kind\s*=\s*['\"]([^'\"]+)['\"]", text)
    return m.group(1) if m else "?"


def _cmd_spec_list(_args) -> int:
    sdir = _specs_dir()
    rows = []
    if sdir.is_dir():
        for f in sorted(sdir.glob("*.py")):
            if f.name.startswith("_"):
                continue
            rows.append((f.name, _spec_kind(f), _spec_doc(f)))
    print(f"specs: {sdir}")
    if not rows:
        print("  (none)")
        return EXIT_OK
    for name, kind, doc in rows:
        print(f"  {name:<24} kind={kind:<16} {doc}")
    return EXIT_OK
