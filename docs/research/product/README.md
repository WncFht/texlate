# research/product/ —— 产品与生态域

面向「做什么、对标谁、生态里有什么可借」的调研档案：目标产品侦察、Web 层设计取证、端到端验证记录、外部产品逆向、引用图谱生态全景。实现现状的唯一事实源在 `spec/`，本文档域保留的是决策当时的证据与外部世界快照——与代码漂移处以代码为准。

## 索引

### 目标产品侦察

| 文件 | 内容 |
| --- | --- |
| [hjfy-site.md](hjfy-site.md) | hjfy.top 线上产品侦察：API 面、产物三件套、五态状态机、DeepSeek 重翻通道——复刻 checklist 的核心 |
| [competitors.md](competitors.md) | 竞品全景：arXiv 阅读/翻译生态扫描，「LaTeX 源码→中译→保排版」生态位确认 hjfy 唯一；ar5iv/arxiv.org/html 为 HTML 降级链第二源 |

### Web 层设计与实装取证

| 文件 | 内容 |
| --- | --- |
| [web-layer.md](web-layer.md) | **SUPERSEDED**：实施前 API/状态机/DDL 设计规格兼取证记录，规范事实源已移交 `spec/architecture.md` §4–§5 与 `server/`、`web/` 代码；texglot 先例拆解仍具参考价值 |
| [shared-cache.md](shared-cache.md) | 社区共享译文缓存设计：share key 七组分寻址、`.share.zip` 包格式、「下载不直接渲染、本地全链重跑」信任模型——已实装 |
| [2026-09-19-select-popup-方案调研.md](2026-09-19-select-popup-方案调研.md) | select 弹层两段式决策：≤4 项枚举改 Segmented 恒可见、长列表 `appearance: base-select` 渐进增强——已落地 `web/src/styles/select.css` |
| [review3-web-perf-2026-09-19.md](review3-web-perf-2026-09-19.md) | Web 前端性能专项审计：慢感三主因（chunkPoll 全量轮询、挂载单帧巨渲染、缺 content-visibility）+ 20 项 findings 当日实施记录 |
| [2026-09-21-pdf-dark-rendering.md](2026-09-21-pdf-dark-rendering.md) | PDF 暗色渲染四路线实测：CSS filter / pdf.js pageColors / Zotero Blender 效果×性能矩阵，Blender 胜出（ADR-0020）；Zotero 算法拆解、pdfslick 丢参 bug、免 fork 三接入坑全记录 |
| [2026-09-21-citation-ux.md](2026-09-21-citation-ux.md) | 引用跳转/跳回+悬浮卡 126-agent 生态调研：同锚双语义（hover=卡 click=跳）+自研跳回栈裁决；PDFHistory 进 SPA 毒药、本地 bib 串三路兜底、S2/OpenAlex 429 铁律；**已落地 v1（ADR-0021，cite_verify.mjs 16/16）**；原始数据在 [citation-ux-2026-09-21/](citation-ux-2026-09-21/) |
| [2026-09-23-pdf-anchoring.md](2026-09-23-pdf-anchoring.md) | PDF 窗格功能锚定可行性 13-agent 调研：「PDF 位置→chunk seq」是唯一真缺口；C 模糊锚已在产线、A SyncTeX ~1 周、B marked-content 注锚 3-5 天已双引擎实证；ActualText/tagpdf/覆盖式改形均否决 |

### 端到端验证与强化记录

| 文件 | 内容 |
| --- | --- |
| [e2e-mock-pipeline.md](e2e-mock-pipeline.md) | 端到端 mock 管线实验：16/16 出 PDF；实锤「出了 PDF ≠ 成功」与「校验层必须独立于编译层」两条设计公理 |
| [2026-09-16-hardening-notes.md](2026-09-16-hardening-notes.md) | 大批量强化合并件：stagerun 五阶段批量架构、pipe-fix `onfail` 语义、续翻语义三修（`_paper_done`/slots/source 漂移防线） |

### Agent 与工具生态

| 文件 | 内容 |
| --- | --- |
| [multiagent-survey.md](multiagent-survey.md) | 多 agent 生态调研：Claude Code 2026 原生多 agent 原语盘点、社区 superpowers 一家独大；结论「先用内置的」 |
| [pi-parity.md](pi-parity.md) | Pi agent 多 agent 能力对照：5 项功能可配 4 项，跨会话信箱/共享任务表配不出 |
| [2026-09-19-流程图skill调研.md](2026-09-19-流程图skill调研.md) | 流程图 skill 选型：官方无此 skill；d2 主渲染 + graphviz 兜底 + GitHub 场景直产 mermaid 源码块 |

### 外部产品逆向

| 文件 | 内容 |
| --- | --- |
| [2026-09-19-alphaxiv-reverse.md](2026-09-19-alphaxiv-reverse.md) | alphaXiv 逆向：公共 REST 面免鉴权、SDK 端点枚举；references 解析器与 per-language 状态机可借鉴（附 [管线图](2026-09-19-alphaxiv-pipeline.svg)） |
| [2026-09-19-paperscool-reverse.md](2026-09-19-paperscool-reverse.md) | papers.cool 逆向：刻意做薄的「刷论文」前端、个性化全在 localStorage；做「筛」不做「读」，与 texlate 不同层 |
| [2026-09-22-moonlight-reverse.md](2026-09-22-moonlight-reverse.md) | Moonlight(Corca) 逆向：Chrome 扩展劫持分发+overlay 阅读器；可抄=行内引用协议/框选解释/匿名漏斗/SEO 语料页/wasmtex；Team=计费容器无协作 |

### 引用图谱发现生态

| 文件 | 内容 |
| --- | --- |
| [2026-09-19-citation-landscape.md](2026-09-19-citation-landscape.md) | 20 lane 全景主报告：空白点 =「全 arXiv 量级 × 语句级边质量 × 算子化查询 × 实时新鲜度」四合一；LaTeX 源侧抽取是 texlate 结构性优势，OpenAlex 快照为底座 |
| [citation-landscape-2026-09-19/](citation-landscape-2026-09-19/) | 20 条 lane 档案（`01-openalex`–`20-engineering`），编号与主报告 §lane 一一对应 |

## 阅读建议

理解「texlate 在复刻什么」读 `hjfy-site.md` + `competitors.md`；理解「Web 层为什么长这样」读 `web-layer.md`（历史规格）对照 `spec/architecture.md` §4–§5（现行事实）；理解「双语阅读之外的延伸空间」读 `2026-09-19-citation-landscape.md`；找外部产品可借鉴设计读两个 reverse 件。
