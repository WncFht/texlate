#!/bin/sh
# git-stash-export.sh [stash@{N}] [outdir] — 无损导出 stash 两棵树到 scratch。
#
# stash@{N} 内含 tracked 提交 + ^3 untracked 提交。本脚本只读 stash，
# 不动工作区/索引——恢复时各 agent 自行 `git show "stash@{N}:f" > f`
# （只写工作区）或 `git checkout stash@{N} -- paths`（会写索引，慎用——
# 曾把队友暂存的 hunk 卷进自己的 commit）。绝不整 `git stash pop`。
# 产出：outdir/{tracked,untracked}/ + MANIFEST.txt + 前缀校验提示。
# 出处：2026-09-16 stash -u/pop 并发事故手工取证固化（tmp/transcript-mining/484a9c38.md A1）。
set -eu
S="${1:-stash@{0}}"
O=${2:-tmp/stash-export-$(date +%Y%m%d-%H%M%S)}

mkdir -p "$O/tracked" "$O/untracked"

for f in $(git stash show --name-only "$S"); do
  mkdir -p "$O/tracked/$(dirname "$f")"
  git show "$S:$f" >"$O/tracked/$f"
done

# ^3 = untracked 提交（stash -u 才有；无则跳过）
git archive "$S^3" 2>/dev/null | tar -x -C "$O/untracked/" || true

{
  echo "# tracked:"
  git stash show --name-only "$S"
  echo "# untracked (^3):"
  git ls-tree -r "$S^3" --name-only 2>/dev/null || echo "(no untracked tree)"
} >"$O/MANIFEST.txt"

echo "exported $(find "$O" -type f | wc -l | tr -d ' ') files -> $O"
echo "恢复: git show \"$S:<path>\" > <path>   (只写工作区, 不动索引)"
