#!/bin/sh
# server-smoke.sh [port] [data-dir] — texlate web 全链 curl 冒烟。
#
# 起服(后台) → /api/health 就绪 → SPA 落地 → openapi 路由表 → upload 建任务
# → SSE 抓流 → artifact 逐个 sha256 → 收尾只杀自己 PID。
# 用法: scripts/server-smoke.sh 8899 /tmp/tw   (省略则 port=8899 data-dir=/tmp/tw-<port>)
# 出处：tmp/transcript-mining/484a9c38.md A9（多 agent 重抄的序列固化）。
set -u
# uv run 依赖仓根 pyproject——与兄弟脚本同规，先钉回仓根再干活
cd "$(dirname "$0")/.." || exit 1
PORT=${1:-8899}
DIR=${2:-/tmp/tw-$PORT}
BASE=http://127.0.0.1:$PORT
LOG=$DIR/server.log
mkdir -p "$DIR"
fail() {
  echo "FAIL: $1" >&2
  exit 1
}

nohup uv run texlate web --port "$PORT" --data-dir "$DIR" >"$LOG" 2>&1 &
SVPID=$!
trap 'kill $SVPID 2>/dev/null' EXIT

ok=0
for _ in $(seq 1 15); do
  curl -sf --max-time 2 "$BASE/api/health" >/dev/null && {
    ok=1
    break
  }
  sleep 1
done
[ "$ok" = 1 ] || fail "health 15s 未就绪 (log: $LOG)"
echo "PASS health"

curl -s -o /dev/null -w 'GET / -> %{http_code} %{content_type}\n' "$BASE/"
echo "--- routes ---"
curl -s "$BASE/openapi.json" | python3 -c 'import json,sys; print("\n".join(sorted(json.load(sys.stdin)["paths"].keys())))'

printf '\\documentclass{article}\n\\begin{document}\nhi\n\\end{document}\n' >"$DIR/m.tex"
RESP=$(curl -s -X POST -F "file=@$DIR/m.tex" "$BASE/api/upload")
echo "upload -> $RESP"
TID=$(printf %s "$RESP" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("task_id") or d.get("id",""))')
[ -n "$TID" ] || fail "upload 未回 task_id"

timeout 60 curl -sN -H "Accept: text/event-stream" "$BASE/api/task/$TID" >"$DIR/sse.log" 2>/dev/null
tail -3 "$DIR/sse.log"

for k in zh.pdf dual.json compile.log zh-src.zip; do
  code=$(curl -s -o "$DIR/dl-$k" -w '%{http_code}' "$BASE/api/files/$TID/$k")
  if [ "$code" = 200 ]; then sha256sum "$DIR/dl-$k"; else echo "$k -> $code"; fi
done

kill $SVPID 2>/dev/null
trap - EXIT
sleep 1
ss -tlnp 2>/dev/null | grep ":$PORT " && echo "WARN: port $PORT still bound" || echo "PASS port free"
