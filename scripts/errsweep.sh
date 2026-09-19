#!/usr/bin/env bash
# errsweep.sh — 定时清扫沉淀错误 → 根因修复（幂等、flock 单实例、systemd-timer 友好）。
#
#   git worktree 隔离分支 → claude -p 按 docs/errsweep-runbook.md 蒸馏修复
#
# 设计：docs/errsweep-runbook.md（流程/纪律/报告协议全在那）。
# 调度建议：每日 18:23（soak 批 10:30 起跑沉淀大半天后）由 systemd --user timer 触发。
# 隔离：主树常态 dirty + 多会话在飞——清扫一律在 errsweep/<date> 分支 worktree 里跑，
#   产物=分支 commit + ~/.local/state/texlate/errsweep-<date>-report.md 摘要。
set -uo pipefail

ROOT="/home/fanghaotian/src/texlate"
# systemd --user 环境 PATH 不含 ~/.local/bin（claude/uv 所在）——补齐保险
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

STATE="$HOME/.local/state/texlate"
mkdir -p "$STATE"

DATE="$(date +%F)"
exec >>"$STATE/errsweep-$DATE.log" 2>&1

echo "===== errsweep run $(date '+%F %T %Z') ====="

# 单实例闸
exec 9>"$STATE/errsweep.lock"
if ! flock -n 9; then
  echo "another errsweep run holds the lock — exit"
  exit 0
fi

cd "$ROOT" || exit 1

# 网关凭证——systemd --user 干净环境不继承会话 ANTHROPIC_*，必须显式 source
# shellcheck disable=SC1091
[ -f "$HOME/.config/texlate/errsweep.env" ] && . "$HOME/.config/texlate/errsweep.env"

BR="errsweep/$DATE"
WT="$STATE/errsweep-wt-$DATE"
REPLAY_DIR="$STATE/replay-$DATE"
mkdir -p "$REPLAY_DIR"

# worktree 闸：当日 worktree 已存在说明跑过/在跑——幂等退出，不叠跑
if [ -d "$WT" ]; then
  echo "worktree $WT already exists — prior run review pending or in flight, exit"
  exit 0
fi

# 分支已存在（同日重跑且旧 worktree 已清）→ 复用；否则从 HEAD 开新分支
if git show-ref --verify --quiet "refs/heads/$BR"; then
  git worktree add "$WT" "$BR" || exit 1
else
  git worktree add "$WT" -b "$BR" HEAD || exit 1
fi
echo "worktree: $WT  branch: $BR"

cd "$WT" || exit 1

# 嵌套会话防护：剥 CLAUDECODE 类 env 再起 headless 实例
# prompt 必须紧跟 -p——--add-dir 是 variadic，会把后面的裸位置参当目录吞掉
# --add-dir 双授权：~/.texlate（DB/workdir，只读语义）+ 主仓根（未入库 soak 结果）
# timeout 6h 保险丝：模型免费不设预算闸，但防真卡死空转（正常一跑 <2h）
timeout 6h env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT claude -p \
  "你是 texlate errsweep agent，今天是 $DATE，工作目录是分支 $BR 的隔离 worktree。完整工作指令在 docs/errsweep-runbook.md——先通读再开工。要点：soak 结果在主仓 $ROOT/bench/results/soak-*/ 下（worktree 里未必有，经 --add-dir 读）；回放副本放 $REPLAY_DIR；报告除随分支提交外复制一份到 $STATE/errsweep-$DATE-report.md。" \
  --dangerously-skip-permissions \
  --add-dir "$HOME/.texlate" \
  --add-dir "$ROOT"

rc=$?

# 后验：agent 自述不算数——ruleset 能否加载是客观证（在 worktree 内跑，测的是分支态规则库）
cd "$WT" && uv run python -c "from texlate.compile.fixloop.ruleset import Ruleset; Ruleset.load()" \
  && echo "post-check: Ruleset.load OK" || echo "post-check: Ruleset.load FAIL"

echo "===== errsweep done rc=$rc $(date '+%F %T %Z') ====="
exit $rc
