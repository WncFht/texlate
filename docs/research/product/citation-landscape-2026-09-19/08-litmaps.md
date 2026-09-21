# Lane 08：Litmaps 逆向

> **结论**：本质是把 Crossref+S2+OpenAlex 三家开放元数据合并去重后自建 2.7 亿节点引用图、再以异步 search job 提供互联度推荐的服务——数据管道是主要资产，算法本身直白，record schema（内嵌边数组+多源 ID）与 Monitor（持久化发现查询）可直接抄。
> **状态**：时点证据（2026-09-19 口径）——对第三方服务的时点观察，仅供互操作参考。
> **日期**：2026-09-19

## 该产品是什么

Litmaps 2016 年创立于新西兰惠灵顿（Axton Pitt + Kyle Webster），初衷「画一张全科学的地图」[^dealroom]。2025-05 收购 ResearchRabbit 并宣布 NZ\$1M 融资首轮关闭（ARR ~\$1M、用户 200 万+）；该轮 2025-08 超额认购终收于 NZ\$1.4M，后续口径将合并为单一平台[^scoop][^ecommerce]。功能四块：Discover/Visualize/Share/**Monitor**；核心对象 Litmap = seed 文章在引用网络上的扩张候选可视化地图；官方推荐 Search-Loop 用法（seed→推荐→加回输入集→重跑，循环至 10–20 篇精选）。定价：Free ≤20 inputs/2 张图；Pro \$10/月 无限[^pricing]。

## 数据面（实测出内部结构）

官方 FAQ：**270M+ 文章 = Crossref + Semantic Scholar + OpenAlex 合并**，只索引开放获取（Open Access）元数据——title/abstract/引用等 article details、不含全文，去重与版本归并（preprint↔正式版归并到 articleFamily）[^docs-db]。实测 `GET api.litmaps.com/article/1` 拿到内部 record 全貌：**稠密 int 内部 id；每条 article 直接内嵌 `forwardEdges`/`backwardEdges` 两个 id 列表 + 多源外部 id 数组**（`openAlexIds`/`magIds`/`semanticScholarCorpusIds`/`dois`/`arxivIds`/`pubmedIds`）+ `familyId` 版本归并——教科书式「自建引用图服务化」结构，可直接借鉴为 schema。

**质量面实测**：keywordSearch 返回过 Zenodo SEO spam 记录与同题重复条目（与其 FAQ 承认的去重残留一致）——**自建库必须留质量过滤层**。

## 算法：三件套官方披露

docs 列三个可选算法，与前端 bundle 算法注册表逐字对应[^docs-algo]：

| key | 展示名 | 机制 |
| --- | --- | --- |
| `shallow` | Shared Citations & References（默认） | 一跳邻域（citations+references+共被引）按图内互联度排序 |
| `authorFiltration` | Common Authors | 共同作者合作模式召回 |
| `semantic` | Similar Text | 标题+摘要 embedding/LLM 语义检索，**唯一不用引用的算法** |

隐藏模式 `seed`：输入恰 1 篇且无过滤时前端改写算法为 `seed` 返回 20 条。可视化排序轴：**Momentum**（被引数按新近度调整）、**Map Connectivity**（图内被引数）、Cite Count、Ref Count、Publication Date[^docs-vis]。

## 协议面（实测）

API 基址 `api.litmaps.com`；错误体 `{"error":true,"reason":...}`；解码错误泄漏 `CodingKeys`——**后端 Swift**（疑 Vapor/Hummingbird）。**无鉴权可读**：`/health`、`/article/{int}`、`/articleFamily/{int}`、`/author/{int}`（hIndex/orcid/citationCount）、`/keywordSearch?query=`。鉴权门：`/search`、`/map*`、`/monitor/*`、`/user/*` 等全部写与配置端点。**搜索是异步 job**：`POST /search?type=<algo>`（body=序列化 discover config）→ `{searchResultId}` → 轮询 `GET /searchResult/{id}` → `DELETE` 清理。存在 WAF/速率限制，密集探测会触发暂时性连接阻断，抓取需温和。

## 可借鉴点

- **record schema 可直接抄**：内部 int id + 内嵌 forward/backward 边 id 数组 + 多源外部 id 数组 + familyId 版本归并。
- **异步 search job**（POST→searchResultId→轮询）避免长连接；读端点裸开放、写端点鉴权是简洁可抄的权限分层。
- **Monitor 的本质** = 把 discover config 持久化、对每周增量文章重跑再 diff——「持久化发现查询」的工业化形态，实现成本低、用户黏性高。
- 教训：库里实测到 spam 与重复条目混进检索——自建库不做质量门（来源白名单/DOI 前缀过滤/重复归并强度）会被垃圾数据拖垮。

## 结论

数据层（三家开放源 ingest→多源 id 对齐→版本归并→内嵌边表落库）是真正壁垒也是最大工程量，等于「重做一个小号 OpenAlex」；算法层出奇的薄（一跳邻域+图内互联度），任何人拿到引用图都能复刻。

### 参考文献

[^dealroom]: Dealroom. Litmaps company information. [app.dealroom.co](https://app.dealroom.co/companies/litmaps)
[^scoop]: Scoop Business. NZ Startup Litmaps Acquires US Rival And Raises $1M. 2025. [scoop.co.nz](https://www.scoop.co.nz/stories/BU2505/S00127/nz-startup-litmaps-acquires-us-rival-and-raises-1m-to-accelerate-ai-driven-research-worldwide.htm)
[^ecommerce]: eCommerceNews. Litmaps secures NZD $1.4 million to drive global platform growth. [ecommercenews.co.nz](https://ecommercenews.co.nz/story/litmaps-secures-nzd-1-4-million-to-drive-global-platform-growth)
[^docs-algo]: Litmaps Docs. Search algorithms in Litmaps（2026-09-19 实测）. [docs.litmaps.com](https://docs.litmaps.com/en/articles/9029858-search-algorithms-in-litmaps)
[^docs-db]: Litmaps Docs. Our database FAQ（2026-09-19 实测）. [docs.litmaps.com](https://docs.litmaps.com/en/articles/7212085-our-database-faq)
[^docs-vis]: Litmaps Docs. Understand research faster visually（2026-09-19 实测）. [docs.litmaps.com](https://docs.litmaps.com/en/articles/9181490-understand-research-faster-visually)
[^pricing]: Litmaps Pricing 页（2026-09-19 实测）. [litmaps.com/pricing](https://www.litmaps.com/pricing)
