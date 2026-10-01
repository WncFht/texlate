# oaipmh.arxiv.org 探针实录：四格式字段矩阵 / license 独占 / resumptionToken 翻页 / 独立限流桶

> **结论**：`oaipmh.arxiv.org/oai` 是 OAI-PMH 2.0 全功能端点、独立于 export 的第三限流桶（13 发全 200 零限流迹象）；`arXivRaw` 格式独占**版本史**（`<version>` date+size+source_type）与 `<license>`（Atom 无此字段，OAI 是唯一机读源）；`ListIdentifiers` 单页可吐 2000+ 条做轻量日窗扫描，`ListRecords` 翻页是体积驱动（~1300 条/页），全库 ~3.16M 篇 ≈ 2430 页 ≈ 8.5GB / ~2–3h 可完成全量元数据回填。
> **状态**：时点证据（2026-09-14 口径）。`GetRecord&metadataPrefix=arXivRaw` 兜底链已实装进 `meta.py`（license + 版本史消费）；批量收割/ListIdentifiers 增量对账属批量层设计，曾由 [2026-09-19-daily-soak.md](2026-09-19-daily-soak.md) 的枚举层承接（该链 2026-09-21 退役）。
> **日期**：2026-09-14 取证，2026-09-20 重订入库

## 1. 端点能力（Identify 确认）

- baseURL `https://oaipmh.arxiv.org/oai`，OAI-PMH 2.0。
- `earliestDatestamp=2005-09-16`——datestamp 只覆盖 2005-09 后的更新事件；`granularity=YYYY-MM-DD`（日粒度闭区间）。
- `deletedRecord=persistent`——删除留墓碑 header（`status="deleted"`），增量同步可感知撤稿。
- 政策声明：metadata harvesting 经 OAI 许可；**full-content harvesting 不允许**——OAI 只做元数据层，源码/全文仍走 e-print/S3[^arxiv-oai]。
- Sets：183 个 setSpec，三层 `{archive}` → `{archive}:{subj-class}` → `{archive}:{subj-class}:{category}`；顶层 8 个（physics math q-bio cs q-fin stat eess econ），叶层如 `cs:cs:LG`。`set=cs` 正确下推（2074 条全含 ≥1 个 cs setSpec；header 同时枚举跨类挂名的非 cs setSpec，是 cross-list 不是漏过滤）。
- identifier 形态 `oai:arXiv.org:{id}`（新式实测 `oai:arXiv.org:1412.6980`；旧式推定 `oai:arXiv.org:hep-th/9901001`，未实测）。
- **错误即 200**：`noRecordsMatch` 等以 HTTP 200 + `<error code='…'>` 返回——调度器必须解 body 判错；周末/假日无公告窗口实测返回空列表错误而非挂起。

## 2. 四格式字段矩阵（同一 id 各拉一条 + XSD 定稿）

| 字段                      | arXivRaw                                                  | arXiv                                           | arXivOld | oai_dc                                 |
| ------------------------- | --------------------------------------------------------- | ----------------------------------------------- | -------- | -------------------------------------- |
| id                        | ✅                                                        | ✅                                              | ✅       | dc:identifier=abs URL ×2（https+http） |
| 版本史                    | ✅ `<version v=N><date>`(RFC822)+`<size>`+`<source_type>` | ❌                                              | ❌       | ❌（dc:date ×2 无标签）                |
| created/updated           | ❌（隐含版本史）                                          | ✅ `<created>`/`<updated>`                      | ❌       | dc:date                                |
| submitter                 | ✅ 原始字符串                                             | ❌                                              | ❌       | ❌                                     |
| authors                   | 扁平 `"A and B"`                                          | **结构化** keyname/forenames/suffix/affiliation | 扁平     | dc:creator `"姓, 名"` ×N               |
| categories                | ✅ 代码 `cs.LG`                                           | ✅                                              | ✅       | dc:subject=**类名**"Machine Learning"  |
| comments                  | ✅                                                        | ✅                                              | ✅       | dc:description #2                      |
| **license**               | ✅ anyURI                                                 | ✅                                              | ✅       | **❌**                                 |
| journal-ref / doi         | schema 可选（0..1）                                       | schema 可选                                     | ❌       | ❌                                     |
| report-no / acm/msc/proxy | schema 可选                                               | schema 可选                                     | ❌       | ❌                                     |
| abstract                  | ✅                                                        | ✅                                              | ✅       | dc:description #1                      |
| 体积（本条）              | 4452B                                                     | 2934B                                           | 2588B    | 2905B                                  |

license 确认：`<license>http://arxiv.org/licenses/nonexclusive-distrib/1.0/</license>`——Atom API 没有此字段[^arxiv-reuse]。2074 条 cs 记录 100% 带 license，分布：nonexclusive 45.2%、CC-BY 41.6%、CC-BY-NC-ND 6.5%、CC-BY-NC-SA 3.8%、CC-BY-SA 2.0%、CC0 0.9%（与 [licensing.md](licensing.md) 全量统计同向）。

## 3. ListRecords / resumptionToken 翻页语义

- 查询 `ListRecords&metadataPrefix=arXivRaw&from=2026-09-10&until=2026-09-11&set=cs`（周四 + 周五）：页 1 = 1300 条 / 3.51MB / 4.8s——**分页体积驱动**（arXivRaw 每条 ~1.7KB），页界可落在日中间。
- token 结构 = **URL 编码的改写后查询串**（收窄 from 到当前日 + 日内 `skip` 偏移），带 `expirationDate`（当夜 UTC 0 点过期，~10h TTL）；**无 completeListSize/cursor**，无法预知总条数。结尾空 `<resumptionToken/>` = 终止。
- 对照：**ListIdentifiers 同窗同 set 单页返回全部 2074 条**（462KB / 4.2s，headers-only 无分页）——轻量同步扫描用 ListIdentifiers，要全字段才上 ListRecords。
- 正确性：token 的「from 收窄 + 日内 skip」对**已闭合日**安全；当日窗口内新增会让 skip 漂移——增量收割建议 `until=昨天` 或先 ListIdentifiers diff。
- 吞吐：~1300 条/页 ×3s/req ≈ 430 条/s 等效；全库 ~3.16M 篇 ≈ 2430 页 ≈ **8.5GB / ~2–3h**（@3s 纪律 ~2h，实测大页 ~4.8s 则 ~3.2h），一个下午可完成全量元数据回填。

## 4. 速率/缓存特征（13 发观测）

全部 200，无 429/503/Retry-After/RateLimit-*。延迟：CDN 命中 350–630ms（`X-Cache: HIT`，Identify 的 `Age` 达 14 天——**responseDate 可陈旧，不可用作时钟**）；miss 的 GetRecord 470–660ms；大页 ListRecords 4.2–4.9s（Age=0 回源）。前端 Varnish/Fastly，静态响应被 CDN 长缓存——翻页链的 skip 游标天然亲和缓存。独立桶确认：export 429 的同时段本 host 全程 200。无官方限速公告实测约束，沿用 3s 纪律即安全水位。

## 5. OAI vs Atom 分工建议（已部分落地）

- **OAI-PMH = 批量目录/回填层**：ListIdentifiers 日窗扫描做增量发现（便宜、单页 2000+）；ListRecords arXivRaw 做全量/分区回填；GetRecord 做单篇定点补（license/版本史）。
- **arXivRaw 选为本层格式**：唯一带版本史（`<version>` 精确到秒 + size + source_type——e-print vN 存在性的权威来源）+ submitter + license；作者名是扁平串，需结构化作者时补 arXiv 格式或沿用 Atom。
- **Atom = 在线单篇层**：翻译流水线按需取（链接族 pdf/html/e-print 只有 Atom 有；OAI 不提供任何下载链接）。
- **license 策略**：按许可过滤（CC-* 占 ~55%）必须走 OAI 回填——相对 Atom 的独占能力。
- 风险注记：`arXivRaw` schema 自述「跟随内部格式会变」——解析器按可选字段全缺省写；`<source_type>` 取值表（实测仅 `D`）待语料统计补全。

### 参考文献

[^arxiv-oai]: arXiv. OAI-PMH harvesting 说明（基址/格式/收割策略/full-content 限制）. info.arxiv.org. [help/oa](https://info.arxiv.org/help/oa/index.html)

[^arxiv-reuse]: arXiv. Reuse FAQ——"the license for the full text is not a part of the current search API schema". info.arxiv.org. [help/license/reuse](https://info.arxiv.org/help/license/reuse.html)
