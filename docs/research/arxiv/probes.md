# arXiv 主站串行探针实录（两波合并）：线缆格式 / 条件请求 / 旧 id 归并 / license 机读位 / HTML 版本矩阵 / v-diff 复用率 / 190 发大样本

> **结论**：HEAD `/src/{id}` 的 content-disposition 后缀（`.tar.gz`/`.gz`/`.pdf`）即 hasSrc+格式预检；条件请求 304 全面支持；旧式 id `math.AG/`、`HEP-TH/` 均 301 归并 archive 小写形；`/html/{id}` latest 可能是 includepdf 包装壳 stub，须逐版本回退探测；v1→latest 的 .tex 行复用率中位 0.52 → 增量重翻可省 ~50–85%；旧式 id 源码率 98.1%、新式 94.8%、遗留格式零观测。
> **状态**：时点证据（2026-09-14 口径，两波合计 ~296 发、间隔 ≥3.1s、零并发）。结论已并入 [layer.md](layer.md) 并实装进 `src/texlate/arxiv/`（fetch 的 cd 三态解析/304 重验证、sniff 的 wrapper 检测、ratelimit 的断路器）。
> **日期**：2026-09-14 取证，2026-09-20 重订入库（并原名映射：`serial2.md` → 本文 §B）

本文合并同一日的两波 arxiv.org 主站探针：§A 端点机制面（content-disposition/条件请求/归并/license/HTML/发现层/类目表），§B 规模化面（v-diff 版本表/官方 PDF/190 发抽样）。原始逐发记录为开发机现场，结论已摘要进正文。

## A. 第一波：端点机制

### A.1 content-disposition 后缀 = 三态判别（销 layer.md 待验项）

| 形态        | 文件名例                                | 附带信号                        |
| ----------- | --------------------------------------- | ------------------------------- |
| tar 多文件  | `arXiv-2203.02155v1.tar.gz`             | `content-type: application/gzip` |
| 单文件 .gz  | `arXiv-0807.5094v1.gz`（裸 .gz 非 .tex.gz） | 同上                            |
| 旧式单文件  | `arXiv-math0404188v6.gz`（id 去斜杠拼）  | 裸 id 解析到 v6 并写进文件名    |
| PDF 直投    | `arXiv-1602.03837v1.pdf`                | `content-type: application/pdf` 双信号 |

一次 HEAD 即定格式分支 + hasSrc 判决；`/e-print/{id}` 301 → `/src/{id}`（新代码直接打 `/src/` 少一跳）；`accept-ranges: bytes` 支持 Range 取魔数。

### A.2 条件请求 304

`If-None-Match` 与 `If-Modified-Since` 对 `/src/` 均回 304（`via: 1.1 varnish`）。etag 两形态并存——新对象 `"sha256:{hex}"`、旧对象 GCS 风格短串（如 `"CJC2qdH9pvICEAE="`）——**存原样串整体回送，不要解析**。etag 变则回 200 拿新 body，天然覆盖「同版本被 replacement」。

### A.3 旧式 id 归并

- `math.AG/0301001` →301→ `/abs/math/0301001`：**subject-class 写法归并到 archive 形式**，`.AG` 不进 canonical id（canonical link 与 `citation_arxiv_id` 均指 archive 形）。
- `HEP-TH/9901001` →301→ `hep-th/9901001`：大小写归一到全小写。
- 落地归一化规则：`{archive}.{subj}/NNNNNNN` → `{archive}/NNNNNNN`，整体 lower-case。引用语料里 `math.AG/…` 写法常见，不归一会重复计数。（实测 math.AG、HEP-TH 两例；nlin/cs 的 subject-class 写法按同构推断。）

### A.4 许可证机器可读位

- abs 页标记 = **`div.abs-license > a[href]`，href URL 即枚举值**；CC 类附 `class="has_license"` + 图标。已观测取值：`arxiv.org/licenses/nonexclusive-distrib/1.0/`、`arxiv.org/licenses/assumed-1991-2003/`（pre-2004 旧文专属）、`creativecommons.org/licenses/by/4.0/`。
- 无 `rel="license"`、无 `citation_license` meta；页内 `rdf:RDF` 块只含 trackback:ping。
- **RSS `dc:rights` 用同一 URL 词表**——批量取 license 不必逐篇爬 abs。
- `citation_doi` meta 只在有正式 DOI 时出现，**不回填 `10.48550/arXiv.*`**。

### A.5 HTML 逐版本覆盖矩阵

| id         | `/html/{id}`          | `{id}v1`              | `{id}v2`              | 解读                                     |
| ---------- | --------------------- | --------------------- | --------------------- | ---------------------------------------- |
| 2501.14787 | 200 · 1912286B        | 200 · 同 etag 同 size | 404                   | 单版本                                   |
| 1706.03762 | 200 · 188707B         | 200 · 180979B         | 200 · 204363B         | ≥3 版本，逐版本独立 etag/size（latest=v3）|
| 1412.6980  | 200 · **20827B stub** | 200 · 150059B         | 200 · 290669B         | latest=v9 为包装壳 stub                  |
| 2203.02155 | 200 · 679724B         | 200 · 同 etag 同 size | 404                   | 单版本                                   |
| 2605.15481 | 200 · 272315B         | 404                   | 200 · 同 etag 同 size | 边缘案复现：v1 无 HTML、v2 有            |

公共特征：全部 `x-robots-tag: nofollow`；`rel='canonical'` 恒指无版本形；每版本独立内容寻址 etag；`last-modified` 是页面再生日（曾观测整批 2026-08-24 重建），非论文时间。

### A.6 第四态源码形态：PDF 包装壳

1412.6980 v9 的 e-print 是合法 tar.gz + 含 `\documentclass` 的主文件，但正文仅 `\includepdf[pages=1-last]{0_adam_main.pdf}`；其 LaTeXML HTML 也是 20KB stub（正文只有「See pages 1-last of 0_adam_main.pdf」一行）。v9 e-print 仅 2 个文件（壳 tex + PDF），v1 的 19 个正文文件全删——**"latest 有源码" ≠ "latest 可翻"**；复用旧版译文也必须先对新版做正文含量检查。判据与 DOM 信号见 [html-path.md](html-path.md) §5。

### A.7 发现层

- `arxiv.org/rss/{cat}` →302→ `export.arxiv.org/rss/{cat}`（**export 桶**，与 Atom API 同池）：cs.LG 实测 558KB / 260 item，每条含 `guid=oai:arXiv.org:{id}v{n}`（带版本）、`announce_type`（new/cross/replace/replace-cross）、`dc:rights`（license URL）、`dc:creator`、标题+摘要；`skipDays` Sat/Sun（工作日日更）。信息密度远高于 list 页，**日更种子源首选**。
- `arxiv.org/list/{cat}/new`（arxiv.org 桶）直出 818KB HTML，三节 New/Cross/Replacement 同数 260——主站桶热备。

### A.8 类目表

`/category_taxonomy` 落盘 84KB：`<h3>` archive 组 + `<h4>` 类目 ×155，覆盖全部现行 subject class；**退役 archive 不在表内**（alg-geom/dg-ga/funct-an/q-alg 等）→ 旧式 id 白名单不能从该表生成，需手工维护。

## B. 第二波：版本表 / v-diff / 官方 PDF / 190 发大样本

### B.1 版本表机制（10 id，HEAD 逐版探测 404 定界）

8/10 有多版本：1412.6980→v9、1706.03762→v7、2005.11401→v4、1403.3985→v3、1810.04805/2106.09685/1801.02634/2003.08934→v2；1512.03385、2203.02155 单版本。知名论文改版是常态，v-diff 缓存问题真实存在。版本包大小可剧烈变化（2106.09685 v1→v2 从 1.83MB 砍到 917KB，换 ICLR 模板）。

### B.2 v1→latest 逐对 diff：增量重翻可省 ~50–85%

口径：`tex_reuse_new` = 全树 .tex 行多重集交集 / 新版全部 .tex 行（改名/搬动不罚，最贴「省翻率」）；`reuse_new` = 同名文件对齐 equal 行占比（偏乐观）。

| id         | 版本跨度 | tex_reuse_new | reuse_new | 备注                                       |
| ---------- | -------- | ------------- | --------- | ------------------------------------------ |
| 1801.02634 | v1→v2    | **0.9985**    | 0.9997    | 近乎纯增补                                 |
| 1706.03762 | v1→v7    | **0.8258**    | 0.9084    | 6 版演进仍保留 83%                         |
| 2003.08934 | v1→v2    | **0.6102**    | 0.8599    |                                            |
| 2005.11401 | v1→v4    | **0.4555**    | 0.8877    | v4 新增大段 tex                            |
| 1810.04805 | v1→v2    | **0.4799**    | 0.8652    | sections/→根目录大搬家                     |
| 1403.3985  | v1→v3    | **0.5502**    | 0.3247    | 换类 + .bbl 552→1793 行全换                |
| 2106.09685 | v1→v2    | **0.4612**    | 0.2716    | NeurIPS→ICLR 模板整套换（sty/bbl/bst 全删） |
| 1412.6980  | v1→v9    | (0.357)       | —         | 边缘案不入统计：v9 正文归零                |

统计（7 对正常）：tex_reuse_new **中位 0.52 / 均值 0.59**；reuse_new 中位 0.87 / 均值 0.73。推论：

- 行级 verbatim 复用下界 ~50–60%；按段落哈希 + ~0.9 相似度模糊匹配可望推到 **60–85%**——「出新版重翻」用增量缓存能省一半以上。
- **缓存配对键必须按内容指纹而非文件名**——改名/结构搬家（1810.04805）与换模板/换 bib 工具链（1403.3985、2106.09685，~45–55% 流失来自 preamble/bbl 整体替换）是主损耗。
- `.bbl` 差异是噪声大户（bib 工具重生成即全文换血）；翻译只消费 .tex，bbl/sty 变化不计入重翻量。

### B.3 官方 PDF 下载事实

`GET /pdf/{id}` 200 直出，`content-disposition: inline; filename="{id}v{N}.pdf"`（**inline**，与 `/src/` 的 attachment 不同）；15/15 全部 ≤8.8MB。旧式 id 落盘注意嵌套目录（`math/0404188.pdf`）。保真度对拍见 [pdf-fidelity.md](pdf-fidelity.md)。

### B.4 190 发大样本（HEAD 判定，未下载）

采样：旧式 12 archive × 3 个 YYMM(1996–2006) × 2 seq，404 重抽一次；新式 2008–2026 按月均匀，同法。

| 池            | n   | tar.gz | 单文件 .gz | PDF-only | 404    | 其他  |
| ------------- | --- | ------ | ---------- | -------- | ------ | ----- |
| 旧式（96–06） | 92  | 37     | 15         | 1        | **39** | **0** |
| 新式（08–26） | 98  | 77     | 15         | 5        | 1      | **0** |

源码率（剔除 404）：旧式 **98.1%**（52/53）、新式 **94.8%**（92/97）；合并 wave-1 前 60 篇基线后新式口径 91.7%——「老论文几乎必有 TeX」实证；旧式 PDF-only 唯一一例是 cond-mat/9610071。

- **旧式单文件率 28.8% ≈ 新式 16.3% 的 2 倍**——老论文更常单 tex 直投，解包必须保住单文件 .gz 分支。
- **遗留尾巴零观测**：190 发 200 响应里只有 `.tar.gz`/`.gz`/`.pdf` 三类——`.ps.gz`/`.dvi`/`.doc`/纯文本 0 例（含 1996–1999 最老样本），rule-of-three 真实「其他」率 <1.6%（95%）→ 三态判决对 ~98.4% 语料充分，「其他」桶记 unknown 人工看即可，无需预建 dvi/ps 工具链。
- **旧式 id 稀疏坑**：39/92 旧式请求 404——seq≤099 并不稠密（nucl-ex 9/11、cs 8/10、hep-lat 6/9；math/9710、cs/9603、cs/9709、hep-ph/9909 整月全灭）。成因：低流量 archive-month 月投稿 < 抽取序号。**枚举式抓取必须容忍大量 404，不能用「seq 连续」做完整性假设**；引用图发现 id 的路线正好规避此坑。
- 预算注记：本波 258 发触顶停发，2025–2026 新式样本 n≈2，新式统计实际覆盖 2008–2025。

### 参考文献

无新增外部来源；全部为本机探针实测（UA 自报、≥3.1s 间隔、零并发纪律）。相关官方端点语义见 [layer.md](layer.md) 参考文献。
