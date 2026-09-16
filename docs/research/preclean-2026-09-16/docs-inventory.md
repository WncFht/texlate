# docs/ 产物引用台账（清理前保全用）

> 2026-09-16 miner-docs 分片产出。范围：docs/ 下全部 90 个 md（决策史 01–05、现行规格 06–10、HANDOFF×2、README/original/tools-runbook、research/ 75 篇）。目的：清理 ~100G bench/ 产物前，钉死「哪些磁盘产物被文档当作证据引用」——**被引用的必须保留，或先在对应文档标注已删除**。行号以撰写时工作区为准；引用分三档：EXACT=文档点名带日期全名；STEM=文档只写词干/花括号（如 `fixloop-v3-{missing-file,docstyle}(-r2)`、`validbench-` 前缀）；ORPHAN=文档从未提及。

## 1. 文档地图

### 1.1 顶层决策层（01–05 冻结决策史，06–10 现行规格）

| 文件 | 行数 | 性质 | 一句话 |
| --- | --- | --- | --- |
| `README.md` | 30 | 索引 | docs 分层规则：01–05 决策史只追加不改写、06–10 为唯一实施依据、research/ 是过程证据 |
| `01-tech-stack-decision.md` | 105 | 决策史 | ADR-001：Python+TS+tectonic 选型；8 库横评表引 `bench/results/00-grand-comparison.md` |
| `02-architecture.md` | 110 | 决策史 | 区间替换模型（placeholder 保护→翻译→回填）架构定案 |
| `03-roadmap.md` | 60 | 决策史 | 早期路线图，已被 05§6 / 10§8 取代 |
| `04-selection-context.md` | 156 | 决策史 | 选型上下文与备选方案记录；§12 悬而未决项在 05§3 收口 |
| `05-reproduction-plan.md` | 270 | 决策史 | 22 条裁决表 + E1–E22 证据矩阵 + M0–M4 里程碑；§9 产品索引列出全部 tmp/exp 实验目录 |
| `06-arxiv-source.md` | 213 | 规格 | arXiv 获取层规格：e-print 取源/解包/locate/缓存 |
| `07-latex-pipeline.md` | 531 | 规格 | 半解析管线规格；§12 记录 v2 Gullet+Segmenter 产品面切换（tag v2prod-final） |
| `08-translate-compile.md` | 356 | 规格 | xlat/validate/compile 规格；fixloop yaml 规则引擎（现 36 条） |
| `09-benchmark-corpus.md` | 220 | 规格 | corpus_v3 四层语料规格（core 1000/booster 200/hot/expand） |
| `10-benchmark-suite.md` | 168 | 规格 | B1–B7 评测套件规格 + 状态注记（多臂点名 results 目录） |

### 1.2 运维与交接

| 文件 | 行数 | 一句话 |
| --- | --- | --- |
| `HANDOFF-2026-09-15.md` | 193 | archbox 迁移日交接：18 commits、segmenter v2 S3–S5 在途、§4 rsync 命令含 work_* 排除清单 |
| `HANDOFF-2026-09-16.md` | 283 | v2 切换日交接：~30 commits、三会话会战、审计波二收口、loop1 在跑 |
| `original.md` | 23 | hjfy 知乎原文存档（产品理念源头） |
| `tools-runbook.md` | 128 | 全工具目录（CLI/scripts/bench-py/web）+ 运维坑手册；证据出处 tmp/transcript-mining/ |
| `research/README.md` | 119 | 73 篇报告索引 + tmp/exp↔报告对应表 |
| `research/2026-09-16-loop1-status-and-next.md` | 84 | loop1 批跑状态与 loop2 计划（stagerun-loop1 ×3 处引用） |

### 1.3 research/ 调研档案（75 篇，按子目录）

**arxiv/（11 篇）**：`layer.md` 获取层调研总报告；`probes.md`/`serial2.md`/`export-probes.md`/`oai-pmh.md`/`bulk-channels.md` 五路取源探针；`html-path.md`/`pdf-fidelity.md` HTML/PDF 备选路径评估；`licensing.md` 许可合规；`arxiv-to-prompt.md` 翻译前处理；`paper-search-assets.md` 检索资产。

**corpus/（13 篇）**：`v3-plan.md` corpus_v3 设计蓝本；`frame-and-allocation.md` 分层抽样框架；`parsebench-v1.md` B1 首跑报告；`2026-09-15-parsebench-icc.md`/`2026-09-16-expand-layer.md` 两轮增量；`ia-pilot.md`/`post2020-sourcing.md`/`bulk-channels` 外源；`datasets.md`/`hf-latex-datasets.md`/`arxmliv-unarxive.md`/`labels.md`/`corpus39-profile.md` 语料侧写；`bench-construction-methods.md`/`parse-metrics-literature.md` 方法论文献。

**gateway/（8 篇）**：`probe-3003.md` 网关探明；`free-model-ranking.md`/`free-glm.md`/`free-swe.md`/`2026-09-16-free-tokens.md` 免费模型梯队；`gwbench-group-c.md`/`xlat.md` 网关实测；`cost-model.md` 成本模型。

**latex/（19 篇）**：`miniscanner-rewrite-spec.md`/`expansion-design.md`/`expansion-timing.md`/`segmenter-integration.md` 展开机四部曲；`validator-rules.md`/`validator-ts.md` 校验器双线；`engine-matrix.md` 引擎矩阵；`ctan-argspec.md`/`ctanfetch-probe.md` CTAN 数据层；`fixloop-rules.md` 修复规则来源；`alignment-probe.md`/`prompt-glossary-spec.md`/`doc-formats.md`/`pdf-path.md`/`pstricks-route.md`/`texglot-patterns.md` 专项；`2026-09-15-adversarial-audit.md`/`2026-09-16-aux-cjk-truncation.md` 两篇对抗/事故报告。

**product/（10 篇）**：`hjfy-site.md`/`competitors.md` 竞品；`web-layer.md`/`e2e-mock-pipeline.md`/`shared-cache.md`/`pi-parity.md`/`multiagent-survey.md` 设计稿；`2026-09-16-{xlat-resume-review,batch-hardening-design,e2e-pipefix-hotlayer,signature-mining}.md` 当日会战四篇。

**audit-2026-09-16/（14 篇）**：`README.md` 审计总控（13 维度 + 剩余清单超集）；`m0/m1/m2/m3` 里程碑判定；`spec06/07/08/spec0910` 四规格对账；`codehealth/docs/e2e-func/evidence/tests` 五专项；`wave2-findings.md` 波二 ~75 条发现处置账。

## 2. 产物引用清单（docs → 磁盘）

### 2.1 `bench/results/` 目录级引用（EXACT 40 + STEM 20，全部在盘）

| results 目录 | 引用处（doc:line） | 引用语境 |
| --- | --- | --- |
| `parsebench-v2prod-final-2026-09-15/` | 07:510、HANDOFF-16:136、audit m0:33、m1:24、spec07 | **v2 终码验收证据**（identity 1955/1955、leak 0.046%），引用最多的目录 |
| `compilebench-v4-2026-09-16/` | 10:22,81、HANDOFF-16:31,87、audit m2:70、signature-mining:9 | B3 compilebench v4 + fixloop 臂 154/172 证据；`summary-diff-v3.md` 归因、cases.jsonl 签名挖掘输入 |
| `fixloop-cbv4-2026-09-16/` | HANDOFF-16:31、audit m2、signature-mining:11 | compilebench-v4 配套 fixloop 臂现场；cases.jsonl 签名挖掘输入 |
| `e2e-real-n100-2026-09-15/` | HANDOFF-16:28,102、audit m0、m1、spec0910 | n100 真网关批跑（chunk 10715/10718=99.97%） |
| `stagerun-loop1-2026-09-16/` | loop1-status ×3、HANDOFF-16:258,281 | **loop1 五阶段批跑现场**（ingest/parse/xlat-mock 全集 + fixloop 两轮，rescue 84.0% 复盘） |
| `e2e-postcutover-n10-2026-09-15/` | HANDOFF-16:144、audit m0、m1、spec0910 | v2 切换后 n10 真网关冒烟（splice 残留 0 硬门 PASS） |
| `e2e-verify-residue-2026-09-16/` | HANDOFF-16:28,104、audit | splice 残留修复后复验全归零 |
| `parsebench-v2full-s3c-2026-09-15/` | segmenter-integration:257-330、HANDOFF-16:28,50 | S3 展开语义验收（双跑 1955，dead_ph 归零） |
| `parsebench-v2full-s4-2026-09-15/` | segmenter-integration ×2 | S4 `\if` 界标档验收 |
| `e2e-real-n100-postcutover-2026-09-16/` | batch-hardening:3、signature-mining:12 | postcutover n100 终态（xlat 99.7%、B7 归因） |
| `compilebench-v3-zh-2026-09-16/` | signature-mining:10、HANDOFF-16 B3 zh 臂 | zh 臂 cases.jsonl 签名挖掘输入 |
| `e2e-hotfix-smoke-2026-09-16/` | 10:120、pipefix-hotlayer:68 | 热层 pipefix 冒烟 |
| `fixloop-corpusv2-2026-09-15/` | 10:79 | B3 早期 fixloop 救回率证据 |
| `qual-run-2026-09-16/` | 10:96 | B4b 质量臂 |
| `e2emock-corpus39-2026-09-15/` | audit m0 ×2 | B5-A mock 端到端 corpus39 基线 |
| `e2emock-v2prod-smoke-2026-09-15/` | audit m0、spec07 | v2 产品面 mock 冒烟 |
| `smoke-2026-09-15/` | audit m0、spec07 | 冒烟基线 |
| `parsebench-corpus39-2026-09-15/` | audit m0（summary.md） | corpus39 B1 验收 |
| `parsebench-fixtures-2026-09-15/` | audit m0（summary.md） | fixtures B2 验收 |
| `parsebench-corpus_v2-2026-09-15/` | parsebench-v1（`parsebench-corpusv2-*` glob） | corpus_v2 B1 首跑 |
| `parsebench-corpus_v3-2026-09-15/` | audit spec0910:53 ×2 | corpus_v3 B1 证据 |
| `parsebench-corpus_v3-postf6-2026-09-15/` | audit spec0910 | post-fix 复跑 |
| `parsebench-v2dual200-2026-09-15/` | HANDOFF-15 | v1/v2 双跑对照 200 |
| `parsebench-v2full1955-2026-09-16/` | HANDOFF-16:27、audit m0、evidence | S5 全量基线（另有同名 `-report.md` 散文件被 audit 引用） |
| `parsebench-audit-defnl-2026-09-15/` | adversarial-audit:54 | defnl 对抗审计复跑 |
| `parsebench-maskfix-probe-2026-09-15/` | HANDOFF-16:32 | mask_tex 修复探针 |
| `validbench-corpus_v2-2026-09-15/` | 10:124（`validbench-` 前缀）、audit m1、spec0910 | B6 校验段基准 |
| `validbench-replay1636-2026-09-15/` | 10:124（前缀）、audit spec0910 | B6 replay 证据 |
| `xlatbench-contract-2026-09-15/` | audit m1、spec0910 | B4a 契约臂 |
| `xlatbench-v3-matrix-2026-09-15/` | audit spec0910 | B4a v3 矩阵 |
| `alignbench-e2ereal-2026-09-15/` | audit spec0910 | B7 锚点保留率 |
| `corpus-expand-qc-2026-09-16/` | expand-layer:6（`QC.md`） | expand 层 QC 报告 |
| `export-realbook-2026-09-16/` | doc-formats:6 | export 真书验证 |
| `fixloop-v3-missing-file-r2-2026-09-16/` | HANDOFF-16:69 | tlmgr 装包层实证 85/111 |
| `e2e-real-s40-2026-09-15/` | HANDOFF-15、aux-cjk:4（`results.json`） | s40 真网关批跑 + aux 截断事故证据 |
| `compilebench-v3-2026-09-15/` | HANDOFF-15 | B3 v3 基线 |
| `b7-pipefix-2026-09-16/` | 10:22 | B7 pipe-fix 复测（mean 0.9918） |
| `base-v3-full-2026-09-16/` | 10:22 | base 臂全量 |
| `mock-sabotage-v3-2026-09-16/` | 10:22、HANDOFF-16 Mode B/C | sabotage 臂 |

STEM 档（词干/花括号被点名，20 个）：`fixloop-v3-missing-file-2026-09-16`、`fixloop-v3-docstyle-2026-09-16`、`fixloop-v3-docstyle-tec-r2-2026-09-16`（HANDOFF-16:29 花括号 `fixloop-v3-{missing-file,docstyle}(-r2)`）、`fixloop-v2-salvage-2026-09-16`（HANDOFF-16:29）、`parsebench-v2full-s3b-2026-09-15`（HANDOFF-16:28）、`e2e-real-s40-r2-2026-09-15`（s40 词干）、`alignbench-e2ereal-2026-09-16`、`fixloop-zh-cbv3-2026-09-16`（10:22）、`parsebench-corpusv2-2026-09-15`（parsebench-v1 glob）、`parsebench-corpus_v3-postf-2026-09-15`（spec0910）、`argspec-verbatim-2026-09-16`（HANDOFF-16:255 #96）、`modec-misschar-2026-09-16`、`repro-2501-2026-09-16`、`v3-100-2026-09-15`、`gullet-corpus-2026-09-15`、`fixloop-v2-rules-2026-09-15`、`clean-clone-2026-09-16`、`live-smoke-2026-09-16`（HANDOFF-16:251）、`share-live-2026-09-16`、`fixloop-rules-2026-09-16`。**弱词干注意**：`demo-2026-09-16`（"demo" 7 处多为 demo.sh）、`babeldoc/`（10 处多指 server/babeldoc.py 库名）、`qualbench-2026-09-16`、`server-smoke-2026-09-16`（同名脚本）——词干命中多指概念本身，目录本体未必是证据，但保守起见归入保留侧。

### 2.2 `bench/results/` 散文件引用（EXACT 19 + STEM 4，全部在盘）

`00-grand-comparison.md`（01:26、04:5——8 库横评主证据）；`scanner-audit-2026-09-15.md`（07:462）；`v2-census-2026-09-15.md`（HANDOFF-15、segmenter-integration）；`v2-diff-2026-09-15.md`（segmenter-integration；姊妹文件 `.jsonl` 词干档）；`f3-patch-notes.md`（HANDOFF-16:228，worker.py 侧补丁留档）；`arxiv-coverage.md`（arxiv/layer、serial2）；`encoding-probe-2026-09-16.json`（HANDOFF-16:81、audit m2）；`e2e-real-n100-2026-09-15-report.md`（HANDOFF-16:102）；`e2e-verify-residue-2026-09-16-report.md`（HANDOFF-16:104）；`parsebench-v2full1955-2026-09-16-report.md`（audit m0/evidence）；`nominations-merge-2026-09-16.md`（HANDOFF-16:30 词干）；`splice-residue-probe-2026-09-16.md`（HANDOFF-16:29 词干）；`gullet-corpus-2026-09-15.md`（词干）；`macro-stats.json`（spec0910）、`macro-stats.md`（miniscanner-rewrite-spec）、`macro-stats-report.md`（expansion-design:4）；`fixloop-results.json`+`fixloop-spike-report.md`（fixloop-rules:5）；`miniscanner-parse.json`+`miniscanner-report.md`（miniscanner-rewrite-spec:409,581）；`pylatexenc-report.md`（spec0910）；`metrics.jsonl`（tools-runbook、batch-hardening——且本身是 git 跟踪文件）。

### 2.3 `bench/work_*/` 引用（全部在盘）

HANDOFF-15:187 rsync 排除清单点名 `work_compile/`、`work_compile_v2/`、`work_e2emock/`、`work_e2ereal/{base-xel,pipe-xel}/`、`work_fixloop/`、`work_fixloop_v2/`、`work_v3/tars/`——语境是**运维排除清单**（gitignored 重产物靠 rsync 搬运），非结果证据。HANDOFF-16:184 重申 `bench/work_*/` gitignored 靠 rsync。audit tests.md:71-72 以 `work_compile/`、`work_fixloop` 为例标注 stale 产物。pipefix-hotlayer:19,65 引用 `work_v3/hot/fetch_fail.jsonl`、`work_v3/hot/candidates.jsonl` 作热层失败现场证据。**work_* 均为可再生 scratch，文档引用语义是"当时现场"而非验收门**——删除不破坏任何判定，但 `work_v3/hot/` 两文件是唯一被当数据证据引用的。

### 2.4 `bench/corpus*/` 与 `bench/fixtures/` 引用（全部在盘）

`bench/corpus/MANIFEST.md`（04:5）；`bench/corpus_v3/` 整体（09、spec0910、adversarial-audit:54、batch-hardening:3）；`corpus_v3/mechanisms.jsonl`（09:91,147、HANDOFF-15:98、v3-plan——144 行机制台账）；`corpus_v3/nominations/`（HANDOFF-15:94,190、HANDOFF-16:184——8 agent 提名合流现场）；`corpus_v3/manifest_expand.jsonl`（expand-layer:5）、`manifest_hot.jsonl`（pipefix:64、signature-mining）、`MANIFEST.md`（audit docs:66）；`corpus_v2/`+`build_corpus.py`+`MANIFEST.md`（parsebench-v1:3,28,98,100）。单篇语料引用：e2e-func 审计引 `corpus/{1706.03762,2501.14787,1412.6980,0906.1291}`；probes:167 引 `corpus/1412.6980/`；pstricks-route 引 `corpus/0807.3917/`；e2e-mock-pipeline 引 `corpus/{math/0404188/main.tex,1706.03762/ms.tex,2609.09529/,1712.01208/acmart_old.tex}`；xlat.md 引 `corpus/1706.03762/ms.tex`。**`bench/corpus*` 语料本体是所有 bench 的输入层——删除等于切断全部 B1–B7 复现链**；`bench/fixtures/` 8 个陷阱文件被 tests.md:93 逐条对账（测试消费全覆盖），另有 xlat:64、free-swe:11、miniscanner-rewrite-spec:509、HANDOFF-15:99,177 引用。audit docs.md:37 的 "parsebench/fixtures/validbench" 是三个评测器名并列，**不是路径**（无 `bench/fixtures/validbench` 缺口）。

### 2.5 `tmp/` 引用（仓内 scratch，整目录 gitignored）

05:40-61,264-270 §9 产品索引成建制列出：`tmp/exp/{ctan/argspec.json, macro-stats/macro_stats2.json, rule-validator/, ts-validator/, fixrules/rules.yaml, engine/, e2e/, align-probe/, ctanfetch/, costmodel/stats.json, gwbench/, selfcheck/, oracle/}` + `tmp/refs/`——这些是 E1–E22 证据矩阵的实验现场。research/README §exp↔报告对应表把 ~20 个 `tmp/exp/` 子目录逐一映射到报告（arxiv-probes/、arxiv-serial2/、export-probes/、oai-probes/、bulk-channels/、datasets/、hf-datasets/、labels/、corpus-sources/、ia-pilot/、post2020/、atp-src/、atp-runs/、html-dom/、pdf-fidelity/、corpus-profile/、pstricks-probe/、ctan/、ctanfetch/、engine/、fixrules/、oracle/、rule-validator/、ts-validator/、align-probe/、gwbench/、costmodel/、modelbench/、e2e/）。09:47 与 v3-plan、frame-and-allocation 引 `tmp/exp/frame/frame.parquet`+`cluster_pick.json`（抽样框架实体）。spec0910 引 `tmp/exp/{oracle,gwbench/bench_free.py,e2e,align-probe,modelbench}`；audit e2e-func 引 `tmp/audit-e2e/`（run-* 现场）；audit spec06 引 `tmp/audit-spec06/hostile_unpack.py`；audit m1 引 `tmp/exp/ctan/`；loop1-status:67 引 `tmp/latex209-probe/`；tools-runbook:3 引 `tmp/transcript-mining/`（本会话挖掘证据出处）。tmp/refs/ 下 8 个参考 repo clone（plastex/BabelDOC/MinerU/texglot/bilingual_book_maker/ieeA/LaTeXTrans/MathTranslate）被 05、04:33、texglot-patterns、doc-formats 引用。**tmp/ 整体 gitignored 且全是 scratch，但 exp/ 子目录是 75 篇研究报告的原始证据现场**——删 tmp/exp 等于让 research/ 全部报告失去可复核性。

### 2.6 `/tmp/` 绝对路径引用（仓外 OS tmp，已自然消失）

`/tmp/arxiv_monthly.csv`（serial2:83 采样上界表）、`/tmp/arxiv_cov.jsonl`（parsebench-v1:23 早轮语料池）、`/tmp/probe_vault_results.json`（free-tokens:4 保险库探测原始数据）、`/tmp/curd/sigmap.tsv`（HANDOFF-15:117 明确注记"本机 /tmp"易失）。四处均为 Mac/本机 OS tmp 的易失中间产物，**不在本仓清理范围**；派生证据（`tmp/exp/arxiv-serial2/sample.jsonl`、`tmp/exp/gwbench/out_smoke_*/`）仍在仓内 tmp/。

## 3. 决策史与规格摘要

**01（技术选型）**：ADR-001 定 Python 主体 + TS bench 对照 + tectonic 引擎；8 库横评（pylatexenc/TexSoup/plasTeX/latex-utensils/unified/tree-sitter/latexjs/latexml）结论是"都不够用→自研半解析"，证据 `results/00-grand-comparison.md`；引擎默认 xelatex 的初判后被 compilebench 修正为双引擎分层。

**02（架构）**：定案"区间替换模型"——源 tex 不解析成 AST，而是扫出可译区间用 `[[TYPE_n]]` 占位符保护，翻译后按占位符回填，从根上保证非译内容字节不变（identity 铁律的源头）。

**03（路线图）**：早期五阶段路线，功能编排已被 05§6 里程碑表与 10§8 取代，仅存决策史价值。

**04（选型上下文）**：记录每个选型点的备选与否决理由（含对 hjfy 原版的观察）；§12 的悬挂问题在 05§3 裁决表中全部收口。

**05（裁决与复现计划）**：22 条裁决表（R 系列）冻结全部技术决策；E1–E22 证据矩阵把每条裁决钉到 `tmp/exp/` 实验或 `results/` 跑分；M0–M4 里程碑定义沿用至今（audit-2026-09-16 判定 M0 验收/M1 实质达成）；§9 是 tmp/exp 全实验目录的官方索引。

**06（arxiv 源规格）**：e-print 取源管线规格——HEAD 探测、版本钉取 `/src/{id}vN`、魔数三态解包、路径安全过滤、钉版缓存；withdrawn stub 语义在此定义。

**07（latex 管线规格）**：半解析全栈规格——Mouth 字符流、Gullet 展开机、Segmenter v2 分段、占位符签发、identity/leak/dead_ph 三硬门；§12 记 v2 产品面切换（`f461683` 起 parse_tex/parse_file 默认 Gullet+Segmenter，`TEXLATE_NO_EXPAND=1` 回退 v1）。

**08（翻译/编译规格）**：xlat 编排（chunk 调度/resume/L0–L2 校验回灌）、validate 三层语义、compile 引擎层（xelatex/tectonic 双引擎、normalize 编码链、ctex/xeCJK 注入、fixloop yaml 规则引擎）。

**09（语料规格）**：corpus_v3 四层设计——core 1000 分层随机、booster 200 机制补强、hot ~72 OpenAlex 高引近期、expand ~3800 IA bulk；mechanisms.jsonl 台账 + nominations 合流流程 + fixtures 陷阱注册规矩。

**10（评测规格）**：B1 parsebench / B2 fixture 断言 / B3 compilebench+fixloop / B4 xlatbench+qualbench / B5 e2e mock+real / B6 validbench / B7 alignbench 七套件定义；正文状态注记点名 ~15 个 results 目录作当前达成证据。

## 4. HANDOFF-09-15 vs HANDOFF-09-16 对比

**09-15（archbox 迁移日）**：主线是把 canonical 仓从 Mac 迁到 archbox + 当日 18 commits；M0 自评"进行中"，segmenter v2 停在 S3–S5 在途（v2dual200/v2-census 等中间证据）；§4 rsync 镜像命令含 `bench/work_*` 排除清单（运维留存价值）；§5 剩余清单大头是 v2 语义落地 + corpus_v3 补强 + compilebench 全量。

**09-16（v2 切换日）**：M0 转"已验收"（audit m0 判定）、M1 实质达成；§0 点名 ~18 个当日新 bench 现场；主线三件事——segmenter v2 S3/S4/产品面切换全落（`bf31377`/`f730dc0`/`f461683`）、fixloop+compile 两波（compilebench-v4 联合 pdf 154/172、mask_tex overshoot 修复、normalize 编码层）、xlat/web/台账。§6 补记午后三会话会战（worker 管线完工、perf 两波、stagerun 五阶段、F1–F4 工单）+ 审计波二 6-fixer 收口 + **loop1 批跑在飞**（stagerun-loop1，rescue 84.0% 复盘已出）。

**leftovers 对账**：09-15 §5 剩余项在 09-16 中大部分销账（v2 语义、compilebench 全量、aux/bib 截断、babeldoc 对照）；跨日仍开的：性能尾（85→20→11 文件 >500ms 递减但未达门）、`res.macros` 消费点 union 遗留、worker 调 fixloop 未传 llm_hook、INLINE_MAX 死常量、`build_corpus_v3.py` 第二套 unpack 未归并、emulateapj/epsf shim-bypass、B3 zh 臂/e2e Mode B·C 在 09-16 午后才实质推进。09-15 的 rsync 命令在 09-16 §5 注明"沿用不变"。

## 5. 文档 ↔ 磁盘对账缺口

### 5.1 文档引用但磁盘已缺（仅 5 项，全部可解释）

| 引用路径 | 引用处 | 状态 |
| --- | --- | --- |
| `/tmp/arxiv_monthly.csv` | serial2:83 | OS tmp 易失物，预期内消失；非仓内路径 |
| `/tmp/arxiv_cov.jsonl` | parsebench-v1:23 | 同上 |
| `/tmp/probe_vault_results.json` | free-tokens:4 | 同上 |
| `/tmp/curd/sigmap.tsv` | HANDOFF-15:117 | 同上（原文已注"本机 /tmp"） |
| `tmp/exp/oracle/report.json` | expansion-design §11.1 | **规格规划产物、从未产出**；audit spec0910 已标"oracle 对拍探针未扶正"；目录内现存 oracle_probe.py+probe_output.txt |

**没有任何一个 `bench/results/`、`bench/work_*`、`bench/corpus*`、`bench/fixtures/`、仓内 `tmp/` 的文档引用路径缺失**——方向 A（文档→磁盘）零缺口。

### 5.2 磁盘存在但文档从未点名（方向 B，删除候选）

**results 目录 ORPHAN 55 个**：alignbench-post-shim、alignbench-selftest、api-cover、b7-attribution、babeldoc-e2e、cli-doctor、compilebench-corpusv2、ctex-anchor、dist-smoke、doc-e2e、docker-smoke、doc-polish、e2emock-smoke、e2e-modes、export-verify、filemap-fix、fixloop-replay-baseline、l2-attr-probe、live-smoke2、modec-{expand,tail,tec-v3,v3,v3-tailfix}、parsebench-argspec-smoke、parsebench-audit-{final,fix,full}、parsebench-corpus_v3-booster、parsebench-textutil-{full,full2,verbatim}、parsebench-v2prod-cutover、parsebench-v2reg-s3grp{,2}、parsebench-v2textfix、parsebench-v3-post-wfix、parse-v3-full、perf-tail、postfix、probe-wire、realarm-repro、repro-{0806,0806-head,0806-textfix,1306,2203,2410b}、share-{apply,wire}、stagerun-{sabsmoke,smoke}、web-docview、web-resmoke、xlatbench-v3-smoke（均带 `-2026-09-1*` 日期后缀）。

**results 散文件 ORPHAN 43 个**：audit-minor-fixes-2026-09-15.md、babeldoc-smoke{,-report}.md、compile-{bench.json,report.md,tables.md}、f12-env-tomb-2026-09-15.md、fixloop-tickets-{F1F2,F3F4}-2026-09-16.md、fixloop-tlmgr-search-cache.json、ieeA-{baseline-report.md,parse.json}、latexjs-walkthrough.md、latexml-pandoc-report.md、latextrans-mathtranslate-walkthrough.md、latex-utensils-{leak,parse,roundtrip,traps}.json+report.md、parsebench-corpus39-{files.jsonl,papers.json,summary.md}（顶层旧命名，与被引目录 parsebench-corpus39-2026-09-15/ 同族不同物）、parsebench-corpusv2-{files.jsonl,papers.json,summary.md}、plastex-{parse.json,report.md}、pylatexenc{,3}-parse.json、texglot-walkthrough.md、texsoup-{parse.json,report.md}、tree-sitter-latex-{parse.json,report.md,traps.json,validator.json}、unified-latex-{leak,parse,roundtrip,tricky}.json+report.md、upload501-worker-patch.md。**注意**：其中 plastex/texsoup/tree-sitter/unified/latex-utensils/ieeA/latexjs/latexml 等是 01 号文档 8 库横评的原始产物——`00-grand-comparison.md`（被引用）是它们的汇总文档，单体文件未被点名但属同一证据簇，删除前建议在 01/04 对应行标注"原始单体报告已删、汇总保留"。

**work_* ORPHAN 11 个**：work_base_v3full、work_compile_v3、work_compile_v4、work_fixloop_cbv4、work_fixloop_replay、work_fixloop_v3、work_fixloop_v3_ds、work_fixloop_zh、work_sabotage_{mock,probe,v3}。全部可再生 scratch；work_fixloop_cbv4 等虽与被引 results 目录同族，但文档引用的是 results 侧，work 侧从未点名。

**tmp/ ORPHAN ~33 项**：alignbench-smoke、babeldoc-e2e-data、check_run_doc.py、cjkfont、corpus_v2_smoke.py、dbg_1012{,b,c,d,e}.py、doc-e2e-data{,2}、e2e-n100-postcutover-src、latex209-verify、live-smoke{,2}-data、probe_dispatch{.py,_out.json}、probe_s3{,b,c}.py、__pycache__、realbook、repro2203、share-live-b、shimtest、smoke400.log、smoke_v2{,_expand}.py、stash-recovery-0958、t017、upload501-worker.patch、web-check、worker_patched.py、preclean（本目录）。

### 5.3 结论

被文档点名的产物共 **60 个 results 目录（40 EXACT + 20 STEM）+ 23 个散文件 + 7 个 work_ 目录 + corpus 全层 + fixtures 全部 + tmp/exp 20 余子目录 + tmp/refs 8 clone**——全部在盘、零缺引。ORPHAN 侧 55 目录 + 43 散文件 + 11 work 目录 + ~33 tmp 项是纯删除候选（其中 8 库横评单体报告簇建议保留或在 01/04 加注）。STEM 档与横评簇属保守保留区：若空间不足优先删 ORPHAN，STEM/横评簇留到最后并先在文档补"已删"注记。
