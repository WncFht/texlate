# docs/research — 调研档案索引

TeXlate（hjfy.top 开源复刻）全部调研报告。**裁决与方案以 `docs/05-reproduction-plan.md` 为准**；本目录是支撑详规与实测证据。实验现场在 `tmp/exp/`（gitignored，同名目录对应），参考仓库在 `tmp/refs/`（gitignored），文献原件在 `lit/`（gitignored——PDF/HTML 二进制再生可得）。

## arxiv/ — arXiv 获取层

| 文件                     | 内容                                                                                      |
| ------------------------ | ----------------------------------------------------------------------------------------- |
| `layer.md`               | **arXiv 层主详规**：三速率桶/406 日配额/e-print 三态/版本语义/license gate，§10-11 全裁决 |
| `probes.md`              | 第一轮探针：rate-limit、HEAD 预检、条件请求                                               |
| `serial2.md`             | 第二轮串行探针：190 发分层 HEAD 抽样（sample.jsonl 底材）                                 |
| `export-probes.md`       | export.arxiv.org 全站镜像=第二下载桶、限流按路径不按 host                                 |
| `oai-pmh.md`             | OAI-PMH 第三桶（oaipmh.arxiv.org）、`<license>` 字段唯一机读源                            |
| `bulk-channels.md`       | IA tar / S3 requester-pays / gs://arxiv-dataset 批量通道对比                              |
| `html-path.md`           | HTML 渲染降级路（ar5iv 生态、DOM 结构）                                                   |
| `pdf-fidelity.md`        | en 侧 PDF 选型：官方 PDF vs 自编译（页漂移 13/15）                                        |
| `licensing.md`           | arXiv license 法律面：nonexcl 对第三方零授权、CC 占比、托管合规                           |
| `arxiv-to-prompt.md`     | `/arxiv-to-prompt` skill 逆向：uvx 工具链分析                                             |
| `paper-search-assets.md` | `/paper-search` skill 的数据集与 API 资产盘点                                             |

## latex/ — LaTeX 解析/编译/翻译管线

| 文件                               | 内容                                                                       |
| ---------------------------------- | -------------------------------------------------------------------------- |
| `miniscanner-rewrite-spec.md`      | **半解析器重写规格**（`src/texlate/latex/` 9 文件蓝图 + 增补项）           |
| `expansion-design.md`              | 宏展开设计：单遍即时展开 vs 两遍建表裁决                                   |
| `expansion-timing.md`              | 展开时机语料统计（UBD=0 实证）                                             |
| `validator-rules.md`               | L0 校验器规则规格（chunk 不变量）                                          |
| `validator-ts.md`                  | tree-sitter L1 校验调研（baseline 相对模式裁决）                           |
| `engine-matrix.md`                 | 编译引擎矩阵：tectonic/xelatex 路由规则                                    |
| `pstricks-route.md`                | pstricks/eps 引擎路由实测                                                  |
| `ctan-argspec.md`                  | CTAN 宏包参数规格获取                                                      |
| `ctanfetch-probe.md`               | tlmgr/CTAN 依赖解析探针                                                    |
| `doc-formats.md`                   | EPUB/DOCX 通路规格（bbm 蓝图照抄）                                         |
| `pdf-path.md`                      | PDF 通路：BabelDOC sidecar 规格 + MinerU 深读                              |
| `prompt-glossary-spec.md`          | 术语表/prompt 工程规格                                                     |
| `texglot-patterns.md`              | texglot 模式借鉴（normalize/阅读器/同步锚点）                              |
| `fixloop-rules.md`                 | fixloop 规则沉淀机制设计                                                   |
| `alignment-probe.md`               | named destinations 滚动同步锚点实测                                        |
| `segmenter-integration.md`         | segmenter v2 集成笔记（S3/S4/切换落地过程）                                |
| `2026-09-15-adversarial-audit.md`  | latex 管线对抗性审计                                                       |
| `2026-09-16-aux-cjk-truncation.md` | aux/bib 8192B 截断→invalid UTF-8 问题留档（**已修** `_transcode_aux_bib`） |

## corpus/ — 语料与 benchmark（当前主线）

| 文件                            | 内容                                                                                                                    |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `v3-plan.md`                    | **corpus_v3 数据管线定稿**：1,200 篇 = 1,000 核心 + 200 补强，30 簇 measure-then-sample                                 |
| `parsebench-v1.md`              | parsebench 首轮报告：137 篇无偏语料 223/223 ok、identity 100%、泄漏 0.086%                                              |
| `parse-metrics-literature.md`   | 解析评估指标文献：unarXive 漏斗/GROBID 三档/Wilson/UTB                                                                  |
| `bench-construction-methods.md` | benchmark 语料构建方法学：20 个先例对比 + 抽样统计引证                                                                  |
| `ia-pilot.md`                   | IA bulk 管线 pilot：成员三态/特征提取速率/zipsum 索引/成本实测                                                          |
| `post2020-sourcing.md`          | post-2020 渠道裁决：TIGER-5T byte-exact 实证、scholarweave 有损定量                                                     |
| `frame-and-allocation.md`       | 抽样 frame：3.16M 行分层表、30 簇清单、配额分配                                                                         |
| `hf-latex-datasets.md`          | HF 上 LaTeX 语料数据集普查                                                                                              |
| `datasets.md`                   | arXiv 开放数据集与批量渠道普查                                                                                          |
| `labels.md`                     | 分层键与真值标签源（HF 快照/OpenAlex/license）                                                                          |
| `corpus39-profile.md`           | bench/corpus 39 篇机器级统计画像                                                                                        |
| `arxmliv-unarxive.md`           | arXMLiv/ar5iv/unarXive 学术发行物调研（结论：无源码不入料）                                                             |
| `2026-09-15-parsebench-icc.md`  | parsebench 月间 ICC 信度分析（§7.2 统计口径行动项）                                                                     |
| `2026-09-16-expand-layer.md`    | corpus_v3 expand 层 +3800（当时总 5072；现四层合计 5135，hot 层 135）：故障率加权配额、新旧池选样、QC 全过 +60 良性超收 |

## gateway/ — LLM 网关与模型选型（本机存档，不入库）

网关探针/免费模型横评/成本模型/fg-bg 分级准入规格一组（probe-3003、free-model-ranking、cost-model、free-tokens、fg-bg-admission 等）属开发机存档、未入库——结论已沉淀进 `docs/05-reproduction-plan.md` §E20–E22 与 `docs/08` BYOK/模型层裁决。

## product/ — 产品/E2E/工程生态

| 文件                                   | 内容                                                                  |
| -------------------------------------- | --------------------------------------------------------------------- |
| `hjfy-site.md`                         | **hjfy.top 线上侦察**：前端 bundle 逆向、API/状态机/OSS 产物          |
| `web-layer.md`                         | Web 层规格：API/SQLite 队列/BYOK/SolidJS+pdfslick/部署                |
| `e2e-mock-pipeline.md`                 | 端到端 mock 管线：16 篇 13 clean 验证机械链路                         |
| `competitors.md`                       | 竞品侦察矩阵：arXiv 阅读/翻译生态                                     |
| `multiagent-survey.md`                 | subagent/multi-agent 生态全景（CC 第一方/社区/外部框架）              |
| `pi-parity.md`                         | pi CLI 多 agent 能力对照                                              |
| `2026-09-16-xlat-resume-review.md`     | xlat 断点续翻三修评审留档                                             |
| `2026-09-16-batch-hardening-design.md` | 批量加固设计：stagerun 五阶段驱动 + records/tickets + preflight/gwcap |
| `2026-09-16-e2e-pipefix-hotlayer.md`   | e2e pipe-fix 救回臂语义校准（onfail 只接 fail）+ hot 语料层取源记录   |
| `2026-09-16-signature-mining.md`       | 失败签名挖掘方法论（n≈3/p 可分辨度）                                  |
| `shared-cache.md`                      | 翻译共享缓存设计（per_key 分桶 / 跨租户 reuse 取舍）                  |

## 日期化快照目录 — 审计/保全/评审/排期

| 目录                         | 内容                                                                                                         |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `audit-2026-09-16/`          | 全仓目标达成审计 13 维度（M0–M3 × spec 06–10 覆盖 × 实测/测试/安全/证据/文档）；总索引与判定见其 README      |
| `refactor-audit-2026-09-17/` | 全仓重构/优化/清理向审查：Top6 结构债（repair.py 单源化、segmenter/worker 拆包、records 读层收敛的决策出处） |
| `review-web-2026-09-17/`     | Web 前后端三方审查一轮：API 层/worker 编排/前端 30+ 发现（一轮已修毕）                                       |
| `review2-web-2026-09-17/`    | Web 前后端二轮审查：一轮修复落地后新状态的优化/升级/重构机会面                                               |
| `roadmap-2026-09-17/`        | 现状报告与未来发展排期：`ROADMAP.md`（四档排期 + 决策点）+ `inputs/` 八轴只读侦察件                          |

## 根目录散件

| 文件                                  | 内容                                                                                                 |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `overseer-2026-09-16.md`              | 车队作战台账：多会话协调的决策与落地逐条记录（2026-09-16 夜间冲刺起续记）                            |
| `2026-09-16-loop1-status-and-next.md` | loop1 复盘 + 三方分派收敛（stagerun-loop1 n=5059 数字总账与在飞清单）                                |
| `report-2026-09-17-final.md`          | 2026-09-17 全天作战终报：一页结论/波次总账/关键数字/缺陷账/排期摘要/决策点                           |
| `reaudit-2026-09-18.md`               | 重构波后全仓重读审计：A 17 真 bug/安全 + B 13 单源债 + C 10 结构 + D 4 测试 + E 10 文档 + F 归属外表 |

## lit/ — 文献原件

unarXive 2020/2022a/2022b、Nougat ×3、BabelDOC、S2ORC、pdfmathtranslate 等 PDF + arxmliv_stats/kitopen/sig HTML 快照 + olmOCR tests 源码。

---

## exp ↔ 报告对应表（`tmp/exp/`）

| exp 目录                                                                | 报告                           | 说明                                                      |
| ----------------------------------------------------------------------- | ------------------------------ | --------------------------------------------------------- |
| `ia-pilot/`                                                             | corpus/ia-pilot.md             | 含可复用 `scan_tar.py`/`assemble.py` + 48 篇 pilot corpus |
| `post2020/`                                                             | corpus/post2020-sourcing.md    | TIGER/scholarweave 对拍脚本与差异表                       |
| `frame/`                                                                | corpus/frame-and-allocation.md | frame.parquet + allocation-*.csv（v3 构建输入）           |
| `arxiv-probes/` `arxiv-serial2/` `export-probes/` `oai-probes/`         | arxiv/ 同名报告                | 探针原始响应                                              |
| `bulk-channels/` `datasets/` `hf-datasets/` `labels/` `corpus-sources/` | corpus/arxiv 对应报告          | 渠道与数据集实测                                          |
| `e2e/`                                                                  | product/e2e-mock-pipeline.md   | mock 管线代码 + 结果（work 目录已清）                     |
| `engine/` `pstricks-probe/` `ctan/` `ctanfetch/`                        | latex/ 对应报告                | 编译路由实测                                              |
| `align-probe/`                                                          | latex/alignment-probe.md       | dest 探针脚本 + 结果                                      |
| `gwbench/` `costmodel/` `modelbench/`                                   | gateway/ 对应报告（本机存档）  | 网关横评与成本                                            |
| `atp-src/` `atp-runs/`                                                  | arxiv/arxiv-to-prompt.md       | skill 逆向现场                                            |
| `html-dom/` `pdf-fidelity/`                                             | arxiv/ 对应报告                | 渲染保真实验                                              |
| `oracle/` `selfcheck/` `fixrules/` `rule-validator/` `ts-validator/`    | latex/ 校验器系                | L0/L1 校验实验                                            |
| `corpus-profile/`                                                       | corpus/corpus39-profile.md     | profile.py + stats.json                                   |
| `misc/`                                                                 | —                              | 无归属散件（userscript、macro_stats2）                    |
