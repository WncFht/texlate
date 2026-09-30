# Lane 13：大平台论文推荐系统机制（GS / S2 / MAG / RG / Mendeley / ADS / 数字图书馆）

> **结论**：工业界个性化论文推荐的配方高度收敛——信号上没有任何一家只用单一信号（内容 embedding 每家都有，引用图邻接、用户文库/共读、作者关系、显式反馈按家叠加），架构上清一色「离线召回 → 线上排序」，分歧只在语料规模 × 实时性的取舍点；已停运的 MAG 留下的是工业级最完整公开配方。
> **状态**：时点证据（2026-09-19 口径）
> **日期**：2026-09-19

## 各平台机制

**Google Scholar**：官方不披露算法，逆向研究（Beel & Gipp 2009 系列，136 万 + 文章位次分析）确认 GS 对关键词检索、Related articles、Cited by 用**三套不同排序算法**；被引数是最重排序因子，标题命中权重高，全文词频几乎无影响，且对近期文章有补偿性加权以抵消马太效应[^beel09a][^beel09b]。**My updates**（2012 上线，前提是有公开 Scholar profile）官方自述四信号：本人论文的内容、论文间的引用图、兴趣随时间漂移、合作者与所引作者[^gsblog]——「用自己的出版物当 profile」范式，作者身份本身就是兴趣模型，用户零操作。**Alerts** 两条线：关键词 alert 与 citation alert（自己论文被引时邮件）——被引是最朴素最强的相关信号[^lse]。无官方 API，事实标准方案是 SerpAPI 类付费抓取（`cites` 参数取被引、`related:` 取相关文，按月配额）[^serpapi]。

**Semantic Scholar**：Recommendations API 只有两端点——`POST /recommendations/v1/papers`（body 正负例 paperId 列表，可混用外部 ID）与 `GET .../forpaper/{id}`，单次最多 500 条按相关度排序[^s2swagger][^s2medium]。实测关键发现：`forpaper` 带 `from=recent|all-cs` 池参数（swagger 定义、默认 `recent`，仅 forpaper 上有）——对 2017 年「Attention is All you Need」（19.3 万被引）在默认 `recent` 池（~近 3 个月新论文，「跟上最新进展」型）**返回空数组**，但 `from=all-cs` 覆盖全 CS 语料并返回真实推荐（live 验证）——双池设计使 forpaper 同时能做全库相似检索[^s2swagger][^s2faq]。Research Feeds 用「state-of-the-art 论文 embedding、对比学习训练」（SPECTER 一脉），正例=library 论文、负例=标 "not relevant"，建议 5 正 3 负起步，日更[^s2faq]。FeedLens（UIST 2022）透露内部抽象：每个 feed 是一个 per-user 偏好模型（lens），把「用户兴趣」建模为 embedding 空间里的方向[^feedlens]。未鉴权共享池限流紧、易 429，API key 免费申请。

**Microsoft Academic（历史范本，最完整公开配方）**：MAG 虽停运，arXiv:1905.08880 留下了工业级论文推荐最完整的设计与评估文档[^mag]：①**全库预计算**——为 ~1.6 亿篇英文论文/专利每篇静态生成推荐列表随 MAG on Azure 开放下载，「推荐即数据」而非在线计算；②**加权混合**——共被引（CcB，高质量但覆盖低）+ 内容 embedding（CB，覆盖全库但精度低）两支用可调 mapping function 融合；③**novelty–authority 旋钮**——调参在「推新」与「推权威」间滑动；④冷启动走 CB 支路保全库覆盖；⑤CB 支路用聚类加速近邻搜索（全库两两 2.56×10¹⁶ 不可行）；⑥40 人用户研究 2400+ 推荐对验证 CcB 支路与人工评分强相关。基本是「引用图谱 + 内容混合、全库离线预计算」路线的标准答案。

**ResearchGate**：算法未完整公开，第三方按行为归纳为人口属性（机构/领域）+ 关系网络（关注/合著）+ 内容三路加权[^rgrec]——差异化在**社交图是引用图之外的第二张网**。

**Mendeley**：有较完整自研披露（arXiv:1409.1357）[^mendeley]：线上 Related research 最初是内容过滤；评测对比 item-based 协同过滤（训练数据=用户文库 co-readership——谁把哪篇收进 library）vs 内容过滤 vs 混合，结果 **CF 略优于 CBF 但部分场景失效，混合最好（precision ~70%）**；co-readership 的独立研究结论：readership 网精度最高但覆盖低，co-readership 兼顾精度与覆盖[^coread]。

**NASA ADS**（机制披露最细，arXiv:1209.1318）：摘要页右侧 **8 个推荐位各用一种算法**——向量空间最近邻、近邻论文读者的最多共读、读后紧随/之前最常读的、近 3 个月近邻中最常读的最新论文等，一个位置一个算法等于并排 A/B[^ads]；「What People are Reading」= most co-read、「What Experts are Citing」= 聚合参考文献表、「Reviews and Introductory Papers」= 聚合施引列表；向量空间由近期主流期刊参考文献里的索引词 + 专业读者阅读模式共同构建。

**数字图书馆史前史**：CiteSeer（鼻祖，2006 停更）有四类链接推荐——文内被引、施引、共被引、active bibliography，加 TF-IDF 内容相似与 1–5 显式评分，**共被引推荐 2003 年就已产品化**；ACM DL 有内容型 find-similar 与行为型 readers-also-read 两路；IEEE Xplore 落地很浅[^dl-survey]。

## 通用配方归纳

**信号源**（按出现频率）：内容/embedding（每家）、引用图邻接（S2·MAG·CiteSeer·GS·ADS）、用户文库/共读行为（Mendeley·ADS·ACM·GS My-updates 隐含）、作者/合作关系（GS·RG）、显式正负反馈（S2·CiteSeer）、人口属性（RG）。混合是通用解，分歧只在权重。

**架构**：清一色离线召回→线上排序。MAG 推到极限（全库逐篇预计算当数据发）；S2 折中（默认候选池裁到近 3 个月实时算，`from=all-cs` 另开全库池）；ADS 实时算但语料只限天文——三家差异本质是语料规模×实时性取舍点不同。

**冷启动**两条主流：引用缺失时内容支路兜底（MAG），或干脆把池限到「有 embedding 的新论文」（S2）。SPECTER 的巧思在于用引用图当训练信号产出内容 embedding——把引用信息蒸馏进向量。

**产品形态三档**：(a) 围绕单篇的相关推荐（发现层底座）；(b) 围绕集合的 feed/updates（留存，需用户资产沉淀）；(c) 围绕作者的 citation alert（最低成本最高精度钩子）。完整发现层一般 (a) 打底、(b) 留存、(c) 召回。

## 结论

自建发现层的可照搬配方：离线侧「BC/引用图召回 + 内容 embedding 召回」双路混合（MAG 模式），线上侧候选集内排序；个性化 feed 用「用户资产（library/自己的论文）→ 候选池 → 时间截断增量推送」（S2/ADS 模式）；池的规模按算力裁——全库预计算、时间窗实时、领域限定实时三档都有先例背书。

### 参考文献

[^beel09a]: Beel, J., & Gipp, B. Google Scholar's Ranking Algorithm: An Introductory Overview. ISSI 2009. [issi-society.org](https://www.issi-society.org/proceedings/issi_2009/ISSI2009-proc-vol1_Aug2009_batch2-paper-1.pdf)

[^beel09b]: Beel, J., & Gipp, B. Google Scholar's Ranking Algorithm: The Impact of Citation Counts. 2009. [uni-goettingen.de](https://gipplab.uni-goettingen.de/wp-content/papercite-data/pdf/beel09a.pdf)

[^gsblog]: Google Scholar Blog. Scholar Updates: Making New Connections（2012）. [benhannigan.com 转引](https://benhannigan.com/2013/07/16/academic-networking/)

[^lse]: LSE Impact Blog. How to keep up to date with the literature but avoid information overload. 2018. [blogs.lse.ac.uk](https://blogs.lse.ac.uk/impactofsocialsciences/2018/05/18/how-to-keep-up-to-date-with-the-literature-but-avoid-information-overload/)

[^serpapi]: SerpApi. Google Scholar API documentation. [serpapi.com/google-scholar-api](https://serpapi.com/google-scholar-api)

[^s2swagger]: Semantic Scholar. Recommendations API swagger（2026-09-19 自取）. api.semanticscholar.org/recommendations/v1/swagger.json

[^s2medium]: AI2. Semantic Scholar Releases New Recommendations API. [medium.com/ai2-blog](https://medium.com/ai2-blog/semantic-scholar-releases-new-recommendations-api-ca01ef2d80d4)

[^s2faq]: Semantic Scholar. FAQ: What are Research Feeds. [semanticscholar.org/faq](https://www.semanticscholar.org/faq/what-are-research-feeds)

[^feedlens]: Kaur, H., et al. FeedLens: Polymorphic Lenses for Personalizing Exploratory Search over Knowledge Graphs. UIST 2022. [arxiv.org/abs/2208.07531](https://arxiv.org/abs/2208.07531)

[^mag]: Wang, D., et al. A Scalable Hybrid Research Paper Recommender System for Microsoft Academic. WWW 2019. [arxiv.org/pdf/1905.08880](https://arxiv.org/pdf/1905.08880)

[^rgrec]: A hybrid recommendation system for ResearchGate academic social network. [springerprofessional.de](https://www.springerprofessional.de/a-hybrid-recommendation-system-for-researchgate-academic-social-/24643936)

[^mendeley]: Jack, K., et al. Recommending Scientific Literature: Comparing Use-Cases and Algorithms. 2014. [arxiv.org/abs/1409.1357](https://ar5iv.labs.arxiv.org/html/1409.1357)

[^coread]: Personalized Recommendation of Research Papers by Fusing Recommendations from Explicit and Implicit Social Network. [academia.edu](https://www.academia.edu/124793479/)

[^ads]: Henneken, E., et al. Finding and Recommending Scholarly Articles. 2012. [arxiv.org/abs/1209.1318](https://doi.org/10.48550/arxiv.1209.1318)

[^dl-survey]: A Hybrid Recommender System Guided by…（数字图书馆推荐综述）. JETWI 2014. [jetwi.us](http://www.jetwi.us/uploadfile/2014/1226/20141226015349581.pdf)
