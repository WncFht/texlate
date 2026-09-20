# Lane 16：arXiv 原生发现工具（paperscape / arxiv-sanity / Argo Scholar / GitHub 小件）

> **结论**：paperscape 是唯一做到全 arXiv 规模且持续运行的引用图地图——每日 TeX/PDF 自抽引用边、arXiv 内匹配率 38% 是该路线的已知基线，除抽取器闭源外整套服务形态（nbody C 布局+Go 瓦片+CSV dump+canvas 客户端）全 MIT；arxiv-sanity-lite 证明个性化推荐运维下限可到 $5/月；Argo Scholar 的「骑托管 API、探索即构图」是零基础设施起步的最优 UX。
> **状态**：时点证据（2026-09-19 口径）
> **日期**：2026-09-19

## 总览

| 工具 | 状态 | 机制 | 开源 | 引用图 |
| --- | --- | --- | --- | --- |
| paperscape.org | 活，宣称日更（blog 停在 2020-06） | Barnes-Hut N-body 布局，边=引用/被引 | 后端+客户端+数据全 MIT | 是（自建，TeX/PDF 抽取） |
| arxiv-sanity-preserver | 死（站点 502） | tf-idf 全文+用户库 SVM | MIT | 否 |
| arxiv-sanity-lite | 活 | tf-idf 摘要+per-tag SVM | MIT | 否 |
| Argo Scholar | 活 | 浏览器内增量构图，PageRank/Degree 映射 | MIT | 是（骑 S2 API） |
| CiteLens 等 GitHub 小件 | 多为课程/个人项目 | S2/OpenAlex API 拼装 | MIT 不等 | 部分 |

## paperscape —— 唯一的全 arXiv 引用图先例

Damien George（MicroPython 作者）与 Rob Knegjens 创建，2011 前后上线，至今仍是全 arXiv 引用图谱可视化**唯一做到全网规模且持续运行**的项目[^pscp-about]。

**数据面**（自建引用图，不走任何第三方 API）：引用边每天从 arXiv 的 TeX/LaTeX 与 PDF 源自行抽取，约在 arXiv 新 listing 公布后 3-4 小时完成更新；**抽取代码未开源**（backend 仓只有 nbody/tiles/webserver 三件）。抽取成功率公开（v2017.12：1991–2017 共 1,219,522 篇、38,464,630 条引用，匹配回 arXiv ID 14,726,797 条=**38%**）；分领域差异巨大——hep-lat 82%、hep-ph 81%、quant-ph/astro-ph 38%、math 仅 8%（数学大量引用 arXiv 外来源）[^pscp-data]。每年一份 CSV dump（含 authors/title/references，Zenodo）公开——现成的 arXiv 内引用边 ground truth，可校验任何自建抽取管线。

**布局算法**（`paperscape-backend/nbody/`，C ~5k 行，MIT）：三力模型——全局斥力 `F=M1·M2/r²`（带 falloff 远程衰减）、连边弹簧力（`r_rest=1.5·(rad1+rad2)`，`rad=sqrt(M/π)`）、近距指数斥力防重叠；**质量 `M=0.2+0.2·cites`**（被引数直接进质量与圆面积）；每轮迭代整体旋转小角度消 quadtree 伪影；Barnes-Hut 把 N² 斥力降到 O(N log N)，headless 模式支持增量更新（新论文插入已有布局继续松弛）[^pscp-nbody]。输入格式极简 `[{id, allcats, refs:[[refid,freq],...]}]`、输出 `[id,x,y,r]`——**布局引擎与数据源完全解耦**，喂任何引用图都出图。

**服务与渲染**：`tiles/`（Go）按 quadtree 切 `tiles/{depth}/{ix}/{iy}.png`+同路径 JSON，CDN 子域分流；`webserver/`（Go，wombat 框架）ajax 总线承载 meta/refs/cite/auth/tile 命令；客户端 CoffeeScript+RequireJS，canvas 渲染、缩放渐进显示关键词标签（标题/摘要词频自动抽取）、references/citations 可叠加成星状背景[^pscp-backend]。

## arxiv-sanity 系 —— 内容路线极简模板

**arxiv-sanity-preserver**（Karpathy 2015，已死）：arXiv API→PDF→pdftotext→bigram tf-idf 全文向量+预计算 sim_dict→每用户库训线性 SVM→Flask+sqlite+mongodb；管线偏重[^as-preserve]。

**arxiv-sanity-lite**（2021 重写，仍在线）：日轮询 arXiv API→tf-idf（只用摘要）→sqlitedict→per-tag SVM+SendGrid 每日邮件；Karpathy 自述跑在 $5/月 VPS 上约 30K 论文[^as-lite]。**轻量个性化推荐运维下限极低，但同样零引用图**。

## Argo Scholar —— 浏览器内增量引用探索

Poloclub（Georgia Tech）出品，MIT。完全前端应用：经 **S2 API** 按 CorpusID/关键词加节点，右键逐跳扩 citations/references；节点大小/颜色映射 PageRank 或 Degree（客户端现算）；快照保存整个图状态；数据 S2ORC API（ODC-BY）[^argo][^argo-gh]。模式价值：**不预建全图**，按需从托管 API 拉图，探索过程即构图过程——零后端数据成本。

## GitHub 小件扫描

CiteLens（引用者排序：Impact 45% OpenAlex 领域归一化+FWCI / Network 25% 局部 PageRank / Relevance 20% 语义 / Context 10% S2 influential，逐条 "why ranked" 解释）；mmaorc/citations（种子递归 5 层 DAG，默认只画 S2 highly-influential 边压规模）；citracer（关键词驱动引用链追踪+Sugiyama-by-year 布局）；ArXivFlow（端到端管线：四模型 embedding+ChromaDB+dense/BM25/引用重叠/实体重叠 RRF 融合）；arxiv-radar（sanity-lite 现代重写：pgvector+RRF+MCP 7 工具）。**基本都是 S2 API 薄壳，深度不足以提供算法增量**——但 CiteLens 的多信号排序配方（加权+逐条解释）是「比裸被引数更好的排序」的现成设计。

## 结论

可搬：paperscape 整套服务形态（除抽取器全 MIT）与其 38% 匹配率基线、paperscape-data 年 CSV、Argo 增量探索 UX、sanity-lite 极简运维模板、CiteLens 排序配方。不可搬：paperscape 引用抽取代码（恰好是各家最想抄的部分）、sanity-preserver 重管线；papers.cool/HF papers 的推荐与引用图无关属另一路线。

### 参考文献

[^pscp-about]: D. George, R. Knegjens. About Paperscape. blog.paperscape.org, 2013. [page_id=2](https://blog.paperscape.org/?page_id=2)
[^pscp-data]: Paperscape data dumps. GitHub/Zenodo 2018. [paperscape/paperscape-data](https://github.com/paperscape/paperscape-data)
[^pscp-backend]: Paperscape backend source. MIT. [paperscape/paperscape-backend](https://github.com/paperscape/paperscape-backend)
[^pscp-nbody]: N-body algorithm README, paperscape-backend/nbody/README.md.
[^as-preserve]: A. Karpathy. arxiv-sanity-preserver. MIT. [karpathy/arxiv-sanity-preserver](https://github.com/karpathy/arxiv-sanity-preserver)
[^as-lite]: A. Karpathy. arxiv-sanity-lite. MIT. [karpathy/arxiv-sanity-lite](https://github.com/karpathy/arxiv-sanity-lite)
[^argo]: K. Chaurasia et al. Argo Scholar: interactive graph exploration system. Poloclub, Georgia Tech.
[^argo-gh]: poloclub/argo-scholar. MIT. [github.com/poloclub/argo-scholar](https://github.com/poloclub/argo-scholar)
