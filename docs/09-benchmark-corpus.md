# 09 · Benchmark 语料构建规格（corpus）

> 最终技术方案 · ~1,200 篇分层 benchmark 语料的构建管线与统计口径。
> 证据基础：`docs/research/corpus/v3-plan.md`（定稿计划）、`frame-and-allocation.md`（frame+30 簇 + 配额）、`ia-pilot.md`（IA 管道实测）、`post2020-sourcing.md`（渠道裁决）、`bench-construction-methods.md`（方法学引证）、`parsebench-v1.md`（指标口径）、`parse-metrics-literature.md`。
> 实现按本文执行。法务/发布细目不在本文（见 `docs/research/` 档案）。

## 0. 目标与设计原则

为 `src/texlate/latex/` 重写（及编译段、fixloop）提供**总体无偏、分层可断、机制覆盖**的验证底材。六条原则：

1. **零在线 API**：语料 100% 来自已发布批量数据集（IA tar / HF tar / HF parquet / HF 元数据快照），永不请求 arxiv.org → 可复现、无限流、可断点续跑。
2. **Measure-then-sample**：bulk tar 给出整月全集 → 先测全体成员真实特征（docclass/文件数/编码/`\input` 深度），再按真实特征配额抽样。优于"盲抽 ID 再祈祷分层命中"。
3. **字节保真分级**：raw e-print blob 原样入库（编译段底材）+ extracted tex（解析段底材）；有损源（scholarweave）只作对照不进正式语料。
4. **两层语料分离**：核心随机层回答"成功率多少"（无偏估计），补强层回答"这个坑处理了吗"（配额命中稀有机制）——**报告分开，池化估计只用核心层**。
5. **钉版可复现**：成员级 sha256 + `(channel, item, member)` 记 manifest；语料可凭脚本重生成。
6. **可发布子集预埋**：license 分层同步记录，CC 系子集可公开分发。

## 1. 规模论证（sizing）

| 需求                          | 所需 n                    | 依据                                                                     |
| ----------------------------- | ------------------------- | ------------------------------------------------------------------------ |
| 池化「parse+identity ≥99.5%」 | ≥600 篇零失败             | rule of three：零失败 95% 上界 ≈ 3/n（Hanley & Lippman-Hand, JAMA 1983） |
| 每时代带单独下结论            | ~200/带 × 5 带 = 1,000    | 带内零失败 → ≤1.5% 上界                                                  |
| 泄漏率 CI                     | chunk 级 ~15 万自动满足   | n=137 时 17,375 chunks → ±0.05%；1,000 篇 → ±0.005%                      |
| 稀有机制发现（0.5%/篇）       | 1,000 篇 → 期望 ~5 次命中 | n ≥ ln(1-α)/ln(1-p)（验收抽样传统）                                      |
| 编译段复用                    | 每引擎×时代 ≥100          | 同底材摊薄                                                               |
| 比例误差边际                  | n=1,000 → ±2.8%           | n=z²p(1−p)/e²（Cochran 1977 ch.4）                                       |

**结论：1,000 核心 + ~200 补强 = ~1,200**。现有 corpus_v2（137 篇无偏钉版）折入核心层 → 新增 ~1,060；corpus_v2 保留 `channel=direct-fetch` 标签（抽样 frame 不同：HEAD 验证 vs tar 成员），池化时做渠道敏感性检查。（勘误 2026-09-17：同日再增 **expand 层 3,800**——`manifest_expand.jsonl`，管线 `bench/py/corpus/build_corpus_expand.py`，QC `bench/results/corpus-expand-qc-2026-09-16/`；四层合计 2026-09-18 时点 **5,232** = 1000+200+166+3866（hot 收官 166、expand 新批续增中——实数以 `MANIFEST.md` 为准），仍守加层不删层约定。再勘误 2026-09-19：评测/开发分轨再加 **holdout/dev_vol/dev_failmine/dev_recent 四层 8,034**，口径与治理见 §4 末注记——八层合计 **13,266**。）

**先例裁决**：同类 benchmark **没有一篇给 n 写统计论证**（SWE-bench 2,294 是漏斗剩余、Nougat 不披露、olmOCR-bench 按类凑数）——写明论证本身是卖点（Card et al. EMNLP 2020）。规模先例恰好同量级：Image2Struct（NeurIPS 2024）~1,200 篇同从 arXiv 源码抽，其 "max 40/day to induce temporal diversity" 是「月簇内配额上限」的逐字先例；OmniDocBench「大池 200k→聚类→配额均衡 981」即两阶段配额先例；unarXive 两版发行 + LAION "URLs not images" 支撑发布形态。

**簇数权衡**：~30 月簇 × ~35 篇 > 15 簇 × 70。30 簇有真引证（WHO EPI 30×7 传统 Henderson & Sundaresan 1982；Kahan et al. Trials 2016「minimum 30–40 clusters」），但 deff=1+(m−1)ρ（Kish 1965）要求估 ρ——**行动项：用 corpus_v2 的 137 篇跨月样本估 TeX 特征月间 ICC 上界**（文献无现成值，P4 前补上）。

## 2. 数据源矩阵

取数渠道与成员级语义定案见 `docs/06-arxiv-source.md` §6（IA 主力 ≤2020 / TIGER-5T 主力 post-2020 / scholarweave 不进正料 / metadata-snapshot 作 frame / S3 不用）。本文只列 benchmark 相关要点：

- 成员名 `{YYMM}/{id}.gz|pdf` 无版本号 → manifest 四元组 `(channel, item, member, blob_sha256)` 钉版；`resolved_version=null`。
- 月块只收当月新提交（跨月重叠实测=0）→ 去重键 = id。
- zipsum.tsv 成员序==tar 序 → 免下载建全月索引；晚期 item 缺失时退化整 chunk 流扫或 Range 头扫描。
- 簇单元 = 月内 1–2 chunk tar（IA 130MB–543MB / TIGER ~0.53GB≈150 篇）——整月粒度 620GB 不可行，已消解为单 chunk 粒度。
- `curl` 必须 `-L`（IA 302→dn* 节点）。

## 3. Frame（抽样框）

产物 `bench/frame/frame.parquet`：3,164,528 行 × 14 列（duckdb+httpfs 列裁剪远程扫 10 shards ≈122s，未落全量；2026-09-19 起与 frame_raw.parquet、item/cluster 索引等 14 件规划资产同置 `bench/frame/`——原 `tmp/exp/frame/` 已退役）。完备性已验证：新式 id 99.9994%（全库仅 17 个 id 缺，删除/未公布号）；旧式逐 archive-month 序号连续（表面缺口全是编号偏移，真实缺失 <1%）。

schema 关键列：

| 列              | 定义                                                                                |
| --------------- | ----------------------------------------------------------------------------------- |
| `tar_yymm`      | **id 内嵌公布月**（新式 `^(yymm)\.` / 旧式 `/yymmNNN`）= tar 成员归属月，簇抽样主键 |
| `year_band`     | `a≤2006 / b 07-11 / c 12-16 / d 17-20 / e 21-25 / f 2026+`（f 不进样）              |
| `primary_cat`   | categories 首 token（157 distinct）                                                 |
| `cat_group`     | 8 组（旧 archive 名归并：alg-geom→math、cmp-lg→cs 等，实测全覆盖）                  |
| `license_class` | `cc0-pd/cc-by/cc-by-sa/cc-by-nc-sa/cc-by-nc-nd/arxiv-nonexclusive/missing`          |
| `n_versions`    | len(versions)（`versions[1]` 恒为 v1 已全量验证）                                   |

带分布：a 400,888 / b 325,304 / c 493,421 / d 598,334 / e 1,104,329（f 242k 不进样）。时代漂移显著：a 带 hep-phys 37%、cs 仅 1.9% → e 带 cs 40% 反超——**cs 源码异质性风险集中在 d/e 带**。

**坑（实测记录，全部已绕过）**：id 月 ≠ v1 月（3.1% 新式 +1 月滚动 + pre-1991 backfill 长尾）→ **簇归属必须用 tar_yymm 不用 v1 月**；yymm 字符串比较在 2000 年界断裂（'0612'<'9501'）→ 先转年序键；shard 不按 v1 时序聚簇（统计必须全扫）；license 是记录级最新版本值；frame 不知成员形态（pdf_only 率由 S2 实测，配额按 ~5% 折损预留）；2011/2012 两月 IA 无 TIGER 有（可作 IA 末端补洞）。

## 4. 分层与配额

### 4.1 簇选择（30 簇已定）

簇月 = 带内**累计论文量等分位点**（(i+0.5)/6, i=0..5）：按论文密度加权且覆盖带首带尾。抽样宇宙：a 带 1995-01 起（9107-9412 化石层有意排除，2.09 遗存由补强层挖）；e 带 ≤2501（TIGER 截止）。

| 带      | 月份簇（yymm）                     | 渠道  | 每簇配额 |
| ------- | ---------------------------------- | ----- | -------: |
| a ≤2006 | 9703, 9910, 0111, 0307, 0501, 0605 | IA    |    33–34 |
| b 07–11 | 0707, 0806, 0905, 1003, 1012, 1109 | IA    |    33–34 |
| c 12–16 | 1206, 1306, 1404, 1502, 1511, 1608 | IA    |    33–34 |
| d 17–20 | 1706, 1803, 1811, 1907, 2003, 2009 | IA    |    33–34 |
| e 21–25 | 2105, 2203, 2211, 2308, 2403, 2410 | TIGER |    33–34 |

d/e 带每簇取间隔 2 块扩候选池（成员按 id 连续 → 类目轻度聚集）；最小簇 9703 也有 ~1.3k 成员，配额无压力。

### 4.2 核心层 1,000（池化估计唯一来源）

- **带内等分** 200/带 × 5 带（等分给每带独立 CI，带内零失败→1.5% 上界；比例分配会牺牲带间可比性）。
- 簇内按 `cat_group` 软配额（参照 `cluster-cat-mix.csv` 该月实际类目份额）。
- **方法学红线**：配额 cell 内必须**随机抽取**（层内概率样本），不是"凑够就行"——否则落 Neyman 1934 对 purposive/quota 抽样的批判旧辙；池化估计做事后分层加权（Holt & Smith 1979 / Little 1993），`w_cell = (frame 宇宙 cell 数)/(样本 cell 数)`，cell = year_band × cat_group。
- 簇内配额不满 → 允许跨簇补位，记录配额达成率。

### 4.3 补强层 ~200（agent 策展制，不进池化）

脚本 flag 只做"已知签名"候选预筛；真正的机制覆盖靠**机制台账 + agent 定向狩猎**。

**机制台账** `bench/corpus/mechanisms.jsonl`——每行一机制：

```json
{"mech_id": "...", "title": "...",
 "kind": "known-trap|suspected|found-in-wild",
 "detection": "regex|feature|manual",
 "status": "wanted|partial|covered|exhausted",
 "examples": ["id", ...], "evidence": "...", "notes": "..."}
```

种子：corpus39 陷阱 T01–T29、rewrite spec 增补项、parsebench v1 发现（caption 参数内注释残留、裸 `\input`、multi_doc、`%auto-ignore` stub、pdf_only…）。

**两类 agent 角色**：

- **Curator**（按时代带分工 ~5-6 个）：从池内随机取论文**实际打开 tex 阅读**，判断"有没有 features 没标出的有趣机制" → 提名 `{id, mech_tags, justification}` + 新机制写台账。
- **Hunter**（~2-3 个）：领台账 `wanted/partial` 条目，设计检出手段（tex staging 上 zgrep / frame 查询 / 浓度先验簇），**开文件验证**后提名；找不到记 `exhausted` + 搜索证据——**"还缺什么"本身就是产出**。

**检出手段分层**（成本递增，便宜的先用）：

| 层  | 手段                         | 覆盖                 |
| --- | ---------------------------- | -------------------- |
| L0  | 成员名/zipsum 索引（免下载） | pdf_only/single-gz   |
| L1  | S2 features flag             | 已知签名候选预筛     |
| L2  | tex staging 上 zgrep         | hunter 定向搜证      |
| L3  | agent 开文件读 tex 判机制    | regex 写不出的一切坑 |

**关键资产：tex staging 不删**——S2 把全成员 tex 文本 gzip 落盘（每簇 ~0.1-0.3GB）→ ~1.5-3 万篇本地可检索语料 = hunter grep 底材 + curator 阅读池。机动 cell 取消固定配额，改为台账 loop 自然产出（总盘 ~200 封顶）。

基础配额锚点（最小保障非上限）：B01 2.09 遗存 30 / B02 非 UTF-8 30 / B03 深多文件 30 / B04 低 TeX 密度类目（cs/econ/eess，d/e 带）30 / B05 宏包机制（minted/pstricks/psfrag/vendored cls）25 / B06 大字节 >2MB 20 / B07 边缘形态（单 gz/pdf_only，记丢弃原因）25。

> 勘误 2026-09-15（P3 已执行）：台账 143 条（W01–W109 野例 + T/B 种子；2026-09-17 勘误：台账为 append-only jsonl 且含 verdict 批注行，行数以 `bench/corpus/mechanisms.jsonl` 实文件为准）；5 curator + 3 hunter 共产出 544 条验证提名（`nominations/*.jsonl` 审计轨迹入库）；`select_booster.py` 选出 200 篇（B 地板全达成、W 覆盖 107/109——W108/W109 池内无例证即 hunter exhausted 记录），明细 `booster_selection.jsonl` + `selection_report.md`。
>
> 增补 2026-09-16（**hot 层**，第三层、扩展不替换）：核心均匀层回答「成功率多少」、补强层回答「坑处理了吗」，但两者抽样框都不是真实用户负载——hjfy 类产品压倒性服务近期高引论文，且核心层止于 2412（TIGER 截止）。hot 层补**需求轴 + 时近轴**：`hot-cite`（OpenAlex `locations.source.id=S4306400194` + `from_publication_date≥2024-01-01` 按 `cited_by_count` 降序取头 120）+ `hot-recent`（同源 2025-06-01+ `sample=` 随机 40）。取源走产品路径 `acquire_source`（arxiv e-print 钉版，3.05s/发、日预算 ~180 → `--limit 85`/日续跑），入库 `manifest_hot.jsonl`，管线 `bench/py/corpus/build_hot_layer.py`（candidates/fetch/report）。不进池化估计（frame 非均匀），按 `stratum_cell=hot|*` 单独报。首日 85 发：入库 72 + `pdf_only` 跳过 13（高引论文无 TeX 源是真实负载固有类）。证据 `research/product/2026-09-16-e2e-pipefix-hotlayer.md`。（勘误 2026-09-18：hot 层当日收官全层 **166 篇**——hot-cite 124 + hot-recent 42，均超计划配额 120/40；收线明细 `bench/corpus/MANIFEST.md` 热层节。）
>
> 增补 2026-09-19（**评测/开发分轨扩层**，再加四层 8,034）：M2/M3 把语料用途分岔为「评测」与「dev 训练/调试」两轴——核心均匀层仍是池化估计唯一来源。**holdout 层 3,020**（evaluate-only 治理：`benchlib.EVAL_ONLY_LAYERS={"holdout"}`，`dev_layers()` 枚举自动排除、评测须显式指定，`corpus_ids()` 仍含全层供跨层去重；bulk 2,699 = 38 cell flat 配额×2.7 + `exclude_cluster_months` 剔除核心 30 簇月→评测/开发月间零泄漏 + eprint recent 321）+ **dev_vol 2,000**（`fbias` 配额：flat×cell 历史失败率偏置，样本往「爱挂的底材」倾斜）+ **dev_failmine 1,500**（`flags` 配额：FLAG_RX 机制旗标定向挖旧时代——deadpkg/docstyle209/epsfig/pdftex_prim/pstricks/babel + fill 兜底）+ **dev_recent 1,514**（2501+ 盲区：scholarweave 脱水 1,065 + eprint 449）。scholarweave 沿用「有损源不进评测/池化」口径——`figures_stripped` 记账、只供 dev 层；eprint 臂 `acquire_source` 钉版同 hot 层。管线 `bench/py/corpus/build_corpus_layers.py`（plan/scan/extract/qc/recent 五子命令）+ `bench/py/corpus/build_sw_layer.py`（HF parquet 行组脱水）；QC 各层 `bench/work_v3/{layer}/qc.md`；收线明细见 `MANIFEST.md` 末节。八层时点合计 **13,266 篇**。

## 5. 管线分阶段（S0–S7）

```
S0 frame 构建（✅ 已产出 frame.parquet）
   ──► S1 簇下载（IA/TIGER tar，整 chunk）
   ──► S2 流式成员扫描 → features.jsonl + tex staging 全留（gzip）
   ──► S3a 核心层配额抽样（cell 内随机）→ 中选 blob 落盘
   ──► S3b 补强层 agent 策展：台账 → curator 阅读提名 / hunter 定向狩猎
   ──► S4 normalize：安全解包 + meta.json + sha256 + manifest.jsonl
   ──► S5 QC/去重（pdf_only/stub/空壳；id 唯一键）
   ──► S6 parsebench 漏斗+归因（事后分层权重 + Wilson/簇稳健 CI）
   ──► S7 license 过滤 → 可发布子集（id 清单 + 重建脚本，不分发字节）
```

- **S2 关键实现**：tar.gz 不可随机读 → 整 chunk 顺序流扫一次；成员 e-print 内存解压（魔数三态），tex 抽特征（~214 成员/s 实测）；原始 blob 暂存当 chunk、抽样后删未中者 → **磁盘峰值 ≈ 单 chunk 大小**。只要成员索引不下内容走 zipsum。
- **S2 逐成员特征**：format 三态、n_tex、n_files、uncompressed_bytes、docclass 集合、`\input` 深度（环安全 BFS）、utf8-fail、package flags（minted/pstricks/tikz/biblatex/hyperref/epsfig）。
- **S4 钉版**：manifest 行 = `{id, channel, item, member, blob_sha256, main_tex_sha256, features, stratum_cell, license_class}`。
- **S5 QC**：`%auto-ignore` 12B 占位 stub 最小尺寸门槛 + 正文含量检测（实测踩中过）。

## 6. 语料库布局

```
bench/corpus/                 # manifest 入库，数据 gitignored
  MANIFEST.md                    # 人类可读清单（生成）
  manifest.jsonl                 # 每篇一行（S4 schema）
  manifest_booster.jsonl         # 补强层清单（S3b）
  manifest_hot.jsonl             # 热层清单（2026-09-16 增补，OpenAlex+eprint 渠道）
  manifest_expand.jsonl          # 扩展层清单（2026-09-16 增补 3800 篇 + 09-18 新批至 3866；build_corpus_expand.py）
  manifest_holdout.jsonl         # 留出评测层（EVAL_ONLY 治理，2026-09-19）
  manifest_dev_failmine.jsonl    # 机制挖掘 dev 层（2026-09-19）
  manifest_dev_vol.jsonl         # 体量 dev 层（2026-09-19）
  manifest_dev_recent.jsonl      # 近期 dev 层（scholarweave+eprint 双通道，2026-09-19）
  mechanisms.jsonl               # 机制台账（S3b）
  {id}/
    meta.json                    # id/source/stratum/features/license
    raw.{tar.gz,gz,pdf}          # 原始 e-print blob（编译段底材）
    extracted/                   # 解包树（解析段底材）
```

规模估算：raw blob ~3.7MB/篇 × 1,200 ≈ 4-5GB。

## 7. 指标与统计口径

### 7.1 指标定义（parsebench v1 口径，学理对齐）

| 口径             | 学名/惯例来源       | 定义                                                                     |
| ---------------- | ------------------- | ------------------------------------------------------------------------ |
| parse ok         | —                   | `parse_file` 无异常返回（30s 超时）                                      |
| strict identity  | GROBID strict match | `reconstruct()` 输出与原文逐字节一致                                     |
| normalized       | GROBID soft         | 仅空白差异                                                               |
| diverged         | —                   | 实质差异（报首差异位置）                                                 |
| leak rate        | UTB 残留同族        | 可译 chunk 内含 `$`/`\cite*`/`\*ref`/`\begin{`/`\if*`/`\input{` 的块占比 |
| dead/orphan      | —                   | fake-translation 重建后残留 CHUNK 占位符 / 孤儿 chunk 数                 |
| flatten coverage | unarXive 漏斗项     | .tex 是否被主文件 `\input` 图触及                                        |

漏斗与归因（unarXive 式）：fetched → 有 .tex（丢 pdf_only/unpack_error）→ rooted（multi_doc/rootless 标记）→ parse ok → identity 三档 → chunk 级 leak → fake-translate dead/orphan。**逐条人工复核归因进机制台账**（泄漏分解先例：注释残留/字面 `$`/footnote 条件式/caption 内自定义引用宏）。

### 7.2 统计报告

- **核心层 vs 补强层分开报**：池化率只用核心层 + 事后分层权重；补强层按 cell 报命中率。
- **双口径都报**：加权池化率（事后分层还原真实分布）+ 宏平均（olmOCR 式等权桶——两口径并列是合法做法）。
- CI：Wilson（file/chunk 级 iid 近似；Brown-Cai-DasGupta 2001）+ 簇稳健 bootstrap（月簇重抽样）作敏感性；deff 报告需月间 ICC（§1 行动项）。
- 与 corpus39/corpus_v2 对拍表继续保留（回归基准线）。

## 8. 验收门槛（M0 gate）

| 指标                | 门槛                                       |
| ------------------- | ------------------------------------------ |
| parse ok（file 级） | 100%（CI 下界 ≥99.5%，n≥600 文件自动满足） |
| strict identity     | ≥99.5%（normalized 容差单列）              |
| leak rate           | ≤0.15%（chunk 级 CI 上界）                 |
| dead/orphan         | 0                                          |
| flatten coverage    | ≥99% 主文件触及（口径勘误见表下）          |

> 勘误 2026-09-15：v3 实测 flatten coverage 93.1%——orphan 大头是 e-print 内**未被主文件 `\input` 触及的随附 tex**（preamble/poster 件，124 例），属语料真实属性而非实现漏跟；口径宜改为「排除 unreferenced 后的触及率」或放宽至 ≥93% 并把 orphan 类目进机制台账。

基线参照（corpus_v2 实测）：137 篇 / 223 .tex → ok 100%、identity 100%、leak 0.086%（15/17,375）、0 dead/orphan；17.6s 全量。

## 9. 执行排期

| 阶段 | 内容                                                                      | 依赖                | 估算                                                       |
| ---- | ------------------------------------------------------------------------- | ------------------- | ---------------------------------------------------------- |
| P0   | 调研实验（4 agent 并行：IA pilot / post-2020 / frame / 方法学）           | —                   | ✅ 全部完成                                                |
| P1   | pilot 3 簇 ~120 篇端到端                                                  | —                   | ✅ 已完成（48 篇抽样 parsebench 79/79 ok、100% identical） |
| P2   | 全量 30 簇 → 核心 1,000（cell 内随机抽）                                  | P1 ✅               | ~17GB / ~45min（IA 13.5GB@11MB/s + TIGER 3.2GB@3.7MB/s）   |
| P3   | 补强 ~200（agent 策展：台账 + curator 分带阅读 + hunter 定向狩猎）        | P2 features+staging | ~8-10 agent-session，半天–一天                             |
| P4   | parsebench v2 报告 + 对拍 + **月间 ICC 估计**（用 corpus_v2 跨月样本）    | P2/P3               | 小时级                                                     |
| P5   | 可发布子集封装（核心∩CC ~130 篇 + 可选 e 带 CC 补强 ~100 打 publishable） | frame license       | 小时级                                                     |

## 10. 风险登记

| 风险                                  | 缓解                                                                    |
| ------------------------------------- | ----------------------------------------------------------------------- |
| 晚期大月整月粒度磁盘爆                | 已消解：簇单元=1–2 chunk，峰值≈单 chunk                                 |
| 同 id 跨渠道版本漂移                  | manifest 四元组钉版；不跨渠道去重                                       |
| `%auto-ignore` stub 混入抽样          | QC 最小尺寸 + 正文含量门槛                                              |
| 簇内配额不满（某月某 cat_group 不足） | d/e 带取间隔 2 块扩池；允许跨簇补位，记达成率                           |
| cs/econ 类目源码稀缺（Word 主流）     | 补强 B04 配额兜底 + frame 预查可得率                                    |
| agent 策展可复现性/审计性             | 提名必带 justification+ 证据（文件/行）；台账+nomination log 即审计轨迹 |
| 晚期 item 缺 zipsum                   | 退化整 chunk 流扫或 Range 头扫描（已验证）                              |
| HF CDN 慢（3.7MB/s vs IA 16.2MB/s）   | post-2020 只取 ~6 块；能用 IA 的月份不用 TIGER                          |
