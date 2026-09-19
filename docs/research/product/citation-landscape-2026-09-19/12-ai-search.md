# AI 检索系论文发现产品调研

本 lane 覆盖「论文发现」生态里的 AI 检索系产品：Elicit、Consensus、Undermind、SciSpace、Keenious、Scinapse。它们的共同点是主打**语义检索 + LLM 处理**路线而非纯引用图遍历，但细拆之后各家对引用数据的使用深浅差异很大——Undermind 把「沿引用链探索」写进了核心算法，Scinapse（Pluto Labs）更是整体转向了引用图定位，并发表了直接丈量「embedding 检索 vs 引用图」差距的审计论文。以下逐家拆解。

## Elicit

Elicit 前身是 Ought（旧金山，2018 年由 Andreas Stuhlmüller 创立的非营利研究组织）孵化的产品，现为独立商业化公司，主打「AI 系统性文献综述」。

### 语料与管线

Elicit 宣称可检索语料为 **1.38 亿篇**论文，来源三方去重合并：Semantic Scholar（主力，周更）、OpenAlex（日更，用于 alerts）、PubMed（周更）；官方称合并前各源总量 2 亿+，去重与剔除不完整记录后为 138M[^elicit-corpus]。检索管线分两阶段（官方页面原文）：先用**自研 embedding 模型**把全库按与查询的语义相似度排序，同时把「被引数、发表时间」等作为特征纳入排序信号；然后取 top 1000 交给 LLM 按与用户研究问题的相关性做二次精排/筛选，最终按套餐展示 top 4–1000[^elicit-search]。可见**被引数只作为排序特征之一，不做引用图遍历**。

### 产品面与 API

产品组：Find Papers（语义搜索）、Research Report / Systematic Review（guided 四步综述：检索→筛选→抽取→报告）、Chat with Papers、Extract Data（LLM 对摘要与可得全文抽取自定义列）、Research Agent、Research Alerts。API 走 docs.elicit.com：`corpus` 可选 `elicit`/`pubmed`/`clinical_trials`，`searchMode` 可选 `semantic`/`keyword`（后者直接跑 Lucene 布尔式），Pro 及以上套餐可用，单次返回上限按档 300/500/10000 条，全局限速 100 req/min，另有官方 MCP server[^elicit-api]。

### 定价

Basic 免费（每月 2 篇自动报告、无限搜索）；Plus $12/月（$120/年，4 报告/月）；Pro $49/月（$499/年，12 报告/月 + 系统综述工作流 + 20 自定义列 + 10 个 Research Alerts）；Scale/Enterprise 询价[^elicit-pricing]。实测 2026-09-19：elicit.com 200 可达；api.elicit.com 裸域不可直连（API 挂在主域 `/api/v2/`，需 Pro key，未验证）。

## Consensus

Consensus 是 2021 年起家的学术搜索引擎（波士顿），与 Semantic Scholar 有公开合作[^casrai-consensus]，定位「AI-native 版 Google Scholar」。

### 语料与三段式管线

语料宣称 **2.2 亿+**篇（官网与文档在 200M/220M 两个数字间浮动，属动态口径），来源 = Semantic Scholar + OpenAlex + 自建爬虫补缺口，周更，含全部 PubMed[^consensus-library]。检索是官方公开的三段式 IR 管线[^consensus-how]：

1. **混合召回**：semantic embedding + BM25 双通道在全库（题名/摘要/可得全文）打分融合；
2. **质量重排**：top 1500 按研究质量信号重排——发表时间、**被引数**、期刊影响力（SJR）；
3. **精排 top 20**：换更大模型只重算前 20 名的相关性。

被引数在 step 2 里是显式质量信号——同样只用到「引用数」，不用引用图结构。

### Consensus Meter 与 Deep Review

Consensus Meter 是其标志性功能：对 yes/no 型问题，用一个**微调过的开源模型**把 top 5–20 篇论文的结论逐篇分类为 Yes / No / Possibly / Mixed 并汇总成仪表；附带的 Snapshot 统计四指标：立场各组的平均发表年份、Meta 分析/系统综述/RCT 计数、期刊平均 SJR、**被引数总和**[^consensus-meter]。通用摘要走商用模型（OpenAI），Meter 这类领域功能走自微调开源模型[^consensus-library]。Deep review 是 agentic 模式：把问题拆成子问题、跑最多 20 次定向检索、扫读 1000+ 篇、取 top ~50 合成结构化文献综述[^consensus-deep]。

### 定价

免费档含无限普通搜索 + 3 次 Deep/月；Pro $20/月（$144/年）含 15 次 Deep/月 + 250 次 API&MCP 调用；Deep $65/月（$540/年）含 200 次 Deep/月 + 1000 次 API 调用[^consensus-plans]。实测 2026-09-19：consensus.app 200；api.consensus.app 裸域 404（活主机），consensus.app/api/search 403——前端走 Next.js，搜索端点存在但拦未授权。

## Undermind

Undermind 是 Y Combinator 孵化的 agentic 学术搜索（创始人 Joshua Ramette CEO 与 Tom Hartke CTO，两位 MIT 量子物理博士），定位「给专家用的复杂问题深度检索」，有 GSK 千人级部署（1000+ scientists）背书[^undermind-site]。

### 机制：embedding + 引用链 + LLM 推理的迭代探索

其白皮书（arXiv 时代版本）写明管线三件套：**semantic vector embeddings + citations + language model reasoning**——「basic search」用自定义算法融合三者识别候选，然后 LLM 像人类研究者一样**沿引用链（citation trails）探索**、反思进展、决定下一步，直到收敛[^undermind-whitepaper]。v1 时代直接搜 arXiv 全文 230 万篇（GPT-4 作推理引擎）；后迁移到 **Semantic Scholar ~2 亿篇**语料，分类步骤退到标题+摘要级别，换取全学科覆盖与 3–6 分钟的单次搜索时长（v1 时代要 8–10 分钟）[^casrai-undermind][^aarontay]。它还会用类似「捕获-再捕获」的统计法估计本次搜索已覆盖了多少比例的相关文献（Aaron Tay 实测：提示「已找到约 90%」并建议是否 extend）[^aarontay]。

### 效果宣称

白皮书用 ~300 条真实查询对比 Google Scholar：Undermind 找到的相关论文是 GS 前 5 页的 **10 倍**；分类器把「highly relevant」误判为不相关的概率 ~2%，反向（UM 判相关但人判不相关）<4%；收敛后几乎不漏 GS 能找到的相关论文（>97% 置信）[^undermind-whitepaper]。新版 v2 benchmark（官网，23 条复杂查询、GPT-5.6 Sol 做 gold-standard judge）：10 分钟时 top-20 召回 85%、全部相关召回 75%、精确率 58%，对照 GPT-5.6 Sol agent 50%/38%/40%、Claude Opus 5 agent 47%/33%/35%[^undermind-site]。注意均为厂商自测口径。

### 定价

Free $0；Pro $16/月（年付）；Team $15/人/月（年付）；Enterprise 询价；另有 industry/academic 两套价目[^undermind-site]。实测 2026-09-19：undermind.ai 200 可达。

## SciSpace

SciSpace 前身 Typeset.io（typeset.io 已 301 到 scispace.com），最早做期刊排版模板（现仍保留数万种期刊格式），后扩成「检索→阅读→写作」全流程平台，宣称 100 万+研究者用户[^scispace-pricing]。

### 检索与 Copilot

Discovery 检索语料宣称 **2.8 亿+**篇、含 5000 万+ OA 全文 PDF；管线为向量语义检索 + rerank 模型重排，支持多语种查询与自定义列抽取[^casrai-scispace]。Copilot（PDF 伴读）是其发表论文最多的组件——AAAI'24 论文披露：对选中文字可做 Explain/Summarize/**Related papers**/highlight，其中 related papers 是「从 2 亿+语料中找与**选中文字**相似的论文」——即内容 embedding 相似，非引用图[^scispace-aaai]。Deep Review 是付费档 agentic 多步综述，按主题归组、带行内引用[^casrai-scispace]。

### 引用图使用与定价

未发现引用图遍历功能；「related papers」纯内容相似。免费档：每篇 5 次 AI 提问、5 篇/月、基础检索；Premium $12/月解限[^theaiselect]。实测 2026-09-19：主页 200。

## Keenious

Keenious 是挪威奥斯陆公司，主打**文档级推荐**（document-as-query）与图书馆机构市场——Word/Google Docs 侧边栏插件是其标志形态。

### 语料：OpenAlex 精选集

Keenious 的语料治理文档是本批产品里最透明的：OpenAlex 全量 ~5.1 亿记录 → 第一层按文档类型留 article/review/preprint/book 得 ~2.88 亿 → 第二层对 28 万+ source 逐个人工抽样评级剔除非学术源 → 第三层记录级质检（可链接/可检索文本量/完整作品/去重，剔除撤稿）得 **~1.81 亿**篇终索引；另接入 Norwegian Scientific Index 做同行评审 venue 标注，并在精选索引内**重算 FWCI**（领域归一化被引影响）[^keenious-index][^keenious-openalex]。

### 检索机制

官方说明：混合检索 = 语义 embedding（仅标题+摘要入库向量）+ BM25 关键词做 rank fusion，语义权重更高；引号短语与 AND/OR/NOT 作为硬约束；排序在相关性之上叠加「学术信号」微调（如语言匹配——非英语查询提权同语种结果）；返回固定大小结果集（默认 300，可调 100–10000）并按 embedding 邻近度把结果**聚成 research areas** 分组展示[^keenious-search]。文档推荐即把用户粘贴文本/上传文档/正在写的 Word 文档当成查询向量去匹配[^keenious-what]。

### 引用图使用与定价

不遍历引用图；引用只以重算 FWCI 的形式做质量信号。Free（5 AI 回复/会话、3 会话/天）；Plus $10/月起；Teams $20/人/月；Institutions 询价（SSO/SAML/IP 认证、馆藏集成）[^keenious-pricing]。实测 2026-09-19：keenious.com 307 跳转到 www。

## Scinapse（Pluto Labs）

Scinapse 是首尔 Pluto Labs 的学术搜索引擎——**本批里唯一整体押注引用图的产品**，也是「embedding 失效」实证研究的出处。

### 数据源与产品转向

官方披露数据 = Microsoft Academic Graph（2021 年底前）+ PubMed + PMC + OpenAlex + Semantic Scholar + 自研爬虫，月处理 840 万数据点、产出 3700 万条数据条目[^scinapse-data]。产品现形是「Scinapse AI」：自研 agent 跑在 **2.5 亿+篇的引用图**上，分工是「LLM 做创造性推理，专用 API 做检索/验证/新颖性校验」；官网直接写明定位——「Text embeddings find the right topic but miss the specific research agenda. Our citation graph — bibliographic coupling and co-citation — recovers the signal they miss」[^scinapse-site]。

### 关键实证：Topic Is Not Agenda

Pluto Labs 把这条定位写成了 arXiv 论文（2605.07158）[^pluto-paper]：用全量 OpenAlex 引用表（~25 亿条）在 358 万篇论文上建「增广引用图」——直接引用 + 文献耦合（≥3 共同引用、Salton 余弦加权、剔除被引超 500 的热门参考文献）+ 共被引（≥3 共同施引、剔除施引超 200 的综述型），三层合并得 1.53 亿条边（均值度 85.5）；再用 Leiden CPM 在两级粒度上切社区（L1 子领域 / L2 研究议程）。结论：**四个 SOTA embedding（Gemini、Qwen3-8B、Qwen3-0.6B、SPECTER2）在 L1 有 45–52% top-10 同区率，但到 L2 研究议程级只剩 15–21%——即每 10 篇语义近邻里约 8 篇不在同一研究议程**，SPECTER2 这种引用对比训练出来的反而最差；而一个「刻意简单」的被引数重排探针，叠在 BM25 上就能拿到 59.6% top-1 L2 命中，比最强 embedding（Gemini 50.6%）高 9 个点、比裸 BM25（39.3%）高 20 个点[^pluto-paper]。第三方评注（Pith Review）认为 L2 分区的 ground-truth 稳健性有待同行评审，但规模与重排结论值得注意[^pith-review]。

### 定价

Free（关键词检索+基础信息）；Basic $23/月（实时引用分析+多过滤）；Pro $36/月（引用网络图+AI mini-review 存储+5 次 Smart Query/4h）；Max $52/月（25 次/4h）；均年付价，7 天试用[^scinapse-pricing]。实测 2026-09-19：scinapse.io 200，Next.js 前端（Google Frontend/Vercel 托管），首页 HTML 81.6KB。

## 横向对比

| 产品 | 语料规模/来源 | 核心发现机制 | 引用图使用 | 定价（月付/年付折算） |
| --- | --- | --- | --- | --- |
| Elicit | 138M；S2+OpenAlex+PubMed 去重 | 自研 embedding 全库排序→LLM 精排 top1000→抽取列 | 仅被引数作排序特征 | 免费/Plus $12/Pro $49 |
| Consensus | 220M；S2+OpenAlex+自爬 | embedding+BM25→质量信号重排（含被引数、SJR）→大模型精排 top20 | 仅被引数/SJR 质量信号 | 免费/Pro $20($12)/Deep $65($45) |
| Undermind | S2 ~200M（标题+摘要） | **迭代 agent**：embedding+**引用链追踪**+LLM 推理，收敛估计 | **沿引用链探索**（核心算法） | 免费/Pro $16/Team $15 |
| SciSpace | 280M+（含 50M OA 全文） | 向量检索+rerank；related=内容相似 | 未见（related papers 走 embedding） | 免费/Premium $12 |
| Keenious | OpenAlex 精选 181M | 文档/查询 embedding+BM25 融合→research areas 聚类 | 重算 FWCI 质量信号 | 免费/Plus $10/Team $20 |
| Scinapse | MAG+S2+OpenAlex+PM 250M+ | **引用图（BC+CC+直接引用）+AI agent** | **整体建在引用图上** | 免费/Basic $23/Pro $36/Max $52 |

## 两条路线的对比结论

本 lane 六家产品恰好排成一条光谱：**纯 embedding/LLM 端**是 Elicit、Consensus、SciSpace、Keenious——引用数据只以「被引数/FWCI/SJR」标量形式进排序或质量信号，图结构完全不用；**混合端**是 Undermind——embedding 做候选召回，但探索阶段显式沿引用链滚动，LLM 决定何时收敛；**纯引用图端**是 Scinapse——把 BC/CC/直接引用三层边当成核心检索资产，embedding 反而只做话题层粗排。

引用图路线的盲区：新文冷启动（无入边可追）、对「语义措辞」无感知（同议程不同措辞的论文照样只能靠图）、构建与更新成本高（Scinapse 要维护 250M 级图）。embedding 路线的盲区由 Pluto 的实测论文量化：语义近邻在「研究议程」粒度上命中率仅 15–21%——找得到「同主题」但找不到「同议程」；且对权威度无先验（无法区分开创性工作与跟风工作，只能靠被引数补救）。可见的收敛方向是混合：召回用 embedding+BM25（保新文覆盖与语义模糊查询），精排/扩展用引用图（保议程一致性与权威度），LLM 只做理解与合成——Undermind 的引用链追踪与 Consensus 的质量信号重排分别是这条线的两种工业实现。

### 参考文献

[^elicit-search]: Elicit. Paper Search | How does Elicit's AI search work. [elicit.com/solutions/search](https://elicit.com/solutions/search)
[^elicit-corpus]: Elicit Help Center. Elicit's source for papers. 2026. [support.elicit.com/en/articles/14758040](https://support.elicit.com/en/articles/14758040-elicit-s-source-for-papers)
[^elicit-api]: Elicit. Elicit API Reference. 2026. [docs.elicit.com](https://docs.elicit.com/)
[^elicit-pricing]: Elicit. Pricing. 2026. [elicit.com/pricing](https://elicit.com/pricing)
[^consensus-how]: Consensus Help Center. How Consensus works. [help.consensus.app/en/articles/9922673](https://help.consensus.app/en/articles/9922673-how-consensus-works)
[^consensus-meter]: Consensus Help Center. The Consensus Meter. [help.consensus.app/en/articles/10069920](https://help.consensus.app/en/articles/10069920-the-consensus-meter)
[^consensus-plans]: Consensus Help Center. Subscription Plans. [help.consensus.app/en/articles/10087865](https://help.consensus.app/en/articles/10087865-subscription-plans)
[^consensus-deep]: Consensus Help Center. How to Use Deep review. [help.consensus.app/en/articles/11740827](https://help.consensus.app/en/articles/11740827-how-to-use-deep-review)
[^consensus-library]: Consensus. Consensus Library Primer. [consensus.app/home/blog/consensus-library-primer](https://consensus.app/home/blog/consensus-library-primer/)
[^casrai-consensus]: CASRAI. Consensus AI: What It Is and Its Real Limits. [casrai.org/guides/consensus-ai-search-engine-guide](https://casrai.org/guides/consensus-ai-search-engine-guide)
[^undermind-whitepaper]: Hartke T, Ramette J. Benchmarking the Undermind Search Assistant (whitepaper). [undermind.ai/whitepaper.pdf](https://www.undermind.ai/whitepaper.pdf)
[^undermind-site]: Undermind. Product site & v2 benchmark. 2026. [undermind.ai](https://www.undermind.ai/)
[^casrai-undermind]: CASRAI. Undermind: What It Is and How Its Deep Search Agent Works. 2026. [casrai.org/guides/undermind-ai](https://casrai.org/guides/undermind-ai)
[^aarontay]: Tay A. Undermind.ai — a different type of AI agent style search optimized for high recall?. 2024. [aarontay.substack.com](https://aarontay.substack.com/p/undermindai-different-type-of-ai-agent)
[^scispace-aaai]: SciSpace. SciSpace Copilot: Empowering Researchers through Intelligent Reading Assistance. AAAI 2024. [doi.org/10.1609/aaai.v38i21.30578](https://doi.org/10.1609/aaai.v38i21.30578)
[^casrai-scispace]: CASRAI. SciSpace: What It Is and How Deep Review Works. 2026. [casrai.org/guides/scispace](https://www.casrai.org/guides/scispace)
[^scispace-pricing]: SciSpace. Pricing. [scispace.com/pricing](https://scispace.com/pricing)
[^theaiselect]: TheAISelect. SciSpace Review 2026. [theaiselect.com/en/tools/scispace](https://www.theaiselect.com/en/tools/scispace)
[^keenious-search]: Keenious Help Center. How Search Works in Keenious. [help.keenious.com/en/articles/169371](https://help.keenious.com/en/articles/169371-how-search-works-in-keenious)
[^keenious-openalex]: Keenious Help Center. Understanding Our Data Source: How Keenious Uses OpenAlex. [help.keenious.com/en/articles/203843](https://help.keenious.com/en/articles/203843-understanding-our-data-source-how-keenious-uses-openalex)
[^keenious-index]: Keenious Help Center. How Keenious Curates Its Index. 2026-07-22. [help.keenious.com/en/articles/699209](https://help.keenious.com/en/articles/699209-how-keenious-curates-its-index)
[^keenious-what]: Keenious Help Center. What is Keenious?. [help.keenious.com/en/articles/185112](https://help.keenious.com/en/articles/185112-what-is-keenious)
[^keenious-pricing]: Keenious. Pricing（WebFetch 实测 2026-09-19）. [keenious.com/pricing](https://keenious.com/pricing)
[^scinapse-site]: Pluto Labs. Scinapse product page. [pluto.im/product/scinapse](https://www.pluto.im/product/scinapse)
[^scinapse-data]: Pluto Labs. Precise Research Data for Your Research / About Our Data. [insights.pluto.im](https://insights.pluto.im/ai-empowers-researchers-with-data/) / [about.scinapse.io/about_our_data](https://about.scinapse.io/about_our_data)
[^scinapse-pricing]: Scinapse. Plans & Pricing. [scinapse.io/pricing](https://www.scinapse.io/pricing)
[^pluto-paper]: Yoo J. Topic Is Not Agenda: A Citation-Community Audit of Text Embeddings. arXiv:2605.07158. [arxiv.org/html/2605.07158](https://arxiv.org/html/2605.07158)
[^pith-review]: Pith Review. Review of arXiv:2605.07158. [pith.science/paper/2605.07158](https://pith.science/paper/2605.07158)

## 探针产物

- `tmp/citation-survey/ai-search/probe-notes.txt` — 端点探测记录（首页可达性、API 域猜测结果、技术栈）
- `tmp/citation-survey/ai-search/scinapse_home.html` — scinapse.io 首页快照（81.6KB，Next.js）
- `tmp/citation-survey/ai-search/consensus_home.html` — consensus.app 首页快照（28KB，Next.js）
- 实测标记：consensus.app 200 / api.consensus.app 404 / consensus.app/api/search 403 / scinapse.io 200 / keenious.com 307 / elicit.com 200 / undermind.ai 200（2026-09-19 12:0x CST）
