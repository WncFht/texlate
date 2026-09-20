# research/ —— 调研档案索引

「为什么这么设计」的证据层，按域分区：`arxiv/` 获取层、`latex/` 解析与编译、`corpus/` 语料构建、`methods/` 评测方法学、`product/` 产品与生态。实现现状的唯一事实源在 `spec/`——本层文件是决策当时的取证与推理，与代码漂移处以代码为准；逐件状态标在各文件头（现行 / 时点证据 / SUPERSEDED / 已落地）。过程性探针日志、命令行与会话叙事已按写作约定削除，结论与数字保留。

## 域索引

| 域 | 内容 | 件数 |
| --- | --- | --- |
| [arxiv/](arxiv/) | arXiv 端点行为、限流纪律、e-print 形态、OAI-PMH、批量渠道、许可边界、HTML/PDF 降级链、规模化路线 | 12 + 索引 |
| [latex/](latex/) | 展开机设计、gullet/segmenter 切换、引擎矩阵、fixloop 规则引擎、占位符/术语表规格、校验器两档、CTAN 补给链、PDF 通路、对齐探针 | 18 + 索引 |
| [corpus/](corpus/) | corpus_v3 设计、分层 frame、IA/HF 渠道实测、post-2020 裁决、expand 层落地、ICLR 章节研究 | 13 + 索引 |
| [methods/](methods/) | 语料构建方法学、解析/翻译质量度量文献、自改进协议、失败签名挖掘、版式损伤 bench、corpus_v3 指标总表、评测体系报告工程 | 9 + 索引 |
| [product/](product/) | hjfy.top 侦察与竞品、Web 层设计取证（SUPERSEDED）、Web 性能审计、共享缓存、E2E 验证、agent/工具生态、alphaXiv/papers.cool 逆向、引用图谱生态 20 lane | 15 + 索引 |
| [errsweep/](errsweep/) | 每日 errsweep agent 错误清扫报告（根因修复蒸馏层的工作档案，契约见 `dev/errsweep-runbook.md`） | 索引 |

## 顶层单件

| 文件 | 内容 |
| --- | --- |
| [model-selection.md](model-selection.md) | 翻译模型选型实证：占位符契约一票否决制横评（网关调研蒸馏件——原 `gateway/` 九件涉内部部署细节不入库，结论、方法学、供给面类型学与 fg/bg 准入设计全部蒸馏于此） |
| [bibliography.md](bibliography.md) | 文献清单：unarXive/arXMLiv/S2ORC/PDFMathTranslate/BabelDOC/Nougat/olmOCR 等 11 项参照系 + 残档判定注记（`lit/` 二进制原件不入库） |

## 阅读建议

- 想懂「产品是什么」：`product/hjfy-site.md` → `product/competitors.md` → `spec/architecture.md`。
- 想懂「技术方案从哪来」：`decisions/` ADR 是本层的结论面——每个 ADR 的脚注指回本层取证件。
- 想懂「为什么是这个模型/协议/引擎」：`model-selection.md`、`latex/engine-matrix.md`、`product/e2e-mock-pipeline.md`。
- 想找某项数字的出处：先按域进子目录 README，索引表逐件标了「结论 + 状态」。
