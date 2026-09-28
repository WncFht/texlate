# research/arxiv/ —— arXiv 获取层调研档案

arXiv 侧的取证与设计档案：端点行为、限流纪律、e-print 形态、元数据通道、批量渠道、降级链、许可边界与规模化路线。`arxiv/` 模块的实现现状唯一事实源在 `spec/`；本域是「为什么这么设计」的证据层，读数类档案均为标注口径日期的时点证据。

## 索引

| 文件                                                           | 内容（结论 + 状态）                                                                                                                                                          |
| -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [layer.md](layer.md)                                           | 获取层总报告：三主机限流桶、e-print 四态、降级链 L1→L3、钉版缓存——**现行**（§8 bulk/§9 引用排序标注未落地）                                                                  |
| [probes.md](probes.md)                                         | arxiv.org 探针实录：§A 端点机制（content-disposition 三态/304/旧 id 归一/license 位/HTML 版本矩阵）+ §B 规模面（版本表/v-diff 复用率/190 探针统计）——**时点证据 2026-09-14** |
| [export-probes.md](export-probes.md)                           | export.arxiv.org 探针：Atom 429 时间线、OAI 301 迁移、镜像端点表、path 级限流——**时点证据 2026-09-14**                                                                       |
| [oai-pmh.md](oai-pmh.md)                                       | OAI-PMH 端点：四格式字段矩阵、license 独占、resumptionToken 语义、独立限流桶——**时点证据**（GetRecord arXivRaw 兜底已落地 meta.py）                                          |
| [bulk-channels.md](bulk-channels.md)                           | 批量渠道 13 行总表 + 直采拐点核算（≤2k 直采 / 凑 N 篇走 tar / 散选走 S3）+ 新鲜度对比——**时点证据 2026-09-14**                                                               |
| [licensing.md](licensing.md)                                   | 许可体系与译文再分发法务边界：non-exclusive 第三方零权利、分布统计（全量 60.3%/近窗 46.6%）、机读入口、产品 gate 分层——**现行**（统计为 2026-09 口径）                       |
| [html-path.md](html-path.md)                                   | L2 HTML 降级路：LaTeXML DOM 事实、叶选择器分块规格、原子占位符、1:1 锚、stub 检测、交错注入决策——**已落地**（元素 key 锚注记）                                               |
| [pdf-fidelity.md](pdf-fidelity.md)                             | 官方 PDF vs 自编译保真度对拍：15 篇锚/页漂移表，跨引擎锚不可借用（1/15 对齐）——**时点证据**（结论否决了借锚路线，落地走自编译 en.pdf）                                       |
| [arxiv-to-prompt.md](arxiv-to-prompt.md)                       | arxiv-to-prompt 0.14.1 解剖：抓取/定位/展平/裁剪四块对照 + 实测翻车记录 + 可借鉴清单——**现行**（缓存原子发布已借入 cache.py）                                                |
| [paper-search-assets.md](paper-search-assets.md)               | 六源检索 CLI 解剖：OpenAlex 引用校准模式（enrich_citations）、各源认证门槛、可搬零件层——**时点证据 2026-09-14**（校准链路未落地）                                            |
| [2026-09-19-scale-roadmap.md](2026-09-19-scale-roadmap.md)     | 规模化路线：缺口清单（2501+ 无损断档为唯一硬约束）、era 三分物化、S3 决策点——**规划**（缺口 2 增量通道曾由 daily-soak 落地，该链 2026-09-21 退役）                           |
| [2026-09-19-daily-soak.md](2026-09-19-daily-soak.md)           | 日更全量 soak：RSS 枚举实测（cs+math 1192 new+cross/日）、公告历、fetch→stagerun 重喂架构——**已退役（2026-09-21）**，枚举层取证仍有效                                        |
| [2026-09-22-id-canon-probes.md](2026-09-22-id-canon-probes.md) | canon 规范化实证：arxiv.org 301 剥 class/小写化/V→v 实录、官方标识符规则、manifest 14,398 id 双形普查——**时点证据 2026-09-22**（契约本体在 `spec/arxiv-id-canon.md`）        |

## 迁移映射（自 texlate/docs/research/arxiv/）

13 源件 → 12 件：`probes.md` + `serial2.md` 两波探针合并为 [probes.md](probes.md)（serial2 内容在 §B 规模面）；其余 11 件同名一一对应（`layer/export-probes/oai-pmh/bulk-channels/html-path/pdf-fidelity/licensing/arxiv-to-prompt/paper-search-assets/2026-09-19-daily-soak/2026-09-19-scale-roadmap`）。过程性探针日志、命令行、会话叙事按约定削除，结论与数字保留。

## 阅读建议

要了解「获取层为什么长这样」先读 [layer.md](layer.md)；要查端点行为细节按主机读 [probes.md](probes.md)（arxiv.org）/ [export-probes.md](export-probes.md)（export）/ [oai-pmh.md](oai-pmh.md)（oaipmh）；要做批量/增量决策读 [bulk-channels.md](bulk-channels.md) + [2026-09-19-scale-roadmap.md](2026-09-19-scale-roadmap.md) + [2026-09-19-daily-soak.md](2026-09-19-daily-soak.md)；要评估法务边界读 [licensing.md](licensing.md)；要理解降级链读 [html-path.md](html-path.md) + [pdf-fidelity.md](pdf-fidelity.md)。
