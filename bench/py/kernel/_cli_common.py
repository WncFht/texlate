"""kernel._cli_common — bench CLI 共享机件叶 (kernel.cli 拆分叶).

所有动词组共用的底座:

- ``EXIT_OK``/``EXIT_FAIL``/``EXIT_REFUSED`` — 退出码词表
  (0 ok · 1 命令跑但报败 · 2 refused/unavailable/未实现)
- ``_err``/``_lazy`` — stderr 行 + kernel 兄弟模块惰性 import
  (import 失败报出来, 不隐藏)
- ``_specs_dir``/``_shim_path``/``_resolve_spec`` — spec 文件解析
- ``_collect_params``/``_parse_size`` — argv k=v 与 K/M/G/T 尺寸规整
- ``_pause_refused``/``_spec_paidness`` — PAUSE 付费闸 (paid=None
  fail-closed)
- ``_try_sweep``/``_pre_write`` — §2.4 写命令前轻扫 (失败只警告
  不阻写)
- ``_open_index``/``_print_json``/``_load_registry`` — index 增量
  tail 打开 / JSON 输出 / registry 尽力加载
- ``_run_dir_of``/``_rundir_of`` — run 名/dir 解析

门面回引名单见 ``kernel.cli._LEAF_EXPORTS``; monkeypatch 锚点归本叶
(如 verbs 测试的 ``_open_index`` 换桩——经 ``cli.`` 属性读的消费者
自动透过门面命中补丁)。
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path

from kernel import idnorm, locks, paths, runs
from kernel import index as index_mod

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_REFUSED = 2


def _err(msg: str) -> None:
    print(f"bench: {msg}", file=sys.stderr)


def _lazy(modname: str):
    """Import a kernel sibling module lazily; (module, None) or (None, err)."""
    try:
        return importlib.import_module(f"kernel.{modname}"), None
    except Exception as exc:  # ImportError AND in-module failures — report, don't hide
        return None, exc


def _specs_dir() -> Path:
    """bench/py/specs — the spec-file home (this file lives in kernel/)."""
    return Path(__file__).resolve().parents[1] / "specs"


def _shim_path() -> Path:
    """bench/py/bench — the executable shim next to the kernel package."""
    return Path(__file__).resolve().parents[1] / "bench"


def _resolve_spec(name: str) -> Path | None:
    """SPEC arg -> path: literal file first, then specs/{name}[.py]."""
    p = Path(name)
    if p.is_file():
        return p
    for cand in (_specs_dir() / name, _specs_dir() / f"{name}.py"):
        if cand.is_file():
            return cand
    _err(f"spec not found: {name!r} (tried literal path and {_specs_dir()})")
    return None


def _collect_params(args) -> dict:
    """--param k=v repeats + positional k=v leftovers -> params dict."""
    out: dict[str, str] = {}
    for kv in [*(args.param or []), *(args.params or [])]:
        if "=" not in kv:
            msg = f"param {kv!r} is not k=v"
            raise ValueError(msg)
        k, v = kv.split("=", 1)
        if not k:
            msg = f"param {kv!r} has an empty key"
            raise ValueError(msg)
        out[k] = v
    return out


def _pause_refused(what: str, paid) -> bool:
    """PAUSE is a paid-spend fence (Phase 3 rescope): only specs carrying a
    paid stage are refused; free work and ``plan`` run straight through so
    the migration can proceed while the fence stays up. ``paid=None``
    (unprovable spec) fails closed."""
    if paid is not False and locks.pause_engaged():
        _err(
            f"{what}: refused — PAUSE engaged ({paths.pause_path()}); "
            "paid work stays fenced, free specs are unaffected"
        )
        return True
    return False


def _spec_paidness(spec_path: Path):
    """True/False when the spec module can prove it, else None."""
    smod, _serr = _lazy("spec")
    loader = getattr(smod, "load_spec", None) if smod is not None else None
    if loader is None:
        return None
    try:
        return loader(str(spec_path)).has_paid()
    except Exception:
        return None


def _try_sweep(light: bool):
    """kernel.sweep.sweep when it exists; (report|None, err|None)."""
    mod, err = _lazy("sweep")
    fn = getattr(mod, "sweep", None) if mod is not None else None
    if fn is None:
        return None, err if err is not None else AttributeError("sweep")
    try:
        return fn(light=light), None
    except Exception as exc:
        return None, exc


def _pre_write() -> None:
    """Every write command auto-runs the light reaper first (§2.4).

    A missing/failed sweep warns on stderr but never blocks the write —
    the reaper's state is recoverable bookkeeping, not a write gate.
    """
    _, err = _try_sweep(light=True)
    if err is not None:
        _err(f"note: pre-write light sweep skipped ({err})")


def _open_index() -> index_mod.Index:
    """Open the derived index and pull it current (incremental tail ingest)."""
    return index_mod.open_index(warn=_err)


def _print_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str))


def _load_registry():
    """PapersRegistry for id resolution at import boundaries (best effort)."""
    try:
        return idnorm.PapersRegistry.load()
    except Exception as exc:
        _err(f"note: PapersRegistry.load failed ({exc}) — ids resolve statelessly")
        return None


def _run_dir_of(name: str) -> Path | None:
    """Resolve a run reference: a directory, or a kind/date/slug run name."""
    p = Path(name)
    if p.is_dir():
        return p
    parts = str(name).split("/")
    if len(parts) == 3:
        d = paths.run_dir(parts[0], parts[1], parts[2])
        if d.is_dir():
            return d
    _err(f"run not found: {name!r} (need kind/date/slug or a run dir)")
    return None


def _rundir_of(name: str):
    """RunDir for a run name/path (kind/date/slug parsed from the dir)."""
    d = _run_dir_of(name)
    if d is None:
        return None
    try:
        parts = d.resolve().relative_to(paths.runs_dir()).parts
    except ValueError:
        parts = ()
    if len(parts) >= 3:
        try:
            return runs.load_run(parts[0], parts[1], parts[2])
        except FileNotFoundError:
            pass
        return runs.RunDir(path=d, kind=parts[0], date=parts[1], slug=parts[2])
    return runs.RunDir(path=d, kind="adhoc", date="-", slug=d.name)


def _parse_size(text: str) -> int:
    """'512M' / '5G' / '1.5T' / raw bytes -> int bytes."""
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KkMmGgTt]?)", str(text).strip())
    if not m:
        msg = f"bad size {text!r} (use bytes or K/M/G/T suffix)"
        raise ValueError(msg)
    mult = {"": 1, "K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40}
    return int(float(m.group(1)) * mult[m.group(2).upper()])
