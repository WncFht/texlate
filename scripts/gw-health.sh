#!/bin/bash
# gw-health.sh — gwcap 闸 + 网关双路探活：单行报告，任一失败 exit 1。
#
#   gwcap   127.0.0.1:3399/__gwcap/healthz → {ok,limit,model_prefix,inflight,queued}
#           （批量机出向 tcp/3003 的 REDIRECT 闸；swe-2-medium 走全局 sem=4）
#   direct  100.105.212.52:3003/healthz   tailscale 直连——bench/脚本约定入口
#   tunnel  127.0.0.1:3003/healthz        ssh 隧道——仅 texlate server 产品链用；
#           bench 批量不需要它，纯 bench 场景可 GW_HEALTH_SKIP_TUNNEL=1 跳过
#
# 输出形如：
#   gw-health ok: gwcap[inflight=0 queued=0 limit=4] direct[200 0.14s] tunnel[200 0.04s]
#   gw-health FAIL(1): gwcap[inflight=0 queued=0 limit=4] direct[000 rc=7] tunnel[skip]
#
# 覆盖：GW_HEALTH_TIMEOUT（秒，默认 5）/ GWCAP_URL / DIRECT_URL / TUNNEL_URL。
set -u

T=${GW_HEALTH_TIMEOUT:-5}
GWCAP_URL=${GWCAP_URL:-http://127.0.0.1:3399/__gwcap/healthz}
DIRECT_URL=${DIRECT_URL:-http://100.105.212.52:3003/healthz}
TUNNEL_URL=${TUNNEL_URL:-http://127.0.0.1:3003/healthz}

fails=0
report=""

add() {
  report="${report:+$report }$1"
}

# probe <name> <url>：2xx/3xx 记 name[code t]，其余记 FAIL 并计数
probe() {
  local name=$1 url=$2 res rc code t
  res=$(curl -sS -m "$T" -o /dev/null -w '%{http_code} %{time_total}' "$url" 2>/dev/null)
  rc=$?
  code=${res%% *}
  t=${res#* }
  case $code in
  2* | 3*)
    add "${name}[${code} ${t}s]"
    ;;
  *)
    add "${name}[FAIL code=${code} rc=${rc}]"
    fails=$((fails + 1))
    ;;
  esac
}

# gwcap：要 body 里的闸面计数；可达但 json 解析失败降级 unparsed 不算 FAIL
if body=$(curl -fsS -m "$T" "$GWCAP_URL" 2>/dev/null); then
  stats=$(
    python3 -c '
import json
import sys

try:
    d = json.loads(sys.argv[1])
except Exception:
    sys.exit(0)
print(
    "inflight=%s queued=%s limit=%s"
    % (d.get("inflight", "?"), d.get("queued", "?"), d.get("limit", "?"))
)
' "$body" 2>/dev/null
  )
  if [ -n "$stats" ]; then
    add "gwcap[${stats}]"
  else
    add "gwcap[ok unparsed]"
  fi
else
  rc=$?
  add "gwcap[FAIL rc=${rc}]"
  fails=$((fails + 1))
fi

probe direct "$DIRECT_URL"
if [ "${GW_HEALTH_SKIP_TUNNEL:-0}" = 1 ]; then
  add "tunnel[skip]"
else
  probe tunnel "$TUNNEL_URL"
fi

if [ "$fails" -eq 0 ]; then
  echo "gw-health ok: ${report}"
else
  echo "gw-health FAIL(${fails}): ${report}"
  exit 1
fi
