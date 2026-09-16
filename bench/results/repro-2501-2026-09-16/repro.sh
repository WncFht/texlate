#!/bin/sh
# repro-2501-2026-09-16 — 复现与验证命令（仓库根目录下执行）
# 任务现场：/tmp/tw-8932/tasks/t_1eb25aae917fc304/
set -eu

TASK=/tmp/tw-8932/tasks/t_1eb25aae917fc304

# --- 缺陷 A 复现：源级 \DeclareUnicodeCharacter undefined under XeTeX ---------
# 原始 zh build（管线已产出、含译文）直接编译 → 10 个 DUC/Missing-begin 错
cp -r "$TASK/build-zh" /tmp/duc-baseline
mkdir -p /tmp/duc-baseline/_out
cd /tmp/duc-baseline
tectonic --color never -X compile --untrusted --keep-logs \
  --outdir _out -Z continue-on-errors main.tex || true
grep -c "^!" _out/main.log                 # → 14（9 DUC + 1 Missing-\begin{document} + 4 xcolor）
grep -n "DeclareUnicodeCharacter" main.tex # → l.88-96 共 9 处调用

# en 臂同炸证明（源级，非 zh 特有）：
grep -c "^!" "$TASK/build-en/_tect_out/main.log" # → 10（同 9 DUC + 1 级联，无 xcolor）

# --- 缺陷 A 修复验证：normalize_engine 注入 shim 后编译 ----------------------
cd /home/fanghaotian/src/texlate
cp -r "$TASK/build-zh" /tmp/duc-norm-test
uv run python - <<'PY'
# 等价于管线 normalize 后新文件形态：旧 XETEX_COMPATIBILITY 块 → 新块（含 shim）
old = open("/tmp/duc-norm-test/main.tex").read()
anchor = "\\typeout{TeXlate-PostScript-object: #1}\\TeXlatePstObject{#1}}%\n\\fi\n}\n"
shim = anchor + (
    "\\providecommand{\\DeclareUnicodeCharacter}[2]{%\n"
    "\\begingroup\\lccode`\\~=\"#1\\relax\n"
    "\\lowercase{\\endgroup\\catcode`\\~\\active\\protected\\def~}{#2}}\n"
)
assert old.count(anchor) == 1
open("/tmp/duc-norm-test/main.tex", "w").write(old.replace(anchor, shim))
PY
cd /tmp/duc-norm-test && mkdir -p _tect_out
tectonic --color never -X compile --untrusted --keep-logs \
  --keep-intermediates --outdir _tect_out -Z continue-on-errors main.tex || true
grep -c "^!" _tect_out/main.log # → 4（DUC 全清，仅剩缺陷 B 残留的 xcolor）
ls -la _tect_out/main.pdf       # → ~888 KB

# --- 缺陷 B 复现：TRANSPARENT 遮蔽 argspec，色名进 chunk --------------------
uv run python - <<'PY'
from texlate.latex.segmenter import parse_tex_v2
tex = r"\documentclass{article}\usepackage{xcolor}\begin{document}" \
      r"The \textcolor{blue}{output} here exceeds threshold.\end{document}"
res = parse_tex_v2(tex)
print(res.chunks[0].content)
# 现状：'The \\textcolor{blue}{output} here ...'  —— {blue} 在 chunk 内被翻译
# 修复后：'The \\textcolor[[KEY_1]]{output} ...'  —— 色名出 [[KEY]] 不译
PY

# --- 缺陷 B 修复验证：影子树（现树 + patch）---------------------------------
git apply bench/results/repro-2501-2026-09-16/tables.py.patch \
  bench/results/repro-2501-2026-09-16/segmenter.py.patch # 须同批
uv run python /tmp/duc-repro/verify_shadow.py            # mini×3 identity TRUE + 真文 672 chunks
uv run python /tmp/duc-repro/verify_diff.py              # base vs shadow：672→672, ph +2, 仅 chunk 383 语义变
PYTHONPATH=/tmp/texlate-shadow uv run pytest tests/ \
  -k "segmenter or expand or latex or parse or recon or placeholder or argspec" -x -q
# → 536 passed
