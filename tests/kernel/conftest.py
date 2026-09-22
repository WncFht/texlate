"""Shared fixtures for kernel tests.

Every test gets an isolated $TEXLATE_BENCH_ROOT under pytest's tmp_path via
the `broot` fixture — env override + paths.ensure_layout(). Kernel modules
resolve paths lazily from env, so monkeypatching works without any caching.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "py"))

from kernel import paths  # noqa: E402


def write_verify_stamp() -> None:
    """Fresh vault/.verify-stamp.json — the first-fire gate's <24h leg.

    Written into every test root so paid-spec tests exercise the gate for
    real (coverage + seal still evaluated live); a test that wants the
    gate's refusal deletes the file first.
    """
    paths.vault_verify_stamp_path().write_text(json.dumps({
        "ts": time.time(), "level": "fixture",
        "metas": 0, "checked": 0, "meta_missing": 0,
    }))


@pytest.fixture()
def broot(tmp_path, monkeypatch):
    root = tmp_path / "broot"
    monkeypatch.setenv(paths.ENV_ROOT, str(root))
    for env in (paths.ENV_LEDGER, paths.ENV_RUNS, paths.ENV_VAULT, paths.ENV_LAKE):
        monkeypatch.delenv(env, raising=False)
    paths.ensure_layout()
    write_verify_stamp()
    return root
