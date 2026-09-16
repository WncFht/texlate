#!/bin/bash
# gw-tunnel.sh — devin2api 网关 SSH 隧道常驻管理（texlate server 产品链用）。
#
# 为什么需要它：server 的 validate_base_url 强制非 localhost 走 https，产品链
# 必须把网关经 ssh -L 映射回 127.0.0.1:3003。远端目标必须是 tailscale IP
# 100.105.212.52:3003——写 127.0.0.1 会撞上 Mac 侧 VS Code "Code H" 进程
# 独占 IPv4 loopback（TCP 能连但永不响应）。tailscaled 重启会把裸 ssh 带走
# （exit 144），所以用 while 重连循环 + setsid 脱离会话：本会话死了隧道还在。
#
# 用法: scripts/gw-tunnel.sh {start|stop|status|logs}
# 覆盖: GW_TUNNEL_HOST(默认 fht-mba) GW_TUNNEL_LPORT(3003)
#       GW_TUNNEL_RHOST(100.105.212.52) GW_TUNNEL_RPORT(3003)
set -euo pipefail

HOST=${GW_TUNNEL_HOST:-fht-mba}
LPORT=${GW_TUNNEL_LPORT:-3003}
RHOST=${GW_TUNNEL_RHOST:-100.105.212.52}
RPORT=${GW_TUNNEL_RPORT:-3003}
LOG=${GW_TUNNEL_LOG:-/tmp/ssh${LPORT}.log}
PAT="ssh -N -L ${LPORT}:${RHOST}:${RPORT}"

# -f：连接失败仍打 000（-w 恒输出），%{http_code} 非空会让 grep 误判 up——必须让 curl 本身非零
is_up() { curl -sf -o /dev/null -m 5 "http://127.0.0.1:${LPORT}/healthz" 2>/dev/null; }

case ${1:-status} in
start)
  if pgrep -f "$PAT" >/dev/null; then
    echo "gw-tunnel: already running ($(pgrep -f "$PAT" | head -3 | tr '\n' ' '))"
  else
    setsid nohup bash -c "while true; do ssh -N -L ${LPORT}:${RHOST}:${RPORT} -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o ConnectTimeout=10 ${HOST}; sleep 3; done" \
      >"$LOG" 2>&1 </dev/null &
    disown
    sleep 1
    echo "gw-tunnel: started, log=$LOG"
  fi
  is_up && echo "gw-tunnel: 127.0.0.1:${LPORT} healthz OK" || echo "gw-tunnel: healthz not yet OK (ssh 握手/重连中，看 $LOG)"
  ;;
stop)
  pkill -f "$PAT" && echo "gw-tunnel: stopped" || echo "gw-tunnel: not running"
  ;;
status)
  pgrep -af "$PAT" || echo "gw-tunnel: no tunnel process"
  is_up && echo "gw-tunnel: 127.0.0.1:${LPORT} healthz OK" || echo "gw-tunnel: healthz FAIL"
  ;;
logs)
  tail -n 40 "$LOG"
  ;;
*)
  echo "usage: $0 {start|stop|status|logs}" >&2
  exit 2
  ;;
esac
