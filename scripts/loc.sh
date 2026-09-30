#!/bin/bash
# loc.sh — 仓库代码量统计（口径：git 跟踪文件，剔除生成数据快照）。
#
# 评测 JSON 快照不入跟踪（旧 bench/results/ 已删），但 corpus
# manifest 等数据文件仍在跟踪集；先 git ls-files 圈定，再按目录分桶剔数据后缀。
# 分桶口径：buckets 具名桶 + 根级文件 (root) + 兜底 (other)（带 / 但未认领的
#   跟踪路径——新顶层目录不会再静默漏计）；exclude_dirs 显式排除
#   .agents（vendor+生成 skill 资产）、shots（纯 PNG 截图）、.vscode（编辑器配置）。
# 未跟踪的新文件单列一档（开发中未提交量）。依赖: cloc、git。
# 用法: scripts/loc.sh [--cloc]（--cloc 追加 cloc 语言分布表）
set -euo pipefail
cd "$(dirname "$0")/.."

buckets="src tests web bench docs scripts zotero .github"
exclude_dirs=".agents shots .vscode"
# 数据/生成/二进制后缀：lock 文件、图片、字体度量等不算手写行
data_re='\.(json|jsonl|jsonc|csv|parquet|pdf|lock|png|jpe?g|gif|svg|ico|xpi|zip|whl|tfm)$'
# 具名桶+排除单合成认领前缀正则（sed 把 .github/.agents 的点转义成字面点）
claimed_re="^($(printf '%s\n' $buckets $exclude_dirs | sed 's/\./\\./g' | paste -sd'|' -))/"

echo "== 手写代码行数（git 跟踪、剔数据文件）=="
total=0
for d in $buckets; do
  # 桶内零命中时 grep 返回 1——包一层防 pipefail 把整脚本带走；-z/-0 防空格文件名被分词
  # wc 同样要兜：index 里还在但工作区已删的文件（在飞删除/改名）会让 wc 报错、
  # xargs 以 123 收尾——wc 仍会印出可读文件的 total，跳过缺失项继续即可
  n=$(git ls-files -z "$d" | { grep -zvE "$data_re" || true; } | { xargs -0r wc -l 2>/dev/null || true; } | tail -1 | awk '{print $1}')
  printf '%-10s %8s\n' "$d" "${n:-0}"
  total=$((total + ${n:-0}))
done
# 根级文件（路径无 /）自成一桶——AGENTS.md/pyproject.toml/ruff.toml 等不入任何目录桶
n=$(git ls-files -z | { grep -zvE "$data_re" || true; } | grep -zv / | { xargs -0r wc -l 2>/dev/null || true; } | tail -1 | awk '{print $1}')
printf '%-10s %8s\n' "(root)" "${n:-0}"
total=$((total + ${n:-0}))
# 兜底桶：带 / 但未被具名桶/排除单认领的路径——新增顶层目录在此显形而非漏计
n=$(git ls-files -z | { grep -zvE "$data_re" || true; } | grep -z / | { grep -zvE "$claimed_re" || true; } | { xargs -0r wc -l 2>/dev/null || true; } | tail -1 | awk '{print $1}')
printf '%-10s %8s\n' "(other)" "${n:-0}"
total=$((total + ${n:-0}))
printf '%-10s %8s\n' TOTAL "$total"

echo
echo "== 未跟踪新文件（开发中未提交）=="
git ls-files -z --others --exclude-standard | { grep -zvE "$data_re" || true; } | xargs -0r wc -l 2>/dev/null | tail -5 || true

echo
echo "== 生成数据快照（单列，不算开发量）=="
git ls-files -z | { grep -zE "$data_re" || true; } | xargs -0r wc -l 2>/dev/null | tail -1 || true

if [[ ${1:-} == --cloc ]]; then
  echo
  echo "== cloc 语言分布 =="
  # cloc --list-file 只认换行分隔，故这里保留行式输出；mktemp 防并行会话互写
  flist=$(mktemp "${TMPDIR:-/tmp}/texlate-loc-files.XXXXXX")
  # core.quotepath=false 出原始 UTF-8——默认 C-quote 会让 cloc 静默跳过 CJK 名文件
  git -c core.quotepath=false ls-files | { grep -vE "$data_re" || true; } >"$flist"
  cloc --list-file="$flist" --quiet
  rm -f "$flist"
fi
