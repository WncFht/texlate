# post-2020 批量源码渠道实测裁决

> **结论**：post-2020 主语料用 `TIGER-Lab/arxiv-latex-5T`（1991-07→2025-01 连续 403 月零缺口，byte-exact 已实证：与 IA 同月 tar 对拍 123/165 成员 sha256 全同、42 差异全是上游 v2+ 修订）；2025-02 之后只有 `scholarweave/arxiv-latex` 覆盖（有损，限文本层用途）。裁决已落地：e 带 6 簇走 TIGER，dev_recent 层走 scholarweave。
> **状态**：已完成（2026-09-14 实测裁决；裁决口径仍现行——渠道角色分工未变）。
> **日期**：2026-09-14

数据只来自 huggingface.co 与 archive.org（未触 arxiv.org/S3/OAI）。总下载 1.61GB。

## 裁决

|               | **TIGER-Lab/arxiv-latex-5T**                                 | **scholarweave/arxiv-latex**                                                 |
| ------------- | ------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| 字节保真      | ✅ 成员 = 官方 e-print blob 逐字节（快照时点 2025-04）；含图 | ❌ 有损：仅 7 种文本扩展名白名单（tex/ltx/bib/bbl/sty/cls/txt），UTF-8 lossy |
| 覆盖          | 1991-07 → **2025-01**，403 个月逐月无缺，9,547 chunk         | 1991-07 → **2026-07**（shard 0046, ts 2026-08-10），月更                     |
| 粒度          | `arXiv_src_YYMM_NNN.tar`，~0.53GB/块，2024 年每块 ~150 篇    | 46 shards × 2-9GB；duckdb httpfs 可按 id 谓词下推，不必整 shard 下载         |
| 单篇成本      | ~3.7MB/篇（2024 chunk 口径）；散选需拖整月 chunk             | ~0.24MB/篇 latex 文本；散选靠 row-group 修剪只拉命中段                       |
| parse bench   | ✅ 全保真（实测与 SW 同 funnel）                             | ✅ **.tex 零丢失**，等价可用                                                 |
| compile bench | ✅ 图/.bst/.bbx 全在，直接可编译                             | ❌ 82% 论文丢图、35% 丢 .bst——不桩化不可用                                   |
| 新鲜度        | 冻 2025-01（之后无 chunk）                                   | 月更至 2026-07——唯一覆盖 2025-02 后                                          |
| 风险          | 第三方镜像，官方更新节奏不可控                               | 有损 ETL，字段语义依赖单一维护者                                             |

裁决细则：

1. **post-2020 主语料用 TIGER-5T**（覆盖 2020-11 → 2025-01）。byte-exact 已实证（§3），成员含图/.bst/.bib 全套——parse 与 compile 两级 bench 通吃。~1,200 篇目标 ≈ 8 个 2024 chunk ≈ 4.4GB、单线程 ~20min @3.7MB/s（可多连接提速）。
2. **2025-02 之后的 strata 只能用 scholarweave**（TIGER 止于 2025-01）。该层只能做 parse 级实验，或需直采/付费 S3 补图。
3. **scholarweave 的定位**：文本层规模实验的正源——全历史 3.12M 行、.tex 逐字保真（实测 845/845 共享文件内容一致）、id 可远程定位。适合「全量 parse 统计 / 方言演化 / 翻译文本抽取」；**不适合** compile/fixloop bench（图与 .bst 缺失）与字节级校验。

## 1. TIGER-5T 清单

- repo `TIGER-Lab/arxiv-latex-5T`：12,058 个对象 = 9,547 个 `arXiv_src_YYMM_NNN.tar` + 2 个散逸解压目录（`arXiv_src_0001_001/` 2,367 文件、`2401/` 135 文件，疑为开发者遗留测试）+ README/.gitattributes。无 pdf tar 集（src only）。
- 月度覆盖：**9107..2501 连续 403 个月零缺口**（含 9107；总 5.08TB 与 usedStorage 一致）。
- 每月 chunk 数随年代增长：2020=789 块/446GB，2021=1,102/602GB，2022=1,280/693GB，2023=1,577/850GB，**2024=2,012 块/1,075GB**（134-202 块/月），2025-01=154 块/82GB。单块 0.11-0.72GB、中位 ~0.53GB。
- 文件 size/sha256 由 HF tree API 递归取得，下载件 sha256 与 LFS oid 逐字节吻合。

## 2. TIGER 下载与成员实测

- `arXiv_src_2408_001.tar` 556,554,240B，HF resolve 单流 **3.76MB/s**（148s）。成员 150 个，命名 `2408/2408.NNNNN.gz|pdf`——**成员名无版本号**（blob 即快照时点最新版 e-print）。
- 三态占比：tgz 129（86.0%）/ 单文件 gz 11（7.3%）/ pdf-only 10（6.7%）。对照 2008_001:132/15/18（80.0%/9.1%/10.9%）。315 个成员合计 tgz 82.9%。
- n_tex：中位 1、p90 12（2408_001）。docclass 前列：article 44、revtex4-2 16、IEEEtran 6、elsarticle 6、mnras 6、revtex4-1 6。
- IA 同文件下载 **16.2MB/s**——IA 带宽约为 HF 4-5 倍，可惜 IA 止于 2020-10。

## 3. byte-exact 验证（`arXiv_src_2008_001.tar` TIGER vs IA）

| 口径                                                                    | 结果                                                                                                                                                                                               |
| ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 整文件 sha256                                                           | **不一致**（TIGER 527,564,800B vs IA 528,148,480B）                                                                                                                                                |
| 成员集合/顺序                                                           | **165/165 完全一致**（同名同序）                                                                                                                                                                   |
| 成员 sha256（对 IA zipsum col2，经验证 col1=sha1 col2=sha256 col3=md5） | **123/165（74.5%）逐字节一致**                                                                                                                                                                     |
| 42 个不一致成员                                                         | 全部 .gz 源 blob（tgz 40 + 单文件 2）；**pdf 成员 18/18 全一致**                                                                                                                                   |
| 不一致成员内层 diff                                                     | 文件名改期（`draft_0731.tex`→`draft_1025.tex`）、图增删、格式转换（png→jpg）——**典型 v2+ 修订痕迹**，即 S3 桶只存最新版 e-print，IA=2020-10 快照、TIGER=2025-04 快照，间期内被修订的论文 blob 不同 |

**结论：TIGER 是真镜像。** 74.5% 成员与其 4.5 年前的官方快照逐字节一致（若 TIGER 重打包/重压 gzip，命中率应≈0）；42 个差异全部由上游修订解释。容器 tar 本身 size 不同（成员内容长度变化所致），但 member 级保真成立。

## 4. scholarweave 实测

- 结构：46 个 `arxiv_part_NNNN.parquet`（2-9GB）+ `arxiv_parquet_manifest.xml`（每 shard 记 first_item/last_item/num_items/yymm/sources 源 tar 名）。shard 按 id 连续切分、零重叠。
- schema：`id, yymm_id, submitter, authors, title, comments, journal-ref, doi, report-no, categories, license, abstract, versions[], update_date, authors_parsed, latex`。
- `latex` 格式：`====…(48)\nFILE: <name>\n====…\n<content>\n\n` 逐文件块。
- **duckdb httpfs 远程谓词下推可用**：`WHERE id IN (140 ids)` 打 6.33GB shard 0028，35s 返回全部 140 行（33.4MB 文本），零整文件下载。140 个 gz 成员 id 全命中；10 个 pdf-only 成员 id 行存在但 `latex IS NULL`。

## 5. scholarweave 有损定量（140 篇 vs TIGER 同 id 树）

| 项                                             | 数字                                                                                                                                                           |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TIGER 树总文件                                 | 3,128                                                                                                                                                          |
| SW 保留                                        | 856（845 共享名 + 11 重命名单文件——SW 把单文件成员改写为 `{id}.tex`，非 `main.tex`，仍计入保留）                                                               |
| **总丢弃**                                     | **2,272（72.6%）**                                                                                                                                             |
| ├ 二进制/图（.pdf/.png/.eps/.jpg/.jpeg/.tif…） | 2,133（68.2%），**82% 论文受影响**                                                                                                                             |
| └ 非图文本（真损失）                           | 139                                                                                                                                                            |
| 非图损失明细                                   | .bst **63**（49 篇=35%）、biblatex 系 .bbx/.cbx/.dbx/.lbx/.clo 10、.dtx/.ins 4、文档 .md/.docx/.xml/无扩展 ~15、构建垃圾 .out/.aux/.toc/.fls/.log/.pygtex… ~50 |
| **.tex 丢失**                                  | **0**（528/528 全在）                                                                                                                                          |
| 共享文件内容一致性                             | **845/845 逐字一致**（rstrip 尾换行后；SW 每文件尾补 `\n\n`）                                                                                                  |
| U+FFFD                                         | 10/140 篇（7.1%）、385 字符——非 UTF-8 字节被替换的硬证据                                                                                                       |
| 空 latex                                       | 0/140（gz 成员）；pdf-only 成员 = NULL 行（样本内 10/150=6.7%）                                                                                                |

**SW 白名单 = 7 种扩展名**：`.tex .ltx .bbl .bib .sty .cls .txt`（上游 ETL lib.rs `allowed_extensions` 实锤；本 140 篇样本内 `.ltx` 未出现，故实测只见 6 种）。其余全部丢弃。

## 6. parsebench funnel 对拍

| corpus            | papers | .tex | ok          | identical | leak              |
| ----------------- | ------ | ---- | ----------- | --------- | ----------------- |
| tiger-corpus-2408 | 150    | 528  | **528/528** | 528       | 38/25,976 (0.15%) |
| sw-corpus         | 140    | 528  | **528/528** | 528       | 38/25,976 (0.15%) |

两者逐文件指标完全一致——SW 丢的 .bst/.bib 附属与图不参与 parse 评测；.tex 全集保真 ⇒ **parse 级 bench 上 SW 与 TIGER 等价**。

## 7. 阻塞项 / 意外发现

- **TIGER 与 IA 非同快照**：42/165 成员差异是上游修订所致，非损坏——用 IA 做 TIGER 校验只能验「未修订成员」子集；要验修订成员需同时点第三方参照（不存在）。对语料库无影响（修订版就是想要的最新版）。
- **TIGER 冻于 2025-01**：之后 20 个月（至 2026-07）只有 scholarweave 覆盖；若 benchmark 需要 2025-02+ 语料，SW 是唯一免费批量源（有损），或直采。
- **SW pdf-only 行 latex=NULL**：全局空率口径即「PDF-only 投稿占比」；语料抽样时须过滤 `latex IS NULL`。
- **SW 单文件成员命名**：`{id}.tex`（非 main.tex）——重建脚本需按此约定。
- **TIGER 散文件残留**：`arXiv_src_0001_001/`、`2401/` 两个解压目录与 tar 并存，抓清单时按 `arXiv_src_*_*.tar` 正则过滤即可。
- `arXiv_src_0106_001.tar.0EFff526`：一个上传残留临时文件，非数据。
