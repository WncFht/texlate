# `dev/` — 贡献者文档索引

面向要改代码、跑评测、维护文档的贡献者。先读 `repository.md` 建立仓库全貌，再按需求取件。

| 文件                  | 内容                                                                                                                               |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `repository.md`       | 仓库布局与代码现状基线：各包职责、入口面、约定                                                                                     |
| `tools-runbook.md`    | 工具与运维手册：产品 CLI 简表、`scripts/` 全脚本、`bench/py/` 评测器与批跑件分域清单、`bench/ts/` 与 `web/` 冒烟工具、运维手法沉淀 |
| `benches.md`          | bench/ 全量普查表：每个 bench 是什么/怎么跑/吃什么吐什么/成本/状态（2026-09-20 口径）                                              |
| `bench-redesign-v2-trizone.md` | bench 终态设计：三区账本法——事件账唯一事实源 + 字节按再生成本分区 + fail-closed 付费裁决，绿地口径不设历史兼容面；架构总览图 `assets/trizone-arch.svg`，`bench/py/kernel/` 已按图落地并验收（2026-09-22） |
| `bench-redesign-plan.md` | bench 重做早期方案（thin-runner + 薄门面）：已被 v2 取代，留档备查                                                                |
| `assets/`             | dev 文档图源与渲染件（`trizone-arch.{tex,pdf,svg,png}`，TikZ + xelatex 可重编）                                                   |
| `errsweep-runbook.md` | errsweep 清扫 agent 完整工作指令与人工审计契约（`scripts/errsweep.sh` 每日喂给 agent 的文本）                                      |
| `bench-harness.md`    | 评测协议与分层契约：L0–L3 问题归层规则、四项评测内容、fixtures 字节即语义纪律、corpus 层化布局、`bench/results/` 工具链豁免        |
| `automation.md`       | 每日自动化系统：arXiv 日更 soak（2026-09-21 退役，留档）与 errsweep（错误沉淀→根因蒸馏修复，在役）的设计与操作契约                |
| `seams.md`            | 测试补丁缝纪律：惰性门面 patch 叶子、注册表 setitem、LoopCtx 平名转写；改动时的两侧义务与已登记接缝清单                            |

上手序：建仓环境（`uv sync` + 格式化工具链，见 `repository.md`）→ 文档维护规则 `../MAINTENANCE.md` → 改动对应层跑对应级验证（`bench-harness.md` §1）。
