# web-idem — create 三路 Idempotency-Key 接线

> 2026-09-17。scope：web/（client.ts + mock-api.ts + idempotency.test.ts）。三链全绿，未 commit。

## server 契约核实（结论：服务端已全收，无缺口）

- 三个 create 端点（POST /api/arxiv/{id}/translate :595、/api/upload :775、/api/share/import :828）全部走 `_create_and_enqueue`（app.py:490）。
- app.py:511 `idem = request.headers.get("idempotency-key") or options.get("idempotency_key")`——头优先，options 兜底。
- 命中语义：store.find_by_idempotency（store.py:355，tenant + options_json.idempotency_key，JSON1）命中 → 直返旧行 **202 + {cache:"idempotent"}**，不建行不入队不占配额；未命中 → key 落 options_json。
- **无 dedup 窗口**：永久去重（同 tenant 任意状态行）；任务删除后行消失 → key 可复用（mock 已对齐此语义）。
- CORS：server 形态 allow_headers 已含 "idempotency-key"（app.py:390）。
- 与 409 duplicate_active 关系：两层不冲突——idem 管「同一提交重发」去重，409 管「同 cache_key 活动任务」跨提交拒绝，UI 未做合并。

## key 生命周期设计（client.ts:338-396）

- 「提交意图」= 提交内容指纹 createFp(kind, payload, byok语义)：translate= arxivId+body；upload/shareImport= file.name+size+lastModified + fields/options。byok 里只有 baseUrl/model 进指纹——**apiKey 是凭证不是意图**，换 key 重试仍复用同 idem key。
- `pendingCreate: Map<fp,key>`：key 在请求发出前登记；**拿到任何 HTTP 响应（2xx/4xx/5xx，含 409）即结案删 fp**；网络层失败（TypeError/AbortError，服务端可能已收单）留 key——同参重发/在飞双击复用同 key。结案守卫 `pendingCreate.get(fp)===key` 防旧在飞调用误删新条目。
- 生成：`crypto.randomUUID()` → getRandomValues 128bit hex → Date.now+Math.random 三档兜底（http://LAN 非安全上下文无 randomUUID）。
- byok.idempotencyKey 显式传入 → 原样透传、跳过 pending 机制（调用方自管）。
- 已知边界（残余）：不同参数各网fail 后原参重发仍各自复用（Map 按 fp 存）；session 级 Map 无上限——唯网fail 才留条目，量级可忽略。

## 改动清单（web/ 内，未 commit）

- `web/src/api/client.ts`：+pendingCreate/newKey/intentSettle/createFp/fileFp/createRequest；translate/upload/shareImport 三路改走 createRequest。Home.tsx 零改动（client 层自动带头，byok() 共存）。
- `web/dev/mock-api.ts`：+idemTasks Map、idemHit/idemRegister；三端点命中直返 202 cache:"idempotent"（upload 保留 isDoc reader_url 条件），登记时 emit `[mock] Idempotency-Key ... registered` log 事件（收头可证）；multipart 两端点命中检查放 on("end") 内先排空 body（对齐真后端 form 解析顺序）。
- `web/src/test/idempotency.test.ts`：新增 8 用例——key 生成与格式 / 成功后新 key / 网fail复用+HTTP错误结案 / 在飞并发同 key / 指纹绑定（换参新key+原参回用） / upload+shareImport 覆盖 / 显式 key 透传不占位 / 改 apiKey 复用。
- i18n 无新增文案（头不可见）；未碰 web/ 外文件；未 commit。

## 三链验证

`npx tsc --noEmit` ✅ / `npx eslint .` ✅ / `npx vitest run` ✅ 14 files / 93 tests 全绿。

## 残余

- `api.retry`（/task/{id}/retry）未接 idem——重试的是已存在行，天然幂等，不在 create 语义内。
- 409 跳转逻辑（Home.tsx:108-114）与 idem 各自独立验证过，无交叉。
