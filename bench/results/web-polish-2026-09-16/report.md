# web-polish — web/ 规格对账 + 前端接线补齐（8 文件）

> 2026-09-16。scope `web/`。工具链改前全绿改后仍全绿：tsc 0 错、eslint 0 警、vitest 57/57、vite build 过、playwright smoke 29/29（mock dev server，console 零错误）、`.share.zip` 上传真浏览器走通（→202→#/reader）。

## 改动（8 文件，全在 web/）

- `api/client.ts`：补 `api.shareImport`（POST /api/share/import——服务端端点早存在前端从未接）；`ApiError` 抓结构化 `task_id`（409 duplicate_active）；`DoneEvent.status` 补 `"deleted"`（DELETE 对在听 SSE 流补发的收尾帧）；`ReadingState.document_version`（PUT position 的 409 防旧版守卫料）；`options.share_pack`、`TaskSnapshot.usage` 类型。
- `stores/tasks.ts`：done{status:"deleted"} 分支删行+清 live——修「别页删任务后本页留僵尸行永不收敛」。
- `pages/Reader.tsx`：persistPosition 抽 saveNow——PUT 带 document_version（zh.pdf sha256）、空 positions 不发（防空表覆盖服务端已存）、卸载冲刷防抖中未发保存（最后 <1s 滚动不再丢）。
- `pages/Home.tsx`：`.share.zip` 路由 share/import；选项格加 share_pack opt-in 与 main 主文件字段（服务端 `_upload_fields` 早收）；409 优先 `e.taskId`。
- `pages/Settings.tsx`：补 `context_guidance` 默认开关（server FIELDS 支持但 UI 缺席）。
- `i18n/zh.ts`：kind.share「共享包」标签 + 新字段文案 + reader aria。
- `components/Toolbar.tsx`：两处硬编码中文 aria-label 走 i18n。
- `dev/mock-api.ts`：/api/share/import mock 路由保 dev parity。

## 规格对账（web-layer.md §5）

已实现：§5.1–§5.5 全要点 + §2 端面全接线；超规格已落 find bar/侧栏三 tab/批注高亮/文档信息/needs_auth 内联重试/任务删除/doc 产物面板/>500px 漂移跳回/mock dev server。

缺失（架构级，待立项）：**事后打包端点** `POST /api/task/{id}/share/pack`——shared-cache §6「完成后提示分享」要服务端口子，现只有建任务时 options.share_pack（已接）与 CLI share pack；Idempotency-Key 协议备而 UI 不用；Settings 无「清除 API Key」（server `clear_api_key:true` 已支持）；无英文 UI；无上传进度条（要 XHR）；split 栏宽不可拖。

## 建议下一步（leader 已立项 #1）

1. 后端 `POST /api/task/{id}/share/pack`（终态任务事后打包）→ 前端 done 面板「分享本译文」按钮——落 §6 完整环。
2. 结果面板用 `snapshot.usage` 细分展示 prompt/completion tokens。
3. Settings 加「清除已存 Key」。
4. needs_auth 的 X-Texlate-Key 透传复用到 translate 表单（per-request BYOK 覆盖）。
