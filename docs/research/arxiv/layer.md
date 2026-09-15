# texlate.arxiv 层规格：下载 / 元数据 / 缓存 / 批量 + 引用排序

日期：2026-09-14 · 依据：`bench/results/arxiv-coverage.md`（60 篇分层抽样实测）+ 本机探针实测 + `docs/original.md`（hjfy 自述）+ arXiv 官方 bulk-data 文档。

## 0. 结论速览

1. **端点分工**：`arxiv.org`（e-print/src/html/abs/pdf，CDN 缓存友好）与 `export.arxiv.org`（Atom API + OAI-PMH）是**两个独立限流桶**——今日实测 export 全程 429 时 arxiv.org 照常 200。调度器必须按 host 分桶限速。
2. **HEAD 预检即元数据**：`HEAD /src/{id}` 的 `content-disposition` 文件名直接给出**解析后版本号 + 打包格式**（`arXiv-2203.02155v1.tar.gz`），不下 body 就能定缓存键和格式分支。裸 id 请求也会被解析成具体 `vN`——缓存键永远用 resolved version。
3. **e-print 三种线缆格式**：tar.gz 多文件（84.6%）、单文件 .gz（15.4%，gunzip 后非 tar 即 .tex 本体）、PDF 直投（13.3%，魔数 `%PDF` 无源码）。**判别靠魔数 + 解包试探，不能靠扩展名**；macOS bsdtar 对「gz 压缩的非 tar 文件」解包报错，必须先 gunzip 再嗅 tar。
4. **降级链三层**（与 coverage 报告结论一致）：e-print 源码（86.7%）→ 解析失败走 arXiv HTML **最新版**（LaTeXML 输出，覆盖集与源码完全重合，救的是「我们的解析器崩了」不是「没源码」；实测边缘案：v1 404 但 v2 200，故探 `/html/{id}` 勿探 `{id}v1`）→ 都无源码才走 PDF sidecar（MinerU，覆盖剩余 ~13%）。
5. **元数据走 Atom API `id_list` 批量**：一次请求可拉多篇元数据，天然适配批量层；但 export.arxiv.org 限流惩罚窗口是**小时级**（当日实测 30min 静默后仍 429，且限流**按路径不按 host**——API 被锤时内容端点照常），批量任务要 checkpoint+park（30–60min 起步）而非原地重试。
6. **批量层成本模型已验证**：S3 bucket `arxiv`（us-east-1，requester-pays，`x-amz-request-payer` 头），`src/arXiv_src_YYMM_SEQ.tar` ~500MB/块 + `arXiv_src_manifest.xml` 索引。全量 ~9.2TB；hjfy 实测 2023+ ~2TB/47 万篇 = $174，与 $0.09/GB egress 吻合。**关键省钱点：同 region EC2 内拉 S3 免 egress**，只回传派生数据。
7. **引用排序 = 语料内正则抽 arXiv id 计数**，hjfy 校准点：Adam 1412.6980 = 29512 引、top-10k ≈ 64 引、top-100k ≈ 个位数。语料边界决定召回偏差（2023+ 语料 → 近因偏差；期刊正式引用不可见 → 低估经典老文）。

## 1. 实测摘录（本机，2026-09-14）

限速 ≥3s，全程串行；export.arxiv.org 重试间隔 20s/60s/90s。

### 1.1 Atom API（export.arxiv.org）—— 持续 429

```
GET https://export.arxiv.org/api/query?id_list=1412.6980
→ HTTP 429 · 14 bytes · body: "Rate exceeded."
  (+20s 重试 → 429；+60s 重试 → 429；+90s 尝试超时)
GET https://arxiv.org/api/query?id_list=1412.6980
→ HTTP 302 → location: http://export.arxiv.org/api/query?id_list=1412.6980
```

结论：API 唯一入口是 export.arxiv.org（arxiv.org/api 仅 302 转发，且落到 http）。**429 惩罚窗口 ≥3 分钟、与单请求间隔无关**——同一 IP 当日早些时候的 ~170 请求 bench 很可能触发了长窗口。spec 必须把「export host 持续 429 → 整个元数据队列 park 15–30min」做成一等公民。

### 1.2 e-print HEAD（arxiv.org）—— 版本 + 格式免费拿

```
HEAD https://arxiv.org/e-print/2203.02155
→ HTTP/2 301 · location: /src/2203.02155
→ HTTP/2 200
   content-disposition: attachment; filename="arXiv-2203.02155v1.tar.gz"
   content-type: application/gzip
   etag: "sha256:f25763898e65142f6e9319537f7309cd0e13add9094909b082745f8c2d448b78"
   last-modified: Mon, 07 Mar 2022 07:41:13 GMT
   content-length: 1072116
   accept-ranges: bytes
   access-control-allow-origin: *
```

`/e-print/{id}` 301 → `/src/{id}`（永久重定向，新代码直接打 `/src/` 少一跳）。裸 id 解析为 `v1` 并写进文件名。`accept-ranges: bytes` 表明可 `Range: bytes=0-9` 只取魔数。

### 1.3 HTML 版 HEAD —— 存在且大

```
HEAD https://arxiv.org/html/2501.14787
→ HTTP/2 200
   content-type: text/html; charset=utf-8
   content-length: 1912286        # LaTeXML 全文 HTML ~1.9MB
   link: <https://arxiv.org/html/2501.14787>; rel='canonical'
   etag: "CI/AnZSYupYDEAE="       # 内容寻址 etag，可直接做缓存键
   x-robots-tag: nofollow
```

### 1.4 引用形态实测（bench/corpus 内 grep，非网络）

```
journal={arXiv preprint arXiv:1802.05365}   # bib journal 字段内嵌
eprint    = {1902.05942}                     # bib eprint 字段（裸 id）
eprint = {https://onlinelibrary.wiley.com/doi/pdf/10.1002/cpa.21423}  # eprint 也能是 URL → 必须形状校验
arXiv:1409.0473 / arXiv 1504.00325           # bbl 纯文本，冒号可有可无
arXiv:hep-ex/0306033  hep-th/9901001         # 旧式 id，带不带 arXiv: 前缀都有
```

## 2. 下载器 spec

### 2.1 端点表

| 用途        | URL                                                 | 备注                                                  |
| ----------- | --------------------------------------------------- | ----------------------------------------------------- |
| 源码包      | `arxiv.org/src/{id}[vN]`（或 `/e-print/` 301 到此） | tar.gz / 单文件.gz / PDF 直投三态                     |
| HTML 版     | `arxiv.org/html/{id}[vN]`                           | 探 `{id}`（最新版），勿只探 `v1`                      |
| abs 页      | `arxiv.org/abs/{id}[vN]`                            | license、替代版本链接（备用元数据源）                 |
| PDF         | `arxiv.org/pdf/{id}[vN]`                            | PDF sidecar 输入                                      |
| Atom 元数据 | `export.arxiv.org/api/query?id_list={id},{id},…`    | **支持批量 id_list**，一次拉多篇                      |
| OAI-PMH     | `oaipmh.arxiv.org/oai?verb=…`                       | **已迁出 export**（/oai2 全动词 301）；独立第三限流桶 |

### 2.2 请求纪律

- **UA**：必须描述性 + 可联系，格式 `texlate/{version} (+{repo_url}; mailto:{contact})`。arXiv 官方要求机器人自报家门，通用 UA（curl/python-urllib）更容易被限。
- **限速**：每 host 桶 **≥3.05s 全局间隔**（官方 API 条款：≤1 req/3s、单连接）。`arxiv.org` 与 `export.arxiv.org` 各自独立计时。
- **并发**：对 arXiv **零并发**——官方要求单连接；我们的吞吐靠批量接口（id_list / OAI / S3）不靠并行打站。
- **HEAD 预检**：GET 之前先 `HEAD /src/{id}`——从 `content-disposition` 拿 resolved_version+ 格式、从 `content-length` 做上限检查（拒 >150MB）、从 `etag` 做缓存重验证。一次 HEAD 替代一次盲下。
- **重验证**：缓存再取时 `If-None-Match: {etag}` / `If-Modified-Since`，命中 304 免下载。

### 2.3 退避表（实测校准）

| 场景                      | 动作                                                                                                                                                                                            |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 单请求 429 / 5xx          | 重试 3 次：+10s → +30s → +90s（±20% jitter）；有 `Retry-After` 头一律从其值                                                                                                                     |
| 单请求 404                | 不重试，记 `not_found`（id 不存在 / 无源码版本）                                                                                                                                                |
| 网络错误                  | 同 429 退避                                                                                                                                                                                     |
| **同 host 连续 2 次 429** | **断路器**：该 host 队列整体 park 15min，任务 checkpoint 落盘（今日实测惩罚窗口 ≥3min，原地重试是浪费配额）                                                                                     |
| park 后首个请求仍 429     | park 时长翻倍，上限 2h；全程可恢复                                                                                                                                                              |
| **持续 ~150 发后 406**    | **按 IP 累计配额惩罚**（2026-09-14 语料抓取实测）：`/src/` 开始回 406，1–3min 自愈但密度渐升至近 100%，与 UA/Accept/代理无关 → 直采日预算 ≈150–200 发，大语料走批量渠道（IA tar/HF parquet/S3） |

### 2.4 版本语义

- `{id}` = 最新版；`{id}v{N}` = 钉版本。两者都可能命中不同 tarball。
- **缓存键永远用 resolved version**：裸 id 请求 → HEAD 文件名里的 `vN` → 记 `resolved_version`。同一裸请求隔周可能解析到新版本——`meta.json` 里同时存 `requested_id`（含用户输入的 v 钉）与 `resolved_version`。
- 用户钉了 `vN` → 直接 `/{id}vN`；解析失败（该版本不存在）返回 404，向用户报版本清单（abs 页可得）。

## 3. 解包：格式判别与路径安全

### 3.1 三态判别（顺序执行）

```
bytes[0:2] == 1f 8b          → gzip 封装
  └ gunzip →
      offset 257 起 5 字节 == "ustar"（或 tar -t 试列成功）→ tar 多文件（84.6% 主流）
      否则                                                  → 单文件 .tex 本体（15.4%）
bytes[0:4] == "%PDF"         → PDF 直投（无源码，走 sidecar）
其他                          → 遗留格式（dvi/ps.gz 等）→ 记 unknown 人工看
```

- **content-disposition 只做预检提示，不做判决**（单文件情形文件名形态待一次实测确认——见 §10）；判决以魔数 + 解包试探为准。
- **macOS bsdtar 坑**：`tar -xf` 直接打 gz-压缩的非 tar 文件会在解完 gzip 后报「Unrecognized archive format」；libarchive 的自动侦测**不会**把裸文本当存档。所以流程必须是「先 `gunzip -c` → 嗅 ustar → 再分流」，禁止依赖 tar 的 auto-magic。
- tar 探测用只读列举（`tar -tf` / libarchive `archive_read_next_header` 干跑），**先列后解**：列举同时产出 `files.txt` 清单入缓存。

### 3.2 路径安全过滤（逐成员，缺一不可）

- 拒绝：成员名含 `..`、绝对路径（`/` 或盘符）、symlink/hardlink 指向包外、device/fifo/socket、setuid 位。
- 规范化：`./` 前缀剥离、重复名去重、**大小写折叠冲突检测**（macOS 默认大小写不敏感，`Fig1.eps`/`fig1.eps` 会互相覆盖——检测到即改名并告警，LaTeX 引用按原名走）。
- 资源上限：解压总量 ≤512MB、成员数 ≤20k、单文件 ≤100MB（zip-bomb 防护；语料最大单包 19MB，余量充足）。
- 落盘目录：`cache/src/{id}v{n}/raw/`（原始 tar.gz 字节原样保存）+ `extracted/`（过滤后树）。raw 保留保证可重放。

### 3.3 mtree 清单

- 解包后用 `bsdtar --format=mtree --options=sha256`（或 Python `libarchive`）生成 `mtree.txt`：每成员 path/size/sha256。用途：缓存完整性校验、增量比对（同 id 跨版本 diff）、引用排序语料的去重依据。开销小，值得每包一份。

## 4. 主文件定位算法

```
candidates = { f | f ∈ *.tex, strip_comments(f) 含 \documentclass 或 \documentstyle }
```

1. **先剥注释再匹配**：2308.07483 的 documentclass 选项被注释穿插；`\documentstyle` 是 LaTeX 2.09 遗留（hep-th/9901001 实测在跑）。剥注释时注意 `\%` 转义与 verbatim 段。
2. **唯一候选** → 主文件。
3. **多候选** 依次裁决：
   a. 含 `\begin{document}` 者优先；
   b. include 图的**根**优先（不被任何其他候选 \input/include 的文件）；
   c. 文件名先验：`main|paper|ms|root|manuscript|thesis|{id}`，顶层目录优先于子目录；
   d. 仍 ≥2 个独立根（2201.05989 实测：camera.tex + paper.tex 双 documentclass 双论文）→ 标 `multi_doc: true`，按 include-degree 最大者选定并在 report.json 记录全部候选，交上层决定（产品层可给版本切换）。
4. **零候选** → 非 LaTeX（plain TeX 用 `\bye`、ConTeXt 用 `\starttext`）→ 直接进降级链，不硬猜。

### \input 拓扑展平

- 识别命令：`\input` `\include` `\InputIfFileExists` `\subfile` `\import{dir}{file}` `\subimport` `\includestandalone` `\CatchFileBetweenTags`（后两个 bib 工具常见）。
- 路径解析：相对当前 including 文件目录 → 退项目根；扩展名补全顺序 `.tex` → `.sty` → 裸名（`\input{macros}` 常见无扩展）。
- `\include` 隐含 `.tex` + `\clearpage` 语义；`\bibliography{x}` 映射 `x.bbl`（48.1% 语料自带 .bbl，直接消费不跑 bibtex——coverage 结论：仅 5.8% 是「只有 .bib 需现场 bibtex」）。
- 输出：展平序列表（flatten order）供 scanner 按文档顺序分段；环检测（互相 \input）→ 断环记 warning。

## 5. 元数据层（Atom → meta schema）

### 5.1 拉取

- `export.arxiv.org/api/query?id_list={id1},{id2},…` **批量拉**——元数据请求天然打包，N 篇一次请求（上限官方未硬定，经验值 ≤200 篇/次，URL 长度封顶 8KB 分批）。
- 发现/订阅类查询用 `search_query=cat:cs.LG&sortBy=submittedDate` + `start/max_results` 分页（仅批量层需要）。
- 今日 export 持续 429 → 元数据队列必须独立于下载队列调度，且支持 park/resume。

### 5.2 Atom 字段 → 内部 schema（按官方 API 文档定稿；今日未能实测响应体，字段名以文档为准，标 †）

```json
{
    "arxiv_id": "1412.6980", // 从 <id> URL 去版本
    "resolved_version": 5, // <id> = .../abs/1412.6980v5 †
    "title": "...", // <title>
    "authors": ["Diederik P. Kingma"], // <author><name> 列表 †
    "abstract": "...", // <summary>
    "primary_category": "cs.LG", // <arxiv:primary_category term=> †
    "categories": ["cs.LG", "stat.ML"], // <category term=> 全部
    "published": "2014-12-22T…", // <published> = v1 日期
    "updated": "2017-01-30T…", // <updated> = 最新版日期
    "doi": "10.48550/arXiv.1412.6980", // <arxiv:doi>（可空）†
    "journal_ref": "ICLR 2015", // <arxiv:journal_ref>（可空）†
    "comment": "15 pages", // <arxiv:comment> 页数/图数线索 †
    "links": { "abs": "…", "pdf": "…" } // <link> rel/href †
}
```

### 5.3 消费点

- **术语表匹配**：`primary_category` → 领域术语包映射（`cs.LG/cs.CL/cs.CV/stat.ML`→ml.yaml、`hep-*/quant-ph/gr-qc`→physics.yaml、`math.*`→math.yaml、`eess.*`→ee.yaml…）；多分类时取并集但 primary 优先。
- **chunk 预算**：`comment` 里页数/图数 → 预估 chunk 数与 token 成本；`categories` 交叉（如 cs+math）→ 公式密度先验。
- **保护名单**：`authors` 姓名注入「不可翻」清单（配合 `\author` 块保护）。
- **版本刷新**：缓存的 `resolved_version` < 新 Atom `resolved_version` → 标 stale，产品层提示「有新版本」。

## 6. 缓存设计

### 6.1 两层键

```
source_tier  = arxiv_id@resolved_version                     # 跨请求/跨语言共享
product_tier = sha256(arxiv_id | resolved_version | model |
                      pipeline_version | target_lang | glossary_hash)
```

- source tier 产物：`raw.tar.gz`（原始字节）、`extracted/`、`files.txt`、`mtree.txt`、`meta.json`、`etag`。
- product tier 产物：`zh.pdf`、`chunks.jsonl`（分段 + 译文，断点续翻载体）、`glossary.json`、`report.json`（每环节状态/耗时）、`compile.log`。
- `pipeline_version` 只失效 product 层——解析器升级重跑翻译但**不重下**源码；`model`/`glossary_hash` 失效仅重翻；`target_lang` 是天然键成员。
- source tier 重验证：下次同 id 请求先 HEAD 比 `etag`，一致即免下（arXiv 对已发布版本基本不可变，但 replacement 会动 last-modified）。

### 6.2 状态机（report.json）

```
pending → downloading → unpacking → locating → parsing → translating
        → validating → compiling → done
   失败终态: no_source(404) | pdf_only(%PDF) | parse_failed | translate_failed
            | compile_failed | degraded_html | degraded_pdf
```

`degraded_*` 也产出（HTML/PDF 路线的译文），状态位让产品层给降级提示。

## 7. 降级链（与 coverage 实测对齐）

```
L1  e-print 源码 (86.7%) ──解析/编译失败──→ L2  arXiv HTML 最新版
       │                                    (LaTeXML, 覆盖集≡源码集,
       │                                     救解析器脆弱性不救无源码)
       └── %PDF/404 → L3  PDF sidecar (MinerU, ~13.3% 唯一通路)
```

- L2 探测顺序：`HEAD /html/{id}`（=最新版，今日实测 200/canonical/内容 etag）→ 必要时 `{id}v{n}`。coverage 实测唯一边缘案：v1 404、v2 200——**先探无版本形式**。
- L2 输入是结构化 HTML（LaTeXML 的 ltx_* class DOM），翻译器走 DOM 节点级分块，不复用 LaTeX scanner——是异构降级，按 coverage 报告 §6.2 的结论预留接口。
- 三层叠加覆盖 ≈100%；L1 单层即 86.7%（CI 76–92%）。

## 8. 批量层（远期）：S3 requester-pays + OAI-PMH

### 8.1 S3（已核实官方文档）

- Bucket：`s3://arxiv`，region **us-east-1 (N. Virginia)**，**Requester Pays**——请求须带 `x-amz-request-payer: requester`，需自有 AWS 账号。
- Key 布局：`src/arXiv_src_{YYMM}_{SEQ}.tar`（~500MB/块）、`pdf/arXiv_pdf_{YYMM}_{SEQ}.tar`；YYMM 从 9108(1991-08) 起跨千年卷绕（0001=2000-01、1008=2010-08）。
- Manifest：`src/arXiv_src_manifest.xml` / `pdf/arXiv_pdf_manifest.xml`，每块记录 `filename/size/md5sum/content_md5sum/first_item/last_item/num_items/seq_num/yymm/timestamp`——**先拉 manifest（KB 级）→ 按 first_item/last_item 区间只取目标月份的块**，无需盲拉全量。
- 规模：全量 ~9.2TB（2025-04 官方数），月增 ~100GB。

### 8.2 成本模型（hjfy 实测锚点）

| 方案                          | 计算                         | 估算                                                                                        |
| ----------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------- |
| 直接拉回家（internet egress） | $0.09/GB × 9.2TB             | ~$830 全量；**hjfy 2023+ ~2TB = $174 实测吻合**                                             |
| us-east-1 EC2 就地处理        | 同 region S3→EC2 egress = $0 | 仅算力 + 回传派生数据费；**推荐路线**：机内解包→引用抽取/元数据落库→只回传 edges.jsonl/meta |
| 混合                          | manifest 选月 + 就地处理     | 按目标月份切片（如只 2023+ ≈ hjfy 的 $174 量级）                                            |

- 块内是顺序打包的 per-paper tar 成员（单篇 ~1MB 中位）→ 流式解包逐篇处理，无需全量落盘。
- 增量：manifest 的 `timestamp`/`yymm` 月度 diff → 每月只拉新增块（~100GB/mo，同 region 免费）。

### 8.3 OAI-PMH（备选/补充）

- `export.arxiv.org/oai2?verb=ListRecords&metadataPrefix=arXiv&set={set}` + `resumptionToken` 翻页；`metadataPrefix` 有 `oai_dc`（Dublin Core 简版）/`arXiv`/`arXivRaw`（含版本史）。
- **只有元数据没有全文**——适合做目录/发现/元数据回填（比逐篇 Atom 高效），源码还得走 S3 或单篇 e-print。限流同 export 桶（3s/req + park 语义）。
- 第三方镜像：GCP `gs://arxiv-dataset`（Kaggle 同款 Cornell arXiv Dataset，元数据 JSON 为主）可作冷备。

## 9. 引用排序算法

目标：从已下载 e-print 语料抽「引用 → arXiv id」边，计数排序选预译种子集（hjfy 同款思路）。

### 9.1 抽取模式表（全部经 bench/corpus 实测存在）

| #   | 模式                                         | 语料实证                                                            | 正则要点                                                                                                                     |
| --- | -------------------------------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| 1   | `arXiv:NNNN.NNNNN` / `arXiv NNNN.NNNN`       | `arXiv:1409.0473`、`arXiv 1504.00325`                               | `arXiv\s*[:：]\s*` 冒号/空格均可空，大小写不敏感                                                                             |
| 2   | 旧式 `arXiv:hep-ph/9712271`                  | hep-ex/0306033 等                                                   | 见 §9.2 旧式规则                                                                                                             |
| 3   | bib `eprint` 字段                            | `eprint={1902.05942}`                                               | **必须形状校验**——语料实证 `eprint` 常装 DOI URL；要求值匹配 id 形状，或同行/条目内 `archivePrefix`/`archiveprefix` 含 arXiv |
| 4   | `journal={arXiv preprint arXiv:…}`           | 大量                                                                | 模式 1 的子集，通用正则自然覆盖                                                                                              |
| 5   | URL 形态                                     | `arxiv.org/(abs\|pdf\|e-print)/{id}`、`doi.org/10.48550/arXiv.{id}` | arXiv 官方 DataCite DOI 前缀固定 `10.48550/arXiv.`                                                                           |
| 6   | `\cite{1412.6980}` 键即 id                   | 存在但少                                                            | cite key 单独跑 id 形状校验，免费增益                                                                                        |
| 7   | `\eprint{…}{…}` / `\arxiv{…}`（REVTeX 等宏） | 物理类常见                                                          | 参数位取 id 形状串                                                                                                           |

扫描面：**.bbl + .bib + .tex 全扫**（46.2% 语料两者皆无，内嵌 `thebibliography` 在 .tex 里——只扫 bib/bbl 会漏一半）。正则打在剥注释后的文本上，verbatim 段可不排除（代价可忽略）。

### 9.2 id 形状与归一化

- **新式**：`\b(\d{4}\.\d{4,5})(v\d+)?\b` → 校验月份 ∈ [01,12] 且 ≤ 当前年月（杜绝 `1234.56789` 假阳性——`\d{4}.\d{5}` 形状本身误报率低但数学式里偶有）；版本后缀剥离→**paper 级计数**（引 v1 和引 v2 = 同一引）。
- **旧式**：`\b((?:[a-z-]+)(?:\.[A-Z][a-zA-Z]+)?)/(\d{7})(v\d+)?\b` + archive 白名单（`hep-th hep-ph hep-ex hep-lat astro-ph cond-mat gr-qc nucl-th nucl-ex quant-ph math nlin cs physics q-bio q-fin stat eess econ` + 退役档 `alg-geom dg-ga funct-an q-alg cmp-lg adap-org chao-dyn solv-int supr-con patt-sol mtrl-th plasm-ph atom-ph bayes-an ao-sci chem-ph acc-phys comp-gas`）；大小写归一 `HEP-TH→hep-th`；`math.AG/0301001` 与 `math/0301001` 是否同文归一并列待验证项（§10）。
- **去重**：`(citing_id, cited_id)` 集合语义——同一论文多处引同一 id 只计 1（`\cite{adam}` 在正文出现 5 次 ≠ 5 引）。

### 9.3 精确度问题（按影响排序）

1. **语料边界偏差**：只能数到「语料内论文发出的引用」。hjfy 语料 = 2023+ 47 万篇 → 强近因偏差（老论文被老论文引的历史看不见）。缓解：随缓存语料自然增长持续重跑；种子集迭代制（top-N 翻译完 → 其引用图并入 → 排序更新）。
2. **正式发表遮蔽**：Adam 后期被引为「ICLR'15」而非 `arXiv:1412.6980` → 系统性低估高引老文。缓解：抽样与 OpenAlex/S2 免费 API 对拍校准（hjfy 的 S2 尝试失败在接口层，OpenAlex 无 key 可直用）；`journal_ref` 与 arXiv id 的映射表可离线积累。
3. **自引**：作者交集（meta.json authors ∩ citing authors，姓氏归一）→ `self: true` 标记，排序时可选降权——先做标记不做剔除。
4. **无 id 引用**：`arXiv preprint` 无号码、会议/journal 引用 → 不可救，接受漏计（方向是低估，排序相对序仍稳）。
5. **PDF 直投引用者（13.3%）**：不在源码语料里 → 漏其发出的引用；同上接受低估。
6. **撤稿/合并**：同一工作多 id（撤回重投）罕见；mtre/manifest 层留 `replaced_by` 人工表即可。

### 9.4 实现形态

```
对 cache/src/*/extracted 单遍扫描:
  → edges.jsonl   {citing_id, cited_id, field(bbl|bib|tex), self_cite}
  → 聚合 counts.json {cited_id: n}
  → rank.txt      种子集
```

edges.jsonl 保留边级数据 → 归一化规则迭代不用重扫语料。hjfy 校准点（47 万篇 2023+ 语料）：`1412.6980`=29512、top-10k≈64、top-100k≈个位数 → 我们的排序阈值可复用「翻译 ~10 万篇覆盖绝大多数阅读需求」的估算。

## 10. 开放问题 / 待验证清单（2026-09-14 第二波调研后状态）

| #   | 问题                                     | 状态           | 结论 / 证据                                                                                                                                                                                                                    |
| --- | ---------------------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | 单文件 .gz 的 content-disposition 形态   | ✅ 销号        | `arXiv-{id}vN.gz` 裸 .gz（旧 id 去斜杠 `arXiv-math0404188v6.gz`）；PDF 直投 `arXiv-{id}vN.pdf` + `content-type: application/pdf` → **HEAD 一次 = hasSrc + 三态格式预检**，见 arxiv-probes.md                                   |
| 2   | export 429 窗口与 `Retry-After`          | ✅ 销号        | 429 响应**无 Retry-After**、无 RateLimit-* 头；窗口 **>30min/小时级**（30min 静默后仍拒）；**限流按路径不按 host**（API 429 时 `/src`/`/pdf`/`/abs` 照常 200）→ park 策略改 30–60min 且只 park 元数据队列，见 export-probes.md |
| 3   | `math.AG/0301001` vs `math/0301001` 归并 | ✅ 销号        | `math.AG/…` →301→ `math/…`（subject-class 归并到 archive 形）；`HEP-TH` 小写归一；canonical + `citation_arxiv_id` 佐证，见 arxiv-probes.md                                                                                     |
| 4   | Atom `<arxiv:doi>` 回填                  | ➖ 弃验/有替代 | Atom 全天 429/503 未验证；但 **DataCite `api.datacite.org/dois/10.48550/arxiv.{id}` 免 key 全量覆盖**且 `dates[]` 白送 v1–vN 版本史 → DOI 反查走 DataCite，不依赖 Atom，见 datasets.md                                         |
| 5   | `/src/` `If-None-Match` → 304            | ✅ 销号        | 304 成立（If-None-Match 与 If-Modified-Since 均可）；etag 有 `"sha256:…"` 与 GCS 短串两形态，按不透明串处理，见 arxiv-probes.md                                                                                                |
| 6   | S3 manifest 边界完整性                   | ⏸ 挂起         | 无 AWS 凭据未验；**替代发现：`gs://arxiv-dataset` 匿名可列可下**（非 requester-pays；逐篇 PDF 至 ~2025-08 + 4.5GB OAI 元数据 + 172MB 内部引用图，无 LaTeX src），见 datasets.md                                                |
| 7   | HTML 降级路 DOM 分块规格                 | ✅ 销号        | `html-path.md` 完整成稿：`p.ltx_p` 等可译叶、`<math>` 整子树 `[[MATH_n]]` 占位、DOM 序 `data-chunk` 锚、stub=section==0∧文本<2KB、交错注入呈现，见 html-path.md                                                                |

## 11. 第二波调研增补（2026-09-14，12 个专项）

> 产物：`docs/research/`（arxiv-probes / export-probes / oai-pmh / arxiv-to-prompt-analysis / datasets / paper-search-assets / licensing / competitors / corpus-profile / arxiv-serial2 / html-path / pdf-fidelity）+ `tmp/exp/` 对应原始数据。

### 规格修订项

1. **export.arxiv.org 是全站镜像、第二下载桶**（export-probes 实测 `/src` `/pdf` `/abs` 全 200、真 e-print 可下、etag 行为一致）→ 下载面容量 ×2 且互为故障转移；调度改为三桶：`arxiv.org` / `export.arxiv.org` / `oaipmh.arxiv.org`，按路径分别 park。
2. **OAI-PMH 迁至 `oaipmh.arxiv.org/oai`**：4 格式（oai_dc/arXiv/arXivOld/arXivRaw）；**`<license>` 只在 OAI 系**（arXivRaw/arXiv/arXivOld，Atom 无）→ license gate 的机读来源；arXivRaw 独占版本史（每版 date+size+source_type）；183 set 三层；resumptionToken=URL 编码改写查询、当夜 UTC 过期；错误以 200+body 返回。M4 元数据回填走 OAI arXivRaw（全库 ~2000 页 ≈ 2h@3s），Atom 留在线单篇层。见 oai-pmh.md。
3. **第四态源码："pdf_wrapper stub"**——源码存在但正文是 `\includepdf`/`\pdfpages` 壳（1412.6980 v9 实证，HTML 仅 20KB stub）→ hasSrc 之外须加**正文含量检测**（stub 判据：section==0 ∧ 文本<2KB，`ltx_ERROR`/`ltx_math_unparsed` 计数作质量信号；ar5iv `/log/{id}` 与 arxiv `__stdout.txt` 可懒取）；L2 策略 latest→逐版本回退。见 arxiv-probes.md/html-path.md。
4. **许可证门控（server 形态必做）**：non-exclusive license 对第三方**零授权**（官方 ToU 明文 redistribution 需版权人许可）；分布实测：全量 nonexcl 60.3%，2023+ 近窗 nonexcl 46.6%/CC-BY 39.8% → ~43–47% 可公开托管，ND/nonexcl 只翻不托管；meta.json 两形态都存 license；**hjfy 全量公开托管属无授权再分发，是反例不是先例**。机读入口：OAI `<license>` 或 abs 页 `div.abs-license a[href]`。见 licensing.md。
5. **en 侧展示用官方 PDF**（pdf-fidelity 对拍：官方 PDF 经 pdfTeX/GS/pikepdf 后处理，13/15 页数漂移中位 +13、锚"同名不同位"不可借用）→ 同步锚以我方 zh PDF 为事实源，en 侧走文本/标题级对齐；arXiv 页眉戳一行，对齐前剥除。见 pdf-fidelity.md。
6. **RSS 种子源**：`/rss/{cat}` 302→export 桶，~260 篇/日含 license+announce_type+ 版本 guid → 每日预译种子首选；`/list/{cat}/new` 主站桶热备。见 arxiv-probes.md。
7. **增量重翻成立（v-diff 实测）**：8 对版本 diff——同文件对齐复用中位 0.87、跨文件改名容忍 0.52–0.59 → 新版重翻可省 50–85%；**缓存配对键内容指纹不键文件名**（改名/bbl 换血是主损耗）。见 arxiv-serial2.md。

### 统计加厚

8. **覆盖率加厚**（合并样本 ~250）：旧式 id 源码率 98.1%、新式 94.8%；**遗留格式尾巴 0/190**（.ps.gz/.doc 已绝迹，95% 上界 <1.6%）→"其他"分支降级为纯告警；旧式单文件 .gz 率 28.8% vs 新式 16.3%；**旧 id 序号空间稀疏**（39/92 抽样 404）→ 枚举抓取须容忍空洞。见 arxiv-serial2.md。
9. **语料画像**（39 篇机器统计）：2501.14787 实为 **5 个 documentclass 根**；2609.08578 新陷阱"wrapper root"（裸 `\input`+`\jobname` 条件）；`\input{tex/x}` 是 CWD 相对路径；0906.4725 主 tex 混 0xa9 游离字节（第二个静默污染雷）；路由预演 1 reject/3 xelatex/1 minted/34 tectonic 优先；~7/39 无 hyperref；manifest 11 处标注错误已编目。见 corpus-profile.md。

### 外部资产/生态

10. **数据集**：`gs://arxiv-dataset`（PDF+OAI 元数据 + 官方引用图，匿名免 key）；HF：`scholarweave/arxiv-latex`（LaTeX 源）、`librarian-bots/arxiv-metadata-snapshot`（CC0 日更）、`cometadata/crossref-arxiv-citations`；OpenAlex 校准两坑（stub 记录搜不到、老文引用数分裂需对拍）；S2 匿名 429 不可用。见 datasets.md。
11. **paper-search 资产**：`.env` 有 OpenAlex key + OpenReview 凭据；`enrich.py` 的 arXiv-DOI→OpenAlex 批查直接复用（Adam：OpenAlex 84,617 vs 语料内 29,512，遮蔽低估 ~3 倍实锤）；`_http_runtime`/flock 节流/`norm_arxiv`+union-find 去重可照搬。见 paper-search-assets.md。
12. **arxiv-to-prompt**：~1400 行纯正则，与我们不同物种（无占位符/分块/splice/校验）；在 1502.01589 上被注释内 documentclass 骗中错主文件 + 裸 `\input file` 不展开（与 E5 实证互证）；可抄：缓存原子发布 + 回滚、section 树消歧 UX。见 arxiv-to-prompt-analysis.md。
13. **竞品**："LaTeX 源码→中译→重排 PDF"生态位只有 hjfy（alphaXiv 已转理解层、只译标题摘要）；ar5iv 与 arxiv.org/html 同引擎同 DOM → L2 第二源（同样救不了 PDF-only）；hjfy 生态插件全靠 `/arxiv/{id}` 深链+status/files API → 保持同构可零改对接。见 competitors.md。
14. **中国可达性**：arXiv 迁 GCP 后国内直连不稳、旧镜像全死 → server 形态需"境外采集 + 境内分发"架构；S3/GCS/HF 同理。见 datasets.md。

### 仍挂起

- §10.6 S3 manifest 边界（需 AWS 凭据）
- Atom `<arxiv:doi>` 原文验证（export API 恢复后可补；有 DataCite 替代故优先级低）
- export 429 窗口精确长度（只确认 >30min 下界）
