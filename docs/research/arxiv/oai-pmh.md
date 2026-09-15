# oaipmh.arxiv.org 探针实录（2026-09-14 下午）

> 原始数据：`tmp/exp/oai-probes/`（`headers.jsonl` 全量响应头 + `elapsed_ms`、`probe.py` 探针脚本、各 verb 响应 body、两个 XSD）。
> 条件：UA `texlate/0.1-dev (…; mailto:research@texlate.dev)`，同 host ≥3.05s 串行零并发，不跟 redirect。**13 发全部 200，零限流迹象。**
> 定位：`export.arxiv.org/oai2` 已整端点 301 到此（见 export-probes.md §1.2）；这是 arXiv 第三个独立限流桶，调度器单独记账。

## 1. 端点能力清单（Identify 实锤）

- baseURL `https://oaipmh.arxiv.org/oai`，OAI-PMH 2.0，adminEmail `help@arxiv.org`。
- `earliestDatestamp=2005-09-16`（datestamp 只覆盖 2005-09 后的更新事件；更早论文的首条 datestamp 即 2005-09-16 起的某次入库）。
- `granularity=YYYY-MM-DD`（日粒度，from/until 按天闭区间）。
- `deletedRecord=persistent`——删除留墓碑 header（`status="deleted"`），增量同步可感知撤稿。
- 政策声明：metadata harvesting 经 OAI 许可；**full-content harvesting 不允许**（除非另有协议）——OAI 只能做元数据层，源码/全文仍走 e-print/S3。
- 4 个 metadataPrefix：`oai_dc` / `arXiv` / `arXivOld` / `arXivRaw`（§2 字段矩阵）。
- Sets：183 个 setSpec，三层 `{archive}` → `{archive}:{subj-class}` → `{archive}:{subj-class}:{category}`。顶层 8 个：physics math q-bio cs q-fin stat eess econ；叶层如 `cs:cs:LG`。`set=cs` 实测正确下推（2074 条全部含 ≥1 个 cs setSpec；header 里同时枚举跨类挂名的非 cs setSpec，是 cross-list 不是漏过滤）。
- identifier 形态：`oai:arXiv.org:{id}`（新式 `oai:arXiv.org:1412.6980` 实测；旧式推定 `oai:arXiv.org:hep-th/9901001`，未实测）。
- **错误即 200**：`noRecordsMatch` 等错误以 HTTP 200 + `<error code='…'>` 元素返回，调度器必须解 body 判错——周末/假日窗口（Sat/Sun 无公告）实测返回空列表错误而非挂起。

## 2. 三格式字段矩阵（同一 id 1412.6980 各拉一条 + XSD 定稿字段清单）

| 字段                                      | arXivRaw                                                             | arXiv                                           | arXivOld | oai_dc                                          |
| ----------------------------------------- | -------------------------------------------------------------------- | ----------------------------------------------- | -------- | ----------------------------------------------- |
| id                                        | ✅                                                                   | ✅                                              | ✅       | dc:identifier=abs URL ×2（https+http）          |
| 版本史                                    | ✅ `<version v=N><date>`（RFC822 GMT）+`<size>280kb`+`<source_type>` | ❌                                              | ❌       | ❌（dc:date ×2 = created+updated，无标签）      |
| created/updated                           | ❌（隐含在版本史）                                                   | ✅ `<created>`/`<updated>`                      | ❌       | 同左 dc:date                                    |
| submitter                                 | ✅ 原始字符串                                                        | ❌                                              | ❌       | ❌                                              |
| authors                                   | 扁平 `"A and B"`                                                     | **结构化** keyname/forenames/suffix/affiliation | 扁平     | dc:creator `"姓, 名"` ×N                        |
| categories                                | ✅ 代码 `cs.LG`                                                      | ✅                                              | ✅       | dc:subject=**类名**"Machine Learning"（非代码） |
| comments                                  | ✅                                                                   | ✅                                              | ✅       | dc:description #2                               |
| **license**                               | ✅ anyURI                                                            | ✅                                              | ✅       | **❌**                                          |
| journal-ref / doi                         | schema 可选（0..1），本条无                                          | schema 可选，本条无                             | ❌       | ❌                                              |
| report-no / acm-class / msc-class / proxy | schema 可选                                                          | schema 可选                                     | ❌       | ❌                                              |
| abstract                                  | ✅                                                                   | ✅                                              | ✅       | dc:description #1                               |
| 体积（本条）                              | 4452B                                                                | 2934B                                           | 2588B    | 2905B                                           |

**license 实锤**：`<license>http://arxiv.org/licenses/nonexclusive-distrib/1.0/</license>`——Atom API 没有此字段，**OAI 是 license 唯一来源**。2074 条 cs 记录 100% 带 license，分布：nonexclusive-distrib 45.2%、CC-BY-4.0 41.6%、CC-BY-NC-ND 6.5%、CC-BY-NC-SA 3.8%、CC-BY-SA 2.0%、CC0 0.9%。

## 3. ListRecords / resumptionToken 翻页语义（实测）

- 查询：`ListRecords&metadataPrefix=arXivRaw&from=2026-09-10&until=2026-09-11&set=cs`（周四 + 周五）。
- **页 1:1300 条 / 3.51MB / 4.8s**——分页是体积驱动（arXivRaw 每条 ~1.7KB）；页界可落在日中间（p1 = 09-10 全部 1014 条 + 09-11 前 286 条）。
- token 结构：**URL 编码的改写后查询串** `verb=ListRecords&metadataPrefix=arXivRaw&from=2026-09-11&until=2026-09-11&set=cs&skip=286`——即「收窄 from 到当前日 + 日内 skip 偏移」，带 `expirationDate` 属性（当夜 UTC 0 点过期，~10h TTL）；**无 completeListSize/cursor 属性**，无法预知总条数。
- 页 2:774 条 / 2.08MB，结尾 `<resumptionToken/>` 空元素 = 终止（OAI 规范形态）。两页合计 2074 条。
- 对比：**ListIdentifiers 同窗同 set 单页返回全部 2074 条**（462KB / 4.2s，headers-only 无分页）——轻量同步扫描用 ListIdentifiers，需要全字段才上 ListRecords。
- 正确性提示：token 的「from 收窄 + 日内 skip」对**已闭合日**安全；当日窗口内新增会让 skip 漂移——增量收割建议 `until=昨天` 或先 ListIdentifiers diff。
- 吞吐估算：~1300 条/页 ×3s/req ≈ 430 条/s 等效；全库 ~2.7M 篇 ≈ 2000 页 ≈ **7GB / ~2h**，一个下午可完成全量元数据回填。

## 4. 速率/缓存特征（13 发观测）

- 全部 200；无 429/503/Retry-After/RateLimit-* 头。延迟：CDN 命中的 verb 350-630ms（`X-Cache: HIT`，Identify 的 `Age` 达 14 天——responseDate 可陈旧，别拿它当时钟）；miss 的 GetRecord 470-660ms；大页 ListRecords 4.2-4.9s（Age=0，回源）。
- 前端 Varnish/Fastly（`X-Served-By: cache-*`），静态响应被 CDN 长缓存——同一查询重发大概率走缓存，**翻页链的 skip 游标天然亲和缓存**。
- 独立桶实锤：export 429 的同时段本 host 全程 200。无官方限速公告实测约束，沿用 3s 纪律即为安全水位。

## 5. 对 texlate 元数据层的建议（OAI vs Atom 分工）

- **OAI-PMH = 批量目录/回填层（M4）**：ListIdentifiers 日窗扫描做增量发现（便宜、单页 2000+）；ListRecords arXivRaw 做全量/分区元数据回填；GetRecord 做单篇定点补（license/版本史）。
- **arXivRaw 选为本层格式**：唯一带版本史（`<version>` 精确到秒的提交时间 + 体积+source_type——versions 页面/e-print vN 存在性的权威来源）+ submitter + size；license/journal-ref/doi 字段全集同 arXiv。作者名是扁平串——需要结构化作者时补 arXiv 格式或沿用 Atom。
- **Atom = 在线单篇层**：翻译流水线里按需取 abs/feed（链接族 pdf/html/e-print 只有 Atom 有）；OAI 不提供任何下载链接（dataPolicy 明示）。
- **license 策略**：若语料/镜像要按许可过滤（CC-* 占 ~55%），必须走 OAI 回填——这是相对 Atom 的独占能力。
- 风险注记：`arXivRaw` schema 自述「跟随内部格式，会变」——解析器按可选字段全缺省写；`<source_type>` 取值表（实测仅 `D`）待语料统计补全。
