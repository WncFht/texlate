"""$TEXLATE_BENCH_ROOT layout — single source of truth for all zone paths.

Root resolution:
    TEXLATE_BENCH_ROOT env, default ~/.local/share/texlate-bench
Per-zone overrides (each may point at a different mount):
    TEXLATE_LEDGER_ROOT / TEXLATE_RUNS_ROOT / TEXLATE_VAULT_ROOT / TEXLATE_LAKE_ROOT

Hard constraints (doctor-enforced):
    - root must NOT be inside a git checkout
    - vault/ and vault/.staging must share st_dev (same-volume rename)
    - lock files are created once and NEVER unlinked (flock pins the inode)
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_ROOT = "TEXLATE_BENCH_ROOT"
ENV_LEDGER = "TEXLATE_LEDGER_ROOT"
ENV_RUNS = "TEXLATE_RUNS_ROOT"
ENV_VAULT = "TEXLATE_VAULT_ROOT"
ENV_LAKE = "TEXLATE_LAKE_ROOT"

_DEFAULT_ROOT = Path.home() / ".local" / "share" / "texlate-bench"


def root() -> Path:
    return Path(os.environ.get(ENV_ROOT, _DEFAULT_ROOT)).expanduser().resolve()


def _zone(env: str, name: str) -> Path:
    override = os.environ.get(env)
    if override:
        return Path(override).expanduser().resolve()
    return root() / name


# --- ledger zone ------------------------------------------------------------


def ledger_dir() -> Path:
    return _zone(ENV_LEDGER, "ledger")


def events_path() -> Path:
    return ledger_dir() / "events.jsonl"


def runs_jsonl_path() -> Path:
    return ledger_dir() / "runs.jsonl"


def index_path() -> Path:
    return ledger_dir() / "index.sqlite"


def seqfile_path() -> Path:
    return ledger_dir() / ".seq"


def global_metrics_path() -> Path:
    return ledger_dir() / "global-metrics.jsonl"


def ledger_lock_path() -> Path:
    return ledger_dir() / ".lock"


def ledger_sentinel_path() -> Path:
    return ledger_dir() / ".ledger-sentinel"


def index_dirty_path() -> Path:
    return ledger_dir() / ".index-dirty"


def seals_path() -> Path:
    return ledger_dir() / "seals.jsonl"


def sealed_dir() -> Path:
    return ledger_dir() / "sealed"


def quarantine_path() -> Path:
    return ledger_dir() / "quarantine.jsonl"


def adjudication_path() -> Path:
    return ledger_dir() / "adjudication.jsonl"


# --- runs zone --------------------------------------------------------------


def runs_dir() -> Path:
    return _zone(ENV_RUNS, "runs")


def run_dir(kind: str, date: str, slug: str) -> Path:
    return runs_dir() / kind / date / slug


# --- vault zone -------------------------------------------------------------


def vault_dir() -> Path:
    return _zone(ENV_VAULT, "vault")


def vault_lock_path() -> Path:
    return vault_dir() / ".lock"


def vault_staging_dir() -> Path:
    return vault_dir() / ".staging"


def vault_sentinel_path() -> Path:
    return vault_dir() / ".vault-sentinel"


def vault_manifest_path() -> Path:
    return vault_dir() / "manifest.jsonl"


def vault_meta_dir() -> Path:
    return vault_dir() / "meta"


def vault_pending_mirror_path() -> Path:
    return vault_dir() / ".pending-mirror"


def vault_verify_stamp_path() -> Path:
    """Freshness stamp written by `bench vault verify` on a clean pass —
    the first-fire gate's <24h evidence leg (§6 Phase-3 首火闸)."""
    return vault_dir() / ".verify-stamp.json"


def vault_kind_dir(kind: str) -> Path:
    """kind in {zh, splice, state}; quarantine lives under vault/quar/<kind>."""
    if kind == "quar":
        return vault_dir() / "quar"
    return vault_dir() / kind


# --- lake zone --------------------------------------------------------------


def lake_dir() -> Path:
    return _zone(ENV_LAKE, "lake")


def lake_corpus_dir() -> Path:
    return lake_dir() / "corpus"


def lake_catalog_path() -> Path:
    return lake_dir() / "corpus" / "catalog.jsonl"


def lake_objects_dir() -> Path:
    return lake_dir() / "objects"


def lake_durable_dir() -> Path:
    return lake_dir() / "durable"


def lake_cache_dir() -> Path:
    return lake_dir() / "cache"


def lake_tmp_dir() -> Path:
    return lake_dir() / "tmp"


def lake_daily_dir() -> Path:
    return lake_dir() / "daily"


def lake_locks_dir() -> Path:
    return lake_dir() / ".locks"


def lake_items_dir() -> Path:
    return lake_dir() / ".items"


# --- global locks / sentinels ------------------------------------------------


def locks_dir() -> Path:
    return root() / "locks"


def claims_locks_dir() -> Path:
    return locks_dir() / "claims"


def slots_dir() -> Path:
    return locks_dir() / "slots"


def auth_dead_path() -> Path:
    return locks_dir() / "AUTH_DEAD"


def pause_path() -> Path:
    return root() / "PAUSE"


def kernel_active_path() -> Path:
    return root() / ".kernel-active"


def import_src_dir() -> Path:
    return root() / "import-src"


def backup_dir() -> Path:
    return root() / "backup"


def state_dir() -> Path:
    """$ROOT/state — non-ledger operational state (status-panel board, …)."""
    return root() / "state"


def status_panel_dir() -> Path:
    """ops/status_panel.py / ops/task_ping.py share this dir (pid, tasks.d, cache)."""
    return state_dir() / "status-panel"


# --- layout bootstrap ---------------------------------------------------------

_SENTINEL_TEXT = (
    "texlate-bench zone sentinel — if this file is missing the mount is wrong\n"
)


def ensure_layout() -> Path:
    """Create the full zone skeleton, sentinels, immortal lock files, seqfile.

    Idempotent. Lock files are touched once and never unlinked.
    Returns the resolved root.
    """
    r = root()
    for d in (
        r,
        ledger_dir(),
        sealed_dir(),
        vault_meta_dir(),
        vault_staging_dir(),
        runs_dir(),
        vault_dir(),
        vault_kind_dir("zh"),
        vault_kind_dir("splice"),
        vault_kind_dir("state"),
        vault_kind_dir("quar"),
        lake_corpus_dir(),
        lake_objects_dir(),
        lake_durable_dir(),
        lake_cache_dir(),
        lake_tmp_dir(),
        lake_daily_dir(),
        lake_locks_dir(),
        lake_items_dir(),
        locks_dir(),
        claims_locks_dir(),
        slots_dir(),
        import_src_dir(),
        backup_dir(),
        status_panel_dir(),
    ):
        d.mkdir(parents=True, exist_ok=True)

    for sentinel in (ledger_sentinel_path(), vault_sentinel_path()):
        if not sentinel.exists():
            sentinel.write_text(_SENTINEL_TEXT)

    for lock in (ledger_lock_path(), vault_lock_path()):
        if not lock.exists():
            lock.touch()

    seq = seqfile_path()
    if not seq.exists():
        seq.write_text("0\n")

    for f in (
        events_path(),
        runs_jsonl_path(),
        vault_manifest_path(),
        seals_path(),
        global_metrics_path(),
    ):
        if not f.exists():
            f.touch()

    return r


def assert_vault_same_volume() -> None:
    """vault and its .staging must share st_dev — else rename is not atomic."""
    v = vault_dir().stat().st_dev
    s = vault_staging_dir().stat().st_dev
    if v != s:
        msg = (
            f"vault {vault_dir()} and staging {vault_staging_dir()} on different devices "
            f"({v} vs {s}) — cross-device rename would lose atomicity"
        )
        raise RuntimeError(msg)
