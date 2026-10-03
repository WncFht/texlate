# texlate web

SolidJS + Vite 阅读器前端（双语对照 PDF + chunk 列表 + 滚动锚点同步）。

## 入口

- `npm ci` 装依赖（版本以 `package-lock.json` 为准）。
- `npm run dev` —— 默认 mock ON（`dev/mock-api.ts` 中间件起 demo 数据，无需后端），<http://localhost:5173>。
- `VITE_MOCK_API=0 npm run dev` —— 真后端联调：`/api` 代理到 `http://127.0.0.1:8765`，先起 `uv run texlate web`（server 依赖在 core，`uv sync` 即得）。
- `npm run build` —— 产物 `dist/`（含 `dist/pdfjs/` 静态资源与 `THIRD_PARTY_LICENSES.txt`）。
- `npm test` / `npm run typecheck` / `npm run lint` —— vitest + tsc + eslint。
- `node scripts/smoke.mjs` —— playwright-core e2e 冒烟（21 断言，打 mock dev server）：先 `npm ci --prefix scripts` 装 playwright-core，`npm run dev` 跑着再跑；`WEB_BASE` 覆盖端口、`PW_EXE` 覆盖 chromium 路径，产物 `scripts/shots/*.png`，失败 exit 1。
- `node scripts/floor_verify.mjs` —— 验收地板（errors/overflow/tokens/ground/landmark/live 六腿 × 4 路由，PASS/WARN/FAIL 分立不求总分）：同 smoke 前置条件；`--reader [taskId]` 追加 reader 腿（默认 mock 种子 `t_0000000000000a01`），含 `__saAnim` 探针面与 sent-align 动效中间帧断言（硬切冒充动效会 FAIL）。

## 构建交付

`texlate web` 起服后 `/` 出本 SPA 的前提是产物进了 `src/texlate/server/static/`——该目录是 **gitignored 构建产物**，clone 后不存在，须先构建：

- `scripts/build-web.sh` —— 一条龙：`npm ci --prefix web` → `vite build` → 清空并拷入 `src/texlate/server/static/`；`--no-install` 跳过 `npm ci`（已装依赖时的快速重建）。
- 打包：wheel 经 pyproject `[tool.hatch.build] artifacts` 携带该目录——`uv tool install texlate` 后 `texlate web` 直接可用，无需 node。
- 开发直挂：产物不落盘也能联调——`vite build --watch` 跑着，另起 `TEXLATE_SPA_DIR=web/dist uv run texlate web` 即让后端直挂 `web/dist`（`src/texlate/server/staticfiles.py` 的 env 覆盖）。
- 产物缺席时 `/` 保持 404（API 照常）；前端是 hash 路由（`#/`、`#/reader/:id`、`#/settings`），服务端无需 SPA fallback。

## API 面

前端只打 `/api/...`（`src/api/client.ts`）：`translate` 202、`task` snapshot + SSE events、`files/{kind}` 白名单下载、`upload` multipart、`reader` 视图聚合、`settings` BYOK。契约见 `docs/` web-layer 规格与 `src/texlate/server/app.py`。
