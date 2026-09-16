#!/bin/bash
# 重建 Claude Code 的本机入口软链：
#   CLAUDE.md -> AGENTS.md
#   .claude/skills/<name> -> ../../.agents/skills/<name>
# AGENTS.md 与 .agents/ 是入库的唯一事实源；/CLAUDE.md 与 /.claude/ 整体
# gitignore，属本机便利层。clone 后或链接损坏时跑一遍本脚本即可恢复。
set -euo pipefail
cd "$(dirname "$0")/.."

# CLAUDE.md 为实体文件时拒绝覆盖——那可能是未入库的真文档，ln -sfn 会无声吞掉
if [[ -e CLAUDE.md && ! -L CLAUDE.md ]]; then
  echo "error: CLAUDE.md 是实体文件而非软链，先手工处置（移走或删除）" >&2
  exit 1
fi
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

# .agents/skills 里已消失的 skill 会留下 dangling 软链——只清指向本机制目标的
for dest in .claude/skills/*; do
  [[ -L $dest ]] || continue
  case $(readlink "$dest") in
  ../../.agents/skills/*)
    [[ -e $dest ]] || {
      rm "$dest"
      echo "pruned dangling: $dest"
    }
    ;;
  esac
done

echo "linked: CLAUDE.md -> AGENTS.md"
echo "linked: .claude/skills/* -> ../../.agents/skills/*"
