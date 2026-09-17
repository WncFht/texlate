# docs/ 索引与阅读序

> **分层规则**：实现照 **06–10** 执行；"为什么这么定"看 **05 裁决表**；**01–04** 是决策史快照（内容冻结，矛盾处以 05/06–10 为准）；**`research/`** 是全部实测证据档案。
> 规范文档的落地状态见各文末注记（07 §12、10 B1 等有落地记录）；改规范时遵守文末「修改纪律」。

| 文档                        | 内容                                                                    | 状态                                              |
| --------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------- |
| `01-tech-stack-decision.md` | ADR-001 技术栈选型（8 库横评 + 选型表）                                 | 决策快照（引擎默认已被 05 裁决 6 改判，文内有注） |
| `02-architecture.md`        | 架构总览：管线图 + 模块划分 + 目录结构                                  | 高层视图；逐模块实现规格以 06–10 为准             |
| `03-roadmap.md`             | 早期路线图 + hjfy 对标差异化表                                          | 里程碑已被 05 §6 / 10 §8 替代；对标表仍有效       |
| `04-selection-context.md`   | 选库/选 API 候选全景（决策输入）                                        | §12 待决清单已全部结案于 05 §3                    |
| `05-reproduction-plan.md`   | 复现方案：功能对齐表 / E1–E22 证据矩阵 / 22 条裁决 / 里程碑             | **裁决总表（冻结）**                              |
| `06-arxiv-source.md`        | arXiv 源获取层：在线端点/解包/缓存/降级/批量渠道                        | **现行规范**                                      |
| `07-latex-pipeline.md`      | LaTeX 半解析器 + 展开层全规范                                           | **现行规范**                                      |
| `08-translate-compile.md`   | 翻译编排 + 校验链 + 归一化 + 引擎 + fixloop                             | **现行规范**                                      |
| `09-benchmark-corpus.md`    | corpus_v3 语料构建管线（底材）                                          | **现行规范**                                      |
| `10-benchmark-suite.md`     | 评测器套件 B1–B7（评测器）                                              | **现行规范**                                      |
| `original.md`               | hjfy.top 实现原文（知乎存档，目标系统参照）                             | 归档原文                                          |
| `research/`                 | 调研/审计报告档案 + `research/README.md` 索引                           | 证据档案                                          |
| `tools-runbook.md`          | 工具与运维手册：产品 CLI / `scripts/` / `bench/py/` 全表 + 运维手法沉淀 | 现役手册（随工具增补更新）                        |
| `CONVENTIONS.md`            | 文档写作/维护约定：SUPERSEDED 横幅、research 索引登记、勘误引用粒度     | 现役约定                                          |
| `HANDOFF-2026-09-15.md`     | archbox 迁移交接：当日落地清单 + 全部剩余工作 inventory                 | 运维交接（随里程碑更新）                          |
| `HANDOFF-2026-09-16.md`     | v2 产品面切换日交接：17 commit 全录 + 剩余项                            | 运维交接（随里程碑更新）                          |

后置规范暂居 research/（M3 时再提正）：`research/product/web-layer.md`（API/前端/BYOK/部署）、`research/latex/{pdf-path,doc-formats}.md`（PDF sidecar / EPUB/DOCX）、`research/arxiv/licensing.md`（法务）。

## 修改纪律

- 改规范（06–10）时若推翻 05 §3 裁决表条目 → 同步改 05，并在规范行文补证据出处。
- 新实验证据进 `docs/research/`；规范只引用、不复述实测细节。
- 01–04 不追改内容；裁决发生变化时在对应文档加状态注记而非改写历史。
- 文档维护约定（SUPERSEDED 横幅 / research 索引登记 / 勘误引用粒度）见 [`CONVENTIONS.md`](CONVENTIONS.md)；行号锚点均为时点快照。
