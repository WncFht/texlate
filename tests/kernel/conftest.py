"""Shared fixtures for kernel tests.

Every test gets an isolated $TEXLATE_BENCH_ROOT under pytest's tmp_path via
the `broot` fixture — env override + paths.ensure_layout(). Kernel modules
resolve paths lazily from env, so monkeypatching works without any caching.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "py"))

from kernel import paths  # noqa: E402


@pytest.fixture()
def broot(tmp_path, monkeypatch):
    root = tmp_path / "broot"
    monkeypatch.setenv(paths.ENV_ROOT, str(root))
    for env in (paths.ENV_LEDGER, paths.ENV_RUNS, paths.ENV_VAULT, paths.ENV_LAKE):
        monkeypatch.delenv(env, raising=False)
    paths.ensure_layout()
    return root
