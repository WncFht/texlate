#!/bin/bash
# loc.sh — 仓库代码量统计（口径：git 跟踪文件，剔除生成数据快照）。
#
# 本仓 bench/results/ 入库了大量评测 JSON 快照（百万行级），裸 cloc 会把数据
# 当代码；所以先 git ls-files 圈定跟踪集，再按目录分桶 + 剔数据后缀。
# 未跟踪的新文件单列一档（开发中未提交量）。依赖: cloc、git。
# 用法: scripts/loc.sh [--cloc]（--cloc 追加 cloc 语言分布表）
set -euo pipefail
cd "$(dirname "$0")/.."

buckets="src tests web bench docs scripts"
data_re='\.(json|jsonl|csv|parquet|pdf)$'

echo "== 手写代码行数（git 跟踪、剔数据文件）=="
total=0
for d in $buckets; do
  n=$(git ls-files "$d" | grep -vE "$data_re" | xargs wc -l 2>/dev/null | tail -1 | awk '{print $1}')
  printf '%-10s %8s\n' "$d" "${n:-0}"
  total=$((total + ${n:-0}))
done
printf '%-10s %8s\n' TOTAL "$total"

echo
echo "== 未跟踪新文件（开发中未提交）=="
git ls-files --others --exclude-standard | grep -vE "$data_re" | xargs wc -l 2>/dev/null | tail -5 || true

echo
echo "== 生成数据快照（单列，不算开发量）=="
git ls-files | grep -E "$data_re" | xargs wc -l 2>/dev/null | tail -1 || true

if [[ ${1:-} == --cloc ]]; then
  echo
  echo "== cloc 语言分布 =="
  git ls-files | grep -vE "$data_re" >/tmp/texlate-loc-files.txt
  cloc --list-file=/tmp/texlate-loc-files.txt --quiet
fi
