# Lane 01: OpenAlex

> **结论**：OpenAlex 是目前唯一「免费 bulk 全量引用边 + CC0 + 可增量同步」的学术图谱源，但 2026 年已转向 freemium（API 计费、增量字段付费墙）；`related_works` 实测基本不可用、头部论文有合并事故。应作「边与元数据基底」，不是「可直接用的推荐服务」。
> **状态**：时点证据（2026-09-19 口径）
> **日期**：2026-09-19

## 该源是什么

OurResearch 运营的开放学术图谱，定位是 MAG/WoS 的免费替代。实体面：works/authors/sources/institutions/topics/keywords/funders/publishers/awards。

## 数据面

- 体量：API 报 works **327,389,651**，其中 `has_references:true` 仅 **102M（31.2%）**——七成 work 缺出边，是建图第一约束[^oa-worksobj]。官方快照口径更大（~6.49 亿条记录、JSONL 压缩 ~750GB），含 XPAC 扩展语料（`corpus=all` 才计入）[^oa-snapshot][^oa-mintlify]。
- 引用边字段：`referenced_works`（出边 ID 列表）、`cited_by_count`、`cited_by_api_url`、`abstract_inverted_index`、`best_oa_location`（arXiv PDF 直链正常）。批量解析引用用 `filter=openalex:W1|W2|...`（单 filter ≤100 OR 值）[^oa-recipes]。
- **`related_works` 不可用**（实测）：官方口径是主题/概念相似而非引用图算法[^oa-attrs]；实测相关列表里主题肉眼无关、多条 404 悬空（MAG 时代预计算遗产 + 后续删除所致）。相似论文必须自算。
- arXiv 适配：source 实体 `S4306400194` 有 **3,236,808 works、61.4% 带 refs**。`ids` 无 arXiv 字段，ID 映射走 `locations.source.id:S4306400194` filter 圈定 arXiv 子集 + `locations.landing_page_url` 反查——`10.48550` DOI 仅在作为 work canonical `doi` 时可解析、合并/期刊 DOI 记录下 404（`filter=doi:` 计数 0），不可作映射主键，仅留作 OpenCitations 侧桥（lane 03）；老 ID（`astro-ph/9901001` 等）能解析但都是 2025-10 新建的空 stub（无 refs、0 被引）。
- **数据质量事故**：标题精确搜 "attention is all you need" 按被引排序，榜首是一条 2025 年 repost（吃掉 7560 被引），真正的 Vaswani 2017 原文在库里找不到——头部论文记录完整性当前不可信，名文要走兜底校验。

## 计费与获取

2026 年已是计费制 freemium，响应头打表（`x-ratelimit-cost-usd` 等）：无 key \$0.10/天、免费 key \$1/天（~1 万次 list 调用），list+filter \$0.10/千次、search \$1/千次、content(PDF) \$10/千次[^oa-auth]。**`from_updated_date` 增量 filter 在付费墙后**——免费档无法按更新日期增量拉取。Partner 档 \$20k+/年[^oa-pricing]。

真正的建图通道是 **bulk snapshot**：`s3://openalex` 免账号匿名下载（`aws s3 --no-sign-request`），gzip JSONL 与 Parquet 双格式，按 `updated_date` 分区（实测 2446 个分区，manifest 记文件清单）——**增量同步=重下 manifest、只取新分区**[^oa-snapfmt][^oa-devdl]。免费快照季度更新，付费档日更 + Changefiles API + `deleted_ids.csv`[^oa-sync]。License **CC0**。注意公共桶只留当期 release，复现需自存档。

## 可借鉴点

1. 边基底而非推荐服务：边全量免费可下，相似度自算。
2. 覆盖缺口要正视：69% works 无 refs、arXiv 老 ID 是空 stub、名文有合并事故——叠加 S2/OpenCitations 边做并集校验。
3. 成本结构：季更快照 + LaTeX 自抽边补新文 = 零成本起步的现实路径。
4. 架构选型：750GB 全量只为 ~320 万节点 arXiv 子图（`S4306400194` source works 实测 3,236,808）浪费大——按 `locations.source.id=S4306400194` + `referenced_works` 交集过滤出自图，边表落 Parquet/DuckDB 即可，无需图数据库。

## 结论

OpenAlex 快照是自建引用图的主干数据源（唯一 CC0 + 免费 bulk + 可增量），API 只做零星补边/单篇解析。OpenAlex 缺出边的 69% works 与 arXiv 新 stub 恰好是 LaTeX `\bibitem`/`.bbl` 自抽能补的部分——这是相对纯 API 玩家的结构优势。

### 参考文献

[^oa-worksobj]: OpenAlex. Work object attributes. GitHub ourresearch/openalex-docs. [api-entities/works/work-object/README.md](https://github.com/ourresearch/openalex-docs/blob/main/api-entities/works/work-object/README.md)

[^oa-attrs]: OpenAlex. Attributes – Works. Help Center. [help.openalex.org/data/works/attributes](https://help.openalex.org/data/works/attributes/)

[^oa-recipes]: OpenAlex. API recipes. [developers.openalex.org/guides/recipes](https://developers.openalex.org/guides/recipes)

[^oa-snapshot]: OpenAlex. Snapshot – Channels. Help Center. [help.openalex.org/access/snapshot](https://help.openalex.org/access/snapshot/)

[^oa-snapfmt]: OpenAlex. Snapshot data format. [developers.openalex.org/download/snapshot-format](https://developers.openalex.org/download/snapshot-format)

[^oa-devdl]: OpenAlex. Download to your machine. [developers.openalex.org/download/download-to-machine](https://developers.openalex.org/download/download-to-machine)

[^oa-sync]: OpenAlex. Sync – Products. Help Center. [help.openalex.org/access/sync](https://help.openalex.org/access/sync/)

[^oa-mintlify]: OpenAlex. Download overview. [openalex.mintlify.app/download/overview](https://openalex.mintlify.app/download/overview)

[^oa-auth]: OpenAlex. Authentication. [developers.openalex.org/api-reference/authentication](https://developers.openalex.org/api-reference/authentication)

[^oa-pricing]: OpenAlex. Pricing Overview. [help.openalex.org/access/pricing](https://help.openalex.org/access/pricing/)
