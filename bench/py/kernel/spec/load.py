"""spec 装载叶 —— load_spec: exec spec .py 取 ``spec`` 对象 +
compile_checks 闸 (§4)。

原 ``kernel.spec`` 顶层「loading」段逐字保留。门面回引名单见
``kernel.spec._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

from kernel.spec.base import Spec, SpecError
from kernel.spec.checks import compile_checks


def load_spec(path) -> Spec:
    """Exec a spec .py file and return its ``spec`` object.

    The file must define a module-level ``spec`` (a Spec). compile_checks
    run here — a spec that fails authoring never reaches the kernel.
    """
    p = Path(path)
    if not p.is_file():
        raise SpecError([f"spec file not found: {p}"])
    name = f"_texlate_spec_{hashlib.sha256(str(p).encode()).hexdigest()[:12]}"
    mod = importlib.util.spec_from_file_location(name, p)
    if mod is None or mod.loader is None:
        raise SpecError([f"cannot load spec file: {p}"])
    module = importlib.util.module_from_spec(mod)
    sys.modules[name] = module
    try:
        mod.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    spec = getattr(module, "spec", None)
    if spec is None:
        # tolerate single-Spec files that named it differently
        cands = [v for v in vars(module).values() if isinstance(v, Spec)]
        spec = cands[0] if len(cands) == 1 else None
    if not isinstance(spec, Spec):
        raise SpecError([f"{p} exports no `spec` Spec object"])
    spec._path = str(p)
    problems = compile_checks(spec)
    if problems:
        raise SpecError(problems)
    return spec
