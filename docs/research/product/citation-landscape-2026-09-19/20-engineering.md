# Lane 20：引用图谱发现层工程规模核算

> **结论**：arXiv 子图（~3.2M 节点、~40-70M 内部边）是单机问题——边表 u32 ~560MB、CSR ~300MB、SPECTER f32 ~9.8GB，一台 $40-80/月 VPS 可同扛图查询+ANN+API；全图（2.4B 边）也只是一台大内存机器的问题（CSR 10-20GB），不要上 Neo4j。路线 C（OpenAlex 快照打底+LaTeX 自抽边补新+API 兜底）是唯一没有硬依赖风险的走法。
> **状态**：时点证据（2026-09-19 口径）
> **日期**：2026-09-19

## 数据规模实测（2026-09-19）

**OpenAlex**：API 在线口径 works 总数 **327,389,651**；快照口径（2026-06-26 release manifest 实测）**649,096,577 条记录、745.5GB 压缩 JSONL**，其中 works 实体 510,372,821 条/665.7GB（快照计数含 API 已过滤的墓碑/合并记录故大于 API 口径）[^oa-manifest]。S3 公开桶**免 AWS 账号免流量费**，免费快照季度更新，文件按 `updated_date` 分区（2446 个）——增量同步天然可行[^oa-dl]。引用边规模：随机采样（n=125）显示仅 ~25.6% 随机 works 带 `referenced_works`、均值 ~7.5 条（按全部采样 works 无条件计，无 refs 记 0）——**推总边数 ~2.4B（=API 口径 327.4M works × 7.5；快照 510M 口径含墓碑/合并记录、贡献 ~0 边，不参与推总），与 S2 的 2.4B 惊人一致**（估算；非随机样本会严重高估。注：若该均值实为仅对带 refs 的 25.6% 求均值的条件口径，则推总仅 ~0.6–1.0B，本行结论与档二存储表需一并复核）。arXiv 覆盖：`locations.source.id:S4306400194` 实测 **3,729,541** works 带 arXiv location，相对现刊 316 万覆盖充分；**坑：arXiv DataCite DOI（`10.48550/arXiv.*`）在 OpenAlex 是 404**——ID 映射不能靠 DOI[^oa-limits]。

**S2**（release 2026-09-17 实测）：papers 200M ~45GB、citations **2.4B ~255GB**（带 influential/intent/context）、abstracts 100M ~54GB、embeddings-specter_v1/_v2 各 120M ~840GB、s2orc_v2 16M ~180GB、paper-ids 450M ~15GB；license ODC-BY[^s2-datasets]。在线 API 无鉴权池实测连续 429——名义 1rps 实际已不可用，生产必须申 key。

**arXiv 本体**：现刊 **3,157,829 篇**（2026-09-03），月增 ~3.0-3.2 万[^arxiv-stats]。bulk S3 requester-pays 全量 PDF+source ~9.2TB（source LaTeX ~2.9TB），一次性全量下载估算 **~$800-830**[^arxiv-s3]；元数据走 OAI-PMH/Kaggle/export API[^arxiv-bulk]。

## 两档规模画像

**档一：arXiv 子图（~3.2M 节点）**。边数：每篇 ~20-35 条参考文献×匹配回 arXiv 内节点 ~50-70% → **内部边 ~40-70M**（估算）。存储：u32 边表 70M×8B≈**560MB**、CSR ≈300MB、带元数据 parquet <1GB——**单机内存即可放下全图**。向量：SPECTER 768d f32→3.2M×768×4≈**9.8GB**，f16 ~2.5-5GB。topK 预计算：3.2M×top50=1.6 亿行×~12B≈**2GB**，一晚跑完。**结论：arXiv 子图是单机问题**，16-32GB RAM VPS（$40-80/月）同扛图查询+ANN+API。

**档二：全图（~2.4B 边、2-3.3 亿节点）**。边存储：u64 ~38GB、u32（OpenAlex ID→int 映射）~20GB、parquet ~15-25GB、CSR u32 **~10-20GB**。处理：745GB jsonl 解压抽 (id, referenced_works) 两列单机估 4-10h（PySpark/Ray 可压到 1h 内）。

| 形态                | 2.4B 边存储  | 一跳邻接查询 | 适用                         |
| ------------------- | ------------ | ------------ | ---------------------------- |
| parquet + DuckDB    | ~20GB        | ~10-50ms     | 离线批算、冷数据             |
| SQLite（边表+索引） | ~30-40GB     | ~1-5ms       | 轻量在线、单写               |
| 内存 CSR            | ~10-20GB RAM | ~µs 级       | 在线服务热路径               |
| Neo4j/Nebula        | 150-300+GB   | ~ms          | 多跳图算法才值——本场景用不上 |

**结论先行：不要上 Neo4j**——这个规模的邻接遍历用 CSR/DuckDB 便宜两个数量级。

## similar-papers 三种实现与成本

1. **托管 API 直接骑**：OpenAlex `related_works` 免费带在 works 记录里（实测与 references 交集 6/20——非纯共被引是混合信号）；S2 `/recommendations` 需 key 速率有限。零基础设施，但覆盖率/稳定性/算法不可控。
2. **预计算 topK**（推荐起步）：离线对全库算共被引+耦合+embedding 混合分写 ~2GB 结果表，在线=一次 KV 查询 µs 级；缺陷是新论文要等下次批算（周更可接受）。
3. **实时计算**：共被引=两个已排序被引列表的交集，70M 边图上 µs-ms 级；embedding ANN topK 也是 ms 级——**实时完全可行，预计算只是省机器不是必需品**。

## 三条路线成本模型

| 项                         | A 全自建                               | B 全骑托管 API                                     | C 混合                         |
| -------------------------- | -------------------------------------- | -------------------------------------------------- | ------------------------------ |
| 数据获取                   | OpenAlex 快照 745GB 免费 + S2 datasets | 零下载                                             | OpenAlex 快照一次性+API 补长尾 |
| 一次性算力                 | 解压抽边 4-10h+topK 批算数小时（单机） | —                                                  | 同 A 左                        |
| 覆盖 316 万 arXiv backfill | 天然全覆盖                             | OpenAlex 10 万 req/日→**~32 天**；S2 无 key 不可用 | 热数据全覆盖+冷启动 API        |
| 月运行                     | $40-80 VPS                             | $0（速率内）但受配额绑死                           | $40-80 VPS                     |
| 更新                       | 季度快照重导或 API diff                | 自动                                               | 季度重导+API 增量              |
| 风险                       | 数据新鲜度=快照节奏                    | 对方改算法/限流/停服即死                           | 主要继承 A 的风险              |

两个加分项：**LaTeX 自抽边的增量价值**——OpenAlex/S2 对 arXiv 新论文与被引匹配有 1-2 周+滞后，手里有 LaTeX 源可立刻产出出边（`.bbl`/`\bibitem` 解析），把「新论文无 similar」窗口从数周压到零，估算每篇抽取成本 <0.1 CPU·s；**OpenAlex `updated_date` 分区**——季度增量同步只需拉变更分区 ~几十 GB，不用全量重下。

## 分阶段路线

1. **MVP（1-2 周）**：32GB RAM 机器→`aws s3 sync` 拉 OpenAlex works 分区（665GB）→抽 (id, referenced_works, arXiv 标记) 到 parquet（~20GB）→过滤 arXiv 子图（~40-70M 边）→DuckDB/CSR 服务 `similar(paper)=共被引+耦合 topK`。只依赖免费快照、无 key、覆盖天然全量。
2. **加 embedding 混合**：S2 `embeddings-specter_v2` 按 paper-ids join 回 arXiv 子集（840GB 全量不必下——30 片按 ID 过滤流式抽取 ~3M 条向量 ~10GB）建 HNSW；最终分=α·共被引+β·耦合+γ·cosine。
3. **新论文热路径**：LaTeX 源自抽边即时入图（增量 CSR 或 WAL→定期重 bake），embedding 用 SPECTER2 自跑（768d，单 CPU ~百 ms 级）。
4. **全图扩展（可选）**：管线不换形，边表升 ~20GB、CSR 20GB RAM——一台 64GB 机器仍够；只有要服务 arXiv 之外全学科才需要这步。

## 结论

arXiv 子图是单机问题，全图也只是一台大内存机器的问题；路线 C（OpenAlex 快照打底+LaTeX 自抽边补新+API 兜底）是唯一没有硬依赖风险的走法——LaTeX 自抽边同时是成本项与差异化资产：别家补不平的新鲜度窗口。

### 参考文献

[^oa-manifest]: OurResearch. OpenAlex JSONL snapshot manifest（2026-06-26 release，s3://openalex 实测拉取）.

[^oa-dl]: OpenAlex. Snapshot – Access & authentication. [help.openalex.org/access/snapshot](https://help.openalex.org/access/snapshot/)

[^oa-limits]: OpenAlex. Rate limits and polite pool（响应头实测 2026-09-19）. [docs.openalex.org](https://docs.openalex.org/)

[^s2-datasets]: Semantic Scholar. Academic Graph Datasets release 2026-09-17（实测）. [api.semanticscholar.org/datasets/v1](https://api.semanticscholar.org/datasets/v1/release/latest)

[^arxiv-stats]: arXiv. Monthly submissions（截至 2026-09-03 共 3,157,829 篇）. [arxiv.org/stats/monthly_submissions](https://arxiv.org/stats/monthly_submissions)

[^arxiv-s3]: arXiv. Full Text via S3. [info.arxiv.org/help/bulk_data_s3.html](https://info.arxiv.org/help/bulk_data_s3.html)

[^arxiv-bulk]: arXiv. Bulk Data Access. [info.arxiv.org/help/bulk_data.html](https://info.arxiv.org/help/bulk_data.html)
