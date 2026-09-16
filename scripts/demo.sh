#!/bin/bash
# demo.sh — texlate 端到端冒烟演示：fetch → parse → mock run → （可选）真翻译。
#
# 全程走产品面（texlate CLI / e2e_real_bench），每步产出让用户看得见。
# 默认样例 2105.11479：21KB article 小品，mock 全链 ~25s、真翻 ~25s。
# 用法: scripts/demo.sh [arxiv_id] [--real]（--real 追加网关真翻译段）
# 前置: uv sync；真翻需网关可达（100.105.212.52:3003 或本地隧道 127.0.0.1:3003）
set -euo pipefail
cd "$(dirname "$0")/.."

ID=2105.11479
REAL=0
for a in "$@"; do
  case $a in
  --real) REAL=1 ;;
  *) ID=$a ;;
  esac
done
WORK=$(mktemp -d "/tmp/texlate-demo-$ID.XXXXXX")

echo "=== 1/4 fetch: $ID ==="
uv run texlate fetch "$ID"

# 多版本目录（v1/v2/…）取版本号最大者——head -1 的 glob 序会拾到旧版
MAIN_TEX=$(find "$HOME/.cache/texlate/src/${ID}v"*"/extracted" -name '*.tex' 2>/dev/null | sort -V | tail -1)
[[ -n $MAIN_TEX ]] || {
  echo "error: fetch 未在 ~/.cache/texlate/src/${ID}v*/extracted 产出 .tex" >&2
  exit 1
}
echo "main_tex: $MAIN_TEX"

echo
echo "=== 2/4 parse（v2 Gullet+Segmenter）==="
uv run texlate parse "$MAIN_TEX" -o "$WORK-chunks.jsonl"
echo "逐块明细: $WORK-chunks.jsonl"
head -3 "$WORK-chunks.jsonl" | python3 -c "
import json, sys
for line in sys.stdin:
    c = json.loads(line)
    print(f'  [{c[\"context\"]}] {c[\"content\"][:80]!r}')"

echo
echo "=== 3/4 mock run（不触网，全链产品 API）==="
timeout 300 uv run texlate run "$ID" --keep -w "$WORK"
PDF=$(find "$WORK" -name '*.pdf' | head -1)
[[ -n $PDF ]] || {
  echo "error: mock run 未产出 PDF（工作区 $WORK，看上方 run 输出）" >&2
  exit 1
}
echo
echo "--- pdftotext 验 CJK 进 PDF ---"
if command -v pdftotext >/dev/null; then
  pdftotext "$PDF" - 2>/dev/null | grep -m5 -E '[一-鿿]' || echo "(未检出中文字符——看 verdict)"
else
  echo "(无 pdftotext，跳过 CJK 验证)"
fi

if [[ $REAL == 1 ]]; then
  echo
  echo "=== 4/4 真翻译（swe-2-medium 经网关）==="
  GW=${TEXLATE_BASE_URL:-http://127.0.0.1:3003}
  curl -s -o /dev/null -w "gw healthz: %{http_code}\n" -m 5 "$GW/healthz" || true
  timeout 600 uv run python bench/py/e2e_real_bench.py \
    --ids "$ID" --base-url "$GW" --model swe-2-medium --base never --tag demo | tail -15
else
  echo
  echo "=== 4/4 真翻译（跳过，--real 开启；需网关）==="
fi

echo
echo "demo 产物: $WORK （chunks: $WORK-chunks.jsonl）"
