# 引用图谱发现层工程规模核算

本 lane 只回答一件事：自建一个「服务全 arXiv（现刊 ~316 万篇）乃至更大规模的引用图谱发现层」到底要多少数据、多少存储、多少算力。所有能实测的都做了实测（2026-09-19，探针产物见文末），估不出来源的标「估算」。

## 数据规模实测

### OpenAlex

- **API 在线口径**：works 总数 **327,389,651**（实测 `api.openalex.org/works` meta.count，2026-09-19）。
- **快照口径**：2026-06-26 release 的 `manifest.json` 实测——**649,096,577 条记录、745.5 GB 压缩 JSONL**；其中 works 实体 510,372,821 条 / 665.7 GB（快照 works 计数含 API 已过滤的墓碑/合并记录，故大于 API 口径——未验证但方向明确）；authors 119.1M / 74.3 GB；其余实体合计 &lt;6 GB[^oa-manifest]。
- **下载成本**：S3 `s3://openalex` 公开桶、**免 AWS 账号免流量费**；免费快照季度更新，付费档月更+每日变更文件；同时提供 Parquet 副本[^oa-dl]。
- **引用边规模**：随机采样（`sample=100`，5 seeds，n=125）显示仅 ~25.6% 的随机 works 带 `referenced_works`、全体均值 ~7.5 条——推总边数 **~2.4B**，与 S2 的 2.4B 惊人一致（注意默认排序采样会严重高估：非随机样本 81.5% 带边、均值 34.7）。**估算**。
- **arXiv 覆盖**：`locations.source.id:S4306400194` 实测 **3,729,541** works 带 arXiv location——相对 arXiv 现刊 316 万篇，覆盖充分（一篇可有多个 location，数字含重复归属）。**坑**：arXiv DataCite DOI（`10.48550/arXiv.1706.03762`）在 OpenAlex 是 **404**（实测）——arXiv 记录走 MAG/抓取管道而非 DOI 注册，做 ID 映射时不能靠 DOI。
- **速率**：实测响应头 `x-ratelimit-remaining: 998`、`x-ratelimit-reset: ~71149s`、`cost_usd: 0.0001/req`——与官方 polite pool 口径（10 rps、10 万 req/日，mailto 即可）一致[^oa-limits]。
- **schema**：works shard 实测含 `referenced_works`、`related_works`、`referenced_works_count`、`fwci`、`citation_normalized_percentile`、`abstract_inverted_index`、`locations` 等全字段；文件按 `updated_date` 分区（2446 个文件），增量同步天然可行。

### Semantic Scholar（release 2026-09-17，实测 datasets API）

| 数据集 | 记录数 | 压缩体积 | 内容 |
| --- | --- | --- | --- |
| papers | 200M | 30×1.5 GB ≈ 45 GB | 核心元数据（title/authors/date/externalIds） |
| citations | **2.4B** | 30×8.5 GB ≈ 255 GB | 引用边，带 influential/intent/context 属性 |
| abstracts | 100M | 30×1.8 GB ≈ 54 GB | 摘要 |
| embeddings-specter_v1 /_v2 | 各 120M | 各 30×28 GB ≈ **840 GB** | 768 维论文向量 |
| s2orc / s2orc_v2 | 10M / 16M | ≈120/180 GB | OA 全文结构化解析 |
| tldrs | 58M | ≈6 GB | 一句话摘要 |
| authors / paper-ids | 75M / 450M | ≈3/15 GB | 作者与 ID 映射 |

- **在线 API 实测**：`api.semanticscholar.org/graph/v1` 与 `/recommendations/v1` 无鉴权调用**连续 429**（间隔 20s+ 仍 429，2026-09-19）——名义 1 rps 的无鉴权池实际已不可用，生产必须申请 API key。datasets 元信息端点不受影响。
- license：数据集 ODC-BY，可免费商用需署名[^s2-datasets]。

### arXiv 本体

- 现刊 **3,157,829 篇**（2026-09-03），2026 年 4 月破 300 万，月新增 ~3.0-3.2 万篇[^arxiv-stats]。
- bulk：S3 **requester-pays** 桶，全量 PDF+source 合计 ~9.2 TB（2025-04），月增 ~100 GB；其中 source（LaTeX tar）~2.9 TB、PDF ~2.7 TB（2023-03 口径）[^arxiv-s3]。按 S3 $0.09/GB 出站价估算，一次性全量下载 **~$800-830**。
- 元数据走 OAI-PMH（日更）/ Kaggle snapshot / export.arxiv.org（建议 4 rps 突发+1s sleep）[^arxiv-bulk]。

## 两档规模画像

### 档一：arXiv 子图（~3.2M 节点）

- 边数：每篇均 ~20-35 条参考文献（arXiv 学科偏高），OpenAlex/S2 内匹配到 arXiv 内节点的比例按 ~50-70% 估——**arXiv 内部边 ~40-70M 条**（估算）。
- 存储：边表 u32 对 = 70M×8B ≈ **560 MB**；CSR 邻接表 ≈ 300 MB 级；带元数据的 parquet 边表 &lt;1 GB。**单机笔记本内存即可放下全图**。
- 向量：SPECTER 768 维 f32 → 3.2M×768×4 ≈ **9.8 GB**；f16/量化后 ~2.5-5 GB；FAISS/HNSW 索引再乘 ~1.2-1.5。
- topK 预计算：3.2M 节点 × top50 = 1.6 亿行 × ~12B（id+score）≈ **2 GB**，预计算一晚跑完（估算）。
- 结论：**arXiv 子图是单机问题**，16-32 GB RAM 的一台 VPS（$40-80/月）可同时扛住图查询 + ANN + API 服务。

### 档二：全图（~2.4B 边、2-3.3 亿节点）

- 边存储：u64 边表 ≈ 38 GB，u32（若压到 2 亿内 OpenAlex ID→int 映射）≈ 20 GB；parquet 列存 ~15-25 GB；CSR u32 ≈ **10-20 GB**（估算）。
- 处理成本：745 GB jsonl 解压+解析抽取 (id, referenced_works) 两列，单机估算 4-10 小时（gzip+JSON 解析 ~30-80 MB/s/核）；PySpark/Ray 集群可压到 1 小时内。抽出后边表 ~20 GB，后续全在 parquet 上工作。
- 图数据库路线对比见下表——**结论先行：不要上 Neo4j**，这个规模的邻接遍历用 CSR/DuckDB 便宜两个数量级。

| 形态 | 2.4B 边存储 | 一跳邻接查询 | 适用 |
| --- | --- | --- | --- |
| parquet + DuckDB | ~20 GB | ~10-50 ms（列扫 bloom+索引） | 离线批算、冷数据 |
| SQLite（边表+索引） | ~30-40 GB | ~1-5 ms | 轻量在线、单写 |
| 内存 CSR | ~10-20 GB RAM | ~µs 级 | 在线服务热路径 |
| Neo4j/Nebula | 150-300+ GB（含索引） | ~ms | 多跳图算法才值——本场景用不上 |

（以上均为估算；CSR/DuckDB 数字由记录数×字节宽推得，Neo4j 按社区经验 60-120B/relationship+索引估）

## 相似论文服务的三种实现与成本

1. **托管 API 直接骑**：OpenAlex `related_works` 免费带在 works 记录里（实测 W2626778328 返回 20 条，与 references 交集 6/20——非纯共被引，是混合信号，ds-openalex lane 有详查）；S2 `/recommendations` 需 key 且速率有限。成本=零基础设施，但覆盖率、稳定性、算法不可控。
2. **预计算 topK**（推荐起步）：离线对全库算共被引+耦合+embedding 混合分，写 2 GB 结果表，在线 = 一次 KV 查询（µs 级）。缺陷：新论文要等下次批算（周更可接受）。
3. **实时计算**：共被引 = 两个已排序被引列表的交集，70M 边图上是 ~µs-ms 级；embedding ANN topK 也是 ms 级。**结论：实时完全可行，预计算只是省机器，不是必需品**。

## 三条路线成本模型

| 项 | A 全自建 | B 全骑托管 API | C 混合 |
| --- | --- | --- | --- |
| 数据获取 | OpenAlex 快照免费下载 745 GB（或只取 works 分区 665 GB）；S2 datasets 免费 | 零下载 | OpenAlex 快照一次性 + API 补长尾 |
| 一次性算力 | 解压抽边 4-10h + topK 批算数小时（单机） | — | 同 A 左 |
| 覆盖 316 万 arXiv 的 backfill | 天然全覆盖 | OpenAlex 10 万 req/日 → **~32 天**；S2 无 key 实测不可用 | 热数据全覆盖+冷启动 API |
| 月运行 | $40-80 VPS | $0（速率内）但受配额与稳定性绑死 | $40-80 VPS |
| 更新 | 季度快照重导 或 API diff 补 | 自动 | 季度重导+API 增量 |
| 风险 | 数据新鲜度=快照节奏 | 对方改算法/限流/停服即死；related_works 黑盒 | 主要继承 A 的风险 |

- **LaTeX 自抽边的增量价值**：OpenAlex/S2 对 arXiv 新论文（&lt;1-2 周）与被引匹配有滞后；手里有 LaTeX 源可立刻产出出边（`.bbl`/`\bibitem` 解析），把「新论文无 similar」的窗口从数周压到零——这是 A/C 路线独有的新鲜度补丁，估算每篇抽取成本 &lt;0.1 CPU·s。
- **鲜为人知的便宜项**：OpenAlex works 文件按 `updated_date` 分区（实测 2446 个分区文件），做「只同步本季度变更」时不用全量重下——`aws s3 sync` 按分区增量即可，季度增量 ~几十 GB 级（估算）。

## 分阶段路线建议

1. **MVP（1-2 周）**：买/复用一台 32 GB RAM 机器 → `aws s3 sync` 拉 OpenAlex works 分区（665 GB）→ 抽 (id, referenced_works, arXiv 标记) 两列到 parquet（~20 GB）→ 过滤出 arXiv 子图（~40-70M 边）→ DuckDB/CSR 服务 `similar(paper) = 共被引+耦合 topK`。**只依赖免费快照，无 key，覆盖天然全量**。
2. **加 embedding 混合**：S2 datasets 的 `embeddings-specter_v2` 按 paper-ids join 回 arXiv 子集（840 GB 全量不必下——数据集分 30 片可按 ID 过滤流式抽取，估算取 ~3M 条向量 ~10 GB），建 HNSW；最终分 = α·共被引 + β·耦合 + γ·cosine。
3. **新论文热路径**：LaTeX 源自抽边即时入图（增量 CSR 或 WAL→定期重 bake），embedding 用 SPECTER2 模型自跑（768 维，单 CPU ~百 ms 级）。
4. **全图扩展（可选）**：同样管线不换形，边表升到 ~20 GB、CSR 20 GB RAM——一台 64 GB 机器仍够；只有要服务 arXiv 之外全学科才需要这步。

一句话：**arXiv 子图是单机问题，全图也只是一台大内存机器的问题；路线 C（OpenAlex 快照打底 + LaTeX 自抽边补新 + API 兜底）是唯一没有硬依赖风险的走法**。

### 参考文献

[^oa-manifest]: OurResearch. OpenAlex JSONL snapshot manifest（2026-06-26 release，`s3://openalex/data/jsonl/manifest.json` 实测拉取）.
[^oa-dl]: OpenAlex. Snapshot – Access &amp; authentication. [help.openalex.org/access/snapshot](https://help.openalex.org/access/snapshot/); [developers.openalex.org/download](https://developers.openalex.org/download/overview).
[^oa-limits]: OpenAlex. Rate limits and polite pool. [docs.openalex.org](https://docs.openalex.org/)（响应头实测 2026-09-19）.
[^s2-datasets]: Semantic Scholar. Academic Graph Datasets release 2026-09-17（`api.semanticscholar.org/datasets/v1/release/latest` 实测）.
[^arxiv-stats]: arXiv. Monthly submissions（截至 2026-09-03 共 3,157,829 篇）. [arxiv.org/stats/monthly_submissions](https://arxiv.org/stats/monthly_submissions); arXiv blog 2026-07-09.
[^arxiv-s3]: arXiv. Full Text via S3. [info.arxiv.org/help/bulk_data_s3.html](https://info.arxiv.org/help/bulk_data_s3.html).
[^arxiv-bulk]: arXiv. Bulk Data Access. [info.arxiv.org/help/bulk_data.html](https://info.arxiv.org/help/bulk_data.html).

## 探针产物

- `tmp/citation-survey/engineering/oa_works_meta.json` — works 总数 meta
- `tmp/citation-survey/engineering/oa_arxiv_source.json` — arXiv source 记录（S4306400194）
- `tmp/citation-survey/engineering/oa_arxiv_count.json` — arXiv location works 数（3,729,541）
- `tmp/citation-survey/engineering/oa_sample_refs.json`、`oa_sample_{7,19,33,55,71}.json`、`oa_sample_rand.json` — 引用边分布随机采样
- `tmp/citation-survey/engineering/oa_manifest.json` — 2026-06-26 快照完整 manifest（实体×大小×文件清单）
- `tmp/citation-survey/engineering/works_shard.gz` — works 分区实样（schema 验证）
- `tmp/citation-survey/engineering/oa_attn.json` — related_works 实测样例
- `tmp/citation-survey/engineering/s2_release.json` — S2 数据集 release 2026-09-17 全量清单
- `tmp/citation-survey/engineering/s2_attn.json`、`s2_recs.json` — S2 429 实测记录
