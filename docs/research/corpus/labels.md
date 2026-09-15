# corpus-labels：大规模 benchmark 的分层键与真值标签数据源

调研日期：2026-09-14。实测证据在 `tmp/exp/labels/`（HF statistics/rows、OpenAlex 响应、duckdb 远程 parquet 统计脚本与结果）。

## 1. 分层键底材：HF `librarian-bots/arxiv-metadata-snapshot`

- CC0，日更（实测 `lastModified: 2026-09-14`）。单 config/split：`default/train`，**3,164,528 行 × 14 列**。
- Parquet 共 **10 shard ≈ 2.98 GB**（`refs%2Fconvert%2Fparquet/default/train/000{0..9}.parquet`）。**shard 按 update_date 聚簇**——shard 0 的 316,453 行全是 2026 年更新过的论文，不是随机样本；做全库统计要么下全量，要么跨 shard 抽样。

### 字段覆盖矩阵（datasets-server `/statistics` 实测，全库）

| 字段                                                                                   | 类型                 | 覆盖率                               | 分层用途           |
| -------------------------------------------------------------------------------------- | -------------------- | ------------------------------------ | ------------------ |
| id / title / abstract / authors / authors_parsed / categories / versions / update_date | string/list/datetime | ~100%                                | 主键、类目、版本史 |
| license                                                                                | string_label         | **85.71%**（452,795 null），9 个取值 | license 分层       |
| comments                                                                               | string               | 71.99%                               | 页数/撤稿线索      |
| doi                                                                                    | string               | 42.11%                               | "已发表"信号       |
| journal-ref                                                                            | string               | 30.47%                               | "已发表"信号       |
| submitter                                                                              | string               | 99.52%                               | —                  |
| report-no                                                                              | string               | 6.10%                                | —                  |

- **年代分层的坑**：`update_date` 是"最近更新时间"，不是首发年份。首发年要用 `versions[1].created`（字符串 `'Thu, 03 Sep 2009 22:17:07 GMT'`，regexp 抽 `\d{4}` 即可）。实测脚本 `tmp/exp/labels/duck_stratify2.py`。
- **"类目×年份×license"离线 join：已验证可行**。duckdb + httpfs 对远程 parquet 做列裁剪 range-read（只拉需要的列块，单 shard 查询秒级）：`tmp/exp/labels/duck_stratify2.py` → `duck_stratify_shard0.json`（license 分布、subyear 分布、primary category 域分布、year×license 交叉表、versions 计数）。正式管线建议把 3GB parquet 一次性拉下来本地跑；datasets-server 的 `/filter`（SQL where）端点对本数据集实测一直 "index is loading"，不可靠。

### license 词表（9 值，与 OAI-PMH `arXiv` 格式 `<license>` 同词表——snapshot 即 OAI 收割产物）

| license URI                                 | 篇数      |
| ------------------------------------------- | --------- |
| arxiv.org/licenses/nonexclusive-distrib/1.0 | 1,909,582 |
| CC-BY-4.0                                   | 578,816   |
| CC-BY-NC-ND-4.0                             | 89,035    |
| CC-BY-NC-SA-4.0                             | 65,822    |
| CC-BY-SA-4.0                                | 30,433    |
| CC0-1.0                                     | 21,789    |
| CC-BY-3.0                                   | 7,912     |
| CC-BY-NC-SA-3.0                             | 5,870     |
| CC publicdomain                             | 2,474     |
| (null)                                      | 452,795   |

- **可再分发子集**：CC0+publicdomain+CC-BY(3.0/4.0)+CC-BY-SA-4.0 ≈ **64.1 万篇**；NC 系（BY-NC-ND/BY-NC-SA）再 +16.1 万（内部 benchmark 可用、公开分发需斟酌）。null 集中在外观较老、近年无更新的记录——shard 0（近期活跃论文）上 license 覆盖率达 99.75%。
- license 也随年代漂移：2024 投稿中 CC-BY-4.0 已与 nonexclusive 接近持平（5,467 vs 4,559，shard0 口径）。

## 2. 编译/解析难度代理标签（LaTeXML severity）

逐篇 severity（no_problem / warning / error / fatal）**有现成清单，但都要过一道轻量授权**：

- **arXMLiv 2020**（SIGMathLing）：1,581,037 篇，覆盖至 2020-12。**`meta/grouped_by_severity.zip` 就是逐篇 severity 表**——只下这个 meta 包即可拿到全量 id→severity 映射，不用下 236GB 正文。LaTeXML 0.8.5 / CorTeX 0.4.3。获取门槛：SIGMathLing 会员（免费注册，签 NDA）。`https://sigmathling.kwarc.info/resources/arxmliv-dataset-2020/`
- **ar5iv 04.2024**（SIGMathLing）：2,170,799 篇，覆盖至 2024-04，LaTeXML 0.8.8。三个 zip 直接按 severity 分捆：**no_problem 366,232 / warning 1,304,052 / error 500,515**（fatal 未单独发布）。C-UDA-1.0 协议，填 Google 表单领下载链接。逐篇标签 = 文件名属于哪个捆；技巧：HTTP Range 只拉 zip 中央目录即可枚举文件名，不必下 318GB。`https://sigmathling.kwarc.info/resources/ar5iv-dataset-2024/`
- 更新的 arXMLiv 逐篇表没有公开渠道；`corpora.mathweb.org` 有 CorTeX 逐篇转换报告在线浏览，但站点挂了 Anubis 人机验证；`corpus.mathweb.org` 无法解析（不存在）。
- arXiv 自家 HTML 管线（2023-12 起全量转 HTML）**未发布逐篇状态表**；`arXiv/html_feedback` GitHub 仓只是反馈 issue 收集器。
- ar5iv `/log/{id}` 单篇可查（在 arxiv.org 域下，本任务禁达）；批量渠道就是上面的 SIGMathLing 捆。自己跑 LaTeXML/CorTeX 亦可（`dginev/ar5ivist` 单机版），200 万篇量级不现实，抽样子集可行。
- **结论**：难度标签首选 ar5iv-04.2024 三捆名单（2.17M 篇，2024-04 前）+ arXMLiv-2020 meta zip（1.58M 篇，2020 前）；两者与 HF snapshot 用 arXiv id 直接 join。2024-04 之后的新论文无现成标签，需自跑子集。

## 3. 质量权重

### cometadata/crossref-arxiv-citations（HF）

- config `all`=1,042,011 / `asserted`=160,089 / `mined`=998,112 行（all = asserted ∪ mined）。
- 字段：`arxiv_id`（`1412.6980` 裸 id，直接 join）、`arxiv_doi`（`10.48550/arXiv.*`）、`citation_count`、`cited_by`（list of `{doi, matches:[{provenance…}]}`）、`reference_count`。
- 覆盖 ~33% 全库，偏有名/有 Crossref 引用的论文；当"被引权重"够用，偏差要有数（asserted 是 Crossref 元数据里声明的，mined 是文本挖掘的）。

### OpenAlex（实测可行）

- arXiv source id：**`S4306400194`**（"arXiv (Cornell University)"，repository）。`locations.source.id:S4306400194` → **3,719,529 works**（arXiv 为任一位置）；`primary_location.source.id:S4306400194` → 2,286,585（arXiv 为主位置）。
- 实测可用写法：
    - 按年过滤 + 取字段：`/works?filter=locations.source.id:S4306400194,from_publication_date:2024-01-01,to_publication_date:2024-12-31&per-page=200&select=id,cited_by_count,locations`（2024 年 232,705 条）。
    - cursor 翻页：`&cursor=*` → `meta.next_cursor`，全量 3.72M ≈ 1.9 万页 ×200 行；要更快用 OpenAlex S3 官方快照。
    - `group_by=publication_year` 可直接拿年代分布。
    - **join 键**：`locations[].landing_page_url` 含 `arxiv.org/abs/{id}`，正则抽 id 与 HF snapshot join。
    - **没有 arXiv id 直接过滤字段**（`locations.id` 非法、`primary_location.landing_page_url` 可解析但查不到东西）→ 只能全量枚举后离线 join，不能单篇点查。
- `select=` 建议：`id,doi,publication_year,cited_by_count,locations`（locations 里带 per-location license/version，顺手多个信号）。

### "已发表"权重

- snapshot 内 `journal-ref`（30.5%）/ `doi`（42.1%）非空即"有发表去处"信号；再叠加 OpenAlex `primary_location.source` 是否为期刊 + `cited_by_count` 分桶，可构成三档质量权重（发表并引 > 发表 > 纯预印本）。

## 4. 撤稿标记

- snapshot 14 列中**无 withdrawn 字段**。代理：`lower(comments) LIKE '%withdraw%'` → shard 0 实测 883/316,453（≈0.28%）；title `WITHDRAWN` 前缀也存在。噪声可控，当弱标签用；真值在 abs 页（禁达域）。

## 落地建议（一句话）

HF snapshot（CC0，3GB parquet）做键表底材 → duckdb 出 `subyear × primary-cat × license` 分层表 → join ar5iv-04.2024/arXMLiv-2020 severity 名单当难度标签 → join OpenAlex（S4306400194 枚举）与 cometadata 当被引权重 → `license` 列圈 CC 系可再分发子集 → comments 正则当 withdrawn 弱标。
