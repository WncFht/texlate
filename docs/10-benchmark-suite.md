# 10 · Benchmark 套件规格：建几个、每个怎么建

> 最终技术方案 · 评测器层。配套 `docs/09-benchmark-corpus.md`——09 定义**底材**（语料）怎么建，本文定义**评测器**建几个、各自怎么构建、门槛是什么。
> 证据基础：`docs/research/corpus/parsebench-v1.md`、`docs/research/latex/{validator-rules,validator-ts,engine-matrix,fixloop-rules,alignment-probe}.md`、`docs/research/product/e2e-mock-pipeline.md`、`docs/05-reproduction-plan.md`（E1–E22 实验矩阵）。

## 0. 总览：七个 benchmark

每个 benchmark 对准管线一段 + 一个"组合层"。共同底材 = corpus_v3（docs/09），合成破坏案例各自生成。

| #   | benchmark        | 测哪段           | 底材                              | 核心指标                                  | 现状                         |
| --- | ---------------- | ---------------- | --------------------------------- | ----------------------------------------- | ---------------------------- |
| B1  | **parsebench**   | 解析段           | corpus_v3 + corpus39              | ok / identity / leak / dead·orphan / 漏斗 | ✅ 已有（spike 级），升级 v3 |
| B2  | **fixtures**     | 解析段（单元级） | `bench/fixtures/*.tex` 手造       | 陷阱断言通过率                            | ✅ 已建成（T01–T29）         |
| B3  | **compilebench** | 编译段 + fixloop | corpus_v3 raw blob                | clean/pdf~/FAIL、救回率、规则触发谱       | spike 已验证，需产品化       |
| B4  | **xlatbench**    | 翻译段           | corpus_v3 chunk 抽样              | 硬契约率 / 延迟 / token 经济 / 质量抽样   | gwbench 雏形已验证           |
| B5  | **e2ebench**     | 全链（组合）     | corpus_v3 子集                    | 每环节成功率漏斗 + 终态分布               | mock 管线已验证（16/16）     |
| B6  | **validbench**   | 校验段           | 生成的破坏案例（语料 chunk 变异） | 检出率 / FP / 延迟                        | exp 已验证（100%/0FP）       |
| B7  | **alignbench**   | 阅读体验（锚点） | en/zh 编译产物对（B3/B5 产出）    | named-dest 保留率 / 链权                  | probe 已验证（保留 ~100%）   |

依赖序：`corpus_v3 → B1 → B4 → {B3, B5} → B7`；B2/B6 独立（合成输入）。

> **现状列更新（2026-09-16 二校）**：B3 已产品化（compilebench_v3.py + fixloop_bench.py，v4+fixloop 臂联合 pdf 154/172=89.5%，`bench/results/compilebench-v4-2026-09-16/` + `base-v3-full-2026-09-16/` 全量基线在盘；**zh 条件臂已跑** `compilebench-v3-zh`/`fixloop-zh-cbv3`）；B4a 已扶正 xlatbench（硬契约基线 240 调用建档）+ B4b 质量臂 `qualbench.py` 已建（LLM-judge 六类 flag+1–5 分，`c81d695`）；B5 Mode A/D 已跑（e2e-real n100 chunk ok 99.97%），**Mode B/C 已实装** `e2e_mock_bench.py` pipeB-xel/pipeC-xel（`f4d9ec8`/`c187025`，`mock-sabotage-v3-2026-09-16/`）；B7 已扶正 alignbench + 已归因（xelatex ~100 错截断 `cite.*` 必死；ctex 共享计数器改 theorem 锚名是离群对根因）+ pipe-fix 产物复测 mean 0.9918（`b7-pipefix-2026-09-16/`）。逐门证据矩阵见 `research/audit-2026-09-16/spec0910.md`。
>
> **套件之外新件（同日批量层）**：`stagerun.py` 五阶段批量驱动（ingest/parse/xlat/compile/fixloop 子命令 + append records + (id,arm,upstream) resume + `--sem` 网关信号量，设计 `research/product/2026-09-16-batch-hardening-design.md`，操作单 `bench/py/runbook_loop.md`）；`triage.py` records→tickets.jsonl 聚类+趋势+报告；`translators_bench.py` xlat 臂工厂（mock/sabotage-b/c/perturb）；`preflight_batch.py` 批前一票闸。

## B1 · parsebench —— 解析段基准

**状态（2026-09-15）**：已落地 `bench/py/parsebench.py`（v2，texlate.latex 产品管线评测器）。首轮：corpus_v3 核心层 1955 文件 parse 100%/strict identity 100%/leak 0.04%/dead 0（coverage 94.4%†）；补强层 187 篇 1388 文件同指标全过（coverage 72.5%）。manifest 非空时即抽样框（`--manifest manifest_booster.jsonl` 切层）。结果 `bench/results/parsebench-*-2026-09-15/`。

**测什么**：`texlate.latex` 对真实语料的解析正确性——能不能零崩溃、能不能逐字节还原、可译 chunk 里有没有漏进受保护内容。

**底材**：corpus_v3 全部 `extracted/`（~1,200 篇 / ~2,000+ .tex）+ corpus39 手挑陷阱集（对拍基线）+ corpus_v2（渠道敏感性）。

**构建方法**（harness 已存在：`bench/py/parsebench.py`，扶正为 `bench/parsebench/` 或 `src/texlate/bench/`）：

1. 对每篇：主文件定位 → flatten → `parse_file`（30s 超时）→ `reconstruct()` 三次测量（identity / 空译文 fake-translate / 占位译文）。
2. 逐文件记录 `files.jsonl`：`{paper_id, file, ok, identity∈{strict,normalized,diverged}, n_chunks, leak_hits[], wall_ms}`。
3. 逐篇聚合 `papers.json`：路由标签（reject/xelatex/minted/non-utf8/no-hyperref——**即 B3 的静态路由金标准**）、flatten coverage（orphan tex 清单）、multi_doc/rootless 标记。
4. `summary.md`：漏斗（fetched→有 .tex→rooted→ok→identity→leak→dead/orphan）+ 逐条泄漏人工归因 → **归因写回 `mechanisms.jsonl` 台账**（docs/09 §4.3，benchmark→语料的反馈环）。
5. 统计口径：核心层加权池化率 + 宏平均双报、Wilson + 月簇稳健 bootstrap CI（docs/09 §7.2）。

**配套探针**：oracle 对拍（`oracle_extract.py`/`oracle_diff.py`——plasTeX par 节点规范化文本流 vs 我们 chunks，`SequenceMatcher` 字符级 recall/noise；`[[*_n]]→*` 哨兵归一化防整段错位）。定位：开发期召回探针，不进 gate。

**门槛**：docs/09 §8（ok 100% / identity ≥99.5% / leak ≤0.15% / dead·orphan=0 / flatten ≥99%）。回归用法：每改一行 scanner 重跑出差异表（v2 规模 17.6s 全量 → v3 预计 ~3min）。

## B2 · fixtures 陷阱断言集 —— 解析段单元级

**状态（2026-09-15）**：已落地 `tests/test_bench_regression.py`（54 用例全绿；2026-09-17 勘误：现 98 用例）——spike `miniscanner_test` 断言矩阵移植到 `texlate.latex`，断言函数与 `bench/py/fixture_assert.py` 共享。spike 原件已退役至 tmp/exp/。

**测什么**：已知机制的逐条断言（"这个具体坑处理了吗"）——parsebench 测分布，fixtures 测机制。

**底材**：`bench/fixtures/*.tex`，`% @Tnn` 标记。**逐字节即语义——永不格式化/润色**（不在 format 链内）。

**构建方法**：

1. 现有断言矩阵照搬 spike：T01–T29 单点陷阱 + 209×3 组合 + multi×4。
2. **生长机制**：parsebench 归因（B1-4）和 mechanisms.jsonl 的 `found-in-wild` 条目达到 `covered` 后 → fixture 化（最小复现提取 + `@Tnn` 登记）——语料里每个真坑沉淀为永久断言。
3. 断言写在 `tests/test_bench_regression.py`（spike `miniscanner_test.py` 移植，import 换 `texlate.latex`）。（勘误 2026-09-17：原文路径 `tests/latex/` 为误记——实装平铺在 `tests/` 根，§B2 状态行已写真名。）

**门槛**：33/33 dict 断言全过（勘误 2026-09-15：原文 32/32 是旧口径——实际断言面 = tricky 26 + 209 三项 + multi T14×4 = 33，加 209 parse_ok 行共 34），新增断言只增不减；BUG1 类回归断言（"ph 尾 `\letters`+后继字母"=0）随修复入列——该指标首测分布：corpus39 5333 / corpus_v2 578 / corpus_v3 10487，rewrite 后实测 0。

## B3 · compilebench —— 编译段 + fixloop 基准

**测什么**：归一化 + 注入 + 引擎 + 修复循环的真实救回能力。这是 hjfy 用 ~5000 篇人肉沉淀护城河的对应物。

**底材**：corpus_v3 `raw.*` blob（**必须字节级保真渠道**——图/.bst/.bbl 全在才能编译，scholarweave 有损源在此被排除的根因）+ B1 产出的路由标签作静态路由金标准。

**构建方法**：

1. 网格 = `paper × condition × engine`：condition ∈ {base 原文 / zh-injected 注入 ctex / mock-translated 占位译文}（mock 用 B5 管线产）；engine ∈ {xelatex, tectonic}（路由预检先行：documentstyle→reject、eps/pstricks→xelatex、minted-frozencache→tectonic）。
2. 每格：`normalize → inject → Engine.compile(沙箱, ≤2 pass, 240s) → fixloop(yaml) → clean 判定三件套`（docs/08 §4.3）。
3. 逐格落 `results.jsonl`：verdict（clean/pdf~/FAIL/reject）+ 每轮 `{cat,pay,rule,result}` + log_excerpt → **直接灌 `cases.jsonl` 沉淀机制**（docs/08 §5.5）。
4. 归因表：sig 聚类分布 × 规则触发谱（sig=首错 cat；构成中计数最高的 cat 严格超过首错 cat 计数时改挂该众数 cat（该 cat 须为 error_cats 构成成员）——verdict_sig 口径；spike 实测：missing_* 16 格救回 16/16、install 系占触发 87%）。

**指标**：clean 率（分 condition/引擎/时代带）、救回率（fail→clean|pdf~）、规则 fires/rescues、stuck/unfixable 率、修复轮数分布。

**门槛（M2 出口）**：200 篇语料 zh 条件编译成功率 ≥90%（hjfy 95% 为渐近线）；reject 判定正确率 100%（路由标签对拍）；无回归（clean 格不被规则改脏）。

**状态（2026-09-15）：fixloop 臂已落地**——`bench/py/fixloop_bench.py` + `bench/results/fixloop-corpusv2-2026-09-15/`：corpus_v2 40 篇无偏样本 × 25 规则库（2026-09-17 勘误：规则库计数不再手维护——现行规则库为 `src/texlate/compile/fixloop/rules/` 分片目录，条目数以生成源为准），union baseline pdf 26/40 → fixloop pdf **36/40**（clean 层 31/40）；xelatex 臂 FAIL→pdf 25/34。已知缺口：tectonic 臂 eps_route 预检过度拒收（baseline pdf~ 格被 0r 拒 6 例）、legacy 包 shim 缺位（revtex.cls/psfig.sty/aastex.cls 类）。

> 更新（2026-09-16）：base×双引擎臂已跑完——compilebench-v4 全量 180 样本（`61a9e16`），baseline 仅 1 格判定更正性迁移；fixloop 臂联合 pdf 127/172→**154/172（89.5%）**，xel missing_file 109 FAIL→84 pdf（tlmgr usermode 装包层实证），归因 `bench/results/compilebench-v4-2026-09-16/summary-diff-v3.md`。zh 条件臂首跑 `compilebench-v3-zh`/`fixloop-zh-cbv3`（union pdf 86.3%）。B3 zh 臂距门槛 200 篇 ≥90% 仍差 n 补齐。

## B4 · xlatbench —— 翻译段基准

**测什么**：LLM 后端的占位符契约遵守 + 真实翻译质量 + 经济性。两子层：

**B4a 硬契约层**（harness 已有：`tmp/exp/gwbench/bench_free.py` + `aggregate.py` 扶正）：

1. chunk 抽样：corpus_v3 chunks 按 kind 分层抽样（含 `\bibitem` 前缀 / `\href` / `\` 压力样例陷阱集——bench/fixtures 增 xlat 类）。
2. 网格：`chunk × model × repeat`；每响应过 L0 validator。
3. 指标排序管线：**硬契约率**（丢/造占位符 + 丢脆弱命令 + validator error）→ ord 软信号（合法中文换序不降权）→ 延迟 p50/p95 → reasoning 开销 → token 经济。338 调用大样本实证此方法有效（swe-2-medium 100% 全场第一）。
4. 用途：模型选型/白名单刷新（免费集 promo 到期即重跑）+ prompt 措辞回归（bump prompt_version 必跑）。

**B4b 质量层**（需 LLM key，M1 出口）：

> 落地注记（2026-09-16）：`bench/py/qualbench.py` 已建（`c81d695`）——LLM-judge 对段对打 1–5 分 + 六类 flag（漏译/错译/术语不一致/格式破坏/幻觉/语言混杂），对应本条第 3 项；首跑 `bench/results/qual-run-2026-09-16/`。第 1/2 项（真译文进编译网格、占位符扰动）由 e2e_real_bench `--fixloop`/`--base` 臂与 e2e_mock_bench pipeC 部分覆盖。

1. 整篇真实翻译 corpus_v3 抽样子集（~100 篇）→ 译文进 B3 编译网格测"翻译对编译的实际影响"（中文长句撑爆 `\hbox`、罕见字缺字形、bibtex 多遍收敛——E10 未覆盖项）。
2. 占位符位置敏感性：mock C（随机挪动 ~10% 占位符）量化 splice 鲁棒性（e2e pipeline 已留接口）。
3. 质量抽样：段对抽取 → 人工/LLM-judge 评流畅度与术语一致性（三级术语表的实际提升测量点）。

**门槛（M1 出口）**：100 篇真实翻译端到端 ≥85%；硬契约率大样本不回退（对照 80/80 基线）；L0 检出率不回退。

## B5 · e2ebench —— 端到端组合基准

**测什么**：全链组合后的逐环节成功率——单段绿不等于组合绿（E10 实证价值）。

**底材**：corpus_v3 子集（先 ~50 篇，后全量）。

**构建方法**（harness 已扶正为 `src/texlate/e2e.py`——`mock_translate_tree`/`pipe_condition`/`base_condition`/`mock_pipeline_run`，CLI `texlate run` 与 `bench/py/e2e_mock_bench.py` 共用；勘误 2026-09-15：原写 `tmp/exp/e2e/pipeline.py` 扶正，实际落地为产品模块而非 bench 脚本，翻译走 XlatPipeline(MockTranslator)+L0 校验器全产品 API。勘误 2026-09-17：`e2e_mock_bench` 的 translate_tree 已改为单源调 `e2e._scan_tree`、fixloop 参数对齐产品签名（`d240b43`）——harness 不再自持第二份扫描实现。勘误 2026-09-17：`e2e_real_bench.translate_tree` 同收敛至 `e2e._scan_tree`（`a08dda3`）——此前 real 臂零文件闸送译 support 件，**n200 run（含）之前的 chunks/src_chars/ok 率等体积类指标与修复后新 run 口径断点不可直接比**（终态类指标不受影响；详见 `bench/results/realn200-2026-09-17/report.md` §4）：

1. Mode A 位置忠实 mock：注入 ctex + 占位译文 + splice + 编译 → 验机械链路（已实证 16/16 PDF、0 FAIL、identity 111/111、leftover=0。勘误 2026-09-17：**mock 保真盲区登记不修**——`MockTranslator._PROSE_RUN_RX` 只认 ASCII 字母 run，西里尔/希腊文等非 ASCII 散文原样回显不进译文，mock 臂对含此类散文的语料过估「忠实」（scout-triage-2026-09-17 F-echo 1 格，low；`bench/py/qualbench.py:_PROSE_RUN_RX` 同源副本同盲区）。真译臂不受影响。）
2. Mode B 幻觉 mock：注入占位符丢失/幻觉 → 验校验链兜底（132 处破坏编译前 132/132 捕获——"出 PDF≠成功"的实证来源）。
3. Mode C 位置扰动 mock：随机移位 ~10% 占位符。（勘误 2026-09-17：已实装并跑——`e2e_mock_bench.py` pipeC-xel/pipeC-tec 双臂，结果 `bench/results/mock-sabotage-v3-2026-09-16/`；pipeB 同有 -tec 变体，B/C 每 Mode 双引擎各一臂，原"待跑"标注失效。）
4. Mode D 真实：B4 真译文接入（M1 后）。（勘误 2026-09-17：已跑——e2e-real n100、chunk ok 99.97%，见 §0 现状列。）
5. 产出 **漏斗看板**：下载/解包/定位/解析/翻译/校验/编译每环节成功率 + 终态分布（done/partial/fault/degraded_*）——这就是"端到端成功率看板"的实现（docs/02 §测试策略）。

**门槛**：mock A 全绿（PDF+identity+ 零残留占位 + 中文实际渲染）；mock B 破坏 100% 编译前捕获；Mode D 成功率即产品 SLA 观测点。

> 增补 2026-09-16（**pipe-fix 救回臂**，`e2e_real_bench.py --fixloop onfail|always|never`）：pipe-xel 产物树 copy → fixloop（xelatex usermode + TUNA 钉 + tlpdb 索引，配方复用 `fixloop_bench`）→ 救后 xelatex+judge 复判，union 口径取 pipe-xel/pipe-fix 较优者。语义经冒烟实证校准：**onfail 只接 `fail`**——partial 已产出 PDF（warning 级判据非编译错误），fixloop 的 halt_on_error 引擎 + 树改写只会丢 PDF 而救不了 warning（hot 层 n9 冒烟实测 partial→fail 回退 2/3、fail→{clean,partial} 救回 3/4）。inject reject 不救。（勘误 2026-09-17：floor 底板落地后 `_want_fix` 已重校为 **fail + misschar/error 级 partial**——`e2e_real_bench.py:_want_fix` 注释自证；产品链 e2e/worker 对任意非 clean 进 fixloop 口径更宽，待 owner 收敛。）证据 `research/product/2026-09-16-e2e-pipefix-hotlayer.md`、`bench/results/e2e-hotfix-smoke-2026-09-16/`。

## B6 · validbench —— 校验段基准

**状态（2026-09-15）**：已落地 `bench/py/validbench.py`——corpus_v2 1503 对 gates 全绿（10 类破坏 L0 100% 检出、干净对 0 error-FP、14 探针全过、摊薄 0.374ms/对）；spike 1636 例 `--replay` 同 schema 兼容。结果 `bench/results/validbench-*-2026-09-15/`。

**测什么**：L0/L1 校验器对 LLM 破坏的检出能力——校验器本身必须被评测（"校验器也必须被测试语料验证"——实现期真抓到过自身 bug）。

**底材**：corpus chunk 对 + 变异器生成的破坏案例。

**构建方法**（harness 已有：`tmp/exp/rule-validator/{gen_cases,run_eval}.py` + `tmp/exp/ts-validator/{gen_cases,run_eval}.js` 扶正合并）：

1. 变异器：干净 chunk 施加 10 类破坏（丢 `}`/丢 `$`/`\end` 改名/删 `\end`/丢占位符/占位符拼错/`\[` 不配对/幻觉宏/删 cite key/多余占位符）× ph/raw 两层 → `cases.jsonl`（现有 1636 例规模，语料扩后重新生成）。
2. 对抗手工探针：合法改写（掉 `\emph` 组）/ src 自带不平衡继承 / 占位符换序 / `\cite {k}` 带空格 / `\cite{a,b,c}`→`{a,b}` 漏 key / 全角 `【MATH_1】`——边界行为逐条断言。
3. 指标：检出率（按破坏类分列命中规则）、error-FP（干净对）、warn-only 率、延迟/对、lev≤2 修复建议率。
4. L1 层同口径跑 tree-sitter 版（绝对/相对判定分开报）。

**门槛**：10 类破坏 100% 检出、干净对 0 error-FP、L0 ≤1ms/对。新增破坏类随真实 LLM 失败案例沉淀（B4 产出反向喂 B6）。

## B7 · alignbench —— 锚点保留基准（滚动同步）

**测什么**：zh 重编译后 named-destination 锚点保留率——对照阅读器滚动同步的质量上限（docs/05 §3-18 方案的前提条件）。

**底材**：B3/B5 编译产物 en/zh PDF 对。

**构建方法**（harness 已有：`tmp/exp/align-probe/` 扶正）：

1. pypdf 提双侧 named destinations → 同名锚点配对 → 保留率 + 最大权值单调链权重（section 12/图表 10/equation 4/cite 2，`page.*` 权 0）。
2. 回归断言：锚点保留率 ≥95%（实测 8/11 对 =1.000、778 页书 5519 锚 100%）；**保留率 <95% 本身可当 zh 编译完整性探针**。
3. 退化集：无 hyperref 工程（~31%）双侧注 hyperref 兜底或同页码同 fraction 退化的正确性断言。
4. 分段器回归联动：`\input/\include/\label/\bibitem` 进 chunk 的锚点连锅端案例（1502.01589 型）必须进 fixtures B2。

**门槛**：有 hyperref 对保留率 ≥95%；无 hyperref 对走退化路径不崩。

## 8. 汇总：构建顺序与里程碑映射

| 序  | benchmark | 何时建/跑                      | 里程碑门                   |
| --- | --------- | ------------------------------ | -------------------------- |
| 1   | B1+B2     | M0 重写验收（语料就绪即跑）    | corpus39+v2 479 文件全绿 † |
| 2   | B6        | M0–M1（校验器随写随测）        | 100%/0FP 保持              |
| 3   | B4a       | M1（LLM 后端选型+prompt 回归） | 硬契约率基线建档           |
| 4   | B3        | M2（fixloop 主战场）           | 200 篇 ≥90%                |
| 5   | B5 A–C    | M0 起常驻；D 随 B4b 接入       | mock 全绿 + 漏斗看板       |
| 6   | B4b       | M1（真实翻译质量）             | 100 篇 ≥85%                |
| 7   | B7        | M3（阅读器前置验证）           | 保留率 ≥95%                |

† 勘误（2026-09-16）：corpus_v2 现为 139 篇/224 .tex（语料冻结后 +2），corpus39 为 256 .tex，合计 480——「479」是冻结前口径；两门均已全绿通过。

统一产出契约：每个 benchmark 落 `bench/results/{name}-{corpus}-{date}/` 三件套（`files|cases.jsonl` 逐单元明细 + `summary.md` 漏斗/归因 + `papers|cells.json` 聚合）；`bench/results/` 划出 format/lint 链，报告由脚本全权重写。
