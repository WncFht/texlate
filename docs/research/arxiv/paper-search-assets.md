# paper-search 技能资产盘点 → TeXlate 复用评估

> 对象：`~/.agents/skills/paper-search/`（六源论文检索统一 CLI，PEP 723 自包含脚本）。
> 调研方式：全量代码通读 + 2026-09-14 轻量实测（未触碰任何 `*.arxiv.org`）。
> 结论先行：**元数据回填/引用校准可直接复用 OpenAlex 通道（key 已配）+ `enrich_citations` 的 DOI 批查模式；`_http_runtime`/`paper_schema`/`resolve_ids` 是值得照搬的零件；S2 无 key 匿名 429、DBLP 当前被反爬拦，都不可用。**

## 1. 凭证现状（`.env`，只报名不报值）

| key                                   | 状态     | 喂给哪个源                                                     |
| ------------------------------------- | -------- | -------------------------------------------------------------- |
| `OPENREVIEW_USER` / `OPENREVIEW_PASS` | 已配     | OpenReview API v1/v2 登录（匿名 403 ChallengeRequired）        |
| `OPENALEX_API_KEY`                    | 已配     | OpenAlex `Authorization: Bearer`（匿名池当前会被限流，见实测） |
| `SEMANTICSCHOLAR_API_KEY`             | **未配** | S2 `x-api-key`；匿名实测 429                                   |
| `PAPER_SEARCH_CONTACT_EMAIL`          | 未配     | Crossref/DBLP 礼貌 UA 的 mailto（可选）                        |

`_env.py`：从脚本目录向上找第一个 `.env`（到 repo root 止），`os.environ.setdefault` 注入，shell 已导出的值优先。模式可直接抄给我们的凭据加载。

## 2. Connector 矩阵

| 源                   | endpoint                                                                                       | auth                        | 引用数                             | 摘要                                | venue                                  | arXiv↔DOI 互转                                      | 限速/重试                                                                                  |
| -------------------- | ---------------------------------------------------------------------------------------------- | --------------------------- | ---------------------------------- | ----------------------------------- | -------------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| **arXiv**            | `export.arxiv.org/api/query`（Atom XML）+ `id_list` 批查（≤100/批）                            | 无                          | 无                                 | 有                                  | 恒 "arXiv"                             | Atom `id`→`arxiv_id`（剥 vN）；`arxiv:doi` 字段→doi | 跨进程 flock 强制 ≥4s 间隔（`ARXIV_MIN_INTERVAL`）；通用 429/5xx 重试                      |
| **OpenAlex**         | `api.openalex.org/works`，cursor 分页 200/页；`search`（词面）/`search.semantic`（≤50 不分页） | Bearer key（已配）          | `cited_by_count`                   | `abstract_inverted_index` 重建      | `primary_location.source.display_name` | doi 有；`arxiv_id` **不填**（恒 None）              | 页间 sleep 1s；语义模式上限 50                                                             |
| **Semantic Scholar** | `api.semanticscholar.org/graph/v1/paper/search`，offset 分页 ≤100                              | `x-api-key`（未配）         | `citationCount`                    | 有                                  | `venue`                                | `externalIds` 给 DOI + ArXiv **双向**               | 页间 sleep 1s；匿名 429 直接抛 `AnonymousRateLimitError` 中止该源                          |
| **Crossref**         | `api.crossref.org/works` + `/works/{doi}` 单查                                                 | 无（礼貌 UA）               | `is-referenced-by-count`           | `abstract`（HTML 标签剥离，常为空） | `container-title`                      | doi 主键；无 arXiv                                  | offset 分页 ≤100，页间 sleep 1s                                                            |
| **DBLP**             | `dblp.org/search/publ/api?format=json`，≤1000/页                                               | 无（礼貌 UA）               | 无                                 | 无（可选逐条 Crossref 富化）        | `venue`                                | `info.doi`                                          | `backoff_base=5.0`；**实测被反爬 HTML 挑战拦截**                                           |
| **OpenReview**       | `api2.openreview.net`（v2）/ `api.openreview.net`（v1）+ 本地 SQLite 缓存                      | `OPENREVIEW_USER/PASS` 登录 | 无 API 字段；缓存预填 S2 crosswalk | 有                                  | venueid→venue                          | note.id 是主键；缓存有 `arxiv_id` 列                | 跨进程 flock ≥0.5s（`OPENREVIEW_MIN_INTERVAL`）；v1 必须 offset 分页（`after` 游标丢数据） |

公共层 `_http_runtime.py`：connect 15s / read-idle 300s / 4 attempts；429/500/502/503/504 有界重试且服从 `Retry-After`；连接/超时异常指数退避（DBLP base 5s，默认 3s）；per-source 墙钟预算（默认 180s，OpenReview 600s）；`configure_external_session` 能把同策略挂到第三方 Session 上（openreview-py 用）。

## 3. 统一 schema 与 ID 规范化（复用价值最高的一层）

`paper_schema.py` 的 15 字段记录：`title/authors/year/abstract/url/venue/citation_count+citation_source/publication_date+date_precision/publication_status+status_source/source/doi/arxiv_id`。`normalize_paper` 校验 + `infer_arxiv_id` 从 doi/url 文本里反提 arXiv id（正则覆盖 `10.48550/arxiv.*`、`arxiv.org/abs|pdf/`、`arxiv:`、旧式 `cs/0601132`）。

`resolve_ids.py`：查询分类（arXiv id/裸 DOI/arXiv-DOI）→ 直查权威端点注入对应桶，绕关键词检索与年份过滤。**arXiv 批查走 `id_list`（≤100/批），DOI 走 Crossref `/works/{doi}` 逐条**。

`postprocess.py` 可搬零件：`norm_doi`（剥 `doi.org/doi:` 前缀）、`norm_arxiv`（剥 `arxiv:`/`vN`）、union-find 跨源去重（强键 DOI/arXiv，标题兜底但会被冲突元数据否决）。

`enrich.py`：缺 `citation_count` 的记录 → 取 doi 或拼 `10.48550/arxiv.<id>` → `filter=doi:a|b|c` 每 50 条一批查 OpenAlex 回填。**这正是我们 §9.3 校准想要的形状：纯 OpenAlex，不打 arxiv.org。**

## 4. 实测记录（2026-09-14）

| 测试                                    | 结果                                                                                                                                                                           |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| OpenAlex 关键词（带 key）               | 正常。Diffusion Policy：IJRR venue、cited_by 515、完整摘要、day 精度日期                                                                                                       |
| Crossref DOI 直查 `10.1038/nature14539` | 正常。LeCun Deep learning：is-referenced-by **76,281**、venue=Nature、摘要空                                                                                                   |
| S2 匿名                                 | **HTTP 429** → `AnonymousRateLimitError`，无 key 不可用                                                                                                                        |
| DBLP                                    | **被反爬**：200 但返回 `Making sure you're not a bot` HTML → JSONDecodeError。curl 直连同样拦                                                                                  |
| OpenAlex 匿名对照                       | `Anonymous search is temporarily rate-limited`（retryAfter 30s）——**key 实测有价值**                                                                                           |
| `enrich_citations` 对 arXiv id          | `1412.6980`→OpenAlex **84,617**（vs 语料内计数 29,512，校准方向正确）；`1706.03762` 的 `10.48550` DOI 在 OpenAlex **404**——DataCite DOI 覆盖不全，老文尤其缺                   |
| OpenReview 本地缓存                     | 97,248 行（accepted 57,834 / rejected 26,458 / withdrawn 12,820 / submitted 136）；`arxiv_id` 预填 15,032、`citation_count` 预填 17,983（nhop/S2 crosswalk，2025+ 届次未覆盖） |

## 5. 映射到 TeXlate 各层

### a) meta.json 回填（arxiv-layer §5：authors/title/abstract/primary_category）

- **主源仍是 arXiv Atom**（本技能的 arxiv connector 就是 Atom 客户端，但只有 title/authors/abstract/id/doi，**不取 `primary_category`、`journal_ref`、`updated`/版本号**——我们的 meta.json 需要这三个，照搬其 `_parse_arxiv_xml` 框架、补字段即可）。
- 备选/兜底：OpenAlex（abstract 倒排索引重建有 artifact 风险，venue=正式发表版），Crossref（DOI 论文的正式 venue，摘要常缺）。S2 有 abstract+externalIds 但要 key。

### b) §9.3 引用排序校准 —— **最确定的复用点**

- 直接照抄 `enrich.py` 模式：`arxiv_id → 10.48550/arxiv.<id> → filter=doi:` 批查（50/批），纯 OpenAlex 零 arxiv 流量。实测 Adam 锚：OpenAlex 84,617 vs 语料内 29,512 → 语料边界低估 ~2.9×，符合预期方向。
- 缺口：`10.48550` DOI 在 OpenAlex 覆盖不全（1706.03762 404）。老文需兜底：OpenAlex `title.search` + 年份约束，或接受漏校准并在报告里标注覆盖率。
- S2 对拍（hjfy 想走没走通的路）需要 `SEMANTICSCHOLAR_API_KEY`，申请免费即可；`externalIds` 双向映射对我们 `journal_ref↔arxiv` 映射表积累也有用。

### c) 发现层 / 种子集

- OpenAlex lexical search + `cited_by_count` 就是现成的"某领域高引 arXiv 候选"发生器（filter 可叠 source=arXiv）。
- OpenReview 本地缓存 9.7 万条（含 arxiv_id 预填 1.5 万）可作 ICLR/NeurIPS/ICML 系种子集来源——**但 SQLite 在 skill 目录下且 gitignored，复用方式是跑它的 `import-citations`/快照导出拿 CSV，而不是把 DB 当依赖**。
- DBLP 目前不可用（反爬），发现层别依赖它。

### d) DOI 反查

`resolve_dois` / `crossref_item_to_paper` 直接可用：`GET api.crossref.org/works/{doi}` → title/authors/venue/is-referenced-by。给我们的 `journal_ref → 正式 venue/DOI` 映射表供数。

### e) 值得照搬的基建零件

1. `_http_runtime.py` 的 connect/read-idle 分离超时 + Retry-After 重试 + per-source 墙钟预算——比手写 requests 强，直接搬。
2. arXiv 跨进程 flock 节流（`arxiv_search_throttle.lock`）——与我们 export.arxiv.org 限速桶纪律完全同构（我们要求 ≥3s，它用 4s 下限）。
3. `_env.py` 免依赖 .env 加载。
4. `postprocess.norm_arxiv/norm_doi/title_norm` + union-find 去重——给引用抽取的 id 规范化、`journal_ref↔arxiv` 映射表合并直接用。
5. OpenReview 缓存的"SQLite + FTS5 + venue_meta 冻结位 + count 探针增量更新"设计，可作我们元数据/边缓存的参考实现。

## 6. 风险与边界

- **不要把 skill 目录当库依赖**：它是本机工具、gitignored 缓存随时重建。复用 = 抄模式/抄函数到我们 `texlate/` 包，或离线跑它拿数据落盘。
- OpenAlex arXiv 覆盖靠 DataCite DOI，老文缺口真实存在（实测 404）；校准报告必须带覆盖率。
- S2、DBLP 当前都不可用（无 key / 反爬）；校准链路按 OpenAlex 单源设计，S2 key 到位后加对拍。
- OpenReview 数据许可见 README 表：nhop crosswalk 是 CC-BY-NC-4.0——**非商用约束，若产品化引用数据要重新评估**。
