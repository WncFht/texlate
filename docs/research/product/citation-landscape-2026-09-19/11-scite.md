# scite.ai 逆向调研

对 scite.ai 做了一轮「官方文档抓取 + OpenAPI 规格解析 + 开源仓库源码 + 论文全文 + SEC 并购文件」五路调研。结论先行：**scite 的护城河不是算法而是数据资产与出版商协议**——整条管线（GROBID→biblio-glutton→SciBERT）全部构建在开源组件之上，co-author 就是 GROBID/DeLFT 作者 Patrice Lopez（kermitt2）；有全文（尤其是 LaTeX 源）时这套管线完全可以复刻，且分类这一步在 LLM 时代成本骤降。

## 公司背景

scite 2018 年创立于纽约布鲁克林，创始人 Josh Nicholson（CEO，细胞生物学博士，2015 年曾在 FEBS J 发「15M 引用分析」论文）与 Yuri Lazebnik（PI，已故——未验证当前状态）；Ashish Uppala、Sean Rife 为核心成员。资金：NSF SBIR Phase I $224,559（2019，合同号 1913619）[^sbir]、NIH/NIDA SBIR Fast-Track（Phase I ≤$225k + Phase II ≤$1.5M，2019-10，奖号 1 R44 DA050155-01）[^nih]；机构股东含 ff Venture Capital（ff Graphite V）与 Cactus Communications（Editage 母公司）[^merger]。

**2023-11-24 被 Research Solutions（NASDAQ: RSSS）收购**：企业价值 $14.8M，约为年化订阅收入 $3.6M（截至 2023-10-31）的 4.11 倍；对价约 50% 现金 + 50% 股票（~$6.3M 现金 + ~273 万股）+ earnout（3.5×期末 ARR − $13.72M，下限 $1.07M，分 8 季支付）[^sec][^prn]。官方口径：被收购时已盈利。现与 Research Solutions 2023-07 收购的 ResoluteAI 证据数据集合并运营（Evidence API 即来自 Resolute）。

## 核心机制：Smart Citations 管线

技术细节全部来自他们自己的论文（QSS 2021，bioRxiv 全文已下载验证）[^qss]。管线四步（论文图 3）：

1. **全文获取**：双轨——开放获取走 PubMed Central + Unpaywall 全量收割（自有 `biblio-glutton-harvester` 开源件，多线程、可断点续传、S3 存储）；订阅内容走与出版商签的**全文索引协议**（论文时点 12+ 家：Wiley、BMJ、Karger、Sage、Europe PMC、Thieme、Cambridge UP、Rockefeller UP、IOP、Microbiology Society、Frontiers 等；现宣称 30+，含 2022 年加入的 AAAS/Science 家族）。更新频率从日更到月更不等。
2. **文内引注与文献条目识别**：PDF 走 **GROBID**（开源 PDF→TEI XML，论文实测 ~5 PDF/s @4 核）；出版商 JATS XML 走 **Pub2TEI** 归一化成同一 TEI 格式。CCC 博客披露全管线用了 **11 个 ML 模型**做抽取与匹配[^ccc]。
3. **文献条目→DOI 匹配**：**biblio-glutton**（GROBID 生态书目匹配服务，对 Crossref 全量做模糊匹配；公开 benchmark F=95.4/17k 条）。端到端引用上下文解析到 DOI 的比例：**PDF 源 ~70%，PMC JATS XML ~95%**——即 PDF 管线丢 ~30% 语句，XML 只丢 ~5%（论文 Limitations 节）。
4. **语句分类**：输入为「引注句 + 前后各一句」的上下文窗口；输出 supporting / disputing(UI 叫 contrasting) / mentioning 三类。训练数据：**~5 万条专家标注语句**（论文时点 working set 38,925 条 + holdout 9,708 条，CCC 口径 ~50k；双人盲标→调和，自研 doccano 部署「sciteano」；开放域 IAA 78.5%、生物医学 ~90%）。模型演进：BidGRU RNN → ELMo+ensemble（慢 20×）→ BERT 初试不佳 → **微调 SciBERT = 生产架构**。类别天然极不均衡（全库估计 92.6% mentioning / 6.5% supporting / 0.8% disputing），训练时对稀有类过采样、部署时在预测层调权重使**各类 precision 均 &gt;80%**；disputing F 从初版 20.5% 提到 58.97%（precision 85.19%）。手动选取「上下文窗口中的关键短语」使 disputing F 再 +8 个点。一个反直觉事实：**全部十几亿条语句的分类跑在单台 GTX 1080Ti 服务器上**——推理成本极低[^qss]。

外部独立评测有争议：Bakker 等 2023 在撤稿引用样本上测得 F 0–0.58（定义口径不同）；scite 方 2025 年发文反驳，认为测试集与训练定义不一致[^bakker][^reply]。取中立场：supporting/mentioning 大体可信，contrasting 稀有类精度高但召回有限。

## 数据资产与规模

| 时点 | 全文论文数 | 语句数 | 出处 |
| --- | --- | --- | --- |
| 2019-10 | 12M | 420M+ | NIH 获奖通稿[^nih] |
| 2021 论文 | 23–25M | 800–880M | [^qss] |
| 2022-02 | 29M | 980M | AAAS 合作通稿[^aaas] |
| 2025 | 38M+ | 1.4B | 自家排名论文[^sjp] |
| 现官方口径 | 32M+ 全文源 / 190M+ 出版物元数据 | 1.6B+ | [^data][^qa] |

注意两层数据的分野：**citation statement（带上下文+分类）只来自有全文的部分（~32–38M 篇）；更大的 citation 图（~190M 出版物的 source→target 引用对）来自 Crossref 参考文献列表与各方元数据**——「We have all citation information from these publishers but do not have all full text」[^qa]。编辑类通知（retracted/concern/erratum/correction/withdrawn）聚合 Crossref、PubMed、Retraction Watch 数据库 + 2022 年自建的元数据自动检测器（月度更新、数据免费开放）[^nature][^notices]。

## 产品面

- **Search**：布尔检索，25+ 过滤器（引文类型、撤稿/关注/更正标记、引注所在章节、MeSH、PubChem 物质、主题、机构等）；单次 limit 到 10,000；聚合 facet；自助 key 上看不到语句 snippet（企业版才有）[^docs]。
- **Scite Report**：每篇 DOI 一页报告——tally 分解 + 逐条语句（上下文、所在章节、分类置信度），可按类型/章节/来源类型过滤；用户可 flag 误判，两名独立专家复核后标 "Expert classified"[^qss]。
- **Reference Check**：传 PDF/DOCX 或 URL → 异步任务 → 逐条参考文献的风险报告（撤稿、被反驳等）。2020-11 上线时约 $1/篇，已有期刊（Acta Orthopaedica）集成进投稿流程[^nature]。
- **Assistant（2023 初上线）**：RAG + 自校验——prompt→判断是否要文献→生成检索策略→库内检索→「secret sauce」重排模型→带内联引用的答案→自我事实核查→返回；支持年份/主题/期刊过滤、答案长度、引用格式（IEEE/APA/MLA）、tables 结构化输出、rankBy（relevance/date/citations/supporting-citations/journal-rank）；当时用 GPT-3.5 16k 上下文+截断策略[^handbook][^yt]。
- **Collections + Dashboards**：DOI 列表或检索式建集，跟踪新 supporting/contrasting、撤稿告警；UI 可从 Zotero/Mendeley/CSV 导入；dashboard=集合报告（期刊/机构/资助者通用）。
- **Scite Journal Index (SJI)**：USI = supporting/(supporting+contrasting)（0–1）；SI = ln(引用数 × USI^指数)（2025 年排名论文 arXiv:2504.05206 给出全公式与期刊榜：Nature 6.31、Science 6.21）；实体需 ≥100 条 supporting+contrasting 才有指数；2y/5y/lifetime 三档[^sjp]。
- **Badge/Widget（开源）**：`&lt;div class="scite-badge" data-doi=…&gt;` + JS bundle 即嵌；Europe PMC、IUCr、Rockefeller UP、Biotechniques 等官网已嵌；ASAPbio 推动预印本侧部署[^badge]。CEO 访谈称 smart citation 已上线 **acs、pnas、wiley、apa、royal society、arxiv** 等页面[^bitsinbio]。
- **浏览器扩展（开源，`scite-extension`）**：Chrome/Firefox；在 Google Scholar、PubMed、出版商、arXiv 等页面正则扫 DOI 就地插 badge；非 DOI 条目走 `GET /search/match_reference?title=&amp;first_author=` 匹配；右键菜单可直跳 Assistant。
- **Zotero 插件（开源，867★）**：库内加 supporting/contrasting/mentioning/total/citing-publications 五列，免 key[^zotero]。
- **MCP server**：`https://api.scite.ai/mcp`，OAuth 2.1+PKCE+DCR 或 `mcp` scope API key；25 个工具（literature/evidence/collections 三组）+ 4 个预置工作流 prompt（literature-review、fact-check-claim、systematic-review-screen、verify-bibliography）；官方 ChatGPT 插件、Claude connector、Microsoft 365 Copilot 的 Article Galaxy connector[^mcp]。
- **Evidence 垂直线**（ResoluteAI 资产）：patents、clinical trials、grants、FDA 药品/510k/MAUDE/FAERS、MHRA——每库统一 search/schema/facets/{id} 四端点，独立 scope 单独售卖[^evidence]。

## API 面（OpenAPI 3.1 全量解析，67 端点）

基座 `https://api.scite.ai`；`Bearer` 认证两档：自助 API key（Pro 档控制台签发，2026-08-08 起自助；此前全要联系销售）与企业 `client_credentials`（2h 短期 token）。**免鉴权公共面**（文档明示 + 浏览器扩展源码实证调用，本机因 CloudFront 区域封锁未能连通实测）：`GET/POST /papers`、`GET/POST /tallies`（≤500 DOI/次）、`POST /tallies/cited-by-sections`、`GET /search/match_reference`。

| 族 | 端点 | 说明 |
| --- | --- | --- |
| 引用图 | `GET /api_partner/citations/citing/{doi}` `cited_by/{doi}` | 带 type/section 的语句级边；文档注「special access，contact sales」 |
| 引用对 | `GET /api_partner/references/references_to/{doi}` `references_from/{doi}` | source↔target DOI 纯对 |
| 推荐 | `GET /api_partner/recommend-papers/{doi}` | 相关论文 + tally + score；**算法未披露**（未验证，按产品形态推测为图+内容混合） |
| 检索 | `GET /api_partner/search` | 见上；商用需单独 license |
| 异步 | `POST /api_partner/assistant/poll`、`POST /reference_check` + `/tasks/{id}` | 轮询制；注意假 task_id 也回 200 PENDING |
| 作者/期刊 | `/authors/{slug}/papers | stats`、`/journal/{issn}/tallies | yearly-si`、`/issn-sji(-bulk)` | slug 为服务端生成 |
| 其他 | `/dashboards/*`、`/collections/*`（写需 write scope）、`/papers/resolve-pmid/{pmid}`、`/issn-editorial-notices` | |

限流：`RateLimit-*`（短窗）+ `X-RateLimit-*-Minute` 双组头，按端点/账户浮动；错误 `{detail}` + 401/403/404/422/429 语义清晰。

## 定价与商业模式

Free $0（公共端点+有限 UI）；Basic $20/月或 $144/年（250 MCP credits，无 REST key）；Pro $50/月或 $480/年（2500 MCP credits + 自助 API key）；Team $50/人/月；Enterprise 定制（SSO/OpenAthens、更高额度、全 scope）[^pricing]。B2B 侧收入：出版商 dashboard/SJI、Reference Check 投稿系统集成、数据 license、Evidence 数据集、徽章企业授权；被收购时 B2C+B2B 年化 $3.6M。

## 技术栈拼图（开源仓库佐证）

GitHub org `scitedotai`：`biblio-glutton`（Java/Scala 书目匹配）、`biblio-glutton-harvester`（Python Unpaywall 收割）、`delft`（Keras/TF 文本 DL 框架——分类器底座）、`arxiv-browse`（fork arXiv NG browse app）、`crossref`（全量 DOI 元数据抓取 notebook）、`mongo_docker_bootstrap`（MongoDB）、`scite-extension`/`scite-badge`/`scite-widget`/`example-journal-badge`（JS）、`scite-zotero-plugin`（TS）、`notices`（编辑通知数据）、`passport-mendeley`、`scite-vivo-integration`、`scite-mcp-skill`、`research-wikipedia`。前端 CloudFront 分发（本机访问被地域 403）[^gh]。

## 可复制性评估

scite 把「引用」从一对 ID 升级成「带上下文+意图分类+章节位置」的三元组，这是引用图谱产品里最厚的一档，但拆开看没有秘密：

- **管线全部是开源件**：GROBID（PDF→TEI）、Pub2TEI（XML 归一）、biblio-glutton（ref→DOI，对 Crossref 全量）、DeLFT（分类框架）、Unpaywall harvester——整条链路今天即可重建，连作者 Patrice Lopez 都是同一人。
- **真正的壁垒三个**：① 全文获取——30+ 出版商协议换来的订阅全文，自建者只能靠 OA 覆盖（Unpaywall ~30%+）或另辟蹊径（arXiv 全量 LaTeX 源其实更优：引注定位零误差、ref 匹配近乎 100%、章节结构原生）；② 标注数据——~5 万条双人专家标注是 2 年重投入，2026 年可用强 LLM 蒸馏低成本复刻（scite 当年是 2019 SciBERT 时代）；③ 数据资产规模——1.6B 语句的存量。
- **借鉴价值最高的设计**：tally 与 citingPublications 双口径分离（语句数 vs 出版物数）；section-level tally（引注出现在 Intro vs Discussion 权重不同——他们为此还专门做了 cited-by-sections 端点）；editorial notices 聚合（Crossref+PubMed+RetractionWatch+自建分类器四源）；「references（纯边）/citations（语句级）」命名分层；SJI 的 USI/加权 SI 公式；任务型异步 API（assistant/reference_check poll 模式）；MCP 工具+prompt 工作流封装。
- **对「完全形态」的启示**：若手里有全文（LaTeX/PDF），语句级引文图是可建的最高档资产——边（谁引谁）之上叠「在哪引、怎么引、挺还是踩」三层信息；分类器从 SciBERT 起步或直接用 LLM 蒸馏，单卡 GPU 即够全量推理。

## 探针产物

`tmp/citation-survey/scite/`：`docs_openapi.json`（979KB 完整 OpenAPI 3.1）、`docs_llms-full.txt`（171KB 全站文档 markdown）、`docs_llms.txt`、`docs_home.html`、`scite_biorxiv.pdf`（QSS 论文 bioRxiv 全文 33 页）、`gh_repos.json`/`ext_tree.json`（GitHub org 清单与扩展源码树）、`s2paper.json`、`qss_a_00146.pdf`+`qss_jina.txt`（MIT Press Cloudflare 拦截留证）、`home.html`（CloudFront 403 留证）、`test_dl/test_dl2`（S2 PDF 202 空响应留证）、`docs_api-reference_openapi.json`（404 留证）。

### 参考文献

[^qss]: Nicholson JM, Mordaunt M, Lopez P, et al. scite: A smart citation index that displays the context of citations and classifies their intent using deep learning. *Quantitative Science Studies* 2021;2(3):882-898. [bioRxiv 全文](https://www.biorxiv.org/content/10.1101/2021.03.15.435418v1) / [DOI](https://doi.org/10.1162/qss_a_00146)
[^docs]: Scite API Documentation. docs.scite.ai 2026. [docs.scite.ai](https://docs.scite.ai/)（openapi.json 已存探针产物）
[^ccc]: Adding Context to Research with "Smart Citations". Copyright Clearance Center blog. [copyright.com](https://www.copyright.com/blog/adding-context-to-research-with-scite-smart-citations/)
[^merger]: Agreement of Merger and Plan of Reorganization, Research Solutions × Scite Inc. SEC EDGAR 2023-11-24. [sec.gov](https://www.sec.gov/Archives/edgar/data/1386301/000110465923121108/tm2331467d1_ex2-1.htm)
[^sec]: Research Solutions 8-K/ex99-2（$14.8M EV、4.11× ARR、earnout 条款）. SEC EDGAR 2023-11-27. [sec.gov](https://www.sec.gov/Archives/edgar/data/1386301/000110465923121108/tm2331467d1_ex99-2.htm)
[^prn]: Research Solutions Announces Acquisition of scite. PR Newswire 2023-11-27. [prnewswire.com](https://www.prnewswire.com/news-releases/research-solutions-announces-acquisition-of-scite-301997608.html)
[^nih]: scite awarded NIH SBIR Fast-Track grant (1 R44 DA050155-01). scite blog 2019-10. [scite.ai](https://scite.ai/blog/scite-awarded-nih-sbir-fast-track-grant-eeccadec97f4)
[^aaas]: The AAAS and scite Partner on Development of Smart Citations. scite blog 2022-02-28. [scite.ai](https://scite.ai/blog/the-american-association-for-the-advancement-of-science-aaas-and-scite-partner)
[^data]: Scite Data page（32M+ 全文源、30+ 出版商、SJI 榜单）. [scite.ai/data](https://scite.ai/data)
[^qa]: Alfasoft Online Demo Days 2025 Scite Q&amp;A（1.4B 语句/190M 文献、无协议出版商走 Crossref+开放仓储）. [alfasoft.com](https://alfasoft.com/files/odd/2025/Scite-QA-EN.pdf)
[^nature]: New bot flags scientific studies that cite retracted papers. Nature Index News. [nature.com](https://www.nature.com/nature-index/news/new-bot-flags-scientific-research-studies-that-cite-retracted-papers)
[^notices]: A new, open system for the automated detection of retractions and other editorial notices. scite blog 2022-10-19. [scite.ai](https://scite.ai/blog/2022-10-19_automated-notice-detection)
[^sjp]: Content-aware rankings: a new approach to rankings in scholarship. arXiv:2504.05206 2025. [arxiv.org](https://arxiv.org/pdf/2504.05206)
[^badge]: Introducing the scite badge. scite blog. [scite.ai](https://scite.ai/blog/introducing-the-scite-badge-ec1fba15ccf4)
[^zotero]: Scite Zotero plugin guide + github.com/scitedotai/scite-zotero-plugin. [docs.scite.ai](https://docs.scite.ai/guides/zotero-plugin)
[^mcp]: Scite MCP overview + tools + prompts. [docs.scite.ai/mcp](https://docs.scite.ai/mcp/overview)
[^evidence]: Evidence datasets overview（ResoluteAI 数据集、四端点模式）. [docs.scite.ai](https://docs.scite.ai/guides/evidence/overview)
[^pricing]: Pricing and plans. [docs.scite.ai](https://docs.scite.ai/pricing-and-plans)
[^handbook]: Assistant by scite — LLM Prompt Handbook. Research Solutions. [researchsolutions.com](https://www.researchsolutions.com/hubfs/LLM-Prompt-Handbook-Scite-Assistant.pdf)
[^yt]: How does scite Assistant work? YouTube. [youtube.com](https://www.youtube.com/watch?v=KfSYyNW7b1s)
[^bitsinbio]: Interview with scite (Josh Nicholson). Bits in Bio. [substack](https://bitsinbio.substack.com/p/interview-with-scite)
[^bakker]: Bakker C, Theis-Mahon N, Brown SJ. Evaluating the accuracy of scite, a smart citation index. *Hypothesis* 2023;35(2). [indianapolis.iu.edu](https://journals.indianapolis.iu.edu/index.php/hypothesis/article/download/26528/25101/54274)
[^reply]: Rife S, Nicholson J, Uppala A, Rosati D. Reply to Bakker et al. *Hypothesis* 2025;37(1). [indianapolis.iu.edu](https://journals.indianapolis.iu.edu/index.php/hypothesis/article/view/28018)
[^gh]: github.com/scitedotai 组织仓库清单（已存 gh_repos.json）. [github.com](https://github.com/scitedotai)
