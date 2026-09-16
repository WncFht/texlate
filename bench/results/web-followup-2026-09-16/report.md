# web-followup — usage 细分面板 + Settings 清除 Key（9 文件）

> 2026-09-16。scope web/。工具链：tsc 0 错、eslint 净、vitest 66/66（+9 新用例）、mock parity curl 实测。

## 改动文件

- `web/src/taskStats.ts`（新）— `mergeResultStats(stats?, counters?, usage?)` 纯函数：done 帧 stats 优先、counters 兜底、usage 细分透传；全空 → null。
- `web/src/api/client.ts` — `TaskUsage` 导出为具名接口（原内联）；`Settings` 加 `clear_api_key?: boolean` 伪字段。
- `web/src/pages/Reader.tsx` — `resultStats` 改用 mergeResultStats；stat-strip 在 Tokens 后追加 输入/输出 Tokens、LLM 调用、API 耗时（latency_s 走 fmtElapsed），各自 `!= null` 门控，老任务无 usage 行自动缺席。
- `web/src/pages/Settings.tsx` — API Key 字段改 `.key-row` 布局，旁置「清除已存 Key」btn-ghost 小按钮：点击 → `save({clear_api_key:true})` → 响应 `has_api_key:false` 落 store → 输入框清空 + 3s 提示；`has_api_key` false/未加载时禁用（needs_auth 语义下无可清对象，置灰而非隐藏）。按钮放 `<label>` 外避免 labelable 嵌套非法。
- `web/src/i18n/zh.ts` — reader 加 statsPrompt/statsCompletion/statsCalls/statsLatency；settings 加 clearKey/clearing/keyCleared/clearFailed。
- `web/src/styles/app.css` — `.key-row` flex 布局。
- `web/dev/mock-api.ts` — settings 状态化（GET/PUT 对齐 `public()` 形状：clear_api_key→false、api_key 非空→true、字段合并、不回显 key 本体）；done 快照带 usage（counters 推演示值）。
- `web/src/test/taskStats.test.ts` + `web/src/test/settings.test.ts`（新）— merge 优先级/兜底/全空、clear_api_key 透传 + store has_api_key 翻转。

## 契约核实

- `PUT /api/settings`（app.py:1142）body 白名单 = `SettingsStore.FIELDS` + `clear_api_key`/`has_api_key` 伪字段；`settings.py:329` `clear_api_key=True` → `merged["api_key"]=""`，返回 `public()`（`has_api_key:false`）。
- `usage` 来自 `TaskSnapshot.usage`（store.py:818 snapshot 注入 task_usage 行，无记录则字段缺席）；done SSE 帧不带 usage，但 Reader onMount 的 `api.snapshot` 会拿到。

## 说明

「done 结果面板」= `renderResultBody` 的 stat-strip（done SSE 帧 stats 驱动），对 done/partial/fault/needs_auth 终态渲染；done+pdf 视图本身无结果面板，未新增。

## 残余（web-polish 队列）

- share 按钮：依赖 share-postpack 端点（在飞）。
- needs_auth X-Texlate-Key 透传 translate 表单：client.ts 已空出，可派。
