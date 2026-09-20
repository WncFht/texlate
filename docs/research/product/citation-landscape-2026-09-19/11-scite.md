# Lane 11：scite.ai 逆向

> **结论**：scite 的护城河不是算法而是数据资产与出版商协议——整条管线（Unpaywall 收割→GROBID/Pub2TEI→biblio-glutton→SciBERT）全部构建在开源组件上；有全文（尤其 LaTeX 源）时完全可以复刻，且分类这一步在 LLM 时代成本骤降。
> **状态**：时点证据（2026-09-19 口径）——对第三方服务的时点观察，仅供互操作参考。
> **日期**：2026-09-19

## 该产品是什么

scite 2018 年创立于纽约布鲁克林（Josh Nicholson CEO），把「A 引 B」升级成「带上下文+意图分类+章节位置的语句级三元组」（Smart Citations）。**2023-11 被 Research Solutions（NASDAQ: RSSS）以 $14.8M 收购**（4.11× ARR $3.6M，50% 现金+50% 股票+earnout）[^sec][^merger]。资金史：NSF/NIH SBIR 两笔[^sbir][^nih]。资产：32M+ 全文源 / 190M+ 出版物元数据 / 1.6B+ 语句[^data][^qa]。定价：Free/Basic $20/Pro $50（自助 API key + MCP credits）/Team/Enterprise[^pricing]。

## 核心管线（论文级拆解）

技术细节全部来自其 QSS 2021 论文[^qss]，四步：

1. **全文获取双轨**：OA 走 PubMed Central + Unpaywall 全量收割（开源 `biblio-glutton-harvester`）；订阅内容走与出版商签的**全文索引协议**（30+ 家：Wiley/BMJ/Sage/Cambridge UP/IOP/Frontiers/AAAS 等）——这是真壁垒。
2. **引注与文献条目识别**：PDF 走 **GROBID**（~5 PDF/s @4 核）；出版商 JATS XML 走 **Pub2TEI** 归一成同一 TEI；全管线 11 个 ML 模型[^ccc]。
3. **条目→DOI 匹配**：**biblio-glutton**（GROBID 生态书目匹配服务，对 Crossref 全量模糊匹配，F=95.4）。端到端引用上下文解析到 DOI 比例：**PDF 源 ~70%、PMC JATS XML ~95%**——PDF 管线丢 ~30% 语句。
4. **语句分类**：输入「引注句+前后各一句」窗口，输出 supporting/disputing/mentioning 三类。训练数据 ~5 万条双人专家标注（自研 doccano 部署）；模型演进到**微调 SciBERT** 定版；类别极不均衡（92.6% mentioning/6.5% supporting/0.8% disputing），过采样+预测层调权使各类 precision>80%，disputing F 58.97%。反直觉事实：**十几亿条语句的分类推理跑在单台 GTX 1080Ti 上**——推理成本极低[^qss]。外部独立评测对稀有类有争议（Bakker 2023 vs scite 反驳）[^bakker][^reply]。

数据分野要记：**语句级产物只来自有全文的 ~32M 篇；更大的 citation 图（~190M source→target 对）来自 Crossref 参考文献列表**[^qa]。Editorial notices（撤稿/关切/更正）聚合 Crossref+PubMed+Retraction Watch+自建检测器四源[^notices]。

## 产品面与 API

- **Scite Report**：每篇 DOI 一页——tally 分解 + 逐条语句（上下文/章节/置信度），**tally（语句数）与 citingPublications（出版物数）双口径分离**是设计精华；cited-by-sections 按引注所在章节统计（Intro vs Discussion 权重不同）。
- **Reference Check**：传 PDF→逐条参考文献风险报告（撤稿/被反驳），已集成进期刊投稿流程[^nature]。
- **Assistant**：RAG + 自校验（检索→重排→带内联引用答案→事实核查），rankBy 含 supporting-citations/journal-rank[^handbook]。
- **SJI 期刊榜**：USI=supporting/(supporting+contrasting)、SI=ln(引用数×USI^指数)，≥100 条分类语句才有指数[^sjp]。
- **Badge/Zotero 插件/浏览器扩展全开源**（`scite-extension`/`scite-badge`/`scite-zotero-plugin`）；MCP server 25 工具 + 4 预置工作流[^mcp]。
- API 67 端点（OpenAPI 3.1）：公共免鉴权面 `GET/POST /papers`、`/tallies`（≤500 DOI/次）、`/search/match_reference`；语句级边 `api_partner/citations/citing/{doi}` 是 special access；推荐端点 `recommend-papers/{doi}` 算法未披露[^docs]。

## 可借鉴点

借鉴价值最高的设计：tally/citingPublications 双口径；section-level 统计；editorial notices 四源聚合；references（纯边）/citations（语句级）命名分层；SJI USI/SI 公式；异步任务 API（poll 模式）；MCP 工具+prompt 工作流封装。

## 结论

管线全部是开源件（GROBID/Pub2TEI/biblio-glutton/DeLFT/Unpaywall harvester——co-author Patrice Lopez 即 GROBID 作者），今天即可重建。真正壁垒三个：① 30+ 出版商全文协议（自建者只有 OA ~30% 或 arXiv LaTeX 源——**LaTeX 源其实更优：引注定位零误差、ref 匹配近 100%、章节结构原生**）；② ~5 万条标注（2026 年可用 LLM 蒸馏低成本复刻）；③ 1.6B 语句存量。有全文者语句级引文图是引用图谱产品最高档资产——边之上叠「在哪引、怎么引、挺还是踩」三层信息。

### 参考文献

[^qss]: Nicholson JM, Mordaunt M, Lopez P, et al. scite: A smart citation index that displays the context of citations and classifies their intent using deep learning. *Quantitative Science Studies* 2021;2(3):882-898. [bioRxiv](https://www.biorxiv.org/content/10.1101/2021.03.15.435418v1)
[^docs]: Scite API Documentation. docs.scite.ai 2026. [docs.scite.ai](https://docs.scite.ai/)
[^ccc]: Adding Context to Research with "Smart Citations". Copyright Clearance Center blog. [copyright.com](https://www.copyright.com/blog/adding-context-to-research-with-scite-smart-citations/)
[^merger]: Agreement of Merger, Research Solutions × Scite Inc. SEC EDGAR 2023-11-24. [sec.gov](https://www.sec.gov/Archives/edgar/data/1386301/000110465923121108/tm2331467d1_ex2-1.htm)
[^sec]: Research Solutions 8-K/ex99-2（$14.8M EV、4.11× ARR）. SEC EDGAR 2023-11-27. [sec.gov](https://www.sec.gov/Archives/edgar/data/1386301/000110465923121108/tm2331467d1_ex99-2.htm)
[^sbir]: NSF SBIR Phase I award 1913619. 2019.
[^nih]: scite awarded NIH SBIR Fast-Track grant. scite blog 2019-10. [scite.ai](https://scite.ai/blog/scite-awarded-nih-sbir-fast-track-grant-eeccadec97f4)
[^data]: Scite Data page. [scite.ai/data](https://scite.ai/data)
[^qa]: Alfasoft Online Demo Days 2025 Scite Q&A. [alfasoft.com](https://alfasoft.com/files/odd/2025/Scite-QA-EN.pdf)
[^nature]: New bot flags scientific studies that cite retracted papers. Nature Index News. [nature.com](https://www.nature.com/nature-index/news/new-bot-flags-scientific-research-studies-that-cite-retracted-papers)
[^notices]: A new, open system for the automated detection of retractions and other editorial notices. scite blog 2022. [scite.ai](https://scite.ai/blog/2022-10-19_automated-notice-detection)
[^sjp]: Content-aware rankings: a new approach to rankings in scholarship. arXiv:2504.05206, 2025. [arxiv.org](https://arxiv.org/pdf/2504.05206)
[^mcp]: Scite MCP overview + tools + prompts. [docs.scite.ai/mcp](https://docs.scite.ai/mcp/overview)
[^pricing]: Pricing and plans. [docs.scite.ai](https://docs.scite.ai/pricing-and-plans)
[^handbook]: Assistant by scite — LLM Prompt Handbook. Research Solutions. [researchsolutions.com](https://www.researchsolutions.com/hubfs/LLM-Prompt-Handbook-Scite-Assistant.pdf)
[^bakker]: Bakker C, Theis-Mahon N, Brown SJ. Evaluating the accuracy of scite. *Hypothesis* 2023;35(2). [indianapolis.iu.edu](https://journals.indianapolis.iu.edu/index.php/hypothesis/article/download/26528/25101/54274)
[^reply]: Rife S, Nicholson J, Uppala A, Rosati D. Reply to Bakker et al. *Hypothesis* 2025;37(1). [indianapolis.iu.edu](https://journals.indianapolis.iu.edu/index.php/hypothesis/article/view/28018)
