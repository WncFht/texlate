"""spec 指纹叶 —— code_sha/spec_hash/cell_fp + _iter_dep_files (§3.4 code
分量：spec 源字节 + code_deps 文件内容，非 repo sha)。

原 ``kernel.spec`` 顶层「hashing」段逐字保留——``_iter_dep_files`` 的
dir-dep rglob 序与 file-dep 路径语义是指纹面，一字不改。门面回引名单见
``kernel.spec._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from typing import TYPE_CHECKING

from kernel import events

if TYPE_CHECKING:
    from kernel.spec.base import Spec


def _iter_dep_files(dep) -> list[Path]:
    p = Path(dep)
    if p.is_file():
        return [p]
    if p.is_dir():
        return sorted(f for f in p.rglob("*") if f.is_file())
    return []


def code_sha(spec: Spec, path=None) -> str:
    """The §3.4 code component: spec source bytes (or stage fn sources when
    no file exists) + every code_deps file's content. NOT a repo sha —
    a dirty tree can never poison the fingerprint."""
    if spec._code_sha is not None and path is None:
        return spec._code_sha
    h = hashlib.sha256()
    p = Path(path) if path is not None else (Path(spec._path) if spec._path else None)
    if p is not None and p.is_file():
        h.update(b"spec-file\x00")
        h.update(p.read_bytes())
    else:
        for st in spec.stages:
            try:
                src = inspect.getsource(st.fn)
            except (OSError, TypeError):
                src = repr(st.fn)
            h.update(b"fn\x00")
            h.update(st.name.encode("utf-8"))
            h.update(src.encode("utf-8", "replace"))
    for dep in spec.code_deps:
        for f in _iter_dep_files(dep):
            h.update(b"dep\x00")
            h.update(str(f).encode("utf-8"))
            h.update(f.read_bytes())
    out = h.hexdigest()
    if path is None:
        spec._code_sha = out
    return out


def spec_hash(spec: Spec, path=None) -> str:
    """Run-registration hash: code component + the serialized spec dict.
    spec_hash feeds run_registered/invocations, never the run identity
    (R15) — but it pins exactly what definition produced this run."""
    payload = {
        "code": code_sha(spec, path),
        "spec": spec.to_dict(),
    }
    blob = events.dumps(payload).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def cell_fp(spec: Spec, cell: dict) -> str:
    """Per-cell fingerprint (§3.4):
    sha256(code component, fp_input, cell-level effective fp params).

    fp never enters done decisions — it only marks staleness. fp_input is
    the upstream fp chain (or manifest-supplied input hash); params carry
    only fp-effective cell params (selector knobs structurally excluded).
    """
    merged = dict(cell.get("run_params") or {})
    merged.update(cell.get("params") or {})
    fp_params = {
        k: v
        for k, v in sorted(merged.items())
        if k in spec.params and spec.params[k].fp_effective(k)
    }
    payload = {
        "code": code_sha(spec),
        "input": cell.get("fp_input"),
        "params": fp_params,
    }
    blob = events.dumps(payload).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
