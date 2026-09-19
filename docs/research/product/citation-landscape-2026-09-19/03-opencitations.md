# OpenCitations / Crossref / Lens 数据源调研

调研对象：开放引用图谱数据生态——OpenCitations 全家桶、Crossref、Lens.org、OpenAIRE、Wikidata。方法为文档调研 + REST 端点 curl 实测（实测时间 2026-09-19 UTC），目标是回答「自建引用图谱发现层时，哪些开放源能拿到边、怎么拿、代价多大」。

## OpenCitations

### 体系现状：统一 Index 取代分库

OpenCitations 早年按来源分数据集（COCI=Crossref、POCI=PubMed、DOCI=DataCite、CROCI=众包），**现已合并为统一的 OpenCitations Index**——原各库退化为 Index 内部的「来源标签」[^ocindex]。截至 2026-07-28 最新 dump，Index 收录 **2,559,460,009 条引用边**，来源包括 Crossref、DataCite、PubMed、OpenAIRE、JaLC（日本 Link Center）、OUTCITE、Matilda 及众包服务[^ocdump]。配套的 OpenCitations Meta 库存 **147,369,096 个书目实体**、2,302,011 个发表场所（venue），并已对齐 OpenAlex 标识符[^ocmeta]。

### REST API（实测）

Index API v2.2.0 基址 `https://api.opencitations.net/index/v2`，全 GET，文档列出的端点[^ocapi]：

| 端点 | 语义 |
| --- | --- |
| `/citation/{oci}` | 按 OCI（`数字-数字`）查单条引用元数据 |
| `/citations/{id}` | 某实体的全部入边（谁引了它） |
| `/references/{id}` | 某实体的全部出边（它引了谁） |
| `/citation-count/{id}` | 入边计数 |
| `/reference-count/{id}` | 出边计数 |
| `/venue-citation-count/{issn}` | 整刊被引计数 |

ID 接受 `omid`、`doi:`、`pmid:`（venue 用 `issn:`），`prefix:value` 形式。**不支持 `arxiv:` 前缀**——arXiv 论文要走其 DataCite DOI（`10.48550/arXiv.*`）。限流 180 req/min/IP，token 可选但官方鼓励申请；Accept 头或 `format` 参数可切 JSON/CSV[^ocapi]。

Meta API v1：`https://api.opencitations.net/meta/v1/metadata/doi:{doi}` 返回题名/作者/场所/日期/出版者，作者挂 omid 与 orcid，实体挂 omid/doi/openalex 交叉 ID（实测 200，715B）[^ocprobe]。

边记录字段（实测样例）：`oci`、`citing`/`cited`（omid+doi+openalex+pmid 多重标识）、`creation`（引用方发表日）、`timespan`、`journal_sc`、`author_sc`——**自带期刊自引与作者自引标志**，这是其他源需要自行计算的字段[^ocprobe]。

### arXiv 覆盖实测（关键结论）

arXiv 论文在 OC 里的表现取决于它的 DOI 形态（2022 起 arXiv 为全部论文回溯注册了 `10.48550/arXiv.*` DataCite DOI，新老 ID 都有）：

- `10.48550/arXiv.1706.03762`（Attention Is All You Need）：入边 **24,956** 条（8.7MB 响应），出边 **0**——arXiv 不向 DataCite 寄存参考文献，所以**任何 arXiv 实体都只有入边没有出边**（实测）。
- `10.48550/arXiv.hep-th/9711200`（Maldacena 1997）：入边仅 **29**——因为引用方寄存到 Crossref 的参考文献绝大多数解析到**期刊版 DOI**（`10.1023/A:1026654312961`），该期刊 DOI 实测入边 **6,881**。引用挂在哪个 DOI 上由引用方的 bib 怎么写决定（实测）。
- 推论：OC 的边是「DOI↔DOI（含 pmid/omid 内部归并）」，arXiv 侧想要被引数必须先做 **arXiv↔出版 DOI 的实体对齐**（或借 OpenAlex 的实体归并——OC 现已把 openalex ID 编进响应，实测可见）。

### Dump 与更新

官方下载页列出四种形态[^ocdump]：

| 形态 | 规模 | 压缩/解压 |
| --- | --- | --- |
| Qlever 数据库 dump（2026-07） | 25.59 亿边 / 76.79 亿三元组 | 69GB 7z / 132GB |
| N-Triples（2025-07） | 22.16 亿边 | 87.4GB / 2.1TB |
| CSV 来源标注 | 26.94 亿边 | 23GB / 104GB |
| Scholix（2025-03） | 21.55 亿边 | 40GB / 1.9TB |

Meta CSV dump 约 8GB 压缩 / 56GB 解压[^ocmeta]。dump 滞后约 5 个月（2026-02 的 Crossref 快照 → 2026-07 发布）；SPARQL 端点 `sparql.opencitations.net`（Virtuoso，调研时段内本机 TLS 连接失败，未验证可用性）。全部数据 **CC0**[^ocindex]。

## Crossref

### REST API 能力面（实测）

`api.crossref.org/works/{doi}` 单条记录含 `reference` 数组（结构化 DOI 项 + `unstructured` 原始引文字符串混合）、`references-count`、`is-referenced-by-count`。实测 `10.1145/3292500.3330928`：`references-count: 43`，reference 数组完整返回 43 条；`is-referenced-by-count: 5`——注意此计数只统计 Crossref 注册 DOI 之间的已匹配链接，系统性低于真实被引[^crprobe]。`has-references:true` 过滤实测当前有 **81,663,823** 个 work 寄存了参考文献[^crprobe]。

速率分三池（2025-12-01 起收紧过列表端点）：public 5 req/s·并发 1；polite（带 `mailto`）10 req/s·并发 3，列表查询降到 3 req/s；Metadata Plus 付费池 150 req/s 不限并发[^crrate]。

### 开放度的真正瓶颈

I4OC 运动的结果是：**2022-06-03 起 Crossref 成员寄存的参考文献一律视为开放**（不可再标记 limited/closed），开放比例从 2017 年的 1% 升至「已寄存即全开放」[^i4oc]。剩余瓶颈转移为「寄存率」——约半数 work（81.66M/约 165M）有 reference 字段；不寄存参考文献的出版商（IEEE、ACS 等部分成员历史上不寄存或迟寄存）的出边在 Crossref 生态里根本不存在[^i4ocstats]。

### Cited-by 与 bulk

Cited-by 是**会员专属服务**：只有 DOI 属主能拉自己被引清单（HTTPS/XML/OAI-PMH 三种接口 + 邮件/回调 alert），公共 API 只暴露 `is-referenced-by-count` 计数[^citedby]。实测 `GET /works/{doi}/citedby` 返回 404。配套还有会员向的 GetResolvedRefs（查 Crossref 给自己参考文献匹配出的 DOI）[^crmeta]。

Bulk：**年度公开数据文件**（March 2025 版，约 165M works、33,402 个文件）经 Academic Torrents 免费分发，AWS 镜像需自付传输费[^crfile]；月度快照属 Metadata Plus 付费档（实测匿名访问 `api.crossref.org/snapshots/monthly/...` 返回 404）。公共文件每年更新一次，增量靠 REST API 补[^crfile]。

## Lens.org

商业性质（Cambia 运营）：学术库 >248M 条记录 + 专利 >138M，学术 bulk 约 160GB 压缩 / >800GB 解压——但 bulk 只随付费机构订阅（ITK）走 S3 限时链接发放[^lensitk]。

API `api.lens.org/scholarly/search`（POST JSON 查询）：token 制，个人可申请 14 天非商业/学术试用；机构档学术 API 5 万 req/月、20 req/min、单页 1000 条[^lensapi]。字段面有 `reference.lens_id`、`reference_count`、`referenced_by`、`referenced_by_count`——**双向引用字段齐全**，还支持 `reference_cited.npl.ids.doi` 等专利非专利文献引用字段（学术↔专利边是其差异化卖点）[^lensapi]。Web UI 匿名免费，学术账号免席位费，Professional Workspace $1000/年[^lensrelease]。**数据专有，不可再分发**——只能做服务后端，不能放数据集。

## OpenAIRE Graph 与 Wikidata

OpenAIRE Graph（欧盟基础设施）：2026-06 版含 **218,421,450** 出版物，`product_Cites` 关系 **2,348,459,637** 条，另有 `product_IsRelatedTo` 5.35 亿条（含推断关系）；ScholeXplorer API 3.0 自称覆盖 3.6B 双边引用关系/4 亿+标识符。Zenodo 半年一 dump，tar 包内 gz JSONL，全量约 321GB，CC0[^oag]。规模与 OC Index 同量级且含推断边，是容易被忽视的第二来源。

Wikidata：`cites work`（P2860）共约 3.14 亿条声明[^wdp2860]，但集中在 PubMed 系批量导入的论文，arXiv/CS 覆盖稀疏；`scholarly article` 实体约 3,700–4,700 万。量级比 OC/OpenAIRE 小一个数量级，价值在其自由文本外的语义结构（作者消歧、基金）而非引用边密度。

## 横向判定

| 源 | 引用边规模 | arXiv 适配 | 获取方式 | 再分发 |
| --- | --- | --- | --- | --- |
| OpenCitations Index | 25.6 亿 | 需 arXiv↔DOI 对齐；arXiv 实体无出边 | REST 180rpm + 69GB dump | CC0 ✅ |
| OpenAIRE product_Cites | 23.5 亿 | 聚合多源含 arXiv 记录，边型待逐条核 | Zenodo 半年 dump + API | CC0 ✅ |
| Crossref | ~11 亿+寄存 ref（出边侧） | 出版 DOI 为主 | REST 10rps + 年度公开文件 | 开放元数据 ✅ |
| Lens | 未公开边数（>2.4 亿实体） | 有 arXiv 记录 | token API 限额 | ❌ 专有 |
| Wikidata | ~3.1 亿 | 稀疏 | SPARQL/dump | CC0 ✅ |

对 arXiv 时代（1991+）CS/物理/数学引用边：**OC Index 与 OpenAIRE 是仅有的两个 CC0 十亿级边集**；OC 字段干净（自引标志、OCI）、API 直接给双向邻接表，但 DOI 中心的实体模型要求自建 arXiv↔DOI 映射；Crossref 是上游原料而非成品服务（无公共反查、计数偏低）；Lens 只能当查询后端不能当数据底座；Wikidata 边密度不足。

## 对自建完整形态发现层的启示

1. **底座 = OC Index dump（或 OpenAIRE product_Cites）+ arXiv↔DOI 对齐表**。CC0 允许整图离线建仓再分发，这是合法自建的前提；`10.48550/arXiv.*` 与出版 DOI 的映射可借 OC Meta 响应里已编的 openalex ID 或 OpenAlex works.ids 补齐。
2. **自引标志白拿**：OC 边自带 `author_sc`/`journal_sc`，发现层做被引数去自引、期刊自引过滤时省去作者消歧。
3. **更新节奏错位要管理**：OC dump ~5 个月滞后，新论文入边得靠 Crossref REST（`is-referenced-by-count` + has-references 出边）或更高频源补 delta。
4. **出边缺口在 arXiv 侧普遍存在**：arXiv 实体的 references 在所有 DOI 中心源里都是空的——有 LaTeX 源/全文抽取能力的管线（如自抽 `\bibitem` 或 GROBID）填的正是这一格，OC 实测结果证明该缺口真实存在且无人填补。
5. **SPARQL/Ad-hoc 查询慎用**：OC SPARQL 端点在调研时段出现连接性故障，生产侧应以 dump 落库 + REST 兜底为骨架，不依赖在线 SPARQL。

## 探针产物

`tmp/citation-survey/opencitations/` 下：`probe_time.txt`、`oc_citations.json`、`oc_references.json`、`oc_citcount.json`、`oc_meta_v1.json`、`oc_arxiv_cits.json`（24,956 条入边全量 8.7MB）、`oc_arxiv_refs.json`、`oc_old_arxiv.json`、`oc_maldacena.json`、`oc_maldacena_refs.json`、`oc_maldacena_journal.json`、`oc_test2.json`、`oc_recheck.json`、`oc_download_index.html`、`cr_work.json`、`cr_sample.json`、`cr_snapshot_head.txt`、`cr_citedby.txt`。注：opencitations.net 在调研中段有约 5 分钟 TLS 抖动后自愈；`hep-th/9711200` 出版 DOI 对照实测 6,881 vs arXiv DOI 29；SPARQL 端点可用性未验证。

### 参考文献

[^ocindex]: Heibi, I., Moretti, A., Peroni, S., & Soricetti, M. The OpenCitations Index: Description of a database providing open citation data. Scientometrics, 2024. [doi.org](https://doi.org/10.1007/s11192-024-05160-7)
[^ocdump]: OpenCitations. Download — OpenCitations Index data dumps. 2026. [download.opencitations.net](https://download.opencitations.net/)
[^ocmeta]: OpenCitations, Massari & Peroni. OpenCitations Meta Database Dump v9.2.0. Zenodo, 2026. [zenodo.org](https://zenodo.org/records/21001553)
[^ocapi]: OpenCitations. OpenCitations Index REST API v2 documentation. [api.opencitations.net](https://api.opencitations.net/index/v2)
[^ocprobe]: 实测：`api.opencitations.net/index/v2/{citations,references,citation-count,reference-count}/doi:*` 与 `meta/v1/metadata/doi:*`，2026-09-19 UTC，原始输出见探针产物。
[^crprobe]: 实测：`api.crossref.org/works/10.1145/3292500.3330928` 与 `works?filter=has-references:true&rows=0`，2026-09-19 UTC。
[^crrate]: Crossref. Access and authentication — REST API rate limits. [crossref.org](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/)
[^i4oc]: I4OC. Initiative for Open Citations — how many citations are open today. [i4oc.org](https://i4oc.org/)
[^i4ocstats]: Kramer, B. I4OC_stats — monthly statistics on submitted references per publisher. GitHub. [github.com](https://github.com/bmkramer/I4OC_stats)
[^citedby]: Crossref. Cited-by — retrieve citations documentation. [crossref.org](https://www.crossref.org/documentation/cited-by/retrieve-citations/)
[^crmeta]: Crossref. Metadata Retrieval — services for members. [crossref.org](https://www.crossref.org/documentation/retrieve-metadata/)
[^crfile]: Crossref. 2025 public data file now available. [crossref.org](https://www.crossref.org/blog/2025-public-data-file-now-available/)；Academic Torrents 分发页 [academictorrents.com](https://academictorrents.com/details/e0eda0104902d61c025e27e4846b66491d4c9f98)
[^lensitk]: The Lens. Institutional Toolkit Subscriber Onboarding — API plans and bulk data. [support.lens.org](https://support.lens.org/knowledge-base/onboarding-institutional-toolkit-subscribers/)
[^lensapi]: The Lens. Lens API Documentation / Scholar Request. [docs.api.lens.org](https://docs.api.lens.org/request-scholar.html)
[^lensrelease]: The Lens. Release 9.4 — account categories and pricing. [about.lens.org](https://about.lens.org/release-9-4/)
[^oag]: OpenAIRE. OpenAIRE Graph Dataset (2026-06 release). Zenodo. [doi.org](https://doi.org/10.5281/zenodo.20428976)；Year in Review 2025 [openaire.eu](https://www.openaire.eu/openaire-graph-year-in-review-2025)
[^wdp2860]: Wikidata. Property talk:P2860 cites work — usage statistics. [wikidata.org](https://wikidata.org/wiki/Property_talk:P2860)
