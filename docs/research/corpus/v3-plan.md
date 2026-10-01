# corpus_v3 数据管线计划：分层 benchmark 语料的设计定稿

> **结论**：语料设计定型为「核心概率样本（1,000 篇月簇配额随机）+ 补强对抗样本（~200 篇 agent 策展）」两桶形态，全部来自批量数据集（IA / HF）零在线 API，成员级 sha256 钉版可复现；该计划已全部执行落地并继续扩层。
> **状态**：已完成（2026-09-15/16 落地执行；语料后续扩至八层 13,266 篇并统一物理根——2026-09-20 七库合一后 `corpus_v3` 更名 `corpus`，现行口径见 `bench/corpus/MANIFEST.md` 与本域 `2026-09-16-expand-layer.md`）。本文保留设计论证作历史与方法依据。
> **日期**：2026-09-14

上游调研：`ia-pilot.md`、`post2020-sourcing.md`、`frame-and-allocation.md`、`labels.md`（本域）；方法学引证 `research/methods/bench-construction-methods.md`、指标口径 `research/methods/parse-metrics-literature.md`。

## 1. 目标与设计原则

为 `src/texlate/latex/` 重写（及后续编译段、fixloop）提供**总体无偏、分层可断、机制覆盖**的验证底材。

1. **零在线 API**：语料 100% 来自已发布的批量数据集（IA tar / HF tar / HF parquet / HF 元数据快照），永不请求 arxiv.org 任何端点——可复现、无限流、可断点续跑。
2. **Measure-then-sample**：bulk tar 给出整月全集，先测全体成员的真实特征（docclass/文件数/编码/`\input` 深度），再按真实特征配额抽样——优于「随机抽 ID 后期望分层命中」。
3. **字节保真分级**：raw e-print blob 原样入库（编译段底材）+ extracted tex（解析段底材）；有损源（scholarweave）只作对照不进正式语料。
4. **两层语料分离**：核心随机层回答「成功率多少」（无偏估计），补强层确认机制陷阱的覆盖（配额命中稀有机制）——报告时分开，池化估计只用核心层。
5. **钉版可复现**：成员级 sha256 + 来源 `(channel, item, member)` 记 manifest；语料可凭脚本重生成。
6. **可发布子集预埋**：license 分层同步记录，CC 系子集可公开分发（差异化资产）。

## 2. 数量论证（sizing）

| 需求                          | 所需 n                    | 依据                                                                 |
| ----------------------------- | ------------------------- | -------------------------------------------------------------------- |
| 池化「parse+identity ≥99.5%」 | ≥600 篇零失败             | rule of three：零失败 95% 上界 ≈ 3/n[^hanley83]                      |
| 每时代带单独下结论            | ~200/带 × 5 带 = 1,000    | 带内零失败 → ≤1.5% 上界                                              |
| 泄漏率 CI                     | chunk 级 ~15 万自动满足   | n=137 时 17,375 chunks → ±0.05%；~1,200 篇（~15 万 chunks）→ ±0.015% |
| 稀有机制发现（0.5%/篇）       | 1,000 篇 → 期望 ~5 次命中 | n ≥ ln(1−α)/ln(1−p)（验收抽样传统[^nielsen93]）                      |
| 编译段复用                    | 每引擎×时代 ≥100          | 同底材摊薄成本                                                       |
| 比例误差边际                  | n=1,000 → ±2.8%           | n=z²p(1−p)/e²[^cochran77]                                            |

结论：**1,000 核心 + ~200 补强 ≈ 1,200**；原 corpus_v2（139 篇无偏钉版样本）折入核心层，保留 `channel=direct-fetch` 标签做渠道敏感性检查。

先例裁决：同类 benchmark **没有一篇给 n 写统计论证**（SWE-bench 2,294 是漏斗剩余、Nougat 不披露、olmOCR-bench 按类目填充）——n 论证只能靠统计文献自担，写明反而是差异化资产[^card20]。规模先例恰好同量级：Image2Struct 约 1,200 篇同样从 arXiv 源码抽[^image2struct]；OmniDocBench「大池 200k→聚类→配额均衡 981」即两阶段配额先例[^omnidoc]。

簇数权衡取 ~30 月簇 × ~33–34 篇：30 簇有明确文献依据（WHO EPI 30×7 传统[^henderson82]；Kahan et al.「minimum 30–40 clusters」approximate guideline[^kahan16]），但 deff=1+(m−1)ρ[^kish65] 要求估 ρ——月间 ICC 后用 corpus 数据自估（结果见 `2026-09-15-parsebench-icc.md`：簇效应≈0）。Image2Struct 的 "max 40/day to induce temporal diversity" 是「月簇内配额上限」的逐字先例。

## 3. 数据源矩阵

| 渠道                                        | 覆盖                                                               | 保真                                                                                                 | 成本                         | 角色                                                       |
| ------------------------------------------- | ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- | ---------------------------- | ---------------------------------------------------------- |
| IA `arxiv-bulk` 月度 tar                    | 1991-07→2020-10 共 352 月无缺（3,242 src item / 1.66TB，实测索引） | 字节级（Range 单成员抽取逐字节核验通过）                                                             | 免费、实测 10.7–16.2MB/s     | ≤2020 主力（~24 簇）                                       |
| HF `TIGER-Lab/arxiv-latex-5T`               | 1991-07→2025-01 连续 403 月零缺口（9,547 tar）                     | 字节级已实证：与 IA `2008_001` 对拍，123/165 成员 sha256 全同，42 差异全是上游 v2+ 修订              | 免费但 HF CDN 仅 3.5–3.8MB/s | post-2020 主力（~6 簇）+ IA 缺月备份；冻于 2025-01         |
| HF `scholarweave/arxiv-latex`               | →2026-07                                                           | .tex 逐字保真（845/845 全同）但结构有损：丢 72.6% 文件（图/bst）、7.1% 论文 U+FFFD、pdf_only 行 NULL | duckdb httpfs 谓词下推       | 文本层规模实验正源；**不进正式语料**；2025-02 后唯一批量源 |
| HF `librarian-bots/arxiv-metadata-snapshot` | 全量元数据                                                         | —                                                                                                    | 免费、可远程列裁剪           | 分层 frame：年月/类目/license 键                           |
| AWS `s3://arxiv`                            | 全量                                                               | 字节级                                                                                               | requester-pays               | 不用                                                       |

渠道粒度与版本语义（实测）：

- TIGER/IA 成员名 = `{YYMM}/{id}.gz|pdf`（旧式 archive 连写），**名中无版本号**——manifest 以 blob sha256 为唯一事实源，version 字段只作参考；blob ≈ tar 构建时点版本非钉版 v1。
- **月块只收当月新提交**：跨 3 个月块 2,763 成员实测 id-yymm 全部等于 chunk 月、跨月 id 重叠 = 0——去重设计简化为 id 唯一键。
- **同月 tar 跨渠道有版本漂移**（IA 快照时点 vs TIGER 镜像时点不同 → 同 id 不同字节）：manifest 必须记 `channel+item+member+sha256` 四元组；重建脚本锁渠道。
- **zipsum.tsv 成员序 == tar 序**（验证 2,549 成员 0 失配）——offset 纯算术重建，免下载 tar 即得全月成员索引；但晚期 item 不规律缺失 zipsum（1912/2001 无、2009/2010 有），缺失月份回退为整 chunk 流式扫描或 Range 头扫描。
- 簇粒度 = 月内 chunk tar：TIGER 2024 每月 134–202 块、单块 ~0.53GB ≈ ~150 篇/块；IA chunk 实测 130–543MB、成员 214–1,668/块。
- 三态占比实测：IA 9802（tar 67%/gz 32%/pdf 0.2%）、1201（66%/25%/9.6%）、2001_040（76%/15%/8.4%）、TIGER 2408_001（86%/7.3%/6.7%）——pdf_only 率随年代上升。

## 4. 分层设计

### 4.1 Frame

每 id 一行：`tar_yymm`（=id 内嵌公布月）、`year_band`、`primary_cat`、`cat_group`、`license_class`、`n_versions` 等 15 列，共 3,164,528 行；完备性已验证（新式 id 99.9994% vs 月内 max-seq；旧式 414k 逐 archive-month 序号连续）。构建与验证细节见 `frame-and-allocation.md`。

year_band 实际分布：`a≤2006: 400,888 / b 07-11: 325,304 / c 12-16: 493,421 / d 17-20: 598,334 / e 21-25: 1,104,329`（f 2026+ 242k 不进样）。cat_group 8 组全覆盖；时代漂移显著：a 带 hep-phys 占 37%/cs 仅 1.9% → e 带 cs 40% 反超。license：a 带 99% missing → e 带 CC 系 ~53%。

陷阱：id 月 ≠ v1 月（3.1% 新式 +1 月滚动公布 + pre-1991 backfill 长尾）——簇归属用 `tar_yymm`；yymm 字符串比较在 2000 年界断裂；`versions[1]` 恒为 v1；frame 不知成员形态（pdf_only 率只能实测）。

### 4.2 簇选择

整月粒度 = ~620GB 下载（e 带单月 44–101GB）不可行——**簇单元 = 月内抽样 chunk**（TIGER 单块 ~0.53GB≈150 篇；IA 同理分块）。每月选 1–2 块，块内测全特征再配额抽 ~33–34。30 簇清单按带内累计论文量等分位取月（a 带 9703/9910/0111/0307/0501/0605 …e 带 2105/2203/2211/2308/2403/2410，全表见 `frame-and-allocation.md` §4.2）。

chunk 内成员按 id 连续，类目有轻度聚集；为保险起见 d/e 带每簇取 2 块（间隔采样），特征测量后配额照常在 ~300 候选池上抽 33–34。

### 4.3 簇内特征测量

逐成员：format 三态、n_tex、n_files、uncompressed_bytes、docclass 集合、`\input` 深度、utf8-fail flag、package flags（minted/pstricks/tikz/biblatex/hyperref/epsfig）。

### 4.4 配额分配

- **核心 1,000**：year_band 内等分（每带 200），带内跨 6 簇均布（33–34/簇），簇内按 cat_group 软配额。
- **方法学红线**：配额 cell 内必须**随机抽取**（层内概率样本），不是「凑够就行」——否则即 Neyman 1934 批判的 purposive/quota 抽样[^neyman34]；池化估计做事后分层加权[^holt79][^little93]。olmOCR 的 macro-avg 等权桶是另一合法口径——**两口径都报**（加权池化率 + 宏平均）。
- **补强 ~200**：**agent 策展制，非纯脚本抽取**（不进入池化估计）。脚本 flag 只做「已知签名」候选预筛（B01 2.09 遗存 / B02 非 UTF-8 / B03 深多文件 / B04 低 TeX 密度类目 / B05 宏包机制 / B06 大字节 / B07 边缘形态），真正的机制覆盖靠**机制台账 + agent 定向查找**：

    机制台账 `mechanisms.jsonl` 每行一个机制 `{mech_id, title, kind, detection, status, examples[], evidence, notes}`。种子来自 corpus39 陷阱 T01–T29、rewrite spec 增补项、parsebench v1 发现（caption 参数内注释残留、裸 `\input`、multi_doc、`%auto-ignore` stub、pdf_only 等）。

    两类 agent 角色：**Curator**（按时代带分工）从池内随机取论文实际打开 tex 阅读，判断「是否还有 features 未覆盖的机制」→ 提名 + 新机制写台账；**Hunter** 领台账 wanted/partial 条目，设计检出手段（zgrep / frame 查询 / 浓度先验簇），开文件验证后提名；找不到记 `exhausted` + 搜索证据——「还缺什么」本身就是产出。

    检出手段分层（成本递增）：L0 成员名/zipsum 索引（免下载）→ L1 features flag 候选预筛 → L2 tex staging 上 zgrep 定向搜证 → L3 agent 开文件读 tex 判机制。**关键资产：tex staging 不删**——扫描时把全成员 tex 文本 gzip 落盘，得 ~1.5–3 万篇本地可检索语料。

## 5. 管线分阶段

```
S0 frame 构建 ──► S1 簇下载（IA/TIGER tar）
                     │
               S2 流式成员扫描 → features.jsonl + tex staging 全留（gzip）
                     │
               S3a 核心层配额抽样（cell 内随机）→ 中选 blob 落盘
                     │
               S3b 补强层 agent 策展：机制台账 → curator 阅读提名 /
                   hunter 定向查找 → 提名集 + 缺口台账
                     │
               S4 normalize：安全解包 + meta.json + sha256 + manifest.jsonl
                     │
               S5 QC/去重（pdf_only/stub/空壳；id 唯一键）
                     │
               S6 parsebench 漏斗+归因（事后分层权重 + Wilson/簇稳健 CI）
                     │
               S7 license 过滤 → 可发布子集（id 清单 + 重建脚本，不分发字节）
```

- **S2 关键实现**：tar.gz 不可随机读——整 chunk 顺序流式扫描一次；成员 e-print 内存解压（gzip/tar/pdf 魔数三态），tex 文本抽特征（实测 ~214 成员/s）；原始 blob 暂存当 chunk，抽样后删未中者——磁盘峰值 ≈ 单 chunk 大小。IA `curl` 必须 `-L`（302 到下载节点）。只要成员索引不下内容时用 zipsum.tsv（有则首选）。
- **S4 钉版**：manifest 记 `{id, channel, item, member, blob_sha256, main_tex_sha256, features, stratum_cell, license_class}`。成员名无版本号，blob sha256 即事实源；同 id 跨渠道可不同字节，`channel` 字段必填。
- **S5 已知陷阱**：`%auto-ignore` 12B 占位 stub 会混进抽样——QC 最小尺寸门槛。

## 6. 语料库布局与规模

`{id}/` 子目录：`meta.json`（id/source/stratum/features/license）+ `raw.{tar.gz,gz,pdf}`（原始 e-print blob）+ `extracted/`（解包树）。规模估算：raw blob ~3.7MB/篇 × 1,200 ≈ 4–5GB。

**可发布子集预测**：strict CC（cc0/by/sa）在随机核心中期望 ~103/1,000 + 补强 ~10–20 ≈ 110–140/1,200（~10%）。若要把可发布集推到 ~250 篇，e 带簇内可做 license 条件超采（CC ~53% 可得率），但该超采子集须独立于核心层、不进池化统计。默认方案：核心∩CC 直接发布 ~130 篇 + 可选 CC 专用补强 ~100 篇。

发布形态先例：unarXive 2022 原文明示两版发行（permissive 子集 open + 全量 restricted）[^unarxive22]；LAION-5B「URLs not images」与 tweet-ID hydration 支撑「manifest+ 重建脚本、不分发字节」形态[^laion]；钉版组合 = `(id, member, sha256)` + 可选 Zenodo DOI（unarXive `_source_hash` 先例）。全行业数据集 license 普遍未声明，明示即高于行业惯例。

## 7. 统计口径

- 沿用 4 指标（ok / identity 三档 / leak / dead·orphan）+ flatten coverage + 漏斗 + 归因（口径学理见 `research/methods/parse-metrics-literature.md`）。
- **核心层 vs 补强层分开报**：池化率只用核心层 + 事后分层权重；补强层按 cell 报命中率。
- **双口径**：加权池化率（事后分层权重还原真实分布）+ 宏平均（olmOCR 式等权桶）。
- CI：Wilson（file/chunk 级 iid 近似[^brown01]）+ 簇稳健 bootstrap（月簇重抽样）作敏感性。

## 8. 验收门槛（M0 重写 gate 建议）

| 指标                | 门槛                                       |
| ------------------- | ------------------------------------------ |
| parse ok（file 级） | 100%（CI 下界 ≥99.5%，n≥600 文件自动满足） |
| strict identity     | ≥99.5%（normalized 容差单列）              |
| leak rate           | ≤0.15%（chunk 级 CI 上界）                 |
| dead/orphan         | 0                                          |
| flatten coverage    | ≥99% 主文件触及                            |

## 9. 风险登记（设计时点）

| 风险                                          | 缓解                                                                          |
| --------------------------------------------- | ----------------------------------------------------------------------------- |
| IA 单 tar 大（d/e 带整月 13–100GB）→ 磁盘峰值 | 已消解：簇单元 = 月内 1–2 chunk（0.13–0.54GB），抽完即删未中 blob             |
| 月度 tar 版本语义不明（id 跨月重复）          | 已实测排除：3 chunk 2,763 成员跨月重叠 = 0                                    |
| TIGER 镜像不保真                              | 已验证：123/165 sha256 全同、差异全是上游修订                                 |
| 同 id 跨渠道版本漂移                          | manifest 四元组钉版；不跨渠道去重同一 id 的不同字节                           |
| `%auto-ignore` 12B 占位 stub 混入抽样         | QC 最小尺寸门槛 + 正文含量检测                                                |
| 簇内配额不满（某月某 cat_group 不足）         | d/e 带取间隔 2 块扩候选池；允许跨簇补位，记录配额达成率                       |
| cs/econ 类目源码稀缺（Word 主流）             | 补强层配额兜底 + frame 预查可得率                                             |
| agent 策展的可复现性/审计性                   | 提名必须带 justification + 证据；mechanisms.jsonl + nomination log 即审计轨迹 |
| HF CDN 慢（3.7MB/s vs IA 16.2MB/s）           | post-2020 只取 ~6 块（~3GB）；能用 IA 的月份不用 TIGER                        |

## 落地结果（追记）

核心 1,000 + 补强 200 于 2026-09-15/16 落地（manifest 四元组钉版、QC 全部通过）；hot 层 166（OpenAlex 高引近期）、expand 层 3,866（故障率加权定向扩容）相继入库；2026-09-19 评测/开发分轨扩 holdout 3,020 + dev_vol 2,000 + dev_failmine 1,500 + dev_recent 1,514，八层合计 **13,266 篇 · 46GB**；2026-09-20 七库合一统一物理根（并入 v1/v2/m1k/iclr 旧库 947 篇搬移 + 251 去重），~14,161 extracted 树 ~54.9GB。现行层口径以 `bench/corpus/MANIFEST.md` 为准。

### 参考文献

[^hanley83]: Hanley & Lippman-Hand. If nothing goes wrong, is everything all right? JAMA 1983. [doi.org](https://doi.org/10.1001/jama.1983.03330370053031)

[^nielsen93]: Nielsen & Landauer. A mathematical model of the finding of usability problems. CHI 1993. [doi.org](https://doi.org/10.1145/169059.169166)

[^cochran77]: Cochran. Sampling Techniques, 3rd ed. Wiley 1977.

[^card20]: Card et al. With Little Power Comes Great Responsibility. EMNLP 2020. [aclanthology.org](https://aclanthology.org/2020.emnlp-main.745/)

[^image2struct]: Roberts et al. Image2Struct: Benchmarking Structure Extraction for Vision-Language Models. NeurIPS 2024 D&B. [arxiv.org](https://arxiv.org/abs/2410.22456)

[^omnidoc]: Ouyang et al. OmniDocBench: Benchmarking Diverse PDF Document Parsing. arXiv 2412.07626. [arxiv.org](https://arxiv.org/abs/2412.07626)

[^henderson82]: Henderson & Sundaresan. Cluster sampling to assess immunization coverage. Bull WHO 1982. [iris.who.int](https://iris.who.int/handle/10665/272820)

[^kahan16]: Kahan et al. Increased risk of type I errors in cluster randomised trials with small or medium numbers of clusters. Trials 2016. [doi.org](https://doi.org/10.1186/s13063-016-1371-6)

[^kish65]: Kish. Survey Sampling. Wiley 1965.

[^neyman34]: Neyman. On the two different aspects of the representative method. JRSS 1934. [doi.org](https://doi.org/10.2307/2342192)

[^holt79]: Holt & Smith. Post stratification. JRSS-A 1979. [jstor.org](https://www.jstor.org/stable/2344652)

[^little93]: Little. Post-stratification: a modeler's perspective. JASA 1993. [doi.org](https://doi.org/10.1080/01621459.1993.10476368)

[^brown01]: Brown, Cai & DasGupta. Interval estimation for a binomial proportion. Statistical Science 2001. [doi.org](https://doi.org/10.1214/ss/1009213286)

[^unarxive22]: Saier, Krause & Färber. unarXive 2022: All arXiv Publications Pre-Processed for NLP. JCDL 2023. [doi.org](https://doi.org/10.1109/JCDL57899.2023.00020)

[^laion]: Schuhmann et al. LAION-5B: An open large-scale dataset for training next generation image-text models. NeurIPS 2022 D&B. [arxiv.org](https://arxiv.org/abs/2210.08402)
