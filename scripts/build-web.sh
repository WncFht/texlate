#!/bin/bash
# 构建 web SPA 并把产物同步进 src/texlate/server/static/：
#   npm ci → vite build（web/dist）→ 拷入包内 static/（gitignored）
# 产物由 app.py 尾部 mount 到 /（texlate web 起服即 SPA）；wheel 经
# pyproject [tool.hatch.build] artifacts 携带，uv tool install 后可用。
# 用法：scripts/build-web.sh [--no-install]（--no-install 跳过 npm ci）
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ${1:-} != --no-install ]]; then
  npm ci --prefix web
fi
npm run --prefix web build

static=src/texlate/server/static
rm -rf "$static"
mkdir -p "$static"
cp -R web/dist/. "$static/"

count=$(find "$static" -type f | wc -l)
echo "web/dist → $static ($count files)"
echo "验证：uv run texlate web 后 curl -s 127.0.0.1:8765/ 应返回 index.html"
