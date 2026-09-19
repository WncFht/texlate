# OpenAlex 数据源调研

对 OpenAlex 做了一轮「文档调研 + API 实测」的数据源档案（2026-09-19 实测）。结论先行：**OpenAlex 是目前唯一「免费 bulk 全量引用边 + CC0 + 可增量同步」的学术图谱数据源**，但 2026 年它已明显转向 freemium 收费化——API 计费化、增量字段付费墙、快照分免费季度档/付费日更档；同时其 `related_works` 字段实测基本不可用，且头部论文存在合并/吞引用的数据质量事故。自建完整形态发现层应把它当「边与元数据的基底」，而不是「可直接用的推荐服务」。

## 体量与语料构成

实测（2026-09-19）API 报 works 总数 **327,389,651**；其中 `has_references:true` 为 **102,017,474**（31.2%），`has_references:false` 为 225,372,177——**仅约三成 work 带解析出的引用列表**，这是用 OpenAlex 边建图时的第一约束：绝大多数 work 是缺出边的叶子节点（含大量 Crossref 无引用注册 DOI、XPAC 扩展语料与数据档记录）[^oa-worksobj]。

官方快照文档给出的口径（2026-06 发布）：每格式约 **6.49 亿条记录**，JSONL 压缩约 **750 GB**（works 独占 ~670 GB），Parquet 约 780 GB，解压后数 TB；快照 works 数 ~5.1 亿，比 API 默认口径多——API 默认查的是"默认语料"，XPAC 扩展语料要 `corpus=all` 才计入[^oa-snapshot][^oa-mintlify]。实体面除 works 外还有 authors/sources/institutions/topics(旧 concepts)/keywords/funders/publishers/awards。

## 引用边字段形态

每个 work 对象上：

| 字段 | 语义 | 实测 |
| --- | --- | --- |
| `referenced_works` | 出边，OpenAlex ID 列表（不带给被引方元数据） | W3126721948 有 59 条 |
| `cited_by_count` | 被引数（OpenAlex 图内口径） | 同篇 1460 |
| `cited_by_api_url` | 入边分页端点（等价 `filter=cites:Wid`） | 存在 |
| `related_works` | "相关论文"，10-20 条 | **实测基本不可用，见下节** |
| `abstract_inverted_index` | 摘要倒排索引（可重建全文摘要） | 存在（55 词的短文也有） |
| `best_oa_location`/`locations` | OA 定位、arXiv landing/PDF URL | arXiv PDF 直链正常返回 |

批量解析引用的正确姿势是 `filter=openalex:W1|W2|...`（单 filter 最多 100 个 OR 值），配合 `per_page`（文档现写上限 100，实测 200 仍返回）[^oa-recipes]。`select=` 可裁掉无关字段。

## related_works：机制与实测

官方口径：`related_works` 是"**与本文 topics/concepts 重合最多的近期论文**"，即**主题/概念相似度，不是引用图算法**[^oa-attrs][^oa-worksobj]。实测比文档更糟糕：

- W3126721948（Space-Time Attention，2021）的 10 条 related：共享引用几乎为 0，主题肉眼无关（CAN 总线、微信 NMT、帧率），其中 1 条已 404（被删记录），多数被引数 ≤2——像是 **MAG 时代的预计算遗产 + 后续删除导致的悬空**（实测 2026-09-19）。
- W2626778328（Attention 2025 repost，7560 被引）的 20 条 related 倒是落在 Adam/BERT/word2vec 这些"经典邻居"上，但 8 条抽查中 3 条 404。
- 另有 `filter=related_to:Wid` 可反查"被列进谁家的 related"[^oa-filters]。

结论：**related_works 不能当相似论文服务用**——既不是共被引/耦合，又大面积悬空。自建发现层要自己算相似度，OpenAlex 只提供素材。

## arXiv 覆盖

- arXiv source 实体为 `S4306400194`（实测 works_count **3,236,808**），其中 `has_references:true` 的 **1,987,501**（61.4%）。
- **新 ID**：OpenAlex 的 `ids` 里没有 arXiv 字段，不能直接 `arxiv.org/abs/ID` 直查（实测 404）；但 arXiv 的 DataCite DOI 可用——`doi:10.48550/arxiv.2102.05095` 命中的 work `locations` 带 `arxiv.org/abs/2102.05095` 与 `pdf` 直链。**ID 映射走 DOI 或 `locations.landing_page_url` 反查**。
- **老 ID**：`doi:10.48550/arxiv.astro-ph/9901001`、`doi:10.48550/arxiv.hep-th/9901001` 均可解析到 work（实测 200）——但都是 **2025-10 新建的 stub 记录**：`referenced_works:[]`、`cited_by_count:0`、`related_works:[]`，即 arXiv DataCite DOI 批量入库后还没走完富化/合并。
- **数据质量事故案例**：标题精确搜索 "attention is all you need" 按被引排序，榜首是 W2626778328——一条 2025 年 repost（DOI 前缀 10.65215），吃掉了 7560 被引；真正的 Vaswani 2017 transformer 原文在本库里**找不到**（标题、作者、arXiv DOI、MAG ID 多个角度都探过），其作者实体 A5103024730 仅 58 works/13k 被引（真实 >15 万）。同批还见到明显错并的"高被引"垃圾记录（一条家教系统教程论文挂 79,061 被引）。**头部论文的记录完整性当前不可信**，做发现层不能假设"名文记录一定在且准"。

## API 实测与计费（重要转向）

2026 年的 OpenAlex API 已是**计费制 freemium**，响应头直接打表（实测 2026-09-19）：

| 项 | 实测/文档值 |
| --- | --- |
| 响应头 | `x-ratelimit-cost-usd: 0.0001`、`x-ratelimit-credits-used: 1`、`x-ratelimit-limit: 1000`（每 window） |
| 免费额度 | 无 key $0.10/天；免费 API key $1/天（10×），UTC 零点重置[^oa-auth][^oa-llmref] |
| 单价 | singleton 免费；list+filter $0.10/千次；search $1/千次；semantic search $1/千次；content(PDF) $10/千次[^oa-auth] |
| 硬限速 | >100 req/s → 429（本机代理下顺序实测 ~0.9 req/s，延迟瓶颈非限速） |
| 付费墙字段 | `from_updated_date` 等增量 filter 实测返回 `{"error":"Plan upgrade required"}`——**免费档无法按更新日期增量拉取** |
| 分页 | cursor 深分页正常；基础分页上限 10k 条；`sample` 上限 10k |
| 付费档 | Member+（额度提高+premium filter）；Partner $20k+/年（$200+/天额度、机构账户）[^oa-pricing] |

对自建方含义：**API 只适合做零星补边/解析单篇**，批量建图必须走快照。免费 $1/天折合约 1 万次 list 调用——拉全 arXiv 引用边不可行。

## Bulk snapshot（真正的建图通道）

- 位置：`s3://openalex`，`data/` 前缀；**免费匿名下载**（`aws s3 --no-sign-request`），AWS Open Data 项目补贴流量费（官方口径每次全量 ~$70）[^oa-snapshot][^oa-devdl]。本机环境实测 S3 域名经 http 代理 TLS 被掐（SSL EOF），属本地网络问题非服务问题，未验证直连。
- 格式：每实体 gzip JSONL 与 Parquet 双份；按 `updated_date` 分区（每分区 ≤40 万条 part 文件），`manifest.json` 记录全部文件与 `content_length`——**增量同步=重下 manifest、只取新分区**[^oa-snapfmt]。
- 节奏：**免费快照季度更新**；付费档每日全量（`s3://openalex-snapshots/full/<date>/`，API key 换临时 AWS 凭证）+ Changefiles API + works `deleted_ids.csv`（2026-08-15 起）[^oa-sync]。
- License：**CC0**，可自由再分发与商用[^oa-sync]。
- 注意：公共桶只保留当期 release，旧状态被覆盖，复现需自存档并引用 manifest 的 date。

## 对自建完整形态发现层的启示

1. **OpenAlex 是"边基底"而非"推荐服务"**：`referenced_works`/`cites` 边全量免费可下，但没有可用的相似度/推荐字段（related_works 是主题相似且残破）。相似论文必须自算（共被引/耦合/embedding）。
2. **覆盖缺口要正视**：69% works 无引用列表；arXiv 老 ID 是新 stub、头部名文有合并事故。自建层应以 OpenAlex 边为主干，叠加 S2/OpenCitations 边做并集校验，名文走兜底校验。
3. **成本结构**：免费快照季度延迟可接受（引用图是慢变量）；要日更得 Member+/Partner 付费或靠 API 增量（但 from_updated_date 付费墙）。季更快照 + LaTeX 源自抽边补新文，是零成本起步的现实路径。
4. **架构选型**：750GB JSONL 全量只为了 arXiv 子图（~250 万节点）浪费大——下载后按 `locations.source.id=S4306400194` + `referenced_works` 交集过滤出自图，边表落 Parquet/DuckDB 即可，无需图数据库。
5. **若有 LaTeX 源可自抽引用边**：OpenAlex 缺出边的 69% works 与 arXiv 新 stub，恰好是 LaTeX `\bibitem`/`.bbl` 自抽能补的部分——这是相对纯 API 玩家的结构优势。

## 探针产物

`tmp/citation-survey/openalex/`：`works_meta.json`（总量 meta）、`attn.json`（标题搜索结果）、`src_search.json`（arXiv source 实体）、`w_spaceattn.json`/`w_attn_related.json`（related_works 抽查）、`doi_9901001.json`（老 arXiv stub 记录）、`oa_1706.03762.json`/`doi_arxiv.1706.03762.json`（直查 404 证据）。注意本环境 Bash cwd 不跨命令持久，早期探针曾落 repo 根目录，已归位（snap_doc.html 为空文件未保留）。

### 参考文献

[^oa-worksobj]: OpenAlex. Work object attributes. GitHub ourresearch/openalex-docs. [api-entities/works/work-object/README.md](https://github.com/ourresearch/openalex-docs/blob/main/api-entities/works/work-object/README.md)
[^oa-attrs]: OpenAlex. Attributes – Works. Help Center. [help.openalex.org/data/works/attributes](https://help.openalex.org/data/works/attributes/)
[^oa-filters]: OpenAlex. Filter works. GitHub ourresearch/openalex-docs. [api-entities/works/filter-works.md](https://github.com/ourresearch/openalex-docs/blob/main/api-entities/works/filter-works.md)
[^oa-recipes]: OpenAlex. API recipes. [developers.openalex.org/guides/recipes](https://developers.openalex.org/guides/recipes)
[^oa-snapshot]: OpenAlex. Snapshot – Channels. Help Center. [help.openalex.org/access/snapshot](https://help.openalex.org/access/snapshot/)
[^oa-snapfmt]: OpenAlex. Snapshot data format. [developers.openalex.org/download/snapshot-format](https://developers.openalex.org/download/snapshot-format)
[^oa-devdl]: OpenAlex. Download to your machine. [developers.openalex.org/download/download-to-machine](https://developers.openalex.org/download/download-to-machine)
[^oa-sync]: OpenAlex. Sync – Products. Help Center. [help.openalex.org/access/sync](https://help.openalex.org/access/sync/)
[^oa-mintlify]: OpenAlex. Download overview. [openalex.mintlify.app/download/overview](https://openalex.mintlify.app/download/overview)
[^oa-auth]: OpenAlex. Authentication. [developers.openalex.org/api-reference/authentication](https://developers.openalex.org/api-reference/authentication)
[^oa-llmref]: OpenAlex. LLM Quick Reference. [help.openalex.org/api/llm-quick-reference](https://help.openalex.org/api/llm-quick-reference/)
[^oa-pricing]: OpenAlex. Pricing Overview. [help.openalex.org/access/pricing](https://help.openalex.org/access/pricing/)
