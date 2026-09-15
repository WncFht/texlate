# parsebench v2full1955 基线报告 — 2026-09-16

> HEAD `4e06299` 快照（worktree 隔离，S3 改动前基线）。
> 数据：`bench/results/parsebench-v2full1955-2026-09-16/`（files.jsonl / papers.json / summary.md）。
> 命令：`.venv/bin/python <wt>/bench/py/parsebench.py --corpus bench/corpus_v3 --v2`，wall 209.2s。

## 头条数字（v1 | v2）

| 指标 | v1 (scanner) | v2 (segmenter) |
|---|---|---|
| parse ok | 1955/1955 | 1955/1955 |
| identity strict | **1955** | **1954**（1 diverged，见下） |
| vtex_vs_src strict | — | 1955 |
| Σ chunks | 135120 | 115273 |
| leaked chunks | **57**（全 dollar） | **3979** |
| dead_ph warn | — | **18345** |
| wall ms p50 / p95 / max | 7 / 43 / — | 35 / 175 / — |
| unresolved_inputs | 111 | 0（v2 吃展平文本，missing_input warn 137/64 文件） |
| flatten coverage | 94.4%（1837/1945，orphan 108 + rootless 10） | — |

## v2 leak 分类（Σ3979）

| kind | n | 对 dual200 基线（214 文件 Σ3396） |
|---|---|---|
| begin_env | 2599 | 3040 → 主文件样本占比高所致 |
| ref_family | 851 | 295 |
| dollar | 587 | 110 |
| cite_family | 52 | （dual200 未单列） |
| conditional | 50 | 17 |
| input_include | 0 | 3 |

top leak 文件：hep-th/9910156 review.tex 104、0905.1757 pdotaph2.tex 90(ref)、
2203.13026 ljdvdd-v3.tex 90、0806.0463 per2.tex 87(ref)、hep-th/0501177 86、
hep-ph/9703402 higgs.tex 85、0806.1019 ros22.tex 80。

## 与 dual200 预期的偏差

- **新增 1 例 v2 identity diverged**：`1803.09012/extracted/nitin_rheath_bigamp.tex`
  （recon quick_ratio 0.7137，first_diff_at=80678）。dual200 是 214/214 strict——
  全量暴露的孤例，S3 期间需单独归因。
- dead_ph 4501→18345（随文件数放大，S1 中途态预期产物，S3 接线后应清零）。
- v2 chunks 总量 115273 < v1 135120（~85%），与 dual200 的 chunk recall ~0.88 中位一致。
- 性能 v2 p50 35ms ≈ v1 的 5×，p95 175ms，S5 需出性能曲线。
- v1 侧基线全绿：identity 100%、leak 0.04%（57 dollar）、dead/orphan 0。
- flatten coverage 94.4% BELOW 是已知口径勘误项（orphan 大头=随附 tex）。

## S3 收口目标（对照用）

leak 3979 → 应近 v1 量级（~57）；dead_ph 18345 → 0；identity diverged 1 → 0；
unresolved/missing_input 口径待 S4 `\input` 接线后再评。
