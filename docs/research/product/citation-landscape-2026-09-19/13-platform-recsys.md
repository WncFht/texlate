# 大平台论文推荐系统机制调研

调研对象：Google Scholar、Semantic Scholar、Microsoft Academic（历史范本）、ResearchGate、Mendeley、以及 ADS/ACM DL/IEEE Xplore/CiteSeer 等数字图书馆的论文推荐机制——重点回答「工业界个性化论文推荐的通用配方是什么」。方法：官方文档/论文取证 + Semantic Scholar Recommendations API 直接探针实测（2026-09-19）。

## 总览对照

| 平台 | 推荐机制 | 主要信号 | 开放程度 |
| --- | --- | --- | --- |
| Google Scholar | Related articles / Cited by / My updates / Alerts | 内容 + 引用图 + 作者关系 + 时间衰减 | 无官方 API，只有网页 + 邮件 |
| Semantic Scholar | Recommendations API + Research Feeds | 对比学习论文 embedding，library 正负例 | 开放 REST API（限流） |
| Microsoft Academic（已停运） | 混合推荐，全库预计算 | 共被引 + 内容 embedding | 推荐结果随 MAG 开放下载 |
| ResearchGate | 混合（内容 + 网络 + 人口属性） | 论文文本、关注/合著网、用户画像 | 无开放 API |
| Mendeley | 内容过滤 + 项目级协同过滤 | 用户文库（co-readership） | 曾开放 5 万文库快照 |
| NASA ADS | 8 种算法面板 + 共读推荐 | 引用表 + 索引词向量空间 + 阅读日志 | API 开放（token 免费） |
| ACM DL / IEEE Xplore / CiteSeer | 内容相似 + 「读者也读」 | 词表/聚类 + 阅读频次 | 网页功能，无公开推荐 API |

## Google Scholar

### Related articles 与 Cited by

官方帮助页只说 Related articles「找到与给定结果相似的文档」，不披露算法[^gshelp]。学界对 GS 排序的逆向研究（Beel &amp; Gipp 2009 系列）给出迄今最细的机制描述：GS 对**关键词检索、Related articles、Cited by 使用三套不同的排序算法**；引用数是最重的排序因子（分析了 136 万+ 文章位次），标题命中权重高，全文词频几乎无影响，且对近期文章有补偿性加权以抵消马太效应[^beel09a][^beel09b]。Related articles 的具体相似度构成未公开——官方只承诺「similar」，从行为推断是内容相似 + 引用邻近的混合（未验证具体配比）。

### My updates（个性化推荐）

2012 年 8 月上线，前提是有公开的 Scholar profile。官方描述值得原文引用[^gsblog]：

&gt; We analyze your articles (as identified in your Scholar profile), scan the entire web looking for new articles relevant to your research… We determine relevance using a statistical model that incorporates **what your work is about, the citation graph between articles, the fact that interests can change over time, and the authors you work with and cite**.

即四个信号：本人论文的**内容**、**引用图**（自己的论文被谁引/引谁）、**兴趣漂移的时间项**、**合作者与所引作者**。这是「用你自己的出版物当 profile」的推荐范式——与用户手动攒 library 不同，作者身份本身就是兴趣模型。推荐结果不进邮箱，只在主页 banner + My updates 页展示[^openalex-blog]。

### Alerts

两条线：关键词 alert（新结果邮件）与 citation alert（profile 页 Follow →「Follow new citations」自己的论文被引时邮件通知；也可以 follow 某位作者的 new articles）[^lse]。这是引用图最朴素的推荐用法：**被引 = 最强的相关信号**。

### API 现状

无官方 API，Scholar 反爬严格。事实标准方案是 SerpAPI 这类付费抓取服务：`engine=google_scholar` 单端点，`cites` 参数取被引列表、`cluster` 取版本聚合、`related:` query helper 取相关文章，每页至多 20 条，按月配额计费，缓存命中免费（实测文档面）[^serpapi]。开源侧有 `scholarly`（python）等爬虫库，稳定性差。

## Semantic Scholar

### Recommendations API（实测，2026-09-19）

swagger 自取（`GET /recommendations/v1/swagger.json`，ReDoc 渲染），整个 API 只有两个端点[^s2swagger]：

- `POST /recommendations/v1/papers`：body `{"positivePaperIds": [...], "negativePaperIds": [...]}`，ID 可混用 hex paperId 与 `ArXiv:`/`DOI:` 外部 ID——实测用 attention 论文（paperId `204e3073…`）作正例成功返回 5 条推荐（TANGO、TITE 评测等近年 Transformer 改进向论文）。
- `GET /recommendations/v1/papers/forpaper/{paper_id}`：单正例版。

官方博文确认两个端点共用同一推荐服务，**单次最多返回 500 条，按相关度排序**[^s2medium]。

实测关键发现：**`forpaper` 对 2017 年「Attention is All you Need」（corpusId 13756489，19.3 万被引）返回空数组**——无论 paperId 还是 CorpusId 前缀。FAQ 给出了原因：**推荐池只含最近 3 个月发表的论文**[^s2faq]。这是「帮你跟上最新进展」型推荐，不是全库相似检索——设计目标决定了召回池的时间窗。

限流：未鉴权共享池非常紧，实测间歇性 429（`Too Many Requests… apply for a key`），API key 免费申请换取专属配额[^s2keymsg]。

### Research Feeds（网站推荐 feed）

官方 FAQ 的机制描述[^s2faq]：

- 底座是「**state-of-the-art 论文 embedding 模型，对比学习训练**」（SPECTER 一脉），为每个 library folder 找相似论文；
- **正例 = 存入 folder 的论文，负例 = feed 里标 "not relevant"**；官方建议 5 正例 + 3 负例起步；
- 推荐**日更**（dashboard + email alert）；
- 召回池同样是**近 3 个月**——feed 与 API 共用一套池约束。

FeedLens（UIST 2022，AI2 自家论文）透露了架构抽象：每个 research feed 本质是一个**per-user 偏好模型（lens）**，定义在论文上但可重定向去排序作者/机构/venue 等 KG 实体[^feedlens]。这说明 S2 内部把「用户兴趣」建模为 embedding 空间里的一个方向，而非一堆规则。

## Microsoft Academic（历史范本，最完整公开配方）

虽然 MAG 已停运，它留下了工业级论文推荐系统最完整的一篇设计与评估文档（arXiv 1905.08880）[^mag]：

- **全库预计算**：为 MAG 里约 1.6 亿篇英文论文/专利**每篇**静态生成推荐列表，结果随 MAG on Azure 开放下载——「推荐即数据」而非在线计算；
- **加权混合（weighted hybrid）**：共被引（CcB，高质量但覆盖低——引用数据不全）+ 内容 embedding（CB，覆盖全库但精度低）两支，用一个可调 mapping function 融合；
- **novelty–authority 旋钮**：调参数可在「推新论文」与「推权威论文」间滑动——产品化上很巧；
- **冷启动处理**：引用缺失的论文只靠 CB 支路，保证全库覆盖；
- **规模工程**：全库两两相似不可行（2.56×10¹⁶），CB 支路用聚类加速近邻搜索；
- **评估**：40 人用户研究、2400+ 推荐对打分，P@10/nDCG——共被引支路与人工评分强相关。

这篇论文基本是「引用图谱 + 内容混合、全库离线预计算」路线的标准答案。

## ResearchGate 与 Mendeley

### ResearchGate

RG 自家算法未完整公开，第三方研究（RGRecSys）按其行为归纳出混合配方：**人口属性（机构/领域）+ 关系网络（关注、合著）+ 内容（论文文本）三路加权**[^rgrec]。学术界在 RG 数据上的实验（13 万+ profile 抓取集）显示混合式能逼近 RG 实际推荐的表现[^rgrec]；另有 Mul-RSR 等工作用 Doc2Vec 文本相似 + random walk 社交相似 + MLP/attention 融合做学者推荐[^mulrsr]。结论：RG 的差异化在于**社交图是引用图之外的第二张网**。

### Mendeley

机制有较完整的自研论文披露（arXiv 1409.1357）[^mendeley]：

- 线上「Related research」最初是**内容过滤**（metadata 相似）；
- 评测对比了 item-based 协同过滤（Apache Mahout，训练数据 = **用户文库的 readership**——谁把哪篇论文收进了自己的 library，即 co-readership 信号）vs 内容过滤 vs 混合；
- 结果：**CF 略优于 CBF 但在部分场景失效，混合最好（precision 至 ~70%）**；
- 配套开放过 50,000 用户文库快照供 CF 研究[^mendeley-data]；
- co-readership 作为「隐式社交网络」的独立研究结论：readership 网精度最高但覆盖低，**co-readership 兼顾精度与覆盖**[^coread]。

## 数字图书馆与领域库

### NASA ADS（机制披露最细）

Henneken et al. 2012（arXiv 1209.1318）把 ADS 的推荐函数写成了文档[^ads]：

- 抽象页右侧 **8 个推荐位各用一种算法**：向量空间最近邻、近邻论文读者的最多共读（co-read）、读后紧随/之前最常读的、近 3 个月近邻中最常读的最新论文等——**一个位置一个算法**，等于把多种召回策略并排 A/B 给用户；
- 「What People are Reading」= most co-read 查询；「What Experts are Citing」= Get Reference Lists（聚合一批论文的参考文献表）；「Reviews and Introductory Papers」= Get Citation Lists；
- 向量空间由**近期主流期刊论文参考文献里的索引词 + 专业读者阅读模式**共同构建——内容信号与使用信号混合。

### ACM DL / IEEE Xplore / CiteSeer / Springer

历史与现状调研[^dl-survey]：

- **ACM DL**：两类——内容型「find similar articles」（cluster analysis + dictionary/thesauri），行为型「readers of this article also read」（简单频次统计，被批不准）；
- **IEEE Xplore**：宣布过内容型推荐，落地很浅；
- **CiteSeer**（鼻祖，2006 停更）：四类链接推荐——文内被引、施引、**共被引**、active bibliography——加 TF-IDF 内容相似 + 1–5 显式评分。共被引推荐在 2003 年就已产品化；
- Springer/Nature 的「recommended」面板未见机制披露（未验证，推断为内容 + 共读）。

## API 可得性对照（实测/文档）

| 平台 | 推荐 API | 鉴权 | 备注 |
| --- | --- | --- | --- |
| Semantic Scholar | `POST /recommendations/v1/papers`、`GET .../forpaper/{id}` | 可无 key（共享池易 429） | 池限近 3 个月、≤500 条（实测 + 官方） |
| Google Scholar | 无 | — | SerpAPI 抓取：engine=google_scholar，`cites`/`cluster`/`related:`（实测文档） |
| NASA ADS | Solr 二阶算子 + 推荐函数 | 免费 token | 机制文档最完整 |
| MAG（停运） | — | — | 推荐结果曾随图开放 |
| ResearchGate / Mendeley / ACM / IEEE | 无公开推荐 API | — | 仅站内功能 |

## 通用配方归纳

把上面所有系统拆到同一张表里，工业界「论文推荐 feed」的配方高度收敛：

**信号源**（按出现频率排序）：内容/embedding（每家都有）、引用图邻接（共被引/施引/被引，S2·MAG·CiteSeer·GS·ADS）、用户文库/共读行为（Mendeley·ADS·ACM·GS My-updates 隐含）、作者/合作关系（GS·RG）、显式正负反馈（S2·CiteSeer）、人口属性（RG）。**没有任何一家只用单一信号**——混合是通用解，分歧只在权重。

**架构**：清一色「离线召回 → 线上排序」。MAG 推到极限——全库 1.6 亿篇逐篇预计算静态推荐列表当数据发；S2 折中——推荐池裁到近 3 个月（大约是把候选集砍两个数量级），实时算；ADS 实时算但语料只限天文。三家的差异本质是**语料规模 × 实时性**的取舍点不同。

**冷启动**：两条主流路径——引用缺失时用内容支路兜（MAG），或像 S2 干脆把池限到「有 embedding 的新论文」。SPECTER 的巧思在于用引用图当训练信号产出内容 embedding，相当于把引用信息蒸馏进了向量。

**反馈回路**：S2 的正负例（library / not-relevant）是当前最简洁的用户适配设计；GS 用「你的论文列表」免操作当 profile；Mendeley 用 library 当隐式评分。

**产品形态三档**：(a) 围绕单篇论文的「相关推荐」（forpaper/related articles——发现层底座）；(b) 围绕集合的「feed/updates」（library→feed，需要用户资产沉淀）；(c) 围绕作者的「citation alert」（最低成本最高精度的钩子）。完整的发现层产品一般是 (a) 打底、(b) 做留存、(c) 做召回。

## 探针产物

`tmp/citation-survey/platform-recsys/`：

- `s2_rec_swagger.json` — S2 Recommendations API swagger（官方自取）
- `rec_pool2.json` — `POST /papers` 以 attention 论文为正例的实测返回（5 条推荐）
- `rec_attn_cid.json` / `rec_forpaper.json` / `rec_recent.json` — forpaper 对老论文返回空/429 的实测记录
- `paper_lookup.json` — graph API 查 attention（corpusId 13756489、19.3 万被引）
- `docs_rec.html` — api-docs ReDoc 壳（swagger 路径来源）
- `probe_s2.py`、`probe2.py` — 探针脚本
- 附注：调研中曾把若干探针 json/html 误写进 repo 根目录（兄弟 lane 同现象），已清理本 lane 产物

### 参考文献

[^gshelp]: Google. Google Scholar Search Help. [scholar.google.com/intl/en/scholar/help.html](https://scholar.google.com/intl/en/scholar/help.html)
[^gsblog]: Google Scholar Blog. Scholar Updates: Making New Connections（2012，经 Ben Hannigan 博客转引）. [benhannigan.com](https://benhannigan.com/2013/07/16/academic-networking/)
[^beel09a]: Beel, J., &amp; Gipp, B. Google Scholar's Ranking Algorithm: An Introductory Overview. ISSI 2009. [issi-society.org](https://www.issi-society.org/proceedings/issi_2009/ISSI2009-proc-vol1_Aug2009_batch2-paper-1.pdf)
[^beel09b]: Beel, J., &amp; Gipp, B. Google Scholar's Ranking Algorithm: The Impact of Citation Counts. 2009. [uni-goettingen.de](https://gipplab.uni-goettingen.de/wp-content/papercite-data/pdf/beel09a.pdf)
[^openalex-blog]: OpenAlex. Impact Challenge Day 21: Stay up-to-date on your entire field. [blog.openalex.org](https://blog.openalex.org/impact-challenge-your-entire-field/)
[^lse]: LSE Impact Blog. How to keep up to date with the literature but avoid information overload. 2018. [blogs.lse.ac.uk](https://blogs.lse.ac.uk/impactofsocialsciences/2018/05/18/how-to-keep-up-to-date-with-the-literature-but-avoid-information-overload/)
[^serpapi]: SerpApi. Google Scholar API documentation. [serpapi.com/google-scholar-api](https://serpapi.com/google-scholar-api)
[^s2swagger]: Semantic Scholar. Recommendations API swagger. 实测 `api.semanticscholar.org/recommendations/v1/swagger.json`（2026-09-19）.
[^s2medium]: AI2. Semantic Scholar Releases New Recommendations API. Medium. [medium.com/ai2-blog](https://medium.com/ai2-blog/semantic-scholar-releases-new-recommendations-api-ca01ef2d80d4)
[^s2faq]: Semantic Scholar. FAQ: What are Research Feeds / Research Feeds signaling. [semanticscholar.org/faq](https://www.semanticscholar.org/faq/what-are-research-feeds)
[^s2keymsg]: Semantic Scholar. API 429 响应体实测（2026-09-19）.
[^feedlens]: Kaur, H., Downey, D., Singh, A., Cheng, Y.-Y., Weld, D. S., &amp; Bragg, J. FeedLens: Polymorphic Lenses for Personalizing Exploratory Search over Knowledge Graphs. UIST 2022. [arxiv.org/abs/2208.07531](https://arxiv.org/abs/2208.07531)
[^mag]: Wang, D., et al. A Scalable Hybrid Research Paper Recommender System for Microsoft Academic. WWW 2019. [arxiv.org/pdf/1905.08880](https://arxiv.org/pdf/1905.08880)
[^rgrec]: A hybrid recommendation system for ResearchGate academic social network. Springer. [springerprofessional.de](https://www.springerprofessional.de/a-hybrid-recommendation-system-for-researchgate-academic-social-/24643936)
[^mulrsr]: Personalized Scholar Recommendation Based on Multi-Dimensional Features. Applied Sciences 2021. [doi.org/10.3390/app11188664](https://doi.org/10.3390/app11188664)
[^mendeley]: Jack, K., et al. Recommending Scientific Literature: Comparing Use-Cases and Algorithms. 2014. [arxiv.org/abs/1409.1357](https://ar5iv.labs.arxiv.org/html/1409.1357)
[^mendeley-data]: Mendeley. Mendeley's open data for science and learning: a reply to the DataTEL challenge. IJTEL 2012. [doi.org/10.1504/ijtel.2012.048309](https://doi.org/10.1504/ijtel.2012.048309)
[^coread]: Personalized Recommendation of Research Papers by Fusing Recommendations from Explicit and Implicit Social Network. [academia.edu](https://www.academia.edu/124793479/)
[^ads]: Henneken, E., et al. Finding and Recommending Scholarly Articles. 2012. [arxiv.org/abs/1209.1318](https://doi.org/10.48550/arxiv.1209.1318)
[^dl-survey]: A Hybrid Recommender System Guided by…（数字图书馆推荐综述）. JETWI 2014. [jetwi.us](http://www.jetwi.us/uploadfile/2014/1226/20141226015349581.pdf)
