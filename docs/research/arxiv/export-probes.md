# export.arxiv.org 探针实录（2026-09-14 下午）

> 原始数据：`tmp/exp/export-probes/`（`headers.jsonl` 全量响应头、`src_2203.02155.tar.gz` 实下载样本、`probe.py` 探针脚本）。
> 注意：`*_atom_sample.xml` 实为错误响应 body 留档（429 的 14B 文本 / 503 的 126B Varnish 页）——**本轮从未拿到真正的 Atom XML**；oai_*.xml 同理不存在（301 无 body）。
> 条件：UA `texlate/0.1-dev (+https://github.com/wncfht/texlate; mailto:research@texlate.dev)`，同 host ≥3.05s 串行，不跟随 redirect。

## 1. 实测摘录

### 1.1 Atom API —— 429 → 503 → 429，未恢复；429 无 `Retry-After`

```
12:38:10  GET /api/query?id_list=1412.6980 → 429 · 14B "Rate exceeded."
          响应头无 Retry-After、无 RateLimit-* 族头（server: Google Frontend, X-Cache: MISS）
12:51:13  同请求 → 503 · 126B · Retry-After: 0 · Server: Varnish
          X-Timer VE46079 → 边缘等后端 46s 超时；body 是 Varnish 骨架页 <!DOCTYPE html>…503
12:58:12  同请求 → 429 · 14B "Rate exceeded."
```

读法：429 是边缘限流器的瞬时拒绝；12:51 那发**穿过了边缘限流**打到后端，后端 46s 不应 → Varnish 给 503（附 `Retry-After: 0`，是 Varnish 后端失败的模板头，不是限流语义）→ 7min 后又是 429。两种可能：(a) 惩罚窗口在 12:51 前后短暂开了一条缝但后端本身病态；(b) 503 就是限流链路深层的失败形态。**无论哪种，API 截至 12:58 不可用**。且每发 api 请求可能续窗——测量只能稀疏采样。

§10.2 更新：429 响应**没有** Retry-After（可关闭该子项）；唯一见过的 Retry-After 是 503 上的 `Retry-After: 0`（Varnish 模板，无调度价值）。窗口只能指数退避实测。

### 1.2 OAI-PMH —— export 不再服务，整端点 301 到专用 host

```
GET https://export.arxiv.org/oai2?verb=Identify
→ HTTP 301 · location: https://oaipmh.arxiv.org/oai?verb=Identify
GET https://export.arxiv.org/oai2?verb=ListMetadataFormats
→ HTTP 301 · location: https://oaipmh.arxiv.org/oai?verb=ListMetadataFormats
GET "https://export.arxiv.org/oai2?verb=ListIdentifiers&metadataPrefix=arXivRaw&from=…"
→ HTTP 301 · location: https://oaipmh.arxiv.org/oai?verb=ListIdentifiers&…（原样透传 query）
```

**`/oai2` 在 export 上已是纯 redirector**。OAI-PMH 的实际服务方是 `oaipmh.arxiv.org`（第三个 host/限流桶），本次未探测（不在本 agent 航道）。→ arxiv-layer §8.3 的端点描述要改：`export.arxiv.org/oai2` 只是兼容跳转，调度器里 OAI 应记到 `oaipmh.arxiv.org` 桶；arXivRaw 字段清单/resumptionToken 翻页结构待那个 host 的探针补。

### 1.3 内容端点 —— export 是全站镜像，第二个下载桶实锤

```
HEAD https://export.arxiv.org/e-print/2203.02155 → 301 · location: /src/2203.02155
HEAD https://export.arxiv.org/src/2203.02155    → 200
  content-disposition: attachment; filename="arXiv-2203.02155v1.tar.gz"
  content-type: application/gzip · etag: "sha256:f257…b78" · Content-Length: 1072116
HEAD https://export.arxiv.org/pdf/2203.02155    → 200
  content-disposition: inline; filename="2203.02155v1.pdf"
  link: <https://arxiv.org/pdf/2203.02155>; rel='canonical'   ← canonical 指回主站
HEAD https://export.arxiv.org/abs/2203.02155    → 200 · text/html · cache-control: max-age=3600

GET  https://export.arxiv.org/src/2203.02155    → 200 · 1,072,116B
  文件头 1f8b0800，file(1) 认 gzip；tar -tzf 列出 33 项（tex+figs/，真 e-print）
```

行为与 arxiv.org 侧完全一致（`/e-print`→`/src` 301、同 content-disposition 命名、同 etag 形态——sha256 强校验）。**export 不是 API-only host，它镜像全部内容端点，是真·第二下载桶**。注意 Age 值（abs ~17 天、pdf ~19 天、src ~9.3h）：内容几乎全走 Fastly/Varnish 缓存命中，这也解释了为什么 429 期间它们照常 200——缓存层根本没回源。

### 1.4 限流的边界：429 只罩 `/api/*`，不罩内容路径

同一时间窗口内：`/api/query` 429（MISS 回源被拒），`/src` `/pdf` `/abs` `/e-print` 全 200/301。**惩罚是 endpoint 级的，不是 host 级**。对照实锤：

```
HEAD https://export.arxiv.org/src/9999.99999（不存在 id，必然 MISS 回源）
→ 404 · X-Cache: MISS · Server: Varnish        ← 回源了，但没被限流器拦
```

即「MISS 回源的非 API 请求」在 API 惩罚窗口内照常服务 → 限流器按路径/服务划分，调度器可以更细：**export 桶被锤时只 park 元数据队列，e-print/src/pdf 下载可继续**。注意 caveat：404 可能由 Varnish/后端边界直接合成（`Server: Varnish` 而非 Google Frontend），与真实 GET /src 的回源路径未必完全等价——但作为「内容路径不受 429 牵连」的证据已足够强。

## 2. 结论对架构的影响

1. **export.arxiv.org = arxiv.org 的完整镜像 + Atom API 唯一入口**。e-print/src/pdf/abs 都能下 → 主站被限速时 export 是天然 failover（但同一 IP 大概共享同一惩罚对象，failover 只解决「主站路径限流」不解决「IP 被拉黑」——待验证）。
2. **OAI-PMH 已迁到 `oaipmh.arxiv.org`**，限流桶第三个。export 上的 `/oai2` 只是 301 壳。
3. **429 无 Retry-After** → 窗口只能稀疏探活实测；且实测窗口 >30min（见 §3），spec 的 park 15–30min 偏乐观，建议上调到 30–60min 起步。
4. **`<arxiv:doi>` 回填验证**（§10.4）：本轮 api 仍 429 拿不到 Atom 样本 → 未验证，留待窗口恢复或 oaipmh/其他途径。

## 3. 惩罚窗口测量

| 时间（UTC）                       | 事件                                                              |
| --------------------------------- | ----------------------------------------------------------------- |
| 今早 bench（见 arxiv-layer §1.1） | ~170 req 后 export 全程 429，+20s/+60s/+90s 重试均灭，窗口 ≥3min  |
| 12:38:10                          | `api/query` → 429（14B "Rate exceeded."，无 Retry-After）         |
| 12:38:19–12:41:29                 | oai2×3 → 301；内容端点×5 → 全 200/301/404，无一被限               |
| 12:51:13                          | `api/query` → **503**（后端 46s 超时，Retry-After: 0）            |
| 12:58:12                          | `api/query` → 429                                                 |
| 13:28:35                          | `api/query` → 429（**30min 零请求静默后仍拒**——窗口 >30min 实锤） |

窗口结论：**从今早 bench 起到 ≥13:28 UTC 全程不可用，30min 静默不足以解封**。下限从早上的「≥3min」上修为「**≥ 小时级**」（bench 发生于上午，窗口迄今 ≥数小时；亦不能排除每发探测续窗，但 30min 单发采样已是低频）。调度 spec：park 起步 30–60min、指数退避到小时级、park 期间零探测（用定时单发探活而非连续重试）。
