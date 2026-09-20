# arXMLiv / unarXive 深挖 —— 学术发行物能否提供 LaTeX 源码底材

> **结论**：两家都不发行 LaTeX 源码——arXMLiv/ar5iv 发的是 HTML5 转换产物（SIGMathLing NDA / C-UDA 授权），unarXive 发的是结构化 JSONL（CC-BY 系）。源码底材走 scholarweave/IA/TIGER 三家（见 `hf-latex-datasets.md`）。unarXive 的生成代码仍有四件可借鉴：`\begin{document}` 主文件定位、latexpand flatten oracle、tralics 预处理 regex、5s timeout 口径。
> **状态**：时点证据（2026-09-14 实测口径）。
> **日期**：2026-09-14

## 0. 裁决表

| 语料 | 发行物内容 | 含 LaTeX 源码？ | 获取门槛 | license 可否再分发 |
| --- | --- | --- | --- | --- |
| arXMLiv 2020（最新 arXMLiv 牌） | 1,581,037 篇 HTML5+MathML | **否** | SIGMathLing 会员 + 互惠 NDA | **不可**（NDA 明示仅限会员） |
| ar5iv-dataset-04.2024（后继版） | 2,170,799 篇 HTML，按 severity 分 3 包 | **否** | Google Form 签 C-UDA-1.0 | C-UDA：计算用途可、数据本体不可再分发 |
| unarXive 2022 open subset | 结构化 JSONL（正文 + 引用标注） | **否** | Zenodo 直下，CC-BY-SA-4.0 | 可（但只有 JSONL 无源码） |
| unarXive 2024 | 同上 JSONL，104.9GB tar.gz | **否** | Zenodo 直下，CC-BY-4.0 | 可 |
| **scholarweave/arxiv-latex（HF）** | **3,120,928 篇文本类源文件全量** | **是（有损）** | **免 key 匿名直下** | 镜像 arXiv ToU，逐篇 license 字段 |

## 1. arXMLiv（kwarc/LaTeXML）发行物解剖

入口：`sigmathling.kwarc.info/resources/`（`arxmliv.kwarc.info` 已死，TLS 失败）。发行列表：082017 / 082018 / 082019 / 2020 / ar5iv-dataset-2024。

### arXMLiv 2020（最新一版 arXMLiv 牌）

- 内容：**仅 HTML5+MathML 转换产物**（LaTeXML 0.8.5 + CorTeX 0.4.3），1,581,037 篇，覆盖到 2020 年底；354 个 ZIP，按 arXiv yymm 命名。236GB 打包 / 2.1TB 解包，需 160 万 inode。**无源码、无图**。
- **severity 标签随发行物给**：`meta/grouped_by_severity.zip` 含逐文档 LaTeXML 转换状态（no_problem/warning/error/fatal 体系，见 LaTeXML manual error codes）。
- 下载："Download links" 指向 `gl.kwarc.info/SIGMathLing/download-links` 私有 repo——**实测未登录 302 到 sign_in**，必须会员。
- License：**SIGMathLing 互惠 NDA**——"right of distribution was only given (or assumed) to arXiv itself"，数据集仅授权会员做 research/tool development，**不可再分发**。加入免费但本质是给 KWARC 一个法律把柄。

### arXMLiv 08.2019（severity 物理分包的起始版）

- 1,374,539 篇；四个 ZIP 直接按 severity 切：no_problem 150,701（7.4GB）/ warning_1 500,000（75GB）/ warning_2 328,127（50GB）/ error 395,711（60GB）。
- 同样 NDA-only。**含义：难度分级标签确实是他们家的招牌设计，但锁在会员墙后。**

### ar5iv-dataset-04.2024（事实上的最新发行，arXMLiv 项目改名续作）

- 2,170,799 篇 HTML（LaTeXML 0.8.8 + CorTeX 0.4.5），源版本冻于 2024-02-22；318GB / 2.9TB；**明示 "HTML-only, does not include images"**。
- severity 三包：no_problem 366,232（20GB）/ warning 1,304,052（216GB）/ error 500,515（82GB），MD5 公开。
- License：**C-UDA-1.0**（微软 Computational Use of Data Agreement），Google Form 申请 → 发链接。比 NDA 轻——允许「计算用途」产出，但数据本体再分发仍受限。
- 注：此 HTML 同时是 ar5iv.labs.arxiv.org 线上站点的种子数据。

## 2. unarXive 发行物解剖

渠道：Zenodo（github.com/IllDepence/unarXive 是生成代码 + 文档，不驻留数据）。作者单位实际是 KIT Karlsruhe。

### 发行版矩阵（Zenodo API 实测）

| record | 版本 | 访问 | license | 内容 | 体积 |
| --- | --- | --- | --- | --- | --- |
| 3385851 | 2019 | restricted | other-at | 旧格式 JSONL | 文件隐藏 |
| 4313164 | 2020 | restricted | other-at | 旧格式 JSONL | 文件隐藏 |
| 7752754 | 2022 full | **restricted（申请制）** | — | 全量（含非 permissive 论文） | 页面标 59.4TB，文件列表不可见 |
| 7752615 | 2022 **open subset** | open | CC-BY-SA-4.0 | permissively-licensed 论文子集 | `unarXive_230324_open_subset.tar.xz` 4.84GB |
| **17431595** | **2024** | **open** | **CC-BY-4.0** | 同 JSONL schema | **`unarXive_2024.tar.gz` 104.9GB** + preview.jsonl |

- 格式（README+preview 实证）：`<yy>/arXiv_src_<yymm>_<num>.jsonl`，每行一个 paper 对象：`paper_id / _source_hash / _source_name / metadata(OAI 全字段) / discipline / abstract / body_text[{section,sec_number,sec_type,content_type,text,cite_spans,ref_spans}] / bib_entries / ref_entries`。正文里 `{{cite:uuid}}`/`{{formula:uuid}}`/`{{figure:uuid}}` 占位符指向 ref_entries（公式保 LaTeX 串）。
- **没有一行 LaTeX 源码**——连「展开后单文件」都不给，只有抽完的正文 + 标注。规模：2022 版 1.9M 篇 / 63M 参考文献 / 134M 文内引用标记 / 742M 公式片段；2024 版口径更大（105GB gz）。
- 结论：价值 = 0 源码 + 可白嫖的**结构化正文对照物**（若以后做「解析输出对拍」可参考其 schema），以及**生成代码可对照**（下条）。

### unarXive 源码对我们的可借鉴点

他们的 normalize→flatten→tralics 路线：

1. **主文件定位**：遍历 tar 内 `.tex`，正则 `\\begin\s*\{\s*document\s*\}`（**非 `\documentclass`**）；注意实现细节——循环内 `main_tex_path` 反复覆写且无 break，**tar 序最后一个含 `\begin{document}` 的 .tex 胜出**（多 docclass 工程取尾不取头，与我们「独立根检测」语义不同，对拍时注意）。fallback：扫非 .tex、非二进制扩展名文件找同模式。
2. **flatten**：`latexpand [--expand-bbl <main>.bbl] <main.tex>`（cwd=解压目录）——仅当 `<主文件同名>.bbl` 存在才加 `--expand-bbl`。输出重读重写统一 UTF-8。**latexpand 可作 \input 解析的 oracle 对拍器**（texlive-extra-utils 自带，递归展 \input/\include/bbl）。
3. **tralics 预处理**：两条 regex 手术——natbib `\cite(t|p|alt|alp|author|year|yearpar)*[..]{k}` → `\cite{k}`；`\bibitem[..]` → `\bibitem`（注释自承 mnras 风格搞不定）。这是「为下游引擎改写源码」的先行案例，与 normalize 手术包同构。
4. **tralics 调用**：`-silent -noxmlerror -utf8 -oe8 -entnames=false -nomathml`，**timeout=5s/篇**——1.9M/2.3M 的覆盖率是 5 秒硬砍出来的，不是解析成功率高。
5. **他们的丢弃面**（我们的边缘语料）：无 `\begin{document}` 的档案、latexpand/tralics 失败、XML 不合法——全部进 log 不进库。

## 3. 同生态顺带核查

- **S2ORC**：解析后全文（LaTeX 源经 tralics 系/ScienceParse 系），无源码；下载需 API key（`datasets.md` 已实测 401）。unarXive 输出 schema 自述 "S2ORC like JSONL"。
- **ar5iv 线上**：`ar5iv.labs.arxiv.org/log/{id}` 提供逐篇 `Status:conversion:N` 报告——**免费的 per-document severity 懒取通道**，可替代锁在会员墙后的 grouped_by_severity.zip（代价是逐篇请求）。
- **NIST**：只是 LaTeXML 手册/error codes 文档托管处（Bruce Miller 单位），无独立语料。
- **Academic Torrents**：本轮连不上（socket 级失败），历史上只有 2016 Kaggle 时代的 stale arXiv 镜像，无追价。
- **HF `saier/unarXive_*`**：citrec/imrad_clf 任务切片，非全量。

## 4. 顺带复核：scholarweave/arxiv-latex 解剖

（登记项见 `hf-latex-datasets.md` §二，本轮实测补齐。）

- **规模/格式**：3,120,928 行（=论文数），46 个 parquet 分片共 **289.2GB**；`latex` 列为 gitingest 风格 `==== FILE: <相对路径> ====` 文本树。**非 gated，匿名 Range GET 实测 206 拿到 PAR1 头**；月更，配套 manifest xml 带逐分片 MD5/ID 区间。
- **白名单扩展名**（ETL `lib.rs` 实锤）：`tex/ltx/bib/bbl/sty/cls/txt`——**图、PDF、.eps 全丢**。多文件工程目录结构保留（实测 `sec/0_abstract.tex` 这类子路径、`main.bbl`/vendored `.sty` 都在）。
- **有损点**：`String::from_utf8_lossy`——非 UTF-8 字节已变 U+FFFD，latin-1/cp1252 源在该镜像里**字节级已损毁**；编码陷阱 fixture 不能用它建。
- 元数据列与 OAI 快照全对齐（含 `license`、`versions`），正好当抽样分层键。
- 生成管线开源：`arthiondaena/arxivETL_sync`（Rust），内含 **`scripts/reconstruct_tar.py`——现成的 FILE 树→tar 重建器**，等于把 parquet 行还原成源码工程目录。
- 克隆项：`thejagstudio/arxiv-latex` 同构 50 文件镜像，可作备胎。

## 5. 适配建议

1. **大规模 benchmark 底材**：arXMLiv/unarXive 均出局；走 scholarweave 直下 parquet → `reconstruct_tar.py` 或按 `FILE:` 分割落盘成工程目录（已落地为 dev_recent 层）。几千~几万篇分层抽样成本 = 几十个 GB 级分片选择性下载（按 manifest 的 ID 区间选片即可，无需全量 289GB）。
2. **分层键设计**：`categories`（领域）× `yymm_id`（年代=TeX 方言）× `license`（可发布性）三维都在行内；**文件数/是否多文件工程**可离线从 FILE 标记数派生。LaTeXML severity 标签想要需走 SIGMathLing 会员（NDA）或 ar5iv `/log/` 懒取——但那是「HTML 转换难度」，与「重编译难度」相关性弱，**不建议为它付会员成本**；我们自己的 tectonic/xelatex verdict 才是真难度标签。
3. **补图/补真字节**：scholarweave 丢图 → 编译链 benchmark 的图依赖从 `s3://arxiv` 单 tar（requester-pays）或 e-print 懒拉补；非 UTF-8 fixture 同理必须回 S3/e-print 取真字节。
4. **license 风险**：scholarweave 镜像 arXiv ToU——若公开发布语料子集，逐篇过滤 `license` 字段（CC-*/public domain）或只发布 ID 清单 + 重建脚本；arXMLiv NDA 与 unarXive restricted 版同理不可碰再分发。
5. **可对照实现**：`latexpand`（flatten oracle）+ unarXive 主文件探测（`\begin{document}` 尾匹配）是值得对拍的两件白捡物；tralics 5s-timeout 覆盖率数据可当「严格解析器」基线参照。
