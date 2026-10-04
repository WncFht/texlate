# research/methods/ —— 方法学域

评测与改进的方法学调研档案：语料怎么抽、指标怎么命名、质量怎么评、失败怎么挖、缺陷怎么量化。主题是「做法的依据」，与 `spec/`（实现现状的唯一事实源）互为证据—规范两面；实证读数类档案同时服务 `decisions/` 的裁决追溯。

## 索引

| 文件                                                                                               | 内容                                                                                                                                                           |
| -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [bench-construction-methods.md](bench-construction-methods.md)                                     | Benchmark 语料构建方法学：20 个先例的抽样方式/规模论证/发布形态对比，两阶段月簇抽样 + 特征配额的先例链与统计方法菜单（Wilson/rule-of-three/deff/事后分层加权） |
| [parse-metrics-literature.md](parse-metrics-literature.md)                                         | 解析/转换质量度量文献：LaTeXML severity 四态、unarXive 漏斗+Wilson CI、olmOCR-bench unit-test 断言范式、GROBID 匹配档位 → 指标命名映射表                       |
| [2026-09-18-xlat-quality-eval.md](2026-09-18-xlat-quality-eval.md)                                 | 翻译质量评估方法：MQM/ESA/GEMBA 谱系、judge 自偏好偏差、统计口径（block bootstrap/acc23）→ qualbench ESA 协议设计（已落地 protocol_v=esa2）                    |
| [2026-09-18-xlat-selfimp-prompt.md](2026-09-18-xlat-selfimp-prompt.md)                             | 自改进环协议：dense-feedback 四层反馈塔（L0 确定性→L1 探针→L2 批层→L3 人锚）+ 20 lane 三波次车队结构                                                           |
| [2026-09-19-selfimp-skeleton.md](2026-09-19-selfimp-skeleton.md)                                   | 自改进假设池快照：open/adopted/rejected/blocked 四态，假设写法范式（机制→证据指针→修法→判死线）与已验证收割记录                                                |
| [2026-09-16-signature-mining.md](2026-09-16-signature-mining.md)                                   | 失败签名 × strata 挖掘方法：多臂编译结果按 era×学科组交叉统计产出 fixloop 规则候选，含 fires 对账与 replay 验收标准                                            |
| [2026-09-18-layout-defects-bench.md](2026-09-18-layout-defects-bench.md)                           | 版式损伤 bench：ctex zihao 字号膨胀与 CJK 不可断段落双根因的机制链、A/B 量化与证伪记录（修复已落地 inject 层）                                                 |
| [2026-09-19-bench-metrics-corpusv3.md](2026-09-19-bench-metrics-corpusv3.md)                       | corpus_v3 全量综合测试指标总表：12 臂逐臂读数、失败类分布、已知缺口与过程教训                                                                                  |
| [metrics-2026-09-19/](metrics-2026-09-19/)                                                         | 评测体系全景报告工程：LaTeX 报告源码 + PDF + 全部原始数据（时间线 CSV/commit 全录/大事记），自包含可重建                                                       |
| [agent-pipeline-baseline-2026-09-28/](agent-pipeline-baseline-2026-09-28/)                         | agent 直翻 vs texlate 管线双臂基线：同模型同网关同 10 篇逐篇 token/质量/时效账 + v4 ph 重发病理定位——v5 对照臂底稿                                             |
| [2026-09-29-keep-roster-and-values-truncation.md](2026-09-29-keep-roster-and-values-truncation.md) | v5 调用膨胀归因（ph 密集 member 梯级重试风暴）+ values 截断 QE 零效应实测 + v6 keep 名单落地形态记录                                                           |
| [2026-10-02-e2e-eval-holdout200.md](2026-10-02-e2e-eval-holdout200.md)                             | holdout-200 冻帧全链路评测：抽样设计/逐 stage 终态账/fixloop 修复判决面/绝版件死因归因/付费账——zh 交付 85.5%，e-era CS 覆盖缺口与 CS 专项帧动机                |
| [2026-10-02-compilecensus-5000.md](2026-10-02-compilecensus-5000.md)                               | 5000 篇原文直编普查：缺件面现状——missing_file 占 fail 92%、91% 撞件 vendor 已备、死因集中 2012 前物理/天文绝版宏包，CS 缺件率 4.7%                             |
| [2026-10-03-e2e-eval-cs200.md](2026-10-03-e2e-eval-cs200.md)                                       | 新 CS 论文 200 篇专项冻帧评测：zh 交付 95.5%（对通用帧 +10pt）、fixloop 51 试 50 救、不可交付 78% 压在 xlat 块故障——编译链对新 CS 近无损                       |
| [token-economy-2026-10-03/](token-economy-2026-10-03/)                                             | token 用量两路解剖：当前实现 vs agent 直翻逐篇账（新输入 23%、总输入 2.0%）、输入组成分解、占位符重头篇逐调用剖析与报文实例、生产 200 篇口径交叉验证           |
| [2026-10-04-e2e-eval-cs800.md](2026-10-04-e2e-eval-cs800.md)                                       | 新 CS 800 篇放大冻帧评测：zh 交付 74.3% 头读数全为限流账（429 风暴 11h/91.8k 拒发烧 144 格），健康窗 e-era 段 92.7% 贴平 base、fixloop 修复 98.3% 复现        |

## 阅读建议

找「为什么这么评」先读 `parse-metrics-literature.md` 与 `2026-09-18-xlat-quality-eval.md`；找「语料为什么这样抽」读 `bench-construction-methods.md`；找「现在水平到哪」读 `2026-09-19-bench-metrics-corpusv3.md` 或 `metrics-2026-09-19/report.pdf`；找「怎么持续改进」读 `2026-09-18-xlat-selfimp-prompt.md` + `2026-09-19-selfimp-skeleton.md`。
