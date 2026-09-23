#!/usr/bin/env bash
# Daily minimal-backup unit for the trizone bench root (§3.10.1):
# ledger + vault meta/manifest + lake durable/catalog + run keep-tier.
# Vault payload bytes are deliberately excluded — restic owns those.
set -uo pipefail
cd /home/fanghaotian/src/texlate
export PYTHONPATH=bench/py
python3 -m kernel backup || exit $?

# tar 轮转：每份 ~1.1G/日，无上限会把盘吃爆——保最新 3 份（2026-09-23
# 磁盘手术裁决，见 docs/research/corpus/2026-09-23-rebuild-plan-v4.md §2.6）。
backup_dir="${TEXLATE_BENCH_ROOT:-$HOME/.local/share/texlate-bench}/backup"
ls -1t "$backup_dir"/bench-backup-*.tar 2>/dev/null | tail -n +4 | while read -r old; do
    rm -f -- "$old" && echo "rotated: $old"
done
