# metrics-2026-09-19 —— TeXlate 评测体系与指标演化全景报告

> **结论**：TeXlate 评测体系的全景报告工程——上半部分为管线架构与评测套件设计背景，下半部分是全部历史 commit 考古出的指标演化时间线、2026-09-19 corpus_v3 全量 13,266 篇综合测试画像、失败归因图谱与十条 takeaway。Markdown 摘要版见同域 `2026-09-19-bench-metrics-corpusv3.md`。
> **状态**：时点证据（2026-09-19 口径）。报告自包含：所有图表由随档 `data/` 原始数据经 pgfplots 生成，不依赖本目录以外的路径。
> **日期**：2026-09-19（2026-09-20 迁入）

## 文件说明

| 件                         | 说明                                                                                                                                                                                                                                                                    |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `report.tex` + `sec-*.tex` | 报告源码：主文件 + 七节（background / bench / history / snapshot / failures / takeaway / appendix）                                                                                                                                                                     |
| `report.pdf`               | 编译产物，直接可读                                                                                                                                                                                                                                                      |
| `data/`                    | 全部原始数据：六条时间线 CSV（scorecard / parse / corpus / rules-tests / qual-xlat / commits-by-day 每日 commit 数）、`arms_history.csv` 377 行评测流水（各轮 run 目录名+样本量+头条读数）、`commits.json` 1,648 条 commit 全录（敏感串已脱敏）、`milestones.md` 大事记 |
| `refs/`                    | 上一期复盘的两张图（`metrics-timeline.svg`、`assets-growth.svg`）；原档的源文档快照（评测器/语料规格、机制台账等）未随迁——对应正文档案见 `research/` 各域与 `spec/`                                                                                                     |
| `make_readme_figs.py`      | README 图生成脚本（matplotlib，读 `data/` CSV 写 PNG）；机器相关件（字体路径）需按环境调整                                                                                                                                                                              |
| `bench-pipeline.html`      | 管线架构图的 diagram-design 源文件（playwright 导出 PNG 的源头），非构建产物，保留作图源                                                                                                                                                                                |

## 复现构建

```bash
latexmk -xelatex report.tex   # 或 xelatex ×2；需 ctex/pgfplots/tikz 全套
```

图全部内联由 `data/` 生成，无需外部图片。`make_readme_figs.py` 是独立的 README 图脚本（与报告 PDF 无关）：`python3 make_readme_figs.py`（需 matplotlib + CJK 字体，输出到上层 `shots/`）。

## 溯源

各臂原始评测产物（编译工作区、译文 jsonl、PDF 中间件）为大体量文件未入档；按 `data/arms_history.csv` 的 run 目录名在主仓评测产物存档区（`bench/results/` 轮次目录）查找对应轮次。构建垃圾（aux/log/fls/xdv 等）已丢弃；refs/ 中源文档快照因目标档案已收录于本库其他域而未随迁，报告正文对此的「随档 refs/」表述以本 README 为准。
