# parse-v3-full baseline — 2026-09-16

## 范围/方法

- 全集 = core 1000 + booster 187（13 篇 stub 无 extracted/ 自动跳过）+ hot 72 = **1259 篇 / 3937 .tex**；expand 3800 篇不在 manifest 抽样框内未覆盖。
- hardlink farm `tmp/exp/corpus-cbh/`（cp -al；symlink 不行——顶层 rglob 不跟进 symlink 子目录），合并 manifest 1272 行在 farm 根。
- src 冻结 `tmp/exp/src-snapshot-parse/`；parsebench 无 TEXLATE_SRC 接缝 → wrapper `tmp/exp/run_parsebench_snap.py` 预 import 钉死 sys.modules（assert 已验证）。双臂 `--v2`，wall 893.8s。
- warning 明细：files.jsonl 的 warn_kinds 只记数 → `tmp/exp/warn_detail_scan.py` 对 190 个 v2 warning 文件补扫出 `warnings-v2.jsonl`（kind/pos/detail 逐条）。

## 头条（v2 产品臂 | v1 对照）

- parse ok **3937/3937 = 100%**（双臂）；measure_error 0
- identity：**v2 strict 3937/3937 = 100%**；v1 3935/0/2
- leak：**v2 95/226622 = 0.042%**（dollar 92 / ref 3 / cite 2）；v1 92/216126
- vtex_vs_src 展开足迹：strict 3812 / normalized 48 / diverged 77（diverged 集中在 pstricks*/pst-node/.rtx/table*.tex 重型宏件，是展开机净改动非失败）
- dead CHUNK ph / protect ph / orphan chunks / bug1 ph-tail = 0
- 门槛：ok/identity/leak/dead 全 PASS；flatten coverage 86.6% BELOW（orphan tex 是 e-print 真实属性，docs/09 §8 已勘误）
- v2 wall p50/p95 = 28/404ms（v1 6/189——v2 约 4-5× 慢，预期内）

## 关键发现

1. **v1 仅有的 2 个 diverged 在 v2 下消失**：2407.21783（new/hot）`\resizebox{..}{!}{\input{...}}`——flatten 展开参数内 \input 而 v1 不回填；v2 gullet 内联展开正确。
2. **dollar 泄漏主形态 = 注释内/未配对 `$`**：v2-only 最大单文件 2410.05959/ichep2024.tex（5 chunk）是 `%\emph{{... $t\bar{t}W$ ...}}` 注释行留在可译 chunk、`$..$` 未占位化。与 unpaired_dollar warning（172 条）同源。
3. **warning 直方图**（704 条）：missing_input 293（epsf×28/xy×11/amstex×8/tcilatex×5/psfig.sty×5——旧 era 系统宏件未随附）、unpaired_dollar 172、unclosed_env 114（figure×87 集中 0707.3972）、stray_end 74、def_parse_fail 27、if_unterminated 11、gen_overflow 9（gen>=32 展开深度闸）、env_mismatch 4。
4. **unresolved_inputs**：79 文件 224 个，两族——旧 era 无扩展名 `\input{epsf|amstex|xy|...}` + 新 era 缺图/缺表（figures/fig_*、acknow.tex×4）；皆语料缺件非解析缺陷。
5. era 分层（v2）：new/booster 0.026%、new/core 0.048%、new/hot 0.052%、old/booster 0.049%、old/core 0.035%——leak 率跨层均匀无 era 退化；泄漏论文 40 篇（new 36/old 4）。

## 复现

`uv run python tmp/exp/run_parsebench_snap.py --corpus tmp/exp/corpus-cbh --v2 --out bench/results/parse-v3-full-2026-09-16`（files.jsonl 行在=done 可续跑）；warning 明细补扫 `uv run python tmp/exp/warn_detail_scan.py`。
