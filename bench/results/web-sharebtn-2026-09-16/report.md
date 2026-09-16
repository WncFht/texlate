# web-sharebtn — 终态「分享本译文」按钮（§6 前端闭环）

> 2026-09-16/17。scope web/。接 `POST /api/task/{id}/share/pack`（`4b537df`）——shared-cache §6「完成后提示分享」全链闭环完成。三链全绿 + mock curl 全分支实测。

## 改动文件

- `web/src/api/client.ts` — `SharePackResponse {share_key, url, bytes}` + `api.sharePack(taskId)`（POST 空 body）。
- `web/src/pages/Reader.tsx` — canShare/onSharePack/renderShareBlock + 三个挂载点 + onRetry 重置 share 态。
- `web/src/i18n/zh.ts` — reader.* 10 个新键。
- `web/src/styles/app.css` — `.share-pack/.share-ok/.share-key`（贴 .rp-actions 后）。
- `web/dev/mock-api.ts` — 路由 + MockTask `share_fail`/`share_key` 字段 + 种子 a08（artifacts 分支）、a09（kind=share）。
- `web/src/test/sharePack.test.ts` — 新文件 jsdom 10 例。

## 渲染条件

`canShare() = status ∈ {done,partial} && kind !== "share" && !!arxiv_id`（client.ts:449 一带）。

三个挂载面（done/partial 全覆盖）：

1. `renderResultBody` 的 `.rp-actions` 尾部（Reader.tsx:~700）——partial 横幅（pdf/html 视图）与 partial+files/empty 整页面板复用此体；fault/cancelled/needs_auth 自门控不显示。
2. done + pdf/html 视图专属细横幅 `.share-banner`（:~870）——`status==="done" && canShare()`，文案「分享本次译文到社区缓存」——§6 提示语义。partial 不出此横幅（钮已在结果横幅内）。
3. done + files/empty 产物面板（`.result-panel`）——doc 类任务有 arxiv_id 时同样可点。

点击 → busy 门（`shareBusy || shareResult` 双重拦截 + disabled）；成功 → 结果态 `已入共享目录：<code>share_key</code>（其他 TeXlate 实例可凭此包导入）`（url 是 server 侧文件名不渲染链接）；onRetry 重跑时 shareResult/shareError 重置。

## 错误映射

| 条件 | 显示 |
| --- | --- |
| 409 invalid_state | `[code] 任务未终态（detail）` |
| 422 share_pack_rejected | `[code] 该任务不可共享（detail）` |
| 422 share_pack_artifacts | `[code] 产物未齐（detail——含缺失文件名）` |
| 422 share_pack_failed | `[code] 共享打包失败（detail）` |
| 其他 | 原 detail |

## 验证

- `npx tsc --noEmit` 绿；`npx eslint .` 绿；`npx vitest run` 13 文件 **85 例全绿**（新文件 10 例：渲染门 6 + 调用/错误 4）。
- mock curl 实测（vite :5199）：a01 done → 200 `{share_key:"s-250114787-zh-0a01",…}` 二次幂等同 key；a03 partial → 200；a09 kind=share → 422 rejected；a06 无 arxiv → 422；a08 → 422 artifacts；a05 needs_auth → 409 invalid_state；不存在 → 404。守卫序与 app.py:935-1003 一致（kind → status → arxiv → artifacts）。
- PdfPane/HtmlPane 测试内 vi.mock 打桩（pdfjs/katex 不进 jsdom）。

## 残余

- done+view 横幅常驻细条（非可关提示）——按 §6 提示语义常显，嫌吵可加 dismiss。
- share_pack_failed 种子未加（a08 已覆盖 artifacts 演示）。
- reuse_hit 拒绝走通用 rejected 映射（detail 带出源任务 id），UI 无单独前置判断。
