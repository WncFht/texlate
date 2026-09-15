# corpus_v3 数据管线计划：~1,200 篇分层 benchmark 语料

> 状态：**定稿**（4 个调研实验 agent 全部完成回填：⟦A1⟧ IA pilot / ⟦A2⟧ post-2020 渠道 / ⟦A3⟧ 抽样 frame / ⟦A4⟧ 方法学引证）
> 日期：2026-09-14
> 上游：`docs/research/corpus/parsebench-v1.md`、`hf-latex-datasets.md`、`bulk-channels.md`、`corpus-labels.md`、`parse-metrics-literature.md`；本计划详证：`ia-pipeline-pilot.md`、`post2020-sourcing.md`、`frame-and-allocation.md`、`bench-construction-methods.md`

## 0. 目标与设计原则

为 `src/texlate/latex/` 重写（及后续编译段、fixloop）提供**总体无偏、分层可断、机制覆盖**的验证底材。

原则：

1. **零在线 API**：语料 100% 来自已发布的批量数据集（IA tar / HF tar / HF parquet / HF 元数据快照），永不请求 arxiv.org 任何端点 → 可复现、无限流、可断点续跑。
2. **Measure-then-sample**：bulk tar 给出整月全集 → 先测全体成员的真实特征（docclass/文件数/编码/\input 深度），再按真实特征配额抽样。优于「盲抽 ID 再祈祷分层命中」。
3. **字节保真分级**：raw e-print blob 原样入库（编译段底材）+ extracted tex（解析段底材）；有损源（scholarweave）只作对照不进正式语料。
4. **两层语料分离**：核心随机层回答「成功率多少」（无偏估计），补强层回答「这个坑处理了吗」（配额命中稀有机制）——报告时分开，池化估计只用核心层。
5. **钉版可复现**：成员级 sha256 + 来源 (channel, item, member) 记 manifest；语料可凭脚本重生成。
6. **可发布子集预埋**：license 分层同步记录，CC 系子集可公开分发（差异化资产）。

## 1. 数量论证（sizing）

| 需求                          | 所需 n                    | 依据                                                                         |
| ----------------------------- | ------------------------- | ---------------------------------------------------------------------------- |
| 池化「parse+identity ≥99.5%」 | ≥600 篇零失败             | rule of three：零失败 95% 上界 ≈ 3/n（Hanley & Lippman-Hand, JAMA 1983）⟦A4⟧ |
| 每时代带单独下结论            | ~200/带 × 5 带 = 1,000    | 带内零失败 → ≤1.5% 上界                                                      |
| 泄漏率 CI                     | chunk 级 ~15 万自动满足   | n=137 时 17,375 chunks → ±0.05%；1,000 篇 → ±0.005%                          |
| 稀有机制发现（0.5%/篇）       | 1,000 篇 → 期望 ~5 次命中 | n ≥ ln(1-α)/ln(1-p)（验收抽样传统）⟦A4⟧                                      |
| 编译段复用                    | 每引擎×时代 ≥100          | 同底材摊薄成本                                                               |
| 比例误差边际                  | n=1,000 → ±2.8%           | n=z²p(1−p)/e²（Cochran 1977 ch.4）⟦A4⟧                                       |

**结论：1,000 核心 + ~200 补强 = ~1,200**；现有 corpus_v2（137，无偏、钉版）折入核心层 → 新增 ~1,060。corpus_v2 保留 `channel=direct-fetch` 标签（抽样 frame 不同：HEAD 验证 vs tar 成员），池化时可做渠道敏感性检查。

**⟦A4⟧ 先例裁决**：同类 benchmark **没有一篇给 n 写统计论证**（SWE-bench 2,294 是漏斗剩余、Nougat 不披露、olmOCR-bench 按类凑数）——我们的 n 论证只能靠统计文献自担，写明反而是卖点（Card et al. EMNLP 2020 是功效论证进 NLP eval 的方法学旗）。规模先例恰好同量级：**Image2Struct（NeurIPS 2024）~1,200 篇、同样从 arXiv 源码抽**；OmniDocBench（2412.07626）「大池 200k→聚类→配额均衡 981」即两阶段配额先例。

簇数权衡：~30 月簇 × ~35 篇 > 15 簇 × 70。30 簇有真引证（WHO EPI 30×7 传统 Henderson & Sundaresan 1982；Kahan et al. Trials 2016「minimum 30–40 clusters…approximate guideline」），但 deff=1+(m−1)ρ（Kish 1965）要求估 ρ——**行动项：用 corpus_v2 的 137 篇跨月样本估 TeX 特征月间 ICC 上界**（文献无现成值，P4 前补上）。Image2Struct 的 "max 40/day to induce temporal diversity" 是我们「月簇内配额上限」的逐字先例。

## 2. 数据源矩阵

| 渠道                                        | 覆盖                                                                        | 保真                                                                                                                                              | 成本                                                | 角色                                                       |
| ------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- | ---------------------------------------------------------- |
| IA `arxiv-bulk` 月度 tar                    | **1991-07→2020-10 共 352 月无缺**（3,242 src item / 1.66TB，⟦A1⟧ 实测索引） | 字节级（Range 单成员抽取逐字节核验通过）                                                                                                          | 免费、实测 10.7–16.2MB/s                            | **≤2020 主力**（~24 簇）                                   |
| HF `TIGER-Lab/arxiv-latex-5T`               | **1991-07→2025-01 连续 403 月零缺口**（9,547 tar）                          | **字节级已实证**：与 IA `2008_001` 对拍，123/165 成员 sha256 全同，42 差异全是上游 v2+ 修订                                                       | 免费但 HF CDN 仅 3.5–3.8MB/s                        | **post-2020 主力**（~6 簇）+ IA 缺月备份；冻于 2025-01     |
| HF `scholarweave/arxiv-latex`               | →2026-08                                                                    | **.tex 逐字保真（845/845 全同）但结构有损**：丢 73% 文件（图/bst）、7.1% 论文 U+FFFD、pdf_only 行 NULL；parsebench funnel 与 TIGER 同 id 完全一致 | duckdb httpfs 谓词下推（140 id 查 6.3GB shard 35s） | 文本层规模实验正源；**不进正式语料**；2025-02 后唯一批量源 |
| HF `librarian-bots/arxiv-metadata-snapshot` | 全量元数据                                                                  | —                                                                                                                                                 | 免费、可远程列裁剪                                  | **分层 frame**：年月/类目/license 键 ⟦A3⟧                  |
| AWS s3://arxiv                              | 全量                                                                        | 字节级                                                                                                                                            | requester-pays                                      | 不用（M4 才考虑）                                          |

**渠道粒度与版本语义（⟦A2⟧ 实测）**：

- TIGER/IA 成员名 = `{YYMM}/{id}.gz|pdf`（旧式 archive 连写），**名中无版本号** → manifest 以 blob sha256 为唯一事实源，version 字段只作参考；blob ≈ tar 构建时点版本非钉版 v1。
- **月块只收当月新提交**：⟦A1⟧ 跨 3 个月块 2,763 成员实测 id-yymm 全部等于 chunk 月、**跨月 id 重叠 = 0** → 去重设计简化为 id 唯一键。
- **同月 tar 跨渠道有版本漂移**（IA 快照时点 vs TIGER 镜像时点不同 → 同 id 不同字节）：manifest 必须记 `channel+item+member+sha256` 四元组；重建脚本锁渠道。
- **zipsum.tsv 成员序 == tar 序**（⟦A1⟧ 验证 2,549 成员 0 失配）→ offset 纯算术重建，**免下 tar 得全月成员索引**（成员名/大小/格式可判 pdf_only）；但晚期 item 不规律缺失 zipsum（1912/2001 无、2009/2010 有）→ 缺失月份退化为整 chunk 流式扫描或 Range 头扫描（46 请求重建 311MB tar 索引，已验证）。
- 簇粒度 = 月内 chunk tar：TIGER 2024 每月 134–202 块、单块 ~0.53GB ≈ **~150 篇/块**；IA chunk 实测 130–543MB、成员 214–1,668/块。
- 三态占比实测：IA 9802（tar 67%/gz 32%/pdf 0.2%）、1201（66%/25%/9.6%）、2001_040（76%/15%/8.4%）、TIGER 2408_001（86%/7.3%/6.7%）——pdf_only 率随年代上升。

## 3. 分层设计

### 3.1 Frame（⟦A3⟧ 已产出 `tmp/exp/frame/frame.parquet`，3,164,528 行）

每 id 一行：`tar_yymm（=id 内嵌公布月）, year_band, primary_cat, cat_group, license_class, n_versions` 等 15 列。完备性已验证（新式 id 99.9994% vs 月内 max-seq；旧式 414k 逐 archive-month 序号连续）。

- year_band 实际分布：`a≤2006: 400,888 / b 07-11: 325,304 / c 12-16: 493,421 / d 17-20: 598,334 / e 21-25: 1,104,329`（f 2026+ 242k 不进样）
- cat_group 8 组全覆盖；时代漂移显著：a 带 hep-phys 占 37%/cs 仅 1.9% → e 带 cs 40% 反超
- license：a 带 99% missing → e 带 CC 系 ~53%
- **坑（⟦A3⟧ §5）**：id 月 ≠ v1 月（3.1% 新式 +1 月滚动公布 + pre-1991 backfill 长尾）→ 簇归属用 `tar_yymm`；yymm 字符串比较在 2000 年界断裂；`versions[1]` 恒为 v1；frame 不知成员形态（pdf_only 率只能 S2 实测）

### 3.2 簇选择（⟦A3⟧ 已定 30 簇清单，`tmp/exp/frame/cluster_pick.json`）

**粒度修正**：整月粒度 = ~620GB 下载（e 带单月 44–101GB）不可行 → **簇单元 = 月内抽样 chunk**（TIGER 单块 ~0.53GB≈150 篇 ⟦A2⟧；IA 同理分块）。每月选 1–2 块，块内测全特征再配额抽 ~33–34。

| 带              | 月份簇（yymm）                     | 规模/簇                                   | 每簇配额 |
| --------------- | ---------------------------------- | ----------------------------------------- | -------- |
| a ≤2006         | 9703, 9910, 0111, 0307, 0501, 0605 | 1–2 chunk, ≤1GB                           | 33–34    |
| b 07–11         | 0707, 0806, 0905, 1003, 1012, 1109 | ~1 chunk 0.5–1GB                          | 33–34    |
| c 12–16         | 1206, 1306, 1404, 1502, 1511, 1608 | ~1–2 chunk                                | 33–34    |
| d 17–20         | 1706, 1803, 1811, 1907, 2003, 2009 | ~1–2 chunk（月总量 13–40GB 不整下）       | 33–34    |
| e 21–25 (TIGER) | 2105, 2203, 2211, 2308, 2403, 2410 | **1 chunk ≈0.53GB**（月 88–202 块取 1–2） | 33–34    |

chunk 内成员按 id 连续 → 类目有轻度聚集；为保险 d/e 带每簇取 2 块（间隔采样），特征测量后配额照常在 ~300 候选池上抽 33–34。

### 3.3 簇内特征测量（⟦A1⟧ 产出格式 `features.jsonl`）

逐成员：format 三态、n_tex、n_files、uncompressed_bytes、docclass 集合、\input 深度、utf8-fail flag、package flags（minted/pstricks/tikz/biblatex/hyperref/epsfig）。

### 3.4 配额分配（⟦A3⟧ 已产出 `allocation-core.csv` / `allocation-booster.csv` / `cluster-cat-mix.csv`）

- **核心 1,000**：year_band 内等分（每带 200），带内跨 6 簇均布（33–34/簇），簇内按 cat_group 软配额参照 `cluster-cat-mix.csv`。
- **⟦A4⟧ 方法学红线**：配额 cell 内必须**随机抽取**（层内概率样本），不是"凑够就行"——否则落 Neyman 1934 对 purposive/quota 抽样的批判旧辙；池化估计做事后分层加权（Holt & Smith 1979 / Little 1993，DOI 已核验）。olmOCR 的 macro-avg 等权桶是另一合法口径 → **两口径都报**（加权池化率 + 宏平均）。
- **补强 ~200**：**agent 策展制，非纯脚本抽取**（不进入池化估计）。脚本 flag（`allocation-booster.csv` B01–B07）只做"已知签名"的候选预筛，真正的机制覆盖靠**机制台账 + agent 定向狩猎**：

    **机制台账**（`bench/corpus_v3/mechanisms.jsonl`）——每行一个机制：
    `{mech_id, title, kind(known-trap/suspected/found-in-wild), detection(regex|feature|manual), status(wanted|partial|covered|exhausted), examples[], evidence, notes}`。
    种子：corpus39 陷阱 T01–T29、rewrite spec 增补项、parsebench v1 发现（caption 参数内注释残留、裸 `\input`、multi_doc、`%auto-ignore` stub、pdf_only…）。

    **两类 agent 角色**（策展 loop，见 §4 S3b）：
    - **Curator**（按时代带分工 ~5-6 个）：从池内随机取论文**实际打开 tex 阅读**，判断"有没有 features 没标出的有趣机制" → 提名 `{id, mech_tags, justification}` + 新机制写台账
    - **Hunter**（~2-3 个）：领台账 `wanted/partial` 条目，设计检出手段（tex staging 上 zgrep / frame 查询 / 浓度先验簇），**开文件验证**后提名；找不到就记 `exhausted` + 搜索证据——**"还缺什么"本身就是产出**

    **检出手段分层**（成本递增，便宜的先用）：

    | 层  | 手段                         | 覆盖                   |
    | --- | ---------------------------- | ---------------------- |
    | L0  | 成员名/zipsum 索引（免下载） | B07 pdf_only/single-gz |
    | L1  | S2 features flag             | B01-B06 候选预筛       |
    | L2  | tex staging 上 zgrep         | hunter 定向搜证        |
    | L3  | agent 开文件读 tex 判机制    | regex 写不出的一切坑   |

    **关键资产：tex staging 不删**。S2 把全成员 tex 文本 gzip 落盘（每簇 ~0.1-0.3GB）→ ~1.5-3 万篇本地可检索语料 = hunter 的 grep 底材 + curator 的阅读池。B08 机动 cell 取消固定配额，改为台账 loop 的自然产出（总盘 ~200 仍封顶）。

    基础配额锚点（最小保障，非上限）：B01 2.09 遗存 30 / B02 非 UTF-8 30 / B03 深多文件 30 / B04 低 TeX 密度类目 30 / B05 宏包机制 25 / B06 大字节 20 / B07 边缘形态 25。

## 4. 管线分阶段

```
S0 frame 构建（A3 ✅）──► S1 簇下载（IA/TIGER tar）
                             │
                       S2 流式成员扫描 → features.jsonl + tex staging 全留（gzip）
                             │
                       S3a 核心层配额抽样（cell 内随机）→ 中选 blob 落盘
                             │
                       S3b 补强层 agent 策展：机制台账 → curator 阅读提名 /
                           hunter 定向狩猎 → 提名集 + 缺口台账
                             │
                       S4 normalize：安全解包 + meta.json + sha256 + manifest.jsonl
                             │
                       S5 QC/去重（pdf_only/stub/空壳；id 唯一键已实测）
                             │
                       S6 parsebench 漏斗+归因（事后分层权重 + Wilson/簇稳健 CI）
                             │
                       S7 license 过滤 → 可发布子集（id 清单 + 重建脚本，不分发字节）
```

- **S2 关键实现**（⟦A1⟧ 已验证可行）：tar.gz 不可随机读 → 整 chunk 顺序流式扫描一次；成员 e-print 内存解压（gzip/tar/pdf 魔数三态），tex 文本抽特征（实测 **~214 成员/s**）；原始 blob 暂存当 chunk，抽样后删未中者 → 磁盘峰值 ≈ 单 chunk 大小。`curl` 必须 `-L`（IA 302 到 dn* 节点）。若只要成员索引不下内容：zipsum.tsv（有则首选）。
- **S4 钉版**：manifest 记 `{id, channel, item, member, blob_sha256, main_tex_sha256, features, stratum_cell, license_class}`。成员名无版本号（⟦A1/A2⟧），**blob sha256 即事实源**；同 id 跨渠道可不同字节 → `channel` 字段必填。
- **S5 新增已知坑**：`%auto-ignore` 12B 占位 stub 会混进抽样 → QC 最小尺寸门槛（⟦A1⟧ 实测踩中）。

## 5. 语料库布局

```
bench/corpus_v3/              # manifest 入库，数据 gitignored
  MANIFEST.md                 # 人类可读清单（生成）
  manifest.jsonl              # 每篇一行（上 schema）
  {id}/
    meta.json                 # id/source/stratum/features/license
    raw.{tar.gz,gz,pdf}       # 原始 e-print blob（编译段用）
    extracted/                # 解包树（解析段用）
tmp/exp/{ia-pilot,post2020,frame}/   # 调研实验现场
```

规模估算：raw blob ~3.7MB/篇（⟦A2⟧ TIGER 实测）× 1,200 ≈ **4-5GB**；tex staging 全成员特征 ~⟦A1⟧。

**可发布子集预测（⟦A3⟧）**：strict CC（cc0/by/sa）在随机核心中期望 ~103/1,000 + 补强 ~10-20 ≈ **110–140/1,200（~10%）**。若要把可发布集推到 ~250 篇：e 带簇内做 license 条件超采（CC ~53% 可得率）——但该超采子集须独立于核心层、不进池化统计（license 不是解析质量的分层轴，污染核心样本不划算）。默认方案：**核心∩CC 直接发布 ~130 篇 + 可选 CC 专用补强 ~100 篇（e 带，打 `publishable` 标）**。

**⟦A4⟧ 发布形态先例**：unarXive 2022 原文明示两版发行（permissive 子集 open + 全量 restricted）；LAION-5B「URLs not images」与 tweet-ID hydration 支撑「manifest+ 重建脚本、不分发字节」形态；钉版组合 = `(id, member, sha256)` + 可选 Zenodo DOI（unarXive `_source_hash` 先例）。全行业数据集 license 普遍未声明，我们明示即超水位。

## 6. 统计口径（PROTOCOL 扩展）

- 沿用 4 指标（ok / identity 三档 / leak / dead·orphan）+ flatten coverage + 漏斗 + 归因。
- **核心层 vs 补强层分开报**：池化率只用核心层 + 事后分层权重；补强层按 cell 报命中率。
- **双口径**（⟦A4⟧）：加权池化率（事后分层权重还原真实分布）+ 宏平均（olmOCR 式等权桶）。
- CI：Wilson（file/chunk 级 iid 近似；Brown-Cai-DasGupta 2001）+ 簇稳健 bootstrap（月簇重抽样）作敏感性；deff 报告需月间 ICC 估计（见 §1 行动项）。
- 与 corpus39/corpus_v2 对拍表继续保留。

## 7. 验收门槛（M0 重写 gate 建议）

| 指标                | 门槛                                       |
| ------------------- | ------------------------------------------ |
| parse ok（file 级） | 100%（CI 下界 ≥99.5%，n≥600 文件自动满足） |
| strict identity     | ≥99.5%（normalized 容差单列）              |
| leak rate           | ≤0.15%（chunk 级 CI 上界）                 |
| dead/orphan         | 0                                          |
| flatten coverage    | ≥99% 主文件触及                            |

## 8. 执行排期

| 阶段 | 内容                                                                                | 依赖                | 估算                                                                                                                     |
| ---- | ----------------------------------------------------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| P0   | 调研实验（4 agent 并行）                                                            | —                   | A1 ✅ A2 ✅ A3 ✅ A4 ✅ 全部完成                                                                                         |
| P1   | pilot 3 簇 ~120 篇端到端                                                            | —                   | **⟦A1⟧ 已完成**：3 chunk/1.17GB/2,763 成员；48 篇抽样语料 parsebench **79/79 ok、100% identical**，路由标签生效          |
| P2   | 全量 30 簇 → 核心 1,000（cell 内随机抽 ⟦A4⟧）                                       | P1 ✅               | **⟦A1⟧ 实测成本：整 chunk 方案 ~13.5GB/30min/峰值 16GB**；加 TIGER 6 块 ~3.2GB@3.7MB/s ≈ 15min → **合计 ~17GB / ~45min** |
| P3   | 补强 ~200（**agent 策展**：机制台账 → curator 分带阅读提名 + hunter 定向狩猎）      | P2 features+staging | ~8-10 个 agent-session，半天–一天                                                                                        |
| P4   | parsebench v2 报告 + 对拍 + **月间 ICC 估计**（⟦A4⟧ 行动项，用 corpus_v2 跨月样本） | P2/P3               | 小时级                                                                                                                   |
| P5   | 可发布子集封装                                                                      | A3 license 列 ✅    | 小时级                                                                                                                   |

## 9. 风险登记

| 风险                                                          | 缓解                                                                                          |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| IA 单 tar 大（2019+ 月 ~2GB+，d/e 带整月 13–100GB）→ 磁盘峰值 | **已消解**：簇单元 = 月内 1–2 chunk（0.13–0.54GB），抽完即删未中 blob；峰值 ≈ 单 chunk ⟦A1⟧   |
| ~~月度 tar 版本语义不明（id 跨月重复）~~                      | **已实测排除**：3 chunk 2,763 成员跨月重叠 = 0，月块只收当月新提交 ⟦A1⟧                       |
| ~~TIGER 镜像不保真~~                                          | **已验证**：123/165 sha256 全同、差异全是上游修订 ⟦A2⟧                                        |
| 同 id 跨渠道版本漂移（同月 tar 不同时点打包）                 | manifest 四元组钉版；不跨渠道去重同一 id 的不同字节                                           |
| `%auto-ignore` 12B 占位 stub 混入抽样 ⟦A1⟧                    | QC 最小尺寸门槛 + 正文含量检测（已有 stub 规格）                                              |
| 旧式 id 在快照缺字段                                          | A3 覆盖率检查 ✅ 通过；缺失时成员名/内容特征兜底                                              |
| 簇内配额不满（某月某 cat_group 不足）                         | chunk 内成员 id 连续、类目轻度聚集 → d/e 带取间隔 2 块扩候选池；允许跨簇补位，记录配额达成率  |
| cs/econ 类目源码稀缺（Word 主流）                             | 补强层配额兜底 + frame 预查可得率                                                             |
| agent 策展的可复现性/审计性                                   | 提名必须带 justification + 证据（文件/行）；mechanisms.jsonl 台账 + nomination log 即审计轨迹 |
| 晚期 item 缺 zipsum（1912/2001 无）⟦A1⟧                       | 需要索引时退化整 chunk 扫描或 Range 头扫描                                                    |
| HF CDN 慢（3.7MB/s vs IA 16.2MB/s）                           | post-2020 只取 ~6 块（~3GB，~15min）；能用 IA 的月份不用 TIGER                                |

## 10. 待回填清单

- ~~⟦A1⟧~~ **已回填**：IA 索引 3,242 src item/352 月无缺/1.66TB；成员 `{yymm}/{id}.{gz|pdf}` 无版本号；跨月重叠=0；zipsum 序==tar 序（可免下载建索引但晚期缺）；特征 ~214 成员/s；pilot 48 篇 parsebench 79/79 ok 100% identical；30 簇成本 ~13.5GB/30min；坑 `%auto-ignore` stub、`curl -L`。详见 `docs/research/corpus/ia-pilot.md`
- ~~⟦A2⟧~~ **已回填**：TIGER byte-exact 实证（123/165 + 差异全为上游修订）；post-2020 → TIGER-5T 裁决落地；scholarweave = 文本层实验源不进正料；成员名无版本号 → sha256 钉版；2024 簇粒度 ~0.53GB/块≈150 篇。详见 `docs/research/corpus/post2020-sourcing.md`
- ~~⟦A3⟧~~ **已回填**：frame 3.16M 行完备验证；30 簇清单（`cluster_pick.json`）；配额表（`allocation-*.csv`）；license 分布（a 带 99% missing → e 带 CC 53%）；可发布子集 ~130 基线；坑：id 月≠v1 月用 tar_yymm。详见 `docs/research/corpus/frame-and-allocation.md`
- ~~⟦A4⟧~~ **已回填**：先例链完整——OmniDocBench（200k→981 两阶段配额）、Image2Struct（~1,200n + "max 40/day" 时间多样性 = 月簇配额逐字先例）、DocGenome（eval 集同学科分布）；**无先例给 n 写统计论证 → 我们写明即卖点**（Cochran/Card et al.）；30 簇有引证（WHO EPI、Kahan）但需自估月间 ICC；**配额 cell 内必须随机抽取**（Neyman 批判）+ 事后分层加权（Holt & Smith/Little）；发布形态有 unarXive 两版发行 + LAION manifest 先例。详见 `docs/research/corpus/bench-construction-methods.md`
