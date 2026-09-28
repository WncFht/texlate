# research/methods/ —— 方法学域

评测与改进的方法学调研档案：语料怎么抽、指标怎么命名、质量怎么评、失败怎么挖、缺陷怎么量化。主题是「做法的依据」，与 `spec/`（实现现状的唯一事实源）互为证据—规范两面；实证读数类档案同时服务 `decisions/` 的裁决追溯。

## 索引

| 文件                                                                         | 内容                                                                                                                                                           |
| ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [bench-construction-methods.md](bench-construction-methods.md)               | Benchmark 语料构建方法学：20 个先例的抽样方式/规模论证/发布形态对比，两阶段月簇抽样 + 特征配额的先例链与统计方法菜单（Wilson/rule-of-three/deff/事后分层加权） |
| [parse-metrics-literature.md](parse-metrics-literature.md)                   | 解析/转换质量度量文献：LaTeXML severity 四态、unarXive 漏斗+Wilson CI、olmOCR-bench unit-test 断言范式、GROBID 匹配档位 → 指标命名映射表                       |
| [2026-09-18-xlat-quality-eval.md](2026-09-18-xlat-quality-eval.md)           | 翻译质量评估方法：MQM/ESA/GEMBA 谱系、judge 自偏好偏差、统计口径（block bootstrap/acc23）→ qualbench ESA 协议设计（已落地 protocol_v=esa2）                    |
| [2026-09-18-xlat-selfimp-prompt.md](2026-09-18-xlat-selfimp-prompt.md)       | 自改进环协议：dense-feedback 四层反馈塔（L0 确定性→L1 探针→L2 批层→L3 人锚）+ 20 lane 三波次车队结构                                                           |
| [2026-09-19-selfimp-skeleton.md](2026-09-19-selfimp-skeleton.md)             | 自改进假设池快照：open/adopted/rejected/blocked 四态，假设写法范式（机制→证据指针→修法→判死线）与已验证收割记录                                                |
| [2026-09-16-signature-mining.md](2026-09-16-signature-mining.md)             | 失败签名 × strata 挖掘方法：多臂编译结果按 era×学科组交叉统计产出 fixloop 规则候选，含 fires 对账与 replay 验收标准                                            |
| [2026-09-18-layout-defects-bench.md](2026-09-18-layout-defects-bench.md)     | 版式损伤 bench：ctex zihao 字号膨胀与 CJK 不可断段落双根因的机制链、A/B 量化与证伪记录（修复已落地 inject 层）                                                 |
| [2026-09-19-bench-metrics-corpusv3.md](2026-09-19-bench-metrics-corpusv3.md) | corpus_v3 全量综合测试指标总表：12 臂逐臂读数、失败类分布、已知缺口与过程教训                                                                                  |
| [metrics-2026-09-19/](metrics-2026-09-19/)                                   | 评测体系全景报告工程：LaTeX 报告源码 + PDF + 全部原始数据（时间线 CSV/commit 全录/大事记），自包含可重建                                                       |
| [agent-pipeline-baseline-2026-09-28/](agent-pipeline-baseline-2026-09-28/)   | agent 直翻 vs texlate 管线双臂基线：同模型同网关同 10 篇逐篇 token/质量/时效账 + v4 ph 重发病理定位——v5 对照臂底稿                                             |

## 阅读建议

找「为什么这么评」先读 `parse-metrics-literature.md` 与 `2026-09-18-xlat-quality-eval.md`；找「语料为什么这样抽」读 `bench-construction-methods.md`；找「现在水平到哪」读 `2026-09-19-bench-metrics-corpusv3.md` 或 `metrics-2026-09-19/report.pdf`；找「怎么持续改进」读 `2026-09-18-xlat-selfimp-prompt.md` + `2026-09-19-selfimp-skeleton.md`。
