# 领域数据库引用数据调研

针对各专业文献库的开放引用数据做了一轮「文档调研 + 直接探针」，目标是回答：除 OpenAlex/S2/COCI 这些大图之外，领域库（INSPIRE-HEP、NASA ADS、PubMed 系、zbMATH、OpenAIRE 等）里谁有可直接取用的引用边、接口形态如何、对一个 arXiv 尺度的自建发现层有多少边际价值。

## 实测环境说明

本机 DNS 对部分域名返回 fake-ip（如 `api.inspirehep.net` 解析到 198.18.5.1 保留段，直连拿到的是无关 haproxy 证书），所有 API 探测必须走代理或改用主域。以下实测均以 2026-09-19 北京时间为准。

## INSPIRE-HEP：高能物理引用网的完全体

INSPIRE-HEP 是 CERN/SLAC/DESY/Fermilab/IHEP 等联合运营的高能物理文献库，前身是 SPIRES。它对本调研最有价值的一点：**它是「在 arXiv 上建引用图谱」这件事的现成参考实现**——它的采集管线（hepcrawl）就是定时爬 arXiv OAI-PMH，再用自家开源的 refextract 从 PDF/LaTeX 抽参考文献并消歧成库内 record[^inspire-harvest][^refextract]。

### API 面（实测）

官方 REST API 文档在 GitHub 维护[^inspire-api-doc]。免鉴权、只读 GET：

- 记录查询：`GET /api/literature/{recid}` 或 `GET /api/literature?q=&lt;query&gt;`。`api.inspirehep.net` 与 `inspirehep.net/api` 双入口（后者实测可用，前者受本机 fake-ip DNS 影响——属本机网络问题非服务故障）。
- **老 arXiv ID 直接可查**（实测）：`q=arxiv_eprints.value:hep-th/0301120` → recid 611845，`astro-ph/9901001` → recid 518795，均命中 1 条。
- **引用边双向可取**（实测）：单条记录 `metadata.references` 内嵌完整参考文献列表，每条含 `record.$ref`（已消歧的库内链接）、`reference.arxiv_eprint`、`curated_relation`（人工审定标记）三件套；反向用搜索语法 `q=refersto:recid:611845` 拿引用它的论文（实测返回 total=31，与记录内 `citation_count` 一致）。
- 排序：`sort=mostcited`（按引用数）/`mostrecent`；`topcite 1000+` 这类 SPIRES 遗留查询语法仍可用[^inspire-api-doc]。
- 分页：`size` 上限 1000，单查询结果窗口上限 10000（更大结果集需按条件切分）[^inspire-api-doc]。
- 速率：官方限制 15 请求/5 秒/IP，超限返回 429 + `x-retry-in` 头[^inspire-api-doc][^inspire-mcp]。（早期版本文档写作「50 次突发后 2 rps」，现行口径以 15/5s 为准。）
- 其他格式：`?format=bibtex|latex-eu|latex-us|cv|json`；还有个有意思的 `POST /api/bibliography-generator`——传一个含 `\cite{}` 的 TeX 文件，服务端帮你生成参考文献表（refextract 消歧能力的直接外露）[^inspire-api-doc]。
- License：大部分元数据 CC0，个别字段有限制、禁批量抓邮箱[^inspire-api-doc]。

### 数据特点

references 的消歧质量是人工+机器双保险（`curated_relation: true` 的记录经过编辑审定），高能物理域内覆盖近乎完全——SPIRES 从 1974 年就开始建引用库，arXiv 时代（1991+）的 hep-th/hep-ph/astro-ph/gr-qc 几乎全覆盖。局限：基本不覆盖 CS。

## NASA ADS：二阶算子语义的教科书

NASA ADS（Astrophysics Data System）覆盖天文/物理，API 需要免费 token（注册账号后在设置页 Generate key，`Authorization: Bearer &lt;token&gt;` 头）[^ads-api]。速率按端点计，响应头 `X-RateLimit-Limit/Remaining/Reset` 自报额度；Solr 搜索端点约 5000 次/日，`/search/bigquery`（POST 传 bibcode 列表，单次上限 2000 个）约 100 次/日[^ads-api][^ads-handout]。

ADS 对本调研的核心价值不在数据（要 token、有日额），而在它把「引用图谱发现」抽象成了一组可组合的二阶查询算子——这套语义几乎是发现层 API 设计的现成模板[^ads-second-order][^ads-citref]：

| 算子 | 语义 | 对应的图谱操作 |
| --- | --- | --- |
| `citations(q)` | 返回引用了 q 结果集的论文 | 正向入边遍历 |
| `references(q)` | 返回被 q 结果集引用的论文（它们的参考文献并集） | 出边遍历 |
| `similar(q)` | 把 q 结果集的摘要拼成大文档，对全库做文本相似排序 | 文本相似（非图谱） |
| `trending(q)` | 读 q 结果集论文的人最近还在读什么，按频次排 | 协同阅读（co-readership，行为信号） |
| `useful(q)` | 合并 q 结果集的参考文献表，按被引频次排 | 文献耦合的聚合形态——找领域方法/工具论文 |
| `reviews(q)` | 找大量引用 q 结果集的论文 | 共被引聚合形态——找综述 |
| `topn(n,q,sort)` | q 结果集里按序取前 n | 排序裁剪 |
| `pos()` | 位置字段查询 | — |

算子可嵌套（如 `trending(topn(10, reviews("weak lensing")))`）、可与普通布尔查询组合。注意 `useful` 和 `reviews` 这对组合就是文献耦合与共被引的查询级封装——与 Connected Papers 的相似度口径同源。`similar()` 是摘要文本相似，`trending()` 用的是 ADS 独有的用户行为日志，这两路是引用图之外的信号。

## PubMed 系：生物医学的 NIH-OCC 引用闭环

生物医学领域的引用数据形成了一个以 PubMed 为轴的自给自足生态，三件套均已实测：

**iCite（NIH Office of Portfolio Analysis）**。免鉴权 REST，`/api/pubs?pmids=a,b,c`（单次上限 1000 个 PMID），返回字段直接就是引用图谱所需全套：`cited_by`（引用方 PMID 列表）、`references`（参考文献 PMID 列表）、`citation_count`、`relative_citation_ratio`（RCR，领域归一化引用影响力）、`nih_percentile`、`expected_citations_per_year`、`field_citation_rate`，外加 human/animal/molecular_cellular 标记与现成的 x_coord/y_coord 可视化坐标[^icite-api][^icite-fields]。实测 `pmids=16367622,24159173` 返回完整（RCR 1.295、nih_percentile 59.3）。另有 offset/limit 的全库遍历模式与 **figshare 上的全量数据库快照**[^icite-api]。

**NIH Open Citation Collection（NIH-OCC）**。iCite 背后的数据集：从 MedLine/PMC/Entrez + Crossref + 自家 ML 管线从开放全文抽取的参考文献合并而成，2019 年论文时已有 4.2 亿+ 条 PubMed↔PubMed 引用边，号称 2010 年后的覆盖超过商业库[^nih-occ]。构建路线本身是个范本：**Crossref 打底 + 全文 ML 抽取补齐 DOI 前时代**。

**NLM elink**。E-utilities 的 `elink.fcgi?dbfrom=pubmed&amp;linkname=pubmed_pubmed_citedin` 返回引用方 PMID（实测 PMID 16367622 → 3 条，远少于 iCite 的 22 条 citation_count——elink 只含 NLM 内部链接，iCite 还融合了 Crossref 与全文抽取）。eutils 有 api_key 可提速（无 key 3 rps）。

**Europe PMC**。免鉴权 REST（约 10 rps 惯用上限），`/{source}/{id}/citations` 与 `/references` 端点（source ∈ MED/PMC/PPR/PAT/AGR…，含 preprint），pageSize 上限 1000，返回引用方/被引方的完整元数据[^epmc-rest]。实测 PMID 24159173 的 references 返回 50 条。规模：3300 万出版物、1940 万有参考文献表[^epmc-dev]。无专门的引用边批量 dump，bulk 只覆盖 OA 全文与元数据。

## 数学系：zbMATH Open

`api.zbmath.org/v1` 免鉴权 REST（uvicorn 后端，实测）。记录内嵌 `references[]`，每条带 `zbmath.document_id`（即库内引用边）、author_codes、msc 分类；但 doi/position/text 字段对相当多记录显示「unavailable due to conflicting licenses」——即**边可用、边文本不可用**[^zbmath]。MathSciNet（AMS 商业版）的引用匹配不开放。另有 OAI-PMH 接口。

## 通用聚合与元数据库

**OpenAIRE Graph**。欧洲开放学术图，定期在 Zenodo 发全量 dump（CC BY 4.0）：2026-06 的 v11.1.1 全量 378.4GB，其中 `product_Cites_*.tar` 就是引用边文件（4 个分片各 ~10.8GB 压缩），`publication_*.tar` 约 150GB 元数据，格式 = tar 包 gz 包 JSONL[^openaire-graph][^openaire-docs]。这是一个被低估的批量引用源——规模接近 OpenAlex 量级，license 宽松。REST 搜索 API（api.openaire.eu/search）实测可用但只覆盖元数据面。

**DBLP**。纯书目（作者/标题/venue），无引用边——这是其设计使然，不是缺口。顺带一提其站点现在挂了 Anubis 反爬，curl 拿到的是人机验证页（实测）。

**DOAJ**。期刊/文章元数据，无引用数据（其定位即 OA 期刊目录，非引文库）。

## 边际价值排序（arXiv 尺度发现层视角）

1. **INSPIRE-HEP**：**值得接**。hep/astro 域内引用边质量全场最高（人工审定 + curated_relation 标记），老 arXiv ID 映射天然解决，CC0，API 形态清晰；还是 arXiv 引用抽取管线的开源参考（hepcrawl + refextract）。覆盖缺口在 CS。
2. **ADS**：**抄语义不取数**。二阶算子（citations/references/similar/trending/useful/reviews）是发现层 API 设计的成熟抽象；token+日额决定了它不适合做数据源。
3. **OpenAIRE Graph**：**值得作为批量补充源**。CC BY 4.0 全量 dump 含 40GB+ 压缩引用边，可作 OpenAlex/S2/COCI 之外的第四源交叉验证与补边。
4. **iCite/Europe PMC**：**生物域外意义有限**（PubMed 内闭环，arXiv 不覆盖）；但 NIH-OCC 的「Crossref + 全文抽取」构建配方与 RCR 归一化指标值得借鉴。
5. **zbMATH Open**：数学域内可用补充（document_id 边），优先级低。
6. **DBLP / DOAJ**：无引用边，仅作作者/venue 元数据补全。

## 对自建完整形态发现层的启示

- **ID 归一化是第一公理**：INSPIRE 的 recid↔arxiv_eprints 映射（含 1991 年起的全部老 ID）证明老 arXiv ID 的解析不是难题，且 INSPIRE 数据可直接当作映射对照表用。自建层的 ID 体系应以外部 ID（arXiv/DOI/PMID/recid）为主键外键并存。
- **API 设计直接借鉴 ADS 算子族**：citations/references 是基操；useful/reviews 这两个聚合算子本质是「按引用频次排序的被引并集」与「按共被引次数排序的引用方集合」，实现成本低（一次 join + group by）但产品价值高（一键出综述与方法论文）；similar/trending 提示文本相似与行为信号早晚要并入排序。
- **引用边质量有梯度，应保留 provenance**：INSPIRE 的 `curated_relation` 标记提示——机器抽取的边与人工审定的边该区别对待；自建时给每条边标来源（Crossref/全文抽取/人工）便于后续加权与纠错。
- **全文抽取是补边的必要手段**：NIH-OCC 明确靠 ML 管线从 OA 全文补 Crossref 没有的边（DOI 前文献尤甚）；对 LaTeX 源可用的语料，从源文件抽边比从 PDF 抽的精度上限更高——INSPIRE/refextract 与 NIH-OCC 的 ML 管线是两种已验证路线。
- **领域库的共性短板在 CS**：INSPIRE/ADS/zbMATH/PubMed 都不覆盖计算机科学，arXiv CS（cs.AI/cs.LG/cs.CL）的引用边只能靠 OpenAlex/S2/COCI 大图或自抽。
- **归一化指标现成可抄**：RCR（NIH）与 ADS 的 citation_count 排序之外，领域归一化引用影响力（fcr/ecr 字段族）是「引用数≠质量」问题的成熟解法。

### 参考文献

[^inspire-api-doc]: INSPIRE-HEP. REST API documentation. GitHub. [inspirehep/rest-api-doc](https://github.com/inspirehep/rest-api-doc)
[^inspire-harvest]: INSPIRE-HEP. Harvesting documentation. ReadTheDocs. [inspirehep.readthedocs.io/en/latest/harvesting.html](https://inspirehep.readthedocs.io/en/latest/harvesting.html)
[^refextract]: INSPIRE-HEP. refextract — library for extracting references used in scholarly communication. GitHub. [inspirehep/refextract](https://github.com/inspirehep/refextract)
[^inspire-mcp]: karuboniru. inspire-mcp — MCP server for the public INSPIRE REST API. GitHub. [karuboniru/inspire-mcp](https://github.com/karuboniru/inspire-mcp)
[^ads-api]: ADS. adsabs-dev-api README — token, rate limits. GitHub. [adsabs/adsabs-dev-api](https://github.com/adsabs/adsabs-dev-api/blob/master/README.md)
[^ads-handout]: ADS. ADS API handout. [ads.harvard.edu/handouts/ADS_API_handout.pdf](https://ads.harvard.edu/handouts/ADS_API_handout.pdf)
[^ads-second-order]: ADS. Second-Order Query Operators. [adsabs.github.io/help/search/second-order](https://adsabs.github.io/help/search/second-order)
[^ads-citref]: ADS. Citations and Reference Operators. [adsabs.github.io/help/search/citations-and-references](https://adsabs.github.io/help/search/citations-and-references)
[^icite-api]: NIH Office of Portfolio Analysis. iCite API documentation. [icite.od.nih.gov/api](https://icite.od.nih.gov/api)
[^icite-fields]: NIH OPA. iCite User Guide — Open Citations module. [icite.od.nih.gov/user_guide](https://icite.od.nih.gov/user_guide?page_id=ug_data)
[^nih-occ]: Hutchins BI et al. The NIH Open Citation Collection: A public access, broad coverage resource. PLOS Biology 2019. [journals.plos.org/plosbiology/article?id=10.1371/journal.pbio.3000385](https://journals.plos.org/plosbiology/article?id=10.1371%2Fjournal.pbio.3000385)
[^epmc-rest]: Europe PMC. RESTful Web Service reference. [europepmc.org/RestfulWebService](https://europepmc.org/RestfulWebService)
[^epmc-dev]: Europe PMC. Developers — bulk download protocols. [europepmc.org/developers](https://europepmc.org/developers)
[^zbmath]: zbMATH Open. api.zbmath.org/v1 REST API（实测响应）. [api.zbmath.org](https://api.zbmath.org/v1/)
[^openaire-graph]: OpenAIRE. OpenAIRE Graph Dataset (v11.1.1). Zenodo 2026. [zenodo.org/records/20428976](https://zenodo.org/records/20428976)
[^openaire-docs]: OpenAIRE. Guide to the Graph Datasets — bulk access. [graph.openaire.eu/docs/bulk-access/](https://graph.openaire.eu/docs/bulk-access/)

## 探针产物

`tmp/citation-survey/domain/` 下：`inspire_alt.json`（hep-th/0301120 搜索）、`inspire_rec.json`（recid 611845 完整记录含 references）、`inspire_citedby.json`（refersto 查询结果）、`inspire_astro.json`（astro-ph/9901001）、`epmc_citations.json`/`epmc_refs.json`/`epmc_refs2.json`（Europe PMC 双向端点）、`icite.json`（iCite 双 PMID 返回）、`elink.json`（NLM citedin）、`zbmath2.json`（zbMATH 搜索含 references）、`openaire.json`（OpenAIRE 搜索）、`dblp.json`（Anubis 反爬页存证）、`inspire_headers.txt`（速率头）。
