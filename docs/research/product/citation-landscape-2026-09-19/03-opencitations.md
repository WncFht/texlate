# Lane 03: OpenCitations / Crossref / Lens / OpenAIRE / Wikidata

> **结论**：OpenCitations Index 是唯一活跃的 CC0 专用十亿级边集；OpenAIRE（2.35B 边）同量级但为 CC BY 4.0、再分发须署名（fatcat refcat 是另一 CC0 数十亿边集但 ~2021-22 起停滞，OpenAlex ~2.4B 边同为 CC0 但嵌于 works 语料非专用边集）；OC 字段干净且自带自引标志，但 DOI 中心模型要求自建 arXiv↔DOI 映射；Crossref 是上游原料而非成品服务；Lens 专有只能当查询后端。
> **状态**：时点证据（2026-09-19 口径）
> **日期**：2026-09-19

## 各源定位

- **OpenCitations Index**：早年分库（COCI/POCI/DOCI/CROCI）已合并为统一 Index，原各库退化为来源标签[^ocindex]。2026-07 dump 收 **2,559,460,009 条边**，来源含 Crossref、DataCite、PubMed、OpenAIRE、JaLC 等[^ocdump]；配套 Meta 库 147M 书目实体并已对齐 OpenAlex 标识符[^ocmeta]。
- **Crossref**：DOI 注册局元数据 API，上游原料层。
- **Lens.org**：Cambia 商业学术 + 专利库（>248M 学术记录 + >138M 专利），学术↔专利引用边是差异化卖点[^lensapi]。
- **OpenAIRE Graph**：欧盟开放学术基础设施，Zenodo 半年 dump。
- **Wikidata**：`cites work`（P2860）众包声明。

## 数据面

**OC Index** REST API v2（`api.opencitations.net/index/v2`，限流 180 req/min/IP）：`/citations/{id}` 入边、`/references/{id}` 出边、`/citation-count`/`/reference-count` 计数、`/citation/{oci}` 单条元数据；ID 接受 `omid:`/`doi:`/`pmid:`，**不支持 `arxiv:` 前缀**——arXiv 论文走 `10.48550/arXiv.*` DataCite DOI[^ocapi]。边记录字段：`oci`、`citing`/`cited`（omid+doi+openalex+pmid 多重标识）、`creation`、`timespan`、**`journal_sc`/`author_sc` 期刊与作者自引标志——其他源需自算的字段这里直接带**[^ocindex]。Dump 形态：Qlever dump 25.59 亿边 69GB 7z 压缩、CSV 来源标注 104GB、N-Triples 2.1TB；**dump 滞后约 5 个月**；全部 CC0[^ocdump]。SPARQL 端点可用性未验证（调研时段连接失败），生产侧应以 dump 落库 + REST 兜底为骨架。

**arXiv 覆盖实测（关键结论）**：`10.48550/arXiv.1706.03762` 入边 24,956 条、**出边 0**——arXiv 不向 DataCite 寄存参考文献，任何 arXiv 实体在 DOI 中心源里都只有入边没有出边。且引用挂在哪个 DOI 上由引用方 bib 怎么写决定（Maldacena 1997 的 arXiv DOI 入边仅 29 vs 期刊 DOI 入边 6,881）——**arXiv 侧想要被引数必须先做 arXiv↔出版 DOI 实体对齐**（OC Meta 响应已编入 openalex ID 可借力）。

**Crossref**：`works/{doi}` 的 `reference` 数组含结构化 DOI + `unstructured` 原始引文字符串；`is-referenced-by-count` 只统计 Crossref 内已匹配链接、系统性低于真实被引。`has-references:true` 实测 **81,663,823** 个 work 寄存了 refs——寄存率约半是真正瓶颈（IEEE/ACS 等历史上不寄存的出边在此生态不存在）[^i4oc][^i4ocstats]。I4OC 成果：2022-06 起寄存的 refs 一律开放[^i4oc]。Cited-by 是**会员专属**（公共 API 只有计数）；bulk 走年度公开文件（Academic Torrents 免费，~165M works）[^crfile]。速率：public 5 rps、polite 10 rps、Metadata Plus 150 rps[^crrate]。

**Lens**：API token 制（个人 14 天试用、机构档 5 万 req/月），`reference.lens_id`/`referenced_by` 双向字段齐全 + 专利↔学术边；**数据专有不可再分发**——只能做服务后端[^lensapi][^lensitk]。

**OpenAIRE Graph**：2026-06 版 **218M 出版物、product_Cites 关系 2,348,459,637 条**，另有 IsRelatedTo 5.35 亿条（含推断关系）；Zenodo 半年 dump 全量 **378.4GB**（tar 包 gz JSONL；product_Cites 边表 8 分片共 ~75.6GB，分片明细见 `04-domain.md`），**CC BY 4.0**（再分发须署名）[^oag]。规模与 OC Index 同量级且含推断边，是被低估的第二来源。

**Wikidata P2860**：~3.14 亿条声明但集中在 PubMed 系批量导入，arXiv/CS 覆盖稀疏；价值在语义结构（作者消歧、基金）而非边密度[^wdp2860]。

## 可借鉴点

1. 底座 = OC Index dump（或 OpenAIRE product_Cites）+ arXiv↔DOI 对齐表——OC Index 为 CC0 可无署名整图离线建仓再分发，是合法自建前提；OpenAIRE 为 CC BY 4.0，同样允许再分发但须署名。
2. `author_sc`/`journal_sc` 自引标志现成——做被引数去自引省去作者消歧。
3. 更新节奏错位要管理：OC dump ~5 个月滞后，新边靠 Crossref REST 或更高频源补 delta。
4. arXiv 出边缺口在 DOI 中心源里普遍存在且无人填补——LaTeX 源/全文抽取填的正是这一格。

## 结论

对 arXiv 时代 CS/物理/数学引用边，OC Index 是唯一活跃的 CC0 专用十亿级边集（fatcat refcat 为另一 CC0 数十亿边集但 ~2021-22 起停滞，见 `05-arxiv-pipe.md`；OpenAlex ~2.4B 边同为 CC0 但嵌于 works 语料非专用边集），OpenAIRE（2.35B 边）同量级但为 CC BY 4.0 须署名；OC 是首选校验/补全源（字段干净、API 直接给双向邻接表），OpenAIRE 作备选第二源；Crossref 只当上游原料，Lens 只能当查询后端，Wikidata 边密度不足。

### 参考文献

[^ocindex]: Heibi I, Moretti A, Peroni S, Soricetti M. The OpenCitations Index: Description of a database providing open citation data. Scientometrics, 2024. [doi.org](https://doi.org/10.1007/s11192-024-05160-7)

[^ocdump]: OpenCitations. Download — OpenCitations Index data dumps. 2026. [download.opencitations.net](https://download.opencitations.net/)

[^ocmeta]: OpenCitations, Massari & Peroni. OpenCitations Meta Database Dump v9.2.0. Zenodo, 2026. [zenodo.org](https://zenodo.org/records/21001553)

[^ocapi]: OpenCitations. OpenCitations Index REST API v2 documentation. [api.opencitations.net](https://api.opencitations.net/index/v2)

[^crrate]: Crossref. Access and authentication — REST API rate limits. [crossref.org](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/)

[^i4oc]: I4OC. Initiative for Open Citations. [i4oc.org](https://i4oc.org/)

[^i4ocstats]: Kramer B. I4OC_stats — monthly statistics on submitted references per publisher. GitHub. [github.com](https://github.com/bmkramer/I4OC_stats)

[^crfile]: Crossref. 2025 public data file now available. [crossref.org](https://www.crossref.org/blog/2025-public-data-file-now-available/)

[^lensitk]: The Lens. Institutional Toolkit Subscriber Onboarding. [support.lens.org](https://support.lens.org/knowledge-base/onboarding-institutional-toolkit-subscribers/)

[^lensapi]: The Lens. Lens API Documentation / Scholar Request. [docs.api.lens.org](https://docs.api.lens.org/request-scholar.html)

[^oag]: OpenAIRE. OpenAIRE Graph Dataset (2026-06 release). Zenodo. [doi.org](https://doi.org/10.5281/zenodo.20428976)

[^wdp2860]: Wikidata. Property talk:P2860 cites work — usage statistics. [wikidata.org](https://wikidata.org/wiki/Property_talk:P2860)
