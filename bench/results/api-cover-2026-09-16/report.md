# api-cover：server 端点覆盖审计（2026-09-16）

`tests/test_app_endpoints.py` 新增 78 用例（71 passed + 7 xfail strict 钉住确认 bug），关联集 287 passed 无连带破坏，ruff clean。

## 覆盖矩阵

| 端点 | 原覆盖 | 本次补测 |
|---|---|---|
| POST /api/arxiv/{id}/translate | 深 | bad JSON 400、非 dict body、options 非标量(xfail)、model 超长/空白 400、`model:""` 回落、glossary 落库、body options.idempotency_key、idem 命中不占配额、坏 header(xfail+对照400) |
| GET /api/task/{id} | 深 | Last-Event-ID 非整数→全量重放、snapshot.artifacts KIND_URL 映射、404 也带 no-store、坏 header(xfail×2) |
| GET /api/files/{id} | 浅 | 非空 shape、租户 404 |
| GET /api/files/{id}/{kind} | 中 | version match/mismatch 409、record 在盘不在 404、path 逃逸 confine 404、download filename 两路、media type、download=abc→400 |
| POST /api/upload | 深 | 空文件 400、file 文本字段 400、options 坏 JSON/非 dict、model/lang 400、Content-Length 预检 413、filename `../` 消毒、idem 孤儿(xfail) |
| GET /api/health | 够 | — |
| GET /api/tasks | 中 | bogus status→[]、error dict、counters shape |
| POST cancel | 中 | 404、done{cancelled} 事件、租户 404 |
| POST retry | 中 | 404、done 409、bad JSON 400、options 深并、main 换文件 wipe/同名保留、终态副作用(xfail) |
| DELETE | 深 | — |
| GET reader | 中 | 坏 dual.json→500 internal、双侧 url、alignment 缺省、view html/pdf 切换、reading 回读 |
| PUT reader/position | 浅 | document_version 409/match、键白名单、404、bad JSON |
| GET settings | 够 | — |
| PUT settings | 中 | bad JSON、lang/engine/quota 400、concurrency clamp、clear_api_key、未知键 |
| POST settings/test | 浅 | base_url 400 两态、body key 脱敏 |
| GET providers | 够 | — |
| CSRF mw | 中 | DELETE/PATCH cross-site、Origin null/子域碰瓷/IPv6/大小写 |

租户遮蔽矩阵补齐：files/files{kind}/cancel/retry/reader/position/SSE 全 404（server 模式 k-B 看 k-A）。

## 确认的 bug（xfail strict 钉住，按严重度）

**B1 — 坏 `X-Texlate-Base-Url`/`X-Texlate-Model` header → 500，错误面分裂**。resolve_auth (settings.py:436-442) 的 validate ValueError 外抛，`_auth` (app.py:321) 不收敛、无 ValueError handler。`_get_task` 内 `_auth` 在存在性检查之后：任务存在 → 全部 `_get_task` 端点 500；不存在 → 侥幸 404。translate 更碎：body 不带 model 时 `_auth` 恰在 try 内 (app.py:504) → 400；带 model 时 app.py:522 `_auth` → 500。复现：`POST translate json={"model":"m"} headers={"X-Texlate-Base-Url":"ftp://x"}` → 500。建议：`_auth` 内 try/except ValueError → `_ApiError(400)`，比全局 handler 精准。

**B2 — `options` 非标量 → 500**。app.py:502 `dict(body.get("options") or {})`：`"xx"`→ValueError、`5`→TypeError、`["a"]`→ValueError 全裸 500。建议 isinstance(dict) 检查 → 400。

**B3 — retry 在状态机守卫前产生副作用（最重）**。app.py:797-824：merge options → `update_fields(options_json)` + main 变更时 `DELETE FROM chunks` + rmtree(base/zh/build-en/build-zh) → transition 才查 RETRYABLE_FROM。实测 done 任务 `retry {"main":"x","options":{...}}` → 返回 409 但 chunks 已删、options 已改写、目录已清。建议：`row["status"] in RETRYABLE_FROM` 前置判断，或 mutation 挪到 transition 之后。

**B4 — upload idempotent 命中留孤儿目录**。app.py:692-710 先 new_task_id+写 blob 再 `_create_and_enqueue` 查 idem；命中返回旧 tid，新 `tasks/{tid}/upload/` 无行永不回收（DELETE 只清有行任务）。实测同 Idempotency-Key 两次 → tasks/ 下 2 目录 1 行。建议：idem 查找前移到落盘前，或命中后 rmtree 兜底。

## 非 bug 观察

- reader_get (app.py:863) 只 catch JSONDecodeError：合法 JSON 非 dict → AttributeError → 裸 500 无 code。
- file_get download filename：旧式 arxiv_id `hep-th/9901001` 带 `/` 进 filename，浏览器可能截断（无注入面，卫生项）。
- SettingsStore.save 把 FIELDS 外未知键写进 settings.json（load 过滤不回读，文件积垃圾）。
- `_read_body` 非 dict body → `{}` 宽松收（已钉样）；quota 在 idem/reuse 之后判定（刻意，已钉样）。
