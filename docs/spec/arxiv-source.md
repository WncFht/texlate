# arXiv 源获取层规范

本层（`src/texlate/arxiv/`）把「arXiv id（可带 `vN` 钉版）」变成「本地可用的解包源树 + 元数据」：限速纪律、HEAD 预检、三态判别、安全解包、主文件定位、钉版缓存、元数据拉取与降级裁决。本文是现行实现的事实源——与代码冲突以代码为准；实测证据引 `research/arxiv/`、`research/corpus/` 对应件，不复述实验过程。

## 0. 定位与消费方

获取层是产品管线的最上游，只负责「源到手、定位到主文件」；解析、翻译、编译全部在下游层。

| 消费方                                 | 入口                                          | 用到的能力                                                             |
| -------------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------- |
| CLI（`texlate fetch` / `texlate run`） | `cli/fetch.py::_acquire`                      | `acquire_source` 全链 + offline 模式                                   |
| Web 任务（arxiv 系 kind）              | `server/worker/fetch.py::_Fetch._fetch_arxiv` | `acquire_source` + `fetch_metadata`（分类目喂术语层）                  |
| Web HTML 臂（`kind=arxiv_html`）       | `server/worker/fetch.py::_fetch_html`         | `arxiv/html.py::fetch_html` 直取 HTML 版                               |
| 降级裁决                               | `arxiv/meta.py::degrade`                      | L2/L3 层探测（当前由语料/bench 侧驱动，产品链 L3 走 babeldoc sidecar） |

批量建库（benchmark 语料）不经过本层打 arxiv.org——见 §6。

## 1. 在线获取：端点与请求纪律

### 1.1 端点表

实现只用官方端点族；下载面在 `arxiv.org` 与 `export.arxiv.org` 两 host 间故障转移（`fetch.py::DEFAULT_HOSTS` + `Fetcher._across_hosts`，两端行为一致互为镜像，另有直连回退臂）。

| 用途           | 路径                                                          | 代码落点                                                      |
| -------------- | ------------------------------------------------------------- | ------------------------------------------------------------- |
| e-print 源码包 | `/src/{id}[vN]`（`/e-print/` 同义）                           | `fetch.py::Fetcher.head_src`/`get_src`                        |
| HTML 版        | `/html/{id}[vN]`                                              | `Fetcher.head_path`/`get_path`（`html.py::fetch_html` 消费）  |
| PDF            | `/pdf/{id}[vN]`                                               | `Fetcher.head_path`/`get_path`（降级探测与 sidecar 取件）     |
| abs 页         | `/abs/{id}[vN]`                                               | 归 `content` 限流类；产品链未消费（**未落地**：备用元数据源） |
| Atom 元数据    | `export.arxiv.org/api/query?id_list={id}`                     | `meta.py::_atom_meta`（单篇查询；批量 id_list 未用）          |
| OAI-PMH        | `oaipmh.arxiv.org/oai?verb=GetRecord&metadataPrefix=arXivRaw` | `meta.py::_oai_meta`（Atom 兜底）                             |
| RSS            | `arxiv.org/rss/{cat}`                                         | **本层未落地**（语料日更管线在 bench 侧使用，见 §6）          |

### 1.2 请求纪律（硬约束）

- **UA**：`Fetcher` 以 `DEFAULT_UA` 自报家门（`texlate/{version} + repo + mailto` 形态）——官方要求机器人可识别、可联系[^arxiv-api]。
- **限速桶**：`ratelimit.py::RateLimiter` 按 `(host, path_class)` 分桶，`path_class` ∈ `api`/`oai`/`content`/`other`（`content` 覆盖 `/src|pdf|abs|html|e-print|list|rss|catchup|refs|cits|format`）；**间隔约束按 host 全局合并计时**——同 host 任意两请求间隔 ≥3.05s、零并发（`RateLimiter.acquire`）。元数据与下载互不 park 对方桶，但共享 host 级间隔。
- **日预算**：单 `RateLimiter` 实例全局日预算 180 发（`DAILY_BUDGET`），超限抛 `BudgetExhaustedError`——按 IP 配额惩罚（实测 `/src/` 密集 406）的经验值取保守口径[^layer]。预算计数按墙钟日翻转（`RateLimiter._rollover`）。
- **状态持久化**：桶状态（`last_ts`/`consec_429`/`park_until`/`park_step`）与当日计数落 `ratelimit.json`（单写者、墙钟时间戳、载入时钳合法域）——进程重启不丢 park/预算状态。
- **HEAD 预检**：GET 之前先 `HEAD /src/{id}`（`Fetcher.head_src` → `HeadInfo`）。一次 HEAD 同时给出：`content-disposition` 文件名解析的 **resolved_version + 格式提示**（`arXiv-{id}vN.tar.gz` / `.gz` / `.pdf`）、`content-length` 上限检查（拒 >150MB，`DL_CAP`）、`etag` 缓存重验证凭据[^layer]。
- **条件请求**：`If-None-Match`/`If-Modified-Since` 重验证；etag 按不透明串处理（`sha256:…` 与 GCS 短串两形态都见过）。304 → `FetchStatus.NOT_MODIFIED`[^probes]。
- **单请求重试**：瞬时态 `TRANSIENT_STATUS`（406/429/5xx）重试 3 次，退避 10s→30s→90s（`RETRY_DELAYS`）±20% 确定性 jitter（`ratelimit.jitter`，sha256 取流）；`Retry-After` 有则从其值、封顶 300s（`MAX_RETRY_AFTER_S`）。404 不重试，归 `not_found`。
- **断路器**：同 `(host,path_class)` 桶连续 2 次 429/406/403 → park 30min，复犯翻倍、封顶 2h、±20% jitter（`RateLimiter.report` + `BREAKER_STRIKES`/`PARK_BASE_SECONDS`/`PARK_MAX_SECONDS`）。403 计入 strike 是因 denied.html 机器人封禁整 IP 连坐约 20min 自解，不 park 会把预算打在死 IP 上[^arxiv-sanity]。成功或确定性 404 复位桶计数。
- **park 传递**：`ParkedError`/`BudgetExhaustedError` 向上抛穿 `_across_hosts`——调用方据此切层或放弃，不静默换 host 续打。

### 1.3 版本语义

- `{id}` = 最新版；`{id}v{N}` = 钉版。id 归一 `normalize_arxiv_id` 接受裸 id、`arxiv:` 前缀与 `arxiv.org/(abs|pdf|src|e-print|html|format)/` URL 形态；合法性 `valid_id` 覆盖新式 `\d{4}\.\d{4,5}` 与旧式 `archive/NNNNNNN` 两类。
- 缓存键永远用 **resolved version**：裸 id 请求经 HEAD `content-disposition` 文件名解出 `vN`（`fetch.py::_parse_head`），301 跳转的 final URL 尾版号同样回收（`meta.py::_head` 的 `_VER_TAIL_RE`）。
- `meta.json` 同存 `requested_id`（含用户钉版原文）与 `resolved_version`；命中缓存后 best-effort 调 `resolve_version` 比对——feed 宣告最新版 > 命中版 → 加 `stale:v{N} available` 告警，不自动升级（`fetch.py::_stale_warnings`）。
- 用户钉 `vN` 但版本不存在 → 上游 404；版本史由 `PaperMeta.has_version`/`resolve_version` 经 Atom→OAI 链还原（§3）。

> 标识符归一化（canon）剥离序管线、host 白名单臂与校验全集 → [arxiv-id-canon.md](arxiv-id-canon.md)。

### 1.4 `acquire_source` 主流程

`fetch.py::acquire_source(id, fetcher, cache, offline=False)` 三段式：`_head_phase`（HEAD + etag 比对命中短路）→ `_get_phase`（GET + sniff + unpack）→ `_commit_phase`（`SourceCache.commit` 原子入库）。`offline=True` 走 `_offline_phase`——完全不触碰 fetcher：钉版精确查、未钉版取已缓存最高版，无缓存报 `error/offline_no_cache`，不静默换版本、不降级联网。结果集 `AcquireStatus`：`ok`/`cache_hit`/`not_found`/`pdf_only`/`unknown_format`/`unpack_error`/`too_large`/`parked`/`budget_exhausted`/`error`。终态条目（`pdf_only`/`unknown_format`）命中缓存时如实透传而非伪装 `cache_hit`（`_HIT_PASSTHROUGH`）；条目目录在但 meta 不可读 → `error/corrupt_cache` 待清理而非静默重下。

## 2. 解包规范

### 2.1 三态判别（`sniff.py`，魔数优先）

```
bytes[0:2] == 1f 8b   → gzip 封装
  └ gunzip → tarfile 试开成功   → TAR 多文件包
             否则               → SINGLE 单文件 .tex 本体
bytes[0:4] == "%PDF"            → PDF 直投（无源码 → 降级链 L3）
未压缩 tar（tarfile 直开）       → TAR
其他                            → UNKNOWN
```

- tar 判定用 `tarfile` 试开（`_is_tar`），**不是** offset 257 `ustar` 字面匹配——v7 tar 无魔数、ustar 字面对非 tar 有假阳性、零成员 tar 也得判 TAR（全零块流按 TAR 归）。
- `BlobKind` ∈ `TAR`/`SINGLE`/`PDF`/`UNKNOWN`；`SniffError` 只在 gunzip 失败等线缆损坏时抛。
- 第四态 **pdf_wrapper stub**：源码包存在但正文是 `\includepdf`/`\pdfpages` 壳——`check_pdf_wrapper`（`WrapperVerdict`，section==0 ∧ 正文 <2KB 判据）检出后走降级链，不算可翻源码[^layer]。

### 2.2 路径安全与成员规范（`unpack.py`）

逐成员检查，缺一即拒（告警名即代码审计键）：

- **拒绝**：`..`、绝对路径与盘符、包外 symlink/hardlink、device/fifo/socket、setuid+setgid（`mode & 0o6000`，`reject_setuid`）；字符级拒绝控制字符 `[\x00-\x1f\x7f]` 与 UTF-16 代理区（`reject_path`/`reject_link`）；linkname 先按原始形查绝对路径/盘符再归一化，归一后 `..` 出根同拒。
- **规范化**：`./` 前缀剥离、空段折叠；同名重复成员 **last-wins**（`dup_member_overwrite`）；大小写折叠冲突——file/link 改名 `~cN` + `casefold_rename`（LaTeX 引用按原名），dir 冲突不可改名只 `casefold_dir` 告警跳过。
- **目录/文件冲突双向拒**（`reject_dir_clash`）：file-over-dir、file-under-file、迟到 dir 撞已落盘 file/symlink——先到者保。
- **IO 降级与硬拒**：落盘 `OSError ∈ {ENAMETOOLONG,ELOOP,EEXIST,ENOTDIR}` 成员级 `reject_io:{errno}` 跳过；tar 成员流中坏头（`getmembers` 静默截断后 offset 非全零）整包 `UnpackError("corrupt member stream")`——其后成员全丢时 mtree 不能谎报完整。
- **上限**：解压总量 ≤512MB、成员 ≤20k（超限整包 `too_many_members`）、单文件 ≤100MB（`reject_filesize`/`reject_totalcap`）。
- **落盘面**：`raw.{tar.gz|gz|pdf|bin}` 原始 blob 单文件（可重放）+ `extracted/` 过滤后树 + `files.txt` 名单。
- **mtree**：每包 `mtree.txt`（TSV：`path\tsize\tsha256\tkind[\t-> target][\tstub]`，kind ∈ file/dir/symlink/hardlink）——缓存完整性、跨版本 diff、引用排序去重的依据。
- **链接语义**：包内 symlink 保留落盘 + `link_kept`；hardlink 延迟二遍物化（`_finish_links`：目标在树 → `hardlink_materialized` 复制实体；缺席/是 symlink → `hardlink_dangling` 不落盘）；后到同名成员压掉未物化 hardlink 声明，与 last-wins 序一致。
- **别名落点对账**（`_reconcile_aliases`）：经 kept symlink 祖先写穿的成员与先到路径共享物理落点——收尾时以最末成员为赢家，把 size/sha256（涉 symlink 含 kind/link_target）回填先到条目，字段实变者记 `dup_member_overwrite`。
- **stub 过滤**：`member_bytes < 100B` 或解压后 `%auto-ignore` 前缀 → 标 `stub`。

### 2.3 主文件定位（`locate.py`）

1. 候选集：`TEX_EXT`（`.tex`/`.ltx`/`.latex`，大小写不敏感）中剥注释后含 `\documentclass`/`\documentstyle` 者（`DOCSTYLE_RX` 等声明正则单源在 `textutil`）。
2. 唯一候选 → 主文件。
3. 多候选裁决序：含 `\begin{document}` 优先 → include 图的根优先 → 文件名先验（`main|paper|ms|root|manuscript|thesis|{id}`）与顶层目录优先 → 仍 ≥2 独立根 → `multi_doc` 标记，按 include-degree 最大者选定并记录全部候选（`_choose`/`multi_doc`）。
4. 零候选 → 非 LaTeX（plain TeX/ConTeXt 等）→ 不硬猜，走降级链。

### 2.4 `\input` 拓扑与参考文献（`locate.py::_REF_RES`/`_resolve_bib`/`_flatten`）

- 识别 9 形：`\input`/`\include`/`\InputIfFileExists`/`\subfile`/`\import{dir}{file}`/`\subimport`/`\includestandalone`/`\CatchFileBetweenTags`/裸文件名形 `\input file`，外加 `\bibliography`。
- 路径解析基目录序：**main_dir（编译主目录）→ 项目根 → including 文件目录**（`_bases`）；扩展名补全 `.tex` → `.sty` → 裸名。注意此序是 **locate 建图层**口径；`latex/` 的 gullet 展开层另有一套解析序（including 目录 → 项目根 → top_dir → basename 补 `.tex` → 裸名），同一 `\input` 两阶段可解析到不同文件——语义权威以 gullet 为准（见 `spec/` 解析层规范）。
- `\bibliography{x}` → 主消费 `\jobname.bbl`（主文件词干）；另按 arg-stem 双探 `x.bbl`→`x.bib`（`_resolve_bib`，宽松超集面）。
- 环检测：绝对路径 `_seen` 集断环记 warning，防环优先于重复展开语义。

## 3. 元数据层（`meta.py`）

### 3.1 拉取链

`fetch_metadata(id, fetcher)` = Atom 主源（`export.arxiv.org/api/query?id_list={id}`，`_atom_meta`）→ OAI-PMH 兜底（`oaipmh.arxiv.org/oai`，`GetRecord` + `metadataPrefix=arXivRaw`，`_oai_meta`）。Atom 返回裸 abs URL（无 vN 尾）时 `resolved_version=None`，显式续走 OAI 补版本史；OAI 也挂则 Atom 残值仍返回。`resolve_version(id, want)`：裸 id → 最新版号；`want`/id 自带 vN 钉 → 存在（`has_version`，版本连续 1..latest）则返回该号否则 `None`——一次拉取同时覆盖两判断。**未落地**：OAI `ListRecords`/`resumptionToken` 翻页、批量 `id_list` 分组、DataCite 版本史反查——均属语料管线/远期设计，产品层只走单篇路径[^oai-pmh]。

### 3.2 `PaperMeta` schema

`PaperMeta`：`arxiv_id`、`resolved_version`、`latest_version`、`title`、`authors[]`、`abstract`、`primary_category`、`categories[]`、`published`、`updated`、`doi`、`journal_ref`、`comment`、`license`、`links`、`versions[]`（`VersionInfo`）。消费点：`primary_category`+`categories` → 术语包类目层（worker `_fetch_arxiv` 写 `options.arxiv_categories`）；`comment` → chunk/token 预算先验；`license` 仅 OAI arXivRaw 提供（机读许可唯一来源[^oai-pmh]）——**字段已落库但产品链无 license 拦截门（策略未落地）**，abs 页兜底抓取亦未落地；许可法律面见 `research/arxiv/licensing.md`。

## 4. 钉版缓存（`cache.py::SourceCache`）

### 4.1 布局与原子提交

- 目录形 `{cache_root}/{id}v{ver}/`：`raw.*`、`extracted/`、`files.txt`、`mtree.txt`、`meta.json`、`etag`。`resolved_version` 上限 999999。
- 提交三段：`.staging` 临时目录写入 → 原子 rename 就位；同版重下走 `.old` 备份 + 失败回滚；上游钉了不存在的版本 → `.bad-version` 哨兵防反复烧预算。
- 查询面：`get(id, ver)` 精确、`get_latest(id)` 最高已缓存版、`find_versions(id)` 版本清单；`entry_dir` 含逃逸守卫（id 归一前不入路径）。
- 命中语义见 §1.4：etag 匹配 → `cache_hit`（终态条目透传原状态）；`stale` 新版提示不升级。

### 4.2 缓存键分层

```
source_tier  = arxiv_id @ resolved_version                      # 本层产物，跨请求/跨语言共享
product_tier = sha256(arxiv_id@ver | model | pipeline_version |
                      target_lang [| src=…] [| fm=…] [| k=…])   # server/worker/_common.py::cache_key_for
```

- product tier 由服务端 `cache_key_for` 生成：`pipeline_version` 含包版本与 prompt 模板版本；可选段区分取源渠道（eprint/html）、front-matter 实跑集与 BYOK 分桶。段级复用另有 `SegmentCache`（`translation_cache` 表，`{cfg_hash}:{seg_key}` 键——cfg_hash 含模型/方言/prompt 配置，seg_key 含 src_text+kind+masked 快照）。
- 失效语义：`pipeline_version` 变化只失效 product 层（升级解析器不重下源码）；`model`/glossary 变化仅重翻。share 打包用另一套七组分键（`share.py`，见 `spec/architecture.md` 数据契约节）。

## 5. 降级链（`meta.py::degrade` + `html.py`）

```
L1  e-print 源码 ──parse_failed/compile_failed──→ L2  arXiv HTML（LaTeXML ltx_* DOM）
       │                                            异构臂：DOM 块分块，不复用 LaTeX scanner
       └── pdf_only/not_found/stub ────────────→ L3  官方 PDF（sidecar 通路）
```

`degrade(id, reason, version)` 按失败因路由首选层：`parse_failed`/`compile_failed` → L2 优先，其余 → L3 优先（`_L2_FIRST`）；首选层不可得自动落另一层兜底，全不可得 → `DegradeTier.NONE`。全程 `probed[]` 记探测轨迹；park/预算/传输错 abort 当前层切下一层。

### 5.1 层探测

- L2 `_probe_html`：`HEAD /html/{id}v{钉}` → 裸 id（301 回收版号）→ 逐版本回退，窗口上限 `_HTML_FALLBACK_MAX=24`（feed 宣告 latest 无上界，phantom vN 曾烧满日预算）；有 OAI 版本史时 `has_version` 滤空洞版本号。
- L3 `_probe_pdf`：`HEAD /pdf/{id}[vN]` 钉版 → 裸 id 两次足够（PDF 全版本都有）。
- 探测全部走 `Fetcher.head_path`——同 hosts 故障转移、同退避、同 `(host,content)` 限流域与预算[^export-probes]。

### 5.2 L2 HTML 臂（`html.py`）

- **获取**：`fetch_html(id, version, fetcher)` → `Fetcher.get_path` 直 GET `{id}[vN]`（钉版透传），不做逐版本回退（回退属 `degrade` HEAD 臂）。错误分类：`HtmlNotAvailableError`（404 或 200 但无 `ltx_document`——撤稿/「HTML not available」/abs 回落页同形）vs `HtmlFetchError`（退避后仍非 200/404）；Parked/Budget 原样上抛。
- **块模型**（`parse_arxiv_html` → `HtmlDoc`/`HtmlBlock`）：`ltx_para`/`ltx_p`→para、`ltx_title*`→title（`ltx_tag` 编号剥离、后缀映射 latex 风 context）、`ltx_caption`→caption、`ltx_note`→footnote（迟发跟宿主块）、`ltx_bibitem`/`ltx_figure`/`ltx_table`/`ltx_float`/`ltx_listing`/`ltx_authors`/`ltx_dates`/equation→support 块（占位保序不译；support 祖先内只挖 caption/title）。
- **行内 token**：`[[TYPE_n]]` 占位族——MATH/CITE/REF/NOTE/GRAPHICS/CMD/TABLE/URL，ph 值 = 元素 outer HTML，`reinsert` 单趟回插不级联。
- **出口**：`doc_chunks` 按 `TRANSLATE_CTX` 白名单产 `ChunkIn`（`ph_fragments` 携 token→片段武装 placeholder 修复臂）；`marked_html` 同源枚举给块注 `data-chunk`（元素 id 优先、缺省 `b{n}`、撞号 `#k`）——与 chunks 行 `chunk_id`、阅读器几何锚 1:1。
- 产品链接入：`options.source=html` → `kind=arxiv_html` 任务，DOM 链无 normalize/主文件步。

### 5.3 L3 PDF 臂

L3 取官方 `/pdf/{id}[vN]` 由 worker `_Pdf` 段交 babeldoc sidecar（独立进程边界，AGPL 隔离——见 `spec/architecture.md` §4）。PDF 选型实证见 `research/arxiv/pdf-fidelity.md`。

## 6. 批量渠道（定位声明）

**硬约束：benchmark 语料构建不请求 arxiv.org 任何端点。** 批量取数（IA 月度 tar、HF TIGER-5T/scholarweave、S3 requester-pays、GCS `gs://arxiv-dataset`、HF 元数据快照作分层 frame）实现在 bench 侧语料管线，**不在 `src/texlate/arxiv/` 产品层内**；本层共享给语料的只有解包/定位语义（成员级 `(channel,item,member,blob_sha256)` 钉版、`resolved_version=null`）。渠道裁决与实测见 `research/arxiv/bulk-channels.md`、`research/corpus/ia-pilot.md`、`research/corpus/post2020-sourcing.md`、`research/corpus/frame-and-allocation.md`[^arxiv-bulk]。

## 7. 未落地清单（规范侧明示边界）

- OAI `ListRecords` 翻页、`metadataPrefix` 全族批量拉取——单篇 `GetRecord` 已落，批量属语料侧。
- RSS 订阅臂、DataCite DOI 版本史反查、abs 页兜底抓取。
- license 策略门——字段入库、无消费/拦截实现。
- §6 全部批量渠道的产品层实现（IA/S3/GCS/HF）——刻意留在 bench 侧，非缺陷。
- export 429 窗口精确长度、Atom `<arxiv:doi>` 原文验证——开放项，不阻塞。

### 参考文献

[^arxiv-api]: arXiv. arXiv API User's Manual. [info.arxiv.org/help/api/user-manual.html](https://info.arxiv.org/help/api/user-manual.html)

[^arxiv-bulk]: arXiv. arXiv Bulk Data Access. [info.arxiv.org/help/bulk_data.html](https://info.arxiv.org/help/bulk_data.html)

[^arxiv-sanity]: karpathy/arxiv-sanity issue #80：arXiv denied.html 机器人封禁口径。[github.com/karpathy/arxiv-sanity](https://github.com/karpathy/arxiv-sanity/issues/80)

[^layer]: TeXlate 调研档案 `research/arxiv/layer.md`：在线层实测主档（速率桶/406 配额/三态比例/版本语义/许可门裁决）。

[^probes]: TeXlate 调研档案 `research/arxiv/probes.md`（§B 规模面含原 serial2 探针波次）：HEAD 预检、条件请求与分层抽样探针。

[^export-probes]: TeXlate 调研档案 `research/arxiv/export-probes.md`：export 镜像=第二下载桶、限流按路径不按 host。

[^oai-pmh]: TeXlate 调研档案 `research/arxiv/oai-pmh.md`：OAI-PMH 第三限流桶与 `<license>`/版本史字段。
