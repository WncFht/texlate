# milestones.md — TeXlate 指标大事记（2026-09-14 → 09-19）

格式：日期 | commit/来源 | 事件 | 指标影响（有数字写数字）

## D0 · 2026-09-14 立项日

| 日期 | 来源 | 事件 | 指标影响 |
| --- | --- | --- | --- |
| 09-14 | 7da5e8be | init：research & planning phase | 仓库起点 |
| 09-14 | a7db4eee | **解析/编译/覆盖率大对比**(20 报告，39 篇 corpus39+30 fixtures) | 定案：自研半解析器路线。miniscanner 陷阱 32/32、identity 259/259、leak 0.11%——8 个第三方库全灭 |
| 09-14 | c93cc6f4 | tech stack ADR + architecture + roadmap | 技术栈冻结 |
| 09-14 | 8d823855 | format/lint/pre-commit 工具链 + agent 布局 | 工程基线 |

## D1 · 2026-09-15 产品骨架日（全七臂同日落地）

| 日期 | 来源 | 事件 | 指标影响 |
| --- | --- | --- | --- |
| 09-15 | c3431f66 | miniscanner 重写为 `texlate/latex` 九文件正式实现 | 解析器产品化 |
| 09-15 | d22b56b8 | Mouth+Gullet 展开机（plasTeX 移植层，未接线） | v2 引擎就位 |
| 09-15 | 866ca279+bf313773+f730dc0a | segmenter S1→S4 骨架→分派→展开语义→if 界标 | v2 分块器就位 |
| 09-15 | c841c343 | compile 引擎层全套（Engine 协议/注入/判定/normalize/沙箱） | 编译段产品化 |
| 09-15 | 179f7e5b | **fixloop yaml 规则引擎——25 规则全移植** | 修复臂诞生 |
| 09-15 | 0a6bcbed | xlat 翻译编排层（网关客户端/prompt 套件/批量/重试/术语表） | 翻译段产品化 |
| 09-15 | 648212c7 | corpus_v2 139 篇分层语料 | 语料 39→139 |
| 09-15 | afb16217 | corpus_v3 core 1000 篇核心随机层 | 语料 →1,139 |
| 09-15 | 52d490e9 | booster 200 篇机制策展层（107/109 W exemplars) | 语料 →1,339 |
| 09-15 | c750da71+601d065c | parsebench v2 产品管线评测器 | 核心层 1955 文件 parse 100%/identity 100%/leak 0.04%;booster 1388 文件全过 |
| 09-15 | a455fd4d | compilebench v3(n=180×双引擎） | 基线：union pdf 71.7%/clean 39.4%——裸编译天花板实测 |
| 09-15 | beaf1db3 | fixloop bench(corpus_v2 40 篇） | 规则库救回率首测 |
| 09-15 | 7ba3050a+b8e81cec | e2e real bench + v3-100 基线 | 真实网关 E2E 首跑 |
| 09-15 | a0c8713a | alignbench B7——named-dest 保留率评测器 | 锚点臂扶正 |
| 09-15 | 149719af | xlatbench 抽样源接 corpus_v3 | 契约率臂扶正 |
| 09-15 | d400669f+ecb1e089 | server(FastAPI+SSE+SQLite+BYOK)+ SolidJS 阅读器 | 产品面成形 |
| 09-15 | 4e039469 | CLI fetch/parse/run——mock E2E 全链 | 16/16 mock 管线 |

## D2 · 2026-09-16 v2 切换 + fixloop 接线（最大单日指标跃升）

| 日期 | 来源 | 事件 | 指标影响 |
| --- | --- | --- | --- |
| 09-16 | **f4616838** | **v2 产品面切换：parse_tex/parse_file 默认走 Gullet+Segmenter** | splice 残留占位符 1524→0(cutover 硬门） |
| 09-16 | **3d5de8f7** | **fixloop 接线 e2e+worker 两臂 + L2 重译回灌** | union pdf 70.6→89.5%(+18.9pt,n180 同口径复跑） |
| 09-16 | 401e9bbf | argspec.json 入包 + res.macros union | 1820 条宏参规格零装载 GAP 闭合 |
| 09-16 | perf-tail 五修 | 墓标/事件钟/cover_text | latex parse 长尾 −48%(51476→26723ms),identity 零回退 |
| 09-16 | 7b6d83c7 | hot 层 166 篇（OpenAlex 高引）+ e2e fixloop 臂 | 语料 →1,505 |
| 09-16 | e9bba9c8 | expand 层管线 +3,800（后 06bdf4b →3,866) | 语料 →5,305 |
| 09-16 | compilebench v4 复跑 | 同 n180 样本 | union pdf 70.6%/clean 38.3%（基线复测稳定） |
| 09-16 | base-v3-full | n=5,059 全 dev 层基线 | union pdf 71.3%/clean 40.2%;missing_file 占 base fail 92.1% |
| 09-16 | compilebench-v3-zh | zh 条件臂首跑 | union pdf 66.7%/clean 44.4%(normalize 代价面初测） |
| 09-16 | qualbench 新建 | LLM-judge 1-5 分+六 flag 协议 | 质量臂诞生（hjfy 都没有的能力） |
| 09-16 | stagerun-loop1 | 五阶段批量驱动 n=5,124 格全 DAG | scorecard union pdf **97.89%**/clean 84.99%;fixloop rescue 84.0% |
| 09-16 | 4e89bbb6 等 | mechanisms.jsonl 台账合并扩充 | 机制台账 →210 条 |

## D3 · 2026-09-17 波次战（残面打成个位数）

| 日期 | 来源 | 事件 | 指标影响 |
| --- | --- | --- | --- |
| 09-17 | a90978ab | **vendor corpus 落地**(files 10+stubs 13,vendored_fetch) | 绝版宏包缺件面 492 格 fail→73.2% clean;scorecard clean +101 格 |
| 09-17 | d2c377bd+1bbc4fb5 | illegal_unit 段修波（tail-arg 扫尾+env argspec) | 108/108 闭环零回归；clean 84.76→85.03% |
| 09-17 | 746237fd | ReDoS 原子组修复（_WS_NOPAR) | held6 卡死 30min+→<0.1s;pytest 全量 48min→3:46 |
| 09-17 | 164a9e0f | **xlat 非锚定 [n] parse 撤除（P0)** | 译文静默错配通道封死，同批核销 4 P1 |
| 09-17 | a08dda3b | e2e_real translate_tree 收敛到 e2e._scan_tree gates | zero-gate metric break point 修复 |
| 09-17 | f2847c33 | **realn200 真臂验收收官** | union pdf **197/200=98.5%**,end clean 86.5%——真臂与 mock 打平，评测面非虚高 |
| 09-17 | loop1 scorecard 波读 | 同批 records 在代码演进下重评 | 89.17→95.99→97.35→97.89%(pdf)/57.20→68.91→82.76→84.99%(clean) |
| 09-17 | eda6b586(09-18 落） | segmenter gen=0 batch 快道 | parse 提速末段 |

## D4 · 2026-09-18 selfimp 常驻环（23+ 车道并行）

| 日期 | 来源 | 事件 | 指标影响 |
| --- | --- | --- | --- |
| 09-18 | 6d7c4a38 | **selfimp loop 启动**:overseer 台账+R1 报告+假设骨架 | 多代理常驻改进环成形；wave-1 23 lane 发车 |
| 09-18 | stagerun-loop2 | 5,135 格冻结快照全 DAG(6d7c4a3) | scorecard union pdf 97.26%/clean **86.42%**(clean +1.43pt vs loop1) |
| 09-18 | c2-dollar 车道 | dollar 族跨边界失配收口 | leak 57→**0**/136,049 chunks（核心层口径）——四年债单类清零 |
| 09-18 | a4-scorecard | gate_scorecard schema v3(csb 三档/freeze 四信号） | loop1 复跑 97.89/84.99 分毫不差——评测器自证稳定 |
| 09-18 | qualbase | esa2 协议 judge=swe-2-max n=1200 | mean **92.9** [92.4,93.3],contested 8.1%——质量基线建档 |
| 09-18 | qualdrift | n=300 vs qualbase | mean 92.8,KS drift pass——评审稳定性验证 |
| 09-18 | review-2026-09-18 | 指标复盘报告+时间线图 | 历史文档层成形 |
| 09-18 | manifest_2026-09-18 | corpus_daily 日更 soak 首批 | 新语料渠道（RSS→export→daily→stagerun) |

## D5 · 2026-09-19 全量综合测试日

| 日期 | 来源 | 事件 | 指标影响 |
| --- | --- | --- | --- |
| 09-19 | 13c603cf | **corpus_v3 eval/dev split 扩到 8 层 13,266 篇** | dev_vol 2000/dev_recent 1514/dev_failmine 1500/holdout 3020 落地 |
| 09-19 | 完整性审计 | 13,266 cell sha256 全量核验 | 13,266/13,266 通过，0 dup,EVAL_ONLY 治理生效 |
| 09-19 | parsebench-v3-all | **全量 28,904 .tex / 13,253 篇**（13,266 cell − 13 B07 stub cell，无 extracted/ 自动跳过） | parse ok 100.0%/strict identity **99.99%**/leak **0.004%**(76/1,845,338) |
| 09-19 | parsebench-l1gate | 核心层复测 | leak 0/128,460——dollar 清零后守住 |
| 09-19 | compilebench n=500 | baseline+zh 双臂 | base union pdf **90.4%**(xel 80.3%);zh xel clean 72.4%——normalize 转正收益 |
| 09-19 | stagerun-v3all | 80 篇跨层全 DAG | union pdf **98.75%**/clean 88.75%（样本口径） |
| 09-19 | e2e-real n=60 | 真臂综合 | union pdf **58/60=96.7%**(7 fail 全救回，2 skipped_oversize),end clean 86.7%,splice 残留 0,**0 管线引入回归** |
| 09-19 | qualbench-e2ereal | n=1937 judged | mean **94.0**/median 95,≥90 占 90.6%,contested 5.5% |
| 09-19 | xlatbench-v3all | n=271 | hard_ok 93.7%,http_err 0 |
| 09-19 | gullet-v3 | n=200 文档 | 199/200 展开，median 39.6ms |
| 09-19 | 67bb23e3 | daily CS+math soak 管线（RSS→export→corpus_daily→stagerun) | ~1200 篇/日 持续语料渠 |
| 09-19 | loop3（在飞） | 第三批 stagerun | 截面 union pdf 99.17%/clean 80.69%(n=606,PARTIAL) |
| 09-19 | 规则库 | fixloop rules | 143 条（16 分片）,tests 6,450,src 425 文件 |
