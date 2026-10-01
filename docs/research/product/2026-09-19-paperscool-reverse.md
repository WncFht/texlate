# papers.cool 逆向调研报告

> **结论**：papers.cool 协议面已完全探明、复制成本极低——刻意做薄的「刷论文」前端，全部个性化在 localStorage；真正不可复制的是 Kimi 官方买单的生成配额。与 texlate 不在同一层（它做「筛」，texlate 做「读」）。
> **状态**：时点证据（2026-09-19 口径）——逆向结论是对第三方服务的时点观察，仅供互操作参考，服务端状态随时会变。
> **日期**：2026-09-19

对 https://papers.cool/ 做了一轮「官方披露挖掘 + 直接探针 + 社区生态」三层逆向。结论：**协议面已完全探明、复制成本极低，但生态位与 texlate 不冲突**——它是一个刻意做薄的「刷论文」前端，全部服务端逻辑一个人就能复刻；真正不可复制的是 Kimi 官方买单的生成配额。与 alphaXiv 的全功能平台路线相反，papers.cool 把所有个性化都塞进 localStorage，服务端只留「列表 + 缓存 FAQ + 计数器」三件事。

## 背景与定位

papers.cool（Cool Papers - Immersive Paper Discovery）是苏剑林（bojone，kexue.fm / 科学空间）的个人项目，域名 2019 年注册，2023-12-25 上线[^pc10088]。定位是「刷（筛）论文」而非「读论文」：镜像 arXiv 全学科约 200 个分类的每日新论文列表（工作日北京时间约 10 点更新，延迟 <10min，周末节假日不更），外加人工收集的 23 家顶会（NeurIPS/ICLR/ICML/CVPR/ACL 等）论文目录[^pc10088]。作者任职于月之暗面，站点的 AI 解读能力直接由 Kimi 赞助（footer 明写 "Powered by kimi.ai"），几乎全部源码由 GPT-4/Kimi 辅助写成，**作者明确表态全站代码不开源**[^pc10088]。

## 架构画像

服务端栈全部来自作者亲述与错误页指纹交叉验证[^pc10088][^pc9920]：**BottlePy** 后端（404/500 错误页是 Bottle 默认模板，`POST /config` 回 `!sig?base64pickle` 格式的 Bottle 签名 cookie，签名内是 pickle 序列化字典）+ **Shelve** KV 存储 + **tantivy**（Rust 全文库的 Python binding，倒排 + BM25，只索引 title+summary、无词干化，搜索结果上限 1000）+ **python-feedgen** 出 Atom + **PyQuery** 实时解析 arXiv 页面，前端 Caddy 反代（HTTP/2、h3）。历史论文源：2024-10-17 起接入 Kaggle arXiv 数据集兜底，实时爬取作补充[^pc9978]。bioRxiv 分支 2025-04 上线、2025-06 因对方 Cloudflare 反爬主动下线（实测 `/biorxiv/` 现存 500/404 残余路由）[^pc9978]。

前端是传统的服务端渲染 + 单文件 JS（`/static/cool.js`，~1100 行无混淆原生 JS，全部端点与逻辑可读）。依赖：MathJax 2.7.9、pdf.js 内嵌预览、marked.js 渲染 FAQ、mark.js 关键词高亮、flatpickr 历史日历、百度统计 + gtag。**页内中英翻译用的是 xnx3/translate.js**（管雷鸣的客户端 DOM 翻译库），调公共服务 `api.translate.zvo.cn`，服务端零成本[^xnx3]。

**个性化完全在客户端**：关注/排除分类、词云推荐（点击 PDF/Kimi 累计论文 keywords 权重，>300 词时折半衰减）、阅读历史、收藏夹、偏好排序、Magic Token、Kimi 语言——全部 localStorage。`?sort=词1,词2,...` 把词云 top20 直接拼进 URL 做服务端 prefer 排序，是整个站最巧妙的设计：无账号体系的个性化推荐。

## 协议面（全部无鉴权、无 CORS 限制、实测无限流）

| 端点                                                         | 实测结果                                                                                                                                                                                                                                                                          |
| ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /arxiv/{cat}`                                           | 分类列表页。`cat` 支持集合语法：`cs.CL,cs.CV`（并）、`cs.CL+cs.CV-cs.NE`（交 + 差，实测 Total: 224）。参数：`?date=YYYY-MM-DD` 历史日历（2024-01 起）、`?show=N` 页大小（show=100 实测出 100 条）、`?skip=N` 分页、`?sort=0`(date)/`1`(stars)/`词,词`(prefer)、`?query=` 页内过滤 |
| `GET /arxiv/{id[,id2,...]}`                                  | 论文详情页；多 ID 逗号聚合（实测 2 篇同页）；容忍 `v7` 版本后缀；无效 ID 返 200 空页                                                                                                                                                                                              |
| `GET /{arxiv,venue}/search?query=`                           | tantivy 搜索，SSR HTML 25 条/页，`Total: 1000` 封顶，`?highlight=1` 高亮                                                                                                                                                                                                          |
| `GET /{path}/feed`                                           | 任意页 + `/feed` 出 Atom（分类/venue/search 均支持，search feed 带 `?query=`）                                                                                                                                                                                                    |
| `GET /{b}/kimi?paper={id}`                                   | **取缓存 FAQ**：命中即整包返回（22KB，0.2s）；全新未生成论文 500「Unhandled exception」；生成过但无人消费完的论文会**重新流式生成**                                                                                                                                               |
| `POST /{b}/kimi?paper={id}`                                  | **生成或取缓存**：命中同上；未命中则入全局 FIFO 队列，轮到时开始**流式吐 markdown**（XHR onprogress 边收边渲染，实测生成速度 ~65B/s ≈ LLM token 流，完整 FAQ 需挂住连接约 5 分钟）                                                                                                |
| `GET /{b}/progress?paper={id}`                               | 生成状态机：浮点 `0`=未开始、`-N`=**全局队列位次**（实测 -4→-1 逐位消化，单篇约 1-3min）、`0<p<1`=生成进度、`1`=完成                                                                                                                                                              |
| `POST /{b}/star?key={pdf,kimi,unstar}&paper={id}&delta={±N}` | 公开计数器：POST 增量返回新值；`delta=0` 即免写读取（页上 PDF 1086/Kimi 633 星就是这么来的）                                                                                                                                                                                      |
| `POST /config`                                               | 表单 `magic_token`+`kimi_lang` → 回 Bottle 签名 cookie（Max-Age 100 万秒），此后请求带上即生效                                                                                                                                                                                    |
| `GET /pdf?url={encoded}`                                     | PDF 代理（venue 论文用，pdf.js viewer 的 file 参数）；arxiv URL 正常代理，非白名单域返回 200 空体——**非开放代理**                                                                                                                                                                 |
| `/venue/{CONF.YEAR}` `/venue/latest`                         | 顶会列表，论文 ID 为 `{openreviewId}@OpenReview`；kimi/progress/star/feed 端点与 arxiv 分支同构；**`?sort=0` 在 venue 必 500**（已知 bug，第三方也踩过）                                                                                                                          |
| `/biorxiv/*`                                                 | 500/404 残余——已下线分支                                                                                                                                                                                                                                                          |

## Kimi 链路（核心价值所在）

FAQ 是固定七问的预生成解读：Q1 解决什么问题 → Q2 相关研究 → Q3 怎么解决 → Q4 实验 → Q5 可探索点 → Q6 总结，**Q7 不是答案而是一个跳转链接**——`kimi.com/_prefill_chat?prefill_prompt={我们要讨论的论文是《标题》，链接是{arxiv pdf url}，已有的FAQ链接是{本页 kimi URL}}&system_prompt={你是一个学术助手…不要出现第一人称…鼓励 markdown 输出}&send_immediately=true`。这是 **Kimi 网页版的公开预填接口**：papers.cool 的 `/kimi` URL 同时充当 Kimi 爬虫可抓的上下文文档，完成「站内 FAQ → kimi.com 追问会话」的交接。

生成侧：整篇 PDF 进 Kimi 128k 上下文做 FAQ（服务端有三条队列：arXiv 列表抓取 / PDF 下载 / Kimi 问答，各带值守重建）[^pc9920]。**中英 FAQ 是两次独立生成而非互译**——`kimi_lang` cookie 选择语种，实测同篇中文 22328B / 英文 18460B 各自缓存[^pc9978]。配额控制是**三级优先级**：magic token「超级 VIP」（不对外发放，README 写「暂不开放」）> 当天论文 > 历史论文[^pc9978]。实测周六白天无 token 排队：位次 -4→-1 耗时约 15 分钟才轮到，低优先级饥饿明显。

**缓存提交语义（两路独立探针交叉归纳）**：POST 入队 → 轮到后流式生成 → **缓存内容 = 实际流向客户端的字节前缀**。两组互补实测：①断开后队列条目照常消化到 progress=1，但零消费的孤儿生成不落盘，GET 重新流式生成（两篇论文多次重复一致）；②消费中途断开会缓存残篇——POST 流至 5945B 断线缓存即停在 5945B（Q3 中途），重试续流至 10087B 再断缓存停在 10087B（Q4 中途），此后 GET 返回的就是该残篇且 progress 恒为 1，服务端不后台补全。统一模型：**生成与客户端连接耦合，断流即截断提交**——这正好解释了组①零字节消费不落盘。把 `/kimi` 当免费 LLM API 的实际代价因此是：排队 15min+ + 全程 hold 连接约 5 分钟，天然限流；下游会读到截断缓存。热门论文则一次生成、永久缓存、全站共享。

## 安全面观察

- Bottle 签名 cookie 内嵌 pickle——签名密钥若泄露即 RCE 面，但这是 Bottle 标准实现而非特有风险。
- 裸 500 多处可触发（`/arxiv/kimi` 未缓存、venue `?sort=0`、venue progress 非法 ID），无统一错误处理。
- `star` 计数器无鉴权无频控，理论上可任意刷星/污染热度信号（delta=±N）。
- 2024-06-30 changelog 明确「提高反爬虫能力，针对恶意爬虫做了措施」；RSSHub 曾因数据中心 IP 疑似被拦而 `fetch failed`（后自愈）——反爬按 IP/UA 启发式，正常频率无感。
- 无 swagger/OpenAPI、无 robots.txt、无 sitemap；10 连发页面请求全 200。

## 社区生态

官方仓库 github.com/bojone/papers.cool（806★）只有 issues + Disclaimer + 两个周边件源码：**Chrome Redirector 扩展**（右键把 arXiv/OpenReview/ACL/IJCAI/PMLR 页面跳进 papers.cool）和 **Zotero translator**（DOM 抓取存条目），无服务端代码[^pcrepo]。README 即完整 changelog。

第三方协议实现三家独立复刻过且一致：**zx33/zotero-cool-paper** 是最完整参考（TypeScript 复刻全部协议：kimi 流式生成预览、search/列表参数、SQLite 缓存，并处理过 venue `sort=0` 返回 500 的缺陷）；**han-517/scholar-mcp** 把 search/detail/download_pdf/kimi_analysis 封装成 MCP 工具（已有人把 /kimi 当免费 LLM 后端）；**RSSHub `/papers/category/:id` 路由** 证明 `?show=` 列表契约被社区依赖[^rshub]。另有 PaperBot（五源聚合）、PaperRank（爬 star 计数做热度榜）、arxiv_daily（`--source cool_paper` 数据源）、PaperPostman、PaperPilot（多源文献 agent，papers.cool 列入免费源清单）、DailyArXiv（日报 bot 只放链接）等周边；**shenhao-stu/paper_online** README 直接附「Why not cool papers」对比表（4 问精简 vs 6 问详细，只做 OpenReview）——同生态位里定位最接近的对标件；**islinxu.github.io/paper-list** 是 meta-aggregator，把 papers.cool/hjfy.top/alphaXiv 当外链 enrichment 而不爬内容——恰好呈现 texlate 所在生态位全景。无人公开逆向过生成侧 prompt（issues #78、#97 两次询问均无回复）。

## 对 texlate 的启示

papers.cool 与 texlate 不在同一层：它做「筛」——浅层 FAQ + 页面翻译，刻意不产出全文翻译物；texlate 做「读」——LaTeX 级全文重编译。可直接借鉴的点：一，**localStorage 个性化 + URL 参数化偏好排序**这套无账号方案，与 texlate server 的轻量定位吻合；二，`?show=`/`?skip=`/集合语法的列表契约被 RSSHub 等下游依赖，说明**稳定的 HTML 列表页本身就是公共 API**；三，FAQ 七问模板 + `_prefill_chat` 交接是个零成本的「AI 解读→追问」模式，texlate 若接问答可照抄交接链接；四，三级队列 + 孤儿生成不落盘的成本控制，正是免费额度下防薅的标准做法。

### 参考文献

[^pc10088]: 苏剑林。《Cool Papers 终于有赞助了！》及评论。科学空间 2024. [spaces.ac.cn/archives/10088](https://spaces.ac.cn/archives/10088)

[^pc9920]: 苏剑林。《构建论文刷卷网站：Cool Papers 的诞生记》. 科学空间 2024. [spaces.ac.cn/archives/9920](https://spaces.ac.cn/archives/9920)

[^pc9978]: 苏剑林。《Cool Papers 升级：历史论文、Kimi 128k、Kaggle 数据集接入》. 科学空间 2024. [spaces.ac.cn/archives/9978](https://spaces.ac.cn/archives/9978)

[^pcrepo]: bojone. papers.cool — issues/Disclaimer/Chrome Redirector/Zotero translator. GitHub 2023-2026. [github.com/bojone/papers.cool](https://github.com/bojone/papers.cool)

[^xnx3]: 管雷鸣。translate.js — 网页自动翻译。GitHub 2024. [github.com/xnx3/translate](https://github.com/xnx3/translate)

[^rshub]: nczitzk, Muyun99. /papers/category/:id route. RSSHub 2024. [github.com/DIYgod/RSSHub](https://github.com/DIYgod/RSSHub/blob/master/lib/routes/papers/category.ts)
