# research/ —— 调研档案索引

「为什么这么设计」的证据层，按域分区：`arxiv/` 获取层、`latex/` 解析与编译、`corpus/` 语料构建、`methods/` 评测方法学、`product/` 产品与生态。实现现状的唯一事实源在 `spec/`——本层文件是决策当时的取证与推理，与代码漂移处以代码为准；逐件状态标在各文件头（现行 / 时点证据 / 已改判 / 已落地 / 已完成；被取代件另加 SUPERSEDED 横幅）。过程性探针日志、命令行与会话叙事已按写作约定删除，结论与数字保留。

## 域索引

| 域                     | 内容                                                                                                                                                                                                       | 件数      |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| [arxiv/](arxiv/)       | arXiv 端点行为、限流纪律、e-print 形态、OAI-PMH、批量渠道、许可边界、HTML/PDF 降级链、规模化路线                                                                                                           | 13 + 索引 |
| [latex/](latex/)       | 展开机设计、gullet/segmenter 切换、引擎矩阵、fixloop 规则引擎、占位符/术语表规格、校验器两档、CTAN 补给链、PDF 通路、对齐探针                                                                              | 18 + 索引 |
| [corpus/](corpus/)     | corpus_v3 设计、分层 frame、IA/HF 渠道实测、post-2020 裁决、expand 层落地、ICLR 章节研究                                                                                                                   | 13 + 索引 |
| [methods/](methods/)   | 语料构建方法学、解析/翻译质量度量文献、自改进协议、失败标记挖掘、版式损伤 bench、corpus_v3 指标总表、评测体系报告工程                                                                                      | 9 + 索引  |
| [product/](product/)   | hjfy.top 侦察与竞品、Web 层设计取证（SUPERSEDED）、Web 性能审计、PDF 暗色渲染实测、共享缓存、E2E 验证、agent/工具生态、alphaXiv/papers.cool 逆向、引用图谱生态 20 lane、引用跳转/悬浮卡生态 126-agent 调研 | 19 + 索引 |
| [errsweep/](errsweep/) | 每日 errsweep agent 错误清扫报告（根因修复提炼层的工作档案，契约见 `dev/errsweep-runbook.md`）                                                                                                             | 索引      |

## 顶层单件

| 文件                                     | 内容                                                                                                                                                          |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [model-selection.md](model-selection.md) | 翻译模型选型实证：占位符契约一票否决制横评（网关调研提炼件——原 `gateway/` 九件涉内部部署细节不入库，结论、方法学、供给面类型学与 fg/bg 准入设计全部提炼于此） |
| [bibliography.md](bibliography.md)       | 文献清单：unarXive/arXMLiv/S2ORC/PDFMathTranslate/BabelDOC/Nougat/olmOCR 等 11 项参照系 + 残档判定注记（`lit/` 二进制原件不入库）                             |

## 删除清单

2026-09-20 文档库重建（`5ebc9797`）对旧顶层件分两类处置。**迁移**（非删除，已按域归位并改前缀日期名）：`audit-2026-09-16/`、`roadmap-2026-09-17/` → `../log/`；`metrics-2026-09-19/`、`selfimp-skeleton.md`、`xlat-quality-eval-2026-09-18.md`、`xlat-selfimp-prompt-2026-09-18.md`、`2026-09-18-layout-defects-bench.md`、`2026-09-19-bench-metrics-corpusv3.md` → `methods/`；`2026-09-19-iclr章节长度.md` → `corpus/`；`2026-09-19-select-popup-方案调研.md`、`2026-09-19-流程图skill调研.md`、`review3-web-perf-2026-09-19` 等产品域件 → `product/`。**有意删除**（过程性叙事删除、结论与数字保留，非丢失）：`overseer-2026-09-16.md`（编排台账）、`overseer-selfimp.md`、`selfimp-2026-09-18.md`（自改进 lane 台账，结论提炼入 `methods/2026-09-18-xlat-selfimp-prompt.md` 与 `methods/2026-09-19-selfimp-skeleton.md`）、`reaudit-2026-09-18.md`、`batchmodel-2026-09-18.md`、`infra-repair-2026-09-19.md`、`refactor-survey-2026-09-19.md`、`report-2026-09-17-final.md`、`2026-09-16-loop1-status-and-next.md`、`2026-09-19-web-frontend-audit.md`，目录件 `packaging-2026-09-19/`、`refactor-audit-2026-09-17/`、`review-2026-09-18/`、`review-web-2026-09-17/`、`review2-web-2026-09-17/`、`gateway/`（涉内部部署细节，结论已提炼入 `model-selection.md`）。原文按 `../MAINTENANCE.md` §10 经 git 历史检索（`git show 5ebc9797^:<路径>`），工作树副本在 `tmp/old-docs-2026-09-20/`。

## 阅读建议

（路径口径：此处裸写路径均为 `research/` 相对；`spec/` 前缀指 `docs/spec/`，`docs/` 前缀为仓根相对。）

- 想懂「产品是什么」：`product/2026-09-14-hjfy-site.md` → `product/2026-09-14-competitors.md` → `spec/architecture.md`。
- 想懂「技术方案从哪来」：`docs/decisions/` ADR 是本层证据的结论面——每个 ADR 的脚注指回本层取证件。
- 想懂「为什么是这个模型/协议/引擎」：`model-selection.md`、`latex/engine-matrix.md`、`product/2026-09-14-e2e-mock-pipeline.md`。
- 想找某项数字的出处：先按域进子目录 README，索引表逐件标了「结论 + 状态」。
