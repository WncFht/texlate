# web-residual — web/ 全量残余打磨（10 面修复 + 14 新测试，147/147 绿）

> 2026-09-17 收口。scope=web/。自验：tsc 净 / eslint 0 problems / vitest **147/147·24 文件**（基线 133/20）/ vite build OK。

## 修复明细

1. **Home.tsx**：上传钮文案 bug（translate 在飞时 busy() 误显「上传中…」→ uploading()）；**导航劫持**——提交在飞时用户切走，请求落地后 openRes 把人拽进 reader → `alive` 标志 + onCleanup 守卫所有 await 后副作用（故意不 abort XHR：幂等键保证服务端只收一单，任务照常落地出现在列表更贴意图）；Enter 隐式提交不走 disabled → submit()/upload() 重入门；进度条 a11y（role=progressbar+valuemin/max/valuenow+aria-label，upPct 哨兵 -1 表不定态，label aria-live）；form-error role=alert。
2. **Reader.tsx 真 bug**：`reading.zoom` 恢复后从不落 viewer（PdfPane 恒以 page-width 起挂，Toolbar select 与视区不一致）——paneReady 里补赶不上 `setInfo→setZoom` 间 await fetch 窗口，改 `zoom×handles` createEffect 响应式落地（恢复/重挂/手改三路共用幂等）。retryError role=alert、transport-badge role=status。
3. **Settings.tsx**：save 无防重（双击/Enter 重入发两次 PUT）→ saving 门+disabled+「保存中…」；concurrency 补 min(16) 与 Home 口径一致；base_url/model/target_lang/api_key trim；form-msg role=status。
4. **HtmlPane.tsx+sanitize.ts**：marked.parse 单 chunk 抛错穿透 onMount 炸 ErrorBoundary 整页 fatal → 逐 chunk try/catch 降级转义原文（新 escapeHtml），坏数据不毁全页。
5. **TaskList.tsx**：progressbar aria-label（任务名）；delError role=alert。
6. **Toolbar.tsx**：downloads 空时菜单钮可点出空菜单 → disabled。
7. **PdfPane.tsx**：spinner role=status（aria-label 挂无 role div 不播报）。
8. **DocInfo.tsx**：Escape 关弹层（与 FindBar/下载菜单同口径）。
9. **zh.ts**：+`settings.saving`（其余 key 全量核对无缺口）。
10. **app.css**：`.up-bar.indet` 不定态往返扫条动画 + prefers-reduced-motion。

## 测试（+14，4 新文件+1 扩展）

homeUploadProgress +4 / settingsForm（新）/ readerZoom（新，桩 PdfPane/HtmlPane——pdfjs 不进 jsdom）/ a11y（新）/ htmlPane（新，marked 注入确定性抛错→坏块转义邻块正常）。

## 明确不动（记档）

- English UI：架构级 backlog 不做。
- `api.cancel` fire-and-forget：失败低频且 SSE 状态自收口。
- 无 localStorage/sessionStorage（阅读位置走服务端 PUT）——该项审计面为空。
- HtmlPane 下 Toolbar 缩放 select 对 chunk 视图无缩放接口——原状无害。
- PdfPane 错误面 String(e) 可能冗长——展示层瑕疵不改契约。

无越 scope 待路由。
