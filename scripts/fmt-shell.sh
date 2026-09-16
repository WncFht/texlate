#!/bin/bash
# git-format-staged 的 stdin→stdout formatter（见 .pre-commit-config.yaml）。
# shfmt/shellcheck 只认 sh/bash/dash/ksh：shebang 为 zsh 的脚本原样透传，
# 其余按 bash 语法以 2 空格缩进格式化。
set -e
# read 在两种边界上返回非零：空输入（first 为空 → 原样透传）与无尾换行的
# 单行文件（first 有值 → 照常走格式化，shfmt 会补尾换行）。
IFS= read -r first || [ -n "$first" ] || exit 0
case "$first" in
# 只认 shebang——首行注释里出现 "zsh" 字样的 bash 脚本不该被透传跳过
'#!'*zsh*) {
  printf '%s\n' "$first"
  cat
} ;;
*) {
  printf '%s\n' "$first"
  cat
} | shfmt -i 2 ;;
esac
