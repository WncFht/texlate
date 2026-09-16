# web-authx — needs_auth X-Texlate-Key 透传 translate 表单（BYOK per-request）

> 2026-09-16。scope web/。三链：tsc 0 err、eslint 0 warn、vitest 75/75（+9 新例）。web-polish 对账残余 #4 收口。

## 契约核实（server 端，只读未改）

**服务端已收此头，无缺口。** `app.py:418-430` `_auth(request)` 三级决议 header > settings > env，读 `x-texlate-key`/`x-texlate-base-url`/`x-texlate-model`：

- `POST /api/arxiv/{id}/translate`（:595-639）：`_auth` 参与 model 决议、`cache_key_for(api_key=…)`、`enqueue(Secrets(api_key=…))`——头直达任务 secrets。
- `POST /api/upload`（:775-824）/`POST /api/share/import`（:899）同样收。
- CORS allow_headers 已含三个 texlate 头（:392-395，server mode）。

## 改动文件

- `web/src/pages/Home.tsx` — :46 `optKey` signal（组件 state 级）；:91-92 `byok()` 帮手（trim 空→undefined）；:103-104 translate 透传+成功后清 key；:133-138 shareImport 同；:152-153 upload 同；:324-334 新增 password 输入于折叠 `.task-opts` 末行（span2 次要位置）。
- `web/src/api/client.ts` — :345-361 `api.upload` 增 `byok?: ByokHeaders` 第三参；:364-372 `api.shareImport` 同。translate(:337)/retry(:380) 已有 byok 参，复用未改。
- `web/src/i18n/zh.ts` — :36-37 `optKey`「临时 API Key」+ `optKeyHint`「仅随本次请求透传，不写入设置」。
- `web/dev/mock-api.ts` — 四端点（translate/upload/shareImport/retry）收 `x-texlate-key` 时 emit `log` 事件（入 t.events，SSE 重放可见）。
- `web/src/test/byok.test.ts`（新）— api 层 5 例：translate 带/不带 key、四头齐发、upload/shareImport multipart 透传（content-type 不被手写污染）、retry 回归。
- `web/src/test/homeByok.test.ts`（新）— jsdom 组件 4 例：fill→submit→`translate(id, undefined, {apiKey})`+提交后输入清空；空/纯空白→byok undefined；`putSettings` 全程未调（不落 settings）。

## 设计取舍

- key 作用于表单全部三个建任务路径（translate/upload/shareImport）——同一折叠选项区，server 三端点都收。
- key 仅提交成功后清（失败保留供修正重试）；成功路径 nav 后组件卸载双保险。
- `type="password"` + `autocomplete="off"`，复用 opts-grid 样式，无 CSS 改动。

## 残余

无浏览器实机目测（headless）——jsdom 覆盖 fill→submit→header 全链；mock log 事件可在 dev UI 日志面板直观察证。
