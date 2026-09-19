# Connected Papers 逆向调研

对 https://www.connectedpapers.com/ 做了「官网文本取证 + JS bundle 反编译 + 无鉴权端点实测」三层逆向。结论：**这是同类产品里逆向成本最低、架构最直白的一个**——全部图数据走公开 REST 面裸奔，CORS 为 `*`，连「建图」都无需登录即可触发；图本身是按月对 Semantic Scholar 全量语料**预计算**的静态产物，不是实时计算。

## 公司与团队

Connected Papers 2019 年创立于以色列特拉维夫（CB Insights 记 2020），创始四人：Alex Tarnavsky Eitan、Eddie Smolyansky（CEO）、Itay Knaan Harpaz、Sahar Perets（UX/产品），另有 Ofer Mustigman 负责 DevOps[^tracxn][^istl]。Tracxn/LinkedIn 口径为未融资或仅小额未披露轮，员工 4 人[^tracxn][^linkedin]。官网 About 自述「朋友间的周末 side project 起家」[^about]。

## 产品与商业模式

- **免费档**：未登录 2 张图试用；登录后 **5 graphs/月**，且「all features included」——Prior/Derivative works、multi-origin、saved papers、graph history 全给（bundle 内定价页原文实测）。
- **付费档**：Academic / Business 个人月付 + Group Plans（团队席位），价格经 `paypro_*` 端点动态下发（未抓到具体数字，历史上约 $6/$20 每月量级——**未验证**）。
- **机构访问**：`POST is_premium_by_ip` 端点实测存在——按 IP 段识别机构订阅，返回 `is_institutional_ip` 标志（实测 200）。
- **配额计数**：客户端 localStorage `graph_visit_timestamps` 记录本月已看图的 paper_id（`Ez()` 函数按月初过滤），服务端另有真值；`add_to_historty/`（是的，URL 里就是 historty 拼错）POST 上报。

## 核心算法（官方说法 + 数据印证）

官方 About 页原文（bundle 内 Vue 渲染函数中提取，实测）：

&gt; "To create each graph, we analyze an order ~50,000 papers and select the few dozen with the strongest connections to the origin paper."
&gt; "Our similarity metric is based on the concepts of **Co-citation** and **Bibliographic Coupling**. According to this measure, two papers that have highly overlapping citations and references are presumed to have a higher chance of treating a related subject matter."
&gt; "Our algorithm then builds a **Force Directed Graph**… Upon node selection we highlight the shortest path from each node to the origin paper in similarity space."
&gt; "Our database is connected to the **Semantic Scholar Paper Corpus** (licensed under ODC-BY)."
&gt; "Connected Papers is **not a citation tree**." —— 相似度边 ≠ 引用边，没互引的论文也能强连接。

实测图数据（见下）完全印证：每个节点带 `cit_with_start`（与起点的共被引得分）与 `ref_with_start`（与起点的文献耦合得分）两个分量——Attention 论文图中，ResNet `cit_with_start=0.886/ref=0.0075`（高共被引低耦合），「CNN Is All You Need」`cit=7.8e-5/ref=1.14`（新论文尚无共被引但共享参考文献），两个方向互补（实测 2026-09-19）。

**Prior works** = "papers most commonly cited by the papers in the graph"（重要祖先）；**Derivative works** = "papers that cited many of the papers in the graph"（综述或最新相关作）。对应图 JSON 里的 `common_references` / `common_citations` 各取 top-10。

## 数据流重构（实测反推）

1. **语料**：Semantic Scholar 全量 dump，月度快照——图 `corpus_date: 2026-06-24`、每版 `valid_until = creation+30d`，即**每月整库重算一遍所有图**（实测 versions 端点返回月度版本链）。
2. **建图参数**（每个图 JSON 内 `parameters` 字段，两次实测一致）：`total_nodes: 40`、`num_neighbors: 5`、`num_commons: 10`、`max_load: 100`、`spring_iterations: 2000`。推测语义：每个节点取 top-5 相似邻居、公共引用/参考列表各 top-10、单图载荷上限 100（边或候选数）、服务端 force-directed 布局跑 2000 轮。
3. **产出**：~40-41 节点、~800 条相似度边的小图，节点坐标 `pos:[x,y]` **服务端预计算好**，前端只负责 D3 渲染与交互微调（bundle 里另有 post_processor 力导向参数 `6e-4/.03/160` 做客户端 tick）。
4. **检索**：`autocomplete/` 与 `search/` 是他们自建的 S2 之上索引（返回格式自有、含 abstract 与分页 totalResults），不是裸代理 S2 API。

## 协议面（全部实测 2026-09-19，均无需凭证，CORS `Access-Control-Allow-Origin: *`）

站点首页直接暴露三个配置文件：`/rest-addr.json`（REST 基址 `rest.prod.connectedpapers.com` + ppg 基址 `iprest.connectedpapers.com`，两域实测响应同一服务）、`/backhpa-addr.json`、`/adb2c-config.json`（Azure AD B2C 租户 `ConnectedPapersUsersAdProd`）、`/config.json`（Amplitude/GA key，Amplitude 走自家代理域名上报）。

| 端点 | 方法/形态 | 实测结果 |
| --- | --- | --- |
| `GET title/&lt;s2id&gt;` | JSON | 200，返回 `{paperId,title}` |
| `GET links/&lt;s2id&gt;` | JSON | 200，`{s2Url,title,arxivId}` 外链 |
| `GET graph_no_build/&lt;s2id&gt;` | **CPGR 二进制** | 200，64KB，仅取已建图不触发构建 |
| `GET fresh_graph_no_build/&lt;s2id&gt;` | CPGR | 同上 fresh 变体 |
| `POST graph/&lt;s2id&gt;` | **CPGR 二进制** | **200 无鉴权**，1.2s 返回完整图；这是建图/取图一体端点 |
| `POST graph/&lt;id1&gt;+&lt;id2&gt;` | CPGR | 200，**multi-origin 图**，`parameters.paper_ids` 为数组 |
| `GET versions/&lt;s2id&gt;/1` | JSON | 200，`graph_versions[]`：uuid/creation_time/corpus_date/valid_until(30d)/is_visual |
| `GET graph_version/&lt;s2id&gt;/&lt;uuid&gt;` | CPGR | 指定历史版本 |
| `GET autocomplete/&lt;q&gt;` | JSON | 200 无鉴权，`matches[]={id,title,authorsYear}` |
| `POST search/&lt;q&gt;/&lt;page&gt;` | JSON | 200 无鉴权，返回含 abstract 的结果，`totalResults` 384 万级（"attention"） |
| `POST is_premium_by_ip` | JSON | 200，返回 `is_institutional_ip` 标志 |
| `POST graph_history` / `add_to_historty/&lt;id&gt;/&lt;ts&gt;` | auth | 历史记录 |
| `POST in_what_lists/&lt;ids&gt;` / `get_reading_list/&lt;list&gt;` | auth | 收藏列表 |
| `POST log_open_in`、`report/&lt;type&gt;` | JSON | 行为埋点/反馈 |
| `paypro_*`（magic_link/suspend/renew/change_product）+ `admin_*` | auth | 计费与组管理 |
| `/api/redirect/{arxiv,doi,pmid,s2}/&lt;id&gt;` | GET | 200，SPA 侧跳图 |
| `/badge/connected_papers_badge.js` | JS | 200，第三方页面嵌入 badge（doi 属性 → 缩略图带 `arxiv_thumbnails/` 随机 18 张） |

**CPGR 二进制格式**（实测解码）：`"CPGR"` magic + u32 状态码 + u32 解压长度 + zlib(JSON)。状态码实测：`0x01`=OK、`0x08`=请求非法（id 编码错）、`0x09`=论文不在库。即「图文件格式」就是一个带码的压缩 JSON 信封。

**图 JSON schema**：`nodes`（~41 个，全量 S2 元数据：abstract/authors/tldr/citations_length/references_length/externalIds{ArXiv,CorpusId,DBLP,MAG}/fieldsOfStudy/venue/year/`cit_with_start`/`ref_with_start`/`pos[x,y]`/`path_length`）、`edges`（~799 条 `[src,dst,weight]` 相似度边，权重 3e-6~2.15）、`common_citations`/`common_references`（各 top-10，附 `local_references`/`local_citations` 交集明细与 `edges_count`）、`common_authors`（作者重叠）、`path_lengths`（各节点到起点的最短相似路径长）、`parameters`、`start_id`、`current_corpus_date`、`creation_time`。

## 前端与基建

Vue 3 SPA（SFC + 作用域样式）+ D3 力导向渲染（`sim_node_circles`/`sim_edges`/`sim_labels`，`citations_to_radius` 节点大小=引用数）+ web worker 线程池（`connected_papers_threadpool`，`tab_shared_queue`，大概率为 CPGR 解压/解析）+ MSAL Azure B2C 登录（另捆了 Firebase auth SDK，可能遗留或备用）+ Amplitude/GA/Hotjar 分析。状态机：`unresolved → ADDED_TO_QUEUE → IN_QUEUE → IN_PROGRESS(%) → OK/ERROR/OVERLOADED/WAITING_LOCAL`——构建是服务端队列任务，但**热门图全部命中预计算缓存，直接 200 回包**。

## 可复制性评估

其「护城河」几乎为零，架构可完全复刻：

- **数据**：S2 全量 dump（月更）→ 出边/入边各建倒排索引 → 对每篇论文算「共被引得分 + 耦合得分」的加权相似度（`cit_with_start`/`ref_with_start` 形态疑似带归一化，权重区间看像 overlap/√(a·b) 类——**未验证**）→ top-40 节点 → spring layout 2000 轮 → CPGR 式压缩 blob 存 KV。
- **成本模型**：核心洞察是**全预计算 + 静态服务**。S2 ~2 亿篇 × 40 节点图（压缩后 ~60KB）≈ 12TB 存储级别，月度重算 ~50k 候选/篇的相似度是批处理作业（Spark/单机分片均可），服务侧沦为只读 KV——这才敢全裸奔零鉴权。
- **前端**：D3 force graph + 最短路径高亮 + prior/derivative 两个榜单，工作量在交互细节而非算法。
- **可差异化处**：他们只做到「单图 + 多源合并 + 月度版本」；实时构建、引用意图（scite 式）、embedding 混合相似度、流式渐进图都是他们没有的空间。

## 探针产物

`tmp/citation-survey/connected-papers/`：`bundle.js`（2.7MB 前端包）、`graph.bin`+`graph.dec`（Attention 论文图 CPGR 原件与解压 JSON）、`niche.bin`、`multi2.bin`（多源图）、`fake.bin`（0x09 错误帧）、`title.json`/`links.json`/`versions.json`/`ac.json`（各 JSON 响应样例）、`badge.js`。

### 参考文献

[^tracxn]: Tracxn. Connected Papers Company Profile. 2026. [tracxn.com/d/companies/connectedpapers](https://tracxn.com/d/companies/connectedpapers/__8w2xWhlgS-l0dACrdAVk5hwBnTPi31NSrf_COG79JN0)
[^linkedin]: LinkedIn. Connected Papers company page. 2026. [linkedin.com/company/connectedpapers](https://www.linkedin.com/company/connectedpapers)
[^istl]: Issues in Science and Technology Librarianship. Visual Exploration of Literature Using Connected Papers. 2023. [doi.org/10.29173/istl2760](https://doi.org/10.29173/istl2760)
[^about]: Connected Papers. About / FAQ（bundle 内嵌文案实测提取）. [connectedpapers.com/about](https://www.connectedpapers.com/about/)
