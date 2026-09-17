# 06 · arXiv 源获取层规格

> 最终技术方案 · arXiv 接入与批量取数。
> 证据基础：`docs/research/arxiv/layer.md`（在线层实测）、`docs/research/corpus/ia-pilot.md`（IA 管道 pilot）、`docs/research/corpus/post2020-sourcing.md`（post-2020 渠道裁决）、`docs/research/corpus/frame-and-allocation.md`（frame）。
> 本文是规范（normative）：实现按此执行；研究文档只作证据出处，不再回查。
> 落地注记（2026-09-16）：§3 元数据层已全落（`arxiv/meta.py`：Atom 主源 + OAI-PMH 兜底 + `PaperMeta` schema + `resolve_version`/`degrade`，`d7b3c0a` + `test_arxiv_meta.py`）；§5 降级链 `degrade()` 裁决层已落（L2 html/L3 pdf sidecar 判空），babeldoc sidecar 进 worker 产品链（`server/babeldoc.py`，`8d50c38`）。
> 落地注记（2026-09-17，G1 arxiv-html-first）：§5 L2 HTML 臂全链已落——`arxiv/html.py`（`fetch_html`/`parse_arxiv_html`/`marked_html`/`doc_chunks`/`reinsert` + `Fetcher.get_path` 跨镜像，`9fab8bf`/`407f1db`）；产品链 `options.source=html` → `kind=arxiv_html` worker emit（`6767726`/`ebf462a`/`792fd0d`，详见 `research/product/web-layer.md`）。

## 0. 定位与两个消费方

本层服务两个消费方，共享同一套解包/定位/钉版语义：

| 消费方                     | 入口                          | 特征                                      |
| -------------------------- | ----------------------------- | ----------------------------------------- |
| 在线单篇（产品管线）       | `arxiv.org` / `export` 端点   | 限速、HEAD 预检、缓存、降级链             |
| 批量建库（benchmark 语料） | IA / HF tar、HF parquet       | **零 arxiv.org 请求**，成员级 sha256 钉版 |
| 批量预译（M4 远期）        | S3 requester-pays / OAI / RSS | 同 region 就地处理，只回传派生数据        |

## 1. 在线层：端点与请求纪律

### 1.1 端点表

| 用途        | URL                                              | 备注                                                        |
| ----------- | ------------------------------------------------ | ----------------------------------------------------------- |
| 源码包      | `arxiv.org/src/{id}[vN]`（`/e-print/` 301 到此） | tar.gz / 单文件 .gz / PDF 直投三态                          |
| HTML 版     | `arxiv.org/html/{id}[vN]`                        | 探 `{id}`（最新版）——实测存在 v1 404 而 v2 200 的边缘案；G1 起兼作取页臂（GET 经 `Fetcher.get_path` 跨镜像，与 e-print 同限流域/退避）     |
| abs 页      | `arxiv.org/abs/{id}[vN]`                         | license 链接、替代版本（备用元数据源）                      |
| PDF         | `arxiv.org/pdf/{id}[vN]`                         | PDF sidecar 输入                                            |
| Atom 元数据 | `export.arxiv.org/api/query?id_list={id},…`      | 批量 id_list 一次拉多篇                                     |
| OAI-PMH     | `oaipmh.arxiv.org/oai?verb=…`                    | 已迁出 export；独立第三限流桶                               |
| 镜像下载桶  | `export.arxiv.org/{src,pdf,abs}/…`               | 全站镜像、行为一致——下载面容量 ×2 且互为故障转移            |
| RSS         | `arxiv.org/rss/{cat}`（302→export）              | ~260 篇/日，含 license+announce_type+guid；每日预译种子首选 |

### 1.2 请求纪律（硬约束）

- **UA**：`texlate/{version} (+{repo_url}; mailto:{contact})`——官方要求机器人自报家门。
- **限速**：每 host 桶 **≥3.05s 全局间隔，零并发**。吞吐靠批量接口（id_list / OAI / 批量渠道），不靠并行打站。
- **HEAD 预检**：GET 之前先 `HEAD /src/{id}`——`content-disposition` 文件名直接给出 **resolved_version + 打包格式**（`arXiv-2203.02155v1.tar.gz` / 单文件 `arXiv-{id}vN.gz` / `arXiv-{id}vN.pdf`+`content-type: application/pdf`），`content-length` 做上限检查（拒 >150MB），`etag` 做缓存重验证。**一次 HEAD = hasSrc + 版本 + 三态格式预检**。
- **重验证**：`If-None-Match` / `If-Modified-Since` → 304 成立已实测；etag 有 `sha256:…` 与 GCS 短串两形态，按不透明串处理。

### 1.3 退避与 park（实测校准）

| 场景                      | 动作                                                                                                                |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| 单请求 429 / 5xx          | 重试 3 次：+10s → +30s → +90s（±20% jitter）；`Retry-After` 有则从其值                                              |
| 单请求 404                | 不重试，记 `not_found`                                                                                              |
| **同 host 连续 2 次 429** | **断路器**：该 host **按路径**队列 park 30min（勘误见表下）                                                         |
| park 后首请求仍 429       | park 翻倍，上限 2h；全程 checkpoint 落盘可恢复                                                                      |
| **~150 发/日后 406**      | 按 IP 累计配额惩罚：`/src/` 开始回 406、1–3min 自愈但密度渐升至近 100% → **直采日预算 ≈150–200 发**，超出走批量渠道 |

> 勘误 2026-09-15：park 时长原文 15min，与本文自身「惩罚窗口 >30min」的实测证据矛盾，实现取 1800s；限流实测按路径不按 host；429 响应无 Retry-After。
> 勘误 2026-09-17：strike 计数实为 **429 与 406 皆计**（ratelimit.py「同 (host,path-class) 连续 N 次 429/406」）——406 本就是本表下行的 IP 配额惩罚信号，计入合理；表行「连续 2 次 429」应读作「429/406 ×2」。

含义：元数据队列与下载队列独立调度；export 持续 429 只 park 元数据队列，下载照常。

### 1.4 版本语义

- `{id}` = 最新版；`{id}v{N}` = 钉版。缓存键**永远用 resolved version**（裸 id 请求从 HEAD 文件名解析出 `vN`）。
- `meta.json` 同时存 `requested_id`（含用户 v 钉）与 `resolved_version`；Atom `resolved_version` > 缓存值 → 标 stale 提示新版。
- 用户钉 `vN` 但版本不存在 → 404，向用户报版本清单（abs 页 / OAI arXivRaw 版本史可得）。

## 2. 解包规格

### 2.1 三态判别（魔数优先，扩展名/响应头只作提示）

```
bytes[0:2] == 1f 8b          → gzip 封装
  └ gunzip → offset 257 起 "ustar"（或 tar -tf 干跑成功）→ tar 多文件（主流 ~67–86%）
             否则                                        → 单文件 .tex 本体（~7–32%）
bytes[0:4] == "%PDF"         → PDF 直投（无源码 → sidecar）
其他                          → 遗留格式告警（实测 0/190 已绝迹，95% 上界 <1.6%）
```

- **先 `gunzip -c` → 嗅 ustar → 再分流**；禁止依赖 bsdtar auto-magic（gz 压缩的非 tar 文件会报 Unrecognized）。
- tar 探测用只读列举先列后解，同时产出 `files.txt`。
- 比例随年代漂移：IA 9802 tar 67%/gz 32%/pdf 0.2% → 2001 tar 76%/gz 15%/pdf 8.4% → TIGER 2408 tar 86%/gz 7%/pdf 6.7%。
- **第四态 pdf_wrapper stub**：源码存在但正文是 `\includepdf`/`\pdfpages` 壳（1412.6980 实测）——hasSrc 之外须加正文含量检测（stub 判据：section==0 ∧ 文本 <2KB），检出后走降级链。

### 2.2 路径安全（逐成员，缺一不可）

- 拒绝：`..`、绝对路径（`/` 前缀或 `C:` 盘符）、包外 symlink/hardlink、device/fifo/socket、setuid（勘误 2026-09-17：impl 判 `mode & 0o6000`——setuid+setgid 并拒，告警 `reject_setuid`）；另加字符级拒绝——控制字符 `[\x00-\x1f\x7f]` 与 UTF-16 代理区 `[\ud800-\udfff]`（非 UTF-8 原名经 str 层浮出，告警文本经 `backslashreplace` 转义防 meta.json 编码炸），成员名 `reject_path`、linkname `reject_link` 同查；linkname **先按原始形查**绝对路径/盘符再归一化（只查 `_link_rel` 解析结果会漏真实逃逸），归一后 `..` 出根亦 `reject_link`。
- 规范化：`./` 前缀剥离、空段折叠；同名重复成员 **last-wins**（`dup_member_overwrite` 后到者覆盖，勘误 2026-09-17：非「去重」）；**大小写折叠冲突检测**——file/link 冲突改 `~cN` 后缀名 + `casefold_rename` 告警（LaTeX 引用按原名），dir 成员冲突不可改名只 `casefold_dir` 告警跳过（大小写不敏感 FS 上目录会静默合并、子成员路径固定无法 rename）。
- 目录/文件冲突双向拒（`reject_dir_clash`）：落点是既有目录（file-over-dir）、父路径段是文件（file-under-file）、dir 成员迟到而同名 file/symlink 已落盘——先到者保、后到者告警跳过。
- IO 降级与硬拒：落盘 `OSError ∈ {ENAMETOOLONG, ELOOP, EEXIST, ENOTDIR}` 按成员级 `reject_io:{errno}` 告警跳过，不流产整包；**成员流中坏头整包拒**——tarfile `getmembers` 遇坏头静默停枚举，offset 后 512B 非全零即 `UnpackError("corrupt member stream")`（其后成员全丢、mtree 不能谎报完整；全零尾巴属真实包形态，9702009 实证）。
- 上限：解压总量 ≤512MB、成员 ≤20k（超限整包 `UnpackError("too_many_members")`）、单文件 ≤100MB（`reject_filesize`/`reject_totalcap` 成员级告警）。
- 落盘：`raw.{tar.gz|gz|pdf|bin}` 单文件（原始 blob 字节原样保存，可重放——勘误 2026-09-17：非 `raw/` 目录，staging 落成单 blob）+ `extracted/`（过滤后树）。
- **mtree**：每包一份 `mtree.txt`（TSV `path\tsize\tsha256\tkind[\t-> target][\tstub]`，kind ∈ file/dir/symlink/hardlink，symlink/hardlink 记 `-> target`，stub 成员尾挂 `stub` 标记——勘误 2026-09-17：原规格只记 path+size+sha256 三列）——缓存完整性校验、跨版本 diff、引用排序去重依据。
- 链接语义：包内 symlink 保留落盘 + `link_kept` 告警（安全已查，引用关系对编译语义要紧）；hardlink 目标可能靠后出现 → 延迟二遍物化（`_finish_links`：目标在树 → `hardlink_materialized` 复制实体计入 mtree；缺席/是 symlink → `hardlink_dangling` 告警不落盘）；后到同名非链接成员压掉未物化的 hardlink 声明，与 last-wins 成员序一致。
- **别名落点对账**（勘误 2026-09-17）：经 kept symlink 祖先写穿的成员与先到路径共享同一物理落点——后到写穿先到（last-wins），但 mtree 按字面成员路径记账会把先到条目的内容字段留成声明时旧值；解包收尾 `_reconcile_aliases` 以各落点最末成员为赢家，把 size/sha256（涉 symlink 时含 kind/link_target）回填先到条目，字段实际变化者记 `dup_member_overwrite`（与字面重名同语义），记录本就一致的别名不告警。
- stub 过滤：`member_bytes < 100B` 或解压后 `%auto-ignore` 前缀 → 标 `stub` 不进抽样（实测 42B 占位混入案例）。

### 2.3 主文件定位算法

```
candidates = { f ∈ *.{tex,latex,ltx,TEX,…}（扩展名大小写不敏感） | strip_comments(f) 含 \documentclass 或 \documentstyle }
# 勘误 2026-09-15：候选扩展名原文仅 *.tex；corpus_v2 实证 article.latex（nucl-ex/0203009
# 唯一主文件）、corpus_v3 命中 .TEX×2——匹配须大小写不敏感且覆盖 .latex/.ltx。
```

1. **先剥注释再匹配**（`\documentclass` 选项可被注释穿插；注释剥离须 `\%` 转义与 verbatim 感知）。
2. 唯一候选 → 主文件。
3. 多候选裁决序：a. 含 `\begin{document}` 优先 → b. include 图的**根**优先 → c. 文件名先验 `main|paper|ms|root|manuscript|thesis|{id}`、顶层目录优先 → d. 仍 ≥2 个独立根 → 标 `multi_doc: true`，按 include-degree 最大者选定，report 记录全部候选。
4. 零候选 → 非 LaTeX（plain TeX `\bye` / ConTeXt `\starttext`）→ 进降级链，不硬猜。

### 2.4 `\input` 拓扑

- 识别：`\input` `\include` `\InputIfFileExists` `\subfile` `\import{dir}{file}` `\subimport` `\includestandalone` `\CatchFileBetweenTags` + **裸文件名形 `\input file`**（1502.01589 实测 20+ 处）。
- 路径解析：**CWD（编译主目录）→ 项目根 → including 文件目录**（勘误 2026-09-15：原文写「including 目录→项目根」，corpus39 实测序以此为准；including-dir 回退覆盖 import 族语义）；扩展名补全 `.tex` → `.sty` → 裸名。（勘误 2026-09-17：此序是 **locate 建图层**实装（`_bases`），**gullet 展开层**用另一套——including 目录 → 项目根 → top_dir → basename 补 `.tex` → 裸名，五级，语义权威以 gullet 为准；两阶段同一 `\input` 可解析到不同文件，详见 docs/07 §7。）
- `\bibliography{x}` → **`\jobname.bbl`**（主文件词干；勘误 2026-09-15：原文写 `x.bbl`，1502.01589 实证 24 个 .bib 全缺而 bbl 在——TeX 语义按 jobname；勘误 2026-09-17：impl `_resolve_bib` 另按 arg-stem 双探 `x.bbl`→`x.bib`——超集宽松面，真 TeX 不读 arg-stem）。48.1% 语料自带 .bbl 直消费；仅 5.8% 需现场 bibtex。
- 环检测：绝对路径 `_seen` 集断环记 warning（防环优先于重复展开语义——留档偏差）。

## 3. 元数据层

### 3.1 拉取

- Atom `id_list` 批量：≤200 篇/次、URL ≤8KB 分批；独立队列调度支持 park/resume。
- 批量发现走 OAI-PMH `oaipmh.arxiv.org/oai`：`ListRecords` + `resumptionToken` 翻页；`metadataPrefix ∈ {oai_dc, arXiv, arXivOld, arXivRaw}`；**`<license>` 只在 OAI 系**（机读许可唯一来源），arXivRaw 独占版本史；183 set；错误以 200+body 返回。全库回填 ~2000 页 ≈ 2h@3s。

> 勘误 2026-09-17：本节批量能力**无实现对应物**——`arxiv/meta.py` 实装仅单篇路径：Atom `id_list={id}`（`_atom_meta`，钉版透传 `id vN`）+ OAI `GetRecord` 兜底（`_oai_meta`）；`ListRecords`/`resumptionToken` 翻页属语料管线/远期设计。
- DOI/版本史反查备用：DataCite `api.datacite.org/dois/10.48550/arxiv.{id}` 免 key 全量覆盖，`dates[]` 送 v1–vN。

### 3.2 Atom → meta schema

```json
{
    "arxiv_id": "1412.6980",
    "resolved_version": 5,
    "title": "...",
    "authors": ["..."],
    "abstract": "...",
    "primary_category": "cs.LG",
    "categories": ["cs.LG", "stat.ML"],
    "published": "...",
    "updated": "...",
    "doi": "...",
    "journal_ref": "...",
    "comment": "15 pages",
    "license": "...",
    "links": { "abs": "...", "pdf": "..." }
}
```

消费点：`primary_category` → 术语包映射（primary 优先、多类并集）；`comment` → chunk/token 预算先验；`authors` → 不可翻名单（配合 `\author` 块保护）。

## 4. 缓存设计

### 4.1 两层键

```
source_tier  = arxiv_id @ resolved_version                       # 跨请求/跨语言共享
product_tier = sha256(id | resolved_version | model |
                      pipeline_version | target_lang | glossary_hash)
```

- source tier 产物：`raw.*`、`extracted/`、`files.txt`、`mtree.txt`、`meta.json`、`etag`。
- product tier 产物：`zh.pdf`、`chunks.jsonl`（断点续翻载体）、`glossary.json`、`report.json`、`compile.log`（勘误 2026-09-17：产物命名与 docs/08 §1.4/§1.6 不一致——规格面是 `term_dict.json` 与中间产物五表 `chunks_map/placeholders_map/glossary/state/errors_report`，以 docs/08 为准）。
- 失效语义：`pipeline_version` 只失效 product 层（升级解析器不重下源码）；`model`/`glossary_hash` 仅重翻。（勘误 2026-09-17：实现键实为 **7 组分**——share.py `KEY_PART_FIELDS` 多含 `prompt_ver`（prompt 模板版本），上方公式漏列。）

### 4.2 状态机（report.json）

```
pending → downloading → unpacking → locating → parsing → translating
        → validating → compiling → done
失败终态: no_source | pdf_only | stub | parse_failed | translate_failed
        | compile_failed | degraded_html | degraded_pdf
```

`degraded_*` 仍产出译文，状态位供产品层给降级提示。

> 勘误 2026-09-17：本状态机是**目标设计，无逐字实现对应物**。`server/store.py` 实装为另一套 11 态机（任务粒度、含 cancelled/failed 终态）；`e2e.py` 的 `report["status"]` 走 clean/partial 裁决词表；`arxiv/meta.py` DegradeReason/DegradeTier 仅碎片对应。对接实现时以 store.py 为准。

## 5. 降级链

```
L1  e-print 源码 ──解析/编译失败──→ L2  arXiv HTML 最新版（LaTeXML ltx_* DOM，
       │                             覆盖集 ≡ 源码集——救"我们解析器崩了"）
       └── %PDF/404/stub → L3  PDF sidecar（~13% 唯一通路）
```

- L2 探测顺序：`HEAD /html/{id}`（最新版）→ 逐版本回退；stub 检测同 §2.1。
- L2 是**异构降级**：DOM 节点级分块（`p.ltx_p` 可译叶、`<math>` 整子树占位、`data-chunk` 锚），不复用 LaTeX scanner。
- 三层叠加覆盖 ≈100%；L1 单层 86.7%（CI 76–92%，~250 合并样本；旧式 id 源码率 98.1%、新式 94.8%）。

> 落地勘误（2026-09-17，G1 arxiv-html-first）：L2 臂已实装 `arxiv/html.py`。**获取**：`fetch_html(id, version, fetcher)` 走 `Fetcher.get_path`——同 hosts 序跨镜像故障转移、`_request` 退避重试（429/406/5xx + TransportError）、pacing/断路器/日预算与 e-print 共域；Parked/Budget 原样上抛。错误分类：`HtmlNotAvailableError`（404 或 200 stub——响应无 `ltx_document`，撤稿/「HTML not available」/abs 回落页同形，`status` 保留线缆码 + `detail` 记判据）vs `HtmlFetchError`（退避后仍非 200/404）；取页直 GET `{id}[vN]`（钉版透传用户 v 钉），不做逐版本回退（回退探测属 `degrade()` HEAD 臂）。**块模型**（`parse_arxiv_html` → `HtmlDoc`）：`div.ltx_para`/`p.ltx_p`→para、`h1–h6.ltx_title*`→title（`ltx_tag` 编号剥离、`ltx_title_*` 后缀映射 latex 风 context）、`figcaption.ltx_caption`→caption、`ltx_note`→footnote（迟发紧跟宿主块）、`ltx_bibitem`/`ltx_figure`/`ltx_table`/`ltx_float`/`ltx_listing`/`ltx_authors`/`ltx_dates`/equation→support 块（只占位保序不译——对齐 `\bibitem`/`\author` 保护族；support 祖先内只挖 caption/title）。**行内 token 族 `[[TYPE_n]]`**：MATH（`<math>`+`ltx_equation*`）、CITE（`ltx_cite`）、REF（`a[href^="#"]`）、NOTE（`ltx_note`）、GRAPHICS（媒体/`ltx_graphics`/`ltx_transformed_outer`）、CMD（`ltx_ERROR`）、TABLE（`ltx_tabular`）、URL（`ltx_url`——外链锚文本照译，同 `\href` 文本臂口径）；ph 值 = 元素 outer HTML（MathML/`alttext` 内嵌——无需重渲染即无损回插，`reinsert` 单趟 `sub` 不级联）。**出口**：`doc_chunks` 按 `TRANSLATE_CTX` 白名单（para/item/section 系/title/abstract/caption/keywords/footnote）+ `normalize_kind` 产 `ChunkIn`（`ph_fragments` 携块内 token→片段，武装 `recover_copied_tokens` 修复臂）；`marked_html` 同源枚举给每个块元素注 `data-chunk=block.key`（元素 `id` 优先、缺失合成 `b{n}`、撞号加 `#k`）——与 chunks 行 `chunk_id`、前端 DomPane 几何锚严格 1:1。无 `article.ltx_document` → `HtmlNotAvailableError`（parse 单用与 fetch 同型判据）。

## 6. 批量渠道（benchmark 取数正源）

**硬约束：语料构建不请求 arxiv.org 任何端点**——可复现、无限流、可断点续跑。

### 6.1 渠道裁决表

| 渠道                                        | 覆盖                                             | 保真                                                                                            | 成本/速率                          | 角色                                        |
| ------------------------------------------- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------- |
| IA `arxiv-bulk` 月度 tar                    | 1991-07→2020-10，352 月无缺（3,242 item/1.66TB） | 字节级（Range 单成员抽取逐字节核验）                                                            | 免费，实测 10.7–16.2MB/s           | **≤2020 主力**（~24 簇）                    |
| HF `TIGER-Lab/arxiv-latex-5T`               | 1991-07→2025-01，403 月零缺口（9,547 tar）       | **字节级已实证**：对拍 IA `2008_001`，123/165 成员 sha256 全同，42 差异全是上游 v2+ 修订        | 免费但 HF CDN 仅 ~3.7MB/s          | **post-2020 主力**（~6 簇）+ IA 缺月备份    |
| HF `scholarweave/arxiv-latex`               | →2026-08（46 shards，duckdb 谓词下推可用）       | **.tex 逐字保真（845/845）但结构有损**：丢 73% 文件（图/.bst）、7.1% 论文 U+FFFD、pdf_only=NULL | 远程列裁剪，140 id/6.3GB shard 35s | 文本层规模实验源；**不进正式语料**          |
| HF `librarian-bots/arxiv-metadata-snapshot` | 全量元数据（CC0 日更）                           | —                                                                                               | 免费、远程列裁剪                   | **分层 frame**（年月/类目/license 键）      |
| AWS `s3://arxiv`                            | 全量（us-east-1，requester-pays）                | 字节级                                                                                          | $0.09/GB egress；同 region EC2 免  | 不用（M4 预译层才考虑；hjfy $174/2TB 锚点） |
| GCP `gs://arxiv-dataset`                    | PDF+OAI 元数据 + 官方引用图                      | —                                                                                               | 匿名免 key                         | 冷备（无 LaTeX src）                        |

### 6.2 成员级语义（实测定案）

- 成员名 = `{YYMM}/{id}.gz|pdf`（旧式 archive 连写如 `astro-ph9802001`）；**名中无版本号** → blob ≈ tar 构建时点 e-print 状态，非钉版 v1。**manifest 以 `(channel, item, member, blob_sha256)` 四元组为唯一事实源**，`resolved_version=null`。
- **月块只收当月新提交**：跨 3 月块 2,763 成员实测 id-yymm 全等于 chunk 月、跨月 id 重叠 = 0 → 去重键 = id。
- 同 id 跨渠道可不同字节（快照时点不同 + 上游修订）→ `channel` 字段必填，不跨渠道去重。
- **zipsum.tsv 捷径**：`{item}_zipsum.tsv` 成员序 == tar 序（2,549 成员 0 失配）→ 成员 data offset 纯算术重建（`512·(i+2) + Σ ceil(size_j/512)·512`），免下 tar 得全月成员索引（名字/大小/格式/sha256）。晚期 item 不规律缺失 → 退化整 chunk 流式扫描或 Range 头扫描（46 请求重建 311MB tar 索引已验证）。
- 簇粒度 = 月内 chunk tar：IA 130–543MB/214–1,668 成员；TIGER ~0.53GB/≈150 篇（2024 每块）。单成员均值 ~3.7MB。
- 吞吐实测：IA bulk ~11MB/s；特征提取 ~214 成员/s（单遍流式：魔数三态+gunzip+ 内层 tar+docclass+`\input` 深度+flags）；Range 延迟 ~1.6s/req。
- `curl` 必须 `-L`（IA `/download/` 302 到 `dn*` 节点）。

### 6.3 引用排序（预译种子集，M4）

对 `extracted/` 语料单遍扫描 `.bbl+.bib+.tex`（46.2% 语料 bib/bbl 皆无、内嵌 thebibliography 在 .tex——必须三面全扫）抽「引用→arXiv id」边：

- 七模式：`arXiv[: ]id`、旧式 `arXiv:hep-ph/9712271`、bib `eprint` 字段（**必须形状校验**——常装 DOI URL）、`journal={arXiv preprint…}`、URL 形态（`arxiv.org/(abs|pdf|e-print)/`、`doi.org/10.48550/arXiv.`）、`\cite{id}` 键即 id、`\eprint/\arxiv` 宏。
- id 归一：新式 `\d{4}\.\d{4,5}` + 月份合法校验；旧式 archive 白名单 + `math.AG/`→`math/` 归并 + 大小写归一；版本后缀剥离→paper 级计数。
- 去重：`(citing_id, cited_id)` 集合语义；作者交集标 `self_cite`。
- 产物：`edges.jsonl` → `counts.json` → `rank.txt`。校准锚（hjfy 47 万篇 2023+ 语料）：`1412.6980`=29,512、top-10k≈64、top-100k≈个位数。
- 已知偏差：语料边界近因偏差；正式发表遮蔽（OpenAlex 对拍 Adam：84,617 vs 语料内 29,512，低估 ~3×）；PDF 直投引用者漏计。方向均为低估，相对序仍稳。

## 7. 开放项（已知未验证，不阻塞）

- S3 manifest 边界完整性（需 AWS 凭据；M4 前不阻塞）。
- export 429 窗口精确长度（只确认 >30min 下界；park 策略已按保守值）。
- Atom `<arxiv:doi>` 原文验证（有 DataCite 替代，优先级低）。
