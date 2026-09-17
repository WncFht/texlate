#!/bin/bash
# dev-smoke.sh — web 前端 e2e 冒烟一条龙：起 vite dev → 从日志解析实际端口
# （5173 被占时 vite 自动漂移，写死端口会打到别的会话）→ /api/health 验
# mock 后端（version:"mock"）→ playwright 冒烟 → 只杀自己起的进程。
#
# 前置: web/ npm ci 已跑 + web/scripts/ npm ci 已跑（playwright-core）。
# 用法: scripts/dev-smoke.sh [--keep]（--keep 跑完留 dev server）
set -euo pipefail
cd "$(dirname "$0")/../web"

# 每跑一次独立 log——固定名会被并行会话互截，PORT 解析抓到别家端口
LOG=$(mktemp "${TMPDIR:-/tmp}/vite-dev-smoke.XXXXXX.log")
npm run dev >"$LOG" 2>&1 &
NPM_PID=$!
MY_VITE_PIDS=""

cleanup() {
  [[ ${KEEP:-0} == 1 ]] && return
  # 只杀自己这棵树的：npm 父进程 + 本 vite 监口属主
  kill "$NPM_PID" 2>/dev/null || true
  for p in $MY_VITE_PIDS; do kill "$p" 2>/dev/null || true; done
}
trap cleanup EXIT
[[ ${1:-} == --keep ]] && KEEP=1

# 等 vite 就绪并解析实际端口（漂移时 Local: 行给真口）
PORT=""
for _ in $(seq 1 30); do
  PORT=$(grep -oE '(localhost|127\.0\.0\.1):[0-9]+' "$LOG" | head -1 | cut -d: -f2 || true)
  [[ -n $PORT ]] && break
  sleep 1
done
[[ -n $PORT ]] || {
  echo "vite 30s 未就绪，看 $LOG" >&2
  exit 1
}
echo "vite on :$PORT"

# 只认本 vite 的监口 PID（按端口属主，不 pkill vite 误杀别会话）
MY_VITE_PIDS=$(ss -tlnp 2>/dev/null | grep ":$PORT " | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true)

curl -sf "http://localhost:$PORT/api/health" | grep -q '"version": *"mock"' ||
  echo "warn: /api/health 非 mock 应答——确认打的是不是自己的 dev server" >&2

WEB_BASE="http://localhost:$PORT" node scripts/smoke.mjs
