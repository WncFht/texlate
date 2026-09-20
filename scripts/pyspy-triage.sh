#!/bin/bash
# pyspy-triage.sh — 「栈零位移」钉栈三板斧：对疑似死循环/ReDoS 的 python 进程
# 做 N 次 py-spy dump，全样本栈签名一致 + CPU 前进 = 疑似卡死自旋。
# 手法固化自 2026-09-16 ReDoS 事故：三采样零位移钉 _TAIL_RX.match() 于
# mainloop.py:764（%[^\n]* 变长片在 (?:_WS_NOPAR)* 下 2^N 回溯爆炸）。
#
# 判定（栈签名 = dump 里全部 frame 行 `    func (file:line)` 的逐项比对）：
#   签名逐样本全同 + utime+stime 前进 → STUCK   exit 1（疑似死循环/ReDoS）
#   签名逐样本全同 + CPU 零前进       → IDLE    exit 3（阻塞在 IO/锁，非自旋）
#   签名有变动                        → MOVING  exit 0（健康推进）
#   参数错/采样失败/进程消失          →         exit 2
# 注意：零位移单独不定罪——sleep/阻塞读栈也纹丝不动，必须叠加 CPU 增量区分。
#
# 用法: scripts/pyspy-triage.sh <PID> [-n 采样数=3] [-i 间隔秒=5] [-o 输出目录]
# 覆盖: PYSPY_BIN（py-spy 路径，默认 PATH 查找）；输出目录缺省
#       tmp/pyspy-triage/<pid>-<ts>/（仓内 gitignored scratch，别写 /tmp——
#       usrquota tmpfs 有 EDQUOT 事故史）。
set -euo pipefail
cd "$(dirname "$0")/.."

usage() {
  echo "usage: $0 <PID> [-n samples=3] [-i interval-sec=5] [-o outdir]" >&2
  exit 2
}

PID=""
N=3
INTERVAL=5
OUT=""
while [[ $# -gt 0 ]]; do
  case $1 in
  -n | --samples)
    N=${2:?"missing value for $1"}
    shift 2
    ;;
  -i | --interval)
    INTERVAL=${2:?"missing value for $1"}
    shift 2
    ;;
  -o | --out)
    OUT=${2:?"missing value for $1"}
    shift 2
    ;;
  -h | --help)
    sed -n '2,20p' "$0"
    exit 0
    ;;
  -*)
    echo "error: unknown flag: $1" >&2
    usage
    ;;
  *)
    [[ -z $PID ]] || {
      echo "error: 多余位置参数: $1" >&2
      usage
    }
    PID=$1
    shift
    ;;
  esac
done

[[ $PID =~ ^[0-9]+$ ]] || {
  echo "error: PID 必须是数字: '${PID:-<空>}'" >&2
  usage
}
[[ $N =~ ^[0-9]+$ && $N -ge 2 ]] || {
  echo "error: 采样数需 >=2 的整数: '$N'" >&2
  exit 2
}
[[ $INTERVAL =~ ^[0-9]+$ && $INTERVAL -ge 1 ]] || {
  echo "error: 间隔需 >=1 的整数秒: '$INTERVAL'" >&2
  exit 2
}
[[ -d /proc/$PID ]] || {
  echo "error: /proc/$PID 不存在——进程已退出或非本机 PID" >&2
  exit 2
}

PYSPY=${PYSPY_BIN:-py-spy}
command -v "$PYSPY" >/dev/null || {
  echo "error: 找不到 py-spy（$PYSPY）。安装: cargo install py-spy / uv tool install py-spy；" >&2
  echo "       或用 PYSPY_BIN=<path> 指定。应急替代: python -X faulthandler 起目标进程" >&2
  echo "       + faulthandler.dump_traceback_later（见 docs/dev/tools-runbook.md §5.2）。" >&2
  exit 2
}

OUT=${OUT:-tmp/pyspy-triage/${PID}-$(date +%Y%m%d-%H%M%S)}
mkdir -p "$OUT"

# utime+stime（field 14/15，jiffies）。comm 可含空格与 ')'，取最后一个 ')' 之后
# 的字段切片再数列。
cpu_jiffies() {
  local stat rest
  stat=$(<"/proc/$1/stat") || return 1
  rest=${stat##*) }
  local -a fields
  read -r -a fields <<<"$rest"
  echo $((fields[11] + fields[12]))
}

CMD=$(tr '\0' ' ' <"/proc/$PID/cmdline" 2>/dev/null || true)
echo "== pyspy-triage: pid=$PID n=$N interval=${INTERVAL}s =="
echo "cmd: ${CMD:-?}"
echo "out: $OUT"

J0=$(cpu_jiffies "$PID") || {
  echo "error: /proc/$PID/stat 读取失败（进程刚退出？）" >&2
  exit 2
}

declare -a SIGS=()
TOPS=()
for i in $(seq 1 "$N"); do
  sfile="$OUT/sample-$i.txt"
  if [[ ! -d /proc/$PID ]]; then
    echo "error: pid $PID 在第 $i 次采样前消失" >&2
    exit 2
  fi
  if ! "$PYSPY" dump --pid "$PID" >"$sfile" 2>"$OUT/sample-$i.err"; then
    echo "error: py-spy dump 失败（样本 $i）：" >&2
    sed 's/^/  /' "$OUT/sample-$i.err" >&2
    echo "  （权限不够试 sudo；进程已退则案发现场没了）" >&2
    exit 2
  fi
  # 栈签名：只收 4 空格缩进的 frame 行（Thread/Process 头行不进签名——
  # 头行含线程 id，与位移判定无关）
  sig=$(grep -E '^    \S' "$sfile" | sha256sum | cut -d' ' -f1)
  SIGS+=("$sig")
  top=$(grep -m1 -E '^    \S' "$sfile" | sed 's/^    //')
  TOPS+=("$top")
  echo "  sample $i: sig=${sig:0:12} top=${top:-<无 frame>}"
  [[ $i -lt $N ]] && sleep "$INTERVAL"
done

J1=$(cpu_jiffies "$PID" 2>/dev/null || echo "$J0")
DJ=$((J1 - J0))

identical=1
for i in $(seq 1 $((N - 1))); do
  [[ ${SIGS[$i]} == "${SIGS[0]}" ]] || {
    identical=0
    break
  }
done

top_identical=1
for i in $(seq 1 $((N - 1))); do
  [[ ${TOPS[$i]} == "${TOPS[0]}" ]] || {
    top_identical=0
    break
  }
done

if [[ $identical == 1 && $DJ -gt 0 ]]; then
  VERDICT="STUCK"
  RC=1
  WHY="栈零位移 + CPU 前进 ${DJ} jiffies——疑似死循环/ReDoS 自旋"
elif [[ $identical == 1 ]]; then
  VERDICT="IDLE"
  RC=3
  WHY="栈零位移但 CPU 零前进——阻塞在 IO/锁/sleep，非自旋（若要仍怀疑，加大 -i 再测）"
else
  VERDICT="MOVING"
  RC=0
  WHY="栈签名逐样本有变动——健康推进"
fi

{
  echo "pyspy-triage report"
  echo "pid:     $PID"
  echo "cmd:     ${CMD:-?}"
  echo "samples: $N x ${INTERVAL}s   py-spy: $(command -v "$PYSPY")"
  echo "cpu:     $J0 -> $J1 jiffies (+$DJ)"
  echo "verdict: $VERDICT — $WHY"
  echo "top-frame 逐样本一致性: $([[ $top_identical == 1 ]] && echo 全同 || echo 有变)"
  [[ $top_identical == 1 ]] && echo "top-frame: ${TOPS[0]}"
  echo "dumps:   $OUT/sample-{1..$N}.txt"
} | tee "$OUT/report.txt"

exit "$RC"
