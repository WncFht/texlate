# arXiv 获取层调研主报告：端点 / 限流 / 线缆格式 / 解包 / 定位 / 元数据 / 降级 / 批量 / 引用排序

> **结论**：arXiv 获取面可拆为三个独立限流桶（arxiv.org 内容端点、export.arxiv.org 全站镜像+Atom API、oaipmh.arxiv.org 元数据收割）；HEAD `/src/{id}` 一次即得版本号+格式+etag；线缆格式四态（tar.gz / 单文件 .gz / PDF 直投 / includepdf 包装壳）靠魔数+content-disposition 后缀判别；降级链 e-print → HTML → PDF sidecar 三层叠加覆盖 ≈100%。
> **状态**：现行——主体结论已实装为 `src/texlate/arxiv/`（fetch/ratelimit/meta/locate/sniff/unpack/cache/html）；规范面唯一事实源 = `spec/`，本文是调研证据与设计动机记录。§9 引用排序与 §8 批量层成本模型为**未落地设计**（截至 2026-09-20）。
> **日期**：2026-09-14 取证，2026-09-20 重订入库

本文是获取层全部调研的汇总件：单篇获取（§1–§7）已逐条销号并实装；批量层（§8）与引用排序（§9）是设计稿，渠道实测见 [bulk-channels.md](bulk-channels.md)、增量通道落地见 [2026-09-19-daily-soak.md](2026-09-19-daily-soak.md)。

## 1. 端点与限流

### 1.1 端点表

| 用途        | URL                                              | 备注                                                       |
| ----------- | ------------------------------------------------ | ---------------------------------------------------------- |
| 源码包      | `arxiv.org/src/{id}[vN]`（`/e-print/` 301 到此） | tar.gz / 单文件 .gz / PDF 直投 / includepdf 壳四态         |
| HTML 版     | `arxiv.org/html/{id}[vN]`                        | LaTeXML 输出；探 `{id}`（最新版）后逐版本回退              |
| abs 页      | `arxiv.org/abs/{id}[vN]`                         | license 机读位（`div.abs-license a[href]`）、备用元数据    |
| PDF         | `arxiv.org/pdf/{id}[vN]`                         | `content-disposition: inline`（注意与 /src 的 attachment 不同） |
| Atom 元数据 | `export.arxiv.org/api/query?id_list={id},…`      | 批量 id_list 一次拉多篇；arxiv.org/api 仅 302 转发到此     |
| OAI-PMH     | `oaipmh.arxiv.org/oai?verb=…`                    | 已迁出 export（/oai2 全动词 301）；独立第三限流桶          |
| RSS 日更    | `export.arxiv.org/rss/{cat}`（arxiv.org 302 到此） | 日更种子源首选，见 [probes.md](probes.md)                  |

`export.arxiv.org` 实测为**全站镜像**：`/src` `/pdf` `/abs` `/e-print` 全通且 etag 行为一致——是第二下载桶与主站故障转移目标，不只 API host（证据见 [export-probes.md](export-probes.md)）。

### 1.2 请求纪律（官方条款 + 实测校准）

- **UA**：描述性 + 可联系，格式 `texlate/{version} (+{repo_url}; mailto:{contact})`。arXiv 官方要求机器人自报家门，通用 UA（curl/python-urllib）更易被限[^arxiv-tou]。
- **限速**：每 host ≥3.05s 全局间隔、零并发（官方 ≤1 req/3s、单连接条款[^arxiv-tou]）；三个 host 各自独立计时。吞吐靠批量接口（id_list / OAI / S3）不靠并行打站。
- **HEAD 预检**：GET 前先 `HEAD /src/{id}`——`content-disposition` 文件名直接给出 resolved 版本号 + 格式后缀（`arXiv-2203.02155v1.tar.gz` / `arXiv-0807.5094v1.gz` / `arXiv-1602.03837v1.pdf`），`content-length` 做上限检查（拒 >150MB），`etag` 做缓存重验证。一次 HEAD = hasSrc + 三态格式预检，魔数嗅探降为下载后 sanity check。
- **重验证**：`If-None-Match` / `If-Modified-Since` 均回 304（Varnish 边界）；etag 有 `"sha256:{hex}"` 与 GCS 风格短串两形态，按不透明串原样回送。

### 1.3 退避与惩罚窗口（实测校准）

| 场景                      | 动作                                                                                                       |
| ------------------------- | ---------------------------------------------------------------------------------------------------------- |
| 单请求 429 / 406 / 5xx    | 重试 3 次：+10s → +30s → +90s（±20% jitter）；有 `Retry-After` 从其值                                       |
| 单请求 404                | 不重试，记 `not_found`                                                                                     |
| 传输层错误                | 同 429 退避                                                                                                |
| 同 (host, path-class) 连 2 次 429/406/403 | **断路器**：该路径类整体 park 30min 起步、翻倍封顶 2h；checkpoint 落盘可恢复                        |
| 持续 ~150 发后 /src 406   | **按 IP 累计配额惩罚**：1–3min 自愈但密度渐升至近 100%，与 UA/Accept/代理无关 → 直采日预算 ≈150–200 发 |

关键实测事实（探针证据见 [export-probes.md](export-probes.md)）：

- **429 无 `Retry-After`**；唯一见过的 Retry-After 是后端超时 503 上的 `Retry-After: 0`（Varnish 模板头，无调度价值）。
- **惩罚窗口 ≥ 小时级**：30min 静默后仍 429，原地重试是浪费配额——park 起步 30–60min，park 期间零探测。
- **限流按路径不按 host**：`/api/query` 429 时同 host 的 `/src` `/pdf` `/abs` 照常 200（缓存命中与 MISS 回源均不受牵连）→ 断路器键是 (host, path-class)，API 被锤只 park 元数据队列，下载可继续。
- **403 机器人封禁**：`arxiv.org/denied.html`，同出口 IP 连坐，社区实证 ~20min 自动解封[^sanity-issue80]；park 窗恰好覆盖。GET 走 Fastly 缓存、POST 绕缓存直撞限流器——保持纯 GET/HEAD。

## 2. 版本语义与缓存键

- `{id}` = 最新版；`{id}v{N}` = 钉版本。裸 id 请求被解析成具体 `vN` 并写进 content-disposition 文件名。
- **缓存键永远用 resolved version**——同一裸请求隔周可能解析到新版本；meta.json 同时存 `requested_id`（含用户输入的 v 钉）与 `resolved_version`。
- 版本探测：`HEAD /src/{id}v{n}` 逐版探测 404 定边界；实测 10 个知名 id 中 8 个有 v≥2（多版本是常态）。
- source tier 缓存产物：`raw.*`（原始字节）、`extracted/`、`files.txt`、`mtree.txt`（path/size/sha256 清单）、`meta.json`、`etag`；product tier 键混入 model/pipeline_version/target_lang/glossary_hash——解析器升级只失效 product 层不重下源码。

## 3. 线缆格式判别与解包安全

### 3.1 四态判别

```
bytes[0:2] == 1f 8b     → gzip 封装
  └ gunzip → tar 试开成功 → tar 多文件（主流形态）
             否则         → 单文件 .tex 本体
bytes[0:4] == "%PDF"    → PDF 直投（无源码 → sidecar）
其他                     → 遗留格式（190 发大样本零观测，95% 上界 <1.6%，纯告警）
```

- content-disposition 后缀（`.tar.gz`/`.gz`/`.pdf`）做**预检判决**，魔数 + 解包试探做下载后复核；单文件文件名是裸 `.gz` 不是 `.tex.gz`，旧式 id 去斜杠拼接（`math/0404188` → `arXiv-math0404188v6.gz`）。
- **macOS bsdtar 坑**：`tar -xf` 直接打 gz 压缩的非 tar 文件会在解完 gzip 后报「Unrecognized archive format」——流程必须先 gunzip → 嗅 ustar → 分流，禁止依赖 tar 的 auto-magic。
- **第四态「PDF 包装壳」**（1412.6980 v9 实证）：e-print 是合法 tar.gz、有 `\documentclass` 主文件，但正文只有 `\includepdf[pages=1-last]{…}`——解包/定位全成功却无可翻内容。主文件定位后须加**正文含量检测**（剥 preamble 后正文 <2KB / `\includepdf` 探测）→ 判 `pdf_wrapper` 走降级链。详见 [probes.md](probes.md)。

### 3.2 解包安全过滤（逐成员，缺一不可）

- 拒绝：成员名含 `..`、绝对路径（`/` 或盘符）、包外 symlink/hardlink、device/fifo/socket、setuid 位。
- 规范化：`./` 前缀剥离、重复名去重、**大小写折叠冲突检测**（macOS 大小写不敏感，`Fig1.eps`/`fig1.eps` 互覆盖——检测到即改名告警，LaTeX 引用按原名走）。
- 资源上限：解压总量 ≤512MB、成员数 ≤20k、单文件 ≤100MB（zip-bomb 防护；语料最大单包 ~19MB 余量充足）。
- tar 探测用只读列举**先列后解**，列举同时产出 `files.txt`；解包后产 `mtree.txt`（每成员 path/size/sha256）供缓存完整性校验与跨版本 diff。

## 4. 主文件定位算法

```
candidates = { f | f ∈ *.tex，strip_comments(f) 含 \documentclass 或 \documentstyle }
```

1. **先剥注释再匹配**：documentclass 选项可被注释穿插（2308.07483）；`\documentstyle` 是 LaTeX 2.09 遗留（hep-th/9901001 在跑）。剥注释注意 `\%` 转义与 verbatim 段。
2. 唯一候选 → 主文件；多候选依次裁决：含 `\begin{document}` 优先 → include 图的**根**优先 → 文件名先验 `main|paper|ms|root|manuscript|thesis|{id}`（顶层目录优先）→ 仍 ≥2 个独立根标 `multi_doc` 取 include-degree 最大者（2201.05989 双 documentclass 双论文实证）。
3. 零候选 → 非 LaTeX（plain TeX `\bye` / ConTeXt `\starttext`）→ 进降级链不硬猜。

`\input` 拓扑展平识别八形态：`\input{…}` / 裸 `\input file`（无括号 TeX 原生语法，1502.01589 实测 25 处——arxiv-to-prompt 在此翻车，见 [arxiv-to-prompt.md](arxiv-to-prompt.md)）/ `\include` / `\InputIfFileExists` / `\subfile` / `\import{dir}{file}` / `\subimport` / `\includestandalone` / `\CatchFileBetweenTags`；`\bibliography{x}` 映射 `x.bbl`（约半数语料自带 .bbl 直接消费）。路径解析基准序经语料实测修正为 **编译 CWD（主文件目录）→ 项目根 → including 文件目录**；扩展名补全 `.tex → .sty → 裸名`。环检测断环记 warning。

## 5. 元数据层

### 5.1 拉取分工

- **Atom API**（export 桶）：`id_list` 批量拉元数据（经验值 ≤200 篇/次，URL 8KB 封顶分批）；发现/订阅用 `search_query` + 分页。**Atom 无 license 字段、无完整版本史**。
- **OAI-PMH**（oaipmh 桶）：`GetRecord&metadataPrefix=arXivRaw`——独占 `<version>` 版本史（每版 date+size+source_type）与 `<license>`（license 唯一机读源）；`ListIdentifiers` 日窗做增量对账、`ListRecords` 做批量回填（全库 ~2000 页 ≈ 2h@3s，见 [oai-pmh.md](oai-pmh.md)）。
- **license 补充机读位**：abs 页 `div.abs-license > a[href]`（URL 即枚举值）；RSS `dc:rights` 同词表。

### 5.2 Atom → 内部 schema

`arxiv_id`（`<id>` 去版本）、`resolved_version`、`title`、`authors`、`abstract`、`primary_category`、`categories`、`published`（v1 日期）、`updated`（最新版日期）、`doi`、`journal_ref`、`comment`（页数/图数线索）、`links`。

### 5.3 消费点

`primary_category` → 领域术语包映射；`comment` 页数 → chunk 预算与 token 成本预估；`authors` → 「不可翻」保护名单；缓存 `resolved_version` < 新 Atom/OAI 版本 → 标 stale 提示新版。

## 6. 降级链（与覆盖实测对齐）

```
L1  e-print 源码 ──解析/编译失败──→ L2  arXiv HTML（LaTeXML，覆盖集≡源码集，
       │                              救「我们的解析器崩了」不救「没源码」）
       └── %PDF/404/stub → L3  PDF sidecar（唯一通路）
```

- L1 单层源码覆盖 ~87–95%（年代敏感，见 [probes.md](probes.md) §B 大样本）；L2 覆盖集与源码集基本重合——它是异构降级（DOM 分块不复用 LaTeX scanner，规格见 [html-path.md](html-path.md)）。
- L2 探测序：钉版 → `HEAD /html/{id}`（latest）→ 逐版本回退（窗口有界）。**latest 可能是 stub**（1412.6980v9=20KB 包装壳而 v1/v2 有完整正文）；边缘案存在 v1 404 v2 200——勿只探单版本。
- 状态机失败终态：`no_source | pdf_only | parse_failed | translate_failed | compile_failed | degraded_html | degraded_pdf`；`degraded_*` 也产出译文，状态位让产品层给降级提示。

## 7. 覆盖率基线（合并样本 ~250）

源码率：旧式 id 98.1%、新式 94.8%（合并口径 ~91.7%）、PDF-only ~5–13%（年代敏感）；遗留格式尾巴零观测；旧式单文件 .gz 率 28.8% vs 新式 16.3%——解包必须保住单文件分支；**旧 id 序号空间稀疏**（低流量 archive-month 大量 404）→ 枚举抓取须容忍空洞，不能假设 seq 稠密。外部 60 万篇尺度对表：88.6% 有效 TeX / 9.3% pdf-only / 1.6% 主文件难定位[^xray]。

## 8. 批量层（未落地设计稿）

### 8.1 S3 requester-pays（官方认可正道）

- Bucket `s3://arxiv`，region us-east-1，请求须带 `x-amz-request-payer: requester`，manifest 本身也收费（匿名 403 实测）。
- Key 布局 `src/arXiv_src_{YYMM}_{SEQ}.tar` ~500MB/块；manifest 记 `first_item/last_item/num_items/yymm` → id→chunk 精确二分定位，无需盲拉全量。全量 ~9.2TB（2025-04 口径），月增 ~100GB[^arxiv-bulk]。
- 成本模型：$0.09/GB egress → 全量 ~$830；**同 region EC2 拉取免 egress**——机内解包→派生数据落库→只回传 edges/meta 是推荐路线。hjfy 实测 2023+ ~2TB/47 万篇 = $174 与该费率吻合。

### 8.2 免费替代与拐点

IA `arxiv-bulk` = S3 桶免费镜像但**冻结 2020-10**；HF `scholarweave/arxiv-latex` 月更近但丢失二进制图；`gs://arxiv-dataset` 零源码。逐渠道实测与「指定清单 ≤2k 篇直采最省力、凑 N 篇走 tar 块」的拐点核算见 [bulk-channels.md](bulk-channels.md)；2501+ 无损批量断档的决策点见 [2026-09-19-scale-roadmap.md](2026-09-19-scale-roadmap.md)。

## 9. 引用排序（未落地设计稿）

目标：从已下载 e-print 语料抽「引用 → arXiv id」边，计数排序选预译种子集。

- **抽取面**：.bbl + .bib + .tex 全扫（近半语料 bib/bbl 皆无、内嵌 `thebibliography` 在 .tex 里）；模式覆盖 `arXiv:NNNN.NNNNN`（冒号/空格可空）、旧式 `arXiv:hep-ph/9712271`、bib `eprint` 字段（**必须形状校验**——语料实证常装 DOI URL）、`journal={arXiv preprint arXiv:…}`、URL 形态（`arxiv.org/(abs|pdf|e-print)/` + DataCite `10.48550/arXiv.`）、`\cite` 键即 id、`\eprint`/`\arxiv` 宏。
- **id 归一化**：新式 `\d{4}\.\d{4,5}` 校验月份合法性与上限；旧式 archive 白名单（含退役档）；`{archive}.{subj}/NNNNNNN` → `{archive}/NNNNNNN` + lower-case（math.AG/HEP-TH 双实证，见 [probes.md](probes.md)）；版本后缀剥离→paper 级计数。
- **去重**：`(citing_id, cited_id)` 集合语义——同文多处引同一 id 计 1。
- **精确度问题**（按影响排序）：语料边界近因偏差（只能数语料内发出的引用）；正式发表遮蔽（Adam 被引为 ICLR'15 而非 arXiv id → 系统性低估高引老文，OpenAlex 对拍校准：84,617 vs 语料内 29,512 ≈ 3×，见 [paper-search-assets.md](paper-search-assets.md)）；自引标 `self: true` 不剔除；无 id 引用与 PDF 直投引用者接受低估；撤稿/多 id 留 `replaced_by` 人工表。
- **产物**：单遍扫描 → `edges.jsonl {citing_id, cited_id, field, self_cite}` → `counts.json` → `rank.txt`；edges 保留边级数据，归一化规则迭代不重扫。hjfy 校准点（47 万篇 2023+ 语料）：`1412.6980`=29512、top-10k≈64、top-100k≈个位数 → 「翻译 ~10 万篇覆盖绝大多数阅读需求」估算可复用。

## 10. 落地对照（2026-09-20 核 `src/texlate/arxiv/`）

| 本文条目                     | 实装位置                                              |
| ---------------------------- | ----------------------------------------------------- |
| §1 三限流桶 + 断路器 + 日预算 | `ratelimit.py`（per-host 桶、(host,path-class) park、180/日） |
| §1 export 第二桶故障转移     | `fetch.py` `DEFAULT_HOSTS` + `_across_hosts`          |
| §1.2 HEAD 预检 + 304 重验证  | `fetch.py` `head_src`/`get_src`/`_refresh_head`       |
| §2 钉版缓存 + 原子发布       | `cache.py`（staging→rename+`.old` 回滚）              |
| §3 四态判别 + 解包安全       | `sniff.py`（魔数+`check_pdf_wrapper`）、`unpack.py`   |
| §4 定位 + 八形态拓扑         | `locate.py`                                           |
| §5 Atom 主源 + OAI 兜底      | `meta.py`（`fetch_metadata`/`resolve_version`）       |
| §6 降级链                    | `meta.py` `degrade`（L2 逐版本回退窗口 ≤24）+ `html.py` |
| §8/§9 批量层 / 引用排序      | **未实装**                                            |

### 参考文献

[^arxiv-tou]: arXiv. arXiv API Terms of Use. info.arxiv.org. [help/api/tou](https://info.arxiv.org/help/api/tou.html)
[^arxiv-bulk]: arXiv. Bulk Data Access via S3. info.arxiv.org / github.com/arxiv/arxiv-docs. [bulk_data_s3](https://info.arxiv.org/help/bulk_data_s3.html)
[^sanity-issue80]: karpathy/arxiv-sanity. "Blocked by arxiv (403)" — 同 IP ~1200 篇后全站 403、约 20min 自解的社区实证. GitHub issue #80. [arxiv-sanity#80](https://github.com/karpathy/arxiv-sanity/issues/80)
[^xray]: X-raying the arXiv. arXiv:2601.11385. 60 万篇实测：88.6% 有效 TeX / 9.3% pdf-only / 0.37% 撤稿 stub / 1.6% 主文件难定位.
