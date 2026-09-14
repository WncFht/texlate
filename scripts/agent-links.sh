#!/bin/bash
# 重建 Claude Code 的本机入口软链：
#   CLAUDE.md -> AGENTS.md
#   .claude/skills/<name> -> ../../.agents/skills/<name>
# AGENTS.md 与 .agents/ 是入库的唯一事实源；/CLAUDE.md 与 /.claude/ 整体
# gitignore，属本机便利层。clone 后或链接损坏时跑一遍本脚本即可恢复。
set -euo pipefail
cd "$(dirname "$0")/.."

ln -sfn AGENTS.md CLAUDE.md

mkdir -p .claude/skills .agents/skills
shopt -s nullglob # 仓内还没有 skill 时 glob 留空,避免生成字面 `*` 软链
for skill in .agents/skills/*/; do
  name=${skill%/}
  name=${name##*/}
  dest=".claude/skills/$name"
  # 目标是真实目录而非软链时拒绝覆盖：那是未迁移的 skill 本体，先手工处置
  if [[ -e $dest && ! -L $dest ]]; then
    echo "error: $dest exists as a real directory; move it into .agents/skills/ first" >&2
    exit 1
  fi
  ln -sfn "../../.agents/skills/$name" "$dest"
done

echo "linked: CLAUDE.md -> AGENTS.md"
echo "linked: .claude/skills/* -> ../../.agents/skills/*"
