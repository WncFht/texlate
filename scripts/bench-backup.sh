#!/usr/bin/env bash
# Daily minimal-backup unit for the trizone bench root (§3.10.1):
# ledger + vault meta/manifest + lake durable/catalog + run keep-tier.
# Vault payload bytes are deliberately excluded — restic owns those.
set -uo pipefail
cd /home/fanghaotian/src/texlate
export PYTHONPATH=bench/py
exec python3 -m kernel backup
