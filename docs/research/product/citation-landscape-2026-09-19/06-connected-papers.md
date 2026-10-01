# Lane 06：Connected Papers 逆向

> **结论**：同类产品里逆向成本最低、架构最直白的一个——全部图数据走公开 REST 面（CORS `*`），连建图都无需登录；图本身是按月对 S2 全量语料预计算的静态产物，不是实时计算。护城河≈0，可完全复刻。
> **状态**：时点证据（2026-09-19 口径）——对第三方服务的时点观察，仅供互操作参考。
> **日期**：2026-09-19

## 产品定位

Connected Papers 2019 年创立于以色列特拉维夫，四人团队（Alex Tarnavsky Eitan、Eddie Smolyansky、Itay Knaan Harpaz、Sahar Perets），未融资或小额未披露轮[^tracxn][^istl]。免费档登录后 5 graphs/月全功能，付费 Academic/Business + Group Plans；机构按 IP 段识别（`is_premium_by_ip` 端点实测存在）。

## 核心算法（官方说法 + 数据印证）

官方 About 页原文[^about]：「analyze an order ~50,000 papers and select the few dozen with the strongest connections」；相似度指标 = **co-citation + bibliographic coupling**（共享引用/参考文献越多越相似）；力导向布局，节点选中时高亮到起点的最短相似路径；「Connected Papers is **not a citation tree**」——相似度边≠引用边。

实测图数据印证：每节点带 `cit_with_start`（与起点的共被引得分）与 `ref_with_start`（与起点的耦合得分）两个分量——Attention 论文图中 ResNet `cit=0.886/ref=0.0075`（高共被引低耦合），「CNN Is All You Need」`cit=7.8e-5/ref=1.14`（新论文尚无共被引但共享参考文献），两方向互补。**Prior works** = 图内被引最多者（重要祖先）；**Derivative works** = 引用图内节点最多者（综述/最新作），对应 `common_references`/`common_citations` 各取 top-10。

## 数据流重构（实测反推）

1. 语料 = S2 全量 dump 月度快照——图 `corpus_date` 字段 + 每版 `valid_until = creation+30d`，即**每月整库重算所有图**（versions 端点返回月度版本链）。
2. 建图参数（图 JSON 内 `parameters`，两次实测一致）：`total_nodes:40`、`num_neighbors:5`、`num_commons:10`、`max_load:100`、`spring_iterations:2000`——推测：每节点取 top-5 相似邻居、公共引用/参考各 top-10、服务端力导向布局 2000 轮。
3. 产出 ~40-41 节点、~800 条相似度边的小图，坐标 `pos:[x,y]` 服务端预算好，前端只 D3 渲染微调。
4. 检索是 S2 之上自建索引（`autocomplete/`、`search/` 返回格式自有含 abstract）。

## 协议面（全部实测免鉴权，CORS `*`）

站点首页直接暴露 `/rest-addr.json`（基址 `rest.prod.connectedpapers.com`）、`/adb2c-config.json`（Azure AD B2C 租户）、`/config.json`（分析 key）。

| 端点                                                    | 实测                                                |
| ------------------------------------------------------- | --------------------------------------------------- |
| `POST graph/<s2id>`                                     | **建图/取图一体端点，无鉴权**，1.2s 返回完整图      |
| `POST graph/<id1>+<id2>`                                | multi-origin 图                                     |
| `GET graph_no_build/<s2id>` / `fresh_graph_no_build/`   | 仅取已建图不触发构建                                |
| `GET versions/<s2id>/1` / `graph_version/<s2id>/<uuid>` | 月度版本链与历史版本                                |
| `GET title/`、`links/`、`autocomplete/`、`POST search/` | 元数据与检索（search 返回 `totalResults` 384 万级） |
| `POST is_premium_by_ip`                                 | 机构 IP 识别                                        |
| `POST graph_history`、`in_what_lists`、`paypro_*`       | auth：历史/收藏/计费                                |

**CPGR 二进制格式**（实测解码）：`"CPGR"` magic + u32 状态码 + u32 解压长度 + zlib(JSON)；状态码 `0x01`=OK、`0x08`=请求非法、`0x09`=论文不在库。**图 JSON schema**：`nodes`（~41 个，全量 S2 元数据 + `cit_with_start`/`ref_with_start`/`pos`/`path_length`）、`edges`（~799 条 `[src,dst,weight]`）、`common_citations`/`common_references`（各 top-10 附交集明细）、`common_authors`、`path_lengths`、`parameters`。

前端：Vue 3 SPA + D3 力导向（节点大小=被引数）+ web worker 池（CPGR 解压）+ MSAL Azure B2C。构建状态机 `unresolved → IN_QUEUE → IN_PROGRESS(%) → OK/ERROR/OVERLOADED`——服务端队列任务，但热门图全部命中预计算缓存直接 200。

## 可借鉴点

- **全预计算 + 静态服务**是核心洞察：S2 ~2 亿篇 × 40 节点图（压缩 ~60KB）≈ 12TB 存储，月度重算 ~50k 候选/篇相似度是批处理作业，服务侧沦为只读 KV——全端点免鉴权开放的成本趋零。
- `cit_with_start`/`ref_with_start` 双分量展示让「为什么相关」可解释，比单相似度分数信息密度高。
- prior/derivative 两榜 = 「图内被引 top」与「引用图内节点 top」，一次 group by 即得。

## 结论

架构可完全复刻：S2 dump → 出入边倒排 → 每篇算共被引 + 耦合加权相似度 → top-40 → spring layout → 压缩 blob 存 KV。他们只做到「单图 + 多源合并 + 月度版本」；实时构建、引用意图（scite 式）、embedding 混合相似度、流式渐进图都是空白空间。

### 参考文献

[^tracxn]: Tracxn. Connected Papers Company Profile. 2026. [tracxn.com](https://tracxn.com/d/companies/connectedpapers/__8w2xWhlgS-l0dACrdAVk5hwBnTPi31NSrf_COG79JN0)

[^istl]: Issues in Science and Technology Librarianship. Visual Exploration of Literature Using Connected Papers. 2023. [doi.org/10.29173/istl2760](https://doi.org/10.29173/istl2760)

[^about]: Connected Papers. About / FAQ（前端 bundle 内嵌文案实测提取）. [connectedpapers.com/about](https://www.connectedpapers.com/about/)
