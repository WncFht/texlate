# web-docview：doc 类任务产物下载入口（2026-09-16）

任务 #53–#55。docx/epub/pdf 任务不产 dual.json → reader 恒 404，前端此前仍渲染阅读器入口。本批把产物面接到任务列表/详情，并对 `reader_url` 缺席做全前端兼容（后端 app.py 侧同步在改 `_accepted` 字段发放）。

## 改动

- `web/src/taskFiles.ts`（新）：任务 → 产物清单助手（kind→下载文件名/媒体类型映射，过滤可用产物）
- `web/src/components/TaskList.tsx`：doc 类任务行内下载钮（zh.docx/zh.epub/zh.pdf 按产物在列渲染，arxiv 行无行内下载）
- `web/src/pages/Home.tsx` / `web/src/api/client.ts`：`reader_url` 缺席兼容——字段不发射到不产 dual 的 kind，前端不崩不白屏
- `web/src/pages/Reader.tsx`：产物清单去重（-34 行重构）
- `web/src/dev/mock-api.ts`：mock 对齐新契约（doc 任务无 reader_url + files 面）
- `web/src/i18n/zh.ts`、`web/src/styles/app.css`：下载钮文案 + 样式
- `web/scripts/smoke.mjs` + `web/scripts/package-lock.json`：smoke 覆盖新面
- `web/src/test/taskFiles.test.ts`（新）：taskFiles 助手单测

## 验证

- `npx tsc --noEmit` 净；`npx eslint src/` 净；`npx vitest run` 57/57
- `node scripts/smoke.mjs`（真 dev server + playwright）：**29/29 全过**——含 docx/epub 行内下载链、arxiv 行无下载钮、产物面板渲染、docx 上传落地（reader_url 缺席不崩）、docx 进度视图、窄屏纵排、无 console 错误
