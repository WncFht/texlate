#!/usr/bin/env bash
# zotero/dev/env.sh — shared dev-toolchain environment. Source, don't execute:
#   source "$(dirname "$0")/env.sh"
#
# Why non-default ports: this box is crowded. 8765 = user's real texlate
# instance, 8766 = bench/py/ops/status_panel.py (long-lived). Dev tools must
# never squat on real services — every port below is chosen free at writing
# time AND each tool asserts port-free before binding plus verifies server
# identity after connect (health .data_dir for texlate; protocol handshake
# for RDP). 局部可归因 starts with talking to the right process.

# shellcheck shell=bash

# --- paths (all inside gitignored tmp/) ---
TEXLATE_DEV_ROOT="${TEXLATE_DEV_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../tmp/zotero-dev" && pwd)}"
export TEXLATE_DEV_ROOT
TEXLATE_DEV_DATA="${TEXLATE_DEV_DATA:-$TEXLATE_DEV_ROOT/texlate-data}"
export TEXLATE_DEV_DATA
# Canonical dev profile: rdp-spike initialized this one (remote-debugging
# prefs seeded, first-run done) and a live Zotero is already on it.
# Zotero's library lives in ZOTERO_DATA (-datadir), NOT inside the profile —
# fixtures/assertions target the running instance's datadir.
TEXLATE_DEV_PROFILE="${TEXLATE_DEV_PROFILE:-$TEXLATE_DEV_ROOT/rdp-profile}"
export TEXLATE_DEV_PROFILE
TEXLATE_DEV_ZDATA="${TEXLATE_DEV_ZDATA:-$TEXLATE_DEV_ROOT/zotero-data}"
export TEXLATE_DEV_ZDATA

# --- ports ---
TEXLATE_DEV_PORT="${TEXLATE_DEV_PORT:-18765}"
export TEXLATE_DEV_PORT
TEXLATE_DEV_BASE="http://127.0.0.1:${TEXLATE_DEV_PORT}"
export TEXLATE_DEV_BASE
TEXLATE_DEV_RDP_PORT="${TEXLATE_DEV_RDP_PORT:-6100}"
export TEXLATE_DEV_RDP_PORT

# --- binaries ---
ZOTERO_BIN="${ZOTERO_BIN:-/usr/bin/zotero}"
export ZOTERO_BIN

# --- repo root ---
TEXLATE_REPO="${TEXLATE_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export TEXLATE_REPO

texlate_dev_port_free() {
  # 0 = free, 1 = taken (prints owner hint on stderr)
  local port="$1"
  if ss -tln 2>/dev/null | grep -q ":${port} "; then
    ss -tlnp 2>/dev/null | grep ":${port} " >&2 || true
    return 1
  fi
  return 0
}
