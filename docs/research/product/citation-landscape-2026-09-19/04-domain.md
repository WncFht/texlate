# Lane 04：领域库（INSPIRE-HEP / ADS / PubMed 系 / zbMATH / OpenAIRE / DBLP）

> **结论**：INSPIRE-HEP 是「在 arXiv 上建引用图」的现成参考实现且数据 CC0 可取；ADS 的二阶算子族是发现层 API 设计的教科书（抄语义不取数）；领域库共性短板是都不覆盖 CS。
> **状态**：时点证据（2026-09-19 口径）
> **日期**：2026-09-19

## INSPIRE-HEP：高能物理引用网的完全体

CERN/SLAC/DESY/Fermilab/IHEP 等联合运营的高能物理文献库（前身 SPIRES，1974 年起建引用库）。对本调研最有价值的一点：**它是「在 arXiv 上建引用图谱」的现成参考实现**——采集管线 hepcrawl 定时爬 arXiv OAI-PMH，再用自家开源 refextract 从 PDF/LaTeX 抽参考文献并消歧成库内 record[^inspire-harvest][^refextract]。

API 免鉴权只读（`inspirehep.net/api`）：**老 arXiv ID 直接可查**（`q=arxiv_eprints.value:hep-th/0301120` 实测命中）；引用边双向可取——记录内 `metadata.references` 每条含 `record.$ref`（已消歧库内链接）+ `reference.arxiv_eprint` + **`curated_relation` 人工审定标记**，反向用 `refersto:recid:N` 搜索语法。排序 `mostcited`/`mostrecent`，SPIRES 遗留 `topcite 1000+` 语法仍可用；size 上限 1000、结果窗口上限 10000；限流 15 req/5s 超限返 429+`x-retry-in`[^inspire-api-doc]。另有 `POST /api/bibliography-generator`——传含 `\cite{}` 的 TeX 文件服务端生成参考文献表（refextract 消歧能力的直接外露）。License 大部分 CC0。域内覆盖近乎完全，局限是不覆盖 CS。

## NASA ADS：二阶算子语义的教科书

ADS 的核心价值不在数据（要 token、有日额），而在它把「引用图谱发现」抽象成一组可组合的二阶查询算子[^ads-second-order][^ads-citref]：

| 算子 | 语义 | 图谱操作 |
| --- | --- | --- |
| `citations(q)` / `references(q)` | 引用方 / 被引方集合 | 入边 / 出边遍历 |
| `useful(q)` | 合并结果集的参考文献表按被引频次排 | **文献耦合聚合形态——找领域方法/工具论文** |
| `reviews(q)` | 找大量引用结果集的论文 | **共被引聚合形态——找综述** |
| `similar(q)` | 摘要拼大文档做文本相似 | 文本相似（非图谱） |
| `trending(q)` | 读这些论文的人还在读什么 | 协同阅读（行为信号，ADS 独有需使用日志） |
| `topn(n,q,sort)` | 结果集内按序取前 n | 排序裁剪 |

算子可嵌套（`trending(topn(10, reviews("weak lensing")))`）、可与布尔查询组合。API 需免费 token，Solr 搜索 ~5000 次/日、`/search/bigquery`（POST bibcode 列表 ≤2000）~100 次/日[^ads-api]。

## PubMed 系：生物医学引用闭环

- **iCite**（NIH OPA）：免鉴权 REST `/api/pubs?pmids=`（≤1000 个/次），返回 `cited_by`/`references` 双向边 + `relative_citation_ratio`（RCR 领域归一化引用影响力）+ `nih_percentile` + 现成可视化坐标；figshare 有全量快照[^icite-api][^icite-fields]。
- **NIH-OCC**：iCite 背后的数据集——MedLine/PMC + Crossref + 自家 ML 从开放全文抽取合并，2019 年已有 4.2 亿+ PubMed↔PubMed 边；构建配方「Crossref 打底 + 全文 ML 抽取补齐 DOI 前时代」本身是范本[^nih-occ]。
- **Europe PMC**：免鉴权 REST ~10rps，`/{source}/{id}/citations` 与 `/references`（source 含 MED/PMC/PPR preprint），3300 万出版物、1940 万有 refs[^epmc-rest]。

## zbMATH / OpenAIRE / DBLP

**zbMATH Open** `api.zbmath.org/v1` 免鉴权：记录内嵌 `references[]` 带 `zbmath.document_id` 库内边——**边可用、边文本不可用**（相当多记录 doi/position/text 因许可冲突显示 unavailable）[^zbmath]。**OpenAIRE Graph** v11.1.1 全量 378.4GB（Zenodo，CC BY 4.0），`product_Cites_*.tar` 引用边 8 分片（7×~10.8GB + 1×~0.1GB，共 ~75.6GB）——被低估的批量引用源[^openaire-graph]。**DBLP** 纯书目无引用边（设计使然）；**DOAJ** 无引用数据。

## 可借鉴点

- **ID 归一化是第一公理**：INSPIRE 的 recid↔arxiv_eprints 映射（含 1991 年起全部老 ID）证明老 arXiv ID 解析不是难题，INSPIRE 数据可直接当映射对照表。
- **API 设计直接借鉴 ADS 算子族**：useful/reviews 两聚合算子实现成本低（一次 join + group by）但产品价值高（一键出综述与方法论文）。
- **边质量有梯度应保留 provenance**：`curated_relation` 提示机器抽取边与人工审定边该区别对待；自建时给每条边标来源便于加权与纠错。
- **归一化指标现成可抄**：RCR/fcr/ecr 字段族是「引用数≠质量」问题的成熟解法。

## 结论

边际价值排序（arXiv 尺度发现层视角）：INSPIRE 值得接（域内边质量最高 + arXiv 抽取管线开源参考）；ADS 抄语义不取数；OpenAIRE 值得作批量补充源；iCite/Europe PMC 生物域外意义有限但 NIH-OCC 配方与 RCR 指标可借鉴；zbMATH 低优先级补充；DBLP/DOAJ 仅作元数据补全。领域库共性短板在 CS——arXiv CS 的引用边只能靠 OpenAlex/S2/COCI 大图或自抽。

### 参考文献

[^inspire-api-doc]: INSPIRE-HEP. REST API documentation. GitHub. [inspirehep/rest-api-doc](https://github.com/inspirehep/rest-api-doc)
[^inspire-harvest]: INSPIRE-HEP. Harvesting documentation. [inspirehep.readthedocs.io/en/latest/harvesting.html](https://inspirehep.readthedocs.io/en/latest/harvesting.html)
[^refextract]: INSPIRE-HEP. refextract — library for extracting references used in scholarly communication. GitHub. [inspirehep/refextract](https://github.com/inspirehep/refextract)
[^ads-api]: ADS. adsabs-dev-api README — token, rate limits. GitHub. [adsabs/adsabs-dev-api](https://github.com/adsabs/adsabs-dev-api/blob/master/README.md)
[^ads-second-order]: ADS. Second-Order Query Operators. [adsabs.github.io/help/search/second-order](https://adsabs.github.io/help/search/second-order)
[^ads-citref]: ADS. Citations and Reference Operators. [adsabs.github.io/help/search/citations-and-references](https://adsabs.github.io/help/search/citations-and-references)
[^icite-api]: NIH Office of Portfolio Analysis. iCite API documentation. [icite.od.nih.gov/api](https://icite.od.nih.gov/api)
[^icite-fields]: NIH OPA. iCite User Guide — Open Citations module. [icite.od.nih.gov/user_guide](https://icite.od.nih.gov/user_guide?page_id=ug_data)
[^nih-occ]: Hutchins BI et al. The NIH Open Citation Collection. PLOS Biology 2019. [journals.plos.org](https://journals.plos.org/plosbiology/article?id=10.1371%2Fjournal.pbio.3000385)
[^epmc-rest]: Europe PMC. RESTful Web Service reference. [europepmc.org/RestfulWebService](https://europepmc.org/RestfulWebService)
[^zbmath]: zbMATH Open. api.zbmath.org/v1 REST API. [api.zbmath.org](https://api.zbmath.org/v1/)
[^openaire-graph]: OpenAIRE. OpenAIRE Graph Dataset (v11.1.1). Zenodo 2026. [zenodo.org/records/20428976](https://zenodo.org/records/20428976)
