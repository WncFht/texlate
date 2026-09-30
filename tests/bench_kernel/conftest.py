"""Shared fixtures for kernel tests.

Every test gets an isolated $TEXLATE_BENCH_ROOT under pytest's tmp_path via
the `broot` fixture — env override + paths.ensure_layout(). Kernel modules
resolve paths lazily from env, so monkeypatching works without any caching.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from kernel import paths


def write_verify_stamp() -> None:
    """Fresh vault/.verify-stamp.json — the first-fire gate's <24h leg.

    Written into every test root so paid-spec tests exercise the gate for
    real (coverage + seal still evaluated live); a test that wants the
    gate's refusal deletes the file first.
    """
    paths.vault_verify_stamp_path().write_text(
        json.dumps(
            {
                "ts": time.time(),
                "level": "fixture",
                "metas": 0,
                "checked": 0,
                "meta_missing": 0,
            }
        )
    )


@pytest.fixture
def broot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "broot"
    monkeypatch.setenv(paths.ENV_ROOT, str(root))
    for env in (paths.ENV_LEDGER, paths.ENV_RUNS, paths.ENV_VAULT, paths.ENV_LAKE):
        monkeypatch.delenv(env, raising=False)
    paths.ensure_layout()
    write_verify_stamp()
    return root


# prepend 模式下本文件与 tests/conftest.py 共用 sys.modules["conftest"] 键，
# 后加载者（本文件，bench_kernel/ 字母序先于 test_*）把根件顶掉——根目录 115 个
# 老测试裸 `from conftest import …` 会拿到本模块然后 ImportError。把根件
# 以私有名 exec 一遍、缺失名嫁接进本模块，两侧消费者各取所需；pytest 内部
# 按模块对象注册 conftest 插件，fixture 解析不受影响。
import importlib.util as _ilu  # noqa: E402

_root_conftest = Path(__file__).resolve().parents[1] / "conftest.py"
_spec = _ilu.spec_from_file_location("_root_conftest", _root_conftest)
if _spec is not None and _spec.loader is not None:
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    for _k in dir(_mod):
        if not _k.startswith("__") and _k not in globals():
            globals()[_k] = getattr(_mod, _k)
