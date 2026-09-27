#!/usr/bin/env bash
# bench 巡检哨兵——系统级（cron/systemd timer 驱动），不依赖任何会话在不在。
# 每轮一行落 tmp/repair-wN/patrol.log；越闸行打 WARN。Claude 巡检 cron 是
# 智能层（会修会判），本脚本是保底层（只量不判）。
set -u

BENCH_ROOT="${TEXLATE_BENCH_ROOT:-$HOME/.local/share/texlate-bench}"
REPO=/home/fanghaotian/src/texlate
GWDB=$HOME/.local/state/devin-2api/devin-2api.db
KEY=1edae453
NOW=$(date '+%m-%d %H:%M:%S')

# 在飞的 soak run：最近 2h 内有 heartbeat 的最新 run 目录
RUN=""
for d in "$BENCH_ROOT"/runs/soak/*/*/; do
    hb="$d/heartbeat"
    [ -f "$hb" ] || continue
    age=$(( $(date +%s) - $(stat -c %Y "$hb") ))
    [ "$age" -lt 7200 ] && RUN="$d"
done
[ -z "$RUN" ] && { echo "$NOW WARN no live soak run dir" >> "$REPO/tmp/bench-patrol.log"; exit 0; }

SLUG=$(basename "$RUN")
LOG="$REPO/tmp/bench-patrol.log"
warn=""

# 1) df 闸（<60G 告警）
free_g=$(df -BG / | awk 'NR==2{gsub("G","",$4); print $4}')
[ "$free_g" -lt 60 ] && warn="$warn DF<60G!"
[ "$free_g" -lt 40 ] && warn="$warn DF<40G-STOPALL!"

# 2) 心跳 + events 鲜度（>600s = 死）
hb_age=$(( $(date +%s) - $(stat -c %Y "$RUN/heartbeat" 2>/dev/null || echo 0) ))
ev_age=$(( $(date +%s) - $(stat -c %Y "$RUN/events.jsonl" 2>/dev/null || echo 0) ))
fin=""
grep -q '"finished"' "$RUN/events.jsonl" 2>/dev/null && tail -50 "$RUN/events.jsonl" | grep -q finished && fin="FINISHED"
[ -z "$fin" ] && [ "$hb_age" -gt 600 ] && warn="$warn HB-STALE(${hb_age}s)!"
[ -z "$fin" ] && [ "$ev_age" -gt 600 ] && warn="$warn EV-STALE(${ev_age}s)!"

# 3) records 进度（xlat 真终态 + compile clean/partial）
prog=$(sqlite3 "file:$BENCH_ROOT/ledger/index.sqlite?mode=ro" "
SELECT stage||':'||status||'='||count(*) FROM records
WHERE run LIKE '%$SLUG' AND stage IN ('xlat','compile','fixloop')
AND status IN ('ok','partial','clean','fail') GROUP BY stage,status" 2>/dev/null | paste -sd' ')

# 4) 网关近 10min 本批 key 面
gw=$(sqlite3 "file:$GWDB?mode=ro" "
SELECT coalesce(sum(status_code=200),0)||'ok/'||coalesce(sum(status_code=429),0)||'x429/'||coalesce(round(sum(output_tokens)/600.0),0)||'tps'
FROM logs WHERE time > (strftime('%s','now')-600)*1000 AND path LIKE '%chat%' AND key_hash LIKE '$KEY%'" 2>/dev/null)

echo "$NOW $SLUG df${free_g}G hb${hb_age}s ev${ev_age}s [$prog] gw:$gw ${fin:-}$warn" >> "$LOG"

# 收官哨兵：finished 后写一行带 cost 的结账单
if [ -n "$fin" ] && ! grep -q "FINAL-ACCT $SLUG" "$LOG" 2>/dev/null; then
    tail -20 "$RUN/events.jsonl" | grep '"finished"' | tail -1 | \
        sed "s/^/$NOW FINAL-ACCT $SLUG /" | cut -c1-400 >> "$LOG"
fi
