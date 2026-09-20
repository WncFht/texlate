# arXiv 开放数据集与批量访问渠道普查

> **结论**：渠道格局已定——元数据回填首选 `librarian-bots/arxiv-metadata-snapshot`（CC0、免 key、当日更新）；引用校准主力 OpenAlex `works/doi:10.48550/arXiv.{id}`（免 key 日更，注意 stub works 与 cited_by_count 分裂两坑）；版本史走 DataCite `dates[]`（免 key 全库）；批量 PDF 冷备用 `gs://arxiv-dataset`（匿名可读但冻于 ~2025-08、无 src）；LaTeX src 批量的唯一正规渠道是 `s3://arxiv` requester-pays tar（匿名 403 实证），免费替代是 IA arxiv-bulk（→2020-10）+ TIGER-5T（→2025-01）+ scholarweave（→2026-07 有损）。
> **状态**：时点证据（2026-09-14 口径）。渠道角色分工已按本普查 + `post2020-sourcing.md` 裁决落地。
> **日期**：2026-09-14

约束说明：本轮未触 `*.arxiv.org`（另一 agent 负责），arXiv 官方信息来自第三方文档与实测。

## 0. 渠道矩阵

| 渠道 | 内容 | 全文？ | 引用？ | 版本史？ | 认证/成本 | 新鲜度 | 实测状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Kaggle `Cornell-University/arxiv` | OAI 元数据 JSONL（~2.4M+） | 摘要 | 无 | `versions[]`+`update_date` | Kaggle key，免费 | 周更 | 未实测（页面 JS 渲染），资料一致 |
| **GCP `gs://arxiv-dataset`** | **逐文件 PDF** + OAI 元数据 + **arXiv 内部引用图** | PDF（无 LaTeX src） | `internal-citations.json`（冻于 2020-08） | 文件名带 `vN` | **实测匿名可读，无需 GCP 账号** | **PDF 到 ~2025-08**；metadata 冻于 2020-08 | ✅ 列目录/Range GET 均通 |
| AWS `s3://arxiv` | PDF+LaTeX src 打 tar 包（官方正源） | **PDF + src** | 无 | manifest 含版本 | **requester-pays**，需 AWS 账号付请求 + 流量费 | 官方持续更新 | ✅ 匿名 403 确认 requester-pays |
| HuggingFace | 社区镜像：LaTeX 全文 parquet、元数据快照、embedding、引用对 | 视数据集 | `cometadata/crossref-arxiv-citations` | 少数 | 匿名可下（部分 gated） | 多个数据集本月仍在更新 | ✅ API 通 |
| Semantic Scholar Graph API | 元数据+citationCount+TLDR+openAccessPdf | 链接非全文 | citationCount/influential | 无 | 无 key 共享池≈100req/5min **实测持续 429**；免费 key ~1rps | 实时 | ✅ 验证（429 本身即结果） |
| S2 Datasets API（S2ORC 等） | papers/abstracts/citations/s2orc/s2orc_v2/tldrs/embeddings 全量快照 | **s2orc = 解析后全文**（含 LaTeX 源解析） | 全量引用图 | 无 | **下载链接必须 API key**（免费申请） | release `2026-09-09` | ✅ release 列表无 key 可查，下载 401 |
| **OpenAlex** | 全量 works：cited_by_count、counts_by_year、OA 位置、license/version | 链接非全文 | **cited_by_count + cited_by_api_url** | `version` 字段 | **完全免费无需 key**，mailto 进礼貌池 ~10rps | 日更（样本 updated 2026-09-12） | ✅ 多条实测 |
| DataCite `10.48550/arXiv.*` | 每篇 arXiv 论文的 DOI 元数据 | 无 | 无 | **`dates[]` 全版本时间线**（最大亮点） | 免费无需 key | 实时（v9 都全） | ✅ HEAD→302 到 abs；API 返回全字段 |
| unpaywall | OA 状态/合法 PDF 链接 | 链接 | 无 | 无 | 免费，email 参数 | — | ✅ 但 **arXiv DataCite DOI 未收录（404）**，只认 Crossref DOI |
| CORE | 聚合各仓库全文 | 有 | 无 | — | 免费 key，~10rps | — | 未实测（需 key），资料记录 |
| OpenReview | 会议投稿/评审 | 有（pdf 字段） | 无 | 有 revisions | api2 匿名可查 | 实时 | ✅ `notes/search` 200 |
| Internet Archive `collection:arxiv` | 每篇一个 item：PDF+meta xml | PDF | 无 | 无 | 免费匿名 | **冻于 ~2017-04**（1,076,003 items） | ✅ |

## 1. Kaggle `Cornell-University/arxiv`

- 内容：`arxiv-metadata-oai-snapshot.json`，JSONL 每行一篇，源自 arXiv OAI-PMH。
- 字段：`id, submitter, authors, authors_parsed, title, abstract, comments, journal-ref, doi, report-no, categories(空格分隔串), license(URL), versions[{version,created}], update_date`。
- 更新：约每周自动刷新，有几百个历史版本。规模 ~2.4M+ 篇。
- 成本：免费但需 Kaggle 账号 + API key。
- 意义：**元数据回填首选之一**——字段最贴 arXiv 原生（含 license、versions、journal-ref），无需碰 arxiv.org。等价替代品：HF `librarian-bots/arxiv-metadata-snapshot`（§4）当日更新、免 key——本语料实际采用了后者建 frame（见 `frame-and-allocation.md`）。

## 2. GCP `gs://arxiv-dataset` —— 本轮最大发现

文档常把它说成 requester-pays，**实测（2026-09-14）匿名可列目录、可 GET/Range 下载，无需 GCP 账号**。`storage.buckets.get` 仍 401，但 `objects.list` 与对象读取对 allUsers 开放。

- 顶层前缀：`arxiv/`、`metadata-v5/`、`test/`（4 字节占位）。
- `arxiv/pdf/YYMM/{id}v{N}.pdf`：新版编号论文逐文件 PDF，**实测存在至 `2508/`（2025-08），`2509/` 起为空**；对象 `updated` 时间统一为 2025-08-24——桶在 2025 年 8 月做过一次全量再同步，之后停更。即：**冻结于 ~2025-08 的全语料逐文件 PDF，免费匿名**。
- `arxiv/{archive}/pdf|ps|html/`：旧式编号（hep-th/9901001 等）按 archive 分树；`html/` 是作者当年自提交的 HTML（非 ar5iv）。
- **没有 LaTeX src**——全桶确认无 `src/` 子树。
- `metadata-v5/` 三个文件（均 2020-08-19 上传，冻结）：`arxiv-metadata-oai.json` 4.5GB JSONL（注意与 Kaggle 版字段差异：`categories` 是数组、`versions` 是字符串数组）；`authors-parsed.json` 220MB；**`internal-citations.json` 172MB，格式 `{arxiv_id: [被引arxiv_id,...]}`——白送的 arXiv→arXiv 引用图**（冻于 2020-08）。
- 用法：`GET https://storage.googleapis.com/storage/v1/b/arxiv-dataset/o?prefix=...` 列目录；`GET https://storage.googleapis.com/arxiv-dataset/<key>` 下载（Range 支持 206）。
- 意义：**批量 PDF 语料 + 引用图冷备首选**；缺点是停更、无 src。

## 3. AWS `s3://arxiv`（官方正源）

- `registry.opendata.aws/arxiv/`：bucket `arxiv`，us-east-1，**requester-pays**——实测匿名 list/HEAD 均 403「Anonymous users cannot invoke requests against Requester Pays buckets」，必须 AWS 凭证 + `--request-payer requester`，请求方付请求费 + 流量费（us-east-1 内 compute 免传输费）。
- 结构：`pdf/arXiv_pdf_manifest.xml` + `pdf/arXiv_pdf_YYMM_NNN.tar`（按月 ~500MB 分块）；`src/arXiv_src_manifest.xml` + `src/arXiv_src_YYMM_NNN.tar`（**LaTeX/e-print 源文件，唯一能批量拿 src 的官方渠道**）。manifest 内含逐文件条目+md5。
- 注意区分 `s3://arxiv-dataset`（AWS 教程用桶，非官方正源）。
- 意义：**LaTeX 源批量获取的唯一正规渠道**（OAI/e-print 逐个拉之外）。成本全在请求方；做全语料镜像要预算，做百篇级语料很便宜。

## 4. HuggingFace datasets（按价值挑 8 个）

| 数据集 | 内容 | 规模/格式 | 更新 | license |
| --- | --- | --- | --- | --- |
| `scholarweave/arxiv-latex` | **LaTeX 源全文 parquet**（46 shards，带 manifest xml） | 1M<n<10M | 2026-08 | other |
| `librarian-bots/arxiv-metadata-snapshot` | **Kaggle 元数据的滚动 parquet 快照**（10 shards） | 1M<n<10M | **当日更新（2026-09-14）** | CC0 |
| `cometadata/crossref-arxiv-citations` | Crossref 挖掘的 **arXiv 引用对**（asserted+mined 两份 parquet） | 1M<n<10M | 2026-09 | CC0 |
| `ccdv/arxiv-summarization` | article/abstract 对（203k 篇） | 100K<n<1M parquet | 停更 2024-08 | — |
| `armanc/scientific_papers` | arXiv+PubMed 分节全文（经典 summarization 集） | 100K<n<1M | 停更 | unknown |
| `taesiri/ArXivSignals` | 按日分区的新论文 + 信号监控 | 按 `date=` 分区 parquet | 2026-09 活跃 | CC-BY-4.0 |
| `bluuebunny/arxiv_abstract_embedding_*` | 摘要 embedding（mxbai，含 milvus binary 版） | 全语料摘要 | 2026-09 活跃 | — |
| `yufan/arxiv-metadata-2020-2026` | 按领域/年切分 metadata.jsonl | 100K<n<1M | 2026-09 | ODC-BY |

- 补充：`togethercomputer/RedPajama-Data-1T` 只放 `urls/arxiv.txt` 下载清单 + 脚本（数据本体在 arXiv S3）；The Pile 的 arXiv 分量是 LaTeX 清洗全文。
- 意义：**免 key 拿「活的」元数据快照用 `librarian-bots/arxiv-metadata-snapshot`；LaTeX 全文用 `scholarweave/arxiv-latex`；引用对用 `cometadata/crossref-arxiv-citations`**——三件正好对上三个需求。HF LaTeX 源数据集细分横评见 `hf-latex-datasets.md`。

## 5. Semantic Scholar

- Graph API：无 key 走共享匿名池（文档 ~100 req/5min 全体匿名用户抢），**实测两次（间隔 20s）均 429**——无 key 档基本不可用；免费 key（表单申请，数天批）~1 rps。端点 `GET /graph/v1/paper/arXiv:{id}?fields=citationCount,influentialCitationCount,externalIds,openAccessPdf,tldr,...`，支持 `/paper/batch` POST 批量。
- Datasets API：`GET /datasets/v1/release/latest` **无 key 可查**——release `2026-09-09`，数据集：`papers, abstracts, authors, citations, paper-ids, publication-venues, s2orc, s2orc_v2, tldrs, embeddings-specter_v1/v2`。**但 `/release/{id}/dataset/{name}` 拿下载 URL 必须 key（实测 401）**。
- S2ORC：~2 亿条元数据、千万级 GROBID/LaTeX 解析全文；`s2orc_v2` 是最新结构。申请 key 后免费用于研究。
- 意义：引用校准的备选源（influentialCitationCount 是独有字段）；S2ORC 是「不想自己解析」时的全文备选，但拿 key 有等待期。

## 6. OpenAlex —— 引用校准主力（重点实测）

- 免费、无 key；`mailto=` 参数进礼貌池（~10 rps、10 万/日）。
- arXiv 在 OpenAlex 是 source `S4306400194`：primary_location 计 **2,286,585 works**，任意 location 计 **3,719,529**。
- **逐篇查法（实测可靠）**：`GET https://api.openalex.org/works/doi:10.48550/arXiv.{id}`——新旧编号皆可（`arXiv.1412.6980`、`arXiv.hep-th/9901001` 都命中）。返回 `cited_by_count`、`counts_by_year[]`、`open_access`、`locations[]`（带 pdf_url/license/version）、`cited_by_api_url` 等。`select=` 可裁剪字段。
- **批量查法**：`filter=doi:a|b`（`|` = OR，`,` = AND）语法本身可用——**但对 arXiv DOI 有个坑：OpenAlex 的 arXiv-DOI 记录里有一批「stub works」，直接 GET 能拿到、filter/search 却不返回**（实测 `0704.0001`、`hep-th/9711200` 均如此；`1706.03762` 更彻底——直接 GET 也 404）。结论：**批量对拍时以逐篇 `works/doi:` GET 为准**，filter 路径只能当辅助。
- **第二坑（对校准最重要）：cited_by_count 在「有正式发表版」的老论文上分裂**——`hep-th/9711200`（Maldacena AdS/CFT）的 arXiv-DOI work 只有 18 次引用，真实引用记在期刊 DOI 的 work 上；而 `1412.6980`（Adam，ICLR 发表）的 arXiv work 却攒了 84,617。**校准建议：arXiv DOI work 的 cited_by_count 与元数据 `doi`/`journal-ref` 指向的发表版 work 各查一次取 max/求和**，否则老论文会系统性偏低。
- 深度分页用 `cursor=*`（`per-page=200`）；`group_by=` 可做统计；全量快照在 `s3://openalex`（requester-pays）。

## 7. DataCite DOI —— 版本史通道

- `HEAD https://doi.org/10.48550/arXiv.{id}` → 302 `arxiv.org/abs/{id}`；新旧编号通吃。prefix `10.48550` 在 api.datacite.org 计 **3,164,738** 条——覆盖全库。
- `GET https://api.datacite.org/dois/10.48550/arxiv.{id}` 返回：`creators/titles/publisher(arXiv)/publicationYear`、**`dates[]` 逐版本 Submitted/Updated 时间线（v1..v9 全在，等价 arXiv 版本史）**、`version` 当前版本号、`relatedIdentifiers`。
- 无 key、无显式限速文档。
- 意义：**不碰 arxiv.org 拿版本史/提交时间的唯一通道**；DOI 本身还是 OpenAlex 的查询键。

## 8. 次要渠道

- **unpaywall**：`api.unpaywall.org/v2/{doi}?email=` 免费；**arXiv DataCite DOI 未收录（404）**，只认出版方 Crossref DOI。仅在需要「发表版 OA 链接」时有用。
- **CORE API v3**：免费 key，~10rps，`/search/works` 返回 `downloadUrl`/`fullText`；CORE Dataset 提供定期全量 dump。定位为兜底聚合源。
- **OpenReview**：`api2.openreview.net/notes/search?term=` 匿名可用（实测 200）。非 arXiv 源，查 ICLR/NeurIPS 投稿 + 评审时用。
- **Internet Archive `collection:arxiv`**：1,076,003 items，每 item = PDF+`*_metadata.xml`（无 src）；**覆盖止于 ~2017-04**。只配做老论文 PDF 冷备。

## 9. 需求 → 渠道映射

| 需求 | 首选 | 备选 | 说明 |
| --- | --- | --- | --- |
| **元数据回填**（abstract/authors/categories/license/versions，不碰 arxiv.org） | `librarian-bots/arxiv-metadata-snapshot`（HF，CC0，当日更新，免 key） | Kaggle Cornell-University/arxiv（需 key）；GCS `metadata-v5`（冻 2020） | 字段最全的是 Kaggle/OAI 系；HF 版更新最勤 |
| **引用排序校准**（语料内抽取计数 vs 外部计数对拍） | **OpenAlex `works/doi:10.48550/arXiv.{id}`**（注意 stub/分裂两坑） | GCS `internal-citations.json`（arXiv↔arXiv，冻 2020-08）；HF `crossref-arxiv-citations`（CC0，新）；S2 citationCount（需 key） | OpenAlex 是唯一日更 + 免 key + 逐篇可查的；GCS 引用图免 API 直接全量 |
| **批量 PDF 语料** | `gs://arxiv-dataset` 匿名逐文件拉（至 2025-08） | IA（至 2017）；`s3://arxiv` tar（最新但付费） | 百篇级随便用；全量镜像选 S3 |
| **LaTeX src 批量** | `s3://arxiv` `src/` tar（requester-pays） | IA arxiv-bulk（→2020-10 免费）；TIGER-5T（→2025-01 免费镜像）；HF `scholarweave/arxiv-latex` parquet（→2026-07 有损文本层） | 免费三家已实测裁决，见 `post2020-sourcing.md` |
| **版本史** | **DataCite API `dates[]`**（免 key，全库） | Kaggle `versions[]` | 完全不依赖 arxiv.org |
| **全量冷备** | `gs://arxiv-dataset`（PDF+metadata+引用图，零成本镜像） | `s3://arxiv`（含 src，付费） | GCS 桶已停更，镜像后需 S3/e-print 补增量 |
| **发表版信息/OA 链接** | unpaywall（Crossref DOI）；OpenAlex `locations[]` | CORE | arXiv DOI 在 unpaywall 查不到，要走 journal-ref→Crossref |

## 10. 中国可达性与部署注意

- **arXiv 本体**：未被正式封锁，但 2023-24 迁到 Google Cloud 后国内直连时通时断、PDF 下载慢且易断流；**官方镜像网已关停——`xxx.itp.ac.cn`（中科院理论物理所镜像）与 `cn.arxiv.org` 均于 ~2021 年失效**，网上的旧镜像清单不可信。
- **GCP `storage.googleapis.com` 与 AWS S3 在国内均不可直连**（GCS 被墙；S3 视线路抖动）——`gs://arxiv-dataset` 的「匿名免费」红利只在境外服务器上成立。
- **huggingface.co 被墙**——境内需 `HF_ENDPOINT=https://hf-mirror.com`（社区镜像，文件下载走镜像 CDN；其 `/api` 308 回 hf.co，API 层不完全镜像）。
- **境内可直接用的替代入口**（给用户侧/降级路径参考）：Semantic Scholar（可下 PDF）、alphaXiv、Papers with Code、ChinaXiv（中科院自建预印本平台）、papers.cool；OpenAlex/DataCite/OpenReview 均境外但通常可达性优于 Google 系。
- **部署建议**：采集端（S3/GCS/HF/S2 抓取、TeX 编译）放境外 VPS；成品双语 PDF/页面走国内可访问的对象存储+CDN 分发；别把 arxiv.org/storage.googleapis.com 写进面向国内用户的前端链路，必要时用 Cloudflare Workers 反代做兜底。
