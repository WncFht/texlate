# TeXlate 文档

TeXlate 将 arXiv LaTeX 源码翻译并重编译成中文 PDF，提供双语阅读器。使用从[快速开始](guide/quickstart.md)进入，开发从[开发与验证](dev/development.md)进入。本文是统一导航；维护要求见[文档维护契约](MAINTENANCE.md)，Agent 入口见 [AGENTS.md](AGENTS.md)。

## 使用

| 文档                                | 任务                             |
| ----------------------------------- | -------------------------------- |
| [快速开始](guide/quickstart.md)     | 安装、自检与首次翻译             |
| [命令行](guide/cli.md)              | 取源、翻译、工具管理与远端调用   |
| [Web 服务](guide/web.md)            | 启动、阅读、上传、部署与故障恢复 |
| [渠道与密钥](guide/byok.md)         | 配置模型渠道、凭据和配额         |
| [导出与共享](guide/export-share.md) | EPUB、DOCX 与共享译文包          |

## 当前契约

| 文档                                                                                           | 内容                           |
| ---------------------------------------------------------------------------------------------- | ------------------------------ |
| [架构](spec/architecture.md)                                                                   | 管线、模块责任与部署边界       |
| [arXiv 获取](spec/arxiv-source.md) · [ID 归一化](spec/arxiv-id-canon.md)                       | 源码、版本、缓存与安全解包     |
| [解析](spec/latex-pipeline.md) · [翻译](spec/translate.md) · [校验](spec/validate.md)          | 块、占位符、重试与回写         |
| [编译与修复](spec/compile.md)                                                                  | 引擎、判定、规则与沙箱         |
| [服务端](spec/server.md)                                                                       | 任务、凭据、渠道、上传与留存   |
| [阅读器](spec/reader.md) · [对齐](spec/reader-alignment.md) · [解码器](spec/seqpos-decoder.md) | 导航、引用、源码复制与双语定位 |
| [语料](spec/corpus.md) · [评测](spec/benchmark.md)                                             | 样本、分层、指标与评测器       |
| [评测账本与资产](spec/bench-trizone.md) · [版面质检](spec/layoutqc.md)                         | 持久性、付费边界、判分与归因   |
| [术语与冻结名](spec/glossary.md)                                                               | 数据键、协议名称与同名对象     |

## 开发

[开发与验证](dev/development.md)说明环境、检查和诊断；[代码约定](dev/conventions.md)说明命名、注释和测试替换位置；[运行评测](dev/bench.md)说明计划、成本、恢复与存储。决策理由按主题维护在 [Agent Notes](../.agents/notes/README.md)，不另建 ADR 或工程日志目录。

## 实验与依据

以下报告归并历史实验，测量日期、样本与限制写在各篇正文中，不代表当前版本重新跑出的结果。

| 报告                                                    | 内容                                  |
| ------------------------------------------------------- | ------------------------------------- |
| [获取与语料](research/2026-10-16-获取与语料实验.md)     | 获取渠道、抽样与许可                  |
| [解析与校验](research/2026-10-16-解析与校验实验.md)     | identity、泄漏、展开与破坏检测        |
| [编译与修复](research/2026-10-16-编译与修复实验.md)     | 引擎覆盖、修复规则与失败恢复          |
| [对齐与阅读器](research/2026-10-16-对齐与阅读器实验.md) | 锚点、文本复制、主题和引用交互        |
| [端到端评测](research/2026-10-16-端到端评测.md)         | 交付分母、去重、失败归因与版面回放    |
| [评测方法](research/2026-10-16-评测方法.md)             | 抽样、质量评审与 token 成本的解释边界 |
| [存储经验](research/2026-10-16-评测存储经验.md)         | 付费字节、恢复、硬链接与备份          |
| [产品路线依据](research/2026-10-16-产品路线依据.md)     | 已采用的机制与尚未实施的方向          |

原始证据包保留[三臂对照](research/methods/agent-pipeline-baseline-2026-09-28/README.md)、[token 实测](research/methods/token-economy-2026-10-03/README.md)、[早期评测报告](research/methods/metrics-2026-09-19/README.md)和[引用调研数据](research/product/citation-ux-2026-09-21/README.md)。报告需要的结构化数据、图表、脚本和 LaTeX 源码随包维护。
