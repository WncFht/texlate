# Lane 12：AI 检索系论文发现产品（Elicit / Consensus / Undermind / SciSpace / Keenious / Scinapse）

> **结论**：六家排成一条光谱——四家把引用只当标量质量信号（图结构零使用），Undermind 显式沿引用链做 agentic 探索，Scinapse 整体押注引用图且其 arXiv:2605.07158 论文给出「embedding 找得到同主题、找不到同议程」的关键实证。
> **状态**：时点证据（2026-09-19 口径）
> **日期**：2026-09-19

## 各家定位与数据面

**Elicit**（Ought 孵化的独立公司，AI 系统性文献综述）：语料 138M（S2 主力周更 + OpenAlex + PubMed 去重）[^elicit-corpus]。管线两阶段：自研 embedding 全库排序（被引数、发表时间作为排序特征之一）→ LLM 对 top 1000 精排/筛选[^elicit-search]。产品面 Find Papers/Systematic Review/Extract Data/Research Agent；API + 官方 MCP，Pro $49/月[^elicit-api][^elicit-pricing]。

**Consensus**（波士顿 2021，「AI-native 版 Google Scholar」）：语料宣称 220M（S2+OpenAlex+ 自爬）[^consensus-library]。三段式 IR：embedding+BM25 混合召回 → top 1500 按质量信号重排（**被引数**、SJR、时间）→ 大模型精排 top 20[^consensus-how]。标志功能 Consensus Meter：微调开源模型把 top 5–20 篇结论分类 Yes/No/Possibly 汇总成仪表[^consensus-meter]。Pro $20/月[^consensus-plans]。

**Undermind**（YC 孵化，两位 MIT 物理博士）：agentic 学术搜索的代表——管线三件套 **semantic embeddings + citations + LLM reasoning**：embedding 召回候选后 LLM 像人类研究者一样**沿引用链探索**、反思进展、决定下一步直到收敛；用 capture-recapture 统计法估计覆盖率（「已找到约 90%」）[^undermind-whitepaper][^aarontay]。语料 S2 ~2 亿篇（标题 + 摘要级），单次搜索 3–6 分钟[^casrai-undermind]。白皮书宣称找到的相关论文是 GS 前 5 页的 10 倍[^undermind-whitepaper]。Pro $16/月[^undermind-site]。

**SciSpace**（前身 Typeset.io，「检索→阅读→写作」全流程）：语料 280M+、含 50M+ OA 全文 PDF；向量检索+rerank；Copilot 的 related papers 是「与选中文字相似」的内容 embedding，**非引用图**[^scispace-aaai][^casrai-scispace]。Premium $12/月[^theaiselect]。

**Keenious**（挪威，文档级推荐 + 图书馆机构市场）：语料治理最透明——OpenAlex 全量 ~5.1 亿 → 类型过滤 ~2.88 亿 → 人工抽样评级剔除非学术源 → 记录级质检得 **~1.81 亿**终索引；精选索引内重算 FWCI[^keenious-index][^keenious-openalex]。检索=embedding（标题 + 摘要入库向量）+BM25 rank fusion + 学术信号微调 + research areas 聚类[^keenious-search]。引用图只用 FWCI 标量形式。Plus $10/月[^keenious-pricing]。

**Scinapse / Pluto Labs**（首尔）：**唯一整体押注引用图的产品**——数据=MAG+PubMed+PMC+OpenAlex+S2+ 自爬 250M+[^scinapse-data]；自研 agent 跑在引用图上，官网明写定位「Text embeddings find the right topic but miss the specific research agenda. Our citation graph — bibliographic coupling and co-citation — recovers the signal they miss」[^scinapse-site]。Basic $23/Pro $36/Max $52/月[^scinapse-pricing]。

## 关键实证：Topic Is Not Agenda

Pluto Labs 的 arXiv:2605.07158 是本调研最重要的实证[^pluto-paper]：全量 OpenAlex 引用表（~25 亿条）在 358 万篇论文上建**增广引用图**——直接引用 + 文献耦合（≥3 共同引用、Salton 加权、剔除被引超 500 的热门 refs）+ 共被引（≥3 共同施引、剔除施引超 200 的综述型），三层合并 1.53 亿边（均值度 85.5）；Leiden CPM 两级社区（L1 子领域/L2 研究议程）。结论：**四个 SOTA embedding（Gemini/Qwen3-8B/Qwen3-0.6B/SPECTER2）在 L1 有 45–52% top-10 同区率，但 L2 议程级只剩 15–21%**——每 10 篇语义近邻里约 8 篇不在同一研究议程，SPECTER2 这种引用对比训练的反而最差；而换到 top-1 命中率口径看，「BM25+ 被引数重排」这种刻意简单的探针拿 **59.6% L2 命中**，比最强 embedding（Gemini 50.6%）高 9 个点[^pluto-paper]。第三方评注认为 L2 分区 ground-truth 稳健性待同行评审[^pith-review]。

## 可借鉴点

两条路线的盲区互补：embedding 路线对「语义措辞」覆盖好但对权威度无先验、议程粒度命中仅 15–21%；引用图路线对新文冷启动差、构建成本高。可见的收敛方向是**混合：召回用 embedding+BM25（保新文覆盖与模糊查询），精排/扩展用引用图（保议程一致性与权威度），LLM 只做理解与合成**——Undermind 的引用链追踪与 Consensus 的质量信号重排分别是这条线的两种工业实现。

## 结论

AI 检索系证明两件事：引用数据即使只作标量（被引数/FWCI）也是排序标配；而「LLM 推理×引用链」（Undermind）与「全引用图+agent」（Scinapse）两条重投入路线都被产品化验证——纯 embedding 检索不是终态。

### 参考文献

[^elicit-search]: Elicit. Paper Search — How does Elicit's AI search work. [elicit.com/solutions/search](https://elicit.com/solutions/search)

[^elicit-corpus]: Elicit Help Center. Elicit's source for papers. 2026. [support.elicit.com](https://support.elicit.com/en/articles/14758040-elicit-s-source-for-papers)

[^elicit-api]: Elicit. Elicit API Reference. [docs.elicit.com](https://docs.elicit.com/)

[^elicit-pricing]: Elicit. Pricing. [elicit.com/pricing](https://elicit.com/pricing)

[^consensus-how]: Consensus Help Center. How Consensus works. [help.consensus.app](https://help.consensus.app/en/articles/9922673-how-consensus-works)

[^consensus-meter]: Consensus Help Center. The Consensus Meter. [help.consensus.app](https://help.consensus.app/en/articles/10069920-the-consensus-meter)

[^consensus-plans]: Consensus Help Center. Subscription Plans. [help.consensus.app](https://help.consensus.app/en/articles/10087865-subscription-plans)

[^consensus-library]: Consensus. Consensus Library Primer. [consensus.app](https://consensus.app/home/blog/consensus-library-primer/)

[^undermind-whitepaper]: Hartke T, Ramette J. Benchmarking the Undermind Search Assistant. [undermind.ai/whitepaper.pdf](https://www.undermind.ai/whitepaper.pdf)

[^undermind-site]: Undermind. Product site & v2 benchmark. [undermind.ai](https://www.undermind.ai/)

[^casrai-undermind]: CASRAI. Undermind: What It Is and How Its Deep Search Agent Works. 2026. [casrai.org](https://casrai.org/guides/undermind-ai)

[^aarontay]: Tay A. Undermind.ai — a different type of AI agent style search optimized for high recall?. 2024. [aarontay.substack.com](https://aarontay.substack.com/p/undermindai-different-type-of-ai-agent)

[^scispace-aaai]: SciSpace. SciSpace Copilot: Empowering Researchers through Intelligent Reading Assistance. AAAI 2024. [doi.org/10.1609/aaai.v38i21.30578](https://doi.org/10.1609/aaai.v38i21.30578)

[^casrai-scispace]: CASRAI. SciSpace: What It Is and How Deep Review Works. 2026. [casrai.org](https://casrai.org/guides/scispace)

[^theaiselect]: TheAISelect. SciSpace Review 2026. [theaiselect.com](https://theaiselect.com/en/tools/scispace)

[^keenious-search]: Keenious Help Center. How Search Works in Keenious. [help.keenious.com](https://help.keenious.com/en/articles/169371-how-search-works-in-keenious)

[^keenious-openalex]: Keenious Help Center. How Keenious Uses OpenAlex. [help.keenious.com](https://help.keenious.com/en/articles/203843-understanding-our-data-source-how-keenious-uses-openalex)

[^keenious-index]: Keenious Help Center. How Keenious Curates Its Index. 2026. [help.keenious.com](https://help.keenious.com/en/articles/699209-how-keenious-curates-its-index)

[^keenious-pricing]: Keenious. Pricing（2026-09-19 实测）. [keenious.com/pricing](https://keenious.com/pricing)

[^scinapse-site]: Pluto Labs. Scinapse product page. [pluto.im/product/scinapse](https://www.pluto.im/product/scinapse)

[^scinapse-data]: Pluto Labs. About Our Data. [about.scinapse.io/about_our_data](https://about.scinapse.io/about_our_data)

[^scinapse-pricing]: Scinapse. Plans & Pricing. [scinapse.io/pricing](https://www.scinapse.io/pricing)

[^pluto-paper]: Yoo J. Topic Is Not Agenda: A Citation-Community Audit of Text Embeddings. arXiv:2605.07158. [arxiv.org/html/2605.07158](https://arxiv.org/html/2605.07158)

[^pith-review]: Pith Review. Review of arXiv:2605.07158. [pith.science/paper/2605.07158](https://pith.science/paper/2605.07158)
