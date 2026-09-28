#!/usr/bin/env bash
# chain_runs.sh——触发件终态后按 --then 分段接力执行命令并打戳的通用编排件
#（tmp 夜间接力链毕业：overnight-probe-chain/overnight-sweep/qc99 watch 族公共骨架）。
# 触发件四形（可复数混给，皆近 sticky 终态）：
#   --pid P         等 pid P 退出（kill -0 轮询；pid 回收复用会假活，与源件同口径）
#   --proc PAT      等 pgrep -f PAT 无匹配（剔自身 $$ 及其探测子壳——cmdsubst
#                   子壳存活于 pgrep 扫描期、argv 与本脚本逐字节相同必中，
#                   不剔会永久假活；外层包装等异 argv 常驻进程含 PAT 仍计存活——改用 --pid $!）
#   --marker F STR  等文件 F 内出现子串 STR（grep -qF；F 缺席=继续等）
#   --flag F        等文件 F 存在
# 默认全部终态才过闸（AND，等价 qc99 序贯旗）；--any 任一命中即过（还原 sweep 的
# marker-OR-进程消失）。非 sticky 条件混给时与「逐个等」语义有微差。
# 段命令裸 exec 不经 shell：管道/重定向/||/env 注入请自包 bash -c 或 env 前缀；
# --then 是切段保留字不可作实参。段非零不中断后续段，整链 rc=首个非零段 rc。
# 口径：控制面戳写 --log（缺省 stdout，格式 [YYYY-MM-DD HH:MM:SS]）；段输出收
# --log-dir/segN.log（缺省直传）；尾行 DONE 戳供下游 --marker 接力自组合。
# 一律仓根相对执行（脚本自定位仓根）；凭证注入（bench.env 等）责任归调用方；
# 「等主链同时周期性干活」chaser/watchdog 模式刻意不泛化，需要时另开件。
set -uo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." || exit 1

POLL=60
LOG=""
LOGDIR=""
ANY=0
HITS=""
PIDS=()
PROCS=()
MARKF=()
MARKS=()
FLAGS=()

usage() {
  cat <<'EOF'
用法: tools/chain_runs.sh [触发件...] [选项] -- CMD [ARGS...] [--then CMD [ARGS...] ...]

触发件（可复数混给；默认全部终态才过闸，--any 任一命中即过）:
  --pid P         等 pid P 退出（kill -0 轮询）
  --proc PAT      等 pgrep -f PAT 无匹配（剔自身；外层常驻包装含 PAT 时改用 --pid $!）
  --marker F STR  等文件 F 内出现子串 STR（F 缺席=继续等）
  --flag F        等文件 F 存在

选项:
  --poll SEC      触发件轮询间隔秒（默认 60）
  --log FILE      控制面戳追加写 FILE（缺省 stdout）
  --log-dir DIR   段输出收 DIR/segN.log（缺省直传本进程 stdout/stderr）
  --any           任一触发件终态即过闸
  -h, --help      打本用法

口径: 仓根相对执行；段命令裸 exec 不经 shell（管道/重定向/||/env 请自包 bash -c 或
env 前缀）；段非零不中断，整链 rc=首个非零段 rc；尾行 DONE 戳可被下游 --marker 接力。

例: env $(cat ~/.config/texlate/bench.env) tools/chain_runs.sh \
      --log tmp/x/run.log --log-dir tmp/x --pid 12345 --marker tmp/x/up.log DONE \
      -- cmd1 arg --then bash -c 'cmd2 | tee tmp/x/o'
EOF
}

die() {
  echo "chain_runs: $*" >&2
  exit 2
}

log() {
  local line
  line="[$(date '+%F %T')] $*"
  if [ -n "$LOG" ]; then
    printf '%s\n' "$line" >>"$LOG"
  else
    printf '%s\n' "$line"
  fi
}

# 触发件清单文字化（wait-start 摘要用）
trig_desc() {
  local d="" p i
  for p in "${PIDS[@]}"; do d="$d pid:$p"; done
  for p in "${PROCS[@]}"; do d="$d proc:'$p'"; done
  for i in "${!MARKF[@]}"; do d="$d marker:${MARKF[$i]}~'${MARKS[$i]}'"; done
  for p in "${FLAGS[@]}"; do d="$d flag:$p"; done
  printf '%s' "${d# }"
}

# 单轮终态判定：四族各计 hit/tot，命中面写全局 HITS。
# AND=全中才过（条件皆 sticky 时等价逐个序贯等）；--any=任一命中即过。
gate_done() {
  local hit=0 tot=0 p i raw cand cppid alive
  HITS=""
  for p in "${PIDS[@]}"; do
    tot=$((tot + 1))
    if ! kill -0 "$p" 2>/dev/null; then
      hit=$((hit + 1))
      HITS="$HITS pid:$p"
    fi
  done
  for p in "${PROCS[@]}"; do
    tot=$((tot + 1))
    # pgrep 直出（勿写成 pgrep|grep 管道——管道子壳不 exec 会多一个克隆匹配）。
    # 候选剔两层：$$ 自身 + PPID=$$ 的子壳——$( ) 命令替换 fork 出的子壳不
    # exec、argv 即本脚本 argv（字面含 PAT）必中，它存活于 pgrep 扫描期、
    # 扫完即被 reap，实测不剔会永久假活。等闸期本脚本只 fork 探测件，
    # 真目标不会以我们为父，故 PPID=$$ 一律算探测残影；ps 取不到 ppid
    # 的（扫读间隙已死）不算活。
    raw=$(pgrep -f "$p" 2>/dev/null) || raw=""
    alive=0
    # shellcheck disable=SC2086 # raw 是纯数字 pid 列表，要靠分词迭代
    for cand in $raw; do
      [ "$cand" = "$$" ] && continue
      cppid=$(ps -o ppid= -p "$cand" 2>/dev/null) || continue
      [ "${cppid// /}" = "$$" ] && continue
      alive=1
      break
    done
    if [ "$alive" -eq 0 ]; then
      hit=$((hit + 1))
      HITS="$HITS proc:$p"
    fi
  done
  for i in "${!MARKF[@]}"; do
    tot=$((tot + 1))
    if [ -f "${MARKF[$i]}" ] && grep -qF -- "${MARKS[$i]}" "${MARKF[$i]}" 2>/dev/null; then
      hit=$((hit + 1))
      HITS="$HITS marker:${MARKF[$i]}"
    fi
  done
  for p in "${FLAGS[@]}"; do
    tot=$((tot + 1))
    if [ -f "$p" ]; then
      hit=$((hit + 1))
      HITS="$HITS flag:$p"
    fi
  done
  [ "$tot" -eq 0 ] && return 0
  if [ "$ANY" -eq 1 ]; then
    [ "$hit" -gt 0 ]
  else
    [ "$hit" -eq "$tot" ]
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
  --pid)
    [ $# -ge 2 ] || die "--pid 缺实参（用法见 -h）"
    [[ $2 =~ ^[0-9]+$ ]] || die "--pid 须为数字（收到 '$2'——若是 \$! 为空说明后台 pid 没传进来）"
    PIDS+=("$2")
    shift 2
    ;;
  --proc)
    [ $# -ge 2 ] || die "--proc 缺实参（用法见 -h）"
    PROCS+=("$2")
    shift 2
    ;;
  --marker)
    [ $# -ge 3 ] || die "--marker 要 FILE STR 两个实参（用法见 -h）"
    MARKF+=("$2")
    MARKS+=("$3")
    shift 3
    ;;
  --flag)
    [ $# -ge 2 ] || die "--flag 缺实参（用法见 -h）"
    FLAGS+=("$2")
    shift 2
    ;;
  --poll)
    [ $# -ge 2 ] || die "--poll 缺实参（用法见 -h）"
    POLL="$2"
    shift 2
    ;;
  --log)
    [ $# -ge 2 ] || die "--log 缺实参（用法见 -h）"
    LOG="$2"
    shift 2
    ;;
  --log-dir)
    [ $# -ge 2 ] || die "--log-dir 缺实参（用法见 -h）"
    LOGDIR="$2"
    shift 2
    ;;
  --any)
    ANY=1
    shift
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  --)
    shift
    break
    ;;
  *)
    echo "chain_runs: 未知参数 $1" >&2
    usage >&2
    exit 2
    ;;
  esac
done

[ $# -gt 0 ] || {
  echo "chain_runs: -- 后缺段命令" >&2
  usage >&2
  exit 2
}
{ [[ $POLL =~ ^[0-9]+$ ]] && [ "$POLL" -gt 0 ]; } || die "--poll 须为正整数秒（收到 '$POLL'）"
if [ "${#PROCS[@]}" -gt 0 ]; then
  command -v pgrep >/dev/null || die "--proc 需要 pgrep（procps）"
  command -v ps >/dev/null || die "--proc 需要 ps（procps）"
fi

TRIG=$((${#PIDS[@]} + ${#PROCS[@]} + ${#MARKF[@]} + ${#FLAGS[@]}))
[ -z "$LOG" ] || mkdir -p -- "$(dirname -- "$LOG")"
[ -z "$LOGDIR" ] || mkdir -p -- "$LOGDIR"

# 等闸：先判后睡（已终态秒过，对齐源件）
if [ "$TRIG" -gt 0 ]; then
  mode=and
  [ "$ANY" -eq 0 ] || mode=any
  log "wait-start mode=$mode poll=${POLL}s triggers: $(trig_desc)"
  until gate_done; do sleep "$POLL"; done
  log "wait-end hits:$HITS"
fi

# --then 切段：位参索引界；紧邻/首尾 --then = 空段拒收
SEG_LO=()
SEG_HI=()
lo=1
for ((i = 1; i <= $#; i++)); do
  if [ "${!i}" = "--then" ]; then
    [ "$i" -ne "$lo" ] || die "空段：--then 紧邻或居段首"
    SEG_LO+=("$lo")
    SEG_HI+=("$((i - 1))")
    lo=$((i + 1))
  fi
done
[ "$lo" -le "$#" ] || die "空段：--then 收尾"
SEG_LO+=("$lo")
SEG_HI+=("$#")
NSEG=${#SEG_LO[@]}

log "chain-start segs=$NSEG"
FIRST_RC=0
for ((s = 0; s < NSEG; s++)); do
  n=$((s + 1))
  a=${SEG_LO[$s]}
  len=$((SEG_HI[s] - a + 1))
  cmd=("${@:a:len}")
  log "seg$n START: ${cmd[*]}"
  if [ -n "$LOGDIR" ]; then
    "${cmd[@]}" >>"$LOGDIR/seg$n.log" 2>&1
  else
    "${cmd[@]}"
  fi
  rc=$?
  log "seg$n EXIT rc=$rc"
  if [ "$FIRST_RC" -eq 0 ] && [ "$rc" -ne 0 ]; then
    FIRST_RC=$rc
  fi
done
log "DONE segs=$NSEG firstrc=$FIRST_RC"
exit "$FIRST_RC"
