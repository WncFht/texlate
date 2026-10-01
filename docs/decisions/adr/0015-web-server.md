# ADR-0015 Web 服务端：FastAPI + SSE + SQLite WAL 单写者 + BYOK 内存态

> **状态**：现行
> **日期**：2026-09-15（05 裁决 4 + web 层规格）| 更新 2026-09-17（arxiv_html 任务臂、retry 语义改判）

## 上下文

hjfy 的阅读体验（已译随便看 + 流式进度 + 双语对照）需要一个 web 层；texlate 定位单机/自托管 BYOK——不引重型队列、不多写者、不落用户 key。裁决面：任务编排（asyncio 够不够）、实时推送（SSE vs WebSocket vs 轮询）、持久化（SQLite 单写者扛得住否）、凭证面（key 的生命周期与租户隔离）。

## 裁决

- **栈**：FastAPI + `asyncio.Queue` 进程内编排 + SQLite WAL 单写者 store——M0 不引 huey/Redis（`REDIS_URL` 留作多实例扩展槽）；worker 是同进程协程不是独立服务。
- **状态机**：11 态 = 5 ACTIVE（queued/fetching/parsing/translating/compiling）+ 6 TERMINAL（done/partial/fault/cancelled/interrupted/needs_auth）；迁移守卫只在 store 一处（cancelled←ACTIVE、queued←RETRYABLE_FROM），`task_events` 滚动上限 2000/任务。
- **SSE**：`Accept` 协商（要流给流、不要流给轮询 JSON）；事件型 snapshot/status/stage/progress/chunk/log/warning/error/done/resync；`Last-Event-ID` 断线重放 + 200ms 合并窗口削碎片；长任务以 snapshot 重锚。
- **持久化**：六表 DDL（tasks/chunks/files/translation_cache/task_events/task_usage）+ 幂等键索引（tenant+idempotency_key 防重复建单）+ 列迁移幂等；flock 单属主防双开 data dir。
- **BYOK 凭证面**：优先级 header > settings > env > CLI；key **只活内存**不落盘；租户身份 = `k_<sha256 指纹>`（key 本体永不进库/日志，`redact()` 全链脱敏）；server 模式下无 key 时**不回退默认网关**（静默用别人的配额是安全洞）。
- **边界**：`request_gate_mw` 收口（body 上限/超时/统一错误形）；upload 走自有安全解包（与 arxiv 包同套规则）；SPA 由 staticfiles 托管（前后端同进程）。

## 理由

- E15：SQLite WAL 单写者 + asyncio 编排对单机并发（个位数任务）足够——多写者与外部队列解决的是不存在的问题；轮询兼容面（compat 路由）证明 SSE 不是唯一消费形态。
- key 内存态 + 指纹租户是 BYOK 的底线隐私承诺——持久化 key 等于把用户账单风险收进我们库里。
- 证据：主仓 `docs/05` E15、web 层规格；调研档案 `research/product/2026-09-15-web-layer.md`、`research/product/2026-09-14-e2e-mock-pipeline.md`。

## 演变

- 2026-09-16：server 模式 key 无回退定案（此前曾议「无 key 回落内部网关」——否决）；P0 安全修复收口 request_gate/upload 面。
- 2026-09-17：G1 落地——`arxiv_html` 任务 kind 进状态机（同 11 态，translating 段换 HTML 块级翻译）；m3gap 裁决 `retry{model}` 语义改判为「新建任务」而非原地重试（原模型参数进键，原地重试会毒 dedup 面）；dedup 口径改「只复用 done」+ partial 毒传播修复 + `prefer=fresh` 显式开关。
- 2026-09-19→20：能力面扩——`routers/compat.py`（hjfy 轮询协议兼容）、`routers/discover.py`（alphaXiv 代理发现面）、`routers/reader.py`（阅读器数据面）；并发档位与 segment 缓存分桶（base_url+auto_glossary）细化。

## 现状

实现落在 `server/` 包：`app.py`（ASGI 装配 + gate 中间件）、`store/`（六表 + 11 态守卫 + 幂等键，`store/_common.py` 是 DDL 单源）、`events.py`（SSE 合帧 + Last-Event-ID）、`worker/`（runner + fetch/parse/translate/compile/share/html/pdf/retranslate 分 stage 叶）、`routers/`（tasks/files/meta/reader/settings/share/upload/compat/discover）、`providers.py`（BYOK 预设 + 探活）、`auth.py`/`settings.py`（凭证解析链）、`upload.py`（安全解包）、`staticfiles.py`（SPA）、`logredact.py`（脱敏）。并发默认与 `TEXLATE_*` 开关以 `settings.py` 实数为准。
