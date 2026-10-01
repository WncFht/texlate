# Lane 07：ResearchRabbit 逆向

> **结论**：迭代式引用链发现的代表产品——seeds→候选扩展（直引 + 共享 refs/citations+合著+语义）→connectedness 归一化排序，核心无 LLM；数据三源全公开、算法零壁垒，真正资产是 session/step checkpoint-branch 交互模型；全端点鉴权无公共 API。
> **状态**：时点证据（2026-09-19 口径）——对第三方服务的时点观察，仅供互操作参考。
> **日期**：2026-09-19

## 产品定位

ResearchRabbit 2021 年创立于西雅图（Michael Ma 创始），文献发现赛道「迭代式引用链」路线代表：给种子论文→沿引用网络扩张候选→按连接度排序→挑新结果再搜的循环，媒体俗称 "Spotify for papers"[^cbinsights]。**2025-05 被 Litmaps 收购**（Litmaps 同时完成 $1M 融资首关，ARR 约 $1M、合并后用户超 200 万）[^scoop]；2025-10 大改版把多列卡片界面换成单视图「rabbit hole」流程[^aarontay]。免费档功能完整（无限搜索/文献夹、种子 ≤50），RR+ $10/月（种子 ≤300 + 高级过滤 + Signals 诚信徽章）[^pricing]。

## 数据面

帮助文档透明度罕见[^db]：**310M+ 条目 = Crossref + Semantic Scholar + OpenAlex 三家合并去重**，只索引具备 Open Access Metadata 的条目，每周更新，多版本「优先最新、被引最高」。覆盖 PubMed/arXiv/bioRxiv/medRxiv 并经数据商间接覆盖 WoS/Scopus/MAG 来源。

## 算法（官方披露到可复现轮廓）

两段式[^algo][^how][^ai]：

1. **候选集选择**——不搜全库，只取与种子「connected」的候选，connected 四类：直接引用、共享 reference（文献耦合）或共享 citation（共被引）、共享作者、标题/摘要语义相似（2025 改版新增）。候选集可达数十万量级。
2. **候选排序**——按对整个种子集的 connectedness 打分：共享引用/被引 + 作者 + 语义相似 + 归一化项（官方称 "complex mathsy stuff"）；倾向「引用网络中最具影响力的文章」（带质量加权的图重要性度量，非裸被引数）。

官方明示**核心推荐不用 LLM**——「一度与二度连接的 network-based 算法 + graph mathematics + old-school server infrastructure + a little bit of pre-processed magic」，即预计算图结构 + 轻量在线打分[^ai]。用户可调旋钮：Articles 三模式 Similar/References/Citations、Authors 两模式；付费档过滤项含关键词/日期/SJR 分区/期刊 H 指数/OA PDF/撤稿状态[^algo]。

## 产品形态与技术栈

核心交互是 **session/step checkpoint-branch**：API 对象 `search-sessions/{id}/steps/{n}`——每次搜索生成新 iteration checkpoint；模式切换作用于当前 iteration 输入集；从旧 checkpoint 重搜开 branch 并清掉后续 iterations[^aarontay]。内置 citation map（x 轴年份/y 轴被引对数刻度可切）、Collections 文献夹 + folder 共享、Zotero OAuth 单向导入、BibTeX/RIS/CSV 导入导出、`/articles/pdf-parse` 上传解析。Signals（research-signals.com 第三方诚信图谱：撤稿/自引率/幻觉参考文献/tortured phrases 30+ 检查项）集成进付费档[^signals]。

后端实测：API 基座 `api.researchrabbit.ai` 经 CloudFront；**后端是 Swift**（`POST /users/login` 空体报错泄漏 `CodingKeys` 签名——Vapor/Hummingbird 系）；错误格式统一 `{"error":true,"reason":...}`。**全部业务端点需登录，无公开查询 API**——与 alphaXiv 全裸 REST 面相反。前端 Vite+React SPA + d3 + SWR + Mixpanel/Intercom。

## 可借鉴点

- **session/step checkpoint-branch 对象模型是交互设计上的真正资产**——迭代链发现产品的「可回退、可分叉」语义值得照抄。
- connectedness 归一化排序 + 候选四类来源（直引/BC/CC/合著/语义）是「图遍历 + 打分」经典工程，无黑盒。
- 只索引 OA metadata 的口径是现成的合规免责声明写法。

## 结论

数据层（三源聚合）与算法层（邻域扩展 + 加权排序）全部可复刻，壁垒只在候选集数十万量级时的预计算图与服务化遍历能力。未验证项：语义相似的具体 embedding 模型、共被引/耦合在 Similar 打分中的权重、「quality of citations」的具体度量。

### 参考文献

[^cbinsights]: CB Insights. ResearchRabbit company profile. [cbinsights.com](https://www.cbinsights.com/company/researchrabbit)

[^scoop]: Scoop Business. NZ Startup Litmaps Acquires US Rival And Raises $1M. 2025. [scoop.co.nz](https://www.scoop.co.nz/stories/BU2505/S00127/nz-startup-litmaps-acquires-us-rival-and-raises-1m-to-accelerate-ai-driven-research-worldwide.htm)

[^aarontay]: Aaron Tay. ResearchRabbit's 2025 revamp: iterative chaining without the clutter. Substack 2025. [aarontay.substack.com](https://aarontay.substack.com/p/researchrabbits-2025-revamp-iterative)

[^db]: Digl. The ResearchRabbit Database. ResearchRabbit Guides 2026. [learn.researchrabbit.ai](https://learn.researchrabbit.ai/en/articles/12454605-the-researchrabbit-database)

[^algo]: Digl. What's behind ResearchRabbit's search algorithm?. ResearchRabbit Guides 2025. [learn.researchrabbit.ai](https://learn.researchrabbit.ai/en/articles/12875619-what-s-behind-researchrabbit-s-search-algorithm)

[^how]: Digl. How does ResearchRabbit work?. ResearchRabbit Guides 2025. [learn.researchrabbit.ai](https://learn.researchrabbit.ai/en/articles/12454660-how-does-researchrabbit-work)

[^ai]: Nathan. How ResearchRabbit uses AI. ResearchRabbit Guides 2026. [learn.researchrabbit.ai](https://learn.researchrabbit.ai/en/articles/13545485-how-researchrabbit-uses-ai)

[^signals]: Signals. Research Integrity Badge and Key Partnerships. 2025. [research-signals.com](https://research-signals.com/2025/08/21/badge-announcement/)

[^pricing]: ResearchRabbit. Pricing. [researchrabbit.ai/pricing](https://www.researchrabbit.ai/pricing)
