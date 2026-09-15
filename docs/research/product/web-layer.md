# Web 服务层 + 前端规格调研

> 交付：API spec / SQLite 队列 / BYOK / 前端框架决策 / 滚动同步 / 部署形态。
> 证据来源：`tmp/refs/texglot`（活体先例，已逐文件读过 server/jobs/reader/alignment/cli/frontend）、npm registry 实测（@pdfslick/* 4.0.2 tarball 解开看过 d.ts 与实现）、`docs/02 §5`、`docs/04 §8`。

## 0. 结论速览

| 议题     | 结论                                                                                                                                                                                                  | 依据                                                                                                                                                                               |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 前端框架 | **SolidJS + TS**                                                                                                                                                                                      | pdfslick 两绑定同版本同维护（同日发版），能力等价；hjfy 同款栈便于复刻阅读体验；Solid store 直接包 zustand 状态、细粒度订阅滚动同步零额外开销；绑定层极薄，未来换 React 是机械移植 |
| PDF 渲染 | `@pdfslick/solid`（@pdfslick/core 包 pdfjs-dist ^6 + zustand ^5）                                                                                                                                     | texglot 用 React+ 裸 pdfjs 手写 viewer 付出 ~57KB 前端代码（PdfReader 39K + PdfPane 17K），pdfslick 白送 PDFViewer/缩略图/缩放/findController                                      |
| 滚动同步 | 页锚映射而非滚动比例：**服务端用 hyperref named destinations 算 alignment（最大权单调链），前端 {page,fraction,viewport} 位置模型分段线性插值**                                                       | texglot `alignment.py` + `readerNavigation.ts` 完整方案可直接借鉴（不搬码），退化路径 = 同页码同 fraction                                                                          |
| 服务形态 | FastAPI 单进程，uvicorn loop 内 `asyncio.Queue` + SQLite(WAL) 持久化；CLI 是本地服务的瘦 HTTP 客户端（服务自动拉起 + flock 单 owner）                                                                 | texglot 同款：`service.lock` + 127.0.0.1 + `--parent-pipe` watchdog                                                                                                                |
| SSE      | `GET /api/task/{id}` 按 Accept 协商：`text/event-stream`→流，否则 JSON 快照；`Last-Event-ID` 断线重放                                                                                                 | texglot 用 2s 轮询够用但 SSE 更贴合逐段进度；事件表落盘即可重放                                                                                                                    |
| BYOK     | 三级入口：请求头 `X-Texlate-Key`（多用户服务端）> settings.json `0600`（本地默认）> env；**key 只进内存，task 序列化绝不包含；redact() 过滤异常与日志**；租户隔离用 `sha256(key)[:12]` 指纹，不存 key | texglot `config.py`/`llm.py redact()` 完整先例                                                                                                                                     |
| 部署     | `uv tool install texlate` → `texlate web` 起本地服务；wheel 用 hatchling `force-include` 把 `web/dist` 打进 `texlate/server/static`；docker 多阶段镜像走 `TEXLATE_DATA_DIR` + Redis 队列升级位        | texglot pyproject `force-include` + vite 拷 pdfjs 资源模式完全可抄作业                                                                                                             |

---

## 1. texglot 参考拆解（证据沉淀）

texglot（Mengqi-Lei/texglot, Apache-2.0）是形态最接近的活体先例：FastAPI+uvicorn 单 owner 本地服务 + React 前端 + per-job 目录持久化。值得借鉴的模式与要避开的坑：

**服务**（`app/server.py`/`main.py`）

- 先 `service_lock(DATA/"service.lock")` flock 再 bind 127.0.0.1:8765；抢锁失败的并发启动直接退出——**单 owner 语义在加载任务状态之前确立**。
- `--parent-pipe`：桌面端 spawn 后读 stdin，EOF 即自杀（父进程崩溃不残留服务）。
- 中间件三件套：`TrustedHostMiddleware`(localhost only) + `local_only`（非 GET 请求校验 `Origin`/`Sec-Fetch-Site`，防浏览器跨站打本地服务）+ `/api` 一律 `Cache-Control: no-store`。**持有 API key 的 localhost 服务必须防 CSRF，这条直接抄**。
- 前端静态：`frontend/dist` mount `/assets` + `/pdfjs`（vite closeBundle 钩子把 `pdfjs-dist/{cmaps,standard_fonts,wasm}` 拷进 dist）+ SPA fallback `index.html`；wheel 用 `hatch force-include "frontend/dist" = "app/web"`。

**任务**（`app/jobs.py`）

- per-job 目录 `JOBS/{id}/`：`job.json`（atomic_json = tmp+os.replace, 0600）+ `source/` `prepared-source/` `translated/`（work）+ `build-*/` + `original.pdf` `translated.pdf` `translated-source.zip` + `cache-{config_hash}.json`。
- **断点续翻 = 逐 chunk 原子落盘**：每翻完一块立刻 `atomic_json(cache_path, cache)`；重启时 ACTIVE 状态 → `interrupted` + "译文已保存点击继续"。cache key 含 `{prompt_version, base_url, model, language, glossary, paper_context}` 的 sha256——配置变了缓存自然失效，这个 hash 构成方式直接可用。
- 并发模型：`slot = Semaphore(1)` 全管线串行 + 翻译阶段内 `Semaphore(concurrency)` 块级并行；cancel = `task.cancel()` + `interrupted` 态；失败 `redact()` 后落 `job.error`。
- 状态机：`queued→downloading→preparing→translating→compiling→completed|partial|failed|cancelled|interrupted`。`partial` = 有块校验失败但 PDF 已出（保原文降级）——比二元成败好，值得保留。

**对齐**（`app/alignment.py` + `readerNavigation.ts`）——本项目最值钱的一段参考

- en.pdf/zh.pdf 共享 hyperref named destinations（`\label`/section/cite 的 dest ID 双 PDF 一致）。逐 dest 取 `(page, /Top→fraction)`，按类型加权：section=12 > figure/table=10 > equation=4 > cite=3 > `page.*`/footnote=0。
- **最大权单调链**（类 LIS DP）剔除浮动/乱序锚点 → `pairs[]`；另有 `regions[]` 处理图浮动（图在译文里漂了 2 页，区域内按图位置插值而非按正文顺序）。
- 前端 `createPositionMapper`：双侧各算累积坐标 `starts[]`（页高可不等比），位置→坐标→pairs 二分→线性插值→目标 `{page,fraction}`；无 alignment 时退化为同页码 clamp。
- 位置模型 `{page, fraction, viewport?}`：capture 用 `scrollTop + 20%视口高` 的焦点行定位页 + 页内比例；jump 用 `page.top + fraction*height - viewport*vh`。**防回环三板斧**：程序跳转后记 `ignoreTop`（匹配到的 scroll 事件丢弃）、rAF 合帧、`generation` epoch 丢弃过期回调。

**前端**

- React 19 + 裸 `pdfjs-dist@6`（**没用 pdfslick**），自写连续滚动虚拟化（IntersectionObserver 700px 预载 + 每页 aspect-ratio 占位 + canvas retina 上限 `min(dpr,2,√(5M/w*h))`）+ 批注层 + 阅读位置持久化（`document_version`=文件 sha256，PDF 变了批注/位置 409）。
- 轮询 `GET /api/jobs/{id}` 每 2s（无 SSE）。

**BYOK**（`config.py`/`llm.py`）

- `~/.texglot/settings.json`（dir 0700, file 0600）；`public_settings` 剥 key 只回 `has_api_key`；env 兜底按 provider 映射（DEEPSEEK_API_KEY 等）；`redact()` = 替换 key 本体 + `sk-[A-Za-z0-9._-]+` 正则；base_url validator 拒绝带 userinfo/query 的 URL、非 localhost 强制 https。

**texglot 没做/我们不要抄的**：SQLite（它用 per-job JSON，我们已定 SQLite）、SSE（它轮询）、pdfslick（它裸 pdfjs）、任务去重/缓存命中即返回（它每次重跑）。

---

## 2. API 规格

统一约定：Base `/api`；错误一律 `{"detail": str, "code"?: str}`；任务相关响应含 `Cache-Control: no-store`；ID 全部 `t_`+16hex / `c_`+16hex（URL 安全、可排序性无所谓）。

### 2.1 `POST /api/arxiv/{arxiv_id}/translate`

- path `arxiv_id`：`new-style 2501.14787[vN]` 或 `old-style cs/0501001[vN]`，服务端 `parse_arxiv` 同款校验（白名单 arxiv.org host、正则 fullmatch）。
- headers（BYOK，全部可选）：`X-Texlate-Key`、`X-Texlate-Base-URL`、`X-Texlate-Model`；`Idempotency-Key: <client-uuid>`（可选，客户端重试去重）。
- body（可选，字段缺省回落 settings）：

```json
{
    "model": "deepseek-flash",
    "target_lang": "zh-CN",
    "glossary": "可选，覆盖/追加术语表",
    "options": {
        "context_guidance": true,
        "concurrency": 3,
        "engine": "auto",
        "prefer": "reuse"
    }
}
```

- `options.prefer`: `reuse`(默认) — `cache_key` 命中已完成任务 → `200 {task_id, status:"done", reused:true}`；`fresh` — 强制新任务。
- 响应 `202`：

```json
{
    "task_id": "t_9f3c…",
    "status": "queued",
    "cache": "miss",
    "events_url": "/api/task/t_9f3c…",
    "reader_url": "/api/task/t_9f3c…/reader"
}
```

- 错误：400 非法 arxiv id/参数；409 同 cache_key 已有 ACTIVE 任务且 `prefer=reuse`（`detail` 带现有 `task_id`）；413 payload 超限。

### 2.2 `GET /api/task/{task_id}` — 快照 or SSE

`Accept: text/event-stream` → SSE 流；否则 `200` JSON 快照（形状 = `snapshot` 事件 data，见下）。SSE 支持 `Last-Event-ID: {seq}` 重放丢失事件。

帧格式：`id: {seq}\nevent: {type}\ndata: {json}\n\n`；每 15s 一行 `: ping` 保活（评论行，不占 seq）。

| event      | 何时发                                                | data schema（均为 object）                                     |
| ---------- | ----------------------------------------------------- | -------------------------------------------------------------- |
| `snapshot` | 连接建立首帧，seq=0                                   | 完整任务快照（见下）                                           |
| `stage`    | 状态机每次迁移                                        | `{stage, progress, message, at}`                               |
| `chunk`    | 每块状态迁移；服务端按 200ms 窗口合帧批量发 `items[]` | `{done,total,cached,failed, items:[{seq,status,error_code?}]}` |
| `log`      | 管线日志行（编译 log 摘要、修复动作）                 | `{line}`                                                       |
| `warning`  | 非致命警告（表格超限、部分块回退原文）                | `{code, message}`                                              |
| `error`    | 块级可重试错误或致命错误                              | `{code, message, stage, retryable, chunk_seq?}`                |
| `done`     | 终态（done/partial/fault/cancelled）                  | `{status, artifacts, stats}`                                   |
| `ping`     | 保活（也可只用评论行）                                | `{}`                                                           |

JSON Schema（可直接实现；`progress` 为 0-100 粗粒度）：

```jsonc
// snapshot.data
{
    "type": "object",
    "required": [
        "task_id",
        "kind",
        "status",
        "progress",
        "created_at",
        "updated_at",
    ],
    "properties": {
        "task_id": { "type": "string" },
        "kind": { "enum": ["arxiv", "upload_tex", "upload_pdf"] },
        "status": {
            "enum": [
                "queued",
                "fetching",
                "parsing",
                "translating",
                "compiling",
                "done",
                "partial",
                "fault",
                "cancelled",
                "interrupted",
                "needs_auth",
            ],
        },
        "stage": {
            "enum": ["fetching", "parsing", "translating", "compiling"],
        },
        "progress": { "type": "integer", "minimum": 0, "maximum": 100 },
        "message": { "type": "string" },
        "title": { "type": "string" },
        "arxiv_id": { "type": "string" },
        "target_lang": { "type": "string" },
        "model": { "type": "string" },
        "counters": {
            "type": "object",
            "properties": {
                "total": { "type": "integer" },
                "done": { "type": "integer" },
                "cached": { "type": "integer" },
                "failed": { "type": "integer" },
                "tokens": { "type": "integer" },
            },
        },
        "warnings": { "type": "array", "items": { "type": "string" } },
        "error": {
            "type": ["object", "null"],
            "properties": {
                "code": { "type": "string" },
                "message": { "type": "string" },
                "retryable": { "type": "boolean" },
            },
        },
        "artifacts": {
            "type": "object",
            "additionalProperties": { "type": "string" },
        },
        "created_at": { "type": "number" },
        "updated_at": { "type": "number" },
        "last_seq": { "type": "integer" },
    },
}
// stage.data   {"stage":"translating","progress":25,"message":"正在翻译","at":1726…}
// chunk.data   {"done":41,"total":217,"cached":12,"failed":0,
//               "items":[{"seq":39,"status":"ok"},{"seq":40,"status":"ok"},
//                        {"seq":41,"status":"fallback_orig","error_code":"placeholder_mismatch"}]}
// error.data   {"code":"provider_rate","message":"…","stage":"translating",
//               "retryable":true,"chunk_seq":87}
// done.data    {"status":"partial","artifacts":{"en_pdf":"…","zh_pdf":"…","dual_json":"…","zh_src_zip":"…","log":"…"},
//               "stats":{"tokens":81233,"seconds":264,"chunks_failed":3}}
```

错误码枚举：`arxiv_fetch | no_latex_source | pdf_wrapper | parse | provider_auth | provider_rate | provider_timeout | provider_error | validate | placeholder_mismatch | compile | fixloop_exhausted | internal | auth_required`。

进度百分比映射（沿用 texglot 刻度，前端也可只用 stage+counters 自绘）：fetching 3→9 / parsing 9→25 / translating 25→85（按 done/total 线性）/ compiling 90→99 / 终态 100。

### 2.3 `GET /api/files/{task_id}` + `GET /api/files/{task_id}/{kind}`

- `GET /api/files/{task_id}` → 产物清单 `{artifacts: {kind: {bytes, sha256, created_at}}}`。
- `GET /api/files/{task_id}/{kind}[?download=1]`：

| kind          | 内容                                     | media_type       |
| ------------- | ---------------------------------------- | ---------------- |
| `en.pdf`      | 原文编译产物                             | application/pdf  |
| `zh.pdf`      | 译文 PDF                                 | application/pdf  |
| `dual.pdf`    | PDF 路线 BabelDOC 同页双语版             | application/pdf  |
| `dual.json`   | 双语对照数据（阅读器用，schema 见 §5.4） | application/json |
| `src.tar`     | arXiv 原始源码包                         | application/gzip |
| `zh-src.zip`  | 注入 ctex 后的译文工程（含修复手术痕迹） | application/zip  |
| `compile.log` | 最后一次编译日志                         | text/plain       |
| `md`          | 降级产物（PDF 路线 MinerU markdown 包）  | application/zip  |

- `download=1` → `Content-Disposition: attachment; filename="texlate-{arxiv_id}-zh.pdf"`。`?version=` 校验文档 sha256 防阅读器拿旧版（texglot 的 409 模式）。
- 路径安全：kind 白名单枚举，绝不接任意 path。

### 2.4 `POST /api/upload`

`multipart/form-data`：`file`（必）+ `target_lang` `model` `main` `options`(JSON 字符串，同 §2.1)。魔数嗅探而非看后缀：

| 嗅探结果                    | kind         | 路由                                                                                                 |
| --------------------------- | ------------ | ---------------------------------------------------------------------------------------------------- |
| `%PDF`                      | `upload_pdf` | BabelDOC sidecar（AGPL 边界：独立进程，未安装→501 提示安装命令）；产出 en.pdf(=原件)+zh.pdf+dual.pdf |
| gzip/zip/tar 或 `.tex` 文本 | `upload_tex` | 与 arxiv 管线共用 parsing 起点的同一状态机                                                           |
| `.docx/.epub`               | —            | M2 之前 `501 {"code":"unsupported_format"}`                                                          |

上限：80MB 上传 / 300MB 解压 / 4000 文件（texglot 常量）。响应同 §2.1 的 202。

### 2.5 辅助端点（texglot 形状，全部本地语义）

- `GET /api/health` — `{ok, version, compilers:{tectonic,xelatex,babeldoc}, data_dir}`
- `GET /api/tasks` — 按 `tenant`（§4）过滤的任务列表（`?status=` 过滤）
- `POST /api/task/{id}/cancel` / `POST /api/task/{id}/retry`（body 可带 `{main, options}`）
- `GET /api/task/{id}/reader` — `{documents:{original:{version,pages,url},translated:{…}}, alignment, reading}`
- `PUT /api/task/{id}/reader/position` — 存 `{positions, active, mode, zoom, sync}`；document_version 不符 → 409
- `GET/PUT /api/settings` + `POST /api/settings/test` — BYOK 管理（§4）；GET 永不回 key 本体，只回 `has_api_key`
- `GET /api/providers` — provider 预设清单

---

## 3. 任务队列：asyncio.Queue + SQLite

### 3.1 形态

- 进程内 `asyncio.Queue` 做调度 + **单写者连接**（所有 DB 写走 loop 线程一个 `sqlite3`/aiosqlite 连接，`PRAGMA journal_mode=WAL; busy_timeout=5000; synchronous=NORMAL`）；读快照可开只读连接。
- 全局 `Semaphore(1)` 管线槽（texglot 同款：编译/下载重活串行），翻译块级并行由 translate 模块内 `Semaphore(settings.concurrency)` 管。
- 服务端化升级位：队列接口抽成 `enqueue/dequeue/heartbeat`，SQLite 实现先跑；`REDIS_URL` 存在时换 Redis broker（docs/04 已定此路径，M0 不实现 huey）。

### 3.2 DDL（可直接执行）

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE tasks (
  id            TEXT PRIMARY KEY,                -- 't_' + hex16
  kind          TEXT NOT NULL,                   -- arxiv | upload_tex | upload_pdf
  status        TEXT NOT NULL DEFAULT 'queued',  -- 见状态机
  stage         TEXT,                            -- 当前 ACTIVE stage
  progress      INTEGER NOT NULL DEFAULT 0,
  message       TEXT NOT NULL DEFAULT '',
  title         TEXT NOT NULL DEFAULT '',
  arxiv_id      TEXT,                            -- '2501.14787v2'（含版本；无版本任务内补记解析到的版本）
  source_name   TEXT NOT NULL DEFAULT '',        -- 上传文件名 / arxiv url
  main_tex      TEXT NOT NULL DEFAULT '',        -- 探测到的主文件相对路径
  target_lang   TEXT NOT NULL,
  model         TEXT NOT NULL,
  config_json   TEXT NOT NULL DEFAULT '{}',      -- public_settings 等价物：model/base_url/glossary/engine/并发 —— 绝不含 api_key
  options_json  TEXT NOT NULL DEFAULT '{}',      -- context_guidance/prefer/idempotency_key…
  auth_source   TEXT NOT NULL DEFAULT 'settings',-- settings | env | header  ← 恢复时决定能否免密续跑
  tenant        TEXT NOT NULL DEFAULT 'local',   -- §4.4：'local' 或 'k_'+fp12
  cache_key     TEXT,                            -- arxiv_id@ver+model+pipeline_ver+lang 的 sha256，reuse 命中依据
  total_chunks  INTEGER NOT NULL DEFAULT 0,
  done_chunks   INTEGER NOT NULL DEFAULT 0,
  cached_chunks INTEGER NOT NULL DEFAULT 0,
  failed_chunks INTEGER NOT NULL DEFAULT 0,
  tokens        INTEGER NOT NULL DEFAULT 0,
  error_json    TEXT,                            -- {code,message,stage,retryable}
  worker_id     TEXT,                            -- 认领标记（崩溃恢复用）
  created_at    REAL NOT NULL, updated_at REAL NOT NULL,
  started_at REAL, finished_at REAL
);
CREATE INDEX idx_tasks_status  ON tasks(status);
CREATE INDEX idx_tasks_tenant  ON tasks(tenant, created_at DESC);
CREATE UNIQUE INDEX uq_tasks_cachekey_active
  ON tasks(cache_key) WHERE status IN ('queued','fetching','parsing','translating','compiling','interrupted');

CREATE TABLE chunks (
  task_id    TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  seq        INTEGER NOT NULL,                   -- 文档内顺序
  chunk_id   TEXT NOT NULL,                      -- sha256(src_file+byte_start+byte_end)[:24]
  src_file   TEXT NOT NULL,
  byte_start INTEGER NOT NULL, byte_end INTEGER NOT NULL,
  kind       TEXT NOT NULL DEFAULT 'text',       -- text|caption|section_title|footnote…
  src_text   TEXT NOT NULL,                      -- 原文（含占位符），重译/调试要回查
  status     TEXT NOT NULL DEFAULT 'pending',    -- pending|ok|fallback_orig|failed
  translation TEXT,
  error_code TEXT,
  attempts   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (task_id, chunk_id),
  UNIQUE (task_id, seq)
);
CREATE INDEX idx_chunks_pending ON chunks(task_id, status) WHERE status='pending';

CREATE TABLE files (
  task_id  TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  kind     TEXT NOT NULL,                        -- src_tar|en_pdf|zh_pdf|dual_pdf|dual_json|zh_src_zip|compile_log|md_zip
  path     TEXT NOT NULL,                        -- 相对 tasks/{id}/ 的路径
  bytes    INTEGER, sha256 TEXT,
  created_at REAL NOT NULL,
  PRIMARY KEY (task_id, kind)
);

CREATE TABLE translation_cache (                 -- 跨任务内容寻址缓存（断点续翻的真正基底）
  key        TEXT PRIMARY KEY,                   -- sha256(model|prompt_ver|target_lang|glossary_ver|src_text)
  translation TEXT NOT NULL,
  model TEXT NOT NULL, target_lang TEXT NOT NULL,
  hit_count INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL, last_hit_at REAL NOT NULL
);

CREATE TABLE task_events (                       -- SSE 重放 + 审计；每任务封顶 2000 条滚动截断
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  seq     INTEGER NOT NULL,
  type    TEXT NOT NULL,                         -- stage|chunk|log|warning|error|done
  data    TEXT NOT NULL,                         -- JSON
  created_at REAL NOT NULL,
  PRIMARY KEY (task_id, seq)
);
```

### 3.3 状态机

```
            ┌────────────────────────────────────────────┐
            │                queued                      │
            └───────┬────────────────────────────────────┘
                    ▼
 fetching → parsing → translating → compiling → done
                    │  块级失败降级     │ 修复循环耗尽
                    └──→ 仍出 PDF ──→ partial
   任意 ACTIVE 态 ──异常──→ fault(retryable) / fault(终)
   任意 ACTIVE 态 ──cancel──→ cancelled（已译块保留，retry 复用）
   进程重启遗留 ACTIVE ──→ interrupted（resume 端点重入队）
   header BYOK 任务中断后重启 ──→ needs_auth（重带 X-Texlate-Key retry）
```

迁移守卫：`retry` 允许自 `fault|partial|cancelled|interrupted|needs_auth → queued`；`cancel` 允许自任意 ACTIVE→cancelled；其余非法迁移 409。

### 3.4 断点恢复（三级粒度）

1. **stage 级**：每个 stage 完成的物证是 `files` 行 + 磁盘哨兵（`tasks/{id}/src/` 就绪、`.fetch-done` 等）。`parsing` 完成 ⇒ `chunks` 行已批量插入；重进 parsing 前先查 `chunks` 有行则跳过解析。
2. **chunk 级**：翻译循环每完成一块，`translation_cache` + `chunks` 同事务写入（批量 flush：每 8 块或 500ms 一次事务，兼顾 SSD 寿命与崩溃窗口）；恢复 = `SELECT … WHERE status='pending'` 继续。`fallback_orig` 块记入 `failed_chunks` 并驱动 `partial` 终态。
3. **事件级**：`task_events` 在每次事件落盘时同事务写 → `Last-Event-ID` 重放与刷新页面后 `snapshot` 重建零成本。
4. 启动恢复：`UPDATE tasks SET status='interrupted', worker_id=NULL WHERE status IN (active)` → 前端列表面向用户"继续"按钮；`auth_source='header'` 的转 `needs_auth`。

---

## 4. BYOK

### 4.1 key 入口优先级（高→低）

1. **请求头**：`X-Texlate-Key` / `X-Texlate-Base-URL` / `X-Texlate-Model` —— 服务端多用户模式与"临时换个 key"共用此路；**只在内存里活过任务生命周期，绝不写 settings/tasks/files/日志**。选 header 而非 body：FastAPI 校验失败时 body 可能进异常细节；header 天然不进 uvicorn access log（它不记 header）。
2. **服务端配置**：`PUT /api/settings` → `~/.texlate/settings.json`（父目录 0700、文件 0600、`atomic_json` 写入）。本地单机默认形态。
3. **环境变量**：`TEXLATE_API_KEY` → provider 映射兜底 `OPENAI_API_KEY`/`DEEPSEEK_API_KEY`/`DASHSCOPE_API_KEY`/`ANTHROPIC_API_KEY`；`TEXLATE_BASE_URL`/`TEXLATE_MODEL` 同理。仅启动时读。
4. CLI `texlate --configure [--key-env NAME]`：交互安全输入（getpass）写 settings.json——texglot 同款。

任务创建时记录 `auth_source ∈ {settings, env, header}`。运行期 `secrets` 仅挂内存任务对象；序列化路径全部不含 key（`config_json` 是 public_settings 形态）。重启后 `auth_source=header` 的任务 → `needs_auth`。

### 4.2 绝不落日志（四层防线）

- 异常边界：`redact(text, key)`（texglot 实现两行：替换 key 本体 + `re.sub(r'sk-[A-Za-z0-9._-]+','[密钥已隐藏]')`，扩 `key-|Bearer \S+|sk-ant-\S+` 模式）——`error_json`、SSE `error`/`log`、`compile.log` 摘要全部先过它。
- `logging.Filter` 挂根 logger 做同款正则 scrub（防三方库把请求体打进 traceback）。
- API 出参：`GET /api/settings`/`config_json` 只给 `has_api_key`；`connections.json` 按 base_url 分槽存 key（texglot 模式，切 endpoint 找回各自 key）。
- base_url validator：拒绝 URL 内嵌 userinfo/query；非 localhost 强制 https（texglot `validate_url` 照抄思路）。

### 4.3 缓存与隔离

- `tasks.tenant`：`local`（单机）或 `'k_'+sha256(api_key+server_salt)[:12]`（服务端模式从 key 派生指纹，**指纹入库、key 不入库**）。`GET /api/tasks`、文件下载、SSE 全部按 tenant 过滤——这是"我的任务列表"隔离。
- `translation_cache` 默认**跨租户共享**：内容寻址（key 由 src_text+model+prompt_ver+lang 决定），不含任何用户数据，命中是双赢；paranoid 部署开 `TEXLATE_CACHE_SCOPE=tenant` 把 tenant 拼进缓存键即可，零 schema 变更（key 仍是单列主键）。
- `tasks.cache_key`（产物级 dedup）= `sha256(arxiv_id@ver|model|pipeline_ver|target_lang)` —— **故意不含 tenant**：同一 arXiv+ 同配置，A 译过 B 可直接 reuse（产物是公开论文的确定性函数）；要求租户间物理隔离的部署同样用 `CACHE_SCOPE=tenant` 一键切。

---

## 5. 前端

### 5.1 框架决策：SolidJS（证据）

npm 实测（registry 直查 + tarball 解包读 d.ts/实现，2026-09-14）：

| 维度                         | `@pdfslick/solid`                                                                                                                                                   | `@pdfslick/react`                                                                                               |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| 版本/维护                    | 4.0.2，2026-08-09 发布                                                                                                                                              | 4.0.2，同日同 monorepo 发布（github.com/pdfslick/pdfslick，MIT，~1.1k★）                                        |
| 共同核心                     | `@pdfslick/core@4.0.2` = pdfjs-dist ^6 + zustand ^5，`PDFSlick` 类暴露 `viewer(PDFViewer)`、`eventBus`、`gotoPage`、`setScrollMode/SpreadMode/Rotation`、`document` | 同左                                                                                                            |
| `usePDFSlick(url,opts)` 返回 | `pdfSlick: Accessor`、`pdfSlickStore`（solid store 包 zustand 态）、`viewerRef`/`thumbsRef`、`PDFSlickViewer`、`PDFSlickThumbnails`、`error`、`isDocumentLoaded`    | `store: StoreApi`、`usePDFSlickStore(selector)`、`viewerRef`/`thumbsRef`、同两组件、`error`、`isDocumentLoaded` |
| peers                        | `solid-js>=1.5`（当前 1.9.x）                                                                                                                                       | `react>=17` `react-dom>=17`                                                                                     |
| Viewer DOM                   | `<div id=viewerContainer style="position:absolute;inset:0;overflow:auto"><div id=viewer class="pdfSlickViewer pdfViewer">`                                          | 同构                                                                                                            |

**决定 SolidJS，理由按权重排序**：

1. **hjfy 同款**：我们要复刻的就是 hjfy 的阅读体验，同栈时其行为（DOM、事件、时序）可直接对照观察，踩过的坑大概率同款。docs/04 §8 也标了"pdfslick 原生"。
2. **响应模型贴合双 viewer**：`pdfSlickStore` 是 solid store 对 zustand 的 reconcile 包装，组件里 `store.pageNumber` 细粒度订阅、零 selector 样板；React 侧每处读数都要 `usePDFSlickStore(s=>s.x)`。滚动同步本身走 DOM/事件不进 store，两个框架都能做——但工具栏、进度、缩略图这些高频小状态，Solid 写法更短且无重渲染顾虑。
3. **包体**：solid-js ~10KB vs react+dom ~45KB（本地工具无所谓但白拿的）。
4. **可逆**：两绑定都是 core 上的 ~150 行薄壳，同步引擎（§5.3）是纯 TS 不依赖框架；若未来要 React 生态（如现成批注组件），移植成本=重写壳组件。

已识别的坑（两绑定共有，写进实现须知）：**`usePDFSlick` 不做实例清理**——React 版 effect `return ()=>{}`、Solid 版无 `onCleanup`，url 变化会在同一 DOM 上叠第二个 PDFSlick。对策：每个文档版本一个新挂载点（Solid：`<Show keyed>` 或组件外套 `{()=>keyed node}`；即 pane 组件 `key={doc.version}` 整体重挂），绝不原位换 url。另一坑：`PDFSlickViewer` 自带 resize→`scaleValue` 重设逻辑，双栏 resize 时缩放行文要一致。

反方观点备案：React 生态大（批注/虚拟列表现成）、招人熟。但本 UI 面窄（任务列表 + 设置 + 阅读器），texglot 已证明裸 pdfjs+React 要手写 ~57KB，我们没有任何 React-only 需求。

依赖钉：`@pdfslick/solid@^4` `solid-js@^1.9` `marked@^18` `katex@^0.18` `vite@^8` `vitest`。

### 5.2 应用骨架与三模式 UI

```
web/
  index.html  package.json  vite.config.ts  tsconfig.json
  src/
    main.tsx  App.tsx
    api/client.ts          # fetch 封装 + EventSource(SSE)+Last-Event-ID 重连 + 类型生成自 §2 schema
    stores/tasks.ts        # 任务列表/活动任务 store（zustand vanilla 或 solid store）
    stores/settings.ts
    pages/Home.tsx         # arxiv 输入 + 上传 + 任务列表（进度条走 SSE）
    pages/Reader.tsx       # 阅读器外壳：模式/缩放/同步/页跳转/下载菜单
    pages/Settings.tsx     # BYOK 表单（key 只写不回显）、engine、glossary、test 按钮
    reader/PdfPane.tsx     # usePDFSlick 封装 + 暴露 capture/jump/ready
    reader/HtmlPane.tsx    # 降级视图（marked+KaTeX，data-chunk 锚）
    reader/sync.ts         # SyncEngine（§5.3，框架无关纯 TS）
    reader/alignment.ts    # Alignment 类型 + createPositionMapper（texglot 逻辑重写）
    components/{Toolbar,TaskList,ProgressGrid,Segmented}.tsx
    i18n/  styles/
```

三模式 `mode ∈ original|translated|split`：顶栏 Segmented 三态 + 同步开关 + 缩放（`page-fit`/`page-width`/百分比）+ 页码输入 + 下载菜单（zh.pdf/en.pdf/dual.pdf/dual.json/zh-src.zip/log）+ 重试/取消。split 下双 `PdfPane` 各挂一个 `usePDFSlick`，active pane 高亮；**模式切换保位置**（texglot `planModeChange`：切 split 时用当前 active 侧位置 map 出对侧；切单栏时带位置走）。阅读位置 `PUT /reader/position` 防抖 1s 落盘。

任务列表/进行中视图：SSE `chunk` 事件驱动 `done/total` 进度条 + `items[]` 渲染**段落棋盘格**（hjfy 式逐段可视：ok 绿/fallback 黄/failed 红），`stage` 事件驱动阶段步进条，`log` 进折叠日志抽屉。

### 5.3 双 viewer 滚动同步（~100 行伪码）

位置模型 `{page, fraction, viewport?}`（texglot 验证过的形状）；映射靠服务端 `dual.json` 里的 `alignment`（§1 对齐算法：named destinations + 最大权单调链 + figure regions；无 hyperref 锚时 `kind:"pages"` 退化为同页码）。pdf.js 侧：滚动容器 = `pdfSlick.viewer.container`，页元素 `.page[data-page-number]`，`viewer._pages[i].div` 有 `offsetTop/offsetHeight`。

```ts
type Pos = { page: number; fraction: number; viewport?: number };
class Pane {
    // 包一个 usePDFSlick 实例
    constructor(
        public slick: PDFSlick,
        public side: Side,
    ) {}
    get el() {
        return this.slick.viewer.container;
    }
    pages(): { page: number; top: number; height: number }[] {
        return this.slick.viewer._pages.map((v, i) => ({
            page: i + 1,
            top: v.div.offsetTop,
            height: v.div.offsetHeight,
        }));
    }
    capture(): Pos {
        // 焦点行 = scrollTop + 20%vh
        const t = this.el.scrollTop,
            h = this.el.clientHeight,
            focus = t + h * 0.2;
        const p =
            [...this.pages()].reverse().find((p) => p.top <= focus) ??
            this.pages()[0];
        const y = Math.min(Math.max(focus, p.top), p.top + p.height);
        return {
            page: p.page,
            fraction: (y - p.top) / p.height,
            viewport: (y - t) / h,
        };
    }
    jump(pos: Pos) {
        const p = this.pages().find((p) => p.page === pos.page);
        if (!p) return;
        this.el.scrollTop =
            p.top +
            pos.fraction * p.height -
            (pos.viewport ?? 0) * this.el.clientHeight;
    }
}
class SyncEngine {
    syncing = true;
    private epoch = 0;
    private ignoreTop = new WeakMap<HTMLElement, number>();
    constructor(
        private A: Pane,
        private B: Pane,
        private map: (p: Pos, from: Side) => Pos,
    ) {
        for (const p of [A, B])
            p.el.addEventListener("scroll", () => this.onScroll(p), {
                passive: true,
            });
    }
    private onScroll(src: Pane) {
        if (!this.syncing) return;
        const it = this.ignoreTop.get(src.el);
        if (it !== undefined && Math.abs(src.el.scrollTop - it) < 1) return; // 吃掉自己程序跳转的回声
        this.ignoreTop.delete(src.el);
        const pos = src.capture(),
            e = ++this.epoch,
            dst = src === this.A ? this.B : this.A;
        requestAnimationFrame(() => {
            // 合帧 + epoch 丢弃过期
            if (e !== this.epoch || !this.syncing) return;
            const target = this.map(pos, src.side);
            dst.jump(target);
            this.ignoreTop.set(dst.el, dst.el.scrollTop);
        });
    }
}
// 映射：alignment.pairs 已是 [(orig_coord, tran_coord)] 递增折线（服务端算好单调链），
// 坐标 = Σheights[0..page-1] + fraction*h[page]；二分插值回 {page,fraction}；regions 优先（图浮动）；
// 无 pairs → {page: clamp(pos.page,1,nB), fraction: pos.fraction}。
```

要点全部有 texglot 先例背书：ignoreTop 防回环、rAF+epoch 合帧、20% 焦点线、viewport 字段让"跳过去时锚点停在屏幕同一高度"。缩放/resize 时 pdfslick 会重排页几何——capture/jump 全部基于当前 DOM 量纲天然免疫；mode 切换前后各 capture 一次再 jump 回去。

### 5.4 `dual.json` 与 HTML 降级路径

`dual.json`（`files` 表 kind=`dual_json`）：

```jsonc
{
  "version": 1,
  "documents": {"original": {"version":"sha256…","pages":42},
                "translated": {"version":"sha256…","pages":45}},
  "alignment": {"kind":"landmarks|pages","heights":{"original":[1.29,…],"translated":[…]},
                "pairs":[{"id":"section.1","original":{"page":3,"fraction":0.12},
                          "translated":{"page":3,"fraction":0.31}}],
                "regions":[{"id":"figure.3","original":{"page":9,"start":0.1,"end":0.4},
                            "translated":{"page":10,"start":0.05,"end":0.33}}]},
  "chunks": [{"seq":0,"src_file":"main.tex","en":"…","zh":"…","kind":"text"}]  // 可选，HTML 视图用
}
```

**降级路径**：`upload_pdf` 路线（MinerU→markdown）或编译彻底失败但译文在库时，`reader` 响应给 `view:"html"`：`HtmlPane` 用 `marked.parse` 渲染双侧，`katex` auto-render 处理 `$…$`/`$$…$$`/`\[\]`，原文侧同样渲染 markdown/en 文本。同步复用 SyncEngine——只是 `pages()` 换成 `querySelectorAll('[data-chunk]')` 的 `offsetTop/offsetHeight`，且 chunk 对是严格 1:1（seq 直映）比 PDF 锚更准。KaTeX 单公式失败 fallback：原样显示源码 + `.katex-error` 样式，不炸整页。

### 5.5 Vite 工程

`vite.config.ts`：`@solidjs/vite-plugin`（或 react plugin）；`server.proxy['/api']='http://127.0.0.1:8765'`；`build` 用 texglot 的 `closeBundle` 插件把 `pdfjs-dist/{cmaps,standard_fonts,wasm}` 拷进 `dist/pdfjs/`（pdfslick `getDocumentParams` 里配 `cMapUrl:'/pdfjs/cmaps/'` 等）+ 生成 `THIRD_PARTY_LICENSES.txt`。测试 vitest（同步引擎/alignment 纯函数可 node --test 式单测，texglot 的 `tsconfig.reader-tests.json` 模式）。

---

## 6. 部署形态

**本地（主形态）**：`uv tool install texlate` → `texlate` 入口三模式（texglot `cli.py` 同构）：

- `texlate web|serve [--port 8765]`：前台跑 `uvicorn`，绑定 127.0.0.1，先 `service.lock` flock（抢不到 → 直接 `open http://127.0.0.1:8765` 复用已有实例）。
- `texlate <arxiv-url|file>`：瘦 HTTP 客户端——健康探测失败就 `spawn python -m texlate.server`（+`--parent-pipe` 可选），等 `/api/health` 起来后走 §2 API，进度 SSE 渲染到终端。
- `texlate --configure/--list/--status/--resume`：设置与任务管理。
- 数据目录 `~/.texlate/`（`TEXLATE_DATA_DIR` 覆盖）：`settings.json`(0600) `texlate.db` `tasks/{id}/` `service.lock` `connections.json`。

**打包**：`hatchling` wheel `force-include`: `"web/dist" = "texlate/server/static"`；FastAPI mount `static/assets`+`static/pdfjs`+SPA fallback（texglot `main.py` 尾部同款）；release 流水线 `npm ci --prefix web && vite build` 先于 `uv build`，dist 不入库。

**Docker（服务端形态）**：multi-stage——`node:xx` build web → `python:3.12-slim` + tectonic 预置二进制（校验和）+ fonts-noto-cjk；`ENV TEXLATE_DATA_DIR=/data`（挂卷）、`EXPOSE 8765`；`TEXLATE_MODE=server` 时：绑 0.0.0.0、关 service.lock 单 owner、`REDIS_URL` 启用 Redis 队列后端、tenant 强制 header 指纹、本地 `local_only` 中间件换正式 CORS allowlist。TeXLive xelatex 变体镜像做 tag `texlate:full`（CI/服务端高成功率编译）。

**桌面（远期）**：texglot 矩阵已验证 Electron+PyInstaller（冻结后端 `--engine-server` 子命令 + spawn + parent-pipe），UI 与 web 同源。

---

## 7. 开放问题 / 风险

1. **SSE 还是轮询**：SSE 已按本规格设计；若 M0 想再省一天，`GET /api/task/{id}` JSON 快照 + 2s 轮询（texglot 模式）完全兼容——事件协议不变，前端只换 transport。建议直接 SSE，`task_events` 表反正要写。
2. **`_pages` 是 pdf.js 内部字段**：`viewer._pages[i].div` 虽稳定多年但非公开 API；备选 = `container.querySelectorAll('.page')`（`data-page-number`）。实现时抽 `pages()` 一层即可随时换。
3. **alignment 依赖 hyperref**：arXiv 论文有少数无 hyperref/禁用 dest 的工程 → `kind:"pages"` 退化（同页码映射），体验降级但仍可用；这是 texglot 同款边界。
4. **pdfslick 单点风险**：个人维护者（1.1k★），但它本质是 pdf.js `web/viewer` 组件的打包封装——最坏情况 fork 或直接掉回 texglot 式裸 pdfjs（有完整先例代码路径）。
5. **BabelDOC sidecar 进度**：sidecar 进程 stdout 进度行 → 解析后映射成 `chunk`/`stage` 事件（docs/04 §120 行已留此口）。
