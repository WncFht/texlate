# arXiv LaTeX 源码数据集普查（HF / Kaggle / Zenodo / IA）

> **结论**：含真源码的 A 级数据集只有五家——scholarweave/arxiv-latex（3.12M 行/289GB parquet，文本层有损）、TIGER-Lab/arxiv-latex-5T（5.08TB 官方 tar 逐字节镜像）、archive.org `arXiv_src_*`（IA 免费镜像 →2020-10）、Mithilss/neurips-2025（3.4k 篇含二进制小而精）、KiteFishAI（边界已丢不推荐）；B 级相邻资产里 `librarian-bots/arxiv-metadata-snapshot`（CC0 3.16M 行周更）与 `cometadata/crossref-arxiv-citations`（CC0）直接可用。本语料实际组合 = IA + TIGER 主源、librarian-bots 建 frame、scholarweave 只做 dev_recent 文本层。
> **状态**：时点证据（2026-09-14 普查口径）。渠道裁决与落地角色见 `post2020-sourcing.md`、`v3-plan.md`。
> **日期**：2026-09-14

判定标准：**含 LaTeX 源码原貌** = 能拿到逐文件 `.tex`（最好含 `.bib/.sty/.cls` 等多文件工程），抽取文本/LaTeXML 结构化/PDF 文本不算。

## 一、总表（按「含源码原貌」分级）

### A 级：含真源码（可作 benchmark 底材）

| 数据集                                                       | 组织形式                                                                                                   | 规模                                       | 覆盖                                                  | License                                  | 关键缺陷                                                                                                                                                    |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------ | ----------------------------------------------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **scholarweave/arxiv-latex** (HF)                            | 46×parquet（~6.6GB/片），行=论文，`latex` 大字符串内嵌 `FILE: path` 分隔符                                 | 3,120,928 行 / 289GB                       | 全 arXiv 至 ~2026-07（月更，lastModified 2026-08-10） | dual：元数据 CC0 + 逐论文原 license      | **只保留 7 种文本扩展名**（tex/ltx/bib/bbl/sty/cls/txt），图全部丢弃；`from_utf8_lossy` 非 UTF-8 源码会被替换字符污染；~2.6% 行 latex 为空（PDF-only 投稿） |
| **TIGER-Lab/arxiv-latex-5T** (HF)                            | **原始 `arXiv_src_YYMM_NNN.tar` 逐字节镜像**（9,547 个 tar）+ `2401/` 下逐篇 `.gz` e-print                 | 5.08TB                                     | YYMM 9107→2501 **整段连续无缺月**                     | 标 apache-2.0（逐论文 license 约束仍在） | 5TB 全量；只能按月度 tar 粒度取样（每 tar ~0.3-0.5GB、数百篇混杂类目）                                                                                      |
| **archive.org `arXiv_src_*`** (IA)                           | 同一批 S3 bulk tar 的免费镜像 item                                                                         | 3,242 items                                | 9107→2010（缺 2010-11 之后）                          | 同 arXiv                                 | 覆盖停在 2020-10；无元数据字段                                                                                                                              |
| **Mithilss/neurips-2025-arxiv-latex-sources** (HF)           | 行=单文件：`arxiv_id, relative_path, filename, extension, sha256, is_text, text, content(base64 原始字节)` | 3,414 篇 / 123,952 文件行（45,808 文本行） | NeurIPS 2025↔arXiv 映射                               | other（逐论文）                          | 仅 3.4k 篇；但作为 venue 过滤 + 多文件原貌（含二进制）的小而精底材极佳                                                                                      |
| **KiteFishAI/arxiv-tex-corpus-full(80GB)/medium(15GB)** (HF) | jsonl `{paper_id, category, latex}` 单串拼接                                                               | 10⁵-10⁶ 量级                               | math/cs/hep-th/hep-ph/quant-ph/stat.* 类目过滤        | mit（声明），逐论文约束仍在              | 文件边界大概率已丢失；无版本/时间字段；`CortexEvolved/arxiv-tex-corpus-full` 是其镜像                                                                       |

### B 级：非源码但有相邻价值

| 数据集                                                                                                                    | 内容                                                                                                                     | 规模                          | License                                       |
| ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------- | --------------------------------------------- |
| **librarian-bots/arxiv-metadata-snapshot** (HF)                                                                           | Cornell OAI 元数据镜像，14 字段全（id/categories/license/versions/journal-ref/doi/abstract/authors_parsed/update_date…） | 3,164,528 行 / 2.98GB parquet | CC0，每周同步（lastModified 2026-09-14 当天） |
| **cometadata/crossref-arxiv-citations** (HF)                                                                              | `arxiv_id → citation_count, cited_by[{doi,reference}], reference_count`；3 config（all/asserted/mined）                  | 1,042,011 行 / 4.3GB          | CC0，2026-09-01                               |
| **unarXive 2024** (Zenodo 17431595)                                                                                       | LaTeXML 结构化全文 + 引用网络（非 .tex 原貌）                                                                            | 104.87GB tar.gz               | CC-BY-4.0（open subset）                      |
| unarXive 2023 (Zenodo 7752615 / Kaggle veeralakrishna 镜像 / HF howey/unarXive)                                           | 同上旧版                                                                                                                 | 4.84GB open subset            | CC-BY-SA-4.0                                  |
| **U4R/DocGenome** (HF)                                                                                                    | 500K arXiv 文档多模态结构化标注（DocParser 产物）                                                                        | 2.84TB                        | —                                             |
| Cornell-University/arxiv (Kaggle)                                                                                         | 元数据（== librarian-bots 内容源）                                                                                       | 1.83GB                        | CC0，更新至 2026-09-12                        |
| dankeg/ArxivBulkDataset (HF)                                                                                              | `{id, raw}` = **PDF 抽取纯文本**，非 LaTeX                                                                               | 194GB                         | —                                             |
| Kyudan/arXiv_latex (HF)                                                                                                   | 7.17M **公式级** TeX 片段 CSV（TeX2Image 用）                                                                            | ~千万行                       | apache-2.0                                    |
| piushorn/arxiv-latex-tables-43k / tbrrss/latextract-arxiv-math / stanford-crfm/image2struct-latex-v1 / im2latex* (Kaggle) | 表格/公式/渲染对 片段级                                                                                                  | —                             | 各异                                          |
| amrachraf/arXiv-full-text-chunked (HF)                                                                                    | 切块全文文本                                                                                                             | —                             | —                                             |
| KuoKuoYeah/dcd-arxiv_aws_src-demo                                                                                         | arXiv AWS src 小样本 demo（含 PDF）                                                                                      | 小                            | —                                             |
| kadubon/paper-tex-corpus                                                                                                  | K.Takahashi 个人 TeX 语料 + 原始 ZIP                                                                                     | ~千级                         | cc-by-4.0                                     |

Kaggle 侧另有一堆 `*/scholarweave-arxiv-latex` "Socbench train data"（0GB 空壳重传，忽略）。

## 二、scholarweave/arxiv-latex 解剖详情

- **Schema**（16 列）：`id, yymm_id, submitter, authors, title, comments, journal-ref, doi, report-no, categories, license, abstract, versions[{version,created}], update_date, authors_parsed, latex(LargeUtf8)`。
- **`latex` 字段格式**：每文件一段，头部 `==== FILE: <相对路径> ====`；实测多文件工程保留 .tex/.bib/.bbl/.sty/.cls/.txt 与目录结构（含 `tables/x.tex` 这类子路径），注释原样保留。
- **管线**（github.com/arthiondaena/arxivETL_sync，Rust）：`extract_latex_from_gz` 内 `allowed_extensions=[tex,ltx,bib,bbl,sty,cls,txt]` 白名单——**图/bst/def/数据文件全丢**；`String::from_utf8_lossy` → 非 UTF-8（老论文 latin-1 常见）会出现 U+FFFD 污染；tar 非 tar 时回退按裸 gz 文本处理。
- **分片与定位**：`arxiv_parquet_manifest.xml` 记录每片的 `first_item/last_item/num_items/size/md5/yymm 列表/来源 tar 列表`。part_0001 = 1991-07→2004-12（302,831 行）。行按时间排序，`yymm_id` 可直接按月切片。
- **体量/密度**：289GB parquet / 801GB 内存展开；`latex` 均值 68KB、中位 42KB、最大 46.8MB；空 latex ≈2.6%（旧分区样本；PDF-only/撤稿）。
- **license 字段**：~9 种值（arxiv nonexclusive-distrib、CC0、CC-BY 3.0/4.0、CC-BY-SA、CC-BY-NC-SA 等），老论文多为 null。
- **镜像**：naveenmarthala/arxiv-latex、justatomic/arxiv-latex、thejagstudio/arxiv-latex 文件名/manifest 相同，属重传镜像，首选 scholarweave 原版（维护活跃）。

**能否直接当「几千篇真源码工程」？** 能——按 categories/时间窗过滤后拉单分片切片即可（parquet 行组可部分读）。但要注意：多文件工程里**缺图**，只能覆盖文本侧陷阱（`\input/.bib/.sty/.cls` 齐全）；需图/字节级保真时改走 TIGER-Lab 或 IA tar。有损定量实测（73% 文件丢弃、.tex 零丢失、U+FFFD 7.1%）见 `post2020-sourcing.md` §5。

## 三、推荐组合

| 用途                                        | 首选                                                                                               | 备选/补充                                                                               |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| a) benchmark 底材（文本工程原貌，可控取样） | **scholarweave/arxiv-latex**（按 `yymm_id`+`categories`+非空 latex 过滤，逐分片拉）                | **Mithilss/neurips-2025**（3.4k 篇 venue 过滤、含二进制、base64 还原字节级）            |
| a') 需图/逐字节保真                         | **TIGER-Lab/arxiv-latex-5T** 按 `arXiv_src_YYMM_NNN.tar` 挑月下载（0.3-0.5GB/tar）                 | **archive.org `arXiv_src_*`**（9107-2010 免费直链，可做老论文陷阱集）                   |
| b) 分层抽样键表                             | **librarian-bots/arxiv-metadata-snapshot**（CC0、14 字段、周更、3.16M 行，离线 parquet join `id`） | scholarweave 自带同套元数据列（可省一次 join）；Kaggle Cornell-University/arxiv 同源    |
| c) 质量权重                                 | **cometadata/crossref-arxiv-citations**（`arxiv_id→citation_count`，CC0）                          | librarian-bots 的 `journal-ref`/`doi` 做 venue 信号；Mithilss 的 NeurIPS 映射做顶会切片 |

**落地取样流水线**：librarian-bots parquet 分层抽 id（categories×年代×license）→ crossref citations join 权重 → scholarweave 按 id 取 latex（或 Mithilss/TIGER 取原始工程）→ `bench/corpus/` 登记 MANIFEST。
