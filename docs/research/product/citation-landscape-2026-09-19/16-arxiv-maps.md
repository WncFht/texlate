# arXiv 原生发现工具调研

lane 范围：专吃 arXiv 的地图/推荐类工具，源码级逆向 + 现状核实。调研时间 2026-09-19。

## 总览

| 工具 | 状态 | 机制 | 开源 | 引用图 |
| --- | --- | --- | --- | --- |
| paperscape.org | 活，宣称日更（实测站点 200，后端 Go+wombat 应答正常；最新 blog 停在 2020-06） | Barnes-Hut N-body 布局，边=引用/被引 | **后端+客户端+数据全 MIT** | 是（自建，TeX/PDF 抽取） |
| arxiv-sanity-preserver | **死**（实测 arxiv-sanity.com 502） | tf-idf 全文 + 用户库 SVM | MIT | 否 |
| arxiv-sanity-lite | 活（arxiv-sanity-lite.com） | tf-idf 摘要 + per-tag SVM | MIT | 否 |
| Argo Scholar | 活（poloclub.github.io/argo-scholar 实测 200） | 浏览器内增量构图，PageRank/Degree 视觉映射 | MIT | 是（骑 S2 API） |
| CiteLens 等 GitHub 小件 | 多为课程/个人项目 | S2/OpenAlex API 拼装 | MIT 不等 | 部分 |

## paperscape.org —— 唯一的「全 arXiv 引用图」先例

由 Damien George（MicroPython 作者）与 Rob Knegjens 创建，2011 前后上线，至今是全 arXiv 引用图谱可视化的**唯一一个做到全网规模且持续运行**的项目[^pscp-about][^pscp-blog]。

### 数据面（自建引用图，不走任何第三方 API）

- 引用边**不从 S2/OpenAlex 拿**，而是每天处理 arXiv 的 TeX/LaTeX 与 PDF 源自行抽取，每日更新约在 arXiv 新 listing 公布后 3-4 小时完成[^pscp-about]。抽取代码**未开源**（backend 仓库只有 nbody/tiles/webserver 三件，抽取管线不在内，实测全仓 grep 无 bib/extract 相关实现）。
- 抽取成功率公开（v2017.12，1991–2017 共 1,219,522 篇、38,464,630 条引用，匹配回 arXiv ID 14,726,797 条 = **38%**）；分领域差异巨大：hep-lat 82%、hep-ph 81%、quant-ph 38%、astro-ph 38%、math 仅 8%——原因是数学文献大量引用 arXiv 外来源[^pscp-data]。
- 每年一份 CSV 数据 dump（1991–2017，含 authors/title/references，Zenodo DOI 10.5281/zenodo.10052）公开可下——这是现成的 arXiv 内引用边数据集，可作 baseline 对照[^pscp-data]。

### 布局算法（N-body，C 实现，已开源，实测可读）

`paperscape-backend/nbody/`（C，约 5k 行）实现三力模型，README 公式完整[^pscp-backend]：

- **全局斥力（anti-gravity）**：`F = M1·M2/r²` 方向向外，带 `falloff = min(1, 1e6/r²)` 远程衰减防过度发散；
- **连边弹簧力**：`F = LS·(r − r_rest)/r`，`r_rest = 1.5·(rad1+rad2)`，半径 `rad = sqrt(M/π)`；
- **近距斥力**：节点重叠时的指数斥力，保证圆不互相覆盖；
- **质量** `M = 0.2 + 0.2·cites`（被引数直接进质量与圆面积）；
- 每轮迭代把图整体旋转一个小角度，消 quadtree 分割造成的伪影；
- Barnes-Hut 四叉树把 N² 斥力降到 O(N log N)，百万节点可算；headless 模式支持**增量更新**（新论文插入已有布局继续松弛），GUI 模式用于调参[^pscp-nbody]。

输入格式极简：`[{id, allcats, refs:[[refid,freq],...]}]` JSON 或 MySQL；输出 `[id,x,y,r]` 布局 JSON。即**布局引擎与数据源完全解耦**——喂任何引用图都能出图。

### 服务与渲染

- 瓦片化：`tiles/`（Go）按 quadtree 切 `tiles/{depth}/{ix}/{iy}.png` + 同路径 JSON 数据；CDN 子域 `tile1-4.paperscape.org` 分流（实测主站 200，瓦片子域 DNS 存活）。
- `webserver/`（Go，基于作者的 wombat 框架）：`/wombat` ajax 总线，客户端字符串含 `meta`/`refs`/`cite`/`auth`/`tile` 命令（从 `js/app/pscp.js` 提取，实测裸 GET 回 "Unknown request"，参数协议需按客户端调用形态构造）。
- 客户端 CoffeeScript+RequireJS（`paperscape-mapclient`）：canvas 渲染、缩放渐进显示关键词标签（标题/摘要词频自动抽取）与作者；点击节点出 metadata 面板，可把 references/citations 叠加成星状背景；`my.paperscape.org` 提供个人收藏夹。
- 还有 heatmap 叠加层、new-papers 搜索、`paperscape.org` 全站无注册墙。

## arxiv-sanity 系 —— 内容路线的极简模板

**arxiv-sanity-preserver**（Karpathy，2015）：全程无引用图。管线 `fetch_papers.py`（arXiv API）→ `download_pdfs` → `parse_pdf_to_text`（pdftotext）→ `analyze.py`（**bigram tf-idf 全文向量 + 预计算 sim_dict 余弦近邻**）→ `buildsvm.py`（每个用户库训一个线性 SVM 做个性化排序）→ Flask/Tornado + sqlite + mongodb + twitter_daemon 社交信号[^as-preserve]。站点现已死（实测 502），代码停滞 2017，管线偏重（pdftotext、MongoDB、ImageMagick）。

**arxiv-sanity-lite**（2021 重写，仍在线）：`arxiv_daemon.py` 日轮询 arXiv API → `compute.py` 算 tf-idf（只用摘要）→ sqlitedict 存库 → per-tag SVM 推荐 + SendGrid 每日邮件。Karpathy 自述在 $5/月 Nanode 上跑 ~30K 论文[^as-lite]。**证明轻量个性化推荐的运维下限极低，但同样零引用图**。

## Argo Scholar —— 浏览器内增量引用探索

Poloclub（Georgia Tech，Polo Chau 组）出品，MIT 开源，发表为可视化系统论文[^argo]。完全前端应用：

- 通过 **Semantic Scholar API** 按 CorpusID/关键词加节点，右键 "Add 5 Paper Citations/References" 逐跳扩图；
- 节点大小/颜色映射 **PageRank 或 Degree**（客户端现算）；
- 内建 Deep Learning、Spatial Computing 示例网络；快照（snapshot）保存整个图状态与视觉配置；数据用 S2ORC API（ODC-BY）[^argo-gh]。

模式价值：**不预建全图**，按需从托管 API 拉图，探索过程即构图过程——零后端数据成本。

## GitHub 小件扫描

| 项目 | 机制要点 | 数据源 |
| --- | --- | --- |
| [CiteLens](https://github.com/0Sa-ad0/CiteLens) | 给「引用了种子论文的论文」打分排序：Impact 45%（OpenAlex 领域归一化被引百分位+FWCI）+ Network 25%（局部 PageRank）+ Relevance 20%（语义相似）+ Context 10%（S2 influential 标记），逐条给 "why ranked" 解释 | S2+OpenAlex+arXiv |
| [mmaorc/citations](https://github.com/mmaorc/citations) | 从一篇种子出发递归 5 层画引用 DAG；大小=被引、颜色=新旧；默认只画 S2 "highly influential" 边压缩图规模 | S2 |
| [citracer](https://github.com/marcpinet/citracer) | 关键词驱动的引用链追踪：PDF 里定位关键词句→找就近引文→下载被引论文→递归 N 层；`--reverse` 用 S2 citation contexts 反向走「谁引了它」；Sugiyama-by-year 布局 + PageRank/betweenness | arXiv/S2/OpenReview/多 preprint |
| [ArXivFlow](https://github.com/DAShaikh10/ArXivFlow) | 端到端管线：arXiv+S2 抓取→数据质量门→NER 标注→SPECTER2/SciNCL/BGE/Qwen 四模型 embedding 入 ChromaDB→dense+BM25+引用重叠+实体重叠 RRF 融合→FastAPI+Next.js | arXiv+S2 |
| [arxiv-radar](https://github.com/deepweather/arxiv-radar) | arxiv-sanity-lite 的现代重写：pgvector 语义搜索+RRF、tag 推荐、S2 引用图端点、MCP server 暴露 7 个工具 | arXiv+S2 |
| paper-finder / PaperLens / arxiv-scout / Semantic-vis | 免登录多源搜索、浏览器内 embedding 重排、LLM curation+引用图、S2 引用可视化——均为小型个人项目 | arXiv/S2/Crossref |

## 已有结论引用（不重查）

- **alphaXiv similar-papers**：公开端点 `GET /papers/v3/{pgid}/similar-papers` 存在但覆盖低且 noisy，随机论文命中率差——见同目录 `2026-09-19-alphaxiv-reverse.md`。
- **papers.cool**：个性化完全在客户端（关键词云权重 + localStorage），`?sort=词云` 拼 URL 做服务端排序，**无引用图**——见 `2026-09-19-paperscool-reverse.md`。
- **Semantic Scholar 论文页推荐**：SPECTER embedding 系（本调研 ds-s2 lane 覆盖细节）。
- **HuggingFace papers**：社区 bookmark/upvote 排序，非引用；**Papers with Code**：按 task/method 关联，非引用图。

## 可搬与不可搬清单

可直接搬：

1. **paperscape 的整套服务形态**：nbody C 布局引擎（Barnes-Hut、增量更新、三力公式全文档化）+ Go 瓦片/webserver + 按年 CSV 数据 + canvas 客户端——除引用抽取闭源外全 MIT，是「全 arXiv 引用图地图」的完整开源骨架；其 38% 的 arXiv 内引用匹配率是 LaTeX/PDF 抽取路线的已知基线。
2. **Argo Scholar 的增量探索 UX**：不建全图、骑 S2 API、探索即构图，适合零基础设施起步。
3. **arxiv-sanity-lite 的极简运维模板**：$5/月量级，tf-idf+SVM 兜底方案。
4. **CiteLens 的多信号排序配方**（Impact/Network/Relevance/Context 加权 + 逐条解释）是「比裸被引数更好的排序」的现成设计。
5. **paperscape-data 年 CSV**：现成的 arXiv 内引用边 ground truth，可用来校验任何自建抽取管线。

不可搬/只留教训：

1. paperscape 引用抽取代码闭源——恰好是各家都想抄的部分；
2. arxiv-sanity-preserver 已死且管线重——直接看 lite；
3. papers.cool / HF papers 的推荐与引用图无关，属于另一路线；
4. 小件项目基本都是 S2 API 薄壳，深度不足以提供算法增量。

## 探针产物

`tmp/citation-survey/arxiv-maps/` 下：`paperscape-backend/`（nbody C + tiles/webserver Go 源码 clone）、`paperscape-data/`（1991–2017 引用 CSV dump）、`paperscape-mapclient/`（CoffeeScript 客户端）、`arxiv-sanity-preserver/`、`arxiv-sanity-lite/`（两个 clone）、`paperscape_home.html`、`pscp_about.html`、`pscp_blog.html`、`psc_mapgen.html`、`pscp.js`（线上客户端 bundle）、`probe_*.out`/`wombat_*.out`（端点探针原始输出）、`sanity_repo.html`、`gh_org.html`。

### 参考文献

[^pscp-about]: D. George, R. Knegjens. About Paperscape. blog.paperscape.org, 2013. [page_id=2](https://blog.paperscape.org/?page_id=2)
[^pscp-blog]: Paperscape development blog. [blog.paperscape.org](https://blog.paperscape.org/)
[^pscp-data]: Paperscape data dumps. GitHub/Zenodo 2018. [paperscape/paperscape-data](https://github.com/paperscape/paperscape-data)
[^pscp-backend]: Paperscape backend source. MIT. [paperscape/paperscape-backend](https://github.com/paperscape/paperscape-backend)
[^pscp-nbody]: N-body algorithm README, paperscape-backend/nbody/README.md. 实测于 2026-09-19 clone 阅读。
[^as-preserve]: A. Karpathy. arxiv-sanity-preserver. MIT. [karpathy/arxiv-sanity-preserver](https://github.com/karpathy/arxiv-sanity-preserver)
[^as-lite]: A. Karpathy. arxiv-sanity-lite. MIT. [karpathy/arxiv-sanity-lite](https://github.com/karpathy/arxiv-sanity-lite)
[^argo]: K. Chaurasia et al. Argo Scholar: interactive graph exploration system. Poloclub, Georgia Tech. 系统实测 200 于 2026-09-19.
[^argo-gh]: [poloclub/argo-scholar](https://github.com/poloclub/argo-scholar), MIT.
