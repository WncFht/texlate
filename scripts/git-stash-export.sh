#!/bin/sh
# git-stash-export.sh [stash@{N}] [outdir] — 无损导出 stash 两棵树到 scratch。
#
# stash@{N} 内含 tracked 提交 + ^3 untracked 提交。本脚本只读 stash，
# 不动工作区/索引——恢复时各 agent 自行 `git show "stash@{N}:f" > f`
# （只写工作区）或 `git checkout stash@{N} -- paths`（会写索引，慎用——
# 曾把队友暂存的 hunk 卷进自己的 commit）。绝不整 `git stash pop`。
# 产出：outdir/{tracked,untracked}/ + MANIFEST.txt + 前缀校验提示。
# 出处：2026-09-16 stash -u/pop 并发事故手工取证固化（transcript-mining 取证记录 484a9c38 §A1）。
set -eu
# 与兄弟脚本同规钉仓根：stash 操作对象是本仓，默认 outdir 落在 gitignored tmp/
cd "$(dirname "$0")/.."

S="${1:-stash@{0}}"
O=${2:-tmp/stash-export-$(date +%Y%m%d-%H%M%S)}

git rev-parse --verify -q "$S" >/dev/null || {
  echo "error: no such stash ref: $S" >&2
  exit 1
}

mkdir -p "$O/tracked" "$O/untracked"

# while-read 防路径含空格被 for+分词劈碎（行内换行的文件名仍然救不了）
# core.quotePath=false 出原始 UTF-8——默认 C-quote 把中文名包成 "\344\270…"，
# 喂给 git show 必失败，会被误判成 "deleted in stash" 静默丢档
# 名单取一次落地 .tracked.lst：导出循环与 MANIFEST 同源，账实一致
# stash 里 deleted 的文件 git show 会失败——记档跳过而非 set -e 中断整批导出
git -c core.quotePath=false stash show --name-only "$S" >"$O/.tracked.lst"
while IFS= read -r f; do
  mkdir -p "$O/tracked/$(dirname "$f")"
  if ! git show "$S:$f" >"$O/tracked/$f" 2>/dev/null; then
    rm -f "$O/tracked/$f"
    echo "  skip (deleted in stash): $f"
  fi
done <"$O/.tracked.lst"

# ^3 = untracked 提交（stash -u 才有；无则跳过——先 verify，避免 tar 吞空输入报错）
if git rev-parse --verify -q "$S^3" >/dev/null; then
  git archive "$S^3" | tar -x -C "$O/untracked/"
fi

{
  echo "# tracked:"
  cat "$O/.tracked.lst"
  echo "# untracked (^3):"
  git -c core.quotePath=false ls-tree -r "$S^3" --name-only 2>/dev/null || echo "(no untracked tree)"
} >"$O/MANIFEST.txt"

echo "exported $(find "$O" -type f | wc -l | tr -d ' ') files -> $O"
echo "恢复: git show \"$S:<path>\" > <path>   (只写工作区, 不动索引)"
