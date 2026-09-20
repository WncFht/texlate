# Lane 10：开源引用图工具源码画像（Gecko / LCN / Zotero Cita / Scholia / litstudy）

> **结论**：五个开源件从「600 行纯前端闭环」到「四源抽象层」到「PID 消歧多源补全」各管一段，全部源码级可读；litstudy 给出 BC/CC 最小正确实现，LCN 是最完整参照。
> **状态**：时点证据（2026-09-19 口径）
> **日期**：2026-09-19

## Citation Gecko（gecko-react，MIT）

React SPA + 小 express server（只做 Zotero/Mendeley OAuth 代理，学术数据全从浏览器直连第三方 API）[^gecko-readme]。数据流：seed 四路输入（BibTeX/Crossref 检索/Zotero/Mendeley）→ Crossref `works?filter=doi:a,doi:b,...` 批量拉元数据+references（50 DOI/批）→ OpenCitations `index/api/v1/citations/{doi}` 逐 DOI 拉入边 → 本地图。核心 ~190 行：Papers 字典 + Edges 数组，去重优先级 MAG ID→DOI→title+首作者姓；**双指标 `seedsCitedBy`（被多少 seed 引=奠基作）/`seedsCited`（引了多少 seed=同领域新作）排序推荐，零 embedding**。整个闭环 ~600 行 JS，是纯前端方案的最小完整样本。

## Local Citation Network（GPL-3，活跃维护 v1.32）

巴塞尔大学 Tim Woelfle，纯静态 Vue 2 单页 + vis-network[^lcn-repo]。**四源抽象层是教科书实现**：统一 `wrapper(ids, responseFunction, phase, retrieveCited, retrieveCiting)` 签名——OpenAlex 用 `filter=cited_by:id1|id2`（≤50 ID/批）+cursor 拉入边、`filter=cites:{id}` 是拿 Top Citing 的关键技巧；S2 用 `paper/batch` POST（≤500 ids，源码注释标了 citations≤9999 上限坑）；Crossref 只有出边；实验性 Co*Citation API 实现 RICS 间接引用（coCited/coCiting 两档，rank=四者之和）[^lcn-src]。算法=两趟调用构 `referenced`/`citing` 局部计数表，Top Cited/Top Citing 取非 seed top-N；**完整度估计**（有 refs 的 seed 占比×ID 命中率）比大多数同类产品诚实[^lcn-faq]。可视化标杆：vis-network 按年份分层 hierarchical 布局，形状编码（◆source/●seed/▲cited/▼citing/⬡indirect）；bookmarklet 支持 17 家出版商页面 DOM 抽引用条目[^lcn-bookmarklet]。

## Zotero Cita（Wikimedia 资助）

Zotero 插件，三大模块：引用元数据管理、Wikidata P2860 双向同步（OAuth 写回）、内嵌 LCN[^cita-readme]。**4 个 indexer**：OC Meta/Index v2、OpenAlex（特别处理 `10.48550/arxiv.*` DOI 映射回 arXiv ID + 过滤自引边）、S2（`paper/search/match` 标题模糊匹配是免费的 citation resolution + batch references）、Crossref[^cita-src]。**matcher.ts 是 PID 消歧参考实现**：ISBN/DOI/QID 冲突即否、年差>1 即否、要求首作者姓+首字母命中。「一次取 4 index、按 PID 消歧、缺口互填」是离线补全引用边的工程模板；还能把校正后的边写回 Wikidata——引用图不只吃数据还能反哺。

## Scholia（GPL-3，Toolforge 托管）

Flask webapp，页面数据 100% 来自 Wikidata 实时 SPARQL[^scholia-repo]。每 aspect 一个模板 + 300+ 个 `.sparql` 模板文件；**`wdt:P2860`（cites work）是唯一边源**；CiTO 引用意图经 statement 限定词存储（citesAsAuthority/disputes 等），是公开数据里唯一大规模引用意图标注（覆盖量远小于 OC）[^scholia-sparql]。证明「一个 SPARQL 端点 + 模板化查询页」就能撑起学术画像站——最轻的 serving 形态。

## litstudy（JOSS，Python 包）

荷兰 eScience Center 的离线文献计量工具箱：`DocumentSet` 抽象 + pandas，11 个 source（arxiv/bibtex/crossref/dblp/ieee/scopus/S2 等）[^litstudy-pypi]。`network.py` 432 行给出**最小正确实现**：直接引用有向图；共被引网=对每个 doc 的 refs 列表两两累加（`max_edges` 截顶）；耦合网=docs 两两 refs 求交（原始计数未归一）；共著网[^litstudy-src]。各 ~40 行 networkx——拿到 reference 列表后这套函数直接可复现 Top-Cited/Top-Citing/BC/CC 全部指标。

## 可直接借鉴的实现清单

1. 最小发现闭环（Gecko 模式）：seeds→Crossref 批量→OC 逐 DOI→本地图→双指标排序，~600 行零后端。
2. 四源抽象层（LCN 模式）：统一 wrapper + 各源批查技巧（`cites:`/`cited_by:` 过滤、S2 batch 坑）+ 完整度指标。
3. 间接引用扩展（RICS）：直引 + coCited/coCiting 两档，rank=四项之和。
4. 多源补全+消歧（Cita 模式）：4 indexer + PID 消歧 + `10.48550/arxiv.*` 映射 + 剔自引边 + 写回 Wikidata。
5. SPARQL 模板页（Scholia 模式）：自建图落 RDF 时一个端点+模板页即成站。
6. 局部图指标（litstudy 模式）：refs 列表→BC/CC 矩阵，40 行/算法。
7. 分层时间布局：LCN year-level hierarchical + 形状编码是引用图可读性标杆。

## 结论

开源侧不缺实现——缺的是把它们合到一个全 arXiv 规模的持久图服务上。OC Index API v2 实测存活（`references|/citations/{doi:...}` 带 oci/openalex 映射 + 自引标志），v1 metadata 端点已停用。

### 参考文献

[^gecko-readme]: Walker B.J. CitationGecko README & source (gecko-react). GitHub/Zenodo 2019-2023. [github.com/CitationGecko/gecko-react](https://github.com/CitationGecko/gecko-react)
[^lcn-repo]: Woelfle T. Local Citation Network README/CHANGELOG. GitHub. [github.com/LocalCitationNetwork/LocalCitationNetwork.github.io](https://github.com/LocalCitationNetwork/LocalCitationNetwork.github.io)
[^lcn-src]: Local-Citation-Network `index.js` v1.32（2026-09-19 clone 实读）.
[^lcn-faq]: LCN web app FAQ（Top Cited/Top Citing/Completeness/Co*Citation 定义；RICS 协议 DOI 10.17605/OSF.IO/NPM2E）.
[^lcn-bookmarklet]: Local-Citation-Network `bookmarklet.js`（17 家出版商引用列表 DOM 选择器 + DOI 正则）.
[^cita-readme]: Zotero Cita README. GitHub. [github.com/zotero-cita/zotero-cita](https://github.com/zotero-cita/zotero-cita)
[^cita-src]: zotero-cita `src/cita/indexers/*.ts`、`src/cita/matcher.ts`（2026-09-19 clone 实读）.
[^scholia-repo]: Nielsen F.Å. et al. Scholia. GitHub/Toolforge. [github.com/WDscholia/scholia](https://github.com/WDscholia/scholia)
[^scholia-sparql]: scholia `work_citations.sparql`、`ask_work_cito.sparql`（2026-09-19 实读）.
[^litstudy-pypi]: litstudy 1.0.6. [pypi.org/project/litstudy](https://pypi.org/project/litstudy); [github.com/nlesc/litstudy](https://github.com/nlesc/litstudy)
[^litstudy-src]: litstudy `litstudy/network.py`、`litstudy/sources/semanticscholar.py`（2026-09-19 clone 实读）.
