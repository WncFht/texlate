#!/bin/bash
# 重建 Claude Code 本机技能入口；AGENTS.md 原生加载，不创建 CLAUDE.md。
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -L CLAUDE.md ]]; then
  if [[ $(readlink CLAUDE.md) != AGENTS.md ]]; then
    echo "error: CLAUDE.md 指向外部位置，拒绝修改" >&2
    exit 1
  fi
elif [[ -e CLAUDE.md ]]; then
  echo "error: CLAUDE.md 是实体文件，请先合并到 AGENTS.md" >&2
  exit 1
fi

if [[ -L .claude/skills ]]; then
  if [[ $(readlink .claude/skills) != ../.agents/skills ]]; then
    echo "error: .claude/skills 指向外部位置，拒绝修改" >&2
    exit 1
  fi
elif [[ -e .claude/skills ]]; then
  if [[ ! -d .claude/skills ]]; then
    echo "error: .claude/skills 不是目录，拒绝修改" >&2
    exit 1
  fi
  # 只迁移本机制创建的逐技能链接；先核验全部条目，再删除已知旧链接。
  shopt -s nullglob dotglob
  for dest in .claude/skills/*; do
    if [[ ! -L $dest || $(readlink "$dest") != "../../.agents/skills/${dest##*/}" ]]; then
      echo "error: $dest 是实体或外来链接，拒绝修改" >&2
      exit 1
    fi
  done
  for dest in .claude/skills/*; do
    unlink "$dest"
  done
  rmdir .claude/skills
fi

mkdir -p .claude .agents/skills
if [[ ! -L .claude/skills ]]; then
  ln -s ../.agents/skills .claude/skills
fi
if [[ -L CLAUDE.md ]]; then
  unlink CLAUDE.md
fi
echo "linked: .claude/skills -> ../.agents/skills"
