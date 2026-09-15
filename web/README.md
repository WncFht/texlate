# texlate web

SolidJS + Vite 阅读器前端（双语对照 PDF + chunk 列表 + 滚动锚点同步）。

## 入口

- `npm ci` 装依赖（版本以 `package-lock.json` 为准）。
- `npm run dev` —— 默认 mock ON（`dev/mock-api.ts` 中间件起 demo 数据，无需后端），<http://localhost:5173>。
- `VITE_MOCK_API=0 npm run dev` —— 真后端联调：`/api` 代理到 `http://127.0.0.1:8765`，先起 `uv run texlate web`（需 `texlate[server]` extra：`uv sync --extra server`）。
- `npm run build` —— 产物 `dist/`（含 `dist/pdfjs/` 静态资源与 `THIRD_PARTY_LICENSES.txt`）。
- `npm test` / `npm run typecheck` / `npm run lint` —— vitest + tsc + eslint。

## API 面

前端只打 `/api/...`（`src/api/client.ts`）：`translate` 202、`task` snapshot + SSE events、`files/{kind}` 白名单下载、`upload` multipart、`reader` 视图聚合、`settings` BYOK。契约见 `docs/` web-layer 规格与 `src/texlate/server/app.py`。
