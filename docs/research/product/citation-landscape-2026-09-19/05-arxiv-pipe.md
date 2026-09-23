# Lane 05：arXiv 数据渠道与引用边抽取管线

> **结论**：arXiv 官方渠道给全量元数据与全文（PDF/源码）但不含引用边；边必须从全文抽取，LaTeX 源侧抽取（S2ORC/unarXive 实证 near-perfect）在精度上碾压 PDF 侧 GROBID（~0.87–0.90 F1）；unarXive 已把 1.9M 篇全 arXiv 引用网络开放下载，是现成冷启动资产。
> **状态**：时点证据（2026-09-19 口径）
> **日期**：2026-09-19

## arXiv 五个官方渠道

分工明确：OAI-PMH 做全量元数据同步、export API 做实时查询、Kaggle/GCS 做免费批量、S3 requester-pays 做全量镜像、RSS 做当日新更[^bulldata]。

- **OAI-PMH**：端点已迁至 `oaipmh.arxiv.org/oai`（301 重定向，实测）。earliestDatestamp 2005-09-16、`deletedRecord=persistent`、声明「Full-content harvesting not permitted」——只有元数据日更。`arXiv` 格式无 journal-ref/doi/references；`arXivRaw` 格式字段最全[^oaipmh]。
- **export API**：实时 Atom XML（`/api/query`），`max_results` ≤30000、单片 ≤2000、建议间隔 ≥3s[^apimanual]。
- **Kaggle + GCS**：`Cornell-University/arxiv` 元数据快照周更（~271 万篇 ~4.58GB）；`gs://arxiv-dataset` 免费桶匿名可列举，逐篇 PDF[^kaggle][^gcs]。
- **S3 requester-pays**：`arxiv` 桶 `pdf/` 与 `src/` tar 分片按月切片；PDF ~2.7TB、**LaTeX 源 ~2.9TB**（分量数字为 2023-03 口径；全桶文件 ~9.2TB 系 2025-04 口径，月增 ~100GB），下载方付流量费（源集约 $260 量级）[^s3]。`src/` 桶是引用图的关键——给的是 LaTeX 源而非 PDF。
- **许可红线**：大多数论文是 arXiv perpetual non-exclusive license——**不能二次分发全文，派生索引/工具必须回链 arXiv**；抽取出的引用边与元数据可自由发布[^bulldata]。程序化抓取限速 burst 4 req/s + sleep 1s，全量走 S3 桶。

## 引用边抽取管线对比

**PDF 侧天花板**：GROBID（事实标准 PDF→TEI 抽取器）官方 benchmark：参考文献抽取+解析 PMC 集 0.87 F1、bioRxiv ~0.90；孤立参考文献解析 >0.90 instance-level；引文上下文对齐 0.76–0.91 F1 视评测集[^grobid]。横评中 GROBID out-of-box 居首（0.89），重训后 0.92；组合使用 GROBID+AnyStyle 最优[^parsereval][^freepipe]。**PDF 路线单工具 ~0.87–0.90 F1 是天花板，字段级错误与漏抽不可避免。**

**LaTeX 源侧**：S2ORC（ACL 2020）论文明示「直接访问源码，引文跨度、参考文献、图表 caption、节标题、公式检测精度 near-perfect」，共处理 1.5M 篇 arXiv LaTeX；配套 `s2orc-doc2json` 开源[^s2orc][^doc2json]。unarXive（Saier & Färber）是直接先例：LaTeXML 转 XML 抽结构化全文，2022 版含 **1.9M 篇结构化全文、63M 条参考文献（28M 已链 OpenAlex）、134M 个 in-text 引用标记（65M 已链接）**、742M 条数学式 LaTeX 保留，横跨 32 年；Zenodo permissively-licensed 子集公开直下、full 版受限申请，HF 有现成 citation-recommendation 训练集[^unarxiv22][^unxgit]。值得注意的反例：S2ORC 发现 LaTeX 侧**元数据**质量反而比 PDF 差（自定义宏花样多），故聚簇仍用 PDF/出版商元数据——抽取分工值得借鉴。

补充：arXiv 官方自 2023 年底起用 LaTeXML 为全部新投稿生成 HTML（`arxiv.org/html/{id}`），是免费中间层但引用锚点语义仍需自解析[^bulldata]。

## 其他全文/书目源

Unpaywall 是 OA 状态与全文定位的事实标准（S2ORC 即用它判 OA），免费需 email 参数[^unpaywall]。CORE API v3 token 计费（注册 1,000/日），用途主要是全文定位而非引用边[^core]。fatcat **refcat** 是被低估的引用图资产：JSON Lines、CC0、数十亿条边带 `match_provenance` 溯源字段，最大来源 Crossref；caveat 是项目活跃度自 2021–2022 后走低[^refcat]。Wikidata P2860 ~3.14 亿声明但 arXiv 覆盖仅 ~104 万——只能当补充边源[^wdstats]。

## 结论

从零建全 arXiv 引用图的最优组合：Kaggle/OAI-PMH 拿全量元数据；LaTeX 源走 S3 `src/` requester-pays（~$260 一次性）或 export API 限速按需；~90% 带源论文走 LaTeX 管线（直接解析 `.bbl/.bib/\bibitem` 比 LaTeXML 全转换更轻），PDF-only 残量走 GROBID；实体链接用 S2ORC 式标题 3-gram + DOI/arXiv ID 直连锚点，对齐 OpenAlex/S2；**先拿 unarXive permissive 子集冷启动、再增量自抽新论文是最省事路径**；许可红线=全文不可再分发、抽取边可自由发布。

### 参考文献

[^bulldata]: arXiv. Bulk Data Access. arXiv Docs. [github.com/arXiv/arxiv-docs](https://github.com/arXiv/arxiv-docs/blob/ca6e62d23ab863cef0031504d0a099c54065a7ff/help/bulk_data.md)

[^oaipmh]: arXiv. OAI-PMH interface（oaipmh.arxiv.org/oai，2026-09-19 实测）.

[^apimanual]: arXiv. API User's Manual. [info.arxiv.org/help/api/user-manual.html](https://info.arxiv.org/help/api/user-manual.html)

[^kaggle]: Cornell University. arXiv Dataset. [kaggle.com/datasets/Cornell-University/arxiv](https://www.kaggle.com/datasets/Cornell-University/arxiv)

[^gcs]: arXiv/Google. gs://arxiv-dataset（2026-09-19 实测匿名列举）.

[^s3]: arXiv. Bulk Data Access on S3. [github.com/arXiv/arxiv-docs bulk_data_s3.md](https://github.com/arXiv/arxiv-docs/blob/develop/source/help/bulk_data_s3.md)

[^grobid]: GROBID Documentation. [grobid.readthedocs.io](https://grobid.readthedocs.io/en/latest/Introduction/)

[^parsereval]: Tkaczyk et al. Evaluation and Comparison of Open Source Bibliographic Reference Parsers. [arxiv.org/pdf/1811.10369](https://arxiv.org/pdf/1811.10369)

[^freepipe]: Comparing Free Reference Extraction Pipelines. [doi.org/10.5281/zenodo.10582213](https://doi.org/10.5281/zenodo.10582213)

[^s2orc]: Lo et al. S2ORC: The Semantic Scholar Open Research Corpus. ACL 2020. [aclanthology.org/2020.acl-main.447](https://aclanthology.org/2020.acl-main.447.pdf)

[^doc2json]: allenai/s2orc-doc2json. [github.com/allenai/s2orc-doc2json](https://github.com/allenai/s2orc-doc2json)

[^unarxiv22]: Saier, Krause & Färber. unarXive 2022. JCDL 2023. [doi.org/10.1109/JCDL57899.2023.00020](https://doi.org/10.1109/JCDL57899.2023.00020)

[^unxgit]: IllDepence/unarXive. [github.com/IllDepence/unarXive](https://github.com/IllDepence/unarXive); [zenodo.org/records/7752754](https://zenodo.org/records/7752754)

[^unpaywall]: Unpaywall (OurResearch). api.unpaywall.org.

[^core]: CORE API. [core.ac.uk/services/api](https://core.ac.uk/services/api/)

[^refcat]: The Fatcat Guide — Reference Graph (refcat). [guide.fatcat.wiki/reference_graph.html](https://guide.fatcat.wiki/reference_graph.html)

[^wdstats]: Wikidata. Property P2860 usage stats. [wikidata.org Property:P2860](https://wikidata.org/wiki/Property:P2860)
