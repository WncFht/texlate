# 项目编年时间线（log/）

> **结论**：TeXlate 于 2026-09-14 立项，一周内从空白仓库走到「arXiv LaTeX 源码 → LLM 段落级翻译 → ctex 中文 PDF」全链实质可用；本文件是逐日大事记，当日档案明细见各日期目录。
> **状态**：现行
> **日期**：2026-09-29

本时间线覆盖 2026-09 项目周期（09-14 立项 → 09-20 迁入本库）。每日一节，先记里程碑与关键数字，再列当日归档出处。归档文件按「当日口径」保留原文快照——前后数字不一致时以较晚日期的测量为准，口径漂移的说明见文末注记。重建前文档是平铺文件 `docs/01-*.md`–`docs/10-*.md` 与旧 `docs/research/` 树（与现行六分区中的 `docs/research/` 同名不同物——旧树在 `5ebc9797` 重建时移除，内容仅存 git 历史），本层引用这些是当日口径的历史指针，一律经本仓库 git 历史（`git log -- docs/`、`git show <commit>:<path>`）检索。逐日 `docs/HANDOFF-*.md` 交接文档原已入库，2026-09-18 由 `d39a1b23` 移出跟踪（发布前整理，文件仍留盘），经 `git show d39a1b23^:docs/HANDOFF-<date>.md` 调阅；本机另有未跟踪副本存 `tmp/old-docs-2026-09-20/docs/`。

## 2026-09-14 · 立项日

仓库 `init`（`7da5e8be`）。当日主事件是解析路线裁决：二十份横评报告（39 篇语料 + 30 个陷阱 fixtures）逐一验证第三方 LaTeX 解析库，八个候选全灭；自研 miniscanner spike 反而拿到陷阱断言 32/32、round-trip identity 259/259、leak 0.11%，据此定案「自研半解析器」路线。同日冻结技术栈与架构决策（`c93cc6f4`）并落 formatter/lint/pre-commit 工具链与 agent 布局（`8d823855`）。

## 2026-09-15 · 产品骨架日

七条臂同日落地：`texlate/latex` 九文件半解析器（`c3431f66`）、Mouth+Gullet 展开机（`d22b56b8`）、segmenter S1→S4 骨架、compile 引擎层（`c841c343`）、fixloop yaml 规则引擎 25 条（`179f7e5b`）、xlat 翻译编排层（`0a6bcbed`）、server（FastAPI+SSE+SQLite+BYOK）+ SolidJS 阅读器与 CLI mock 全链（16/16）。语料 39→1,339 篇；compilebench v3（n=180 双引擎）测出裸编译天花板 union pdf 71.7%/clean 39.4%；parsebench 核心层 1,955 文件 identity 100%/leak 0.04%。当日收尾 pytest 1,020 绿，HEAD `063ab49`。归档：`docs/HANDOFF-2026-09-15.md`（本仓库 git 历史，`d39a1b23` 起移出跟踪；调阅 `git show d39a1b23^:docs/HANDOFF-2026-09-15.md`）。

## 2026-09-16 · v2 切换日

最大单日指标跃升。`f461683` BREAKING——`parse_tex`/`parse_file` 默认走 Gullet+Segmenter v2，splice 残留占位符 1,524→0 硬门通过；`3d5de8f7` fixloop 接线 e2e+worker 双臂并落 L2 重译回灌，union pdf 同口径 70.6%→89.5%（+18.9pt）。同日十三维度全仓只读审计判 M0 验收通过、M1 实质达成、M2 字面未达（89.5%<90%）、M3 约半程；审计发现的 P0 安全三件（worker 路径逃逸、glossary 任意读、RedactFilter 未挂载）当日全部修复。午后至深夜多波加固：parse 长尾 −48%、stagerun 五阶段批驱动成形、Mode-B 内容通道逃逸全链修复（门槛 escaped=0 ∧ dirty=0 PASS）、审计波二 9 只读 scout 约 75 条发现经 6 修复车道当日全交付；stagerun-loop1（n=5,124 格）起跑。语料扩至约 5,059 篇，pytest 1,090 绿（当日快照，后勘误为 2,668 收集例）。归档：`docs/HANDOFF-2026-09-16.md`（本仓库 git 历史，`d39a1b23` 起移出跟踪；调阅 `git show d39a1b23^:docs/HANDOFF-2026-09-16.md`）+ 本目录 [audit-2026-09-16/](audit-2026-09-16/README.md)。

## 2026-09-17 · 波次战日

当日无单列交接文档，产出见本目录 [roadmap-2026-09-17/](roadmap-2026-09-17/ROADMAP.md) 与 `docs/research/report-2026-09-17-final.md` 终报（本仓库 git 历史，`5ebc9797` 前旧树）。白天是重构波：repair 单源化、segmenter/worker/gullet/builtins 拆包、rules.yaml 拆分为 `rules/` 分片（结构债台账见 `docs/research/refactor-audit-2026-09-17/report.md`，同前、`5ebc9797` 前旧树经 git 历史检索）。并行收残面：vendor 语料落地（`a90978ab`，绝版宏包缺件面 492 格 fail→73.2% clean）、illegal_unit 段修波 108/108 闭环、ReDoS 原子组修复把 pytest 全量从 48 分钟压到 3 分 46 秒、xlat 非锚定 `[n]` parse 撤除（P0，`164a9e0f`）封死译文静默错配通道。realn200 真臂验收收官 union pdf 197/200=98.5%——真臂与 mock 打平，评测面非虚高；loop1 records 在代码演进下多轮重评，scorecard 爬到 pdf 97.89%/clean 84.99%，M2 门以 4,554/5,059=90.02% 复评越过。傍晚出 ROADMAP.md 现状报告与排期，另有 web 两轮审查。

## 2026-09-18 · 重读审计与自我修复环

重构波尘落后五路并行只读审计产出 reaudit（A17/B13/C10/D4/E10 五表 + F 归属外表），旧审计债基本清零；当日 12-lane 修复波起跑——安全面 A 批逐项对销、单源化 B 批收编、fuzz 三臂补测、文档漂移 E 批落地；晚间 wave-2A 收编 C 批：textutil.py 1,355 行拆包、engine.py 1,715 行拆三件套，均字节级搬移。同日 selfimp 常驻改进环成形（wave-1 共 23 车道并行）：dollar 族泄漏收口 57→0/136,049 chunks（单类四年债清零）、scorecard schema v3 复跑 loop1 分毫不差自证评测器稳定、qualbench esa2 基线 n=1,200 mean 92.9。stagerun-loop2（n=5,135 格）pdf 97.26%/clean 86.42%。发布评审当日判「可发布，前提是轮换密钥」；M1 公共缓存 registry 与 Electron 两案裁决不做。corpus_daily 日更 soak 首批启动。归档：`docs/HANDOFF-2026-09-18.md`（本仓库 git 历史，`d39a1b23` 起移出跟踪；调阅 `git show d39a1b23^:docs/HANDOFF-2026-09-18.md`）。

## 2026-09-19 · 全量综合测试日

语料与评测同时拉满：corpus_v3 扩到 8 层 13,266 篇并做 sha256 全量核验（13,266/13,266、0 dup、EVAL_ONLY 治理生效）；parsebench 全量 28,904 个 .tex / 13,253 篇——parse ok 100%、strict identity 99.99%、leak 0.004%（76/1,845,338），L1 核心层复测 leak 0/128,460；compilebench n=500 base union pdf 90.4%、zh xel clean 72.4%；stagerun-v3all n=80 pdf 98.75%/clean 88.75%；e2e-real n=60 pdf 96.7% 且零管线引入回归、splice 残留 0；qualbench n=1,937 mean 94.0。工程侧：fixloop 规则库达 143 条（16 分片）、tests 6,450 例、bibtex/biber 链路打通、XCOMET-QE 质量信号建档；磁盘治理与语料七库合一（统一根约 54.9G）当日推进，日更 soak 管线（RSS→export→corpus_daily→stagerun，约 1,200 篇/日）上线。

## 2026-09-20 · 台账收尾日

本文件写作时点：texmf 复测 19/26 篇复活；3,000-id 隔夜批与 wave-13/14 修复清单在飞；fixloop 规则库自 143 条续增至约 185 条（分片目录口径），zh-leak 与 taxonomy 行级修复仍在落；错误沉淀→根因蒸馏的 errsweep 日更机制上线。本目录两份档案（audit-2026-09-16、roadmap-2026-09-17）于当日迁入本库重编。

## 2026-09-21 · census2 收口与内核奠基日

census2 全仓重构清扫当日收尾：src/web/bench/tests/agents 各面分批落盘，公共 seam（textutil/compile/http/pipecore 助手、ENV_* 单源、store/_common、axsearch/task-row 组件叶、_fixloopkit 等测试套件）全数收编，文档侧 spec/roadmap 漂移同步。同日 trizone-ledger v2 bench 内核开工并落地前两波：Wave A 基础件（idnorm/locks/ledger/index/fsutil/cas，`0804c246`）与 Wave B 分区件（vault/runs/lake/dedup/importer/exporter，`251d927b`）。日更 soak 链退役（`f7a2f32c`）。

## 2026-09-22 · bench 内核验收日

Wave C 运行径落地（spec/ctx/paid/kernel、sweep/doctor、cli/specs，`205606d7`；另有 dedup 预修 `45123054`、`f431c4fd`），`bench/py/kernel/` 25 模块约 15.1k 行全部就位。Wave-D 对抗验证两轮收口：首轮三车道裁决落 `76dc3341`/`bb78edff`/`147e6766`；第二轮六车道复审产出 94 条发现（13 fatal/43 major，汇总件 `tmp/jr_wf_7b0ace3b-589.txt`）全数裁决，落 `b7a7dd07`/`c203c1e6`/`56a13b12`/`5254b776` 四批——含 export 路径逃逸、redact 漏面、registry 污染、封存段不可见与封存机制悬空等 fatal 级修复。`tests/kernel/` 546 例通过 / 2 例按设计跳过。收官报告：[2026-09-22-bench 内核 wave-d 收官.md](2026-09-22-bench内核wave-d收官.md)。全量 bench 重建为下一阶段，未启动。

## 2026-09-23 · Wave-F 清点与阅读器 UX 落地日

bench 面大清点（Wave-F）：旧 `bench/py/` 驱动脚本全数退役改写为 kernel spec（`specs/`），repo 数据面出清（`406f3e6c` corpus/zh-store/archive 移出 checkout，物理载荷归 `$TEXLATE_BENCH_ROOT` 湖/库）、网关密钥字面量出 tracked 面（`1e5e3b71`）、ruff/prettier 全仓追平五批。layoutqc 验证电池落地：三档 tier 门 + 标记页收割 + pdf_corrupt/broken_refs 补签（`4c59de79`/`b2a4f72a`/`746b7519`），PDF 侧 B 路 marked-content seq 注锚后端接通（`823107dc`/`f95b47a6`）。阅读器 UX 六功能 + 主题色板轴 + 引用面 + pdf seq 锚前端一次落地（`97a7b6db`/`e6edbf23`），当晚线上五 bug 修复（`a3308396`）。e2e_real 探针批起跑：260 帧提名集六波连跑（新 id 入帧 `1b9c7d83`），翻译走内部网关真付费。

## 2026-09-24 · 磁盘策略与 dedup 修复日

P3 磁盘保留策略全量落地（`702e1554`）：splice 叶 slim 即焚回填释放 2.28G、≥256KiB 叶文件 CAS 硬链去重（1,363 文件/2,303 MiB）、prune 遇 blocked cell 改收壳（6.3G→392M）、corpus TARS 即焚。dedup 预言机修掉 meta 腿不分辨 kind 的致命误判（`e9c18aa6`）——{state}-only harvest 曾给 xlat 铸 VERIFIED 致 35 篇永久死锁，retry39 复跑实证全灭后修复，待下批以 ABSENT→重跑兑现。探针批收官：260 帧 layoutqc 评估通过 111（42.7%），账本累计花费 $48.20。阅读器侧续落 sent-align seq 精度链（`33cb792b`）、PDF 内链 UsagesCard（`6944c513`）、nearestSeq 距离闸（`8b0e3604`）。`tests/kernel/` 616 例、全仓 10,164 例。收官报告：[2026-09-24-磁盘策略落地与探针批指标.md](2026-09-24-磁盘策略落地与探针批指标.md)。全量 bench 重建按指令仍待放行。

## 2026-09-25/26 · bench 全量重建起跑与 dedup 遗毒解掩日

trizone-ledger v2 全量重建放行：W1 soak 500 格首批起跑（n=500 seed=42）、W2 n=1000 seed=43 在飞——manifest 14,290 篇目标，swe-2-medium promo 2026-10-16 死线。W1 qc_replay 校准实录：`geo_text_overlap` 检测器误报两类根因修复（splice 整页源文 Form XObject clip 幻影层按 bbox 收词、图内 en×en 标签互撞非管线产物），`_layoutqc.py` 换 pymupdf clip-aware + CJK 参与闸，findings 188→35/格 93→25（-81%）且真阳保留；tiers clean 241→280。主战役是 **no_pdf 根因翻案**：46 格追查证明规则库本就齐全，真凶=恢复期硬链物化把 compile-fail 陈 splice 封进 vault——`fixloop mutates=[splice]` 与 compile 同 kind 键域 → `need⊆alive` 永判 VERIFIED → fixloop 每波 dedup 永不登场（producer-blind 字节证据面天花板，同 2609.20519 锁死案族）。处置=103 格 `vault tombstone kind=splice` 解掩 + regen 波：soak-7 终态 **98/103 救活**（fixloop partial×97+ok×1，零 LLM 重花），逐格核到 pdf 落盘。新发现第二毒源：fail 终态也 harvest 复封 splice——regen 重试协议收敛为「每次重试前先复葬」。配套规则蒸馏波（未提交）：EuroPhys.cls/memo-l.cls/crckapbk.cls/EuroMacr.tex 四缺类补 shim_map、journal_cs_polyfill 收 `\ptlandscape`、cs_table 落 **38 键 usepackage:aaspp4** 桥 vendor/stubs/aaspp4.sty 救 2.09 `documentstyle[aj_pt4]` 选项蒸发族；cond-mat/0103528、astro-ph/0003115 逐格实证。台账明细分记 `docs/dev/bench-massrun-plan.md` §5。

## 本层档案索引

| 路径                                                                               | 内容                                                                                                                                                                             |
| ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [audit-2026-09-16/](audit-2026-09-16/README.md)                                    | 2026-09-16 十三维度全仓只读审计，15 件（其 README 为逐维索引与收口建议）                                                                                                         |
| [roadmap-2026-09-17/](roadmap-2026-09-17/ROADMAP.md)                               | 2026-09-17 现状报告与排期 ROADMAP + inputs/ 八路侦察底档（架构/bench 扩展/缺陷台账/文档健康/前端/测量/性能/产品缺口），9 件                                                      |
| [2026-09-22-bench 内核 wave-d 收官.md](2026-09-22-bench内核wave-d收官.md)          | trizone-ledger v2 bench 内核四波构建 + Wave-D 两轮对抗验证收口报告（94 条 round-2 发现全裁决、7 个修复提交、546 例测试绿）                                                       |
| [2026-09-22-trizone-phase0-2-进场实录.md](2026-09-22-trizone-phase0-2-进场实录.md) | trizone-ledger Phase 0–2 存量普查进场实录：真账册勘定、四源 44.4 万行进 ledger、zh-store 294 id 字节对账播种（自 spec 文件头迁出）                                               |
| [2026-09-24-磁盘策略落地与探针批指标.md](2026-09-24-磁盘策略落地与探针批指标.md)   | P3 磁盘保留策略落地实测 + dedup meta-kind 修复 + e2e_real 260 帧探针批/retry39 指标 + 四区磁盘与账本基线                                                                         |
| [2026-09-27-修复普查与硬尾审计.md](2026-09-27-修复普查与硬尾审计.md)               | 修复普查（`tools/repair_census.py` events 驱动签名聚类，never-done 真身分解）+ 八道只读审计裁决：missing_file/RulesetError/oversize 等族重跑救回口径，真「规则要修」面收敛至尾量 |
| [2026-09-29-selfimp-ledger-digest.md](2026-09-29-selfimp-ledger-digest.md)         | selfimp 常驻环台账（tmp/blob-ledger*.md 九快照）蒸馏归档：2026-09-18~20 战役事件链、事故录、门①-⑤与 harvest 机制产出、关键数字与未决队列                                         |

## 口径注记

- **pytest 计数随时间漂移**：09-15 记 1,020、09-16 记 1,090（当日快照，文件内已勘误为 2,668）、09-19 达 6,450 并仍在增长——引用时注明日期口径。
- **leak 口径随语料层变化**：0.11%（09-14 spike）→ 0.04~0.046%（09-15/16 核心层）→ 0.004%（09-19 全量 13,253 篇）→ 0.000%（同日核心层 L1 复测）；分母不同，勿直接横向比。
- **语料规模阶梯**：39 → 139 → 1,339 → 5,059/5,124 → 5,135 → 13,266 篇；loop1/loop2/loop3 的格数差异来自层化扩展与冻结快照时点。
- **M2 门判定**：09-16 审计按当时最近测值 89.5%<90% 判 FAIL；09-17 复评 4,554/5,059=90.02% 越过——两条记录各自属实，口径为不同时点。
- **09-17 无 HANDOFF**：当日产出由终报与 overseer 作战台账承载，本时间线已如实标注而非补写。
