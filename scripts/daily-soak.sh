#!/usr/bin/env bash
# daily-soak.sh — arXiv CS+math 日更批次全流程（幂等、cron/systemd-timer 友好）。
#
#   enum(RSS) → fetch(acquire_source→corpus_daily) → stagerun 五 stage → report
#
# 设计：docs/research/arxiv/2026-09-19-daily-soak.md。
# 幂等：enum 命中已有批次即跳过；fetch/stagerun 逐篇 records 账续跑——
#   任意时刻中断/重跑都安全。无公告日 feed 空 → 自动续做最近批次的欠账。
# 调度建议：每日 02:30 UTC（公告 20:00 ET 后 ~1.5h）由 systemd --user timer 触发。
# 密钥：real 翻译臂需 TEXLATE_API_KEY——放 ~/.config/texlate/soak.env（gitignore 外）。
set -uo pipefail

ROOT="/home/fanghaotian/src/texlate"
# systemd --user 环境 PATH 不含 ~/.local/bin（uv 所在）——补齐保险
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
cd "$ROOT" || exit 1

export TEXLATE_CORPUS="$ROOT/bench/corpus_daily"
WORK="$ROOT/bench/work_daily"
mkdir -p "$WORK"
exec >>"$WORK/soak-$(date -u +%F).log" 2>&1

echo "===== soak run $(date -u '+%F %T UTC') ====="

# 单实例闸——上一批没跑完不叠跑（stagerun records 账续跑即可，不急这一会儿）
exec 9>"$WORK/soak.lock"
if ! flock -n 9; then
  echo "another soak run holds the lock — exit"
  exit 0
fi

# shellcheck disable=SC1091
[ -f "$HOME/.config/texlate/soak.env" ] && . "$HOME/.config/texlate/soak.env"

# 代理健康闸——arxiv 全站 TLS 直连被重置，必须走 clash；代理死=整天白跑
if ! curl -sf -m 15 -o /dev/null -A "texlate-soak/1.0" "https://rss.arxiv.org/rss/cs.CL"; then
  echo "PREFLIGHT FAIL: rss.arxiv.org unreachable（代理死？）— abort"
  exit 3
fi

# 1. 枚举当天公告集（无公告日秒退写 empty 戳）
uv run python bench/py/corpus/daily_arxiv.py enum || echo "enum failed rc=$?"

# 2. 最新批次 = 词法序最大 manifest_*.jsonl（日期命名天然有序）
MANIFEST=$(ls "$ROOT"/bench/corpus_daily/manifest_*.jsonl 2>/dev/null | sort | tail -1)
if [ -z "$MANIFEST" ]; then
  echo "no manifest yet — nothing to do"
  exit 0
fi
DATE=$(basename "$MANIFEST" .jsonl | sed 's/^manifest_//')
echo "batch: $DATE"

# 3. 取源（export 主站，钉版物化 corpus_daily；~1200 篇 ≈ 2h）
uv run python bench/py/corpus/daily_arxiv.py fetch --date "$DATE" || echo "fetch rc=$?"

# 4. 管线 soak——records 账全部可续；--no-preflight（工作树常态 dirty）
SR=(uv run python bench/py/stagerun.py)
DIR="$ROOT/bench/results/soak-$DATE"
COMMON=(--layers "$DATE" --dir "$DIR" --no-preflight)
run() {
  echo "----- $* -----"
  "$@" || echo "stage rc=$? ($*)"
}

run "${SR[@]}" ingest "${COMMON[@]}"
run "${SR[@]}" parse "${COMMON[@]}" --jobs 6
run "${SR[@]}" xlat --arm mock "${COMMON[@]}"
run "${SR[@]}" compile --arm zh --xlat-arm mock "${COMMON[@]}" --jobs 8
run "${SR[@]}" compile --arm base "${COMMON[@]}" --jobs 8
run "${SR[@]}" fixloop "${COMMON[@]}" --jobs 8

# 5. real 臂子集（同 --n/--seed 跨 stage 命中同一子集；有 key 才跑）
if [ -n "${TEXLATE_API_KEY:-}" ]; then
  run "${SR[@]}" xlat --arm real "${COMMON[@]}" --n 40 --seed 42 \
    --api-key "$TEXLATE_API_KEY" --base-url "${TEXLATE_BASE_URL:-http://127.0.0.1:3033}" \
    --model "${TEXLATE_MODEL:-swe-2-medium}"
  run "${SR[@]}" compile --arm zh --xlat-arm real "${COMMON[@]}" --n 40 --seed 42 --jobs 4
  run "${SR[@]}" fixloop "${COMMON[@]}" --n 40 --seed 42 --xlat-arm real --jobs 4
else
  echo "TEXLATE_API_KEY unset — skip real arm"
fi

# 6. 日报
uv run python bench/py/corpus/daily_arxiv.py report --date "$DATE" || true

# 7. work 目录瘦身——单日 ~21G，clean 格删、异常格留供 triage（磁盘硬约束）
uv run python bench/py/corpus/daily_arxiv.py prune --date "$DATE" || echo "prune rc=$?"
echo "===== soak done $(date -u '+%F %T UTC') ====="
