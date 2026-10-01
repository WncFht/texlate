# arXiv 批量数据渠道盘点（LaTeX 源码视角）+ 直采拐点核算

> **结论**：免费渠道里 IA `arxiv-bulk` 是官方 S3 桶的免费镜像但冻结 2020-10，HF `scholarweave/arxiv-latex` 月更至 2026-07 但无二进制图，`gs://arxiv-dataset` 确认零源码；**`s3://arxiv` 是唯一「全量 + 当前」源码正源**（requester-pays，manifest 也收费）。直采拐点：指定清单 ≤~2000 篇直采最省力；「凑 N 篇语料」任何规模都走 tar 块；2k–20k 散选走 S3 付费。
> **状态**：时点证据（2026-09-14 口径；各渠道新鲜度为该时点读数）。IA 渠道随后在语料建设中实跑（语料侧档案见 [../corpus/](../corpus/)）；2501+ 无损批量断档与 S3 决策点由 [2026-09-19-scale-roadmap.md](2026-09-19-scale-roadmap.md) 续议。
> **日期**：2026-09-14 取证，2026-09-20 重订入库

本轮未请求 `*.arxiv.org`；S3 布局取自官方 bulk-data 文档[^arxiv-bulk]。

## 1. 渠道总表

| 渠道                                                  | LaTeX src                                   | 规模                                   | 新鲜度             | 凭据/成本                                             | 粒度                              | 状态                                    |
| ----------------------------------------------------- | ------------------------------------------- | -------------------------------------- | ------------------ | ----------------------------------------------------- | --------------------------------- | --------------------------------------- |
| **`s3://arxiv` `src/`**                               | ✅ e-print 原始 blob                        | ~2.9TB（2023-03），月更                | 持续（每月）       | AWS 账号 + requester-pays（~$0.09/GB egress+ 请求费） | 500MB tar/月-chunk，manifest 定位 | 匿名 403 实测                           |
| **IA `arxiv-bulk`**[^ia-bulk]                         | ✅ 同上 tar 原样镜像                        | 1.65TB（3,242 src + 3,523 pdf chunks） | **冻 2020-10**     | 免费匿名                                              | 同上                              | ✅ 实测列目录/Range/tar 头              |
| **HF `scholarweave/arxiv-latex`**[^hf-latex]          | ✅ 展平文本（FILE: 分隔，**无图无二进制**） | 289GB / 3.12M 行                       | **月更至 2026-07** | 免费匿名（HF 访问部分地区需镜像）                     | 46 shards，manifest 给 id→shard   | ✅ 实测 rows API                        |
| `gs://arxiv-dataset`[^gcs]                            | ❌ 零 src                                   | pdf 2.77M+ps 1.63M 文件（至 2508）     | 冻 2025-08         | 免费匿名                                              | 逐文件                            | ✅ 三重核实                             |
| IA `collection:arxiv`（单篇 item）                    | ❌ 仅 PDF+meta                              | 1,076,003 items                        | 冻 ~2017-04        | 免费匿名                                              | 逐篇 PDF                          | ✅                                      |
| IA `arxiv-bulk-hashes`                                | —（成员级 checksum 清单）                   | zipsum TSV ~213MB                      | 2017-09/2018-01    | 免费                                                  | `{yymm}/{id}.gz\|pdf` 逐成员      | ✅ Range 实测                           |
| IA `arxiv-bulk-metadata`                              | —（OAI-PMH dump）                           | 2.4–2.8GB XML ×3                       | 2017-09/2018-01    | 免费                                                  | 全量 XML                          | ✅                                      |
| IA `ARXIV-CRAWL-2019-10`                              | 间接（WARC 爬虫）                           | 37×~10GB WARC                          | 2019-10 一次       | 免费                                                  | WARC                              | ✅                                      |
| Kaggle `Cornell-University/arxiv`[^kaggle]            | ❌ 仅元数据 JSONL                           | ~2.4M 条                               | 周更               | Kaggle key                                            | 单文件                            | 沿用渠道普查                            |
| HF `librarian-bots/arxiv-metadata-snapshot`[^hf-meta] | ❌ 元数据 parquet                           | 全库                                   | **日更**           | 免费                                                  | 10 shards                         | 沿用                                    |
| S2 S2ORC                                              | 间接（GROBID/LaTeX 解析全文，非原始 blob）  | 千万级                                 | 滚动 release       | 免费 key（申请等待）                                  | API/批量 dump                     | 下载需 key（401 实测）                  |
| Academic Torrents                                     | 站点当时不可达                              | —                                      | —                  | —                                                     | —                                 | ⚠️ 未实测；IA item 自带 .torrent 可替代 |
| Common Crawl                                          | ❌（e-print blob 不在抓取面）               | —                                      | —                  | —                                                     | —                                 | 不推荐                                  |

### 关键细节

- **IA `arxiv-bulk` 成员形态**（实测 tar 头 + Range 抽成员验证）：`{YYMM}/{id}.gz`（源码 e-print blob，为 tar.gz 或单文件 .gz）与 `{YYMM}/{id}.pdf`（PDF-only 投稿）混放，成员近似按月聚但不严格按 id 排序。成员即 `arxiv.org/e-print/{id}` 同款 blob——**二进制图保留**（优于 HF parquet），且 HTTP Range 可单点抽取 tar 内任一成员（扫 chunk 头定位 offset 后 Range 拉取，不必下整个 500MB）。冻结于 2020-10/11（最后 publicdate 2020-11-24）。
- **定位能力**：IA 无 manifest item、S3 manifest 需付费；但成员名自带 YYMM ⇒ 目标论文只需下载其投稿月的全部 chunk（2001=92 chunks≈46GB；早期月仅 1 chunk）。`arxiv-bulk-hashes` zipsum 提供成员级清单（按 hash 排序，当校验/存在性索引用，不带 chunk 定位）。
- **S3 manifest 格式**[^arxiv-bulk]：每 chunk 记 `first_item/last_item/num_items/seq_num/size/md5sum/timestamp/yymm`——**id→chunk 精确二分定位**；manifest 本身也 requester-pays（匿名 GET 403 实测）。全桶 2025-04 口径 ~9.2TB、月增 ~100GB。
- **HF parquet**：`latex` 列文本含 `==== FILE: name ====` 分隔的全部文本文件（.tex/.bbl/.bib/.sty），可切回文件树；**图/PDF 等二进制被丢弃**——解析 bench 够用，编译 bench 需桩化 `\includegraphics`；UTF-8 已解码，latin-1 老文件带转码痕迹。manifest（免费 GET）记每 shard 的 `first_item/last_item/num_items/yymm/sources`，46 shard 按 id 连续切分，近月独占 shard（2607: 29,687 篇/1.8GB）。
- **HF datasets-server 免下载取行**：`/rows?offset=N&length≤100` 顺序分页（row 序=id 序）；`/filter` 按 id 查询实测不稳。连续 id 段可纯 API 拉（5,000 行≈50 请求）。

## 2. 直采子集成本核算

基准（[probes.md](probes.md) §B 实测）：≥3.05s 间距 + 请求延迟 ≈ **4.42 s/req**；新式 src 命中 94.8%、PDF-only ~5%、404 重抽 ~1–2% → 每篇均耗 ≈1.05–1.10 req（GET 自检，HEAD 预检只增不减）。

| 规模       | 请求数  | 串行耗时 @4.42s | 数据量（~1–2MB/篇） | 备注                                                    |
| ---------- | ------- | --------------- | ------------------- | ------------------------------------------------------- |
| 500        | ~530    | ~39 min         | ~0.7GB              | 直采划算                                                |
| 1,000      | ~1,060  | ~1.3 h          | ~1.4GB              | 仍划算                                                  |
| 2,000      | ~2,120  | ~2.6 h          | ~2.8GB              | 拐点区                                                  |
| **5,000**  | ~5,300  | **~6.5 h**      | ~7GB                | 整夜任务；触发封禁的风险随小时数上升                    |
| **20,000** | ~21,200 | **~26 h**       | ~28GB               | 不现实：>1 天连续请求 e-print，违背 arXiv bulk 政策本意 |

对照批量渠道（同一 5,000 篇）：

| 路径                  | 字节量                                   | 耗时 @实测带宽            | 适用条件                           |
| --------------------- | ---------------------------------------- | ------------------------- | ---------------------------------- |
| IA tar（聚集选月）    | ~10–25 chunk ≈ 5–13GB                    | ~15–40min @4 并发 6.6MB/s | 「任取 N 篇」，选 1–2 个现代月即可 |
| IA tar（散选 id）     | 每篇下载 500MB chunk                     | 散选 200 chunk=105GB≈4.4h | 与直采相当，还多流量               |
| S3 tar（散选 id）     | 同上但 ~50–100MB/s+                      | 每 chunk 5–10s            | 付费后散选也占优（~$0.09/GB）      |
| HF parquet（散选 id） | manifest 定位 shard，命中 shard 数×2–7GB | shard ~10–25min @3.9MB/s  | 覆盖至 2026-07，近月 shard 小      |
| HF `/rows`（连续段）  | 0 下载                                   | 50 req API                | 仅限连续 id 段/取样                |

**拐点建议**：

- **指定论文清单 ≤~2,000 篇** → 直采最省力（无 GB 级下载、无新基础设施；~2.6h 内）。
- **「凑 N 篇真实语料」（bench 扩容典型诉求）** → 任何规模都走 IA/S3 tar：挑月=挑 era+archive，密度 ~500 篇/500MB，最快最省还零请求 arxiv.org。
- **指定清单 2k–20k 且散跨月份** → S3 付费（$0.09/GB，散选几百 chunk ≈ $10–30）> HF parquet 命中 shard 下载 > IA 整 chunk > 直采。
- **要 2020-10 之后的论文** → IA 出局；免费只有 HF parquet（至 2026-07）；要最新 + 原始 blob 树（含图）只有 S3 或直采。

## 3. 新鲜度对比

| 渠道                | 截止                                         | 延迟口径               |
| ------------------- | -------------------------------------------- | ---------------------- |
| S3 `src/`           | 上月（月更）                                 | arXiv 官方每月打包推送 |
| HF scholarweave     | **2026-07**（月同步）                        | 跟着 S3 月度 drop 跑   |
| GCS pdf             | 2025-08（停更，2025-08-24 全量重同步过一次） | 只当冷备               |
| IA arxiv-bulk       | **2020-10**                                  | 已停更 5 年 +          |
| IA collection:arxiv | ~2017-04                                     | 停更 ~9.5 年           |
| Kaggle/HF 元数据    | 周更/日更                                    | 元数据无此问题         |

benchmark 语料对新鲜度不敏感（TeX 方言演化以年计），但 2020→2026 间宏包生态有漂变（UTF-8 默认化等）——语料若要代表「当前用户会翻的论文」，2020-10 前的 IA 镜像需用 HF/S3/直采补近年代层。

## 4. 推荐路径

1. **bench 扩容（首选）**：IA `arxiv-bulk` 抓 ~10–30 个 src chunk（按目标 era/类别挑月）→ 解 tar → 成员即 e-print blob，天然覆盖全形态；5,000 篇 ≈ 几 GB、<1h、零凭据零限速。
2. **补 2020 后年代层**：HF `scholarweave/arxiv-latex`——manifest 选 2–4 个近月 shard，`FILE:` 切回文件树，图用占位桩；或直接 API `/rows` 顺序段。
3. **指定论文小批量（≤2k）**：维持 3s 串行直采，~1–2h。
4. **指定论文大批量/全量**：开 AWS 号走 `s3://arxiv`（manifest 定位 → 只拉覆盖 chunk），~$0.09/GB + GET 费。
5. **元数据**：`librarian-bots/arxiv-metadata-snapshot`（HF，日更，免 key）回填 abstract/categories/license/versions；权威慢路是 OAI-PMH 全量收割（见 [oai-pmh.md](oai-pmh.md)）。

### 参考文献

[^arxiv-bulk]: arXiv. Bulk Data Access via S3（bucket 布局/manifest 字段/requester-pays/规模口径）. info.arxiv.org / github.com/arxiv/arxiv-docs. [bulk_data_s3](https://info.arxiv.org/help/bulk_data_s3.html)

[^ia-bulk]: Internet Archive. arxiv-bulk 集合（S3 镜像 tar chunks，冻 2020-10）. [archive.org/details/arxiv-bulk](https://archive.org/details/arxiv-bulk)

[^hf-latex]: scholarweave. arxiv-latex（LaTeX 展平文本 parquet，月更）. HuggingFace. [datasets/scholarweave/arxiv-latex](https://huggingface.co/datasets/scholarweave/arxiv-latex)

[^hf-meta]: librarian-bots. arxiv-metadata-snapshot（CC0 元数据 parquet，日更）. HuggingFace. [datasets/librarian-bots/arxiv-metadata-snapshot](https://huggingface.co/datasets/librarian-bots/arxiv-metadata-snapshot)

[^gcs]: Google Cloud. arxiv-dataset（逐篇 PDF/ps/html + metadata-v5 快照，无源码）. [console.cloud.google.com/storage/browser/arxiv-dataset](https://console.cloud.google.com/storage/browser/arxiv-dataset)

[^kaggle]: Cornell University. arXiv Dataset（元数据 JSONL，周更）. Kaggle. [kaggle.com/datasets/Cornell-University/arxiv](https://www.kaggle.com/datasets/Cornell-University/arxiv)
