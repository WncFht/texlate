#!/bin/bash
# find-gateway-hog.sh —「谁在打网关」归因链：进程 → Claude 会话 → fleet 名。
#
# 套路（2026-09-16 实战定型）：ss -tnp 拿 :3003 连接的 PID → ps 拿 cmdline
# 指纹 → /proc/PID/cwd 圈项目 → ~/.claude/projects/<proj> 按 mtime 圈活跃
# transcript → grep 命令指纹定位 sid → 'This session is' 拿 fleet 名。
# 拿到 fleet 名后用 SendMessage 附证据（PID/命令行/连接数）请属主降并发。
#
# 用法: scripts/find-gateway-hog.sh [端口]（默认 3003）
set -uo pipefail

PORT=${1:-3003}
PROJDIR=$HOME/.claude/projects

echo "== 1) 谁在连 :${PORT} =="
# 尾随空格锚定——裸 ":3003" 会误中 ":30030" 类端口
ss -tnp 2>/dev/null | grep -E ":${PORT} " | head -20 || echo "(无连接)"

echo
echo "== 2) 嫌疑进程（CPU 排序）=="
ps -eo pid,ppid,etime,pcpu,args --sort=-pcpu | grep -vE 'grep|ps -eo' | grep -iE 'texlate|pytest|bench|e2e|uv run|python' | head -15

echo
echo "== 3) 本机 claude 进程 + cwd =="
for p in $(pgrep -f 'claude' | sort -u); do
  cwd=$(readlink "/proc/$p/cwd" 2>/dev/null || echo '?')
  args=$(ps -o etime=,args= -p "$p" 2>/dev/null | cut -c1-120)
  printf 'pid=%-7s cwd=%-45s %s\n' "$p" "$cwd" "$args"
done

echo
echo "== 4) 近 2h 活跃的会话 transcript =="
find "$PROJDIR" -name '*.jsonl' -newermt '2 hours ago' -printf '%T+ %s %p\n' 2>/dev/null | sort -r | head -15

echo
echo "== 5) 下一步手工动作 =="
echo "  grep -rl '<命令指纹>' $PROJDIR/<bucket>/*.jsonl   # 定位肇事 sid"
echo "  grep -oE 'This session is [a-z0-9-]+' <sid>.jsonl  # 拿 fleet 名"
echo "  → SendMessage 附 PID/证据请属主降并发"
