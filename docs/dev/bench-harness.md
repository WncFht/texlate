# 评测协议与分层契约

本仓的评测体系由两份主仓文件定义：`bench/PROTOCOL.md`（单项评测测什么）与 `bench/TIERS.md`（一个问题该在哪一层被抓）。本文把它们重整为公开口径：先讲四层验证契约，再讲语料与陷阱夹具的底材纪律，最后是 `bench/results/` 的工具链豁免。各评测脚本的逐件清单见 `dev/tools-runbook.md` §3。

## 1. 分层契约：什么问题在哪级验证

核心原则一句话：修复不算完，直到它能看见的最便宜那层被钉住；更高层只接低层结构性看不见的东西。

| 层 | 入口 | 底材 | 量级 | 时机 |
| --- | --- | --- | --- | --- |
| L0 单元/断言 | `uv run pytest tests/`（含 fixture 断言矩阵；契约产出走 `bench/py/fixture_assert.py`） | 合成输入 + `bench/fixtures/*.tex`（@Tnn/@Wnn/@Xn，逐字节即语义） | 秒级/单文件，分钟级/全套 | 每 commit、CI 硬门 |
| L1 机制覆盖 | `uv run python bench/py/parsebench.py --corpus bench/corpus` | `bench/corpus/` 统一物理根（v1 手挑陷阱 + v2 渠道敏感 + 分层全量各层） | 分钟级 | 解析/扫描/归一化改动后，开批前 |
| L2 子集回归 | `uv run python bench/py/stagerun.py {parse,xlat,compile,fixloop} --n N --seed S` 或 `--ids` 定点 | corpus `mechanisms.jsonl` 机制台账 + 分层 manifest | 分钟–小时 | 管线 stage 改动、新机制落账后定向重放 |
| L3 全量集成 | stagerun 全层全臂 + fixloop + sabotage 两臂 → `gate_scorecard.py` + `triage.py`（操作单 `bench/py/runbook_loop.md`） | corpus 全层（core/booster/expand/hot/dev_*/holdout，规模以 manifest 实数为准） | 过夜级 | 里程碑门、发版前 |

问题类型到层级的首选映射：

| 问题类型 | 首选层 | 说明 |
| --- | --- | --- |
| 纯函数/codec/mask/正则/边界逻辑 | L0 | 合成输入当场钉 |
| 日志判定（分类/红线/verdict） | L0 + L3 | 合成 log 钉语义；真 `-file-line-error` log 只有 L3 生产面见得到 |
| 解析机制（新坑/回归坑） | L0 → L1 → L2 | 最小复现 fixture 化登记 @Tnn；L1 确认分布面；`mechanisms.jsonl` 落账后 L2 定向重放 |
| 翻译臂/台账契约（mock/sabotage/perturb） | L0 + L2 | 台账谓词单测钉口径；臂行为用 L2 子集跑真 records |
| 编译/fixloop 规则触发 | L0 + L2/L3 | 合成 log 钉判定；救回率/规则谱只在批量上有意义 |
| 逃逸面/对抗闸（sabotage/gate 红线） | L2 + L3 | sabotage 臂分钟级台账；`escaped>0` 是 L3 硬门 |
| resume/StateStore/跨进程状态 | L2 | records append + `(id,arm,upstream)` resume 语义跨运行才成立，L0 测不到 |
| 性能/规模/并发/资源闸 | L3 | 低层无代表性负载 |
| 接口漂移（harness↔产品） | L0 + L2 | 绑定/spy 钉接线；真跑是 L2 起 |

四条规则。其一「能低不高」：L0 能钉的（合成输入可复现）不许只在 L2/L3 靠批量撞见——批量发现的每个真坑都要沉淀回 L0 断言或 fixture。其二「逐层语义」：每层绿只证明该层契约成立，不证明下层问题不存在（L0 全绿 ≠ 分布面无漂；L3 闸过 ≠ 单点逻辑无残余）。其三「跨层不重复」：同一断言不重复钉在两层——高层存在的理由是低层看不见（规模/真料/跨进程），看得见的归低层。其四「量级兑现」：估时以 `bench/py/runbook_loop.md` 表为唯一事实源；层级归属争议按「cheapest tier that can see it」裁决。

## 2. 评测协议：每个库/管线测什么

这套四项评测最初用于外部 LaTeX 解析库选型（pylatexenc/TexSoup/plasTeX/latex-utensils/unified-latex/tree-sitter-latex 等，选型期已结案，横评脚本在 `bench/py/report/` 与 `bench/ts/`）；同一框架现在是 `texlate.latex` 产品管线的正式评测口径，由 `bench/py/parsebench.py`（parsebench v2）承载。

### 2.1 解析鲁棒性（corpus 全部 .tex）

逐文件记录成功/失败（异常类型）/耗时，30s 超时。产出 `results/{lib}-parse.json` 形态的逐文件明细。

### 2.2 陷阱断言（fixtures）

逐条检查分类是否符合「段落级提取 + 保护 + 重建」管线的期望：`% @Tnn` 标记的每个构造都要么整体保护（数学/引用 key/verbatim/宏定义绝不进可译块）、要么内部文本可译（caption/footnote/item/长标题/强调文本）、要么展平（`\input`/`\include`，注释掉的不展开）、要么不崩（`\ifdraft`、`\bibliography`、`\makeatletter` 区）。断言矩阵随产品解析器演进，以 `tests/test_bench_regression.py` 与 `bench/py/fixture_assert.py` 为准。

### 2.3 Round-trip 保真（corpus 主文件）

parse→serialize→与原文对比：identical / normalized（仅空白差异）/ diverged（报告差异位置和大小）。只测声称支持序列化的库；产品管线的对应口径是 vtex 重建逐字节对比。

### 2.4 泄漏率（corpus 全部文件）

提取可译段落块后，统计块内含 `$`、`\cite`、`\ref`、`\begin{` 等数学/保护标记的块比例 = 泄漏率，越低越好。产品口径把泄漏正则扩到六组（`$`、`\cite`、`\ref`、`\begin{`、`\if`、`\input`），实测量级见主仓审计报告。

## 3. 底材纪律

### 3.1 `bench/fixtures/` — 逐字节即语义

fixtures 是陷阱构造语料：`tricky.tex`（@Tnn 主集）、`tricky-209.tex`（LaTeX 2.09 旧格式）、`tricky-multi/` 与 `tricky-w73/`（`\input` 多文件与路径逃逸）、`tricky-w.tex`/`tricky-wenc.tex`/`tricky-dollar.tex`/`tricky-mask.tex`（野外机制与编码/遮蔽陷阱）、`xlat-traps.tex`（翻译层 @Xn）、`escape-outside.tex`（根外逃逸目标件）。每个陷阱由 `% @Tnn`/`% @Wnn`/`% @Xn` 注释标记定位。

**字节即语义**：这些文件的每一个字节都是测试输入——空白、注释位置、未配平括号都是构造的一部分。任何格式化、润色、自动修复都会改变语义，所以 `*.tex` 整体不进格式化工具链，也不许顺手「修正」fixture 内容。新陷阱从野外发现生长：found-in-wild → 断言覆盖 → fixture 化登记（@Wnn 系列就是这条生长线的产物）。

### 3.2 `bench/corpus/` — 统一语料物理根

全部钉版语料在一个物理根下按层组织，层名归 manifest 管：`manifest.jsonl`（core 均匀层）+ `manifest_booster.jsonl`（补强）+ `manifest_expand.jsonl`（扩库增量）+ `manifest_hot.jsonl`（高引近期）+ `manifest_dev_*.jsonl`（修复训练层）+ `manifest_holdout.jsonl`（留出评测层，EVAL_ONLY 治理——dev 枚举不碰它，防 dev==eval 污染）+ `mechanisms.jsonl`（机制台账，L2 定向重放的依据）。层规模随扩库续增，口径以 `bench/corpus/MANIFEST.md` 与各 manifest 实数为准。语料数据 gitignored；构建管线在 `bench/py/corpus/`。

两个独立生命周期的旁根：`bench/corpus_daily/`（日更 soak 滚动窗口，逐日增删，见 `dev/automation.md`）与 `bench/corpus_iclr_pdf/`（ICLR PDF 产物，非 e-print 树）。

### 3.3 `bench/results/` — 全链划出

`bench/results/` 是脚本产出目录：report/walkthrough/json 均由脚本重写，重跑即覆盖。因此它对**整条格式化与检查链豁免**——改写型 formatter（prettier/git-format-staged/autocorrect）经 ignore 文件与 hook `exclude` 划出，check 类链（markdownlint、ruff）经各自 ignores/extend-exclude 划出，shfmt/shellcheck/taplo 因目录内无对应文件类型而自然 vacuous。含义有二：往里手写文档没用（会被下次跑批覆盖，索引类文档放主仓 `bench/` 根或 docs 库）；若日后往此目录入库脚本/源文件，需要重新评估链覆盖。

## 4. 产出契约与记账

批跑侧的统一契约：每篇/每格一行 append 进 `records/{stage}.jsonl`——行在盘上即 done，崩了同参重启按 `(id, arm, upstream)` 键 resume 续跑。`triage.py` 把 records 聚成 `tickets.jsonl`（按签名 count 降序的待修榜）与 `metrics.jsonl` 趋势；`rundiff.py` 做两次 run 的逐格迁移矩阵；`gate_scorecard.py` 出出口门记分卡；`wave.py` 把「选样→快照→跑波→对账→记分」固化成修复波编排。这些脚本的具体参数在各文件头 docstring 与 `bench/py/runbook_loop.md` 操作单里。
