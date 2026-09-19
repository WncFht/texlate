# 开源引用图谱工具源码调研

本轮把「基于引用图谱做论文发现」领域里真正开源、可逐行读实现的项目翻了一遍：**Citation Gecko**（gecko-react，React SPA）、**Local Citation Network**（LCN，Vue 单页 + 其姊妹版 Co*Citation Network）、**Zotero Cita**（嵌入 LCN 的 Zotero 插件，Wikimedia 资助）、**Scholia**（Wikidata SPARQL 驱动的学术画像站）、**litstudy**（荷兰 eScience Center 的 Python 文献计量包）。另实测了 OpenCitations Index API v2。GitHub 搜索未见其他高星同类——剩下的同类项目多为 0-1 star 的 AI 小作品，不具参考价值（实测 2026-09-19，`api.github.com` 搜索 `citation network papers`/`citation graph discovery literature` 两页结果）。

## 一、Citation Gecko（gecko-react）

### 概况

作者 Barnabas James Walker，MIT 协议，Zenodo DOI 存档（10.5281/zenodo.7068284），线上版 citationgecko.com[^gecko-readme]。React 16 SPA + 一个小 express server（server 只做 Zotero/Mendeley OAuth 代理，**所有学术数据都从浏览器直连第三方 API**，自己零后端数据层）。第三方库全 vendored（`src/third-party/`：d3 v4/v5、crossref.min.js、bibtexParse.js）。

### 数据流

- **seed 输入四条路**：BibTeX 上传（只收有 DOI 的条目）、Crossref 全文检索、Zotero collections（OAuth）、Mendeley（OAuth）[^gecko-readme]。
- **元数据与出边（references）**：`src/data-modules/crossref/index.js`——`GET https://api.crossref.org/works?rows=1000&amp;filter=doi:a,doi:b,...`，每 50 个 DOI 一批并行 `Promise.all`；`parsePaper` 取 `DOI/title[0]/author[0].family/date-parts/container-title[0]/is-referenced-by-count/reference[]`，reference 只保留 `DOI/article-title/author/year/journal-title/unstructured`。
- **入边（citations）**：`src/data-modules/open-citations/index.js`——对每个 `seed &amp;&amp; doi` 逐个 `GET https://w3id.org/oc/index/api/v1/citations/{doi}`（COCI Index API v1），解析 `edge.citing` 字段正则 `=&gt; (\S*)` 提 DOI。
- **种子搜索**：`api.crossref.org/works?query={q}&amp;rows=60`。
- **本地小后端**：`/services/zotero/login|getCollections|getItemsInCollection`、`/services/mendeley/*`，仅转发 api.zotero.org / api.mendeley.com 的 OAuth 调用。

### 构图与指标（`src/core/state/data.js`，约 190 行核心）

- `Papers` 字典 + `Edges` 数组；`matchPaper` 去重优先级：`microsoftID`（MAG 时代遗留）→ DOI（大小写不敏感）→ title+first-author-lastname 全等匹配；`merge` 时旧字段优先、seed 标记取或。
- 四个本地指标在 `metrics` 对象里，每次 updatePapers 全量重算：
    - `localCitedBy` / `localReferences`：图内入/出度；
    - **`seedsCitedBy`**：被多少个 seed 引用（局部共被引强度——「被 seed 们共同引用多→奠基作」）；
    - **`seedsCited`**：引用了多少个 seed（局部文献耦合强度——「引 seed 引得多→同领域新作」）。
- 这正是 README 里写明的推荐语义：「cited by a lot of seeds → foundational；cites a lot of seeds → recent worth reading」——**推荐 = 按这两个指标排序，不做任何 embedding**[^gecko-readme]。

### 可视化

两个视图：`force-graph`（d3，按 `seedsCitedBy`/`seedsCited` 两模式过滤节点与边，节点大小=指标值）与 `timeline`（自绘 SVG，年份分行、引用边连线）。列表视图含 "Recommended" 面板（按上述指标排序的非 seed 节点）。

### 借鉴点

整个「多源补全 + 本地图 + 双指标排序」闭环 ~600 行 JS，是纯前端方案的最小完整样本；DOI 归一与 title+author 兜底匹配的去重策略可直接抄。

## 二、Local Citation Network（LCN）

### 概况

作者 Tim Woelfle（巴塞尔大学/University Hospital Basel 医学背景），GPL-3，主仓 `LocalCitationNetwork/LocalCitationNetwork.github.io`（147 stars，实测 2026-09-19），当前版本 v1.32（2026-08-05 更新，活跃维护）。纯静态单页应用（GitHub Pages 托管），Vue 2 + Buefy + vis-network，库全部本地打包（作者刻意不用 CDN 防追踪）[^lcn-repo]。

### 数据源（`index.js` 前 500 行，四路可切换 API）

- **OpenAlex（默认）**：`api.openalex.org/works` + `mailto` 参数（polite pool）。单文献走 `/works/{id}?select=id,doi,title,authorships,publication_year,primary_location,biblio,referenced_works,cited_by_count,abstract_inverted_index,is_retracted,type,publication_date`；批量出边用 `filter=cited_by:id1|id2|...`（OR 最多 50 个 ID 一批）+ cursor 分页（per-page=200）；**入边（被谁引）用 `filter=cites:{id}`**——这是 LCN 拿 Top Citing 的关键技巧，不用逐条展开 cited_by_api_url[^lcn-src]。
- **Semantic Scholar**：`api.semanticscholar.org/graph/v1/paper/...`，三档策略——seed 全量出/入边走 `paper/{id}/references|?limit=1000&amp;offset=` 分页（phase=references/citations）；Top Cited/Citing 走 `paper/batch` POST（≤500 ids/次，selectFields 含 `references.paperId,citations.paperId`）。源码注释记了一个坑：**batch 端点 citations 总数上限 9999，会导致 Top Citing 算错**（s2-folks issue 199）；另一注释：单条 API 现在一律 429，所以逐条路径被注释停用[^lcn-src]。
- **Crossref**：`api.crossref.org/works?filter=doi:{id}&amp;select=DOI,title,author,issued,container-title,reference,is-referenced-by-count,abstract`——只有 references 没有 citations（Crossref 不公开 cited-by），所以 CR 模式没有 Top Citing。
- **OpenCitations**：`opencitations.net/index/api/v1/metadata/{dois}`——v1.30 changelog 标注「endpoint 疑似停服，暂禁用」[^lcn-changelog]。
- **Co*Citation Network API（实验）**：`openalex-query-api.scicore.unibas.ch/queries`（巴塞尔大学内部服务，POST `{dois, seed_set_title, rics_rank_cutoff}`，异步 job→result JSON）。这是 RICS（Ranked Indirect Citation Searching，OSF 研究协议 10.17605/OSF.IO/NPM2E）的实现——在直接引用之上加了**间接引用两档：coCited（共被引）与 coCiting（共引/耦合），rank=四者之和**，节点形状里 hexagon 就是间接档[^lcn-faq]。
- **Zotero Cita**：LCN 还能直接吃 Zotero Cita 插件导出的 JSON（`API === 'Zotero Cita'` 分支）。

### seed 定义与文件扫描

seed=source 文献的完整参考文献表，或用户粘贴/上传的自定义 ID 列表（DOI/PMID/OpenAlex/MAG/S2 id 自动识别：含 `/`→doi、纯数字→pmid、否则→openalex）。bookmarklet.js 支持 **17 家出版商页面 DOM 选择器**（wiley/nature/pnas/frontiers/nejm/oup/plos/cell/sage/jmir/sciencedirect/science/pubmed/ieee…）抽 `&lt;li&gt;` 引用条目，再用 Crossref 推荐正则 `10.\d{4,9}/[-._;()/:A-Z0-9]+[-_()/:A-Z0-9]+` 提 DOI——等于在 DOI 层面自建 seed 参考文献表（`customListOfReferences`）[^lcn-bookmarklet]。

### 算法（`computeSeedArticlesRelationships` + `retrievedSeedArticles`）

- 两趟调用：先取 seed 们各自的 references/citations，构建 `referenced`（某文献被多少 seed 引）与 `citing`（某文献引了多少 seed）两个局部计数表；
- **Top Cited** = `referenced` 里非 seed 的 top-N（默认排序 `referenced[b].length - referenced[a].length`）；**Top Citing** = `citing` 里非 seed、非 cited 的 top-N；
- 之后按需再调 references/citations 端点拉这些 top-N 的完整元数据；All Cited/All Citing 模式则直接批量拉全量（OA `filter=cited_by:` / S2 references 端点）；
- 完整度估计（completeness tooltip）：OA=有 reference-list 的 seed 比例；S2/CR 再乘 referenceCount vs 实际解析出 DOI 的比例——**对「数据不全」给了量化指标**，比大多数同类产品诚实[^lcn-faq]。

### 可视化与交互

- 引用网：vis-network **hierarchical 布局按年份分层**（`level=years.indexOf(article.year)`，新上旧下；方向 DU 或 LR 可切），节点大小=`rankNumber`（局部 cited+citing+coCited+coCiting 计数），形状区分：source=◆、seed=●、Top Cited=▲、Top Citing=▼、间接=⬡；边按 coCited/coCiting 画虚线+中段菱形箭头。节点可按年份/期刊着色。
- 共作者网：barnesHut 物理布局，节点=seed 集内高频作者（默认自适应阈值保证 ≤50 作者），边宽=合作篇数；点作者/边反查过滤文献表——**网络与表格双向联动**。
- 导出：CSV/RIS/JSON 整网（`fromJSON` URL 参数可重新载入，cache repo `LocalCitationNetwork/cache` 存示例图）；localStorage 缓存最多 5 个 tab。

### 借鉴点

LCN 是「引用图发现」的最完整开源参照：**双指标推荐 + 四档 API 抽象层（统一 wrapper 签名 `wrapper(ids, responseFunction, phase, retrieveCited, retrieveCiting)`）+ 完整度估计 + 分层布局 + JSON 互通**。它的 `openAlexWrapper`/`semanticScholarWrapper` 是「怎么用最少的 API 调用拼出局部引用图」的教科书实现（50-id OR 批、cursor、batch 端点上限坑都标了注释）。

## 三、Zotero Cita（zotero-cita）

### 概况

Zotero 插件，Wikimedia Foundation WikiCite 资助项目，把引用元数据与 LCN 可视化塞进 Zotero[^cita-readme]。三大模块：citations 元数据管理（存 note attachment）、Wikidata 双向同步（P2860 "cites work"，需 OAuth 2.0 consumer token 才能写）、LCN/co-authorship 网嵌入（`Local-Citation-Network/` 目录直接 vendor 了 LCN 构建产物）。

### 数据源（`src/cita/indexers/` 四个 indexer）

- `opencitations.ts`：`w3id.org/oc/meta/api/v1/metadata/{doi}`（OC Meta）+ **`opencitations.net/index/api/v2/references/{doi}`（Index v2）**；
- `openalex.ts`：works 查询；**特别处理 arXiv——DOI 形如 `10.48550/arxiv.{id}` 时把 OpenAlex work 映射回 arXiv ID**（`work.doi.replace("https://doi.org/10.48550/arxiv.", "")`），并过滤自引边（罕见但存在，注释里给了例子 W2963003673）[^cita-src]；
- `semantic.ts`：`paper/{id}?fields=externalIds`、**`paper/search/match?query={title}`（标题模糊匹配拿 paperId——免费的 citation resolution）**、`paper/batch?fields=references,externalIds,title,references.externalIds,references.title`，支持 `x-api-key` 头；
- `crossref.ts`：`api.crossref.org/works/{doi}` 单条 + `filter=` 批量（select DOI,title,reference,references-count），还有 `doi.crossref.org/openurl?pid=...&amp;multihit=true` 的 OpenURL 解析路径。

### 匹配器（`src/cita/matcher.ts`）

条目对齐逻辑：ISBN/DOI/QID 冲突即否、年份差 &gt;1 即否、要求 first author 姓+首字母命中——**多源引用边并库的 PID 消歧参考实现**。

### 借鉴点

「一次取 4 个 index、按 PID 消歧、缺口互填」是离线补全引用边的工程模板；它还能**把校正后的引用边写回 Wikidata**——引用图不只吃数据还能反哺。

## 四、Scholia（WDscholia/scholia）

### 概况

Finn Årup Nielsen 主导的 Flask webapp（GPL-3，257 stars，Toolforge 托管 scholia.toolforge.org），页面数据 100% 来自 Wikidata 实时 SPARQL（新版走 QLever 端点 qlever.scholia.wiki）[^scholia-repo]。

### 结构

每个 aspect（work/author/venue/topic/chemical/award/event…）一个 html 模板 + 一组 `.sparql` 模板文件（`scholia/app/templates/`，300+ 个），`{{ q }}` 占位符填 QID，`#defaultView:Table` 指令给 WDQS 前端直接渲染表/图。citation 面：

- **`wdt:P2860`（"cites work"）是唯一边源**。实测 `work_citations.sparql` 全文：内层 `?citing_work wdt:P2860 target:` 取引文献，顺带算每篇引文献的被引数排序，`LIMIT 1000`；外层 `INCLUDE %result + wikibase:label` 取标签[^scholia-sparql]。
- **CiTO 引用意图**：`ask_work_cito.sparql` 查 `pq:P3712 / wdt:P31 wd:Q96471816; ps:P2860` ——Wikidata 用 statement 限定词存 "has citation (P3712) → cites work + CiTO 意图类型"（如 citesAsAuthority/disputes），是公开数据里**唯一带引用意图标注的大规模源**（但覆盖量远小于 COCI）。
- 作者页：`author_citations-by-year`、`author_most-cited-works`、`author_most-citing-authors` 等都是 GroupBy-P2860 聚合，单条 SPARQL 即成图。

### 借鉴点

证明了「一个 SPARQL 端点 + 模板化查询页」就能撑起学术画像站——自建图的 serving 形态里最轻的一种；P2860 也可作为自建边的又一补充源（且能写回）。

## 五、litstudy（nlesc/litstudy）

### 概况

Netherlands eScience Center 出品，JOSS 发表论文的 Python 文献计量包（pip 装，v1.0.6）[^litstudy-pypi]。定位不是在线发现服务而是**离线分析工具箱**：`DocumentSet` 抽象 + pandas 后端，在 notebook 里做系统综述/文献计量。

### 数据源（`litstudy/sources/`）

arxiv、bibtex、csv、crossref、dblp、ieee、ris、scopus、scopus_csv、semanticscholar、springer 共 11 个 source。S2 用 `api.semanticscholar.org/v1/paper/`（legacy v1）+ `/graph/v1/paper/search`，带磁盘 cache；Crossref 走 works API。

### 网络算法（`litstudy/network.py`，432 行，公式全在这）

- `build_citation_network(docs)`：docs 间直接引用有向图（networkx DiGraph，DocumentMapping 做 ref→node 解析）；
- **`build_cocitation_network`**：对每个 doc 的 reference 列表（已映射到集合内节点）取所有对 (i,j) 累加——边权=集合内共被引次数；`max_edges` 截顶（默认 `2*len(docs)`），因为共被引网稠密[^litstudy-src]；
- **`build_coupling_network`**：docs 两两 reference 集合求交，边权=共享文献数（耦合强度，**未做 Jaccard/余弦归一**，原始计数）；
- `build_coauthor_network`：作者共现网；
- `calculate_layout`：自写 force layout（gravity 参数）；`plot_network` 走 matplotlib/seaborn 渲染，节点颜色/大小/形状由 docs.data 列驱动。

### 借鉴点

共被引与耦合的**最小正确实现**（各 ~40 行），以及「reference 列表是算一切局部指标的唯一输入」这一设计：拿到 OpenAlex referenced_works 或 LaTeX 抽出的引用列表后，litstudy 这套函数直接可复现 Top-Cited/Top-Citing/共被引/耦合全部指标。

## 六、实测：OpenCitations Index API v2

`GET https://opencitations.net/index/api/v2/references| /citations/{id}`，id 必须带方案前缀（`doi:` 等，裸 DOI 报 400 并附示例——实测 2026-09-19）。返回数组每条：`oci`（Open Citation Identifier）、`citing`/`cited`（多 ID 并列：`omid:br/... doi:... openalex:W... pmid:...`）、`creation`（引用发生年）、`timespan`、`journal_sc`/`author_sc`（期刊/作者自引标志）。比 v1 多了 openalex/pmid 映射与自引标注——**自引标志对推荐排序去噪直接可用**。LCN 标记停用的是 `/index/api/v1/metadata/{dois}` 端点，v2 references/citations 活着（实测）。

## 可直接借鉴的实现清单

1. **最小发现闭环（Gecko 模式）**：seeds→Crossref 批量 metadata+references→OpenCitations 逐 DOI citations→本地图→`seedsCitedBy`/`seedsCited` 双指标排序。零后端，~600 行。
2. **四源抽象层（LCN 模式）**：统一 `(ids, phase, retrieveCited, retrieveCiting)` wrapper，OA 用 `cites:`/`cited_by:` 过滤+cursor、S2 用 batch POST（≤500 ids，citations≤9999 坑）、CR 只有出边；Top Cited/Top Citing=局部计数排序+去重；完整度=有 refs 的 seed 占比×ID 命中率。
3. **间接引用扩展（RICS/Co*Citation 模式）**：在直引基础上加共被引/耦合两档候选，rank=直引+间接四项之和——就是 LCN coCited/coCiting 列与 hexagon 节点。
4. **多源补全+消歧（Cita 模式）**：OC Meta/Index v2 + OpenAlex + S2（search/match 标题解析 + batch references）+ Crossref，PID 冲突否决+年差≤1+首作者匹配；OpenAlex arXiv DOI（10.48550/arxiv.*）记得映射回 arXiv ID；剔除自引边。
5. **SPARQL 模板页（Scholia 模式）**：若自建图落 Wikidata/RDF 形态，一个查询端点+模板页即成站；Wikidata P2860 是可写回的边源，CiTO 是唯一的意图标注。
6. **局部图指标（litstudy 模式）**：reference 列表→共被引矩阵（doc 内 refs 两两累加）/耦合矩阵（refs 交集计数），networkx 构图+max_edges 截顶，40 行/算法。
7. **分层时间布局**：LCN 的 year-level hierarchical + 形状编码（◆source/●seed/▲cited/▼citing/⬡indirect）是引用图可读性的标杆做法；Gecko 的 force-graph+timeline 双视图是轻量替代。

## 探针产物

- `tmp/citation-survey/oss-tools/gecko-react/` — Citation Gecko 完整 clone（depth 1）
- `tmp/citation-survey/oss-tools/Local-Citation-Network/` — LCN clone（timwoelfle/Local-Citation-Network 镜像路径，内容同官方 LocalCitationNetwork.github.io 仓）
- `tmp/citation-survey/oss-tools/zotero-cita/` — Zotero Cita 完整 clone（含 vendor 的 LCN）
- `tmp/citation-survey/oss-tools/litstudy/` — litstudy 完整 clone
- `tmp/citation-survey/oss-tools/query.py`、`requirements.txt` — Scholia 关键源文件（raw.githubusercontent 抓取；整仓 clone 因 github TLS 不稳未成）
- `tmp/citation-survey/oss-tools/oc-v2-refs.json`、`oc-v2-cits.json` — OpenCitations Index API v2 实测响应
- `tmp/citation-survey/oss-tools/gh-search1.json`、`gh-search2.json`、`gh-search4.json` — GitHub 仓库搜索原始结果

### 参考文献

[^gecko-readme]: Walker, B. J. CitationGecko README &amp; source (gecko-react). GitHub/Zenodo 2019-2023. [github.com/CitationGecko/gecko-react](https://github.com/CitationGecko/gecko-react); DOI 10.5281/zenodo.7068284.
[^lcn-repo]: Woelfle, T. Local Citation Network README/CHANGELOG. GitHub. [github.com/LocalCitationNetwork/LocalCitationNetwork.github.io](https://github.com/LocalCitationNetwork/LocalCitationNetwork.github.io).
[^lcn-src]: Local-Citation-Network `index.js`（v1.32，本次 clone 实读：semanticScholarWrapper/openAlexWrapper/crossrefWrapper/coCitationNetworkAPI/computeSeedArticlesRelationships/initCitationNetwork）.
[^lcn-changelog]: Local-Citation-Network CHANGELOG v1.30/v1.32（OpenCitations v1 metadata 端点停用记录、Co*Citation API 上线记录）.
[^lcn-faq]: LCN web app FAQ（index.html 内嵌）：Top Cited/Top Citing/Completeness/Co*Citation 定义；RICS 协议 DOI 10.17605/OSF.IO/NPM2E；TARCiS 引用检索术语 DOI 10.1136/bmj-2023-078384.
[^lcn-bookmarklet]: Local-Citation-Network `bookmarklet.js`（17 家出版商引用列表 DOM 选择器 + Crossref DOI 正则）.
[^cita-readme]: Zotero Cita README. GitHub. [github.com/zotero-cita/zotero-cita](https://github.com/zotero-cita/zotero-cita); WikiCite grant: meta.wikimedia.org WikiCite addon for Zotero.
[^cita-src]: zotero-cita `src/cita/indexers/{openalex,semantic,crossref,opencitations}.ts`、`src/cita/matcher.ts`（本次 clone 实读）.
[^scholia-repo]: Nielsen, F. Å. et al. Scholia. GitHub/Toolforge. [github.com/WDscholia/scholia](https://github.com/WDscholia/scholia); scholia.toolforge.org.
[^scholia-sparql]: scholia `scholia/app/templates/work_citations.sparql`、`ask_work_cito.sparql`（raw.githubusercontent 实读，2026-09-19）；Wikidata P2860/P3712 属性定义.
[^litstudy-pypi]: litstudy 1.0.6, PyPI metadata &amp; repo. [pypi.org/project/litstudy](https://pypi.org/project/litstudy); [github.com/nlesc/litstudy](https://github.com/nlesc/litstudy); JOSS DOI 10.21105/joss.xxxx（具体编号未验证）.
[^litstudy-src]: litstudy `litstudy/network.py`、`litstudy/sources/semanticscholar.py`（本次 clone 实读）.
