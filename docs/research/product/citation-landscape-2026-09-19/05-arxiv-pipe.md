# arXiv 数据渠道与引用边抽取管线调研

围绕「基于引用数与引用图谱的论文发现」生态，本 lane 回答一个底层问题：**要自建全 arXiv 引用图，原始数据从哪来、引用边怎么抽、现成管线谁做得好**。结论是：arXiv 官方渠道给全量元数据与全文（PDF/源码）但**不含引用边**；引用边必须从全文抽取，而 LaTeX 源侧抽取（unarXive/S2ORC 已验证「near-perfect」）在精度上碾压 PDF 侧 GROBID 管线（~0.87 F1），且 unarXive 已把 1.9M 篇全 arXiv 的成品数据开放下载。

## arXiv 官方数据渠道

arXiv 提供五个访问面，分工明确：OAI-PMH 做全量元数据同步、export API 做实时查询、Kaggle/GCS 做免费批量、S3 requester-pays 做全量镜像、RSS 做当日新更[^bulldata]。

### OAI-PMH（实测）

端点已从 `export.arxiv.org/oai2` 迁移至 `https://oaipmh.arxiv.org/oai`（301 永久重定向，实测 2026-09-19）。`Identify` 显示：earliestDatestamp=2005-09-16、`deletedRecord=persistent`、日期粒度 `YYYY-MM-DD`、明确声明「Full-content harvesting not permitted」——**只有元数据，日更**。`ListMetadataFormats` 返回四个 prefix：`oai_dc`、`arXiv`、`arXivOld`、`arXivRaw`。实测 `arXiv` 格式单条记录（1706.03762）字段为 id/created/updated/authors(keyname+forenames)/title/categories/comments/license/abstract——**无 journal-ref/doi/report-no，更无参考文献**；`arXivRaw` 格式按官方文档包含最完整字段（journal-ref、doi、report-no、versions 等），本次探测时该端点出现 TLS 抖动未能二次实测，但格式定义见官方 XSD[^oaipmh]。

### export.arxiv.org API（实测 + 文档）

实时 Atom XML 查询接口，`GET/POST /api/query`，参数 `search_query`/`id_list`/`start`/`max_results`。文档规定：`max_results` 上限 30000、单次切片 ≤2000、建议连续调用间隔 ≥3 秒、结果每日刷新故同查询一天一次即可；大批量应走 OAI-PMH[^apimanual]。实测 `id_list=1706.03762` 返回 2965 字节 Atom 记录（含 summary/authors/category/links，同样无引用数据）。

### Kaggle + GCS 免费桶

康奈尔在 Kaggle 托管 `Cornell-University/arxiv` 数据集：`arxiv-metadata-oai-snapshot.json` JSONL 全量元数据（id/submitter/authors/title/comments/journal-ref/doi/report-no/categories/license/abstract/versions/update_date/authors_parsed），社区镜像记录为 2025-05-14 时点 2,710,806 篇、约 4.58GB，**周更**[^kaggle]。PDF 全文经 Google Cloud 公共桶 `gs://arxiv-dataset` 免费分发（Kaggle 项目配套，早期称 1.1TB）。实测（2026-09-19）该桶仍可匿名列举：`arxiv-dataset_list-of-files.txt.gz` 索引 + `arxiv/{category}/pdf/{yymm}/{id}v{n}.pdf` 逐篇 PDF 布局（如 `arxiv/acc-phys/pdf/9411/9411001v1.pdf`）[^gcs]。

### S3 requester-pays 批量桶

`arxiv` 桶（us-east-1）内 `pdf/arXiv_pdf_{yymm}_{nnn}.tar` 与 `src/arXiv_src_{yymm}_{nnn}.tar`，各 ~500MB tar 分片、按月切片，配 manifest XML（含 checksum）；PDF 全集约 2.7TB、LaTeX 源约 2.9TB（2023-03 口径），合计约 9.2TB（2025-04 口径），月更、月增 ~100GB[^s3]。下载方付 AWS 出口流量费（量级：源集 ~2.9TB × ~$0.09/GB ≈ $260 量级，未验证实测账单）。**`src/` 桶是引用图的关键**——它给的是 LaTeX 源而非 PDF，直接决定下游走哪条抽取管线。

### 爬取政策与许可约束

官方要求程序化抓取走 `export.arxiv.org` 镜像站，建议速率「burst 4 req/s + sleep 1s」，明令不要程序化下载全集（全量请走 S3 桶）[^bulldata]。许可上大多数论文是 arXiv perpetual non-exclusive distribution license——**不能二次分发全文，派生索引/工具必须回链 arXiv**；license 字段逐篇在元数据可查。

## 引用边抽取管线对比

### PDF 侧：GROBID 及横评

GROBID 是事实标准的 PDF→TEI/XML 抽取器（CRF/深度学习序列标注）：官方 benchmark 给出参考文献抽取+解析 PMC 集 0.87 F1（1943 篇 PDF、90,125 条参考文献）、bioRxiv 集 ~0.90（Deep Learning citation 模型）；孤立参考文献解析 >0.90 instance-level / 0.95 field-level；经 biblio-glutton 或 Crossref 归一化后 DOI/PMID 解析 >0.95 F1；引文上下文（in-text callout↔bibliography 条目对齐）0.76–0.91 F1 视评测集而定[^grobid]。横向评测给出的相对位次：10 款开源解析器对比中 GROBID out-of-box F1 0.89 居首（CERMINE 0.83、ParsCit 0.75），按任务数据重训后 GROBID/CERMINE 均 0.92、ParsCit 0.87，meta-learning 集成（ParsRec）达 0.909[^parsereval]；另一项 27 学科 56 篇 PDF 评测中 AnyStyle 总分第一、CERMINE 次之[^oc-eval]；2024 年「Comparing Free Reference Extraction Pipelines」结论是 GROBID 与 AnyStyle 最好、建议组合使用[^freepipe]。**启示：PDF 路线单工具 ~0.87–0.90 F1 是天花板，字段级错误与漏抽不可避免。**

### LaTeX 源侧：S2ORC 与 unarXive

S2ORC（Lo et al., ACL 2020）是迄今最大规模的引用图谱管线实证：从 ~200M 论文簇出发，PDF 路径用 ScienceParse 抽标题作者（评测称其 header 抽取优于 GROBID）+ GROBID v0.5.5 抽正文/引文，再正则后处理修 bracket-range 展开与上标误检；**LaTeX 路径把源码转 XML 再抽结构（tex2json，思路源自 Saier & Färber），论文明示「直接访问源码，引文跨度、参考文献、图表 caption、节标题、公式检测精度 near-perfect」，共处理 1.5M 篇 arXiv LaTeX**；书目条目→论文簇的实体链接用标题归一化 + 字符 3-gram 的 Jaccard/containment 调和平均打分；最终 81.1M 篇、其中 8.1M OA 全文（2020 时点）[^s2orc]。配套工具 `allenai/s2orc-doc2json` 开源（grobid2json + tex2json）[^doc2json]。值得注意的是 S2ORC 发现 LaTeX 侧**元数据**质量反而比 PDF 差（作者自定义宏花样多），故聚簇仍用 PDF/出版商元数据——抽取分工值得借鉴。

unarXive（Saier & Färber, Scientometrics 2020；Saier, Krause & Färber, JCDL 2023）是「全 arXiv LaTeX→引用图」的直接先例：LaTeXML 把 LaTeX 源转 XML 后抽结构化全文。2022 版含 **1.9M 篇结构化全文、63M 条参考文献（28M 链接到 OpenAlex）、134M 个 in-text 引用标记（65M 已链接）、9M 图注、742M 条数学式 LaTeX 保留**，横跨 32 年[^unarxiv22]；2020 版为 1M+ 篇、29.2M 引用上下文、链 MAG[^unarxiv20]。代码开源（GitHub IllDepence/unarXive），Zenodo 提供 permissively-licensed 子集公开下载、full 版受限申请，HuggingFace 上有现成 citation-recommendation 训练集[^unxgit]。

两条 LaTeX 管线共同验证了关键判断：**对 arXiv 这种 ~90%+ 论文带 LaTeX 源的语料，源侧抽取在参考文献/引文上下文两端的精度都接近无损**，碾压 PDF-GROBID 的 0.87 天花板；且省掉 DOI 归一化的模糊匹配损耗（`\bibitem`/`.bbl` 里常有 arXiv ID/DOI 直连锚点）。

### 补充：arXiv 官方 HTML 化

arXiv 自 2023 年底起用 LaTeXML 为全部新投稿生成 HTML 版（`arxiv.org/html/{id}`），相当于官方替全网做了一遍 LaTeX→XML——对下游抽取器是免费中间层，但引用锚点语义仍需自行解析[^bulldata]。

## 其他全文/书目源

Unpaywall（api.unpaywall.org/v2/{doi}?email=）是 OA 状态与全文定位的事实标准，S2ORC 即用它判 OA；免费、需 email 参数、限额宽松（社区口径 ~100k/日），另有定期快照 dump。本次调研两次探测均连接超时，**直接实测未验证**[^unpaywall]。

CORE API v3（api.core.ac.uk）实测可达：token 计费制，未注册 100 tokens/日、注册个人 1,000/日、学术 5,000/日，约 5 请求/10 秒；主打全球最大 OA 聚合（数亿条 work/full-text 声明），对引用图的用途主要是全文定位而非引用边[^core]。

fatcat.wiki（Internet Archive 学术目录）的 **refcat** 是被低估的引用图资产：2021 夏发布，JSON Lines、CC0、archive.org 公开下载，宣称含数十亿条 paper↔paper 引用及 paper→书/网页、Wikipedia→论文的边；每条边带 `match_provenance` 溯源字段，最大来源是 Crossref，其余来自 PubMed/arXiv/Wikipedia 抽取与 GROBID PDF 解析；整库 pg_dump ~100GB。 caveat：项目活跃度自 2021–2022 后明显走低，Elasticsearch 面 schema 未稳定[^refcat]。

Wikidata `P2860 cites work` 属性总用量 ~3.14 亿次（scholarly-article 子图内 ~2.63 亿条引用三元组），SPARQL（WDQS）可查、Scholia 前端消费；但分布严重不均（PLOS 过采样、IEEE 稀薄），arXiv ID 仅 ~104 万条——**只能当补充边源，撑不起全 arXiv 覆盖**[^wdstats][^scholia]。

## 对自建引用图的启示

从零建全 arXiv 引用图的最优组合已经清晰：

1. **元数据底座**：Kaggle/OAI-PMH 拿全量元数据（周更/日更），免费且零门槛；约 271 万篇（2025 中口径）。
2. **全文获取**：LaTeX 源走 S3 `src/` requester-pays（~2.9TB，几百美元级一次性成本）或按需经 export.arxiv.org 限速拉取；PDF 走 GCS 免费桶。
3. **抽取策略**：~90% 带源论文走 LaTeX 管线（复用 unarXive 或直接解析 `.bbl/.bib/\bibitem`——后者比 LaTeXML 全转换更轻），PDF-only 残量走 GROBID；优先保证 in-text callout 与 bibliography 的双向链接。
4. **实体链接**：S2ORC 式标题 3-gram 模糊匹配 + DOI/arXiv ID 直连锚点，目标图 ID 对齐 OpenAlex/S2。
5. **能白嫖的成品**：unarXive 已把 1.9M 篇全 arXiv 的引用网络做好并开放（permissively-licensed 子集直下）——**先拿它冷启动、再增量自抽新论文，是最省事的路径**；refcat 可作跨库边补充。
6. **许可红线**：全文不可再分发，引用边（抽取产物）与元数据可自由发布，这是所有下游服务的合规形态。

## 探针产物

- `tmp/citation-survey/arxiv-pipe/oai-identify.xml` — OAI-PMH Identify（新端点实测）
- `tmp/citation-survey/arxiv-pipe/oai-formats.xml` — ListMetadataFormats 响应
- `tmp/citation-survey/arxiv-pipe/oai-sample.xml` — arXiv 格式单记录（1706.03762）
- `tmp/citation-survey/arxiv-pipe/api-sample.xml` — export API Atom 记录
- `tmp/citation-survey/arxiv-pipe/gcs-list.json` — GCS 桶列举响应（前缀探测）
- `tmp/citation-survey/arxiv-pipe/core-api.json`、`core-search.json` — CORE v3 可达性实测
- `tmp/citation-survey/arxiv-pipe/unpaywall-sample.json` — Unpaywall 探测（两次超时，未验证）

### 参考文献

[^bulldata]: arXiv. Bulk Data Access. arXiv Docs. [github.com/arXiv/arxiv-docs](https://github.com/arXiv/arxiv-docs/blob/ca6e62d23ab863cef0031504d0a099c54065a7ff/help/bulk_data.md)
[^oaipmh]: arXiv. OAI-PMH interface. 实测 https://oaipmh.arxiv.org/oai（2026-09-19）.
[^apimanual]: arXiv. API User's Manual. [info.arxiv.org/help/api/user-manual.html](https://info.arxiv.org/help/api/user-manual.html)
[^kaggle]: Cornell University. arXiv Dataset. [kaggle.com/datasets/Cornell-University/arxiv](https://www.kaggle.com/datasets/Cornell-University/arxiv)（镜像见 [huggingface.co/datasets/jackkuo/arXiv-metadata-oai-snapshot](https://huggingface.co/datasets/jackkuo/arXiv-metadata-oai-snapshot)）
[^gcs]: arXiv/Google. gs://arxiv-dataset. 实测列举（2026-09-19）.
[^s3]: arXiv. Bulk Data Access on S3. [github.com/arXiv/arxiv-docs bulk_data_s3.md](https://github.com/arXiv/arxiv-docs/blob/develop/source/help/bulk_data_s3.md)
[^grobid]: GROBID Documentation. [grobid.readthedocs.io](https://grobid.readthedocs.io/en/latest/Introduction/) 及 [PMC benchmark](https://grobid.readthedocs.io/en/latest/benchmarks/Benchmarking-pmc/)
[^parsereval]: Tkaczyk et al. Evaluation and Comparison of Open Source Bibliographic Reference Parsers. [dblp corr1802](https://dblp.uni-trier.de/db/journals/corr/corr1802.html); ParsRec meta-learning. [arxiv.org/pdf/1811.10369](https://arxiv.org/pdf/1811.10369)
[^oc-eval]: Structured references from PDF articles: assessing the tools. [doi.org/10.48550/arxiv.2205.14677](https://doi.org/10.48550/arxiv.2205.14677)
[^freepipe]: Comparing Free Reference Extraction Pipelines. [doi.org/10.5281/zenodo.10582213](https://doi.org/10.5281/zenodo.10582213)
[^s2orc]: Lo et al. S2ORC: The Semantic Scholar Open Research Corpus. ACL 2020. [aclanthology.org/2020.acl-main.447](https://aclanthology.org/2020.acl-main.447.pdf)
[^doc2json]: allenai/s2orc-doc2json. [github.com/allenai/s2orc-doc2json](https://github.com/allenai/s2orc-doc2json)
[^unarxiv22]: Saier, Krause & Färber. unarXive 2022. JCDL 2023. [doi.org/10.1109/JCDL57899.2023.00020](https://doi.org/10.1109/JCDL57899.2023.00020)
[^unarxiv20]: Saier & Färber. unarXive. Scientometrics 125(3), 2020. [doi.org/10.1007/s11192-020-03382-z](https://doi.org/10.1007/s11192-020-03382-z)
[^unxgit]: IllDepence/unarXive. [github.com/IllDepence/unarXive](https://github.com/IllDepence/unarXive); [zenodo.org/records/7752754](https://zenodo.org/records/7752754)
[^unpaywall]: Unpaywall (OurResearch). api.unpaywall.org（探测超时，未实测）.
[^core]: CORE API. [core.ac.uk/services/api](https://core.ac.uk/services/api/)（v3 可达性实测 2026-09-19）.
[^refcat]: The Fatcat Guide — Reference Graph (refcat). [guide.fatcat.wiki/reference_graph.html](https://guide.fatcat.wiki/reference_graph.html)
[^wdstats]: Wikidata. Property P2860 usage stats. [wikidata.org Property:P2860](https://wikidata.org/wiki/Property:P2860); [Wikidata Scholarly Articles Subgraph Analysis](https://wikitech.wikimedia.org/wiki/User:AKhatun/Wikidata_Scholarly_Articles_Subgraph_Analysis)
[^scholia]: Nielsen et al. Scholia, Scientometrics and Wikidata. [imm7010.pdf](https://www2.imm.dtu.dk/pubdb/edoc/imm7010.pdf)
