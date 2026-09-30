"""kernel._kernel_frame — 规划面机件叶 (kernel.kernel 拆分叶).

run/plan 两管线共享的预编排机件:

- ``_resolve_spec``   — Spec|path -> spec + compile_checks 编译闸
- ``_coerce_params``  — stringly 参数闸: defaults <- supplied 经 Param
                        类型规整, unknown/missing required 在副作用前拒
- ``_spec_env``       — env probe 记名不记值 (只记 tool 身份/路径)
- ``_enumerate_cells``— items × stages -> plan cells + canon drop 问题表
                        (eval spec 免 registry 闸, G1 select 先裁后 canon)
- ``_sel_hit``        --sel 选择子 (逗号 k=v 谓词 / 裸 id|idc / '*')

无状态纯函数; 门面回引名单见 ``kernel.kernel._LEAF_EXPORTS``。
monkeypatch 锚点: setattr patch 须指本叶, 指门面无效。
"""

from __future__ import annotations

import shutil
import sys

from kernel import idnorm
from kernel import spec as specmod
from kernel.spec import Spec, SpecError, compile_checks, load_spec


def _resolve_spec(spec_or_path):
    if isinstance(spec_or_path, Spec):
        spec = spec_or_path
    elif isinstance(spec_or_path, dict):
        raise SpecError(["dict is not a Spec — author Spec(...) objects"])
    else:
        spec = load_spec(spec_or_path)
    problems = compile_checks(spec)
    if problems:
        raise SpecError(problems)
    return spec


def _coerce_params(spec: Spec, params) -> dict:
    """Run params: defaults <- supplied, coerced through Param types.
    Unknown keys and missing requireds are refused (§4 — no stringly)."""
    params = dict(params or {})
    unknown = sorted(set(params) - set(spec.params))
    if unknown:
        raise SpecError(
            [(f"unknown run params {unknown} — spec declares {sorted(spec.params)}")]
        )
    out = {}
    for name, p in spec.params.items():
        raw = params.get(name, p.default)
        if raw is None:
            if p.required:
                raise SpecError([f"required param {name!r} missing"])
            out[name] = None
            continue
        out[name] = p.coerce(name, raw)
    return out


def _spec_env(spec: Spec) -> dict:
    """Probe-name -> resolution. 记名不记值: only tool identities/paths,
    never secrets."""
    env = {"python": sys.version.split()[0]}
    for probe in spec.env_probes:
        if probe == "python":
            continue
        env[str(probe)] = shutil.which(str(probe)) or None
    return env


def _enumerate_cells(spec: Spec, registry, resolved: dict):
    """Items x stages -> plan cell dicts. Returns (cells, problems) —
    problems are ids that failed canon (dropped, noted later)."""
    stage_order = specmod.topo_stages(spec) or list(spec.stages)
    cells: list[dict] = []
    problems: list[str] = []
    for item in spec.iter_items():
        # G1 plan-filter: spec.select(item, resolved_params) narrows the
        # frame per-run BEFORE canon — rejected items never pay a registry
        # lookup, and raw-id selectors (--ids) match the author's spelling.
        if spec.select is not None and not spec.select(item, resolved):
            continue
        raw = item.get("id")
        if spec.eval:
            idc = str(raw)
        else:
            res = idnorm.canon_id(str(raw), registry)
            if not res.ok or not res.idc:
                problems.append(f"item {raw!r}: canon {res.state} ({res.reason})")
                continue
            idc = res.idc
        wanted = item.get("stage")
        for st in stage_order:
            if wanted and st.name != wanted:
                continue
            cell = {
                "id": str(raw),
                "idc": idc,
                "arm": str(item.get("arm", "-")),
                "up": str(item.get("up", "-")),
                "variant": str(item.get("variant", "-")),
                "stage": st.name,
                "needs": [{"stage": s, "accept": sorted(a)} for s, a in st.needs],
                "fp_input": item.get("fp_input"),
                "params": dict(item.get("params") or {}),
                "run_params": dict(resolved),
                "layer": item.get("layer"),
            }
            # Extra item fields ride the cell verbatim (eval dedup_key
            # callables read them — e.g. cell["model"]/["rep"]). Framework
            # keys are already set above and never overwritten; "id"/"idc"/
            # "stage" are the canonical spellings, also already set.
            for k, v in item.items():
                if k not in cell:
                    cell[k] = v
            cells.append(cell)
    return cells, problems


def _sel_hit(sel, cell: dict) -> bool:
    """Selector match: comma-separated k=v predicates over
    {id,idc,arm,up,variant,stage}; bare tokens match id|idc. All must
    match; '*' matches everything. sel=None -> False (no hit claimed)."""
    if sel is None:
        return False
    s = str(sel).strip()
    if not s or s == "*":
        return True
    for raw_pred in s.split(","):
        pred = raw_pred.strip()
        if not pred:
            continue
        if "=" in pred:
            k, v = pred.split("=", 1)
            if str(cell.get(k.strip(), "")) != v.strip():
                return False
        elif pred not in (str(cell.get("id")), str(cell.get("idc"))):
            return False
    return True
