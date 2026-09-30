"""verbs.dossier 环境/依赖叶 —— 常量面 + texlate taxonomy 桥 + triage 桥 +
ruleset 懒装 + venv 重入 + registry 装载（dossier.py 拆分叶）。

``load_ruleset``/``parse_log``/``parse_text`` 在 texlate 缺席时绑 None
（``_ruleset()`` 先于调用面闸住），与原「名未绑」的差异只在降级面可见。
门面回引名单见 ``verbs.dossier._LEAF_EXPORTS``。
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

from kernel import idnorm

from verbs._common import _STAGE_SUFFIXES

BENCH = Path(__file__).resolve().parents[2]
REPO = BENCH.parent
CORPUS = BENCH / "corpus"

try:  # taxonomy 需 texlate 系依赖——bare python3 下由 main() 里
    # _maybe_reexec_venv 切仓内 .venv 重入；仍不可用时降级 sig 级
    from texlate.compile.fixloop.engine import load_ruleset
    from texlate.compile.logparse import parse_log, parse_text

    _TAX_OK = True
except Exception:
    load_ruleset = parse_log = parse_text = None
    _TAX_OK = False

try:  # triage 动词产物复用（bucket_sig/classify/retired_names——缺席降级）
    from verbs import triage as _triage_mod
except Exception:
    _triage_mod = None


def _triage_fn(name: str):
    fn = getattr(_triage_mod, name, None) if _triage_mod is not None else None
    return fn if callable(fn) else None


STAGES = _STAGE_SUFFIXES  # 阶段词表单源在 verbs/_common.py（原同内容双 tuple）
_FAIL_WORDS = {"fail", "error", "reject", "crash", "timeout"}
_SUBCLASS_SIGS = ("other", "syntax", "unfixable:other")
_WONTFIX_CATS = {"early_eof", "capacity", "latex209", "inject"}
_EXCERPT_HEAD = 600

_RULESET: list = [None]  # 懒装格：[None]=未装 [False]=装败（免 global）


def _ruleset():
    if not _TAX_OK:
        return None
    if _RULESET[0] is None:
        try:
            _RULESET[0] = load_ruleset()
        except Exception:
            _RULESET[0] = False
    return _RULESET[0] or None


def _maybe_reexec_venv() -> None:
    """bare python3 缺 httpx/regex → texlate.compile 面全灭；仓内 .venv 在
    且当前非其解释器时，execve 重入整个 bench 进程（env 闸防环）。

    纯 python 包可借 addsitedir 混用，但 regex 是 C 扩展且 .venv=py3.12
    vs 系统 py3.14 副版本错位——只有整进程切解释器一条路。
    """
    if _TAX_OK or os.environ.get("TEXLATE_BENCH_REEXEC"):
        return
    venv_py = REPO / ".venv" / "bin" / "python"
    if not venv_py.is_file():
        return
    with contextlib.suppress(OSError):
        if Path(sys.executable).resolve() == venv_py.resolve():
            return
    shim = BENCH / "py" / "bench"
    env = dict(os.environ, TEXLATE_BENCH_REEXEC="1")
    os.execve(  # noqa: S606 — 解释器重入非 shell 起进程
        str(venv_py), [str(venv_py), str(shim), *sys.argv[1:]], env
    )


def _load_registry():
    try:
        return idnorm.PapersRegistry.load()
    except Exception:
        return None
