# 调研任务：引用图谱驱动的论文推荐——数据生态、做法与规模化路径（texlate 长期能力调研）

## 背景与目标

texlate 是开源「arXiv LaTeX 源 → LLM 段落级翻译 → ctex 重编译中文 PDF」项目，仓库在 `~/src/texlate`（产品代码 `src/texlate/`，web 前端 `web/`，路线图 `docs/03-roadmap.md` 与 `docs/06–10` 规格，可随时翻看）。

产品方向已扩展：**不止翻译，还要基于引用数与引用图谱做论文推荐/发现**——目标是最终拥有类似 alphaXiv similar-papers、Connected Papers 那一档的发现层能力，而不是只给某个功能选个数据源。本轮是纯调研：把「这件事要怎么做、做多大规模、别人怎么做的」彻底搞清楚，为后续架构决策供弹药。

已验证可直接引用的前提：

- alphaXiv 的 references/overview 等富产物覆盖率很低（随机论文 ~7–20%，老 ID 0%），只能机会型白嫖——逆向细节见同目录 `2026-09-19-alphaxiv-reverse.md`。
- texlate 有每篇论文的 LaTeX 源（`.bbl`/`.bib`/`\bibitem`），引用边可自抽——这是相对 PDF 侧玩家的结构优势。

## 调研范围（三块，自由展开）

**数据源层**：OpenAlex、Semantic Scholar（API + datasets/S2ORC）、OpenCitations、Crossref、arXiv 官方渠道、领域库（INSPIRE-HEP、ADS、PubMed、DBLP）、Lens.org 等——谁有引用边、被引数、arXiv ID（含 `astro-ph/` 老 ID）、bulk dump、license、更新延迟。

**算法与产品层**：Connected Papers、ResearchRabbit、Litmaps、Inciteful、scite.ai、alphaXiv 各自怎么算「相关论文」（co-citation / bibliographic coupling / SPECTER 类 embedding / 混合）；托管推荐 API 现状（S2 recommendations、OpenAlex related_works 等）；embedding 资产有哪些可直接用。

**工程层**：真要做到全 arXiv（~250 万篇、上亿条边）规模需要什么——bulk dump 多大、存储形态、预计算 vs 按需、更新节奏；S2ORC / OpenAlex snapshot / GROBID 这些现成管线各是什么角色；「自建全图 / 骑托管 API / 混合」三条路线的真实成本对比。

## 产出

中文报告写到 `docs/research/product/2026-09-19-citation-landscape.md`：数据源对照表 + 各产品/管线的规模化做法 + 给 texlate 的路线分析（自建/托管/混合的取舍与建议）。外部断言用脚注、文末列参考文献；实测验证过的标实测，查不到的标「未验证」。探针脚本和原始输出放 `tmp/` 自建目录，报告里指路。

## 工作方式

WebSearch / WebFetch 调研 + `curl` 直接探 API 验证（限流、字段、覆盖率主张尽量实测，别抄二手数字）。环境注意：有 http 代理，`raw.githubusercontent.com`/`api.github.com` 不稳；fish 下 grep 常空输出，解析用 `python3`；**scratch 一律写仓库 `tmp/` 下自建目录，不要写 `/tmp`**（usrquota，写满全炸）。

规模上不必缩手：该下载的 metadata 样本、该压测的 API 都可以试；判断题不设限，但报告必须落到「texlate 下一步该怎么走」的具体建议上。
