# export.arxiv.org 探针实录：Atom 惩罚窗口 / OAI 迁站 / 全站镜像 / 路径级限流

> **结论**：export.arxiv.org 是 arxiv.org 的**全站镜像 + Atom API 唯一入口**——内容端点与主站同行为、互为故障转移；OAI-PMH 已整端点 301 迁至 `oaipmh.arxiv.org`（第三限流桶）；`/api` 的 429 惩罚窗口 ≥小时级、无 Retry-After、且**限流按路径不按 host**。
> **状态**：时点证据（2026-09-14 口径）。结论已实装：`ratelimit.py` 三桶 + (host,path-class) 断路器、`fetch.py` export 故障转移、`meta.py` OAI baseURL。
> **日期**：2026-09-14 取证，2026-09-20 重订入库

## 1. Atom API：429 → 503 → 429，窗口 ≥小时级

同一 `api/query?id_list=` 请求在当日时间线（UTC）：

| 时间    | 结果                                                                                          |
| ------- | --------------------------------------------------------------------------------------------- |
| 早先    | ~170 发 bench 后全程 429，+20s/+60s/+90s 重试均灭                                             |
| 12:38   | 429 · 14B `"Rate exceeded."` · **无 Retry-After、无 RateLimit-* 头**（edge：Google Frontend） |
| 12:51   | 503 · 126B Varnish 骨架页 · `Retry-After: 0`（后端 46s 超时的模板头，非限流语义）             |
| 12:58   | 429                                                                                           |
| 13:28   | 429（**30min 零请求静默后仍拒**）                                                             |

读法：429 是边缘限流器瞬时拒绝；12:51 那发穿过边缘打到后端，后端 46s 不应由 Varnish 给 503——两种可能（惩罚窗口短暂开缝但后端病态 / 503 是限流链路深层失败形态），无论哪种 API 均不可用。**窗口下限从「≥3min」上修为「≥小时级」**；429 响应没有 Retry-After，窗口只能稀疏探活实测（每发 api 请求可能续窗）。调度含义：park 起步 30–60min、指数退避、park 期间用定时单发探活而非连续重试。

## 2. OAI-PMH 迁站

`export.arxiv.org/oai2` 全动词 301 → `oaipmh.arxiv.org/oai`（query 原样透传）。export 上的 `/oai2` 已是纯 redirector——调度器里 OAI 记到第三桶 `oaipmh.arxiv.org`。该 host 能力见 [oai-pmh.md](oai-pmh.md)。

## 3. 内容端点：export 是全站镜像

| 请求                            | 结果                                                                                          |
| ------------------------------- | --------------------------------------------------------------------------------------------- |
| `HEAD /e-print/2203.02155`      | 301 → `/src/2203.02155`（同主站行为）                                                        |
| `HEAD /src/2203.02155`          | 200 · 同 cd 文件名 `arXiv-2203.02155v1.tar.gz` · 同 etag `"sha256:f257…"`                    |
| `HEAD /pdf/2203.02155`          | 200 · `content-disposition: inline` · canonical 指回 `arxiv.org/pdf/…`                        |
| `HEAD /abs/2203.02155`          | 200 · `cache-control: max-age=3600`                                                          |
| `GET /src/2203.02155`           | 200 · 1,072,116B · gzip 头、tar 列 33 项真 e-print                                            |

行为与主站完全一致（301 形态、cd 命名、sha256 etag）。Age 值（abs ~17 天、pdf ~19 天、src ~9.3h）表明内容几乎全走 Fastly/Varnish 缓存命中——**这解释了为什么 429 期间内容端点照常 200：缓存层根本没回源**。

## 4. 限流边界：429 只罩 `/api/*`，不罩内容路径

同一时间窗口内 `/api/query` 429（MISS 回源被拒）而 `/src` `/pdf` `/abs` `/e-print` 全 200/301——**惩罚是 endpoint 级不是 host 级**。对照实锤：`HEAD /src/9999.99999`（必然 MISS 回源）在 API 惩罚窗口内照常回 404。含义：调度可以更细——export 的 API 被锤时只 park 元数据队列，e-print/src/pdf 下载可继续。注意 404 可能由 Varnish 边界直接合成（`Server: Varnish` 而非 Google Frontend），与真实 GET 回源路径未必完全等价——但作为「内容路径不受 429 牵连」的证据已足够强。

## 5. 对架构的影响

1. **下载面容量 ×2**：export 是天然 failover——但同一 IP 大概共享同一惩罚对象，failover 只解决「主站路径限流」不解决「IP 被拉黑」。
2. **三桶调度**：`arxiv.org` / `export.arxiv.org` / `oaipmh.arxiv.org`，按路径类（api/oai/content/other）分别 park。
3. **`<arxiv:doi>` 验证弃验**：Atom 全程不可用未拿到真 XML；DataCite `api.datacite.org/dois/10.48550/arxiv.{id}` 免 key 全量覆盖且 `dates[]` 白送版本史——DOI 反查走 DataCite 不依赖 Atom（渠道细节见 [bulk-channels.md](bulk-channels.md) 与语料域档案 [../corpus/](../corpus/)）。
